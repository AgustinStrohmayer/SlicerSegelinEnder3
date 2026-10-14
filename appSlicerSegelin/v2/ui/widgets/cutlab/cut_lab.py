"""Cut Lab: interactive physics of the hot wire in the foam.

It opens in **guided mode** (:mod:`.guided`): five short screens that ask one
thing each — supply and wire, a test feed, the result, an optional
calibration, the recommended settings. **Advanced mode**, one click away in
the header, is the full lab described below; both modes edit the same
parameter panel.

Four tabs share one parameter panel and one row of live read-outs:

* **Explore** — the wire's cross-section in the foam (melt radius, gap,
  kerf), the operating map (drive × feed) and the wire along its span;
* **Curves** — kerf and friends against feed, from every model and the
  measurements;
* **Cut simulation** — a slicer-like replay of a G-code cut, slice by slice
  along the wire, with the part that actually comes out and its deviation;
* **Calibration** — the step-by-step guide that fits the model to test cuts.

Responsiveness: every edit recomputes the cheap read-outs at once (one
point of the model, a few milliseconds even in CV mode). The heavy part — the
contact speed and feed scan, the operating map, the profile along the wire —
waits until the edits pause (``HEAVY_DEBOUNCE_MS``) and runs on one background
worker, latest-wins: a newer edit makes a running job stop at its next stage
and start over with the new parameters, so jobs never pile up.

Persistence: the lab saves its profile (supply, wire, foam, calibration,
measurements and the work settings chosen in guided mode) a moment after each
change, and loads it on start-up — ``core.cut_profile.default_profile_path``,
``datos/`` in portable mode. ``core.cut_profile.load_saved_cut_settings``
reads the work feed and kerf compensation back for the main window.

On the project's G-code (``linked``) the foam block is the project's: its
width and offset (parameter panel) and its position and size (Cut simulation
tab) go back through ``block_edited``; the wire span comes from the project's
machine (:meth:`CutLab.set_rig`).
"""
from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ....core import cut_profile
from ....core.cut_profile import WorkSettings, default_profile_path
from ....core.cut_sim import simulate
from ....core.cutting_physics import (
    CutSetup,
    cold_resistance_ohm,
    contact_speed,
    operating_map,
    point_state,
    span_profile,
    wire_time_constant_s,
)
from ....core.gcode_reader import Toolpath, parse_gcode
from ....core.hotwire_rig import DEFAULT_PRESET, PRESETS, FoamBlock, HotWireRig, fit_block
from ....core.thermal2d import solve_section
from .calibration_tab import CalibrationTab
from .common import REGIME, Job, KpiTile, colors, kpi_qss
from .curves_tab import CurvesTab
from .explore import REGIME_TEXT, ExploreTab, regime_of
from .guided import GuidedPanel
from .params import ParamsPanel
from .simulate_tab import SimTab
from .typical import feed_scan, recommend, typical

HEAVY_DEBOUNCE_MS = 150   # the heavy plots wait for the edits to pause this long
AUTOSAVE_MS = 1200        # the profile is saved this long after the last change
PROFILE_SPEEDS = np.geomspace(0.05, 200.0, 30)  # along-the-wire profile for the UI (the cut simulation uses more)
PROFILE_NODES = 161

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


GLOSSARY = """<table cellspacing="0" cellpadding="3">
<tr><td><b>Wire in air</b></td><td>How hot the wire gets on its own, in free air, at this current.</td></tr>
<tr><td><b>Wire in foam</b></td><td>How hot it stays while cutting at the probe feed. Lower than in air: the foam
takes heat from it as it melts.</td></tr>
<tr><td><b>Radius of incidence</b></td><td>How far ahead of the wire's centre the foam has already melted. Bigger
than the wire's radius means a gap of hot gas: the wire never touches the foam.</td></tr>
<tr><td><b>Kerf</b></td><td>The width of the slot the wire leaves. The part comes out half of it smaller on each
side.</td></tr>
<tr><td><b>Regime</b></td><td>What kind of cut it is: <i>non-contact</i> (clean), <i>over-melting</i> (clean but
wide), <i>contact</i> (the wire touches, drags and bends) or <i>stall</i> (too cold to cut).</td></tr>
<tr><td><b>Max non-contact feed</b></td><td>The fastest speed that still cuts without touching. Stay below
it.</td></tr>
<tr><td><b>Bow at centre</b></td><td>How far the middle of the wire bends back behind its ends. 0 when it cuts
without touching.</td></tr>
<tr><td><b>Wire response</b></td><td>How quickly the wire heats up or cools down when something changes; wait about
three times this before cutting.</td></tr>
</table>"""

