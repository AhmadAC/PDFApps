# app/window.py
"""PDFApps – MainWindow: application main window facade."""
import os
import json

from PySide6.QtCore import Qt, QSize, QTimer, QPoint
from PySide6.QtGui import (
    QIcon, QColor, QShortcut, QKeySequence, QMouseEvent,
    QPixmap, QPainter, QImage, QFont
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QStackedWidget, QSplitter, QStatusBar,
    QFrame, QApplication, QLineEdit, QMenu, QTabBar, QFileDialog, QMessageBox,
)
from shiboken6 import isValid
import qtawesome as qta
import fitz

from app.constants import ACCENT, TEXT_PRI, TEXT_SEC, _LQ, DESKTOP, BORDER, APP_VERSION
from app.i18n import t, set_language, get_language, add_recent_file, _CONFIG_PATH
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

from app.window_tabs import _ViewerTabBar, WindowTabsMixin
from app.window_pipeline import WindowPipelineMixin
from app.window_actions import WindowActionsMixin


class MainWindow(WindowTabsMixin, WindowPipelineMixin, WindowActionsMixin, QMainWindow):
    """Main Application Window."""

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

        self._sb = QStatusBar()
        self.setStatusBar(self._sb)
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

        body = QWidget()
        body.setObjectName("workspace_shell")
        main_h = QHBoxLayout(body)
        main_h.setContentsMargins(10, 10, 10, 0)
        main_h.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────────
        self._sidebar = QWidget()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(228)
        sb_lay = QVBoxLayout(self._sidebar)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.setSpacing(0)

        brand = QWidget()
        brand.setObjectName("brand_area")
        self._brand_layout = bh = QHBoxLayout(brand)
        bh.setContentsMargins(12, 10, 10, 10)
        bh.setSpacing(8)
        ico_lbl = QLabel()
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
            p = QPainter(img)
            renderer.render(p)
            p.end()
            _app_pix = QPixmap.fromImage(img)
            _app_pix.setDevicePixelRatio(dpr)
        else:
            _w = _h
            _ico_path = resource_path("icon.ico")
            _app_pix = QPixmap(_ico_path).scaled(
                int(_w * dpr), int(_h * dpr), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            _app_pix.setDevicePixelRatio(dpr)
        ico_lbl.setPixmap(_app_pix)
        ico_lbl.setObjectName("app_icon")
        ico_lbl.setFixedSize(_w, _h)
        ico_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bh.addWidget(ico_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        self._brand_text_w = QWidget()
        brand_text = QVBoxLayout(self._brand_text_w)
        brand_text.setContentsMargins(0, 0, 0, 0)
        brand_text.setSpacing(1)
        self._brand_title = QLabel(t("app.name"))
        self._brand_title.setObjectName("app_title")
        self._brand_sub = QLabel(t("app.subtitle"))
        self._brand_sub.setObjectName("app_sub")
        brand_text.addWidget(self._brand_title)
        brand_text.addWidget(self._brand_sub)
        bh.addWidget(self._brand_text_w, 1)
        sb_lay.addWidget(brand)

        sep = QFrame()
        sep.setObjectName("nav_sep")
        sep.setFixedHeight(1)
        sb_lay.addWidget(sep)

        self._nav_search = QLineEdit()
        self._nav_search.setPlaceholderText("🔍 " + t("nav.search"))
        self._nav_search.setClearButtonEnabled(True)
        self._nav_search.setObjectName("nav_search")
        self._nav_search.textChanged.connect(self._filter_nav)
        sb_lay.addWidget(self._nav_search)

        self.nav = QListWidget()
        self.nav.setObjectName("nav_list")
        self.nav.setSpacing(0)
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if self.nav.verticalScrollBar():
            self.nav.verticalScrollBar().setFixedWidth(0)
            self.nav.verticalScrollBar().setMaximumWidth(0)
            self.nav.verticalScrollBar().setStyleSheet("width: 0px; max-width: 0px; border: none; background: transparent;")

        self._tool_usage = {}
        try:
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
            f = QFont()
            f.setPointSize(9)
            f.setBold(True)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
            hdr.setFont(f)
            hdr.setSizeHint(QSize(0, 26))
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
                sep_line = QFrame()
                sep_line.setFixedHeight(1)
                sep_line.setStyleSheet(f"background:{BORDER}; margin: 0 8px 0 4px;")
                self.nav.setItemWidget(sep_item, sep_line)

            hdr = QListWidgetItem(t(group_key).upper())
            hdr.setFlags(Qt.ItemFlag.NoItemFlags)
            hdr.setData(Qt.ItemDataRole.UserRole, -1)
            hdr.setForeground(QColor(TEXT_SEC))
            f = QFont()
            f.setPointSize(9)
            f.setBold(True)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
            hdr.setFont(f)
            hdr.setSizeHint(QSize(0, 26))
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

        self._footer_w = QWidget()
        self._footer_w.setObjectName("sidebar")
        footer_h = QHBoxLayout(self._footer_w)
        footer_h.setContentsMargins(14, 8, 14, 10)
        footer_h.setSpacing(0)
        footer_lbl = QLabel(f"v{APP_VERSION}  ·  {t('app.credits')}")
        footer_lbl.setObjectName("sidebar_footer")
        footer_h.addWidget(footer_lbl, 1)
        sb_lay.addWidget(self._footer_w)
        self._sidebar_collapsed = False

        self._dark_mode = True
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as _cf:
                self._dark_mode = json.load(_cf).get("dark_mode", True)
        except Exception:
            pass
        self._qapp: QApplication = QApplication.instance()

        # ── Tool Stack & Right Tool Container ────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.setObjectName("content_area")
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
        tc_lay = QVBoxLayout(self._tab_container)
        tc_lay.setContentsMargins(0, 0, 0, 0)
        tc_lay.setSpacing(0)

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(0)
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
        self._splitter.setHandleWidth(1)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._tab_container)
        self._splitter.addWidget(self._right_tool_container)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        self._splitter.setSizes([1200, 0])

        main_h.addWidget(self._sidebar)
        main_h.addWidget(self._splitter, 1)
        root_v.addWidget(body, 1)
        self.setCentralWidget(central)

        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as _cf:
                _saved = json.load(_cf)
            mode = _saved.get("sidebar_mode")
            if mode == "icons":
                self._toggle_sidebar()
            elif mode == "hidden":
                self._toggle_sidebar()
                self._toggle_sidebar()
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
        
        # FIX: Provide correct window-scoping constraints to avoid ambiguous overloads with canvas
        sc_undo = QShortcut(QKeySequence("Ctrl+Z"), self, self._handle_global_undo)
        sc_redo1 = QShortcut(QKeySequence("Ctrl+Y"), self, self._handle_global_redo)
        sc_redo2 = QShortcut(QKeySequence("Ctrl+Shift+Z"), self, self._handle_global_redo)
        
        sc_close = QShortcut(QKeySequence("Ctrl+W"), self, self._close_current_tab)
        sc_save = QShortcut(QKeySequence("Ctrl+S"), self, self._save_current_tool)
        sc_pgup = QShortcut(QKeySequence("PgUp"), self, self._goto_prev_page)
        sc_pgdn = QShortcut(QKeySequence("PgDown"), self, self._goto_next_page)
        for sc in (sc_undo, sc_redo1, sc_redo2, sc_close, sc_save, sc_pgup, sc_pgdn):
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

    def closeEvent(self, event):
        for v in self._viewers:
            if self._viewer_has_unsaved(v):
                ans = QMessageBox.question(
                    self, t("msg.warning"), t("pipeline.unsaved_prompt"),
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel
                )
                if ans == QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                if ans == QMessageBox.StandardButton.Save:
                    self._save_pipeline()
                break
        edit_w = self.stack.widget(self._edit_tool_idx())
        if edit_w and getattr(edit_w, "_user_pending", None):
            ans = QMessageBox.question(
                self, t("msg.warning"), t("pipeline.unsaved_prompt"),
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel
            )
            if ans == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
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