# app\base.py

"""PDFApps – BasePage: standard page layout (header + scroll + action bar)."""

import os
import tempfile
import shutil
from typing import Iterable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QPushButton, QLabel
)
from shiboken6 import isValid

from app import pdf_io
from app.constants import DESKTOP, ACCENT
from app.i18n import t
from app.utils import (ToolHeader, ActionBar, scrolled, _paint_bg,
                       WrongPasswordError, reveal_file, open_folder)

# Backward-compatibility aliases
_reveal_file = reveal_file
_open_folder = open_folder

__all__ = ["BasePage", "Iterable", "_reveal_file", "_open_folder"]


class BasePage(QWidget):
    """Standard layout: header + scroll area + action bar."""

    pipeline_done = Signal(str)  # emitted with temp output path
    pipeline_save_requested = Signal()  # toast "Save as..." button clicked

    def __init__(self, icon, title, desc, action_text, status_fn):
        super().__init__()
        self._status = status_fn
        self.setObjectName("content_area")
        self._pipeline_active = False
        self._pipeline_supported = False  # subclasses set True if they emit pipeline_done
        self._pipeline_tmp_dir: str | None = None
        # Password captured by _maybe_prompt_password for the loaded PDF.
        # Persists for the lifetime of one input file so _run can re-open
        # the same PDF (or fitz.Document) without re-prompting.
        self._pdf_password: str = ""

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # Header inside the scrollable container so scrolling down scrolls the header away
        self._header = ToolHeader(icon, title, desc)

        # scrollable content
        self._inner = QWidget(); self._inner.setObjectName("scroll_inner")
        self._inner.setMinimumWidth(0)
        inner_layout = QVBoxLayout(self._inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        inner_layout.addWidget(self._header)

        form_container = QWidget()
        self._form = QVBoxLayout(form_container)
        self._form.setContentsMargins(24, 16, 24, 20)
        self._form.setSpacing(10)
        inner_layout.addWidget(form_container, 1)

        scroll_area = scrolled(self._inner)
        scroll_area.setMinimumWidth(0)
        page_layout.addWidget(scroll_area, 1)
        # Allow this page to shrink below its content's natural width — the
        # splitter needs this so the side panel can be made narrow.
        self.setMinimumWidth(0)

        # Widgets hidden when entering "compact mode" (input/output already
        # known from the viewer). Subclasses populate this list during build.
        self._compact_hidden: list = []
        self._compact_active = False
        self._compact_link: QPushButton | None = None

        # fixed action bar
        self._action_bar, self.action_btn = ActionBar(action_text, self._run)
        page_layout.addWidget(self._action_bar)

    def paintEvent(self, event):
        _paint_bg(self)

    def update_theme(self, dark: bool) -> None:
        """Default theme refresh: re-skins the action bar's progress
        strip. Subclasses overriding this should call ``super().update_theme(dark)``
        so the progress strip keeps tracking the theme.
        """
        fn = getattr(self._action_bar, "update_theme", None)
        if callable(fn):
            try: fn(dark)
            except RuntimeError: pass  # widget destroyed

    def _build(self):
        """Subclasses add widgets to self._form here."""

    def _run(self):
        """Main logic called by the action button."""

    def _prompt_save_as(self, default_name: str = "result.pdf",
                        start_dir: str = "", filter_key: str = "file_filter.pdf") -> str:
        """Open a Save File dialog and return the chosen path (or "")."""
        base = start_dir if start_dir and os.path.isdir(start_dir) else DESKTOP
        suggested = os.path.join(base, default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, t("btn.choose"), suggested, t(filter_key))
        return path or ""

    def _prompt_save_dir(self, start_dir: str = "") -> str:
        """Open a folder picker and return the chosen directory (or "")."""
        base = start_dir if start_dir and os.path.isdir(start_dir) else DESKTOP
        return QFileDialog.getExistingDirectory(self, t("btn.choose"), base) or ""

    def _resolve_output_file(self, drop_widget, input_path: str = "",
                             filter_key: str = "file_filter.pdf") -> str:
        """Return the output file path, prompting via Save dialog if empty.
        In pipeline mode, returns a temp file path instead of prompting."""
        if self._pipeline_active:
            return self._make_pipeline_temp(input_path, drop_widget)
        out = drop_widget.path()
        if out:
            return out
        default_name = getattr(drop_widget, "_default", "") or "result.pdf"
        if input_path:
            base, ext = os.path.splitext(os.path.basename(input_path))
            stem, sfx = os.path.splitext(default_name)
            if sfx:
                default_name = base + "_" + stem + sfx
        start_dir = os.path.dirname(input_path) if input_path else ""
        out = self._prompt_save_as(default_name, start_dir, filter_key)
        if out:
            drop_widget.set_path(out)
        return out

    def _make_pipeline_temp(self, input_path: str, drop_widget=None) -> str:
        """Create a temp file path for pipeline output."""
        if self._pipeline_tmp_dir is None:
            self._pipeline_tmp_dir = tempfile.mkdtemp(prefix="pdfapps_")
        default_name = (getattr(drop_widget, "_default", "") or "result.pdf") if drop_widget else "result.pdf"
        if input_path:
            base, ext = os.path.splitext(os.path.basename(input_path))
            stem, sfx = os.path.splitext(default_name)
            if sfx:
                default_name = base + "_" + stem + sfx
        return os.path.join(self._pipeline_tmp_dir, default_name)

    def _pipeline_success(self, message: str, out_path: str) -> None:
        """Call after a successful tool run in pipeline mode:
        shows a toast (with a prominent "Save as..." button) and emits
        the pipeline_done signal."""
        self._show_toast(message, out_path, with_save=True)
        self.pipeline_done.emit(out_path)

    def cleanup_pipeline(self) -> None:
        """Remove temp files created during pipeline."""
        if self._pipeline_tmp_dir and os.path.isdir(self._pipeline_tmp_dir):
            shutil.rmtree(self._pipeline_tmp_dir, ignore_errors=True)
            self._pipeline_tmp_dir = None

    def set_compact_mode(self, active: bool, path: str = "") -> None:
        """Hide source/output boilerplate when the input PDF is implicit
        (e.g. coming from the viewer with a loaded document)."""
        if active and path:
            fn = getattr(self, "auto_load", None)
            if callable(fn):
                fn(path)

        for w in self._compact_hidden:
            try:
                w.setVisible(not active)
            except RuntimeError:
                pass

        if active and self._compact_link is None:
            link = QPushButton("← " + t("compact.change_source"))
            link.setObjectName("compact_link")
            link.setFlat(True)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setStyleSheet(
                f"QPushButton#compact_link {{ color:{ACCENT}; border:none; "
                f"background:transparent; padding:2px 4px; text-align:left; }}"
                f"QPushButton#compact_link:hover {{ text-decoration: underline; }}"
            )
            link.clicked.connect(
                lambda: self.set_compact_mode(False) if isValid(self) else None)
            self._form.insertWidget(0, link)
            self._compact_link = link

        if self._compact_link is not None:
            self._compact_link.setVisible(active)

        self._compact_active = active
        self._pipeline_active = active and self._pipeline_supported

    def _show_toast(self, message: str, file_path: str = "",
                    with_save: bool = False) -> None:
        """Show a brief success toast above the action bar with optional
        'Save as...' / 'Open file' / 'Open folder' buttons."""
        old = getattr(self, "_toast_widget", None)
        if old:
            old.setParent(None); old.deleteLater()

        toast = QWidget(); toast.setObjectName("toast")
        toast.setStyleSheet(
            "#toast { background: #065F46; border: 1px solid #10B981; "
            "border-radius: 8px; padding: 8px 12px; }"
            "#toast QLabel { color: white; font-size: 10pt; background: transparent; }"
            "#toast QPushButton { color: #A7F3D0; border: none; background: transparent; "
            "font-size: 10pt; text-decoration: underline; padding: 0 4px; }"
            "#toast QPushButton:hover { color: white; }"
            "#toast QPushButton#toast_save { color: white; font-weight: 600; }")
        h = QHBoxLayout(toast); h.setContentsMargins(8, 4, 8, 4); h.setSpacing(8)
        h.addWidget(QLabel(f"✔ {message}"), 1)
        if with_save:
            btn_save = QPushButton(t("widget.save_as"))
            btn_save.setObjectName("toast_save")
            btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_save.clicked.connect(self.pipeline_save_requested)
            h.addWidget(btn_save)
        if file_path and os.path.exists(file_path):
            btn_file = QPushButton(t("toast.open_file"))
            btn_file.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_file.clicked.connect(lambda: reveal_file(file_path))
            h.addWidget(btn_file)
            btn_folder = QPushButton(t("toast.open_folder"))
            btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_folder.clicked.connect(lambda: open_folder(file_path))
            h.addWidget(btn_folder)

        layout = self.layout()
        idx = layout.indexOf(self._action_bar)
        layout.insertWidget(idx, toast)
        self._toast_widget = toast
        if not with_save:
            QTimer.singleShot(
                8000, lambda t=toast: t.setVisible(False) if isValid(t) else None)

    def _resolve_output_dir(self, drop_widget, input_path: str = "") -> str:
        """Return the output directory, prompting via folder picker if empty."""
        out = drop_widget.path()
        if out:
            return out
        start_dir = os.path.dirname(input_path) if input_path else ""
        out = self._prompt_save_dir(start_dir)
        if out:
            drop_widget.set_path(out)
        return out

    # ── encrypted-PDF helpers ──────────────────────────────────────────────

    def _maybe_prompt_password(self, path: str) -> bool:
        from app.pdf_password import authenticate_fitz
        try:
            import fitz
            doc = fitz.open(path)
        except Exception:
            return True
        try:
            if not doc.needs_pass:
                self._pdf_password = ""
                return True
            if self._pdf_password:
                winner = authenticate_fitz(doc, self._pdf_password)
                if winner is not None:
                    self._pdf_password = winner
                    return True
        finally:
            doc.close()
        from app.utils import prompt_pdf_password
        ok, pwd = prompt_pdf_password(path, self)
        if not ok:
            return False
        self._pdf_password = pwd
        return True

    def _open_reader(self, path: str):
        from app.pdf_password import decrypt_pypdf
        from pypdf import PdfReader
        r = PdfReader(path)
        if r.is_encrypted and self._pdf_password:
            if decrypt_pypdf(r, self._pdf_password) is None:
                raise WrongPasswordError(t("tool.err.wrong_password"))
        return r

    def _open_fitz(self, path: str):
        from app.pdf_password import authenticate_fitz
        import fitz
        doc = fitz.open(path)
        if doc.needs_pass and self._pdf_password:
            if authenticate_fitz(doc, self._pdf_password) is None:
                raise WrongPasswordError(t("tool.err.wrong_password"))
        return doc

    def _clear_pdf_password(self) -> None:
        from app.utils import wipe_pdf_password
        wipe_pdf_password(self)

    # ── safe PDF writer ────────────────────────────────────────────────────

    @staticmethod
    def _check_not_same_path(dst: str,
                             sources: "Iterable[str] | None" = None) -> None:
        pdf_io.check_not_same_path(dst, sources)

    @staticmethod
    def _atomic_pdf_write(writer, dst: str, *,
                          sources: "Iterable[str] | None" = None,
                          save_opts: "dict | None" = None,
                          close_writer: bool = False) -> None:
        pdf_io.atomic_pdf_write(writer, dst, sources=sources,
                                save_opts=save_opts,
                                close_writer=close_writer)

    # ── background-task helper ────────────────────────────────────────────

    def _run_background(self, do_work_fn, total: int, label: str,
                        on_done=None, on_err=None,
                        cancelled_status: str = "") -> None:
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QProgressDialog
        from app.worker import TaskRunner, run_task
        from app.utils import show_error

        progress = QProgressDialog(label, t("progress.cancel"), 0, total, self)
        progress.setWindowModality(_Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        class _Run(TaskRunner):
            def do_work(_self):
                return do_work_fn(_self)

        self.action_btn.setEnabled(False)

        def _wrap_done(r):
            self.action_btn.setEnabled(True)
            if r is None:
                self._status(cancelled_status or t("progress.cancelled"))
                return
            if on_done:
                on_done(r)

        def _wrap_err(exc):
            if not isinstance(exc, BaseException):
                exc = RuntimeError(str(exc))
            self.action_btn.setEnabled(True)
            if on_err:
                on_err(exc)
            else:
                show_error(self, exc)

        self._bg_runner = _Run()
        self._bg_thread = run_task(self, self._bg_runner, progress,
                                   _wrap_done, _wrap_err)

    def wait_for_workers(self, timeout_ms: int = 2000) -> None:
        from PySide6.QtCore import QCoreApplication, QEventLoop
        import time

        threads = []
        for runner_attr, thread_attr in (("_runner", "_runner_thread"),
                                          ("_bg_runner", "_bg_thread")):
            runner = getattr(self, runner_attr, None)
            thread = getattr(self, thread_attr, None)
            if thread is None:
                continue
            try:
                if not isValid(thread) or not thread.isRunning():
                    continue
            except RuntimeError:
                continue
            if runner is not None and isValid(runner):
                try: runner.cancel()
                except Exception: pass
            threads.append(thread)
        if not threads:
            return
        deadline = time.monotonic() + timeout_ms / 1000
        flags = QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
        while time.monotonic() < deadline:
            still_running = False
            for thread in threads:
                try:
                    if isValid(thread) and thread.isRunning():
                        still_running = True
                        break
                except RuntimeError:
                    pass
            if not still_running:
                break
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                break
            QCoreApplication.processEvents(flags, min(50, remaining_ms))