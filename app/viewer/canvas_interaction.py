"""PDFApps – Interaction handler for _SelectCanvas (Mouse, Keyboard, Context Menus)."""
from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox
import qtawesome as qta

from app.constants import TEXT_SEC
from app.i18n import t
from app.viewer.canvas_worker import _NOTE_ICON_SIZE

if TYPE_CHECKING:
    from app.viewer.canvas import _SelectCanvas


class CanvasInteractionHandler:
    """Handles text selection, note balloon interaction, shortcuts, and context actions."""

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

    def mouse_press(self, e):
        c = self.canvas
        if c._crop_mode and e.button() == Qt.MouseButton.LeftButton:
            pos = e.position().toPoint()
            c.setFocus()
            c._crop_active_page = c.page_at_y(pos.y())
            c._crop_drag_start = pos
            c._crop_drag_cur = pos
            c.update()
            e.accept()
            return

        if e.button() == Qt.MouseButton.LeftButton:
            c.setFocus()
            c._drag_start = e.position().toPoint()
            c._drag_end   = c._drag_start
            c._sel_rects  = []
            c._sel_text   = ""
            c.update()
            e.accept()

    def mouse_move(self, e):
        c = self.canvas
        if c._crop_mode and c._crop_drag_start:
            c._crop_drag_cur = e.position().toPoint()
            c.update()
            e.accept()
            return

        if c._drag_start and (e.buttons() & Qt.MouseButton.LeftButton):
            c._drag_end = e.position().toPoint()
            self.compute_selection()
            c.update()
            e.accept()

    def mouse_double_click(self, e):
        c = self.canvas
        if c._crop_mode and e.button() == Qt.MouseButton.LeftButton:
            c.crop_applied.emit()
            e.accept()
            return

    def mouse_release(self, e):
        c = self.canvas
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

        # Canvas-focused keyboard events routed to appropriate global actions
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
                        import fitz
                        from app.utils import show_error
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
                                show_error(c, exc)
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
                        except Exception as exc:
                            if backup_path:
                                with contextlib.suppress(Exception):
                                    os.unlink(backup_path)
                            show_error(c, exc)
                            return
                        if c._path:
                            c._prepare_for_save()
                            try:
                                c._doc.saveIncr()
                            except Exception as exc:
                                if backup_path:
                                    with contextlib.suppress(Exception):
                                        shutil.move(backup_path, c._path)
                                    backup_path = None
                                new_doc = c._reopen_document()
                                if new_doc is not None:
                                    c._schedule_visible()
                                show_error(c, exc)
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
        if not c._sel_text:
            return
        menu = QMenu(c)
        act = menu.addAction(
            qta.icon("fa5s.copy", color=TEXT_SEC),
            t("viewer.copy_chars", n=len(c._sel_text)),
        )
        act.triggered.connect(lambda: QApplication.clipboard().setText(c._sel_text))
        menu.exec(e.globalPos())