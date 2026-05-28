"""Scene that renders a list of segments + grid background.

For performance with large geometries (50k+ segments), all CUT
segments are batched into a single ``QGraphicsPathItem`` per call
instead of one item per segment.
"""
from __future__ import annotations

from PyQt6.QtCore import QLineF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsScene

from ....core.geometry import Segment, SegmentKind


_KIND_COLOR: dict[SegmentKind, str] = {
    SegmentKind.CUT: "#7C5CFF",
    SegmentKind.ENTRY: "#34D399",
    SegmentKind.EXIT: "#F87171",
    SegmentKind.RETURN_H: "#8A93A6",
    SegmentKind.RETURN_V: "#8A93A6",
    SegmentKind.UNION: "#F59E0B",
    SegmentKind.TRAVEL: "#5B6478",
}


class SlicerScene(QGraphicsScene):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._grid_color = QColor("#2A3142")
        self._grid_step = 10.0
        self.setBackgroundBrush(QColor("#0F1115"))

    def set_palette(self, *, background: str, grid: str) -> None:
        self.setBackgroundBrush(QColor(background))
        self._grid_color = QColor(grid)
        self.update()

    def set_grid_step(self, step: float) -> None:
        self._grid_step = max(1.0, step)
        self.update()

    def render_segments(self, segments: list[Segment]) -> None:
        self.clear()
        if not segments:
            return
        per_kind: dict[SegmentKind, QPainterPath] = {}
        for s in segments:
            path = per_kind.setdefault(s.kind, QPainterPath())
            path.moveTo(s.a.y, s.a.z)
            path.lineTo(s.b.y, s.b.z)
        for kind, path in per_kind.items():
            item = self.addPath(path, QPen(QColor(_KIND_COLOR.get(kind, "#7C5CFF")), 0))
            item.setZValue(1 if kind == SegmentKind.CUT else 0)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        pen = QPen(self._grid_color, 0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        step = self._grid_step
        left = int(rect.left() / step) * step
        top = int(rect.top() / step) * step
        lines = []
        x = left
        while x <= rect.right():
            lines.append(QLineF(x, rect.top(), x, rect.bottom()))
            x += step
        y = top
        while y <= rect.bottom():
            lines.append(QLineF(rect.left(), y, rect.right(), y))
            y += step
        painter.drawLines(lines)
        # accent axes
        pen.setColor(QColor("#7C5CFF"))
        pen.setWidthF(0.0)
        painter.setPen(pen)
        painter.drawLine(QLineF(rect.left(), 0.0, rect.right(), 0.0))
        painter.drawLine(QLineF(0.0, rect.top(), 0.0, rect.bottom()))
