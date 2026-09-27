# app/viewer/thumbnails.py
"""PDFApps – PDF page thumbnails facade exposing the panel, model, delegate, view, and worker."""

from __future__ import annotations

from app.viewer.thumbnail_worker import (
    CACHE_MAX,
    DEFAULT_THUMB_HEIGHT,
    DEFAULT_THUMB_WIDTH,
    HIDDEN_WINDOW,
    PAGE_NUM_HEIGHT,
    THUMB_LOG_NAME,
    THUMB_PADDING,
    VISIBLE_BUFFER,
    ThumbnailWorker,
    _FlushFileHandler,
    _install_debug_log,
    _thumb_log_path,
)
from app.viewer.thumbnail_model import (
    ThumbnailDelegate,
    ThumbnailModel,
)
from app.viewer.thumbnail_view import (
    ThumbnailListView,
    _ThumbnailListView,
)
from app.viewer.thumbnail_panel import (
    ThumbnailPanel,
)

__all__ = [
    "CACHE_MAX",
    "DEFAULT_THUMB_HEIGHT",
    "DEFAULT_THUMB_WIDTH",
    "HIDDEN_WINDOW",
    "PAGE_NUM_HEIGHT",
    "THUMB_LOG_NAME",
    "THUMB_PADDING",
    "ThumbnailDelegate",
    "ThumbnailListView",
    "ThumbnailModel",
    "ThumbnailPanel",
    "ThumbnailWorker",
    "VISIBLE_BUFFER",
    "_FlushFileHandler",
    "_ThumbnailListView",
    "_install_debug_log",
    "_thumb_log_path",
]