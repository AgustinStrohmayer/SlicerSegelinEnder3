"""Calibration tab: a step-by-step guide from test cuts to a fitted model.

The guide can be followed once per machine or repeated whenever the wire,
foam or supply change. Measurements are kept in the Cut Lab profile.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ....core.calibration import (
    FitResult,
    Measurement,
    StaircaseSpec,
    fit,
    fit_empirical,
    resistivity_from_cold,
    section_warnings,
    staircase_gcode,
    temperature_from_resistance,
)
from ....core.cutting_physics import CutSetup, point_state, resistance_per_m, span_profile
from ..numfield import NumField
from .common import colors, style_plot

STEPS = (
    "1 · What & why",
    "2 · Check the wire",
    "3 · Cut the test strips",
    "4 · Measure",
    "5 · Fit & apply",
    "6 · Bow (optional)",
)


def _num_list(text: str) -> list[float]:
    out = []
    for tok in text.replace(";", ",").split(","):
        tok = tok.strip()
        if tok:
            try:
                out.append(float(tok))
            except ValueError:
                pass
    return out


def _body(html: str) -> QLabel:
    lab = QLabel(html)
    lab.setObjectName("StepBody")
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.TextFormat.RichText)
    lab.setOpenExternalLinks(True)
    return lab


def _spin(lo: float, hi: float, val: float, dec: int, suffix: str) -> NumField:
    s = NumField()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


class CalibrationTab(QWidget):
    apply_calibration = pyqtSignal(float, float)   # eta, kappa
    apply_resistivity = pyqtSignal(float)          # Ω·m at 20 °C
    apply_drag = pyqtSignal(float)
    preview_gcode = pyqtSignal(str, str)           # text, name
    measurements_changed = pyqtSignal()

    def __init__(self, theme: str, get_setup: Callable[[], CutSetup], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._c = colors(theme)
        self._setup = get_setup
        self.measurements: list[Measurement] = []
        self._fit: FitResult | None = None
        self._filling = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.steps = QListWidget()
        self.steps.addItems(STEPS)
        self.steps.setFixedWidth(190)
        lay.addWidget(self.steps)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        for build in (self._step_intro, self._step_wire, self._step_test, self._step_measure, self._step_fit,
                      self._step_bow):
            page = QWidget()
            v = QVBoxLayout(page)
            v.setContentsMargins(12, 6, 12, 6)
            build(v)
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setWidget(page)
            self.stack.addWidget(sa)
        self.steps.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.steps.setCurrentRow(0)

    def _nav(self, v: QVBoxLayout, k: int) -> None:
        row = QHBoxLayout()
        row.addStretch(1)
        if k > 0:
            b = QPushButton("← Back")
            b.clicked.connect(lambda: self.steps.setCurrentRow(k - 1))
            row.addWidget(b)
        if k < len(STEPS) - 1:
            b = QPushButton("Next →")
            b.setProperty("role", "primary")
            b.clicked.connect(lambda: self.steps.setCurrentRow(k + 1))
            row.addWidget(b)
        v.addStretch(1)
        v.addLayout(row)

    @staticmethod
    def _title(v: QVBoxLayout, text: str) -> None:
        t = QLabel(text)
        t.setObjectName("StepTitle")
        v.addWidget(t)

    # ── 1 ─────────────────────────────────────────────────────────────
    def _step_intro(self, v: QVBoxLayout) -> None:
        self._title(v, "Calibrate the model to your machine")
        v.addWidget(_body(
            "The physics behind the Cut Lab is general; the numbers that make it <i>yours</i> come from a few "
            "test cuts. Calibration fits two factors: <b>η</b> (how well heat crosses from the wire to the foam) "
            "and <b>κ</b> (how wide the kerf is relative to the melt front). After it, the predicted kerf "
            "matches what your wire, supply and foam really do.<br><br>"
            "<b>Why test strips instead of measuring the kerf?</b> A kerf is a narrow, soft-walled slot that "
            "calipers can't measure well. Instead, two parallel cuts <i>W</i> apart free a strip whose thickness is "
            "<i>W − kerf</i>: an outside measurement, the one calipers are good at. Each cut is split into steps "
            "at different feeds, so one strip gives one kerf per feed.<br><br>"
            "<b>You need</b><ul>"
            "<li>a foam block of the kind you'll cut, about 200 × 40 mm (Y × Z) and as wide as your parts;</li>"
            "<li>a caliper (0.01–0.02 mm), and two thin flat plates (e.g. glass slides) to measure soft foam;</li>"
            "<li>your supply's current/voltage read-out; optionally a multimeter;</li>"
            "<li>about 30 minutes. Repeat when the wire, foam batch or supply changes.</li></ul>"))
        self._nav(v, 0)

    # ── 2 ─────────────────────────────────────────────────────────────
    def _step_wire(self, v: QVBoxLayout) -> None:
        self._title(v, "Check the wire")
        v.addWidget(_body(
            "With the supply <b>off</b>, measure the wire's resistance clamp-to-clamp with a multimeter "
            "(subtract the probes' own reading). It pins down the wire's real resistivity and diameter "
            "together, which sets the Joule heat."))
        f = QFormLayout()
        self.r_cold = _spin(0, 1000, 0, 3, " Ω")
        f.addRow("Cold resistance (measured)", self.r_cold)
        self.r_expected = QLabel()
        f.addRow("Expected from the parameters", self.r_expected)
        btn = QPushButton("Use measured resistance")
        btn.clicked.connect(self._apply_cold)
        f.addRow(btn)
        v.addLayout(f)
        v.addWidget(_body(
            "<br>Then switch the supply on with the wire in free air and read voltage and current once it has "
            "settled. For wires whose resistance changes a lot with temperature (stainless, steel) this gives "
            "the wire's real temperature; nichrome and Kanthal barely change, so there it only checks the "
            "power."))
        f = QFormLayout()
        self.v_hot = _spin(0, 100, 0, 2, " V")
        self.i_hot = _spin(0, 20, 0, 3, " A")
        f.addRow("Voltage across the wire", self.v_hot)
        f.addRow("Current", self.i_hot)
        self.hot_out = QLabel("")
        self.hot_out.setWordWrap(True)
        f.addRow(self.hot_out)
        for w in (self.r_cold, self.v_hot, self.i_hot):
            w.valueChanged.connect(self._wire_check)
        v.addLayout(f)
        self._nav(v, 1)

    def _wire_check(self) -> None:
        s = self._setup()
        r_exp = float(resistance_per_m(s.ambient_c + 273.15, s)) * s.span_mm * 1e-3
        self.r_expected.setText(f"{r_exp:.3f} Ω ({s.wire.name}, Ø {s.diameter_mm:.2f} mm, span {s.span_mm:.0f} mm)")
        msg = []
        if self.v_hot.value() > 0 and self.i_hot.value() > 0:
            r_hot = self.v_hot.value() / self.i_hot.value()
            msg.append(f"Hot resistance {r_hot:.3f} Ω, power {self.v_hot.value() * self.i_hot.value():.1f} W.")
            st = point_state(s, 1.0, current_a=self.i_hot.value())
            msg.append(f"The model puts the wire at {float(st.t_air_c):.0f} °C in air at {self.i_hot.value():.2f} A.")
            r_cold = self.r_cold.value() or r_exp
            t = temperature_from_resistance(r_hot, r_cold, s)
            if t is not None:
                msg.append(f"From the resistance change the wire is at ≈ <b>{t:.0f} °C</b>.")
            else:
                msg.append("This alloy's resistance barely changes with temperature: no temperature reading.")
        self.hot_out.setText(" ".join(msg))

    def _apply_cold(self) -> None:
        if self.r_cold.value() > 0:
            self.apply_resistivity.emit(resistivity_from_cold(self.r_cold.value(), self._setup()))
            self._wire_check()

    # ── 3 ─────────────────────────────────────────────────────────────
    def _step_test(self, v: QVBoxLayout) -> None:
        self._title(v, "Cut the test strips")
        v.addWidget(_body(
            "One G-code per drive setting. Each makes two cuts through the whole block at the heights below; "
            "each cut runs the feeds in order, slow to fast. The wire goes back over the top of the block in air "
            "between them, so both faces of each step see the same wire."))
        f = QFormLayout()
        self.t_speeds = QLineEdit("1, 2, 3.5, 6, 10")
        self.t_speeds.setToolTip("Feeds of the steps, mm/s, slow to fast.")
        self.t_drives = QLineEdit("")
        self.t_drives.setToolTip("Current (A) or voltage (V) settings: one strip per value.")
        self.t_len = _spin(40, 1000, 200, 0, " mm")
        self.t_h = _spin(15, 500, 40, 0, " mm")
        self.t_w = _spin(2, 50, 10, 1, " mm")
        self.t_z = _spin(1, 200, 12, 1, " mm")
        f.addRow("Feeds (mm/s)", self.t_speeds)
        f.addRow("Drive settings", self.t_drives)
        f.addRow("Block length (Y)", self.t_len)
        f.addRow("Block height (Z)", self.t_h)
        f.addRow("Strip, nominal (W)", self.t_w)
        f.addRow("Lower cut height", self.t_z)
        v.addLayout(f)
        for w in (self.t_len, self.t_h, self.t_w, self.t_z):
            w.valueChanged.connect(self._refresh_test)
        self.t_speeds.editingFinished.connect(self._refresh_test)
        self.t_drives.editingFinished.connect(self._refresh_test)
        self.t_warn = QLabel("")
        self.t_warn.setWordWrap(True)
        v.addWidget(self.t_warn)
        self.t_table = QTableWidget()
        self.t_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.t_table.setMinimumHeight(150)
        v.addWidget(QLabel("Predicted strip thickness (mm) with the current model:"))
        v.addWidget(self.t_table)
        row = QHBoxLayout()
        b = QPushButton("Save G-code files…")
        b.setProperty("role", "primary")
        b.clicked.connect(self._save_tests)
        p = QPushButton("Preview first test in the simulator")
        p.clicked.connect(self._preview_test)
        row.addWidget(b)
        row.addWidget(p)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(_body(
            "<b>Setting up</b><ol>"
            "<li>Put the block on the bed (on its spacer), its front face across the Y axis.</li>"
            "<li>Park the wire 5 mm in front of the front face, level with the block's bottom, and run the "
            "file from there: it starts with <code>G92 Y0 Z0</code>.</li>"
            "<li>Set the supply to the drive written in the file name, let the wire settle in air for ~10 s, "
            "start.</li>"
            "<li>Label each strip with its drive as it comes out.</li></ol>"))
        self._nav(v, 2)

    def spec(self) -> StaircaseSpec:
        speeds = tuple(_num_list(self.t_speeds.text())) or (1.0, 2.0, 3.5, 6.0, 10.0)
        return StaircaseSpec(speeds_mm_s=speeds, block_length_mm=self.t_len.value(),
                             block_height_mm=self.t_h.value(), strip_mm=self.t_w.value(),
                             first_cut_z_mm=self.t_z.value())

    def drives(self) -> list[float]:
        s = self._setup()
        d = _num_list(self.t_drives.text())
        if not d:
            base = s.current_a if s.mode == "current" else s.voltage_v
            d = [round(base * 0.85, 2), round(base, 2), round(base * 1.2, 2)]
            self.t_drives.setText(", ".join(f"{x:g}" for x in d))
        return d

    def _unit(self) -> str:
        return "A" if self._setup().mode == "current" else "V"

    def _refresh_test(self) -> None:
        s = self._setup()
        spec, drives = self.spec(), self.drives()
        warn = section_warnings(spec, s)
        if spec.first_cut_z_mm + spec.strip_mm >= spec.block_height_mm - 2:
            warn.append("The upper cut is too close to the block top.")
        self.t_warn.setText("".join(f"<span style='color:{self._c.warning}'>⚠ {w}</span><br>" for w in warn))
        self.t_table.setRowCount(len(drives))
        self.t_table.setColumnCount(len(spec.speeds_mm_s))
        self.t_table.setHorizontalHeaderLabels([f"{x:g} mm/s" for x in spec.speeds_mm_s])
        self.t_table.setVerticalHeaderLabels([f"{d:g} {self._unit()}" for d in drives])
        kw = "current_a" if s.mode == "current" else "voltage_v"
        for i, d in enumerate(drives):
            st = point_state(s, np.array(spec.speeds_mm_s), **{kw: d})
            for j, k in enumerate(st.kerf_mm):
                txt = f"{spec.strip_mm - float(k):.2f}" + (" ⚠" if bool(st.stall[j]) else "")
                self.t_table.setItem(i, j, QTableWidgetItem(txt))
        self.t_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._rebuild_measure_table()

    def _save_tests(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Folder for the test G-code files")
        if not folder:
            return
        spec = self.spec()
        for d in self.drives():
            name = f"kerf_test_{d:g}{self._unit()}.gcode"
            (Path(folder) / name).write_text(staircase_gcode(spec, f"{d:g} {self._unit()}"), encoding="utf-8")
        self.t_warn.setText(self.t_warn.text() + f"Saved {len(self.drives())} file(s) to {folder}.")

    def _preview_test(self) -> None:
        d = self.drives()[0]
        self.preview_gcode.emit(staircase_gcode(self.spec(), f"{d:g} {self._unit()}"),
                                f"kerf_test_{d:g}{self._unit()}.gcode")

    # ── 4 ─────────────────────────────────────────────────────────────
    def _step_measure(self, v: QVBoxLayout) -> None:
        self._title(v, "Measure the strips")
        self.m_points = _body("")
        v.addWidget(self.m_points)
        v.addWidget(_body(
            "<b>How to measure soft foam</b><ul>"
            "<li>Let the strips cool. Mark the steps from the end that faced the front of the block.</li>"
            "<li>Sandwich the strip between two thin flat plates and close the caliper until the plates just "
            "stop moving — don't squeeze. Subtract the plates' thickness.</li>"
            "<li>Measure in the <b>middle of the strip's width</b> (the model's reference), three times, and "
            "enter the average. Readings near the strip's two ends show the barrelling along the wire.</li>"
            "</ul>"))
        self.m_table = QTableWidget()
        self.m_table.setColumnCount(5)
        self.m_table.setHorizontalHeaderLabels(["Drive", "Feed (mm/s)", "Predicted (mm)", "Measured (mm)",
                                                "Kerf (mm)"])
        self.m_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.m_table.setMinimumHeight(260)
        self.m_table.itemChanged.connect(self._measure_edited)
        v.addWidget(self.m_table)
        self._nav(v, 3)

    def _rebuild_measure_table(self) -> None:
        spec, drives, s = self.spec(), self.drives(), self._setup()
        pts = spec.measure_points()
        self.m_points.setText(
            "Measure each step at these distances from the strip's front end: "
            + ", ".join(f"<b>{p:.0f} mm</b> ({v:g} mm/s)" for p, v in zip(pts, spec.speeds_mm_s, strict=True))
            + ". That is 80 % along each step, where the wire temperature has settled.")
        old = {(round(m.drive, 4), round(m.speed_mm_s, 4)): m.thickness_mm for m in self.measurements}
        kw = "current_a" if s.mode == "current" else "voltage_v"
        self._filling = True
        self.m_table.setRowCount(len(drives) * len(spec.speeds_mm_s))
        r = 0
        for d in drives:
            pred = point_state(s, np.array(spec.speeds_mm_s), **{kw: d}).kerf_mm
            for j, vv in enumerate(spec.speeds_mm_s):
                cells = [f"{d:g} {self._unit()}", f"{vv:g}", f"{spec.strip_mm - float(pred[j]):.2f}"]
                meas = old.get((round(d, 4), round(vv, 4)))
                cells.append("" if meas is None else f"{meas:.2f}")
                cells.append("" if meas is None else f"{spec.strip_mm - meas:.2f}")
                for c, txt in enumerate(cells):
                    it = QTableWidgetItem(txt)
                    if c != 3:
                        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.m_table.setItem(r, c, it)
                r += 1
        self._filling = False

    def _measure_edited(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != 3:
            return
        spec, s = self.spec(), self._setup()
        ms: list[Measurement] = []
        self._filling = True
        for r in range(self.m_table.rowCount()):
            d = float(self.m_table.item(r, 0).text().split()[0])
            vv = float(self.m_table.item(r, 1).text())
            txt = self.m_table.item(r, 3).text().strip().replace(",", ".")
            try:
                t = float(txt)
            except ValueError:
                self.m_table.setItem(r, 4, QTableWidgetItem(""))
                continue
            ms.append(Measurement(vv, d, s.mode, t, spec.strip_mm))
            self.m_table.setItem(r, 4, QTableWidgetItem(f"{spec.strip_mm - t:.2f}"))
        self._filling = False
        self.measurements = ms
        self.measurements_changed.emit()

    def set_measurements(self, ms: list[Measurement]) -> None:
        self.measurements = list(ms)
        if ms:
            self.t_drives.setText(", ".join(f"{d:g}" for d in sorted({m.drive for m in ms})))
            self.t_speeds.setText(", ".join(f"{x:g}" for x in sorted({m.speed_mm_s for m in ms})))
            self.t_w.setValue(ms[0].strip_mm)
        self._refresh_test()

    # ── 5 ─────────────────────────────────────────────────────────────
    def _step_fit(self, v: QVBoxLayout) -> None:
        self._title(v, "Fit the model and apply it")
        v.addWidget(_body("The fit adjusts η and κ so the model's kerf matches your measurements at every feed "
                          "and drive (least squares on the logarithm, so thin and wide kerfs weigh alike)."))
        row = QHBoxLayout()
        b = QPushButton("Fit to my measurements")
        b.setProperty("role", "primary")
        b.clicked.connect(self._do_fit)
        self.apply_btn = QPushButton("Apply to the model")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply_fit)
        row.addWidget(b)
        row.addWidget(self.apply_btn)
        row.addStretch(1)
        v.addLayout(row)
        self.fit_out = QLabel("")
        self.fit_out.setWordWrap(True)
        self.fit_out.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.fit_out)
        self.fit_plot = pg.PlotWidget()
        self.fit_plot.setBackground(self._c.bg)
        style_plot(self.fit_plot, self._c)
        self.fit_plot.setLogMode(x=True, y=False)
        self.fit_plot.setLabel("bottom", "feed (mm/s)")
        self.fit_plot.setLabel("left", "kerf (mm)")
        self.fit_plot.setMinimumHeight(300)
        self.fit_plot.addLegend(offset=(-10, 10))
        v.addWidget(self.fit_plot, 1)
        self._nav(v, 4)

    def _do_fit(self) -> None:
        s = self._setup()
        ms = [m for m in self.measurements if m.mode == s.mode]
        if not ms:
            self.fit_out.setText(f"<span style='color:{self._c.warning}'>Enter measurements in step 4 first "
                                 f"(made in the current supply mode).</span>")
            return
        try:
            r = fit(s, ms)
        except ValueError as exc:
            self.fit_out.setText(f"<span style='color:{self._c.danger}'>{exc}</span>")
            return
        self._fit = r
        self.apply_btn.setEnabled(True)
        rel = r.rms_mm / max(1e-9, float(np.mean(r.measured)))
        quality = "excellent" if rel < 0.05 else ("good" if rel < 0.12 else "rough — check the measurements")
        self.fit_out.setText(
            f"η = <b>{r.eta:.3f}</b>, κ = <b>{r.kappa:.3f}</b> · RMS error {r.rms_mm:.3f} mm "
            f"({100 * rel:.0f} %, {quality}). {r.note}" + self._empirical_line(ms))
        self._plot_fit(s, ms, r)

    def _empirical_line(self, ms: list[Measurement]) -> str:
        try:
            e = fit_empirical(ms)
        except ValueError:
            return ""
        return (f"<br>Empirical law, no physics: <b>{e.equation()}</b> (R² {e.r2:.3f}, RMS {e.rms_mm:.3f} mm) — "
                "compare every model in the Curves tab.")

    def _plot_fit(self, s: CutSetup, ms: list[Measurement], r: FitResult) -> None:
        p = self.fit_plot
        p.clear()
        p.addLegend(offset=(-10, 10))
        palette = ["#F28C28", "#5AA9E6", "#2BB673", "#E5484D", "#B07CE8", "#D6B656"]
        fitted = replace(s, calib=replace(s.calib, eta=r.eta, kappa=r.kappa))
        vs = np.geomspace(min(m.speed_mm_s for m in ms) * 0.7, max(m.speed_mm_s for m in ms) * 1.4, 60)
        kw = "current_a" if s.mode == "current" else "voltage_v"
        for k, d in enumerate(sorted({m.drive for m in ms})):
            col = palette[k % len(palette)]
            pts = [m for m in ms if m.drive == d]
            p.plot([m.speed_mm_s for m in pts], [m.kerf_mm for m in pts], pen=None, symbol="o", symbolSize=9,
                   symbolBrush=col, name=f"{d:g} {self._unit()} measured")
            p.plot(vs, point_state(fitted, vs, **{kw: d}).kerf_mm, pen=pg.mkPen(col, width=2), name="fitted")
            p.plot(vs, point_state(s, vs, **{kw: d}).kerf_mm, pen=pg.mkPen(col, width=1, style=Qt.PenStyle.DotLine))

    def _apply_fit(self) -> None:
        if self._fit is not None:
            self.apply_calibration.emit(self._fit.eta, self._fit.kappa)
            self.fit_out.setText(self.fit_out.text() + "<br>✓ Applied. Save the profile to keep it.")

    # ── 6 ─────────────────────────────────────────────────────────────
    def _step_bow(self, v: QVBoxLayout) -> None:
        self._title(v, "Bow (lag) — optional")
        v.addWidget(_body(
            "Past the contact speed the wire pushes the foam and bows: its middle trails the ends. To measure "
            "it, cut straight into a block at a fast feed and <b>cut the wire power the moment the machine stops"
            "</b> (the wire freezes in its bowed shape). Split the block along the cut and measure how much "
            "shallower the slot is in the middle of the block than at its faces: that is the bow at that feed."))
        f = QFormLayout()
        self.bow_v = _spin(0.1, 200, 15, 1, " mm/s")
        self.bow_mm = _spin(0, 100, 0, 2, " mm")
        f.addRow("Feed of the test", self.bow_v)
        f.addRow("Measured bow (faces − middle)", self.bow_mm)
        b = QPushButton("Fit drag")
        b.clicked.connect(self._fit_bow)
        f.addRow(b)
        self.bow_out = QLabel("")
        self.bow_out.setWordWrap(True)
        f.addRow(self.bow_out)
        v.addLayout(f)
        self._nav(v, 5)

    def _fit_bow(self) -> None:
        s = self._setup()
        prof = span_profile(s, speeds=[self.bow_v.value()], nodes=121)
        in_f = prof.in_foam
        model = float(prof.bow_mm[0, in_f].max() - prof.bow_mm[0, in_f][[0, -1]].mean()) if in_f.any() else 0.0
        if model <= 1e-6:
            self.bow_out.setText(f"At {self.bow_v.value():g} mm/s the model predicts no contact, so no bow. "
                                 "Repeat the test at a faster feed (see the operating map's orange line).")
            return
        c = s.calib.c_drag_n_m_per_mm_s * self.bow_mm.value() / model
        self.apply_drag.emit(c)
        self.bow_out.setText(f"Model bow was {model:.2f} mm; drag set to <b>{c:.3f}</b> N/m per mm/s.")

    def refresh(self) -> None:
        """Re-evaluate things that depend on the model parameters."""
        self._wire_check()
        self._refresh_test()
