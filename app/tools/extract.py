# app/tools/extract.py

"""PDFApps – TabExtrair: extract PDF pages tool."""

import contextlib
import os
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QHBoxLayout, QLineEdit, QLabel, QFileDialog, QMessageBox,
    QPushButton,
)
from pypdf import PdfWriter

from app.base import BasePage
from app.pdf_io import atomic_pdf_write
from app.i18n import t
from app.utils import section, info_lbl, parse_pages, show_error
from app.constants import DESKTOP
from app.widgets import DropFileEdit


class TabExtrair(BasePage):
    def __init__(self, status_fn):
        super().__init__("fa5s.file-export", t("tool.extract.name"),
                         t("tool.extract.desc"),
                         t("tool.extract.btn"), status_fn)
        self._pipeline_supported = True
        f = self._form
        sec_src = section(t("tool.extract.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox(t("tool.extract.section"))
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText(t("tool.extract.hint"))
        hint = QLabel(t("tool.extract.help"))
        hint.setObjectName("info_lbl")
        form.addRow(t("tool.extract.pages_label"), self.edit_pages)
        form.addRow("", hint)
        f.addWidget(grp)

        # In-panel action button row
        btn_save_row = QHBoxLayout()
        btn_save_row.setContentsMargins(0, 10, 0, 0)
        btn_save_row.addStretch()
        self.btn_save = QPushButton(t("tool.extract.btn"))
        self.btn_save.setObjectName("btn_action_small")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.setFixedHeight(32)
        self.btn_save.setMinimumWidth(80)
        self.btn_save.clicked.connect(self._run)
        btn_save_row.addWidget(self.btn_save)
        f.addLayout(btn_save_row)
        self.action_btn = self.btn_save

        sec_out = section(t("tool.extract.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("extracted.pdf", save=True, default_name="extracted.pdf")
        f.addWidget(self.drop_out); f.addStretch()
        self._compact_hidden = [sec_src, self.drop_in, self.lbl_info]
        sec_out.setVisible(False)
        self.drop_out.setVisible(False)
        self._action_bar.setVisible(False)

    def _pick_input(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if p: self._load_input(p)

    def _load_input(self, p: str):
        self.drop_in.blockSignals(True)
        self.drop_in.set_path(p)
        self.drop_in.blockSignals(False)
        if not self._maybe_prompt_password(p):
            self.drop_in.blockSignals(True); self.drop_in.set_path("")
            self.drop_in.blockSignals(False); return
        if not self.drop_out.path():
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_extracted" + ext)
        try:
            r = self._open_reader(p); self.lbl_info.setText(t("edit.status.pages", n=len(r.pages)))
        except Exception as e: self.lbl_info.setText(t("tool.split.error_info", e=e))

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _run(self):
        pdf_path = self.drop_in.path()
        txt = self.edit_pages.text().strip()
        win: Any = self.window()
        viewer = getattr(win, "_viewer", None)
        if not pdf_path or not os.path.isfile(pdf_path):
            if viewer and viewer.current_path():
                pdf_path = viewer.current_path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf")); return
        if not txt:
            QMessageBox.warning(self, t("msg.warning"), t("tool.extract.specify")); return
        
        default_name = "extracted.pdf"
        if pdf_path:
            base, ext = os.path.splitext(os.path.basename(pdf_path))
            default_name = f"{base}_extracted{ext}"
        start_dir = os.path.dirname(pdf_path) if pdf_path else ""
        out_path = self._prompt_save_as(default_name, start_dir)
        if not out_path:
            return
        self.drop_out.set_path(out_path)

        try:
            reader = self._open_reader(pdf_path)
            pages  = parse_pages(txt, len(reader.pages))
            w = PdfWriter()
            for p in pages: w.add_page(reader.pages[p])

            if viewer and viewer.current_path() and os.path.abspath(viewer.current_path()) == os.path.abspath(out_path):
                viewer._canvas.close_doc()
                if viewer._fitz_doc:
                    with contextlib.suppress(Exception):
                        viewer._fitz_doc.close()
                    viewer._fitz_doc = None
                viewer._thumbnails._stop_all_workers()

            atomic_pdf_write(w, out_path, sources=[pdf_path])
            
            self._status(t("tool.extract.status.done",
                           n=len(pages), name=os.path.basename(out_path)))
            msg = t("tool.extract.done", n=len(pages), path=out_path)

            cleanup_fn = getattr(win, "_cleanup_pipeline", None)
            if callable(cleanup_fn) and viewer:
                cleanup_fn(id(viewer))

            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle(t("msg.done"))
            box.setText(msg)
            btn_open = box.addButton("Open Extracted PDF", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Ok)
            box.setDefaultButton(btn_open)
            box.exec()

            if box.clickedButton() == btn_open:
                if viewer:
                    viewer.load(out_path)
                elif win and hasattr(win, "_load_and_track"):
                    win._load_and_track(out_path)
        except Exception as e: show_error(self, e)