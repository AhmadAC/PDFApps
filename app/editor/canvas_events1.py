
# app/editor/canvas_events1.py

"""Canvas interaction handler: mouse, drag handles, keyboard and context menus."""

from __future__ import annotations

import fitz
from PySide6.QtCore import Qt, QRect
from PySide6.QtWidgets import QMenu, QMessageBox
import qtawesome as qta

from app.constants import ACCENT
from app.i18n import t
from app.editor.canvas_overlay1 import CanvasOverlayManager

# Safe fallback for PyMuPDF annotation constant to satisfy Pylance
_PDF_ANNOT_TEXT: int = getattr(fitz, "PDF_ANNOT_TEXT", 0)


class CanvasEventHandler:
    def __init__(self, canvas):
        self.canvas = canvas

    def handle_mouse_press(self, e):
        c = self.canvas
        pos = e.position().toPoint()
        c.setFocus()

        # 1. Placing signature from cursor
        if c._placing_signature:
            if e.button() == Qt.MouseButton.RightButton:
                c.cancel_signature_placement()
                e.accept()
                return
            if e.button() == Qt.MouseButton.LeftButton:
                page_idx, lx, ly = c._page_and_local(pos.x(), pos.y())
                z = c._zoom or 1.0
                px = lx / z
                py = ly / z
                pix = c._placing_sig_pixmap
                aspect = (pix.height() / pix.width()) if pix and pix.width() > 0 else 0.35
                sig_w = 160.0
                sig_h = sig_w * aspect
                r = fitz.Rect(max(0.0, px - sig_w / 2), max(0.0, py - sig_h / 2),
                              px + sig_w / 2, py + sig_h / 2)
                edit = {
                    "type": "signature",
                    "page": page_idx,
                    "rect": r,
                    "path": c._placing_sig_path,
                }
                c._overlays.append(edit)
                c._selected_overlay_idx = len(c._overlays) - 1
                c._placing_signature = False
                c._placing_sig_path = ""
                c._sig_cursor_pos = None
                c.setCursor(Qt.CursorShape.ArrowCursor)
                c.signature_added.emit(page_idx, r, edit["path"])
                c.update()
                e.accept()
                return

        # 2. Selected overlay handle or drag move
        if c._selected_overlay_idx >= 0 and e.button() == Qt.MouseButton.LeftButton:
            handle = c._overlay_mgr.get_overlay_handle_at(c._selected_overlay_idx, pos)
            if handle != CanvasOverlayManager.HANDLE_NONE:
                c._drag_handle = handle
                c._drag_start_pos = pos
                cur_ov = c._overlays[c._selected_overlay_idx]
                r_val = cur_ov.get("rect") if "rect" in cur_ov else fitz.Rect(cur_ov.get("bbox", (0, 0, 0, 0)))
                c._drag_start_rect = fitz.Rect(r_val)
                e.accept()
                return
            if c._overlay_mgr.is_pos_inside_overlay(c._selected_overlay_idx, pos):
                c._moving_overlay = True
                c._drag_start_pos = pos
                cur_ov = c._overlays[c._selected_overlay_idx]
                r_val = cur_ov.get("rect") if "rect" in cur_ov else fitz.Rect(cur_ov.get("bbox", (0, 0, 0, 0)))
                c._drag_start_rect = fitz.Rect(r_val)
                e.accept()
                return
            c._selected_overlay_idx = -1
            c.update()

        # 3. Hit testing overlays
        if e.button() == Qt.MouseButton.LeftButton:
            for idx in reversed(range(len(c._overlays))):
                if c._overlay_mgr.is_pos_inside_overlay(idx, pos):
                    c._selected_overlay_idx = idx
                    c._moving_overlay = True
                    c._drag_start_pos = pos
                    cur_ov = c._overlays[idx]
                    r_val = cur_ov.get("rect") if "rect" in cur_ov else fitz.Rect(cur_ov.get("bbox", (0, 0, 0, 0)))
                    c._drag_start_rect = fitz.Rect(r_val)
                    if cur_ov.get("type") in ("text", "text_edit"):
                        fn = cur_ov.get("font", "Helvetica")
                        sz = float(cur_ov.get("font_size", cur_ov.get("size", 12)))
                        color_val = cur_ov.get("color", 0)
                        flags = int(cur_ov.get("flags", 0) or 0)
                        if isinstance(color_val, (list, tuple)) and len(color_val) >= 3:
                            col = tuple(float(x) for x in color_val[:3])
                        elif isinstance(color_val, int):
                            col = (((color_val >> 16) & 0xFF) / 255.0, ((color_val >> 8) & 0xFF) / 255.0, (color_val & 0xFF) / 255.0)
                        else:
                            col = (0.0, 0.0, 0.0)
                        c.text_edit_started.emit({
                            "font": fn, "size": sz, "color": col,
                            "bold": bool(flags & 16), "italic": bool(flags & 2),
                            "text": cur_ov.get("new_text", cur_ov.get("text", "")),
                        })
                    c.update()
                    e.accept()
                    return

            # 4. Check existing media in PDF
            page_idx, lx, ly = c._page_and_local(pos.x(), pos.y())
            pdf_pt = c._to_pdf(page_idx, lx, ly)
            existing_media = c._overlay_mgr.detect_existing_media_at(page_idx, pdf_pt)
            if existing_media:
                c._selected_overlay_idx = c._overlays.index(existing_media)
                c._moving_overlay = True
                c._drag_start_pos = pos
                c._drag_start_rect = fitz.Rect(existing_media["rect"])
                c.update()
                e.accept()
                return

        if e.button() != Qt.MouseButton.LeftButton:
            return

        if c._draw_mode and c._page_offsets:
            page_idx, _lx, _ly = c._page_and_local(pos.x(), pos.y())
            c._stroke_page = page_idx
            c._current_stroke = [(pos.x(), pos.y())]
            c.update()
            return

        c._drag_start = pos
        c._drag_rect = None

    def handle_mouse_move(self, e):
        c = self.canvas
        pos = e.position().toPoint()

        if c._placing_signature:
            c._sig_cursor_pos = pos
            c.update()
            e.accept()
            return

        if c._selected_overlay_idx >= 0:
            z = c._zoom
            orig = c._drag_start_rect
            start = c._drag_start_pos

            if c._drag_handle != CanvasOverlayManager.HANDLE_NONE and orig:
                dx = (pos.x() - start.x()) / z
                dy = (pos.y() - start.y()) / z
                handle = c._drag_handle
                r = fitz.Rect(orig)
                min_s = 15.0

                if handle == CanvasOverlayManager.HANDLE_BR:
                    r.x1 = max(r.x0 + min_s, orig.x1 + dx)
                    r.y1 = max(r.y0 + min_s, orig.y1 + dy)
                elif handle == CanvasOverlayManager.HANDLE_BL:
                    r.x0 = min(r.x1 - min_s, orig.x0 + dx)
                    r.y1 = max(r.y0 + min_s, orig.y1 + dy)
                elif handle == CanvasOverlayManager.HANDLE_TR:
                    r.x1 = max(r.x0 + min_s, orig.x1 + dx)
                    r.y0 = min(r.y1 - min_s, orig.y0 + dy)
                elif handle == CanvasOverlayManager.HANDLE_TL:
                    r.x0 = min(r.x1 - min_s, orig.x0 + dx)
                    r.y0 = min(r.y1 - min_s, orig.y0 + dy)

                ov = c._overlays[c._selected_overlay_idx]
                if "rect" in ov:
                    ov["rect"] = r
                elif "bbox" in ov:
                    ov["bbox"] = [r.x0, r.y0, r.x1, r.y1]
                if "point" in ov:
                    ov["point"] = fitz.Point(r.x0, r.y0 + ov.get("size", 12) * 0.82)
                c.overlay_changed.emit()
                c.update()
                e.accept()
                return

            if c._moving_overlay and orig:
                dx = (pos.x() - start.x()) / z
                dy = (pos.y() - start.y()) / z
                w = orig.width
                h = orig.height
                ov = c._overlays[c._selected_overlay_idx]
                new_r = fitz.Rect(orig.x0 + dx, orig.y0 + dy, orig.x0 + dx + w, orig.y0 + dy + h)
                if "rect" in ov:
                    ov["rect"] = new_r
                elif "bbox" in ov:
                    ov["bbox"] = [new_r.x0, new_r.y0, new_r.x1, new_r.y1]
                    if "origin" in ov:
                        ov["origin"] = [new_r.x0, new_r.y1]
                if "point" in ov:
                    ov["point"] = fitz.Point(new_r.x0, new_r.y0 + ov.get("size", 12) * 0.82)
                c.overlay_changed.emit()
                c.update()
                e.accept()
                return

            h_id = c._overlay_mgr.get_overlay_handle_at(c._selected_overlay_idx, pos)
            if h_id in (CanvasOverlayManager.HANDLE_TL, CanvasOverlayManager.HANDLE_BR):
                c.setCursor(Qt.CursorShape.SizeFDiagCursor)
                return
            if h_id in (CanvasOverlayManager.HANDLE_TR, CanvasOverlayManager.HANDLE_BL):
                c.setCursor(Qt.CursorShape.SizeBDiagCursor)
                return
            if c._overlay_mgr.is_pos_inside_overlay(c._selected_overlay_idx, pos):
                c.setCursor(Qt.CursorShape.SizeAllCursor)
                return
            c.setCursor(Qt.CursorShape.ArrowCursor)

        if c._draw_mode and c._current_stroke is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            if c._stroke_page < 0 or c._stroke_page >= len(c._page_offsets):
                return
            yo, pw, ph = c._page_offsets[c._stroke_page]
            sx = max(0, min(pos.x(), pw))
            sy = max(yo, min(pos.y(), yo + ph))
            last = c._current_stroke[-1]
            if (sx - last[0]) ** 2 + (sy - last[1]) ** 2 >= 4:
                c._current_stroke.append((sx, sy))
                c.update()
            return
        if c._drag_start and (e.buttons() & Qt.MouseButton.LeftButton):
            c._drag_rect = QRect(c._drag_start, pos).normalized()
            c.update()

    def handle_mouse_release(self, e):
        c = self.canvas
        if c._selected_overlay_idx >= 0:
            if c._drag_handle != CanvasOverlayManager.HANDLE_NONE or c._moving_overlay:
                c._drag_handle = CanvasOverlayManager.HANDLE_NONE
                c._moving_overlay = False
                c.update()
                e.accept()
                return

        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position().toPoint()
        if c._draw_mode and c._current_stroke is not None:
            if len(c._current_stroke) >= 2 and c._stroke_page >= 0:
                z = c._zoom or 1.0
                yo = c._page_offsets[c._stroke_page][0]
                pdf_points = [(round(x / z, 2), round((y - yo) / z, 2))
                              for x, y in c._current_stroke]
                c._page_idx = c._stroke_page
                c.stroke_finished.emit(c._stroke_page, pdf_points)
            c._current_stroke = None
            c._stroke_page = -1
            c.update()
            return
        if c._drag_rect and c._drag_rect.width() > 6 and c._drag_rect.height() > 6:
            page_idx, lx, ly = c._page_and_local(c._drag_rect.left(), c._drag_rect.top())
            yo = c._page_offsets[page_idx][0] if page_idx < len(c._page_offsets) else 0
            local_rect = QRect(c._drag_rect.left(), c._drag_rect.top() - yo,
                               c._drag_rect.width(), c._drag_rect.height())
            c._page_idx = page_idx
            pdf_rect = c._rect_to_pdf(page_idx, local_rect)
            if pdf_rect is not None:
                c.rect_selected.emit(page_idx, pdf_rect)
        else:
            hit = c._overlay_mgr.note_icon_at(pos)
            if hit < 0:
                hit, _ = c._overlay_mgr.annot_note_at(pos)
            if hit >= 0:
                c._open_note = None if c._open_note == hit else hit
                c.update()
                c._drag_start = None; c._drag_rect = None
                return
            if c._open_note is not None:
                c._open_note = None
                c.update()
            page_idx, lx, ly = c._page_and_local(pos.x(), pos.y())
            c._page_idx = page_idx
            c.point_clicked.emit(page_idx, c._to_pdf(page_idx, lx, ly))
        c._drag_start = None; c._drag_rect = None
        c.update()

    def handle_key_press(self, e):
        c = self.canvas
        key = e.key()
        modifiers = e.modifiers()

        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if c._selected_overlay_idx >= 0:
                c.delete_selected_overlay()
                e.accept()
                return

        if key == Qt.Key.Key_Escape:
            if c._placing_signature:
                c.cancel_signature_placement()
                e.accept()
                return
            if c._selected_overlay_idx >= 0:
                c._selected_overlay_idx = -1
                c.update()
                e.accept()
                return

        # Nudge movement of selected media/image using Arrow keys
        if c._selected_overlay_idx >= 0 and key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            step = 15.0 if (modifiers & Qt.KeyboardModifier.ShiftModifier) else (1.0 if (modifiers & Qt.KeyboardModifier.AltModifier) else 4.0)
            dx = 0.0
            dy = 0.0
            if key == Qt.Key.Key_Left: dx = -step
            elif key == Qt.Key.Key_Right: dx = step
            elif key == Qt.Key.Key_Up: dy = -step
            elif key == Qt.Key.Key_Down: dy = step
            ov = c._overlays[c._selected_overlay_idx]
            if "rect" in ov:
                r = ov["rect"]
                ov["rect"] = fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy)
                if "point" in ov:
                    ov["point"] = fitz.Point(ov["point"].x + dx, ov["point"].y + dy)
            elif "bbox" in ov:
                b = ov["bbox"]
                ov["bbox"] = [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy]
                if "origin" in ov:
                    ov["origin"] = [b[0] + dx, b[3] + dy]
                if "point" in ov:
                    ov["point"] = fitz.Point(ov["point"].x + dx, ov["point"].y + dy)
            elif "point" in ov:
                ov["point"] = fitz.Point(ov["point"].x + dx, ov["point"].y + dy)
            c._drag_start_rect = fitz.Rect(ov["rect"]) if "rect" in ov else fitz.Rect(ov["bbox"])
            c.overlay_changed.emit()
            c.update()
            e.accept()
            return

        # Resizing selected media/image using Ctrl + and Ctrl -
        if c._selected_overlay_idx >= 0:
            if (modifiers & Qt.KeyboardModifier.ControlModifier) or key in (Qt.Key.Key_Plus, Qt.Key.Key_Minus):
                if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                    c.scale_selected_overlay(1.10)
                    e.accept()
                    return
                elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
                    c.scale_selected_overlay(0.90)
                    e.accept()
                    return

    def handle_context_menu(self, e):
        c = self.canvas
        pos = e.pos()

        if c._placing_signature:
            c.cancel_signature_placement()
            return

        if c._selected_overlay_idx >= 0 and c._overlay_mgr.is_pos_inside_overlay(c._selected_overlay_idx, pos):
            menu = QMenu(c)
            act_inc = menu.addAction(qta.icon("fa5s.search-plus", color=ACCENT), "Increase Size (Ctrl+)")
            act_inc.triggered.connect(lambda: c.scale_selected_overlay(1.10))
            act_dec = menu.addAction(qta.icon("fa5s.search-minus", color=ACCENT), "Decrease Size (Ctrl-)")
            act_dec.triggered.connect(lambda: c.scale_selected_overlay(0.90))
            menu.addSeparator()
            act_del = menu.addAction(qta.icon("fa5s.trash-alt", color="#EF4444"), t("btn.delete"))
            act_del.triggered.connect(c.delete_selected_overlay)
            act_dup = menu.addAction(qta.icon("fa5s.clone", color=ACCENT), t("tool.duplicate", default="Duplicate"))
            act_dup.triggered.connect(c.duplicate_selected_overlay)
            menu.exec(e.globalPos())
            return

        for idx in reversed(range(len(c._overlays))):
            if c._overlay_mgr.is_pos_inside_overlay(idx, pos):
                c._selected_overlay_idx = idx
                c.update()
                menu = QMenu(c)
                act_inc = menu.addAction(qta.icon("fa5s.search-plus", color=ACCENT), "Increase Size (Ctrl+)")
                act_inc.triggered.connect(lambda: c.scale_selected_overlay(1.10))
                act_dec = menu.addAction(qta.icon("fa5s.search-minus", color=ACCENT), "Decrease Size (Ctrl-)")
                act_dec.triggered.connect(lambda: c.scale_selected_overlay(0.90))
                menu.addSeparator()
                act_del = menu.addAction(qta.icon("fa5s.trash-alt", color="#EF4444"), t("btn.delete"))
                act_del.triggered.connect(c.delete_selected_overlay)
                act_dup = menu.addAction(qta.icon("fa5s.clone", color=ACCENT), t("tool.duplicate", default="Duplicate"))
                act_dup.triggered.connect(c.duplicate_selected_overlay)
                menu.exec(e.globalPos())
                return

        hit = c._overlay_mgr.note_icon_at(pos)
        if hit < 0:
            hit, _ = c._overlay_mgr.annot_note_at(pos)
        if hit >= 0:
            menu = QMenu(c)
            delete_action = menu.addAction(t("viewer.delete_comment"))
            action = menu.exec(e.globalPos())
            if action == delete_action:
                reply = QMessageBox.question(
                    c, t("msg.confirm"),
                    t("viewer.confirm_delete_comment"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
                overlay = c._overlays[hit]
                if c._doc and overlay.get("_existing"):
                    page = c._doc[overlay.get("page", 0)]
                    for annot in page.annots() or []:
                        if annot.type[0] == _PDF_ANNOT_TEXT or annot.type[1] == "Text":
                            txt = annot.info.get("content", "") or ""
                            if txt.strip() == overlay.get("text", "").strip():
                                page.delete_annot(annot)
                                break
                c._overlays.pop(hit)
                if hasattr(c, "note_deleted"):
                    c.note_deleted.emit(overlay)
                if c._open_note == hit:
                    c._open_note = None
                elif c._open_note is not None and c._open_note > hit:
                    c._open_note -= 1
                c.update()
            return

        menu = QMenu(c)
        act_add_sig = menu.addAction(qta.icon("fa5s.signature", color=ACCENT), t("viewer.add_signature"))
        act_add_sig.triggered.connect(lambda: c.start_add_signature_flow(pos))
        menu.exec(e.globalPos())
