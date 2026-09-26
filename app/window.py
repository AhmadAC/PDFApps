# app/window.py

"""PDFApps – MainWindow: application main window."""
import contextlib
import os
import sys

from PySide6.QtCore import Qt, QSize, QTimer, QPoint
from PySide6.QtGui import QIcon, QColor, QShortcut, QKeySequence, QMouseEvent
from shiboken6 import isValid
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QStackedWidget, QSplitter, QStatusBar,
    QFrame, QApplication, QLineEdit, QMenu, QTabBar, QFileDialog, QMessageBox,
)
import qtawesome as qta
import fitz

from app.constants import ACCENT, TEXT_PRI, TEXT_SEC, _LQ, DESKTOP, BORDER
from app.i18n import t, set_language, get_language, add_recent_file
from app.styles import STYLE, STYLE_LIGHT
from app.utils import resource_path, _make_palette, show_error, reveal_file
from app.widgets import DropFileEdit, MultiDropWidget
from app.single_instance import SingleInstanceServer
from app.update_controller import UpdateController
from app.viewer.panel import PdfViewerPanel
from app.base import BasePage
from app.tools.rotate import TabRotar
from app.tools.crop import TabCortar
from app.editor.tab import TabEditar
from app.workspace_bar import WorkspaceBar
from app.nav_config import _NAV_GROUPS, _NAV_KEYS, NAV_ITEMS


