# app/editor/dialogs.py

"""PDFApps – editor dialogs: password, text edit, text insert, note, signature."""

import os
import tempfile

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QImage, QPainter, QPen, QColor, QFont, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QTextEdit, QTabWidget, QWidget,
    QCheckBox, QFileDialog, QMessageBox, QListWidget,
    QListWidgetItem, QAbstractItemView,
)
import qtawesome as qta

from app.constants import (
    ACCENT, BORDER, TEXT_PRI, TEXT_SEC, BG_INNER,
    _LO, _LP, _LQ, _LN,
)
from app.i18n import (
    t, get_saved_signatures, save_new_signature, delete_saved_signature,
)
from app.utils import error_color, format_size_localized
from app.widgets import FocusComboBox, FocusSpinBox


def _theme_colors(parent):
    """Return (pri, sec, bg, border) based on parent's dark mode."""
    dark = parent._dark_mode if parent and hasattr(parent, '_dark_mode') else True
    if dark:
        return TEXT_PRI, TEXT_SEC, BG_INNER, BORDER
    return _LP, _LQ, _LN, _LO


def load_signature_pixmap(path: str, max_size: tuple[int, int] = (240, 80)) -> QPixmap:
    """Load a signature from PNG or SVG with transparent background into a scaled QPixmap."""
    if not path or not os.path.isfile(path):
        return QPixmap()
    if path.lower().endswith((".svg", ".svgz")):
        from PySide6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(path)
        if renderer.isValid():
            ds = renderer.defaultSize()
            dw = ds.width() if ds.width() > 0 else 240
            dh = ds.height() if ds.height() > 0 else 80
            scale = min(max_size[0] / dw, max_size[1] / dh)
            tw = max(1, int(dw * scale))
            th = max(1, int(dh * scale))
            pix = QPixmap(tw, th)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            renderer.render(p)
            p.end()
            return pix
    pix = QPixmap(path)
    if not pix.isNull():
        return pix.scaled(
            max_size[0], max_size[1],
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return QPixmap()


class _PdfPasswordDialog(QDialog):
    """Styled dialog to enter the password of a protected PDF."""
    def __init__(self, filename: str, wrong: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("dialog.password_title"))
        self.setModal(True)
        self.setMinimumWidth(400)
        pri, sec, bg, brd = _theme_colors(parent)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 20)
        v.setSpacing(16)

        top = QHBoxLayout(); top.setSpacing(14)
        ico = QLabel()
        dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        if dpr <= 0:
            dpr = 1.0
        size = int(40 * dpr)
        _pix = qta.icon("fa5s.lock", color=ACCENT).pixmap(size, size)
        _pix.setDevicePixelRatio(dpr)
        ico.setPixmap(_pix)
        ico.setFixedSize(40, 40)
        top.addWidget(ico)
        title_col = QVBoxLayout(); title_col.setSpacing(2)
        lbl_title = QLabel(t("dialog.password_header"))
        lbl_title.setStyleSheet(f"font-size:13pt; font-weight:700; color:{pri};")
        lbl_file  = QLabel(filename)
        lbl_file.setStyleSheet(f"font-size:9pt; color:{sec};")
        lbl_file.setWordWrap(True)
        title_col.addWidget(lbl_title); title_col.addWidget(lbl_file)
        top.addLayout(title_col, 1)
        v.addLayout(top)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{brd};"); v.addWidget(sep)

        lbl_pwd = QLabel(t("dialog.password_label"))
        lbl_pwd.setStyleSheet(f"color:{sec}; font-size:10pt;")
        v.addWidget(lbl_pwd)
        self._edit = QLineEdit()
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit.setPlaceholderText(t("dialog.password_hint"))
        v.addWidget(self._edit)

        self._warn = QLabel(t("dialog.password_wrong"))
        self._warn.setStyleSheet(f"color:{error_color()}; font-size:9pt;")
        self._warn.setVisible(wrong)
        v.addWidget(self._warn)

        btns = QHBoxLayout(); btns.setSpacing(8)
        btns.addStretch()
        ca = QPushButton(t("btn.cancel")); ca.setFixedHeight(36)
        ca.clicked.connect(self.reject)
        ok = QPushButton(t("btn.open")); ok.setObjectName("btn_primary")
        ok.setFixedHeight(36); ok.clicked.connect(self.accept)
        self._edit.returnPressed.connect(self.accept)
        btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)

        self._edit.setFocus()
        self.setTabOrder(self._edit, ok)
        self.setTabOrder(ok, ca)

    def password(self) -> str:
        return self._edit.text()


