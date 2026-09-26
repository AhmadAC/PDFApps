# app/viewer/panel_search_print.py
"""PDFApps – In-document text search and print dialog routines."""
import os

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QProgressDialog
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
import fitz

from app.i18n import t


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

    def _print_pdf(self, page_indices: list[int] | None = None):
        doc = self._fitz_doc
        if doc is None or getattr(doc, "is_closed", False):
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setDocName(os.path.basename(self._current_path))

        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle(t("viewer.print"))
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return

        painter = QPainter()
        if not painter.begin(printer):
            return

        page_count = len(self._fitz_doc)
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
        copies = max(1, printer.copyCount())

        total_steps = max(1, copies * len(pages))
        progress = QProgressDialog(t("viewer.print"), t("btn.cancel"), 0, total_steps, self)
        progress.setWindowTitle(t("viewer.print"))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        step = 0
        first_page_printed = True
        try:
            for copy in range(copies):
                for i in pages:
                    if progress.wasCanceled():
                        break
                    step += 1
                    progress.setValue(step)
                    progress.setLabelText(f"{t('viewer.print')}: {step}/{total_steps}…")
                    QApplication.processEvents()

                    if not first_page_printed:
                        printer.newPage()
                    first_page_printed = False
                    page = self._fitz_doc[i]
                    dpi = printer.resolution()
                    zoom = dpi / 72.0
                    mat = fitz.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    if pix.n != 3:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    img = QImage(pix.samples, pix.width, pix.height,
                                 pix.stride, QImage.Format.Format_RGB888).copy()
                    target = QRectF(painter.viewport())
                    source = QRectF(0, 0, img.width(), img.height())
                    scale = min(target.width() / source.width(),
                                target.height() / source.height())
                    w = source.width() * scale
                    h = source.height() * scale
                    x = (target.width() - w) / 2
                    y = (target.height() - h) / 2
                    painter.drawImage(QRectF(x, y, w, h), img, source)
                    QApplication.processEvents()
                if progress.wasCanceled():
                    break
        finally:
            progress.close()
            painter.end()