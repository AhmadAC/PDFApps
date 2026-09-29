# app/viewer/panel_search_print.py
"""PDFApps – In-document text search and print dialog routines."""
from __future__ import annotations

import contextlib
import os
import threading

import fitz
from PySide6.QtCore import QRectF, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QProgressDialog

from app.i18n import t
from app.utils import show_error


class _PrintPageWorker(QThread):
    """Background worker thread that rasterizes PDF pages into QImages without blocking the GUI."""

    page_rendered = Signal(int, int, QImage)  # step_idx, page_idx, QImage
    render_error = Signal(str)
    finished_all = Signal()

    def __init__(self, doc_path: str, password: str, job_pages: list[int], target_dpi: int, parent=None):
        super().__init__(parent)
        self.doc_path = doc_path
        self.password = password
        self.job_pages = job_pages
        self.target_dpi = target_dpi
        self._is_cancelled = False
        self._next_event = threading.Event()
        self._next_event.set()

    def cancel(self):
        self._is_cancelled = True
        self._next_event.set()

    def continue_next(self):
        self._next_event.set()

    def run(self):
        doc = None
        try:
            doc = fitz.open(self.doc_path)
            if self.password and doc.needs_pass:
                doc.authenticate(self.password)

            zoom = self.target_dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)

            for step, page_idx in enumerate(self.job_pages, start=1):
                if self._is_cancelled:
                    break

                self._next_event.wait()
                if self._is_cancelled:
                    break
                self._next_event.clear()

                if page_idx < 0 or page_idx >= doc.page_count:
                    continue

                page = doc[page_idx]
                pix = page.get_pixmap(matrix=mat, alpha=False)
                if pix.n != 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                img = QImage(pix.samples, pix.width, pix.height,
                             pix.stride, QImage.Format.Format_RGB888).copy()
                pix = None

                self.page_rendered.emit(step, page_idx, img)

            if not self._is_cancelled:
                self.finished_all.emit()
        except Exception as exc:
            if not self._is_cancelled:
                self.render_error.emit(str(exc))
        finally:
            if doc is not None:
                with contextlib.suppress(Exception):
                    doc.close()


