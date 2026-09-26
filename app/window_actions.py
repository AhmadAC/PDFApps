# app/window_actions.py
"""PDFApps – Navigation, themes, UI interactions, and page control mixin."""
import contextlib
import logging
import os
import sys

from PySide6.QtCore import Qt, QTimer, QProcess, QProcessEnvironment
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QFileDialog
import qtawesome as qta
from shiboken6 import isValid

from app.constants import ACCENT, TEXT_PRI, TEXT_SEC, _LQ, DESKTOP
from app.i18n import t, set_language, get_language, add_recent_file
from app.styles import STYLE, STYLE_LIGHT
from app.utils import _make_palette, show_error
from app.widgets import DropFileEdit, MultiDropWidget
from app.viewer.presentation import PresentationWidget
from app.nav_config import NAV_ITEMS, _NAV_KEYS


class WindowActionsMixin:
    """Mixin for navigation, page transitions, themes, and presentation."""

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
                        has_visible = True
                        break
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
            self._undo_top_btn.setVisible(True)
            self._redo_top_btn.setVisible(True)
            prev = getattr(self, "_undo_redo_handlers", None)
            if prev is not None:
                try:
                    self._undo_top_btn.clicked.disconnect(prev[0])
                except (RuntimeError, TypeError):
                    pass
                try:
                    self._redo_top_btn.clicked.disconnect(prev[1])
                except (RuntimeError, TypeError):
                    pass
            self._undo_top_btn.clicked.connect(self._viewer.undo)
            self._redo_top_btn.clicked.connect(self._viewer.redo)
            self._undo_redo_handlers = (self._viewer.undo, self._viewer.redo)
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
                    try:
                        self._undo_top_btn.clicked.disconnect(prev[0])
                    except (RuntimeError, TypeError):
                        pass
                    try:
                        self._redo_top_btn.clicked.disconnect(prev[1])
                    except (RuntimeError, TypeError):
                        pass
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
                        try:
                            self._undo_top_btn.clicked.disconnect(prev[0])
                        except (RuntimeError, TypeError):
                            pass
                        try:
                            self._redo_top_btn.clicked.disconnect(prev[1])
                        except (RuntimeError, TypeError):
                            pass
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
                        try:
                            fn(self._dark_mode)
                        except RuntimeError:
                            pass
        pres = getattr(self, "_presentation", None)
        if pres is not None and isValid(pres):
            pres.update_theme(self._dark_mode)