# app/viewer/thumbnail_view.py
"""Thumbnail custom QListView with drag-and-drop reordering, auto-scroll, and keyboard shortcuts."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QMimeData,
    QPoint,
    QRect,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QDrag,
    QFont,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QListView,
)

from app.constants import ACCENT, TEXT_SEC

if TYPE_CHECKING:
    from app.viewer.thumbnail_panel import ThumbnailPanel

_log = logging.getLogger(__name__)


class ThumbnailListView(QListView):
    """QListView supporting multi-selection, drag-and-drop page reordering, keyboard shortcuts, and context menu."""

    def __init__(self, panel: ThumbnailPanel) -> None:
        super().__init__(panel)
        self._panel = panel
        self._drop_target_row: int = -1
        self._auto_scroll_delta: int = 0
        self._last_drag_pos: QPoint = QPoint()

        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.setInterval(30)
        self._auto_scroll_timer.timeout.connect(self._handle_auto_scroll)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self._panel._enlarge_thumbnails()
            else:
                self._panel._reduce_thumbnails()
            event.accept()
            return
        super().wheelEvent(event)

    # ── Drag & Drop Implementation ────────────────────────────────────────

    def _create_drag_pixmap(self, selected_pages: list[int]) -> QPixmap:
        n = len(selected_pages)
        if n == 0:
            return QPixmap()
        first_page = selected_pages[0]
        base_pix = self._panel._model._cache.get(first_page)

        target_w = 90
        target_h = 120
        dpr = self.devicePixelRatioF() or 1.0

        stack_offset = 5 if n > 1 else 0
        total_w = target_w + stack_offset * min(2, n - 1)
        total_h = target_h + stack_offset * min(2, n - 1)

        drag_pix = QPixmap(int(total_w * dpr), int(total_h * dpr))
        drag_pix.fill(Qt.GlobalColor.transparent)
        drag_pix.setDevicePixelRatio(dpr)

        p = QPainter(drag_pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if n > 2:
            p.setBrush(QColor(210, 220, 225, 200))
            p.setPen(QPen(QColor(120, 140, 150, 160), 1))
            p.drawRoundedRect(
                QRect(stack_offset * 2, 0, target_w, target_h), 4, 4
            )
        if n > 1:
            p.setBrush(QColor(230, 235, 240, 220))
            p.setPen(QPen(QColor(120, 140, 150, 180), 1))
            p.drawRoundedRect(
                QRect(stack_offset, stack_offset, target_w, target_h), 4, 4
            )

        front_rect = QRect(0, stack_offset * min(2, n - 1), target_w, target_h)
        p.setBrush(QColor(255, 255, 255))
        p.setPen(QPen(QColor(ACCENT), 2))
        p.drawRoundedRect(front_rect, 4, 4)

        if base_pix and not base_pix.isNull():
            scaled = base_pix.scaled(
                target_w - 6,
                target_h - 6,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            pix_dpr = scaled.devicePixelRatio() or 1.0
            scaled_w = round(scaled.width() / pix_dpr)
            scaled_h = round(scaled.height() / pix_dpr)
            cx = front_rect.x() + (target_w - scaled_w) // 2
            cy = front_rect.y() + (target_h - scaled_h) // 2
            p.drawPixmap(cx, cy, scaled)
        else:
            p.setPen(QColor(TEXT_SEC))
            p.drawText(
                front_rect, Qt.AlignmentFlag.AlignCenter, f"Page {first_page + 1}"
            )

        if n > 1:
            badge_text = f"{n} pages"
            font = QFont("Segoe UI", 9, QFont.Weight.Bold)
            p.setFont(font)
            fm = p.fontMetrics()
            bw = fm.horizontalAdvance(badge_text) + 12
            bh = fm.height() + 4
            bx = total_w - bw
            by = total_h - bh
            p.setBrush(QColor(ACCENT))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRect(bx, by, bw, bh), 4, 4)
            p.setPen(QColor(255, 255, 255))
            p.drawText(
                QRect(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, badge_text
            )

        p.end()
        return drag_pix

    def startDrag(self, supportedActions):
        selected_pages = self._panel.selected_pages()
        if (
            not selected_pages
            or not self._panel._model
            or self._panel._model.rowCount() <= 1
        ):
            return

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setData(
            "application/x-pdfapps-thumbnail-pages",
            json.dumps(selected_pages).encode("utf-8"),
        )
        drag.setMimeData(mime_data)

        pixmap = self._create_drag_pixmap(selected_pages)
        if pixmap and not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, 20))

        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._drop_target_row = -1
            self._auto_scroll_timer.stop()
            self._auto_scroll_delta = 0
            self.viewport().update()

    def _update_drop_target(self, pos: QPoint) -> int:
        count = self.model().rowCount() if self.model() else 0
        if count == 0:
            self._drop_target_row = -1
            self.viewport().update()
            return -1

        idx = self.indexAt(pos)
        if idx.isValid():
            rect = self.visualRect(idx)
            if pos.y() < rect.center().y():
                target = idx.row()
            else:
                target = idx.row() + 1
        else:
            first_rect = self.visualRect(self.model().index(0))
            last_rect = self.visualRect(self.model().index(count - 1))
            if pos.y() <= first_rect.top():
                target = 0
            elif pos.y() >= last_rect.bottom():
                target = count
            else:
                target = count
                for r in range(count):
                    r_rect = self.visualRect(self.model().index(r))
                    if pos.y() < r_rect.bottom():
                        target = r if pos.y() < r_rect.center().y() else r + 1
                        break

        target = max(0, min(target, count))
        if self._drop_target_row != target:
            self._drop_target_row = target
            self.viewport().update()
        return target

    def _handle_auto_scroll(self) -> None:
        if self._auto_scroll_delta != 0:
            sb = self.verticalScrollBar()
            if sb:
                old_val = sb.value()
                sb.setValue(sb.value() + self._auto_scroll_delta)
                if sb.value() != old_val:
                    self._update_drop_target(self._last_drag_pos)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-pdfapps-thumbnail-pages"):
            if not self.model() or self.model().rowCount() <= 1:
                event.ignore()
                return
            event.acceptProposedAction()
            self._drop_target_row = -1
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-pdfapps-thumbnail-pages"):
            pos = (
                event.position().toPoint()
                if hasattr(event, "position")
                else event.pos()
            )
            self._last_drag_pos = pos
            self._update_drop_target(pos)

            vp_height = self.viewport().height()
            margin = 40
            if pos.y() < margin:
                self._auto_scroll_delta = -max(5, int((margin - pos.y()) * 0.6))
                if not self._auto_scroll_timer.isActive():
                    self._auto_scroll_timer.start()
            elif pos.y() > vp_height - margin:
                self._auto_scroll_delta = max(
                    5, int((pos.y() - (vp_height - margin)) * 0.6)
                )
                if not self._auto_scroll_timer.isActive():
                    self._auto_scroll_timer.start()
            else:
                self._auto_scroll_delta = 0
                self._auto_scroll_timer.stop()

            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._auto_scroll_timer.stop()
        self._auto_scroll_delta = 0
        self._drop_target_row = -1
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._auto_scroll_timer.stop()
        self._auto_scroll_delta = 0
        target = self._drop_target_row
        self._drop_target_row = -1
        self.viewport().update()

        if event.mimeData().hasFormat("application/x-pdfapps-thumbnail-pages"):
            try:
                raw_bytes = bytes(
                    event.mimeData().data(
                        "application/x-pdfapps-thumbnail-pages"
                    )
                )
                pages = json.loads(raw_bytes.decode("utf-8"))
            except Exception as exc:
                _log.warning("Failed to decode dropped thumbnail pages: %s", exc)
                return

            if not pages or target < 0:
                return

            event.acceptProposedAction()
            self._panel.action_requested.emit("reorder", (pages, target))
        else:
            super().dropEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)

        # Draw insertion line when hovering during drag
        if (
            self._drop_target_row >= 0
            and self.model()
            and self.model().rowCount() > 0
        ):
            count = self.model().rowCount()
            target = max(0, min(self._drop_target_row, count))
            if target < count:
                rect = self.visualRect(self.model().index(target))
                y = rect.top()
            else:
                rect = self.visualRect(self.model().index(count - 1))
                y = rect.bottom()

            y_draw = max(2, min(y, self.viewport().height() - 2))

            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            accent_col = QColor(ACCENT)
            pen = QPen(accent_col, 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(accent_col)

            vp_w = self.viewport().width()
            x0 = 8
            x1 = vp_w - 8

            painter.drawLine(x0, y_draw, x1, y_draw)
            painter.drawEllipse(QPoint(x0, y_draw), 3, 3)
            painter.drawEllipse(QPoint(x1, y_draw), 3, 3)
            painter.end()

    # ── Key and Context Menu Handlers ─────────────────────────────────────

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            selected_pages = self._panel.selected_pages()
            if selected_pages:
                self._panel.action_requested.emit("delete", selected_pages)
                event.accept()
                return

        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Left:
                selected_pages = self._panel.selected_pages()
                if selected_pages:
                    self._panel.action_requested.emit(
                        "rotate_left", selected_pages
                    )
                    event.accept()
                    return
            elif key == Qt.Key.Key_Right:
                selected_pages = self._panel.selected_pages()
                if selected_pages:
                    self._panel.action_requested.emit(
                        "rotate_right", selected_pages
                    )
                    event.accept()
                    return
            elif key == Qt.Key.Key_Z:
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    self._panel.action_requested.emit("redo", [])
                else:
                    self._panel.action_requested.emit("undo", [])
                event.accept()
                return
            elif key == Qt.Key.Key_Y:
                self._panel.action_requested.emit("redo", [])
                event.accept()
                return

        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        pos = event.pos()
        idx = self.indexAt(pos)
        selected_indexes = self.selectedIndexes()
        selected_pages = sorted(
            {i.row() for i in selected_indexes if i.isValid()}
        )

        if idx.isValid():
            clicked_page = idx.row()
            if clicked_page not in selected_pages:
                self.setCurrentIndex(idx)
                selected_pages = [clicked_page]
        else:
            if not selected_pages:
                selected_pages = (
                    [self._panel._anchor] if self._panel._anchor >= 0 else [0]
                )

        if not selected_pages:
            selected_pages = [0]

        self._panel._show_context_menu(event.globalPos(), selected_pages)


_ThumbnailListView = ThumbnailListView