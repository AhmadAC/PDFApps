# app/editor/canvas_text1.py

"""Inline text editor controller for Foxit-style in-place editing & insertion."""

from __future__ import annotations

import fitz
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLineEdit

from app.constants import ACCENT


class CanvasInlineTextManager:
    def __init__(self, canvas):
        self.canvas = canvas
        self.edit = QLineEdit(canvas)
        self.edit.hide()
        self.edit.installEventFilter(canvas)
        self.edit.returnPressed.connect(self.commit)

        self.mode: str | None = None
        self.span: dict | None = None
        self.page_idx: int = -1
        self.original_text: str = ""
        self.insert_point: tuple[float, float] | None = None
        self.insert_size: float = 12.0
        self.insert_color: tuple = (0.0, 0.0, 0.0)
        self.insert_font: str = "Helvetica"
        self.insert_flags: int = 0

    def begin_edit(self, span: dict, page_idx: int):
        if self.edit.isVisible():
            self.commit()
        self.mode = "edit"
        self.span = dict(span)
        self.page_idx = page_idx
        self.original_text = span.get("text", "")
        self.edit.setText(self.original_text)

        bb = span["bbox"]
        visual_size = max(float(span.get("size") or 0), float(bb[3] - bb[1]))
        font_name = span.get("font", "Helvetica")
        flags = int(span.get("flags", 0) or 0)
        c = span.get("color", 0)
        if isinstance(c, int):
            color = (((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0)
        elif isinstance(c, (list, tuple)) and len(c) >= 3:
            color = (float(c[0]), float(c[1]), float(c[2]))
        else:
            color = (0.0, 0.0, 0.0)

        self._style_inline_edit(self.span)
        self.reposition()
        self.edit.show()
        self.edit.raise_()
        self.edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self.edit.selectAll()

        self.canvas.text_edit_started.emit({
            "font": font_name,
            "size": visual_size,
            "color": color,
            "bold": bool(flags & 16),
            "italic": bool(flags & 2),
            "text": self.original_text,
        })

    def begin_insert(self, page_idx: int, pdf_point, size: float, color: tuple, font: str = ""):
        if self.edit.isVisible():
            self.commit()
        self.mode = "insert"
        self.span = None
        self.page_idx = page_idx
        self.original_text = ""
        self.insert_point = (float(pdf_point.x), float(pdf_point.y))
        self.insert_size = float(size)
        self.insert_color = tuple(color)
        self.insert_font = font or "Helvetica"
        self.insert_flags = 0
        self.edit.setText("")
        self._style_inline_insert()
        self.reposition()
        self.edit.show()
        self.edit.raise_()
        self.edit.setFocus(Qt.FocusReason.OtherFocusReason)

        self.canvas.text_edit_started.emit({
            "font": self.insert_font,
            "size": self.insert_size,
            "color": self.insert_color,
            "bold": False,
            "italic": False,
            "text": "",
        })

    def update_format(self, font: str, size: float, color: tuple, bold: bool, italic: bool):
        flags = (16 if bold else 0) | (2 if italic else 0)
        c = self.canvas
        if self.mode == "edit" and self.span is not None:
            self.span["font"] = font
            self.span["size"] = size
            self.span["color"] = color
            self.span["flags"] = flags
            self._style_inline_edit(self.span)
            self.reposition()
            c.update()
        elif self.mode == "insert":
            self.insert_font = font
            self.insert_size = size
            self.insert_color = color
            self.insert_flags = flags
            self._style_inline_insert()
            self.reposition()
            c.update()
        elif 0 <= c._selected_overlay_idx < len(c._overlays):
            ov = c._overlays[c._selected_overlay_idx]
            if ov.get("type") == "text_edit":
                ov["font"] = font
                ov["font_size"] = size
                ov["size"] = size
                ov["color"] = color
                ov["flags"] = flags
                ov["_font_changed"] = True
                c.overlay_changed.emit()
                c.update()
            elif ov.get("type") == "text":
                ov["font"] = font
                ov["size"] = size
                ov["color"] = color
                c.overlay_changed.emit()
                c.update()

    def _style_inline_insert(self):
        family = self._resolve_font_family(self.insert_font)
        fnt = QFont(family)
        fnt.setPointSizeF(max(4.0, self.insert_size * self.canvas._zoom * 0.75))
        if self.insert_flags & 16:
            fnt.setBold(True)
        if self.insert_flags & 2:
            fnt.setItalic(True)
        self.edit.setFont(fnt)
        c = self.insert_color
        r, g, b = int(c[0]*255), int(c[1]*255), int(c[2]*255)
        self.edit.setStyleSheet(
            f"QLineEdit {{ background: #FFFFFF; color: #{r:02x}{g:02x}{b:02x};"
            f" border: 1.5px solid {ACCENT}; border-radius: 2px; padding: 1px 3px; }}")

    def _style_inline_edit(self, span: dict):
        bb = span["bbox"]
        visual_size = max(float(span.get("size") or 0), float(bb[3] - bb[1]))
        family = self._resolve_font_family(span.get("font", ""))
        fnt = QFont(family)
        fnt.setPointSizeF(max(4.0, visual_size * self.canvas._zoom * 0.75))
        flags = int(span.get("flags", 0) or 0)
        fname = span.get("font", "").lower()
        if (flags & 16) or "bold" in fname:
            fnt.setBold(True)
        if (flags & 2) or "italic" in fname or "oblique" in fname:
            fnt.setItalic(True)
        self.edit.setFont(fnt)

        c = span.get("color", 0)
        if isinstance(c, int):
            r, g, b = (c >> 16) & 0xFF, (c >> 8) & 0xFF, c & 0xFF
        elif isinstance(c, (list, tuple)) and len(c) >= 3:
            r, g, b = int(c[0]*255), int(c[1]*255), int(c[2]*255)
        else:
            r, g, b = 0, 0, 0
        self.edit.setStyleSheet(
            f"QLineEdit {{ background: #FFFFFF; color: #{r:02x}{g:02x}{b:02x};"
            f" border: 1.5px solid {ACCENT}; border-radius: 2px; padding: 1px 3px; }}")

    @staticmethod
    def _resolve_font_family(fname: str) -> str:
        fn = (fname or "Helvetica").lower()
        if "times" in fn or "serif" in fn or "roman" in fn:
            return "Times New Roman"
        if "mono" in fn or "courier" in fn or "consol" in fn:
            return "Courier New"
        if "segoe" in fn:
            return "Segoe UI"
        if "georgia" in fn:
            return "Georgia"
        if "calibri" in fn:
            return "Calibri"
        return "Arial"

    def reposition(self):
        c = self.canvas
        if self.mode is None or self.page_idx < 0 or self.page_idx >= len(c._page_offsets):
            return
        z = c._zoom
        yo = c._page_offsets[self.page_idx][0]
        if self.mode == "edit" and self.span is not None:
            bb = self.span["bbox"]
            x = int(bb[0] * z) - 3
            y = yo + int(bb[1] * z) - 3
            w = max(60, int((bb[2] - bb[0]) * z) + 30)
            h = max(24, int((bb[3] - bb[1]) * z) + 6)
            self.edit.setGeometry(x, y, w, h)
        elif self.mode == "insert" and self.insert_point is not None:
            px, py = self.insert_point
            size = self.insert_size
            x = int(px * z) - 3
            y = yo + int((py - size * 0.85) * z) - 3
            w = max(120, int(size * z * 8))
            h = max(24, int(size * z * 1.4) + 6)
            self.edit.setGeometry(x, y, w, h)

    def commit(self):
        if self.mode is None or not self.edit.isVisible():
            return
        new_text = self.edit.text()
        mode = self.mode
        page_idx = self.page_idx
        span = self.span
        ipoint = self.insert_point
        isize = self.insert_size
        icolor = self.insert_color
        ifont = self.insert_font
        original = self.original_text

        self.edit.hide()
        self.mode = None
        self.span = None
        self.page_idx = -1
        self.insert_point = None
        self.original_text = ""

        if mode == "edit" and span is not None:
            if new_text == original:
                return
            bb = span["bbox"]
            visual_size = max(float(span.get("size") or 0), float(bb[3] - bb[1]))
            font_name = span.get("font", "Helvetica")
            edit = {
                "type": "text_edit",
                "page": page_idx,
                "bbox": list(bb),
                "old_text": span.get("text", ""),
                "new_text": new_text,
                "size": visual_size,
                "font_size": float(span.get("size") or visual_size),
                "color": span.get("color", 0),
                "font": font_name,
                "flags": int(span.get("flags", 0) or 0),
                "ascender": float(span.get("ascender") or 0.8),
                "descender": float(span.get("descender") or -0.2),
                "origin": list(span.get("origin", (bb[0], bb[3]))),
                "_font_changed": bool(font_name != span.get("font", "")),
            }
            self.canvas.text_edit_committed.emit(page_idx, edit)
        elif mode == "insert" and ipoint is not None:
            if not new_text.strip():
                return
            edit = {
                "type": "text",
                "page": page_idx,
                "point": fitz.Point(ipoint[0], ipoint[1]),
                "text": new_text,
                "size": isize,
                "color": icolor,
                "font": ifont,
            }
            self.canvas.text_inserted.emit(page_idx, edit)

    def cancel(self):
        self.edit.hide()
        self.mode = None
        self.span = None
        self.page_idx = -1
        self.insert_point = None
        self.original_text = ""

    def handle_event_filter(self, obj, event) -> bool:
        if obj is self.edit:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    self.cancel()
                    return True
                if event.key() == Qt.Key.Key_Tab:
                    self.commit()
                    return True
            elif event.type() == QEvent.Type.FocusOut:
                self.commit()
                return False
        return False