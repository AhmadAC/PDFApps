"""PDFApps – Annotation overlay for presentation mode (pen, highlighter, eraser, laser, type)."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from enum import IntEnum

from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, QTimer
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetricsF, QPainter, QPainterPath,
    QPainterPathStroker, QPen, QPixmap, QTransform,
)
from PySide6.QtWidgets import QApplication, QWidget
import qtawesome as qta


class ToolMode(IntEnum):
    POINTER = 0
    PEN = 1
    HIGHLIGHTER = 2
    ERASER = 3
    LASER = 4
    TYPE = 5


@dataclass
class Stroke:
    path: QPainterPath
    color: QColor
    width: int
    kind: int = ToolMode.PEN
    points: list = field(default_factory=list)


@dataclass
class TextBox:
    rect: QRectF
    text: str
    color: QColor
    font_size: float = 24.0
    id: int = 0


_PEN_WIDTH = 3
_HIGHLIGHTER_WIDTH = 18
_LASER_RADIUS = 14
_ERASER_TOL = 6
_POINT_MERGE_SQ = 4
_CURSOR_ICON_PX = 24
_OUTLINE_PAD = 2
_HANDLE_SIZE = 8.0

_OUTLINE_OFFSETS = (
    (-1, 0), (1, 0), (0, -1), (0, 1),
    (-1, -1), (1, 1), (-1, 1), (1, -1),
)


def fit_font_size(text: str, rect: QRectF, min_size: float = 8.0, max_size: float = 220.0) -> float:
    """Calculate the optimal font size so that the text fits snugly within the bounding rect."""
    if rect.width() < 16 or rect.height() < 16:
        return min_size
    lines = text.split("\n") if text else [" "]
    avail_w = max(12.0, rect.width() - 14.0)
    avail_h = max(12.0, rect.height() - 10.0)

    if not text.strip():
        # Default proportional font height when empty
        return max(min_size, min(max_size, round(rect.height() * 0.65, 1)))

    low = min_size
    high = max_size
    best = min_size

    for _ in range(12):
        mid = (low + high) / 2.0
        font = QFont("Segoe UI", int(mid))
        font.setPointSizeF(mid)
        fm = QFontMetricsF(font)

        line_h = fm.lineSpacing()
        total_h = line_h * len(lines)
        max_line_w = max((fm.horizontalAdvance(line) for line in lines), default=0.0)

        if total_h <= avail_h and max_line_w <= avail_w:
            best = mid
            low = mid + 0.5
        else:
            high = mid - 0.5

    return max(min_size, round(best, 1))


def _draw_edge_type_icon(painter: QPainter, size: int, color: QColor) -> None:
    """Draw the Microsoft Edge-style [T] icon: rounded square with serif T."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, max(1.5, size * 0.08), Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    margin = size * 0.12
    box_rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    radius = size * 0.18
    painter.drawRoundedRect(box_rect, radius, radius)

    # Serif capital 'T'
    bar_y = size * 0.32
    stem_bottom = size * 0.72
    mid_x = size * 0.5
    bar_left = size * 0.30
    bar_right = size * 0.70
    serif_len = size * 0.10

    # Top horizontal bar
    painter.drawLine(QPointF(bar_left, bar_y), QPointF(bar_right, bar_y))
    # Top serifs
    painter.drawLine(QPointF(bar_left, bar_y), QPointF(bar_left, bar_y + serif_len))
    painter.drawLine(QPointF(bar_right, bar_y), QPointF(bar_right, bar_y + serif_len))
    # Vertical stem
    painter.drawLine(QPointF(mid_x, bar_y), QPointF(mid_x, stem_bottom))
    # Bottom base serif
    base_w = size * 0.14
    painter.drawLine(QPointF(mid_x - base_w, stem_bottom), QPointF(mid_x + base_w, stem_bottom))


def _icon_with_outline(
    icon_name: str,
    fill_color: str,
    rotation: float,
    size: int,
    outline_color: str = "#000000",
) -> QPixmap:
    outer = size + _OUTLINE_PAD * 2
    result = QPixmap(outer, outer)
    result.fill(Qt.GlobalColor.transparent)

    if icon_name == "type":
        p = QPainter(result)
        for dx, dy in _OUTLINE_OFFSETS:
            p.save()
            p.translate(_OUTLINE_PAD + dx, _OUTLINE_PAD + dy)
            _draw_edge_type_icon(p, size, QColor(outline_color))
            p.restore()
        p.save()
        p.translate(_OUTLINE_PAD, _OUTLINE_PAD)
        _draw_edge_type_icon(p, size, QColor(fill_color))
        p.restore()
        p.end()
        return result

    base_pix = qta.icon(icon_name, color=fill_color).pixmap(size, size)
    outline_pix = qta.icon(icon_name, color=outline_color).pixmap(size, size)

    if rotation:
        t = QTransform()
        t.rotate(rotation)
        mode = Qt.TransformationMode.SmoothTransformation
        base_pix = base_pix.transformed(t, mode)
        outline_pix = outline_pix.transformed(t, mode)

    painter = QPainter(result)
    for dx, dy in _OUTLINE_OFFSETS:
        painter.drawPixmap(_OUTLINE_PAD + dx, _OUTLINE_PAD + dy, outline_pix)
    painter.drawPixmap(_OUTLINE_PAD, _OUTLINE_PAD, base_pix)
    painter.end()
    return result


