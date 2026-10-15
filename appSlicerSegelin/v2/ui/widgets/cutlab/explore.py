"""Explore tab: the wire's cross-section in the foam, the operating map and the wire along its span.

The cross-section has two views: the reduced model (instant) and the
high-fidelity 2-D thermal solve (:mod:`core.thermal2d`, run on demand).
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QWidget,
)

from ....core.cutting_physics import CutSetup, OperatingMap, PointState, SpanProfile
from ....core.thermal2d import Thermal2DResult
from .common import FOAM, REGIME, card, heat_cmap, qcolor, style_plot

HOT_LIMIT_C = 400.0  # above this the wire smokes the foam and the kerf balloons


def wire_color(t_c: float) -> str:
    """Glow colour of the wire: dull grey when cold, red → orange → yellow when hot."""
    stops = [(20, (90, 90, 95)), (150, (120, 40, 30)), (300, (210, 50, 20)), (500, (250, 140, 30)),
             (800, (255, 220, 120))]
    for (t0, c0), (t1, c1) in itertools.pairwise(stops):
        if t_c <= t1:
            f = max(0.0, (t_c - t0) / (t1 - t0))
            return "#{:02x}{:02x}{:02x}".format(*tuple(int(a + (b - a) * f) for a, b in zip(c0, c1, strict=True)))
    return "#ffe9a8"


def regime_of(st: PointState, setup: CutSetup) -> str:
    if bool(st.stall):
        return "stall"
    if bool(st.contact):
        return "contact"
    if float(st.kerf_mm) > 4 * setup.diameter_mm and float(st.kerf_mm) > 1.2:
        return "overmelt"
    return "noncontact"


REGIME_TEXT = {
    "noncontact": "Non-contact cut",
    "contact": "Contact — wire drags",
    "stall": "Stall — too cold to melt",
    "overmelt": "Over-melting — wide kerf",
}


class IncidenceView(pg.PlotWidget):
    """Cross-section of the cut around the wire: foam, melt front, gap, kerf walls, wire."""

    def __init__(self, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from .common import colors

        self._c = colors(theme)
        self.setBackground(self._c.bg)
        self.setAspectLocked(True)
        self.setMouseEnabled(False, False)
        self.hideButtons()
        style_plot(self, self._c, grid=False)
        self.getPlotItem().setLabel("bottom", "along the feed (mm)")
        self.getPlotItem().setLabel("left", "across the kerf (mm)")
        self._items: list = []

    def _add(self, item):  # type: ignore[no-untyped-def]
        self.addItem(item)
        self._items.append(item)
        return item

    def show_state(self, st: PointState, setup: CutSetup, v: float) -> None:
        for it in self._items:
            self.removeItem(it)
        self._items = []
        c = self._c
        rw = setup.diameter_mm / 2
        rm = float(st.r_m_mm)
        hw = float(st.kerf_mm) / 2
        reg = regime_of(st, setup)
        view = max(4.0 * rm, 1.6, 3.0 * hw)
        X = view * 1.6

        foam = QGraphicsRectItem(QRectF(-3 * X, -3 * view, 6 * X, 6 * view))
        foam.setBrush(QBrush(qcolor(FOAM, 150)))
        foam.setPen(QPen(Qt.PenStyle.NoPen))
        self._add(foam)
        # the cut: a channel of half-width hw behind the wire, closed ahead by the melt front
        path = QPainterPath()
        n = 40
        pts = [QPointF(-3 * X, hw)]
        for k in range(n + 1):
            a = math.pi / 2 - math.pi * k / n
            pts.append(QPointF(rm * math.cos(a), hw * math.sin(a)))
        pts.append(QPointF(-3 * X, -hw))
        path.addPolygon(QPolygonF(pts))
        path.closeSubpath()
        cut = QGraphicsPathItem(path)
        cut.setBrush(QBrush(qcolor(c.bg)))
        cut.setPen(QPen(qcolor(REGIME[reg]), 0))
        self._add(cut)
        # hot gas in the gap: a soft glow that fades with distance
        if not bool(st.stall):
            for k, frac in enumerate((1.0, 0.75, 0.5)):
                r = rw + (rm - rw) * frac
                g = QGraphicsEllipseItem(QRectF(-r, -r, 2 * r, 2 * r))
                g.setBrush(QBrush(qcolor("#F59E0B", 28 + 22 * k)))
                g.setPen(QPen(Qt.PenStyle.NoPen))
                self._add(g)
        wire = QGraphicsEllipseItem(QRectF(-rw, -rw, 2 * rw, 2 * rw))
        wire.setBrush(QBrush(qcolor(wire_color(float(st.t_foam_c)))))
        wire.setPen(QPen(qcolor("#000000", 160), 0))
        self._add(wire)
        # melt front radius
        self._add(pg.PlotDataItem([0, rm], [0, 0], pen=pg.mkPen(c.text, width=1, style=Qt.PenStyle.DashLine)))
        # kerf dimension behind the wire
        xk = -max(2.2 * rm, 0.6 * X)
        self._add(pg.PlotDataItem([xk, xk], [-hw, hw], pen=pg.mkPen("#F5A623", width=2)))
        for yy in (-hw, hw):
            self._add(pg.PlotDataItem([xk - 0.06 * view, xk + 0.06 * view], [yy, yy], pen=pg.mkPen(c.accent, width=2)))

        def label(text: str, x: float, y: float, color: str, anchor=(0, 0.5)):  # type: ignore[no-untyped-def]
            t = pg.TextItem(text, color=color, anchor=anchor)
            t.setPos(x, y)
            self._add(t)

        label(f"kerf {2 * hw:.2f} mm", xk + 0.08 * view, hw * 0.5 + 0.1 * view, c.accent)
        label(f"r_m {rm:.3f} mm · wire {float(st.t_foam_c):.0f} °C", rm * 0.5, -hw - 0.04 * view, c.text,
              anchor=(0.5, 0))
        gap = float(st.gap_mm)
        label(f"gap {gap * 1000:.0f} µm" if gap < 0.1 else f"gap {gap:.2f} mm", rm + 0.05 * view, 0.18 * view,
              REGIME[reg])
        arrow = pg.ArrowItem(angle=180, tipAngle=30, headLen=14, tailLen=40, tailWidth=3, brush=c.text,
                             pen=pg.mkPen(None))
        arrow.setPos(X * 0.85, view * 0.78)
        self._add(arrow)
        label(f"feed {v:.2f} mm/s", X * 0.85, view * 0.6, c.text, anchor=(1, 0.5))
        self.setXRange(-X, X, padding=0)
        self.setYRange(-view, view, padding=0)


class Section2DView(pg.GraphicsLayoutWidget):
    """The 2-D solve: temperature around the wire, the melt front it found, and how it settled.

    Dashed: the reduced model's melt front and kerf at the same point, for comparison.
    """

    def __init__(self, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from .common import colors

        c = self._c = colors(theme)
        self.setBackground(c.bg)
        self.p = self.addPlot(row=0, col=0)
        self.h = self.addPlot(row=1, col=0)
        self.ci.layout.setRowStretchFactor(0, 3)
        self.ci.layout.setRowStretchFactor(1, 1)
        for p in (self.p, self.h):
            style_plot(p, c, grid=p is self.h)
            p.setMouseEnabled(False, False)
            p.hideButtons()
            p.getAxis("left").enableAutoSIPrefix(False)
        self.p.setAspectLocked(True)
        self.p.setLabel("bottom", "along the feed (mm)")
        self.p.setLabel("left", "across the kerf (mm)")
        self.h.setLabel("bottom", "simulated time (s)")
        self.h.setLabel("left", "mm")
        self.img = pg.ImageItem(axisOrder="col-major")
        self.p.addItem(self.img)
        self.bar = pg.ColorBarItem(values=(20, 300), colorMap=pg.colormap.get("inferno"), label="°C",
                                   interactive=False, width=12)
        self.bar.setImageItem(self.img, insert_in=self.p)
        self.bar.getAxis("right").setTextPen(pg.mkPen(c.muted))
        self.front = pg.IsocurveItem(level=0.5, pen=pg.mkPen(FOAM, width=2))
        self.front.setParentItem(self.img)
        leg = self.h.addLegend(offset=(-10, -4))
        leg.setLabelTextColor(c.muted)
        self.k_curve = self.h.plot(pen=pg.mkPen(c.accent, width=2), name="kerf")
        self.r_curve = self.h.plot(pen=pg.mkPen(FOAM, width=2), name="r_m")
        self._items: list = []
        self._hint = pg.TextItem("Run the 2-D solve to see the heat around the wire.", color=c.muted,
                                 anchor=(0.5, 0.5))
        self.p.addItem(self._hint)

    def _add(self, item):  # type: ignore[no-untyped-def]
        self.p.addItem(item)
        self._items.append(item)
        return item

    def show_result(self, r: Thermal2DResult, setup: CutSetup) -> None:
        for it in self._items:
            self.p.removeItem(it)
        self._items = []
        self._hint.hide()
        x, y = r.x_mm, r.y_mm
        dx = float(x[1] - x[0])
        hw = r.kerf_mm / 2
        view = max(2.4 * r.r_m_mm, 0.9, 1.8 * hw, 1.4 * r.model_kerf_mm / 2, 1.4 * r.model_r_m_mm)
        view = min(view, float(y[-1]))
        x0, x1 = max(float(x[0]), -2.0 * view), min(float(x[-1]), 1.6 * view)
        self.img.setImage(r.t_c, autoLevels=False)
        self.img.setRect(QRectF(float(x[0]) - dx / 2, float(y[0]) - dx / 2, dx * len(x), dx * len(y)))
        self.bar.setLevels((setup.ambient_c, max(r.t_wire_c, setup.foam.iso_temp_c + 20)))
        self.front.setData(r.phi)
        # the reduced model at the same point (drawn light: the inferno image is dark in both themes)
        on_img = "#F2F2F2"
        dash = pg.mkPen(on_img, width=1.4, style=Qt.PenStyle.DashLine)
        a = np.linspace(-np.pi / 2, np.pi / 2, 60)
        rm0, hw0 = r.model_r_m_mm, r.model_kerf_mm / 2
        self._add(pg.PlotDataItem(rm0 * np.cos(a), hw0 * np.sin(a), pen=dash))
        for sgn in (-1, 1):
            self._add(pg.PlotDataItem([x0, 0], [sgn * hw0, sgn * hw0], pen=dash))
        rw = setup.diameter_mm / 2
        wire = QGraphicsEllipseItem(QRectF(-rw, -rw, 2 * rw, 2 * rw))
        wire.setBrush(QBrush(qcolor(wire_color(r.t_wire_c))))
        wire.setPen(QPen(qcolor("#000000", 160), 0))
        self._add(wire)
        xk = 0.6 * x0
        self._add(pg.PlotDataItem([xk, xk], [-hw, hw], pen=pg.mkPen("#F5A623", width=2)))

        def label(text: str, px: float, py: float, color: str, anchor=(0, 0.5)):  # type: ignore[no-untyped-def]
            t = pg.TextItem(text, color=color, anchor=anchor, fill=pg.mkBrush(qcolor("#000000", 170)))
            t.setPos(px, py)
            self._add(t)

        label(f"kerf {r.kerf_mm:.2f} mm", xk, -0.82 * view, "#F5A623", anchor=(0.5, 0.5))
        label(f"r_m {r.r_m_mm:.3f} mm", 0.15 * view, 0.82 * view, FOAM)
        label(f"wire {r.t_wire_c:.0f} °C", -0.15 * view, 0.82 * view, on_img, anchor=(1, 0.5))
        label("- - model", x1 - 0.05 * view, -0.82 * view, on_img, anchor=(1, 0.5))
        self.p.setXRange(x0, x1, padding=0)
        self.p.setYRange(-view, view, padding=0)
        self.k_curve.setData(r.hist_t, r.hist_kerf)
        self.r_curve.setData(r.hist_t, r.hist_rm)


def _speed_ticks(lo: float, hi: float) -> list[tuple[float, str]]:
    vals = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200]
    return [(math.log10(v), f"{v:g}") for v in vals if lo <= v <= hi]


class OperatingMapView(pg.PlotWidget):
    """Kerf over drive × feed; contact boundary, stall and over-temperature areas; click to pick."""

    picked = pyqtSignal(float, float)  # drive, speed

    def __init__(self, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from .common import colors

        self._c = colors(theme)
        self.setBackground(self._c.bg)
        style_plot(self, self._c, grid=False)
        pi = self.getPlotItem()
        pi.setLabel("bottom", "feed (mm/s)")
        pi.setMouseEnabled(False, False)
        self.hideButtons()
        self.img = pg.ImageItem()
        self.addItem(self.img)
        self.mask = pg.ImageItem()
        self.addItem(self.mask)
        self.iso = pg.IsocurveItem(level=0.5, pen=pg.mkPen(REGIME["contact"], width=2.5))
        self.iso.setParentItem(self.img)
        self.marker = pg.ScatterPlotItem(size=14, brush=pg.mkBrush(self._c.text), pen=pg.mkPen(self._c.bg, width=2),
                                         symbol="o")
        self.addItem(self.marker)
        self.hover = pg.TextItem("", color=self._c.text, anchor=(0, 1), fill=pg.mkBrush(qcolor(self._c.surface, 220)))
        self.hover.setZValue(10)
        self.addItem(self.hover)
        self.hover.hide()
        self.bar = pg.ColorBarItem(values=(0.3, 3.0), colorMap=heat_cmap(), label="kerf (mm)", interactive=False,
                                   width=14)
        self.bar.setImageItem(self.img, insert_in=pi)
        self.bar.getAxis("right").setTextPen(pg.mkPen(self._c.muted))
        self._map: OperatingMap | None = None
        self.scene().sigMouseClicked.connect(self._click)
        self.scene().sigMouseMoved.connect(self._move)

    def set_map(self, m: OperatingMap) -> None:
        self._map = m
        lv = np.log10(m.speeds)
        rect = QRectF(lv[0], m.drive[0], lv[-1] - lv[0], m.drive[-1] - m.drive[0])
        k = np.clip(m.kerf_mm, 0, None)
        lo = float(np.nanmin(k))
        hi = min(float(np.nanpercentile(k, 75)), 3.0)  # the capped slow/hot corner would wash out the rest
        self.img.setImage(k, autoLevels=False, axisOrder="row-major")  # rows: drive (y), cols: feed (x)
        self.img.setRect(rect)
        self.bar.setLevels((lo, max(hi, lo + 0.1)))
        rgba = np.zeros((*m.kerf_mm.shape, 4), np.ubyte)
        rgba[m.stall] = (229, 72, 77, 170)
        hot = (m.t_air_c > HOT_LIMIT_C) & ~m.stall
        rgba[hot] = (150, 80, 200, 70)
        self.mask.setImage(rgba, axisOrder="row-major")
        self.mask.setRect(rect)
        self.iso.setData(m.contact.astype(float).T)  # isocurve data is [x, y]
        pi = self.getPlotItem()
        pi.getAxis("bottom").setTicks([_speed_ticks(m.speeds[0], m.speeds[-1])])
        pi.setLabel("left", "current (A)" if m.mode == "current" else "voltage (V)")
        pi.setXRange(lv[0], lv[-1], padding=0)
        pi.setYRange(m.drive[0], m.drive[-1], padding=0)

    def set_point(self, drive: float, v: float) -> None:
        self.marker.setData([math.log10(max(v, 1e-3))], [drive])

    def _lookup(self, pos) -> tuple[float, float, int, int] | None:  # type: ignore[no-untyped-def]
        if self._map is None:
            return None
        p = self.getPlotItem().vb.mapSceneToView(pos)
        m = self._map
        lv = np.log10(m.speeds)
        if not (lv[0] <= p.x() <= lv[-1] and m.drive[0] <= p.y() <= m.drive[-1]):
            return None
        j = int(np.clip(np.searchsorted(lv, p.x()), 0, len(lv) - 1))
        i = int(np.clip(np.searchsorted(m.drive, p.y()), 0, len(m.drive) - 1))
        return p.y(), 10 ** p.x(), i, j

    def _click(self, ev) -> None:  # type: ignore[no-untyped-def]
        hit = self._lookup(ev.scenePos())
        if hit is not None and ev.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(hit[0], hit[1])

    def _move(self, pos) -> None:  # type: ignore[no-untyped-def]
        hit = self._lookup(pos)
        if hit is None:
            self.hover.hide()
            return
        d, v, i, j = hit
        m = self._map
        assert m is not None
        unit = "A" if m.mode == "current" else "V"
        reg = "stall" if m.stall[i, j] else ("contact" if m.contact[i, j] else "non-contact")
        self.hover.setText(f"{d:.2f} {unit} · {v:.2f} mm/s\nkerf {m.kerf_mm[i, j]:.2f} mm · {reg}\n"
                           f"wire {m.t_foam_c[i, j]:.0f} °C in foam")
        p = self.getPlotItem().vb.mapSceneToView(pos)
        self.hover.setPos(p)
        self.hover.show()


class AlongWireView(pg.GraphicsLayoutWidget):
    """Temperature, kerf and bow along the wire at the probe feed."""

    def __init__(self, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from .common import colors

        c = self._c = colors(theme)
        self.setBackground(c.bg)
        self.pt = self.addPlot(row=0, col=0)
        self.pk = self.addPlot(row=1, col=0)
        self.pk.setXLink(self.pt)
        for p in (self.pt, self.pk):
            style_plot(p, c)
            p.setMouseEnabled(False, False)
            p.hideButtons()
        self.pt.setLabel("left", "wire °C")
        self.pk.setLabel("left", "mm")
        for p in (self.pt, self.pk):
            p.getAxis("left").enableAutoSIPrefix(False)
        self.pk.setLabel("bottom", "position along the wire (mm, 0 = centre)")
        self.t_curve = self.pt.plot(pen=pg.mkPen("#F28C28", width=2))
        self.t_air = self.pt.plot(pen=pg.mkPen(c.muted, width=1, style=Qt.PenStyle.DashLine))
        self.k_curve = self.pk.plot(pen=pg.mkPen(c.accent, width=2), name="kerf")
        self.b_curve = self.pk.plot(pen=pg.mkPen("#5AA9E6", width=2, style=Qt.PenStyle.DashLine), name="bow")
        self.regions = [pg.LinearRegionItem(movable=False, brush=pg.mkBrush(qcolor(FOAM, 35)),
                                            pen=pg.mkPen(None)) for _ in range(2)]
        self.pt.addItem(self.regions[0])
        self.pk.addItem(self.regions[1])
        leg = self.pk.addLegend(offset=(-10, 6))
        leg.setLabelTextColor(c.muted)

    def show_profile(self, p: SpanProfile, v: float) -> None:
        ls = np.log(p.speeds)
        lv = math.log(min(max(v, p.speeds[0]), p.speeds[-1]))
        k = int(np.clip(np.searchsorted(ls, lv) - 1, 0, len(ls) - 2))
        f = (lv - ls[k]) / (ls[k + 1] - ls[k])

        def row(a: np.ndarray) -> np.ndarray:
            return a[k] * (1 - f) + a[k + 1] * f

        x = p.x_mm
        self.t_curve.setData(x, row(p.t_c))
        self.t_air.setData([x[0], x[-1]], [float(p.t_air_ref_c[k])] * 2)
        self.k_curve.setData(x, np.where(p.in_foam, row(p.kerf_mm), np.nan), connect="finite")
        self.b_curve.setData(x, row(p.bow_mm))
        xs = x[p.in_foam]
        if len(xs):
            for r in self.regions:
                r.setRegion((xs[0], xs[-1]))


QUALITIES = (("Coarse grid", "coarse"), ("Normal grid", "normal"), ("Fine grid", "fine"), ("Ultra grid", "ultra"))


class ExploreTab(QWidget):
    picked = pyqtSignal(float, float)
    hifi_requested = pyqtSignal(str)  # grid quality
    hifi_cancel = pyqtSignal()

    def __init__(self, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        lay.addWidget(split)
        f, v = card("Wire in the foam — cross-section",
                    "The foam retreats to the melt front before the wire reaches it. The gap between them is "
                    "the non-contact margin; when it closes the wire drags and bows. The 2-D solve resolves the "
                    "heat flow around the wire instead of the model's closed form (dashed).")
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.view_group = QButtonGroup(self)
        self.view_btns = []
        for i, text in enumerate(("Model", "2-D solve")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.view_group.addButton(b, i)
            self.view_btns.append(b)
            bar.addWidget(b)
        bar.addSpacing(8)
        self.quality = QComboBox()
        for text, key in QUALITIES:
            self.quality.addItem(text, key)
        self.quality.setCurrentIndex(1)
        self.quality.setToolTip("Grid of the 2-D solve. Coarse: seconds. Normal: 1 s to ~1 min (slow feeds take "
                                "longest). Fine: up to ~3 min. Ultra: about a minute at fast feeds, over 15 min at slow ones — for checking the grid.")
        self.run_btn = QPushButton("▶  Run 2-D solve")
        self.run_btn.setProperty("role", "primary")
        self.run_btn.setToolTip("Transient 2-D heat conduction around the wire at the probe feed and drive.")
        self.run_btn.clicked.connect(lambda: self.hifi_requested.emit(self.quality.currentData()))
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.hifi_cancel.emit)
        for w in (self.quality, self.run_btn, self.cancel_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        v.addLayout(bar)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFormat("2-D solve: not run")
        self.progress.setTextVisible(True)
        v.addWidget(self.progress)
        self.stack = QStackedWidget()
        self.incidence = IncidenceView(theme)
        self.section = Section2DView(theme)
        self.stack.addWidget(self.incidence)
        self.stack.addWidget(self.section)
        self.view_group.idClicked.connect(self.stack.setCurrentIndex)
        v.addWidget(self.stack, 1)
        self.hifi_note = QLabel("")
        self.hifi_note.setObjectName("CardSub")
        self.hifi_note.setWordWrap(True)
        self.hifi_note.setVisible(False)
        v.addWidget(self.hifi_note)
        self.hifi_result: Thermal2DResult | None = None
        self._hifi_text = ""
        split.addWidget(f)
        right = QSplitter(Qt.Orientation.Vertical)
        f, v = card("Operating map", "Kerf for every drive × feed. Orange line: contact boundary (right of it the "
                    "wire touches). Red: too cold to cut. Violet: wire above 400 °C. Click to pick a point.")
        self.map = OperatingMapView(theme)
        self.map.picked.connect(self.picked.emit)
        v.addWidget(self.map, 1)
        right.addWidget(f)
        f, v = card("Along the wire", "Temperature (dashed: same wire in free air), kerf and bow at the probe feed. "
                    "Shaded: inside the block. The wire is cooler in the foam and near the clamps.")
        self.along = AlongWireView(theme)
        v.addWidget(self.along, 1)
        right.addWidget(f)
        right.setSizes([520, 360])
        split.addWidget(right)
        split.setSizes([520, 720])


    # ── 2-D solve ─────────────────────────────────────────────────────
    def show_view(self, i: int) -> None:
        self.view_btns[i].setChecked(True)
        self.stack.setCurrentIndex(i)

    def hifi_busy(self, on: bool) -> None:
        self.run_btn.setEnabled(not on)
        self.cancel_btn.setEnabled(on)
        self.quality.setEnabled(not on)
        if on:
            self.progress.setValue(0)
            self.progress.setFormat("2-D solve: starting…")
            self.show_view(1)

    def hifi_progress(self, f: float, msg: str) -> None:
        self.progress.setValue(int(f * 1000))
        self.progress.setFormat(msg)

    def show_section(self, r: Thermal2DResult, setup: CutSetup) -> None:
        self.hifi_result = r
        self.section.show_result(r, setup)
        self.progress.setValue(1000)
        self.progress.setFormat(f"2-D solve: {r.runtime_s:.1f} s · {r.t_c.size // 2:,} cells of {r.cell_um:.0f} µm")
        state = "stall" if r.stall else ("contact" if r.contact else "non-contact")
        conv = "" if r.converged else " Not fully settled: compare the trend below."
        self._hifi_text = (
            f"2-D at {r.v_mm_s:.2f} mm/s, {r.current_a:.2f} A: kerf {r.kerf_mm:.2f} mm (model {r.model_kerf_mm:.2f}) · "
            f"r_m {r.r_m_mm:.3f} mm (model {r.model_r_m_mm:.3f}) · wire {r.t_wire_c:.0f} °C (model "
            f"{r.model_t_wire_c:.0f}) · {r.q_cut_w_m:.1f} W/m into the foam · {state} · "
            f"{r.sim_time_s:.1f} s of cut simulated.{conv}")
        self.hifi_note.setText(self._hifi_text)
        self.hifi_note.setVisible(True)
        self.show_view(1)

    def mark_stale(self) -> None:
        if self.hifi_result is not None:
            self.hifi_note.setText("Parameters changed since this 2-D solve — run it again. " + self._hifi_text)
