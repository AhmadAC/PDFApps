

# app/viewer/canvas_interaction.py

"""PDFApps – Interaction handler for _SelectCanvas (Mouse, Keyboard, Context Menus, Signatures)."""
from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from typing import TYPE_CHECKING

import fitz
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox
import qtawesome as qta

from app.constants import ACCENT, TEXT_SEC
from app.i18n import t
from app.viewer.canvas_worker import _NOTE_ICON_SIZE

if TYPE_CHECKING:
    from app.viewer.canvas_1 import _SelectCanvas


class CanvasInteractionHandler:
    """Handles text selection, note balloon interaction, shortcuts, signatures, and context actions."""

    def __init__(self, canvas: _SelectCanvas):
        self.canvas = canvas

    def clear_selection(self):
        c = self.canvas
        c._drag_start = None
        c._drag_end   = None
        c._sel_rects  = []
        c._sel_text   = ""

    def page_word_to_screen(self, y_off: int, x0: float, y0: float, x1: float, y1: float) -> QRect:
        z = self.canvas._zoom
        return QRect(int(x0 * z), y_off + int(y0 * z),
                     max(1, int((x1 - x0) * z)),
                     max(1, int((y1 - y0) * z)))

    def find_closest_word(self, pos: QPoint) -> tuple[int, int]:
        z = self.canvas._zoom
        best_page, best_idx, best_dist = -1, -1, float("inf")
        for pi, e in enumerate(self.canvas._entries):
            if not e.words:
                continue
            if pos.y() < e.y_off - 50 or pos.y() > e.y_off + e.h + 50:
                continue
            px = pos.x() / z
            py = (pos.y() - e.y_off) / z
            for wi, w in enumerate(e.words):
                cx = (w[0] + w[2]) / 2
                cy = (w[1] + w[3]) / 2
                d = (px - cx) ** 2 + (py - cy) ** 2
                if d < best_dist:
                    best_dist = d
                    best_page = pi
                    best_idx = wi
        return best_page, best_idx

    def compute_selection(self):
        c = self.canvas
        if not c._drag_start or not c._drag_end:
            return
        p1_page, p1_word = self.find_closest_word(c._drag_start)
        p2_page, p2_word = self.find_closest_word(c._drag_end)
        if p1_page < 0 or p2_page < 0:
            return
        if (p1_page, p1_word) > (p2_page, p2_word):
            p1_page, p1_word, p2_page, p2_word = p2_page, p2_word, p1_page, p1_word
        rects, words = [], []
        for pi in range(p1_page, p2_page + 1):
            e = c._entries[pi]
            if not e.words:
                continue
            w_start = p1_word if pi == p1_page else 0
            w_end   = p2_word if pi == p2_page else len(e.words) - 1
            for wi in range(w_start, w_end + 1):
                w = e.words[wi]
                x0, y0, x1, y1 = w[0], w[1], w[2], w[3]
                if wi < w_end:
                    nw = e.words[wi + 1]
                    line_h = y1 - y0
                    overlap = min(y1, nw[3]) - max(y0, nw[1])
                    if overlap > line_h * 0.5:
                        x1 = nw[0]
                rects.append(self.page_word_to_screen(e.y_off, x0, y0, x1, y1))
                words.append(w[4])
        c._sel_rects = rects
        c._sel_text  = " ".join(words)

    def note_icon_at(self, pos: QPoint) -> tuple[int, int] | None:
        z = self.canvas._zoom
        margin = 8
        for page_idx, entry in enumerate(self.canvas._entries):
            if not entry.annots:
                continue
            if pos.y() < entry.y_off - margin or pos.y() > entry.y_off + entry.h + margin:
                continue
            for annot_idx, (rect, _txt) in enumerate(entry.annots):
                px = int(rect.x0 * z)
                py = entry.y_off + int(rect.y0 * z)
                hit_r = QRect(px - margin, py - margin,
                              _NOTE_ICON_SIZE + margin * 2, _NOTE_ICON_SIZE + margin * 2)
                if hit_r.contains(pos):
                    return (page_idx, annot_idx)
        return None

    def get_sig_handle_at(self, pos: QPoint) -> int:
        c = self.canvas
        if not c._active_sig:
            return c.HANDLE_NONE
        page_idx = c._active_sig["page"]
        if not (0 <= page_idx < len(c._entries)):
            return c.HANDLE_NONE
        entry = c._entries[page_idx]
        x_off = (max(c.width(), entry.w) - entry.w) // 2 if c.width() > entry.w else 0
        z = c._zoom
        r = c._active_sig["rect"]
        sx0 = x_off + int(r.x0 * z)
        sy0 = entry.y_off + int(r.y0 * z)
        sx1 = x_off + int(r.x1 * z)
        sy1 = entry.y_off + int(r.y1 * z)
        hs = 10
        if QRect(sx0 - hs, sy0 - hs, hs * 2, hs * 2).contains(pos):
            return c.HANDLE_TL
        if QRect(sx1 - hs, sy0 - hs, hs * 2, hs * 2).contains(pos):
            return c.HANDLE_TR
        if QRect(sx0 - hs, sy1 - hs, hs * 2, hs * 2).contains(pos):
            return c.HANDLE_BL
        if QRect(sx1 - hs, sy1 - hs, hs * 2, hs * 2).contains(pos):
            return c.HANDLE_BR
        return c.HANDLE_NONE

    def is_pos_inside_active_sig(self, pos: QPoint) -> bool:
        c = self.canvas
        if not c._active_sig:
            return False
        page_idx = c._active_sig["page"]
        if not (0 <= page_idx < len(c._entries)):
            return False
        entry = c._entries[page_idx]
        x_off = (max(c.width(), entry.w) - entry.w) // 2 if c.width() > entry.w else 0
        z = c._zoom
        r = c._active_sig["rect"]
        sx0 = x_off + int(r.x0 * z)
        sy0 = entry.y_off + int(r.y0 * z)
        sx1 = x_off + int(r.x1 * z)
        sy1 = entry.y_off + int(r.y1 * z)
        return QRect(sx0, sy0, max(1, sx1 - sx0), max(1, sy1 - sy0)).contains(pos)

    def mouse_press(self, e):
        c = self.canvas
        pos = e.position().toPoint()

        # ── 1. Placing Signature from cursor ──────────────────────────
        if c._placing_signature:
            if e.button() == Qt.MouseButton.RightButton:
                c.cancel_signature_placement()
                e.accept()
                return
            if e.button() == Qt.MouseButton.LeftButton:
                page_idx = c.page_at_y(pos.y())
                if 0 <= page_idx < len(c._entries):
                    entry = c._entries[page_idx]
                    x_off = (max(c.width(), entry.w) - entry.w) // 2 if c.width() > entry.w else 0
                    z = c._zoom
                    px = (pos.x() - x_off) / z
                    py = (pos.y() - entry.y_off) / z
                    pix = c._placing_sig_pixmap
                    aspect = (pix.height() / pix.width()) if pix and pix.width() > 0 else 0.35
                    sig_w = min(180.0, (entry.w / z) * 0.6)
                    sig_h = sig_w * aspect
                    x0 = max(0.0, min(entry.w / z - sig_w, px - sig_w / 2.0))
                    y0 = max(0.0, min(entry.h / z - sig_h, py - sig_h / 2.0))
                    rect = fitz.Rect(x0, y0, x0 + sig_w, y0 + sig_h)
                    c._active_sig = {
                        "page": page_idx,
                        "rect": rect,
                        "path": c._placing_sig_path,
                        "pixmap": c._placing_sig_pixmap,
                        "resizing": False,
                        "moving": False,
                        "handle": c.HANDLE_NONE,
                        "drag_start": pos,
                        "orig_rect": fitz.Rect(rect),
                    }
                    c._placing_signature = False
                    c._placing_sig_path = ""
                    c._sig_cursor_pos = None
                    c.setCursor(Qt.CursorShape.ArrowCursor)
                    c.update()
                e.accept()
                return

        # ── 2. Interacting with placed Active Signature ────────────────
        if c._active_sig is not None:
            handle = self.get_sig_handle_at(pos)
            if handle != c.HANDLE_NONE and e.button() == Qt.MouseButton.LeftButton:
                c._active_sig["resizing"] = True
                c._active_sig["handle"] = handle
                c._active_sig["drag_start"] = pos
                c._active_sig["orig_rect"] = fitz.Rect(c._active_sig["rect"])
                e.accept()
                return
            if self.is_pos_inside_active_sig(pos) and e.button() == Qt.MouseButton.LeftButton:
                c._active_sig["moving"] = True
                c._active_sig["drag_start"] = pos
                c._active_sig["orig_rect"] = fitz.Rect(c._active_sig["rect"])
                e.accept()
                return
            # Clicked outside active signature: commit it!
            if e.button() == Qt.MouseButton.LeftButton:
                c.commit_active_signature()

        # ── 3. Crop mode ──────────────────────────────────────────────
        if c._crop_mode and e.button() == Qt.MouseButton.LeftButton:
            c.setFocus()
            c._crop_active_page = c.page_at_y(pos.y())
            c._crop_drag_start = pos
            c._crop_drag_cur = pos
            c.update()
            e.accept()
            return

        # ── 4. Standard text selection drag ───────────────────────────
        if e.button() == Qt.MouseButton.LeftButton:
            c.setFocus()
            c._drag_start = pos
            c._drag_end   = pos
            c._sel_rects  = []
            c._sel_text   = ""
            c.update()
            e.accept()

    def mouse_move(self, e):
        c = self.canvas
        pos = e.position().toPoint()

        # Signature on cursor: follows mouse
        if c._placing_signature:
            c._sig_cursor_pos = pos
            c.update()
            e.accept()
            return

        # Active signature resizing & moving
        if c._active_sig is not None:
            z = c._zoom
            orig = c._active_sig.get("orig_rect")
            start = c._active_sig.get("drag_start", pos)
            page_idx = c._active_sig["page"]
            entry = c._entries[page_idx] if 0 <= page_idx < len(c._entries) else None
            max_w = entry.w / z if entry else 1000.0
            max_h = entry.h / z if entry else 1000.0

            if c._active_sig.get("resizing") and orig:
                dx = (pos.x() - start.x()) / z
                dy = (pos.y() - start.y()) / z
                handle = c._active_sig["handle"]
                r = fitz.Rect(orig)
                min_s = 20.0

                if handle == c.HANDLE_BR:
                    r.x1 = max(r.x0 + min_s, min(max_w, orig.x1 + dx))
                    r.y1 = max(r.y0 + min_s, min(max_h, orig.y1 + dy))
                elif handle == c.HANDLE_BL:
                    r.x0 = min(r.x1 - min_s, max(0.0, orig.x0 + dx))
                    r.y1 = max(r.y0 + min_s, min(max_h, orig.y1 + dy))
                elif handle == c.HANDLE_TR:
                    r.x1 = max(r.x0 + min_s, min(max_w, orig.x1 + dx))
                    r.y0 = min(r.y1 - min_s, max(0.0, orig.y0 + dy))
                elif handle == c.HANDLE_TL:
                    r.x0 = min(r.x1 - min_s, max(0.0, orig.x0 + dx))
                    r.y0 = min(r.y1 - min_s, max(0.0, orig.y0 + dy))

                c._active_sig["rect"] = r
                c.update()
                e.accept()
                return

            if c._active_sig.get("moving") and orig:
                dx = (pos.x() - start.x()) / z
                dy = (pos.y() - start.y()) / z
                w = orig.width
                h = orig.height
                new_x0 = max(0.0, min(max_w - w, orig.x0 + dx))
                new_y0 = max(0.0, min(max_h - h, orig.y0 + dy))
                c._active_sig["rect"] = fitz.Rect(new_x0, new_y0, new_x0 + w, new_y0 + h)
                c.update()
                e.accept()
                return

            # Handle hover cursors for active signature
            h_id = self.get_sig_handle_at(pos)
            if h_id in (c.HANDLE_TL, c.HANDLE_BR):
                c.setCursor(Qt.CursorShape.SizeFDiagCursor)
                return
            if h_id in (c.HANDLE_TR, c.HANDLE_BL):
                c.setCursor(Qt.CursorShape.SizeBDiagCursor)
                return
            if self.is_pos_inside_active_sig(pos):
                c.setCursor(Qt.CursorShape.SizeAllCursor)
                return
            c.setCursor(Qt.CursorShape.ArrowCursor)

        if c._crop_mode and c._crop_drag_start:
            c._crop_drag_cur = pos
            c.update()
            e.accept()
            return

        if c._drag_start and (e.buttons() & Qt.MouseButton.LeftButton):
            c._drag_end = pos
            self.compute_selection()
            c.update()
            e.accept()

    def mouse_double_click(self, e):
        c = self.canvas
        if c._active_sig is not None and e.button() == Qt.MouseButton.LeftButton:
            c.commit_active_signature()
            e.accept()
            return
        if c._crop_mode and e.button() == Qt.MouseButton.LeftButton:
            c.crop_applied.emit()
            e.accept()
            return

    def mouse_release(self, e):
        c = self.canvas

        if c._active_sig is not None:
            if c._active_sig.get("resizing") or c._active_sig.get("moving"):
                c._active_sig["resizing"] = False
                c._active_sig["moving"] = False
                c._active_sig["handle"] = c.HANDLE_NONE
                c.update()
                e.accept()
                return

        if c._crop_mode and c._crop_drag_start:
            start = c._crop_drag_start
            end = e.position().toPoint()
            page_idx = c._crop_active_page
            c._crop_drag_start = None
            c._crop_drag_cur = None
            if (abs(end.x() - start.x()) > 5 and abs(end.y() - start.y()) > 5
                    and 0 <= page_idx < len(c._entries)):
                entry = c._entries[page_idx]
                x_off = (max(c.width(), entry.w) - entry.w) // 2 if c.width() > entry.w else 0
                z = c._zoom
                p_x0 = max(0.0, min(start.x() - x_off, end.x() - x_off) / z)
                p_y0 = max(0.0, min(start.y() - entry.y_off, end.y() - entry.y_off) / z)
                p_x1 = min(entry.w / z, max(start.x() - x_off, end.x() - x_off) / z)
                p_y1 = min(entry.h / z, max(start.y() - entry.y_off, end.y() - entry.y_off) / z)
                pw = entry.w / z
                ph = entry.h / z
                c.crop_selected.emit(page_idx, (p_x0, p_y0, p_x1, p_y1, pw, ph))
            c.update()
            e.accept()
            return

        if e.button() != Qt.MouseButton.LeftButton or not c._drag_start:
            return
        c._drag_end = e.position().toPoint()
        is_click = (abs(c._drag_start.x() - c._drag_end.x()) < 4
                    and abs(c._drag_start.y() - c._drag_end.y()) < 4)
        if is_click:
            hit = self.note_icon_at(c._drag_end)
            if hit is not None:
                c._open_note = None if c._open_note == hit else hit
                c._drag_start = None
                c._drag_end = None
                c.update()
                e.accept()
                return
            if c._open_note is not None:
                c._open_note = None
                c.update()
        self.compute_selection()
        c._drag_start = None
        c._drag_end   = None
        if c._sel_text:
            QApplication.clipboard().setText(c._sel_text)
        c.text_copied.emit(c._sel_text)
        c.update()
        e.accept()

    def key_press(self, e) -> bool:
        c = self.canvas

        # Signature placement & resizing shortcuts
        if c._placing_signature:
            if e.key() == Qt.Key.Key_Escape:
                c.cancel_signature_placement()
                return True

        if c._active_sig is not None:
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
                c.commit_active_signature()
                return True
            if e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                c.delete_active_signature()
                return True

        if c._crop_mode and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            c.crop_applied.emit()
            return True
        if c._crop_mode and (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            if e.key() == Qt.Key.Key_Z:
                if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    c.crop_redo_requested.emit()
                else:
                    c.crop_undo_requested.emit()
                return True
            elif e.key() == Qt.Key.Key_Y:
                c.crop_redo_requested.emit()
                return True

        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            sb_val = c.parent().parent().verticalScrollBar().value() if c.parent() and c.parent().parent() else 0
            idx = c.page_at_y(sb_val)
            if e.key() == Qt.Key.Key_Z:
                action = "redo" if (e.modifiers() & Qt.KeyboardModifier.ShiftModifier) else "undo"
                c.page_action_requested.emit(action, [idx])
                return True
            elif e.key() == Qt.Key.Key_Y:
                c.page_action_requested.emit("redo", [idx])
                return True
            elif e.key() == Qt.Key.Key_Left:
                c.page_action_requested.emit("rotate_left", [idx])
                return True
            elif e.key() == Qt.Key.Key_Right:
                c.page_action_requested.emit("rotate_right", [idx])
                return True
            elif e.key() == Qt.Key.Key_C and c._sel_text:
                QApplication.clipboard().setText(c._sel_text)
                return True

        if not c._crop_mode and e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            sb_val = c.parent().parent().verticalScrollBar().value() if c.parent() and c.parent().parent() else 0
            idx = c.page_at_y(sb_val)
            c.page_action_requested.emit("delete", [idx])
            return True

        return False

    def context_menu(self, e):
        c = self.canvas
        pos = e.pos()

        # If placing signature: right-click cancels placement
        if c._placing_signature:
            c.cancel_signature_placement()
            return

        # If right clicking on active placed signature: options to commit / delete
        if c._active_sig is not None and self.is_pos_inside_active_sig(pos):
            menu = QMenu(c)
            act_apply = menu.addAction(qta.icon("fa5s.check", color=ACCENT), t("btn.apply"))
            act_apply.triggered.connect(c.commit_active_signature)
            act_del = menu.addAction(qta.icon("fa5s.trash-alt", color="#EF4444"), t("btn.delete"))
            act_del.triggered.connect(c.delete_active_signature)
            menu.exec(e.globalPos())
            return

        hit = self.note_icon_at(pos)
        if hit is not None:
            menu = QMenu(c)
            delete_action = menu.addAction(t("viewer.delete_comment"))
            action = menu.exec(e.globalPos())
            if action == delete_action:
                page_idx, annot_idx = hit
                entry = c._entries[page_idx]
                if entry.annots and annot_idx < len(entry.annots):
                    rect, txt = entry.annots[annot_idx]
                    reply = QMessageBox.question(
                        c, t("msg.confirm"),
                        t("viewer.confirm_delete_comment"),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        return
                    if c._doc:
                        backup_path = None
                        if c._path and os.path.isfile(c._path):
                            try:
                                src_dir = os.path.dirname(c._path) or "."
                                fd, backup_path = tempfile.mkstemp(
                                    prefix=".pdfapps_backup_",
                                    suffix=".pdf.bak",
                                    dir=src_dir,
                                )
                                os.close(fd)
                                shutil.copy2(c._path, backup_path)
                            except Exception as exc:
                                if backup_path:
                                    with contextlib.suppress(Exception):
                                        os.unlink(backup_path)
                                    backup_path = None
                                return
                        target_annot = None
                        try:
                            page = c._doc[page_idx]
                            for annot in page.annots() or []:
                                if annot.type[0] != fitz.PDF_ANNOT_TEXT:
                                    continue
                                content = annot.info.get("content", "") or ""
                                if content.strip() != txt.strip():
                                    continue
                                ar = annot.rect
                                if abs(ar.x0 - rect.x0) < 1 and abs(ar.y0 - rect.y0) < 1:
                                    target_annot = annot
                                    break
                            if target_annot is None:
                                for annot in page.annots() or []:
                                    if annot.type[0] != fitz.PDF_ANNOT_TEXT:
                                        continue
                                    content = annot.info.get("content", "") or ""
                                    if content.strip() == txt.strip():
                                        target_annot = annot
                                        break
                            if target_annot is not None:
                                page.delete_annot(target_annot)
                            else:
                                if backup_path:
                                    with contextlib.suppress(Exception):
                                        os.unlink(backup_path)
                                QMessageBox.warning(c, t("msg.warning"), t("viewer.delete_no_match"))
                                return
                        except Exception:
                            if backup_path:
                                with contextlib.suppress(Exception):
                                    os.unlink(backup_path)
                            return
                        if c._path:
                            c._prepare_for_save()
                            try:
                                c._doc.saveIncr()
                            except Exception:
                                if backup_path:
                                    with contextlib.suppress(Exception):
                                        shutil.move(backup_path, c._path)
                                    backup_path = None
                                new_doc = c._reopen_document()
                                if new_doc is not None:
                                    c._schedule_visible()
                                return
                        if backup_path:
                            with contextlib.suppress(Exception):
                                os.unlink(backup_path)
                    entry.annots.pop(annot_idx)
                    if c._open_note is not None:
                        open_page, open_idx = c._open_note
                        if open_page == page_idx:
                            if open_idx == annot_idx:
                                c._open_note = None
                            elif open_idx > annot_idx:
                                c._open_note = (open_page, open_idx - 1)
                    c._schedule_visible()
                    c.update()
            return

        # ── Page Right-Click Menu: Add Signature & Copy ────────────────
        menu = QMenu(c)

        if c._sel_text:
            act_copy = menu.addAction(
                qta.icon("fa5s.copy", color=TEXT_SEC),
                t("viewer.copy_chars", n=len(c._sel_text)),
            )
            act_copy.triggered.connect(lambda: QApplication.clipboard().setText(c._sel_text))
            menu.addSeparator()

        act_sig = menu.addAction(
            qta.icon("fa5s.signature", color=ACCENT),
            t("viewer.add_signature"),
        )
        act_sig.triggered.connect(lambda: c.start_add_signature_flow(pos))

        menu.exec(e.globalPos())