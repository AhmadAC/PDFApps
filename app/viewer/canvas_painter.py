"""PDFApps – Painting subsystem for _SelectCanvas."""
from __future__ import annotations

from typing import TYPE_CHECKING
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

from app.constants import ACCENT, TEXT_SEC
from app.i18n import t
from app.viewer.canvas_worker import _NOTE_ICON_SIZE

if TYPE_CHECKING:
    from app.viewer.canvas_1 import _SelectCanvas


class CanvasPainter:
    """Renders pages, annotations, search highlights, selection rects, crop, and page numbers overlay."""

    @staticmethod
    def draw_crop_box(p: QPainter, zoom: float, px: int, py: int, pw: int, ph: int,
                      cx0: int, cy0: int, cx1: int, cy1: int):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        if cy0 > py:
            p.drawRect(px, py, pw, cy0 - py)
        if cy1 < py + ph:
            p.drawRect(px, cy1, pw, py + ph - cy1)
        if cx0 > px:
            p.drawRect(px, cy0, cx0 - px, cy1 - cy0)
        if cx1 < px + pw:
            p.drawRect(cx1, cy0, px + pw - cx1, cy1 - cy0)

        p.setPen(QPen(QColor(ACCENT), 2, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(cx0, cy0, max(1, cx1 - cx0), max(1, cy1 - cy0))

        k = 14
        p.setPen(QPen(QColor(ACCENT), 3, Qt.PenStyle.SolidLine))
        p.drawLine(cx0, cy0, cx0 + k, cy0)
        p.drawLine(cx0, cy0, cx0, cy0 + k)
        p.drawLine(cx1, cy0, cx1 - k, cy0)
        p.drawLine(cx1, cy0, cx1, cy0 + k)
        p.drawLine(cx0, cy1, cx0 + k, cy1)
        p.drawLine(cx0, cy1, cx0, cy1 - k)
        p.drawLine(cx1, cy1, cx1 - k, cy1)
        p.drawLine(cx1, cy1, cx1 - k, cy1)

        z = zoom or 1.0
        pt_w = int(round((cx1 - cx0) / z))
        pt_h = int(round((cy1 - cy0) / z))
        if pt_w > 20 and pt_h > 20:
            tag = f"{pt_w} × {pt_h} pt"
            f = QFont("Segoe UI", 9, QFont.Weight.Bold)
            p.setFont(f)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(tag) + 12
            th = fm.height() + 6
            badge_x = cx0 + 6
            badge_y = cy0 + 6
            p.setPen(Qt.PenStyle.NoPen)
            badge_col = QColor(ACCENT)
            badge_col.setAlpha(220)
            p.setBrush(badge_col)
            p.drawRoundedRect(QRect(badge_x, badge_y, tw, th), 4, 4)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(QRect(badge_x, badge_y, tw, th), Qt.AlignmentFlag.AlignCenter, tag)

    @classmethod
    def paint(cls, canvas: _SelectCanvas, _event):
        p = QPainter(canvas)
        p.fillRect(canvas.rect(), QColor(canvas._bg_color))

        if not canvas._entries:
            p.setPen(QColor(TEXT_SEC))
            f = QFont()
            f.setPointSize(11)
            p.setFont(f)
            p.drawText(canvas.rect(), Qt.AlignmentFlag.AlignCenter, t("viewer.open_prompt"))
            return

        first, last = canvas._visible_range()
        for i in range(first, last + 1):
            e = canvas._entries[i]
            x = (max(canvas.width(), e.w) - e.w) // 2 if canvas.width() > e.w else 0
            if e.pixmap:
                p.drawPixmap(x, e.y_off, e.pixmap)
            else:
                p.fillRect(x, e.y_off, e.w, e.h, QColor("#2B2B2B"))
                p.setPen(QColor(TEXT_SEC))
                f = QFont()
                f.setPointSize(9)
                p.setFont(f)
                p.drawText(QRect(x, e.y_off, e.w, e.h), Qt.AlignmentFlag.AlignCenter, t("viewer.loading"))
            p.setPen(QPen(QColor("#151515"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(x, e.y_off, e.w - 1, e.h - 1)

        # Note icons
        z = canvas._zoom
        for page_idx in range(first, last + 1):
            entry = canvas._entries[page_idx]
            if not entry.annots:
                continue
            for annot_idx, (rect, txt) in enumerate(entry.annots):
                px = int(rect.x0 * z)
                py = entry.y_off + int(rect.y0 * z)
                icon_r = QRect(px, py, _NOTE_ICON_SIZE, _NOTE_ICON_SIZE)
                p.setBrush(QColor("#FBBF24"))
                p.setPen(QPen(QColor("#D97706"), 1))
                p.drawRoundedRect(icon_r, 4, 4)
                fi = QFont()
                fi.setPointSize(10)
                fi.setBold(True)
                p.setFont(fi)
                p.setPen(QColor("#1C1917"))
                p.drawText(icon_r, Qt.AlignmentFlag.AlignCenter, "✎")
                if canvas._open_note == (page_idx, annot_idx):
                    balloon_x = px + _NOTE_ICON_SIZE + 6
                    balloon_y = py
                    ft = QFont()
                    ft.setPointSize(9)
                    p.setFont(ft)
                    fm = p.fontMetrics()
                    lines = txt.split("\n")
                    text_w = max(fm.horizontalAdvance(ln) for ln in lines) + 20
                    text_h = fm.height() * len(lines) + 16
                    balloon_w = max(140, min(text_w, 300))
                    balloon_h = max(36, text_h)
                    balloon_r = QRect(balloon_x, balloon_y, balloon_w, balloon_h)
                    shadow_r = QRect(balloon_x + 2, balloon_y + 2, balloon_w, balloon_h)
                    p.setBrush(QColor(0, 0, 0, 40))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawRoundedRect(shadow_r, 6, 6)
                    p.setBrush(QColor("#2B2B2B"))
                    p.setPen(QPen(QColor(ACCENT), 1))
                    p.drawRoundedRect(balloon_r, 6, 6)
                    p.setPen(QColor("#F0F0F0"))
                    text_rect = QRect(balloon_x + 10, balloon_y + 8, balloon_w - 20, balloon_h - 16)
                    p.drawText(
                        text_rect,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                        txt,
                    )

        # Search highlights
        for hi_idx, (pg_idx, fr) in enumerate(canvas._search_highlights):
            if pg_idx < first or pg_idx > last:
                continue
            ey = canvas._entries[pg_idx].y_off
            rx = int(fr.x0 * z)
            ry = ey + int(fr.y0 * z)
            rw = int((fr.x1 - fr.x0) * z)
            rh = int((fr.y1 - fr.y0) * z)
            if hi_idx == canvas._search_current:
                p.fillRect(rx, ry, rw, rh, QColor(0, 120, 212, 160))
                p.setPen(QPen(QColor("#60A5FA"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(rx, ry, rw, rh)
            else:
                p.fillRect(rx, ry, rw, rh, QColor(250, 204, 21, 100))

        # Selection
        for r in canvas._sel_rects:
            p.fillRect(r, QColor(0, 120, 212, 100))

        # Crop preview
        if (canvas._crop_mode and canvas._crop_drag_start and canvas._crop_drag_cur
                and 0 <= canvas._crop_active_page < len(canvas._entries)):
            i = canvas._crop_active_page
            e = canvas._entries[i]
            x = (max(canvas.width(), e.w) - e.w) // 2 if canvas.width() > e.w else 0
            start = canvas._crop_drag_start
            cur = canvas._crop_drag_cur
            cx0 = max(x, min(start.x(), cur.x()))
            cy0 = max(e.y_off, min(start.y(), cur.y()))
            cx1 = min(x + e.w, max(start.x(), cur.x()))
            cy1 = min(e.y_off + e.h, max(start.y(), cur.y()))
            cls.draw_crop_box(p, canvas._zoom, x, e.y_off, e.w, e.h, cx0, cy0, cx1, cy1)
        elif canvas._crop_preview:
            margins = canvas._crop_preview.get("margins", (0, 0, 0, 0))
            targets = canvas._crop_preview.get("targets")
            top_m, bot_m, left_m, right_m = margins
            if any(m > 0 for m in margins):
                for i in range(first, last + 1):
                    if targets is not None and i not in targets:
                        continue
                    e = canvas._entries[i]
                    x = (max(canvas.width(), e.w) - e.w) // 2 if canvas.width() > e.w else 0
                    cx0 = x + int(round(left_m * z))
                    cy0 = e.y_off + int(round(top_m * z))
                    cx1 = x + e.w - int(round(right_m * z))
                    cy1 = e.y_off + e.h - int(round(bot_m * z))
                    if cx1 > cx0 and cy1 > cy0:
                        cls.draw_crop_box(p, canvas._zoom, x, e.y_off, e.w, e.h, cx0, cy0, cx1, cy1)

        # Page numbers live preview
        np = getattr(canvas, "_numbers_preview", None)
        if np:
            targets = np.get("targets", {})
            pos_code = np.get("pos_code", "bc")
            font_size = np.get("font_size", 10)
            margin = max(18.0, (font_size + 8.0)) * z
            screen_font_size = max(7, int(font_size * z))
            font = QFont("Segoe UI", screen_font_size, QFont.Weight.Bold)
            p.setFont(font)
            fm = p.fontMetrics()

            for i in range(first, last + 1):
                if i not in targets:
                    continue
                label = targets[i]
                e = canvas._entries[i]
                x_page = (max(canvas.width(), e.w) - e.w) // 2 if canvas.width() > e.w else 0
                tw = fm.horizontalAdvance(label)
                th = fm.height()

                if pos_code[0] == "t":
                    y_baseline = e.y_off + margin
                else:
                    y_baseline = e.y_off + e.h - margin

                if pos_code[1] == "l":
                    x = x_page + margin
                elif pos_code[1] == "c":
                    x = x_page + (e.w - tw) / 2
                else:
                    x = x_page + e.w - margin - tw

                badge_pad_x = 6
                badge_pad_y = 3
                badge_rect = QRect(int(x - badge_pad_x), int(y_baseline - th + badge_pad_y * 2),
                                   int(tw + badge_pad_x * 2), int(th + badge_pad_y * 2))

                p.setPen(Qt.PenStyle.NoPen)
                badge_bg = QColor(ACCENT)
                badge_bg.setAlpha(60)
                p.setBrush(badge_bg)
                p.drawRoundedRect(badge_rect, 4, 4)

                p.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
                p.drawRoundedRect(badge_rect, 4, 4)

                p.setPen(QColor(ACCENT))
                p.drawText(int(x), int(y_baseline), label)

