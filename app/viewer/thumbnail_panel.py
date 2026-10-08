# app/viewer/thumbnail_panel.py
"""Thumbnail panel container widget with Foxit-style actions, responsive multi-column layout, and worker orchestration."""

from __future__ import annotations

import contextlib
import json
import logging
import os

from PySide6.QtCore import (
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QMenu,
    QProxyStyle,
    QStyle,
    QVBoxLayout,
    QWidget,
)
import qtawesome as qta

from app.constants import TEXT_PRI, _LQ
from app.i18n import _CONFIG_PATH, _update_config
from app.viewer.thumbnail_model import ThumbnailDelegate, ThumbnailModel
from app.viewer.thumbnail_view import _ThumbnailListView
from app.viewer.thumbnail_worker import (
    DEFAULT_THUMB_HEIGHT,
    DEFAULT_THUMB_WIDTH,
    HIDDEN_WINDOW,
    PAGE_NUM_HEIGHT,
    THUMB_PADDING,
    VISIBLE_BUFFER,
    ThumbnailWorker,
    _install_debug_log,
)

_log = logging.getLogger(__name__)


class _ScrollableMenuStyle(QProxyStyle):
    """Enforce single-column scrollable QMenu across all platforms."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_Menu_Scrollable:
            return 1
        return super().styleHint(hint, option, widget, returnData)


class ThumbnailPanel(QWidget):
    """Sidebar container hosting the QListView of thumbnails with responsive multi-column grid support."""

    page_requested = Signal(int)
    action_requested = Signal(str, object)  # (action_name, list[int] | tuple)

    _thumb_scale_pref: float | None = None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        _install_debug_log()
        self.setObjectName("thumbnail_panel")
        self._doc_path = ""
        self._password = ""
        self._rotations: dict[int, int] = {}
        self._crops: dict[int, tuple[float, float, float, float]] = {}
        self._page_order: list[int] | None = None
        self._doc_page_count: int = 0
        self._workers: list[ThumbnailWorker] = []
        self._inflight: set[int] = set()
        self._anchor = 0
        self._epoch = 0

        if ThumbnailPanel._thumb_scale_pref is None:
            try:
                if os.path.isfile(_CONFIG_PATH):
                    with open(_CONFIG_PATH, "r", encoding="utf-8") as _f:
                        cfg = json.load(_f)
                        val = cfg.get("thumbnail_scale", 1.0)
                        ThumbnailPanel._thumb_scale_pref = max(0.5, min(2.5, float(val)))
                else:
                    ThumbnailPanel._thumb_scale_pref = 1.0
            except Exception:
                ThumbnailPanel._thumb_scale_pref = 1.0

        self._thumb_scale = ThumbnailPanel._thumb_scale_pref or 1.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._model = ThumbnailModel(self)
        self._delegate = ThumbnailDelegate(self)
        tw = int(DEFAULT_THUMB_WIDTH * self._thumb_scale)
        th = int(DEFAULT_THUMB_HEIGHT * self._thumb_scale)
        self._delegate.set_thumb_size(tw, th)

        self._view = _ThumbnailListView(self)
        self._view.setModel(self._model)
        self._view.setItemDelegate(self._delegate)
        self._view.setViewMode(QListView.ViewMode.IconMode)
        self._view.setResizeMode(QListView.ResizeMode.Adjust)
        self._view.setWrapping(True)
        self._view.setFlow(QListView.Flow.LeftToRight)
        self._view.setMovement(QListView.Movement.Static)
        self._view.setUniformItemSizes(True)
        self._view.setMouseTracking(True)
        self._view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._view.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        # Enable visual and model drag and drop reordering
        self._view.setDragEnabled(True)
        self._view.setAcceptDrops(True)
        self._view.viewport().setAcceptDrops(True)
        self._view.setDropIndicatorShown(True)
        self._view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._view.setDefaultDropAction(Qt.DropAction.MoveAction)

        self._view.clicked.connect(self._on_activated)
        self._view.activated.connect(self._on_activated)

        sm = self._view.selectionModel()
        if sm is not None:
            sm.currentChanged.connect(self._on_selection_current_changed)

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(120)
        self._scroll_timer.timeout.connect(self._render_visible)
        sb = self._view.verticalScrollBar()
        if sb is not None:
            sb.valueChanged.connect(lambda _=0: self._scroll_timer.start())
        layout.addWidget(self._view)

    # ── Multi-Column Geometry Helpers ─────────────────────────────

    def column_count(self) -> int:
        vp = self._view.viewport() if self._view else None
        if not vp:
            return 1
        vp_w = vp.width()
        if vp_w <= 10:
            return 1
        target_thumb_w = int(DEFAULT_THUMB_WIDTH * self._thumb_scale)
        min_cell_w = target_thumb_w + 16
        return max(1, vp_w // min_cell_w)

    def _update_grid_layout(self) -> None:
        vp = self._view.viewport() if self._view else None
        if not vp:
            return
        vp_w = vp.width()
        if vp_w <= 10:
            return

        target_thumb_w = int(DEFAULT_THUMB_WIDTH * self._thumb_scale)
        target_thumb_h = int(DEFAULT_THUMB_HEIGHT * self._thumb_scale)
        min_cell_w = target_thumb_w + 16

        cols = max(1, vp_w // min_cell_w)
        cell_w = max(min_cell_w, vp_w // cols)
        cell_h = target_thumb_h + 2 * THUMB_PADDING + PAGE_NUM_HEIGHT

        self._delegate.set_thumb_size(target_thumb_w, target_thumb_h)
        self._delegate.set_cell_width(cell_w)
        self._view.setGridSize(QSize(cell_w, cell_h))

    # ── Context Menu (Single-Column Scrollable Pane) ───────────────

    def _show_context_menu(
        self, global_pos: QPoint, selected_pages: list[int]
    ) -> None:
        if self._model.rowCount() <= 0:
            return

        dark = self._delegate._dark
        icon_color = TEXT_PRI if dark else _LQ
        n_sel = len(selected_pages)
        suffix = f" ({n_sel})" if n_sel > 1 else ""

        menu = QMenu(self)
        self._menu_style = _ScrollableMenuStyle(menu.style())
        menu.setStyle(self._menu_style)
        menu.setStyleSheet("QMenu { menu-scrollable: 1; }")

        # 1. Clipboard
        act_copy = menu.addAction(
            qta.icon("fa5s.copy", color=icon_color), f"Copy{suffix}"
        )
        act_paste = menu.addAction(
            qta.icon("fa5s.paste", color=icon_color), "Paste"
        )
        menu.addSeparator()

        # 2. Thumbnail Zoom and Fitting
        act_enlarge = menu.addAction(
            qta.icon("fa5s.search-plus", color=icon_color),
            "Enlarge Page Thumbnails",
        )
        act_reduce = menu.addAction(
            qta.icon("fa5s.search-minus", color=icon_color),
            "Reduce Page Thumbnails",
        )
        act_fit_window = menu.addAction(
            qta.icon("fa5s.arrows-alt-h", color=icon_color),
            "Fit Window to Thumbnails",
        )
        act_fit_width = menu.addAction(
            qta.icon("fa5s.expand-arrows-alt", color=icon_color),
            "Fit Thumbnails to Window Width",
        )
        menu.addSeparator()

        # 3. Embed actions
        act_embed = menu.addAction(
            qta.icon("fa5s.th-large", color=icon_color),
            "Embed All Page Thumbnails",
        )
        act_rem_embed = menu.addAction(
            qta.icon("fa5s.th", color=icon_color),
            "Remove Embedded Page Thumbnails",
        )
        menu.addSeparator()

        # 4. Insert submenu
        insert_menu = menu.addMenu(
            qta.icon("fa5s.file-medical", color=icon_color), "Insert Pages..."
        )
        act_ins_blank = insert_menu.addAction(
            qta.icon("fa5s.file", color=icon_color), "Blank Page..."
        )
        act_ins_file = insert_menu.addAction(
            qta.icon("fa5s.folder-open", color=icon_color), "From File..."
        )

        # 5. Core Page Manipulations
        act_delete = menu.addAction(
            qta.icon("fa5s.trash-alt", color="#EF4444"),
            f"Delete Pages{suffix}...\tDel",
        )
        act_extract = menu.addAction(
            qta.icon("fa5s.file-export", color=icon_color),
            f"Extract Pages{suffix}...",
        )
        act_reverse = menu.addAction(
            qta.icon("fa5s.sort-numeric-down-alt", color=icon_color),
            f"Reverse Pages{suffix}...",
        )
        act_replace = menu.addAction(
            qta.icon("fa5s.exchange-alt", color=icon_color), "Replace Pages..."
        )
        act_swap = menu.addAction(
            qta.icon("fa5s.random", color=icon_color), "Swap Pages..."
        )
        act_duplicate = menu.addAction(
            qta.icon("fa5s.clone", color=icon_color),
            f"Duplicate Pages{suffix}...",
        )
        act_move = menu.addAction(
            qta.icon("fa5s.arrows-alt", color=icon_color),
            f"Move Pages{suffix}...",
        )
        act_split = menu.addAction(
            qta.icon("fa5s.cut", color=icon_color), "Split Document..."
        )
        menu.addSeparator()

        # 6. Page Geometry
        act_crop = menu.addAction(
            qta.icon("fa5s.crop-alt", color=icon_color), f"Crop Pages{suffix}..."
        )
        act_resize = menu.addAction(
            qta.icon("fa5s.expand-arrows-alt", color=icon_color),
            f"Resize pages{suffix}...",
        )

        rotate_menu = menu.addMenu(
            qta.icon("fa5s.sync-alt", color=icon_color), f"Rotate Pages{suffix}..."
        )
        act_rot_right = rotate_menu.addAction(
            qta.icon("fa5s.redo", color=icon_color),
            "Rotate Right (90° Clockwise)\tCtrl+Right",
        )
        act_rot_left = rotate_menu.addAction(
            qta.icon("fa5s.undo", color=icon_color),
            "Rotate Left (90° Counter-Clockwise)\tCtrl+Left",
        )
        act_rot_180 = rotate_menu.addAction(
            qta.icon("fa5s.sync-alt", color=icon_color), "Rotate 180°"
        )
        menu.addSeparator()

        # 7. Navigation & Numbering
        act_transitions = menu.addAction(
            qta.icon("fa5s.tv", color=icon_color), "Page Transitions..."
        )
        act_page_nums = menu.addAction(
            qta.icon("fa5s.list-ol", color=icon_color),
            f"Format Page Numbers{suffix}...",
        )
        menu.addSeparator()

        # 8. Print & Properties
        act_print = menu.addAction(
            qta.icon("fa5s.print", color=icon_color), f"Print Pages{suffix}..."
        )
        act_props = menu.addAction(
            qta.icon("fa5s.info-circle", color=icon_color), "Properties..."
        )

        selected_action = menu.exec(global_pos)
        if not selected_action:
            return

        # Action Router
        if selected_action == act_copy:
            self.action_requested.emit("copy", selected_pages)
        elif selected_action == act_paste:
            self.action_requested.emit("paste", selected_pages)
        elif selected_action == act_enlarge:
            self._enlarge_thumbnails()
        elif selected_action == act_reduce:
            self._reduce_thumbnails()
        elif selected_action == act_fit_window:
            self.fit_window_to_thumbnails()
        elif selected_action == act_fit_width:
            self.fit_thumbnails_to_window()
        elif selected_action == act_embed:
            self.action_requested.emit("embed_thumbnails", selected_pages)
        elif selected_action == act_rem_embed:
            self.action_requested.emit("remove_thumbnails", selected_pages)
        elif selected_action == act_ins_blank:
            self.action_requested.emit("insert_blank", selected_pages)
        elif selected_action == act_ins_file:
            self.action_requested.emit("insert_file", selected_pages)
        elif selected_action == act_delete:
            self.action_requested.emit("delete", selected_pages)
        elif selected_action == act_extract:
            self.action_requested.emit("extract", selected_pages)
        elif selected_action == act_reverse:
            self.action_requested.emit("reverse", selected_pages)
        elif selected_action == act_replace:
            self.action_requested.emit("replace", selected_pages)
        elif selected_action == act_swap:
            self.action_requested.emit("swap", selected_pages)
        elif selected_action == act_duplicate:
            self.action_requested.emit("duplicate", selected_pages)
        elif selected_action == act_move:
            self.action_requested.emit("move", selected_pages)
        elif selected_action == act_split:
            self.action_requested.emit("split", selected_pages)
        elif selected_action == act_crop:
            self.action_requested.emit("crop", selected_pages)
        elif selected_action == act_resize:
            self.action_requested.emit("resize", selected_pages)
        elif selected_action == act_rot_right:
            self.action_requested.emit("rotate_right", selected_pages)
        elif selected_action == act_rot_left:
            self.action_requested.emit("rotate_left", selected_pages)
        elif selected_action == act_rot_180:
            self.action_requested.emit("rotate_180", selected_pages)
        elif selected_action == act_transitions:
            self.action_requested.emit("transitions", selected_pages)
        elif selected_action == act_page_nums:
            self.action_requested.emit("page_numbers", selected_pages)
        elif selected_action == act_print:
            self.action_requested.emit("print", selected_pages)
        elif selected_action == act_props:
            self.action_requested.emit("properties", selected_pages)

    def _save_thumb_scale_pref(self) -> None:
        ThumbnailPanel._thumb_scale_pref = self._thumb_scale
        try:
            scale = self._thumb_scale
            _update_config(lambda cfg: cfg.__setitem__("thumbnail_scale", scale))
        except Exception:
            pass

    def fit_window_to_thumbnails(self) -> None:
        """Resize the parent sidebar panel in the splitter to fit the thumbnails."""
        cols = self.column_count()
        tw = int(DEFAULT_THUMB_WIDTH * self._thumb_scale)
        needed_w = (tw + 2 * THUMB_PADDING) * cols + 24
        self.action_requested.emit("fit_sidebar_width", needed_w)

    def fit_thumbnails_to_window(self) -> None:
        """Scale thumbnail dimensions so they fill the current sidebar viewport width."""
        vp = self._view.viewport() if self._view else None
        vp_w = vp.width() if vp else 0
        if vp_w <= 0:
            vp_w = self.width()
        cols = self.column_count()
        avail_for_col = max(60, vp_w // cols)
        target_thumb_w = max(60, min(360, avail_for_col - 2 * THUMB_PADDING - 4))
        self._thumb_scale = round(target_thumb_w / DEFAULT_THUMB_WIDTH, 2)
        self._update_grid_layout()
        self._model.clear_cache()
        self._stop_all_workers()
        self._inflight.clear()
        self._render_visible()
        self._view.viewport().update()
        self._save_thumb_scale_pref()

    def _enlarge_thumbnails(self) -> None:
        self._thumb_scale = min(2.5, round(self._thumb_scale * 1.25, 2))
        self._update_grid_layout()
        self._model.clear_cache()
        self._stop_all_workers()
        self._inflight.clear()
        self._render_visible()
        self._view.viewport().update()
        self._save_thumb_scale_pref()

    def _reduce_thumbnails(self) -> None:
        self._thumb_scale = max(0.5, round(self._thumb_scale / 1.25, 2))
        self._update_grid_layout()
        self._model.clear_cache()
        self._stop_all_workers()
        self._inflight.clear()
        self._render_visible()
        self._view.viewport().update()
        self._save_thumb_scale_pref()

    # ── Public API ────────────────────────────────────────────────

    def selected_pages(self) -> list[int]:
        """Return the sorted list of 0-based indices of all currently selected pages."""
        if not self._view or not self._model:
            return [self._anchor] if self._anchor >= 0 else [0]
        selected_indexes = self._view.selectedIndexes()
        pages = sorted(
            {
                i.row()
                for i in selected_indexes
                if i.isValid() and 0 <= i.row() < self._model.rowCount()
            }
        )
        return (
            pages
            if pages
            else (
                [self._anchor]
                if 0 <= self._anchor < self._model.rowCount()
                else [0]
            )
        )

    def set_selected_pages(self, pages: list[int]) -> None:
        """Select the specified list of page indices in the thumbnail view and scroll into view."""
        if not self._view or not self._model or self._model.rowCount() <= 0:
            return
        selection = QItemSelection()
        for p in pages:
            if 0 <= p < self._model.rowCount():
                idx = self._model.index(p)
                selection.select(idx, idx)
        sm = self._view.selectionModel()
        if sm is not None:
            sm.select(
                selection, QItemSelectionModel.SelectionFlag.ClearAndSelect
            )
        if pages:
            first_p = min(pages)
            self._delegate.set_current_page(first_p)
            self._anchor = first_p
            idx = self._model.index(first_p)
            self._view.setCurrentIndex(idx)
            self._view.scrollTo(idx, QAbstractItemView.ScrollHint.EnsureVisible)
        vp = self._view.viewport()
        if vp is not None:
            vp.update()

    def set_document(
        self, doc_path: str, page_count: int, password: str = ""
    ) -> None:
        self._doc_path = doc_path
        self._password = password or ""
        self._rotations = {}
        self._crops = {}
        self._page_order = None
        self._doc_page_count = page_count
        self._stop_all_workers()
        self._epoch += 1
        self._inflight.clear()
        self._anchor = 0
        self._delegate.set_total_pages(page_count)
        self._model.set_document(doc_path, page_count)
        self._delegate.set_current_page(-1)
        self._update_grid_layout()
        _log.debug(
            "set_document: %r page_count=%d epoch=%d visible=%s",
            doc_path,
            page_count,
            self._epoch,
            self.isVisible(),
        )
        if page_count > 0 and doc_path:
            self._render_visible()

    def set_page_rotations(self, rotations: dict[int, int]) -> None:
        """Update preview rotation angles in memory without saving to disk."""
        self._rotations = {int(k): int(v) % 360 for k, v in rotations.items()}
        self._model.clear_cache()
        self._stop_all_workers()
        self._inflight.clear()
        self._update_grid_layout()
        self._render_visible()

    def set_page_crops(
        self, crops: dict[int, tuple[float, float, float, float]]
    ) -> None:
        """Update preview crops in memory without saving to disk."""
        self._crops = {
            int(k): (float(v[0]), float(v[1]), float(v[2]), float(v[3]))
            for k, v in crops.items()
        }
        self._model.clear_cache()
        self._stop_all_workers()
        self._inflight.clear()
        self._update_grid_layout()
        self._render_visible()

    def set_page_order(self, order: list[int] | None) -> None:
        """Update preview page order in memory without saving to disk."""
        self._page_order = [int(x) for x in order] if order is not None else None
        self._model.clear_cache()
        self._stop_all_workers()
        self._inflight.clear()
        count = len(self._page_order) if self._page_order is not None else getattr(self, "_doc_page_count", 0)
        self._delegate.set_total_pages(count)
        self._model.set_page_order(self._page_order, count)
        self._update_grid_layout()
        self._render_visible()

    def clear(self) -> None:
        self._doc_path = ""
        self._password = ""
        self._rotations = {}
        self._crops = {}
        self._page_order = None
        self._doc_page_count = 0
        self._stop_all_workers()
        self._epoch += 1
        self._inflight.clear()
        self._anchor = 0
        self._model.clear()
        self._delegate.set_total_pages(0)
        self._delegate.set_current_page(-1)

    def set_current_page(self, page_idx: int) -> None:
        if not (0 <= page_idx < self._model.rowCount()):
            return
        self._anchor = page_idx
        old = self._delegate.set_current_page(page_idx)
        idx = self._model.index(page_idx)
        if len(self._view.selectedIndexes()) <= 1:
            self._view.setCurrentIndex(idx)
        self._view.scrollTo(idx, QAbstractItemView.ScrollHint.EnsureVisible)
        vp = self._view.viewport()
        if vp is not None:
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
            self._anchor = index.row()
            self._delegate.set_current_page(index.row())
            self.page_requested.emit(index.row())
            vp = self._view.viewport()
            if vp is not None:
                vp.update()

    def _on_selection_current_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        if current.isValid():
            row = current.row()
            self._anchor = row
            self._delegate.set_current_page(row)
            self.page_requested.emit(row)
            vp = self._view.viewport()
            if vp is not None:
                vp.update()

    def _row_height(self) -> int:
        gs = self._view.gridSize()
        if gs.isValid() and gs.height() > 0:
            return gs.height()
        return (
            self._delegate.sizeHint(None, self._model.index(0)).height() or 1
        )

    def _visible_range(self) -> list[int]:
        total = self._model.rowCount()
        if total <= 0:
            return []
        row_h = self._row_height()
        vp = self._view.viewport()
        vp_h = vp.height() if vp is not None else 0
        cols = self.column_count()

        if vp_h <= 0 or not self._view.isVisible():
            first_page = max(0, self._anchor - VISIBLE_BUFFER * cols)
            last_page = min(total - 1, self._anchor + HIDDEN_WINDOW * cols)
            return list(range(first_page, last_page + 1))

        sb = self._view.verticalScrollBar()
        top = sb.value() if sb is not None else 0

        first_row = max(0, top // row_h - VISIBLE_BUFFER)
        last_row = (top + vp_h) // row_h + VISIBLE_BUFFER

        first_page = max(0, first_row * cols)
        last_page = min(total - 1, (last_row + 1) * cols - 1)
        return list(range(first_page, last_page + 1))

    def _render_visible(self) -> None:
        if not self._doc_path or self._model.rowCount() <= 0:
            return
        self._workers = [w for w in self._workers if w.isRunning()]
        want = self._visible_range()
        missing = [
            p
            for p in want
            if p not in self._inflight and not self._model.has_pixmap(p)
        ]
        if not missing:
            return
        self._inflight.update(missing)
        _log.debug(
            "render_visible: want=[%d..%d] missing=%d inflight=%d cache=%d workers=%d",
            want[0] if want else -1,
            want[-1] if want else -1,
            len(missing),
            len(self._inflight),
            self._model.cache_size(),
            len(self._workers),
        )
        self._start_worker(missing)

    def _start_worker(self, page_indices: list[int]) -> None:
        try:
            dpr = (
                self._view.devicePixelRatioF()
                or self.devicePixelRatioF()
                or 1.0
            )
        except Exception:
            dpr = 1.0
        tw = int(DEFAULT_THUMB_WIDTH * self._thumb_scale)
        th = int(DEFAULT_THUMB_HEIGHT * self._thumb_scale)
        worker = ThumbnailWorker(
            self._doc_path,
            page_indices,
            self._password,
            self._epoch,
            dpr,
            rotations=self._rotations,
            crops=self._crops,
            page_order=self._page_order,
            thumb_w=tw,
            thumb_h=th,
            parent=self,
        )
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
        _log.debug(
            "start_worker: %d pages epoch=%d", len(page_indices), self._epoch
        )
        worker.start()

    @Slot(int, QImage, int)
    def _on_image_ready(self, page_idx: int, img: QImage, epoch: int) -> None:
        if epoch != self._epoch:
            _log.debug(
                "Dropping stale thumbnail page %d (epoch %d != %d)",
                page_idx + 1,
                epoch,
                self._epoch,
            )
            return
        self._inflight.discard(page_idx)
        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(img.devicePixelRatio())
        self._model.cache_pixmap(page_idx, pix)
        _log.debug(
            "image_ready: page %d (%dx%d) cache=%d",
            page_idx + 1,
            img.width(),
            img.height(),
            self._model.cache_size(),
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
            self._doc_path,
            reason,
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
        self._update_grid_layout()
        _log.debug(
            "showEvent: visible=%s cache=%d",
            self.isVisible(),
            self._model.cache_size(),
        )
        self._render_visible()
        vp = self._view.viewport()
        if vp is not None:
            self._model.refresh_decorations()
            vp.update()

            def _refresh_again():
                if self._view is None:
                    return
                self._update_grid_layout()
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
        self._update_grid_layout()
        self._render_visible()
        vp = self._view.viewport()
        if vp is not None:
            self._model.refresh_decorations()
            vp.update()

    def closeEvent(self, event):
        self._stop_all_workers()
        super().closeEvent(event)