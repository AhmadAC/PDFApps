# app/viewer/panel_nav.py
"""PDFApps – Navigation, TOC generation, recent files, and theme rendering."""
import logging
import os

from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QDialog, QTreeWidgetItem
)
import qtawesome as qta
import fitz

from app.constants import ACCENT, TEXT_SEC, _LQ, DESKTOP
from app.pdf_password import authenticate_fitz
from app.utils import _paint_bg
from app.i18n import t

_log = logging.getLogger(__name__)


class PanelNavMixin:
    """Mixin for navigation, recent list, TOC, zoom, and theme operations."""

    def _toggle_pages_sidebar(self):
        if not self._pages_sidebar_collapsed:
            self._saved_sidebar_width = max(180, self._sidebar_panel.width())
            self._pages_sidebar_collapsed = True
            self._sidebar_panel.setVisible(False)
            total = self._viewer_splitter.width() or 1020
            self._viewer_splitter.setSizes([0, total])
            self.__class__._pages_sidebar_visible_pref = False
        else:
            self._pages_sidebar_collapsed = False
            self._sidebar_panel.setVisible(True)
            self._sidebar_tabs.setVisible(True)
            w = min(400, max(180, getattr(self, "_saved_sidebar_width", 220)))
            total = self._viewer_splitter.width() or 1020
            self._viewer_splitter.setSizes([w, max(300, total - w)])
            self.__class__._pages_sidebar_visible_pref = True

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
                f"QPushButton {{ border: 1px solid transparent; background: transparent; }}"
                f"QPushButton:hover {{ background: rgba(239,68,68,0.15); border-radius: 4px; }}"
                f"QPushButton:focus {{ border: 1px solid {ACCENT}; border-radius: 4px; }}")
            del_btn.clicked.connect(lambda checked, p=rp, r=row: self._remove_recent(p, r))
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

    def _on_thumbnail_clicked(self, page_idx: int) -> None:
        y = self._canvas.scroll_to_page(int(page_idx))
        self._canvas_scroll.verticalScrollBar().setValue(y)

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

    def load(self, path: str, target_page: int = 0, target_scroll: int = -1, selected_pages: list[int] | None = None, active_sidebar_tab: QWidget | int | None = None, _is_history_step: bool = False):
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
        self.set_page_crops({})
        self._canvas.load(doc, target_page, path=path, password=getattr(self, "_pdf_password", ""), target_scroll=target_scroll)
        if target_scroll >= 0:
            self._canvas_scroll.verticalScrollBar().setValue(target_scroll)
        elif 0 < target_page < doc.page_count:
            self._canvas_scroll.verticalScrollBar().setValue(self._canvas.scroll_to_page(target_page))
        else:
            self._canvas_scroll.verticalScrollBar().setValue(0)

        self._placeholder.setVisible(False)
        self._viewer_splitter.setVisible(True)

        show_pages = getattr(self.__class__, "_pages_sidebar_visible_pref", True)
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

        display_name = os.path.basename(self._original_doc_path or path)
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

    def _zoom_fit(self):
        self._canvas.zoom_reset()
        self._zoom_lbl.setText(t("zoom.fit"))

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