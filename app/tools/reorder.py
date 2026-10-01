"""PDFApps – TabReordenar: reorder PDF pages tool."""

import contextlib
import os
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QAbstractItemView, QPushButton, QFileDialog, QMessageBox,
)
import qtawesome as qta
from pypdf import PdfWriter

from app.base import BasePage
from app.pdf_io import atomic_pdf_write
from app.i18n import t
from app.utils import section, info_lbl, danger_btn, show_error
from app.constants import DESKTOP, TEXT_PRI, _LQ
from app.widgets import DropFileEdit


class _ReorderListWidget(QListWidget):
    """List widget that emits a signal whenever an internal drag-and-drop reorder occurs or a delete key is pressed."""

    order_changed = Signal()

    def dropEvent(self, event):
        super().dropEvent(event)
        self.order_changed.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            r = self.currentRow()
            if r >= 0:
                self.takeItem(r)
                if self.count() > 0:
                    self.setCurrentRow(min(r, self.count() - 1))
                self.order_changed.emit()
                event.accept()
                return
        super().keyPressEvent(event)


class TabReordenar(BasePage):
    order_changed = Signal(object)

    def __init__(self, status_fn):
        super().__init__("fa5s.sort", t("tool.reorder.name"),
                         t("tool.reorder.desc"),
                         t("tool.reorder.btn"), status_fn)
        self._pipeline_supported = True
        self._page_count = 0
        f = self._form
        sec_src = section(t("tool.reorder.source"))
        f.addWidget(sec_src)
        self.drop_in = DropFileEdit()
        try: self.drop_in.btn.clicked.disconnect()
        except RuntimeError: pass
        self.drop_in.btn.clicked.connect(self._pick_input)
        self.drop_in.path_changed.connect(self._load_input)
        self.lbl_info = info_lbl()
        f.addWidget(self.drop_in); f.addWidget(self.lbl_info)

        grp = QGroupBox(t("tool.reorder.list"))
        vl  = QVBoxLayout(grp); vl.setSpacing(8)
        self.lst = _ReorderListWidget()
        self.lst.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lst.setAlternatingRowColors(True)
        self.lst.setMinimumHeight(200)
        self.lst.order_changed.connect(self._emit_order_changed)
        vl.addWidget(self.lst)

        hb = QHBoxLayout()
        hb.setSpacing(6)

        self.btn_up = QPushButton()
        self.btn_up.setIcon(qta.icon("fa5s.arrow-up", color=TEXT_PRI))
        self.btn_up.setToolTip(t("btn.up"))
        self.btn_up.setAccessibleName(t("btn.up"))
        self.btn_up.setFixedWidth(40)
        self.btn_up.clicked.connect(self._up)

        self.btn_dn = QPushButton()
        self.btn_dn.setIcon(qta.icon("fa5s.arrow-down", color=TEXT_PRI))
        self.btn_dn.setToolTip(t("btn.down"))
        self.btn_dn.setAccessibleName(t("btn.down"))
        self.btn_dn.setFixedWidth(40)
        self.btn_dn.clicked.connect(self._dn)

        self.btn_del = danger_btn("")
        self.btn_del.setIcon(qta.icon("fa5s.trash-alt", color="#F87171"))
        self.btn_del.setToolTip(t("btn.delete"))
        self.btn_del.setAccessibleName(t("btn.delete"))
        self.btn_del.setFixedWidth(40)
        self.btn_del.clicked.connect(self._del)

        self.btn_reset = QPushButton()
        self.btn_reset.setIcon(qta.icon("fa5s.history", color=TEXT_PRI))
        self.btn_reset.setToolTip(t("btn.reset_order"))
        self.btn_reset.setAccessibleName(t("btn.reset_order"))
        self.btn_reset.setFixedWidth(40)
        self.btn_reset.clicked.connect(self._reset)

        hb.addWidget(self.btn_up)
        hb.addWidget(self.btn_dn)
        hb.addWidget(self.btn_del)
        hb.addWidget(self.btn_reset)
        hb.addStretch()
        vl.addLayout(hb)
        f.addWidget(grp)

        sec_out = section(t("tool.reorder.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("reordered.pdf", save=True, default_name="reordered.pdf")
        f.addWidget(self.drop_out); f.addStretch()
        self._compact_hidden = [sec_src, self.drop_in, self.lbl_info]
        sec_out.setVisible(False)
        self.drop_out.setVisible(False)

    def update_theme(self, dark: bool) -> None:
        super().update_theme(dark)
        pri = TEXT_PRI if dark else _LQ
        self.btn_up.setIcon(qta.icon("fa5s.arrow-up", color=pri))
        self.btn_dn.setIcon(qta.icon("fa5s.arrow-down", color=pri))
        self.btn_del.setIcon(qta.icon("fa5s.trash-alt", color="#F87171" if dark else "#DC2626"))
        self.btn_reset.setIcon(qta.icon("fa5s.history", color=pri))

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
            self.drop_out.set_path(base + "_reordered" + ext)
        try:
            reader = self._open_reader(p)
            n = len(reader.pages)
            self._page_count = n
            self.lbl_info.setText(t("edit.status.pages", n=n))
            self._populate(list(range(n)))
            self._emit_order_changed()
        except Exception as e:
            self._page_count = 0
            self.lbl_info.setText(t("tool.split.error_info", e=e))

    def auto_load(self, path: str):
        if path and not self.drop_in.path(): self._load_input(path)

    def _populate(self, indices: list):
        self.lst.clear()
        for i in indices:
            item = QListWidgetItem(t("tool.reorder.page", n=i + 1))
            item.setData(256, i); self.lst.addItem(item)

    def get_order(self) -> list[int]:
        return [self.lst.item(i).data(256) for i in range(self.lst.count())]

    def _emit_order_changed(self):
        self.order_changed.emit(self.get_order())

    def _up(self):
        r = self.lst.currentRow()
        if r > 0:
            item = self.lst.takeItem(r)
            self.lst.insertItem(r - 1, item)
            self.lst.setCurrentRow(r - 1)
            self._emit_order_changed()

    def _dn(self):
        r = self.lst.currentRow()
        if r >= 0 and r < self.lst.count() - 1:
            item = self.lst.takeItem(r)
            self.lst.insertItem(r + 1, item)
            self.lst.setCurrentRow(r + 1)
            self._emit_order_changed()

    def _del(self):
        r = self.lst.currentRow()
        if r >= 0:
            self.lst.takeItem(r)
            if self.lst.count() > 0:
                self.lst.setCurrentRow(min(r, self.lst.count() - 1))
            self._emit_order_changed()

    def _reset(self):
        if self._page_count:
            self._populate(list(range(self._page_count)))
            self._emit_order_changed()

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
        if not self._page_count:
            QMessageBox.warning(self, t("msg.warning"), t("msg.open_pdf_first"))
            return
        indices = self.get_order()
        if not indices:
            QMessageBox.warning(self, t("msg.warning"), t("tool.reorder.no_pages"))
            return

        default_name = "reordered.pdf"
        if pdf_path:
            base, ext = os.path.splitext(os.path.basename(pdf_path))
            default_name = f"{base}_reordered{ext}"
        start_dir = os.path.dirname(pdf_path) if pdf_path else ""
        out_path = self._prompt_save_as(default_name, start_dir)
        if not out_path:
            return
        self.drop_out.set_path(out_path)

        win: Any = self.window()
        viewer = getattr(win, "_viewer", None)

        try:
            reader = self._open_reader(pdf_path)
            w = PdfWriter()
            for idx in indices:
                w.add_page(reader.pages[idx])

            if viewer and viewer.current_path() and os.path.abspath(viewer.current_path()) == os.path.abspath(out_path):
                viewer._canvas.close_doc()
                if viewer._fitz_doc:
                    with contextlib.suppress(Exception):
                        viewer._fitz_doc.close()
                    viewer._fitz_doc = None
                viewer._thumbnails._stop_all_workers()

            atomic_pdf_write(w, out_path, sources=[pdf_path])
            self._status(t("tool.reorder.status.done", name=os.path.basename(out_path)))
            msg = t("tool.reorder.done", path=out_path)

            cleanup_fn = getattr(win, "_cleanup_pipeline", None)
            if callable(cleanup_fn) and viewer:
                cleanup_fn(id(viewer))

            if viewer:
                viewer.load(out_path)

            QMessageBox.information(self, t("msg.done"), msg)
        except Exception as e:
            show_error(self, e)