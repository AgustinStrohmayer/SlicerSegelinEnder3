"""Scene that renders the part, the bed, cut path and simulation state.

The main window assembles a small view-model each refresh and calls
:meth:`render`. Geometry outside the bed is drawn in the danger colour,
the cut entry point gets a green marker, manual-cut lines are dashed,
and during simulation the trajectory is revealed up to the slider's
fractional position with a moving head marker.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from PyQt6.QtCore import QLineF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsScene

from ....core.geometry import Point, Segment, SegmentKind


@dataclass(slots=True)
class ScenePalette:
    background: str = "#0F1115"
    grid: str = "#2A3142"
    axis: str = "#7C5CFF"
    cut: str = "#7C5CFF"
    entry: str = "#34D399"
    exit: str = "#F87171"
    travel: str = "#8A93A6"
    union: str = "#F59E0B"
    danger: str = "#F87171"
    bed: str = "#3A4256"
    surface_alt: str = "#1B2230"
    measure: str = "#22D3EE"   # cyan — reads as "measurement", distinct from the cut colour
    dim_line: str = "#8A93A6"  # dimension witness/arrow lines
    dim_text: str = "#E6E8EE"  # dimension labels
    select: str = "#3B82F6"    # selection highlight + handles
    guide: str = "#22D3EE"     # snap guide lines


_KIND_COLOR = {
    SegmentKind.CUT: "cut",
    SegmentKind.ENTRY: "entry",
    SegmentKind.EXIT: "exit",
    SegmentKind.RETURN_H: "travel",
    SegmentKind.RETURN_V: "travel",
    SegmentKind.UNION: "union",
    SegmentKind.TRAVEL: "travel",
}


@dataclass(slots=True)
class SceneModel:
    segments: list[Segment] = field(default_factory=list)
    trajectory: list[Segment] = field(default_factory=list)
    progress: float = 0.0  # fractional index into trajectory
    entry_point: Point | None = None
    manual_lines: list[tuple[float, float, float]] = field(default_factory=list)
    bed_y: float = 220.0
    bed_z: float = 100.0
    show_bed: bool = True
    show_grid: bool = True
    show_dims: bool = False                       # overlay the part's W×H
    measure: tuple[Point, Point] | None = None    # (a, b) of the measure tool
    measure_active: bool = False                  # True while picking the 2nd point
    selected: tuple | None = None                 # ("part",) | ("cut", i) | ("part", "handles")
    handles: bool = False                         # draw rotate/scale handles on the part
    guides: list[tuple[float, float, float]] = field(default_factory=list)  # snap guides a·y+b·z+c=0
    live_label: tuple[str, float, float] | None = None  # (text, y, z) shown near the cursor


class SlicerScene(QGraphicsScene):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.palette = ScenePalette()
        self._grid_color = QColor(self.palette.grid)
        self._grid_step = 10.0
        self._model = SceneModel()
        # Handle scene positions from the last render, for the window's hit-test:
        # {"rotate": (y, z), 0: (y, z), 1: ..., 2: ..., 3: ...}.
        self.handle_points: dict = {}
        self.setBackgroundBrush(QColor(self.palette.background))

    def set_palette(self, palette: ScenePalette) -> None:
        self.palette = palette
        self._grid_color = QColor(palette.grid)
        self.setBackgroundBrush(QColor(palette.background))
        self.render_model(self._model)

    def render_model(self, model: SceneModel) -> None:
        self._model = model
        self.handle_points = {}
        self.clear()
        if model.show_bed:
            self._draw_bed(model)
        self._draw_segments(model)
        if model.manual_lines:
            self._draw_manual_lines(model)
        if model.trajectory:
            self._draw_trajectory(model)
        if model.entry_point is not None:
            self._draw_entry(model.entry_point)
        if model.show_dims and model.segments:
            self._draw_dims(model)
        if model.guides:
            self._draw_guides(model)
        if model.selected is not None:
            self._draw_selection(model)
        if model.measure is not None:
            self._draw_measure(model)
        if model.live_label is not None:
            txt, lx, lz = model.live_label
            self._add_label(txt, lx, lz, self.palette.select)
        self._update_scene_rect(model)

    # ── selection + guides + handles ──────────────────────────────────
    def _part_bbox(self, model: SceneModel):
        if not model.segments:
            return None
        ys = [p for s in model.segments for p in (s.a.y, s.b.y)]
        zs = [p for s in model.segments for p in (s.a.z, s.b.z)]
        return (min(ys), min(zs), max(ys), max(zs))

    def _full_line(self, model: SceneModel, a: float, b: float, c: float) -> QLineF:
        diag = max(model.bed_y, model.bed_z) * 4
        if abs(b) > abs(a):
            y0, y1 = -diag, diag
            z0 = (-c - a * y0) / b
            z1 = (-c - a * y1) / b
        else:
            z0, z1 = -diag, diag
            y0 = (-c - b * z0) / a if abs(a) > 1e-12 else 0.0
            y1 = (-c - b * z1) / a if abs(a) > 1e-12 else 0.0
        return QLineF(y0, z0, y1, z1)

    def _draw_guides(self, model: SceneModel) -> None:
        pen = QPen(QColor(self.palette.guide), 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        pen.setWidthF(1.0)
        for a, b, c in model.guides:
            self.addLine(self._full_line(model, a, b, c), pen).setZValue(13)

    def _draw_selection(self, model: SceneModel) -> None:
        col = QColor(self.palette.select)
        if model.selected[0] == "part":
            bb = self._part_bbox(model)
            if bb is None:
                return
            y0, z0, y1, z1 = bb
            pad = max(y1 - y0, z1 - z0) * 0.03 + 1.0
            pen = QPen(col, 0, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            pen.setWidthF(1.4)
            rect = QRectF(y0 - pad, z0 - pad, (y1 - y0) + 2 * pad, (z1 - z0) + 2 * pad)
            self.addRect(rect, pen).setZValue(12)
            if model.handles:
                self._draw_handles(rect)
        elif model.selected[0] == "cut":
            i = model.selected[1]
            if 0 <= i < len(model.manual_lines):
                pen = QPen(col, 0)
                pen.setCosmetic(True)
                pen.setWidthF(2.6)
                self.addLine(self._full_line(model, *model.manual_lines[i]), pen).setZValue(12)

    def _draw_handles(self, rect: QRectF) -> None:
        col = QColor(self.palette.select)
        pen = QPen(col, 0)
        pen.setCosmetic(True)
        brush = QBrush(QColor("#FFFFFF"))
        r = max(2.0, min(rect.width(), rect.height()) * 0.03)
        corners = [
            (rect.left(), rect.top()), (rect.right(), rect.top()),
            (rect.right(), rect.bottom()), (rect.left(), rect.bottom()),
        ]
        for i, (cx, cz) in enumerate(corners):
            self.addEllipse(QRectF(cx - r, cz - r, 2 * r, 2 * r), pen, brush).setZValue(13)
            self.handle_points[i] = (cx, cz)
        # Rotate handle: a dot beyond the top-centre (rect.bottom is +z = up).
        hx = (rect.left() + rect.right()) / 2
        hz = rect.bottom() + (rect.height() * 0.18 + r * 3)
        self.addLine(QLineF(hx, rect.bottom(), hx, hz), pen).setZValue(12)
        self.addEllipse(QRectF(hx - r, hz - r, 2 * r, 2 * r), pen, QBrush(col)).setZValue(13)
        self.handle_points["rotate"] = (hx, hz)

    def _update_scene_rect(self, model: SceneModel) -> None:
        """Pad the scene around the content so the view can pan freely.

        Without a generous scene rect, dragging stops as soon as the
        content fits the viewport — there is nothing left to scroll.
        """
        content = self.itemsBoundingRect()
        if content.isEmpty():
            content = QRectF(0, 0, model.bed_y, model.bed_z)
        # Generous padding so panning feels free (no scrollbars are shown).
        pad = max(content.width(), content.height(), model.bed_y, model.bed_z, 50.0) * 3.0
        self.setSceneRect(content.adjusted(-pad, -pad, pad, pad))

    # ── pieces ────────────────────────────────────────────────────────
    def _draw_bed(self, model: SceneModel) -> None:
        from PyQt6.QtGui import QBrush

        fill = QColor(self.palette.surface_alt)
        fill.setAlpha(46)
        pen = QPen(QColor(self.palette.bed), 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        item = self.addRect(QRectF(0, 0, model.bed_y, model.bed_z), pen, QBrush(fill))
        item.setZValue(-1)

    def _draw_segments(self, model: SceneModel) -> None:
        cut_path = QPainterPath()
        oob_path = QPainterPath()
        for s in model.segments:
            target = oob_path if self._out_of_bed(s, model) else cut_path
            target.moveTo(s.a.y, s.a.z)
            target.lineTo(s.b.y, s.b.z)
        cut_pen = QPen(QColor(self.palette.cut), 0)
        cut_pen.setCosmetic(True)
        cut_pen.setWidthF(1.4)
        item = self.addPath(cut_path, cut_pen)
        item.setZValue(1)
        oob_pen = QPen(QColor(self.palette.danger), 0)
        oob_pen.setCosmetic(True)
        oob_pen.setWidthF(1.6)
        self.addPath(oob_path, oob_pen).setZValue(2)

    def _out_of_bed(self, s: Segment, model: SceneModel) -> bool:
        if not model.show_bed:
            return False
        for p in (s.a, s.b):
            if p.y < -1e-6 or p.y > model.bed_y + 1e-6 or p.z < -1e-6 or p.z > model.bed_z + 1e-6:
                return True
        return False

    def _draw_manual_lines(self, model: SceneModel) -> None:
        pen = QPen(QColor(self.palette.union), 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        diag = max(model.bed_y, model.bed_z) * 4
        for a, b, c in model.manual_lines:
            # a*y + b*z + c = 0 → draw a long clipped line across the bed
            if abs(b) > abs(a):  # mostly horizontal
                y0, y1 = -diag, diag
                z0 = (-c - a * y0) / b
                z1 = (-c - a * y1) / b
            else:
                z0, z1 = -diag, diag
                y0 = (-c - b * z0) / a if abs(a) > 1e-12 else 0.0
                y1 = (-c - b * z1) / a if abs(a) > 1e-12 else 0.0
            self.addLine(QLineF(y0, z0, y1, z1), pen).setZValue(3)

    def _draw_trajectory(self, model: SceneModel) -> None:
        n = len(model.trajectory)
        progress = max(0.0, min(float(n), model.progress))
        full = progress >= n
        drawn_head: Point | None = None
        for i, s in enumerate(model.trajectory):
            color = QColor(getattr(self.palette, _KIND_COLOR.get(s.kind, "travel")))
            if i + 1 <= progress or full:
                seg = s
            elif i < progress < i + 1:
                t = progress - i
                seg = Segment(s.a, Point(s.a.y + (s.b.y - s.a.y) * t, s.a.z + (s.b.z - s.a.z) * t), s.kind)
                drawn_head = seg.b
            else:
                continue
            pen = QPen(color, 0)
            pen.setCosmetic(True)
            pen.setWidthF(2.2)
            self.addLine(QLineF(seg.a.y, seg.a.z, seg.b.y, seg.b.z), pen).setZValue(5)
        if drawn_head is not None:
            self._draw_dot(drawn_head, self.palette.axis, 2.4)

    def _draw_entry(self, p: Point) -> None:
        self._draw_dot(p, self.palette.entry, 3.0)

    # ── measurement + dimensions ──────────────────────────────────────
    def _add_label(self, text: str, x: float, y: float, color: str) -> None:
        """Add a screen-constant-size text label anchored at scene (x, y)."""
        item = self.addText(text)
        item.setDefaultTextColor(QColor(color))
        font = item.font()
        font.setPointSizeF(8.5)
        item.setFont(font)
        # Stay upright and a fixed size regardless of zoom / the flipped Y.
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        item.setZValue(21)
        item.setPos(x, y)

    def _draw_measure(self, model: SceneModel) -> None:
        a, b = model.measure  # type: ignore[misc]
        col = self.palette.measure
        pen = QPen(QColor(col), 0)
        pen.setCosmetic(True)
        pen.setWidthF(1.8)
        if model.measure_active:
            pen.setStyle(Qt.PenStyle.DashLine)
        self.addLine(QLineF(a.y, a.z, b.y, b.z), pen).setZValue(15)
        self._draw_dot(a, col, 2.2)
        self._draw_dot(b, col, 2.2)
        dy, dz = b.y - a.y, b.z - a.z
        dist = math.hypot(dy, dz)
        self._add_label(
            f"{dist:.1f} mm  (Δy {dy:+.1f}, Δz {dz:+.1f})",
            (a.y + b.y) / 2, (a.z + b.z) / 2, col,
        )

    def _draw_dims(self, model: SceneModel) -> None:
        ys = [p for s in model.segments for p in (s.a.y, s.b.y)]
        zs = [p for s in model.segments for p in (s.a.z, s.b.z)]
        y0, y1, z0, z1 = min(ys), max(ys), min(zs), max(zs)
        w, h = y1 - y0, z1 - z0
        if w <= 1e-6 and h <= 1e-6:
            return
        pen = QPen(QColor(self.palette.dim_line), 0)
        pen.setCosmetic(True)
        off = max(w, h) * 0.07 + 3.0
        # Width dimension below the bounding box.
        zb = z0 - off
        for ln in (QLineF(y0, zb, y1, zb), QLineF(y0, z0, y0, zb), QLineF(y1, z0, y1, zb)):
            self.addLine(ln, pen).setZValue(14)
        self._add_label(f"{w:.1f} mm", (y0 + y1) / 2, zb, self.palette.dim_text)
        # Height dimension to the left of the bounding box.
        yl = y0 - off
        for ln in (QLineF(yl, z0, yl, z1), QLineF(y0, z0, yl, z0), QLineF(y0, z1, yl, z1)):
            self.addLine(ln, pen).setZValue(14)
        self._add_label(f"{h:.1f} mm", yl, (z0 + z1) / 2, self.palette.dim_text)

    def _draw_dot(self, p: Point, color: str, r: float) -> None:
        pen = QPen(QColor(color), 0)
        pen.setCosmetic(True)
        brush = QBrush(QColor(color))
        item = self.addEllipse(QRectF(p.y - r, p.z - r, 2 * r, 2 * r), pen, brush)
        item.setZValue(10)

    # ── grid background ───────────────────────────────────────────────
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        if not self._model.show_grid:
            return
        pen = QPen(self._grid_color, 0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        step = self._grid_step
        x = int(rect.left() / step) * step
        lines = []
        while x <= rect.right():
            lines.append(QLineF(x, rect.top(), x, rect.bottom()))
            x += step
        y = int(rect.top() / step) * step
        while y <= rect.bottom():
            lines.append(QLineF(rect.left(), y, rect.right(), y))
            y += step
        painter.drawLines(lines)
        axis_pen = QPen(QColor(self.palette.axis), 0)
        axis_pen.setCosmetic(True)
        painter.setPen(axis_pen)
        painter.drawLine(QLineF(rect.left(), 0.0, rect.right(), 0.0))
        painter.drawLine(QLineF(0.0, rect.top(), 0.0, rect.bottom()))
