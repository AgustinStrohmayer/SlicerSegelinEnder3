"""Pannable, zoomable QGraphicsView.

Emits ``cursorMoved(y, z)`` whenever the mouse hovers a position and
``transformChanged()`` whenever zoom or scroll change — both feed the
rulers, coord readout and zoom badge.
"""
from __future__ import annotations

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QPainter, QResizeEvent, QWheelEvent
from PyQt6.QtWidgets import QGraphicsView

_ZOOM_FACTOR = 1.15


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
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setMouseTracking(True)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        # Mathematical Y axis (up), as in the legacy app.
        self.scale(1.0, -1.0)
        self._panning = False
        self._space_held = False

    # ── input ────────────────────────────────────────────────────────
    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = _ZOOM_FACTOR if event.angleDelta().y() > 0 else 1 / _ZOOM_FACTOR
            self.scale(factor, factor)
            self.transformChanged.emit()
            event.accept()
            return
        super().wheelEvent(event)
        self.transformChanged.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            event.accept()
            return
        if event.key() == Qt.Key.Key_F and not event.modifiers():
            self.fit_to_content()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_held = False
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            fake = QMouseEvent(
                event.type(),
                event.position(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
            super().mousePressEvent(fake)
            event.accept()
            return
        if (
            event.button() == Qt.MouseButton.LeftButton
            and not self._space_held
            and self.dragMode() != QGraphicsView.DragMode.ScrollHandDrag
        ):
            pt = self.mapToScene(event.position().toPoint())
            self.clicked.emit(pt.x(), pt.y())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pt = self.mapToScene(event.position().toPoint())
        self.cursorMoved.emit(pt.x(), pt.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.setDragMode(
                QGraphicsView.DragMode.ScrollHandDrag if self._space_held else QGraphicsView.DragMode.RubberBandDrag
            )
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
