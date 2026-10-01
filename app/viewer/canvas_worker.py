from __future__ import annotations

"""PDFApps – Background worker and data structures for canvas page rendering."""

import os
from PySide6.QtCore import QObject, QRunnable, Signal

_PAGE_GAP       = 4    # px between pages
_BUFFER_PGS     = 2    # extra pages to pre-render outside the visible area
_MAX_THREADS    = max(2, min(4, os.cpu_count() or 2))   # simultaneous render workers
_NOTE_ICON_SIZE = 22   # note icon size in pixels


class _RenderSignals(QObject):
    page_ready = Signal(int, int, object, object)  # gen, idx, QPixmap, words


class _PageEntry:
    __slots__ = ("y_off", "w", "h", "pixmap", "prev_pixmap", "words", "annots", "src_page")

    def __init__(self, y_off: int, w: int, h: int, src_page: int = 0):
        self.y_off       = y_off
        self.w           = w
        self.h           = h
        self.src_page    = src_page
        self.pixmap      = None   # QPixmap | None — filled by worker
        self.prev_pixmap = None   # QPixmap | None — retained during zoom for smooth scaling
        self.words       = None   # list | None   — filled by worker
        self.annots      = None   # list | None   — [(rect, text), ...]


def sort_words_in_reading_order(raw_words: list) -> list:
    """Sort words into visual natural reading order (top-to-bottom, left-to-right lines)."""
    if not raw_words:
        return []

    lines: list[list] = []
    sorted_by_y = sorted(raw_words, key=lambda w: (w[1], w[0]))

    for w in sorted_by_y:
        placed = False
        w_h = max(6.0, w[3] - w[1])
        w_mid_y = (w[1] + w[3]) / 2.0

        for line in lines:
            line_y0 = min(lw[1] for lw in line)
            line_y1 = max(lw[3] for lw in line)
            line_mid_y = (line_y0 + line_y1) / 2.0
            line_h = max(6.0, line_y1 - line_y0)

            overlap = min(w[3], line_y1) - max(w[1], line_y0)
            if overlap > 0.40 * min(w_h, line_h) or abs(w_mid_y - line_mid_y) < min(w_h, line_h) * 0.40:
                line.append(w)
                placed = True
                break

        if not placed:
            lines.append([w])

    for line in lines:
        line.sort(key=lambda w: w[0])

    lines.sort(key=lambda line: sum((w[1] + w[3]) / 2.0 for w in line) / len(line))

    result = []
    for line_idx, line in enumerate(lines):
        for word_idx, w in enumerate(line):
            result.append((
                w[0], w[1], w[2], w[3],
                w[4],
                w[5] if len(w) > 5 else 0,
                line_idx,
                word_idx,
            ))
    return result


class _PageJob(QRunnable):
    """Renders a fitz page in a background thread with optional rotation and crop."""

    def __init__(self, path: str, password: str, idx: int,
                 zoom: float, dpr: float, gen: int, signals: _RenderSignals,
                 night_mode: bool = False, rotation: int = 0,
                 crop: tuple[float, float, float, float] | None = None,
                 pos: int | None = None):
        super().__init__()
        self._path       = path
        self._password   = password
        self._idx        = idx
        self._pos        = pos if pos is not None else idx
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
            from PySide6.QtGui import QImage, QPixmap as QP
            doc = fitz.open(self._path)
            if self._password:
                doc.authenticate(self._password)
            page = doc[self._idx]
            if self._crop:
                crop_rect = fitz.Rect(self._crop) & page.mediabox
                if not crop_rect.is_empty and crop_rect.width >= 10 and crop_rect.height >= 10:
                    page.set_cropbox(crop_rect)
            rot = self._rotation % 360
            if rot:
                page.set_rotation((page.rotation + rot) % 360)
            rz = self._zoom * self._dpr
            mat = fitz.Matrix(rz, rz)
            pix = page.get_pixmap(matrix=mat, alpha=False, annots=False)
            if self._night_mode:
                pix.invert_irect()

            raw_words = page.get_text("words")
            rx0 = page.rect.x0
            ry0 = page.rect.y0
            norm_words = []
            for w in raw_words:
                norm_words.append((
                    w[0] - rx0,
                    w[1] - ry0,
                    w[2] - rx0,
                    w[3] - ry0,
                    w[4],
                    w[5] if len(w) > 5 else 0,
                    w[6] if len(w) > 6 else 0,
                    w[7] if len(w) > 7 else 0,
                ))

            words = sort_words_in_reading_order(norm_words)

            img = pix.tobytes("png")
            qp = QP()
            if not qp.loadFromData(img):
                qi = QImage(pix.samples_mv, pix.width, pix.height,
                            pix.stride, QImage.Format.Format_RGB888)
                qp = QP.fromImage(qi.copy())
            qp.setDevicePixelRatio(self._dpr)
            self.signals.page_ready.emit(self._gen, self._pos, qp, words)
        except Exception:
            import logging, traceback
            logging.error("Page render failed:\n%s", traceback.format_exc())
        finally:
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass