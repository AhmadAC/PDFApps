# app/tools/import_pdf.py
"""PDFApps – TabImport: convert TXT, Images, Markdown, DOCX, PPTX, XLSX, HTML, EPUB, PDF to PDF."""

from __future__ import annotations

import contextlib
import os
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QFileDialog, QLabel, 
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QAbstractItemView,
)
import qtawesome as qta

from app.base import BasePage
from app.pdf_io import atomic_pdf_write
from app.i18n import t
from app.utils import section, danger_btn, result_label_style
from app.constants import DESKTOP, TEXT_SEC
from app.widgets import DropFileEdit


_IMG_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".webp", ".gif")

_ALL_SUPPORTED_FILTER = (
    "All Supported Files (*.txt *.md *.markdown *.docx *.pptx *.xlsx *.html *.htm *.epub "
    "*.png *.jpg *.jpeg *.bmp *.tiff *.webp *.gif *.pdf);;"
    "Office Documents (*.docx *.pptx *.xlsx);;"
    "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.webp *.gif);;"
    "Text & Markdown (*.txt *.md *.markdown);;"
    "Web & eBooks (*.html *.htm *.epub);;"
    "PDF Files (*.pdf);;"
    "All Files (*.*)"
)


class _NoContent:
    """Sentinel result: a converter produced a zero-page document."""

    __slots__ = ("skipped",)

    def __init__(self, skipped: int = 0):
        self.skipped = skipped