class _ViewerTabBar(QTabBar):
    """Custom tab bar supporting middle-click (mouse wheel click) to close tabs."""

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            idx = self.tabAt(pos)
            if idx >= 0:
                self.tabCloseRequested.emit(idx)
                event.accept()
                return
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("app.name"))
        _ico_path = resource_path("icon.ico")
        if os.path.exists(_ico_path):
            self.setWindowIcon(QIcon(_ico_path))
        else:
            _svg = resource_path("pdfapps.svg")
            if os.path.exists(_svg):
                self.setWindowIcon(QIcon(_svg))
        self.resize(1220, 700)
        self.setMinimumSize(860, 540)

        self._sb = QStatusBar(); self.setStatusBar(self._sb)
        self._sb.showMessage(t("app.ready"))
        self.setAcceptDrops(True)

        central = QWidget()
        root_v = QVBoxLayout(central)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)

        # ── Workspace Bar Component ──────────────────────────────────────────
        self._workspace_bar = WorkspaceBar(self)
        wb = self._workspace_bar
        self._sidebar_toggle_btn = wb._sidebar_toggle_btn
        self._pages_toggle_btn = wb._pages_toggle_btn
        self._right_pane_toggle_btn = wb._right_pane_toggle_btn
        self._breadcrumb = wb._breadcrumb
        self._open_pdf_btn = wb._open_pdf_btn
        self._toc_top_btn = wb._toc_top_btn
        self._night_top_btn = wb._night_top_btn
        self._print_top_btn = wb._print_top_btn
        self._present_btn = wb._present_btn
        self._search_top_btn = wb._search_top_btn
        self._zoom_widget = wb._zoom_widget
        self._zm_btn = wb._zm_btn
        self._lbl_zoom = wb._lbl_zoom
        self._zp_btn = wb._zp_btn
        self._z0_btn = wb._z0_btn
        self._page_nav_widget = wb._page_nav_widget
        self._first_pg_btn = wb._first_pg_btn
        self._prev_pg_btn = wb._prev_pg_btn
        self._page_input = wb._page_input
        self._page_total_lbl = wb._page_total_lbl
        self._next_pg_btn = wb._next_pg_btn
        self._last_pg_btn = wb._last_pg_btn
        self._undo_top_btn = wb._undo_top_btn
        self._redo_top_btn = wb._redo_top_btn
        self._help_btn = wb._help_btn
        self._lang_btn = wb._lang_btn
        self._theme_btn = wb._theme_btn
        self._update_btn = wb._update_btn

        # Wire top bar events
        self._sidebar_toggle_btn.clicked.connect(self._toggle_sidebar)
        self._pages_toggle_btn.clicked.connect(self._toggle_pages_sidebar)
        self._right_pane_toggle_btn.clicked.connect(self._toggle_right_pane)
        self._open_pdf_btn.clicked.connect(self._open_pdf)
        self._toc_top_btn.clicked.connect(self._toggle_pages_sidebar)
        self._night_top_btn.clicked.connect(self._toggle_night_mode_top)
        self._print_top_btn.clicked.connect(lambda: self._viewer._print_pdf())
        self._present_btn.clicked.connect(self._start_presentation)
        self._search_top_btn.clicked.connect(lambda: self._viewer._toggle_search())
        self._first_pg_btn.clicked.connect(self._goto_first_page)
        self._prev_pg_btn.clicked.connect(self._goto_prev_page)
        self._next_pg_btn.clicked.connect(self._goto_next_page)
        self._last_pg_btn.clicked.connect(self._goto_last_page)
        self._page_input.returnPressed.connect(self._goto_input_page)
        self._help_btn.clicked.connect(lambda: __import__('webbrowser').open("https://pdf-apps.com/docs#first-steps"))
        self._lang_btn.clicked.connect(self._show_language_menu)
        self._theme_btn.clicked.connect(self._toggle_theme)

        self._update_controller = UpdateController(self, self._update_btn)
        self._update_btn.clicked.connect(self._update_controller.show_update_dialog)
        QTimer.singleShot(2000, lambda: self._update_controller.check_async() if isValid(self) else None)

        root_v.addWidget(self._workspace_bar)

        body = QWidget(); body.setObjectName("workspace_shell")
        main_h = QHBoxLayout(body)
        main_h.setContentsMargins(10, 10, 10, 0)
        main_h.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────────
        self._sidebar = QWidget(); self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(228)
        sb_lay  = QVBoxLayout(self._sidebar)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(0)

        brand = QWidget(); brand.setObjectName("brand_area")
        self._brand_layout = bh = QHBoxLayout(brand)
        bh.setContentsMargins(12, 10, 10, 10); bh.setSpacing(8)
        ico_lbl = QLabel()
        from PySide6.QtGui import QPixmap as _QPixmap, QPainter, QImage
        from PySide6.QtSvg import QSvgRenderer
        _svg_path = resource_path("pdfapps.svg")
        _h = 36
        dpr = self.devicePixelRatioF() if hasattr(self, 'devicePixelRatioF') else 1.0
        if dpr <= 0:
            dpr = 1.0
        if os.path.exists(_svg_path):
            renderer = QSvgRenderer(_svg_path)
            vb = renderer.viewBox()
            ratio = vb.width() / vb.height() if vb.height() else 1.0
            _w = int(_h * ratio)
            img = QImage(int(_w * dpr), int(_h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            p = QPainter(img); renderer.render(p); p.end()
            _app_pix = _QPixmap.fromImage(img)
            _app_pix.setDevicePixelRatio(dpr)
        else:
            _w = _h
            _ico_path = resource_path("icon.ico")
            _app_pix = _QPixmap(_ico_path).scaled(
                int(_w * dpr), int(_h * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            _app_pix.setDevicePixelRatio(dpr)
        ico_lbl.setPixmap(_app_pix); ico_lbl.setObjectName("app_icon")
        ico_lbl.setFixedSize(_w, _h); ico_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bh.addWidget(ico_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        self._brand_text_w = QWidget()
        brand_text = QVBoxLayout(self._brand_text_w)
        brand_text.setContentsMargins(0, 0, 0, 0); brand_text.setSpacing(1)
        self._brand_title = QLabel(t("app.name")); self._brand_title.setObjectName("app_title")
        self._brand_sub = QLabel(t("app.subtitle")); self._brand_sub.setObjectName("app_sub")
        brand_text.addWidget(self._brand_title); brand_text.addWidget(self._brand_sub)
        bh.addWidget(self._brand_text_w, 1)
        sb_lay.addWidget(brand)

        sep = QFrame(); sep.setObjectName("nav_sep"); sep.setFixedHeight(1)
        sb_lay.addWidget(sep)

        self._nav_search = QLineEdit()
        self._nav_search.setPlaceholderText("🔍 " + t("nav.search"))
        self._nav_search.setClearButtonEnabled(True)
        self._nav_search.setObjectName("nav_search")
        self._nav_search.textChanged.connect(self._filter_nav)
        sb_lay.addWidget(self._nav_search)

        self.nav = QListWidget(); self.nav.setObjectName("nav_list")
        self.nav.setSpacing(0); self.nav.setIconSize(QSize(18, 18))
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if self.nav.verticalScrollBar():
            self.nav.verticalScrollBar().setFixedWidth(0)
            self.nav.verticalScrollBar().setMaximumWidth(0)
            self.nav.verticalScrollBar().setStyleSheet("width: 0px; max-width: 0px; border: none; background: transparent;")

        self._tool_usage = {}
        try:
            from app.i18n import _CONFIG_PATH
            import json
            with open(_CONFIG_PATH, "r", encoding="utf-8") as _cf:
                self._tool_usage = json.load(_cf).get("tool_usage", {})
        except Exception:
            pass

        sorted_usage = sorted(self._tool_usage.items(), key=lambda x: x[1], reverse=True)
        freq_tools = [(k, v) for k, v in sorted_usage if v >= 2][:3]
        if freq_tools:
            hdr = QListWidgetItem(t("nav.group.frequent").upper())
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            hdr.setData(Qt.ItemDataRole.UserRole, -1)
            hdr.setForeground(QColor(ACCENT))
            from PySide6.QtGui import QFont as _QF
            f = _QF(); f.setPointSize(9); f.setBold(True); f.setLetterSpacing(_QF.SpacingType.AbsoluteSpacing, 1.5)
            hdr.setFont(f); hdr.setSizeHint(QSize(0, 26))
            self.nav.addItem(hdr)
            for nav_key, _count in freq_tools:
                for idx, (key, icon_name, _) in enumerate(_NAV_KEYS):
                    if key == nav_key:
                        item = QListWidgetItem(qta.icon(icon_name, color=ACCENT), t(key))
                        item.setData(Qt.ItemDataRole.UserRole, idx)
                        self.nav.addItem(item)
                        break

        tool_idx = 0
        for group_key, tools in _NAV_GROUPS:
            if tool_idx > 0:
                sep_item = QListWidgetItem()
                sep_item.setFlags(Qt.ItemFlag.NoItemFlags)
                sep_item.setData(Qt.ItemDataRole.UserRole, -1)
                sep_item.setSizeHint(QSize(0, 24))
                self.nav.addItem(sep_item)
                sep_line = QFrame(); sep_line.setFixedHeight(1)
                sep_line.setStyleSheet(f"background:{BORDER}; margin: 0 8px 0 4px;")
                self.nav.setItemWidget(sep_item, sep_line)

            hdr = QListWidgetItem(t(group_key).upper())
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            hdr.setData(Qt.ItemDataRole.UserRole, -1)
            hdr.setForeground(QColor(TEXT_SEC))
            from PySide6.QtGui import QFont as _QF
            f = _QF(); f.setPointSize(9); f.setBold(True); f.setLetterSpacing(_QF.SpacingType.AbsoluteSpacing, 1.5)
            hdr.setFont(f); hdr.setSizeHint(QSize(0, 26))
            self.nav.addItem(hdr)
            for key, icon_name, _ in tools:
                item = QListWidgetItem(qta.icon(icon_name, color=TEXT_SEC), t(key))
                item.setData(Qt.ItemDataRole.UserRole, tool_idx)
                desc_key = key.replace("nav.", "tool.") + ".desc"
                tip = t(desc_key)
                if tip != desc_key:
                    item.setToolTip(tip)
                self.nav.addItem(item)
                tool_idx += 1
        sb_lay.addWidget(self.nav, 1)

        self._footer_w = QWidget(); self._footer_w.setObjectName("sidebar")
        footer_h = QHBoxLayout(self._footer_w)
        footer_h.setContentsMargins(14, 8, 14, 10); footer_h.setSpacing(0)
        from app.constants import APP_VERSION
        footer_lbl = QLabel(f"v{APP_VERSION}  ·  {t('app.credits')}"); footer_lbl.setObjectName("sidebar_footer")
        footer_h.addWidget(footer_lbl, 1)
        sb_lay.addWidget(self._footer_w)
        self._sidebar_collapsed = False

        self._dark_mode = True
        try:
            from app.i18n import _CONFIG_PATH
            import json
            with open(_CONFIG_PATH, "r", encoding="utf-8") as _cf:
                self._dark_mode = json.load(_cf).get("dark_mode", True)
        except Exception:
            pass
        self._qapp: QApplication = QApplication.instance()

        # ── Tool Stack & Right Tool Container ────────────────────────────────
        self.stack = QStackedWidget(); self.stack.setObjectName("content_area")
        for _, __, cls in NAV_ITEMS:
            self.stack.addWidget(cls(self._set_status))
        self.stack.setVisible(False)

        self._right_tool_container = QWidget()
        self._right_tool_container.setObjectName("right_tool_container")
        rc_lay = QVBoxLayout(self._right_tool_container)
        rc_lay.setContentsMargins(0, 0, 0, 0)
        rc_lay.setSpacing(0)
        rc_lay.addWidget(self.stack, 1)
        self._right_tool_container.setVisible(False)
        self._saved_right_width = 400

        # ── Tabbed Viewer ────────────────────────────────────────────────────
        self._tab_container = QWidget()
        tc_lay = QVBoxLayout(self._tab_container); tc_lay.setContentsMargins(0, 0, 0, 0); tc_lay.setSpacing(0)

        tab_row = QHBoxLayout(); tab_row.setContentsMargins(0, 0, 0, 0); tab_row.setSpacing(0)
        self._tab_bar = _ViewerTabBar()
        self._tab_bar.setTabsClosable(True)
        self._tab_bar.setMovable(True)
        self._tab_bar.setExpanding(False)
        self._tab_bar.setObjectName("viewer_tabs")
        self._tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tab_bar.customContextMenuRequested.connect(self._on_tab_context_menu)
        self._current_tool = -1
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        self._tab_bar.tabCloseRequested.connect(self._close_tab)
        self._tab_bar.setVisible(False)
        tab_row.addWidget(self._tab_bar, 1)
        tc_lay.addLayout(tab_row)

        self._viewer_stack = QStackedWidget()
        self._viewers: list[PdfViewerPanel] = []
        self._add_viewer_tab()
        tc_lay.addWidget(self._viewer_stack, 1)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(1); self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._tab_container)
        self._splitter.addWidget(self._right_tool_container)
        self._splitter.setCollapsible(0, False); self._splitter.setCollapsible(1, False)
        self._splitter.setSizes([1200, 0])

        main_h.addWidget(self._sidebar)
        main_h.addWidget(self._splitter, 1)
        root_v.addWidget(body, 1)
        self.setCentralWidget(central)

        try:
            from app.i18n import _CONFIG_PATH
            import json
            with open(_CONFIG_PATH, "r", encoding="utf-8") as _cf:
                _saved = json.load(_cf)
            mode = _saved.get("sidebar_mode")
            if mode == "icons":
                self._toggle_sidebar()
            elif mode == "hidden":
                self._toggle_sidebar(); self._toggle_sidebar()
            pages_pref = _saved.get("pages_sidebar_open")
            if pages_pref is not None:
                PdfViewerPanel._pages_sidebar_visible_pref = bool(pages_pref)
        except Exception:
            pass

        self._current_tool = -1
        self.nav.itemClicked.connect(self._on_nav_clicked)
        for i in range(self.stack.count()):
            for dfe in self.stack.widget(i).findChildren(DropFileEdit):
                if not dfe._save:
                    dfe.path_changed.connect(lambda p: self._viewer.load(p) if p and os.path.isfile(p) else None)

        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if isinstance(w, BasePage):
                w.pipeline_done.connect(self._on_pipeline_done)
                w.pipeline_save_requested.connect(self._save_pipeline)
            if isinstance(w, TabRotar):
                w.rotations_changed.connect(self._on_rotations_changed)
            if isinstance(w, TabCortar):
                w.crop_changed.connect(self._on_crop_changed)
                w.crops_changed.connect(self._on_crops_changed)
                w.crop_mode_toggled.connect(self._on_crop_mode_toggled)

        self._pipeline_state: dict[int, dict] = {}

        QShortcut(QKeySequence("F5"), self, self._start_presentation)
        QShortcut(QKeySequence("F11"), self, self._toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+O"), self, self._open_pdf)
        QShortcut(QKeySequence("Ctrl+P"), self, lambda: self._viewer._print_pdf())
        sc_close = QShortcut(QKeySequence("Ctrl+W"), self, self._close_current_tab)
        sc_save  = QShortcut(QKeySequence("Ctrl+S"), self, self._save_current_tool)
        sc_pgup  = QShortcut(QKeySequence("PgUp"), self, self._goto_prev_page)
        sc_pgdn  = QShortcut(QKeySequence("PgDown"), self, self._goto_next_page)
        for sc in (sc_close, sc_save, sc_pgup, sc_pgdn):
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        assert len(NAV_ITEMS) <= 18, f"Max 18 tool shortcuts defined but NAV_ITEMS has {len(NAV_ITEMS)}."
        for idx in range(len(NAV_ITEMS)):
            if idx < 9:
                QShortcut(QKeySequence(f"Ctrl+{idx+1}"), self, lambda i=idx: self._activate_tool(i))
            elif idx < 18:
                QShortcut(QKeySequence(f"Ctrl+Shift+{idx-8}"), self, lambda i=idx: self._activate_tool(i))
        self._fullscreen = False

        if not self._dark_mode:
            self._apply_theme()

        self._instance_server = SingleInstanceServer(self)
        self._instance_server.new_paths.connect(self._on_second_instance)

    # ── Tab Right-Click Context Menu ─────────────────────────────────────

    def _on_tab_context_menu(self, pos: QPoint):
        idx = self._tab_bar.tabAt(pos)
        if idx < 0 or idx >= len(self._viewers):
            return

        viewer = self._viewers[idx]
        path = viewer.current_path()
        if not path:
            return

        dark = self._dark_mode
        c = TEXT_PRI if dark else _LQ

        menu = QMenu(self)

        # 1. Clipboard options
        act_copy_path = menu.addAction(qta.icon("fa5s.copy", color=c), "Copy Full Path")
        act_copy_name = menu.addAction(qta.icon("fa5s.file", color=c), "Copy File Name")
        menu.addSeparator()

        # 2. Explorer / Finder actions
        reveal_label = "Reveal in File Explorer" if sys.platform == "win32" else ("Reveal in Finder" if sys.platform == "darwin" else "Show in File Manager")
        act_reveal = menu.addAction(qta.icon("fa5s.folder-open", color=c), reveal_label)
        menu.addSeparator()

        # 3. Tab management
        act_close = menu.addAction(qta.icon("fa5s.times", color="#EF4444"), "Close Tab")
        act_close_others = menu.addAction("Close Other Tabs")

        action = menu.exec(self._tab_bar.mapToGlobal(pos))
        if not action:
            return

        if action == act_copy_path:
            QApplication.clipboard().setText(os.path.normpath(path))
            self._set_status(f"✔ Copied path to clipboard: {os.path.normpath(path)}")
        elif action == act_copy_name:
            name = os.path.basename(path)
            QApplication.clipboard().setText(name)
            self._set_status(f"✔ Copied file name to clipboard: {name}")
        elif action == act_reveal:
            reveal_file(path)
        elif action == act_close:
            self._close_tab(idx)
        elif action == act_close_others:
            self._close_other_tabs(idx)

    def _close_other_tabs(self, keep_idx: int):
        total = len(self._viewers)
        for i in range(total - 1, -1, -1):
            if i != keep_idx:
                self._close_tab(i)

    def _toggle_pages_sidebar(self):
        v = self._viewer
        if hasattr(v, "_toggle_pages_sidebar"):
            v._toggle_pages_sidebar()
        elif hasattr(v, "_sidebar_panel"):
            is_vis = v._sidebar_panel.isVisible()
            v._sidebar_panel.setVisible(not is_vis)
            if not is_vis:
                w = min(400, max(180, getattr(v, "_saved_sidebar_width", 220)))
                total = v._viewer_splitter.width()
                v._viewer_splitter.setSizes([w, max(300, total - w)])
            else:
                total = v._viewer_splitter.width()
                v._viewer_splitter.setSizes([0, total])

    def _toggle_right_pane(self):
        if self._current_tool < 0:
            return
        edit_idx = self._edit_tool_idx()
        if self._current_tool == edit_idx:
            edit_w = self.stack.widget(edit_idx)
            if hasattr(edit_w, "toggle_controls"):
                edit_w.toggle_controls()
            elif hasattr(edit_w, "_ctrl_scroll"):
                is_vis = edit_w._ctrl_scroll.isVisible()
                edit_w._ctrl_scroll.setVisible(not is_vis)
            return

        is_visible = self._right_tool_container.isVisible()
        if is_visible:
            self._saved_right_width = max(320, self._right_tool_container.width())
            self._right_tool_container.setVisible(False)
            self.stack.setVisible(False)
            total = self._splitter.width()
            self._splitter.setSizes([total, 0])
        else:
            self._right_tool_container.setVisible(True)
            self.stack.setVisible(True)
            tool_w = min(600, max(320, getattr(self, "_saved_right_width", 400)))
            total = self._splitter.width()
            self._splitter.setSizes([max(300, total - tool_w), tool_w])

    @property
    def _viewer(self) -> PdfViewerPanel:
        idx = self._viewer_stack.currentIndex()
        if 0 <= idx < len(self._viewers):
            return self._viewers[idx]
        return self._viewers[0]

    def _rotate_tool_idx(self) -> int:
        return next(i for i, (_, __, cls) in enumerate(NAV_ITEMS) if cls is TabRotar)

    def _crop_tool_idx(self) -> int:
        return next(i for i, (_, __, cls) in enumerate(NAV_ITEMS) if cls is TabCortar)

    def _on_rotations_changed(self, rotations: dict):
        self._viewer.set_page_rotations(rotations)

    def _on_crop_changed(self, crop_data: dict):
        self._viewer.set_crop_preview(crop_data)

    def _on_crops_changed(self, crops: dict):
        self._viewer.set_page_crops(crops)

    def _on_crop_mode_toggled(self, active: bool):
        if self._current_tool == self._crop_tool_idx():
            self._viewer.set_crop_mode(active)

    def _on_viewer_crop_selected(self, page_idx: int, rect: tuple):
        if self._current_tool == self._crop_tool_idx():
            crop_w = self.stack.widget(self._crop_tool_idx())
            crop_w.on_canvas_crop_selected(page_idx, rect)

    def _on_viewer_crop_applied(self):
        if self._current_tool == self._crop_tool_idx():
            crop_w = self.stack.widget(self._crop_tool_idx())
            crop_w.apply_crop_preview()

    def _on_viewer_crop_undo(self):
        if self._current_tool == self._crop_tool_idx():
            crop_w = self.stack.widget(self._crop_tool_idx())
            crop_w._undo()

    def _on_viewer_crop_redo(self):
        if self._current_tool == self._crop_tool_idx():
            crop_w = self.stack.widget(self._crop_tool_idx())
            crop_w._redo()

    def _add_viewer_tab(self, path: str = "") -> PdfViewerPanel:
        v = PdfViewerPanel()
        self._viewers.append(v)
        self._viewer_stack.addWidget(v)
        idx = self._tab_bar.addTab(t("viewer.title"))
        self._tab_bar.setCurrentIndex(idx)
        self._update_tab_visibility()

        v._canvas_scroll.verticalScrollBar().valueChanged.connect(lambda _: self._update_page_nav())
        v.crop_selected.connect(self._on_viewer_crop_selected)
        v.crop_applied.connect(self._on_viewer_crop_applied)
        v.crop_undo_requested.connect(self._on_viewer_crop_undo)
        v.crop_redo_requested.connect(self._on_viewer_crop_redo)

        original_load = v.load
        def _make_wrapped(viewer, orig):
            def _wrapped(*args, track=True, **kwargs):
                orig(*args, **kwargs)
                if viewer.current_path():
                    curr = viewer.current_path()
                    vid = id(viewer)
                    ps = self._pipeline_state.get(vid)
                    if ps and ps.get("original_path"):
                        orig_path = ps["original_path"]
                        name = f"● {os.path.basename(orig_path)}"
                        tooltip = f"{orig_path} (modified)"
                    else:
                        if track:
                            add_recent_file(curr)
                        name = os.path.basename(curr)
                        tooltip = curr
                    for i in range(len(self._viewers)):
                        if self._viewers[i] is viewer:
                            self._tab_bar.setTabText(i, name)
                            self._tab_bar.setTabToolTip(i, tooltip)
                            break
                    self._refresh_viewer_top_buttons()
                QTimer.singleShot(100, self._update_page_nav)
                self._update_tab_visibility()
                if self._current_tool == -1 and viewer.current_path():
                    self._setup_zoom_bar(True, canvas=viewer._canvas)
            return _wrapped
        v.load = _make_wrapped(v, original_load)
        if path:
            v.load(path)
        return v

    def _update_tab_visibility(self):
        has_doc = any(v.current_path() for v in self._viewers)
        self._tab_bar.setVisible(has_doc)

    def _on_tab_changed(self, idx: int):
        if idx < 0 or idx >= len(self._viewers):
            return
        self._viewer_stack.setCurrentIndex(idx)
        self._update_page_nav()

        v = self._viewer
        if v.current_path():
            show_pages = getattr(PdfViewerPanel, "_pages_sidebar_visible_pref", True)
            if show_pages is not None and v._pages_sidebar_collapsed == show_pages:
                v._pages_sidebar_collapsed = not show_pages
                v._sidebar_panel.setVisible(show_pages)
                v._sidebar_tabs.setVisible(show_pages)
                total = v._viewer_splitter.width() or 1020
                if show_pages:
                    w = min(400, max(180, getattr(v, "_saved_sidebar_width", 220)))
                    v._viewer_splitter.setSizes([w, max(300, total - w)])
                else:
                    v._viewer_splitter.setSizes([0, total])

        if self._current_tool == -1:
            self._setup_zoom_bar(True, canvas=self._viewer._canvas)
        elif self._current_tool == self._rotate_tool_idx():
            rot_w = self.stack.widget(self._rotate_tool_idx())
            rots = getattr(rot_w, "_rotations", {})
            self._viewer.set_page_rotations(rots)
        elif self._current_tool == self._crop_tool_idx():
            crop_w = self.stack.widget(self._crop_tool_idx())
            crop_w._emit_preview()
            self._viewer.set_page_crops(crop_w._applied_crops)
        else:
            self._viewer.set_page_rotations({})
            self._viewer.set_crop_mode(False)
            self._viewer.set_crop_preview(None)
            self._viewer.set_page_crops({})
        self._refresh_viewer_top_buttons()

    def _close_tab(self, idx: int):
        viewer = self._viewers[idx] if idx < len(self._viewers) else self._viewers[0]
        if self._viewer_has_unsaved(viewer):
            ans = QMessageBox.question(
                self, t("msg.warning"), t("pipeline.unsaved_prompt"),
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if ans == QMessageBox.StandardButton.Cancel:
                return
            if ans == QMessageBox.StandardButton.Save:
                self._save_pipeline()
                return
        self._cleanup_pipeline(id(viewer))
        if self._tab_bar.count() <= 1:
            viewer = self._viewers[0]
            viewer._canvas.close_doc()
            self._wipe_password_holder(viewer)
            viewer._fitz_doc = None
            viewer._current_path = ""
            viewer._viewer_splitter.setVisible(False)
            viewer._toc_tree.clear()
            viewer._toc_tree.setVisible(False)
            viewer._toc_btn.setVisible(False)
            viewer._placeholder.setVisible(True)
            viewer._hdr.setVisible(False)
            viewer._name_lbl.setText(t("viewer.title"))
            self._tab_bar.setTabText(0, t("viewer.title"))
            self._tab_bar.setTabToolTip(0, "")
            self._update_tab_visibility()
            self._update_page_nav()
            self._setup_zoom_bar(False)
            self._page_nav_widget.setVisible(False)
            self._refresh_viewer_top_buttons()
            return
        viewer = self._viewers.pop(idx)
        self._tab_bar.removeTab(idx)
        self._viewer_stack.removeWidget(viewer)
        viewer._canvas.close_doc()
        self._wipe_password_holder(viewer)
        viewer.deleteLater()
        self._update_tab_visibility()
        self._update_page_nav()

    def _open_tool_by_name(self, tool_name: str):
        for i, (name, _, _) in enumerate(NAV_ITEMS):
            if name == tool_name or t(name) == tool_name:
                for r in range(self.nav.count()):
                    if self.nav.item(r).data(Qt.ItemDataRole.UserRole) == i:
                        self.nav.setCurrentRow(r)
                        self._on_nav_clicked(self.nav.item(r))
                        return
                self._activate_tool(i)
                return

    def _try_auto_load(self, index: int):
        nav_key = _NAV_KEYS[index][0]
        self._tool_usage[nav_key] = self._tool_usage.get(nav_key, 0) + 1
        with contextlib.suppress(Exception):
            from app.i18n import _update_config
            usage = dict(self._tool_usage)
            _update_config(lambda cfg: cfg.__setitem__("tool_usage", usage))
        widget = self.stack.widget(index)
        path = self._viewer.current_path()
        if path:
            viewer_pwd = getattr(self._viewer, "_pdf_password", "")
            if hasattr(widget, "_pdf_password"):
                widget._pdf_password = viewer_pwd
            fn = getattr(widget, "auto_load", None)
            if callable(fn):
                fn(path)

        compact_fn = getattr(widget, "set_compact_mode", None)
        if callable(compact_fn):
            compact_fn(bool(path), path or "")

    def _edit_tool_idx(self) -> int:
        return next(i for i, (_, __, cls) in enumerate(NAV_ITEMS) if cls is TabEditar)

    def _setup_zoom_bar(self, active: bool, canvas=None):
        self._zoom_widget.setVisible(active)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for btn in (self._zm_btn, self._zp_btn, self._z0_btn):
                try:
                    btn.clicked.disconnect()
                except (RuntimeError, TypeError):
                    pass
        if canvas is None:
            canvas = getattr(self.stack.widget(self._edit_tool_idx()), '_canvas', None)
        if canvas is None:
            return
        if active:
            self._zm_btn.clicked.connect(canvas.zoom_out)
            self._zp_btn.clicked.connect(canvas.zoom_in)
            self._z0_btn.clicked.connect(canvas.zoom_reset)
            canvas.zoom_changed.connect(lambda pct: self._lbl_zoom.setText(f"{pct}%"))
            self._lbl_zoom.setText(f"{round(canvas._zoom_factor * 100)}%")

    def _activate_tool(self, tool_idx: int):
        for r in range(self.nav.count()):
            it = self.nav.item(r)
            if it.data(Qt.ItemDataRole.UserRole) == tool_idx:
                self.nav.setCurrentRow(r)
                self._on_nav_clicked(it)
                return

    def _filter_nav(self, text: str):
        q = text.lower().strip()
        visible_groups = set()
        for r in range(self.nav.count()):
            it = self.nav.item(r)
            tool_idx = it.data(Qt.ItemDataRole.UserRole)
            if tool_idx is not None and tool_idx >= 0:
                match = not q or q in it.text().lower()
                it.setHidden(not match)
                if match:
                    visible_groups.add(r)
        for r in range(self.nav.count()):
            it = self.nav.item(r)
            if it.data(Qt.ItemDataRole.UserRole) == -1:
                has_visible = False
                for r2 in range(r + 1, self.nav.count()):
                    it2 = self.nav.item(r2)
                    if it2.data(Qt.ItemDataRole.UserRole) == -1:
                        break
                    if not it2.isHidden():
                        has_visible = True; break
                it.setHidden(not has_visible)

    def _on_nav_clicked(self, item):
        row = item.data(Qt.ItemDataRole.UserRole)
        if row is None or row < 0:
            self.nav.clearSelection()
            return
        edit_idx = self._edit_tool_idx()
        rotate_idx = self._rotate_tool_idx()
        crop_idx = self._crop_tool_idx()

        if row == self._current_tool:
            self.nav.clearSelection()
            self._current_tool = -1
            self.stack.setVisible(False)
            self._right_tool_container.setVisible(False)
            self._right_pane_toggle_btn.setVisible(False)
            self._pages_toggle_btn.setVisible(True)
            self._tab_container.setVisible(True)
            self._breadcrumb.setText(t("workspace.title"))
            self._setup_zoom_bar(True, canvas=self._viewer._canvas)
            self._undo_top_btn.setVisible(False)
            self._redo_top_btn.setVisible(False)
            self._viewer.set_page_rotations({})
            self._viewer.set_crop_mode(False)
            self._viewer.set_crop_preview(None)
            self._viewer.set_page_crops({})
        else:
            self._setup_zoom_bar(False)
            self._current_tool = row
            self.stack.setCurrentIndex(row)
            self._right_tool_container.setVisible(True)
            self.stack.setVisible(True)
            self._right_pane_toggle_btn.setVisible(True)

            if row == edit_idx:
                self.stack.setMinimumWidth(0)
                self.stack.setMaximumWidth(16777215)
                self._right_tool_container.setMinimumWidth(0)
                self._right_tool_container.setMaximumWidth(16777215)
                self._tab_container.setVisible(False)
                self._pages_toggle_btn.setVisible(False)
                self._setup_zoom_bar(True)
                edit_w = self.stack.widget(edit_idx)
                if hasattr(edit_w, "_ctrl_scroll"):
                    edit_w._ctrl_scroll.setVisible(True)
                self._undo_top_btn.setVisible(True)
                self._redo_top_btn.setVisible(True)
                prev = getattr(self, "_undo_redo_handlers", None)
                if prev is not None:
                    try: self._undo_top_btn.clicked.disconnect(prev[0])
                    except (RuntimeError, TypeError): pass
                    try: self._redo_top_btn.clicked.disconnect(prev[1])
                    except (RuntimeError, TypeError): pass
                self._undo_top_btn.clicked.connect(edit_w._undo)
                self._redo_top_btn.clicked.connect(edit_w._redo)
                self._undo_redo_handlers = (edit_w._undo, edit_w._redo)
                self._viewer.set_page_rotations({})
                self._viewer.set_crop_mode(False)
                self._viewer.set_crop_preview(None)
                self._viewer.set_page_crops({})
            else:
                self._pages_toggle_btn.setVisible(True)
                self.stack.setMinimumWidth(320)
                self.stack.setMaximumWidth(600)
                self._right_tool_container.setMinimumWidth(320)
                self._right_tool_container.setMaximumWidth(600)
                self._tab_container.setVisible(True)
                total = self._splitter.width()
                tool_w = max(380, min(450, total // 3))
                self._splitter.setSizes([total - tool_w, tool_w])

                if row == rotate_idx:
                    rot_w = self.stack.widget(rotate_idx)
                    rots = getattr(rot_w, "_rotations", {})
                    self._viewer.set_page_rotations(rots)
                else:
                    self._viewer.set_page_rotations({})

                if row == crop_idx:
                    crop_w = self.stack.widget(crop_idx)
                    active = crop_w.btn_draw_crop.isChecked()
                    self._viewer.set_crop_mode(active)
                    crop_w._emit_preview()
                    self._viewer.set_page_crops(crop_w._applied_crops)
                    self._undo_top_btn.setVisible(True)
                    self._redo_top_btn.setVisible(True)
                    prev = getattr(self, "_undo_redo_handlers", None)
                    if prev is not None:
                        try: self._undo_top_btn.clicked.disconnect(prev[0])
                        except (RuntimeError, TypeError): pass
                        try: self._redo_top_btn.clicked.disconnect(prev[1])
                        except (RuntimeError, TypeError): pass
                    self._undo_top_btn.clicked.connect(crop_w._undo)
                    self._redo_top_btn.clicked.connect(crop_w._redo)
                    self._undo_redo_handlers = (crop_w._undo, crop_w._redo)
                else:
                    self._viewer.set_crop_mode(False)
                    self._viewer.set_crop_preview(None)
                    self._viewer.set_page_crops({})
                    self._undo_top_btn.setVisible(False)
                    self._redo_top_btn.setVisible(False)

            self._breadcrumb.setText(f"{t('workspace.title')}  ›  {NAV_ITEMS[row][0]}")
            self._try_auto_load(row)

    def _open_pdf(self):
        paths, _ = QFileDialog.getOpenFileNames(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        for path in paths:
            self._load_and_track(path)

    def _load_and_track(self, path: str):
        path = os.path.abspath(os.path.normpath(path))
        if self._viewer.current_path():
            self._add_viewer_tab(path)
        else:
            self._viewer.load(path)
        if self._viewer.current_path():
            add_recent_file(path)
        for v in self._viewers:
            refresh = getattr(v, "_refresh_recents", None)
            if callable(refresh):
                with contextlib.suppress(Exception):
                    refresh()
        self._refresh_viewer_top_buttons()

    def _on_second_instance(self, paths: list):
        import logging as _logging
        _wlog = _logging.getLogger(__name__)
        for path in paths:
            if isinstance(path, str) and os.path.isfile(path) and path.lower().endswith(".pdf"):
                try:
                    self._load_and_track(path)
                except Exception as exc:
                    _wlog.warning("second instance: failed to load %s: %s", path, exc)
        if self.isMinimized():
            self.showNormal()
        self.raise_(); self.activateWindow()

    def _clear_recent(self):
        from app.i18n import _update_config
        try:
            _update_config(lambda cfg: cfg.__setitem__("recent_files", []))
        except Exception:
            pass
        for v in self._viewers:
            refresh = getattr(v, "_refresh_recents", None)
            if callable(refresh):
                with contextlib.suppress(Exception):
                    refresh()

    def _set_status(self, msg: str):
        self._sb.showMessage(msg)

    # ── Page navigation ───────────────────────────────────────────────────
    def _update_page_nav(self):
        canvas = self._viewer._canvas
        entries = canvas._entries
        if not entries:
            self._page_nav_widget.setVisible(False)
            return
        self._page_nav_widget.setVisible(True)
        sb_val = self._viewer._canvas_scroll.verticalScrollBar().value()
        idx = canvas.page_at_y(sb_val)
        total = len(entries)
        self._page_input.setText(str(idx + 1))
        self._page_total_lbl.setText(f"/ {total}")
        self._first_pg_btn.setEnabled(idx > 0)
        self._prev_pg_btn.setEnabled(idx > 0)
        self._next_pg_btn.setEnabled(idx < total - 1)
        self._last_pg_btn.setEnabled(idx < total - 1)

    def _goto_first_page(self):
        canvas = self._viewer._canvas
        if not canvas._entries:
            return
        sb = self._viewer._canvas_scroll.verticalScrollBar()
        sb.setValue(canvas.scroll_to_page(0))

    def _goto_prev_page(self):
        canvas = self._viewer._canvas
        if not canvas._entries:
            return
        sb = self._viewer._canvas_scroll.verticalScrollBar()
        idx = canvas.page_at_y(sb.value())
        if idx > 0:
            sb.setValue(canvas.scroll_to_page(idx - 1))

    def _goto_next_page(self):
        canvas = self._viewer._canvas
        if not canvas._entries:
            return
        sb = self._viewer._canvas_scroll.verticalScrollBar()
        idx = canvas.page_at_y(sb.value())
        if idx < len(canvas._entries) - 1:
            sb.setValue(canvas.scroll_to_page(idx + 1))

    def _goto_last_page(self):
        canvas = self._viewer._canvas
        if not canvas._entries:
            return
        sb = self._viewer._canvas_scroll.verticalScrollBar()
        sb.setValue(canvas.scroll_to_page(len(canvas._entries) - 1))

    def _goto_input_page(self):
        canvas = self._viewer._canvas
        if not canvas._entries:
            return
        try:
            page_num = int(self._page_input.text())
        except ValueError:
            return
        page_num = max(1, min(page_num, len(canvas._entries)))
        self._page_input.setText(str(page_num))
        sb = self._viewer._canvas_scroll.verticalScrollBar()
        sb.setValue(canvas.scroll_to_page(page_num - 1))

    def _show_language_menu(self):
        _langs = [("en", "English"), ("pt", "Português"), ("es", "Español"), ("fr", "Français"),
                  ("de", "Deutsch"), ("zh", "中文"), ("it", "Italiano"), ("nl", "Nederlands")]
        menu = QMenu(self)
        current = get_language()
        for code, name in _langs:
            action = menu.addAction(f"  {'● ' if code == current else '  '}{name}")
            action.triggered.connect(lambda checked, c=code, n=name: self._set_language(c, n))
        menu.exec(self._lang_btn.mapToGlobal(self._lang_btn.rect().bottomLeft()))

    def _set_language(self, code: str, name: str):
        if code == get_language():
            return
        ans = QMessageBox.question(
            self, t("lang.selector"), t("lang.restart", lang=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if ans != QMessageBox.StandardButton.Yes:
            return
        set_language(code)
        _labels = {"en": "EN", "pt": "PT", "es": "ES", "fr": "FR", "de": "DE", "zh": "ZH", "it": "IT", "nl": "NL"}
        self._lang_btn.setText(_labels.get(code, "EN"))
        self._restart_app()

    def _restart_app(self):
        self._wait_for_workers_on_all_pages()
        self._wipe_all_pdf_passwords()
        import sys
        from PySide6.QtCore import QProcess, QProcessEnvironment
        pdf_args = [a for a in sys.argv[1:] if a.lower().endswith(".pdf")]
        if getattr(sys, "frozen", False):
            program = sys.executable; args = pdf_args; cwd = os.path.dirname(sys.executable) or os.getcwd()
        else:
            script = os.path.abspath(sys.argv[0]); program = sys.executable; args = [script] + pdf_args; cwd = os.path.dirname(script) or os.getcwd()
        proc = QProcess(); proc.setProgram(program); proc.setArguments(args); proc.setWorkingDirectory(cwd)
        env = QProcessEnvironment.systemEnvironment()
        for _k in list(env.keys()):
            if _k.startswith("_PYI_") or _k.startswith("_MEIPASS"):
                env.remove(_k)
        proc.setEnvironment(env)
        proc.startDetached()
        QApplication.instance().exit(0)

    def dragEnterEvent(self, e):
        if not e.mimeData().hasUrls():
            return
        for url in e.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            if (local.lower().endswith(".pdf") or os.path.isdir(local)):
                e.acceptProposedAction()
                return

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if not path:
                scheme = url.scheme().lower() if url.isValid() else ""
                if scheme in ("http", "https", "ftp"):
                    QMessageBox.warning(self, t("msg.warning"), t("viewer.drop_url_not_supported"))
                    return
                continue
            if os.path.isdir(path):
                try:
                    entries = os.listdir(path)
                except OSError:
                    entries = []
                pdfs = sorted(os.path.join(path, f) for f in entries if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(path, f)))
                if len(pdfs) > 20:
                    reply = QMessageBox.question(self, t("msg.confirm"), t("viewer.drop_many_pdfs_confirm", count=len(pdfs)),
                                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
                    if reply != QMessageBox.StandardButton.Yes:
                        continue
                for pdf in pdfs:
                    self._load_and_track(pdf)
                continue
            if path.lower().endswith(".pdf"):
                self._load_and_track(path)

    def _toggle_night_mode_top(self):
        active = self._night_top_btn.isChecked()
        self._viewer._canvas.set_night_mode(active)

    def _refresh_viewer_top_buttons(self):
        try:
            v = self._viewer
            self._toc_top_btn.setVisible(v._toc_tree.topLevelItemCount() > 0)
            self._night_top_btn.setChecked(v._canvas._night_mode)
        except Exception:
            self._toc_top_btn.setVisible(False)
            self._night_top_btn.setChecked(False)

    def _close_current_tab(self):
        idx = self._tab_bar.currentIndex()
        if idx >= 0:
            self._close_tab(idx)

    def _save_current_tool(self):
        vid = id(self._viewer)
        ps = self._pipeline_state.get(vid)
        if ps and ps.get("temp_path"):
            self._save_pipeline()
        elif self._current_tool >= 0:
            w = self.stack.widget(self._current_tool)
            if hasattr(w, '_run'):
                w._run()

    # ── Pipeline ─────────────────────────────────────────────────────────
    def _on_pipeline_done(self, temp_path: str):
        viewer = self._viewer
        vid = id(viewer)
        ps = self._pipeline_state.get(vid)
        if ps is None:
            ps = {"original_path": viewer.current_path(), "temp_path": None}
            self._pipeline_state[vid] = ps
        ps["temp_path"] = temp_path
        viewer.load(temp_path, track=False)
        idx = self._viewer_stack.currentIndex()
        orig_name = os.path.basename(ps["original_path"])
        self._tab_bar.setTabText(idx, f"● {orig_name}")
        self._tab_bar.setTabToolTip(idx, f"{ps['original_path']} (modified)")
        self._sb.showMessage(t("pipeline.applied"))
        if self._current_tool >= 0:
            w = self.stack.widget(self._current_tool)
            fn = getattr(w, "auto_load", None)
            if callable(fn):
                for attr in ("drop_in", "drop_out"):
                    drop = getattr(w, attr, None)
                    if drop:
                        drop.clear()
                fn(temp_path)

    def _save_pipeline(self):
        import shutil, tempfile
        vid = id(self._viewer)
        ps = self._pipeline_state.get(vid)
        if not ps or not ps.get("temp_path"):
            return
        orig = ps["original_path"]
        base, ext = os.path.splitext(os.path.basename(orig))
        suggested = os.path.join(os.path.dirname(orig), base + "_edited" + ext)
        path, _ = QFileDialog.getSaveFileName(self, t("btn.choose"), suggested, t("file_filter.pdf"))
        if not path:
            return
        try:
            if os.path.lexists(path) and os.path.realpath(path) != os.path.abspath(path):
                import logging as _logging
                _logging.getLogger("pdfapps").warning("Pipeline save destination is a symlink: %s -> %s", path, os.path.realpath(path))
        except Exception:
            pass

        for v in self._viewers:
            if v.current_path() and os.path.abspath(v.current_path()) == os.path.abspath(path):
                v._canvas.close_doc()
                if v._fitz_doc:
                    with contextlib.suppress(Exception):
                        v._fitz_doc.close()
                    v._fitz_doc = None
                v._thumbnails._stop_all_workers()

        try:
            dst_dir = os.path.dirname(path) or "."
            fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=dst_dir)
            os.close(fd)
            try:
                shutil.copyfile(ps["temp_path"], tmp)
                os.replace(tmp, path)
            except Exception:
                with contextlib.suppress(Exception):
                    os.unlink(tmp)
                raise
        except OSError:
            shutil.copy2(ps["temp_path"], path)

        self._cleanup_pipeline(vid)
        self._viewer.load(path)
        idx = self._viewer_stack.currentIndex()
        self._tab_bar.setTabText(idx, os.path.basename(path))
        self._tab_bar.setTabToolTip(idx, path)
        self._sb.showMessage(t("pipeline.saved"))

    def _cleanup_pipeline(self, viewer_id: int):
        ps = self._pipeline_state.pop(viewer_id, None)
        if not ps:
            return
        temp_path = ps.get("temp_path")
        if temp_path and os.path.isfile(temp_path):
            with contextlib.suppress(Exception):
                os.unlink(temp_path)
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if isinstance(w, BasePage):
                w.cleanup_pipeline()

    def _viewer_has_unsaved(self, viewer=None) -> bool:
        v = viewer or self._viewer
        ps = self._pipeline_state.get(id(v))
        return bool(ps and ps.get("temp_path"))

    # ── Fullscreen & Presentation ──────────────────────────────────────────
    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self._workspace_bar.setVisible(False)
            self._sidebar.setVisible(False)
            self._sb.setVisible(False)
            self.showFullScreen()
        else:
            self._workspace_bar.setVisible(True)
            if not self._sidebar_collapsed:
                self._sidebar.setVisible(True)
            self._sb.setVisible(True)
            self.showMaximized()

    def _start_presentation(self):
        viewer = self._viewer
        if not viewer._current_path:
            return
        canvas = viewer._canvas
        sb = viewer._canvas_scroll.verticalScrollBar()
        start_page = canvas.page_at_y(sb.value()) if canvas.page_count() > 0 else 0
        from app.viewer.presentation import PresentationWidget
        try:
            pres = PresentationWidget(
                viewer._current_path, getattr(viewer, "_pdf_password", ""),
                start_page, canvas.page_count(), dark_mode=self._dark_mode)
        except Exception as e:
            show_error(self, e)
            return
        pres.destroyed.connect(lambda _=None, w=pres: setattr(self, "_presentation", None) if getattr(self, "_presentation", None) is w else None)
        self._presentation = pres
        self._presentation.show()

    @staticmethod
    def _wipe_password_holder(holder) -> None:
        with contextlib.suppress(Exception):
            clear_fn = getattr(holder, "_clear_pdf_password", None)
            if callable(clear_fn):
                clear_fn()

    def _wait_for_workers_on_all_pages(self) -> None:
        for i in range(self.stack.count()):
            page = self.stack.widget(i)
            with contextlib.suppress(Exception):
                wait_fn = getattr(page, "wait_for_workers", None)
                if callable(wait_fn):
                    wait_fn()

    def _wipe_all_pdf_passwords(self) -> None:
        holders = [self.stack.widget(i) for i in range(self.stack.count())]
        holders += list(self._viewers)
        for holder in holders:
            self._wipe_password_holder(holder)

    def closeEvent(self, event):
        for v in self._viewers:
            if self._viewer_has_unsaved(v):
                ans = QMessageBox.question(self, t("msg.warning"), t("pipeline.unsaved_prompt"),
                                           QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                           QMessageBox.StandardButton.Cancel)
                if ans == QMessageBox.StandardButton.Cancel:
                    event.ignore(); return
                if ans == QMessageBox.StandardButton.Save:
                    self._save_pipeline()
                break
        edit_w = self.stack.widget(self._edit_tool_idx())
        if edit_w and getattr(edit_w, "_user_pending", None):
            ans = QMessageBox.question(self, t("msg.warning"), t("pipeline.unsaved_prompt"),
                                       QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                       QMessageBox.StandardButton.Cancel)
            if ans == QMessageBox.StandardButton.Cancel:
                event.ignore(); return
        for v in list(self._viewers):
            self._cleanup_pipeline(id(v))
        self._wait_for_workers_on_all_pages()
        self._wipe_all_pdf_passwords()
        self._update_controller.release_worker()
        try:
            from app.i18n import _update_config
            sizes = self._splitter.sizes()
            mode = "hidden" if self._sidebar_collapsed else ("icons" if self._sidebar.width() <= 60 else "full")
            pages_open = getattr(PdfViewerPanel, "_pages_sidebar_visible_pref", True)
            def _mutate(cfg: dict) -> None:
                cfg["splitter_sizes"] = sizes
                cfg["sidebar_mode"] = mode
                cfg["pages_sidebar_open"] = bool(pages_open)
            _update_config(_mutate)
        except Exception:
            pass
        super().closeEvent(event)

    def _toggle_sidebar(self):
        if not self._sidebar_collapsed and self._sidebar.width() > 60:
            self._sidebar_collapsed = False
            self._sidebar.setFixedWidth(52)
            self._brand_layout.setContentsMargins(8, 10, 8, 10)
            self._brand_text_w.setVisible(False)
            self._brand_title.setVisible(False)
            self._brand_sub.setVisible(False)
            self._nav_search.setVisible(False)
            self._footer_w.setVisible(False)
            for r in range(self.nav.count()):
                it = self.nav.item(r)
                idx = it.data(Qt.ItemDataRole.UserRole)
                if idx is not None and idx < 0:
                    it.setHidden(True)
            self._sidebar_toggle_btn.setIcon(self._workspace_bar._ico_bars)
        elif not self._sidebar_collapsed:
            self._sidebar_collapsed = True
            self._sidebar.setVisible(False)
            self._sidebar_toggle_btn.setIcon(self._workspace_bar._ico_bars)
        else:
            self._sidebar_collapsed = False
            self._sidebar.setVisible(True)
            self._sidebar.setFixedWidth(228)
            self._brand_layout.setContentsMargins(12, 10, 10, 10)
            self._brand_text_w.setVisible(True)
            self._brand_title.setVisible(True)
            self._brand_sub.setVisible(True)
            self._nav_search.setVisible(True)
            self._footer_w.setVisible(True)
            for r in range(self.nav.count()):
                it = self.nav.item(r)
                idx = it.data(Qt.ItemDataRole.UserRole)
                if idx is not None and idx < 0:
                    it.setHidden(False)
            self._sidebar_toggle_btn.setIcon(self._workspace_bar._ico_times)
        QTimer.singleShot(50, self._relayout_viewer)

    def _relayout_viewer(self):
        for v in self._viewers:
            if v._canvas._doc and v._canvas._zoom_factor == 1.0:
                v._canvas._layout_and_schedule()

    def _toggle_theme(self):
        self._dark_mode = not self._dark_mode
        self._apply_theme()
        from app.i18n import _update_config
        dark = self._dark_mode
        try:
            _update_config(lambda cfg: cfg.__setitem__("dark_mode", dark))
        except Exception:
            pass

    def _apply_theme(self):
        style = STYLE if self._dark_mode else STYLE_LIGHT
        nav_color = TEXT_SEC if self._dark_mode else _LQ
        self._qapp.setPalette(_make_palette(self._dark_mode))
        self._qapp.setStyleSheet(style)
        self._workspace_bar.update_theme(self._dark_mode, self._sidebar_collapsed)
        for r in range(self.nav.count()):
            it = self.nav.item(r)
            tool_idx = it.data(Qt.ItemDataRole.UserRole)
            if tool_idx is not None and tool_idx >= 0:
                _, icon_name, _ = _NAV_KEYS[tool_idx]
                it.setIcon(qta.icon(icon_name, color=nav_color))
            else:
                it.setForeground(QColor(nav_color))
        for v in self._viewers:
            v.update_theme(self._dark_mode)
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if hasattr(w, 'update_theme'):
                w.update_theme(self._dark_mode)
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            for cls in (DropFileEdit, MultiDropWidget):
                for child in w.findChildren(cls):
                    fn = getattr(child, "update_theme", None)
                    if callable(fn):
                        try: fn(self._dark_mode)
                        except RuntimeError: pass
        pres = getattr(self, "_presentation", None)
        if pres is not None and isValid(pres):
            pres.update_theme(self._dark_mode)