def _cursor_for_tool(tool: ToolMode, dark: bool = True) -> QCursor:
    if tool == ToolMode.POINTER:
        return QCursor(Qt.CursorShape.ArrowCursor)
    if tool == ToolMode.LASER:
        return QCursor(Qt.CursorShape.BlankCursor)
    if tool == ToolMode.TYPE:
        icon_color = "#FFFFFF" if dark else "#000000"
        pix = _icon_with_outline("type", icon_color, 0, _CURSOR_ICON_PX)
        return QCursor(pix, _CURSOR_ICON_PX // 2, _CURSOR_ICON_PX // 2)

    icon_color = "#FFFFFF" if dark else "#000000"
    size = _CURSOR_ICON_PX

    if tool == ToolMode.PEN:
        pix = _icon_with_outline("fa5s.pen", icon_color, 90, size)
        return QCursor(pix, 2 + _OUTLINE_PAD, 2 + _OUTLINE_PAD)
    if tool == ToolMode.HIGHLIGHTER:
        pix = _icon_with_outline("fa5s.highlighter", icon_color, 90, size)
        return QCursor(pix, 2 + _OUTLINE_PAD, 2 + _OUTLINE_PAD)
    if tool == ToolMode.ERASER:
        pix = _icon_with_outline("fa5s.eraser", icon_color, 0, size)
        c = (size + _OUTLINE_PAD * 2) // 2
        return QCursor(pix, c, c)
    return QCursor(Qt.CursorShape.ArrowCursor)


class AnnotationOverlay(QWidget):
    """Transparent overlay capturing freehand drawings, text annotations, and laser pointers."""

    HANDLE_NONE = 0
    HANDLE_TL = 1
    HANDLE_TR = 2
    HANDLE_BL = 3
    HANDLE_BR = 4

    def __init__(self, parent: QWidget, dark_mode: bool):
        super().__init__(parent)
        self._dark_mode = bool(dark_mode)
        self._tool = ToolMode.POINTER
        self._pen_color = QColor("#EF4444")
        self._pen_width = _PEN_WIDTH
        self._highlighter_color = QColor(251, 191, 36, 90)
        self._highlighter_width = _HIGHLIGHTER_WIDTH

        self._strokes: dict[int, list[Stroke]] = {}
        self._text_boxes: dict[int, list[TextBox]] = {}
        self._current_stroke: Stroke | None = None
        self._current_page: int = 0
        self._laser_pos: QPoint | None = None

        # Text tool state
        self._active_box: TextBox | None = None
        self._cursor_pos: int = 0
        self._cursor_visible: bool = True
        self._drag_handle: int = self.HANDLE_NONE
        self._drag_start_pos: QPointF = QPointF()
        self._drag_start_rect: QRectF = QRectF()
        self._moving_box: bool = False

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_cursor_blink)

        # Undo / Redo stacks: list of {page_idx: {"strokes": [...], "text_boxes": [...]}}
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._apply_cursor()

    # ── Public API ────────────────────────────────────────────────────────

    def set_tool(self, tool: int) -> None:
        new_tool = ToolMode(int(tool))
        if new_tool == self._tool:
            return
        if self._active_box and not self._active_box.text.strip():
            self._remove_box(self._active_box)
        self._active_box = None
        self._blink_timer.stop()
        self._current_stroke = None
        if self._tool == ToolMode.LASER and new_tool != ToolMode.LASER:
            self._laser_pos = None
        self._tool = new_tool
        passthrough = new_tool == ToolMode.POINTER
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, passthrough)
        self._apply_cursor()
        self.update()

    def tool(self) -> int:
        return int(self._tool)

    def set_pen_color(self, color: QColor) -> None:
        c = color if isinstance(color, QColor) else QColor(color)
        if self._active_box:
            self._push_undo()
            self._active_box.color = QColor(c)
            self.update()
        if self._tool == ToolMode.HIGHLIGHTER:
            self._highlighter_color = QColor(c.red(), c.green(), c.blue(), 90)
        else:
            self._pen_color = QColor(c)

    def pen_color(self) -> QColor:
        return QColor(self._pen_color)

    def set_current_page(self, idx: int) -> None:
        if idx == self._current_page and self._current_stroke is None:
            return
        if self._active_box and not self._active_box.text.strip():
            self._remove_box(self._active_box)
        self._active_box = None
        self._blink_timer.stop()
        self._current_page = int(idx)
        self._current_stroke = None
        self._laser_pos = None
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self.update()

    def clear_current_page(self) -> None:
        if self._strokes.get(self._current_page) or self._text_boxes.get(self._current_page):
            self._push_undo()
        self._strokes.pop(self._current_page, None)
        self._text_boxes.pop(self._current_page, None)
        self._active_box = None
        self._current_stroke = None
        self._blink_timer.stop()
        self.update()

    def clear_all(self) -> None:
        self._push_undo()
        self._strokes.clear()
        self._text_boxes.clear()
        self._active_box = None
        self._current_stroke = None
        self._laser_pos = None
        self._blink_timer.stop()
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        self.update()

    def update_theme(self, dark: bool) -> None:
        self._dark_mode = bool(dark)
        self._apply_cursor()

    def set_laser_pos(self, pos: QPoint | None) -> None:
        if self._tool != ToolMode.LASER:
            return
        self._laser_pos = QPoint(pos) if pos is not None else None
        self.update()

    # ── Undo / Redo ───────────────────────────────────────────────────────

    def _push_undo(self) -> None:
        page_state = {
            "page": self._current_page,
            "strokes": copy.deepcopy(self._strokes.get(self._current_page, [])),
            "text_boxes": [
                TextBox(QRectF(b.rect), b.text, QColor(b.color), b.font_size, b.id)
                for b in self._text_boxes.get(self._current_page, [])
            ],
        }
        self._undo_stack.append(page_state)
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        current_state = {
            "page": self._current_page,
            "strokes": copy.deepcopy(self._strokes.get(self._current_page, [])),
            "text_boxes": [
                TextBox(QRectF(b.rect), b.text, QColor(b.color), b.font_size, b.id)
                for b in self._text_boxes.get(self._current_page, [])
            ],
        }
        self._redo_stack.append(current_state)
        prev = self._undo_stack.pop()
        p = prev["page"]
        self._current_page = p
        self._strokes[p] = prev["strokes"]
        self._text_boxes[p] = prev["text_boxes"]
        self._active_box = None
        self._blink_timer.stop()
        self.update()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        current_state = {
            "page": self._current_page,
            "strokes": copy.deepcopy(self._strokes.get(self._current_page, [])),
            "text_boxes": [
                TextBox(QRectF(b.rect), b.text, QColor(b.color), b.font_size, b.id)
                for b in self._text_boxes.get(self._current_page, [])
            ],
        }
        self._undo_stack.append(current_state)
        nxt = self._redo_stack.pop()
        p = nxt["page"]
        self._current_page = p
        self._strokes[p] = nxt["strokes"]
        self._text_boxes[p] = nxt["text_boxes"]
        self._active_box = None
        self._blink_timer.stop()
        self.update()
        return True

    # ── Text Box Internals ────────────────────────────────────────────────

    def _toggle_cursor_blink(self) -> None:
        self._cursor_visible = not self._cursor_visible
        if self._active_box:
            self.update(self._active_box.rect.toRect().adjusted(-8, -8, 8, 8))

    def _remove_box(self, box: TextBox) -> None:
        boxes = self._text_boxes.get(self._current_page, [])
        if box in boxes:
            boxes.remove(box)
            if not boxes:
                self._text_boxes.pop(self._current_page, None)

    def _box_handles(self, rect: QRectF) -> dict[int, QRectF]:
        s = _HANDLE_SIZE
        hs = s / 2.0
        return {
            self.HANDLE_TL: QRectF(rect.left() - hs, rect.top() - hs, s, s),
            self.HANDLE_TR: QRectF(rect.right() - hs, rect.top() - hs, s, s),
            self.HANDLE_BL: QRectF(rect.left() - hs, rect.bottom() - hs, s, s),
            self.HANDLE_BR: QRectF(rect.right() - hs, rect.bottom() - hs, s, s),
        }

    def _handle_at(self, box: TextBox, pt: QPointF) -> int:
        for h_id, h_rect in self._box_handles(box.rect).items():
            if h_rect.adjusted(-3, -3, 3, 3).contains(pt):
                return h_id
        return self.HANDLE_NONE

    def _find_box_at(self, pt: QPointF) -> TextBox | None:
        for box in reversed(self._text_boxes.get(self._current_page, [])):
            if box.rect.adjusted(-4, -4, 4, 4).contains(pt):
                return box
        return None

    # ── Cursors & Tools ───────────────────────────────────────────────────

    def _apply_cursor(self) -> None:
        if self._tool == ToolMode.POINTER:
            self.unsetCursor()
            return
        self.setCursor(_cursor_for_tool(self._tool, dark=self._dark_mode))

    def _new_stroke(self, start: QPoint) -> Stroke:
        if self._tool == ToolMode.HIGHLIGHTER:
            color = QColor(self._highlighter_color)
            width = self._highlighter_width
            kind = ToolMode.HIGHLIGHTER
        else:
            color = QColor(self._pen_color)
            width = self._pen_width
            kind = ToolMode.PEN
        path = QPainterPath()
        path.moveTo(start)
        return Stroke(path=path, color=color, width=width, kind=kind,
                      points=[QPoint(start)])

    def _erase_at(self, pos: QPoint) -> bool:
        page_strokes = self._strokes.get(self._current_page)
        hit_stroke = False
        if page_strokes:
            for i in range(len(page_strokes) - 1, -1, -1):
                s = page_strokes[i]
                stroker = QPainterPathStroker()
                stroker.setWidth(max(2, s.width) + _ERASER_TOL)
                stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
                stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                outline = stroker.createStroke(s.path)
                if outline.contains(pos):
                    self._push_undo()
                    page_strokes.pop(i)
                    if not page_strokes:
                        self._strokes.pop(self._current_page, None)
                    hit_stroke = True
                    break

        # Also erase text boxes if clicked directly with eraser
        page_boxes = self._text_boxes.get(self._current_page, [])
        for i in range(len(page_boxes) - 1, -1, -1):
            if page_boxes[i].rect.contains(pos):
                self._push_undo()
                if self._active_box is page_boxes[i]:
                    self._active_box = None
                    self._blink_timer.stop()
                page_boxes.pop(i)
                hit_stroke = True
                break

        return hit_stroke

    # ── Events ────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)
            return
        pos = e.position().toPoint()
        pos_f = QPointF(pos)

        parent = self.parentWidget()
        if parent is not None and hasattr(parent, "_show_hud"):
            parent._show_hud()

        # Handle active text box interactions
        if self._active_box is not None:
            handle = self._handle_at(self._active_box, pos_f)
            if handle != self.HANDLE_NONE:
                self._drag_handle = handle
                self._drag_start_pos = pos_f
                self._drag_start_rect = QRectF(self._active_box.rect)
                e.accept()
                return
            if self._active_box.rect.contains(pos_f):
                # Reposition cursor inside active text box
                self._cursor_pos = len(self._active_box.text)
                self._moving_box = True
                self._drag_start_pos = pos_f
                self._drag_start_rect = QRectF(self._active_box.rect)
                self.update()
                e.accept()
                return

        # Check existing text box selection in TYPE or POINTER mode
        if self._tool in (ToolMode.TYPE, ToolMode.POINTER):
            hit_box = self._find_box_at(pos_f)
            if hit_box:
                if self._active_box and not self._active_box.text.strip() and self._active_box is not hit_box:
                    self._remove_box(self._active_box)
                self._active_box = hit_box
                self._cursor_pos = len(hit_box.text)
                self._cursor_visible = True
                self._blink_timer.start()
                self._moving_box = True
                self._drag_start_pos = pos_f
                self._drag_start_rect = QRectF(hit_box.rect)
                self.update()
                e.accept()
                return

        # Clicking on empty space in TYPE mode -> create new box
        if self._tool == ToolMode.TYPE:
            if self._active_box and not self._active_box.text.strip():
                self._remove_box(self._active_box)
            self._push_undo()
            w, h = 220.0, 56.0
            new_rect = QRectF(pos_f.x(), pos_f.y(), w, h)
            # Ensure within window boundaries
            if new_rect.right() > self.width() - 10:
                new_rect.moveLeft(max(10.0, self.width() - w - 10))
            if new_rect.bottom() > self.height() - 10:
                new_rect.moveTop(max(10.0, self.height() - h - 10))

            new_box = TextBox(
                rect=new_rect,
                text="",
                color=QColor(self._pen_color),
                font_size=fit_font_size("", new_rect),
                id=int(Qt.Key.Key_T) + len(self._text_boxes.get(self._current_page, [])),
            )
            self._text_boxes.setdefault(self._current_page, []).append(new_box)
            self._active_box = new_box
            self._cursor_pos = 0
            self._cursor_visible = True
            self._blink_timer.start()
            self.setFocus()
            self.update()
            e.accept()
            return

        # Deselect active text box if clicking elsewhere
        if self._active_box is not None:
            if not self._active_box.text.strip():
                self._remove_box(self._active_box)
            self._active_box = None
            self._blink_timer.stop()
            self.update()

        if self._tool in (ToolMode.PEN, ToolMode.HIGHLIGHTER):
            self._current_stroke = self._new_stroke(pos)
            self.update()
            e.accept()
            return

        if self._tool == ToolMode.ERASER:
            if self._erase_at(pos):
                self.update()
            e.accept()
            return

        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, "_show_hud"):
            parent._show_hud()
        pos = e.position().toPoint()
        pos_f = QPointF(pos)

        # Dynamic resizing of text box
        if self._active_box and self._drag_handle != self.HANDLE_NONE:
            dx = pos_f.x() - self._drag_start_pos.x()
            dy = pos_f.y() - self._drag_start_pos.y()
            r = QRectF(self._drag_start_rect)
            min_w, min_h = 36.0, 24.0

            if self._drag_handle == self.HANDLE_BR:
                r.setRight(max(r.left() + min_w, r.right() + dx))
                r.setBottom(max(r.top() + min_h, r.bottom() + dy))
            elif self._drag_handle == self.HANDLE_BL:
                r.setLeft(min(r.right() - min_w, r.left() + dx))
                r.setBottom(max(r.top() + min_h, r.bottom() + dy))
            elif self._drag_handle == self.HANDLE_TR:
                r.setRight(max(r.left() + min_w, r.right() + dx))
                r.setTop(min(r.bottom() - min_h, r.top() + dy))
            elif self._drag_handle == self.HANDLE_TL:
                r.setLeft(min(r.right() - min_w, r.left() + dx))
                r.setTop(min(r.bottom() - min_h, r.top() + dy))

            self._active_box.rect = r
            # Auto-scale font size dynamically with box resize
            self._active_box.font_size = fit_font_size(self._active_box.text, r)
            self.update()
            e.accept()
            return

        # Moving active text box
        if self._active_box and self._moving_box and (e.buttons() & Qt.MouseButton.LeftButton):
            dx = pos_f.x() - self._drag_start_pos.x()
            dy = pos_f.y() - self._drag_start_pos.y()
            r = QRectF(self._drag_start_rect)
            r.translate(dx, dy)
            self._active_box.rect = r
            self.update()
            e.accept()
            return

        # Update hover cursor over handles or text box
        if self._active_box and self._tool in (ToolMode.TYPE, ToolMode.POINTER):
            handle = self._handle_at(self._active_box, pos_f)
            if handle in (self.HANDLE_TL, self.HANDLE_BR):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                return
            if handle in (self.HANDLE_TR, self.HANDLE_BL):
                self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                return
            if self._active_box.rect.contains(pos_f):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                return
            self._apply_cursor()

        if self._tool == ToolMode.LASER:
            self._laser_pos = pos
            self.update()
            e.accept()
            return

        if self._current_stroke is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            last = self._current_stroke.points[-1]
            dx = pos.x() - last.x()
            dy = pos.y() - last.y()
            if dx * dx + dy * dy >= _POINT_MERGE_SQ:
                self._current_stroke.path.lineTo(pos)
                self._current_stroke.points.append(QPoint(pos))
                self.update()
            e.accept()
            return

        if self._tool == ToolMode.ERASER and (e.buttons() & Qt.MouseButton.LeftButton):
            if self._erase_at(pos):
                self.update()
            e.accept()
            return

        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(e)
            return

        if self._drag_handle != self.HANDLE_NONE or self._moving_box:
            self._drag_handle = self.HANDLE_NONE
            self._moving_box = False
            self._push_undo()
            self.update()
            e.accept()
            return

        if self._current_stroke is not None:
            if len(self._current_stroke.points) >= 2:
                self._push_undo()
                self._strokes.setdefault(self._current_page, []).append(self._current_stroke)
            self._current_stroke = None
            self.update()
            e.accept()
            return

        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        key = e.key()
        modifiers = e.modifiers()

        # Global Undo/Redo shortcuts
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Z:
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    self.redo()
                else:
                    self.undo()
                e.accept()
                return
            if key == Qt.Key.Key_Y:
                self.redo()
                e.accept()
                return

        # Typing in active text box
        if self._active_box is not None:
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._push_undo()
                t = self._active_box.text
                self._active_box.text = t[:self._cursor_pos] + "\n" + t[self._cursor_pos:]
                self._cursor_pos += 1
                self._active_box.font_size = fit_font_size(self._active_box.text, self._active_box.rect)
                self._cursor_visible = True
                self.update()
                e.accept()
                return

            if key == Qt.Key.Key_Backspace:
                if self._cursor_pos > 0:
                    self._push_undo()
                    t = self._active_box.text
                    self._active_box.text = t[:self._cursor_pos - 1] + t[self._cursor_pos:]
                    self._cursor_pos -= 1
                    self._active_box.font_size = fit_font_size(self._active_box.text, self._active_box.rect)
                    self._cursor_visible = True
                    self.update()
                e.accept()
                return

            if key == Qt.Key.Key_Delete:
                t = self._active_box.text
                if self._cursor_pos < len(t):
                    self._push_undo()
                    self._active_box.text = t[:self._cursor_pos] + t[self._cursor_pos + 1:]
                    self._active_box.font_size = fit_font_size(self._active_box.text, self._active_box.rect)
                    self._cursor_visible = True
                    self.update()
                e.accept()
                return

            if key == Qt.Key.Key_Left:
                self._cursor_pos = max(0, self._cursor_pos - 1)
                self._cursor_visible = True
                self.update()
                e.accept()
                return

            if key == Qt.Key.Key_Right:
                self._cursor_pos = min(len(self._active_box.text), self._cursor_pos + 1)
                self._cursor_visible = True
                self.update()
                e.accept()
                return

            if key == Qt.Key.Key_Home:
                self._cursor_pos = 0
                self._cursor_visible = True
                self.update()
                e.accept()
                return

            if key == Qt.Key.Key_End:
                self._cursor_pos = len(self._active_box.text)
                self._cursor_visible = True
                self.update()
                e.accept()
                return

            if key == Qt.Key.Key_Escape:
                if not self._active_box.text.strip():
                    self._remove_box(self._active_box)
                self._active_box = None
                self._blink_timer.stop()
                self.update()
                e.accept()
                return

            # Clipboard paste
            if (modifiers & Qt.KeyboardModifier.ControlModifier) and key == Qt.Key.Key_V:
                clip_text = QApplication.clipboard().text()
                if clip_text:
                    self._push_undo()
                    t = self._active_box.text
                    self._active_box.text = t[:self._cursor_pos] + clip_text + t[self._cursor_pos:]
                    self._cursor_pos += len(clip_text)
                    self._active_box.font_size = fit_font_size(self._active_box.text, self._active_box.rect)
                    self._cursor_visible = True
                    self.update()
                e.accept()
                return

            # Printable characters
            char = e.text()
            if char and char.isprintable():
                self._push_undo()
                t = self._active_box.text
                self._active_box.text = t[:self._cursor_pos] + char + t[self._cursor_pos:]
                self._cursor_pos += len(char)
                self._active_box.font_size = fit_font_size(self._active_box.text, self._active_box.rect)
                self._cursor_visible = True
                self.update()
                e.accept()
                return

        super().keyPressEvent(e)

    def leaveEvent(self, e):
        if self._tool == ToolMode.LASER and self._laser_pos is not None:
            self._laser_pos = None
            self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # 1. Draw strokes
        for s in self._strokes.get(self._current_page, ()):
            pen = QPen(s.color, s.width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPath(s.path)

        if self._current_stroke is not None and len(self._current_stroke.points) >= 1:
            s = self._current_stroke
            pen = QPen(s.color, s.width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPath(s.path)

        # 2. Draw text boxes
        for box in self._text_boxes.get(self._current_page, []):
            is_active = (box is self._active_box)
            font = QFont("Segoe UI", int(box.font_size))
            font.setPointSizeF(box.font_size)
            p.setFont(font)
            fm = QFontMetricsF(font)

            # Draw text
            p.setPen(QPen(box.color))
            inner_rect = box.rect.adjusted(7, 5, -7, -5)
            p.drawText(
                inner_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                box.text,
            )

            # Active selection frame and handles
            if is_active:
                p.setPen(QPen(QColor("#14B8A6"), 1.5, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(box.rect)

                # Resize handles at 4 corners
                for h_rect in self._box_handles(box.rect).values():
                    p.setPen(QPen(QColor("#14B8A6"), 1.5))
                    p.setBrush(QColor("#FFFFFF"))
                    p.drawRect(h_rect)

                # Blinking text cursor
                if self._cursor_visible and self.hasFocus():
                    before_cursor = box.text[:self._cursor_pos]
                    lines = before_cursor.split("\n")
                    cur_line = lines[-1] if lines else ""
                    line_idx = max(0, len(lines) - 1)

                    cx = inner_rect.left() + fm.horizontalAdvance(cur_line)
                    cy = inner_rect.top() + line_idx * fm.lineSpacing()
                    cursor_h = max(14.0, fm.height())
                    p.setPen(QPen(box.color, 1.8))
                    p.drawLine(QPointF(cx, cy), QPointF(cx, cy + cursor_h))

        # 3. Draw laser pointer
        if self._tool == ToolMode.LASER and self._laser_pos is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(239, 68, 68, 200))
            p.drawEllipse(self._laser_pos, _LASER_RADIUS, _LASER_RADIUS)
            p.setBrush(QColor(255, 255, 255, 80))
            p.drawEllipse(self._laser_pos, _LASER_RADIUS // 3, _LASER_RADIUS // 3)

        p.end()