# app/viewer/panel_page_ops.py
"""PDFApps – Multi-page operations and thumbnail action handlers."""
import os

from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QApplication
import fitz

from app.constants import DESKTOP
from app.i18n import t
from app.utils import show_error
from app.pdf_io import atomic_pdf_write


class PanelPageOpsMixin:
    """Mixin for page modification, reordering, extraction, and insertion."""

    def _on_thumbnail_action(self, action: str, pages_arg: object) -> None:
        if not self._fitz_doc or not self._current_path:
            return

        if action == "undo":
            self.undo()
            return
        if action == "redo":
            self.redo()
            return

        if isinstance(pages_arg, int):
            pages = [pages_arg]
        elif isinstance(pages_arg, (list, tuple, set)):
            pages = sorted(list(pages_arg))
        else:
            pages = [0]

        if not pages:
            return

        if action in ("rotate_right", "rotate_left", "rotate_180"):
            delta = 90 if action == "rotate_right" else (270 if action == "rotate_left" else 180)
            self._rotate_pages(pages, delta)
        elif action == "delete":
            self._delete_pages(pages)
        elif action == "extract":
            self._extract_pages(pages)
        elif action == "insert_blank":
            self._insert_blank_page(pages[-1])
        elif action == "insert_file":
            self._insert_pages_from_file(pages[-1])
        elif action == "duplicate":
            self._duplicate_pages(pages)
        elif action == "reverse":
            self._reverse_pages(pages)
        elif action == "swap":
            self._swap_page_dialog(pages[0])
        elif action == "move":
            self._move_page_dialog(pages)
        elif action == "replace":
            self._replace_page_dialog(pages[0])
        elif action == "resize":
            self._resize_pages_dialog(pages)
        elif action == "crop":
            self._trigger_crop_tool(pages)
        elif action == "page_numbers":
            self._trigger_page_numbers_tool(pages)
        elif action == "split":
            self._trigger_split_tool()
        elif action == "print":
            self._print_pdf(pages)
        elif action == "properties":
            self._show_properties_dialog()
        elif action == "copy":
            self._copy_page_content(pages)
        elif action == "paste":
            self._paste_page_content(pages[0])

    def _rotate_pages(self, pages: list[int], delta: int) -> None:
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            for p_idx in pages:
                if 0 <= p_idx < doc.page_count:
                    page = doc[p_idx]
                    cur_rot = page.rotation
                    new_rot = (cur_rot + delta) % 360
                    page.set_rotation(new_rot)
            first_page = min(pages) if pages else None
            self._save_and_reload(doc, target_page=first_page, selected_pages=pages)
        except Exception as exc:
            show_error(self, exc)

    def _delete_pages(self, pages: list[int]) -> None:
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            if doc.page_count <= len(pages):
                QMessageBox.warning(self, t("msg.warning"), "Cannot delete all pages in the document.")
                doc.close()
                return

            page_str = ", ".join(str(p + 1) for p in pages)
            if len(pages) > 6:
                page_str = f"{len(pages)} pages ({pages[0] + 1}..{pages[-1] + 1})"

            reply = QMessageBox.question(
                self, t("msg.confirm"),
                f"Are you sure you want to delete page(s) {page_str}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                doc.close()
                return

            for p_idx in sorted(pages, reverse=True):
                if 0 <= p_idx < doc.page_count:
                    doc.delete_page(p_idx)

            target = min(pages[0], doc.page_count - 1)
            self._save_and_reload(doc, target_page=target, selected_pages=[target])
        except Exception as exc:
            show_error(self, exc)

    def _extract_pages(self, pages: list[int]) -> None:
        base, ext = os.path.splitext(os.path.basename(self._current_path))
        if len(pages) == 1:
            default_name = f"{base}_page_{pages[0] + 1}{ext}"
        else:
            default_name = f"{base}_extracted_pages{ext}"
        out_path, _ = QFileDialog.getSaveFileName(
            self, t("tool.extract.name"),
            os.path.join(os.path.dirname(self._current_path), default_name),
            t("file_filter.pdf"),
        )
        if not out_path:
            return
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            new_doc = fitz.open()
            for p_idx in pages:
                if 0 <= p_idx < doc.page_count:
                    new_doc.insert_pdf(doc, from_page=p_idx, to_page=p_idx)
            doc.close()
            atomic_pdf_write(new_doc, out_path, close_writer=True)
            QMessageBox.information(self, t("msg.done"), f"{len(pages)} page(s) extracted to:\n{out_path}")
        except Exception as exc:
            show_error(self, exc)

    def _insert_blank_page(self, page_idx: int) -> None:
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            ref_rect = doc[page_idx].rect if 0 <= page_idx < doc.page_count else fitz.Rect(0, 0, 595, 842)
            doc.new_page(pno=page_idx + 1, width=ref_rect.width, height=ref_rect.height)
            self._save_and_reload(doc, target_page=page_idx + 1, selected_pages=[page_idx + 1])
        except Exception as exc:
            show_error(self, exc)

    def _insert_pages_from_file(self, page_idx: int) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Insert Pages from PDF", DESKTOP, t("file_filter.pdf"))
        if not p or not os.path.isfile(p):
            return
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            src = fitz.open(p)
            doc.insert_pdf(src, start_at=page_idx + 1)
            src.close()
            self._save_and_reload(doc, target_page=page_idx + 1, selected_pages=[page_idx + 1])
        except Exception as exc:
            show_error(self, exc)

    def _duplicate_pages(self, pages: list[int]) -> None:
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            for p_idx in sorted(pages, reverse=True):
                if 0 <= p_idx < doc.page_count:
                    doc.insert_pdf(doc, from_page=p_idx, to_page=p_idx, start_at=p_idx + 1)
            self._save_and_reload(doc, target_page=pages[0], selected_pages=pages)
        except Exception as exc:
            show_error(self, exc)

    def _reverse_pages(self, pages: list[int]) -> None:
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            n = doc.page_count
            if n <= 1:
                doc.close()
                return
            order = list(range(n))
            if len(pages) > 1:
                sub_order = list(reversed(pages))
                for orig_idx, rev_idx in zip(pages, sub_order):
                    order[orig_idx] = rev_idx
            else:
                order = list(reversed(order))
            new_doc = fitz.open()
            for idx in order:
                new_doc.insert_pdf(doc, from_page=idx, to_page=idx)
            doc.close()
            self._save_and_reload(new_doc, target_page=pages[0] if pages else 0, selected_pages=pages)
        except Exception as exc:
            show_error(self, exc)

    def _swap_page_dialog(self, page_idx: int) -> None:
        total = self._fitz_doc.page_count if self._fitz_doc else 1
        target, ok = QInputDialog.getInt(
            self, "Swap Pages",
            f"Swap page {page_idx + 1} with page (1-{total}):",
            min(total, max(1, page_idx + 2)), 1, total, 1
        )
        if not ok or target == page_idx + 1:
            return
        try:
            target_idx = target - 1
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            order = list(range(doc.page_count))
            order[page_idx], order[target_idx] = order[target_idx], order[page_idx]
            new_doc = fitz.open()
            for idx in order:
                new_doc.insert_pdf(doc, from_page=idx, to_page=idx)
            doc.close()
            self._save_and_reload(new_doc, target_page=target_idx, selected_pages=[target_idx])
        except Exception as exc:
            show_error(self, exc)

    def _move_page_dialog(self, pages: list[int]) -> None:
        total = self._fitz_doc.page_count if self._fitz_doc else 1
        page_str = ", ".join(str(p + 1) for p in pages)
        dest, ok = QInputDialog.getInt(
            self, "Move Pages",
            f"Move page(s) {page_str} to position (1-{total}):",
            min(total, max(1, max(pages) + 2)), 1, total, 1
        )
        if not ok:
            return
        try:
            dest_idx = dest - 1
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            order = [i for i in range(doc.page_count) if i not in pages]
            dest_clamped = max(0, min(dest_idx, len(order)))
            for i, p in enumerate(pages):
                order.insert(dest_clamped + i, p)
            new_doc = fitz.open()
            for idx in order:
                new_doc.insert_pdf(doc, from_page=idx, to_page=idx)
            doc.close()
            new_selected = list(range(dest_clamped, dest_clamped + len(pages)))
            self._save_and_reload(new_doc, target_page=dest_clamped, selected_pages=new_selected)
        except Exception as exc:
            show_error(self, exc)

    def _replace_page_dialog(self, page_idx: int) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "Replace with PDF", DESKTOP, t("file_filter.pdf"))
        if not p or not os.path.isfile(p):
            return
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            src = fitz.open(p)
            doc.insert_pdf(src, from_page=0, to_page=0, start_at=page_idx)
            doc.delete_page(page_idx + 1)
            src.close()
            self._save_and_reload(doc, target_page=page_idx, selected_pages=[page_idx])
        except Exception as exc:
            show_error(self, exc)

    def _resize_pages_dialog(self, pages: list[int]) -> None:
        sizes = {
            "A4 (595 × 842 pt)": (595.0, 842.0),
            "Letter (612 × 792 pt)": (612.0, 792.0),
            "A3 (842 × 1191 pt)": (842.0, 1191.0),
            "A5 (420 × 595 pt)": (420.0, 595.0),
        }
        item, ok = QInputDialog.getItem(
            self, "Resize Pages", f"Select page size for {len(pages)} page(s):", list(sizes.keys()), 0, False
        )
        if not ok or item not in sizes:
            return
        try:
            new_w, new_h = sizes[item]
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            for p_idx in pages:
                if 0 <= p_idx < doc.page_count:
                    doc[p_idx].set_mediabox(fitz.Rect(0, 0, new_w, new_h))
            self._save_and_reload(doc, target_page=pages[0] if pages else 0, selected_pages=pages)
        except Exception as exc:
            show_error(self, exc)

    def _copy_page_content(self, pages: list[int]) -> None:
        if not self._fitz_doc:
            return
        texts = []
        for p_idx in pages:
            if 0 <= p_idx < self._fitz_doc.page_count:
                t_str = self._fitz_doc[p_idx].get_text("text").strip()
                if t_str:
                    texts.append(t_str)
        if texts:
            combined = "\n\n--- Page Break ---\n\n".join(texts)
            QApplication.clipboard().setText(combined)
            win = self.window()
            if hasattr(win, "_set_status"):
                win._set_status(f"✔ Copied text from {len(texts)} page(s) to clipboard")

    def _paste_page_content(self, page_idx: int) -> None:
        text = QApplication.clipboard().text().strip()
        if not text:
            return
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            page = doc[page_idx]
            page.insert_textbox(page.rect.adjusted(36, 36, -36, -36), text, fontsize=11, fontname="helv")
            self._save_and_reload(doc, target_page=page_idx, selected_pages=[page_idx])
        except Exception as exc:
            show_error(self, exc)

    def _show_properties_dialog(self) -> None:
        if not self._current_path or not os.path.isfile(self._current_path):
            return
        win = self.window()
        if hasattr(win, "_open_tool_by_name"):
            win._open_tool_by_name(t("nav.info"))

    def _trigger_crop_tool(self, pages: list[int] | None = None) -> None:
        win = self.window()
        if hasattr(win, "_open_tool_by_name"):
            win._open_tool_by_name(t("nav.crop"))
            if pages and hasattr(win, "stack") and hasattr(win, "_crop_tool_idx"):
                crop_idx = win._crop_tool_idx()
                if crop_idx >= 0:
                    crop_w = win.stack.widget(crop_idx)
                    if hasattr(crop_w, "cmb_page_mode") and hasattr(crop_w, "edit_custom_pages"):
                        crop_w.cmb_page_mode.setCurrentIndex(2)
                        crop_w.edit_custom_pages.setText(",".join(str(p + 1) for p in pages))

    def _trigger_page_numbers_tool(self, pages: list[int] | None = None) -> None:
        win = self.window()
        if hasattr(win, "_open_tool_by_name"):
            win._open_tool_by_name(t("nav.page_numbers"))
            if pages and hasattr(win, "stack"):
                for i in range(win.stack.count()):
                    w = win.stack.widget(i)
                    if hasattr(w, "edit_pages") and hasattr(w, "spin_start_page"):
                        w.edit_pages.setText(",".join(str(p + 1) for p in pages))
                        break

    def _trigger_split_tool(self) -> None:
        win = self.window()
        if hasattr(win, "_open_tool_by_name"):
            win._open_tool_by_name(t("nav.split"))