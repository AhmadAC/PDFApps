# app/viewer/thumbnail_model.py
"""Thumbnail list model and custom delegate rendering page previews and selection."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QStyle,
    QStyledItemDelegate,
)

from app.constants import ACCENT, TEXT_SEC
from app.viewer.thumbnail_worker import (
    CACHE_MAX,
    DEFAULT_THUMB_HEIGHT,
    DEFAULT_THUMB_WIDTH,
    PAGE_NUM_HEIGHT,
    THUMB_PADDING,
)


class ThumbnailModel(QAbstractListModel):
    """List model: one row per page. Decoration = QPixmap thumbnail."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._page_count = 0
        self._cache: dict[int, QPixmap] = {}
        self._doc_path = ""
        self._page_order: list[int] | None = None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else self._page_count

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        default_flags = super().flags(index)
        if index.isValid():
            return default_flags | Qt.ItemFlag.ItemIsDragEnabled
        return default_flags

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        row = index.row()
        if row < 0 or row >= self._page_count:
            return None
        if role == Qt.ItemDataRole.DecorationRole:
            return self._cache.get(row)
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                f"{row + 1} / {self._page_count}"
                if self._page_count > 0
                else str(row + 1)
            )
        return None

    def set_document(self, doc_path: str, page_count: int) -> None:
        self.beginResetModel()
        self._doc_path = doc_path
        self._page_count = max(0, int(page_count))
        self._page_order = None
        self._cache.clear()
        self.endResetModel()

    def set_page_order(self, order: list[int] | None, page_count: int) -> None:
        self.beginResetModel()
        self._page_order = list(order) if order is not None else None
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
            self.dataChanged.emit(
                top,
                bottom,
                [Qt.ItemDataRole.DecorationRole, Qt.ItemDataRole.DisplayRole],
            )

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
        self.dataChanged.emit(
            top,
            bottom,
            [Qt.ItemDataRole.DecorationRole, Qt.ItemDataRole.DisplayRole],
        )


class ThumbnailDelegate(QStyledItemDelegate):
    """Paint each row centered: thumbnail + page number in '1 / N' format,
    with multi-selection support and current-page highlight."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_page = -1
        self._total_pages = 0
        self._dark = True
        self._thumb_w = DEFAULT_THUMB_WIDTH
        self._thumb_h = DEFAULT_THUMB_HEIGHT

    def set_current_page(self, page_idx: int) -> int:
        old = self._current_page
        self._current_page = page_idx
        return old

    def set_total_pages(self, total: int) -> None:
        self._total_pages = max(0, int(total))

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

        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_current = page_idx == self._current_page

        # Highlight background box covering item
        if is_selected or is_current:
            accent = QColor(ACCENT)
            accent.setAlpha(70 if is_selected else 40)
            painter.setBrush(accent)
            if is_selected and is_current:
                painter.setPen(QPen(QColor(ACCENT), 2))
            elif is_selected:
                painter.setPen(QPen(QColor(ACCENT), 1.5))
            else:
                painter.setPen(QPen(QColor(ACCENT), 1.5, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(rect.adjusted(6, 4, -6, -4), 6, 6)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            hover = (
                QColor(255, 255, 255, 22) if self._dark else QColor(0, 0, 0, 20)
            )
            painter.setBrush(hover)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(6, 4, -6, -4), 6, 6)

        # Centered thumbnail within available row width
        thumb_w = min(self._thumb_w, max(40, rect.width() - 2 * THUMB_PADDING))
        thumb_h = self._thumb_h
        thumb_x = rect.x() + (rect.width() - thumb_w) // 2
        thumb_y = rect.y() + THUMB_PADDING
        thumb_rect = QRect(thumb_x, thumb_y, thumb_w, thumb_h)

        if pix is not None and not pix.isNull():
            dpr = pix.devicePixelRatio() or 1.0
            scaled = pix.scaled(
                round(thumb_w * dpr),
                round(thumb_h * dpr),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            lw = round(scaled.width() / dpr)
            lh = round(scaled.height() / dpr)
            cx = rect.x() + (rect.width() - lw) // 2
            cy = thumb_y + (thumb_h - lh) // 2
            painter.drawPixmap(cx, cy, scaled)
            painter.setPen(QColor(0, 0, 0, 80))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(cx, cy, lw - 1, lh - 1)
        else:
            painter.setPen(QColor(TEXT_SEC))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(thumb_rect)
            painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, "…")

        # Centered page number displaying "1 / N"
        total = self._total_pages or (
            index.model().rowCount() if index.model() else 0
        )
        label_text = (
            f"{page_idx + 1} / {total}" if total > 0 else str(page_idx + 1)
        )

        if is_selected or is_current:
            painter.setPen(QColor(ACCENT))
        else:
            painter.setPen(QColor(TEXT_SEC))

        num_rect = QRect(
            rect.x(),
            thumb_y + self._thumb_h + 2,
            rect.width(),
            PAGE_NUM_HEIGHT,
        )
        painter.drawText(num_rect, Qt.AlignmentFlag.AlignCenter, label_text)

        painter.restore()