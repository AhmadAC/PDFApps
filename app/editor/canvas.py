# app/editor/canvas.py

"""PDFApps – PdfEditCanvas facade: visual PDF edit canvas with Foxit-style media object selection & text editing."""

from __future__ import annotations

import contextlib
import fitz
from PySide6.QtCore import Qt, Signal, QRect, QPoint, QThreadPool
from PySide6.QtGui import QPainter, QCursor
from PySide6.QtWidgets import QWidget, QSizePolicy

from app.constants import BG_INNER, _LN
from app.editor.canvas_render1 import (
    _PAGE_GAP, _BUFFER_PGS, _MAX_THREADS,
    _EditRenderSignals, _EditPageJob,
    _get_icon_cursor, _load_overlay_pixmap, clear_overlay_pixmap_cache
)
from app.editor.canvas_overlay1 import CanvasOverlayManager
from app.editor.canvas_text1 import CanvasInlineTextManager
from app.editor.canvas_painter1 import CanvasPainter
from app.editor.canvas_events1 import CanvasEventHandler


class PdfEditCanvas(QWidget):
    rect_selected        = Signal(int, object)        # (page_idx, fitz.Rect)
    point_clicked        = Signal(int, object)        # (page_idx, fitz.Point)
    stroke_finished      = Signal(int, object)        # (page_idx, list[fitz.Point])
    note_deleted         = Signal(dict)
    zoom_changed         = Signal(int)
    text_edit_committed  = Signal(int, dict)          # (page_idx, edit_dict)
    text_inserted        = Signal(int, dict)          # (page_idx, edit_dict)
    text_edit_started    = Signal(dict)               # (format_dict)
    signature_added      = Signal(int, object, str)   # (page_idx, fitz.Rect, sig_path)
    overlay_changed      = Signal()
    overlay_deleted      = Signal(int, dict)          # (index, overlay_dict)

    HANDLE_NONE = CanvasOverlayManager.HANDLE_NONE
    HANDLE_TL   = CanvasOverlayManager.HANDLE_TL
    HANDLE_TR   = CanvasOverlayManager.HANDLE_TR
    HANDLE_BL   = CanvasOverlayManager.HANDLE_BL
    HANDLE_BR   = CanvasOverlayManager.HANDLE_BR

    def __init__(self):
        super().__init__()
        self._doc         = None
        self._path        = ""
        self._password    = ""
        self._page_idx    = 0
        self._zoom        = 1.0
        self._zoom_factor = 1.0
        self._base_avail  = 300
        self._page_pixmaps: list = []
        self._page_prev_pixmaps: list = []
        self._page_offsets = []
        self._gen         = 0
        self._pending: set[int] = set()
        self._render_signals = _EditRenderSignals()
        self._render_signals.page_ready.connect(self._on_page_ready)
        self._drag_start  = None
        self._drag_rect   = None
        self._overlays    = []
        self._select_mode = False
        self._draw_mode   = False
        self._text_mode   = False
        self._draw_color  = (1.0, 0.0, 0.0)
        self._draw_width  = 2
        self._current_stroke = None
        self._stroke_page = -1
        self._open_note   = None
        self._screen_signal_window = None

        # Media Overlay State
        self._placing_signature: bool = False
        self._placing_sig_path: str = ""
        self._placing_sig_pixmap = None
        self._sig_cursor_pos: QPoint | None = None
        self._selected_overlay_idx: int = -1
        self._drag_handle: int = self.HANDLE_NONE
        self._drag_start_pos: QPoint = QPoint()
        self._drag_start_rect: fitz.Rect | None = None
        self._moving_overlay: bool = False

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setMinimumSize(300, 400)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._bg_color = BG_INNER

        # Subsystem managers
        self._overlay_mgr = CanvasOverlayManager(self)
        self._inline_mgr = CanvasInlineTextManager(self)
        self._painter = CanvasPainter()
        self._event_handler = CanvasEventHandler(self)

    @property
    def _inline_edit(self):
        return self._inline_mgr.edit

    # ── Tool Modes ────────────────────────────────────────────────────────

    def set_dark_mode(self, dark: bool):
        self._bg_color = BG_INNER if dark else _LN
        self.update()

    def set_select_mode(self, active: bool):
        self._select_mode = active
        if active:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_text_mode(self, active: bool):
        self._text_mode = active
        if active:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        elif not self._draw_mode and not self._placing_signature:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_draw_mode(self, active: bool, color=None, width=None):
        self._draw_mode = active
        if color is not None:
            self._draw_color = color
        if width is not None:
            self._draw_width = max(1, int(width))
        if active:
            self.setCursor(_get_icon_cursor("fa5s.pencil-alt", 14, 2, rotate=135))
        else:
            self._current_stroke = None
            self._stroke_page = -1
            if not self._text_mode and not self._placing_signature:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()

    def set_overlays(self, overlays: list):
        self._overlays = overlays
        self._open_note = None
        if self._selected_overlay_idx >= len(self._overlays):
            self._selected_overlay_idx = -1
        self.update()

    # ── Overlay Delegation ────────────────────────────────────────────────

    def start_add_signature_flow(self, pos: QPoint | None = None):
        self._overlay_mgr.start_add_signature_flow(pos)

    def begin_signature_placement(self, sig_path: str):
        self._overlay_mgr.begin_signature_placement(sig_path)

    def cancel_signature_placement(self):
        self._overlay_mgr.cancel_signature_placement()

    def delete_selected_overlay(self) -> dict | None:
        return self._overlay_mgr.delete_selected_overlay()

    def duplicate_selected_overlay(self) -> None:
        self._overlay_mgr.duplicate_selected_overlay()

    def _get_overlay_handle_at(self, idx: int, pos: QPoint) -> int:
        return self._overlay_mgr.get_overlay_handle_at(idx, pos)

    def _is_pos_inside_overlay(self, idx: int, pos: QPoint) -> bool:
        return self._overlay_mgr.is_pos_inside_overlay(idx, pos)

    def _detect_existing_media_at(self, page_idx: int, pdf_pt: fitz.Point) -> dict | None:
        return self._overlay_mgr.detect_existing_media_at(page_idx, pdf_pt)

    def _note_icon_at(self, pos: QPoint) -> int:
        return self._overlay_mgr.note_icon_at(pos)

    def _annot_note_at(self, pos: QPoint):
        return self._overlay_mgr.annot_note_at(pos)

    # ── Text Inline Editing Delegation ────────────────────────────────────

    def begin_inline_text_edit(self, span: dict, page_idx: int):
        self._inline_mgr.begin_edit(span, page_idx)

    def begin_inline_text_insert(self, page_idx: int, pdf_point, size: float, color: tuple, font: str = ""):
        self._inline_mgr.begin_insert(page_idx, pdf_point, size, color, font)

    def update_active_text_format(self, font: str, size: float, color: tuple, bold: bool, italic: bool):
        self._inline_mgr.update_format(font, size, color, bold, italic)

    def _commit_inline(self):
        self._inline_mgr.commit()

    def _cancel_inline(self):
        self._inline_mgr.cancel()

    def _reposition_inline(self):
        self._inline_mgr.reposition()

    def eventFilter(self, obj, event):
        if self._inline_mgr.handle_event_filter(obj, event):
            return True
        return super().eventFilter(obj, event)

    # ── Document, Layout & Background Rendering ───────────────────────────

    def _get_scroll_area(self):
        from PySide6.QtWidgets import QScrollArea as _SA
        vp = self.parent()
        sa = vp.parent() if vp else None
        return sa if isinstance(sa, _SA) else None

    def load(self, path: str, password: str = ""):
        if self._doc:
            self._doc.close()
        self._doc = None
        doc = fitz.open(path)
        if doc.needs_pass and password:
            doc.authenticate(password)
        self._doc = doc
        self._path = path
        self._password = password
        self._page_idx = 0
        self._zoom_factor = 1.0
        self._gen += 1
        self._pending.clear()
        self.cancel_signature_placement()
        self._selected_overlay_idx = -1
        self._page_prev_pixmaps.clear()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._layout_and_schedule)

    def zoom_in(self, anchor_pos: QPoint | None = None):
        self._zoom_factor = min(4.0, round(self._zoom_factor * 1.25, 4))
        self._invalidate_and_relayout(anchor_pos=anchor_pos)

    def zoom_out(self, anchor_pos: QPoint | None = None):
        self._zoom_factor = max(0.2, round(self._zoom_factor / 1.25, 4))
        self._invalidate_and_relayout(anchor_pos=anchor_pos)

    def zoom_reset(self):
        self._zoom_factor = 1.0
        self._invalidate_and_relayout()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            pos = e.position().toPoint()
            if e.angleDelta().y() > 0:
                self.zoom_in(anchor_pos=pos)
            else:
                self.zoom_out(anchor_pos=pos)
            e.accept()
        else:
            super().wheelEvent(e)

    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    def set_page(self, idx: int):
        if self._doc and 0 <= idx < self._doc.page_count:
            self._page_idx = idx

    def scroll_to_page(self, idx: int) -> int:
        if 0 <= idx < len(self._page_offsets):
            return self._page_offsets[idx][0]
        return 0

    def page_at_y(self, y: int) -> int:
        for i, (yo, w, h) in enumerate(self._page_offsets):
            if y < yo + h + _PAGE_GAP:
                return i
        return max(0, len(self._page_offsets) - 1)

    def get_span_at(self, page_idx: int, pdf_pt: fitz.Point, max_dist: float = 18.0):
        if not self._doc or not (0 <= page_idx < self._doc.page_count):
            return None
        page = self._doc[page_idx]
        click = fitz.Point(pdf_pt.x, pdf_pt.y)
        found, best_dist = None, float(max_dist)
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = fitz.Rect(span["bbox"])
                    if bbox.contains(click):
                        return span
                    cx = max(bbox.x0, min(click.x, bbox.x1))
                    cy = max(bbox.y0, min(click.y, bbox.y1))
                    dist = ((click.x - cx)**2 + (click.y - cy)**2) ** 0.5
                    if dist < best_dist:
                        best_dist = dist
                        found = span
        return found

    def release_doc(self):
        if self._doc:
            self._doc.close()
            self._doc = None

    def close_doc(self):
        self._cancel_inline()
        self.cancel_signature_placement()
        self._selected_overlay_idx = -1
        self._gen += 1
        self._pending.clear()
        self.release_doc()
        self._page_pixmaps.clear()
        self._page_prev_pixmaps.clear()
        self._page_offsets.clear()
        self._overlays = []
        self._open_note = None
        clear_overlay_pixmap_cache()
        self.setMinimumSize(300, 400)
        self.setMaximumSize(16777215, 16777215)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        win = self.window().windowHandle() if self.window() else None
        prev_win = self._screen_signal_window
        if win is prev_win:
            return
        if prev_win is not None:
            with contextlib.suppress(TypeError, RuntimeError):
                prev_win.screenChanged.disconnect(self._on_screen_changed)
        if win is not None:
            win.screenChanged.connect(self._on_screen_changed)
        self._screen_signal_window = win

    def _on_screen_changed(self, _screen):
        self._gen += 1
        self._pending.clear()
        for i, p in enumerate(self._page_pixmaps):
            if p is not None:
                if i < len(self._page_prev_pixmaps):
                    self._page_prev_pixmaps[i] = p
                self._page_pixmaps[i] = None
        self._schedule_visible()
        self.update()

    def on_scroll(self):
        self._schedule_visible()

    def _invalidate_and_relayout(self, anchor_pos: QPoint | None = None):
        self._gen += 1
        self._pending.clear()

        sa = self._get_scroll_area()
        anchor_ratio_y = None
        anchor_vp_y = 0.0
        anchor_ratio_x = None
        anchor_vp_x = 0.0
        if sa and self.height() > 0:
            sb_v = sa.verticalScrollBar()
            vp_h = sa.viewport().height()
            anchor_vp_y = float(anchor_pos.y()) if anchor_pos is not None else vp_h / 2.0
            doc_y = sb_v.value() + anchor_vp_y
            anchor_ratio_y = doc_y / max(1.0, float(self.height()))

            sb_h = sa.horizontalScrollBar()
            vp_w = sa.viewport().width()
            anchor_vp_x = float(anchor_pos.x()) if anchor_pos is not None else vp_w / 2.0
            doc_x = sb_h.value() + anchor_vp_x
            anchor_ratio_x = doc_x / max(1.0, float(self.width()))

        old_pixmaps = [
            p if p is not None else prev
            for p, prev in zip(
                self._page_pixmaps,
                getattr(self, "_page_prev_pixmaps", []),
            )
        ]
        self._layout_and_schedule(
            old_pixmaps=old_pixmaps,
            anchor_ratio_y=anchor_ratio_y,
            anchor_vp_y=anchor_vp_y,
            anchor_ratio_x=anchor_ratio_x,
            anchor_vp_x=anchor_vp_x,
        )

    def _layout_and_schedule(self, old_pixmaps: list | None = None,
                             anchor_ratio_y: float | None = None, anchor_vp_y: float = 0.0,
                             anchor_ratio_x: float | None = None, anchor_vp_x: float = 0.0):
        if not self._doc:
            return

        if self._zoom_factor == 1.0:
            from PySide6.QtWidgets import QScrollArea as _SA
            vp = self.parent()
            sa = vp.parent() if vp else None
            avail = sa.viewport().width() - 4 if isinstance(sa, _SA) else self.width()
            self._base_avail = max(avail, 300)

        ref_w = self._doc[0].rect.width
        self._zoom = (self._base_avail / ref_w) * self._zoom_factor

        self._page_pixmaps.clear()
        self._page_prev_pixmaps = []
        self._page_offsets.clear()
        y_off = 0
        max_w = 0
        for i in range(self._doc.page_count):
            r = self._doc[i].rect
            pw = round(r.width * self._zoom)
            ph = round(r.height * self._zoom)
            self._page_pixmaps.append(None)
            prev_p = old_pixmaps[i] if (old_pixmaps and i < len(old_pixmaps)) else None
            self._page_prev_pixmaps.append(prev_p)
            self._page_offsets.append((y_off, pw, ph))
            max_w = max(max_w, pw)
            y_off += ph + _PAGE_GAP

        total_h = y_off - _PAGE_GAP if y_off > 0 else 400
        new_w = max(max_w, 300)
        new_h = max(total_h, 400)
        self.setFixedSize(new_w, new_h)

        if anchor_ratio_y is not None:
            sa = self._get_scroll_area()
            if sa:
                new_scroll_y = int(round(anchor_ratio_y * new_h - anchor_vp_y))
                sb_v = sa.verticalScrollBar()
                sb_v.setValue(max(0, min(new_scroll_y, sb_v.maximum())))
                if anchor_ratio_x is not None:
                    new_scroll_x = int(round(anchor_ratio_x * new_w - anchor_vp_x))
                    sb_h = sa.horizontalScrollBar()
                    sb_h.setValue(max(0, min(new_scroll_x, sb_h.maximum())))

        self.zoom_changed.emit(round(self._zoom_factor * 100))
        self.update()
        self._schedule_visible()
        if self._inline_mgr.edit.isVisible():
            self._inline_mgr.reposition()

    def _visible_range(self) -> tuple[int, int]:
        from PySide6.QtWidgets import QScrollArea as _SA
        vp = self.parent()
        sa = vp.parent() if vp else None
        n = len(self._page_offsets)
        if not isinstance(sa, _SA) or not n:
            return (0, min(n - 1, _BUFFER_PGS * 2))
        y0 = sa.verticalScrollBar().value()
        y1 = y0 + sa.viewport().height()
        first = last = 0
        found = False
        for i, (yo, pw, ph) in enumerate(self._page_offsets):
            if not found and yo + ph >= y0:
                first = i; found = True
            if yo <= y1:
                last = i
        return (max(0, first - _BUFFER_PGS), min(n - 1, last + _BUFFER_PGS))

    def _schedule_visible(self):
        if not self._page_offsets or not self._path:
            return
        first, last = self._visible_range()
        dpr = self.devicePixelRatioF() or 1.0
        gen = self._gen
        pool = QThreadPool.globalInstance()
        pool.setMaxThreadCount(_MAX_THREADS)
        for i in range(first, last + 1):
            if self._page_pixmaps[i] is None and i not in self._pending:
                self._pending.add(i)
                pool.start(_EditPageJob(self._path, i, self._zoom, dpr,
                                        gen, self._render_signals,
                                        password=getattr(self, "_password", "")))

    def _on_page_ready(self, gen: int, idx: int, pixmap):
        if gen != self._gen:
            return
        self._pending.discard(idx)
        if 0 <= idx < len(self._page_pixmaps):
            self._page_pixmaps[idx] = pixmap
            if idx < len(self._page_prev_pixmaps):
                self._page_prev_pixmaps[idx] = None
            self.update()

    def _page_and_local(self, sx, sy):
        for i, (yo, w, h) in enumerate(self._page_offsets):
            if sy < yo + h + _PAGE_GAP // 2 or i == len(self._page_offsets) - 1:
                return i, sx, sy - yo
        return 0, sx, sy

    def _to_pdf(self, page_idx, sx, sy):
        return fitz.Point(sx / self._zoom, sy / self._zoom)

    def _rect_to_pdf(self, page_idx, local_rect):
        z = self._zoom
        r = fitz.Rect(local_rect.left()/z, local_rect.top()/z,
                      local_rect.right()/z, local_rect.bottom()/z)
        if self._doc and 0 <= page_idx < self._doc.page_count:
            page_rect = self._doc[page_idx].rect
            r = r & page_rect
            if r.is_empty or r.width < 1 or r.height < 1:
                return None
        return r

    # ── Qt Event Dispatches ───────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        self._painter.paint(self, p)
        p.end()

    def mousePressEvent(self, e):
        self._event_handler.handle_mouse_press(e)

    def mouseMoveEvent(self, e):
        self._event_handler.handle_mouse_move(e)

    def mouseReleaseEvent(self, e):
        self._event_handler.handle_mouse_release(e)

    def keyPressEvent(self, e):
        self._event_handler.handle_key_press(e)
        super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        self._event_handler.handle_context_menu(e)