TAB_INTRO = {
    "explore": "<b>Explore</b> — change any setting on the left and watch the wire react. Left: the wire seen from "
               "its end as it melts through the foam. Top right: every current × speed at once (click to try one). "
               "Bottom right: the wire from clamp to clamp.",
    "curves": "<b>Curves</b> — how the slot width (and more) changes with speed, for several currents, from each "
              "model and from your own measurements.",
    "sim": "<b>Cut simulation</b> — replays a G-code through the foam and shows the part that comes out. Press "
           "<i>Run cut simulation</i>, then pick a layer on the right to see that cross-section.",
    "calib": "<b>Calibration</b> — six short steps to fit the model to test cuts from your own machine.",
}


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


class CutLab(QWidget):
    block_edited = pyqtSignal(object)  # FoamBlock, after a user edit of the project's block
    work_speed_chosen = pyqtSignal(float, float)  # saved work settings: feed (mm/s), kerf (mm, full width)
    work_saved = pyqtSignal(object)  # WorkSettings, after "Save and use for the project"
    close_requested = pyqtSignal()   # the guided mode is done: the host window may close

    def __init__(self, parent: QWidget | None = None, theme: str = "dark", *, load_saved: bool = True,
                 profile_path: str | Path | None = None) -> None:
        """``load_saved``: load the default profile on start and keep it saved (off in tests).
        ``profile_path``: where (default: :func:`core.cut_profile.default_profile_path`)."""
        super().__init__(parent)
        self.theme = theme
        self._c = colors(theme)
        self.setObjectName("CutLab")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(kpi_qss(self._c))
        self.toolpath: Toolpath = parse_gcode("")
        self.block = FoamBlock()
        self.source_name = ""
        self.linked = False  # showing the project's G-code: block edits belong to the project
        self._token = 0
        self._heavy: Job | None = None
        self._sim_job: Job | None = None
        self._hifi_job: Job | None = None
        self._profile = None
        self.project_provider = None  # callable returning (gcode_text, name, block) or None
        self.persist = load_saved
        self.profile_path = Path(profile_path) if profile_path is not None else default_profile_path()
        self.work: WorkSettings | None = None
        self._heavy_pending = False
        self._last_vc: float | None = None
        self.timings: dict[str, float] = {}  # ms of the last fast update / heavy stages (for profiling)
        self._heavy_timer = QTimer(self)
        self._heavy_timer.setSingleShot(True)
        self._heavy_timer.setInterval(HEAVY_DEBOUNCE_MS)
        self._heavy_timer.timeout.connect(self._launch_heavy)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(AUTOSAVE_MS)
        self._save_timer.timeout.connect(self.save_default)

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
        arow = QHBoxLayout()
        self.advice = QLabel("")
        self.advice.setObjectName("Advice")
        self.advice.setWordWrap(True)
        self.advice.setTextFormat(Qt.TextFormat.RichText)
        arow.addWidget(self.advice, 1)
        self.glossary_btn = QPushButton("ⓘ  What do these numbers mean?")
        self.glossary_btn.setProperty("role", "ghost")
        self.glossary_btn.setCheckable(True)
        arow.addWidget(self.glossary_btn, 0, Qt.AlignmentFlag.AlignTop)
        rv.addLayout(arow)
        self.glossary = QLabel(GLOSSARY)
        self.glossary.setObjectName("Glossary")
        self.glossary.setWordWrap(True)
        self.glossary.setTextFormat(Qt.TextFormat.RichText)
        self.glossary.setVisible(False)
        self.glossary_btn.setMinimumWidth(self.glossary_btn.sizeHint().width() + 24)
        self.glossary_btn.toggled.connect(self.glossary.setVisible)
        self.glossary_btn.toggled.connect(lambda on: self.glossary_btn.setText(
            "Hide the explanations" if on else "ⓘ  What do these numbers mean?"))
        rv.addWidget(self.glossary)
        self.tab_intro = QLabel("")
        self.tab_intro.setObjectName("TabIntro")
        self.tab_intro.setWordWrap(True)
        self.tab_intro.setTextFormat(Qt.TextFormat.RichText)
        self.tabs = QTabWidget()
        self.explore = ExploreTab(theme)
        self.sim = SimTab(theme)
        self.calib = CalibrationTab(theme, self.params.setup)
        self.curves = CurvesTab(theme, self.params.setup, lambda: self.calib.measurements)
        self.tabs.addTab(self.explore, "Explore")
        self.tabs.addTab(self.curves, "Curves")
        self.tabs.addTab(self.sim, "Cut simulation")
        self.tabs.addTab(self.calib, "Calibration")
        rv.addWidget(self.tab_intro)
        rv.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([330, 1200])
        split.setStretchFactor(1, 1)

        self.guided = GuidedPanel(theme, self.params)
        self.guided.save_path_text = str(self.profile_path)
        self.pages = QStackedWidget()  # guided | advanced; both drive self.params
        self.pages.addWidget(self.guided)
        self.pages.addWidget(split)
        root.addWidget(self.pages, 1)

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
        self.calib.measurements_changed.connect(
            lambda: self.guided.set_measurement_count(len(self.calib.measurements)))
        self.calib.measurements_changed.connect(self._schedule_save)
        self.guided.advanced_requested.connect(self.show_advanced)
        self.guided.simulate_requested.connect(self._guided_simulate)
        self.guided.save_requested.connect(self.save_work)
        self.mode_group.idClicked.connect(lambda i: self.show_advanced() if i else self.show_guided())

        self.params.set_span(PRESETS[DEFAULT_PRESET].wire_span)
        if load_saved:
            self._load_saved()
        self.load_text(demo_gcode(), "Demo — NACA 0012 rib")
        self._tab_shown(0)
        self.show_guided()
        self._recompute()
        self._save_timer.stop()  # nothing changed yet

    # ── header & KPIs ─────────────────────────────────────────────────
    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        title = QLabel("Cut Lab")
        title.setObjectName("StepTitle")
        self.source = QLabel("")
        self.source.setObjectName("CardSub")
        row.addWidget(title)
        row.addSpacing(10)
        self.mode_group = QButtonGroup(self)
        self.mode_btns: list[QPushButton] = []
        for i, (text, tip) in enumerate((
                ("Guided", "Step by step: one question per screen, with the result next to it."),
                ("Advanced", "The full lab: every parameter, the operating map, curves, the cut simulation "
                             "and the calibration."))):
            b = QPushButton(text)
            b.setObjectName("ModeBtn")
            b.setCheckable(True)
            b.setToolTip(tip)
            self.mode_group.addButton(b, i)
            self.mode_btns.append(b)
            row.addWidget(b)
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

    def _kpis(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.k_cur = KpiTile("Current", "A", "Current through the wire (CV: what the wire draws at the set voltage; "
                                             "the supply holds its current limit if the wire would draw more).")
        self.k_pow = KpiTile("Power", "W", "Electrical power heating the wire (I²·R, R at the wire's temperature).")
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
        for k, tile in enumerate((self.k_cur, self.k_pow, self.k_air, self.k_foam, self.k_tau,
                                  self.k_rm, self.k_kerf, self.k_reg, self.k_vc, self.k_bow)):
            grid.addWidget(tile, k // 5, k % 5)
        for c in range(5):
            grid.setColumnStretch(c, 1)
        return grid

    # ── guided / advanced ─────────────────────────────────────────────
    @property
    def guided_mode(self) -> bool:
        return self.pages.currentWidget() is self.guided

    def show_guided(self) -> None:
        self.mode_btns[0].setChecked(True)
        self.pages.setCurrentWidget(self.guided)

    def show_advanced(self, tab: str = "") -> None:
        """Advanced mode, optionally on a tab: "explore", "curves", "sim" or "calib"."""
        self.mode_btns[1].setChecked(True)
        self.pages.setCurrentIndex(1)
        w = {"explore": self.explore, "curves": self.curves, "sim": self.sim, "calib": self.calib}.get(tab)
        if w is not None:
            self.tabs.setCurrentWidget(w)

    def _guided_simulate(self) -> None:
        self.show_advanced("sim")
        self.run_simulation()

    # ── live model ────────────────────────────────────────────────────
    def setup(self) -> CutSetup:
        return self.params.setup()

    def _recompute(self) -> None:
        """Every edit: the cheap read-outs now, the heavy part once the edits pause."""
        t0 = time.perf_counter()
        self._token += 1
        width, offset = self.params.bw.value(), self.params.boff.value()
        if (width, offset) != (self.block.width_x, self.block.x_offset):
            self.block = replace(self.block, width_x=width, x_offset=offset)
            if self.linked:
                self.block_edited.emit(self.block)
        s = self.setup()
        v = self.params.probe_speed()
        st = point_state(s, v)
        reg = regime_of(st, s)
        typ = typical(s)
        i, u, p = float(st.current_a), float(st.voltage_v), float(st.power_w)
        lim = bool(st.limited)
        warn = self._c.warning
        if s.mode == "voltage":
            self.k_cur.set(f"{i:.2f}", f"at {s.voltage_v:.1f} V" + (" · on the current limit" if lim else ""),
                           warn if lim else None)
        else:
            self.k_cur.set(f"{i:.2f}", f"needs {u:.1f} V" + (" · supply at its max" if lim else ""),
                           warn if lim else None)
        self.k_cur.set_typical(typ.current, typ.tip["current"])
        self.k_pow.set(f"{p:.1f}", f"{p / max(s.span_mm * 1e-3, 1e-9):.0f} W/m of wire")
        self.k_pow.set_typical(typ.power, typ.tip["power"])
        self.k_air.set(f"{float(st.t_air_c):.0f}", "in free air",
                       self._c.danger if float(st.t_air_c) > s.wire.max_temp_c else None)
        self.k_air.set_typical(typ.t_air, typ.tip["t_air"])
        self.k_foam.set(f"{float(st.t_foam_c):.0f}", f"{float(st.t_foam_c - st.t_air_c):+.0f} °C vs air")
        self.k_foam.set_typical(typ.t_foam, typ.tip["t_foam"])
        self.k_rm.set(f"{float(st.r_m_mm):.3f}",
                      f"gap {float(st.gap_mm) * 1000:.0f} µm" if float(st.gap_mm) < 0.1 else f"gap {float(st.gap_mm):.2f} mm")
        self.k_rm.set_typical(typ.r_m, typ.tip["r_m"])
        self.k_kerf.set(f"{float(st.kerf_mm):.2f}", f"part −{float(st.kerf_mm) / 2:.2f} mm per side")
        self.k_kerf.set_typical(typ.kerf, typ.tip["kerf"])
        self.k_reg.set(REGIME_TEXT[reg].split(" —")[0], REGIME_TEXT[reg].split("— ")[-1] if "—" in REGIME_TEXT[reg]
                       else "gap of hot gas", REGIME[reg])
        tau = wire_time_constant_s(s, float(st.t_air_c))
        self.k_tau.set(f"{tau:.1f}", f"~{3 * tau:.0f} s to settle")
        if self.k_vc.value_text() == "—" and self._last_vc is None:
            self.k_vc.set("…", "computing")
        else:
            self.k_vc.set_hint("updating…")
        self.k_bow.set_hint("updating…")
        self._supply_readout(s, st)
        self.explore.incidence.show_state(st, s, v)
        self.explore.mark_stale()
        drive = s.current_a if s.mode == "current" else s.voltage_v
        self.explore.map.set_point(drive, v)
        self._advise(st, s, v, None)
        self.guided.refresh(st, s, v)
        self._heavy_timer.start()
        self._schedule_save()
        self.timings["fast_ms"] = 1000 * (time.perf_counter() - t0)

    def _supply_readout(self, s: CutSetup, st) -> None:  # type: ignore[no-untyped-def]
        c = self._c
        i, u, p = float(st.current_a), float(st.voltage_v), float(st.power_w)
        r_cold = cold_resistance_ohm(s)
        if s.mode == "voltage":
            txt = f"<b>{s.voltage_v:.1f} V</b> → the wire draws <b>{i:.2f} A</b>, <b>{p:.1f} W</b>"
            if bool(st.limited):
                txt += (f"<br><span style='color:{c.warning}'>On the {s.current_limit_a:.1f} A current limit: the "
                        f"supply drops to {u:.1f} V (CC).</span>")
        else:
            txt = f"<b>{s.current_a:.2f} A</b> → needs <b>{u:.1f} V</b>, <b>{p:.1f} W</b>"
            if bool(st.limited):
                txt += (f"<br><span style='color:{c.warning}'>The supply tops out at {s.voltage_limit_v:.0f} V: "
                        f"only {i:.2f} A flow (CV).</span>")
        txt += (f"<br><span style='color:{c.muted}'>Hot wire {float(st.voltage_v) / max(i, 1e-9) - s.lead_resistance_ohm:.2f} Ω"
                f" · cold {r_cold:.2f} Ω + leads {s.lead_resistance_ohm:.2f} Ω</span>")
        self.params.set_supply_readout(txt)
        self.params.set_wire_info(f"Cold resistance between the clamps: {r_cold:.3f} Ω "
                                  f"(ρ·L/A, {s.span_mm:.0f} mm, Ø {s.diameter_mm:.2f} mm). Or type the one you "
                                  "measured:")

    def _tab_shown(self, i: int) -> None:
        w = self.tabs.widget(i)
        key = {id(self.explore): "explore", id(self.curves): "curves", id(self.sim): "sim",
               id(self.calib): "calib"}.get(id(w), "")
        self.tab_intro.setText(TAB_INTRO.get(key, ""))
        if w is self.calib:
            self.calib.refresh()
        elif w is self.curves:
            self.curves.refresh()

    def _refresh_curves(self) -> None:
        if self.tabs.currentWidget() is self.curves:
            self.curves.refresh()

    def _axis_limit(self) -> float | None:
        lim = self.params.limits()
        return min(lim.vmax_y, lim.vmax_z) * lim.feed_scale if lim.honor_axis_limits else None

    def _launch_heavy(self) -> None:
        """Start the background job for the latest parameters (or flag it, if one is still running)."""
        self._refresh_curves()  # debounced with the heavy part: a few model calls, on the UI thread
        if self._heavy is not None:
            self._heavy_pending = True  # the running job sees the new token, stops, and we start over
            return
        self._heavy_pending = False
        token = self._token
        s, v = self.setup(), self.params.probe_speed()
        s_profile = s.with_(block_width_mm=self.params.bw.value(), block_offset_mm=self.params.boff.value())
        vmax_axis = self._axis_limit()
        job = Job(lambda: None, parent=self)

        def stale() -> bool:
            return token != self._token

        def work() -> dict | None:
            t0 = time.perf_counter()
            vc = contact_speed(s)
            scan = feed_scan(s)
            rec = recommend(s, vc, vmax_axis)
            job.partial.emit({"token": token, "stage": "vc", "vc": vc, "scan": scan, "rec": rec, "v": v,
                              "setup": s, "ms": 1000 * (time.perf_counter() - t0)})
            if stale():
                return None
            t1 = time.perf_counter()
            m = operating_map(s)
            job.partial.emit({"token": token, "stage": "map", "map": m, "v": v, "setup": s,
                              "ms": 1000 * (time.perf_counter() - t1)})
            if stale():
                return None
            t2 = time.perf_counter()
            prof = span_profile(s_profile, speeds=PROFILE_SPEEDS, nodes=PROFILE_NODES)
            return {"token": token, "stage": "profile", "profile": prof, "v": v, "setup": s, "vc": vc,
                    "ms": 1000 * (time.perf_counter() - t2), "total_ms": 1000 * (time.perf_counter() - t0)}

        job._fn = work
        job.partial.connect(self._heavy_partial)
        job.done.connect(self._heavy_done)
        job.failed.connect(self._heavy_failed)
        self._heavy = job
        job.start()

    def _heavy_partial(self, out: dict) -> None:
        if out["token"] != self._token:
            return  # a newer edit is on its way
        s, v = out["setup"], out["v"]
        self.timings[f"{out['stage']}_ms"] = out["ms"]
        if out["stage"] == "vc":
            vc = out["vc"]
            self._last_vc = vc
            self.k_vc.set(f"{vc:.1f}" if vc > 0 else "—", "go slower to avoid contact" if v > vc else
                          f"you're at {100 * v / max(vc, 1e-9):.0f} %")
            win = out["scan"]["clean"]
            self.k_vc.set_typical(f"clean {win[0]:.1f}–{win[1]:.1f} mm/s (model)" if win else "no clean feed (model)",
                                  "Model estimate: the feeds that cut without contact and without over-melting at "
                                  "this drive.")
            self._advise(point_state(s, v), s, v, vc)
            self.guided.set_scan(vc, out["scan"], out["rec"], v)
        elif out["stage"] == "map":
            self.explore.map.set_map(out["map"])
            self.explore.map.set_point(s.current_a if s.mode == "current" else s.voltage_v, v)

    def _heavy_done(self, out: dict | None) -> None:
        self._heavy = None
        if out is not None and out["token"] == self._token:
            self.timings["profile_ms"] = out["ms"]
            self.timings["heavy_total_ms"] = out["total_ms"]
            self._last_profile = out["profile"]
            v = out["v"]
            self.explore.along.show_profile(out["profile"], v)
            at = out["profile"].at(v, self.params.boff.value())
            self.k_bow.set(f"{at['bow_mm']:.2f}", "no drag" if at["bow_mm"] < 1e-3 else "wire drags behind")
            self.guided.set_profile(out["profile"], v)
        if self._heavy_pending or (out is None or out["token"] != self._token):
            if not self._heavy_timer.isActive():
                self._launch_heavy()

    def _heavy_failed(self, msg: str) -> None:
        self._heavy = None
        self.advice.setText(f"<span style='color:{self._c.danger}'>{msg}</span>")
        if self._heavy_pending and not self._heavy_timer.isActive():
            self._launch_heavy()

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
    def load_text(self, text: str, name: str, block: FoamBlock | None = None) -> None:
        """Load a G-code. With ``block`` (the project's) the lab is linked to the project;
        without, it fits a block of its own to the G-code."""
        self.toolpath = parse_gcode(text)
        self.source_name = name
        self.linked = block is not None
        if block is not None:
            self.set_block(block)
        elif self.toolpath.moves:
            fit = fit_block(self.toolpath, width_x=self.params.bw.value())
            self.block = replace(fit, x_offset=self.params.boff.value())
            self.sim.set_block(self.block)
        tp = self.toolpath
        info = f"{len(tp.moves)} moves · {tp.cut_length:.0f} mm of path" if tp.moves else "no moves"
        owner = "the project's block and machine" if self.linked else "a block fitted to this G-code"
        self.source.setText(f"{name} — {info} · {owner}")

    def set_block(self, block: FoamBlock) -> None:
        """Show ``block`` (from the project) without echoing it back."""
        self.block = block
        self.sim.set_block(block)
        if (self.params.bw.value(), self.params.boff.value()) != (block.width_x, block.x_offset):
            self.params.set_block(block.width_x, block.x_offset)

    def set_rig(self, rig: HotWireRig) -> None:
        """The project's machine: the wire span between the arm tips."""
        if abs(self.params.span.value() - rig.wire_span) > 0.05:
            self.params.set_span(rig.wire_span)

    def load_file(self, path: str) -> None:
        with open(path, encoding="utf-8", errors="replace") as fh:
            self.load_text(fh.read(), Path(path).name)

    def _open_gcode(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open G-code", filter="G-code (*.gcode *.nc *.txt);;All files (*)")
        if path:
            self.load_file(path)
            self.show_advanced("sim")

    def set_project_provider(self, provider) -> None:  # type: ignore[no-untyped-def]
        self.project_provider = provider
        self.project_btn.setVisible(provider is not None)

    def _use_project(self) -> None:
        if self.project_provider is None:
            return
        got = self.project_provider()
        if got:
            self.load_text(*got)
            self.show_advanced("sim")

    def _preview_test(self, text: str, name: str) -> None:
        self.load_text(text, name)
        self.show_advanced("sim")
        self.run_simulation()

    def _block_from_form(self, vals: tuple[float, float, float, float]) -> None:
        y0, z0, ln, h = vals
        self.block = replace(self.block, length_y=ln, height_z=h, width_x=self.params.bw.value(), y0=y0, z0=z0,
                             x_offset=self.params.boff.value())
        if self.linked:
            self.block_edited.emit(self.block)

    # ── simulation ────────────────────────────────────────────────────
    def run_simulation(self) -> None:
        if not self.toolpath.moves:
            self.sim.on_progress(0, "Open a G-code first")
            return
        if self._sim_job is not None:
            return
        self.block = replace(self.block, width_x=self.params.bw.value(), x_offset=self.params.boff.value())
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
        p = self.params.profile(self.calib.measurements)
        p.work = self.work
        return p

    def apply_profile(self, p: cut_profile.CutProfile) -> None:
        self.params.set_profile(p)
        self.calib.set_measurements(p.measurements)

    def _load_saved(self) -> None:
        path = self.profile_path
        if path.exists():
            try:
                p = cut_profile.load(path)
                self.apply_profile(p)
                self.work = p.work
            except Exception:  # a broken profile must not keep the lab from opening
                pass

    def _schedule_save(self) -> None:
        if self.persist:
            self._save_timer.start()

    def save_default(self) -> None:
        """Write the profile (and the saved work settings) to :attr:`profile_path`. No-op unless ``persist``."""
        if not self.persist:
            return
        self._save_timer.stop()
        try:
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            cut_profile.save(self.current_profile(), self.profile_path)
        except OSError:
            pass

    def save_work(self) -> WorkSettings | None:
        """Guided mode's "Save and use for the project": store the work settings and hand them over."""
        rec = self.guided.recommendation()
        if "v" not in rec:
            return None
        s = self.setup()
        st = point_state(s, rec["v"])
        cal = s.calib
        self.work = WorkSettings(
            work_feed_mm_s=float(rec["v"]), kerf_mm=float(rec["kerf"]), supply_mode=s.mode,
            voltage_v=float(s.voltage_v if s.mode == "voltage" else st.voltage_v),
            current_a=float(st.current_a), calibrated=not (abs(cal.eta - 1) < 1e-6 and abs(cal.kappa - 1) < 1e-6),
            saved_at=datetime.now().isoformat(timespec="seconds"))
        self.params.set_probe_speed(rec["v"])
        self.save_default()
        where = f" to <i>{self.profile_path}</i>" if self.persist else ""
        self.guided.show_saved(f"<span style='color:{self._c.success}'>✓ Saved{where}.</span> Work feed "
                               f"{self.work.work_feed_mm_s:.1f} mm/s, kerf compensation "
                               f"{self.work.kerf_offset_mm:.2f} mm per side.")
        self.work_speed_chosen.emit(self.work.work_feed_mm_s, self.work.kerf_mm)
        self.work_saved.emit(self.work)
        self.close_requested.emit()
        return self.work

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
        self.setWindowTitle("Step 4 · Cut Lab — wire temperature, feed and kerf")
        self.resize(1560, 940)
        self.lab = CutLab(self, theme)
        self.lab.close_requested.connect(lambda: QTimer.singleShot(700, self.close))  # let "✓ Saved" show
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.lab)

    def closeEvent(self, ev) -> None:  # type: ignore[no-untyped-def]
        self.lab.save_default()
        super().closeEvent(ev)

