# app/viewer/panel_history.py
"""PDFApps – Panel history, undo/redo state management, and temp pipeline persistence."""
import contextlib
import os
import tempfile

from app.utils import show_error
from app.pdf_io import atomic_pdf_write


class PanelHistoryMixin:
    """Mixin providing undo/redo history and pipeline modification saving."""

    def _cleanup_history_files(self):
        for path in getattr(self, "_history_temp_files", set()):
            if path and os.path.isfile(path) and path != self._original_doc_path:
                with contextlib.suppress(Exception):
                    os.unlink(path)
        self._history_temp_files = set()

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def undo(self):
        if not self._undo_stack:
            win = self.window()
            if hasattr(win, "_set_status"):
                win._set_status("ℹ Nothing to undo")
            return

        scroll_val = self._canvas_scroll.verticalScrollBar().value()
        viewed_page = self._canvas.page_at_y(scroll_val) if self._canvas.page_count() > 0 else 0
        selected_pages = self._thumbnails.selected_pages() if hasattr(self, "_thumbnails") else [0]
        cur_state = {
            "path": self._current_path,
            "target_page": viewed_page,
            "scroll_val": scroll_val,
            "selected_pages": selected_pages,
            "is_temp": bool(self._current_path != self._original_doc_path),
        }
        self._redo_stack.append(cur_state)

        target_state = self._undo_stack.pop()
        target_path = target_state["path"]
        current_tab_widget = self._sidebar_tabs.currentWidget()

        self._canvas.close_doc()
        if self._fitz_doc is not None:
            with contextlib.suppress(Exception):
                self._fitz_doc.close()
            self._fitz_doc = None
        self._thumbnails._stop_all_workers()

        self.load(
            target_path,
            target_page=target_state.get("target_page", 0),
            target_scroll=target_state.get("scroll_val", -1),
            selected_pages=target_state.get("selected_pages"),
            active_sidebar_tab=current_tab_widget,
            _is_history_step=True,
        )

        win = self.window()
        vid = id(self)
        if target_path == self._original_doc_path:
            if hasattr(win, "_pipeline_state"):
                win._pipeline_state.pop(vid, None)
            if hasattr(win, "_tab_bar") and hasattr(win, "_viewers"):
                for idx, v in enumerate(win._viewers):
                    if v is self:
                        orig_name = os.path.basename(self._original_doc_path)
                        win._tab_bar.setTabText(idx, orig_name)
                        win._tab_bar.setTabToolTip(idx, self._original_doc_path)
                        break
            if hasattr(win, "_set_status"):
                win._set_status("↩ Undo (Original document state)")
        else:
            if hasattr(win, "_pipeline_state"):
                win._pipeline_state[vid] = {
                    "original_path": self._original_doc_path,
                    "temp_path": target_path,
                }
            if hasattr(win, "_set_status"):
                win._set_status("↩ Undo")

        if hasattr(win, "_update_page_nav"):
            win._update_page_nav()

    def redo(self):
        if not self._redo_stack:
            win = self.window()
            if hasattr(win, "_set_status"):
                win._set_status("ℹ Nothing to redo")
            return

        scroll_val = self._canvas_scroll.verticalScrollBar().value()
        viewed_page = self._canvas.page_at_y(scroll_val) if self._canvas.page_count() > 0 else 0
        selected_pages = self._thumbnails.selected_pages() if hasattr(self, "_thumbnails") else [0]
        cur_state = {
            "path": self._current_path,
            "target_page": viewed_page,
            "scroll_val": scroll_val,
            "selected_pages": selected_pages,
            "is_temp": bool(self._current_path != self._original_doc_path),
        }
        self._undo_stack.append(cur_state)

        target_state = self._redo_stack.pop()
        target_path = target_state["path"]
        current_tab_widget = self._sidebar_tabs.currentWidget()

        self._canvas.close_doc()
        if self._fitz_doc is not None:
            with contextlib.suppress(Exception):
                self._fitz_doc.close()
            self._fitz_doc = None
        self._thumbnails._stop_all_workers()

        self.load(
            target_path,
            target_page=target_state.get("target_page", 0),
            target_scroll=target_state.get("scroll_val", -1),
            selected_pages=target_state.get("selected_pages"),
            active_sidebar_tab=current_tab_widget,
            _is_history_step=True,
        )

        win = self.window()
        vid = id(self)
        if target_path == self._original_doc_path:
            if hasattr(win, "_pipeline_state"):
                win._pipeline_state.pop(vid, None)
            if hasattr(win, "_tab_bar") and hasattr(win, "_viewers"):
                for idx, v in enumerate(win._viewers):
                    if v is self:
                        orig_name = os.path.basename(self._original_doc_path)
                        win._tab_bar.setTabText(idx, orig_name)
                        win._tab_bar.setTabToolTip(idx, self._original_doc_path)
                        break
        else:
            if hasattr(win, "_pipeline_state"):
                win._pipeline_state[vid] = {
                    "original_path": self._original_doc_path,
                    "temp_path": target_path,
                }
            if hasattr(win, "_tab_bar") and hasattr(win, "_viewers"):
                for idx, v in enumerate(win._viewers):
                    if v is self:
                        orig_name = os.path.basename(self._original_doc_path)
                        win._tab_bar.setTabText(idx, f"● {orig_name}")
                        win._tab_bar.setTabToolTip(idx, f"{self._original_doc_path} (modified)")
                        break

        if hasattr(win, "_set_status"):
            win._set_status("↪ Redo")
        if hasattr(win, "_update_page_nav"):
            win._update_page_nav()

    def _save_and_reload(self, doc_to_save, target_page: int | None = None, selected_pages: list[int] | None = None):
        """Persist modifications to a temporary pipeline file and reload live viewer without modifying original on disk."""
        try:
            win = self.window()
            vid = id(self)
            ps = getattr(win, "_pipeline_state", None)

            orig_path = self._original_doc_path or self._current_path

            # Preserve current state in undo history before applying new modification
            scroll_val = self._canvas_scroll.verticalScrollBar().value()
            viewed_page = self._canvas.page_at_y(scroll_val) if self._canvas.page_count() > 0 else 0
            cur_selected = self._thumbnails.selected_pages() if hasattr(self, "_thumbnails") else [0]
            prev_state = {
                "path": self._current_path,
                "target_page": viewed_page,
                "scroll_val": scroll_val,
                "selected_pages": cur_selected,
                "is_temp": bool(self._current_path != orig_path),
            }
            self._undo_stack.append(prev_state)
            if len(self._undo_stack) > 30:
                old_state = self._undo_stack.pop(0)
                if old_state.get("is_temp") and old_state.get("path") != self._current_path:
                    with contextlib.suppress(Exception):
                        os.unlink(old_state["path"])

            # Clear redo stack on new operation
            for red_s in self._redo_stack:
                if red_s.get("is_temp") and red_s.get("path") != self._current_path:
                    with contextlib.suppress(Exception):
                        os.unlink(red_s["path"])
            self._redo_stack.clear()

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

            # Release all open document handles before writing to temp
            self._canvas.close_doc()
            if self._fitz_doc is not None:
                with contextlib.suppress(Exception):
                    self._fitz_doc.close()
                self._fitz_doc = None
            self._thumbnails._stop_all_workers()

            fd, temp_path = tempfile.mkstemp(prefix="pdfapps_modified_", suffix=".pdf")
            os.close(fd)
            self._history_temp_files.add(temp_path)

            atomic_pdf_write(
                doc_to_save, temp_path,
                save_opts={"garbage": 4, "deflate": True},
                close_writer=True,
            )

            if ps is not None:
                ps[vid] = {
                    "original_path": orig_path,
                    "temp_path": temp_path,
                }

            self.load(
                temp_path,
                target_page=viewed_page,
                target_scroll=scroll_val,
                selected_pages=selected_pages,
                active_sidebar_tab=current_tab_widget,
                _is_history_step=True,
            )

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