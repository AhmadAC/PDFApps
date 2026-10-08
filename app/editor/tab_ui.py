

# app/editor/tab_ui.py
"""PDFApps – tab_ui: UI builder and styling manager for TabEditar."""

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QStackedWidget, QGroupBox,
    QSizePolicy, QListWidget, QTableWidget, QHeaderView,
    QTextEdit, QApplication, QSlider, QGridLayout,
)
import qtawesome as qta

from app.constants import ACCENT, TEXT_PRI, TEXT_SEC, DESKTOP, BG_INNER, _LN, _LP, _LQ
from app.utils import ToolHeader, ActionBar, info_lbl
from app.i18n import t, get_saved_signature
from app.widgets import DropFileEdit, ColorPickerButton, FocusSpinBox, FocusComboBox
from app.editor.canvas import PdfEditCanvas
from app.editor.dialogs import load_signature_pixmap
from app.editor.tab_constants import (
    _MODE_KEYS, _MODE_TEXT,
)


def setup_editor_ui(tab) -> None:
    """Build and attach all UI components to the TabEditar facade instance."""
    tab.setObjectName("content_area")
    root = QVBoxLayout(tab)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    body = QWidget()
    body_h = QHBoxLayout(body)
    body_h.setContentsMargins(0, 0, 0, 0)
    body_h.setSpacing(0)

    # Canvas Scroll Area (Left window - full height)
    tab._canvas = PdfEditCanvas()
    canvas_scroll = QScrollArea()
    canvas_scroll.setFrameShape(QFrame.Shape.NoFrame)
    canvas_scroll.setWidgetResizable(False)
    canvas_scroll.setStyleSheet(f"QScrollArea {{ background: {BG_INNER}; }}")
    canvas_scroll.setWidget(tab._canvas)
    canvas_scroll.setMinimumWidth(320)
    canvas_scroll.viewport().installEventFilter(tab)
    canvas_scroll.verticalScrollBar().valueChanged.connect(
        lambda _: tab._canvas.on_scroll()
    )
    tab._canvas_scroll = canvas_scroll
    body_h.addWidget(canvas_scroll, 1)

    # Control Sidebar (Right window)
    ctrl_inner = QWidget()
    ctrl_inner.setObjectName("scroll_inner")
    ctrl_inner.setFixedWidth(380)
    cv = QVBoxLayout(ctrl_inner)
    cv.setContentsMargins(10, 10, 10, 10)
    cv.setSpacing(8)

    # Banner header placed exclusively inside the right sidebar
    cv.addWidget(ToolHeader("fa5s.edit", t("edit.title"), t("edit.subtitle")))

    # 1. PDF File Group
    tab._grp_file = QGroupBox(t("edit.pdf_file"))
    gf = QVBoxLayout(tab._grp_file)
    gf.setSpacing(4)
    tab._drop_in = DropFileEdit()
    try:
        tab._drop_in.btn.clicked.disconnect()
    except RuntimeError:
        pass
    tab._drop_in.btn.clicked.connect(tab._pick_pdf)
    tab._drop_in.path_changed.connect(tab._load_pdf)
    tab._drop_in._clr.clicked.connect(tab._close_pdf)
    tab._lbl_info = info_lbl()
    gf.addWidget(tab._drop_in)
    gf.addWidget(tab._lbl_info)
    cv.addWidget(tab._grp_file)

    # 2. Page Navigation Group
    grp_page = QGroupBox(t("edit.page"))
    gp = QHBoxLayout(grp_page)
    gp.setSpacing(6)
    tab._btn_prev = QPushButton()
    tab._btn_prev.setIcon(qta.icon("fa5s.chevron-left", color=TEXT_PRI))
    tab._btn_prev.setFixedSize(28, 28)
    tab._btn_prev.setObjectName("viewer_nav_btn")
    tab._btn_prev.setToolTip(t("nav.prev_page"))
    tab._btn_prev.setAccessibleName(t("nav.prev_page"))
    tab._btn_prev.clicked.connect(tab._prev_page)

    tab._lbl_page = QLabel("---")
    tab._lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)

    tab._btn_next = QPushButton()
    tab._btn_next.setIcon(qta.icon("fa5s.chevron-right", color=TEXT_PRI))
    tab._btn_next.setFixedSize(28, 28)
    tab._btn_next.setObjectName("viewer_nav_btn")
    tab._btn_next.setToolTip(t("nav.next_page"))
    tab._btn_next.setAccessibleName(t("nav.next_page"))
    tab._btn_next.clicked.connect(tab._next_page)

    gp.addWidget(tab._btn_prev)
    gp.addWidget(tab._lbl_page, 1)
    gp.addWidget(tab._btn_next)
    cv.addWidget(grp_page)

    # 3. Edit Modes Grid
    grp_mode = QGroupBox(t("edit.mode"))
    gm = QGridLayout(grp_mode)
    gm.setSpacing(4)
    tab._mode_btns = []
    tab._mode_btn_idx = {}
    cols = 5
    for i, (label, icon_name) in enumerate(tab._MODE_DEFS):
        btn = QPushButton()
        btn.setIcon(qta.icon(icon_name, color=TEXT_SEC))
        btn.setIconSize(QSize(18, 18))
        btn.setToolTip(label)
        btn.setCheckable(True)
        btn.setFixedSize(36, 36)
        tab._mode_btn_idx[id(btn)] = i
        btn.clicked.connect(lambda checked, b=btn: tab._on_mode_btn(b))
        tab._mode_btns.append(btn)
        gm.addWidget(btn, i // cols, i % cols)
    cv.addWidget(grp_mode)

    # 4. Mode Options Stack
    grp_opts = QGroupBox(t("edit.options"))
    go = QVBoxLayout(grp_opts)
    go.setContentsMargins(6, 6, 6, 6)
    tab._opt_stack = QStackedWidget()
    tab._hint_labels = []

    _build_mode_options(tab)
    go.addWidget(tab._opt_stack)
    cv.addWidget(grp_opts)

    # 5. Pending Edits Group
    grp_pend = QGroupBox(t("edit.pending"))
    gpe = QVBoxLayout(grp_pend)
    gpe.setSpacing(4)
    tab._pending_list = QListWidget()
    tab._pending_list.setMaximumHeight(110)
    gpe.addWidget(tab._pending_list)
    pend_btns = QHBoxLayout()
    pend_btns.setSpacing(4)
    tab._btn_undo = QPushButton()
    tab._btn_undo.setIcon(qta.icon("fa5s.undo", color=TEXT_PRI))
    tab._btn_undo.setToolTip(t("edit.undo_tip"))
    tab._btn_undo.setAccessibleName(t("edit.undo_tip"))
    tab._btn_undo.setFixedSize(28, 28)
    tab._btn_undo.clicked.connect(tab._undo)

    tab._btn_redo = QPushButton()
    tab._btn_redo.setIcon(qta.icon("fa5s.redo", color=TEXT_PRI))
    tab._btn_redo.setToolTip(t("edit.redo_tip"))
    tab._btn_redo.setAccessibleName(t("edit.redo_tip"))
    tab._btn_redo.setFixedSize(28, 28)
    tab._btn_redo.clicked.connect(tab._redo)

    btn_clear = QPushButton(t("btn.clear_all"))
    btn_clear.clicked.connect(tab._clear_pending)
    pend_btns.addWidget(tab._btn_undo)
    pend_btns.addWidget(tab._btn_redo)
    pend_btns.addWidget(btn_clear)
    pend_btns.addStretch()
    gpe.addLayout(pend_btns)
    cv.addWidget(grp_pend)

    # 6. Save Group
    tab._grp_save = QGroupBox(t("edit.save_to"))
    gs = QVBoxLayout(tab._grp_save)
    tab._drop_out = DropFileEdit("output_edited.pdf", save=True, default_name="output_edited.pdf")
    gs.addWidget(tab._drop_out)
    cv.addWidget(tab._grp_save)
    cv.addStretch()

    # Sidebar Scroll Container
    ctrl_scroll = QScrollArea()
    ctrl_scroll.setWidgetResizable(True)
    ctrl_scroll.setFrameShape(QFrame.Shape.NoFrame)
    ctrl_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    ctrl_scroll.setWidget(ctrl_inner)
    ctrl_scroll.setFixedWidth(400)
    ctrl_scroll.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
    body_h.addWidget(ctrl_scroll)
    tab._ctrl_scroll = ctrl_scroll

    root.addWidget(body, 1)
    tab._action_bar, _ = ActionBar(t("btn.apply_save"), tab._run)
    root.addWidget(tab._action_bar)


def _build_mode_options(tab) -> None:
    """Build individual option sub-panels for each editing mode."""
    # 0 - Redact
    w0 = QWidget(); v0 = QVBoxLayout(w0); v0.setContentsMargins(0, 4, 0, 0); v0.setSpacing(4)
    v0.addWidget(QLabel(t("edit.color")))
    tab._red_color = ColorPickerButton((0, 0, 0))
    v0.addWidget(tab._red_color)
    hint0 = QLabel(t("edit.hint.redact")); hint0.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
    tab._hint_labels.append(hint0)
    v0.addWidget(hint0); v0.addStretch()
    tab._opt_stack.addWidget(w0)

    # 1 - Text & Typography Options
    w1 = QWidget(); v1 = QVBoxLayout(w1); v1.setContentsMargins(0, 4, 0, 0); v1.setSpacing(6)

    mode_btn_row = QHBoxLayout()
    mode_btn_row.setSpacing(4)
    tab._btn_text_add = QPushButton("➕ " + t("tool.text.add_mode", default="Add Text"))
    tab._btn_text_add.setCheckable(True)
    tab._btn_text_add.setChecked(True)
    tab._btn_text_add.setFixedHeight(28)
    tab._btn_text_add.setCursor(Qt.CursorShape.PointingHandCursor)

    tab._btn_text_edit = QPushButton("✏ " + t("tool.text.edit_mode", default="Edit Text"))
    tab._btn_text_edit.setCheckable(True)
    tab._btn_text_edit.setChecked(False)
    tab._btn_text_edit.setFixedHeight(28)
    tab._btn_text_edit.setCursor(Qt.CursorShape.PointingHandCursor)

    tab._btn_text_add.clicked.connect(lambda: tab._set_text_submode("add"))
    tab._btn_text_edit.clicked.connect(lambda: tab._set_text_submode("edit"))

    mode_btn_row.addWidget(tab._btn_text_add)
    mode_btn_row.addWidget(tab._btn_text_edit)
    v1.addLayout(mode_btn_row)

    font_row = QHBoxLayout()
    font_row.addWidget(QLabel("Font:"))
    tab._text_font = FocusComboBox()
    tab._text_font.addItems([
        "Helvetica", "Arial", "Times New Roman", "Courier New",
        "Segoe UI", "Georgia", "Calibri", "Verdana", "Trebuchet MS"
    ])
    tab._text_font.currentTextChanged.connect(tab._on_text_format_changed)
    font_row.addWidget(tab._text_font, 1)
    v1.addLayout(font_row)

    row1 = QHBoxLayout(); row1.setSpacing(8)
    row1.addWidget(QLabel(t("dialog.insert_size")))
    tab._text_size = FocusSpinBox()
    tab._text_size.setMinimum(4); tab._text_size.setMaximum(144); tab._text_size.setValue(12)
    tab._text_size.setSuffix(" pt")
    tab._text_size.valueChanged.connect(tab._on_text_format_changed)
    row1.addWidget(tab._text_size)

    tab._btn_bold = QPushButton(); tab._btn_bold.setIcon(qta.icon("fa5s.bold", color=TEXT_PRI))
    tab._btn_bold.setCheckable(True); tab._btn_bold.setFixedSize(32, 32); tab._btn_bold.setToolTip("Bold (Ctrl+B)")
    tab._btn_bold.toggled.connect(tab._on_text_format_changed)
    row1.addWidget(tab._btn_bold)

    tab._btn_italic = QPushButton(); tab._btn_italic.setIcon(qta.icon("fa5s.italic", color=TEXT_PRI))
    tab._btn_italic.setCheckable(True); tab._btn_italic.setFixedSize(32, 32); tab._btn_italic.setToolTip("Italic (Ctrl+I)")
    tab._btn_italic.toggled.connect(tab._on_text_format_changed)
    row1.addWidget(tab._btn_italic)
    v1.addLayout(row1)

    row_col = QHBoxLayout()
    row_col.addWidget(QLabel(t("dialog.insert_color")))
    tab._text_color = ColorPickerButton((0, 0, 0))
    tab._text_color.color_changed.connect(lambda c: tab._on_text_format_changed())
    row_col.addWidget(tab._text_color); row_col.addStretch()

    tab._btn_del_text = QPushButton(t("btn.delete"))
    tab._btn_del_text.setIcon(qta.icon("fa5s.trash-alt", color="#EF4444"))
    tab._btn_del_text.setCursor(Qt.CursorShape.PointingHandCursor)
    tab._btn_del_text.clicked.connect(tab._delete_active_text)
    row_col.addWidget(tab._btn_del_text)
    v1.addLayout(row_col)

    tab._text_hint = QLabel("💡 Click anywhere on the page to insert new text exactly where you click.")
    tab._text_hint.setWordWrap(True)
    tab._text_hint.setStyleSheet(f"color:{ACCENT}; font-size:11px;")
    v1.addWidget(tab._text_hint); v1.addStretch()
    tab._opt_stack.addWidget(w1)

    # 2 - Image
    w2 = QWidget(); v2 = QVBoxLayout(w2); v2.setContentsMargins(0, 4, 0, 0); v2.setSpacing(4)
    v2.addWidget(QLabel(t("edit.image")))
    tab._img_drop = DropFileEdit(placeholder=t("edit.image_hint"), filters=t("file_filter.images"))
    try: tab._img_drop.btn.clicked.disconnect()
    except RuntimeError: pass
    tab._img_drop.btn.clicked.connect(tab._pick_image)
    v2.addWidget(tab._img_drop)
    hint2 = QLabel(t("edit.hint.image")); hint2.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
    tab._hint_labels.append(hint2); v2.addWidget(hint2); v2.addStretch()
    tab._opt_stack.addWidget(w2)

    # 3 - Highlight
    w3 = QWidget(); v3 = QVBoxLayout(w3); v3.setContentsMargins(0, 4, 0, 0); v3.setSpacing(4)
    v3.addWidget(QLabel(t("edit.color")))
    tab._hi_color = ColorPickerButton((1, 1, 0))
    tab._hi_color.color_changed.connect(lambda c: tab._canvas.set_highlight_mode(tab._mode_idx == 3, color=c))
    v3.addWidget(tab._hi_color)
    hint3 = QLabel("💡 Drag across text or click a word to highlight it (like in Foxit PDF).")
    hint3.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;"); hint3.setWordWrap(True)
    tab._hint_labels.append(hint3); v3.addWidget(hint3); v3.addStretch()
    tab._opt_stack.addWidget(w3)

    # 4 - Note
    w4 = QWidget(); v4 = QVBoxLayout(w4); v4.setContentsMargins(0, 4, 0, 0); v4.setSpacing(4)
    v4.addWidget(QLabel(t("edit.note_text")))
    tab._note_txt = QTextEdit(); tab._note_txt.setMaximumHeight(80)
    v4.addWidget(tab._note_txt)
    hint4 = QLabel(t("edit.hint.note")); hint4.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
    tab._hint_labels.append(hint4); v4.addWidget(hint4); v4.addStretch()
    tab._opt_stack.addWidget(w4)

    # 5 - Forms
    w5 = QWidget(); v5 = QVBoxLayout(w5); v5.setContentsMargins(0, 4, 0, 0); v5.setSpacing(4)
    v5.addWidget(QLabel(t("edit.fields_detected")))
    tab._form_table = QTableWidget(0, 2)
    tab._form_table.setHorizontalHeaderLabels([t("edit.field"), t("edit.value")])
    tab._form_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    tab._form_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    tab._form_table.setObjectName("pdf_table"); tab._form_table.setMinimumHeight(130)
    v5.addWidget(tab._form_table)
    tab._form_status = QLabel("")
    tab._form_status.setWordWrap(True)
    tab._form_status.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;")
    tab._hint_labels.append(tab._form_status); v5.addWidget(tab._form_status)
    tab._opt_stack.addWidget(w5)

    # 6 - Signature
    w6 = QWidget(); v6s = QVBoxLayout(w6); v6s.setContentsMargins(0, 4, 0, 0); v6s.setSpacing(6)
    tab._sig_preview = QLabel(t("edit.signature.none"))
    tab._sig_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    tab._sig_preview.setMinimumHeight(60)
    tab._sig_preview.setStyleSheet("background: white; border: 1.5px dashed #ccc; border-radius: 6px;")
    v6s.addWidget(tab._sig_preview)
    tab._sig_choose = QPushButton(t("edit.signature.choose"))
    tab._sig_choose.setIcon(qta.icon("fa5s.signature", color=TEXT_PRI))
    tab._sig_choose.clicked.connect(tab._pick_signature)
    v6s.addWidget(tab._sig_choose)
    sig_clear = QPushButton(t("edit.signature.clear"))
    sig_clear.clicked.connect(tab._clear_signature)
    v6s.addWidget(sig_clear)
    hint6s = QLabel("💡 Click on any placed signature to move (Arrow keys), resize (Ctrl +/- or wheel), or delete (<kbd>Del</kbd>).")
    hint6s.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;"); hint6s.setWordWrap(True)
    tab._hint_labels.append(hint6s); v6s.addWidget(hint6s); v6s.addStretch()
    tab._opt_stack.addWidget(w6)

    saved = get_saved_signature()
    if saved:
        tab._signature_path = saved
        pix = load_signature_pixmap(saved, max_size=(200, 50))
        if not pix.isNull():
            tab._sig_preview.setPixmap(pix)

    # 7 - Draw (freehand ink)
    w_draw = QWidget(); v_d = QVBoxLayout(w_draw); v_d.setContentsMargins(0, 4, 0, 0); v_d.setSpacing(4)
    v_d.addWidget(QLabel(t("edit.color")))
    tab._draw_color_cb = ColorPickerButton((1, 0, 0))
    tab._draw_color_cb.color_changed.connect(tab._on_draw_color_changed)
    v_d.addWidget(tab._draw_color_cb)
    v_d.addWidget(QLabel(t("edit.draw.width")))
    tab._draw_width_slider = QSlider(Qt.Orientation.Horizontal)
    tab._draw_width_slider.setMinimum(1); tab._draw_width_slider.setMaximum(12); tab._draw_width_slider.setValue(2)
    tab._draw_width_lbl = QLabel("2")
    tab._draw_width_slider.valueChanged.connect(tab._on_draw_width_changed)
    wrow = QHBoxLayout(); wrow.addWidget(tab._draw_width_slider, 1); wrow.addWidget(tab._draw_width_lbl)
    v_d.addLayout(wrow)
    hint_d = QLabel(t("edit.hint.draw")); hint_d.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;"); hint_d.setWordWrap(True)
    tab._hint_labels.append(hint_d); v_d.addWidget(hint_d); v_d.addStretch()
    tab._opt_stack.addWidget(w_draw)

    # 8 - Select / Copy / Highlight text
    w8 = QWidget(); v8 = QVBoxLayout(w8); v8.setContentsMargins(0, 4, 0, 0); v8.setSpacing(6)
    hint8 = QLabel(t("edit.hint.select")); hint8.setStyleSheet(f"color:{TEXT_SEC}; font-size:11px;"); hint8.setWordWrap(True)
    tab._hint_labels.append(hint8)
    tab._sel_result = QTextEdit(); tab._sel_result.setReadOnly(True); tab._sel_result.setMaximumHeight(80)
    tab._sel_result.setPlaceholderText(t("edit.select_placeholder"))
    
    sel_btn_row = QHBoxLayout()
    tab._btn_copy = QPushButton(t("btn.copy"))
    tab._btn_copy.setIcon(qta.icon("fa5s.copy", color=TEXT_PRI))
    tab._btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(tab._sel_result.toPlainText()))
    
    tab._btn_highlight = QPushButton(t("edit.mode.highlight"))
    tab._btn_highlight.setIcon(qta.icon("fa5s.highlighter", color=ACCENT))
    tab._btn_highlight.clicked.connect(tab._highlight_selection)
    
    sel_btn_row.addWidget(tab._btn_copy)
    sel_btn_row.addWidget(tab._btn_highlight)

    v8.addWidget(hint8); v8.addWidget(tab._sel_result); v8.addLayout(sel_btn_row); v8.addStretch()
    tab._opt_stack.addWidget(w8)