class _ImportFileList(QListWidget):
    """File list supporting drag & drop of arbitrary files directly into the list."""

    def __init__(self, on_drop_callback, parent=None):
        super().__init__(parent)
        self._on_drop_callback = on_drop_callback
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [
                os.path.abspath(u.toLocalFile())
                for u in event.mimeData().urls()
                if u.toLocalFile() and os.path.isfile(u.toLocalFile())
            ]
            if paths:
                self._on_drop_callback(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            for item in self.selectedItems():
                row = self.row(item)
                self.takeItem(row)
            event.accept()
            return
        super().keyPressEvent(event)


class TabImport(BasePage):
    """Import and convert any supported document or image types directly to PDF with auto-detection."""

    def __init__(self, status_fn):
        super().__init__(
            "fa5s.file-import",
            t("tool.import.name"),
            t("tool.import.desc"),
            t("tool.import.btn"),
            status_fn,
        )
        f = self._form

        # ── Source files list (drag & drop / multi-select) ────────────
        f.addWidget(section(t("tool.import.source_file")))

        self._file_list = _ImportFileList(self._on_files_dropped, self)
        self._file_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._file_list.setMinimumHeight(180)
        f.addWidget(self._file_list)

        file_btns = QHBoxLayout()
        self._add_btn = QPushButton(t("tool.import.add_files"))
        self._add_btn.setIcon(qta.icon("fa5s.plus", color=TEXT_SEC))
        self._add_btn.clicked.connect(self._pick_files)
        file_btns.addWidget(self._add_btn)

        self._remove_selected_btn = QPushButton(t("btn.remove"))
        self._remove_selected_btn.setIcon(qta.icon("fa5s.minus", color=TEXT_SEC))
        self._remove_selected_btn.clicked.connect(self._remove_selected_files)
        file_btns.addWidget(self._remove_selected_btn)

        self._clear_btn = danger_btn(t("btn.clear"))
        self._clear_btn.clicked.connect(self._file_list.clear)
        file_btns.addWidget(self._clear_btn)
        file_btns.addStretch()
        f.addLayout(file_btns)

        # ── Output file ──────────────────────────────────────────────
        f.addWidget(section(t("tool.import.output")))
        self.drop_out = DropFileEdit(save=True, default_name="output.pdf")
        f.addWidget(self.drop_out)

        self.lbl_result = QLabel("")
        self.lbl_result.setStyleSheet(result_label_style())
        f.addWidget(self.lbl_result)
        f.addStretch()

    def set_compact_mode(self, active: bool, path: str = "") -> None:
        """TabImport creates new PDFs from external files; ignore viewer compact mode."""
        pass

    def update_theme(self, dark: bool) -> None:
        super().update_theme(dark)
        try:
            self.lbl_result.setStyleSheet(result_label_style(dark))
        except RuntimeError:
            pass

    @staticmethod
    def _icon_for_ext(ext: str) -> str:
        ext = ext.lower()
        if ext in _IMG_EXTS:
            return "fa5s.image"
        if ext in (".docx", ".doc"):
            return "fa5s.file-word"
        if ext in (".pptx", ".ppt"):
            return "fa5s.file-powerpoint"
        if ext in (".xlsx", ".xls"):
            return "fa5s.file-excel"
        if ext in (".html", ".htm"):
            return "fa5s.file-code"
        if ext in (".epub",):
            return "fa5s.book"
        if ext in (".pdf",):
            return "fa5s.file-pdf"
        return "fa5s.file-alt"

    def _add_file_path(self, p: str):
        if not p or not os.path.isfile(p):
            return
        p = os.path.abspath(p)
        existing = [
            self._file_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._file_list.count())
        ]
        if p in existing:
            return

        ext = os.path.splitext(p)[1].lower()
        icon_name = self._icon_for_ext(ext)
        item = QListWidgetItem(qta.icon(icon_name, color=TEXT_SEC), os.path.basename(p))
        item.setData(Qt.ItemDataRole.UserRole, p)
        item.setToolTip(p)
        self._file_list.addItem(item)

        if not self.drop_out.path():
            base = os.path.splitext(p)[0]
            self.drop_out.set_path(base + ".pdf")

    def _on_files_dropped(self, paths: list[str]):
        for p in paths:
            self._add_file_path(p)

    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            t("tool.import.add_files"),
            DESKTOP,
            _ALL_SUPPORTED_FILTER,
        )
        for p in paths:
            self._add_file_path(p)

    def _remove_selected_files(self):
        for item in self._file_list.selectedItems():
            row = self._file_list.row(item)
            self._file_list.takeItem(row)

    def _get_files(self) -> list[str]:
        return [
            self._file_list.item(i).data(Qt.ItemDataRole.UserRole)
            or self._file_list.item(i).text()
            for i in range(self._file_list.count())
        ]

    def _run(self):
        files = self._get_files()
        if not files:
            QMessageBox.warning(self, t("msg.warning"), t("tool.import.select_file"))
            return

        default_name = "output.pdf"
        if files:
            base, _ = os.path.splitext(os.path.basename(files[0]))
            default_name = f"{base}.pdf"
        start_dir = os.path.dirname(files[0]) if files else ""
        out = self._prompt_save_as(default_name, start_dir)
        if not out:
            return
        self.drop_out.set_path(out)

        self.lbl_result.setText("")

        # Pre-validate dependencies required for selected files
        has_docx = any(f.lower().endswith(".docx") for f in files)
        has_pptx = any(f.lower().endswith(".pptx") for f in files)
        has_xlsx = any(f.lower().endswith(".xlsx") for f in files)
        has_html = any(f.lower().endswith((".html", ".htm")) for f in files)

        if has_docx:
            try:
                import docx  # noqa: F401
            except ImportError:
                QMessageBox.critical(self, t("msg.missing_dep"), t("tool.convert.dep_docx"))
                return
        if has_pptx:
            try:
                import pptx  # noqa: F401
            except ImportError:
                QMessageBox.critical(self, t("msg.missing_dep"), t("tool.convert.dep_pptx"))
                return
        if has_xlsx:
            try:
                import openpyxl  # noqa: F401
            except ImportError:
                QMessageBox.critical(self, t("msg.missing_dep"), t("tool.convert.dep_xlsx"))
                return
        if has_html:
            try:
                import bs4  # noqa: F401
            except ImportError:
                QMessageBox.critical(self, t("msg.missing_dep"), t("tool.import.dep_bs4"))
                return

        n = len(files)

        def do_work(worker):
            import fitz

            doc = fitz.open()
            skipped = 0
            try:
                for i, file_path in enumerate(files):
                    if worker.is_cancelled():
                        return None
                    worker.progress.emit(i + 1, f"{i + 1}/{n}: {os.path.basename(file_path)}")
                    ext = os.path.splitext(file_path)[1].lower()

                    if ext in _IMG_EXTS:
                        ok = self._process_image(doc, file_path)
                        if not ok:
                            skipped += 1
                    elif ext in (".md", ".markdown"):
                        self._process_md(doc, file_path)
                    elif ext in (".docx",):
                        self._process_docx(doc, file_path)
                    elif ext in (".pptx",):
                        self._process_pptx(doc, file_path)
                    elif ext in (".xlsx",):
                        self._process_xlsx(doc, file_path)
                    elif ext in (".html", ".htm"):
                        self._process_html(doc, file_path)
                    elif ext in (".epub",):
                        self._process_epub(doc, file_path)
                    elif ext in (".pdf",):
                        self._process_pdf(doc, file_path)
                    else:
                        self._process_txt(doc, file_path)

                if worker.is_cancelled():
                    return None
                if doc.page_count == 0:
                    return _NoContent(skipped)

                win: Any = self.window()
                viewer = getattr(win, "_viewer", None)
                if (
                    viewer
                    and viewer.current_path()
                    and os.path.abspath(viewer.current_path()) == os.path.abspath(out)
                ):
                    viewer._canvas.close_doc()
                    if viewer._fitz_doc:
                        with contextlib.suppress(Exception):
                            viewer._fitz_doc.close()
                        viewer._fitz_doc = None
                    viewer._thumbnails._stop_all_workers()

                atomic_pdf_write(doc, out, close_writer=True)
            finally:
                with contextlib.suppress(Exception):
                    doc.close()
            return out

        self._run_background(
            do_work,
            total=max(n, 1),
            label=t("tool.import.converting"),
            on_done=lambda r: self._on_result(r, out),
        )

    def _process_image(self, doc, img_path: str) -> bool:
        import fitz
        from app.utils import check_image_size

        ok, _w, _h = check_image_size(img_path)
        if not ok:
            return False
        img = fitz.open(img_path)
        try:
            if img.page_count == 0:
                return False
            rect = img[0].rect
            page = doc.new_page(width=rect.width, height=rect.height)
            page.insert_image(page.rect, filename=img_path)
            return True
        finally:
            img.close()

    def _process_txt(self, doc, txt_path: str) -> None:
        import fitz

        with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        lines = content.split("\n")
        page = None
        y = 50
        fontsize = 10
        line_height = fontsize * 1.4
        margin_x = 50
        max_y = 792
        max_width = 495
        for line in lines:
            if page is None or y + fontsize > max_y:
                page = doc.new_page(width=595, height=842)
                y = 50
            if not line.strip():
                y += line_height
                continue
            rect = fitz.Rect(margin_x, y, margin_x + max_width, max_y)
            used = page.insert_textbox(rect, line, fontsize=fontsize, fontname="helv")
            if used < 0:
                page = doc.new_page(width=595, height=842)
                y = 50
                rect = fitz.Rect(margin_x, y, margin_x + max_width, max_y)
                used = page.insert_textbox(rect, line, fontsize=fontsize, fontname="helv")
            est_lines = max(1, len(line) * fontsize * 0.5 / max_width + 1)
            y += line_height * est_lines

    def _process_md(self, doc, md_path: str) -> None:
        with open(md_path, "r", encoding="utf-8", errors="replace") as f:
            md_text = f.read()
        lines = self._md_to_lines(md_text)
        self._render_lines_to_doc(doc, lines)

    def _process_docx(self, doc, docx_path: str) -> None:
        from docx import Document

        dx = Document(docx_path)
        lines = []
        for para in dx.paragraphs:
            text = para.text.strip()
            p_style = para.style
            style = (p_style.name or "").lower() if p_style is not None else ""
            if "heading 1" in style:
                lines.append((text, 18, True))
            elif "heading 2" in style:
                lines.append((text, 15, True))
            elif "heading 3" in style:
                lines.append((text, 13, True))
            elif "heading" in style:
                lines.append((text, 12, True))
            elif text:
                bold = any(r.bold for r in para.runs if r.bold)
                lines.append((text, 10, bold))
            else:
                lines.append(("", 10, False))
        for table in dx.tables:
            lines.append(("", 10, False))
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells]
                lines.append(("  |  ".join(cells), 9, False))
            lines.append(("", 10, False))
        self._render_lines_to_doc(doc, lines)

    def _process_pptx(self, doc, pptx_path: str) -> None:
        from pptx import Presentation
        import fitz

        prs = Presentation(pptx_path)
        slide_w = prs.slide_width.pt if prs.slide_width else 960
        slide_h = prs.slide_height.pt if prs.slide_height else 540
        for slide in prs.slides:
            page = doc.new_page(width=slide_w, height=slide_h)
            y = 40
            for shape in slide.shapes:
                if not getattr(shape, "has_text_frame", False):
                    continue
                tf = getattr(shape, "text_frame", None)
                if tf is None:
                    continue
                for para in tf.paragraphs:
                    text = para.text.strip()
                    if not text:
                        continue
                    size = 10
                    bold = False
                    if para.runs:
                        r = para.runs[0]
                        font = getattr(r, "font", None)
                        if font is not None and getattr(font, "size", None):
                            size = min(36, font.size.pt)
                        if font is not None:
                            bold = bool(getattr(font, "bold", False))
                    font_name = "hebo" if bold else "helv"
                    if y + size > slide_h - 20:
                        break
                    try:
                        page.insert_text(fitz.Point(40, y), text, fontsize=size, fontname=font_name)
                    except Exception:
                        page.insert_text(fitz.Point(40, y), text, fontsize=size, fontname="helv")
                    y += size * 1.4

    def _process_xlsx(self, doc, xlsx_path: str) -> None:
        from openpyxl import load_workbook

        wb = load_workbook(xlsx_path, data_only=True)
        for ws in wb.worksheets:
            lines = []
            lines.append((f"— {ws.title} —", 12, True))
            lines.append(("", 10, False))
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) if c is not None else "" for c in row]
                lines.append(("  |  ".join(cells), 8, False))
            lines.append(("", 10, False))
            self._render_lines_to_doc(doc, lines)

    def _process_html(self, doc, html_path: str) -> None:
        from bs4 import BeautifulSoup

        with open(html_path, "r", encoding="utf-8", errors="replace") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
        lines = self._html_to_lines(soup)
        self._render_lines_to_doc(doc, lines)

    def _process_epub(self, doc, epub_path: str) -> None:
        import fitz

        converted = False
        try:
            epub_doc = fitz.open(epub_path)
            try:
                pdf_bytes = epub_doc.convert_to_pdf()
                pdf_part = fitz.open("pdf", pdf_bytes)
                try:
                    doc.insert_pdf(pdf_part)
                finally:
                    pdf_part.close()
                converted = True
            finally:
                epub_doc.close()
        except Exception:
            converted = False
        if not converted:
            try:
                epub_doc = fitz.open(epub_path)
                try:
                    lines = []
                    for page in epub_doc:
                        raw_text = page.get_text("text")
                        text = str(raw_text or "")
                        for line in text.split("\n"):
                            if line.strip():
                                lines.append((line.strip(), 10, False))
                            else:
                                lines.append(("", 10, False))
                    if lines:
                        self._render_lines_to_doc(doc, lines)
                finally:
                    epub_doc.close()
            except Exception:
                pass

    def _process_pdf(self, doc, pdf_path: str) -> None:
        import fitz

        pdf_part = fitz.open(pdf_path)
        try:
            doc.insert_pdf(pdf_part)
        finally:
            pdf_part.close()

    def _md_to_lines(self, md: str) -> list:
        result = []
        for line in md.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# "):
                result.append((stripped[2:], 18, True))
            elif stripped.startswith("## "):
                result.append((stripped[3:], 15, True))
            elif stripped.startswith("### "):
                result.append((stripped[4:], 13, True))
            elif stripped.startswith("#### "):
                result.append((stripped[5:], 12, True))
            elif stripped.startswith("- ") or stripped.startswith("* "):
                result.append(("  \u2022  " + stripped[2:], 10, False))
            elif stripped.startswith("```"):
                continue
            elif stripped in ("---", "***"):
                result.append(("\u2500" * 60, 8, False))
            elif stripped == "":
                result.append(("", 10, False))
            else:
                clean = stripped.replace("**", "").replace("__", "")
                clean = clean.replace("*", "").replace("_", "")
                clean = clean.replace("`", "")
                result.append((clean, 10, False))
        return result

    def _html_to_lines(self, soup) -> list:
        lines = []
        tag_map = {
            "h1": (18, True),
            "h2": (15, True),
            "h3": (13, True),
            "h4": (12, True),
            "h5": (11, True),
            "h6": (11, True),
        }
        for el in soup.find_all(
            [
                "h1", "h2", "h3", "h4", "h5", "h6",
                "p", "li", "pre", "td", "th", "blockquote",
            ]
        ):
            text = el.get_text(strip=True)
            if not text:
                continue
            tag = el.name
            if tag in tag_map:
                size, bold = tag_map[tag]
                lines.append((text, size, bold))
            elif tag == "li":
                lines.append(("  \u2022  " + text, 10, False))
            elif tag == "pre":
                for ln in text.split("\n"):
                    lines.append((ln, 9, False))
            elif tag == "blockquote":
                lines.append(("  \u201c " + text + " \u201d", 10, False))
            elif tag in ("th",):
                lines.append((text, 10, True))
            else:
                lines.append((text, 10, False))
            if tag in tag_map:
                lines.append(("", 10, False))
        return lines

    def _render_lines_to_doc(self, doc, lines: list):
        import fitz

        page = None
        y = 50
        for text, size, bold in lines:
            if page is None or y + size > 780:
                page = doc.new_page(width=595, height=842)
                y = 50
            if not text:
                y += size * 0.8
                continue
            font = "hebo" if bold else "helv"
            try:
                page.insert_text(fitz.Point(50, y), text, fontsize=size, fontname=font)
            except Exception:
                page.insert_text(fitz.Point(50, y), text, fontsize=size, fontname="helv")
            y += size * 1.5

    def _on_result(self, result, out_path: str):
        if isinstance(result, _NoContent):
            if result.skipped:
                self._status(t("tool.import.skipped_images", n=result.skipped))
            else:
                self._status(t("tool.import.no_content"))
            QMessageBox.warning(self, t("msg.warning"), t("tool.import.no_content"))
            return
        self._done(out_path)

    def _done(self, out_path: str):
        self.lbl_result.setText(f"  \u2192 {os.path.basename(out_path)}")
        self._status(t("tool.import.status.done", path=out_path))

        win: Any = self.window()
        viewer = getattr(win, "_viewer", None)
        cleanup_fn = getattr(win, "_cleanup_pipeline", None)
        if callable(cleanup_fn) and viewer:
            cleanup_fn(id(viewer))

        if viewer:
            viewer.load(out_path)

        QMessageBox.information(self, t("msg.done"), t("tool.import.done", path=out_path))