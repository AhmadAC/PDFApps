# app/viewer/canvas_1.py

"""PDFApps – _SelectCanvas: continuous-scroll visual PDF viewer canvas with smooth zooming, persistent zoom preference, and centered layout."""

from __future__ import annotations

import contextlib
import json
import os
from typing import Any

import fitz
from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QThreadPool, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.constants import BG_INNER, _LN
from app.editor.dialogs import _SignatureDialog, load_signature_pixmap
from app.i18n import _CONFIG_PATH, _update_config
from app.viewer.canvas_interaction import CanvasInteractionHandler
from app.viewer.canvas_painter import CanvasPainter
from app.viewer.canvas_worker import (
    _BUFFER_PGS,
    _MAX_THREADS,
    _PAGE_GAP,
    _PageEntry,
    _PageJob,
    _RenderSignals,
)

# Safe fallback for PyMuPDF annotation constant to satisfy Pylance
_PDF_ANNOT_TEXT: int = getattr(fitz, "PDF_ANNOT_TEXT", 0)


class _SelectCanvas(QWidget):
    """Continuous-scroll PDF viewer canvas supporting text selection, search highlights,
    page notes, cropping, live signature placement, and smooth flash-free zooming."""

    zoom_changed = Signal(int)
    doc_replaced = Signal(object)
    crop_selected = Signal(int, object)
    crop_applied = Signal()
    crop_undo_requested = Signal()
    crop_redo_requested = Signal()
    page_action_requested = Signal(str, object)
    text_copied = Signal(str)
    signature_committed = Signal(int, object, str)  # (page_idx, fitz.Rect, sig_path)

    HANDLE_NONE = 0
    HANDLE_TL = 1
    HANDLE_TR = 2
    HANDLE_BL = 3
    HANDLE_BR = 4

    _saved_zoom_factor_pref: float | None = None

    def __init__(self):
        super().__init__()
        self._doc = None
        self._path = ""
        self._password = ""
        self._entries: list[Any] = []

        if _SelectCanvas._saved_zoom_factor_pref is None:
            try:
                if os.path.isfile(_CONFIG_PATH):
                    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                        val = cfg.get("viewer_zoom_factor")
                        if val is not None:
                            _SelectCanvas._saved_zoom_factor_pref = max(0.2, min(5.0, float(val)))
            except Exception:
                pass
            if _SelectCanvas._saved_zoom_factor_pref is None:
                _SelectCanvas._saved_zoom_factor_pref = 1.0

        self._zoom_factor = _SelectCanvas._saved_zoom_factor_pref or 1.0
        self._zoom = 1.0
        self._base_avail = 600
        self._gen = 0
        self._pending: set[int] = set()
        self._bg_color = BG_INNER
        self._night_mode = False
        self._page_rotations: dict[int, int] = {}
        self._page_crops: dict[int, tuple[float, float, float, float]] = {}
        self._page_order: list[int] | None = None
        self._search_highlights: list = []
        self._search_current: int = -1
        self._sel_rects: list[QRect] = []
        self._sel_text: str = ""
        self._drag_start: QPoint | None = None
        self._drag_end: QPoint | None = None
        self._open_note: tuple[int, int] | None = None
        self._crop_mode = False
        self._crop_preview: dict | None = None
        self._crop_active_page = 0
        self._crop_drag_start: QPoint | None = None
        self._crop_drag_cur: QPoint | None = None
        self._numbers_preview: dict | None = None
        self._screen_signal_window = None

        self._placing_signature: bool = False
        self._placing_sig_path: str = ""
        self._placing_sig_pixmap = None
        self._sig_cursor_pos: QPoint | None = None
        self._active_sig: dict | None = None

        self._render_signals = _RenderSignals()
        self._render_signals.page_ready.connect(self._on_page_ready)
        self._interaction = CanvasInteractionHandler(self)

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(300, 400)

    def page_x_offset(self, entry) -> int:
        """Calculate horizontal centering offset for a page within the canvas width."""
        if not entry:
            return 0
        return max(0, (self.width() - entry.w) // 2)

    def _save_zoom_pref(self) -> None:
        type(self)._saved_zoom_factor_pref = self._zoom_factor
        try:
            val = self._zoom_factor
            _update_config(lambda cfg: cfg.__setitem__("viewer_zoom_factor", val))
        except Exception:
            pass

    # ── Display Modes and Themes ──────────────────────────────────────────

    def set_dark_mode(self, dark: bool):
        self._bg_color = BG_INNER if dark else _LN
        self.update()

    def set_night_mode(self, night: bool):
        if self._night_mode == night:
            return
        self._night_mode = night
        self._invalidate_and_relayout(preserve_pixmaps=False)

    def set_crop_mode(self, active: bool):
        self._crop_mode = active
        if active:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.IBeamCursor)
            self._crop_drag_start = None
            self._crop_drag_cur = None
        self.update()

    def set_crop_preview(self, crop_data: dict | None):
        self._crop_preview = crop_data
        self.update()

    def set_numbers_preview(self, preview_data: dict | None):
        self._numbers_preview = preview_data
        self.update()

    def set_page_rotations(self, rotations: dict[int, int]):
        self._page_rotations = dict(rotations)
        self._invalidate_and_relayout(preserve_pixmaps=False)

    def set_page_crops(self, crops: dict[int, tuple[float, float, float, float]]):
        self._page_crops = dict(crops)
        self._invalidate_and_relayout(preserve_pixmaps=False)

    def set_page_order(self, order: list[int] | None):
        self._page_order = list(order) if order is not None else None
        self._invalidate_and_relayout(preserve_pixmaps=False)

    def set_search_highlights(self, highlights: list, current: int = -1):
        self._search_highlights = highlights
        self._search_current = current
        self.update()

    # ── Signature Flow & Placement Methods ────────────────────────────────

    def start_add_signature_flow(self, pos: QPoint | None = None):
        dlg = _SignatureDialog(self)
        if dlg.exec() == _SignatureDialog.DialogCode.Accepted:
            path = dlg.selected_signature_path()
            if path and os.path.isfile(path):
                self.begin_signature_placement(path)

    def begin_signature_placement(self, sig_path: str):
        if self._active_sig is not None:
            self.commit_active_signature()
        self._placing_signature = True
        self._placing_sig_path = sig_path
        self._placing_sig_pixmap = load_signature_pixmap(sig_path, max_size=(320, 140))
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def cancel_signature_placement(self):
        self._placing_signature = False
        self._placing_sig_path = ""
        self._placing_sig_pixmap = None
        self._sig_cursor_pos = None
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.update()

    def commit_active_signature(self):
        if not self._active_sig:
            return
        sig = dict(self._active_sig)
        self._active_sig = None
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.update()
        page_idx = sig["page"]
        rect = sig["rect"]
        path = sig["path"]
        self.signature_committed.emit(page_idx, rect, path)

    def delete_active_signature(self):
        self._active_sig = None
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.update()

    # ── Document Lifecycle ────────────────────────────────────────────────

    def load(self, doc, target_page: int = 0, path: str = "", password: str = "", target_scroll: int = -1):
        self._doc = doc
        self._path = path
        self._password = password
        self._zoom_factor = type(self)._saved_zoom_factor_pref or 1.0
        self._gen += 1
        self._pending.clear()
        self._open_note = None
        self._search_highlights.clear()
        self._search_current = -1
        self.cancel_signature_placement()
        self._active_sig = None
        self._interaction.clear_selection()
        self._entries.clear()
        self._layout_and_schedule()

    def close_doc(self):
        self._gen += 1
        self._pending.clear()
        self.cancel_signature_placement()
        self._active_sig = None
        if self._doc:
            with contextlib.suppress(Exception):
                self._doc.close()
            self._doc = None
        self._entries.clear()
        self._interaction.clear_selection()
        self._open_note = None
        self._search_highlights.clear()
        self._search_current = -1
        self.setMinimumSize(300, 400)
        self.setMaximumSize(16777215, 16777215)
        self.update()

    def _prepare_for_save(self):
        self._gen += 1
        self._pending.clear()

    def _reopen_document(self):
        if not self._path:
            return None
        try:
            if self._doc:
                with contextlib.suppress(Exception):
                    self._doc.close()
            doc = fitz.open(self._path)
            if self._password and doc.needs_pass:
                doc.authenticate(self._password)
            self._doc = doc
            self.doc_replaced.emit(doc)
            return doc
        except Exception:
            return None

    # ── Geometry, Zoom and Anchored Navigation ────────────────────────────

    def _get_scroll_area(self):
        from PySide6.QtWidgets import QScrollArea as _SA
        vp = self.parent()
        sa = vp.parent() if vp else None
        return sa if isinstance(sa, _SA) else None

    def page_count(self) -> int:
        return len(self._entries)

    def scroll_to_page(self, idx: int) -> int:
        if 0 <= idx < len(self._entries):
            return self._entries[idx].y_off
        return 0

    def page_at_y(self, y: int) -> int:
        for i, entry in enumerate(self._entries):
            if y < entry.y_off + entry.h + _PAGE_GAP:
                return i
        return max(0, len(self._entries) - 1)

    def zoom_in(self, anchor_pos: Any = None):
        pos = anchor_pos if isinstance(anchor_pos, (QPoint, QPointF)) else None
        self._zoom_factor = min(5.0, round(self._zoom_factor * 1.25, 4))
        self._save_zoom_pref()
        self._invalidate_and_relayout(anchor_pos=pos, preserve_pixmaps=True)

    def zoom_out(self, anchor_pos: Any = None):
        pos = anchor_pos if isinstance(anchor_pos, (QPoint, QPointF)) else None
        self._zoom_factor = max(0.2, round(self._zoom_factor / 1.25, 4))
        self._save_zoom_pref()
        self._invalidate_and_relayout(anchor_pos=pos, preserve_pixmaps=True)

    def zoom_reset(self):
        self._zoom_factor = 1.0
        self._save_zoom_pref()
        self._invalidate_and_relayout(preserve_pixmaps=True)

    def _on_viewport_resized(self):
        sa = self._get_scroll_area()
        if not sa or not self._doc:
            return
        vp_w = sa.viewport().width()
        if vp_w > 50:
            if self._zoom_factor == 1.0:
                self._layout_and_schedule()
            else:
                max_w = max((e.w for e in self._entries), default=300)
                canvas_w = max(max_w + 32, vp_w)
                if canvas_w != self.width():
                    self.setFixedWidth(canvas_w)
                    self.update()

    def _invalidate_and_relayout(self, anchor_pos: Any = None, preserve_pixmaps: bool = True):
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
            valid_anchor = isinstance(anchor_pos, (QPoint, QPointF))
            anchor_vp_y = float(anchor_pos.y()) if valid_anchor else vp_h / 2.0
            doc_y = sb_v.value() + anchor_vp_y
            anchor_ratio_y = doc_y / max(1.0, float(self.height()))

            sb_h = sa.horizontalScrollBar()
            vp_w = sa.viewport().width()
            anchor_vp_x = float(anchor_pos.x()) if valid_anchor else vp_w / 2.0
            doc_x = sb_h.value() + anchor_vp_x
            anchor_ratio_x = doc_x / max(1.0, float(self.width()))

        old_pixmaps: dict[int, QPixmap] = {}
        if preserve_pixmaps:
            for e in self._entries:
                p = e.pixmap if e.pixmap is not None else e.prev_pixmap
                if p is not None and not p.isNull():
                    old_pixmaps[e.src_page] = p

        self._layout_and_schedule(
            old_pixmaps=old_pixmaps,
            anchor_ratio_y=anchor_ratio_y,
            anchor_vp_y=anchor_vp_y,
            anchor_ratio_x=anchor_ratio_x,
            anchor_vp_x=anchor_vp_x,
        )

    def _layout_and_schedule(
        self,
        old_pixmaps: dict[int, QPixmap] | None = None,
        anchor_ratio_y: float | None = None,
        anchor_vp_y: float = 0.0,
        anchor_ratio_x: float | None = None,
        anchor_vp_x: float = 0.0,
    ):
        if not self._doc or self._doc.page_count <= 0:
            return

        sa = self._get_scroll_area()
        vp_w = sa.viewport().width() if sa else self.width()

        page0 = self._doc[0]
        rot0 = self._page_rotations.get(0, 0) % 360
        r0 = page0.rect
        ref_w = r0.height if rot0 in (90, 270) else r0.width
        ref_w = max(ref_w, 1.0)

        # In fit-width mode (zoom_factor == 1.0), use the full viewport width
        if self._zoom_factor == 1.0:
            avail = max(300, vp_w - 36) if vp_w > 50 else max(300, self.width())
            self._base_avail = avail
        self._zoom = (self._base_avail / ref_w) * self._zoom_factor

        self._entries.clear()
        y_off = 0
        max_w = 0

        page_count = len(self._page_order) if self._page_order is not None else self._doc.page_count
        for i in range(page_count):
            src_idx = self._page_order[i] if self._page_order is not None and i < len(self._page_order) else i
            if src_idx < 0 or src_idx >= self._doc.page_count:
                continue
            pg = self._doc[src_idx]
            rot = self._page_rotations.get(src_idx, 0) % 360
            crop = self._page_crops.get(src_idx)
            if crop:
                cr = fitz.Rect(crop) & pg.mediabox
                w = cr.width if not cr.is_empty else pg.rect.width
                h = cr.height if not cr.is_empty else pg.rect.height
            else:
                w = pg.rect.width
                h = pg.rect.height
            if rot in (90, 270):
                w, h = h, w

            pw = round(w * self._zoom)
            ph = round(h * self._zoom)

            entry: Any = _PageEntry(y_off, pw, ph, src_page=src_idx)
            if old_pixmaps and src_idx in old_pixmaps:
                entry.prev_pixmap = old_pixmaps[src_idx]

            annots = []
            try:
                rx0 = pg.rect.x0
                ry0 = pg.rect.y0
                for a in pg.annots() or []:
                    a_type = getattr(a, "type", (None, None))
                    if (isinstance(a_type, (tuple, list)) and len(a_type) >= 2 and (a_type[0] == _PDF_ANNOT_TEXT or a_type[1] == "Text")) or a_type == _PDF_ANNOT_TEXT:
                        info = getattr(a, "info", None) or {}
                        content = info.get("content", "") if isinstance(info, dict) else ""
                        if not content:
                            raw_t = a.get_text()
                            content = raw_t if isinstance(raw_t, str) else str(raw_t)
                        txt = content.strip()
                        norm_rect = fitz.Rect(a.rect.x0 - rx0, a.rect.y0 - ry0, a.rect.x1 - rx0, a.rect.y1 - ry0)
                        annots.append((norm_rect, txt))
            except Exception:
                pass
            entry.annots = annots

            self._entries.append(entry)
            max_w = max(max_w, pw)
            y_off += ph + _PAGE_GAP

        total_h = y_off - _PAGE_GAP if y_off > 0 else 400
        canvas_w = max(max_w + 32, vp_w, 300)
        canvas_h = max(total_h, 400)
        self.setFixedSize(canvas_w, canvas_h)

        if anchor_ratio_y is not None and sa:
            new_scroll_y = int(round(anchor_ratio_y * canvas_h - anchor_vp_y))
            sb_v = sa.verticalScrollBar()
            sb_v.setValue(max(0, min(new_scroll_y, sb_v.maximum())))
            if anchor_ratio_x is not None:
                new_scroll_x = int(round(anchor_ratio_x * canvas_w - anchor_vp_x))
                sb_h = sa.horizontalScrollBar()
                sb_h.setValue(max(0, min(new_scroll_x, sb_h.maximum())))

        self.zoom_changed.emit(round(self._zoom_factor * 100))
        self.update()
        self._schedule_visible()

    def _visible_range(self) -> tuple[int, int]:
        from PySide6.QtWidgets import QScrollArea as _SA
        vp = self.parent()
        sa = vp.parent() if vp else None
        n = len(self._entries)
        if not n:
            return (0, 0)
        if not isinstance(sa, _SA):
            return (0, min(n - 1, _BUFFER_PGS * 2))
        y0 = sa.verticalScrollBar().value()
        vp_h = sa.viewport().height()
        y1 = y0 + (vp_h if vp_h > 0 else 600)
        first = last = 0
        found = False
        for i, entry in enumerate(self._entries):
            if not found and entry.y_off + entry.h >= y0:
                first = i
                found = True
            if entry.y_off <= y1:
                last = i
        return (max(0, first - _BUFFER_PGS), min(n - 1, last + _BUFFER_PGS))

    def on_scroll(self):
        self._schedule_visible()

    def _schedule_visible(self):
        if not self._entries or not self._path:
            return
        first, last = self._visible_range()
        dpr = self.devicePixelRatioF() or 1.0
        gen = self._gen
        pool = QThreadPool.globalInstance()
        pool.setMaxThreadCount(_MAX_THREADS)
        for i in range(first, last + 1):
            entry = self._entries[i]
            if entry.pixmap is None and i not in self._pending:
                self._pending.add(i)
                src_idx = entry.src_page
                rot = self._page_rotations.get(src_idx, 0)
                crop = self._page_crops.get(src_idx)
                job = _PageJob(
                    self._path, self._password, src_idx,
                    self._zoom, dpr, gen, self._render_signals,
                    night_mode=self._night_mode, rotation=rot,
                    crop=crop, pos=i,
                )
                pool.start(job)

    def _on_page_ready(self, gen: int, pos: int, pixmap, words):
        if gen != self._gen:
            return
        self._pending.discard(pos)
        if 0 <= pos < len(self._entries):
            entry: Any = self._entries[pos]
            entry.pixmap = pixmap
            entry.prev_pixmap = None
            entry.words = words
            self.update()

    # ── Screen and UI Events ──────────────────────────────────────────────

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
        for e in self._entries:
            if e.pixmap is not None:
                e.prev_pixmap = e.pixmap
                e.pixmap = None
        self._schedule_visible()
        self.update()

    def mousePressEvent(self, e):
        self._interaction.mouse_press(e)

    def mouseMoveEvent(self, e):
        self._interaction.mouse_move(e)

    def mouseDoubleClickEvent(self, e):
        self._interaction.mouse_double_click(e)

    def mouseReleaseEvent(self, e):
        self._interaction.mouse_release(e)

    def keyPressEvent(self, e):
        if not self._interaction.key_press(e):
            super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        self._interaction.context_menu(e)

    def paintEvent(self, event):
        CanvasPainter.paint(self, event)

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

