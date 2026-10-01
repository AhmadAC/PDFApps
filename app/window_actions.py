# app/window_actions.py
"""PDFApps – Navigation, themes, UI interactions, and page control mixin."""
from __future__ import annotations

import contextlib
import logging
import os
import sys
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, QTimer, QProcess, QProcessEnvironment
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QFileDialog
import qtawesome as qta
from shiboken6 import isValid

from app.constants import ACCENT, TEXT_SEC, _LQ, DESKTOP
from app.i18n import t, set_language, get_language, add_recent_file
from app.styles import STYLE, STYLE_LIGHT
from app.utils import _make_palette, show_error
from app.widgets import DropFileEdit, MultiDropWidget
from app.viewer.presentation import PresentationWidget
from app.nav_config import NAV_ITEMS, _NAV_KEYS
from app.editor.tab import TabEditar
from app.tools.crop import TabCortar
from app.tools.page_numbers import TabPageNumbers
from app.tools.reorder import TabReordenar
from app.tools.rotate import TabRotar

if TYPE_CHECKING:
    from PySide6.QtWidgets import (
        QMainWindow, QWidget, QStackedWidget, QSplitter, QLabel,
        QPushButton, QListWidget, QLineEdit, QHBoxLayout, QStatusBar,
        QListWidgetItem,
    )
    from app.viewer.panel import PdfViewerPanel
    from app.workspace_bar import WorkspaceBar
    _Base = QMainWindow
else:
    _Base = object


