# app/editor/canvas_painter1.py

"""Canvas painter: renders pages, overlays, vector check/cross stamps, text modifications, notes, and smoothed freehand drawings."""

from __future__ import annotations

import os
import fitz
from PySide6.QtCore import Qt, QRect, QPoint, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPixmap, QPainterPath

from app.constants import ACCENT, TEXT_SEC
from app.i18n import t
from app.editor.canvas_render1 import _NOTE_ICON_SIZE, _load_overlay_pixmap


class CanvasPainter:
    @staticmethod
    def paint(canvas, painter: QPainter):
        p = painter
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.fillRect(canvas.rect(), QColor(canvas._bg_color))

        if not canvas._page_pixmaps:
            p.setPen(QColor(TEXT_SEC))
            f = QFont(); f.setPointSize(11); p.setFont(f)
            p.drawText(canvas.rect(), Qt.AlignmentFlag.AlignCenter, t("edit.open_prompt"))
            return

        # 1. Render pages
        for i, qpix in enumerate(canvas._page_pixmaps):
            yo, pw, ph = canvas._page_offsets[i]
            page_r = QRect(0, yo, pw, ph)
            if qpix is not None:
                p.drawPixmap(0, yo, qpix)
            elif i < len(canvas._page_prev_pixmaps) and canvas._page_prev_pixmaps[i] is not None:
                p.save()
                p.drawPixmap(page_r, canvas._page_prev_pixmaps[i])
                p.restore()
            else:
                p.fillRect(page_r, QColor("#FFFFFF"))
                p.setPen(QColor(TEXT_SEC))
                f = QFont(); f.setPointSize(9); p.setFont(f)
                p.drawText(page_r, Qt.AlignmentFlag.AlignCenter, f"⏳ {i+1}")
                p.setPen(QColor("#E0E0E0"))
                p.drawRect(QRect(0, yo, pw - 1, ph - 1))

        # 2. Render overlays
        z = canvas._zoom
        for ov_idx, e in enumerate(canvas._overlays):
            pg = e.get("page", 0)
            if pg >= len(canvas._page_offsets):
                continue
            yo = canvas._page_offsets[pg][0]
            etype = e["type"]
            is_selected = (ov_idx == canvas._selected_overlay_idx)

            # Cleanly cover deleted items on canvas with white fill
            if e.get("_deleted"):
                orig_r = e.get("_orig_rect") or e.get("bbox") or e.get("rect")
                if orig_r:
                    if isinstance(orig_r, (list, tuple)):
                        qr = QRect(int(orig_r[0] * z) - 1, yo + int(orig_r[1] * z) - 1,
                                   max(1, int((orig_r[2] - orig_r[0]) * z)) + 2,
                                   max(1, int((orig_r[3] - orig_r[1]) * z)) + 2)
                    else:
                        qr = QRect(int(orig_r.x0 * z) - 1, yo + int(orig_r.y0 * z) - 1,
                                   max(1, int(orig_r.width * z)) + 2,
                                   max(1, int(orig_r.height * z)) + 2)
                    p.fillRect(qr, QColor("#FFFFFF"))
                continue

            if etype == "redact":
                r = e["rect"]; fill = e["fill"]
                qr = QRect(int(r.x0*z), yo+int(r.y0*z), max(1,int(r.width*z)), max(1,int(r.height*z)))
                p.fillRect(qr, QColor(int(fill[0]*255), int(fill[1]*255), int(fill[2]*255), 210))
                p.setPen(QPen(QColor("#EF4444"), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(qr)

            elif etype == "check":
                r = e["rect"]
                sx0 = int(r.x0 * z)
                sy0 = yo + int(r.y0 * z)
                sw = max(4, int(r.width * z))
                sh = max(4, int(r.height * z))
                c = e.get("color", (0, 0, 0))
                col = QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255))
                stroke_w = max(1.5, float(e.get("width", min(sw, sh) * 0.12)))
                pen = QPen(col, stroke_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p1 = QPointF(sx0 + 0.16 * sw, sy0 + 0.52 * sh)
                p2 = QPointF(sx0 + 0.40 * sw, sy0 + 0.82 * sh)
                p3 = QPointF(sx0 + 0.86 * sw, sy0 + 0.18 * sh)
                check_path = QPainterPath()
                check_path.moveTo(p1)
                check_path.lineTo(p2)
                check_path.lineTo(p3)
                p.drawPath(check_path)

                if is_selected:
                    p.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
                    p.drawRect(QRect(sx0 - 2, sy0 - 2, sw + 4, sh + 4))
                    hs = 8
                    p.setBrush(QColor("#FFFFFF"))
                    p.setPen(QPen(QColor(ACCENT), 1.5))
                    for hpt in [
                        QPoint(sx0 - 2, sy0 - 2),
                        QPoint(sx0 + sw + 2, sy0 - 2),
                        QPoint(sx0 - 2, sy0 + sh + 2),
                        QPoint(sx0 + sw + 2, sy0 + sh + 2),
                    ]:
                        p.drawRect(QRect(hpt.x() - hs//2, hpt.y() - hs//2, hs, hs))

            elif etype == "cross":
                r = e["rect"]
                sx0 = int(r.x0 * z)
                sy0 = yo + int(r.y0 * z)
                sw = max(4, int(r.width * z))
                sh = max(4, int(r.height * z))
                c = e.get("color", (0, 0, 0))
                col = QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255))
                stroke_w = max(1.5, float(e.get("width", min(sw, sh) * 0.12)))
                pen = QPen(col, stroke_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawLine(QPointF(sx0 + 0.20 * sw, sy0 + 0.20 * sh), QPointF(sx0 + 0.80 * sw, sy0 + 0.80 * sh))
                p.drawLine(QPointF(sx0 + 0.80 * sw, sy0 + 0.20 * sh), QPointF(sx0 + 0.20 * sw, sy0 + 0.80 * sh))

                if is_selected:
                    p.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
                    p.drawRect(QRect(sx0 - 2, sy0 - 2, sw + 4, sh + 4))
                    hs = 8
                    p.setBrush(QColor("#FFFFFF"))
                    p.setPen(QPen(QColor(ACCENT), 1.5))
                    for hpt in [
                        QPoint(sx0 - 2, sy0 - 2),
                        QPoint(sx0 + sw + 2, sy0 - 2),
                        QPoint(sx0 - 2, sy0 + sh + 2),
                        QPoint(sx0 + sw + 2, sy0 + sh + 2),
                    ]:
                        p.drawRect(QRect(hpt.x() - hs//2, hpt.y() - hs//2, hs, hs))

            elif etype == "highlight":
                c = e.get("color", (1, 1, 0))
                col = QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255), 120)
                rects = e.get("rects")
                if rects:
                    for r_item in rects:
                        qr = QRect(int(r_item.x0*z), yo+int(r_item.y0*z), max(1,int(r_item.width*z)), max(1,int(r_item.height*z)))
                        p.fillRect(qr, col)
                elif "rect" in e:
                    r = e["rect"]
                    qr = QRect(int(r.x0*z), yo+int(r.y0*z), max(1,int(r.width*z)), max(1,int(r.height*z)))
                    p.fillRect(qr, col)

            elif etype == "text":
                pt = e["point"]; c = e["color"]
                p.setPen(QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255)))
                fname = e.get("font", "Helvetica")
                f2 = QFont(fname)
                f2.setPointSizeF(max(4.0, float(e.get("size", 12)) * z * 0.75))
                flags = int(e.get("flags", 0) or 0)
                if (flags & 16) or "bold" in fname.lower():
                    f2.setBold(True)
                if (flags & 2) or "italic" in fname.lower() or "oblique" in fname.lower():
                    f2.setItalic(True)
                p.setFont(f2)
                p.drawText(int(pt.x*z), yo+int(pt.y*z), e["text"])

                if is_selected:
                    r = e.get("rect")
                    if not r:
                        sz = float(e.get("size", 12))
                        tw = max(16.0, len(e.get("text", "")) * sz * 0.65)
                        r = fitz.Rect(pt.x, pt.y - sz * 0.85, pt.x + tw, pt.y + sz * 0.25)
                        e["rect"] = r
                    qr = QRect(int(r.x0*z) - 2, yo+int(r.y0*z) - 2, max(1,int(r.width*z)) + 4, max(1,int(r.height*z)) + 4)
                    p.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(qr)

                    hs = 8
                    p.setBrush(QColor("#FFFFFF"))
                    p.setPen(QPen(QColor(ACCENT), 1.5))
                    for hpt in [
                        QPoint(qr.left(), qr.top()),
                        QPoint(qr.right(), qr.top()),
                        QPoint(qr.left(), qr.bottom()),
                        QPoint(qr.right(), qr.bottom()),
                    ]:
                        p.drawRect(QRect(hpt.x() - hs//2, hpt.y() - hs//2, hs, hs))

            elif etype in ("image", "signature"):
                r = e["rect"]
                qr = QRect(int(r.x0*z), yo+int(r.y0*z), max(1,int(r.width*z)), max(1,int(r.height*z)))
                path = e["path"]
                try:
                    mtime = os.path.getmtime(path)
                    img_px = _load_overlay_pixmap(path, mtime)
                except OSError:
                    img_px = QPixmap(path)
                if not img_px.isNull():
                    p.drawPixmap(qr, img_px)

                if is_selected:
                    border_col = ACCENT
                    p.setPen(QPen(QColor(border_col), 2, Qt.PenStyle.DashLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(qr)

                    hs = 10
                    p.setBrush(QColor("#FFFFFF"))
                    p.setPen(QPen(QColor(border_col), 2))
                    for hpt in [
                        QPoint(qr.left(), qr.top()),
                        QPoint(qr.right(), qr.top()),
                        QPoint(qr.left(), qr.bottom()),
                        QPoint(qr.right(), qr.bottom()),
                    ]:
                        p.drawRect(QRect(hpt.x() - hs//2, hpt.y() - hs//2, hs, hs))

            elif etype == "text_edit":
                r = e["bbox"]
                qr = QRect(int(r[0]*z) - 1, yo+int(r[1]*z) - 1,
                           max(1, int((r[2]-r[0])*z)) + 2, max(1, int((r[3]-r[1])*z)) + 2)

                p.fillRect(qr, QColor("#FFFFFF"))
                new_txt = e.get("new_text", "")
                if new_txt:
                    c = e.get("color", 0)
                    if isinstance(c, int):
                        col = QColor((c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF)
                    elif isinstance(c, (list, tuple)) and len(c) >= 3:
                        col = QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255))
                    else:
                        col = QColor("#000000")
                    p.setPen(col)

                    fname = e.get("font", "Helvetica")
                    fnt = QFont(fname)
                    sz = float(e.get("font_size", e.get("size", 12)))
                    fnt.setPointSizeF(max(4.0, sz * z * 0.75))
                    flags = int(e.get("flags", 0) or 0)
                    if (flags & 16) or "bold" in fname.lower():
                        fnt.setBold(True)
                    if (flags & 2) or "italic" in fname.lower() or "oblique" in fname.lower():
                        fnt.setItalic(True)
                    p.setFont(fnt)

                    origin = e.get("origin", [r[0], r[3]])
                    baseline_x = int(origin[0] * z)
                    baseline_y = yo + int(origin[1] * z)
                    p.drawText(baseline_x, baseline_y, new_txt)

                if is_selected:
                    p.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(qr)

                    hs = 8
                    p.setBrush(QColor("#FFFFFF"))
                    p.setPen(QPen(QColor(ACCENT), 1.5))
                    for hpt in [
                        QPoint(qr.left(), qr.top()),
                        QPoint(qr.right(), qr.top()),
                        QPoint(qr.left(), qr.bottom()),
                        QPoint(qr.right(), qr.bottom()),
                    ]:
                        p.drawRect(QRect(hpt.x() - hs//2, hpt.y() - hs//2, hs, hs))

            elif etype == "note":
                pt = e["point"]
                px, py = int(pt.x*z), yo+int(pt.y*z)
                note_idx = ov_idx
                icon_r = QRect(px, py - _NOTE_ICON_SIZE, _NOTE_ICON_SIZE, _NOTE_ICON_SIZE)
                p.setBrush(QColor("#FBBF24")); p.setPen(QPen(QColor("#D97706"), 1))
                p.drawRoundedRect(icon_r, 4, 4)
                fi = QFont(); fi.setPointSize(10); fi.setBold(True); p.setFont(fi)
                p.setPen(QColor("#1C1917")); p.drawText(icon_r, Qt.AlignmentFlag.AlignCenter, "\u270e")
                if canvas._open_note == note_idx:
                    bx = px + _NOTE_ICON_SIZE + 6
                    by = py - _NOTE_ICON_SIZE - 4
                    ft = QFont(); ft.setPointSize(9); p.setFont(ft)
                    fm = p.fontMetrics()
                    lines = e["text"].split("\n")
                    tw = max(fm.horizontalAdvance(ln) for ln in lines) + 20
                    th = fm.height() * len(lines) + 16
                    bw, bh = max(120, min(tw, 260)), max(32, th)
                    br = QRect(bx, by, bw, bh)
                    p.setBrush(QColor(0,0,0,30)); p.setPen(Qt.PenStyle.NoPen)
                    p.drawRoundedRect(QRect(bx+2, by+2, bw, bh), 6, 6)
                    p.setBrush(QColor("#FFFDF5")); p.setPen(QPen(QColor("#D97706"), 1))
                    p.drawRoundedRect(br, 6, 6)
                    p.setPen(QColor("#000000"))
                    p.drawText(QRect(bx+10, by+8, bw-20, bh-16),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                               e["text"])

            elif etype == "draw":
                pts = e.get("points", [])
                if len(pts) >= 2:
                    col = e.get("color", (1, 0, 0))
                    w = max(1, int(e.get("width", 2)))
                    pen = QPen(QColor(int(col[0]*255), int(col[1]*255), int(col[2]*255)),
                               max(1, int(w * z)))
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    p.setPen(pen)
                    p.setBrush(Qt.BrushStyle.NoBrush)

                    path = QPainterPath()
                    p0 = (pts[0][0] * z, yo + pts[0][1] * z)
                    path.moveTo(p0[0], p0[1])
                    if len(pts) == 2:
                        p1 = (pts[1][0] * z, yo + pts[1][1] * z)
                        path.lineTo(p1[0], p1[1])
                    else:
                        for i in range(1, len(pts) - 1):
                            cur = (pts[i][0] * z, yo + pts[i][1] * z)
                            nxt = (pts[i + 1][0] * z, yo + pts[i + 1][1] * z)
                            mid_x = (cur[0] + nxt[0]) / 2.0
                            mid_y = (cur[1] + nxt[1]) / 2.0
                            path.quadTo(cur[0], cur[1], mid_x, mid_y)
                        p_last = (pts[-1][0] * z, yo + pts[-1][1] * z)
                        path.lineTo(p_last[0], p_last[1])
                    p.drawPath(path)

        # 3. Interactive signature follow preview
        if canvas._placing_signature and canvas._sig_cursor_pos and canvas._placing_sig_pixmap:
            pos = canvas._sig_cursor_pos
            pix = canvas._placing_sig_pixmap
            if not pix.isNull():
                aspect = (pix.height() / pix.width()) if pix.width() > 0 else 0.35
                pw = max(40, int(160 * z))
                ph = max(20, int(pw * aspect))
                preview_r = QRect(pos.x() - pw//2, pos.y() - ph//2, pw, ph)
                p.save()
                p.setOpacity(0.75)
                p.drawPixmap(preview_r, pix)
                p.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(preview_r)
                p.restore()

        # 4. Interactive check/cross vector stamp placement follow preview
        if getattr(canvas, "_placing_stamp", False) and getattr(canvas, "_stamp_cursor_pos", None):
            pos = canvas._stamp_cursor_pos
            st_size = getattr(canvas, "_stamp_size", 20.0) * z
            sw = max(8, int(st_size))
            sh = sw
            sx0 = pos.x() - sw // 2
            sy0 = pos.y() - sh // 2
            c_val = getattr(canvas, "_stamp_color", (0, 0, 0))
            col = QColor(int(c_val[0]*255), int(c_val[1]*255), int(c_val[2]*255))
            stroke_w = max(1.5, sw * 0.12)
            pen = QPen(col, stroke_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.save()
            p.setOpacity(0.85)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            st_type = getattr(canvas, "_placing_stamp_type", "check")
            if st_type == "check":
                p1 = QPointF(sx0 + 0.16 * sw, sy0 + 0.52 * sh)
                p2 = QPointF(sx0 + 0.40 * sw, sy0 + 0.82 * sh)
                p3 = QPointF(sx0 + 0.86 * sw, sy0 + 0.18 * sh)
                cp = QPainterPath()
                cp.moveTo(p1); cp.lineTo(p2); cp.lineTo(p3)
                p.drawPath(cp)
            else:
                p.drawLine(QPointF(sx0 + 0.20 * sw, sy0 + 0.20 * sh), QPointF(sx0 + 0.80 * sw, sy0 + 0.80 * sh))
                p.drawLine(QPointF(sx0 + 0.80 * sw, sy0 + 0.20 * sh), QPointF(sx0 + 0.20 * sw, sy0 + 0.80 * sh))
            p.setPen(QPen(QColor(ACCENT), 1.0, Qt.PenStyle.DashLine))
            p.drawRect(QRect(sx0 - 2, sy0 - 2, sw + 4, sh + 4))
            p.restore()

        # 5. Interactive smoothed freehand stroke preview
        if canvas._draw_mode and canvas._current_stroke and len(canvas._current_stroke) >= 2:
            col = canvas._draw_color
            pen = QPen(QColor(int(col[0]*255), int(col[1]*255), int(col[2]*255)),
                       max(1, int(canvas._draw_width * canvas._zoom)))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)

            pts = canvas._current_stroke
            path = QPainterPath()
            path.moveTo(pts[0][0], pts[0][1])
            if len(pts) == 2:
                path.lineTo(pts[1][0], pts[1][1])
            else:
                for i in range(1, len(pts) - 1):
                    mid_x = (pts[i][0] + pts[i + 1][0]) / 2.0
                    mid_y = (pts[i][1] + pts[i + 1][1]) / 2.0
                    path.quadTo(pts[i][0], pts[i][1], mid_x, mid_y)
                path.lineTo(pts[-1][0], pts[-1][1])
            p.drawPath(path)

        # 6. Drag selection rectangle
        if canvas._drag_rect:
            if canvas._select_mode:
                p.setPen(QPen(QColor("#3B82F6"), 2, Qt.PenStyle.SolidLine))
                p.setBrush(QColor(59, 130, 246, 50))
                p.drawRect(canvas._drag_rect)
            elif getattr(canvas, "_highlight_mode", False):
                hi_c = getattr(canvas, "_highlight_color", (1.0, 1.0, 0.0))
                col_border = QColor(int(hi_c[0]*255), int(hi_c[1]*255), int(hi_c[2]*255), 230)
                col_fill = QColor(int(hi_c[0]*255), int(hi_c[1]*255), int(hi_c[2]*255), 90)
                p.setPen(QPen(col_border, 1.5, Qt.PenStyle.SolidLine))
                p.setBrush(col_fill)
                p.drawRect(canvas._drag_rect)
            else:
                p.setPen(QPen(QColor("#EF4444"), 2, Qt.PenStyle.DashLine))
                p.setBrush(QColor(239, 68, 68, 50))
                p.drawRect(canvas._drag_rect)

        # 7. Active persistent selection rectangle in Select mode (Foxit style)
        if getattr(canvas, "_select_mode", False) and getattr(canvas, "_active_sel_rect", None) and not canvas._drag_rect:
            sel_r = canvas._active_sel_rect
            sel_pg = getattr(canvas, "_active_sel_page", 0)
            if 0 <= sel_pg < len(canvas._page_offsets):
                yo = canvas._page_offsets[sel_pg][0]
                sx0 = int(sel_r.x0 * z)
                sy0 = yo + int(sel_r.y0 * z)
                sw = max(1, int(sel_r.width * z))
                sh = max(1, int(sel_r.height * z))
                qr = QRect(sx0, sy0, sw, sh)
                p.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
                p.setBrush(QColor(59, 130, 246, 35))
                p.drawRect(qr)

                hs = 8
                p.setBrush(QColor("#FFFFFF"))
                p.setPen(QPen(QColor(ACCENT), 1.5))
                for hpt in [
                    QPoint(qr.left(), qr.top()),
                    QPoint(qr.right(), qr.top()),
                    QPoint(qr.left(), qr.bottom()),
                    QPoint(qr.right(), qr.bottom()),
                ]:
                    p.drawRect(QRect(hpt.x() - hs//2, hpt.y() - hs//2, hs, hs))