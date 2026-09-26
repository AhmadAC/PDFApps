# app/viewer/panel.py
"""PDFApps – PdfViewerPanel: PDF viewer with drag & drop, text selection, and thumbnail multi-page actions."""

import os
import sys
import logging
import contextlib
import tempfile
import shutil

from PySide6.QtCore import Qt, QEvent, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QFileDialog, QMessageBox, QDialog,
    QLineEdit, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QApplication, QInputDialog,
)
from PySide6.QtGui import QKeySequence, QShortcut
from shiboken6 import isValid
import qtawesome as qta
import fitz

from app.constants import ACCENT, TEXT_SEC, _LQ, DESKTOP
from app.pdf_password import authenticate_fitz
from app.utils import _paint_bg, show_error, format_size_localized
from app.pdf_io import atomic_pdf_write
from app.i18n import t
from app.viewer.canvas import _SelectCanvas
from app.viewer.thumbnails import ThumbnailPanel

_log = logging.getLogger(__name__)


class PdfViewerPanel(QWidget):
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
        self._fitz_doc     = None
        self._pdf_password = ""

        if PdfViewerPanel._pages_sidebar_visible_pref is None:
            try:
                from app.i18n import _CONFIG_PATH
                import json
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
        hdr = QWidget(); hdr.setObjectName("viewer_header")
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
            btn.setToolTip(tip); btn.setAccessibleName(tip)

        self._open_btn     = _nav_btn('fa5s.folder-open')
        self._open_btn.setEnabled(True)
        _a11y(self._open_btn, t("btn.open_pdf"))
        self._open_btn.clicked.connect(self._open_dialog)

        self._toc_btn      = _nav_btn('fa5s.bookmark')
        _a11y(self._toc_btn, t("viewer.toc"))
        self._toc_btn.clicked.connect(self._toggle_pages_sidebar)
        self._toc_btn.setVisible(False)

        self._night_btn    = _nav_btn('fa5s.moon')
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

        self._zoom_in_btn  = _nav_btn('fa5s.search-plus')
        _a11y(self._zoom_in_btn, t("zoom.in"))
        self._zoom_in_btn.clicked.connect(lambda: self._canvas.zoom_in())

        self._fit_btn      = _nav_btn('fa5s.compress-arrows-alt')
        _a11y(self._fit_btn, t("zoom.fit_tip"))
        self._fit_btn.clicked.connect(self._zoom_fit)

        self._prev_btn     = _nav_btn('fa5s.chevron-left')
        _a11y(self._prev_btn, t("nav.prev_page"))
        self._prev_btn.clicked.connect(self._prev_page)

        self._page_lbl = QLabel("— / —")
        self._page_lbl.setObjectName("viewer_page_lbl")
        self._page_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._next_btn     = _nav_btn('fa5s.chevron-right')
        _a11y(self._next_btn, t("nav.next_page"))
        self._next_btn.clicked.connect(self._next_page)

        self._print_btn    = _nav_btn('fa5s.print')
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
        ph_widget = QWidget(); ph_widget.setObjectName("viewer_ph_widget")
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
        self._search_prev_btn.setFixedSize(28, 28); self._search_prev_btn.setObjectName("viewer_nav_btn")
        self._search_prev_btn.setToolTip(t("search.prev")); self._search_prev_btn.setAccessibleName(t("search.prev"))
        self._search_prev_btn.clicked.connect(self._search_prev)
        self._search_next_btn = QPushButton()
        self._search_next_btn.setIcon(qta.icon("fa5s.chevron-down", color=TEXT_SEC))
        self._search_next_btn.setFixedSize(28, 28); self._search_next_btn.setObjectName("viewer_nav_btn")
        self._search_next_btn.setToolTip(t("search.next")); self._search_next_btn.setAccessibleName(t("search.next"))
        self._search_next_btn.clicked.connect(self._search_next)
        self._search_close_btn = QPushButton()
        self._search_close_btn.setIcon(qta.icon("fa5s.times", color=TEXT_SEC))
        self._search_close_btn.setFixedSize(28, 28); self._search_close_btn.setObjectName("viewer_nav_btn")
        self._search_close_btn.setToolTip(t("search.close")); self._search_close_btn.setAccessibleName(t("search.close"))
        self._search_close_btn.clicked.connect(self._close_search)
        sb_lay.addWidget(self._search_input, 1)
        sb_lay.addWidget(self._search_lbl)
        sb_lay.addWidget(self._search_prev_btn); sb_lay.addWidget(self._search_next_btn); sb_lay.addWidget(self._search_close_btn)
        self._search_bar.setVisible(False)
        layout.addWidget(self._search_bar)
        self._search_results: list[tuple[int, list]] = []
        self._search_current = -1
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(250)
        self._search_debounce.timeout.connect(self._run_pending_search)
        self._pending_search_query = ""

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+F"), self, self._toggle_search)
        QShortcut(QKeySequence("Escape"), self._search_input, self._close_search)

    def _toggle_pages_sidebar(self):
        if not self._pages_sidebar_collapsed:
            self._saved_sidebar_width = max(180, self._sidebar_panel.width())
            self._pages_sidebar_collapsed = True
            self._sidebar_panel.setVisible(False)
            total = self._viewer_splitter.width() or 1020
            self._viewer_splitter.setSizes([0, total])
            PdfViewerPanel._pages_sidebar_visible_pref = False
        else:
            self._pages_sidebar_collapsed = False
            self._sidebar_panel.setVisible(True)
            self._sidebar_tabs.setVisible(True)
            w = min(400, max(180, getattr(self, "_saved_sidebar_width", 220)))
            total = self._viewer_splitter.width() or 1020
            self._viewer_splitter.setSizes([w, max(300, total - w)])
            PdfViewerPanel._pages_sidebar_visible_pref = True

        try:
            from app.i18n import _update_config
            pref = not self._pages_sidebar_collapsed
            _update_config(lambda cfg: cfg.__setitem__("pages_sidebar_open", pref))
        except Exception:
            pass

    def set_crop_mode(self, active: bool):
        if hasattr(self, "_canvas"):
            self._canvas.set_crop_mode(active)

    def set_crop_preview(self, crop_data: dict | None):
        if hasattr(self, "_canvas"):
            self._canvas.set_crop_preview(crop_data)

    def set_page_rotations(self, rotations: dict[int, int]):
        """Update live preview rotations across continuous scroll and thumbnail sidebar."""
        if hasattr(self, "_canvas"):
            self._canvas.set_page_rotations(rotations)
        if hasattr(self, "_thumbnails"):
            self._thumbnails.set_page_rotations(rotations)

    def set_page_crops(self, crops: dict[int, tuple[float, float, float, float]]):
        """Update live preview crops across continuous scroll and thumbnail sidebar."""
        if hasattr(self, "_canvas"):
            self._canvas.set_page_crops(crops)
        if hasattr(self, "_thumbnails"):
            self._thumbnails.set_page_crops(crops)

    def _on_zoom_changed(self, pct: int):
        self._zoom_lbl.setText(f"{pct}%")
        self._update_page_label()

    def _on_scroll(self, val: int):
        self._canvas.on_scroll()
        self._update_page_label()

    def paintEvent(self, event):
        _paint_bg(self)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QTimer
        if obj is self._canvas_scroll.viewport():
            if event.type() == QEvent.Type.Wheel:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    if event.angleDelta().y() > 0:
                        self._canvas.zoom_in()
                    else:
                        self._canvas.zoom_out()
                    return True
            elif event.type() == QEvent.Type.Resize:
                if self._canvas._doc and self._canvas._zoom_factor == 1.0:
                    QTimer.singleShot(0, self._canvas._layout_and_schedule)
        return super().eventFilter(obj, event)

    @staticmethod
    def _recent_link_style(dark: bool) -> str:
        hover_bg = "rgba(255,255,255,0.05)" if dark else "rgba(0,0,0,0.05)"
        focus_border = ACCENT
        return (
            "QPushButton#recent_link { text-align: left; padding: 4px 12px; "
            "border: 1px solid transparent; background: transparent; font-size: 10pt; }"
            f"QPushButton#recent_link:hover {{ background: {hover_bg}; border-radius: 6px; }}"
            f"QPushButton#recent_link:focus {{ border: 1px solid {focus_border}; border-radius: 6px; }}")

    def update_theme(self, dark: bool) -> None:
        self._canvas.set_dark_mode(dark)
        c = TEXT_SEC if dark else _LQ
        self._open_btn.setIcon(qta.icon('fa5s.folder-open',          color=c))
        self._toc_btn.setIcon(qta.icon('fa5s.bookmark',              color=c))
        self._night_btn.setIcon(qta.icon('fa5s.moon',                color=c))
        self._prev_btn.setIcon(qta.icon('fa5s.chevron-left',          color=c))
        self._next_btn.setIcon(qta.icon('fa5s.chevron-right',         color=c))
        self._zoom_out_btn.setIcon(qta.icon('fa5s.search-minus',      color=c))
        self._zoom_in_btn.setIcon(qta.icon('fa5s.search-plus',        color=c))
        self._fit_btn.setIcon(qta.icon('fa5s.compress-arrows-alt',    color=c))
        self._print_btn.setIcon(qta.icon('fa5s.print',                color=c))
        self._search_prev_btn.setIcon(qta.icon('fa5s.chevron-up',     color=c))
        self._search_next_btn.setIcon(qta.icon('fa5s.chevron-down',   color=c))
        self._search_close_btn.setIcon(qta.icon('fa5s.times',         color=c))
        link_style = self._recent_link_style(dark)
        for link in self._recent_links:
            link.setStyleSheet(link_style)
        for btn in self._recent_del_btns:
            btn.setIcon(qta.icon("fa5s.trash-alt", color=c))
        self._thumbnails.update_theme(dark)

    def _refresh_recents(self):
        from app.i18n import get_recent_files
        lay = self._recents_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._recent_links = []
        self._recent_del_btns = []
        recents = get_recent_files()
        if not recents:
            return
        rec_title = QLabel(t("viewer.recent"))
        rec_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rec_title.setStyleSheet(
            "font-size: 10pt; font-weight: 600; opacity: 0.7;")
        lay.addWidget(rec_title)
        for rp in recents[:5]:
            if not os.path.lexists(rp):
                continue
            if os.path.isdir(rp):
                continue
            fname = os.path.basename(rp)
            row = QWidget()
            row_h = QHBoxLayout(row)
            row_h.setContentsMargins(0, 0, 0, 0)
            row_h.setSpacing(0)
            link = QPushButton(f"📄  {fname}")
            link.setObjectName("recent_link")
            link.setToolTip(rp)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setFlat(True)
            link.setStyleSheet(self._recent_link_style(dark=True))
            link.clicked.connect(lambda checked=False, p=rp, r=row: self._on_recent_clicked(p, r))
            self._recent_links.append(link)
            del_btn = QPushButton()
            del_btn.setIcon(qta.icon("fa5s.trash-alt", color=TEXT_SEC))
            del_btn.setFixedSize(28, 28)
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setFlat(True)
            del_btn.setToolTip(t("btn.remove"))
            del_btn.setAccessibleName(t("btn.remove"))
            del_btn.setStyleSheet(
                f"QPushButton {{ border: 1px solid transparent; "
                f"background: transparent; }}"
                f"QPushButton:hover {{ background: rgba(239,68,68,0.15); "
                f"border-radius: 4px; }}"
                f"QPushButton:focus {{ border: 1px solid {ACCENT}; "
                f"border-radius: 4px; }}")
            del_btn.clicked.connect(
                lambda checked, p=rp, r=row: self._remove_recent(p, r))
            self._recent_del_btns.append(del_btn)
            row_h.addWidget(link, 1)
            row_h.addWidget(del_btn)
            lay.addWidget(row)

    def _on_recent_clicked(self, path: str, row_widget=None):
        print(f"[PDFApps] Recent file clicked: {path}")
        _log.info("Recent file clicked: %s", path)
        resolved = path
        if not os.path.isfile(resolved):
            if os.path.isfile(resolved + ".pdf"):
                resolved = resolved + ".pdf"
        if not os.path.isfile(resolved):
            _log.warning("Recent file does not exist: %s", path)
            QMessageBox.warning(
                self, t("msg.warning"),
                f"{t('viewer.error_open')}:\n{path}\n\nFile not found on disk."
            )
            if row_widget is not None:
                self._remove_recent(path, row_widget)
            return

        self.load(resolved)

    def _remove_recent(self, path: str, row_widget):
        from app.i18n import _update_config
        normed = os.path.normpath(path)

        def _mutate(cfg: dict) -> None:
            recents = cfg.get("recent_files", [])
            if not isinstance(recents, list):
                recents = []
            cfg["recent_files"] = [
                r for r in recents
                if isinstance(r, str) and os.path.normpath(r) != normed
            ]

        try:
            _update_config(_mutate)
        except Exception:
            pass
        row_widget.setVisible(False)

    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window(), t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        if path:
            self.load(path)

    def current_path(self) -> str:
        return self._current_path

    # ── TOC / Bookmarks ─────────────────────────────────────────────────
    def _set_toc_tab_visible(self, visible: bool) -> None:
        if hasattr(self._sidebar_tabs, "setTabVisible"):
            self._sidebar_tabs.setTabVisible(self._toc_tab_idx, visible)
            return
        present = self._sidebar_tabs.indexOf(self._toc_tree) != -1
        if visible and not present:
            self._sidebar_tabs.insertTab(
                0, self._toc_tree, t("viewer.sidebar.contents"))
            self._toc_tab_idx = 0
            self._pages_tab_idx = self._sidebar_tabs.indexOf(self._thumbnails)
        elif not visible and present:
            self._sidebar_tabs.removeTab(self._toc_tab_idx)
            self._pages_tab_idx = self._sidebar_tabs.indexOf(self._thumbnails)

    def _populate_toc(self, doc, active_sidebar_tab: QWidget | int | None = None):
        self._toc_tree.clear()
        try:
            toc = doc.get_toc()
        except Exception as exc:
            _log.warning("Failed to read TOC for %s: %s", self._current_path, exc)
            toc = []
        if not toc:
            self._set_toc_tab_visible(False)
            pages_idx = self._sidebar_tabs.indexOf(self._thumbnails)
            if pages_idx >= 0:
                self._sidebar_tabs.setCurrentIndex(pages_idx)
            return
        try:
            stack = [(0, self._toc_tree.invisibleRootItem())]
            for level, title, page in toc:
                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent = stack[-1][1] if stack else self._toc_tree.invisibleRootItem()
                item = QTreeWidgetItem(parent, [title])
                item.setData(0, Qt.ItemDataRole.UserRole, max(0, page - 1))
                item.setToolTip(0, title)
                stack.append((level, item))
            self._toc_tree.expandToDepth(1)
            self._set_toc_tab_visible(True)
            if isinstance(active_sidebar_tab, QWidget) and self._sidebar_tabs.indexOf(active_sidebar_tab) != -1:
                self._sidebar_tabs.setCurrentWidget(active_sidebar_tab)
            elif isinstance(active_sidebar_tab, int) and 0 <= active_sidebar_tab < self._sidebar_tabs.count():
                self._sidebar_tabs.setCurrentIndex(active_sidebar_tab)
            else:
                self._sidebar_tabs.setCurrentIndex(self._toc_tab_idx)
        except Exception as exc:
            _log.warning("Failed to build TOC tree for %s: %s", self._current_path, exc)
            self._toc_tree.clear()
            self._set_toc_tab_visible(False)

    def _on_toc_clicked(self, item, column):
        page_idx = item.data(0, Qt.ItemDataRole.UserRole)
        if page_idx is None:
            return
        y = self._canvas.scroll_to_page(int(page_idx))
        self._canvas_scroll.verticalScrollBar().setValue(y)

    def _on_thumbnail_clicked(self, page_idx: int) -> None:
        y = self._canvas.scroll_to_page(int(page_idx))
        self._canvas_scroll.verticalScrollBar().setValue(y)

    # ── Multi-page Context Menu Operations Handler ───────────────────────

    def _on_thumbnail_action(self, action: str, pages_arg: object) -> None:
        if not self._fitz_doc or not self._current_path:
            return

        if isinstance(pages_arg, int):
            pages = [pages_arg]
        elif isinstance(pages_arg, (list, tuple, set)):
            pages = sorted(list(pages_arg))
        else:
            pages = [0]

        if not pages:
            return

        if action in ("rotate_right", "rotate_left", "rotate_180"):
            delta = 90 if action == "rotate_right" else (270 if action == "rotate_left" else 180)
            self._rotate_pages(pages, delta)
        elif action == "delete":
            self._delete_pages(pages)
        elif action == "extract":
            self._extract_pages(pages)
        elif action == "insert_blank":
            self._insert_blank_page(pages[-1])
        elif action == "insert_file":
            self._insert_pages_from_file(pages[-1])
        elif action == "duplicate":
            self._duplicate_pages(pages)
        elif action == "reverse":
            self._reverse_pages(pages)
        elif action == "swap":
            self._swap_page_dialog(pages[0])
        elif action == "move":
            self._move_page_dialog(pages)
        elif action == "replace":
            self._replace_page_dialog(pages[0])
        elif action == "resize":
            self._resize_pages_dialog(pages)
        elif action == "crop":
            self._trigger_crop_tool(pages)
        elif action == "page_numbers":
            self._trigger_page_numbers_tool(pages)
        elif action == "split":
            self._trigger_split_tool()
        elif action == "print":
            self._print_pdf(pages)
        elif action == "properties":
            self._show_properties_dialog()
        elif action == "copy":
            self._copy_page_content(pages)
        elif action == "paste":
            self._paste_page_content(pages[0])

    def _save_and_reload(self, doc_to_save, target_page: int | None = None, selected_pages: list[int] | None = None):
        """Persist modifications to a temporary pipeline file and reload live viewer without modifying original on disk."""
        try:
            win = self.window()
            vid = id(self)
            ps = getattr(win, "_pipeline_state", None)

            # Determine original path and temp path
            orig_path = self._current_path
            if ps is not None and vid in ps:
                orig_path = ps[vid].get("original_path") or self._current_path
                temp_path = ps[vid].get("temp_path")
            else:
                temp_path = None

            if not temp_path:
                fd, temp_path = tempfile.mkstemp(prefix="pdfapps_modified_", suffix=".pdf")
                os.close(fd)

            # Preserve current view states before unloading
            scroll_val = self._canvas_scroll.verticalScrollBar().value()
            viewed_page = self._canvas.page_at_y(scroll_val) if self._canvas.page_count() > 0 else 0
            if target_page is not None:
                viewed_page = target_page

            if selected_pages is None and hasattr(self, "_thumbnails"):
                selected_pages = self._thumbnails.selected_pages()

            current_tab_widget = self._sidebar_tabs.currentWidget()

            thumb_scroll_val = 0
            if hasattr(self, "_thumbnails") and getattr(self._thumbnails, "_view", None) is not None:
                sb = self._thumbnails._view.verticalScrollBar()
                if sb:
                    thumb_scroll_val = sb.value()

            # Release all open document handles before saving/replacing in-place
            self._canvas.close_doc()
            if self._fitz_doc is not None:
                with contextlib.suppress(Exception):
                    self._fitz_doc.close()
                self._fitz_doc = None
            self._thumbnails._stop_all_workers()

            atomic_pdf_write(
                doc_to_save, temp_path,
                save_opts={"garbage": 4, "deflate": True},
                close_writer=True,
            )

            # Track pipeline state in MainWindow so it knows the document is modified (unsaved)
            if ps is not None:
                ps[vid] = {
                    "original_path": orig_path,
                    "temp_path": temp_path,
                }

            # Reload with target page and scroll value passed in directly
            self.load(
                temp_path,
                target_page=viewed_page,
                target_scroll=scroll_val,
                selected_pages=selected_pages,
                active_sidebar_tab=current_tab_widget,
            )

            # Update tab bar text in window to reflect unsaved state
            if win and hasattr(win, "_tab_bar") and hasattr(win, "_viewers"):
                for idx, v in enumerate(win._viewers):
                    if v is self:
                        orig_name = os.path.basename(orig_path)
                        win._tab_bar.setTabText(idx, f"● {orig_name}")
                        win._tab_bar.setTabToolTip(idx, f"{orig_path} (modified)")
                        break

            if thumb_scroll_val > 0 and hasattr(self, "_thumbnails") and getattr(self._thumbnails, "_view", None) is not None:
                sb = self._thumbnails._view.verticalScrollBar()
                if sb:
                    sb.setValue(min(thumb_scroll_val, sb.maximum()))

            if hasattr(win, "_update_page_nav"):
                win._update_page_nav()
            if hasattr(win, "_set_status"):
                win._set_status("ℹ Document modified (Press Ctrl+S to save changes)")
        except Exception as exc:
            show_error(self, exc)

    def _rotate_pages(self, pages: list[int], delta: int) -> None:
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            for p_idx in pages:
                if 0 <= p_idx < doc.page_count:
                    page = doc[p_idx]
                    cur_rot = page.rotation
                    new_rot = (cur_rot + delta) % 360
                    page.set_rotation(new_rot)
            first_page = min(pages) if pages else None
            self._save_and_reload(doc, target_page=first_page, selected_pages=pages)
        except Exception as exc:
            show_error(self, exc)

    def _delete_pages(self, pages: list[int]) -> None:
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            if doc.page_count <= len(pages):
                QMessageBox.warning(self, t("msg.warning"), "Cannot delete all pages in the document.")
                doc.close()
                return

            page_str = ", ".join(str(p + 1) for p in pages)
            if len(pages) > 6:
                page_str = f"{len(pages)} pages ({pages[0] + 1}..{pages[-1] + 1})"

            reply = QMessageBox.question(
                self, t("msg.confirm"),
                f"Are you sure you want to delete page(s) {page_str}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                doc.close()
                return

            for p_idx in sorted(pages, reverse=True):
                if 0 <= p_idx < doc.page_count:
                    doc.delete_page(p_idx)

            target = min(pages[0], doc.page_count - 1)
            self._save_and_reload(doc, target_page=target, selected_pages=[target])
        except Exception as exc:
            show_error(self, exc)

    def _extract_pages(self, pages: list[int]) -> None:
        base, ext = os.path.splitext(os.path.basename(self._current_path))
        if len(pages) == 1:
            default_name = f"{base}_page_{pages[0] + 1}{ext}"
        else:
            default_name = f"{base}_extracted_pages{ext}"
        out_path, _ = QFileDialog.getSaveFileName(
            self, t("tool.extract.name"),
            os.path.join(os.path.dirname(self._current_path), default_name),
            t("file_filter.pdf"),
        )
        if not out_path:
            return
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            new_doc = fitz.open()
            for p_idx in pages:
                if 0 <= p_idx < doc.page_count:
                    new_doc.insert_pdf(doc, from_page=p_idx, to_page=p_idx)
            doc.close()
            atomic_pdf_write(new_doc, out_path, close_writer=True)
            QMessageBox.information(self, t("msg.done"), f"{len(pages)} page(s) extracted to:\n{out_path}")
        except Exception as exc:
            show_error(self, exc)

    def _insert_blank_page(self, page_idx: int) -> None:
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            ref_rect = doc[page_idx].rect if 0 <= page_idx < doc.page_count else fitz.Rect(0, 0, 595, 842)
            doc.new_page(pno=page_idx + 1, width=ref_rect.width, height=ref_rect.height)
            self._save_and_reload(doc, target_page=page_idx + 1, selected_pages=[page_idx + 1])
        except Exception as exc:
            show_error(self, exc)

    def _insert_pages_from_file(self, page_idx: int) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Insert Pages from PDF", DESKTOP, t("file_filter.pdf"))
        if not p or not os.path.isfile(p):
            return
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            src = fitz.open(p)
            doc.insert_pdf(src, start_at=page_idx + 1)
            src.close()
            self._save_and_reload(doc, target_page=page_idx + 1, selected_pages=[page_idx + 1])
        except Exception as exc:
            show_error(self, exc)

    def _duplicate_pages(self, pages: list[int]) -> None:
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            for p_idx in sorted(pages, reverse=True):
                if 0 <= p_idx < doc.page_count:
                    doc.insert_pdf(doc, from_page=p_idx, to_page=p_idx, start_at=p_idx + 1)
            self._save_and_reload(doc, target_page=pages[0], selected_pages=pages)
        except Exception as exc:
            show_error(self, exc)

    def _reverse_pages(self, pages: list[int]) -> None:
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            n = doc.page_count
            if n <= 1:
                doc.close()
                return
            order = list(range(n))
            if len(pages) > 1:
                sub_order = list(reversed(pages))
                for orig_idx, rev_idx in zip(pages, sub_order):
                    order[orig_idx] = rev_idx
            else:
                order = list(reversed(order))
            new_doc = fitz.open()
            for idx in order:
                new_doc.insert_pdf(doc, from_page=idx, to_page=idx)
            doc.close()
            self._save_and_reload(new_doc, target_page=pages[0] if pages else 0, selected_pages=pages)
        except Exception as exc:
            show_error(self, exc)

    def _swap_page_dialog(self, page_idx: int) -> None:
        total = self._fitz_doc.page_count if self._fitz_doc else 1
        target, ok = QInputDialog.getInt(
            self, "Swap Pages",
            f"Swap page {page_idx + 1} with page (1-{total}):",
            min(total, max(1, page_idx + 2)), 1, total, 1
        )
        if not ok or target == page_idx + 1:
            return
        try:
            target_idx = target - 1
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            order = list(range(doc.page_count))
            order[page_idx], order[target_idx] = order[target_idx], order[page_idx]
            new_doc = fitz.open()
            for idx in order:
                new_doc.insert_pdf(doc, from_page=idx, to_page=idx)
            doc.close()
            self._save_and_reload(new_doc, target_page=target_idx, selected_pages=[target_idx])
        except Exception as exc:
            show_error(self, exc)

    def _move_page_dialog(self, pages: list[int]) -> None:
        total = self._fitz_doc.page_count if self._fitz_doc else 1
        page_str = ", ".join(str(p + 1) for p in pages)
        dest, ok = QInputDialog.getInt(
            self, "Move Pages",
            f"Move page(s) {page_str} to position (1-{total}):",
            min(total, max(1, max(pages) + 2)), 1, total, 1
        )
        if not ok:
            return
        try:
            dest_idx = dest - 1
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            order = [i for i in range(doc.page_count) if i not in pages]
            dest_clamped = max(0, min(dest_idx, len(order)))
            for i, p in enumerate(pages):
                order.insert(dest_clamped + i, p)
            new_doc = fitz.open()
            for idx in order:
                new_doc.insert_pdf(doc, from_page=idx, to_page=idx)
            doc.close()
            new_selected = list(range(dest_clamped, dest_clamped + len(pages)))
            self._save_and_reload(new_doc, target_page=dest_clamped, selected_pages=new_selected)
        except Exception as exc:
            show_error(self, exc)

    def _replace_page_dialog(self, page_idx: int) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Replace with PDF", DESKTOP, t("file_filter.pdf"))
        if not p or not os.path.isfile(p):
            return
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            src = fitz.open(p)
            doc.insert_pdf(src, from_page=0, to_page=0, start_at=page_idx)
            doc.delete_page(page_idx + 1)
            src.close()
            self._save_and_reload(doc, target_page=page_idx, selected_pages=[page_idx])
        except Exception as exc:
            show_error(self, exc)

    def _resize_pages_dialog(self, pages: list[int]) -> None:
        sizes = {
            "A4 (595 × 842 pt)": (595.0, 842.0),
            "Letter (612 × 792 pt)": (612.0, 792.0),
            "A3 (842 × 1191 pt)": (842.0, 1191.0),
            "A5 (420 × 595 pt)": (420.0, 595.0),
        }
        item, ok = QInputDialog.getItem(
            self, "Resize Pages", f"Select page size for {len(pages)} page(s):", list(sizes.keys()), 0, False
        )
        if not ok or item not in sizes:
            return
        try:
            new_w, new_h = sizes[item]
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            for p_idx in pages:
                if 0 <= p_idx < doc.page_count:
                    doc[p_idx].set_mediabox(fitz.Rect(0, 0, new_w, new_h))
            self._save_and_reload(doc, target_page=pages[0] if pages else 0, selected_pages=pages)
        except Exception as exc:
            show_error(self, exc)

    def _copy_page_content(self, pages: list[int]) -> None:
        if not self._fitz_doc:
            return
        texts = []
        for p_idx in pages:
            if 0 <= p_idx < self._fitz_doc.page_count:
                t_str = self._fitz_doc[p_idx].get_text("text").strip()
                if t_str:
                    texts.append(t_str)
        if texts:
            combined = "\n\n--- Page Break ---\n\n".join(texts)
            QApplication.clipboard().setText(combined)
            win = self.window()
            if hasattr(win, "_set_status"):
                win._set_status(f"✔ Copied text from {len(texts)} page(s) to clipboard")

    def _paste_page_content(self, page_idx: int) -> None:
        text = QApplication.clipboard().text().strip()
        if not text:
            return
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            page = doc[page_idx]
            page.insert_textbox(page.rect.adjusted(36, 36, -36, -36), text, fontsize=11, fontname="helv")
            self._save_and_reload(doc, target_page=page_idx, selected_pages=[page_idx])
        except Exception as exc:
            show_error(self, exc)

    def _show_properties_dialog(self) -> None:
        if not self._current_path or not os.path.isfile(self._current_path):
            return
        win = self.window()
        if hasattr(win, "_open_tool_by_name"):
            win._open_tool_by_name(t("nav.info"))

    def _trigger_crop_tool(self, pages: list[int] | None = None) -> None:
        win = self.window()
        if hasattr(win, "_open_tool_by_name"):
            win._open_tool_by_name(t("nav.crop"))
            if pages and hasattr(win, "stack") and hasattr(win, "_crop_tool_idx"):
                crop_idx = win._crop_tool_idx()
                if crop_idx >= 0:
                    crop_w = win.stack.widget(crop_idx)
                    if hasattr(crop_w, "cmb_page_mode") and hasattr(crop_w, "edit_custom_pages"):
                        crop_w.cmb_page_mode.setCurrentIndex(2)
                        crop_w.edit_custom_pages.setText(",".join(str(p + 1) for p in pages))

    def _trigger_page_numbers_tool(self, pages: list[int] | None = None) -> None:
        win = self.window()
        if hasattr(win, "_open_tool_by_name"):
            win._open_tool_by_name(t("nav.page_numbers"))
            if pages and hasattr(win, "stack"):
                for i in range(win.stack.count()):
                    w = win.stack.widget(i)
                    if hasattr(w, "edit_pages") and hasattr(w, "spin_start_page"):
                        w.edit_pages.setText(",".join(str(p + 1) for p in pages))
                        break

    def _trigger_split_tool(self) -> None:
        win = self.window()
        if hasattr(win, "_open_tool_by_name"):
            win._open_tool_by_name(t("nav.split"))

    def _toggle_night_mode(self):
        self._canvas.set_night_mode(self._night_btn.isChecked())

    def _on_doc_replaced(self, new_doc):
        self._fitz_doc = new_doc

    def _reset_search_state(self):
        self._search_debounce.stop()
        self._pending_search_query = ""
        self._close_search()

    def _reset_to_placeholder(self):
        self._current_path = ""
        self._fitz_doc = None
        self._reset_search_state()
        self.set_crop_mode(False)
        self.set_crop_preview(None)
        self.set_page_crops({})
        self._placeholder.setVisible(True)
        self._viewer_splitter.setVisible(False)
        self._sidebar_panel.setVisible(False)
        self._name_lbl.setText(t("viewer.title"))
        self._page_lbl.setText("— / —")
        self._zoom_lbl.setText(t("zoom.fit"))
        self._toc_btn.setVisible(False)
        self._night_btn.setChecked(False)
        self.set_page_rotations({})
        for btn in (self._zoom_out_btn, self._zoom_in_btn, self._fit_btn,
                    self._print_btn, self._night_btn, self._prev_btn,
                    self._next_btn, self._toc_btn):
            btn.setEnabled(False)
        self._refresh_recents()

    def load(self, path: str, target_page: int = 0, target_scroll: int = -1, selected_pages: list[int] | None = None, active_sidebar_tab: QWidget | int | None = None):
        print(f"[PDFApps] Loading: {path}")
        _log.info("Loading PDF in panel: %s", path)
        if not path:
            return

        resolved = path
        if not os.path.isfile(resolved):
            if os.path.isfile(resolved + ".pdf"):
                resolved = resolved + ".pdf"
        if not os.path.isfile(resolved):
            _log.error("Could not load PDF, file does not exist: %s", path)
            QMessageBox.warning(self, t("msg.error"), f"{t('viewer.error_open')}:\n{path}\n\nFile not found.")
            return

        path = resolved

        is_pdf_format = path.lower().endswith(".pdf")
        if not is_pdf_format:
            try:
                with open(path, "rb") as f:
                    header = f.read(1024)
                    if b"%PDF-" in header:
                        is_pdf_format = True
            except Exception:
                is_pdf_format = False

        if not is_pdf_format:
            _log.warning("Invalid PDF format: %s", path)
            QMessageBox.warning(self, t("viewer.invalid_format"),
                                t("viewer.invalid_msg"))
            return

        if self._fitz_doc:
            self._canvas.close_doc()
            self._fitz_doc = None
            self._reset_search_state()
            self._thumbnails.clear()
            self._clear_pdf_password()
        try:
            doc = fitz.open(path)
        except Exception as ex:
            _log.exception("Error opening PDF: %s", path)
            QMessageBox.critical(self, t("viewer.error_open"),
                                 t("viewer.error_open_msg", ex=ex))
            return
        self._pdf_password = ""
        if doc.needs_pass:
            from app.editor.dialogs import _PdfPasswordDialog
            wrong = False
            while True:
                dlg = _PdfPasswordDialog(os.path.basename(path), wrong=wrong, parent=self)
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    doc.close()
                    self._reset_to_placeholder()
                    return
                winner = authenticate_fitz(doc, dlg.password())
                if winner is not None:
                    self._pdf_password = winner
                    break
                wrong = True
        self._current_path = path
        self._fitz_doc     = doc
        self.set_page_rotations({})
        self.set_crop_preview(None)
        self.set_page_crops({})
        self._canvas.load(doc, target_page, path=path, password=getattr(self, "_pdf_password", ""), target_scroll=target_scroll)
        if target_scroll >= 0:
            self._canvas_scroll.verticalScrollBar().setValue(target_scroll)
        elif target_page > 0 and target_page < doc.page_count:
            self._canvas_scroll.verticalScrollBar().setValue(self._canvas.scroll_to_page(target_page))
        else:
            self._canvas_scroll.verticalScrollBar().setValue(0)

        self._placeholder.setVisible(False)
        self._viewer_splitter.setVisible(True)

        show_pages = getattr(PdfViewerPanel, "_pages_sidebar_visible_pref", True)
        if show_pages is None:
            show_pages = True
        self._pages_sidebar_collapsed = not show_pages
        self._sidebar_panel.setVisible(show_pages)
        self._sidebar_tabs.setVisible(show_pages)
        total = self._viewer_splitter.width() or 1020
        if show_pages:
            w = min(400, max(180, getattr(self, "_saved_sidebar_width", 220)))
            self._viewer_splitter.setSizes([w, max(300, total - w)])
        else:
            self._viewer_splitter.setSizes([0, total])

        display_name = os.path.basename(path)
        win = self.window()
        if win and hasattr(win, "_pipeline_state"):
            ps = win._pipeline_state.get(id(self))
            if ps and ps.get("original_path"):
                display_name = f"● {os.path.basename(ps['original_path'])}"
        self._name_lbl.setText(display_name)

        self._zoom_lbl.setText(t("zoom.fit"))
        for btn in (self._zoom_out_btn, self._zoom_in_btn, self._fit_btn,
                    self._print_btn, self._night_btn):
            btn.setEnabled(True)
        self._toc_btn.setVisible(True)
        self._toc_btn.setEnabled(True)
        self._thumbnails.set_document(
            path, doc.page_count,
            password=getattr(self, "_pdf_password", ""))

        if selected_pages:
            self._thumbnails.set_selected_pages(selected_pages)
        else:
            self._thumbnails.set_current_page(target_page)

        self._populate_toc(doc, active_sidebar_tab=active_sidebar_tab)
        if isinstance(active_sidebar_tab, QWidget) and self._sidebar_tabs.indexOf(active_sidebar_tab) != -1:
            self._sidebar_tabs.setCurrentWidget(active_sidebar_tab)
        elif isinstance(active_sidebar_tab, int) and 0 <= active_sidebar_tab < self._sidebar_tabs.count():
            self._sidebar_tabs.setCurrentIndex(active_sidebar_tab)

        self._update_page_label()
        _log.info("Successfully opened: %s (%d pages)", path, doc.page_count)

    # ── Search ──────────────────────────────────────────────────────────
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

    # ── Navigation ────────────────────────────────────────────────────────
    def _update_page_label(self):
        pages = self._canvas._entries
        if not pages:
            self._page_lbl.setText("— / —")
            self._prev_btn.setEnabled(False)
            self._next_btn.setEnabled(False)
            return
        sb_val = self._viewer._canvas_scroll.verticalScrollBar().value() if hasattr(self, "_viewer") else self._canvas_scroll.verticalScrollBar().value()
        idx = self._canvas.page_at_y(sb_val)
        total = len(pages)
        self._page_lbl.setText(f"{idx + 1} / {total}")
        self._prev_btn.setEnabled(idx > 0)
        self._next_btn.setEnabled(idx < total - 1)
        self._thumbnails.set_current_page(idx)

    def _prev_page(self):
        if not self._canvas._entries:
            return
        sb = self._canvas_scroll.verticalScrollBar()
        idx = self._canvas.page_at_y(sb.value())
        if idx > 0:
            sb.setValue(self._canvas.scroll_to_page(idx - 1))

    def _next_page(self):
        if not self._canvas._entries:
            return
        sb = self._canvas_scroll.verticalScrollBar()
        idx = self._canvas.page_at_y(sb.value())
        if idx < len(self._canvas._entries) - 1:
            sb.setValue(self._canvas.scroll_to_page(idx + 1))

    # ── Zoom ─────────────────────────────────────────────────────────────────
    def _zoom_fit(self):
        self._canvas.zoom_reset()
        self._zoom_lbl.setText(t("zoom.fit"))

    # ── Print ────────────────────────────────────────────────────────────────
    def _print_pdf(self, page_indices: list[int] | None = None):
        doc = self._fitz_doc
        if doc is None or getattr(doc, "is_closed", False):
            return
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        from PySide6.QtGui import QImage
        from PySide6.QtCore import QRectF
        from PySide6.QtWidgets import QProgressDialog

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
            reverse = (printer.pageOrder()
                       == QPrinter.PageOrder.LastPageFirst)
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

    # ── Password lifecycle ──────────────────────────────────────────────
    def _clear_pdf_password(self) -> None:
        from app.utils import wipe_pdf_password
        wipe_pdf_password(self)

    def closeEvent(self, event):
        self._clear_pdf_password()
        try:
            self._thumbnails.clear()
        except Exception:
            pass
        super().closeEvent(event)