class _TextEditDialog(QDialog):
    """Dialog to edit existing text in the PDF (pre-filled with detected text)."""
    def __init__(self, old_text: str, font_size: float, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("dialog.edit_text_title")); self.setModal(True)
        self.setMinimumWidth(420)
        pri, sec, bg, brd = _theme_colors(parent)
        v = QVBoxLayout(self); v.setContentsMargins(20, 20, 20, 16); v.setSpacing(10)

        lbl_orig = QLabel(t("dialog.edit_text_detected",
                              size=format_size_localized(font_size)))
        lbl_orig.setStyleSheet(f"color:{sec}; font-size:10pt;")
        v.addWidget(lbl_orig)

        orig_box = QLabel(old_text or t("dialog.edit_text_notext"))
        orig_box.setWordWrap(True)
        orig_box.setStyleSheet(
            f"color:{sec}; font-size:9pt; padding:6px 8px;"
            f"background:{bg}; border:1px solid {brd}; border-radius:4px;")
        v.addWidget(orig_box)

        lbl_new = QLabel(t("dialog.edit_text_new"))
        lbl_new.setStyleSheet(f"color:{pri}; font-size:10pt;")
        v.addWidget(lbl_new)

        self._edit = QLineEdit()
        safe_text = (old_text or "").replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        self._edit.setText(safe_text)
        self._edit.returnPressed.connect(self.accept)
        v.addWidget(self._edit)

        btns = QHBoxLayout(); btns.setSpacing(8); btns.addStretch()
        ca = QPushButton(t("btn.cancel")); ca.setFixedHeight(34); ca.clicked.connect(self.reject)
        ok = QPushButton(t("btn.apply")); ok.setObjectName("btn_primary")
        ok.setFixedHeight(34); ok.clicked.connect(self.accept)
        btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)

    def new_text(self) -> str:
        return self._edit.text()


class _TextDialog(QDialog):
    """Popup to insert text when clicking on the canvas."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(t("dialog.insert_title")); self.setModal(True)
        v = QVBoxLayout(self)
        self.edit = QLineEdit(); self.edit.setPlaceholderText(t("dialog.insert_hint"))
        v.addWidget(self.edit)
        row = QHBoxLayout()
        row.addWidget(QLabel(t("dialog.insert_size")))
        self.font_size = FocusSpinBox(); self.font_size.setMinimum(4); self.font_size.setMaximum(144); self.font_size.setValue(12)
        row.addWidget(self.font_size); row.addSpacing(12)
        row.addWidget(QLabel(t("dialog.insert_color")))
        from app.widgets import ColorPickerButton
        self.color = ColorPickerButton((0, 0, 0))
        row.addWidget(self.color); row.addStretch()
        v.addLayout(row)
        btns = QHBoxLayout()
        ok = QPushButton(t("btn.ok")); ok.setObjectName("btn_primary"); ok.clicked.connect(self.accept)
        ca = QPushButton(t("btn.cancel")); ca.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)
        self.setMinimumWidth(360)

    def color_tuple(self):
        return self.color.color_tuple()


class _NoteDialog(QDialog):
    """Popup to write a comment."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(t("dialog.note_title")); self.setModal(True)
        self.setMinimumWidth(360)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(t("dialog.note_label")))
        self.edit = QTextEdit()
        self.edit.setPlaceholderText(t("dialog.note_hint"))
        self.edit.setMinimumHeight(90)
        v.addWidget(self.edit)
        btns = QHBoxLayout()
        ok = QPushButton(t("btn.ok")); ok.setObjectName("btn_primary"); ok.clicked.connect(self.accept)
        ca = QPushButton(t("btn.cancel")); ca.clicked.connect(self.reject)
        btns.addStretch(); btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)


