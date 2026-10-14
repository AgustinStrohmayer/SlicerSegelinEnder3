"""Cut Lab parameter panel: supply, feed, wire, foam, machine motion and model calibration."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ....core.calibration import resistivity_from_cold
from ....core.cut_profile import CutProfile
from ....core.cutting_physics import FOAMS, WIRE_MATERIALS, Calibration, CutSetup, Foam, WireMaterial
from ....core.motion import MotionLimits
from ..collapsible import CollapsibleSection
from ..numfield import NumField
from .common import ParamRow

CUSTOM = "Custom"


def _spin(lo: float, hi: float, val: float, dec: int = 2, step: float = 0.1, suffix: str = "", tip: str = "") -> NumField:
    s = NumField()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(val)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    s.setToolTip(tip)
    s.setAlignment(Qt.AlignmentFlag.AlignRight)
    return s


class ParamsPanel(QScrollArea):
    """Every parameter that changes the cut. ``changed`` is debounced (fires once per burst of edits)."""

    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setObjectName("Sidebar")  # same surface + cards as the main window's sidebar
        self._loading = False
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(10)  # coalesce one burst of edits; the read-outs are cheap
        self._debounce.timeout.connect(self.changed.emit)

        body = QWidget()
        body.setObjectName("SidebarBody")
        self.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)

        # ── power supply ──────────────────────────────────────────────
        sec = CollapsibleSection("Power supply")
        self.mode = QComboBox()
        self.mode.addItems(["Set current (CC), voltage limit", "Set voltage (CV), current limit"])
        self.mode.setCurrentIndex(1)  # bench supplies are usually run in CV, capped near 30 V
        self.mode.setToolTip("Like a bench supply:\n"
                             "CV: you set the voltage and a current limit. As the wire heats its resistance rises "
                             "and the current drops; if the wire would draw more than the limit, the supply holds "
                             "the limit (it drops into CC).\n"
                             "CC: you set the current; the supply raises the voltage up to its maximum.")
        sec.add(self.mode)
        self.current = ParamRow("Current", 0.1, 6.0, 1.2, step=0.05, suffix=" A",
                                tip="Current through the wire. Joule heat grows with I².")
        self.voltage = ParamRow("Voltage", 0.3, 30.0, 4.0, step=0.1, suffix=" V",
                                tip="Voltage at the supply terminals (leads + wire).")
        self.ilim = _spin(0.1, 20, 5.0, 2, 0.1, " A", "CV mode: the supply's current limit. If the wire would draw "
                                                      "more, the supply holds this current instead.")
        self.vmax = _spin(1, 120, 30.0, 1, 1, " V", "The most your supply can give (bench supplies: about 30 V). "
                                                   "Caps the voltage slider; in CC mode the supply cannot push "
                                                   "the current past this voltage.")
        self.leads = _spin(0, 5, 0.10, 3, 0.01, " Ω", "Resistance of the leads and clamps: they take a share of the "
                                                    "voltage.")
        sec.add(self.current)
        sec.add(self.voltage)
        f = QFormLayout()
        self.ilim_lbl = QLabel("Current limit")
        f.addRow(self.ilim_lbl, self.ilim)
        f.addRow("Supply max voltage", self.vmax)
        f.addRow("Lead resistance", self.leads)
        sec.add_layout(f)
        self.supply_out = QLabel("")
        self.supply_out.setObjectName("SupplyReadout")
        self.supply_out.setWordWrap(True)
        self.supply_out.setTextFormat(Qt.TextFormat.RichText)
        sec.add(self.supply_out)
        v.addWidget(sec)

        # ── feed ──────────────────────────────────────────────────────
        sec = CollapsibleSection("Feed")
        self.speed = ParamRow("Probe feed", 0.1, 60.0, 3.0, step=0.1, suffix=" mm/s", log=True,
                              tip="Feed speed used by the live read-outs and the cross-section.\n"
                                  "The cut simulation uses the G-code's own feeds (× override).")
        self.override = ParamRow("Feed override (simulation)", 10, 300, 100, step=5, decimals=0, suffix=" %",
                                 tip="Scales every feed of the G-code, like Marlin's M220.")
        sec.add(self.speed)
        sec.add(self.override)
        v.addWidget(sec)

        # ── wire ──────────────────────────────────────────────────────
        sec = CollapsibleSection("Wire")
        f = QFormLayout()
        self.wire = QComboBox()
        self.wire.addItems([*WIRE_MATERIALS, CUSTOM])
        self.diam = _spin(0.05, 2.0, 0.30, 3, 0.01, " mm", "Wire diameter.")
        self.span = _spin(20, 2000, 216.0, 1, 1, " mm", "Free length between the clamps (arm tips).")
        self.tension = _spin(0.5, 200, 8.0, 1, 0.5, " N", "Spring tension on the wire: resists bowing.")
        self.rho = _spin(0.01, 5.0, 1.09, 3, 0.01, " µΩ·m", "Electrical resistivity at 20 °C.")
        self.alpha = _spin(0, 20, 0.10, 3, 0.01, " ‰/K", "Temperature coefficient of resistance (per mille per K).")
        self.emis = _spin(0.05, 1.0, 0.70, 2, 0.05, "", "Emissivity: oxidised wire ≈ 0.7, bright ≈ 0.3.")
        self.wire_k = _spin(1, 400, 11.3, 1, 0.5, " W/m·K", "Thermal conductivity of the wire.")
        f.addRow("Material", self.wire)
        f.addRow("Diameter", self.diam)
        f.addRow("Span (clamp to clamp)", self.span)
        f.addRow("Tension", self.tension)
        f.addRow("Resistivity", self.rho)
        f.addRow("α (resistance)", self.alpha)
        f.addRow("Emissivity", self.emis)
        f.addRow("Conductivity", self.wire_k)
        sec.add_layout(f)
        self.r_info = QLabel("")
        self.r_info.setObjectName("CardSub")
        self.r_info.setWordWrap(True)
        sec.add(self.r_info)
        f = QFormLayout()
        self.r_meas = _spin(0, 1000, 0, 3, 0.1, " Ω", "Measured with a multimeter, supply OFF, clamp to clamp. "
                                                    "Sets the resistivity so the model's wire matches yours.")
        row = QHBoxLayout()
        row.addWidget(self.r_meas, 1)
        self.r_use = QPushButton("Use")
        self.r_use.setToolTip("Derive the resistivity from the measured cold resistance (ρ = R·A / L).")
        self.r_use.clicked.connect(self._use_measured_r)
        row.addWidget(self.r_use)
        f.addRow("Measured cold R", row)
        sec.add_layout(f)
        v.addWidget(sec)

        # ── foam ──────────────────────────────────────────────────────
        sec = CollapsibleSection("Foam")
        f = QFormLayout()
        self.foam = QComboBox()
        self.foam.addItems([*FOAMS, CUSTOM])
        self.foam.setCurrentText("EPS 20 kg/m³")
        self.dens = _spin(5, 200, 20, 1, 1, " kg/m³", "Foam density: more mass to melt per mm of cut.")
        self.fk = _spin(0.01, 0.2, 0.035, 3, 0.001, " W/m·K", "Foam thermal conductivity.")
        self.fc = _spin(500, 3000, 1300, 0, 50, " J/kg·K", "Specific heat of the polymer.")
        self.tiso = _spin(60, 400, 150, 0, 5, " °C",
                          "Collapse isotherm: the foam retreats from the wire where it gets this hot.\n"
                          "Polystyrene: Tg ≈ 100 °C, melts ≈ 240 °C. A calibration knob.")
        self.latent = _spin(0, 2000, 100, 0, 10, " kJ/kg", "Effective extra energy to remove the foam "
                                                            "(melt + partial ablation). A calibration knob.")
        self.bw = _spin(1, 2000, 150, 1, 1, " mm", "Block width along the wire (X).")
        self.boff = _spin(-1000, 1000, 0, 1, 1, " mm", "Block centre relative to the wire's centre.")
        f.addRow("Preset", self.foam)
        f.addRow("Density", self.dens)
        f.addRow("Conductivity", self.fk)
        f.addRow("Specific heat", self.fc)
        f.addRow("Collapse isotherm", self.tiso)
        f.addRow("Effective latent", self.latent)
        f.addRow("Block width (X)", self.bw)
        f.addRow("Block offset (X)", self.boff)
        sec.add_layout(f)
        v.addWidget(sec)

        # ── motion ────────────────────────────────────────────────────
        sec = CollapsibleSection("Machine motion (firmware)", expanded=False)
        f = QFormLayout()
        self.vy = _spin(1, 1000, 500, 0, 10, " mm/s", "Marlin max feedrate, Y.")
        self.vz = _spin(0.5, 1000, 5, 1, 1, " mm/s", "Marlin max feedrate, Z (stock Ender-3: 5 mm/s).")
        self.ay = _spin(10, 10000, 500, 0, 50, " mm/s²", "Max acceleration, Y.")
        self.az = _spin(10, 10000, 100, 0, 10, " mm/s²", "Max acceleration, Z.")
        self.jd = _spin(0.001, 1.0, 0.013, 3, 0.001, " mm", "Junction deviation: how fast corners are taken.")
        self.honor = QCheckBox("Apply per-axis feed limits")
        self.honor.setChecked(True)
        f.addRow("Max feed Y", self.vy)
        f.addRow("Max feed Z", self.vz)
        f.addRow("Accel Y", self.ay)
        f.addRow("Accel Z", self.az)
        f.addRow("Junction dev.", self.jd)
        f.addRow(self.honor)
        sec.add_layout(f)
        v.addWidget(sec)

        # ── model ─────────────────────────────────────────────────────
        sec = CollapsibleSection("Model & calibration", expanded=False)
        f = QFormLayout()
        self.ambient = _spin(-10, 50, 22, 1, 1, " °C", "Room temperature.")
        self.eta = _spin(0.05, 20, 1.0, 3, 0.05, " ×", "Wire→foam heat-transfer factor (fitted by calibration).")
        self.kappa = _spin(0.2, 4, 1.0, 3, 0.05, " ×", "Kerf ÷ (2 × melt radius) (fitted by calibration).")
        self.gapc = _spin(0.001, 0.5, 0.02, 3, 0.005, " mm", "Under this gap the wire is touching the foam.")
        self.drag = _spin(0, 20, 0.5, 3, 0.05, " N/m per mm/s",
                          "Bow force per metre of foam for each mm/s above the contact speed.")
        f.addRow("Ambient", self.ambient)
        f.addRow("η heat transfer", self.eta)
        f.addRow("κ kerf spread", self.kappa)
        f.addRow("Contact gap", self.gapc)
        f.addRow("Drag", self.drag)
        sec.add_layout(f)
        note = QLabel("Material values are typical handbook values. Fit η and κ to your own cuts in "
                      "the Calibration tab.")
        note.setWordWrap(True)
        note.setObjectName("CardSub")
        sec.add(note)
        v.addWidget(sec)
        v.addStretch(1)

        self.mode.currentIndexChanged.connect(self._on_mode)
        self.wire.currentTextChanged.connect(self._on_wire)
        self.foam.currentTextChanged.connect(self._on_foam)
        for w in (self.current, self.voltage, self.speed, self.override):
            w.valueChanged.connect(self._edited)
        self.vmax.valueChanged.connect(self._on_vmax)
        for w in (self.ilim, self.leads, self.diam, self.span, self.tension, self.ambient, self.eta, self.kappa, self.gapc,
                  self.drag, self.bw, self.boff, self.vy, self.vz, self.ay, self.az, self.jd):
            w.valueChanged.connect(self._edited)
        for w in (self.rho, self.alpha, self.emis, self.wire_k):
            w.valueChanged.connect(lambda _=0: self._custom(self.wire))
        for w in (self.dens, self.fk, self.fc, self.tiso, self.latent):
            w.valueChanged.connect(lambda _=0: self._custom(self.foam))
        self.honor.toggled.connect(self._edited)
        self._on_wire(self.wire.currentText())
        self._on_mode()

    def minimumSizeHint(self) -> QSize:
        # never narrower than the fields: the horizontal scroll bar is off, so they would be cut
        body = self.widget().minimumSizeHint().width() if self.widget() else 0
        return QSize(max(310, body + self.verticalScrollBar().sizeHint().width() + 2 * self.frameWidth()),
                     super().minimumSizeHint().height())

    # ── state ─────────────────────────────────────────────────────────
    def _edited(self, *_: object) -> None:
        if not self._loading:
            self._debounce.start()

    def _custom(self, combo: QComboBox) -> None:
        if self._loading:
            return
        if combo.currentText() != CUSTOM:
            combo.blockSignals(True)
            combo.setCurrentText(CUSTOM)
            combo.blockSignals(False)
        self._edited()

    def _on_mode(self) -> None:
        cv = self.mode.currentIndex() == 1
        self.current.setVisible(not cv)
        self.voltage.setVisible(cv)
        self.ilim.setVisible(cv)
        self.ilim_lbl.setVisible(cv)
        self._edited()

    def _on_vmax(self, vmax: float) -> None:
        self.voltage.set_maximum(vmax)
        self._edited()

    def _use_measured_r(self) -> None:
        r = self.r_meas.value()
        if r > 0:
            self.set_resistivity(resistivity_from_cold(r, self.setup()))

    def set_supply_readout(self, html: str) -> None:
        self.supply_out.setText(html)

    def set_wire_info(self, text: str) -> None:
        self.r_info.setText(text)

    def is_cv(self) -> bool:
        return self.mode.currentIndex() == 1

    def _on_wire(self, name: str) -> None:
        w = WIRE_MATERIALS.get(name)
        if w is None:
            return
        self._loading = True
        self.rho.setValue(w.resistivity_ohm_m * 1e6)
        self.alpha.setValue(w.alpha_per_k * 1e3)
        self.emis.setValue(w.emissivity)
        self.wire_k.setValue(w.conductivity_w_mk)
        self._loading = False
        self._edited()

    def _on_foam(self, name: str) -> None:
        fo = FOAMS.get(name)
        if fo is None:
            return
        self._loading = True
        self.dens.setValue(fo.density_kg_m3)
        self.fk.setValue(fo.conductivity_w_mk)
        self.fc.setValue(fo.specific_heat_j_kgk)
        self.tiso.setValue(fo.iso_temp_c)
        self.latent.setValue(fo.latent_j_kg / 1e3)
        self._loading = False
        self._edited()

    def setup(self) -> CutSetup:
        base = WIRE_MATERIALS.get(self.wire.currentText(), WIRE_MATERIALS["Nichrome 80/20"])
        wire = WireMaterial(self.wire.currentText(), self.rho.value() * 1e-6, self.alpha.value() * 1e-3,
                            self.wire_k.value(), self.emis.value(), base.density_kg_m3, base.specific_heat_j_kgk,
                            base.max_temp_c)
        fbase = FOAMS.get(self.foam.currentText(), FOAMS["EPS 20 kg/m³"])
        foam = Foam(self.foam.currentText(), self.dens.value(), self.fk.value(), self.fc.value(), self.tiso.value(),
                    self.latent.value() * 1e3, fbase.compressive_kpa)
        return CutSetup(
            wire=wire, diameter_mm=self.diam.value(), span_mm=self.span.value(), tension_n=self.tension.value(),
            foam=foam, block_width_mm=min(self.bw.value(), self.span.value() - 2), block_offset_mm=self.boff.value(),
            mode="voltage" if self.mode.currentIndex() == 1 else "current", current_a=self.current.value(),
            voltage_v=self.voltage.value(), lead_resistance_ohm=self.leads.value(), ambient_c=self.ambient.value(),
            current_limit_a=self.ilim.value(), voltage_limit_v=self.vmax.value(),
            calib=Calibration(eta=self.eta.value(), kappa=self.kappa.value(), contact_gap_mm=self.gapc.value(),
                              c_drag_n_m_per_mm_s=self.drag.value()),
        )

    def limits(self) -> MotionLimits:
        return MotionLimits(vmax_y=self.vy.value(), vmax_z=self.vz.value(), accel_y=self.ay.value(),
                            accel_z=self.az.value(), junction_deviation_mm=self.jd.value(),
                            honor_axis_limits=self.honor.isChecked(), feed_scale=self.override.value() / 100)

    def probe_speed(self) -> float:
        return self.speed.value()

    def set_drive(self, drive: float) -> None:
        (self.voltage if self.mode.currentIndex() == 1 else self.current).setValue(drive)
        self._edited()

    def set_voltage(self, x: float) -> None:
        self.voltage.setValue(x)
        self._edited()

    def set_current(self, x: float) -> None:
        self.current.setValue(x)
        self._edited()

    def set_probe_speed(self, v: float) -> None:
        self.speed.setValue(v)
        self._edited()

    def set_calibration(self, eta: float, kappa: float) -> None:
        self.eta.setValue(eta)
        self.kappa.setValue(kappa)

    def set_drag(self, c: float) -> None:
        self.drag.setValue(c)

    def set_block(self, width: float, offset: float) -> None:
        self._loading = True
        self.bw.setValue(width)
        self.boff.setValue(offset)
        self._loading = False
        self._edited()

    def set_span(self, span: float) -> None:
        self.span.setValue(span)

    def set_resistivity(self, rho_ohm_m: float) -> None:
        self.rho.setValue(rho_ohm_m * 1e6)

    def profile(self, measurements: list) -> CutProfile:  # type: ignore[type-arg]
        return CutProfile(setup=self.setup(), limits=self.limits(), measurements=list(measurements),
                          probe_speed_mm_s=self.probe_speed())

    def set_profile(self, p: CutProfile) -> None:
        s = p.setup
        self._loading = True
        self.mode.setCurrentIndex(1 if s.mode == "voltage" else 0)
        self.vmax.setValue(s.voltage_limit_v)
        self.voltage.set_maximum(s.voltage_limit_v)
        self.ilim.setValue(s.current_limit_a)
        self.current.setValue(s.current_a)
        self.voltage.setValue(s.voltage_v)
        self.leads.setValue(s.lead_resistance_ohm)
        self.wire.setCurrentText(s.wire.name if s.wire.name in WIRE_MATERIALS else CUSTOM)
        self.rho.setValue(s.wire.resistivity_ohm_m * 1e6)
        self.alpha.setValue(s.wire.alpha_per_k * 1e3)
        self.emis.setValue(s.wire.emissivity)
        self.wire_k.setValue(s.wire.conductivity_w_mk)
        self.diam.setValue(s.diameter_mm)
        self.span.setValue(s.span_mm)
        self.tension.setValue(s.tension_n)
        self.foam.setCurrentText(s.foam.name if s.foam.name in FOAMS else CUSTOM)
        self.dens.setValue(s.foam.density_kg_m3)
        self.fk.setValue(s.foam.conductivity_w_mk)
        self.fc.setValue(s.foam.specific_heat_j_kgk)
        self.tiso.setValue(s.foam.iso_temp_c)
        self.latent.setValue(s.foam.latent_j_kg / 1e3)
        self.bw.setValue(s.block_width_mm)
        self.boff.setValue(s.block_offset_mm)
        self.ambient.setValue(s.ambient_c)
        self.eta.setValue(s.calib.eta)
        self.kappa.setValue(s.calib.kappa)
        self.gapc.setValue(s.calib.contact_gap_mm)
        self.drag.setValue(s.calib.c_drag_n_m_per_mm_s)
        lim = p.limits
        self.vy.setValue(lim.vmax_y)
        self.vz.setValue(lim.vmax_z)
        self.ay.setValue(lim.accel_y)
        self.az.setValue(lim.accel_z)
        self.jd.setValue(lim.junction_deviation_mm)
        self.honor.setChecked(lim.honor_axis_limits)
        self.override.setValue(lim.feed_scale * 100)
        self.speed.setValue(p.probe_speed_mm_s)
        self._loading = False
        self._on_mode()
        self._edited()

