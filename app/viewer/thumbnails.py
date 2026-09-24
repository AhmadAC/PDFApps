# app/viewer/thumbnails.py
"""PDFApps – PDF page thumbnails panel for the viewer sidebar with Foxit-style context actions."""

from __future__ import annotations

import contextlib
import logging
import os

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, QRect, QSize, QStandardPaths, Qt,
    QThread, QTimer, Signal, Slot, QPoint,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QListView, QStyle, QStyledItemDelegate,
    QVBoxLayout, QWidget, QMenu,
)
import qtawesome as qta

from app.constants import ACCENT, TEXT_SEC, TEXT_PRI, _LQ


_log = logging.getLogger(__name__)


class _FlushFileHandler(logging.FileHandler):
    """FileHandler that flushes + fsyncs after every record."""

    def emit(self, record):
        super().emit(record)
        with contextlib.suppress(Exception):
            self.flush()
            os.fsync(self.stream.fileno())


THUMB_LOG_NAME = "pdfapps_thumbnails.log"


def _thumb_log_path() -> str:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericDataLocation)
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
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(message)s"))
        handler.setLevel(logging.DEBUG)
        _log.addHandler(handler)
        _log.setLevel(logging.DEBUG)
        _log.info("── thumbnail debug log opened (pid=%d) ──", os.getpid())


DEFAULT_THUMB_WIDTH = 120
DEFAULT_THUMB_HEIGHT = 160
THUMB_PADDING = 12
PAGE_NUM_HEIGHT = 20
CACHE_MAX = 200
VISIBLE_BUFFER = 4
HIDDEN_WINDOW = 12


# ── Worker ────────────────────────────────────────────────────────────


class ThumbnailWorker(QThread):
    """Render a batch of page thumbnails in a background thread with rotation and crop support."""

    thumbnail_ready = Signal(int, QImage, int)
    render_failed = Signal(int, str)

    def __init__(self, doc_path: str, page_indices: list[int],
                 password: str = "", epoch: int = 0, dpr: float = 1.0,
                 rotations: dict[int, int] | None = None,
                 crops: dict[int, tuple[float, float, float, float]] | None = None,
                 thumb_w: int = DEFAULT_THUMB_WIDTH,
                 thumb_h: int = DEFAULT_THUMB_HEIGHT,
                 parent=None) -> None:
        super().__init__(parent)
        self._doc_path = doc_path
        self._pages = list(page_indices)
        self._password = password
        self._dpr = float(dpr) if dpr and dpr > 0 else 1.0
        self._epoch = epoch
        self._rotations = dict(rotations) if rotations else {}
        self._crops = dict(crops) if crops else {}
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
                    self._doc_path, exc,
                )
                return
            if self._password and doc.needs_pass:
                with contextlib.suppress(Exception):
                    doc.authenticate(self._password)
            page_count = doc.page_count
            for idx in self._pages:
                if self._cancelled:
                    break
                if idx < 0 or idx >= page_count:
                    continue
                try:
                    _log.debug(
                        "ThumbnailWorker: rendering page %d/%d",
                        idx + 1, page_count,
                    )
                    page = doc[idx]
                    if self._crops and idx in self._crops:
                        crop_rect = fitz.Rect(self._crops[idx]) & page.mediabox
                        if not crop_rect.is_empty and crop_rect.width >= 10 and crop_rect.height >= 10:
                            page.set_cropbox(crop_rect)

                    rot = self._rotations.get(idx, 0) % 360

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
                    pix = page.get_pixmap(matrix=mat, alpha=False,
                                          annots=False)
                    if pix.n != 3:
                        pix = fitz.Pixmap(fitz.csRGB, pix)

                    img = QImage(
                        pix.samples, pix.width, pix.height,
                        pix.stride, QImage.Format.Format_RGB888,
                    ).copy()
                    img.setDevicePixelRatio(self._dpr)
                    rendered += 1
                    self.thumbnail_ready.emit(idx, img, self._epoch)
                except Exception as exc:
                    _log.warning(
                        "ThumbnailWorker: failed to render page %d: %s",
                        idx + 1, exc,
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
                    requested, self._doc_path,
                )
                with contextlib.suppress(RuntimeError):
                    self.render_failed.emit(
                        self._epoch,
                        f"rendered 0/{requested} pages",
                    )


# ── Model ─────────────────────────────────────────────────────────────


