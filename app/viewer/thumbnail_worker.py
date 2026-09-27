# app/viewer/thumbnail_worker.py
"""Thumbnail background rendering worker, file logging, and geometry sizing constants."""

from __future__ import annotations

import contextlib
import logging
import os

from PySide6.QtCore import QStandardPaths, QThread, Signal
from PySide6.QtGui import QImage

_log = logging.getLogger(__name__)

THUMB_LOG_NAME = "pdfapps_thumbnails.log"

DEFAULT_THUMB_WIDTH = 130
DEFAULT_THUMB_HEIGHT = 170
THUMB_PADDING = 10
PAGE_NUM_HEIGHT = 20
CACHE_MAX = 200
VISIBLE_BUFFER = 4
HIDDEN_WINDOW = 12


class _FlushFileHandler(logging.FileHandler):
    """FileHandler that flushes + fsyncs after every record."""

    def emit(self, record):
        super().emit(record)
        with contextlib.suppress(Exception):
            self.flush()
            os.fsync(self.stream.fileno())


def _thumb_log_path() -> str:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericDataLocation
    )
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    d = os.path.join(base, "PDFApps")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, THUMB_LOG_NAME)


def _install_debug_log() -> None:
    if not os.environ.get("PDFAPPS_THUMB_DEBUG"):
        return
    for h in _log.handlers:
        if isinstance(h, _FlushFileHandler):
            return
    with contextlib.suppress(Exception):
        log_path = _thumb_log_path()
        handler = _FlushFileHandler(log_path, mode="a", encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        handler.setLevel(logging.DEBUG)
        _log.addHandler(handler)
        _log.setLevel(logging.DEBUG)
        _log.info("── thumbnail debug log opened (pid=%d) ──", os.getpid())


class ThumbnailWorker(QThread):
    """Render a batch of page thumbnails in a background thread with rotation and crop support."""

    thumbnail_ready = Signal(int, QImage, int)
    render_failed = Signal(int, str)

    def __init__(
        self,
        doc_path: str,
        page_indices: list[int],
        password: str = "",
        epoch: int = 0,
        dpr: float = 1.0,
        rotations: dict[int, int] | None = None,
        crops: dict[int, tuple[float, float, float, float]] | None = None,
        page_order: list[int] | None = None,
        thumb_w: int = DEFAULT_THUMB_WIDTH,
        thumb_h: int = DEFAULT_THUMB_HEIGHT,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._doc_path = doc_path
        self._pages = list(page_indices)
        self._password = password
        self._dpr = float(dpr) if dpr and dpr > 0 else 1.0
        self._epoch = epoch
        self._rotations = dict(rotations) if rotations else {}
        self._crops = dict(crops) if crops else {}
        self._page_order = list(page_order) if page_order is not None else None
        self._thumb_w = thumb_w
        self._thumb_h = thumb_h
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        requested = len(self._pages)
        rendered = 0
        doc = None
        try:
            import fitz

            try:
                doc = fitz.open(self._doc_path)
            except Exception as exc:
                _log.warning(
                    "ThumbnailWorker: failed to open %r: %s",
                    self._doc_path,
                    exc,
                )
                return
            if self._password and doc.needs_pass:
                with contextlib.suppress(Exception):
                    doc.authenticate(self._password)
            page_count = doc.page_count
            for pos in self._pages:
                if self._cancelled:
                    break
                src_idx = (
                    self._page_order[pos]
                    if self._page_order is not None and pos < len(self._page_order)
                    else pos
                )
                if src_idx < 0 or src_idx >= page_count:
                    continue
                try:
                    _log.debug(
                        "ThumbnailWorker: rendering pos %d (page %d/%d)",
                        pos + 1,
                        src_idx + 1,
                        page_count,
                    )
                    page = doc[src_idx]
                    if self._crops and src_idx in self._crops:
                        crop_rect = fitz.Rect(self._crops[src_idx]) & page.mediabox
                        if (
                            not crop_rect.is_empty
                            and crop_rect.width >= 10
                            and crop_rect.height >= 10
                        ):
                            page.set_cropbox(crop_rect)

                    rot = self._rotations.get(src_idx, 0) % 360

                    rect = page.rect
                    eff_w = rect.height if rot in (90, 270) else rect.width
                    eff_h = rect.width if rot in (90, 270) else rect.height
                    tw = self._thumb_w * self._dpr
                    th = self._thumb_h * self._dpr
                    if eff_w > 0 and eff_h > 0:
                        zoom = min(tw / eff_w, th / eff_h)
                    else:
                        zoom = self._dpr
                    mat = fitz.Matrix(zoom, zoom)
                    if rot:
                        mat = mat.prerotate(rot)
                    pix = page.get_pixmap(matrix=mat, alpha=False, annots=False)
                    if pix.n != 3:
                        pix = fitz.Pixmap(fitz.csRGB, pix)

                    img = QImage(
                        pix.samples,
                        pix.width,
                        pix.height,
                        pix.stride,
                        QImage.Format.Format_RGB888,
                    ).copy()
                    img.setDevicePixelRatio(self._dpr)
                    rendered += 1
                    self.thumbnail_ready.emit(pos, img, self._epoch)
                except Exception as exc:
                    _log.warning(
                        "ThumbnailWorker: failed to render pos %d: %s",
                        pos + 1,
                        exc,
                    )
                    continue
        except Exception as exc:
            _log.error(
                "ThumbnailWorker: fatal error, no thumbnails produced: %s",
                exc,
            )
        finally:
            if doc is not None:
                with contextlib.suppress(Exception):
                    doc.close()
            if requested and rendered == 0 and not self._cancelled:
                _log.warning(
                    "ThumbnailWorker: rendered 0/%d pages for %r",
                    requested,
                    self._doc_path,
                )
                with contextlib.suppress(RuntimeError):
                    self.render_failed.emit(
                        self._epoch,
                        f"rendered 0/{requested} pages",
                    )