class PanelSearchPrintMixin:
    """Mixin for text search bar interactions and document printing."""

    def _toggle_search(self):
        if self._search_bar.isVisible():
            self._close_search()
        else:
            self._search_bar.setVisible(True)
            self._search_input.setFocus()
            self._search_input.selectAll()

    def _close_search(self):
        self._search_bar.setVisible(False)
        self._search_results.clear()
        self._search_current = -1
        self._search_lbl.setText("")
        self._canvas.set_search_highlights([])
        self._canvas.update()

    def _on_search_text_changed(self, text: str):
        query = text.strip()
        if not query:
            self._search_debounce.stop()
            self._pending_search_query = ""
            self._search_results.clear()
            self._search_current = -1
            self._search_lbl.setText("")
            self._canvas.set_search_highlights([])
            self._canvas.update()
            return
        self._pending_search_query = query
        self._search_debounce.start()

    def _run_pending_search(self):
        query = self._pending_search_query
        if query:
            self._do_search(query)

    def _do_search(self, query: str):
        doc = self._fitz_doc
        if doc is None or getattr(doc, "is_closed", False):
            return
        results = []
        try:
            for page_idx in range(doc.page_count):
                page = doc[page_idx]
                rects = page.search_for(query)
                if rects:
                    results.append((page_idx, rects))
        except (RuntimeError, ValueError):
            return
        self._search_results = results
        total = sum(len(rects) for _, rects in results)
        if total == 0:
            self._search_lbl.setText("0 / 0")
            self._search_current = -1
            self._canvas.set_search_highlights([])
            self._canvas.update()
            return
        self._search_current = 0
        self._update_search_highlight()

    def _search_next(self):
        if not self._search_results:
            text = self._search_input.text().strip()
            if text:
                self._do_search(text)
            return
        total = sum(len(rects) for _, rects in results) if (results := self._search_results) else 0
        if total == 0:
            return
        self._search_current = (self._search_current + 1) % total
        self._update_search_highlight()

    def _search_prev(self):
        if not self._search_results:
            return
        total = sum(len(rects) for _, rects in self._search_results)
        if total == 0:
            return
        self._search_current = (self._search_current - 1) % total
        self._update_search_highlight()

    def _update_search_highlight(self):
        total = sum(len(rects) for _, rects in self._search_results)
        self._search_lbl.setText(f"{self._search_current + 1} / {total}")
        all_highlights = []
        flat_idx = 0
        current_page = 0
        for page_idx, rects in self._search_results:
            for rect in rects:
                all_highlights.append((page_idx, rect))
                if flat_idx == self._search_current:
                    current_page = page_idx
                flat_idx += 1
        self._canvas.set_search_highlights(all_highlights, self._search_current)
        if current_page < len(self._canvas._entries):
            entry = self._canvas._entries[current_page]
            _, cur_rect = all_highlights[self._search_current]
            z = self._canvas._zoom
            y_target = entry.y_off + int(cur_rect.y0 * z) - 100
            self._canvas_scroll.verticalScrollBar().setValue(max(0, y_target))
        self._canvas.update()

    def _reset_search_state(self):
        self._search_debounce.stop()
        self._pending_search_query = ""
        self._close_search()

    def _cancel_print_job(self):
        """Clean up any active background print worker and finish painter."""
        if getattr(self, "_print_in_progress", False):
            if hasattr(self, "_print_worker") and self._print_worker is not None:
                self._print_worker.cancel()
                self._print_worker.wait(1500)
                self._print_worker.deleteLater()
                self._print_worker = None
            if hasattr(self, "_print_painter") and self._print_painter is not None:
                with contextlib.suppress(Exception):
                    self._print_painter.end()
                self._print_painter = None
            if hasattr(self, "_print_progress") and self._print_progress is not None:
                with contextlib.suppress(Exception):
                    self._print_progress.close()
                    self._print_progress.deleteLater()
                self._print_progress = None
            self._print_in_progress = False

    def _print_pdf(self, page_indices: list[int] | None = None):
        if getattr(self, "_print_in_progress", False):
            return

        doc = self._fitz_doc
        if doc is None or getattr(doc, "is_closed", False):
            return
        if not self._current_path or not os.path.isfile(self._current_path):
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(os.path.basename(self._current_path))

        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle(t("viewer.print"))
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return

        page_count = doc.page_count
        if page_indices is not None and len(page_indices) > 0:
            pages = [p for p in page_indices if 0 <= p < page_count]
        else:
            from_page = printer.fromPage()
            to_page = printer.toPage()
            if from_page == 0 and to_page == 0:
                pages = list(range(page_count))
            else:
                start = max(0, from_page - 1)
                end = min(page_count, to_page)
                pages = list(range(start, end))

        try:
            reverse = (printer.pageOrder() == QPrinter.PageOrder.LastPageFirst)
        except AttributeError:
            reverse = False
        if reverse:
            pages = list(reversed(pages))

        copies = 1 if printer.supportsMultipleCopies() else max(1, printer.copyCount())

        job_pages: list[int] = []
        for _ in range(copies):
            job_pages.extend(pages)

        total_steps = len(job_pages)
        if total_steps == 0:
            return

        # Cap raster DPI to 300 to prevent multi-gigabyte memory allocations and UI freezing
        target_dpi = min(300, max(150, printer.resolution()))

        painter = QPainter()
        if not painter.begin(printer):
            return

        self._print_in_progress = True
        self._print_painter = painter
        self._print_first_page = True

        progress = QProgressDialog(t("viewer.print"), t("btn.cancel"), 0, total_steps, self)
        progress.setWindowTitle(t("viewer.print"))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.setLabelText(f"{t('viewer.print')}: 1/{total_steps}…")
        self._print_progress = progress

        worker = _PrintPageWorker(
            self._current_path,
            getattr(self, "_pdf_password", ""),
            job_pages,
            target_dpi,
            parent=self,
        )
        self._print_worker = worker

        def finish_printing():
            if not getattr(self, "_print_in_progress", False):
                return
            self._print_in_progress = False

            w = getattr(self, "_print_worker", None)
            if w is not None:
                w.cancel()
                w.wait(2000)
                w.deleteLater()
                self._print_worker = None

            p = getattr(self, "_print_painter", None)
            if p is not None:
                with contextlib.suppress(Exception):
                    p.end()
                self._print_painter = None

            prog = getattr(self, "_print_progress", None)
            if prog is not None:
                with contextlib.suppress(Exception):
                    prog.close()
                    prog.deleteLater()
                self._print_progress = None

        def on_page_rendered(step: int, page_idx: int, img: QImage):
            if not getattr(self, "_print_in_progress", False) or progress.wasCanceled():
                finish_printing()
                return

            if not self._print_first_page:
                printer.newPage()
            self._print_first_page = False

            target = QRectF(painter.viewport())
            source = QRectF(0, 0, img.width(), img.height())
            scale = min(target.width() / source.width(), target.height() / source.height())
            w = source.width() * scale
            h = source.height() * scale
            x = target.x() + (target.width() - w) / 2
            y = target.y() + (target.height() - h) / 2
            painter.drawImage(QRectF(x, y, w, h), img, source)

            progress.setValue(step)
            progress.setLabelText(f"{t('viewer.print')}: {step}/{total_steps}…")

            # Signal worker to render next page in background
            w_inst = getattr(self, "_print_worker", None)
            if w_inst is not None:
                w_inst.continue_next()

        def on_worker_finished():
            finish_printing()

        def on_worker_error(err_msg: str):
            finish_printing()
            show_error(self, RuntimeError(err_msg))

        progress.canceled.connect(finish_printing)
        worker.page_rendered.connect(on_page_rendered, Qt.ConnectionType.QueuedConnection)
        worker.finished_all.connect(on_worker_finished, Qt.ConnectionType.QueuedConnection)
        worker.render_error.connect(on_worker_error, Qt.ConnectionType.QueuedConnection)

        progress.show()
        worker.start()