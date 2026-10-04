# app/editor/tab.py
"""PDFApps – TabEditar: visual PDF editor tool tab with media object manipulation & typography styling."""

from __future__ import annotations

import os
from typing import Callable

import fitz
from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtWidgets import (
    QWidget, QScrollArea, QGroupBox, QPushButton, QLabel,
    QStackedWidget, QListWidget, QTextEdit, QTableWidget,
    QSlider, QFileDialog, QMessageBox, QDialog, QApplication,
)
from shiboken6 import isValid
import qtawesome as qta

from app.constants import ACCENT, TEXT_PRI, TEXT_SEC, DESKTOP, _LQ
from app.utils import _paint_bg
from app.i18n import t
from app.widgets import DropFileEdit, ColorPickerButton, FocusSpinBox, FocusComboBox
from app.editor.canvas import PdfEditCanvas
from app.editor.dialogs import _NoteDialog, _SignatureDialog, load_signature_pixmap
from app.pdf_password import authenticate_fitz

try:
    from app.editor.canvas_render1 import _get_icon_cursor
except ImportError:
    try:
        from .canvas_render1 import _get_icon_cursor
    except ImportError:
        from app.editor.canvas import _get_icon_cursor  # type: ignore

from app.editor.tab_constants import (
    _MAX_REDO, _MAX_PENDING,
    _HI_COLORS_KEYS, _HI_COLORS_VALS,
    _RED_FILLS_KEYS, _RED_FILLS_VALS,
    _MODE_KEYS, _DRAW_COLORS_KEYS, _DRAW_COLORS_VALS,
    _MODE_REDACT, _MODE_TEXT, _MODE_IMAGE, _MODE_HIGHLIGHT,
    _MODE_NOTE, _MODE_FORMS, _MODE_SIGNATURE, _MODE_DRAW, _MODE_SELECT,
)
from app.editor.tab_ui import setup_editor_ui, update_tab_theme
from app.editor.tab_history import TabHistoryManager
from app.editor.tab_operations import (
    prompt_encryption_choice, get_fitz_permissions, cleanup_signature_temp_file,
    load_form_fields, apply_form_fields_and_save, apply_visual_edits_and_save,
)

# Safe fallback for PyMuPDF annotation constant to satisfy Pylance
_PDF_ANNOT_TEXT: int = getattr(fitz, "PDF_ANNOT_TEXT", 0)


