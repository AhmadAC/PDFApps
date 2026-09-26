# app\tools\rotate.py

"""PDFApps – TabRotar: rotate PDF pages tool."""
import contextlib
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox, QFormLayout, QHBoxLayout, QLineEdit,
    QPushButton, QFileDialog, QMessageBox,
)
import qtawesome as qta
from pypdf import PdfWriter

from app import i18n
from app.base import BasePage
from app.pdf_io import atomic_pdf_write
from app.i18n import t, get_language
from app.utils import section, info_lbl, parse_pages, show_error
from app.constants import DESKTOP, TEXT_PRI, TEXT_SEC, _LQ
from app.widgets import DropFileEdit, FocusComboBox


_SAVE_BTN_TEXT = {
    "en": "Save",
    "pt": "Guardar",
    "es": "Guardar",
    "fr": "Enregistrer",
    "de": "Speichern",
    "zh": "保存",
    "it": "Salva",
    "nl": "Opslaan",
}

for _lang, _text in _SAVE_BTN_TEXT.items():
    if _lang in i18n._TRANSLATIONS:
        i18n._TRANSLATIONS[_lang]["tool.rotate.btn"] = _text


class TabRotar(BasePage):
    """Rotate PDF pages in memory with live viewer preview before saving."""

    rotations_changed = Signal(object)

    def __init__(self, status_fn):
        btn_text = _SAVE_BTN_TEXT.get(get_language(), "Save")
        super().__init__("fa5s.sync-alt", t("tool.rotate.name"),
                         t("tool.rotate.desc"),
                         btn_text, status_fn)
        self._pipeline_supported = True
        self._page_count = 0
        self._rotations: dict[int, int] = {}
        self._updating_controls = False

        self._undo_stack: list[dict[int, int]] = []
        self._redo_stack: list[dict[int, int]] = []

        f = self._form

        sec_src = section(t("tool.rotate.source"))
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

        grp = QGroupBox(t("tool.rotate.options"))
        form = QFormLayout(grp)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.edit_pages = QLineEdit()
        self.edit_pages.setPlaceholderText(t("tool.rotate.pages_hint"))
        self.edit_pages.textChanged.connect(self._on_pages_changed)

        self.cmb_angle = FocusComboBox()
        self.cmb_angle.addItems([
            t("tool.rotate.90"),
            t("tool.rotate.180"),
            t("tool.rotate.270"),
        ])
        self.cmb_angle.currentIndexChanged.connect(self._on_angle_changed)

        form.addRow(t("tool.rotate.pages_label"), self.edit_pages)
        form.addRow(t("tool.rotate.angle_label"), self.cmb_angle)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_rot_left = QPushButton("90°")
        self.btn_rot_left.setIcon(qta.icon("fa5s.undo", color=TEXT_PRI))
        self.btn_rot_left.setToolTip("90° Counter-clockwise")
        self.btn_rot_left.clicked.connect(self._rotate_left)

        self.btn_rot_right = QPushButton("90°")
        self.btn_rot_right.setIcon(qta.icon("fa5s.redo", color=TEXT_PRI))
        self.btn_rot_right.setToolTip("90° Clockwise")
        self.btn_rot_right.clicked.connect(self._rotate_right)

        self.btn_rot_180 = QPushButton("180°")
        self.btn_rot_180.clicked.connect(self._rotate_180)

        self.btn_reset_rot = QPushButton()
        self.btn_reset_rot.setIcon(qta.icon("fa5s.history", color=TEXT_SEC))
        self.btn_reset_rot.setToolTip(t("btn.reset_order"))
        self.btn_reset_rot.clicked.connect(self._reset_rotations)

        btn_row.addWidget(self.btn_rot_left)
        btn_row.addWidget(self.btn_rot_right)
        btn_row.addWidget(self.btn_rot_180)
        btn_row.addWidget(self.btn_reset_rot)
        form.addRow("", btn_row)

        f.addWidget(grp)

        sec_out = section(t("tool.rotate.output"))
        f.addWidget(sec_out)
        self.drop_out = DropFileEdit("rotated.pdf", save=True, default_name="rotated.pdf")
        f.addWidget(self.drop_out)
        f.addStretch()

        self._compact_hidden = [sec_src, self.drop_in, self.lbl_info]
        sec_out.setVisible(False)
        self.drop_out.setVisible(False)

    def _get_target_pages(self) -> list[int]:
        total = self._page_count
        if total <= 0:
            cur_path = self.drop_in.path()
            if cur_path and os.path.isfile(cur_path):
                try:
                    doc = self._open_fitz(cur_path)
                    self._page_count = doc.page_count
                    total = self._page_count
                    doc.close()
                except Exception:
                    try:
                        r = self._open_reader(cur_path)
                        self._page_count = len(r.pages)
                        total = self._page_count
                    except Exception:
                        pass
        if total <= 0:
            win = self.window()
            viewer = getattr(win, "_viewer", None)
            if viewer is not None:
                doc = getattr(viewer, "_fitz_doc", None)
                if doc is not None and not getattr(doc, "is_closed", False):
                    self._page_count = doc.page_count
                    total = self._page_count
        if total <= 0:
            return []
        txt = self.edit_pages.text().strip()
        if not txt:
            return list(range(total))
        try:
            return parse_pages(txt, total)
        except ValueError:
            return []

    def _push_undo(self):
        self._undo_stack.append(dict(self._rotations))
        self._redo_stack.clear()

    def _undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(dict(self._rotations))
        self._rotations = self._undo_stack.pop()
        self._sync_angle_combo()
        self.rotations_changed.emit(self._rotations)

    def _redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(dict(self._rotations))
        self._rotations = self._redo_stack.pop()
        self._sync_angle_combo()
        self.rotations_changed.emit(self._rotations)

    def _on_angle_changed(self):
        if self._updating_controls:
            return
        self._push_undo()
        angle = {0: 90, 1: 180, 2: 270}.get(self.cmb_angle.currentIndex(), 90)
        target_pages = self._get_target_pages()
        for p in target_pages:
            self._rotations[p] = angle
        self.rotations_changed.emit(self._rotations)

    def _on_pages_changed(self):
        if self._updating_controls:
            return
        self._push_undo()
        angle = {0: 90, 1: 180, 2: 270}.get(self.cmb_angle.currentIndex(), 90)
        target_pages = self._get_target_pages()
        self._rotations.clear()
        for p in target_pages:
            self._rotations[p] = angle
        self.rotations_changed.emit(self._rotations)

    def _rotate_left(self):
        self._push_undo()
        target_pages = self._get_target_pages()
        for p in target_pages:
            self._rotations[p] = (self._rotations.get(p, 0) + 270) % 360
        self._sync_angle_combo()
        self.rotations_changed.emit(self._rotations)

    def _rotate_right(self):
        self._push_undo()
        target_pages = self._get_target_pages()
        for p in target_pages:
            self._rotations[p] = (self._rotations.get(p, 0) + 90) % 360
        self._sync_angle_combo()
        self.rotations_changed.emit(self._rotations)

    def _rotate_180(self):
        self._push_undo()
        target_pages = self._get_target_pages()
        for p in target_pages:
            self._rotations[p] = (self._rotations.get(p, 0) + 180) % 360
        self._sync_angle_combo()
        self.rotations_changed.emit(self._rotations)

    def _reset_rotations(self):
        if not self._rotations:
            return
        self._push_undo()
        self._rotations.clear()
        target_pages = self._get_target_pages()
        for p in target_pages:
            self._rotations[p] = 0
        self._sync_angle_combo()
        self.rotations_changed.emit(self._rotations)

    def _sync_angle_combo(self):
        target_pages = self._get_target_pages()
        if not target_pages:
            return
        angles = [self._rotations.get(p, 0) % 360 for p in target_pages]
        first_angle = angles[0] if angles else 0
        if all(a == first_angle for a in angles) and first_angle in (90, 180, 270):
            self._updating_controls = True
            mapping = {90: 0, 180: 1, 270: 2}
            self.cmb_angle.setCurrentIndex(mapping.get(first_angle, 0))
            self._updating_controls = False

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
            base, ext = os.path.splitext(p)
            self.drop_out.set_path(base + "_rotated" + ext)
        try:
            doc = self._open_fitz(p)
            self._page_count = doc.page_count
            doc.close()
        except Exception:
            try:
                r = self._open_reader(p)
                self._page_count = len(r.pages)
            except Exception as e:
                self.lbl_info.setText(t("tool.split.error_info", e=e))
                return
        
        self._rotations.clear()
        self._undo_stack.clear()
        self._redo_stack.clear()
        
        self.lbl_info.setText(t("edit.status.pages", n=self._page_count))
        self.rotations_changed.emit(self._rotations)

    def auto_load(self, path: str):
        if path and (self.drop_in.path() != path or self._page_count <= 0):
            self._load_input(path)

    def update_theme(self, dark: bool) -> None:
        super().update_theme(dark)
        pri = TEXT_PRI if dark else _LQ
        self.btn_rot_left.setIcon(qta.icon("fa5s.undo", color=pri))
        self.btn_rot_right.setIcon(qta.icon("fa5s.redo", color=pri))
        self.btn_reset_rot.setIcon(qta.icon("fa5s.history", color=TEXT_SEC if dark else _LQ))

    def _run(self):
        pdf_path = self.drop_in.path()
        if not pdf_path or not os.path.isfile(pdf_path):
            win = self.window()
            viewer = getattr(win, "_viewer", None)
            if viewer and viewer.current_path():
                pdf_path = viewer.current_path()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.select_valid_pdf"))
            return

        # Prompt Save As dialog so user can choose destination file and name
        default_name = "rotated.pdf"
        if pdf_path:
            base, ext = os.path.splitext(os.path.basename(pdf_path))
            default_name = f"{base}_rotated{ext}"
        start_dir = os.path.dirname(pdf_path) if pdf_path else ""
        out_path = self._prompt_save_as(default_name, start_dir)
        if not out_path:
            return
        self.drop_out.set_path(out_path)

        win = self.window()
        viewer = getattr(win, "_viewer", None)

        try:
            reader = self._open_reader(pdf_path)
            total = len(reader.pages)

            if not self._rotations:
                angle = {0: 90, 1: 180, 2: 270}.get(self.cmb_angle.currentIndex(), 90)
                txt = self.edit_pages.text().strip()
                pages = parse_pages(txt, total) if txt else list(range(total))
                for p in pages:
                    self._rotations[p] = angle

            w = PdfWriter()
            for i, page in enumerate(reader.pages):
                rot = self._rotations.get(i, 0) % 360
                if rot:
                    page.rotate(rot)
                w.add_page(page)

            # Release viewer document locks before atomic overwrite if applicable
            if viewer and viewer.current_path() and os.path.abspath(viewer.current_path()) == os.path.abspath(out_path):
                viewer._canvas.close_doc()
                if viewer._fitz_doc:
                    with contextlib.suppress(Exception):
                        viewer._fitz_doc.close()
                    viewer._fitz_doc = None
                viewer._thumbnails._stop_all_workers()

            atomic_pdf_write(w, out_path, sources=[pdf_path])

            self._status(t("tool.rotate.status.done", name=os.path.basename(out_path)))
            msg = t("tool.rotate.done", path=out_path)

            if win and hasattr(win, "_cleanup_pipeline") and viewer:
                win._cleanup_pipeline(id(viewer))

            if viewer:
                viewer.load(out_path)

            QMessageBox.information(self, t("msg.done"), msg)
        except Exception as e:
            show_error(self, e)