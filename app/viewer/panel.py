# app/viewer/panel.py
"""PDFApps – PdfViewerPanel: PDF viewer with drag & drop, text selection, and thumbnail multi-page actions."""
import json
import logging
import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QLineEdit, QSplitter, QTabWidget,
    QTreeWidget
)
from PySide6.QtGui import QKeySequence, QShortcut
import qtawesome as qta

from app.constants import TEXT_SEC, DESKTOP
from app.i18n import t, _CONFIG_PATH
from app.viewer.canvas import _SelectCanvas
from app.viewer.thumbnails import ThumbnailPanel

from app.viewer.panel_history import PanelHistoryMixin
from app.viewer.panel_page_ops import PanelPageOpsMixin
from app.viewer.panel_search_print import PanelSearchPrintMixin
from app.viewer.panel_nav import PanelNavMixin

_log = logging.getLogger(__name__)


class PdfViewerPanel(PanelHistoryMixin, PanelPageOpsMixin, PanelSearchPrintMixin, PanelNavMixin, QWidget):
    """PDF viewer with drag & drop, native text selection and navigation."""

    crop_selected       = Signal(int, object)
    crop_applied        = Signal()
    crop_undo_requested = Signal()
    crop_redo_requested = Signal()

    _pages_sidebar_visible_pref: bool | None = None

    def __init__(self):
        super().__init__()
        self.setObjectName("viewer_panel")
        self.setMinimumWidth(260)
        self._current_path = ""
        self._original_doc_path = ""
        self._fitz_doc = None
        self._pdf_password = ""

        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._history_temp_files: set[str] = set()

        if PdfViewerPanel._pages_sidebar_visible_pref is None:
            try:
                if os.path.isfile(_CONFIG_PATH):
                    with open(_CONFIG_PATH, "r", encoding="utf-8") as _f:
                        cfg = json.load(_f)
                        PdfViewerPanel._pages_sidebar_visible_pref = bool(
                            cfg.get("pages_sidebar_open", True)
                        )
                else:
                    PdfViewerPanel._pages_sidebar_visible_pref = True
            except Exception:
                PdfViewerPanel._pages_sidebar_visible_pref = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────────
        hdr = QWidget()
        hdr.setObjectName("viewer_header")
        hdr_lay = QHBoxLayout(hdr)
        hdr_lay.setContentsMargins(12, 8, 8, 8)
        hdr_lay.setSpacing(6)

        self._name_lbl = QLabel(t("viewer.title"))
        self._name_lbl.setObjectName("viewer_title")
        hdr_lay.addWidget(self._name_lbl, 1)

        def _nav_btn(icon_name):
            b = QPushButton()
            b.setIcon(qta.icon(icon_name, color=TEXT_SEC))
            b.setObjectName("viewer_nav_btn")
            b.setFixedSize(28, 28)
            b.setEnabled(False)
            return b

        def _a11y(btn, tip):
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)

        self._open_btn = _nav_btn('fa5s.folder-open')
        self._open_btn.setEnabled(True)
        _a11y(self._open_btn, t("btn.open_pdf"))
        self._open_btn.clicked.connect(self._open_dialog)

        self._toc_btn = _nav_btn('fa5s.bookmark')
        _a11y(self._toc_btn, t("viewer.toc"))
        self._toc_btn.clicked.connect(self._toggle_pages_sidebar)
        self._toc_btn.setVisible(False)

        self._night_btn = _nav_btn('fa5s.moon')
        _a11y(self._night_btn, t("viewer.night_mode"))
        self._night_btn.setCheckable(True)
        self._night_btn.clicked.connect(self._toggle_night_mode)

        self._zoom_out_btn = _nav_btn('fa5s.search-minus')
        _a11y(self._zoom_out_btn, t("zoom.out"))
        self._zoom_out_btn.clicked.connect(lambda: self._canvas.zoom_out())

        self._zoom_lbl = QLabel(t("zoom.fit"))
        self._zoom_lbl.setObjectName("viewer_page_lbl")
        self._zoom_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._zoom_lbl.setMinimumWidth(52)

        self._zoom_in_btn = _nav_btn('fa5s.search-plus')
        _a11y(self._zoom_in_btn, t("zoom.in"))
        self._zoom_in_btn.clicked.connect(lambda: self._canvas.zoom_in())

        self._fit_btn = _nav_btn('fa5s.compress-arrows-alt')
        _a11y(self._fit_btn, t("zoom.fit_tip"))
        self._fit_btn.clicked.connect(self._zoom_fit)

        self._prev_btn = _nav_btn('fa5s.chevron-left')
        _a11y(self._prev_btn, t("nav.prev_page"))
        self._prev_btn.clicked.connect(self._prev_page)

        self._page_lbl = QLabel("— / —")
        self._page_lbl.setObjectName("viewer_page_lbl")
        self._page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._next_btn = _nav_btn('fa5s.chevron-right')
        _a11y(self._next_btn, t("nav.next_page"))
        self._next_btn.clicked.connect(self._next_page)

        self._print_btn = _nav_btn('fa5s.print')
        _a11y(self._print_btn, t("viewer.print"))
        self._print_btn.clicked.connect(self._print_pdf)

        for w in (self._open_btn, self._toc_btn, self._zoom_out_btn, self._zoom_lbl,
                  self._zoom_in_btn, self._fit_btn,
                  self._prev_btn, self._page_lbl, self._next_btn,
                  self._night_btn, self._print_btn):
            hdr_lay.addWidget(w)
        self._hdr = hdr
        self._hdr.setVisible(False)
        layout.addWidget(hdr)

        # ── Placeholder ─────────────────────────────────────────────────────
        ph_widget = QWidget()
        ph_widget.setObjectName("viewer_ph_widget")
        ph_lay = QVBoxLayout(ph_widget)
        ph_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph_lay.setSpacing(14)
        ph_drag = QLabel(t("viewer.drag_hint"))
        ph_drag.setObjectName("viewer_placeholder")
        ph_drag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ph_btn = QPushButton(t("viewer.open_btn"))
        self._ph_btn.setIcon(qta.icon('fa5s.folder-open', color='#FFFFFF'))
        self._ph_btn.setObjectName("btn_primary")
        self._ph_btn.setFixedWidth(160)
        self._ph_btn.clicked.connect(self._open_dialog)

        ph_lay.addWidget(self._ph_btn, 0, Qt.AlignmentFlag.AlignCenter)
        ph_lay.addWidget(ph_drag)

        # Recent files section
        self._recents_container = QWidget()
        self._recents_container.setMaximumWidth(400)
        self._recent_links: list[QPushButton] = []
        self._recent_del_btns: list[QPushButton] = []
        self._recents_layout = QVBoxLayout(self._recents_container)
        self._recents_layout.setContentsMargins(0, 16, 0, 0)
        self._recents_layout.setSpacing(4)
        self._refresh_recents()
        ph_lay.addWidget(self._recents_container, 0, Qt.AlignmentFlag.AlignCenter)

        self._placeholder = ph_widget
        layout.addWidget(self._placeholder, 1)

        # ── TOC tree (Contents tab of the sidebar) ─────────────────────
        self._toc_tree = QTreeWidget()
        self._toc_tree.setObjectName("toc_tree")
        self._toc_tree.setHeaderHidden(True)
        self._toc_tree.setMinimumWidth(180)
        self._toc_tree.itemClicked.connect(self._on_toc_clicked)

        # ── Thumbnails (Pages tab of the sidebar) ───────────────────────
        self._thumbnails = ThumbnailPanel(self)
        self._thumbnails.page_requested.connect(self._on_thumbnail_clicked)
        self._thumbnails.action_requested.connect(self._on_thumbnail_action)

        # Sidebar tab widget: [Contents | Pages]
        self._sidebar_tabs = QTabWidget()
        self._sidebar_tabs.setObjectName("viewer_sidebar_tabs")
        self._sidebar_tabs.setDocumentMode(True)
        self._sidebar_tabs.setMinimumWidth(180)
        self._toc_tab_idx = self._sidebar_tabs.addTab(
            self._toc_tree, t("viewer.sidebar.contents"))
        self._pages_tab_idx = self._sidebar_tabs.addTab(
            self._thumbnails, t("viewer.sidebar.pages"))

        # Left Sidebar Panel hosting sidebar tabs
        self._sidebar_panel = QWidget()
        self._sidebar_panel.setObjectName("viewer_left_sidebar")
        sp_lay = QVBoxLayout(self._sidebar_panel)
        sp_lay.setContentsMargins(0, 0, 0, 0)
        sp_lay.setSpacing(0)
        sp_lay.addWidget(self._sidebar_tabs, 1)

        initial_open = bool(PdfViewerPanel._pages_sidebar_visible_pref)
        self._pages_sidebar_collapsed = not initial_open
        self._saved_sidebar_width = 220

        # ── Canvas with continuous scroll of all pages ──────────────────
        self._canvas = _SelectCanvas()
        self._canvas.zoom_changed.connect(self._on_zoom_changed)
        self._canvas.doc_replaced.connect(self._on_doc_replaced)
        self._canvas.crop_selected.connect(self.crop_selected.emit)
        self._canvas.crop_applied.connect(self.crop_applied.emit)
        self._canvas.crop_undo_requested.connect(self.crop_undo_requested.emit)
        self._canvas.crop_redo_requested.connect(self.crop_redo_requested.emit)
        self._canvas.page_action_requested.connect(self._on_thumbnail_action)

        self._canvas_scroll = QScrollArea()
        self._canvas_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._canvas_scroll.setWidgetResizable(False)
        self._canvas_scroll.setWidget(self._canvas)
        self._canvas_scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._canvas_scroll.viewport().installEventFilter(self)
        self._canvas_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # Splitter: sidebar | canvas
        self._viewer_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._viewer_splitter.addWidget(self._sidebar_panel)
        self._viewer_splitter.addWidget(self._canvas_scroll)
        self._viewer_splitter.setStretchFactor(0, 0)
        self._viewer_splitter.setStretchFactor(1, 1)
        self._viewer_splitter.setSizes([220, 800])
        self._viewer_splitter.setCollapsible(0, True)
        self._viewer_splitter.setCollapsible(1, False)
        self._viewer_splitter.setVisible(False)
        self._sidebar_panel.setVisible(False)
        layout.addWidget(self._viewer_splitter, 1)

        # ── Search bar (Ctrl+F) ───────────────────────────────────────────
        self._search_bar = QWidget()
        self._search_bar.setObjectName("search_bar")
        sb_lay = QHBoxLayout(self._search_bar)
        sb_lay.setContentsMargins(8, 4, 8, 4)
        sb_lay.setSpacing(4)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(t("search.placeholder"))
        self._search_input.setObjectName("search_input")
        self._search_input.returnPressed.connect(self._search_next)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._search_lbl = QLabel("")
        self._search_lbl.setMinimumWidth(60)
        self._search_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._search_prev_btn = QPushButton()
        self._search_prev_btn.setIcon(qta.icon("fa5s.chevron-up", color=TEXT_SEC))
        self._search_prev_btn.setFixedSize(28, 28)
        self._search_prev_btn.setObjectName("viewer_nav_btn")
        self._search_prev_btn.setToolTip(t("search.prev"))
        self._search_prev_btn.setAccessibleName(t("search.prev"))
        self._search_prev_btn.clicked.connect(self._search_prev)
        self._search_next_btn = QPushButton()
        self._search_next_btn.setIcon(qta.icon("fa5s.chevron-down", color=TEXT_SEC))
        self._search_next_btn.setFixedSize(28, 28)
        self._search_next_btn.setObjectName("viewer_nav_btn")
        self._search_next_btn.setToolTip(t("search.next"))
        self._search_next_btn.setAccessibleName(t("search.next"))
        self._search_next_btn.clicked.connect(self._search_next)
        self._search_close_btn = QPushButton()
        self._search_close_btn.setIcon(qta.icon("fa5s.times", color=TEXT_SEC))
        self._search_close_btn.setFixedSize(28, 28)
        self._search_close_btn.setObjectName("viewer_nav_btn")
        self._search_close_btn.setToolTip(t("search.close"))
        self._search_close_btn.setAccessibleName(t("search.close"))
        self._search_close_btn.clicked.connect(self._close_search)
        sb_lay.addWidget(self._search_input, 1)
        sb_lay.addWidget(self._search_lbl)
        sb_lay.addWidget(self._search_prev_btn)
        sb_lay.addWidget(self._search_next_btn)
        sb_lay.addWidget(self._search_close_btn)
        self._search_bar.setVisible(False)
        layout.addWidget(self._search_bar)
        self._search_results: list[tuple[int, list]] = []
        self._search_current = -1
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(250)
        self._search_debounce.timeout.connect(self._run_pending_search)
        self._pending_search_query = ""

        # Shortcuts (Correctly scoped context)
        sc_find = QShortcut(QKeySequence("Ctrl+F"), self, self._toggle_search)
        sc_find.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_esc = QShortcut(QKeySequence("Escape"), self._search_input, self._close_search)
        sc_esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)