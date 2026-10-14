"""Cut-simulation tab: the slicer-like view of what the hot wire removes and what part comes out.

Left: the selected slice (a Y–Z cross-section of the block at one X along the
wire), replayable in time. Right: the stack of slices ("layers") — a list and
a 3D view of the part's edge in every slice, coloured by its deviation from
the nominal part — and the part's numbers.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ....core.cut_sim import SimResult, SliceResult
from ....core.hotwire_rig import FoamBlock
from ..numfield import NumField
from .common import FOAM, REGIME, card, colors, diverging_cmap, fmt, heat_cmap, style_plot

SPEEDS = (1.0, 2.0, 5.0, 10.0, 25.0)
COLOR_MODES = ("Kerf width", "Regime", "Removal time")


def _rgb(hex_: str) -> np.ndarray:
    h = hex_.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.ubyte)


class SliceView(pg.PlotWidget):
    """One slice of the block, recoloured for any instant of the cut."""

    def __init__(self, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        c = self._c = colors(theme)
        self.setBackground(c.bg)
        self.setAspectLocked(True)
        style_plot(self, c)
        pi = self.getPlotItem()
        pi.setLabel("bottom", "Y (mm, G-code)")
        pi.setLabel("left", "Z (mm)")
        self.img = pg.ImageItem()
        self.addItem(self.img)
        self.path = pg.PlotDataItem(pen=pg.mkPen(c.text, width=1, style=Qt.PenStyle.DashLine))
        self.path.setOpacity(0.55)
        self.addItem(self.path)
        self.edge = pg.ScatterPlotItem(size=3, pen=pg.mkPen(None))
        self.addItem(self.edge)
        self.melt = pg.ScatterPlotItem(pxMode=False, pen=pg.mkPen("#F59E0B", width=1.5), brush=pg.mkBrush(245, 158, 11, 60))
        self.addItem(self.melt)
        self.cmd = pg.ScatterPlotItem(size=11, symbol="+", pen=pg.mkPen(c.text, width=1.5), brush=None)
        self.addItem(self.cmd)
        self.hover = pg.TextItem("", color=c.text, anchor=(0, 1), fill=pg.mkBrush(c.surface))
        self.hover.setZValue(20)
        self.addItem(self.hover)
        self.hover.hide()
        self.scene().sigMouseMoved.connect(self._move)
        self.res: SimResult | None = None
        self.sl: SliceResult | None = None
        self.mode = 0
        self._removed_rgba: np.ndarray | None = None
        self._base: np.ndarray | None = None
        self._kmax = 1.0

    def set_slice(self, res: SimResult, sl: SliceResult, mode: int) -> None:
        first = self.res is not res
        self.res, self.sl, self.mode = res, sl, mode
        nz, ny = sl.t_removed.shape
        removed = np.isfinite(sl.t_removed)
        # colours of removed cells (static for this slice and mode)
        rr = np.zeros((nz, ny, 4), np.ubyte)
        if mode == 0:
            r = sl.r_removed.astype(np.float32)
            self._kmax = float(np.nanpercentile(r[removed], 99)) * 2 if removed.any() else 1.0
            lut = heat_cmap().getLookupTable(0.0, 1.0, 256, alpha=True)
            idx = np.clip((2 * r / max(self._kmax, 1e-6)) * 255, 0, 255).astype(np.int32)
            rr[:] = lut[idx]
        elif mode == 1:
            rr[..., :3] = _rgb(REGIME["noncontact"])
            rr[sl.contact] = (*_rgb(REGIME["contact"]), 255)
        else:
            lut = pg.colormap.get("viridis").getLookupTable(0.0, 1.0, 256, alpha=True)
            tt = np.where(removed, sl.t_removed, 0) / max(res.samples.total_s, 1e-9)
            rr[:] = lut[np.clip(tt * 255, 0, 255).astype(np.int32)]
        rr[..., 3] = 255
        self._removed_rgba = rr
        base = np.zeros((nz, ny, 4), np.ubyte)
        base[...] = (*_rgb(FOAM), 120)
        base[sl.product] = (*_rgb("#B9D7F5"), 255)
        self._base = base
        self.img.setRect(QRectF(res.y0, res.z0, ny * res.h, nz * res.h))
        self.path.setData(res.samples.y, res.samples.z)
        if len(sl.edge_dev):
            lim = max(0.05, float(np.max(np.abs(sl.edge_dev))))
            lut = diverging_cmap().getLookupTable(0.0, 1.0, 256, alpha=True)
            k = np.clip((sl.edge_dev / lim + 1) / 2 * 255, 0, 255).astype(np.int32)
            step = max(1, len(k) // 12000)
            cols = lut[k[::step]]
            self._edge = (sl.edge_y[::step], sl.edge_z[::step], [pg.mkBrush(*map(int, q)) for q in cols])
        else:
            self._edge = (np.zeros(0), np.zeros(0), [])
        if first:
            b = res.block
            self.setXRange(b.y0, b.y1, padding=0.03)
            self.setYRange(b.z0, b.z1, padding=0.05)

    def set_time(self, t: float) -> None:
        if self.res is None or self.sl is None or self._removed_rgba is None or self._base is None:
            return
        sl, res = self.sl, self.res
        done = sl.t_removed <= t
        img = self._base.copy()
        if t < res.samples.total_s:
            # before the end the product isn't separated yet: draw all foam alike
            img[...] = (*_rgb(FOAM), 200)
        img[done] = self._removed_rgba[done]
        self.img.setImage(img, axisOrder="row-major", autoLevels=False)
        i = res.samples.index_at(t)
        # in air (or parked) the melt zone means nothing: just draw the wire itself
        d = 2 * float(sl.radius[i]) if sl.in_foam[i] else res.setup.diameter_mm
        self.melt.setData([sl.wire_y[i]], [sl.wire_z[i]], size=[max(d, 0.05)])
        self.cmd.setData([res.samples.y[i]], [res.samples.z[i]])
        if t >= res.samples.total_s - 1e-9 and len(self._edge[0]):
            self.edge.setData(self._edge[0], self._edge[1], brush=self._edge[2])
        else:
            self.edge.setData([], [])

    def _move(self, pos) -> None:  # type: ignore[no-untyped-def]
        if self.res is None or self.sl is None:
            return
        p = self.getPlotItem().vb.mapSceneToView(pos)
        res, sl = self.res, self.sl
        j = math.floor((p.x() - res.y0) / res.h)
        i = math.floor((p.y() - res.z0) / res.h)
        nz, ny = sl.t_removed.shape
        if not (0 <= i < nz and 0 <= j < ny):
            self.hover.hide()
            return
        tr = float(sl.t_removed[i, j])
        if math.isfinite(tr):
            txt = (f"removed at {tr:.1f} s · kerf {2 * float(sl.r_removed[i, j]):.2f} mm\n"
                   + ("wire touching (contact)" if sl.contact[i, j] else "non-contact"))
        else:
            txt = "part" if sl.product[i, j] else "foam (scrap)"
        if len(sl.edge_dev):
            d2 = (sl.edge_y - p.x()) ** 2 + (sl.edge_z - p.y()) ** 2
            k = int(np.argmin(d2))
            if d2[k] < (4 * res.h + 0.5) ** 2:
                dv = float(sl.edge_dev[k])
                txt += f"\nedge {'+' if dv >= 0 else '−'}{abs(dv):.3f} mm {'excess' if dv >= 0 else 'loss'}"
        self.hover.setText(f"Y {p.x():.2f}  Z {p.y():.2f}\n{txt}")
        self.hover.setPos(p)
        self.hover.show()


class Layers3D(QWidget):
    """The part's edge in every slice, stacked along the wire and coloured by deviation."""

    def __init__(self, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from ..view3d import Scene3D

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = Scene3D(self, theme)
        self.view.setMinimumHeight(220)
        lay.addWidget(self.view)

    def show_result(self, res: SimResult, selected: int) -> None:
        sc = self.view
        first = not sc.has("block")
        sc.clear()
        devs = [s.edge_dev for s in res.slices if len(s.edge_dev)]
        lim = max(0.05, max((float(np.max(np.abs(d))) for d in devs), default=0.05))
        lut = diverging_cmap().getLookupTable(0.0, 1.0, 256, alpha=True).astype(float) / 255
        b = res.block
        yc, zc = (b.y0 + b.y1) / 2, (b.z0 + b.z1) / 2
        for k, s in enumerate(res.slices):
            if not len(s.edge_dev):
                continue
            step = max(1, len(s.edge_dev) // 2500)
            pos = np.column_stack([np.full(len(s.edge_y[::step]), s.x_mm), s.edge_y[::step] - yc,
                                   s.edge_z[::step] - zc])
            col = lut[np.clip((s.edge_dev[::step] / lim + 1) / 2 * 255, 0, 255).astype(int)]
            if k != selected:
                col[:, 3] = 0.55
            sc.points(f"slice{k}", pos, colors=col, size=4 if k == selected else 2.5)
        xl, xr = b.x_offset - b.width_x / 2, b.x_offset + b.width_x / 2
        y0, y1, z0, z1 = b.y0 - yc, b.y1 - yc, b.z0 - zc, b.z1 - zc
        sc.box("block", xl, y0, z0, xr, y1, z1, FOAM, opacity=0.10, shadow=False)
        edges = []
        for x in (xl, xr):
            edges += [[x, y0, z0], [x, y1, z0], [x, y1, z1], [x, y0, z1], [x, y0, z0], [np.nan] * 3]
        for y, z in ((y0, z0), (y1, z0), (y1, z1), (y0, z1)):
            edges += [[xl, y, z], [xr, y, z], [np.nan] * 3]
        sc.lines("block_edges", np.array(edges, float), (0.5, 0.7, 0.9, 0.6), width=1.0)
        if first:
            sc.fit(24, -60, animate=False)


class SimTab(QWidget):
    run_requested = pyqtSignal()
    cancel_requested = pyqtSignal()
    block_changed = pyqtSignal(object)

    def __init__(self, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._c = colors(theme)
        self.res: SimResult | None = None
        self.t = 0.0
        self._last = 0.0
        self._syncing = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        bar = QHBoxLayout()
        self.run_btn = QPushButton("▶  Run cut simulation")
        self.run_btn.setProperty("role", "primary")
        self.run_btn.clicked.connect(self.run_requested.emit)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(True)
        self.progress.setFormat("Ready")
        self.slices = QSpinBox()
        self.slices.setRange(1, 25)
        self.slices.setValue(7)
        self.slices.setPrefix("Slices ")
        self.slices.setToolTip("How many cross-sections along the wire to simulate.")
        self.res_combo = QComboBox()
        self.res_combo.addItems(["Fast (0.2 mm)", "Normal (auto)", "Fine (0.03 mm)"])
        self.res_combo.setCurrentIndex(1)
        self.res_combo.setToolTip("Grid cell size of each slice.")
        self.color = QComboBox()
        self.color.addItems(COLOR_MODES)
        self.color.setToolTip("Colour of the removed foam.")
        self.color.currentIndexChanged.connect(lambda _: self._select(self.layers.currentRow()))
        for w in (self.run_btn, self.cancel_btn):
            bar.addWidget(w)
        bar.addWidget(self.progress, 1)
        bar.addWidget(self.slices)
        bar.addWidget(self.res_combo)
        bar.addWidget(QLabel("Colour"))
        bar.addWidget(self.color)
        lay.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        f, v = card("Slice", "A cross-section of the block at one position along the wire. Dashed: programmed path. "
                    "Cross: commanded wire; amber disc: the wire's melt zone (lagging when it bows). At the end the "
                    "part's edge is coloured by deviation: red = material lost, blue = extra material.")
        self.view = SliceView(theme)
        v.addWidget(self.view, 1)
        lv.addWidget(f, 1)
        lv.addLayout(self._transport())
        split.addWidget(left)

        right = QSplitter(Qt.Orientation.Vertical)
        f, v = card("Layers along the wire",
                    "Cross-sections of the block at several positions (X) along the wire. Pick one to see it on "
                    "the left. ✓ = the part comes free; mean edge below 0 = smaller than drawn.")
        self.layers = QListWidget()
        self.layers.currentRowChanged.connect(self._select)
        self.layers.setStyleSheet("QListWidget::item { padding: 1px 6px; min-height: 20px; }")
        self.layers.setMinimumHeight(110)
        v.addWidget(self.layers)
        right.addWidget(f)
        f, v = card("Part, all layers (3D)",
                    "Why do the layers differ? The wire runs across the whole block but isn't the same along its "
                    "length: it is hottest in the middle and cooler near the arms, and when it touches the foam it "
                    "bends back most in the middle. So each position along the wire is cut a little differently. "
                    "Here every layer's outline is stacked along the wire as on the machine (the selected one is "
                    "brighter); if they differ, the part comes out slightly barrel-shaped. Red edge: smaller than "
                    "drawn; blue: bigger. Drag to orbit.")
        self.view3d = Layers3D(theme)
        v.addWidget(self.view3d, 1)
        right.addWidget(f)
        f, v = card("Result")
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(0, 0, 6, 0)
        self.stats = QLabel("Run the simulation to see the part that comes out.")
        self.stats.setWordWrap(True)
        self.stats.setTextFormat(Qt.TextFormat.RichText)
        self.stats.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bv.addWidget(self.stats)
        bv.addWidget(self._block_form())
        bv.addStretch(1)
        scroll = QScrollArea()  # stats + block form scroll so the 3D view keeps its room
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        v.addWidget(scroll, 1)
        right.addWidget(f)
        right.setSizes([200, 330, 250])
        split.addWidget(right)
        split.setSizes([860, 380])
        lay.addWidget(split, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)

    # ── block ─────────────────────────────────────────────────────────
    def _block_form(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 6, 0, 0)

        def sp(lo: float, hi: float) -> NumField:
            s = NumField(step=5)
            s.setRange(lo, hi)
            s.setDecimals(1)
            s.setSuffix(" mm")
            s.setKeyboardTracking(False)
            s.valueChanged.connect(self._block_edit)
            return s

        self.b_y0, self.b_z0 = sp(-1000, 1000), sp(-1000, 1000)
        self.b_len, self.b_h = sp(1, 2000), sp(1, 1000)
        f.addRow("Block front face Y", self.b_y0)
        f.addRow("Block bottom Z", self.b_z0)
        f.addRow("Block length (Y)", self.b_len)
        f.addRow("Block height (Z)", self.b_h)
        return w

    def set_block(self, b: FoamBlock) -> None:
        self._syncing = True
        for s, val in ((self.b_y0, b.y0), (self.b_z0, b.z0), (self.b_len, b.length_y), (self.b_h, b.height_z)):
            s.setValue(val)
        self._syncing = False

    def _block_edit(self) -> None:
        if not self._syncing:
            self.block_changed.emit((self.b_y0.value(), self.b_z0.value(), self.b_len.value(), self.b_h.value()))

    def cell_mm(self) -> float | None:
        return {0: 0.2, 1: None, 2: 0.03}[self.res_combo.currentIndex()]

    # ── transport ─────────────────────────────────────────────────────
    def _transport(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.play = QPushButton("▶ Play")
        self.play.setCheckable(True)
        self.play.toggled.connect(self._toggle_play)
        self.speed = QComboBox()
        self.speed.addItems([f"{s:g}×" for s in SPEEDS])
        self.speed.setCurrentIndex(3)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 2000)
        self.slider.valueChanged.connect(self._slid)
        self.clock = QLabel("0.0 / 0.0 s")
        self.clock.setMinimumWidth(100)
        self.readout = QLabel("")
        self.readout.setProperty("role", "mono")
        self.readout.setMinimumWidth(330)
        for w in (self.play, self.speed):
            row.addWidget(w)
        row.addWidget(self.slider, 1)
        row.addWidget(self.clock)
        row.addWidget(self.readout)
        return row

    def _slid(self, v: int) -> None:
        if self.res is not None and not self._syncing:
            self.set_time(v / 2000 * self.res.samples.total_s)

    def _toggle_play(self, on: bool) -> None:
        self.play.setText("❚❚ Pause" if on else "▶ Play")
        if on and self.res is not None:
            if self.t >= self.res.samples.total_s - 1e-9:
                self.t = 0.0
            self._last = time.perf_counter()
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self) -> None:
        if self.res is None:
            return
        now = time.perf_counter()
        dt, self._last = now - self._last, now
        t = self.t + dt * SPEEDS[self.speed.currentIndex()]
        if t >= self.res.samples.total_s:
            t = self.res.samples.total_s
            self.play.setChecked(False)
        self.set_time(t)

    def set_time(self, t: float) -> None:
        if self.res is None:
            return
        total = self.res.samples.total_s
        self.t = max(0.0, min(t, total))
        self.view.set_time(self.t)
        self.clock.setText(f"{self.t:6.1f} / {total:.1f} s")
        self._syncing = True
        if not self.slider.isSliderDown():
            self.slider.setValue(int(2000 * self.t / total) if total else 0)
        self._syncing = False
        sl = self.view.sl
        if sl is not None:
            i = self.res.samples.index_at(self.t)
            v = float(self.res.samples.v[i])
            state = ("contact" if sl.contact_t[i] else "cutting") if sl.in_foam[i] else "in air / own kerf"
            lag = math.hypot(sl.wire_y[i] - self.res.samples.y[i], sl.wire_z[i] - self.res.samples.z[i])
            kerf = f"{2 * sl.radius[i]:.2f}" if sl.in_foam[i] else "—"
            self.readout.setText(f"v {v:5.2f} mm/s  kerf {kerf}  lag {lag:.2f}  {state}")

    # ── results ───────────────────────────────────────────────────────
    def busy(self, on: bool) -> None:
        self.run_btn.setEnabled(not on)
        self.cancel_btn.setEnabled(on)
        if on:
            self.progress.setValue(0)

    def on_progress(self, f: float, msg: str) -> None:
        self.progress.setValue(int(f * 1000))
        self.progress.setFormat(msg)

    def show_result(self, res: SimResult) -> None:
        self.res = res
        self.layers.blockSignals(True)
        self.layers.clear()
        for s in res.slices:
            ok = "✓" if s.released else "✗"
            dm = s.stats.get("dev_mean")
            txt = f"{ok}  X {s.x_mm:+7.1f} mm   mean edge {fmt(dm, 3) if dm is not None else '—'} mm"
            QListWidgetItem(txt, self.layers)
        self.layers.blockSignals(False)
        mid = len(res.slices) // 2
        self.layers.setCurrentRow(mid)
        self._select(mid)
        self.progress.setFormat(f"Done · {len(res.slices)} slices · cell {res.h:.3f} mm")
        self.set_time(res.samples.total_s)

    def _select(self, k: int) -> None:
        if self.res is None or not (0 <= k < len(self.res.slices)):
            return
        self.view.set_slice(self.res, self.res.slices[k], self.color.currentIndex())
        self.view.set_time(self.t)
        self.view3d.show_result(self.res, k)
        self._stats(k)

    def _stats(self, k: int) -> None:
        res = self.res
        assert res is not None
        s = res.slices[k]
        st = s.stats
        c = self._c
        ok, bad, warn = c.success, c.danger, c.warning
        lines = [f"<b>Layer X {s.x_mm:+.1f} mm</b> &nbsp; "
                 + (f"<span style='color:{ok}'>✓ part released</span>" if s.released
                    else f"<span style='color:{bad}'>✗ no closed part in this slice</span>")]
        if "length_y" in st:
            loss = 100 * (1 - st["area_mm2"] / max(st["nominal_area_mm2"], 1e-9))
            lines.append(f"Size Y × Z: <b>{st['length_y']:.2f} × {st['height_z']:.2f}</b> mm "
                         f"(nominal {st['nominal_length_y']:.2f} × {st['nominal_height_z']:.2f})")
            lines.append(f"Area: {st['area_mm2']:.0f} mm² ({loss:+.1f} % lost)")
            lines.append(f"Edge vs nominal: mean <b>{st['dev_mean']:+.3f}</b>, worst loss {st['dev_min']:+.3f}, "
                         f"worst excess {st['dev_max']:+.3f} mm")
            lines.append(f"Wire touching the foam on {100 * st['contact_frac']:.0f} % of the cut")
            comp = -st["dev_mean"]
            if comp > 0.02:
                lines.append(f"<span style='color:{c.accent}'>→ To hit the nominal size, offset the path outward "
                             f"by ≈ {comp:.2f} mm (kerf compensation).</span>")
        summ = res.summary()
        if "dev_mean" in summ and len(res.slices) > 1:
            spread = max(s.stats.get("dev_mean", 0) for s in res.slices) - min(
                s.stats.get("dev_mean", 0) for s in res.slices)
            lines.append(f"<br><b>All layers</b>: mean edge {summ['dev_mean']:+.3f} mm; "
                         f"varies {spread:.3f} mm along the wire (barrelling)")
        for w in res.warnings:
            lines.append(f"<span style='color:{warn}'>⚠ {w}</span>")
        self.stats.setText("<br>".join(lines))

