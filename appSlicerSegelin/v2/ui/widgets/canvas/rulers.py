"""Horizontal (Y) and vertical (Z) rulers tied to the canvas transform.

Both rulers listen to ``CanvasView.transformChanged`` and repaint
their tick marks in scene coordinates. The numeric labels stay in mm.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ..canvas.graphics_view import CanvasView

RULER_THICKNESS = 26


class _Ruler(QWidget):
    def __init__(self, view: CanvasView, horizontal: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Ruler")
        self._view = view
        self._horizontal = horizontal
        if horizontal:
            self.setFixedHeight(RULER_THICKNESS)
        else:
            self.setFixedWidth(RULER_THICKNESS)
        view.transformChanged.connect(self.update)
        view.cursorMoved.connect(lambda *_: self.update())
        self._tick_color = QColor("#384256")
        self._text_color = QColor("#8A93A6")
        self._accent = QColor("#7C5CFF")
        self._bg = QColor("#15181F")

    def set_palette(self, *, tick: str, text: str, accent: str, bg: str | None = None) -> None:
        self._tick_color = QColor(tick)
        self._text_color = QColor(text)
        self._accent = QColor(accent)
        if bg is not None:
            self._bg = QColor(bg)
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), self._bg)

        view = self._view
        if view.scene() is None:
            return

        font = QFont(self.font())
        font.setPointSize(9)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)

        major, minor = self._tick_steps()
        if major <= 0:
            return

        if self._horizontal:
            self._paint_horizontal(painter, major, minor)
        else:
            self._paint_vertical(painter, major, minor)

        cursor = view.cursor_scene_pos()
        self._paint_cursor_marker(painter, cursor)

    # ── geometry helpers ─────────────────────────────────────────────
    def _scale(self) -> float:
        t = self._view.transform()
        return abs(t.m11()) if self._horizontal else abs(t.m22())

    def _tick_steps(self) -> tuple[float, float]:
        """Pick a major tick step in mm such that ticks are ~80 px apart."""
        scale = self._scale()
        if scale <= 0:
            return (0.0, 0.0)
        target_px = 80
        raw_mm = target_px / scale
        if raw_mm <= 0:
            return (0.0, 0.0)
        pow10 = 10 ** math.floor(math.log10(raw_mm))
        for m in (1, 2, 5, 10):
            step = m * pow10
            if step >= raw_mm:
                return (step, step / 5)
        return (raw_mm, raw_mm / 5)

    def _scene_to_widget_x(self, scene_x: float) -> float:
        return self._view.mapFromScene(QPointF(scene_x, 0)).x()

    def _scene_to_widget_y(self, scene_y: float) -> float:
        return self._view.mapFromScene(QPointF(0, scene_y)).y()

    def _visible_scene_x(self) -> tuple[float, float]:
        p_left = self._view.mapToScene(0, 0)
        p_right = self._view.mapToScene(self._view.viewport().width(), 0)
        return (min(p_left.x(), p_right.x()), max(p_left.x(), p_right.x()))

    def _visible_scene_y(self) -> tuple[float, float]:
        p_top = self._view.mapToScene(0, 0)
        p_bot = self._view.mapToScene(0, self._view.viewport().height())
        return (min(p_top.y(), p_bot.y()), max(p_top.y(), p_bot.y()))

    # ── painters ─────────────────────────────────────────────────────
    def _paint_horizontal(self, painter: QPainter, major: float, minor: float) -> None:
        x_min, x_max = self._visible_scene_x()
        major_pen = QPen(self._tick_color, 1)
        minor_pen = QPen(self._tick_color, 1)
        h = self.height()

        # minor
        painter.setPen(minor_pen)
        start = math.floor(x_min / minor) * minor
        x = start
        while x <= x_max:
            wx = round(self._scene_to_widget_x(x))
            painter.drawLine(wx, h - 4, wx, h)
            x += minor

        # major + labels
        painter.setPen(major_pen)
        start = math.floor(x_min / major) * major
        x = start
        while x <= x_max:
            wx = round(self._scene_to_widget_x(x))
            painter.drawLine(wx, h - 8, wx, h)
            painter.setPen(self._text_color)
            label = _format_mm(x, major)
            painter.drawText(QRect(wx + 2, 0, 70, h - 2), Qt.AlignmentFlag.AlignVCenter, label)
            painter.setPen(major_pen)
            x += major

    def _paint_vertical(self, painter: QPainter, major: float, minor: float) -> None:
        y_min, y_max = self._visible_scene_y()
        major_pen = QPen(self._tick_color, 1)
        minor_pen = QPen(self._tick_color, 1)
        w = self.width()

        painter.setPen(minor_pen)
        start = math.floor(y_min / minor) * minor
        y = start
        while y <= y_max:
            wy = round(self._scene_to_widget_y(y))
            painter.drawLine(w - 4, wy, w, wy)
            y += minor

        painter.setPen(major_pen)
        start = math.floor(y_min / major) * major
        y = start
        while y <= y_max:
            wy = round(self._scene_to_widget_y(y))
            painter.drawLine(w - 8, wy, w, wy)
            painter.setPen(self._text_color)
            label = _format_mm(y, major)
            painter.save()
            painter.translate(w - 10, wy + 24)
            painter.rotate(-90)
            painter.drawText(QRect(0, 0, 60, RULER_THICKNESS - 2), Qt.AlignmentFlag.AlignVCenter, label)
            painter.restore()
            painter.setPen(major_pen)
            y += major

    def _paint_cursor_marker(self, painter: QPainter, cursor: QPointF) -> None:
        pen = QPen(self._accent, 1.5)
        painter.setPen(pen)
        if self._horizontal:
            wx = round(self._scene_to_widget_x(cursor.x()))
            if 0 <= wx <= self.width():
                painter.drawLine(wx, 0, wx, self.height())
        else:
            wy = round(self._scene_to_widget_y(cursor.y()))
            if 0 <= wy <= self.height():
                painter.drawLine(0, wy, self.width(), wy)


class HorizontalRuler(_Ruler):
    def __init__(self, view: CanvasView, parent: QWidget | None = None) -> None:
        super().__init__(view, horizontal=True, parent=parent)


class VerticalRuler(_Ruler):
    def __init__(self, view: CanvasView, parent: QWidget | None = None) -> None:
        super().__init__(view, horizontal=False, parent=parent)


class RulerCorner(QWidget):
    """Tiny inert square filling the top-left intersection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Ruler")
        # Plain QWidgets ignore a stylesheet background unless told to
        # paint a styled background — without this the corner stays
        # transparent and composites to black on Windows.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(RULER_THICKNESS, RULER_THICKNESS)


def _format_mm(value: float, step: float) -> str:
    if step >= 1:
        return f"{round(value)}"
    decimals = max(0, round(-math.log10(step)))
    return f"{value:.{decimals}f}"
