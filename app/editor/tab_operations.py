# app/editor/tab_operations.py
"""PDFApps – tab_operations: form operations and PDF saving logic for TabEditar."""

import contextlib
import logging
import os
import tempfile
import fitz
from PySide6.QtWidgets import QMessageBox, QTableWidgetItem

from app.i18n import t
from app.utils import show_error, WrongPasswordError
from app.editor.apply_edits import apply_pending_edits
from app.pdf_io import atomic_pdf_write
from app.pdf_password import decrypt_pypdf

_log = logging.getLogger(__name__)


def prompt_encryption_choice(parent) -> str | None:
    """Prompt user whether to keep or remove PDF encryption upon saving."""
    box = QMessageBox(parent)
    box.setWindowTitle(t("editor.encrypt.warning_title"))
    box.setText(t("editor.encrypt.warning_text"))
    box.setIcon(QMessageBox.Icon.Warning)
    keep_btn = box.addButton(t("editor.encrypt.save_protected"), QMessageBox.ButtonRole.AcceptRole)
    plain_btn = box.addButton(t("editor.encrypt.save_unprotected"), QMessageBox.ButtonRole.DestructiveRole)
    cancel_btn = box.addButton(t("btn.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(keep_btn)
    box.exec()
    clicked = box.clickedButton()
    if clicked is keep_btn:
        return "protect"
    if clicked is plain_btn:
        return "plaintext"
    return None


def get_fitz_permissions(doc) -> int:
    """Extract standard PDF permission bitmask flags from PyMuPDF doc."""
    try:
        perms = getattr(doc, "permissions", -1)
        return int(perms) if perms is not None else -1
    except Exception:
        return -1


def cleanup_signature_temp_file(signature_path: str | None) -> None:
    """Safely delete signature temporary image if located in system temp directory."""
    if not signature_path or not os.path.isfile(signature_path):
        return
    try:
        old_dir = os.path.normcase(os.path.dirname(signature_path))
        tmp_dir = os.path.normcase(tempfile.gettempdir())
        if old_dir.startswith(tmp_dir):
            os.unlink(signature_path)
    except OSError:
        pass


def load_form_fields(tab, path: str) -> None:
    """Populate the AcroForm fields table from the opened PDF document."""
    tab._form_table.setRowCount(0)
    tab._form_status.setText("")
    try:
        from pypdf import PdfReader
        tab._form_table.setUpdatesEnabled(False)
        _r = PdfReader(path)
        if _r.is_encrypted and tab._pdf_password:
            if decrypt_pypdf(_r, tab._pdf_password) is None:
                raise WrongPasswordError(t("tool.err.wrong_password"))
        fields = _r.get_fields() or {}
        for name, field in fields.items():
            r = tab._form_table.rowCount()
            tab._form_table.insertRow(r)
            tab._form_table.setItem(r, 0, QTableWidgetItem(name))
            tab._form_table.setItem(r, 1, QTableWidgetItem(str(field.get("/V", "") or "")))
        tab._form_table.setUpdatesEnabled(True)
        if not fields:
            tab._form_status.setText(t("editor.forms.no_fields"))
    except Exception as exc:
        tab._form_table.setUpdatesEnabled(True)
        _log.warning("Failed to load form fields from %s: %s", path, exc)
        tab._form_status.setText(t("editor.forms.load_failed"))


def invalidate_viewer_pipeline(tab, out_path: str) -> None:
    """Close reader handles in main viewer if the target output file is currently opened."""
    win = tab.window()
    viewer = getattr(win, "_viewer", None)
    if viewer and viewer.current_path() and os.path.abspath(viewer.current_path()) == os.path.abspath(out_path):
        viewer._canvas.close_doc()
        if viewer._fitz_doc:
            with contextlib.suppress(Exception):
                viewer._fitz_doc.close()
            viewer._fitz_doc = None
        viewer._thumbnails._stop_all_workers()
        if win and hasattr(win, "_cleanup_pipeline"):
            win._cleanup_pipeline(id(viewer))


def apply_form_fields_and_save(tab, out: str) -> None:
    """Apply updated AcroForm field values to the output file using pypdf."""
    try:
        from pypdf import PdfWriter, PdfReader
        with open(tab._doc_path, "rb") as _src:
            _r = PdfReader(_src)
            was_encrypted = bool(_r.is_encrypted)
            if was_encrypted and tab._pdf_password:
                if decrypt_pypdf(_r, tab._pdf_password) is None:
                    raise WrongPasswordError(t("tool.err.wrong_password"))
            encrypt_choice = "plaintext"
            if was_encrypted and tab._pdf_password:
                encrypt_choice = prompt_encryption_choice(tab)
                if encrypt_choice is None:
                    return
            writer = PdfWriter()
            writer.append(_r)
            fields = {
                tab._form_table.item(r, 0).text():
                (tab._form_table.item(r, 1).text() if tab._form_table.item(r, 1) else "")
                for r in range(tab._form_table.rowCount())
            }
            if "/AcroForm" not in writer._root_object:
                tab._status(t("editor.forms.no_fields"))
                tab._form_status.setText(t("editor.forms.no_fields"))
                return
            try:
                _w_fields = _r.get_fields() or {}
            except Exception:
                _w_fields = {}
            if not _w_fields:
                tab._status(t("editor.forms.no_fields"))
                tab._form_status.setText(t("editor.forms.no_fields"))
                return
            for page in writer.pages:
                writer.update_page_form_field_values(page, fields, auto_regenerate=True)
            if encrypt_choice == "protect" and tab._pdf_password:
                writer.encrypt(
                    user_password=tab._pdf_password,
                    owner_password=tab._pdf_password,
                    algorithm="AES-256",
                )
                _log.info("Re-encrypted forms output with user password as owner")

            invalidate_viewer_pipeline(tab, out)
            atomic_pdf_write(writer, out, sources=[tab._doc_path])

        tab._status(t("edit.status.form_saved", path=out))
        QMessageBox.information(tab, t("msg.done"), t("msg.form_saved", path=out))
    except Exception as e:
        show_error(tab, e)


def apply_visual_edits_and_save(tab, out: str) -> None:
    """Apply pending visual and text edits to PDF document and write to disk."""
    try:
        peek = fitz.open(tab._doc_path)
        was_encrypted = bool(peek.needs_pass)
        if was_encrypted and tab._pdf_password:
            peek.authenticate(tab._pdf_password)
        encrypt_choice = "plaintext"
        if was_encrypted and tab._pdf_password:
            encrypt_choice = prompt_encryption_choice(tab)
            if encrypt_choice is None:
                peek.close()
                return
        peek.close()

        tab._canvas.release_doc()
        doc = fitz.open(tab._doc_path)
        if doc.needs_pass and tab._pdf_password:
            doc.authenticate(tab._pdf_password)

        _non_latin = any(
            e.get("type") in ("text", "note", "text_edit")
            and any(ord(c) > 0xFF for c in (e.get("text") or e.get("new_text") or ""))
            for e in tab._pending
        )
        if _non_latin:
            tab._status(t("tool.warn.font_latin_only"))

        _apply_result = apply_pending_edits(doc, tab._pending)
        text_fit_warnings = _apply_result.text_fit_warnings
        reencrypt = bool(encrypt_choice == "protect" and tab._pdf_password)
        if reencrypt:
            perms = get_fitz_permissions(doc)
            save_opts = dict(
                garbage=4, deflate=True,
                encryption=fitz.PDF_ENCRYPT_AES_256,
                user_pw=tab._pdf_password,
                owner_pw=tab._pdf_password,
                permissions=perms,
            )
        else:
            save_opts = dict(garbage=4, deflate=True)

        invalidate_viewer_pipeline(tab, out)
        atomic_pdf_write(doc, out, save_opts=save_opts, close_writer=True)
        if reencrypt:
            _log.info("Re-encrypted output with user password as owner")

        tab._pending.clear()
        tab._pending_list.clear()
        tab._status(t("edit.status.saved", path=out))

        if text_fit_warnings:
            QMessageBox.warning(tab, t("msg.warning"), t("msg.pdf_saved", path=out))
        else:
            QMessageBox.information(tab, t("msg.done"), t("msg.pdf_saved", path=out))
        tab._load_pdf(out)
    except Exception as e:
        show_error(tab, e)