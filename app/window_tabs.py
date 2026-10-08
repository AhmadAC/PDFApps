#################### START OF FILE: app\window_tabs.py ####################

# app/window_tabs.py
"""PDFApps – Tab management and multi-viewer window mixin."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QTabBar,
)
import qtawesome as qta

from app.constants import TEXT_PRI, _LQ
from app.i18n import add_recent_file, t
from app.utils import reveal_file
from app.viewer.panel import PdfViewerPanel

if TYPE_CHECKING:
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import (
        QMainWindow,
        QStackedWidget,
        QWidget,
    )
    _Base = QMainWindow
else:
    _Base = object

__all__ = ["_ViewerTabBar", "WindowTabsMixin"]


class _ViewerTabBar(QTabBar):
    """Custom tab bar supporting mouse middle-click to close tabs and double-click to open."""

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            pos = (
                event.position().toPoint()
                if hasattr(event, "position")
                else event.pos()
            )
            idx = self.tabAt(pos)
            if idx >= 0:
                self.tabCloseRequested.emit(idx)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        pos = (
            event.position().toPoint()
            if hasattr(event, "position")
            else event.pos()
        )
        idx = self.tabAt(pos)
        if idx < 0:
            parent = self.window()
            open_fn = getattr(parent, "_open_pdf", None)
            if callable(open_fn):
                open_fn()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)


class WindowTabsMixin(_Base):
    """Mixin for MainWindow managing viewer tabs, document routing, and tab lifecycle."""

    if TYPE_CHECKING:
        _viewers: list[PdfViewerPanel]
        _viewer_stack: QStackedWidget
        _tab_bar: _ViewerTabBar
        stack: QStackedWidget
        _current_tool: int
        _dark_mode: bool

        def _handle_global_undo(self) -> None: ...
        def _handle_global_redo(self) -> None: ...
        def _update_page_nav(self) -> None: ...
        def _update_breadcrumb(self) -> None: ...
        def _viewer_has_unsaved(self, viewer: Any = ...) -> bool: ...
        def _save_pipeline(self) -> None: ...
        def _cleanup_pipeline(self, viewer_id: int) -> None: ...
        def _crop_tool_idx(self) -> int: ...
        def _setup_zoom_bar(self, active: bool, canvas: Any = ...) -> None: ...

    @property
    def _viewer(self) -> PdfViewerPanel | None:
        if hasattr(self, "_viewers") and self._viewers:
            idx = self._viewer_stack.currentIndex()
            if 0 <= idx < len(self._viewers):
                return self._viewers[idx]
            return self._viewers[0]
        return None

    def _add_viewer_tab(self, path: str = "") -> PdfViewerPanel:
        viewer = PdfViewerPanel()

        viewer.crop_selected.connect(self._on_canvas_crop_selected)
        viewer.crop_applied.connect(self._on_canvas_crop_applied)
        viewer.crop_undo_requested.connect(self._handle_global_undo)
        viewer.crop_redo_requested.connect(self._handle_global_redo)
        if hasattr(viewer, "page_action_requested"):
            viewer.page_action_requested.connect(self._on_thumbnail_action_requested)

        viewer._canvas_scroll.verticalScrollBar().valueChanged.connect(
            lambda _: self._update_page_nav()
        )
        viewer._canvas.zoom_changed.connect(lambda _: self._update_page_nav())

        self._viewers.append(viewer)
        self._viewer_stack.addWidget(viewer)

        tab_title = os.path.basename(path) if path else t("viewer.title")
        tab_idx = self._tab_bar.addTab(tab_title)
        self._tab_bar.setTabToolTip(tab_idx, path or "")
        self._tab_bar.setCurrentIndex(tab_idx)
        self._viewer_stack.setCurrentIndex(tab_idx)

        if path:
            viewer.load(path)

        self._update_tab_bar_visibility()
        if hasattr(self, "_update_page_nav"):
            self._update_page_nav()
        if hasattr(self, "_update_breadcrumb"):
            self._update_breadcrumb()
        return viewer

    def _update_tab_bar_visibility(self) -> None:
        has_multiple = len(self._viewers) > 1
        has_open_doc = any(bool(v.current_path()) for v in self._viewers)
        self._tab_bar.setVisible(has_multiple or has_open_doc)
        if hasattr(self, "_update_breadcrumb"):
            self._update_breadcrumb()

    def _close_tab(self, index: int) -> None:
        if not (0 <= index < len(self._viewers)):
            return
        viewer = self._viewers[index]

        if hasattr(self, "_viewer_has_unsaved") and self._viewer_has_unsaved(viewer):
            ans = QMessageBox.question(
                self,
                t("msg.warning"),
                t("pipeline.unsaved_prompt"),
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if ans == QMessageBox.StandardButton.Cancel:
                return
            if ans == QMessageBox.StandardButton.Save:
                self._save_pipeline()

        if hasattr(self, "_cleanup_pipeline"):
            self._cleanup_pipeline(id(viewer))

        viewer.close_doc()
        self._viewer_stack.removeWidget(viewer)
        self._viewers.pop(index)

        self._tab_bar.blockSignals(True)
        self._tab_bar.removeTab(index)
        self._tab_bar.blockSignals(False)
        viewer.deleteLater()

        if not self._viewers:
            self._add_viewer_tab()
        else:
            new_idx = min(index, len(self._viewers) - 1)
            self._tab_bar.setCurrentIndex(new_idx)
            self._viewer_stack.setCurrentIndex(new_idx)

        self._update_tab_bar_visibility()
        if hasattr(self, "_update_page_nav"):
            self._update_page_nav()
        if hasattr(self, "_update_breadcrumb"):
            self._update_breadcrumb()

    def _close_current_tab(self) -> None:
        if hasattr(self, "_viewer_stack"):
            self._close_tab(self._viewer_stack.currentIndex())

    def _on_tab_changed(self, index: int) -> None:
        if 0 <= index < len(self._viewers):
            self._viewer_stack.setCurrentIndex(index)
            viewer = self._viewers[index]
            self._update_tab_bar_visibility()
            if hasattr(self, "_update_page_nav"):
                self._update_page_nav()
            if hasattr(self, "_update_breadcrumb"):
                self._update_breadcrumb()
            if hasattr(self, "setWindowTitle"):
                doc_name = os.path.basename(viewer._original_doc_path or viewer.current_path()) if viewer.current_path() else ""
                if doc_name:
                    self.setWindowTitle(f"{t('app.name')} - {doc_name}")
                else:
                    self.setWindowTitle(t("app.name"))
            if getattr(self, "_current_tool", -1) >= 0:
                tool_w = self.stack.widget(self._current_tool)
                cur_path = viewer.current_path()
                fn = getattr(tool_w, "auto_load", None)
                if cur_path and callable(fn):
                    fn(cur_path)
            elif hasattr(self, "_setup_zoom_bar"):
                self._setup_zoom_bar(True, canvas=viewer._canvas)

    def _on_tab_context_menu(self, point: QPoint) -> None:
        tab_idx = self._tab_bar.tabAt(point)
        if tab_idx < 0:
            return
        viewer = self._viewers[tab_idx]
        path = viewer.current_path()
        dark = getattr(self, "_dark_mode", True)
        icon_color = TEXT_PRI if dark else _LQ

        menu = QMenu(self)

        # Tab navigation & closing actions
        act_close = menu.addAction(
            qta.icon("fa5s.times", color="#EF4444"),
            "Close Tab",
        )

        can_close_others = len(self._viewers) > 1
        act_close_others = menu.addAction(
            qta.icon("fa5s.window-close", color=icon_color),
            "Close All Other Tabs",
        )
        act_close_others.setEnabled(can_close_others)

        menu.addSeparator()

        # Filesystem actions
        act_reveal = None
        act_copy_path = None
        if path and os.path.exists(path):
            if sys.platform == "win32":
                reveal_label = "Reveal in File Explorer"
            elif sys.platform == "darwin":
                reveal_label = "Reveal in Finder"
            else:
                reveal_label = "Reveal in File Manager"

            act_reveal = menu.addAction(
                qta.icon("fa5s.folder-open", color=icon_color),
                reveal_label,
            )
            act_copy_path = menu.addAction(
                qta.icon("fa5s.copy", color=icon_color),
                "Copy Full Path",
            )

        chosen = menu.exec(self._tab_bar.mapToGlobal(point))
        if chosen == act_close:
            self._close_tab(tab_idx)
        elif chosen == act_close_others:
            for i in range(len(self._viewers) - 1, -1, -1):
                if i != tab_idx:
                    self._close_tab(i)
        elif act_reveal and chosen == act_reveal:
            reveal_file(path)
        elif act_copy_path and chosen == act_copy_path:
            QApplication.clipboard().setText(path)

    def _load_and_track(self, path: str) -> PdfViewerPanel | None:
        if not path or not os.path.isfile(path):
            return None
        norm_path = os.path.abspath(path)

        for i, v in enumerate(self._viewers):
            if v.current_path() and os.path.abspath(v.current_path()) == norm_path:
                self._tab_bar.setCurrentIndex(i)
                self._viewer_stack.setCurrentIndex(i)
                add_recent_file(norm_path)
                self._update_tab_bar_visibility()
                if hasattr(self, "_update_page_nav"):
                    self._update_page_nav()
                if hasattr(self, "_update_breadcrumb"):
                    self._update_breadcrumb()
                return v

        cur_v = self._viewer
        if cur_v and not cur_v.current_path():
            target_v = cur_v
            idx = self._viewer_stack.currentIndex()
        else:
            target_v = self._add_viewer_tab()
            idx = len(self._viewers) - 1

        target_v.load(norm_path)
        add_recent_file(norm_path)
        self._tab_bar.setTabText(idx, os.path.basename(norm_path))
        self._tab_bar.setTabToolTip(idx, norm_path)
        self._update_tab_bar_visibility()
        if hasattr(self, "_update_breadcrumb"):
            self._update_breadcrumb()
        if hasattr(self, "_update_page_nav"):
            self._update_page_nav()

        if getattr(self, "_current_tool", -1) >= 0:
            tool_w = self.stack.widget(self._current_tool)
            fn = getattr(tool_w, "auto_load", None)
            if callable(fn):
                fn(norm_path)
        return target_v

    def _on_second_instance(self, paths: list[str]) -> None:
        self.setWindowState(
            self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive
        )
        self.show()
        self.raise_()
        self.activateWindow()
        for p in paths:
            if os.path.isfile(p) and p.lower().endswith(".pdf"):
                self._load_and_track(p)

    def _on_canvas_crop_selected(self, page_idx: int, rect: tuple) -> None:
        crop_idx = self._crop_tool_idx() if hasattr(self, "_crop_tool_idx") else -1
        if crop_idx >= 0:
            crop_w = self.stack.widget(crop_idx)
            fn = getattr(crop_w, "on_canvas_crop_selected", None)
            if callable(fn):
                fn(page_idx, rect)

    def _on_canvas_crop_applied(self) -> None:
        crop_idx = self._crop_tool_idx() if hasattr(self, "_crop_tool_idx") else -1
        if crop_idx >= 0:
            crop_w = self.stack.widget(crop_idx)
            fn = getattr(crop_w, "apply_crop_preview", None)
            if callable(fn):
                fn()

    def _on_thumbnail_action_requested(self, action: str, pages_arg: object) -> None:
        if self._viewer and hasattr(self._viewer, "_on_thumbnail_action"):
            self._viewer._on_thumbnail_action(action, pages_arg)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        pdf_paths = [
            u.toLocalFile()
            for u in urls
            if u.toLocalFile().lower().endswith(".pdf") and os.path.isfile(u.toLocalFile())
        ]
        if pdf_paths:
            for p in pdf_paths:
                self._load_and_track(p)
            event.acceptProposedAction()
            return
        super().dropEvent(event)