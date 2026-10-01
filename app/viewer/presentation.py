# app/viewer/presentation.py
"""PDFApps – Presentation mode: fullscreen single-page viewer with page transitions and auto-advance."""

import contextlib
import logging
import re
import time

from PySide6.QtCore import Qt, QTimer, QPoint, QRect
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QApplication
from shiboken6 import isValid

from app.viewer.annotation_layer import AnnotationOverlay, ToolMode
from app.viewer.annotation_hud import AnnotationHUD


_log = logging.getLogger(__name__)

_HUD_AUTO_HIDE_MS = 3000
_HUD_RESTART_DEBOUNCE_MS = 100

_PALETTE_HOTKEYS = {
    Qt.Key.Key_1: "#EF4444",
    Qt.Key.Key_2: "#10B981",
    Qt.Key.Key_3: "#3B82F6",
    Qt.Key.Key_4: "#FBBF24",
    Qt.Key.Key_5: "#111111",
    Qt.Key.Key_6: "#FFFFFF",
}


class PresentationWidget(QWidget):
    """Fullscreen single-page PDF viewer with keyboard navigation, zoom controls,
    smooth page transitions, auto-advance (/Dur), and a PowerPoint/Edge-style annotation HUD.
    Annotations are session-scoped — kept per page while the window lives,
    discarded on close."""

    def __init__(self, path: str, password: str, start_page: int,
                 total_pages: int, dark_mode: bool = True):
        super().__init__()
        self._path = path
        self._password = password
        self._current = start_page
        self._total = total_pages
        self._pixmap = None
        self._prev_pixmap = None
        self._ready = False
        self._dark_mode = bool(dark_mode)
        self._hud_last_shown_ms = 0.0

        # Zoom and Pan state
        self._zoom_factor: float = 1.0
        self._pan_x: int = 0
        self._pan_y: int = 0
        self._is_panning = False
        self._pan_start_pos = QPoint()
        self._pan_start_offset = QPoint()

        # Transitions state
        self._trans_style = None
        self._trans_progress = 1.0
        self._trans_step = 0.05
        self._trans_direction = 0
        self._trans_timer = QTimer(self)
        self._trans_timer.setInterval(25)
        self._trans_timer.timeout.connect(self._on_trans_tick)

        # Auto-advance (/Dur) timer
        self._auto_advance_timer = QTimer(self)
        self._auto_advance_timer.setSingleShot(True)
        self._auto_advance_timer.timeout.connect(self._on_auto_advance)

        import fitz
        self._doc = fitz.open(self._path)
        if self._password:
            self._doc.authenticate(self._password)

        self._counter = QLabel(self)
        self._counter.setStyleSheet(
            "background: rgba(0,0,0,0.6); color: white; "
            "padding: 6px 16px; border-radius: 8px; font-size: 14px;"
        )
        self._counter.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._overlay = AnnotationOverlay(self, self._dark_mode)
        self._overlay.set_current_page(self._current)
        self._overlay.setGeometry(self.rect())

        self._hud = AnnotationHUD(self, self._dark_mode)
        self._hud.tool_selected.connect(self._on_tool_selected)
        self._hud.color_selected.connect(self._on_color_selected)
        self._hud.stroke_toggled.connect(self._on_stroke_toggled)
        self._hud.cloud_toggled.connect(self._on_cloud_toggled)
        self._hud.clear_requested.connect(self._on_clear_requested)
        self._hud.set_active_tool(int(ToolMode.POINTER))
        self._hud.set_active_color(self._overlay.pen_color())
        self._hud.hide()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(
            lambda: self._counter.setVisible(False)
            if isValid(self._counter) else None)

        self._hud_hide_timer = QTimer(self)
        self._hud_hide_timer.setSingleShot(True)
        self._hud_hide_timer.timeout.connect(
            lambda: self._hud.hide() if isValid(self._hud) else None)

        self.setWindowFlags(Qt.WindowType.Window)
        self.setStyleSheet("background: #000000;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setWindowState(Qt.WindowState.WindowFullScreen)

        self._ready = True
        QTimer.singleShot(0, lambda: self._render(transition=False))

    def update_theme(self, dark: bool) -> None:
        self._dark_mode = bool(dark)
        if isValid(self._overlay):
            self._overlay.update_theme(self._dark_mode)
        if isValid(self._hud):
            self._hud.update_theme(self._dark_mode)

    # ── Zoom & Pan & Scroll Controls ──────────────────────────────────────

    def _zoom_in(self):
        self._zoom_factor = min(5.0, round(self._zoom_factor * 1.25, 3))
        self._render(transition=False)

    def _zoom_out(self):
        self._zoom_factor = max(0.4, round(self._zoom_factor / 1.25, 3))
        if self._zoom_factor <= 1.0:
            self._pan_x = 0
            self._pan_y = 0
        self._render(transition=False)

    def _zoom_reset(self):
        self._zoom_factor = 1.0
        self._pan_x = 0
        self._pan_y = 0
        self._render(transition=False)

    def _scroll_page(self, up: bool, amount: float = 80.0):
        if not self._pixmap:
            return
        dpr = self._pixmap.devicePixelRatio() or 1.0
        ph = self._pixmap.height() / dpr
        sh = float(self.height())
        max_pan = max(0.0, (ph - sh) / 2.0) + (sh * 0.35 if ph > sh else sh * 0.45)

        if up:
            self._pan_y = int(round(min(max_pan, self._pan_y + amount)))
        else:
            self._pan_y = int(round(max(-max_pan, self._pan_y - amount)))

        self.update()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if e.angleDelta().y() > 0:
                self._zoom_in()
            else:
                self._zoom_out()
            e.accept()
            return
        else:
            delta = e.angleDelta().y()
            if delta > 0:
                self._scroll_page(up=True, amount=abs(delta) * 0.6)
            elif delta < 0:
                self._scroll_page(up=False, amount=abs(delta) * 0.6)
            e.accept()
            return

    def _go_to_page(self, new_page: int):
        if new_page == self._current or not (0 <= new_page < self._total):
            return
        self._prev_pixmap = self._pixmap
        self._current = new_page
        self._pan_x = 0
        self._pan_y = 0
        self._render(transition=True)

    def _on_auto_advance(self):
        if self._current < self._total - 1:
            self._go_to_page(self._current + 1)

    def _on_trans_tick(self):
        self._trans_progress += self._trans_step
        if self._trans_progress >= 1.0:
            self._trans_progress = 1.0
            self._trans_timer.stop()
            self._prev_pixmap = None
        self.update()

    def _render(self, transition: bool = False):
        import fitz
        self._auto_advance_timer.stop()

        try:
            if self._doc is None:
                self._pixmap = None
                return
            page = self._doc[self._current]
            screen = self.screen() or QApplication.primaryScreen()
            geom = screen.geometry()
            dpr = screen.devicePixelRatio() or 1.0
            sw, sh = geom.width(), geom.height()
            base_zoom = min(sw / page.rect.width, sh / page.rect.height)
            zoom = base_zoom * self._zoom_factor
            rz = zoom * dpr
            pix = page.get_pixmap(matrix=fitz.Matrix(rz, rz))
            qp = QPixmap()
            qp.loadFromData(pix.tobytes("png"))
            qp.setDevicePixelRatio(dpr)
            self._pixmap = qp

            # Check /Dur for auto-advance
            val_dur = self._doc.xref_get_key(page.xref, "Dur")
            if val_dur and val_dur[0] != "null":
                try:
                    dur_s = float(val_dur[1].strip())
                    if dur_s > 0:
                        self._auto_advance_timer.start(int(dur_s * 1000))
                except ValueError:
                    pass

            # Check /Trans for transition animation
            if transition and self._prev_pixmap is not None:
                trans_val = self._doc.xref_get_key(page.xref, "Trans")
                trans_style = None
                trans_dur = 0.6
                direction = 0
                if trans_val and trans_val[0] != "null":
                    raw = trans_val[1]
                    m_s = re.search(r"/S\s+/([A-Za-z]+)", raw)
                    if m_s:
                        trans_style = m_s.group(1)
                    m_d = re.search(r"/D\s+([\d\.]+)", raw)
                    if m_d:
                        trans_dur = min(2.5, max(0.1, float(m_d.group(1))))
                    m_di = re.search(r"/Di\s+(\d+)", raw)
                    if m_di:
                        direction = int(m_di.group(1))

                if trans_style and trans_style != "None":
                    self._trans_style = trans_style
                    self._trans_direction = direction
                    self._trans_progress = 0.0
                    frames = max(10, int(trans_dur * 40.0))
                    self._trans_step = 1.0 / frames
                    self._trans_timer.start(25)
                else:
                    self._prev_pixmap = None
                    self._trans_progress = 1.0
            else:
                self._prev_pixmap = None
                self._trans_progress = 1.0
        except Exception:
            _log.exception("presentation _render failed")
            self._pixmap = None

        self._overlay.set_current_page(self._current)
        self._overlay.raise_()
        self._hud.raise_()
        self._update_counter()
        self.update()

    def _update_counter(self):
        zoom_str = f"  ·  {int(round(self._zoom_factor * 100))}%" if self._zoom_factor != 1.0 else ""
        self._counter.setText(f"{self._current + 1} / {self._total}{zoom_str}")
        self._counter.adjustSize()
        lw = self._counter.width()
        self._counter.move(self.width() // 2 - lw // 2, self.height() - 50)
        self._counter.setVisible(True)
        self._counter.raise_()
        self._hide_timer.start(3000)

    def _sync_hud_text_options(self):
        if isValid(self._hud) and isValid(self._overlay):
            self._hud.set_stroke_active(self._overlay.is_active_box_stroke())
            self._hud.set_cloud_active(self._overlay.is_active_box_cloud())

    def _show_hud(self):
        if not isValid(self._hud):
            return
        self._sync_hud_text_options()
        if not self._hud.isVisible():
            self._hud.reposition()
            self._hud.show()
            self._hud.raise_()
        now = time.monotonic() * 1000.0
        if now - self._hud_last_shown_ms < _HUD_RESTART_DEBOUNCE_MS:
            return
        self._hud_last_shown_ms = now
        self._hud_hide_timer.start(_HUD_AUTO_HIDE_MS)
        if self._overlay.tool() in (int(ToolMode.POINTER), int(ToolMode.TYPE)):
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _on_tool_selected(self, mode: int):
        self._overlay.set_tool(int(mode))
        self._hud.set_active_tool(int(mode))
        if int(mode) in (int(ToolMode.POINTER), int(ToolMode.TYPE)):
            self.setCursor(Qt.CursorShape.ArrowCursor
                           if self._hud.isVisible()
                           else Qt.CursorShape.BlankCursor)
        else:
            self.setCursor(Qt.CursorShape.BlankCursor)
        self._show_hud()

    def _on_color_selected(self, color):
        self._overlay.set_pen_color(color)
        self._hud.set_active_color(color)
        self._show_hud()

    def _on_stroke_toggled(self):
        new_state = self._overlay.toggle_text_stroke()
        self._hud.set_stroke_active(new_state)
        self._show_hud()

    def _on_cloud_toggled(self):
        new_state = self._overlay.toggle_text_cloud()
        self._hud.set_cloud_active(new_state)
        self._show_hud()

    def _on_clear_requested(self):
        self._overlay.clear_current_page()
        self._sync_hud_text_options()
        self.update()
        self._show_hud()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000000"))

        if self._pixmap:
            dpr = self._pixmap.devicePixelRatio() or 1.0
            pw = self._pixmap.width() / dpr
            ph = self._pixmap.height() / dpr
            x = (self.width() - pw) / 2 + self._pan_x
            y = (self.height() - ph) / 2 + self._pan_y

            t = self._trans_progress
            if self._prev_pixmap is not None and t < 1.0 and self._trans_style:
                old_dpr = self._prev_pixmap.devicePixelRatio() or 1.0
                old_w = self._prev_pixmap.width() / old_dpr
                old_h = self._prev_pixmap.height() / old_dpr
                old_x = (self.width() - old_w) / 2
                old_y = (self.height() - old_h) / 2

                style = self._trans_style
                if style == "Push":
                    di = self._trans_direction
                    if di == 90:    # bottom to top
                        dy = int(self.height() * t)
                        p.drawPixmap(int(old_x), int(old_y - dy), self._prev_pixmap)
                        p.drawPixmap(int(x), int(y + self.height() - dy), self._pixmap)
                    elif di == 180: # right to left
                        dx = int(self.width() * t)
                        p.drawPixmap(int(old_x + dx), int(old_y), self._prev_pixmap)
                        p.drawPixmap(int(x - self.width() + dx), int(y), self._pixmap)
                    elif di == 270: # top to bottom
                        dy = int(self.height() * t)
                        p.drawPixmap(int(old_x), int(old_y + dy), self._prev_pixmap)
                        p.drawPixmap(int(x), int(y - self.height() + dy), self._pixmap)
                    else:           # left to right (0)
                        dx = int(self.width() * t)
                        p.drawPixmap(int(old_x - dx), int(old_y), self._prev_pixmap)
                        p.drawPixmap(int(x + self.width() - dx), int(y), self._pixmap)

                elif style in ("Wipe", "Cover"):
                    p.drawPixmap(int(old_x), int(old_y), self._prev_pixmap)
                    di = self._trans_direction
                    p.save()
                    if di == 90:
                        split_y = int(self.height() * (1.0 - t))
                        p.setClipRect(QRect(0, split_y, self.width(), self.height() - split_y))
                    elif di == 180:
                        split_x = int(self.width() * (1.0 - t))
                        p.setClipRect(QRect(split_x, 0, self.width() - split_x, self.height()))
                    elif di == 270:
                        split_y = int(self.height() * t)
                        p.setClipRect(QRect(0, 0, self.width(), split_y))
                    else:
                        split_x = int(self.width() * t)
                        p.setClipRect(QRect(0, 0, split_x, self.height()))
                    p.drawPixmap(int(x), int(y), self._pixmap)
                    p.restore()

                elif style in ("Fade", "Dissolve"):
                    p.setOpacity(max(0.0, 1.0 - t))
                    p.drawPixmap(int(old_x), int(old_y), self._prev_pixmap)
                    p.setOpacity(min(1.0, t))
                    p.drawPixmap(int(x), int(y), self._pixmap)
                    p.setOpacity(1.0)

                elif style == "Box":
                    p.drawPixmap(int(old_x), int(old_y), self._prev_pixmap)
                    bw = int(self.width() * t)
                    bh = int(self.height() * t)
                    bx = (self.width() - bw) // 2
                    by = (self.height() - bh) // 2
                    p.save()
                    p.setClipRect(QRect(bx, by, bw, bh))
                    p.drawPixmap(int(x), int(y), self._pixmap)
                    p.restore()

                else:
                    p.setOpacity(max(0.0, 1.0 - t))
                    p.drawPixmap(int(old_x), int(old_y), self._prev_pixmap)
                    p.setOpacity(min(1.0, t))
                    p.drawPixmap(int(x), int(y), self._pixmap)
                    p.setOpacity(1.0)
            else:
                p.drawPixmap(int(x), int(y), self._pixmap)
        p.end()

    def keyPressEvent(self, e):
        key = e.key()
        modifiers = e.modifiers()

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self._zoom_in()
                e.accept()
                return
            if key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
                self._zoom_out()
                e.accept()
                return
            if key == Qt.Key.Key_0:
                self._zoom_reset()
                e.accept()
                return

        if self._overlay._active_box is not None:
            self._overlay.keyPressEvent(e)
            self._sync_hud_text_options()
            if e.isAccepted():
                return

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Z:
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    self._overlay.redo()
                else:
                    self._overlay.undo()
                self._sync_hud_text_options()
                e.accept()
                return
            if key == Qt.Key.Key_Y:
                self._overlay.redo()
                self._sync_hud_text_options()
                e.accept()
                return

        if modifiers & (Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.AltModifier
                        | Qt.KeyboardModifier.MetaModifier):
            super().keyPressEvent(e)
            return

        if key == Qt.Key.Key_P:
            self._on_tool_selected(int(ToolMode.PEN))
            return
        if key == Qt.Key.Key_H:
            self._on_tool_selected(int(ToolMode.HIGHLIGHTER))
            return
        if key == Qt.Key.Key_E:
            self._on_tool_selected(int(ToolMode.ERASER))
            return
        if key == Qt.Key.Key_T:
            self._on_tool_selected(int(ToolMode.TYPE))
            return
        if key == Qt.Key.Key_L:
            self._on_tool_selected(int(ToolMode.LASER))
            return
        if key == Qt.Key.Key_C:
            self._on_clear_requested()
            return
        if key in _PALETTE_HOTKEYS:
            current = self._overlay.tool()
            if current in (int(ToolMode.PEN), int(ToolMode.HIGHLIGHTER), int(ToolMode.TYPE)):
                color = QColor(_PALETTE_HOTKEYS[key])
                self._overlay.set_pen_color(color)
                self._hud.set_active_color(color)
                self._show_hud()
                return

        if key == Qt.Key.Key_Up:
            self._scroll_page(up=True)
            e.accept()
            return
        if key == Qt.Key.Key_Down:
            self._scroll_page(up=False)
            e.accept()
            return

        if key == Qt.Key.Key_Escape:
            self.close()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Space, Qt.Key.Key_PageDown):
            if self._current < self._total - 1:
                self._go_to_page(self._current + 1)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Backspace, Qt.Key.Key_PageUp):
            if self._current > 0:
                self._go_to_page(self._current - 1)
        elif key == Qt.Key.Key_Home:
            self._go_to_page(0)
        elif key == Qt.Key.Key_End:
            self._go_to_page(self._total - 1)

    def mousePressEvent(self, e):
        if (e.button() == Qt.MouseButton.MiddleButton or
                (e.button() == Qt.MouseButton.LeftButton and
                 self._overlay.tool() == int(ToolMode.POINTER) and self._zoom_factor > 1.0)):
            self._is_panning = True
            self._pan_start_pos = e.position().toPoint()
            self._pan_start_offset = QPoint(int(self._pan_x), int(self._pan_y))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        self._show_hud()
        if self._is_panning:
            delta = e.position().toPoint() - self._pan_start_pos
            self._pan_x = int(self._pan_start_offset.x() + delta.x())
            self._pan_y = int(self._pan_start_offset.y() + delta.y())
            self.update()
            e.accept()
            return

        if self._overlay.tool() == int(ToolMode.LASER):
            self._overlay.set_laser_pos(e.position().toPoint())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._is_panning:
            self._is_panning = False
            if self._overlay.tool() in (int(ToolMode.POINTER), int(ToolMode.TYPE)):
                self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
                self.setCursor(Qt.CursorShape.BlankCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def resizeEvent(self, _):
        if not self._ready:
            return
        if isValid(self._overlay):
            self._overlay.setGeometry(self.rect())
        if isValid(self._hud):
            self._hud.reposition()
        self._update_counter()
        QTimer.singleShot(0, lambda: self._render(transition=False))

    def closeEvent(self, event):
        if isValid(self._overlay):
            self._overlay.clear_all(record_undo=False)
        for tmr in (
            getattr(self, "_hide_timer", None),
            getattr(self, "_hud_hide_timer", None),
            getattr(self, "_auto_advance_timer", None),
            getattr(self, "_trans_timer", None),
        ):
            if tmr is not None and isValid(tmr):
                tmr.stop()
        if self._doc is not None:
            with contextlib.suppress(Exception):
                self._doc.close()
            self._doc = None
        super().closeEvent(event)