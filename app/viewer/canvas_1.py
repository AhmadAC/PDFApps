

# app/viewer/canvas_1.py

"""PDFApps – _SelectCanvas: continuous-scroll visual PDF viewer canvas."""

from __future__ import annotations

import contextlib
import os

import fitz
from PySide6.QtCore import QPoint, QRect, Qt, QThreadPool, Signal
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.constants import BG_INNER, _LN
from app.editor.dialogs import _SignatureDialog, load_signature_pixmap
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


class _SelectCanvas(QWidget):
    """Continuous-scroll PDF viewer canvas supporting text selection, search highlights,
    page notes, cropping, and live signature placement and resizing."""

    zoom_changed = Signal(int)
    doc_replaced = Signal(object)
    crop_selected = Signal(int, object)
    crop_applied = Signal()
    crop_undo_requested = Signal()
    crop_redo_requested = Signal()
    page_action_requested = Signal(str, object)
    text_copied = Signal(str)
    signature_committed = Signal(int, object, str)  # (page_idx, fitz.Rect, sig_path)

    # Resize handles identifiers
    HANDLE_NONE = 0
    HANDLE_TL = 1
    HANDLE_TR = 2
    HANDLE_BL = 3
    HANDLE_BR = 4

    def __init__(self):
        super().__init__()
        self._doc = None
        self._path = ""
        self._password = ""
        self._entries: list[_PageEntry] = []
        self._zoom = 1.0
        self._zoom_factor = 1.0
        self._base_avail = 300
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

        # Signature Placement & Resizing State
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

    # ── Display Modes and Themes ──────────────────────────────────────────

    def set_dark_mode(self, dark: bool):
        self._bg_color = BG_INNER if dark else _LN
        self.update()

    def set_night_mode(self, night: bool):
        if self._night_mode == night:
            return
        self._night_mode = night
        self._invalidate_and_relayout()

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
        self._invalidate_and_relayout()

    def set_page_crops(self, crops: dict[int, tuple[float, float, float, float]]):
        self._page_crops = dict(crops)
        self._invalidate_and_relayout()

    def set_page_order(self, order: list[int] | None):
        self._page_order = list(order) if order is not None else None
        self._invalidate_and_relayout()

    def set_search_highlights(self, highlights: list, current: int = -1):
        self._search_highlights = highlights
        self._search_current = current
        self.update()

    # ── Signature Flow & Placement Methods ────────────────────────────────

    def start_add_signature_flow(self, pos: QPoint | None = None):
        """Open the signature selection dialog and enter cursor placement mode."""
        dlg = _SignatureDialog(self)
        if dlg.exec() == _SignatureDialog.DialogCode.Accepted:
            path = dlg.selected_signature_path()
            if path and os.path.isfile(path):
                self.begin_signature_placement(path)

    def begin_signature_placement(self, sig_path: str):
        """Enter cursor placement mode where the signature follows the mouse."""
        if self._active_sig is not None:
            self.commit_active_signature()
        self._placing_signature = True
        self._placing_sig_path = sig_path
        self._placing_sig_pixmap = load_signature_pixmap(sig_path, max_size=(320, 140))
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def cancel_signature_placement(self):
        """Remove signature from cursor (cancel placement)."""
        self._placing_signature = False
        self._placing_sig_path = ""
        self._placing_sig_pixmap = None
        self._sig_cursor_pos = None
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.update()

    def commit_active_signature(self):
        """Commit the placed/resized signature into the PDF document."""
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
        """Discard the currently placed active signature."""
        self._active_sig = None
        self.setCursor(Qt.CursorShape.IBeamCursor)
        self.update()

    # ── Document Lifecycle ────────────────────────────────────────────────

    def load(self, doc, target_page: int = 0, path: str = "", password: str = "", target_scroll: int = -1):
        self._doc = doc
        self._path = path
        self._password = password
        self._zoom_factor = 1.0
        self._gen += 1
        self._pending.clear()
        self._open_note = None
        self._search_highlights.clear()
        self._search_current = -1
        self.cancel_signature_placement()
        self._active_sig = None
        self._interaction.clear_selection()
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

    # ── Geometry and Navigation ───────────────────────────────────────────

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

    def zoom_in(self):
        self._zoom_factor = min(5.0, round(self._zoom_factor * 1.25, 4))
        self._invalidate_and_relayout()

    def zoom_out(self):
        self._zoom_factor = max(0.2, round(self._zoom_factor / 1.25, 4))
        self._invalidate_and_relayout()

    def zoom_reset(self):
        self._zoom_factor = 1.0
        self._invalidate_and_relayout()

    def _invalidate_and_relayout(self):
        self._gen += 1
        self._pending.clear()
        for e in self._entries:
            e.pixmap = None
            e.words = None
        self._layout_and_schedule()

    def _layout_and_schedule(self):
        if not self._doc or self._doc.page_count <= 0:
            return

        if self._zoom_factor == 1.0:
            from PySide6.QtWidgets import QScrollArea as _SA
            vp = self.parent()
            sa = vp.parent() if vp else None
            avail = sa.viewport().width() - 4 if isinstance(sa, _SA) else self.width()
            self._base_avail = max(avail, 300)

        page0 = self._doc[0]
        rot0 = self._page_rotations.get(0, 0) % 360
        r0 = page0.rect
        ref_w = r0.height if rot0 in (90, 270) else r0.width
        ref_w = max(ref_w, 1.0)
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

            entry = _PageEntry(y_off, pw, ph, src_page=src_idx)

            annots = []
            try:
                for a in pg.annots() or []:
                    if a.type[0] == fitz.PDF_ANNOT_TEXT:
                        txt = a.info.get("content", "") or a.get_text() or ""
                        annots.append((a.rect, txt.strip()))
            except Exception:
                pass
            entry.annots = annots

            self._entries.append(entry)
            max_w = max(max_w, pw)
            y_off += ph + _PAGE_GAP

        total_h = y_off - _PAGE_GAP if y_off > 0 else 400
        self.setFixedSize(max(max_w, 300), max(total_h, 400))
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
            entry = self._entries[pos]
            entry.pixmap = pixmap
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
            if e.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            e.accept()
        else:
            super().wheelEvent(e)