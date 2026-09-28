# app/viewer/panel_page_ops.py
"""PDFApps – Multi-page operations, drag/drop reordering, and thumbnail action handlers."""
import os
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
import fitz

from app.constants import DESKTOP
from app.i18n import t
from app.pdf_io import atomic_pdf_write
from app.utils import parse_pages, show_error


class _PageTransitionsDialog(QDialog):
    """Dialog to configure presentation page transitions and auto-advance timing."""

    def __init__(self, parent, pages: list[int], total_pages: int, current_info: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle(t("viewer.transitions", default="Page Transitions"))
        self.setMinimumWidth(400)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        # ── Group 1: Transition Effect ──
        grp_effect = QGroupBox("Transition Effect")
        form_effect = QFormLayout(grp_effect)
        form_effect.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_effect.setSpacing(8)

        self.cmb_effect = QComboBox()
        self.effects = [
            ("None (Remove transition)", "None"),
            ("Split", "Split"),
            ("Blinds", "Blinds"),
            ("Box", "Box"),
            ("Wipe", "Wipe"),
            ("Dissolve", "Dissolve"),
            ("Glitter", "Glitter"),
            ("Push", "Push"),
            ("Cover", "Cover"),
            ("Uncover", "Uncover"),
            ("Fade", "Fade"),
        ]
        for label, val in self.effects:
            self.cmb_effect.addItem(label, val)
        form_effect.addRow("Style:", self.cmb_effect)

        self.spin_duration = QDoubleSpinBox()
        self.spin_duration.setRange(0.1, 10.0)
        self.spin_duration.setSingleStep(0.5)
        self.spin_duration.setValue(1.0)
        self.spin_duration.setSuffix(" s")
        form_effect.addRow("Duration:", self.spin_duration)

        self.cmb_direction = QComboBox()
        self.directions = [
            ("Left to Right (0°)", 0),
            ("Bottom to Top (90°)", 90),
            ("Right to Left (180°)", 180),
            ("Top to Bottom (270°)", 270),
        ]
        for label, val in self.directions:
            self.cmb_direction.addItem(label, val)
        form_effect.addRow("Direction:", self.cmb_direction)

        self.cmb_dimension = QComboBox()
        self.cmb_dimension.addItem("Horizontal", "H")
        self.cmb_dimension.addItem("Vertical", "V")
        form_effect.addRow("Dimension:", self.cmb_dimension)

        self.cmb_motion = QComboBox()
        self.cmb_motion.addItem("Inward", "I")
        self.cmb_motion.addItem("Outward", "O")
        form_effect.addRow("Motion:", self.cmb_motion)

        layout.addWidget(grp_effect)

        # ── Group 2: Auto-Advance / Timing ──
        grp_timing = QGroupBox("Auto-Advance & Duration")
        form_timing = QFormLayout(grp_timing)
        form_timing.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_timing.setSpacing(8)

        self.chk_auto_advance = QCheckBox("Auto-advance to next page after:")
        self.spin_advance_seconds = QSpinBox()
        self.spin_advance_seconds.setRange(1, 3600)
        self.spin_advance_seconds.setValue(5)
        self.spin_advance_seconds.setSuffix(" s")
        self.spin_advance_seconds.setEnabled(False)
        self.chk_auto_advance.toggled.connect(self.spin_advance_seconds.setEnabled)

        form_timing.addRow(self.chk_auto_advance, self.spin_advance_seconds)
        layout.addWidget(grp_timing)

        # ── Group 3: Page Range ──
        grp_range = QGroupBox("Page Range")
        v_range = QVBoxLayout(grp_range)
        v_range.setSpacing(6)

        self.cmb_range = QComboBox()
        sel_str = ", ".join(str(p + 1) for p in pages) if pages else "1"
        if len(pages) > 5:
            sel_str = f"{len(pages)} pages"
        self.cmb_range.addItem(f"Selected page(s) ({sel_str})", "selected")
        self.cmb_range.addItem(f"All pages in document (1-{total_pages})", "all")
        self.cmb_range.addItem("Custom range:", "custom")

        range_row = QHBoxLayout()
        self.edit_custom = QLineEdit()
        self.edit_custom.setPlaceholderText("e.g. 1-3, 5")
        self.edit_custom.setEnabled(False)
        if pages:
            self.edit_custom.setText(",".join(str(p + 1) for p in pages))
        range_row.addWidget(self.cmb_range)
        range_row.addWidget(self.edit_custom)
        v_range.addLayout(range_row)

        self.cmb_range.currentIndexChanged.connect(
            lambda idx: self.edit_custom.setEnabled(self.cmb_range.currentData() == "custom")
        )
        layout.addWidget(grp_range)

        # ── Buttons ──
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)
        btn_box.addStretch()

        self.btn_cancel = QPushButton(t("btn.cancel"))
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        self.btn_ok = QPushButton(t("btn.ok"))
        self.btn_ok.setObjectName("btn_primary")
        self.btn_ok.clicked.connect(self.accept)
        btn_box.addWidget(self.btn_ok)

        layout.addLayout(btn_box)

        self.cmb_effect.currentIndexChanged.connect(self._update_effect_fields)
        self._update_effect_fields()

        if current_info:
            eff = current_info.get("effect", "None")
            for idx in range(self.cmb_effect.count()):
                if self.cmb_effect.itemData(idx) == eff:
                    self.cmb_effect.setCurrentIndex(idx)
                    break
            self.spin_duration.setValue(current_info.get("duration", 1.0))
            di = current_info.get("direction", 0)
            for idx in range(self.cmb_direction.count()):
                if self.cmb_direction.itemData(idx) == di:
                    self.cmb_direction.setCurrentIndex(idx)
                    break
            dm = current_info.get("dimension", "H")
            for idx in range(self.cmb_dimension.count()):
                if self.cmb_dimension.itemData(idx) == dm:
                    self.cmb_dimension.setCurrentIndex(idx)
                    break
            m = current_info.get("motion", "I")
            for idx in range(self.cmb_motion.count()):
                if self.cmb_motion.itemData(idx) == m:
                    self.cmb_motion.setCurrentIndex(idx)
                    break
            adv = current_info.get("auto_advance")
            if adv is not None and adv > 0:
                self.chk_auto_advance.setChecked(True)
                self.spin_advance_seconds.setValue(int(round(adv)))

    def _update_effect_fields(self):
        eff = self.cmb_effect.currentData()
        is_none = (eff == "None")
        self.spin_duration.setEnabled(not is_none)
        self.cmb_direction.setEnabled(eff in ("Wipe", "Glitter", "Push", "Cover", "Uncover"))
        self.cmb_dimension.setEnabled(eff in ("Split", "Blinds"))
        self.cmb_motion.setEnabled(eff in ("Split", "Box"))

    def get_settings(self) -> dict:
        return {
            "effect": self.cmb_effect.currentData(),
            "duration": self.spin_duration.value(),
            "direction": self.cmb_direction.currentData(),
            "dimension": self.cmb_dimension.currentData(),
            "motion": self.cmb_motion.currentData(),
            "auto_advance": self.spin_advance_seconds.value() if self.chk_auto_advance.isChecked() else None,
            "range_type": self.cmb_range.currentData(),
            "custom_range": self.edit_custom.text().strip(),
        }


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

        if action == "reorder":
            if isinstance(pages_arg, (tuple, list)) and len(pages_arg) == 2:
                pages_to_move, target_index = pages_arg
                if isinstance(pages_to_move, (list, tuple, set)):
                    self._move_pages_to(sorted(list(pages_to_move)), int(target_index))
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
        elif action == "transitions":
            self._page_transitions_dialog(pages)
        elif action == "embed_thumbnails":
            self._embed_all_thumbnails()
        elif action == "remove_thumbnails":
            self._remove_all_thumbnails()
        elif action == "print":
            self._print_pdf(pages)
        elif action == "properties":
            self._show_properties_dialog()
        elif action == "copy":
            self._copy_page_content(pages)
        elif action == "paste":
            self._paste_page_content(pages[0])

    @staticmethod
    def _get_page_transition_info(doc, page_idx: int) -> dict:
        info = {
            "effect": "None",
            "duration": 1.0,
            "direction": 0,
            "dimension": "H",
            "motion": "I",
            "auto_advance": None,
        }
        if 0 <= page_idx < doc.page_count:
            page = doc[page_idx]
            try:
                dur_val = doc.xref_get_key(page.xref, "Dur")
                if dur_val and dur_val[0] != "null":
                    info["auto_advance"] = float(dur_val[1].strip())
            except Exception:
                pass
            try:
                trans_val = doc.xref_get_key(page.xref, "Trans")
                if trans_val and trans_val[0] != "null":
                    raw = trans_val[1]
                    m_s = re.search(r"/S\s+/([A-Za-z]+)", raw)
                    if m_s:
                        info["effect"] = m_s.group(1)
                    m_d = re.search(r"/D\s+([\d\.]+)", raw)
                    if m_d:
                        info["duration"] = float(m_d.group(1))
                    m_di = re.search(r"/Di\s+(\d+)", raw)
                    if m_di:
                        info["direction"] = int(m_di.group(1))
                    m_dm = re.search(r"/Dm\s+/([A-Za-z]+)", raw)
                    if m_dm:
                        info["dimension"] = m_dm.group(1).upper()
                    m_m = re.search(r"/M\s+/([A-Za-z]+)", raw)
                    if m_m:
                        info["motion"] = m_m.group(1).upper()
            except Exception:
                pass
        return info

    def _page_transitions_dialog(self, pages: list[int]) -> None:
        if not self._fitz_doc or not self._current_path:
            return
        total = self._fitz_doc.page_count
        if total <= 0:
            return

        ref_page = pages[0] if pages else 0
        current_info = self._get_page_transition_info(self._fitz_doc, ref_page)

        dlg = _PageTransitionsDialog(self, pages, total, current_info)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        settings = dlg.get_settings()
        range_type = settings["range_type"]
        if range_type == "selected":
            target_pages = [p for p in pages if 0 <= p < total]
        elif range_type == "all":
            target_pages = list(range(total))
        else:
            try:
                target_pages = parse_pages(settings["custom_range"], total)
            except ValueError as ex:
                QMessageBox.warning(self, t("msg.warning"), str(ex))
                return

        if not target_pages:
            QMessageBox.warning(self, t("msg.warning"), "No pages selected for transition.")
            return

        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)

            effect = settings["effect"]
            duration = settings["duration"]
            direction = settings["direction"]
            dimension = settings["dimension"]
            motion = settings["motion"]
            auto_advance = settings["auto_advance"]

            for p_idx in target_pages:
                if 0 <= p_idx < doc.page_count:
                    page = doc[p_idx]
                    if effect == "None":
                        doc.xref_set_key(page.xref, "Trans", "null")
                    else:
                        parts = ["/Type /Trans", f"/S /{effect}", f"/D {duration:g}"]
                        if effect in ("Split", "Blinds"):
                            parts.append(f"/Dm /{dimension}")
                        if effect in ("Split", "Box"):
                            parts.append(f"/M /{motion}")
                        if effect in ("Wipe", "Glitter", "Push", "Cover", "Uncover"):
                            parts.append(f"/Di {direction}")
                        trans_dict = "<< " + " ".join(parts) + " >>"
                        doc.xref_set_key(page.xref, "Trans", trans_dict)

                    if auto_advance is not None and auto_advance > 0:
                        doc.xref_set_key(page.xref, "Dur", f"{auto_advance:g}")
                    else:
                        doc.xref_set_key(page.xref, "Dur", "null")

            self._save_and_reload(doc, target_page=target_pages[0], selected_pages=target_pages)
            win = self.window()
            if hasattr(win, "_set_status"):
                desc = "removed" if effect == "None" else f"'{effect}'"
                win._set_status(f"✔ Page transition {desc} applied to {len(target_pages)} page(s)")
        except Exception as exc:
            show_error(self, exc)

    def _remove_all_thumbnails(self) -> None:
        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)
            doc.scrub(thumbnails=True)
            for page in doc:
                doc.xref_set_key(page.xref, "Thumb", "null")
            self._save_and_reload(doc)
            win = self.window()
            if hasattr(win, "_set_status"):
                win._set_status("✔ Removed embedded page thumbnails")
            QMessageBox.information(self, t("msg.done"), "Removed all embedded page thumbnails.")
        except Exception as exc:
            show_error(self, exc)

    def _embed_all_thumbnails(self) -> None:
        QMessageBox.information(
            self,
            t("msg.info"),
            "PDFApps renders page thumbnails dynamically on the fly without increasing the PDF file size. Embedded thumbnail streams are an obsolete legacy feature not needed for modern viewers.",
        )

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

    def _move_pages_to(self, pages: list[int], target_index: int) -> None:
        """Move one or more pages to target_index using standard reordering logic."""
        if not self._fitz_doc or not self._current_path:
            return
        total = self._fitz_doc.page_count
        if total <= 1 or not pages:
            return

        pages = [p for p in pages if 0 <= p < total]
        if not pages or len(pages) == total:
            return

        order = [i for i in range(total) if i not in pages]
        dest_pos = sum(1 for i in order if i < target_index)
        dest_pos = max(0, min(dest_pos, len(order)))

        for i, p in enumerate(pages):
            order.insert(dest_pos + i, p)

        if order == list(range(total)):
            return

        try:
            doc = fitz.open(self._current_path)
            if self._pdf_password and doc.needs_pass:
                doc.authenticate(self._pdf_password)

            new_doc = fitz.open()
            for idx in order:
                new_doc.insert_pdf(doc, from_page=idx, to_page=idx)
            doc.close()

            new_selected = list(range(dest_pos, dest_pos + len(pages)))
            target_view_page = dest_pos
            self._save_and_reload(new_doc, target_page=target_view_page, selected_pages=new_selected, scroll_to_target=True)

            win = self.window()
            if hasattr(win, "_set_status"):
                win._set_status(f"✔ Moved {len(pages)} page(s)")
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
        dest_idx = dest - 1
        order = [i for i in range(total) if i not in pages]
        dest_clamped = max(0, min(dest_idx, len(order)))
        target_index = order[dest_clamped] if dest_clamped < len(order) else total
        self._move_pages_to(pages, target_index)

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