class ThumbnailModel(QAbstractListModel):
    """List model: one row per page. Decoration = QPixmap thumbnail."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._page_count = 0
        self._cache: dict[int, QPixmap] = {}
        self._doc_path = ""

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._page_count

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        row = index.row()
        if row < 0 or row >= self._page_count:
            return None
        if role == Qt.ItemDataRole.DecorationRole:
            return self._cache.get(row)
        if role == Qt.ItemDataRole.DisplayRole:
            return str(row + 1)
        return None

    def set_document(self, doc_path: str, page_count: int) -> None:
        self.beginResetModel()
        self._doc_path = doc_path
        self._page_count = max(0, int(page_count))
        self._cache.clear()
        self.endResetModel()

    def clear(self) -> None:
        self.set_document("", 0)

    def clear_cache(self) -> None:
        """Clear cached pixmaps and signal decoration changes to refresh visible items."""
        self._cache.clear()
        if self._page_count > 0:
            top = self.index(0)
            bottom = self.index(self._page_count - 1)
            self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DecorationRole])

    def cache_pixmap(self, page_idx: int, pix: QPixmap) -> None:
        if page_idx in self._cache:
            self._cache.pop(page_idx, None)
        self._cache[page_idx] = pix
        while len(self._cache) > CACHE_MAX:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        idx = self.index(page_idx)
        self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])

    def cache_size(self) -> int:
        return len(self._cache)

    def has_pixmap(self, page_idx: int) -> bool:
        return page_idx in self._cache

    def refresh_decorations(self) -> None:
        if self._page_count <= 0:
            return
        top = self.index(0)
        bottom = self.index(self._page_count - 1)
        self.dataChanged.emit(top, bottom, [Qt.ItemDataRole.DecorationRole])


# ── Delegate ──────────────────────────────────────────────────────────


class ThumbnailDelegate(QStyledItemDelegate):
    """Paint each row: thumbnail + page number, with current-page
    highlight in ACCENT and hover feedback."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_page = -1
        self._dark = True
        self._thumb_w = DEFAULT_THUMB_WIDTH
        self._thumb_h = DEFAULT_THUMB_HEIGHT

    def set_current_page(self, page_idx: int) -> int:
        old = self._current_page
        self._current_page = page_idx
        return old

    def set_dark(self, dark: bool) -> None:
        self._dark = bool(dark)

    def set_thumb_size(self, w: int, h: int) -> None:
        self._thumb_w = max(60, min(360, w))
        self._thumb_h = max(80, min(480, h))

    def sizeHint(self, option, index):
        return QSize(
            self._thumb_w + 2 * THUMB_PADDING,
            self._thumb_h + 2 * THUMB_PADDING + PAGE_NUM_HEIGHT,
        )

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        page_idx = index.row()
        rect = option.rect
        pix = index.data(Qt.ItemDataRole.DecorationRole)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if page_idx == self._current_page:
            accent = QColor(ACCENT)
            accent.setAlpha(60)
            painter.setBrush(accent)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(4, 4, -4, -4), 6, 6)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            hover = QColor(255, 255, 255, 20) if self._dark \
                else QColor(0, 0, 0, 20)
            painter.setBrush(hover)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(4, 4, -4, -4), 6, 6)

        thumb_x = rect.x() + THUMB_PADDING
        thumb_y = rect.y() + THUMB_PADDING
        thumb_rect = QRect(thumb_x, thumb_y, self._thumb_w, self._thumb_h)

        if pix is not None and not pix.isNull():
            dpr = pix.devicePixelRatio() or 1.0
            scaled = pix.scaled(
                round(self._thumb_w * dpr), round(self._thumb_h * dpr),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            lw = round(scaled.width() / dpr)
            lh = round(scaled.height() / dpr)
            cx = thumb_x + (self._thumb_w - lw) // 2
            cy = thumb_y + (self._thumb_h - lh) // 2
            painter.drawPixmap(cx, cy, scaled)
            painter.setPen(QColor(0, 0, 0, 60))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(cx, cy, lw - 1, lh - 1)
        else:
            painter.setPen(QColor(TEXT_SEC))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(thumb_rect)
            painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, "…")

        if page_idx == self._current_page:
            painter.setPen(QColor(ACCENT))
        else:
            painter.setPen(QColor(TEXT_SEC))
        num_rect = QRect(
            rect.x(), thumb_y + self._thumb_h + 2,
            rect.width(), PAGE_NUM_HEIGHT,
        )
        painter.drawText(num_rect, Qt.AlignmentFlag.AlignCenter,
                         str(page_idx + 1))

        painter.restore()


