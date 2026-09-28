"""PDFApps – _SelectCanvas: Facade widget providing continuous scroll with lazy rendering."""
from __future__ import annotations

import contextlib
from PySide6.QtCore import QPoint, QRect, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import QWidget

from app.constants import BG_INNER, _LN
from app.viewer.canvas_interaction import CanvasInteractionHandler
from app.viewer.canvas_painter import CanvasPainter
from app.viewer.canvas_worker import (
    _BUFFER_PGS,
    _MAX_THREADS,
    _NOTE_ICON_SIZE,
    _PAGE_GAP,
    _PageEntry,
    _PageJob,
    _RenderSignals,
)

# Re-export definitions for backwards compatibility
__all__ = ["_SelectCanvas", "_PageEntry", "_PageJob", "_RenderSignals", "_PAGE_GAP", "_NOTE_ICON_SIZE"]


class _SelectCanvas(QWidget):
    """Continuous scroll of all pages with lazy background rendering (Facade)."""

    zoom_changed        = Signal(int)   # current zoom percentage
    text_copied         = Signal(str)   # copied text (empty = no text layer)
    doc_replaced        = Signal(object)  # new fitz.Document after a close/reopen
    crop_selected       = Signal(int, object)  # (page_idx, (x0, y0, x1, y1, pw, ph))
    crop_applied        = Signal()
    crop_undo_requested = Signal()
    crop_redo_requested = Signal()
    page_action_requested = Signal(str, object)  # (action, list[int])

    def __init__(self):
        super().__init__()
        self._doc         = None    # fitz.Document (main thread only)
        self._path        = ""
        self._password    = ""
        self._zoom        = 1.0
        self._zoom_factor = 1.0
        self._base_avail  = 700
        self._entries: list[_PageEntry] = []
        self._gen         = 0       # generation — invalidates old renders
        self._pending: set[int] = set()
        self._page_rotations: dict[int, int] = {}
        self._page_crops: dict[int, tuple[float, float, float, float]] = {}
        self._page_order: list[int] | None = None

        self._crop_mode   = False
        self._crop_preview = None
        self._crop_drag_start: QPoint | None = None
        self._crop_drag_cur: QPoint | None = None
        self._crop_active_page = -1

        self._numbers_preview: dict | None = None

        self._signals     = _RenderSignals()
        self._signals.page_ready.connect(self._on_page_ready)
        self._pool        = QThreadPool()
        self._pool.setMaxThreadCount(_MAX_THREADS)
        self._night_mode  = False
        self._drag_start: QPoint | None = None
        self._drag_end: QPoint | None = None
        self._sel_rects: list[QRect] = []
        self._sel_text    = ""
        self._open_note   = None   # (page_idx, annot_idx) of open balloon
        self._search_highlights: list[tuple[int, object]] = []
        self._search_current = -1
        self._screen_signal_window = None

        self._interaction = CanvasInteractionHandler(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.setMinimumSize(300, 400)
        self._bg_color = BG_INNER

    # ── Public API ───────────────────────────────────────────────────────────

    def load(self, doc, page_idx: int = 0, path: str = "", password: str = "", target_scroll: int = -1):
        self._doc      = doc
        self._path     = path or (doc.name if doc else "")
        self._password = password
        self._zoom_factor = 1.0
        self._page_rotations = {}
        self._page_crops = {}
        self._page_order = None
        self._crop_mode = False
        self._crop_preview = None
        self._numbers_preview = None
        self._gen     += 1
        self._pending.clear()
        self._interaction.clear_selection()
        QTimer.singleShot(0, lambda: self._layout_and_schedule(target_page=page_idx, target_scroll=target_scroll))

    def set_page_rotations(self, rotations: dict[int, int]):
        self._page_rotations = {int(k): int(v) % 360 for k, v in rotations.items()}
        self._invalidate_and_relayout()

    def set_page_crops(self, crops: dict[int, tuple]):
        self._page_crops = {int(k): tuple(float(x) for x in v) for k, v in crops.items()}
        self._invalidate_and_relayout()

    def set_page_order(self, order: list[int] | None):
        self._page_order = [int(x) for x in order] if order is not None else None
        self._invalidate_and_relayout()

    def set_crop_mode(self, active: bool):
        self._crop_mode = bool(active)
        self._crop_drag_start = None
        self._crop_drag_cur = None
        self._crop_active_page = -1
        self.setCursor(Qt.CursorShape.CrossCursor if self._crop_mode else Qt.CursorShape.IBeamCursor)
        self.update()

    def set_crop_preview(self, crop_data: dict | None):
        self._crop_preview = crop_data
        self.update()

    def set_numbers_preview(self, preview_data: dict | None):
        self._numbers_preview = preview_data
        self.update()

    def on_scroll(self):
        self._schedule_visible()

    def scroll_to_page(self, idx: int) -> int:
        return self._entries[idx].y_off if 0 <= idx < len(self._entries) else 0

    def page_at_y(self, y: int) -> int:
        for i, e in enumerate(self._entries):
            if e.y_off <= y < e.y_off + e.h + _PAGE_GAP:
                return i
        return max(0, len(self._entries) - 1)

    def page_count(self) -> int:
        return len(self._entries)

    def set_search_highlights(self, highlights: list, current: int = -1):
        self._search_highlights = highlights
        self._search_current = current

    def zoom_in(self):
        self._zoom_factor = min(4.0, round(self._zoom_factor * 1.25, 4))
        self._invalidate_and_relayout()

    def zoom_out(self):
        self._zoom_factor = max(0.2, round(self._zoom_factor / 1.25, 4))
        self._invalidate_and_relayout()

    def zoom_reset(self):
        self._zoom_factor = 1.0
        self._invalidate_and_relayout()

    def set_dark_mode(self, dark: bool):
        self._bg_color = "#000000" if self._night_mode else (BG_INNER if dark else _LN)
        self.update()

    def set_night_mode(self, active: bool):
        if self._night_mode == active:
            return
        self._night_mode = active
        self._bg_color = "#000000" if active else BG_INNER
        self._invalidate_and_relayout()

    def close_doc(self):
        self._gen += 1
        self._pending.clear()
        self._page_rotations = {}
        self._page_crops = {}
        self._page_order = None
        self._crop_mode = False
        self._crop_preview = None
        self._numbers_preview = None
        if self._doc is not None:
            with contextlib.suppress(ValueError):
                self._doc.close()
            self._doc = None
        self._entries = []
        self._interaction.clear_selection()
        self.setFixedSize(300, 400)
        self.update()

    # ── Qt Event Hooks ───────────────────────────────────────────────────────

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

    def paintEvent(self, event):
        CanvasPainter.paint(self, event)

    def mousePressEvent(self, event):
        self._interaction.mouse_press(event)

    def mouseMoveEvent(self, event):
        self._interaction.mouse_move(event)

    def mouseDoubleClickEvent(self, event):
        self._interaction.mouse_double_click(event)
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        self._interaction.mouse_release(event)

    def keyPressEvent(self, event):
        if not self._interaction.key_press(event):
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        self._interaction.context_menu(event)

    # ── Delegated / Helper Methods ───────────────────────────────────────────

    def _clear_selection(self):
        self._interaction.clear_selection()

    def _page_word_to_screen(self, y_off: int, x0: float, y0: float, x1: float, y1: float) -> QRect:
        return self._interaction.page_word_to_screen(y_off, x0, y0, x1, y1)

    def _find_closest_word(self, pos: QPoint) -> tuple[int, int]:
        return self._interaction.find_closest_word(pos)

    def _compute_selection(self):
        self._interaction.compute_selection()

    def _note_icon_at(self, pos: QPoint):
        return self._interaction.note_icon_at(pos)

    def _on_screen_changed(self, _screen):
        self._gen += 1
        self._pending.clear()
        for entry in self._entries:
            entry.pixmap = None
        self._schedule_visible()
        self.update()

    def _invalidate_and_relayout(self):
        self._gen += 1
        self._pending.clear()
        for e in self._entries:
            e.pixmap = None
        self._layout_and_schedule()

    def _layout_and_schedule(self, target_page: int = 0, target_scroll: int = -1):
        if not self._doc or self._doc.page_count == 0:
            return
        import fitz

        if self._zoom_factor == 1.0:
            from PySide6.QtWidgets import QScrollArea as _SA
            vp = self.parent()
            sa = vp.parent() if vp else None
            avail = sa.viewport().width() - 4 if isinstance(sa, _SA) else self.width()
            self._base_avail = max(avail, 300)

        if self._page_order is not None:
            page_indices = [p for p in self._page_order if 0 <= p < self._doc.page_count]
        else:
            page_indices = list(range(self._doc.page_count))

        if not page_indices:
            self._entries = []
            self.setFixedSize(300, 400)
            self.update()
            return

        ref_idx = page_indices[0]
        rot0 = self._page_rotations.get(ref_idx, 0) % 360
        r0 = self._doc[ref_idx].rect
        crop0 = self._page_crops.get(ref_idx)
        if crop0:
            cr0 = fitz.Rect(crop0) & self._doc[ref_idx].mediabox
            if not cr0.is_empty and cr0.width >= 10 and cr0.height >= 10:
                r0 = cr0
        ref_w = r0.height if rot0 in (90, 270) else r0.width
        self._zoom = (self._base_avail / max(ref_w, 1.0)) * self._zoom_factor

        entries: list[_PageEntry] = []
        total_h, max_w = 0, 0
        for pos, src_idx in enumerate(page_indices):
            r = self._doc[src_idx].rect
            crop = self._page_crops.get(src_idx)
            if crop:
                cr = fitz.Rect(crop) & self._doc[src_idx].mediabox
                if not cr.is_empty and cr.width >= 10 and cr.height >= 10:
                    r = cr
            rot = self._page_rotations.get(src_idx, 0) % 360
            if rot in (90, 270):
                pw = round(r.height * self._zoom)
                ph = round(r.width  * self._zoom)
            else:
                pw = round(r.width  * self._zoom)
                ph = round(r.height * self._zoom)
            entry = _PageEntry(total_h, pw, ph, src_page=src_idx)
            entries.append(entry)
            total_h += ph + _PAGE_GAP
            max_w    = max(max_w, pw)

        self._entries = entries
        self.setFixedSize(max(max_w, 300), max(total_h, 400))
        self.zoom_changed.emit(round(self._zoom_factor * 100))
        self._load_annotations()
        self._open_note = None
        self.update()

        vp = self.parent()
        sa = vp.parent() if vp else None
        if sa and hasattr(sa, "verticalScrollBar"):
            if target_scroll >= 0:
                sa.verticalScrollBar().setValue(min(target_scroll, sa.verticalScrollBar().maximum()))
            elif 0 < target_page < len(self._entries):
                sa.verticalScrollBar().setValue(self._entries[target_page].y_off)

        self._schedule_visible()

    def _load_annotations(self):
        if not self._doc:
            return
        import fitz
        for pos, entry in enumerate(self._entries):
            src_idx = getattr(entry, "src_page", pos)
            if src_idx >= self._doc.page_count:
                continue
            page = self._doc[src_idx]
            notes = []
            for annot in page.annots():
                if annot.type[0] == fitz.PDF_ANNOT_TEXT:
                    txt = annot.info.get("content", "")
                    if txt:
                        notes.append((annot.rect, txt))
            entry.annots = notes

    def _visible_range(self) -> tuple[int, int]:
        from PySide6.QtWidgets import QScrollArea as _SA
        vp = self.parent()
        sa = vp.parent() if vp else None
        n  = len(self._entries)
        if not isinstance(sa, _SA) or not n:
            return (0, min(n - 1, _BUFFER_PGS * 2))

        y0 = sa.verticalScrollBar().value()
        y1 = y0 + sa.viewport().height()

        first = last = 0
        found = False
        for i, e in enumerate(self._entries):
            if not found and e.y_off + e.h >= y0:
                first = i
                found = True
            if e.y_off <= y1:
                last = i

        return (max(0, first - _BUFFER_PGS), min(n - 1, last + _BUFFER_PGS))

    def _schedule_visible(self):
        if not self._entries or not self._path:
            return
        first, last = self._visible_range()
        dpr = self.devicePixelRatioF() or 1.0
        gen = self._gen
        pool = self._pool
        for i in range(first, last + 1):
            e = self._entries[i]
            if e.pixmap is None and i not in self._pending:
                self._pending.add(i)
                src_idx = getattr(e, "src_page", i)
                rot = self._page_rotations.get(src_idx, 0)
                crop = self._page_crops.get(src_idx)
                pool.start(_PageJob(
                    self._path, self._password, src_idx,
                    self._zoom, dpr, gen, self._signals,
                    night_mode=self._night_mode,
                    rotation=rot,
                    crop=crop,
                    pos=i,
                ))

    def _on_page_ready(self, gen: int, idx: int, pixmap, words):
        if gen != self._gen:
            return
        self._pending.discard(idx)
        if 0 <= idx < len(self._entries):
            self._entries[idx].pixmap = pixmap
            self._entries[idx].words  = words
            self.update()

    def _prepare_for_save(self, timeout_ms: int = 5000) -> bool:
        self._gen += 1
        self._pending.clear()
        return self._pool.waitForDone(timeout_ms)

    def _reopen_document(self):
        import fitz
        saved_path = self._path
        saved_password = self._password
        old_doc = self._doc
        self._doc = None
        with contextlib.suppress(Exception):
            if old_doc is not None:
                old_doc.close()
        new_doc = None
        try:
            new_doc = fitz.open(saved_path)
            if new_doc.needs_pass and saved_password:
                new_doc.authenticate(saved_password)
        except Exception:
            with contextlib.suppress(Exception):
                if new_doc is not None:
                    new_doc.close()
            new_doc = None
        self._doc = new_doc
        self.doc_replaced.emit(new_doc)
        return new_doc