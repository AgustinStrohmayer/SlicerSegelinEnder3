"""Curves tab: what every model predicts against feed, next to what was measured.

Left: what to show (quantity, drives, feed range, which sources) and the 2-D
points on demand. Right: the curves, the empirical law fitted to the
measurements, and predicted-vs-measured for every source.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QWidget,
)

from ....core.calibration import EmpiricalFit, Measurement, fit_empirical
from ....core.cutting_physics import CutSetup
from ....core.model_curves import (
    QUANTITIES,
    Series,
    empirical_series,
    errors_vs_measured,
    measured_series,
    model_series,
    thermal2d_series,
    to_csv,
)
from .common import Job, card, colors, qcolor, style_plot

PALETTE = ["#F28C28", "#5AA9E6", "#2BB673", "#E5484D", "#B07CE8", "#D6B656"]
SOURCES = {  # label, line style (None: markers only), marker
    "model": ("Model (calibrated)", Qt.PenStyle.SolidLine, None),
    "uncalibrated": ("Model, handbook values", Qt.PenStyle.DotLine, None),
    "empirical": ("Empirical law", Qt.PenStyle.DashDotLine, None),
    "2-D": ("2-D solve", None, "d"),
    "measured": ("Measured", None, "o"),
}
SOURCE_TEXT = {
    "model": "the reduced model with your η and κ",
    "uncalibrated": "the reduced model with handbook values only (η = κ = 1)",
    "empirical": "a power law fitted straight to your measurements, no physics",
    "2-D": "the 2-D heat-conduction solve, from first principles (no calibration)",
}


def _nums(text: str) -> list[float]:
    out = []
    for tok in text.replace(";", ",").split(","):
        try:
            x = float(tok.strip())
        except ValueError:
            continue
        if x > 0:
            out.append(x)
    return sorted(set(out))


def _b_meaning(b: float) -> str:
    if b < -0.85:
        return "close to −1: the wire delivers about the same power whatever the feed, so the kerf thins in proportion"
    if b < -0.35:
        return ("between −½ and −1: part of the heat goes into the foam that stays (the walls), more so at slow "
                "feeds — the usual case")
    return "flatter than −½: the kerf barely depends on feed — check for contact or a wire that runs too cold"


class CurvesTab(QWidget):
    def __init__(self, theme: str, get_setup: Callable[[], CutSetup],
                 get_measurements: Callable[[], list[Measurement]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._c = c = colors(theme)
        self._setup = get_setup
        self._meas = get_measurements
        self._series: list[Series] = []
        self._two_d: list[Series] = []
        self._two_d_setup: CutSetup | None = None
        self._emp: EmpiricalFit | None = None
        self._job: Job | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)
        lay.addWidget(split)

        # ── controls ──
        f, v = card("What to show", "Pick a quantity and the drives to compare. Curves use the parameters on the "
                    "left; measurements come from the Calibration tab.")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.quantity = QComboBox()
        for key, text in QUANTITIES.items():
            self.quantity.addItem(text, key)
        self.drives = QLineEdit()
        self.drives.setPlaceholderText("e.g. 1.0, 1.2, 1.4")
        self.drives.setToolTip("Currents (A) or voltages (V), comma separated.")
        self.from_meas = QPushButton("Use the measured drives")
        self.v_lo = QDoubleSpinBox()
        self.v_hi = QDoubleSpinBox()
        for sp, val in ((self.v_lo, 0.5), (self.v_hi, 12.0)):
            sp.setRange(0.05, 200)
            sp.setDecimals(2)
            sp.setSuffix(" mm/s")
            sp.setValue(val)
        self.logy = QCheckBox("Logarithmic vertical axis")
        form.addRow("Quantity", self.quantity)
        form.addRow("Drives", self.drives)
        form.addRow("", self.from_meas)
        form.addRow("Feed from", self.v_lo)
        form.addRow("to", self.v_hi)
        form.addRow("", self.logy)
        v.addLayout(form)
        v.addSpacing(6)
        src_title = QLabel("Sources")
        src_title.setObjectName("CardTitle")
        v.addWidget(src_title)
        self.show_src: dict[str, QCheckBox] = {}
        for key, (label, _, _) in SOURCES.items():
            cb = QCheckBox(label)
            cb.setChecked(key != "uncalibrated")
            if key in SOURCE_TEXT:
                cb.setToolTip(SOURCE_TEXT[key])
            self.show_src[key] = cb
            v.addWidget(cb)
        v.addSpacing(6)
        t = QLabel("2-D points")
        t.setObjectName("CardTitle")
        v.addWidget(t)
        sub = QLabel("Solves the cut's cross-section at a few feeds per drive. Coarse: a few seconds a point; "
                     "Normal: up to a minute a point at slow feeds.")
        sub.setObjectName("CardSub")
        sub.setWordWrap(True)
        v.addWidget(sub)
        row = QHBoxLayout()
        self.n2d = QSpinBox()
        self.n2d.setRange(2, 12)
        self.n2d.setValue(4)
        self.n2d.setSuffix(" feeds")
        self.q2d = QComboBox()
        for text, key in (("Coarse grid", "coarse"), ("Normal grid", "normal")):
            self.q2d.addItem(text, key)
        row.addWidget(self.n2d)
        row.addWidget(self.q2d)
        v.addLayout(row)
        row = QHBoxLayout()
        self.run2d = QPushButton("▶  Compute 2-D points")
        self.run2d.setProperty("role", "primary")
        self.cancel2d = QPushButton("Cancel")
        self.cancel2d.setEnabled(False)
        row.addWidget(self.run2d)
        row.addWidget(self.cancel2d)
        v.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(True)
        self.progress.setFormat("No 2-D points yet")
        v.addWidget(self.progress)
        v.addSpacing(6)
        row = QHBoxLayout()
        self.csv_btn = QPushButton("Export CSV…")
        self.png_btn = QPushButton("Save image…")
        row.addWidget(self.csv_btn)
        row.addWidget(self.png_btn)
        v.addLayout(row)
        v.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(f)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(350)
        split.addWidget(scroll)

        # ── plots ──
        right = QSplitter(Qt.Orientation.Vertical)
        f, v = card("Prediction curves", "Colour: drive. Line: source. Hollow markers: the wire touches the foam "
                    "(contact) at that point.")
        self.plot = pg.PlotWidget()
        self.plot.setBackground(c.bg)
        style_plot(self.plot, c)
        self.plot.setLogMode(x=True, y=False)
        self.plot.setLabel("bottom", "feed (mm/s)")
        self.plot.getAxis("left").enableAutoSIPrefix(False)
        self.plot.setMinimumHeight(280)
        v.addWidget(self.plot, 1)
        self.curve_card = f
        right.addWidget(f)
        bottom = QSplitter(Qt.Orientation.Horizontal)
        f, v = card("Empirical law", "Fitted straight to your measurements: a line in log–log.")
        self.emp_text = QLabel("")
        self.emp_text.setWordWrap(True)
        self.emp_text.setTextFormat(Qt.TextFormat.RichText)
        self.emp_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.emp_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.emp_text, 1)
        bottom.addWidget(f)
        f, v = card("Predicted vs measured", "Kerf of each source at your measured points; on the line = exact.")
        self.parity = pg.PlotWidget()
        self.parity.setBackground(c.bg)
        style_plot(self.parity, c)
        self.parity.setLabel("bottom", "measured kerf (mm)")
        self.parity.setLabel("left", "predicted (mm)")
        self.parity.setMouseEnabled(False, False)
        self.parity.hideButtons()
        v.addWidget(self.parity, 1)
        self.parity_text = QLabel("")
        self.parity_text.setObjectName("CardSub")
        self.parity_text.setTextFormat(Qt.TextFormat.RichText)
        self.parity_text.setWordWrap(True)
        v.addWidget(self.parity_text)
        bottom.addWidget(f)
        bottom.setSizes([420, 420])
        right.addWidget(bottom)
        right.setSizes([560, 320])
        split.addWidget(right)
        split.setSizes([360, 1000])

        self.quantity.currentIndexChanged.connect(self.refresh)
        self.drives.editingFinished.connect(self.refresh)
        self.from_meas.clicked.connect(self._drives_from_measurements)
        self.v_lo.valueChanged.connect(self.refresh)
        self.v_hi.valueChanged.connect(self.refresh)
        self.logy.toggled.connect(self.refresh)
        for cb in self.show_src.values():
            cb.toggled.connect(self.refresh)
        self.run2d.clicked.connect(self.run_2d)
        self.cancel2d.clicked.connect(self._cancel_2d)
        self.csv_btn.clicked.connect(self._export_csv)
        self.png_btn.clicked.connect(self._export_png)

    # ── inputs ────────────────────────────────────────────────────────
    def unit(self) -> str:
        return "A" if self._setup().mode == "current" else "V"

    def measurements(self) -> list[Measurement]:
        mode = self._setup().mode
        return [m for m in self._meas() if m.mode == mode]

    def drive_list(self) -> list[float]:
        ds = _nums(self.drives.text())
        if ds:
            return ds[:6]
        ms = self.measurements()
        if ms:
            return sorted({m.drive for m in ms})[:6]
        s = self._setup()
        d0 = s.current_a if s.mode == "current" else s.voltage_v
        return [round(d0 * f, 3) for f in (0.8, 1.0, 1.25)]

    def speeds(self) -> np.ndarray:
        lo, hi = sorted((self.v_lo.value(), self.v_hi.value()))
        return np.geomspace(lo, max(hi, lo * 1.5), 60)

    def _drives_from_measurements(self) -> None:
        ms = self.measurements()
        if ms:
            self.drives.setText(", ".join(f"{d:g}" for d in sorted({m.drive for m in ms})))
            vs = [m.speed_mm_s for m in ms]
            self.v_lo.setValue(min(vs) * 0.7)
            self.v_hi.setValue(max(vs) * 1.4)
        self.refresh()

    # ── compute & draw ────────────────────────────────────────────────
    def refresh(self) -> None:
        s = self._setup()
        drives, vs = self.drive_list(), self.speeds()
        if not self.drives.text().strip():
            self.drives.setPlaceholderText(", ".join(f"{d:g}" for d in drives) + f" {self.unit()}")
        ms = self.measurements()
        series = model_series(s, drives, vs) + model_series(s, drives, vs, "uncalibrated")
        try:
            self._emp = fit_empirical(ms) if ms else None
        except ValueError as exc:
            self._emp = None
            self.emp_text.setText(f"<span style='color:{self._c.warning}'>{exc}</span>")
        if self._emp is not None:
            series += empirical_series(self._emp, drives, vs)
        if self._two_d and self._two_d_setup != s:
            self._two_d = []
            self.progress.setValue(0)
            self.progress.setFormat("Parameters changed: compute the 2-D points again")
        series += [sr for sr in self._two_d if sr.drive in drives]
        series += measured_series(ms, s.mode)
        self._series = series
        self._draw()
        self._draw_empirical(ms)
        self._draw_parity(ms)

    def _pen_color(self, drive: float, drives: list[float]) -> str:
        k = drives.index(drive) if drive in drives else len(drives)
        return PALETTE[k % len(PALETTE)]

    def _draw(self) -> None:
        q = self.quantity.currentData()
        p = self.plot
        p.clear()
        leg = p.addLegend(offset=(-10, 8), colCount=2)
        leg.setLabelTextColor(self._c.muted)
        p.setLogMode(x=True, y=self.logy.isChecked())
        p.setLabel("left", QUANTITIES[q])
        drives = self.drive_list()
        unit = self.unit()
        named: set[float] = set()
        for sr in self._series:
            if not self.show_src[sr.source].isChecked() or q not in sr.values:
                continue
            col = self._pen_color(sr.drive, drives)
            _, style, marker = SOURCES[sr.source]
            y = sr.values[q]
            if q == "gap_mm" and self.logy.isChecked():
                y = np.maximum(y, 1e-3)
            name = None
            if sr.source in ("model", "measured") and sr.drive not in named and (
                    sr.source == "model" or not self.show_src["model"].isChecked()):
                name = f"{sr.drive:g} {unit}"
                named.add(sr.drive)
            if style is not None:
                p.plot(sr.speeds, y, pen=pg.mkPen(col, width=2 if sr.source == "model" else 1.6, style=style),
                       name=name)
            else:
                contact = sr.flags.get("contact", np.zeros(len(y), bool))
                brushes = [pg.mkBrush(self._c.bg) if c else pg.mkBrush(col) for c in contact]
                p.plot(sr.speeds, y, pen=None, symbol=marker, symbolSize=10 if marker == "o" else 12,
                       symbolBrush=brushes, symbolPen=pg.mkPen(col, width=1.5), name=name)
        # one legend entry per source, in a neutral colour
        for key, (label, style, marker) in SOURCES.items():
            if not self.show_src[key].isChecked():
                continue
            if style is not None:
                p.plot([], [], pen=pg.mkPen(self._c.muted, width=2, style=style), name=label)
            else:
                p.plot([], [], pen=None, symbol=marker, symbolBrush=pg.mkBrush(self._c.muted),
                       symbolPen=pg.mkPen(self._c.muted), name=label)
        p.enableAutoRange()

    def _draw_empirical(self, ms: list[Measurement]) -> None:
        c = self._c
        e = self._emp
        if e is None:
            if not ms:
                self.emp_text.setText(
                    "No measurements yet. Cut the staircase test (Calibration tab, steps 3–4) and enter the strip "
                    "thicknesses: the law <i>kerf = a · v<sup>b</sup> · I<sup>c</sup></i> is fitted here, with its "
                    "uncertainty, and every model is checked against your cuts.")
            return
        unit = "I" if e.mode == "current" else "U"
        se_b = f" ± {e.se_b:.2f}" if np.isfinite(e.se_b) else ""
        se_c = f" ± {e.se_c:.2f}" if np.isfinite(e.se_c) else ""
        drive = (f" · {unit}<sup>{e.c:.2f}</sup>" if e.c else "")
        rows = "".join(f"<tr><td>{d:g} {self.unit()}</td><td>&nbsp;a = {a:.3g}</td><td>&nbsp;b = {b:.2f}</td></tr>"
                       for d, a, b in e.per_drive)
        per = f"<br>One law per drive:<table>{rows}</table>" if len(e.per_drive) > 1 else ""
        c_line = (f"Exponent of the drive c = <b>{e.c:.2f}</b>{se_c}." if e.c else
                  "Measure at a second drive to fit how the kerf grows with it.")
        self.emp_text.setText(
            f"<span style='font-size:15px'><b>kerf = {e.a:.3g} · v<sup>{e.b:.2f}</sup>{drive}</b></span> "
            f"&nbsp;<span style='color:{c.muted}'>(mm, mm/s, {self.unit()})</span><br>"
            f"Exponent of the feed b = <b>{e.b:.2f}</b>{se_b}: {_b_meaning(e.b)}.<br>{c_line}<br>"
            f"R² = {e.r2:.3f} (log) · RMS error {e.rms_mm:.3f} mm over {e.n} points.{per}")

    def _draw_parity(self, ms: list[Measurement]) -> None:
        p = self.parity
        p.clear()
        self.parity_text.setText("")
        if not ms:
            return
        mode = self._setup().mode
        errs = errors_vs_measured(self._series, ms, mode)
        hi = max(m.kerf_mm for m in ms) * 1.3
        p.plot([0, hi], [0, hi], pen=pg.mkPen(self._c.muted, width=1, style=Qt.PenStyle.DashLine))
        lines = []
        colors_src = {"model": "#F28C28", "uncalibrated": "#9AA0A6", "empirical": "#2BB673", "2-D": "#5AA9E6"}
        for src, col in colors_src.items():
            if src not in errs or not self.show_src[src].isChecked():
                continue
            xs, ys = [], []
            for sr in self._series:
                if sr.source != src or len(sr.speeds) < 2:
                    continue
                for m in ms:
                    if abs(m.drive - sr.drive) < 1e-9 and sr.speeds[0] <= m.speed_mm_s <= sr.speeds[-1]:
                        xs.append(m.kerf_mm)
                        ys.append(float(np.exp(np.interp(np.log(m.speed_mm_s), np.log(sr.speeds),
                                                         np.log(sr.values["kerf_mm"])))))
            p.plot(xs, ys, pen=None, symbol="o", symbolSize=8, symbolBrush=pg.mkBrush(qcolor(col, 220)),
                   symbolPen=pg.mkPen(None))
            lines.append(f"<span style='color:{col}'>●</span> {SOURCES[src][0]}: RMS <b>{errs[src]:.3f}</b> mm")
        self.parity_text.setText(" &nbsp; ".join(lines))
        p.setXRange(0, hi, padding=0.02)
        p.setYRange(0, hi, padding=0.02)

    # ── 2-D points ────────────────────────────────────────────────────
    def run_2d(self) -> None:
        if self._job is not None:
            return
        s = self._setup()
        drives = self.drive_list()
        lo, hi = sorted((self.v_lo.value(), self.v_hi.value()))
        vs = np.geomspace(lo, max(hi, lo * 1.5), self.n2d.value())
        job = Job(thermal2d_series, s, drives, vs, quality=self.q2d.currentData(), parent=self)
        job._kw["progress"] = job.report
        job.progress.connect(self._on_progress)
        job.done.connect(lambda out: self._done_2d(out, s))
        job.failed.connect(self._failed_2d)
        self._job = job
        self.run2d.setEnabled(False)
        self.cancel2d.setEnabled(True)
        self.progress.setValue(0)
        self.progress.setFormat("2-D: starting…")
        job.start()

    def _on_progress(self, f: float, msg: str) -> None:
        self.progress.setValue(int(f * 1000))
        self.progress.setFormat(msg)

    def _done_2d(self, out: list[Series], s: CutSetup) -> None:
        self._job = None
        self.run2d.setEnabled(True)
        self.cancel2d.setEnabled(False)
        self._two_d = out
        self._two_d_setup = s
        n = sum(len(sr.speeds) for sr in out)
        self.progress.setValue(1000)
        self.progress.setFormat(f"{n} 2-D points")
        self.show_src["2-D"].setChecked(True)
        self.refresh()

    def _failed_2d(self, msg: str) -> None:
        self._job = None
        self.run2d.setEnabled(True)
        self.cancel2d.setEnabled(False)
        self.progress.setValue(0)
        self.progress.setFormat("2-D: cancelled" if msg == "cancelled" else "2-D failed: " + msg.splitlines()[-1])

    def _cancel_2d(self) -> None:
        if self._job is not None:
            self._job.cancelled = True

    # ── export ────────────────────────────────────────────────────────
    def csv_text(self) -> str:
        return to_csv(self._series, self._setup().mode)

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export curves", "cut_lab_curves.csv", filter="CSV (*.csv)")
        if path:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(self.csv_text())

    def _export_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save image", "cut_lab_curves.png", filter="PNG (*.png)")
        if path:
            self.grab().save(path)