# ── Custom List View with Context Menu ───────────────────────────────


class _ThumbnailListView(QListView):
    """QListView with native right click context menu for page manipulation."""

    def __init__(self, panel: ThumbnailPanel) -> None:
        super().__init__(panel)
        self._panel = panel

    def contextMenuEvent(self, event):
        pos = event.pos()
        idx = self.indexAt(pos)
        page_idx = idx.row() if idx.isValid() else self._panel._anchor
        if page_idx < 0:
            page_idx = 0
        self._panel._show_context_menu(event.globalPos(), page_idx)


# ── Panel ─────────────────────────────────────────────────────────────


class ThumbnailPanel(QWidget):
    """Sidebar container hosting the QListView of thumbnails with Foxit-style actions."""

    page_requested = Signal(int)
    action_requested = Signal(str, int)  # (action_name, page_index)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        _install_debug_log()
        self.setObjectName("thumbnail_panel")
        self._doc_path = ""
        self._password = ""
        self._rotations: dict[int, int] = {}
        self._crops: dict[int, tuple[float, float, float, float]] = {}
        self._workers: list[ThumbnailWorker] = []
        self._inflight: set[int] = set()
        self._anchor = 0
        self._epoch = 0
        self._thumb_scale = 1.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._model = ThumbnailModel(self)
        self._delegate = ThumbnailDelegate(self)

        self._view = _ThumbnailListView(self)
        self._view.setModel(self._model)
        self._view.setItemDelegate(self._delegate)
        self._view.setViewMode(QListView.ViewMode.ListMode)
        self._view.setUniformItemSizes(True)
        self._view.setMouseTracking(True)
        self._view.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self._view.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.clicked.connect(self._on_activated)
        self._view.activated.connect(self._on_activated)

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(120)
        self._scroll_timer.timeout.connect(self._render_visible)
        sb = self._view.verticalScrollBar()
        if sb is not None:
            sb.valueChanged.connect(lambda _=0: self._scroll_timer.start())
        layout.addWidget(self._view)

    # ── Context Menu (Foxit Layout) ───────────────────────────────

    def _show_context_menu(self, global_pos: QPoint, page_idx: int) -> None:
        if self._model.rowCount() <= 0:
            return

        dark = self._delegate._dark
        icon_color = TEXT_PRI if dark else _LQ

        menu = QMenu(self)

        # 1. Clipboard
        act_copy = menu.addAction(qta.icon("fa5s.copy", color=icon_color), "Copy")
        act_paste = menu.addAction(qta.icon("fa5s.paste", color=icon_color), "Paste")
        menu.addSeparator()

        # 2. Thumbnail Zoom
        act_enlarge = menu.addAction(qta.icon("fa5s.search-plus", color=icon_color), "Enlarge Page Thumbnails")
        act_reduce = menu.addAction(qta.icon("fa5s.search-minus", color=icon_color), "Reduce Page Thumbnails")
        menu.addSeparator()

        # 3. Embed actions
        act_embed = menu.addAction(qta.icon("fa5s.th-large", color=icon_color), "Embed All Page Thumbnails")
        act_rem_embed = menu.addAction(qta.icon("fa5s.th", color=icon_color), "Remove Embedded Page Thumbnails")
        menu.addSeparator()

        # 4. Insert submenu
        insert_menu = menu.addMenu(qta.icon("fa5s.file-medical", color=icon_color), "Insert Pages...")
        act_ins_blank = insert_menu.addAction(qta.icon("fa5s.file", color=icon_color), "Blank Page...")
        act_ins_file = insert_menu.addAction(qta.icon("fa5s.folder-open", color=icon_color), "From File...")

        # 5. Core Page Manipulations
        act_delete = menu.addAction(qta.icon("fa5s.trash-alt", color="#EF4444"), "Delete Pages...")
        act_extract = menu.addAction(qta.icon("fa5s.file-export", color=icon_color), "Extract Pages...")
        act_reverse = menu.addAction(qta.icon("fa5s.sort-numeric-down-alt", color=icon_color), "Reverse Pages...")
        act_replace = menu.addAction(qta.icon("fa5s.exchange-alt", color=icon_color), "Replace Pages...")
        act_swap = menu.addAction(qta.icon("fa5s.random", color=icon_color), "Swap Pages...")
        act_duplicate = menu.addAction(qta.icon("fa5s.clone", color=icon_color), "Duplicate Pages...")
        act_move = menu.addAction(qta.icon("fa5s.arrows-alt", color=icon_color), "Move Pages...")
        act_split = menu.addAction(qta.icon("fa5s.cut", color=icon_color), "Split Document...")
        menu.addSeparator()

        # 6. Page Geometry
        act_crop = menu.addAction(qta.icon("fa5s.crop-alt", color=icon_color), "Crop Pages...")
        act_resize = menu.addAction(qta.icon("fa5s.expand-arrows-alt", color=icon_color), "Resize pages...")

        rotate_menu = menu.addMenu(qta.icon("fa5s.sync-alt", color=icon_color), "Rotate Pages...")
        act_rot_right = rotate_menu.addAction(qta.icon("fa5s.redo", color=icon_color), "Rotate Right (90° Clockwise)")
        act_rot_left = rotate_menu.addAction(qta.icon("fa5s.undo", color=icon_color), "Rotate Left (90° Counter-Clockwise)")
        act_rot_180 = rotate_menu.addAction(qta.icon("fa5s.sync-alt", color=icon_color), "Rotate 180°")
        menu.addSeparator()

        # 7. Navigation & Numbering
        act_transitions = menu.addAction(qta.icon("fa5s.tv", color=icon_color), "Page Transitions...")
        act_page_nums = menu.addAction(qta.icon("fa5s.list-ol", color=icon_color), "Format Page Numbers...")
        menu.addSeparator()

        # 8. Print & Properties
        act_print = menu.addAction(qta.icon("fa5s.print", color=icon_color), "Print Pages...")
        act_props = menu.addAction(qta.icon("fa5s.info-circle", color=icon_color), "Properties...")

        selected_action = menu.exec(global_pos)
        if not selected_action:
            return

        # Action Router
        if selected_action == act_copy:
            self.action_requested.emit("copy", page_idx)
        elif selected_action == act_paste:
            self.action_requested.emit("paste", page_idx)
        elif selected_action == act_enlarge:
            self._enlarge_thumbnails()
        elif selected_action == act_reduce:
            self._reduce_thumbnails()
        elif selected_action == act_embed:
            self.action_requested.emit("embed_thumbnails", page_idx)
        elif selected_action == act_rem_embed:
            self.action_requested.emit("remove_thumbnails", page_idx)
        elif selected_action == act_ins_blank:
            self.action_requested.emit("insert_blank", page_idx)
        elif selected_action == act_ins_file:
            self.action_requested.emit("insert_file", page_idx)
        elif selected_action == act_delete:
            self.action_requested.emit("delete", page_idx)
        elif selected_action == act_extract:
            self.action_requested.emit("extract", page_idx)
        elif selected_action == act_reverse:
            self.action_requested.emit("reverse", page_idx)
        elif selected_action == act_replace:
            self.action_requested.emit("replace", page_idx)
        elif selected_action == act_swap:
            self.action_requested.emit("swap", page_idx)
        elif selected_action == act_duplicate:
            self.action_requested.emit("duplicate", page_idx)
        elif selected_action == act_move:
            self.action_requested.emit("move", page_idx)
        elif selected_action == act_split:
            self.action_requested.emit("split", page_idx)
        elif selected_action == act_crop:
            self.action_requested.emit("crop", page_idx)
        elif selected_action == act_resize:
            self.action_requested.emit("resize", page_idx)
        elif selected_action == act_rot_right:
            self.action_requested.emit("rotate_right", page_idx)
        elif selected_action == act_rot_left:
            self.action_requested.emit("rotate_left", page_idx)
        elif selected_action == act_rot_180:
            self.action_requested.emit("rotate_180", page_idx)
        elif selected_action == act_transitions:
            self.action_requested.emit("transitions", page_idx)
        elif selected_action == act_page_nums:
            self.action_requested.emit("page_numbers", page_idx)
        elif selected_action == act_print:
            self.action_requested.emit("print", page_idx)
        elif selected_action == act_props:
            self.action_requested.emit("properties", page_idx)

    def _enlarge_thumbnails(self) -> None:
        self._thumb_scale = min(2.5, round(self._thumb_scale * 1.25, 2))
        tw = int(DEFAULT_THUMB_WIDTH * self._thumb_scale)
        th = int(DEFAULT_THUMB_HEIGHT * self._thumb_scale)
        self._delegate.set_thumb_size(tw, th)
        self._model.clear_cache()
        self._stop_all_workers()
        self._inflight.clear()
        self._render_visible()
        self._view.viewport().update()

    def _reduce_thumbnails(self) -> None:
        self._thumb_scale = max(0.5, round(self._thumb_scale / 1.25, 2))
        tw = int(DEFAULT_THUMB_WIDTH * self._thumb_scale)
        th = int(DEFAULT_THUMB_HEIGHT * self._thumb_scale)
        self._delegate.set_thumb_size(tw, th)
        self._model.clear_cache()
        self._stop_all_workers()
        self._inflight.clear()
        self._render_visible()
        self._view.viewport().update()

    # ── Public API ────────────────────────────────────────────────

    def set_document(self, doc_path: str, page_count: int,
                     password: str = "") -> None:
        self._doc_path = doc_path
        self._password = password or ""
        self._rotations = {}
        self._crops = {}
        self._stop_all_workers()
        self._epoch += 1
        self._inflight.clear()
        self._anchor = 0
        self._model.set_document(doc_path, page_count)
        self._delegate.set_current_page(-1)
        _log.debug(
            "set_document: %r page_count=%d epoch=%d visible=%s",
            doc_path, page_count, self._epoch, self.isVisible(),
        )
        if page_count > 0 and doc_path:
            self._render_visible()

    def set_page_rotations(self, rotations: dict[int, int]) -> None:
        """Update preview rotation angles in memory without saving to disk."""
        self._rotations = {int(k): int(v) % 360 for k, v in rotations.items()}
        self._model.clear_cache()
        self._stop_all_workers()
        self._inflight.clear()
        self._render_visible()

    def set_page_crops(self, crops: dict[int, tuple[float, float, float, float]]) -> None:
        """Update preview crops in memory without saving to disk."""
        self._crops = {int(k): tuple(float(x) for x in v) for k, v in crops.items()}
        self._model.clear_cache()
        self._stop_all_workers()
        self._inflight.clear()
        self._render_visible()

    def clear(self) -> None:
        self._doc_path = ""
        self._password = ""
        self._rotations = {}
        self._crops = {}
        self._stop_all_workers()
        self._epoch += 1
        self._inflight.clear()
        self._anchor = 0
        self._model.clear()
        self._delegate.set_current_page(-1)

    def set_current_page(self, page_idx: int) -> None:
        if not (0 <= page_idx < self._model.rowCount()):
            return
        self._anchor = page_idx
        old = self._delegate.set_current_page(page_idx)
        idx = self._model.index(page_idx)
        self._view.setCurrentIndex(idx)
        self._view.scrollTo(
            idx, QAbstractItemView.ScrollHint.EnsureVisible)
        vp = self._view.viewport()
        if old >= 0:
            old_rect = self._view.visualRect(self._model.index(old))
            vp.update(old_rect)
        vp.update(self._view.visualRect(idx))
        self._render_visible()

    def update_theme(self, dark: bool) -> None:
        self._delegate.set_dark(dark)
        self._view.viewport().update()

    # ── Internals ─────────────────────────────────────────────────

    def _on_activated(self, index: QModelIndex) -> None:
        if index.isValid():
            self.page_requested.emit(index.row())

    def _row_height(self) -> int:
        return (self._delegate.sizeHint(None, self._model.index(0)).height()
                or 1)

    def _visible_range(self) -> list[int]:
        total = self._model.rowCount()
        if total <= 0:
            return []
        row_h = self._row_height()
        vp = self._view.viewport()
        vp_h = vp.height() if vp is not None else 0
        if vp_h <= 0 or not self._view.isVisible():
            first = max(0, self._anchor - VISIBLE_BUFFER)
            last = min(total - 1, self._anchor + HIDDEN_WINDOW)
            return list(range(first, last + 1))
        sb = self._view.verticalScrollBar()
        top = sb.value() if sb is not None else 0
        first = top // row_h
        last = (top + vp_h) // row_h
        first = max(0, first - VISIBLE_BUFFER)
        last = min(total - 1, last + VISIBLE_BUFFER)
        return list(range(first, last + 1))

    def _render_visible(self) -> None:
        if not self._doc_path or self._model.rowCount() <= 0:
            return
        self._workers = [w for w in self._workers if w.isRunning()]
        want = self._visible_range()
        missing = [p for p in want
                   if p not in self._inflight and not self._model.has_pixmap(p)]
        if not missing:
            return
        self._inflight.update(missing)
        _log.debug(
            "render_visible: want=[%d..%d] missing=%d inflight=%d "
            "cache=%d workers=%d",
            want[0] if want else -1, want[-1] if want else -1,
            len(missing), len(self._inflight),
            self._model.cache_size(), len(self._workers),
        )
        self._start_worker(missing)

    def _start_worker(self, page_indices: list[int]) -> None:
        try:
            dpr = (self._view.devicePixelRatioF()
                   or self.devicePixelRatioF() or 1.0)
        except Exception:
            dpr = 1.0
        tw = int(DEFAULT_THUMB_WIDTH * self._thumb_scale)
        th = int(DEFAULT_THUMB_HEIGHT * self._thumb_scale)
        worker = ThumbnailWorker(
            self._doc_path, page_indices, self._password, self._epoch,
            dpr, rotations=self._rotations, crops=self._crops,
            thumb_w=tw, thumb_h=th, parent=self)
        worker.thumbnail_ready.connect(
            self._on_image_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.render_failed.connect(
            self._on_render_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.finished.connect(
            self._on_worker_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._workers.append(worker)
        _log.debug("start_worker: %d pages epoch=%d",
                   len(page_indices), self._epoch)
        worker.start()

    @Slot(int, QImage, int)
    def _on_image_ready(self, page_idx: int, img: QImage, epoch: int) -> None:
        if epoch != self._epoch:
            _log.debug(
                "Dropping stale thumbnail page %d (epoch %d != %d)",
                page_idx + 1, epoch, self._epoch,
            )
            return
        self._inflight.discard(page_idx)
        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(img.devicePixelRatio())
        self._model.cache_pixmap(page_idx, pix)
        _log.debug(
            "image_ready: page %d (%dx%d) cache=%d",
            page_idx + 1, img.width(), img.height(), self._model.cache_size(),
        )

    @Slot(int, str)
    def _on_render_failed(self, epoch: int, reason: str) -> None:
        worker = self.sender()
        if isinstance(worker, ThumbnailWorker):
            self._release_inflight_for(worker)
        if epoch != self._epoch:
            return
        _log.warning(
            "Thumbnail rendering failed for %r: %s",
            self._doc_path, reason,
        )

    @Slot()
    def _on_worker_finished(self) -> None:
        worker = self.sender()
        if not isinstance(worker, ThumbnailWorker):
            return
        self._release_inflight_for(worker)
        with contextlib.suppress(ValueError):
            self._workers.remove(worker)
        worker.deleteLater()

    def _release_inflight_for(self, worker: ThumbnailWorker) -> None:
        if worker._epoch != self._epoch:
            return
        for page in worker._pages:
            if not self._model.has_pixmap(page):
                self._inflight.discard(page)

    def _stop_all_workers(self) -> None:
        workers, self._workers = self._workers, []
        for worker in workers:
            worker.cancel()
            with contextlib.suppress(RuntimeError, TypeError):
                worker.thumbnail_ready.disconnect(self._on_image_ready)
            with contextlib.suppress(RuntimeError, TypeError):
                worker.render_failed.disconnect(self._on_render_failed)
            worker.wait(2000)

    def showEvent(self, event):
        super().showEvent(event)
        if self._view is None:
            return
        _log.debug("showEvent: visible=%s cache=%d",
                   self.isVisible(), self._model.cache_size())
        self._render_visible()
        vp = self._view.viewport()
        if vp is not None:
            self._model.refresh_decorations()
            vp.update()

            def _refresh_again():
                if self._view is None:
                    return
                self._render_visible()
                self._model.refresh_decorations()
                v = self._view.viewport()
                if v is not None:
                    v.update()
            QTimer.singleShot(0, _refresh_again)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._view is None:
            return
        self._render_visible()
        vp = self._view.viewport()
        if vp is not None:
            self._model.refresh_decorations()
            vp.update()

    def closeEvent(self, event):
        self._stop_all_workers()
        super().closeEvent(event)