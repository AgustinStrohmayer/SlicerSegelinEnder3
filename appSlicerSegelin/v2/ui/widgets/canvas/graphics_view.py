"""Pannable, zoomable QGraphicsView.

Navigation is mouse-first: the wheel zooms toward the cursor, dragging
with the left or middle button pans, and Shift+wheel scrolls sideways.
A left press that doesn't drag is reported as ``clicked`` for picking
(entry point, diagonal cuts). Emits ``cursorMoved(y, z)`` on hover and
``transformChanged()`` on any zoom/scroll — both feed the rulers,
coord readout and zoom badge.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QPainter, QResizeEvent, QWheelEvent
from PyQt6.QtWidgets import QGraphicsView

_ZOOM_FACTOR = 1.15
_CLICK_SLOP = 5  # px of travel still treated as a click, not a pan


class CanvasView(QGraphicsView):
    clicked = pyqtSignal(float, float)
    cursorMoved = pyqtSignal(float, float)
    transformChanged = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setMouseTracking(True)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        # Mathematical Y axis (up), as in the legacy app.
        self.scale(1.0, -1.0)
        self._pan_active = False
        self._pan_last = QPoint()
        self._press_pos = QPoint()
        self._maybe_click = False

    # ── input ────────────────────────────────────────────────────────
    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
            self.transformChanged.emit()
            event.accept()
            return
        # Plain (or Ctrl) wheel zooms toward the cursor.
        factor = _ZOOM_FACTOR if delta > 0 else 1 / _ZOOM_FACTOR
        self.scale(factor, factor)
        self.transformChanged.emit()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_F and not event.modifiers():
            self.fit_to_content()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._pan_active = True
            self._pan_last = event.position().toPoint()
            self._press_pos = self._pan_last
            self._maybe_click = event.button() == Qt.MouseButton.LeftButton
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        if self._pan_active:
            delta = pos - self._pan_last
            self._pan_last = pos
            h = self.horizontalScrollBar()
            v = self.verticalScrollBar()
            h.setValue(h.value() - delta.x())
            v.setValue(v.value() - delta.y())
            if (pos - self._press_pos).manhattanLength() > _CLICK_SLOP:
                self._maybe_click = False
        scene_pt = self.mapToScene(pos)
        self.cursorMoved.emit(scene_pt.x(), scene_pt.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._pan_active and event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._pan_active = False
            self.viewport().unsetCursor()
            if self._maybe_click and event.button() == Qt.MouseButton.LeftButton:
                pt = self.mapToScene(event.position().toPoint())
                self.clicked.emit(pt.x(), pt.y())
            self._maybe_click = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.transformChanged.emit()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.transformChanged.emit()

    # ── public API ───────────────────────────────────────────────────
    def fit_to_content(self) -> None:
        scene = self.scene()
        if scene is None:
            return
        rect = scene.itemsBoundingRect()
        if rect.isEmpty():
            return
        margin = 0.05 * max(rect.width(), rect.height())
        rect.adjust(-margin, -margin, margin, margin)
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
        self.transformChanged.emit()

    def zoom(self, factor: float) -> None:
        self.scale(factor, factor)
        self.transformChanged.emit()

    def reset_zoom(self) -> None:
        self.resetTransform()
        self.scale(1.0, -1.0)
        self.transformChanged.emit()

    def cursor_scene_pos(self) -> QPointF:
        return self.mapToScene(self.mapFromGlobal(self.cursor().pos()))

    def zoom_percent(self) -> int:
        return round(abs(self.transform().m11()) * 100)