class TabEditar(QWidget):
    """Visual editor facade: click/drag directly on the rendered PDF."""

    _MAX_REDO = _MAX_REDO
    _MAX_PENDING = _MAX_PENDING
    _HI_COLORS_KEYS = _HI_COLORS_KEYS
    _HI_COLORS_VALS = _HI_COLORS_VALS
    _RED_FILLS_KEYS = _RED_FILLS_KEYS
    _RED_FILLS_VALS = _RED_FILLS_VALS
    _MODE_KEYS = _MODE_KEYS
    _DRAW_COLORS_KEYS = _DRAW_COLORS_KEYS
    _DRAW_COLORS_VALS = _DRAW_COLORS_VALS

    # UI controls (attached by setup_editor_ui)
    _canvas: PdfEditCanvas
    _canvas_scroll: QScrollArea
    _ctrl_scroll: QScrollArea
    _grp_file: QGroupBox
    _drop_in: DropFileEdit
    _lbl_info: QLabel
    _btn_prev: QPushButton
    _lbl_page: QLabel
    _btn_next: QPushButton
    _mode_btns: list[QPushButton]
    _mode_btn_idx: dict[int, int]
    _opt_stack: QStackedWidget
    _hint_labels: list[QLabel]
    _pending_list: QListWidget
    _btn_undo: QPushButton
    _btn_redo: QPushButton
    _grp_save: QGroupBox
    _drop_out: DropFileEdit
    _action_bar: QWidget

    # Mode option widgets (attached by _build_mode_options in setup_editor_ui)
    _btn_text_add: QPushButton
    _btn_text_edit: QPushButton
    _red_color: ColorPickerButton
    _text_font: FocusComboBox
    _text_size: FocusSpinBox
    _btn_bold: QPushButton
    _btn_italic: QPushButton
    _text_color: ColorPickerButton
    _btn_del_text: QPushButton
    _text_hint: QLabel
    _img_drop: DropFileEdit
    _hi_color: ColorPickerButton
    _note_txt: QTextEdit
    _form_table: QTableWidget
    _form_status: QLabel
    _sig_preview: QLabel
    _sig_choose: QPushButton
    _draw_color_cb: ColorPickerButton
    _draw_width_slider: QSlider
    _draw_width_lbl: QLabel
    _sel_result: QTextEdit
    _btn_copy: QPushButton

    @property
    def _HI_COLORS(self):
        return {t(k): v for k, v in zip(self._HI_COLORS_KEYS, self._HI_COLORS_VALS)}

    @property
    def _RED_FILLS(self):
        return {t(k): v for k, v in zip(self._RED_FILLS_KEYS, self._RED_FILLS_VALS)}

    @property
    def _MODE_DEFS(self):
        return [(t(k), icon) for k, icon in self._MODE_KEYS]

    @property
    def _DRAW_COLORS(self):
        return {t(k): v for k, v in zip(self._DRAW_COLORS_KEYS, self._DRAW_COLORS_VALS)}

    @property
    def _user_pending(self) -> list:
        return [
            e for e in self._pending
            if not e.get("_existing") or e.get("_deleted") or e.get("type") in ("delete_annot", "text_edit", "image", "signature")
        ]

    def __init__(self, status_fn: Callable[[str], None]):
        super().__init__()
        self._status = status_fn
        self._pending: list[dict] = []
        self._redo_stack: list[dict] = []
        self._doc_path: str | None = None
        self._pdf_password: str = ""
        self._mode_idx: int = _MODE_TEXT
        self._text_submode: str = "edit"
        self._dark_mode: bool = True
        self._signature_path: str | None = None
        self._page_idx: int = 0

        self._history = TabHistoryManager(self)
        setup_editor_ui(self)

        # Wire canvas signals
        self._canvas.rect_selected.connect(self._on_rect)
        self._canvas.point_clicked.connect(self._on_point)
        self._canvas.stroke_finished.connect(self._on_stroke)
        self._canvas.note_deleted.connect(self._on_note_deleted)
        self._canvas.text_edit_committed.connect(self._on_text_edit_committed)
        self._canvas.text_inserted.connect(self._on_text_edit_committed)
        self._canvas.text_edit_started.connect(self._on_text_edit_started)
        self._canvas.signature_added.connect(self._on_signature_added)
        self._canvas.overlay_changed.connect(self.update)
        self._canvas.overlay_deleted.connect(self._on_overlay_deleted)

        self._set_text_submode("edit")
        self._on_mode_btn(self._mode_btns[_MODE_TEXT])
        self._update_nav()

    def toggle_controls(self) -> bool:
        """Toggle the right-hand controls sidebar within the editor."""
        is_vis = self._ctrl_scroll.isVisible()
        self._ctrl_scroll.setVisible(not is_vis)
        if hasattr(self, "_canvas") and self._canvas._doc and self._canvas._zoom_factor == 1.0:
            QTimer.singleShot(50, self._canvas._layout_and_schedule)
        return not is_vis

    def paintEvent(self, event):
        _paint_bg(self)

    def eventFilter(self, obj, event):
        if obj is self._canvas_scroll.viewport() and event.type() == QEvent.Type.Resize:
            if self._canvas._doc and self._canvas._zoom_factor == 1.0:
                QTimer.singleShot(0, self._canvas._layout_and_schedule)
        return super().eventFilter(obj, event)

    def set_compact_mode(self, active: bool, path: str = "") -> None:
        if active and path:
            self._load_pdf(path)
        self._grp_file.setVisible(not active)
        self._grp_save.setVisible(not active)

    def update_theme(self, dark: bool) -> None:
        update_tab_theme(self, dark)
        self._update_text_submode_styles()

    def _update_nav(self):
        n = self._canvas.page_count()
        self._btn_prev.setEnabled(n > 0 and self._page_idx > 0)
        self._btn_next.setEnabled(n > 0 and self._page_idx < n - 1)
        self._lbl_page.setText(f"{self._page_idx+1} / {n}" if n else "—")

    def _scroll_to(self, idx: int):
        self._page_idx = idx
        y = self._canvas.scroll_to_page(idx)
        self._canvas_scroll.verticalScrollBar().setValue(y)
        self._update_nav()

    def _prev_page(self):
        if self._page_idx > 0:
            self._scroll_to(self._page_idx - 1)

    def _next_page(self):
        if self._page_idx < self._canvas.page_count() - 1:
            self._scroll_to(self._page_idx + 1)

    def _on_mode_btn(self, btn: QPushButton):
        idx = self._mode_btn_idx.get(id(btn), 0)
        self._mode_idx = idx
        sec = TEXT_SEC if self._dark_mode else _LQ
        for i, b in enumerate(self._mode_btns):
            active = b is btn
            b.setChecked(active)
            b.setIcon(qta.icon(self._MODE_DEFS[i][1], color=ACCENT if active else sec))
            if active:
                b.setStyleSheet(
                    f"background:#264F78; border:1px solid {ACCENT}; color:#FFFFFF; border-radius:6px;"
                    if self._dark_mode else
                    f"background:#D6E8FA; border:1px solid #70A7DB; color:{ACCENT}; border-radius:6px;"
                )
            else:
                b.setStyleSheet(
                    "background:#333333; border:1px solid #444444; color:#CCCCCC; border-radius:6px;"
                    if self._dark_mode else
                    "background:#FFFFFF; border:1px solid #D1D5DB; color:#555555; border-radius:6px;"
                )
        self._opt_stack.setCurrentIndex(idx)
        if idx == _MODE_FORMS:
            tip = t("editor.forms.undo_unavailable")
            self._btn_undo.setToolTip(tip)
            self._btn_redo.setToolTip(tip)
        else:
            self._btn_undo.setToolTip(t("edit.undo_tip"))
            self._btn_redo.setToolTip(t("edit.redo_tip"))
        if hasattr(self, "_canvas") and self._canvas._inline_edit.isVisible():
            self._canvas._commit_inline()
        self._canvas.set_select_mode(idx in (_MODE_SIGNATURE, _MODE_SELECT))
        is_draw = (idx == _MODE_DRAW)
        self._canvas.set_draw_mode(
            is_draw,
            color=self._draw_color_cb.color_tuple() if is_draw else None,
            width=self._draw_width_slider.value() if is_draw else None,
        )
        self._canvas.set_text_mode(idx == _MODE_TEXT)
        cursors = {
            _MODE_REDACT: _get_icon_cursor("fa5s.eraser", 22, 22),
            _MODE_TEXT: Qt.CursorShape.IBeamCursor,
            _MODE_IMAGE: _get_icon_cursor("fa5s.image", 14, 14),
            _MODE_HIGHLIGHT: _get_icon_cursor("fa5s.highlighter", 14, 2, rotate=135),
            _MODE_NOTE: _get_icon_cursor("fa5s.sticky-note", 4, 4),
            _MODE_FORMS: Qt.CursorShape.ArrowCursor,
            _MODE_SIGNATURE: Qt.CursorShape.ArrowCursor,
            _MODE_SELECT: Qt.CursorShape.ArrowCursor,
        }
        if idx in cursors:
            self._canvas.setCursor(cursors[idx])

        if idx == _MODE_IMAGE:
            cur = self._img_drop.path()
            if not cur or not os.path.isfile(cur):
                self._pick_image()

    def _set_text_submode(self, mode: str):
        is_add = (mode == "add")
        if hasattr(self, "_btn_text_add"):
            self._btn_text_add.setChecked(is_add)
        if hasattr(self, "_btn_text_edit"):
            self._btn_text_edit.setChecked(not is_add)
        self._text_submode = mode
        self._update_text_submode_styles()
        if hasattr(self, "_text_hint"):
            if is_add:
                self._text_hint.setText("💡 Click anywhere on the page to insert new text exactly where you click.")
            else:
                self._text_hint.setText("💡 Click any text to edit or delete it. Click empty space to add text.")

    def _update_text_submode_styles(self):
        if not hasattr(self, "_btn_text_add") or not hasattr(self, "_btn_text_edit"):
            return
        is_add = getattr(self, "_text_submode", "edit") == "add"
        active_style = (
            f"background:#264F78; border:1px solid {ACCENT}; color:#FFFFFF; border-radius:4px; font-weight:600; padding:3px 8px;"
            if self._dark_mode else
            f"background:#D6E8FA; border:1px solid #70A7DB; color:{ACCENT}; border-radius:4px; font-weight:600; padding:3px 8px;"
        )
        inactive_style = (
            "background:#333333; border:1px solid #444444; color:#CCCCCC; border-radius:4px; padding:3px 8px;"
            if self._dark_mode else
            "background:#FFFFFF; border:1px solid #D1D5DB; color:#555555; border-radius:4px; padding:3px 8px;"
        )
        self._btn_text_add.setStyleSheet(active_style if is_add else inactive_style)
        self._btn_text_edit.setStyleSheet(inactive_style if is_add else active_style)

    def _on_text_format_changed(self):
        font = self._text_font.currentText()
        size = float(self._text_size.value())
        color = self._text_color.color_tuple()
        bold = self._btn_bold.isChecked()
        italic = self._btn_italic.isChecked()
        self._canvas.update_active_text_format(font, size, color, bold, italic)

    def _on_text_edit_started(self, fmt: dict):
        self._text_font.blockSignals(True)
        self._text_size.blockSignals(True)
        self._text_color.blockSignals(True)
        self._btn_bold.blockSignals(True)
        self._btn_italic.blockSignals(True)

        font_name = fmt.get("font", "Helvetica")
        idx = self._text_font.findText(font_name, Qt.MatchFlag.MatchContains)
        if idx >= 0:
            self._text_font.setCurrentIndex(idx)
        else:
            self._text_font.addItem(font_name)
            self._text_font.setCurrentIndex(self._text_font.count() - 1)

        self._text_size.setValue(max(4, int(round(fmt.get("size", 12)))))
        col = fmt.get("color", (0, 0, 0))
        self._text_color.set_color(col)
        self._btn_bold.setChecked(fmt.get("bold", False))
        self._btn_italic.setChecked(fmt.get("italic", False))

        self._text_font.blockSignals(False)
        self._text_size.blockSignals(False)
        self._text_color.blockSignals(False)
        self._btn_bold.blockSignals(False)
        self._btn_italic.blockSignals(False)

    def _delete_active_text(self):
        if self._canvas._inline_edit.isVisible():
            self._canvas._inline_edit.setText("")
            self._canvas._commit_inline()
        elif self._canvas._selected_overlay_idx >= 0:
            self._canvas.delete_selected_overlay()

    def _pick_pdf(self):
        p, _ = QFileDialog.getOpenFileName(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if p:
            self._load_pdf(p)

    def _load_pdf(self, p: str):
        if not p:
            return
        if not os.path.isfile(p):
            if os.path.isfile(p + ".pdf"):
                p = p + ".pdf"
            else:
                return
        try:
            probe = fitz.open(p)
            needs_pass = bool(probe.needs_pass)
            if needs_pass and self._pdf_password:
                winner = authenticate_fitz(probe, self._pdf_password)
                self._pdf_password = winner or ""
            probe.close()
        except Exception:
            needs_pass = False
        if needs_pass and not self._pdf_password:
            from app.utils import prompt_pdf_password
            ok, pwd = prompt_pdf_password(p, self)
            if not ok:
                return
            self._pdf_password = pwd
        elif not needs_pass:
            self._pdf_password = ""
        self._doc_path = p
        self._drop_in.blockSignals(True)
        self._drop_in.set_path(p)
        self._drop_in.blockSignals(False)
        if not self._drop_out.path():
            self._drop_out.set_path(os.path.splitext(p)[0] + "_edited.pdf")
        self._pending.clear()
        self._pending_list.clear()
        try:
            self._canvas.load(p, password=self._pdf_password)
        except ModuleNotFoundError as ex:
            QMessageBox.critical(self, t("msg.missing_dep"), t("msg.dep_pymupdf", ex=ex))
            return
        except Exception as ex:
            QMessageBox.critical(self, t("msg.error"), t("msg.pdf_open_error", ex=ex))
            return
        self._page_idx = 0
        n = self._canvas.page_count()
        self._lbl_info.setText(t("edit.status.pages", n=n))
        self._update_nav()
        QTimer.singleShot(100, lambda: self._load_existing_annotations() if isValid(self) else None)
        QTimer.singleShot(200, lambda: self._load_form_fields(p) if isValid(self) else None)

    def _load_existing_annotations(self):
        self._history.load_existing_annotations()

    def auto_load(self, path: str):
        if path and not self._drop_in.path():
            self._load_pdf(path)

    def _close_pdf(self):
        self._doc_path = None
        self._canvas.close_doc()
        self._canvas.set_overlays([])
        self._pending.clear()
        self._pending_list.clear()
        self._lbl_info.setText("")
        self._page_idx = 0
        self._update_nav()
        self._clear_pdf_password()

    def _clear_pdf_password(self) -> None:
        from app.utils import wipe_pdf_password
        wipe_pdf_password(self)

    def _pick_image(self):
        p, _ = QFileDialog.getOpenFileName(self, t("edit.image"), DESKTOP, t("file_filter.images"))
        if p:
            from app.utils import check_image_size
            ok, w, h = check_image_size(p)
            if not ok:
                QMessageBox.warning(
                    self, t("msg.warning"),
                    t("editor.image_too_large", width=w, height=h, megapix=w * h // 1_000_000)
                )
                return
            self._img_drop.blockSignals(True)
            self._img_drop.set_path(p)
            self._img_drop.blockSignals(False)

    def _cleanup_signature_temp(self):
        cleanup_signature_temp_file(self._signature_path)

    def _pick_signature(self):
        dlg = _SignatureDialog(self)
        if dlg.exec() == _SignatureDialog.DialogCode.Accepted:
            path = dlg.selected_signature_path()
            if path and os.path.isfile(path):
                self._cleanup_signature_temp()
                self._signature_path = path
                pix = load_signature_pixmap(path, max_size=(200, 50))
                if not pix.isNull():
                    self._sig_preview.setPixmap(pix)
                self._canvas.begin_signature_placement(path)
                self._status(t("edit.signature.place_hint"))

    def _clear_signature(self):
        from PySide6.QtGui import QPixmap
        self._cleanup_signature_temp()
        self._signature_path = None
        self._sig_preview.setText(t("edit.signature.none"))
        self._sig_preview.setPixmap(QPixmap())
        self._canvas.cancel_signature_placement()
        from app.i18n import clear_saved_signature
        clear_saved_signature()

    def _load_form_fields(self, path: str):
        load_form_fields(self, path)

    def _on_draw_color_changed(self, _color_tuple):
        self._canvas.set_draw_mode(
            self._mode_idx == _MODE_DRAW,
            color=self._draw_color_cb.color_tuple(),
            width=self._draw_width_slider.value(),
        )

    def _on_draw_width_changed(self, v: int):
        self._draw_width_lbl.setText(str(v))
        self._canvas.set_draw_mode(
            self._mode_idx == _MODE_DRAW,
            color=self._draw_color_cb.color_tuple(),
            width=v,
        )

    def _on_stroke(self, page_idx: int, pdf_points):
        self._page_idx = page_idx
        self._update_nav()
        self._add({
            "type": "draw",
            "page": page_idx,
            "points": pdf_points,
            "color": self._draw_color_cb.color_tuple(),
            "width": self._draw_width_slider.value(),
        })

    def _on_rect(self, page_idx: int, pdf_rect):
        self._page_idx = page_idx
        self._update_nav()
        mode = self._mode_idx
        if mode == _MODE_SELECT:
            doc = self._canvas._doc
            if not doc:
                return
            raw_text = doc[page_idx].get_text("text", clip=pdf_rect)
            text = raw_text.strip() if isinstance(raw_text, str) else str(raw_text).strip()
            self._sel_result.setPlainText(text)
            if text:
                clipboard = QApplication.clipboard()
                if clipboard:
                    clipboard.setText(text)
                self._status(t("edit.status.copied_clipboard", n=len(text)))
            else:
                self._status(t("edit.status.no_text_in_selection"))
            return

        if mode == _MODE_TEXT:
            insert_pt = fitz.Point(pdf_rect.x0, pdf_rect.y0)
            size = float(self._text_size.value())
            color = self._text_color.color_tuple()
            font = self._text_font.currentText()
            bold = self._btn_bold.isChecked()
            italic = self._btn_italic.isChecked()
            self._canvas.begin_inline_text_insert(page_idx, insert_pt, size, color, font)
            self._canvas.update_active_text_format(font, size, color, bold, italic)
            return

        if mode == _MODE_NOTE:
            center = fitz.Point((pdf_rect.x0 + pdf_rect.x1) / 2, (pdf_rect.y0 + pdf_rect.y1) / 2)
            self._on_point(page_idx, center)
            return
        if mode == _MODE_REDACT:
            self._add({"type": "redact", "page": self._page_idx, "rect": pdf_rect, "fill": self._red_color.color_tuple()})
        elif mode == _MODE_IMAGE:
            img = self._img_drop.path()
            if not img or not os.path.isfile(img):
                self._pick_image()
                img = self._img_drop.path()
                if not img or not os.path.isfile(img):
                    return
            self._add({"type": "image", "page": self._page_idx, "rect": pdf_rect, "path": img})
        elif mode == _MODE_SIGNATURE:
            sig = self._signature_path
            if not sig or not os.path.isfile(sig):
                self._pick_signature()
                sig = self._signature_path
                if not sig or not os.path.isfile(sig):
                    return
            self._add({"type": "signature", "page": self._page_idx, "rect": pdf_rect, "path": sig})
        elif mode == _MODE_HIGHLIGHT:
            self._add({"type": "highlight", "page": self._page_idx, "rect": pdf_rect, "color": self._hi_color.color_tuple()})

    def _on_point(self, page_idx: int, pdf_pt):
        self._page_idx = page_idx
        self._update_nav()
        doc = self._canvas._doc
        if doc:
            page = doc[page_idx]
            for annot in page.annots() or []:
                annot_type = getattr(annot, "type", (None, None))
                if (isinstance(annot_type, (tuple, list)) and len(annot_type) >= 2 and (annot_type[0] == _PDF_ANNOT_TEXT or annot_type[1] == "Text")) or annot_type == _PDF_ANNOT_TEXT:
                    ar = annot.rect
                    expanded = fitz.Rect(ar.x0 - 10, ar.y0 - 10, ar.x1 + 10, ar.y1 + 10)
                    if expanded.contains(fitz.Point(pdf_pt.x, pdf_pt.y)):
                        info = getattr(annot, "info", None) or {}
                        txt = info.get("content", "") if isinstance(info, dict) else ""
                        if txt:
                            QMessageBox.information(self, t("edit.note_popup"), txt)
                            return
        mode = self._mode_idx
        if mode == _MODE_TEXT:
            submode = getattr(self, "_text_submode", "edit")
            # In edit mode (or default), if user clicks on existing text, edit it in-place
            if submode != "add":
                hit = self._canvas.get_span_at(page_idx, pdf_pt, max_dist=6.0)
                if hit:
                    self._canvas.begin_inline_text_edit(hit, page_idx)
                    return

            # If in 'add' mode, or clicking in blank space, insert new text where clicked:
            size = float(self._text_size.value())
            color = self._text_color.color_tuple()
            font = self._text_font.currentText()
            bold = self._btn_bold.isChecked()
            italic = self._btn_italic.isChecked()
            self._canvas.begin_inline_text_insert(page_idx, pdf_pt, size, color, font)
            self._canvas.update_active_text_format(font, size, color, bold, italic)
        elif mode == _MODE_NOTE:
            dlg = _NoteDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            txt = dlg.edit.toPlainText().strip()
            if not txt:
                return
            self._add({"type": "note", "page": self._page_idx, "point": pdf_pt, "text": txt})

    def _on_text_edit_committed(self, page_idx: int, edit: dict):
        self._add(edit)

    def _on_signature_added(self, page_idx: int, rect, path: str):
        self._add({"type": "signature", "page": page_idx, "rect": rect, "path": path})

    def _on_overlay_deleted(self, idx: int, edit: dict):
        self._history.handle_overlay_deleted(idx, edit)

    def _on_note_deleted(self, overlay: dict):
        self._history.handle_note_deleted(overlay)

    def _add(self, edit: dict, *, _from_redo: bool = False):
        self._history.add(edit, _from_redo=_from_redo)

    def _undo(self):
        self._history.undo()

    def _redo(self):
        self._history.redo()

    def _clear_pending(self):
        self._history.clear()

    def _prompt_encryption_choice(self) -> str | None:
        return prompt_encryption_choice(self)

    @staticmethod
    def _fitz_permissions_of(doc) -> int:
        return get_fitz_permissions(doc)

    def _apply_forms(self, out: str):
        apply_form_fields_and_save(self, out)

    def _run(self):
        if not self._doc_path or not os.path.isfile(self._doc_path):
            QMessageBox.warning(self, t("msg.warning"), t("msg.open_pdf_first"))
            return
        out = self._drop_out.path()
        if not out:
            base, ext = os.path.splitext(os.path.basename(self._doc_path))
            suggested = os.path.join(os.path.dirname(self._doc_path), base + "_edited" + ext)
            out, _ = QFileDialog.getSaveFileName(self, t("btn.choose"), suggested, t("file_filter.pdf"))
            if not out:
                return
            self._drop_out.set_path(out)

        if self._mode_idx == _MODE_FORMS:
            if self._user_pending:
                reply = QMessageBox.question(
                    self, t("msg.warning"),
                    t("editor.forms.has_pending"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            self._apply_forms(out)
            return

        if not self._user_pending:
            QMessageBox.warning(self, t("msg.warning"), t("msg.no_pending"))
            return

        apply_visual_edits_and_save(self, out)