def update_tab_theme(tab, dark: bool) -> None:
    """Apply active dark/light palette to TabEditar controls."""
    tab._dark_mode = dark
    bg = BG_INNER if dark else _LN
    tab._canvas.set_dark_mode(dark)
    tab._canvas_scroll.setStyleSheet(f"QScrollArea {{ background: {bg}; }}")
    pri = TEXT_PRI if dark else _LP
    sec = TEXT_SEC if dark else _LQ

    tab._btn_prev.setIcon(qta.icon("fa5s.chevron-left", color=pri))
    tab._btn_next.setIcon(qta.icon("fa5s.chevron-right", color=pri))
    tab._btn_undo.setIcon(qta.icon("fa5s.undo", color=pri))
    tab._btn_redo.setIcon(qta.icon("fa5s.redo", color=pri))
    tab._btn_copy.setIcon(qta.icon("fa5s.copy", color=pri))
    if hasattr(tab, "_btn_highlight"):
        tab._btn_highlight.setIcon(qta.icon("fa5s.highlighter", color=ACCENT))
    tab._sig_choose.setIcon(qta.icon("fa5s.signature", color=pri))
    tab._btn_bold.setIcon(qta.icon("fa5s.bold", color=pri))
    tab._btn_italic.setIcon(qta.icon("fa5s.italic", color=pri))

    for lbl in tab._hint_labels:
        try:
            lbl.setStyleSheet(f"color:{sec}; font-size:11px;")
        except RuntimeError:
            pass

    for dfe in (tab._drop_in, tab._img_drop, tab._drop_out):
        fn = getattr(dfe, "update_theme", None)
        if callable(fn):
            fn(dark)

    fn = getattr(tab._action_bar, "update_theme", None)
    if callable(fn):
        fn(dark)

    for i, b in enumerate(tab._mode_btns):
        if not b.isChecked():
            b.setIcon(qta.icon(tab._MODE_DEFS[i][1], color=sec))
            b.setStyleSheet(
                "background:#333333; border:1px solid #444444; color:#CCCCCC; border-radius:6px;"
                if dark else
                "background:#FFFFFF; border:1px solid #D1D5DB; color:#555555; border-radius:6px;"
            )
        else:
            b.setStyleSheet(
                f"background:#264F78; border:1px solid {ACCENT}; color:#FFFFFF; border-radius:6px;"
                if dark else
                f"background:#D6E8FA; border:1px solid #70A7DB; color:{ACCENT}; border-radius:6px;"
            )

