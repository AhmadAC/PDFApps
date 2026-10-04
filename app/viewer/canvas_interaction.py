# app/viewer/canvas_interaction.py

"""PDFApps – Interaction handler for _SelectCanvas (Mouse, Keyboard, Context Menus, Signatures, Shortcuts)."""
from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from typing import TYPE_CHECKING, Any

import fitz
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox
import qtawesome as qta

from app.constants import ACCENT, TEXT_SEC
from app.i18n import t
from app.viewer.canvas_worker import _NOTE_ICON_SIZE, sort_words_in_reading_order

if TYPE_CHECKING:
    from app.viewer.canvas_1 import _SelectCanvas

# Safe fallback for PyMuPDF annotation constant to satisfy Pylance
_PDF_ANNOT_TEXT: int = getattr(fitz, "PDF_ANNOT_TEXT", 0)


def is_cjk(ch: str) -> bool:
    """Return True if character is a CJK ideograph, kana, hangul, or fullwidth punctuation."""
    if not ch:
        return False
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF or      # CJK Unified Ideographs
        0x3400 <= cp <= 0x4DBF or      # CJK Unified Ideographs Extension A
        0x20000 <= cp <= 0x2A6DF or    # Extension B
        0xF900 <= cp <= 0xFAFF or      # CJK Compatibility Ideographs
        0x3000 <= cp <= 0x303F or      # CJK Symbols and Punctuation
        0xFF00 <= cp <= 0xFFEF or      # Halfwidth and Fullwidth Forms
        0x3040 <= cp <= 0x309F or      # Hiragana
        0x30A0 <= cp <= 0x30FF or      # Katakana
        0xAC00 <= cp <= 0xD7AF         # Hangul Syllables
    )


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

    def ensure_entry_words(self, entry) -> list:
        """Ensure page word coordinates are extracted and sorted in reading order, even if off-screen."""
        words = getattr(entry, "words", None)
        if words is not None:
            return words
        c = self.canvas
        if not c._doc:
            return []
        src_idx = getattr(entry, "src_page", -1)
        if src_idx < 0 or src_idx >= c._doc.page_count:
            return []
        try:
            page = c._doc[src_idx]
            rot = c._page_rotations.get(src_idx, 0) % 360
            crop = c._page_crops.get(src_idx)
            orig_rot = page.rotation
            orig_crop = page.cropbox
            try:
                if crop:
                    crop_rect = fitz.Rect(crop) & page.mediabox
                    if not crop_rect.is_empty and crop_rect.width >= 10 and crop_rect.height >= 10:
                        page.set_cropbox(crop_rect)
                if rot:
                    page.set_rotation((orig_rot + rot) % 360)
                raw_words = page.get_text("words")
                rx0 = page.rect.x0
                ry0 = page.rect.y0
            finally:
                if rot:
                    page.set_rotation(orig_rot)
                if crop:
                    page.set_cropbox(orig_crop)

            norm_words = []
            for w in raw_words:
                norm_words.append((
                    w[0] - rx0,
                    w[1] - ry0,
                    w[2] - rx0,
                    w[3] - ry0,
                    w[4],
                    w[5] if len(w) > 5 else 0,
                    w[6] if len(w) > 6 else 0,
                    w[7] if len(w) > 7 else 0,
                ))
            words = sort_words_in_reading_order(norm_words)
            entry.words = words
            return words
        except Exception:
            return []

    def select_all(self):
        """Select all text across all pages in the open document, copy it, and display highlights."""
        c = self.canvas
        if not c._entries or not c._doc:
            return

        first_pi = -1
        first_wi = -1
        last_pi = -1
        last_wi = -1

        for pi, entry in enumerate(c._entries):
            words = self.ensure_entry_words(entry)
            if words:
                if first_pi < 0:
                    first_pi = pi
                    first_wi = 0
                last_pi = pi
                last_wi = len(words) - 1

        if first_pi < 0:
            c._sel_rects = []
            c._sel_text = ""
            c.text_copied.emit("")
            c.update()
            win: Any = c.window()
            set_status = getattr(win, "_set_status", None)
            if callable(set_status):
                set_status("ℹ No text found in document")
            return

        c._drag_start = None
        c._drag_end = None
        self._select_word_range(first_pi, first_wi, last_pi, last_wi)
        if c._sel_text:
            QApplication.clipboard().setText(c._sel_text)
        c.text_copied.emit(c._sel_text)
        c.update()

        win: Any = c.window()
        set_status = getattr(win, "_set_status", None)
        if callable(set_status) and c._sel_text:
            char_count = len(c._sel_text)
            page_count = last_pi - first_pi + 1
            set_status(f"✔ Selected all text across {page_count} page(s) ({char_count:,} characters) — copied to clipboard")

    def _get_page_lines(self, words: list | None) -> list[list[tuple[int, tuple]]]:
        """Group words into natural reading lines with uniform baseline and vertical bounds."""
        if not words:
            return []
        lines: list[list[tuple[int, tuple]]] = []
        curr_line: list[tuple[int, tuple]] = []
        curr_key = None

        for wi, w in enumerate(words):
            # w = (x0, y0, x1, y1, text, block_no, line_no, word_no)
            key = (w[5], w[6]) if len(w) >= 7 else (0, 0)
            if key != curr_key:
                if curr_line:
                    lines.append(curr_line)
                curr_line = [(wi, w)]
                curr_key = key
            else:
                prev_w = curr_line[-1][1]
                line_h = max(6.0, prev_w[3] - prev_w[1])
                if abs(w[3] - prev_w[3]) > line_h * 0.8:
                    lines.append(curr_line)
                    curr_line = [(wi, w)]
                else:
                    curr_line.append((wi, w))
        if curr_line:
            lines.append(curr_line)
        return lines

    def _find_word_index(self, words: list | None, px: float, py: float) -> int:
        """Find the word index at or closest to the given page coordinates."""
        if not words:
            return -1
        lines = self._get_page_lines(words)
        if not lines:
            return -1

        # 1. Exact hit inside word bounding box
        for line in lines:
            for wi, w in line:
                if w[0] <= px <= w[2] and w[1] <= py <= w[3]:
                    return wi

        # 2. Check if py is vertically within any line
        line_data = []
        for line in lines:
            lx0 = min(item[1][0] for item in line)
            ly0 = min(item[1][1] for item in line)
            lx1 = max(item[1][2] for item in line)
            ly1 = max(item[1][3] for item in line)
            lyc = (ly0 + ly1) / 2.0
            line_data.append((line, lx0, ly0, lx1, ly1, lyc))

        for line, lx0, ly0, lx1, ly1, _ in line_data:
            if ly0 - 3.0 <= py <= ly1 + 3.0:
                if px <= lx0:
                    return line[0][0]
                if px >= lx1:
                    return line[-1][0]
                best_wi = line[0][0]
                best_dist = float("inf")
                for wi, w in line:
                    wc = (w[0] + w[2]) / 2.0
                    d = abs(px - wc)
                    if d < best_dist:
                        best_dist = d
                        best_wi = wi
                return best_wi

        # 3. Outside all lines vertically
        if py < line_data[0][2]:
            return line_data[0][0][0][0]
        if py > line_data[-1][4]:
            return line_data[-1][0][-1][0]

        best_line = min(line_data, key=lambda ld: abs(py - ld[5]))
        line, lx0, ly0, lx1, ly1, _ = best_line
        if px <= lx0:
            return line[0][0]
        if px >= lx1:
            return line[-1][0]
        best_wi = line[0][0]
        best_dist = float("inf")
        for wi, w in line:
            wc = (w[0] + w[2]) / 2.0
            d = abs(px - wc)
            if d < best_dist:
                best_dist = d
                best_wi = wi
        return best_wi

    def _select_word_range(self, p1_page: int, w1: int, p2_page: int, w2: int):
        c = self.canvas
        if p1_page < 0 or p2_page < 0:
            c._sel_rects = []
            c._sel_text = ""
            return

        if (p1_page, w1) > (p2_page, w2):
            p_start, w_start = p2_page, w2
            p_end, w_end = p1_page, w1
        else:
            p_start, w_start = p1_page, w1
            p_end, w_end = p2_page, w2

        rects: list[QRect] = []
        page_texts: list[str] = []
        z = c._zoom or 1.0

        for pi in range(p_start, p_end + 1):
            if pi >= len(c._entries):
                continue
            entry = c._entries[pi]
            words = self.ensure_entry_words(entry)
            if not words:
                continue

            pw_start = w_start if pi == p_start else 0
            pw_end = w_end if pi == p_end else len(words) - 1
            if pw_start > pw_end or pw_start >= len(words):
                continue

            selected_indices = set(range(pw_start, pw_end + 1))
            lines = self._get_page_lines(words)

            x_off = c.page_x_offset(entry)
            line_strings: list[str] = []

            for line in lines:
                sel_in_line = [item for item in line if item[0] in selected_indices]
                if not sel_in_line:
                    continue

                sel_in_line.sort(key=lambda item: item[1][0])

                full_ly0 = min(item[1][1] for item in line)
                full_ly1 = max(item[1][3] for item in line)
                line_h = max(6.0, full_ly1 - full_ly0)

                # Segment and merge consecutive words into continuous rectangles
                segments: list[tuple[float, float]] = []
                seg_x0 = sel_in_line[0][1][0]
                seg_x1 = sel_in_line[0][1][2]

                for item in sel_in_line[1:]:
                    w = item[1]
                    gap = w[0] - seg_x1
                    if gap <= max(14.0, line_h * 1.5) and w[0] >= seg_x0:
                        seg_x1 = max(seg_x1, w[2])
                    else:
                        segments.append((seg_x0, seg_x1))
                        seg_x0 = w[0]
                        seg_x1 = w[2]
                segments.append((seg_x0, seg_x1))

                for sx_start, sx_end in segments:
                    rx0 = x_off + int(round(sx_start * z))
                    ry0 = entry.y_off + int(round(full_ly0 * z))
                    rx1 = x_off + int(round(sx_end * z))
                    ry1 = entry.y_off + int(round(full_ly1 * z))
                    rects.append(QRect(rx0, ry0, max(1, rx1 - rx0), max(1, ry1 - ry0)))

                line_parts: list[str] = []
                for idx, item in enumerate(sel_in_line):
                    txt = item[1][4]
                    if idx == 0:
                        line_parts.append(txt)
                    else:
                        prev_txt = sel_in_line[idx - 1][1][4]
                        if prev_txt and txt and is_cjk(prev_txt[-1]) and is_cjk(txt[0]):
                            line_parts.append(txt)
                        else:
                            line_parts.append(" " + txt)
                line_strings.append("".join(line_parts))

            if line_strings:
                page_texts.append("\n".join(line_strings))

        c._sel_rects = rects
        c._sel_text = "\n\n".join(page_texts)

    def compute_selection(self):
        c = self.canvas
        start = c._drag_start
        end = c._drag_end
        if start is None or end is None:
            return

        p1_page = c.page_at_y(start.y())
        p2_page = c.page_at_y(end.y())
        if not (0 <= p1_page < len(c._entries)) or not (0 <= p2_page < len(c._entries)):
            return

        e1 = c._entries[p1_page]
        x_off1 = c.page_x_offset(e1)
        z = c._zoom or 1.0
        p1_x = (start.x() - x_off1) / z
        p1_y = (start.y() - e1.y_off) / z

        e2 = c._entries[p2_page]
        x_off2 = c.page_x_offset(e2)
        p2_x = (end.x() - x_off2) / z
        p2_y = (end.y() - e2.y_off) / z

        words1 = self.ensure_entry_words(e1)
        words2 = self.ensure_entry_words(e2)

        w1_idx = self._find_word_index(words1, p1_x, p1_y)
        w2_idx = self._find_word_index(words2, p2_x, p2_y)

        if w1_idx < 0 and w2_idx < 0:
            c._sel_rects = []
            c._sel_text = ""
            return

        if w1_idx < 0:
            w1_idx = 0
        if w2_idx < 0:
            w2_idx = len(words2 or []) - 1

        self._select_word_range(p1_page, w1_idx, p2_page, w2_idx)

    def note_icon_at(self, pos: QPoint) -> tuple[int, int] | None:
        c = self.canvas
        z = c._zoom
        margin = 8
        for page_idx, entry in enumerate(c._entries):
            annots = getattr(entry, "annots", None)
            if not annots:
                continue
            if pos.y() < entry.y_off - margin or pos.y() > entry.y_off + entry.h + margin:
                continue
            x_off = c.page_x_offset(entry)
            for annot_idx, (rect, _txt) in enumerate(annots):
                px = x_off + int(round(rect.x0 * z))
                py = entry.y_off + int(round(rect.y0 * z))
                hit_r = QRect(px - margin, py - margin,
                              _NOTE_ICON_SIZE + margin * 2, _NOTE_ICON_SIZE + margin * 2)
                if hit_r.contains(pos):
                    return (page_idx, annot_idx)
        return None

    def get_sig_handle_at(self, pos: QPoint) -> int:
        c = self.canvas
        sig = c._active_sig
        if not sig:
            return c.HANDLE_NONE
        page_idx = sig["page"]
        if not (0 <= page_idx < len(c._entries)):
            return c.HANDLE_NONE
        entry = c._entries[page_idx]
        x_off = c.page_x_offset(entry)
        z = c._zoom
        r = sig["rect"]
        sx0 = x_off + int(round(r.x0 * z))
        sy0 = entry.y_off + int(round(r.y0 * z))
        sx1 = x_off + int(round(r.x1 * z))
        sy1 = entry.y_off + int(round(r.y1 * z))
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
        sig = c._active_sig
        if not sig:
            return False
        page_idx = sig["page"]
        if not (0 <= page_idx < len(c._entries)):
            return False
        entry = c._entries[page_idx]
        x_off = c.page_x_offset(entry)
        z = c._zoom
        r = sig["rect"]
        sx0 = x_off + int(round(r.x0 * z))
        sy0 = entry.y_off + int(round(r.y0 * z))
        sx1 = x_off + int(round(r.x1 * z))
        sy1 = entry.y_off + int(round(r.y1 * z))
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
                    x_off = c.page_x_offset(entry)
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
        sig = c._active_sig
        if sig is not None:
            handle = self.get_sig_handle_at(pos)
            if handle != c.HANDLE_NONE and e.button() == Qt.MouseButton.LeftButton:
                sig["resizing"] = True
                sig["handle"] = handle
                sig["drag_start"] = pos
                sig["orig_rect"] = fitz.Rect(sig["rect"])
                e.accept()
                return
            if self.is_pos_inside_active_sig(pos) and e.button() == Qt.MouseButton.LeftButton:
                sig["moving"] = True
                sig["drag_start"] = pos
                sig["orig_rect"] = fitz.Rect(sig["rect"])
                e.accept()
                return
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
            self.compute_selection()
            c.update()
            e.accept()

    def mouse_move(self, e):
        c = self.canvas
        pos = e.position().toPoint()

        if c._placing_signature:
            c._sig_cursor_pos = pos
            c.update()
            e.accept()
            return

        sig = c._active_sig
        if sig is not None:
            z = c._zoom
            orig = sig.get("orig_rect")
            start = sig.get("drag_start", pos)
            page_idx = sig["page"]
            entry = c._entries[page_idx] if 0 <= page_idx < len(c._entries) else None
            max_w = entry.w / z if entry else 1000.0
            max_h = entry.h / z if entry else 1000.0

            if sig.get("resizing") and orig:
                dx = (pos.x() - start.x()) / z
                dy = (pos.y() - start.y()) / z
                handle = sig.get("handle", c.HANDLE_NONE)
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

                sig["rect"] = r
                c.update()
                e.accept()
                return

            if sig.get("moving") and orig:
                dx = (pos.x() - start.x()) / z
                dy = (pos.y() - start.y()) / z
                w = orig.width
                h = orig.height
                new_x0 = max(0.0, min(max_w - w, orig.x0 + dx))
                new_y0 = max(0.0, min(max_h - h, orig.y0 + dy))
                sig["rect"] = fitz.Rect(new_x0, new_y0, new_x0 + w, new_y0 + h)
                c.update()
                e.accept()
                return

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
        if e.button() == Qt.MouseButton.LeftButton:
            pos = e.position().toPoint()
            page_idx = c.page_at_y(pos.y())
            if 0 <= page_idx < len(c._entries):
                entry = c._entries[page_idx]
                words = self.ensure_entry_words(entry)
                if words:
                    x_off = c.page_x_offset(entry)
                    z = c._zoom or 1.0
                    px = (pos.x() - x_off) / z
                    py = (pos.y() - entry.y_off) / z
                    wi = self._find_word_index(words, px, py)
                    if wi >= 0:
                        c._drag_start = pos
                        c._drag_end = pos
                        self._select_word_range(page_idx, wi, page_idx, wi)
                        if c._sel_text:
                            QApplication.clipboard().setText(c._sel_text)
                        c.text_copied.emit(c._sel_text)
                        c.update()
                        e.accept()

    def mouse_release(self, e):
        c = self.canvas

        sig = c._active_sig
        if sig is not None:
            if sig.get("resizing") or sig.get("moving"):
                sig["resizing"] = False
                sig["moving"] = False
                sig["handle"] = c.HANDLE_NONE
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
                x_off = c.page_x_offset(entry)
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
        drag_start = c._drag_start
        pos = e.position().toPoint()
        c._drag_end = pos
        is_click = (abs(drag_start.x() - pos.x()) < 4
                    and abs(drag_start.y() - pos.y()) < 4)
        if is_click:
            hit = self.note_icon_at(pos)
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
            self.clear_selection()
            c.text_copied.emit("")
        else:
            self.compute_selection()
            if c._sel_text:
                QApplication.clipboard().setText(c._sel_text)
            c.text_copied.emit(c._sel_text)
        c._drag_start = None
        c._drag_end   = None
        c.update()
        e.accept()

    def key_press(self, e) -> bool:
        c = self.canvas
        key = e.key()
        modifiers = e.modifiers()

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                c.zoom_in()
                return True
            if key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
                c.zoom_out()
                return True
            if key == Qt.Key.Key_0:
                c.zoom_reset()
                return True

        if c._placing_signature:
            if key == Qt.Key.Key_Escape:
                c.cancel_signature_placement()
                return True

        if c._active_sig is not None:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
                c.commit_active_signature()
                return True
            if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                c.delete_active_signature()
                return True

        if c._crop_mode and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            c.crop_applied.emit()
            return True
        if c._crop_mode and (modifiers & Qt.KeyboardModifier.ControlModifier):
            if key == Qt.Key.Key_Z:
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    c.crop_redo_requested.emit()
                else:
                    c.crop_undo_requested.emit()
                return True
            elif key == Qt.Key.Key_Y:
                c.crop_redo_requested.emit()
                return True

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            sa = c._get_scroll_area()
            sb_val = sa.verticalScrollBar().value() if sa else 0
            idx = c.page_at_y(sb_val)
            if key == Qt.Key.Key_Z:
                action = "redo" if (modifiers & Qt.KeyboardModifier.ShiftModifier) else "undo"
                c.page_action_requested.emit(action, [idx])
                return True
            elif key == Qt.Key.Key_Y:
                c.page_action_requested.emit("redo", [idx])
                return True
            elif key == Qt.Key.Key_Left:
                c.page_action_requested.emit("rotate_left", [idx])
                return True
            elif key == Qt.Key.Key_Right:
                c.page_action_requested.emit("rotate_right", [idx])
                return True
            elif key == Qt.Key.Key_C and c._sel_text:
                QApplication.clipboard().setText(c._sel_text)
                win: Any = c.window()
                set_status = getattr(win, "_set_status", None)
                if callable(set_status):
                    set_status(f"✔ Copied {len(c._sel_text):,} characters to clipboard")
                return True
            elif key == Qt.Key.Key_A:
                self.select_all()
                return True

        if key == Qt.Key.Key_Escape and c._sel_text:
            self.clear_selection()
            c.text_copied.emit("")
            c.update()
            return True

        if not c._crop_mode and key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            sa = c._get_scroll_area()
            sb_val = sa.verticalScrollBar().value() if sa else 0
            idx = c.page_at_y(sb_val)
            c.page_action_requested.emit("delete", [idx])
            return True

        return False

    def context_menu(self, e):
        c = self.canvas
        pos = e.pos()

        if c._placing_signature:
            c.cancel_signature_placement()
            return

        sig = c._active_sig
        if sig is not None and self.is_pos_inside_active_sig(pos):
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
                annots = getattr(entry, "annots", None)
                if annots and annot_idx < len(annots):
                    rect, txt = annots[annot_idx]
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
                            except Exception:
                                if backup_path:
                                    with contextlib.suppress(Exception):
                                        os.unlink(backup_path)
                                    backup_path = None
                                return
                        target_annot = None
                        try:
                            page = c._doc[page_idx]
                            for annot in page.annots() or []:
                                if annot.type[0] != _PDF_ANNOT_TEXT and annot.type[1] != "Text":
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
                                    if annot.type[0] != _PDF_ANNOT_TEXT and annot.type[1] != "Text":
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
                    annots.pop(annot_idx)
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

        menu = QMenu(c)

        if c._sel_text:
            act_copy = menu.addAction(
                qta.icon("fa5s.copy", color=TEXT_SEC),
                t("viewer.copy_chars", n=len(c._sel_text)),
            )
            act_copy.triggered.connect(lambda: QApplication.clipboard().setText(c._sel_text))
            menu.addSeparator()

        act_sel_all = menu.addAction(
            qta.icon("fa5s.object-group", color=TEXT_SEC),
            t("viewer.select_all", default="Select All\tCtrl+A"),
        )
        act_sel_all.triggered.connect(self.select_all)
        menu.addSeparator()

        act_sig = menu.addAction(
            qta.icon("fa5s.signature", color=ACCENT),
            t("viewer.add_signature"),
        )
        act_sig.triggered.connect(lambda: c.start_add_signature_flow(pos))

        menu.exec(e.globalPos())