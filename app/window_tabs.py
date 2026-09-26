# app/window_tabs.py
"""PDFApps – Tab management and custom tab bar component."""
import os
import sys

from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QTabBar, QMenu, QApplication, QMessageBox
import qtawesome as qta

from app.constants import TEXT_PRI, _LQ
from app.i18n import t, add_recent_file
from app.utils import reveal_file
from app.viewer.panel import PdfViewerPanel
from app.tools.rotate import TabRotar
from app.tools.crop import TabCortar
from app.editor.tab import TabEditar
from app.nav_config import NAV_ITEMS


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


class WindowTabsMixin:
    """Mixin for MainWindow tab operations and viewer interactions."""

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

    def _edit_tool_idx(self) -> int:
        return next(i for i, (_, __, cls) in enumerate(NAV_ITEMS) if cls is TabEditar)

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
            viewer._original_doc_path = ""
            viewer._cleanup_history_files()
            viewer._undo_stack.clear()
            viewer._redo_stack.clear()
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

    def _close_current_tab(self):
        idx = self._tab_bar.currentIndex()
        if idx >= 0:
            self._close_tab(idx)

    def _close_other_tabs(self, keep_idx: int):
        total = len(self._viewers)
        for i in range(total - 1, -1, -1):
            if i != keep_idx:
                self._close_tab(i)

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
        reveal_label = (
            "Reveal in File Explorer"
            if sys.platform == "win32"
            else ("Reveal in Finder" if sys.platform == "darwin" else "Show in File Manager")
        )
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