class WindowActionsMixin(_Base):
    """Mixin for navigation, page transitions, themes, and presentation."""

    if TYPE_CHECKING:
        stack: QStackedWidget
        nav: QListWidget
        _viewers: list[PdfViewerPanel]
        _viewer: PdfViewerPanel | None
        _current_tool: int
        _saved_right_width: int
        _right_tool_container: QWidget
        _splitter: QSplitter
        _breadcrumb: QLabel
        _undo_top_btn: QPushButton
        _redo_top_btn: QPushButton
        _tool_usage: dict[str, int]
        _zoom_widget: QWidget
        _zm_btn: QPushButton
        _zp_btn: QPushButton
        _z0_btn: QPushButton
        _lbl_zoom: QLabel
        _sidebar_collapsed: bool
        _sidebar: QWidget
        _brand_layout: QHBoxLayout
        _brand_text_w: QWidget
        _brand_title: QLabel
        _brand_sub: QLabel
        _nav_search: QLineEdit
        _footer_w: QWidget
        _sidebar_toggle_btn: QPushButton
        _pages_toggle_btn: QPushButton
        _right_pane_toggle_btn: QPushButton
        _tab_container: QWidget
        _page_nav_widget: QWidget
        _first_pg_btn: QPushButton
        _prev_pg_btn: QPushButton
        _next_pg_btn: QPushButton
        _last_pg_btn: QPushButton
        _page_input: QLineEdit
        _page_total_lbl: QLabel
        _lang_btn: QPushButton
        _toc_top_btn: QPushButton
        _night_top_btn: QPushButton
        _presentation: PresentationWidget | None
        _dark_mode: bool
        _qapp: QApplication
        _workspace_bar: WorkspaceBar
        _sb: QStatusBar
        _fullscreen: bool

        def _add_viewer_tab(self, path: str = ...) -> PdfViewerPanel: ...
        def _update_tab_bar_visibility(self) -> None: ...
        def _wait_for_workers_on_all_pages(self) -> None: ...
        def _wipe_all_pdf_passwords(self) -> None: ...

    def _tool_idx_for_class(self, cls) -> int:
        for idx, (_, _, tool_cls) in enumerate(_NAV_KEYS):
            if tool_cls is cls:
                return idx
        return -1

    def _edit_tool_idx(self) -> int:
        return self._tool_idx_for_class(TabEditar)

    def _rotate_tool_idx(self) -> int:
        return self._tool_idx_for_class(TabRotar)

    def _crop_tool_idx(self) -> int:
        return self._tool_idx_for_class(TabCortar)

    def _reorder_tool_idx(self) -> int:
        return self._tool_idx_for_class(TabReordenar)

    def _page_numbers_tool_idx(self) -> int:
        return self._tool_idx_for_class(TabPageNumbers)

    def _toggle_pages_sidebar(self):
        viewer = self._viewer
        if viewer:
            viewer._toggle_pages_sidebar()
            if self.sender() is getattr(self, "_toc_top_btn", None) and not viewer._pages_sidebar_collapsed:
                if viewer._toc_tree.topLevelItemCount() > 0:
                    viewer._sidebar_tabs.setCurrentIndex(viewer._toc_tab_idx)

    def _toggle_right_pane(self):
        edit_idx = self._edit_tool_idx()
        if self._current_tool == edit_idx:
            edit_w = self.stack.widget(edit_idx)
            if isinstance(edit_w, TabEditar):
                edit_w.toggle_controls()
            return
        if self._right_tool_container.isVisible():
            self._saved_right_width = max(320, self._right_tool_container.width())
            self._right_tool_container.setVisible(False)
            total = self._splitter.width()
            self._splitter.setSizes([total, 0])
        else:
            self._right_tool_container.setVisible(True)
            total = self._splitter.width()
            tool_w = max(320, getattr(self, "_saved_right_width", 380))
            self._splitter.setSizes([max(300, total - tool_w), tool_w])

    def _on_rotations_changed(self, rotations: dict[int, int]):
        if self._viewer:
            self._viewer.set_page_rotations(rotations)

    def _on_crop_changed(self, crop_data: dict | None):
        if self._viewer:
            self._viewer.set_crop_preview(crop_data)

    def _on_crops_changed(self, crops: dict[int, tuple[float, float, float, float]]):
        if self._viewer:
            self._viewer.set_page_crops(crops)

    def _on_crop_mode_toggled(self, active: bool):
        if self._viewer:
            self._viewer.set_crop_mode(active)

    def _on_order_changed(self, order: list[int] | None):
        if self._viewer:
            self._viewer.set_page_order(order)

    def _on_numbers_preview_changed(self, preview_data: dict | None):
        if self._viewer:
            self._viewer.set_numbers_preview(preview_data)

    def _update_breadcrumb(self):
        cur_file = ""
        viewer = self._viewer
        if viewer and viewer.current_path():
            cur_file = os.path.basename(viewer._original_doc_path or viewer.current_path())

        file_part = f"  ›  {cur_file}" if cur_file else ""
        if getattr(self, "_current_tool", -1) >= 0 and self._current_tool < len(NAV_ITEMS):
            tool_name = NAV_ITEMS[self._current_tool][0]
            self._breadcrumb.setText(f"{t('workspace.title')}{file_part}  ›  {tool_name}")
        elif cur_file:
            self._breadcrumb.setText(f"{t('workspace.title')}{file_part}")
        else:
            self._breadcrumb.setText(t("workspace.title"))

        if viewer and viewer.current_path():
            self._breadcrumb.setToolTip(viewer._original_doc_path or viewer.current_path())
        else:
            self._breadcrumb.setToolTip("")

    def _update_undo_redo_buttons(self):
        if not hasattr(self, "_undo_top_btn") or not hasattr(self, "_redo_top_btn"):
            return
        edit_idx = self._edit_tool_idx()
        crop_idx = self._crop_tool_idx()
        page_numbers_idx = self._page_numbers_tool_idx()
        viewer = self._viewer

        if getattr(self, "_current_tool", -1) == -1:
            self._undo_top_btn.setVisible(True)
            self._redo_top_btn.setVisible(True)
            can_u = viewer.can_undo() if viewer and hasattr(viewer, "can_undo") else False
            can_r = viewer.can_redo() if viewer and hasattr(viewer, "can_redo") else False
            self._undo_top_btn.setEnabled(can_u)
            self._redo_top_btn.setEnabled(can_r)
        elif self._current_tool == edit_idx:
            self._undo_top_btn.setVisible(True)
            self._redo_top_btn.setVisible(True)
            edit_w = self.stack.widget(edit_idx)
            if isinstance(edit_w, TabEditar):
                self._undo_top_btn.setEnabled(bool(edit_w._pending))
                self._redo_top_btn.setEnabled(bool(edit_w._redo_stack))
            else:
                self._undo_top_btn.setEnabled(False)
                self._redo_top_btn.setEnabled(False)
        elif self._current_tool in (crop_idx, page_numbers_idx):
            self._undo_top_btn.setVisible(True)
            self._redo_top_btn.setVisible(True)
            tool_w = self.stack.widget(self._current_tool)
            btn_u = getattr(tool_w, "btn_undo", None)
            btn_r = getattr(tool_w, "btn_redo", None)
            self._undo_top_btn.setEnabled(btn_u.isEnabled() if btn_u else False)
            self._redo_top_btn.setEnabled(btn_r.isEnabled() if btn_r else False)
        else:
            self._undo_top_btn.setVisible(False)
            self._redo_top_btn.setVisible(False)

    def _open_tool_by_name(self, tool_name: str):
        for i, (name, _, _) in enumerate(NAV_ITEMS):
            if name == tool_name or t(name) == tool_name:
                for r in range(self.nav.count()):
                    item = self.nav.item(r)
                    if item and item.data(Qt.ItemDataRole.UserRole) == i:
                        self.nav.setCurrentRow(r)
                        self._on_nav_clicked(item)
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
        if widget is None:
            return
        viewer = self._viewer
        path = viewer.current_path() if viewer else ""
        if path:
            viewer_pwd = getattr(viewer, "_pdf_password", "")
            if hasattr(widget, "_pdf_password"):
                setattr(widget, "_pdf_password", viewer_pwd)
            fn = getattr(widget, "auto_load", None)
            if callable(fn):
                fn(path)

        compact_fn = getattr(widget, "set_compact_mode", None)
        if callable(compact_fn):
            compact_fn(bool(path), path or "")

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
        if canvas is None and hasattr(self, "_edit_tool_idx"):
            edit_idx = self._edit_tool_idx()
            if edit_idx >= 0:
                canvas = getattr(self.stack.widget(edit_idx), '_canvas', None)
        viewer = self._viewer
        if canvas is None and viewer:
            canvas = getattr(viewer, '_canvas', None)
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
            if it and it.data(Qt.ItemDataRole.UserRole) == tool_idx:
                self.nav.setCurrentRow(r)
                self._on_nav_clicked(it)
                return

    def _filter_nav(self, text: str):
        q = text.lower().strip()
        visible_groups = set()
        for r in range(self.nav.count()):
            it = self.nav.item(r)
            if it:
                tool_idx = it.data(Qt.ItemDataRole.UserRole)
                if tool_idx is not None and tool_idx >= 0:
                    match = not q or q in it.text().lower()
                    it.setHidden(not match)
                    if match:
                        visible_groups.add(r)
        for r in range(self.nav.count()):
            it = self.nav.item(r)
            if it and it.data(Qt.ItemDataRole.UserRole) == -1:
                has_visible = False
                for r2 in range(r + 1, self.nav.count()):
                    it2 = self.nav.item(r2)
                    if it2 and it2.data(Qt.ItemDataRole.UserRole) == -1:
                        break
                    if it2 and not it2.isHidden():
                        has_visible = True
                        break
                it.setHidden(not has_visible)

    def _on_nav_clicked(self, item: QListWidgetItem):
        row = item.data(Qt.ItemDataRole.UserRole)
        if row is None or row < 0:
            self.nav.clearSelection()
            return
        edit_idx = self._edit_tool_idx()
        rotate_idx = self._rotate_tool_idx()
        crop_idx = self._crop_tool_idx()
        reorder_idx = self._reorder_tool_idx()
        page_numbers_idx = self._page_numbers_tool_idx()
        viewer = self._viewer

        if row == self._current_tool:
            self.nav.clearSelection()
            self._current_tool = -1
            self.stack.setVisible(False)
            self._right_tool_container.setVisible(False)
            self._right_pane_toggle_btn.setVisible(False)
            self._pages_toggle_btn.setVisible(True)
            self._tab_container.setVisible(True)
            self._update_breadcrumb()
            self._setup_zoom_bar(True, canvas=viewer._canvas if viewer else None)
            if viewer:
                viewer.set_page_rotations({})
                viewer.set_crop_mode(False)
                viewer.set_crop_preview(None)
                viewer.set_numbers_preview(None)
                viewer.set_page_crops({})
                viewer.set_page_order(None)
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
                if isinstance(edit_w, TabEditar):
                    edit_w._ctrl_scroll.setVisible(True)
                if viewer:
                    viewer.set_page_rotations({})
                    viewer.set_crop_mode(False)
                    viewer.set_crop_preview(None)
                    viewer.set_numbers_preview(None)
                    viewer.set_page_crops({})
                    viewer.set_page_order(None)
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
                    if isinstance(rot_w, TabRotar) and viewer:
                        viewer.set_page_rotations(rot_w._rotations)
                elif viewer:
                    viewer.set_page_rotations({})

                if row == crop_idx:
                    crop_w = self.stack.widget(crop_idx)
                    if isinstance(crop_w, TabCortar):
                        active = crop_w.btn_draw_crop.isChecked()
                        if viewer:
                            viewer.set_crop_mode(active)
                            crop_w._emit_preview()
                            viewer.set_page_crops(crop_w._applied_crops)
                elif viewer:
                    viewer.set_crop_mode(False)
                    viewer.set_crop_preview(None)
                    viewer.set_page_crops({})

                if row == page_numbers_idx:
                    pn_w = self.stack.widget(page_numbers_idx)
                    if isinstance(pn_w, TabPageNumbers):
                        pn_w._emit_preview()
                        pn_w._update_undo_redo_state()
                elif viewer:
                    viewer.set_numbers_preview(None)

                if row == reorder_idx:
                    reorder_w = self.stack.widget(reorder_idx)
                    if isinstance(reorder_w, TabReordenar):
                        order = reorder_w.get_order()
                        if order and viewer:
                            viewer.set_page_order(order)
                elif viewer:
                    viewer.set_page_order(None)

            self._update_breadcrumb()
            self._try_auto_load(row)

        self._update_undo_redo_buttons()

    def _open_pdf(self):
        paths, _ = QFileDialog.getOpenFileNames(self, t("btn.open_pdf"), DESKTOP, t("file_filter.pdf"))
        for path in paths:
            self._load_and_track(path)

    def _load_and_track(self, path: str):
        path = os.path.abspath(os.path.normpath(path))
        viewer = self._viewer
        if viewer and viewer.current_path():
            self._add_viewer_tab(path)
        elif viewer:
            viewer.load(path)
        if viewer and viewer.current_path():
            add_recent_file(path)
        for v in self._viewers:
            refresh = getattr(v, "_refresh_recents", None)
            if callable(refresh):
                with contextlib.suppress(Exception):
                    refresh()
        self._refresh_viewer_top_buttons()
        self._update_tab_bar_visibility()
        self._update_breadcrumb()

    def _on_second_instance(self, paths: list):
        _wlog = logging.getLogger(__name__)
        for path in paths:
            if isinstance(path, str) and os.path.isfile(path) and path.lower().endswith(".pdf"):
                try:
                    self._load_and_track(path)
                except Exception as exc:
                    _wlog.warning("second instance: failed to load %s: %s", path, exc)
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

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
        viewer = self._viewer
        if not viewer:
            self._page_nav_widget.setVisible(False)
            return
        canvas = viewer._canvas
        entries = canvas._entries
        if not entries:
            self._page_nav_widget.setVisible(False)
            return
        self._page_nav_widget.setVisible(True)
        sb = viewer._canvas_scroll.verticalScrollBar()
        sb_val = sb.value() if sb else 0
        idx = canvas.page_at_y(sb_val)
        total = len(entries)
        self._page_input.setText(str(idx + 1))
        self._page_total_lbl.setText(f"/ {total}")
        self._first_pg_btn.setEnabled(idx > 0)
        self._prev_pg_btn.setEnabled(idx > 0)
        self._next_pg_btn.setEnabled(idx < total - 1)
        self._last_pg_btn.setEnabled(idx < total - 1)
        self._update_undo_redo_buttons()

    def _goto_first_page(self):
        viewer = self._viewer
        if not viewer:
            return
        canvas = viewer._canvas
        if not canvas._entries:
            return
        sb = viewer._canvas_scroll.verticalScrollBar()
        if sb:
            sb.setValue(canvas.scroll_to_page(0))

    def _goto_prev_page(self):
        viewer = self._viewer
        if not viewer:
            return
        canvas = viewer._canvas
        if not canvas._entries:
            return
        sb = viewer._canvas_scroll.verticalScrollBar()
        if sb:
            idx = canvas.page_at_y(sb.value())
            if idx > 0:
                sb.setValue(canvas.scroll_to_page(idx - 1))

    def _goto_next_page(self):
        viewer = self._viewer
        if not viewer:
            return
        canvas = viewer._canvas
        if not canvas._entries:
            return
        sb = viewer._canvas_scroll.verticalScrollBar()
        if sb:
            idx = canvas.page_at_y(sb.value())
            if idx < len(canvas._entries) - 1:
                sb.setValue(canvas.scroll_to_page(idx + 1))

    def _goto_last_page(self):
        viewer = self._viewer
        if not viewer:
            return
        canvas = viewer._canvas
        if not canvas._entries:
            return
        sb = viewer._canvas_scroll.verticalScrollBar()
        if sb:
            sb.setValue(canvas.scroll_to_page(len(canvas._entries) - 1))

    def _goto_input_page(self):
        viewer = self._viewer
        if not viewer:
            return
        canvas = viewer._canvas
        if not canvas._entries:
            return
        try:
            page_num = int(self._page_input.text())
        except ValueError:
            return
        page_num = max(1, min(page_num, len(canvas._entries)))
        self._page_input.setText(str(page_num))
        sb = viewer._canvas_scroll.verticalScrollBar()
        if sb:
            sb.setValue(canvas.scroll_to_page(page_num - 1))

    def _show_language_menu(self):
        _langs = [("en", "English"), ("pt", "Português"), ("es", "Español"), ("fr", "Français"),
                  ("de", "Deutsch"), ("zh", "中文"), ("it", "Italiano"), ("nl", "Nederlands")]
        menu = QMenu(self)
        current = get_language()
        for code, name in _langs:
            action = menu.addAction(f"  {'● ' if code == current else '  '}{name}")
            action.triggered.connect(lambda checked=False, c=code, n=name: self._set_language(c, n))
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
        pdf_args = [a for a in sys.argv[1:] if a.lower().endswith(".pdf")]
        if getattr(sys, "frozen", False):
            program = sys.executable
            args = pdf_args
            cwd = os.path.dirname(sys.executable) or os.getcwd()
        else:
            script = os.path.abspath(sys.argv[0])
            program = sys.executable
            args = [script] + pdf_args
            cwd = os.path.dirname(script) or os.getcwd()
        proc = QProcess()
        proc.setProgram(program)
        proc.setArguments(args)
        proc.setWorkingDirectory(cwd)
        env = QProcessEnvironment.systemEnvironment()
        for _k in list(env.keys()):
            if _k.startswith("_PYI_") or _k.startswith("_MEIPASS"):
                env.remove(_k)
        proc.setProcessEnvironment(env)
        proc.startDetached()
        app = QApplication.instance()
        if app is not None:
            app.exit(0)

    def dragEnterEvent(self, e):
        if not e.mimeData().hasUrls():
            return
        for url in e.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            if local.lower().endswith(".pdf") or os.path.isdir(local):
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
        viewer = self._viewer
        if viewer:
            active = self._night_top_btn.isChecked()
            viewer._canvas.set_night_mode(active)

    def _refresh_viewer_top_buttons(self):
        try:
            v = self._viewer
            if v:
                self._toc_top_btn.setVisible(v._toc_tree.topLevelItemCount() > 0)
                self._night_top_btn.setChecked(v._canvas._night_mode)
            else:
                self._toc_top_btn.setVisible(False)
                self._night_top_btn.setChecked(False)
        except Exception:
            self._toc_top_btn.setVisible(False)
            self._night_top_btn.setChecked(False)

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
        if not viewer or not viewer._current_path:
            return
        canvas = viewer._canvas
        sb = viewer._canvas_scroll.verticalScrollBar()
        start_page = canvas.page_at_y(sb.value()) if canvas.page_count() > 0 and sb else 0
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

    def _toggle_sidebar(self):
        if not self._sidebar_collapsed and self._sidebar.width() > 60:
            self._sidebar_collapsed = False
            self._sidebar.setFixedWidth(52)
            self._brand_layout.setContentsMargins(0, 10, 0, 10)
            self._brand_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._brand_text_w.setVisible(False)
            self._brand_title.setVisible(False)
            self._brand_sub.setVisible(False)
            self._nav_search.setVisible(False)
            self._footer_w.setVisible(False)
            for r in range(self.nav.count()):
                it = self.nav.item(r)
                if it:
                    idx = it.data(Qt.ItemDataRole.UserRole)
                    if idx is not None and idx < 0:
                        it.setHidden(True)
            self._sidebar_toggle_btn.setIcon(self._workspace_bar._ico_bars)
            self.nav.updateGeometries()
            self.nav.viewport().update()
        elif not self._sidebar_collapsed:
            self._sidebar_collapsed = True
            self._sidebar.setVisible(False)
            self._sidebar_toggle_btn.setIcon(self._workspace_bar._ico_bars)
        else:
            self._sidebar_collapsed = False
            self._sidebar.setVisible(True)
            self._sidebar.setFixedWidth(228)
            self._brand_layout.setContentsMargins(12, 10, 10, 10)
            self._brand_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._brand_text_w.setVisible(True)
            self._brand_title.setVisible(True)
            self._brand_sub.setVisible(True)
            self._nav_search.setVisible(True)
            self._footer_w.setVisible(True)
            for r in range(self.nav.count()):
                it = self.nav.item(r)
                if it:
                    idx = it.data(Qt.ItemDataRole.UserRole)
                    if idx is not None and idx < 0:
                        it.setHidden(False)
            self._sidebar_toggle_btn.setIcon(self._workspace_bar._ico_times)
            self.nav.updateGeometries()
            self.nav.viewport().update()
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
            if it:
                tool_idx = it.data(Qt.ItemDataRole.UserRole)
                if tool_idx is not None and tool_idx >= 0:
                    _, icon_name, _ = _NAV_KEYS[tool_idx]
                    it.setIcon(qta.icon(icon_name, color=nav_color))
                else:
                    it.setForeground(QColor(nav_color))
        self.nav.viewport().update()
        for v in self._viewers:
            v.update_theme(self._dark_mode)
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            fn = getattr(w, "update_theme", None)
            if callable(fn):
                fn(self._dark_mode)
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            for cls in (DropFileEdit, MultiDropWidget):
                for child in w.findChildren(cls):
                    child_fn = getattr(child, "update_theme", None)
                    if callable(child_fn):
                        try:
                            child_fn(self._dark_mode)
                        except RuntimeError:
                            pass
        pres = getattr(self, "_presentation", None)
        if pres is not None and isValid(pres):
            pres.update_theme(self._dark_mode)