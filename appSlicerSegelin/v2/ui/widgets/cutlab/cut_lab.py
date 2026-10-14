"""Cut Lab: interactive physics of the hot wire in the foam.

Three tabs share one parameter panel and one row of live read-outs:

* **Explore** — the wire's cross-section in the foam (melt radius, gap,
  kerf), the operating map (drive × feed) and the wire along its span;
* **Cut simulation** — a slicer-like replay of a G-code cut, slice by slice
  along the wire, with the part that actually comes out and its deviation;
* **Calibration** — the step-by-step guide that fits the model to test cuts.

The fast read-outs are computed on every edit; the operating map, the span
profile and the simulation run on a background thread.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PyQt6.QtCore import QStandardPaths, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ....core import cut_profile
from ....core.cut_sim import simulate
from ....core.cutting_physics import (
    CutSetup,
    contact_speed,
    operating_map,
    point_state,
    span_profile,
    wire_time_constant_s,
)
from ....core.gcode_reader import Toolpath, parse_gcode
from ....core.hotwire_rig import PRESETS, FoamBlock, fit_block
from ....core.thermal2d import solve_section
from .calibration_tab import CalibrationTab
from .common import REGIME, Job, KpiTile, colors, kpi_qss
from .curves_tab import CurvesTab
from .explore import REGIME_TEXT, ExploreTab, regime_of
from .params import ParamsPanel
from .simulate_tab import SimTab

HELP = """<h3>How the Cut Lab models the cut</h3>
<p><b>Wire.</b> The current heats the wire (I²R, with R rising with temperature). It loses heat to the air by
natural convection and radiation, and inside the foam to the melt front. Along its span it behaves like a fin:
the clamps keep its ends cool, and the part in the foam is cooler than the part in air.</p>
<p><b>Melt front — radius of incidence.</b> The foam retreats where it reaches its collapse temperature. Heat
crosses the gap between wire and foam through the hot gas and by radiation, and must melt a swath as wide as the
kerf at the feed speed. The balance gives the melt radius <i>r<sub>m</sub></i>: large when slow or hot (wide
kerf, wide gap), down to the wire itself when fast or cold — then the wire <b>touches</b> the foam, drags and
bows.</p>
<p><b>Bow.</b> Past the contact speed the wire pushes the foam; under the spring tension it deflects like a
string. In the simulation this lag rounds corners where the wire bows most.</p>
<p><b>Motion.</b> The cut follows the firmware's trapezoidal motion (per-axis feed and acceleration limits,
junction speed at corners): where the wire slows, it melts more.</p>
<p><b>2-D solve (high fidelity).</b> On demand, the Explore tab solves the transient heat conduction in the
cut's cross-section, in a window that travels with the wire: the wire heats by I²R, the gas in the slot and the
foam conduct, and the foam turns to gas once it reaches its collapse temperature and has taken its latent heat.
The kerf comes out of the front it finds. It also counts the heat left in the walls of the cut, which the closed
form leaves out, so at low drive it predicts contact at lower feeds. A run takes from about 1 s (fast feed) to about a
minute (slow feed) on the Normal grid.</p>
<p><b>Curves.</b> Kerf, radius of incidence, wire temperature and gap against feed, for several drives, from
every source at once: the model as calibrated, the model with handbook values, an empirical power law
<i>kerf = a·v<sup>b</sup>·I<sup>c</sup></i> fitted straight to your measurements, the 2-D solve and the
measurements themselves — with predicted-vs-measured errors, and CSV export.</p>
<p><b>Calibration.</b> The material data are typical values. Two factors (η, κ) are fitted to your own test
cuts, so the predicted kerf becomes your machine's.</p>
<p><b>Equations and references.</b> The full derivation, the validation against published data and a test
plan are in <i>docs/fisica-del-corte.md</i> in the repository.</p>"""


def demo_gcode() -> str:
    """A NACA 0012 rib, 100 mm chord, with a lead-in: something to look at before loading a G-code."""
    c = 100.0
    xs = (1 - np.cos(np.linspace(0, np.pi, 70))) / 2
    yt = 5 * 0.12 * (0.2969 * np.sqrt(xs) - 0.126 * xs - 0.3516 * xs**2 + 0.2843 * xs**3 - 0.1036 * xs**4)
    up = [(10 + c * x, 15 + c * t) for x, t in zip(xs, yt, strict=True)]
    lo = [(10 + c * x, 15 - c * t) for x, t in zip(xs[::-1], yt[::-1], strict=True)]
    pts = [(10.0, 15.0), *up[1:], *lo[1:], (0.0, 15.0), (0.0, 0.0)]
    lines = ["; Demo: NACA 0012 rib, chord 100 mm", "G21", "G90", "G92 Y0 Z0", "G1 F180 Y0 Z15"]
    lines += [f"G1 Y{y:.3f} Z{z:.3f}" for y, z in pts]
    return "\n".join(lines) + "\n"


def _profile_path() -> Path:
    from ....portable import data_dir

    base = data_dir() or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(base or Path.home()) / "cut_lab_profile.json"


class CutLab(QWidget):
    def __init__(self, parent: QWidget | None = None, theme: str = "dark", *, load_saved: bool = True) -> None:
        super().__init__(parent)
        self.theme = theme
        self._c = colors(theme)
        self.setObjectName("CutLab")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(kpi_qss(self._c))
        self.toolpath: Toolpath = parse_gcode("")
        self.block = FoamBlock()
        self.source_name = ""
        self._token = 0
        self._heavy: Job | None = None
        self._sim_job: Job | None = None
        self._hifi_job: Job | None = None
        self._profile = None
        self.project_provider = None  # callable returning (gcode_text, name) or None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.addLayout(self._header())

        split = QSplitter(Qt.Orientation.Horizontal)
        self.params = ParamsPanel()
        split.addWidget(self.params)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(8)
        rv.addLayout(self._kpis())
        self.advice = QLabel("")
        self.advice.setObjectName("Advice")
        self.advice.setWordWrap(True)
        self.advice.setTextFormat(Qt.TextFormat.RichText)
        rv.addWidget(self.advice)
        self.tabs = QTabWidget()
        self.explore = ExploreTab(theme)
        self.sim = SimTab(theme)
        self.calib = CalibrationTab(theme, self.params.setup)
        self.curves = CurvesTab(theme, self.params.setup, lambda: self.calib.measurements)
        self.tabs.addTab(self.explore, "Explore")
        self.tabs.addTab(self.curves, "Curves")
        self.tabs.addTab(self.sim, "Cut simulation")
        self.tabs.addTab(self.calib, "Calibration")
        rv.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([330, 1200])
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        self.params.changed.connect(self._recompute)
        self.explore.picked.connect(self._picked)
        self.explore.hifi_requested.connect(self.run_hifi)
        self.explore.hifi_cancel.connect(self._cancel_hifi)
        self.sim.run_requested.connect(self.run_simulation)
        self.sim.cancel_requested.connect(self._cancel_sim)
        self.sim.block_changed.connect(self._block_from_form)
        self.calib.apply_calibration.connect(self._apply_calib)
        self.calib.apply_resistivity.connect(self.params.set_resistivity)
        self.calib.apply_drag.connect(self.params.set_drag)
        self.calib.preview_gcode.connect(self._preview_test)
        self.tabs.currentChanged.connect(self._tab_shown)
        self.calib.measurements_changed.connect(self._refresh_curves)

        self.params.set_span(PRESETS["Ender-3 (long arms)"].wire_span)
        if load_saved:
            self._load_saved()
        self.load_text(demo_gcode(), "Demo — NACA 0012 rib")
        self._recompute()

    # ── header & KPIs ─────────────────────────────────────────────────
    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QLabel("Cut Lab")
        title.setObjectName("StepTitle")
        self.source = QLabel("")
        self.source.setObjectName("CardSub")
        row.addWidget(title)
        row.addSpacing(10)
        row.addWidget(self.source, 1)
        self.project_btn = QPushButton("Use current project")
        self.project_btn.clicked.connect(self._use_project)
        self.project_btn.setVisible(False)
        for text, slot in (("Open G-code…", self._open_gcode), ("Load profile…", self._load_profile),
                           ("Save profile…", self._save_profile), ("How it works", self._help)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            if text == "Open G-code…":
                row.addWidget(self.project_btn)
            row.addWidget(b)
        return row

    def _kpis(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.k_air = KpiTile("Wire in air", "°C", "Steady temperature of the wire in free air.")
        self.k_foam = KpiTile("Wire in foam", "°C", "Temperature of the wire while it cuts at the probe feed.")
        self.k_rm = KpiTile("Radius of incidence", "mm",
                            "Melt radius r_m: how far ahead of the wire's axis the foam retreats.")
        self.k_kerf = KpiTile("Kerf", "mm", "Width of the slot the wire leaves (2·κ·r_m).")
        self.k_reg = KpiTile("Regime", "", "Non-contact: a gap of hot gas between wire and foam.\n"
                                           "Contact: the gap closed — the wire pushes, drags and bows.\n"
                                           "Stall: the wire is too cold to melt the foam.")
        self.k_vc = KpiTile("Max non-contact feed", "mm/s", "Fastest feed that still cuts without touching.")
        self.k_bow = KpiTile("Bow at centre", "mm", "Lag of the wire's middle behind its ends at the probe feed.")
        self.k_tau = KpiTile("Wire response", "s", "Thermal time constant of the wire (how fast it heats/cools).")
        for k in (self.k_air, self.k_foam, self.k_rm, self.k_kerf, self.k_reg, self.k_vc, self.k_bow, self.k_tau):
            row.addWidget(k, 1)
        return row

    # ── live model ────────────────────────────────────────────────────
    def setup(self) -> CutSetup:
        return self.params.setup()

    def _recompute(self) -> None:
        s = self.setup()
        v = self.params.probe_speed()
        st = point_state(s, v)
        reg = regime_of(st, s)
        unit_drive = f"{float(st.current_a):.2f} A" if s.mode == "voltage" else f"{s.current_a:.2f} A"
        self.k_air.set(f"{float(st.t_air_c):.0f}", f"{unit_drive} · {float(st.power_w):.1f} W")
        self.k_foam.set(f"{float(st.t_foam_c):.0f}", f"{float(st.t_foam_c - st.t_air_c):+.0f} °C vs air")
        self.k_rm.set(f"{float(st.r_m_mm):.3f}",
                      f"gap {float(st.gap_mm) * 1000:.0f} µm" if float(st.gap_mm) < 0.1 else f"gap {float(st.gap_mm):.2f} mm")
        self.k_kerf.set(f"{float(st.kerf_mm):.2f}", f"part −{float(st.kerf_mm) / 2:.2f} mm per side")
        self.k_reg.set(REGIME_TEXT[reg].split(" —")[0], REGIME_TEXT[reg].split("— ")[-1] if "—" in REGIME_TEXT[reg]
                       else "gap of hot gas", REGIME[reg])
        tau = wire_time_constant_s(s, float(st.t_air_c))
        self.k_tau.set(f"{tau:.1f}", f"~{3 * tau:.0f} s to settle")
        self.explore.incidence.show_state(st, s, v)
        self.explore.mark_stale()
        self._refresh_curves()
        drive = s.current_a if s.mode == "current" else s.voltage_v
        self.explore.map.set_point(drive, v)
        self._advise(st, s, v, None)
        self._launch_heavy(s, v)

    def _tab_shown(self, i: int) -> None:
        w = self.tabs.widget(i)
        if w is self.calib:
            self.calib.refresh()
        elif w is self.curves:
            self.curves.refresh()

    def _refresh_curves(self) -> None:
        if self.tabs.currentWidget() is self.curves:
            self.curves.refresh()

    def _launch_heavy(self, s: CutSetup, v: float) -> None:
        self._token += 1
        token = self._token
        s_profile = s.with_(block_width_mm=self.params.bw.value(), block_offset_mm=self.params.boff.value())

        def work() -> dict:
            return {"token": token, "vc": contact_speed(s), "map": operating_map(s),
                    "profile": span_profile(s_profile), "v": v, "setup": s}

        job = Job(work, parent=self)
        job.done.connect(self._heavy_done)
        job.failed.connect(lambda msg: self.advice.setText(f"<span style='color:{self._c.danger}'>{msg}</span>"))
        self._heavy = job
        self.k_vc.set("…", "computing")
        job.start()

    def _heavy_done(self, out: dict) -> None:
        if out["token"] != self._token:
            return  # a newer edit is on its way
        self._last_profile = out["profile"]
        self.explore.map.set_map(out["map"])
        s, v = out["setup"], out["v"]
        self.explore.map.set_point(s.current_a if s.mode == "current" else s.voltage_v, v)
        self.explore.along.show_profile(out["profile"], v)
        vc = out["vc"]
        self.k_vc.set(f"{vc:.1f}" if vc > 0 else "—", "go slower to avoid contact" if v > vc else
                      f"you're at {100 * v / max(vc, 1e-9):.0f} %")
        at = out["profile"].at(v, self.params.boff.value())
        self.k_bow.set(f"{at['bow_mm']:.2f}", "no drag" if at["bow_mm"] < 1e-3 else "wire drags behind")
        self._advise(point_state(s, v), s, v, vc)

    def _advise(self, st, s: CutSetup, v: float, vc: float | None) -> None:  # type: ignore[no-untyped-def]
        reg = regime_of(st, s)
        c = self._c
        k = float(st.kerf_mm)
        if reg == "stall":
            msg = (f"<span style='color:{REGIME['stall']}'>■</span> The wire can't keep the foam above its collapse "
                   f"temperature at {v:.1f} mm/s: it will tear the foam or stall. Raise the drive or slow down.")
        elif reg == "contact":
            msg = (f"<span style='color:{REGIME['contact']}'>■</span> The wire touches the foam: it drags, bows "
                   f"and rounds corners. Slow down" + (f" below {vc:.1f} mm/s" if vc else "") +
                   " or raise the drive.")
        elif reg == "overmelt":
            msg = (f"<span style='color:{REGIME['overmelt']}'>■</span> Clean cut, but the kerf ({k:.2f} mm) is wide: "
                   f"slow feed or hot wire. Go faster" + (f" (up to ~{0.8 * vc:.1f} mm/s)" if vc else "") +
                   " or lower the drive for a finer edge.")
        else:
            margin = f" — {100 * v / vc:.0f} % of the contact speed" if vc else ""
            msg = (f"<span style='color:{REGIME['noncontact']}'>■</span> Clean non-contact cut: kerf {k:.2f} mm, "
                   f"the part comes out {k / 2:.2f} mm smaller per side{margin}.")
        if float(st.t_air_c) > s.wire.max_temp_c:
            msg += f" <span style='color:{c.danger}'>The wire is above its {s.wire.max_temp_c:.0f} °C limit.</span>"
        self.advice.setText(msg)

    def _picked(self, drive: float, v: float) -> None:
        self.params.set_drive(drive)
        self.params.set_probe_speed(v)

    def _apply_calib(self, eta: float, kappa: float) -> None:
        self.params.set_calibration(eta, kappa)

    # ── sources ───────────────────────────────────────────────────────
    def load_text(self, text: str, name: str) -> None:
        self.toolpath = parse_gcode(text)
        self.source_name = name
        if self.toolpath.moves:
            w = self.params.bw.value()
            self.block = fit_block(self.toolpath, width_x=w)
            self.block = FoamBlock(length_y=self.block.length_y, height_z=self.block.height_z, width_x=w,
                                   y0=self.block.y0, z0=self.block.z0, x_offset=self.params.boff.value())
        self.sim.set_block(self.block)
        tp = self.toolpath
        info = f"{len(tp.moves)} moves · {tp.cut_length:.0f} mm of path" if tp.moves else "no moves"
        self.source.setText(f"{name} — {info}")

    def load_file(self, path: str) -> None:
        with open(path, encoding="utf-8", errors="replace") as fh:
            self.load_text(fh.read(), Path(path).name)

    def _open_gcode(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open G-code", filter="G-code (*.gcode *.nc *.txt);;All files (*)")
        if path:
            self.load_file(path)
            self.tabs.setCurrentWidget(self.sim)

    def set_project_provider(self, provider) -> None:  # type: ignore[no-untyped-def]
        self.project_provider = provider
        self.project_btn.setVisible(provider is not None)

    def _use_project(self) -> None:
        if self.project_provider is None:
            return
        got = self.project_provider()
        if got:
            self.load_text(*got)
            self.tabs.setCurrentWidget(self.sim)

    def _preview_test(self, text: str, name: str) -> None:
        self.load_text(text, name)
        self.tabs.setCurrentWidget(self.sim)
        self.run_simulation()

    def _block_from_form(self, vals: tuple[float, float, float, float]) -> None:
        y0, z0, ln, h = vals
        self.block = FoamBlock(length_y=ln, height_z=h, width_x=self.params.bw.value(), y0=y0, z0=z0,
                               x_offset=self.params.boff.value())

    # ── simulation ────────────────────────────────────────────────────
    def run_simulation(self) -> None:
        if not self.toolpath.moves:
            self.sim.on_progress(0, "Open a G-code first")
            return
        if self._sim_job is not None:
            return
        b = self.block
        self.block = FoamBlock(length_y=b.length_y, height_z=b.height_z, width_x=self.params.bw.value(), y0=b.y0,
                               z0=b.z0, x_offset=self.params.boff.value())
        job = Job(simulate, self.toolpath, self.block, self.setup(), limits=self.params.limits(),
                  n_slices=self.sim.slices.value(), cell_mm=self.sim.cell_mm(), parent=self)
        job._kw["progress"] = job.report
        job.progress.connect(self.sim.on_progress)
        job.done.connect(self._sim_done)
        job.failed.connect(self._sim_failed)
        self._sim_job = job
        self.sim.busy(True)
        job.start()

    def _sim_done(self, res) -> None:  # type: ignore[no-untyped-def]
        self._sim_job = None
        self.sim.busy(False)
        self.sim.show_result(res)

    def _sim_failed(self, msg: str) -> None:
        self._sim_job = None
        self.sim.busy(False)
        self.sim.on_progress(0, "Cancelled" if msg == "cancelled" else "Failed — see details")
        if msg != "cancelled":
            QMessageBox.warning(self, "Simulation failed", msg)

    def _cancel_sim(self) -> None:
        if self._sim_job is not None:
            self._sim_job.cancelled = True

    # ── high-fidelity 2-D solve ──────────────────────────────────────
    def run_hifi(self, quality: str = "normal") -> None:
        if self._hifi_job is not None:
            return
        s, v = self.setup(), self.params.probe_speed()
        job = Job(solve_section, s, v, quality=quality, parent=self)
        job._kw["progress"] = job.report
        job.progress.connect(self.explore.hifi_progress)
        job.done.connect(lambda res: self._hifi_done(res, s))
        job.failed.connect(self._hifi_failed)
        self._hifi_job = job
        self.explore.hifi_busy(True)
        job.start()

    def _hifi_done(self, res, s: CutSetup) -> None:  # type: ignore[no-untyped-def]
        self._hifi_job = None
        self.explore.hifi_busy(False)
        self.explore.show_section(res, s)
        if s != self.setup() or abs(res.v_mm_s - self.params.probe_speed()) > 1e-9:
            self.explore.mark_stale()

    def _hifi_failed(self, msg: str) -> None:
        self._hifi_job = None
        self.explore.hifi_busy(False)
        self.explore.hifi_progress(0, "2-D solve: cancelled" if msg == "cancelled" else "2-D solve failed")
        if msg != "cancelled":
            QMessageBox.warning(self, "2-D solve failed", msg)

    def _cancel_hifi(self) -> None:
        if self._hifi_job is not None:
            self._hifi_job.cancelled = True

    # ── profiles ──────────────────────────────────────────────────────
    def current_profile(self) -> cut_profile.CutProfile:
        return self.params.profile(self.calib.measurements)

    def apply_profile(self, p: cut_profile.CutProfile) -> None:
        self.params.set_profile(p)
        self.calib.set_measurements(p.measurements)

    def _load_saved(self) -> None:
        path = _profile_path()
        if path.exists():
            try:
                self.apply_profile(cut_profile.load(path))
            except Exception:  # a broken profile must not keep the lab from opening
                pass

    def save_default(self) -> None:
        path = _profile_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            cut_profile.save(self.current_profile(), path)
        except OSError:
            pass

    def _load_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load Cut Lab profile", filter="Cut Lab profile (*.json)")
        if path:
            try:
                self.apply_profile(cut_profile.load(path))
            except Exception as exc:
                QMessageBox.warning(self, "Could not load the profile", str(exc))

    def _save_profile(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Cut Lab profile", "cut_lab_profile.json",
                                              filter="Cut Lab profile (*.json)")
        if path:
            cut_profile.save(self.current_profile(), path)
            self.save_default()

    def _help(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("How the Cut Lab works")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(HELP)
        c = self._c  # explicit colours: the inherited theme left black text on black
        box.setStyleSheet(f"QMessageBox {{ background: {c.surface}; }} QLabel {{ color: {c.text}; }}")
        box.exec()


class CutLabDialog(QDialog):
    """Non-modal window hosting the Cut Lab."""

    def __init__(self, parent: QWidget | None = None, theme: str = "dark") -> None:
        super().__init__(parent)
        self.setWindowTitle("Cut Lab — hot wire in foam")
        self.resize(1560, 940)
        self.lab = CutLab(self, theme)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.lab)

    def closeEvent(self, ev) -> None:  # type: ignore[no-untyped-def]
        self.lab.save_default()
        super().closeEvent(ev)

