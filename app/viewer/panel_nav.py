# app/viewer/panel_nav.py
"""PDFApps – Navigation, TOC generation, recent files, and theme rendering."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import fitz
from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QDialog, QTreeWidgetItem,
    QScrollArea, QSplitter, QTabWidget, QTreeWidget, QVBoxLayout,
)
import qtawesome as qta

from app.constants import ACCENT, TEXT_SEC, _LQ, DESKTOP
from app.pdf_password import authenticate_fitz
from app.utils import _paint_bg
from app.i18n import t

if TYPE_CHECKING:
    from app.viewer.canvas_1 import _SelectCanvas
    from app.viewer.thumbnails import ThumbnailPanel
    _Base = QWidget
else:
    _Base = object

_log = logging.getLogger(__name__)


class PanelNavMixin(_Base):
    """Mixin for navigation, recent list, TOC, zoom, and theme operations."""

    _pages_sidebar_visible_pref: bool | None = None
    _saved_sidebar_width_pref: int | None = None

    if TYPE_CHECKING:
        _current_path: str
        _original_doc_path: str
        _fitz_doc: fitz.Document | None
        _pdf_password: str
        _pages_sidebar_collapsed: bool
        _saved_sidebar_width: int
        _sidebar_panel: QWidget
        _sidebar_tabs: QTabWidget
        _viewer_splitter: QSplitter
        _canvas_scroll: QScrollArea
        _canvas: _SelectCanvas
        _thumbnails: ThumbnailPanel
        _toc_tree: QTreeWidget
        _toc_tab_idx: int
        _pages_tab_idx: int
        _placeholder: QWidget
        _name_lbl: QLabel
        _page_lbl: QLabel
        _zoom_lbl: QLabel
        _open_btn: QPushButton
        _toc_btn: QPushButton
        _night_btn: QPushButton
        _prev_btn: QPushButton
        _next_btn: QPushButton
        _zoom_out_btn: QPushButton
        _zoom_in_btn: QPushButton
        _fit_btn: QPushButton
        _print_btn: QPushButton
        _search_prev_btn: QPushButton
        _search_next_btn: QPushButton
        _search_close_btn: QPushButton
        _recent_links: list[QPushButton]
        _recent_del_btns: list[QPushButton]
        _recents_layout: QVBoxLayout
        _undo_stack: list[dict]
        _redo_stack: list[dict]

        def _cleanup_history_files(self) -> None: ...
        def _reset_search_state(self) -> None: ...

    def _toggle_pages_sidebar(self):
        from app.viewer.panel import PdfViewerPanel

        if not self._pages_sidebar_collapsed:
            self._saved_sidebar_width = max(70, self._sidebar_panel.width())
            PdfViewerPanel._saved_sidebar_width_pref = self._saved_sidebar_width
            type(self)._saved_sidebar_width_pref = self._saved_sidebar_width
            self._pages_sidebar_collapsed = True
            self._sidebar_panel.setVisible(False)
            total = self._viewer_splitter.width() or 1020
            self._viewer_splitter.setSizes([0, total])
            type(self)._pages_sidebar_visible_pref = False
            PdfViewerPanel._pages_sidebar_visible_pref = False
        else:
            self._pages_sidebar_collapsed = False
            self._sidebar_panel.setVisible(True)
            self._sidebar_tabs.setVisible(True)
            w = min(500, max(70, getattr(self, "_saved_sidebar_width", 220)))
            total = self._viewer_splitter.width() or 1020
            self._viewer_splitter.setSizes([w, max(300, total - w)])
            type(self)._pages_sidebar_visible_pref = True
            PdfViewerPanel._pages_sidebar_visible_pref = True

        try:
            from app.i18n import _update_config
            pref = not self._pages_sidebar_collapsed
            saved_w = self._saved_sidebar_width
            def _save_nav_pref(cfg: dict) -> None:
                cfg["pages_sidebar_open"] = pref
                cfg["sidebar_panel_width"] = saved_w
            _update_config(_save_nav_pref)
        except Exception:
            pass

        QTimer.singleShot(0, self._canvas._on_viewport_resized)

    def set_crop_mode(self, active: bool):
        if hasattr(self, "_canvas"):
            self._canvas.set_crop_mode(active)

    def set_crop_preview(self, crop_data: dict | None):
        if hasattr(self, "_canvas"):
            self._canvas.set_crop_preview(crop_data)

    def set_numbers_preview(self, preview_data: dict | None):
        """Update live preview for page numbers on the continuous scroll canvas."""
        if hasattr(self, "_canvas"):
            self._canvas.set_numbers_preview(preview_data)

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

    def set_page_order(self, order: list[int] | None):
        """Update live preview page order across continuous scroll and thumbnail sidebar."""
        if hasattr(self, "_canvas"):
            self._canvas.set_page_order(order)
        if hasattr(self, "_thumbnails"):
            self._thumbnails.set_page_order(order)

    def _on_zoom_changed(self, pct: int):
        self._zoom_lbl.setText(f"{pct}%")
        self._update_page_label()

    def _on_scroll(self, val: int):
        self._canvas.on_scroll()
        self._update_page_label()

    def paintEvent(self, event):
        _paint_bg(self)

    def eventFilter(self, obj, event):
        if hasattr(self, "_viewer_splitter") and obj is self._viewer_splitter.handle(1):
            if event.type() == QEvent.Type.MouseButtonDblClick:
                if hasattr(self, "_thumbnails"):
                    self._thumbnails.fit_window_to_thumbnails()
                    return True
        if obj is self._canvas_scroll.viewport():
            if event.type() == QEvent.Type.Wheel:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                    if event.angleDelta().y() > 0:
                        self._canvas.zoom_in(anchor_pos=pos)
                    else:
                        self._canvas.zoom_out(anchor_pos=pos)
                    return True
            elif event.type() == QEvent.Type.Resize:
                if self._canvas._doc:
                    QTimer.singleShot(0, self._canvas._on_viewport_resized)
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
        self._open_btn.setIcon(qta.icon('fa5s.folder-open', color=c))
        self._toc_btn.setIcon(qta.icon('fa5s.bookmark', color=c))
        self._night_btn.setIcon(qta.icon('fa5s.moon', color=c))
        self._prev_btn.setIcon(qta.icon('fa5s.chevron-left', color=c))
        self._next_btn.setIcon(qta.icon('fa5s.chevron-right', color=c))
        self._zoom_out_btn.setIcon(qta.icon('fa5s.search-minus', color=c))
        self._zoom_in_btn.setIcon(qta.icon('fa5s.search-plus', color=c))
        self._fit_btn.setIcon(qta.icon('fa5s.compress-arrows-alt', color=c))
        self._print_btn.setIcon(qta.icon('fa5s.print', color=c))
        self._search_prev_btn.setIcon(qta.icon('fa5s.chevron-up', color=c))
        self._search_next_btn.setIcon(qta.icon('fa5s.chevron-down', color=c))
        self._search_close_btn.setIcon(qta.icon('fa5s.times', color=c))
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
            if item:
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
        rec_title.setStyleSheet("font-size: 10pt; font-weight: 600; opacity: 0.7;")
        lay.addWidget(rec_title)

        dark = getattr(self.window(), "_dark_mode", True) if self.window() else True
        link_style = self._recent_link_style(dark=dark)
        for rp in recents[:5]:
            if not os.path.lexists(rp) or os.path.isdir(rp):
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
            link.setStyleSheet(link_style)
            link.clicked.connect(lambda checked=False, p=rp, r=row: self._on_recent_clicked(p, r))
            self._recent_links.append(link)
            del_btn = QPushButton()
            del_btn.setIcon(qta.icon("fa5s.trash-alt", color=TEXT_SEC if dark else _LQ))
            del_btn.setFixedSize(28, 28)
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.setFlat(True)
            del_btn.setToolTip(t("btn.remove"))
            del_btn.setAccessibleName(t("btn.remove"))
            del_btn.setStyleSheet(
                f"QPushButton {{ border: 1px solid transparent; background: transparent; }}"
                f"QPushButton:hover {{ background: rgba(239,68,68,0.15); border-radius: 4px; }}"
                f"QPushButton:focus {{ border: 1px solid {ACCENT}; border-radius: 4px; }}")
            del_btn.clicked.connect(lambda checked, p=rp, r=row: self._remove_recent(p, r))
            self._recent_del_btns.append(del_btn)
            row_h.addWidget(link, 1)
            row_h.addWidget(del_btn)
            lay.addWidget(row)

    def _on_recent_clicked(self, path: str, row_widget=None):
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

        win: Any = self.window()
        if win and hasattr(win, "_load_and_track"):
            win._load_and_track(resolved)
        else:
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
            win: Any = self.window()
            if win and hasattr(win, "_load_and_track"):
                win._load_and_track(path)
            else:
                self.load(path)

    def current_path(self) -> str:
        return self._current_path

    def _set_toc_tab_visible(self, visible: bool) -> None:
        if hasattr(self._sidebar_tabs, "setTabVisible"):
            self._sidebar_tabs.setTabVisible(self._toc_tab_idx, visible)
            return
        present = self._sidebar_tabs.indexOf(self._toc_tree) != -1
        if visible and not present:
            self._sidebar_tabs.insertTab(0, self._toc_tree, t("viewer.sidebar.contents"))
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
        self._canvas._active_page_idx = int(page_idx)

    def _on_thumbnail_clicked(self, page_idx: int) -> None:
        y = self._canvas.scroll_to_page(int(page_idx))
        self._canvas_scroll.verticalScrollBar().setValue(y)
        self._canvas._active_page_idx = int(page_idx)

    def _toggle_night_mode(self):
        self._canvas.set_night_mode(self._night_btn.isChecked())

    def _on_doc_replaced(self, new_doc):
        self._fitz_doc = new_doc

    def _reset_to_placeholder(self):
        self._current_path = ""
        self._original_doc_path = ""
        self._fitz_doc = None
        self._cleanup_history_files()
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._reset_search_state()
        self.set_crop_mode(False)
        self.set_crop_preview(None)
        self.set_numbers_preview(None)
        self.set_page_crops({})
        self.set_page_order(None)
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

        win: Any = self.window()
        if win:
            if hasattr(win, "_tab_bar") and hasattr(win, "_viewers"):
                for idx, v in enumerate(win._viewers):
                    if v is self:
                        win._tab_bar.setTabText(idx, t("viewer.title"))
                        win._tab_bar.setTabToolTip(idx, "")
                        break
            if hasattr(win, "_update_tab_bar_visibility"):
                win._update_tab_bar_visibility()
            if hasattr(win, "_update_breadcrumb"):
                win._update_breadcrumb()
            if hasattr(win, "setWindowTitle"):
                win.setWindowTitle(t("app.name"))

    def load(self, path: str, target_page: int = 0, target_scroll: int = -1, selected_pages: list[int] | None = None, active_sidebar_tab: QWidget | int | None = None, _is_history_step: bool = False):
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
            QMessageBox.warning(self, t("viewer.invalid_format"), t("viewer.invalid_msg"))
            return

        if not _is_history_step:
            self._original_doc_path = path
            self._cleanup_history_files()
            self._undo_stack.clear()
            self._redo_stack.clear()

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
            QMessageBox.critical(self, t("viewer.error_open"), t("viewer.error_open_msg", ex=ex))
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
        self._fitz_doc = doc
        self.set_page_rotations({})
        self.set_crop_preview(None)
        self.set_numbers_preview(None)
        self.set_page_crops({})
        self.set_page_order(None)

        self._placeholder.setVisible(False)
        self._viewer_splitter.setVisible(True)

        show_pages = getattr(type(self), "_pages_sidebar_visible_pref", True)
        if show_pages is None:
            show_pages = True
        self._pages_sidebar_collapsed = not show_pages
        self._sidebar_panel.setVisible(show_pages)
        self._sidebar_tabs.setVisible(show_pages)
        total = self._viewer_splitter.width() or 1020
        if show_pages:
            w = min(500, max(70, getattr(self, "_saved_sidebar_width", 220)))
            self._viewer_splitter.setSizes([w, max(300, total - w)])
        else:
            self._viewer_splitter.setSizes([0, total])

        self._canvas.load(doc, target_page, path=path, password=getattr(self, "_pdf_password", ""), target_scroll=target_scroll)
        self._canvas._active_page_idx = target_page

        if target_scroll >= 0:
            self._canvas_scroll.verticalScrollBar().setValue(target_scroll)
        elif 0 < target_page < doc.page_count:
            self._canvas_scroll.verticalScrollBar().setValue(self._canvas.scroll_to_page(target_page))
        else:
            self._canvas_scroll.verticalScrollBar().setValue(0)

        QTimer.singleShot(50, self._canvas._on_viewport_resized)

        display_name = os.path.basename(self._original_doc_path or path)
        win: Any = self.window()
        if win and hasattr(win, "_pipeline_state"):
            ps = win._pipeline_state.get(id(self))
            if ps and ps.get("original_path"):
                display_name = f"● {os.path.basename(ps['original_path'])}"
        self._name_lbl.setText(display_name)

        if win:
            if hasattr(win, "_tab_bar") and hasattr(win, "_viewers"):
                for idx, v in enumerate(win._viewers):
                    if v is self:
                        win._tab_bar.setTabText(idx, display_name)
                        win._tab_bar.setTabToolTip(idx, self._original_doc_path or path)
                        break
            if hasattr(win, "_update_tab_bar_visibility"):
                win._update_tab_bar_visibility()
            if hasattr(win, "_update_breadcrumb"):
                win._update_breadcrumb()
            if hasattr(win, "setWindowTitle"):
                win.setWindowTitle(f"{t('app.name')} - {display_name}")

        self._zoom_lbl.setText(f"{round(self._canvas._zoom_factor * 100)}%")
        for btn in (self._zoom_out_btn, self._zoom_in_btn, self._fit_btn,
                    self._print_btn, self._night_btn):
            btn.setEnabled(True)
        self._toc_btn.setVisible(True)
        self._toc_btn.setEnabled(True)
        self._thumbnails.set_document(path, doc.page_count, password=getattr(self, "_pdf_password", ""))

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

    def _update_page_label(self):
        pages = self._canvas._entries
        if not pages:
            self._page_lbl.setText("— / —")
            self._prev_btn.setEnabled(False)
            self._next_btn.setEnabled(False)
            return
        sb = self._canvas_scroll.verticalScrollBar()
        sb_val = sb.value() if sb else 0
        idx = self._canvas.page_at_y(sb_val)
        self._canvas._active_page_idx = idx
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
            target = idx - 1
            self._canvas._active_page_idx = target
            sb.setValue(self._canvas.scroll_to_page(target))

    def _next_page(self):
        if not self._canvas._entries:
            return
        sb = self._canvas_scroll.verticalScrollBar()
        idx = self._canvas.page_at_y(sb.value())
        if idx < len(self._canvas._entries) - 1:
            target = idx + 1
            self._canvas._active_page_idx = target
            sb.setValue(self._canvas.scroll_to_page(target))

    def _zoom_fit(self):
        self._canvas.zoom_reset()
        self._zoom_lbl.setText(f"{round(self._canvas._zoom_factor * 100)}%")

    def _clear_pdf_password(self) -> None:
        from app.utils import wipe_pdf_password
        wipe_pdf_password(self)

    def closeEvent(self, event):
        self._clear_pdf_password()
        self._cleanup_history_files()
        try:
            self._thumbnails.clear()
        except Exception:
            pass
        super().closeEvent(event)

