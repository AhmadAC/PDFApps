# app/window_pipeline.py
"""PDFApps – Pipeline processing, state saving, and security wiping mixin."""
import contextlib
import os
import shutil
import tempfile
import logging

from PySide6.QtWidgets import QFileDialog

from app.i18n import t
from app.base import BasePage


class WindowPipelineMixin:
    """Mixin for managing pipeline processing, undo/redo, and worker lifecycles."""

    def _handle_global_undo(self):
        edit_idx = self._edit_tool_idx()
        crop_idx = self._crop_tool_idx()
        rotate_idx = self._rotate_tool_idx()
        
        if self._current_tool == edit_idx:
            self.stack.widget(edit_idx)._undo()
        elif self._current_tool == crop_idx:
            self.stack.widget(crop_idx)._undo()
        elif self._current_tool == rotate_idx:
            self.stack.widget(rotate_idx)._undo()
        elif self._current_tool == -1:
            self._viewer.undo()

    def _handle_global_redo(self):
        edit_idx = self._edit_tool_idx()
        crop_idx = self._crop_tool_idx()
        rotate_idx = self._rotate_tool_idx()
        
        if self._current_tool == edit_idx:
            self.stack.widget(edit_idx)._redo()
        elif self._current_tool == crop_idx:
            self.stack.widget(crop_idx)._redo()
        elif self._current_tool == rotate_idx:
            self.stack.widget(rotate_idx)._redo()
        elif self._current_tool == -1:
            self._viewer.redo()

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
                logging.getLogger("pdfapps").warning("Pipeline save destination is a symlink: %s -> %s", path, os.path.realpath(path))
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

    def _save_current_tool(self):
        vid = id(self._viewer)
        ps = self._pipeline_state.get(vid)
        if ps and ps.get("temp_path"):
            self._save_pipeline()
        elif self._current_tool >= 0:
            w = self.stack.widget(self._current_tool)
            if hasattr(w, '_run'):
                w._run()

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