class _SignatureCanvas(QWidget):
    """Freehand drawing canvas for signatures with smooth transparent background."""

    def __init__(self):
        super().__init__()
        self._strokes = []
        self._current = []
        self.setMinimumSize(420, 160)
        self.setStyleSheet("background: white; border: 1.5px dashed #666; border-radius: 6px;")
        self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._current = [e.position().toPoint()]

    def mouseMoveEvent(self, e):
        if self._current:
            self._current.append(e.position().toPoint())
            self.update()

    def mouseReleaseEvent(self, e):
        if self._current:
            self._strokes.append(self._current)
            self._current = []
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        pen = QPen(QColor("#111827"), 2.5, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        for stroke in self._strokes + ([self._current] if self._current else []):
            if len(stroke) < 2:
                continue
            path = QPainterPath(stroke[0].toPointF())
            for pt in stroke[1:]:
                path.lineTo(pt.toPointF())
            p.drawPath(path)
        p.end()

    def clear(self):
        self._strokes.clear()
        self._current.clear()
        self.update()

    def is_empty(self):
        return not self._strokes and len(self._current) < 2

    def _all_strokes(self):
        if self._current and len(self._current) >= 2:
            return self._strokes + [self._current]
        return list(self._strokes)

    def to_image(self) -> QImage | None:
        if self.is_empty():
            return None
        strokes = self._all_strokes()
        all_pts = [pt for s in strokes for pt in s]
        if not all_pts:
            return None
        xs = [p.x() for p in all_pts]
        ys = [p.y() for p in all_pts]
        pad = 8
        x0, y0 = max(0, min(xs) - pad), max(0, min(ys) - pad)
        x1, y1 = min(self.width(), max(xs) + pad), min(self.height(), max(ys) + pad)
        w, h = max(1, x1 - x0), max(1, y1 - y0)

        img = QImage(w * 2, h * 2, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(2, 2)
        p.translate(-x0, -y0)
        pen = QPen(QColor("#111827"), 2.5, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        for stroke in strokes:
            if len(stroke) < 2:
                continue
            path = QPainterPath(stroke[0].toPointF())
            for pt in stroke[1:]:
                path.lineTo(pt.toPointF())
            p.drawPath(path)
        p.end()
        return img


class _SignatureDialog(QDialog):
    """Dialog to select from saved signatures (PNG/SVG) or create/import a new one with transparent background."""

    _FONTS = ["Segoe Script", "Brush Script MT", "Freestyle Script",
              "Comic Sans MS", "Lucida Handwriting"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("edit.mode.signature"))
        self.setModal(True)
        self.setMinimumWidth(540)
        self.setMinimumHeight(440)
        self._result_path = None
        pri, sec, bg, brd = _theme_colors(parent)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 16)
        v.setSpacing(12)

        self._main_tabs = QTabWidget(self)
        v.addWidget(self._main_tabs)

        # ── Tab 1: Saved Signatures ──────────────────────────────────────
        self._saved_w = QWidget()
        sv_lay = QVBoxLayout(self._saved_w)
        sv_lay.setContentsMargins(0, 8, 0, 0)
        sv_lay.setSpacing(8)

        self._sig_list = QListWidget()
        self._sig_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._sig_list.setIconSize(QSize(160, 50))
        self._sig_list.setAlternatingRowColors(True)
        self._sig_list.itemDoubleClicked.connect(self._on_saved_item_double_clicked)
        self._sig_list.itemSelectionChanged.connect(self._on_saved_selection_changed)
        sv_lay.addWidget(self._sig_list, 1)

        sig_btns_row = QHBoxLayout()
        self._del_sig_btn = QPushButton(t("btn.delete"))
        self._del_sig_btn.setIcon(qta.icon("fa5s.trash-alt", color="#EF4444"))
        self._del_sig_btn.setEnabled(False)
        self._del_sig_btn.clicked.connect(self._delete_selected_saved_sig)
        sig_btns_row.addWidget(self._del_sig_btn)
        sig_btns_row.addStretch()
        sv_lay.addLayout(sig_btns_row)

        self._main_tabs.addTab(self._saved_w, t("edit.signature.saved_tab"))

        # ── Tab 2: Create / Import New Signature ─────────────────────────
        self._create_w = QWidget()
        cv_lay = QVBoxLayout(self._create_w)
        cv_lay.setContentsMargins(0, 8, 0, 0)
        cv_lay.setSpacing(8)

        sub_tabs = QTabWidget()
        cv_lay.addWidget(sub_tabs)

        # 1. Draw sub-tab
        draw_w = QWidget()
        dv = QVBoxLayout(draw_w); dv.setContentsMargins(0, 8, 0, 0)
        hint_d = QLabel(t("edit.signature.draw_hint"))
        hint_d.setStyleSheet(f"color:{sec}; font-size:11px;")
        dv.addWidget(hint_d)
        self._draw_canvas = _SignatureCanvas()
        dv.addWidget(self._draw_canvas)
        btn_clear = QPushButton(t("edit.signature.clear_canvas"))
        btn_clear.clicked.connect(self._draw_canvas.clear)
        dv.addWidget(btn_clear)
        sub_tabs.addTab(draw_w, t("edit.signature.draw"))

        # 2. Type sub-tab
        type_w = QWidget()
        tv = QVBoxLayout(type_w); tv.setContentsMargins(0, 8, 0, 0); tv.setSpacing(8)
        hint_t = QLabel(t("edit.signature.type_hint"))
        hint_t.setStyleSheet(f"color:{sec}; font-size:11px;")
        tv.addWidget(hint_t)
        self._type_input = QLineEdit()
        self._type_input.setPlaceholderText(t("edit.signature.type_hint"))
        self._type_input.textChanged.connect(self._update_type_preview)
        tv.addWidget(self._type_input)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel(t("edit.signature.font")))
        self._font_combo = FocusComboBox()
        from PySide6.QtGui import QFontDatabase
        available = QFontDatabase.families()
        for f in self._FONTS:
            if f in available:
                self._font_combo.addItem(f)
        if self._font_combo.count() == 0:
            self._font_combo.addItem(available[0] if available else "Sans Serif")
        self._font_combo.currentTextChanged.connect(self._update_type_preview)
        font_row.addWidget(self._font_combo, 1)
        tv.addLayout(font_row)

        self._type_preview = QLabel()
        self._type_preview.setMinimumHeight(64)
        self._type_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._type_preview.setStyleSheet("background: white; border: 1.5px dashed #888; border-radius: 6px;")
        tv.addWidget(self._type_preview)
        tv.addStretch()
        sub_tabs.addTab(type_w, t("edit.signature.type"))

        # 3. Import sub-tab (PNG & SVG with transparent background)
        imp_w = QWidget()
        iv = QVBoxLayout(imp_w); iv.setContentsMargins(0, 8, 0, 0); iv.setSpacing(8)
        self._imp_btn = QPushButton(t("edit.signature.import"))
        self._imp_btn.clicked.connect(self._pick_image)
        iv.addWidget(self._imp_btn)
        self._imp_preview = QLabel(t("edit.signature.none"))
        self._imp_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._imp_preview.setMinimumHeight(64)
        self._imp_preview.setStyleSheet("background: white; border: 1.5px dashed #888; border-radius: 6px;")
        iv.addWidget(self._imp_preview)
        iv.addStretch()
        self._imp_path = None
        sub_tabs.addTab(imp_w, t("edit.signature.import"))

        self._sub_tabs = sub_tabs

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(t("edit.signature.name_prompt")))
        self._sig_name_input = QLineEdit()
        self._sig_name_input.setPlaceholderText("My Signature")
        name_row.addWidget(self._sig_name_input, 1)
        cv_lay.addLayout(name_row)

        self._save_cb = QCheckBox(t("edit.signature.save_reuse"))
        self._save_cb.setChecked(True)
        cv_lay.addWidget(self._save_cb)

        self._main_tabs.addTab(self._create_w, t("edit.signature.new_tab"))

        # ── Dialog Buttons Row ───────────────────────────────────────────
        btns = QHBoxLayout(); btns.setSpacing(8); btns.addStretch()
        ca = QPushButton(t("btn.cancel")); ca.setFixedHeight(36)
        ca.clicked.connect(self.reject)
        ok = QPushButton(t("btn.ok")); ok.setObjectName("btn_primary")
        ok.setFixedHeight(36); ok.clicked.connect(self._on_accept)
        btns.addWidget(ca); btns.addWidget(ok)
        v.addLayout(btns)
        self._ok_btn = ok

        self._refresh_saved_list()

        # If saved signatures exist, focus saved list, otherwise switch to create tab
        if self._sig_list.count() > 0:
            self._main_tabs.setCurrentIndex(0)
            self._sig_list.setCurrentRow(0)
            self._sig_list.setFocus()
        else:
            self._main_tabs.setCurrentIndex(1)
            self._draw_canvas.setFocus()

    def _refresh_saved_list(self):
        self._sig_list.clear()
        saved = get_saved_signatures()
        for s in saved:
            path = s["path"]
            item = QListWidgetItem()
            pix = load_signature_pixmap(path, max_size=(160, 48))
            if not pix.isNull():
                item.setIcon(pix)
            label = f"{s['name']}  [{s['type']}]"
            item.setText(label)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setSizeHint(QSize(200, 56))
            self._sig_list.addItem(item)
        has_items = self._sig_list.count() > 0
        self._del_sig_btn.setEnabled(has_items)

    def _on_saved_selection_changed(self):
        sel = bool(self._sig_list.selectedItems())
        self._del_sig_btn.setEnabled(sel)

    def _on_saved_item_double_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and os.path.isfile(path):
            self._result_path = path
            self.accept()

    def _delete_selected_saved_sig(self):
        item = self._sig_list.currentItem()
        if not item:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, t("msg.confirm"),
            t("edit.signature.delete_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_saved_signature(path)
            self._refresh_saved_list()
            if self._sig_list.count() > 0:
                self._sig_list.setCurrentRow(0)

    def _update_type_preview(self):
        text = self._type_input.text().strip()
        if not text:
            self._type_preview.setPixmap(QPixmap())
            return
        font = QFont(self._font_combo.currentText(), 32)
        img = QImage(460, 90, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(font)
        p.setPen(QColor("#111827"))
        p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, text)
        p.end()
        pix = QPixmap.fromImage(img)
        self._type_preview.setPixmap(pix.scaled(
            self._type_preview.width(), 64,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _pick_image(self):
        p, _ = QFileDialog.getOpenFileName(
            self, t("edit.signature.import"), "",
            t("edit.signature.filter"))
        if p and os.path.isfile(p):
            self._imp_path = p
            pix = load_signature_pixmap(p, max_size=(400, 64))
            if not pix.isNull():
                self._imp_preview.setPixmap(pix)
                if not self._sig_name_input.text().strip():
                    stem = os.path.splitext(os.path.basename(p))[0]
                    self._sig_name_input.setText(stem.title())

    def _on_accept(self):
        # 1. If user selected an existing signature from "My Signatures"
        if self._main_tabs.currentIndex() == 0:
            item = self._sig_list.currentItem()
            if not item and self._sig_list.count() > 0:
                item = self._sig_list.item(0)
            if item:
                path = item.data(Qt.ItemDataRole.UserRole)
                if path and os.path.isfile(path):
                    self._result_path = path
                    self.accept()
                    return
            QMessageBox.warning(self, t("msg.warning"), t("edit.signature.no_saved"))
            return

        # 2. If user is in "Create / Import"
        sub_tab = self._sub_tabs.currentIndex()

        if sub_tab == 0:
            if self._draw_canvas.is_empty():
                QMessageBox.warning(self, t("msg.warning"), t("editor.signature.empty_draw"))
                return
            img = self._draw_canvas.to_image()
            if img is None:
                return
            fd, tmp = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            img.save(tmp, b"PNG")

        elif sub_tab == 1:
            text = self._type_input.text().strip()
            if not text:
                QMessageBox.warning(self, t("msg.warning"), t("editor.signature.empty_type"))
                return
            font = QFont(self._font_combo.currentText(), 48)
            from PySide6.QtGui import QFontMetrics
            fm = QFontMetrics(font)
            br = fm.boundingRect(text)
            pad = 12
            img = QImage(br.width() + pad * 2, br.height() + pad * 2,
                         QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setFont(font)
            p.setPen(QColor("#111827"))
            p.drawText(pad - br.x(), pad - br.y(), text)
            p.end()

            fd, tmp = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            img.save(tmp, b"PNG")

        elif sub_tab == 2:
            if not self._imp_path or not os.path.isfile(self._imp_path):
                QMessageBox.warning(self, t("msg.warning"), t("editor.signature.empty_import"))
                return
            tmp = self._imp_path

        name = self._sig_name_input.text().strip()
        if self._save_cb.isChecked():
            final_path = save_new_signature(tmp, display_name=name)
        else:
            final_path = tmp

        self._result_path = final_path
        self.accept()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._on_accept()
            e.accept()
            return
        super().keyPressEvent(e)

    def result_path(self) -> str | None:
        return self._result_path

    def selected_signature_path(self) -> str | None:
        return self._result_path