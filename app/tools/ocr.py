"""PDFApps – TabOCR: OCR text recognition tool using EasyOCR."""

from __future__ import annotations

import contextlib
import os
import tempfile
import warnings
from typing import Any

import fitz
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QFileDialog,
    QMessageBox,
    QProgressDialog,
    QProgressBar,
)

from app.base import BasePage
from app.pdf_io import atomic_pdf_write
from app.i18n import t
from app.utils import (
    section,
    info_lbl,
    show_error,
    CancelledError,
    WrongPasswordError,
)
from app.worker import TaskRunner, run_task
from app.constants import TEXT_SEC, DESKTOP
from app.widgets import DropFileEdit, FocusComboBox


class TabOCR(BasePage):
    """OCR tool powered by EasyOCR, outputting searchable PDFs or extracted plain text."""

    _LANG_KEYS = [
        ("tool.ocr.lang.en",    ["en"]),
        ("tool.ocr.lang.pt",    ["pt"]),
        ("tool.ocr.lang.pt_en", ["pt", "en"]),
        ("tool.ocr.lang.es",    ["es", "en"]),
        ("tool.ocr.lang.fr",    ["fr", "en"]),
        ("tool.ocr.lang.de",    ["de", "en"]),
        ("tool.ocr.lang.it",    ["it", "en"]),
    ]

    @property
    def _LANGS(self):
        return [(t(k), codes) for k, codes in self._LANG_KEYS]

    def __init__(self, status_fn):
        super().__init__(
            "fa5s.search",
            t("tool.ocr.name"),
            t("tool.ocr.desc"),
            t("tool.ocr.btn"),
            status_fn,
        )
        f = self._form

        sec_src = section(t("tool.ocr.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try:
            self.drop_in.btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in)
        f.addWidget(self.lbl_info)

        f.addWidget(section(t("tool.ocr.options")))
        row_lang = QHBoxLayout()
        lbl_lang = QLabel(t("tool.ocr.lang_label"))
        lbl_lang.setStyleSheet(f"color:{TEXT_SEC};")
        self.cmb_lang = FocusComboBox()
        self._lang_codes = [codes for _, codes in self._LANGS]
        for name, _ in self._LANGS:
            self.cmb_lang.addItem(name)
        row_lang.addWidget(lbl_lang)
        row_lang.addWidget(self.cmb_lang)
        row_lang.addStretch()
        f.addLayout(row_lang)

        row_fmt = QHBoxLayout()
        lbl_fmt = QLabel(t("tool.ocr.format_label"))
        lbl_fmt.setStyleSheet(f"color:{TEXT_SEC};")
        self.cmb_fmt = FocusComboBox()
        self.cmb_fmt.addItems([t("tool.ocr.format.pdf"), t("tool.ocr.format.txt")])
        self.cmb_fmt.currentIndexChanged.connect(self._on_fmt_change)
        row_fmt.addWidget(lbl_fmt)
        row_fmt.addWidget(self.cmb_fmt)
        row_fmt.addStretch()
        f.addLayout(row_fmt)

        sec_out = section(t("tool.ocr.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("ocr_output.pdf", save=True, default_name="ocr_output.pdf")
        f.addWidget(self.drop_out)
        f.addStretch()

        self._compact_hidden = [sec_src, self.drop_in, self.lbl_info]
        sec_out.setVisible(False)
        self.drop_out.setVisible(False)

    def _on_fmt_change(self, idx: int):
        p = self.drop_out.path()
        if p:
            base = os.path.splitext(p)[0]
            self.drop_out.set_path(base + (".pdf" if idx == 0 else ".txt"))

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if p:
            self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self._maybe_prompt_password(p):
            self.drop_in.blockSignals(True)
            self.drop_in.set_path("")
            self.drop_in.blockSignals(False)
            return
        if not self.drop_out.path():
            base = os.path.splitext(p)[0]
            ext = ".pdf" if self.cmb_fmt.currentIndex() == 0 else ".txt"
            self.drop_out.set_path(base + "_ocr" + ext)
        try:
            doc = self._open_fitz(p)
            self.lbl_info.setText(t("edit.status.pages", n=doc.page_count))
            doc.close()
        except Exception as e:
            self.lbl_info.setText(t("tool.split.error_info", e=e))

    def auto_load(self, path: str):
        if path and not self.drop_in.path():
            self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            win: Any = self.window()
            viewer = getattr(win, "_viewer", None)
            if viewer and viewer.current_path():
                pdf_path = viewer.current_path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf"))
            return

        is_pdf = (self.cmb_fmt.currentIndex() == 0)
        ext = ".pdf" if is_pdf else ".txt"
        default_name = f"ocr_output{ext}"
        if pdf_path:
            base, _ = os.path.splitext(os.path.basename(pdf_path))
            default_name = f"{base}_ocr{ext}"
        start_dir = os.path.dirname(pdf_path) if pdf_path else ""
        out_path = self._prompt_save_as(
            default_name,
            start_dir,
            filter_key="file_filter.pdf" if is_pdf else "file_filter.txt",
        )
        if not out_path:
            return
        self.drop_out.set_path(out_path)

        codes = getattr(self, "_lang_codes", [codes for _, codes in self._LANGS])
        if not codes:
            QMessageBox.warning(self, t("msg.warning"), t("tool.ocr.no_langs"))
            return
        idx = max(0, min(self.cmb_lang.currentIndex(), len(codes) - 1))
        selected_lang_list = list(codes[idx])
        fmt = self.cmb_fmt.currentIndex()
        pwd = self._pdf_password

        try:
            with self._open_fitz(pdf_path) as _doc:
                n_pages = _doc.page_count
        except Exception as e:
            show_error(self, e)
            return

        progress = QProgressDialog(
            "Initializing OCR model...",
            t("progress.cancel"),
            0,
            100,
            self,
        )
        progress.setWindowTitle(t("progress.ocr.title", default="OCR in progress"))
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setMinimumWidth(440)
        progress.setValue(0)

        bar = progress.findChild(QProgressBar)
        if bar is not None:
            bar.setTextVisible(True)
            bar.setFixedHeight(22)
            bar.setStyleSheet("""
                QProgressBar {
                    background: #1E1E1E;
                    border: 1px solid #555555;
                    border-radius: 6px;
                    text-align: center;
                    color: #FFFFFF;
                    font-size: 10pt;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background: #0078D4;
                    border-radius: 5px;
                }
            """)

        class _OcrRunner(TaskRunner):
            def do_work(_self):
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=UserWarning, module="torch")

                _self.progress.emit(5, "Checking EasyOCR models...")
                import easyocr
                import easyocr.utils

                orig_print_bar = getattr(easyocr.utils, "printProgressBar", None)

                def _custom_progress_bar(prefix='', suffix='', length=50):
                    def reporthook(block_num, block_size, total_size):
                        if _self.is_cancelled():
                            raise CancelledError("OCR cancelled by user")
                        if total_size > 0:
                            downloaded = block_num * block_size
                            pct = max(0, min(100, int((downloaded / total_size) * 100)))
                            cur_mb = downloaded / (1024 * 1024)
                            tot_mb = total_size / (1024 * 1024)
                            _self.progress.emit(
                                pct,
                                f"Downloading OCR model: {pct}% ({cur_mb:.1f}/{tot_mb:.1f} MB)",
                            )
                    return reporthook

                if hasattr(easyocr.utils, "printProgressBar"):
                    easyocr.utils.printProgressBar = _custom_progress_bar

                try:
                    import torch
                    use_gpu = bool(torch.cuda.is_available())
                except Exception:
                    use_gpu = False

                try:
                    reader = easyocr.Reader(selected_lang_list, gpu=use_gpu, verbose=True)
                finally:
                    if orig_print_bar is not None and hasattr(easyocr.utils, "printProgressBar"):
                        easyocr.utils.printProgressBar = orig_print_bar

                if _self.is_cancelled():
                    return None

                _self.progress.emit(20, "OCR models ready. Loading PDF...")

                doc = fitz.open(pdf_path)
                if doc.needs_pass:
                    if not (pwd and doc.authenticate(pwd)):
                        raise WrongPasswordError(t("tool.err.wrong_password"))
                try:
                    if fmt == 1:
                        texts = []
                        for i in range(len(doc)):
                            if _self.is_cancelled():
                                return None
                            page = doc[i]
                            page_pct = 20 + int(((i + 1) / n_pages) * 75)
                            _self.progress.emit(
                                page_pct,
                                t("progress.ocr.page", current=i + 1, total=n_pages),
                            )
                            pix = page.get_pixmap(dpi=150)
                            img_bytes = pix.tobytes("png")
                            raw_lines: Any = reader.readtext(img_bytes, detail=0)

                            page_lines = [
                                str(line).strip()
                                for line in raw_lines
                                if str(line).strip()
                            ]
                            texts.append("\n".join(page_lines))

                        _self.progress.emit(98, "Writing extracted text...")
                        self._check_not_same_path(out_path, [pdf_path])
                        out_dir = os.path.dirname(out_path) or os.getcwd()
                        _fd, _tmp = tempfile.mkstemp(suffix=".txt", dir=out_dir)
                        try:
                            with os.fdopen(_fd, "w", encoding="utf-8") as fh:
                                fh.write("\f\n".join(texts))
                            os.replace(_tmp, out_path)
                        except Exception:
                            if os.path.exists(_tmp):
                                with contextlib.suppress(OSError):
                                    os.unlink(_tmp)
                            raise
                    else:
                        for i in range(len(doc)):
                            if _self.is_cancelled():
                                return None
                            page = doc[i]
                            page_pct = 20 + int(((i + 1) / n_pages) * 75)
                            _self.progress.emit(
                                page_pct,
                                t("progress.ocr.page", current=i + 1, total=n_pages),
                            )
                            pix = page.get_pixmap(dpi=150)
                            img_bytes = pix.tobytes("png")
                            scale_x = page.rect.width / max(1.0, float(pix.width))
                            scale_y = page.rect.height / max(1.0, float(pix.height))

                            raw_results: Any = reader.readtext(img_bytes)

                            for entry in raw_results:
                                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                                    bbox = entry[0]
                                    text_clean = str(entry[1]).strip()
                                    prob = float(entry[2]) if len(entry) >= 3 else 1.0
                                elif isinstance(entry, dict):
                                    bbox = entry.get("boxes", [])
                                    text_clean = str(entry.get("text", "")).strip()
                                    prob = float(entry.get("confident", 1.0))
                                else:
                                    continue

                                if not text_clean or prob < 0.2:
                                    continue

                                xs = [pt[0] for pt in bbox]
                                ys = [pt[1] for pt in bbox]
                                x0 = min(xs) * scale_x
                                y0 = min(ys) * scale_y
                                x1 = max(xs) * scale_x
                                y1 = max(ys) * scale_y

                                box_rect = fitz.Rect(x0, y0, x1, y1) & page.rect
                                if box_rect.is_empty or box_rect.width < 1 or box_rect.height < 1:
                                    continue

                                h = max(6.0, box_rect.height)
                                font_size = max(4.0, min(72.0, h * 0.85))

                                rc = page.insert_textbox(
                                    box_rect,
                                    text_clean,
                                    fontsize=font_size,
                                    fontname="helv",
                                    render_mode=3,
                                )
                                if rc < 0:
                                    page.insert_text(
                                        fitz.Point(box_rect.x0, box_rect.y1 - h * 0.15),
                                        text_clean,
                                        fontsize=font_size,
                                        fontname="helv",
                                        render_mode=3,
                                    )

                        _self.progress.emit(98, "Saving output PDF...")
                        win: Any = self.window()
                        viewer = getattr(win, "_viewer", None)
                        if (
                            viewer
                            and viewer.current_path()
                            and os.path.abspath(viewer.current_path()) == os.path.abspath(out_path)
                        ):
                            viewer._canvas.close_doc()
                            if viewer._fitz_doc:
                                with contextlib.suppress(Exception):
                                    viewer._fitz_doc.close()
                                viewer._fitz_doc = None
                            viewer._thumbnails._stop_all_workers()

                        atomic_pdf_write(
                            doc,
                            out_path,
                            sources=[pdf_path],
                            save_opts={"garbage": 4, "deflate": True},
                            close_writer=True,
                        )

                    _self.progress.emit(100, "Done")
                finally:
                    with contextlib.suppress(Exception):
                        doc.close()
                return out_path

        self.action_btn.setEnabled(False)

        def _on_done(result):
            self.action_btn.setEnabled(True)
            if progress and not progress.isHidden():
                progress.close()

            if result is None:
                self._status(t("progress.cancelled"))
                return
            self._status(t("tool.ocr.status.done", path=result))

            win: Any = self.window()
            viewer = getattr(win, "_viewer", None)
            cleanup_fn = getattr(win, "_cleanup_pipeline", None)
            if callable(cleanup_fn) and viewer:
                cleanup_fn(id(viewer))

            if viewer and isinstance(result, str) and result.lower().endswith(".pdf"):
                viewer.load(result)

            target_parent = win if (win and win.isVisible()) else self
            QMessageBox.information(target_parent, t("msg.done"), t("tool.ocr.done", path=result))

        def _on_err(exc):
            self.action_btn.setEnabled(True)
            if progress and not progress.isHidden():
                progress.close()

            if not isinstance(exc, BaseException):
                exc = RuntimeError(str(exc))
            target_parent = self.window() if (self.window() and self.window().isVisible()) else self
            show_error(target_parent, exc)

        self._runner = _OcrRunner()
        self._runner_thread = run_task(self, self._runner, progress, _on_done, _on_err)