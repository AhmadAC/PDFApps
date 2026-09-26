# app/viewer/canvas.py

"""PDFApps – _SelectCanvas: continuous scroll with lazy rendering via threads."""
from __future__ import annotations

import contextlib
import os
import shutil
import tempfile

from PySide6.QtCore import Qt, Signal, QRect, QObject, QRunnable, QThreadPool
from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtGui import QColor, QPainter, QPen, QFont
import qtawesome as qta

from app.constants import ACCENT, BG_INNER, TEXT_SEC, _LN
from app.i18n import t

_PAGE_GAP       = 4    # px between pages
_BUFFER_PGS     = 2    # extra pages to pre-render outside the visible area
_MAX_THREADS    = 2    # simultaneous render workers
_NOTE_ICON_SIZE = 22   # note icon size in pixels


# ── Worker ────────────────────────────────────────────────────────────────────

class _RenderSignals(QObject):
    page_ready = Signal(int, int, object, object)  # gen, idx, QPixmap, words


class _PageJob(QRunnable):
    """Renders a fitz page in a background thread with optional rotation and crop."""

    def __init__(self, path: str, password: str, idx: int,
                 zoom: float, dpr: float, gen: int, signals: _RenderSignals,
                 night_mode: bool = False, rotation: int = 0,
                 crop: tuple[float, float, float, float] | None = None):
        super().__init__()
        self._path       = path
        self._password   = password
        self._idx        = idx
        self._zoom       = zoom
        self._dpr        = dpr
        self._gen        = gen
        self._night_mode = night_mode
        self._rotation   = rotation
        self._crop       = crop
        self.signals     = signals
        self.setAutoDelete(True)

    def run(self):
        doc = None
        try:
            import fitz
            from PySide6.QtGui import QPixmap as QP, QImage
            doc = fitz.open(self._path)
            if self._password:
                doc.authenticate(self._password)
            page = doc[self._idx]
            if self._crop:
                crop_rect = fitz.Rect(self._crop) & page.mediabox
                if not crop_rect.is_empty and crop_rect.width >= 10 and crop_rect.height >= 10:
                    page.set_cropbox(crop_rect)
            rot = self._rotation % 360
            rz = self._zoom * self._dpr
            mat = fitz.Matrix(rz, rz)
            if rot:
                mat = mat.prerotate(rot)
            pix = page.get_pixmap(matrix=mat, alpha=False, annots=False)
            if self._night_mode:
                pix.invert_irect()
            words = page.get_text("words")
            img = pix.tobytes("png")
            qp = QP()
            if not qp.loadFromData(img):
                qi = QImage(pix.samples_mv, pix.width, pix.height,
                            pix.stride, QImage.Format.Format_RGB888)
                qp = QP.fromImage(qi.copy())
            qp.setDevicePixelRatio(self._dpr)
            self.signals.page_ready.emit(self._gen, self._idx, qp, words)
        except Exception:
            import traceback, logging
            logging.error("Page render failed:\n%s", traceback.format_exc())
        finally:
            if doc is not None:
                try: doc.close()
                except Exception: pass


# ── Page entry ─────────────────────────────────────────────────────────

class _PageEntry:
    __slots__ = ("y_off", "w", "h", "pixmap", "words", "annots")

    def __init__(self, y_off: int, w: int, h: int):
        self.y_off  = y_off
        self.w      = w
        self.h      = h
        self.pixmap = None   # QPixmap | None — filled by worker
        self.words  = None   # list | None   — filled by worker
        self.annots = None   # list | None   — [(rect, text), ...]


# ── Canvas ────────────────────────────────────────────────────────────────────

