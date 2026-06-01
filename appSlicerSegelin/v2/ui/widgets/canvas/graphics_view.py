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
    escapePressed = pyqtSignal()
    nudge = pyqtSignal(float, float)      # (dy, dz) mm for the selected element
    deleteSelection = pyqtSignal()

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
        # No scrollbars — it's an infinite-canvas feel: drag to pan, wheel to
        # zoom. The view still keeps a scroll range internally (so programmatic
        # panning via the scrollbar values keeps working), it's just not shown.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        # Mathematical Y axis (up), as in the legacy app.
        self.scale(1.0, -1.0)
        self._pan_active = False
        self._pan_last = QPoint()
        self._press_pos = QPoint()
        self._maybe_click = False
        # Direct manipulation: the window installs these. ``hit_test(QPointF)``
        # returns an opaque handle (or None); dragging on a hit grabs the object
        # instead of panning.
        self.hit_test = None
        self.on_object_drag = None       # (handle, dy, dz) live during drag
        self.on_object_drag_end = None   # (handle) on release
        self._drag_handle = None
        self._drag_last = QPointF()

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
        if event.key() == Qt.Key.Key_Escape:
            self.escapePressed.emit()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.deleteSelection.emit()
            event.accept()
            return
        arrows = {
            Qt.Key.Key_Left: (-1.0, 0.0), Qt.Key.Key_Right: (1.0, 0.0),
            Qt.Key.Key_Up: (0.0, 1.0), Qt.Key.Key_Down: (0.0, -1.0),
        }
        if event.key() in arrows:
            mods = event.modifiers()
            step = 10.0 if (mods & Qt.KeyboardModifier.ControlModifier) else (
                0.1 if (mods & Qt.KeyboardModifier.ShiftModifier) else 1.0)
            ux, uz = arrows[event.key()]
            self.nudge.emit(ux * step, uz * step)
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        # Left-press on a draggable object grabs it (move); empty space pans.
        if event.button() == Qt.MouseButton.LeftButton and self.hit_test is not None:
            handle = self.hit_test(self.mapToScene(pos))
            if handle is not None:
                self._drag_handle = handle
                self._drag_last = self.mapToScene(pos)
                self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
                event.accept()
                return
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._pan_active = True
            self._pan_last = pos
            self._press_pos = pos
            self._maybe_click = event.button() == Qt.MouseButton.LeftButton
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        scene_pt = self.mapToScene(pos)
        if self._drag_handle is not None:
            dy = scene_pt.x() - self._drag_last.x()
            dz = scene_pt.y() - self._drag_last.y()
            self._drag_last = scene_pt
            if self.on_object_drag is not None:
                self.on_object_drag(self._drag_handle, dy, dz)
            self.cursorMoved.emit(scene_pt.x(), scene_pt.y())
            return
        if self._pan_active:
            delta = pos - self._pan_last
            self._pan_last = pos
            h = self.horizontalScrollBar()
            v = self.verticalScrollBar()
            h.setValue(h.value() - delta.x())
            v.setValue(v.value() - delta.y())
            if (pos - self._press_pos).manhattanLength() > _CLICK_SLOP:
                self._maybe_click = False
        else:
            # Hover feedback: show the move cursor over grabbable objects.
            self._update_hover_cursor(scene_pt)
        self.cursorMoved.emit(scene_pt.x(), scene_pt.y())
        super().mouseMoveEvent(event)

    def _update_hover_cursor(self, scene_pt: QPointF) -> None:
        if self.hit_test is None:
            return
        grabbable = self.hit_test(scene_pt) is not None
        if grabbable:
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        elif self.viewport().cursor().shape() == Qt.CursorShape.OpenHandCursor:
            self.viewport().unsetCursor()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_handle is not None and event.button() == Qt.MouseButton.LeftButton:
            if self.on_object_drag_end is not None:
                self.on_object_drag_end(self._drag_handle)
            self._drag_handle = None
            self.viewport().unsetCursor()
            event.accept()
            return
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