class _SelectCanvas(QWidget):
    """Continuous scroll of all pages with lazy background rendering."""

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
        self._page_rotations: dict[int, int] = {}  # page_idx -> rotation angle preview
        self._page_crops: dict[int, tuple[float, float, float, float]] = {}  # page_idx -> cropbox

        self._crop_mode   = False
        self._crop_preview = None   # dict with {"margins": (t, b, l, r), "targets": set(...)}
        self._crop_drag_start = None
        self._crop_drag_cur   = None
        self._crop_active_page = -1

        self._signals     = _RenderSignals()
        self._signals.page_ready.connect(self._on_page_ready)
        self._pool        = QThreadPool()
        self._pool.setMaxThreadCount(_MAX_THREADS)
        self._night_mode  = False
        self._drag_start  = None
        self._drag_end    = None
        self._sel_rects: list[QRect] = []
        self._sel_text    = ""
        self._open_note   = None   # (page_idx, annot_idx) of open balloon
        self._search_highlights: list[tuple[int, object]] = []
        self._search_current = -1
        self._screen_signal_window = None
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
        self._crop_mode = False
        self._crop_preview = None
        self._gen     += 1
        self._pending.clear()
        self._clear_selection()
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._layout_and_schedule(target_page=page_idx, target_scroll=target_scroll))

    def set_page_rotations(self, rotations: dict[int, int]):
        """Update in-memory preview rotations for pages without saving."""
        self._page_rotations = {int(k): int(v) % 360 for k, v in rotations.items()}
        self._invalidate_and_relayout()

    def set_page_crops(self, crops: dict[int, tuple]):
        """Update in-memory preview cropboxes for pages without saving."""
        self._page_crops = {int(k): tuple(float(x) for x in v) for k, v in crops.items()}
        self._invalidate_and_relayout()

    def set_crop_mode(self, active: bool):
        self._crop_mode = bool(active)
        self._crop_drag_start = None
        self._crop_drag_cur = None
        self._crop_active_page = -1
        if self._crop_mode:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        self.update()

    def set_crop_preview(self, crop_data: dict | None):
        self._crop_preview = crop_data
        self.update()

    def on_scroll(self):
        """Called when scroll changes — schedules newly visible pages."""
        self._schedule_visible()

    def scroll_to_page(self, idx: int) -> int:
        if 0 <= idx < len(self._entries):
            return self._entries[idx].y_off
        return 0

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
        if self._night_mode:
            self._bg_color = "#000000"
        else:
            self._bg_color = BG_INNER if dark else _LN
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
        self._crop_mode = False
        self._crop_preview = None
        if self._doc is not None:
            try:
                self._doc.close()
            except ValueError:
                pass
            self._doc = None
        self._entries = []
        self._clear_selection()
        self.setFixedSize(300, 400)
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
        for entry in self._entries:
            entry.pixmap = None
        self._schedule_visible()
        self.update()

    # ── Layout ───────────────────────────────────────────────────────────────

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

        rot0 = getattr(self, "_page_rotations", {}).get(0, 0) % 360
        r0 = self._doc[0].rect
        crop0 = getattr(self, "_page_crops", {}).get(0)
        if crop0:
            cr0 = fitz.Rect(crop0) & self._doc[0].mediabox
            if not cr0.is_empty and cr0.width >= 10 and cr0.height >= 10:
                r0 = cr0
        ref_w = r0.height if rot0 in (90, 270) else r0.width
        self._zoom = (self._base_avail / max(ref_w, 1.0)) * self._zoom_factor

        entries: list[_PageEntry] = []
        total_h = 0
        max_w   = 0
        for i in range(self._doc.page_count):
            r = self._doc[i].rect
            crop = getattr(self, "_page_crops", {}).get(i)
            if crop:
                cr = fitz.Rect(crop) & self._doc[i].mediabox
                if not cr.is_empty and cr.width >= 10 and cr.height >= 10:
                    r = cr
            rot = getattr(self, "_page_rotations", {}).get(i, 0) % 360
            if rot in (90, 270):
                pw = round(r.height * self._zoom)
                ph = round(r.width  * self._zoom)
            else:
                pw = round(r.width  * self._zoom)
                ph = round(r.height * self._zoom)
            entries.append(_PageEntry(total_h, pw, ph))
            total_h += ph + _PAGE_GAP
            max_w    = max(max_w, pw)

        self._entries = entries
        self.setFixedSize(max_w, max(total_h, 400))
        self.zoom_changed.emit(round(self._zoom_factor * 100))
        self._load_annotations()
        self._open_note = None
        self.update()

        # Apply target scroll position directly during layout
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
        for page_idx in range(self._doc.page_count):
            if page_idx >= len(self._entries):
                break
            page = self._doc[page_idx]
            notes = []
            for annot in page.annots():
                if annot.type[0] == fitz.PDF_ANNOT_TEXT:
                    txt = annot.info.get("content", "")
                    if txt:
                        notes.append((annot.rect, txt))
            self._entries[page_idx].annots = notes

    # ── Lazy render ──────────────────────────────────────────────────────────

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
                rot = getattr(self, "_page_rotations", {}).get(i, 0)
                crop = getattr(self, "_page_crops", {}).get(i)
                pool.start(_PageJob(self._path, self._password, i,
                                    self._zoom, dpr, gen, self._signals,
                                    night_mode=self._night_mode,
                                    rotation=rot,
                                    crop=crop))

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

    # ── Text selection ─────────────────────────────────────────────────────

    def _clear_selection(self):
        self._drag_start = None
        self._drag_end   = None
        self._sel_rects  = []
        self._sel_text   = ""

    def _page_word_to_screen(self, y_off: int, x0, y0, x1, y1) -> QRect:
        z = self._zoom
        return QRect(int(x0 * z), y_off + int(y0 * z),
                     max(1, int((x1 - x0) * z)),
                     max(1, int((y1 - y0) * z)))

    def _find_closest_word(self, pos) -> tuple[int, int]:
        z = self._zoom
        best_page, best_idx, best_dist = -1, -1, float("inf")
        for pi, e in enumerate(self._entries):
            if not e.words:
                continue
            if pos.y() < e.y_off - 50 or pos.y() > e.y_off + e.h + 50:
                continue
            px = pos.x() / z
            py = (pos.y() - e.y_off) / z
            for wi, w in enumerate(e.words):
                cx = (w[0] + w[2]) / 2
                cy = (w[1] + w[3]) / 2
                d = (px - cx) ** 2 + (py - cy) ** 2
                if d < best_dist:
                    best_dist = d
                    best_page = pi
                    best_idx = wi
        return best_page, best_idx

    def _compute_selection(self):
        if not self._drag_start or not self._drag_end:
            return
        p1_page, p1_word = self._find_closest_word(self._drag_start)
        p2_page, p2_word = self._find_closest_word(self._drag_end)
        if p1_page < 0 or p2_page < 0:
            return
        if (p1_page, p1_word) > (p2_page, p2_word):
            p1_page, p1_word, p2_page, p2_word = p2_page, p2_word, p1_page, p1_word
        rects, words = [], []
        for pi in range(p1_page, p2_page + 1):
            e = self._entries[pi]
            if not e.words:
                continue
            w_start = p1_word if pi == p1_page else 0
            w_end   = p2_word if pi == p2_page else len(e.words) - 1
            for wi in range(w_start, w_end + 1):
                w = e.words[wi]
                x0, y0, x1, y1 = w[0], w[1], w[2], w[3]
                if wi < w_end:
                    nw = e.words[wi + 1]
                    line_h = y1 - y0
                    overlap = min(y1, nw[3]) - max(y0, nw[1])
                    if overlap > line_h * 0.5:
                        x1 = nw[0]
                rects.append(self._page_word_to_screen(e.y_off, x0, y0, x1, y1))
                words.append(w[4])
        self._sel_rects = rects
        self._sel_text  = " ".join(words)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def _draw_crop_box(self, p: QPainter, px: int, py: int, pw: int, ph: int,
                       cx0: int, cy0: int, cx1: int, cy1: int):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 140))
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
        p.drawLine(cx1, cy1, cx1, cy1 - k)

        z = self._zoom or 1.0
        pt_w = int(round((cx1 - cx0) / z))
        pt_h = int(round((cy1 - cy0) / z))
        if pt_w > 20 and pt_h > 20:
            tag = f"{pt_w} × {pt_h} pt"
            f = QFont()
            f.setPointSize(9)
            f.setBold(True)
            p.setFont(f)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(tag) + 12
            th = fm.height() + 6
            badge_x = cx0 + 6
            badge_y = cy0 + 6
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(20, 184, 166, 220))
            p.drawRoundedRect(QRect(badge_x, badge_y, tw, th), 4, 4)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(QRect(badge_x, badge_y, tw, th), Qt.AlignmentFlag.AlignCenter, tag)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self._bg_color))

        if not self._entries:
            p.setPen(QColor(TEXT_SEC))
            f = QFont(); f.setPointSize(11); p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       t("viewer.open_prompt"))
            return

        first, last = self._visible_range()
        for i in range(first, last + 1):
            e = self._entries[i]
            x = (max(self.width(), e.w) - e.w) // 2 if self.width() > e.w else 0
            if e.pixmap:
                p.drawPixmap(x, e.y_off, e.pixmap)
            else:
                p.fillRect(x, e.y_off, e.w, e.h, QColor("#252F45"))
                p.setPen(QColor(TEXT_SEC))
                f = QFont(); f.setPointSize(9); p.setFont(f)
                p.drawText(QRect(x, e.y_off, e.w, e.h),
                           Qt.AlignmentFlag.AlignCenter, t("viewer.loading"))
            p.setPen(QPen(QColor("#0d0d1a"), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(x, e.y_off, e.w - 1, e.h - 1)

        # Note icons
        z = self._zoom
        for page_idx in range(first, last + 1):
            entry = self._entries[page_idx]
            if not entry.annots:
                continue
            for annot_idx, (rect, txt) in enumerate(entry.annots):
                px = int(rect.x0 * z)
                py = entry.y_off + int(rect.y0 * z)
                icon_r = QRect(px, py, _NOTE_ICON_SIZE, _NOTE_ICON_SIZE)
                p.setBrush(QColor("#FBBF24"))
                p.setPen(QPen(QColor("#D97706"), 1))
                p.drawRoundedRect(icon_r, 4, 4)
                fi = QFont(); fi.setPointSize(10); fi.setBold(True); p.setFont(fi)
                p.setPen(QColor("#1C1917"))
                p.drawText(icon_r, Qt.AlignmentFlag.AlignCenter, "✎")
                if self._open_note == (page_idx, annot_idx):
                    balloon_x = px + _NOTE_ICON_SIZE + 6
                    balloon_y = py
                    ft = QFont(); ft.setPointSize(9); p.setFont(ft)
                    fm = p.fontMetrics()
                    lines = txt.split("\n")
                    text_w = max(fm.horizontalAdvance(ln) for ln in lines) + 20
                    text_h = fm.height() * len(lines) + 16
                    balloon_w = max(140, min(text_w, 300))
                    balloon_h = max(36, text_h)
                    balloon_r = QRect(balloon_x, balloon_y, balloon_w, balloon_h)
                    shadow_r = QRect(balloon_x + 2, balloon_y + 2, balloon_w, balloon_h)
                    p.setBrush(QColor(0, 0, 0, 30)); p.setPen(Qt.PenStyle.NoPen)
                    p.drawRoundedRect(shadow_r, 6, 6)
                    p.setBrush(QColor("#FFFDF5")); p.setPen(QPen(QColor("#D97706"), 1))
                    p.drawRoundedRect(balloon_r, 6, 6)
                    p.setPen(QColor("#000000"))
                    text_rect = QRect(balloon_x + 10, balloon_y + 8,
                                      balloon_w - 20, balloon_h - 16)
                    p.drawText(text_rect,
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                               txt)

        # Search highlights
        for hi_idx, (pg_idx, fr) in enumerate(self._search_highlights):
            if pg_idx < first or pg_idx > last:
                continue
            ey = self._entries[pg_idx].y_off
            rx = int(fr.x0 * z)
            ry = ey + int(fr.y0 * z)
            rw = int((fr.x1 - fr.x0) * z)
            rh = int((fr.y1 - fr.y0) * z)
            if hi_idx == self._search_current:
                p.fillRect(rx, ry, rw, rh, QColor(249, 115, 22, 140))
                p.setPen(QPen(QColor("#F97316"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(rx, ry, rw, rh)
            else:
                p.fillRect(rx, ry, rw, rh, QColor(250, 204, 21, 100))

        # Selection
        for r in self._sel_rects:
            p.fillRect(r, QColor(59, 130, 246, 90))

        # Crop preview
        if (self._crop_mode and self._crop_drag_start and self._crop_drag_cur
                and 0 <= self._crop_active_page < len(self._entries)):
            i = self._crop_active_page
            e = self._entries[i]
            x = (max(self.width(), e.w) - e.w) // 2 if self.width() > e.w else 0
            start = self._crop_drag_start
            cur = self._crop_drag_cur
            cx0 = max(x, min(start.x(), cur.x()))
            cy0 = max(e.y_off, min(start.y(), cur.y()))
            cx1 = min(x + e.w, max(start.x(), cur.x()))
            cy1 = min(e.y_off + e.h, max(start.y(), cur.y()))
            self._draw_crop_box(p, x, e.y_off, e.w, e.h, cx0, cy0, cx1, cy1)
        elif self._crop_preview:
            margins = self._crop_preview.get("margins", (0, 0, 0, 0))
            targets = self._crop_preview.get("targets")
            top_m, bot_m, left_m, right_m = margins
            if any(m > 0 for m in margins):
                for i in range(first, last + 1):
                    if targets is not None and i not in targets:
                        continue
                    e = self._entries[i]
                    x = (max(self.width(), e.w) - e.w) // 2 if self.width() > e.w else 0
                    cx0 = x + int(round(left_m * z))
                    cy0 = e.y_off + int(round(top_m * z))
                    cx1 = x + e.w - int(round(right_m * z))
                    cy1 = e.y_off + e.h - int(round(bot_m * z))
                    if cx1 > cx0 and cy1 > cy0:
                        self._draw_crop_box(p, x, e.y_off, e.w, e.h, cx0, cy0, cx1, cy1)

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if self._crop_mode and e.button() == Qt.MouseButton.LeftButton:
            pos = e.position().toPoint()
            self.setFocus()
            self._crop_active_page = self.page_at_y(pos.y())
            self._crop_drag_start = pos
            self._crop_drag_cur = pos
            self.update()
            e.accept()
            return

        if e.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            self._drag_start = e.position().toPoint()
            self._drag_end   = self._drag_start
            self._sel_rects  = []
            self._sel_text   = ""
            self.update()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._crop_mode and self._crop_drag_start:
            self._crop_drag_cur = e.position().toPoint()
            self.update()
            e.accept()
            return

        if self._drag_start and (e.buttons() & Qt.MouseButton.LeftButton):
            self._drag_end = e.position().toPoint()
            self._compute_selection()
            self.update()
            e.accept()

    def mouseDoubleClickEvent(self, e):
        if self._crop_mode and e.button() == Qt.MouseButton.LeftButton:
            self.crop_applied.emit()
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def mouseReleaseEvent(self, e):
        if self._crop_mode and self._crop_drag_start:
            start = self._crop_drag_start
            end = e.position().toPoint()
            page_idx = self._crop_active_page
            self._crop_drag_start = None
            self._crop_drag_cur = None
            if (abs(end.x() - start.x()) > 5 and abs(end.y() - start.y()) > 5
                    and 0 <= page_idx < len(self._entries)):
                entry = self._entries[page_idx]
                x_off = (max(self.width(), entry.w) - entry.w) // 2 if self.width() > entry.w else 0
                z = self._zoom
                p_x0 = max(0.0, min(start.x() - x_off, end.x() - x_off) / z)
                p_y0 = max(0.0, min(start.y() - entry.y_off, end.y() - entry.y_off) / z)
                p_x1 = min(entry.w / z, max(start.x() - x_off, end.x() - x_off) / z)
                p_y1 = min(entry.h / z, max(start.y() - entry.y_off, end.y() - entry.y_off) / z)
                pw = entry.w / z
                ph = entry.h / z
                self.crop_selected.emit(page_idx, (p_x0, p_y0, p_x1, p_y1, pw, ph))
            self.update()
            e.accept()
            return

        if e.button() != Qt.MouseButton.LeftButton or not self._drag_start:
            return
        self._drag_end = e.position().toPoint()
        is_click = (abs(self._drag_start.x() - self._drag_end.x()) < 4
                     and abs(self._drag_start.y() - self._drag_end.y()) < 4)
        if is_click:
            hit = self._note_icon_at(self._drag_end)
            if hit is not None:
                self._open_note = None if self._open_note == hit else hit
                self._drag_start = None
                self._drag_end = None
                self.update()
                e.accept()
                return
            if self._open_note is not None:
                self._open_note = None
                self.update()
        self._compute_selection()
        self._drag_start = None
        self._drag_end   = None
        if self._sel_text:
            QApplication.clipboard().setText(self._sel_text)
        self.text_copied.emit(self._sel_text)
        self.update()
        e.accept()

    def _note_icon_at(self, pos):
        z = self._zoom
        margin = 8
        for page_idx, entry in enumerate(self._entries):
            if not entry.annots:
                continue
            if pos.y() < entry.y_off - margin or pos.y() > entry.y_off + entry.h + margin:
                continue
            for annot_idx, (rect, txt) in enumerate(entry.annots):
                px = int(rect.x0 * z)
                py = entry.y_off + int(rect.y0 * z)
                hit_r = QRect(px - margin, py - margin,
                              _NOTE_ICON_SIZE + margin * 2, _NOTE_ICON_SIZE + margin * 2)
                if hit_r.contains(pos):
                    return (page_idx, annot_idx)
        return None

    # ── Keyboard ───────────────────────────────────────────────────────────────

    def keyPressEvent(self, e):
        if self._crop_mode and e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.crop_applied.emit()
            e.accept()
            return
        if self._crop_mode and (e.modifiers() & Qt.KeyboardModifier.ControlModifier):
            if e.key() == Qt.Key.Key_Z:
                if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self.crop_redo_requested.emit()
                else:
                    self.crop_undo_requested.emit()
                e.accept()
                return
            elif e.key() == Qt.Key.Key_Y:
                self.crop_redo_requested.emit()
                e.accept()
                return

        # Canvas-focused keyboard events routed to appropriate global actions
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if e.key() == Qt.Key.Key_Z:
                sb_val = self.parent().parent().verticalScrollBar().value() if self.parent() and self.parent().parent() else 0
                idx = self.page_at_y(sb_val)
                action = "redo" if (e.modifiers() & Qt.KeyboardModifier.ShiftModifier) else "undo"
                self.page_action_requested.emit(action, [idx])
                e.accept()
                return
            elif e.key() == Qt.Key.Key_Y:
                sb_val = self.parent().parent().verticalScrollBar().value() if self.parent() and self.parent().parent() else 0
                idx = self.page_at_y(sb_val)
                self.page_action_requested.emit("redo", [idx])
                e.accept()
                return
            elif e.key() == Qt.Key.Key_Left:
                sb_val = self.parent().parent().verticalScrollBar().value() if self.parent() and self.parent().parent() else 0
                idx = self.page_at_y(sb_val)
                self.page_action_requested.emit("rotate_left", [idx])
                e.accept()
                return
            elif e.key() == Qt.Key.Key_Right:
                sb_val = self.parent().parent().verticalScrollBar().value() if self.parent() and self.parent().parent() else 0
                idx = self.page_at_y(sb_val)
                self.page_action_requested.emit("rotate_right", [idx])
                e.accept()
                return
            elif e.key() == Qt.Key.Key_C and self._sel_text:
                QApplication.clipboard().setText(self._sel_text)
                e.accept()
                return

        if not self._crop_mode and e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            sb_val = self.parent().parent().verticalScrollBar().value() if self.parent() and self.parent().parent() else 0
            idx = self.page_at_y(sb_val)
            self.page_action_requested.emit("delete", [idx])
            e.accept()
            return

        super().keyPressEvent(e)

    # ── Context menu ───────────────────────────────────────────────────────

    def contextMenuEvent(self, e):
        from PySide6.QtWidgets import QMenu, QMessageBox
        pos = e.pos()
        hit = self._note_icon_at(pos)
        if hit is not None:
            menu = QMenu(self)
            delete_action = menu.addAction(t("viewer.delete_comment"))
            action = menu.exec(e.globalPos())
            if action == delete_action:
                page_idx, annot_idx = hit
                entry = self._entries[page_idx]
                if entry.annots and annot_idx < len(entry.annots):
                    rect, txt = entry.annots[annot_idx]
                    reply = QMessageBox.question(
                        self, t("msg.confirm"),
                        t("viewer.confirm_delete_comment"),
                        QMessageBox.StandardButton.Yes
                        | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if reply != QMessageBox.StandardButton.Yes:
                        return
                    if self._doc:
                        import fitz
                        from app.utils import show_error
                        backup_path = None
                        if self._path and os.path.isfile(self._path):
                            try:
                                src_dir = os.path.dirname(self._path) or "."
                                fd, backup_path = tempfile.mkstemp(
                                    prefix=".pdfapps_backup_",
                                    suffix=".pdf.bak",
                                    dir=src_dir,
                                )
                                os.close(fd)
                                shutil.copy2(self._path, backup_path)
                            except Exception as exc:
                                if backup_path:
                                    with contextlib.suppress(Exception):
                                        os.unlink(backup_path)
                                    backup_path = None
                                show_error(self, exc)
                                return
                        target_annot = None
                        try:
                            page = self._doc[page_idx]
                            for annot in page.annots() or []:
                                if annot.type[0] != fitz.PDF_ANNOT_TEXT:
                                    continue
                                content = annot.info.get("content", "") or ""
                                if content.strip() != txt.strip():
                                    continue
                                ar = annot.rect
                                if (abs(ar.x0 - rect.x0) < 1
                                        and abs(ar.y0 - rect.y0) < 1):
                                    target_annot = annot
                                    break
                            if target_annot is None:
                                for annot in page.annots() or []:
                                    if annot.type[0] != fitz.PDF_ANNOT_TEXT:
                                        continue
                                    content = annot.info.get("content", "") or ""
                                    if content.strip() == txt.strip():
                                        target_annot = annot
                                        break
                            if target_annot is not None:
                                page.delete_annot(target_annot)
                            else:
                                if backup_path:
                                    with contextlib.suppress(Exception):
                                        os.unlink(backup_path)
                                QMessageBox.warning(
                                    self, t("msg.warning"),
                                    t("viewer.delete_no_match"))
                                return
                        except Exception as exc:
                            if backup_path:
                                with contextlib.suppress(Exception):
                                    os.unlink(backup_path)
                            show_error(self, exc)
                            return
                        if self._path:
                            self._prepare_for_save()
                            try:
                                self._doc.saveIncr()
                            except Exception as exc:
                                if backup_path:
                                    with contextlib.suppress(Exception):
                                        shutil.move(backup_path, self._path)
                                    backup_path = None
                                new_doc = self._reopen_document()
                                if new_doc is not None:
                                    self._schedule_visible()
                                show_error(self, exc)
                                return
                        if backup_path:
                            with contextlib.suppress(Exception):
                                os.unlink(backup_path)
                    entry.annots.pop(annot_idx)
                    if self._open_note is not None:
                        open_page, open_idx = self._open_note
                        if open_page == page_idx:
                            if open_idx == annot_idx:
                                self._open_note = None
                            elif open_idx > annot_idx:
                                self._open_note = (open_page, open_idx - 1)
                    self._schedule_visible()
                    self.update()
            return
        if not self._sel_text:
            return
        menu = QMenu(self)
        act  = menu.addAction(
            qta.icon("fa5s.copy", color=TEXT_SEC),
            t("viewer.copy_chars", n=len(self._sel_text)))
        act.triggered.connect(lambda: QApplication.clipboard().setText(self._sel_text))
        menu.exec(e.globalPos())