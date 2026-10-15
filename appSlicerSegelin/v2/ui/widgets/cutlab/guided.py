"""Guided mode of the Cut Lab: five short screens for someone who has never cut foam.

Each screen asks one question (or one action), says in one sentence why it
matters and shows the result right next to it:

1. your power supply and wire  → how hot the wire gets, the current it draws;
2. a test feed                  → what the wire does in the foam at that speed;
3. the result                   → wire temperature, kerf, clean cut or not;
4. calibrate (optional)         → the quick resistance check or the full guide;
5. your settings                → one summary and one button: *Save and use for
                                  the project*.

The guided screens hold no state of their own: every control writes straight
into the shared :class:`ParamsPanel`, and :meth:`GuidedPanel.refresh` reads it
back, so guided and advanced mode always show the same setup. ``refresh`` is
the cheap part (every edit); the feed scan, the recommendation and the profile
along the wire arrive later from the Cut Lab's background job
(:meth:`set_scan`, :meth:`set_profile`).
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ....core.calibration import resistivity_from_cold
from ....core.cutting_physics import (
    FOAMS,
    WIRE_MATERIALS,
    CutSetup,
    PointState,
    SpanProfile,
    cold_resistance_ohm,
)
from ..numfield import NumField
from .common import REGIME, ParamRow, card, colors
from .explore import HOT_LIMIT_C, AlongWireView, IncidenceView, regime_of, wire_color
from .params import ParamsPanel
from .typical import SAFE_FRACTION, typical

STEPS = ("Supply && wire", "Test feed", "Result", "Calibrate", "Your settings")

VERDICT = {
    "noncontact": ("Yes — a clean cut", "The wire melts its way through without touching the foam."),
    "overmelt": ("Clean, but a wide slot", "The wire is hot for this speed: the edge is clean but more foam melts away."),
    "contact": ("No — the wire touches", "It is moving faster than it can melt: it drags, bends and rounds the corners."),
    "stall": ("No — the wire can't keep up", "It can't melt the foam this fast: it tears it or gets stuck. "
                                            "Slow down or raise the drive."),
}


def _body(text: str, obj: str = "GuideBody") -> QLabel:
    lab = QLabel(text)
    lab.setObjectName(obj)
    lab.setWordWrap(True)
    lab.setTextFormat(Qt.TextFormat.RichText)
    return lab


def supply_text(s: CutSetup, st: PointState) -> str:
    """'4.0 V → 1.14 A · 4.6 W' (CV) or '1.20 A → 4.1 V · 4.9 W' (CC), with the limit when it bites."""
    i, u, p = float(st.current_a), float(st.voltage_v), float(st.power_w)
    if s.mode == "voltage":
        txt = f"{s.voltage_v:.1f} V → {i:.2f} A · {p:.1f} W"
        if bool(st.limited):
            txt += f" (held at the {s.current_limit_a:.1f} A limit: {u:.1f} V at the terminals)"
    else:
        txt = f"{s.current_a:.2f} A → {u:.1f} V · {p:.1f} W"
        if bool(st.limited):
            txt += f" (the supply tops out at {s.voltage_limit_v:.0f} V: only {i:.2f} A flow)"
    return txt


class WireGlow(QWidget):
    """The wire between the machine's arms, glowing at its temperature, over a 'can it cut?' thermometer."""

    def __init__(self, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._c = colors(theme)
        self.t_air = 20.0
        self.t_cut_min = 150.0  # the foam's collapse temperature: below it nothing melts
        self.t_max = 1100.0
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_temps(self, t_air: float, t_cut_min: float, t_max: float) -> None:
        self.t_air, self.t_cut_min, self.t_max = t_air, t_cut_min, t_max
        self.update()

    def paintEvent(self, ev) -> None:  # type: ignore[no-untyped-def]
        c = self._c
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        # arms and wire
        x0, x1, yw = 50.0, w - 50.0, h * 0.34
        p.setPen(QPen(QColor(c.border_strong), 6, cap=Qt.PenCapStyle.RoundCap))
        for x in (x0, x1):
            p.drawLine(QPointF(x, yw - 46), QPointF(x, yw + 30))
        grad = QLinearGradient(x0, 0, x1, 0)  # the arms keep the ends cool
        grad.setColorAt(0.0, QColor(wire_color(min(self.t_air, 120.0))))
        grad.setColorAt(0.12, QColor(wire_color(self.t_air)))
        grad.setColorAt(0.88, QColor(wire_color(self.t_air)))
        grad.setColorAt(1.0, QColor(wire_color(min(self.t_air, 120.0))))
        if self.t_air > 200:  # a soft halo when it glows
            halo = QColor(wire_color(self.t_air))
            halo.setAlpha(60)
            p.setPen(QPen(halo, 16, cap=Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(x0, yw), QPointF(x1, yw))
        p.setPen(QPen(grad, 5, cap=Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(x0, yw), QPointF(x1, yw))
        f = QFont(self.font())
        f.setPixelSize(30)  # the theme sizes fonts in px, so scale in px too
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(c.text))
        p.drawText(QRectF(0, yw - 72, w, 44), Qt.AlignmentFlag.AlignCenter, f"{self.t_air:.0f} °C")
        p.setFont(self.font())
        p.setPen(QColor(c.muted))
        p.drawText(QRectF(0, yw + 8, w, 22), Qt.AlignmentFlag.AlignCenter, "the wire in free air, between the arms")

        # thermometer: too cold | cuts | too hot
        bx0, bx1, by, bh = 40.0, w - 40.0, h * 0.70, 14.0
        top = max(self.t_max, HOT_LIMIT_C * 1.4, self.t_air * 1.1)

        def xt(t: float) -> float:
            return bx0 + (bx1 - bx0) * min(max(t, 0.0), top) / top

        zones = ((0, self.t_cut_min, REGIME["stall"], ("too cold to cut", "too cold", "cold")),
                 (self.t_cut_min, HOT_LIMIT_C, REGIME["noncontact"], ("cuts foam", "cuts")),
                 (HOT_LIMIT_C, top, "#9B6BE0", ("too hot: smoke, wide slot", "too hot", "hot")))
        fm = p.fontMetrics()
        for t0, t1, col, texts in zones:
            room = xt(t1) - xt(t0)
            text = next((t for t in texts if fm.horizontalAdvance(t) + 6 <= room), texts[-1])
            qc = QColor(col)
            qc.setAlpha(170)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qc)
            p.drawRoundedRect(QRectF(xt(t0), by, xt(t1) - xt(t0), bh), 4, 4)
            p.setPen(QColor(c.muted))
            tw = fm.horizontalAdvance(text) + 6  # a narrow zone's label may spill over, but never off the bar
            cx = min(max((xt(t0) + xt(t1)) / 2, bx0 + tw / 2), bx1 - tw / 2)
            p.drawText(QRectF(cx - tw / 2, by + bh + 4, tw, 20), Qt.AlignmentFlag.AlignCenter, text)
        xm = xt(self.t_air)
        p.setPen(QPen(QColor(c.text), 2))
        p.drawLine(QPointF(xm, by - 8), QPointF(xm, by + bh + 2))
        p.setBrush(QColor(c.text))
        p.drawPolygon([QPointF(xm - 6, by - 14), QPointF(xm + 6, by - 14), QPointF(xm, by - 6)])
        p.end()


class FeedGauge(QWidget):
    """Feed speeds from slow to fast, coloured by what the cut does there, with a marker at the test feed."""

    LO, HI = 0.1, 60.0

    def __init__(self, theme: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._c = colors(theme)
        self.v = 3.0
        self.v_rec: float | None = None
        self.zones: list[tuple[float, float, str]] = []
        self.setMinimumHeight(84)
        self.setMaximumHeight(96)

    def set_scan(self, scan: dict, v_rec: float | None) -> None:
        """Regimes along the feed axis (from :func:`typical.feed_scan`, computed in the background)."""
        vs, regs = scan["speeds"], scan["regimes"]
        zones: list[tuple[float, float, str]] = []
        for k, r in enumerate(regs):
            lo = float(vs[k])
            hi = float(vs[k + 1]) if k + 1 < len(vs) else self.HI
            r = str(r)
            if zones and zones[-1][2] == r:
                zones[-1] = (zones[-1][0], hi, r)
            else:
                zones.append((lo, hi, r))
        self.zones, self.v_rec = zones, v_rec
        self.update()

    def set_speed(self, v: float) -> None:
        self.v = v
        self.update()

    def _x(self, v: float) -> float:
        f = (math.log(max(v, self.LO)) - math.log(self.LO)) / (math.log(self.HI) - math.log(self.LO))
        return 20 + (self.width() - 40) * min(1.0, max(0.0, f))

    def paintEvent(self, ev) -> None:  # type: ignore[no-untyped-def]
        c = self._c
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        by, bh = 30.0, 16.0
        names = {"noncontact": "clean", "overmelt": "wide slot", "contact": "wire touches", "stall": "can't melt"}
        for lo, hi, r in self.zones:
            col = QColor(REGIME[r])
            col.setAlpha(190)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            x0, x1 = self._x(lo), self._x(hi)
            p.drawRect(QRectF(x0, by, x1 - x0, bh))
            if x1 - x0 > 60:
                p.setPen(QColor("#111111"))
                p.drawText(QRectF(x0, by, x1 - x0, bh), Qt.AlignmentFlag.AlignCenter, names[r])
        p.setPen(QColor(c.muted))
        for v in (0.1, 0.3, 1, 3, 10, 30, 60):
            x = self._x(v)
            p.drawText(QRectF(x - 20, by + bh + 2, 40, 16), Qt.AlignmentFlag.AlignCenter, f"{v:g}")
        p.drawText(QRectF(0, by + bh + 18, self.width(), 16), Qt.AlignmentFlag.AlignCenter, "feed, mm/s (slow → fast)")
        if self.v_rec is not None:  # the suggestion, as a hollow tick
            xr = self._x(self.v_rec)
            p.setPen(QPen(QColor(c.accent), 2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(xr, by - 2), QPointF(xr, by + bh + 2))
        xm = self._x(self.v)
        p.setPen(QPen(QColor(c.text), 2))
        p.drawLine(QPointF(xm, by - 4), QPointF(xm, by + bh + 2))
        p.setBrush(QColor(c.text))
        p.drawPolygon([QPointF(xm - 6, by - 12), QPointF(xm + 6, by - 12), QPointF(xm, by - 4)])
        p.drawText(QRectF(xm - 60, 0, 120, 16), Qt.AlignmentFlag.AlignCenter, f"you: {self.v:.1f}")
        p.end()


class BigCard(QFrame):
    """A plain-language result: caption, big value, one line of meaning, and what is typical."""

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("GuideCard")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(2)
        self.cap = QLabel(caption)
        self.cap.setObjectName("GuideCardCaption")
        self.val = QLabel("—")
        self.val.setObjectName("GuideCardValue")
        self.sub = QLabel("")
        self.sub.setObjectName("GuideCardSub")
        self.sub.setWordWrap(True)
        self.typ = QLabel("")
        self.typ.setObjectName("GuideTypical")
        self.typ.setWordWrap(True)
        self.typ.setVisible(False)
        for w in (self.cap, self.val, self.sub, self.typ):
            v.addWidget(w)
        v.addStretch(1)

    def set(self, value: str, sub: str, color: str | None = None) -> None:
        self.val.setText(value)
        self.sub.setText(sub)
        self.val.setStyleSheet(f"color: {color};" if color else "")

    def set_typical(self, text: str, tip: str = "") -> None:
        self.typ.setText(text)
        self.typ.setToolTip(tip)
        self.typ.setVisible(bool(text))


class GuidedPanel(QWidget):
    """The five guided screens over the shared parameter panel."""

    advanced_requested = pyqtSignal(str)  # tab to open: "explore", "curves", "sim", "calib"
    simulate_requested = pyqtSignal()
    save_requested = pyqtSignal()  # "Save and use for the project" (the Cut Lab saves and hands it over)

    def __init__(self, theme: str, params: ParamsPanel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Guided")
        self._c = colors(theme)
        self.params = params
        self._syncing = False
        self._vc: float | None = None
        self._profile: SpanProfile | None = None
        self._scan: dict | None = None
        self._rec: dict = {"state": "pending"}
        self._st: PointState | None = None
        self._s: CutSetup | None = None
        self.measurement_count = 0
        self.save_path_text = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 0, 4, 4)
        root.setSpacing(10)
        root.addLayout(self._chips())
        self.stack = QStackedWidget()
        for build in (self._screen_supply, self._screen_feed, self._screen_result, self._screen_calib,
                      self._screen_final):
            self.stack.addWidget(build(theme))
        root.addWidget(self.stack, 1)
        root.addLayout(self._nav())
        self.go(0)

    # ── frame: chips, screens, nav ────────────────────────────────────
    def _chips(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        self.chip_group = QButtonGroup(self)
        self.chips: list[QPushButton] = []
        for k, name in enumerate(STEPS):
            b = QPushButton(f"{k + 1}  {name}")
            b.setObjectName("GuideChip")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setMinimumWidth(b.sizeHint().width() + 16)
            self.chip_group.addButton(b, k)
            self.chips.append(b)
            row.addWidget(b)
        row.addStretch(1)
        self.chip_group.idClicked.connect(self.go)
        return row

    def _nav(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self.back_btn = QPushButton("← Back")
        self.back_btn.clicked.connect(lambda: self.go(self.step - 1))
        self.next_btn = QPushButton("Next →")
        self.next_btn.setProperty("role", "primary")
        self.next_btn.clicked.connect(lambda: self.go(self.step + 1))
        self.save_btn = QPushButton("Save and use for the project")
        self.save_btn.setProperty("role", "primary")
        self.save_btn.setToolTip("Saves these settings (loaded again next time) and hands the work feed and the "
                                 "kerf compensation to the project.")
        self.save_btn.clicked.connect(self.save_requested.emit)
        self.pos_lbl = QLabel("")
        self.pos_lbl.setObjectName("CardSub")
        row.addWidget(self.back_btn)
        row.addStretch(1)
        row.addWidget(self.pos_lbl)
        row.addSpacing(12)
        row.addWidget(self.next_btn)
        row.addWidget(self.save_btn)
        return row

    def go(self, k: int) -> None:
        k = max(0, min(len(STEPS) - 1, k))
        self.step = k
        self.stack.setCurrentIndex(k)
        self.chips[k].setChecked(True)
        self.back_btn.setEnabled(k > 0)
        last = k == len(STEPS) - 1
        self.next_btn.setVisible(not last)
        self.save_btn.setVisible(last)
        self.next_btn.setText("Skip — use typical values →" if k == 3 else "Next →")
        self.pos_lbl.setText(f"Step {k + 1} of {len(STEPS)}")
        if last:
            self.save_out.setText("")
        if k == 1 and self._st is not None and self._s is not None:  # only the visible view is kept live
            self.g_incidence.show_state(self._st, self._s, self.params.probe_speed())

    def _screen(self, k: int, question: str, why: str) -> tuple[QWidget, QVBoxLayout, QVBoxLayout]:
        """A screen: question + why + controls on the left, the visible result on the right."""
        page = QWidget()
        h = QHBoxLayout(page)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(14)
        left = QFrame()
        left.setObjectName("GuideAsk")
        left.setFixedWidth(430)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(18, 16, 18, 16)
        lv.setSpacing(10)
        n = QLabel(f"STEP {k + 1} OF {len(STEPS)}")
        n.setObjectName("GuideStepNo")
        q = _body(question, "GuideQuestion")
        w = _body(f"<b>Why it matters:</b> {why}", "GuideWhy")
        for x in (n, q, w):
            lv.addWidget(x)
        lv.addSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(left)
        scroll.setFixedWidth(446)
        h.addWidget(scroll)
        right = QVBoxLayout()
        right.setSpacing(10)
        h.addLayout(right, 1)
        return page, lv, right

    # ── 1 supply & wire ───────────────────────────────────────────────
    def _screen_supply(self, theme: str) -> QWidget:
        page, lv, rv = self._screen(
            0, "What powers your wire, and what wire is it?",
            "the supply heats the wire, and how hot it gets decides how the foam melts.")
        f = QFormLayout()
        f.setVerticalSpacing(8)
        self.g_mode = QComboBox()
        self.g_mode.addItems(["Voltage (V), with a current limit — CV", "Current (A), up to the max voltage — CC"])
        self.g_mode.setToolTip("Look at your supply: most bench supplies are set in volts with a current limit "
                               "(CV). If you set the amps instead, it is constant current (CC).")
        f.addRow("I set my supply by", self.g_mode)
        lv.addLayout(f)
        self.g_voltage = ParamRow("Voltage", 0.3, 30.0, 4.0, step=0.1, suffix=" V",
                                  tip="The voltage you set on the supply.")
        self.g_current = ParamRow("Current", 0.1, 6.0, 1.2, step=0.05, suffix=" A",
                                  tip="The current you set on the supply.")
        lv.addWidget(self.g_voltage)
        lv.addWidget(self.g_current)
        f = QFormLayout()
        f.setVerticalSpacing(8)
        self.g_ilim = NumField(lo=0.1, hi=20.0, step=0.1, decimals=2, suffix=" A")
        self.g_ilim.setToolTip("The current limit you set on the supply (CV).")
        self.g_ilim_lbl = QLabel("Current limit")
        f.addRow(self.g_ilim_lbl, self.g_ilim)
        self.g_wire = QComboBox()
        self.g_wire.addItems(list(WIRE_MATERIALS))
        self.g_diam = NumField()
        self.g_diam.setRange(0.05, 2.0)
        self.g_diam.setDecimals(2)
        self.g_diam.setSingleStep(0.05)
        self.g_diam.setSuffix(" mm")
        self.g_diam.setKeyboardTracking(False)
        self.g_foam = QComboBox()
        self.g_foam.addItems(list(FOAMS))
        f.addRow("Wire material", self.g_wire)
        f.addRow("Wire diameter", self.g_diam)
        f.addRow("Foam", self.g_foam)
        lv.addLayout(f)
        self.g_span = _body("", "GuideHint")
        lv.addWidget(self.g_span)
        lv.addStretch(1)

        fr, v = card("How hot your wire gets")
        self.glow = WireGlow(theme)
        v.addWidget(self.glow, 1)
        self.supply_verdict = _body("", "GuideVerdict")
        v.addWidget(self.supply_verdict)
        self.supply_typ = _body("", "GuideTypical")
        v.addWidget(self.supply_typ)
        rv.addWidget(fr, 1)

        self.g_mode.currentIndexChanged.connect(lambda i: self._push(self.params.mode.setCurrentIndex, 1 - i))
        self.g_current.valueChanged.connect(lambda x: self._push(self.params.set_current, x))
        self.g_voltage.valueChanged.connect(lambda x: self._push(self.params.set_voltage, x))
        self.g_ilim.valueChanged.connect(lambda x: self._push(self.params.ilim.setValue, x))
        self.g_wire.currentTextChanged.connect(lambda t: self._push(self.params.wire.setCurrentText, t))
        self.g_diam.valueChanged.connect(lambda x: self._push(self.params.diam.setValue, x))
        self.g_foam.currentTextChanged.connect(lambda t: self._push(self.params.foam.setCurrentText, t))
        return page

    # ── 2 test feed ───────────────────────────────────────────────────
    def _screen_feed(self, theme: str) -> QWidget:
        page, lv, rv = self._screen(
            1, "Pick a test speed for the wire.",
            "too slow melts a wide slot; too fast and the wire touches the foam, drags and bends.")
        self.g_speed = ParamRow("Test feed", 0.1, 60.0, 3.0, step=0.1, suffix=" mm/s", log=True,
                                tip="How fast the wire moves through the foam.")
        lv.addWidget(self.g_speed)
        row = QHBoxLayout()
        for text, val in (("Slow · 1", 1.0), ("Medium · 3", 3.0), ("Fast · 8", 8.0)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, x=val: self._set_speed(x))
            row.addWidget(b)
        lv.addLayout(row)
        self.suggest_btn = QPushButton("Suggest a good speed for me")
        self.suggest_btn.setProperty("role", "primary")
        self.suggest_btn.clicked.connect(self._suggest_speed)
        lv.addWidget(self.suggest_btn)
        self.suggest_why = _body("", "GuideHint")
        lv.addWidget(self.suggest_why)
        self.feed_verdict = _body("", "GuideVerdict")
        lv.addWidget(self.feed_verdict)
        lv.addStretch(1)

        fr, v = card("Where your speed falls",
                     "Every speed from slow to fast for this wire and supply, coloured by what the cut does. "
                     "Dashed tick: the suggested speed.")
        self.gauge = FeedGauge(theme)
        v.addWidget(self.gauge)
        self.feed_typ = _body("", "GuideTypical")
        v.addWidget(self.feed_typ)
        rv.addWidget(fr)
        fr, v = card("The wire in the foam, seen from the end",
                     "The wire (dot) moves right. The foam melts away before the wire reaches it, leaving a slot "
                     "(the kerf) behind. A gap between wire and foam = a clean cut; no gap = the wire touches.")
        self.g_incidence = IncidenceView(theme)
        v.addWidget(self.g_incidence, 1)
        rv.addWidget(fr, 1)
        self.g_speed.valueChanged.connect(lambda x: self._push(self.params.set_probe_speed, x))
        return page

    def _set_speed(self, v: float) -> None:
        self.g_speed.setValue(v)
        self._push(self.params.set_probe_speed, v)

    def _suggest_speed(self) -> None:
        if "v" in self._rec:
            self._set_speed(self._rec["v"])

    # ── 3 result ──────────────────────────────────────────────────────
    def _screen_result(self, theme: str) -> QWidget:
        page, lv, rv = self._screen(
            2, "Read the result of your test.",
            "these three numbers tell you if the cut is clean and how much smaller the part comes out.")
        self.c_temp = BigCard("Wire temperature while cutting")
        self.c_kerf = BigCard("Slot width (kerf)")
        self.c_clean = BigCard("Clean cut?")
        for w in (self.c_clean, self.c_kerf, self.c_temp):
            lv.addWidget(w)
        again = QPushButton("← Try another speed")
        again.clicked.connect(lambda: self.go(1))
        lv.addWidget(again)
        lv.addStretch(1)
        fr, v = card("Along the wire, clamp to clamp",
                     "The wire is not equally hot everywhere. The arms cool its ends, and inside the foam (shaded) it "
                     "gives heat to the foam, so it is hottest in the middle and in free air. Where it is hotter "
                     "the slot is wider. Orange: wire temperature (dashed: in free air). Amber: slot width. "
                     "Blue dashed: how far the wire bends back.")
        self.g_along = AlongWireView(theme)
        v.addWidget(self.g_along, 1)
        rv.addWidget(fr, 1)
        return page

    # ── 4 calibrate ───────────────────────────────────────────────────
    def _screen_calib(self, theme: str) -> QWidget:
        page, lv, rv = self._screen(
            3, "Do you want the numbers to match your own machine?",
            "the model uses typical material data; your own measurements make its predictions yours.")
        self.calib_status = _body("", "GuideVerdict")
        lv.addWidget(self.calib_status)
        lv.addWidget(_body("<b>This step is optional.</b> Without it the predictions are a starting point from "
                           "handbook values; a calibration is saved and reused next time.", "GuideHint"))
        lv.addStretch(1)

        fr, v = card("Quick check · 2 minutes",
                     "With the supply OFF, measure the wire's resistance from clamp to clamp with a multimeter. "
                     "This corrects the wire's real resistance, which sets how much it heats.")
        f = QFormLayout()
        self.g_rcold = NumField(step=0.1)
        self.g_rcold.setRange(0, 1000)
        self.g_rcold.setDecimals(3)
        self.g_rcold.setSuffix(" Ω")
        self.g_rcold.setKeyboardTracking(False)
        f.addRow("Measured resistance", self.g_rcold)
        self.g_rexp = QLabel("")
        self.g_rexp.setObjectName("CardSub")
        f.addRow("Expected", self.g_rexp)
        v.addLayout(f)
        b = QPushButton("Use my measurement")
        b.clicked.connect(self._apply_cold)
        self.g_rout = _body("", "GuideHint")
        row = QHBoxLayout()
        row.addWidget(b)
        row.addWidget(self.g_rout, 1)
        v.addLayout(row)
        rv.addWidget(fr)

        fr, v = card("Full calibration · about 30 minutes",
                     "Cut a few test strips at different speeds, measure them with a caliper and type the numbers "
                     "in. The Cut Lab then fits its model so the predicted kerf is your machine's. A six-step guide "
                     "walks you through it (it opens in Advanced mode).")
        b = QPushButton("Open the calibration guide →")
        b.setProperty("role", "primary")
        b.clicked.connect(lambda: self.advanced_requested.emit("calib"))
        row = QHBoxLayout()
        row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        rv.addWidget(fr)
        rv.addStretch(1)
        return page

    def _apply_cold(self) -> None:
        r = self.g_rcold.value()
        if r <= 0:
            self.g_rout.setText("Type the resistance you measured first.")
            return
        self.params.set_resistivity(resistivity_from_cold(r, self.params.setup()))
        self.g_rout.setText(f"<span style='color:{self._c.success}'>✓ Applied: the model now uses {r:.3f} Ω.</span>")

    # ── 5 your settings ───────────────────────────────────────────────
    def _screen_final(self, theme: str) -> QWidget:
        page, lv, rv = self._screen(
            4, "Check your settings, then save them.",
            "the work feed and the kerf compensation are what the project's G-code needs to come out the "
            "size you drew.")
        self.final_text = _body("", "GuideVerdict")
        lv.addWidget(self.final_text)
        self.save_note = _body("", "SaveNote")
        lv.addWidget(self.save_note)
        self.save_out = _body("", "GuideVerdict")
        lv.addWidget(self.save_out)
        lv.addStretch(1)
        more = QLabel("Optional")
        more.setObjectName("GuideHint")
        lv.addWidget(more)
        links = QHBoxLayout()
        b = QPushButton("Simulate the cut of my part")
        b.setProperty("role", "ghost")
        b.setToolTip("Opens the Cut simulation (Advanced mode) and runs it with these settings.")
        b.clicked.connect(self._simulate)
        links.addWidget(b)
        b = QPushButton("Advanced mode")
        b.setProperty("role", "ghost")
        b.clicked.connect(lambda: self.advanced_requested.emit("explore"))
        links.addWidget(b)
        links.addStretch(1)
        lv.addLayout(links)

        grid = QHBoxLayout()
        grid.setSpacing(10)
        self.r_drive = BigCard("Set your supply to")
        self.r_speed = BigCard("Work feed")
        self.r_offset = BigCard("Kerf compensation")
        for w in (self.r_drive, self.r_speed, self.r_offset):
            grid.addWidget(w, 1)
        rv.addLayout(grid)

        box = QFrame()
        box.setObjectName("SummaryCard")
        g = QGridLayout(box)
        g.setContentsMargins(16, 12, 16, 12)
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(8)
        t = QLabel("What will be saved")
        t.setObjectName("CardTitle")
        g.addWidget(t, 0, 0, 1, 2)
        self.sum_rows: dict[str, QLabel] = {}
        for r, (key, label) in enumerate((("supply", "Supply"), ("wire", "Wire"), ("foam", "Foam"),
                                          ("feed", "Work feed"), ("kerf", "Kerf compensation"),
                                          ("model", "Model")), start=1):
            k = QLabel(label)
            k.setObjectName("SummaryKey")
            val = _body("", "SummaryVal")
            g.addWidget(k, r, 0, Qt.AlignmentFlag.AlignTop)
            g.addWidget(val, r, 1)
            self.sum_rows[key] = val
        g.setColumnStretch(1, 1)
        rv.addWidget(box)
        rv.addStretch(1)
        return page

    def _simulate(self) -> None:
        if "v" in self._rec:
            self._push(self.params.set_probe_speed, self._rec["v"])
        self.simulate_requested.emit()

    def recommendation(self) -> dict:
        return dict(self._rec)

    def show_saved(self, html: str) -> None:
        self.save_out.setText(html)

    # ── sync with the parameter panel ─────────────────────────────────
    def _push(self, setter, value) -> None:  # type: ignore[no-untyped-def]
        """A guided control changed: write it into the shared parameters."""
        if not self._syncing:
            setter(value)

    def _pull(self) -> None:
        """Show the shared parameters in the guided controls."""
        pp = self.params
        self._syncing = True
        try:
            cv = pp.is_cv()
            self.g_mode.setCurrentIndex(0 if cv else 1)
            self.g_current.setVisible(not cv)
            self.g_voltage.setVisible(cv)
            self.g_ilim.setVisible(cv)
            self.g_ilim_lbl.setVisible(cv)
            self.g_voltage.set_maximum(pp.vmax.value())
            self.g_current.setValue(pp.current.value())
            self.g_voltage.setValue(pp.voltage.value())
            self.g_ilim.setValue(pp.ilim.value())
            for combo, src in ((self.g_wire, pp.wire), (self.g_foam, pp.foam)):
                name = src.currentText()
                if combo.findText(name) < 0:  # custom values from Advanced mode
                    combo.addItem(name)
                combo.setCurrentText(name)
            self.g_diam.setValue(pp.diam.value())
            self.g_speed.setValue(pp.speed.value())
        finally:
            self._syncing = False

    def set_measurement_count(self, n: int) -> None:
        self.measurement_count = n

    def refresh(self, st: PointState, s: CutSetup, v: float) -> None:
        """Fast read-outs for the current parameters (every edit; no scans here)."""
        self._st, self._s = st, s
        self._pull()
        reg = regime_of(st, s)
        c = self._c
        typ = typical(s)
        t_air, t_foam, kerf = float(st.t_air_c), float(st.t_foam_c), float(st.kerf_mm)
        r_cold = cold_resistance_ohm(s)

        # 1 · supply
        self.glow.set_temps(t_air, s.foam.iso_temp_c, s.wire.max_temp_c)
        self.g_span.setText(f"Wire between the arms: <b>{s.span_mm:.0f} mm</b> (from your machine) → "
                            f"<b>{r_cold:.2f} Ω</b> cold (resistivity × length ÷ area).")
        power = f"<b>{supply_text(s, st)}</b>"
        if t_air < s.foam.iso_temp_c:
            msg = (f"<span style='color:{REGIME['stall']}'>■</span> {power}: the wire only reaches "
                   f"{t_air:.0f} °C, too cold to melt {s.foam.name}. Raise the "
                   + ("current." if s.mode == "current" else "voltage."))
        elif t_air > s.wire.max_temp_c:
            msg = (f"<span style='color:{c.danger}'>■</span> {power}: {t_air:.0f} °C is above this wire's "
                   f"{s.wire.max_temp_c:.0f} °C limit — it may sag or break. Lower the drive.")
        elif t_air > HOT_LIMIT_C:
            msg = (f"<span style='color:#9B6BE0'>■</span> {power}: hot ({t_air:.0f} °C). It cuts, but the foam "
                   "may smoke and the slot gets wide. A bit less drive gives finer edges.")
        else:
            msg = (f"<span style='color:{REGIME['noncontact']}'>■</span> {power}: the wire reaches "
                   f"{t_air:.0f} °C in air, hot enough to melt the foam.")
        if bool(st.limited):
            msg += (f"<br><span style='color:{c.warning}'>■</span> The supply is on its "
                    + ("current limit." if s.mode == "voltage" else "maximum voltage."))
        self.supply_verdict.setText(msg)
        self.supply_typ.setText(
            f"Wire in air {typ.t_air} (doc §1) · for this wire: {typ.voltage}, {typ.current}, {typ.power} "
            "(model estimate for 160–400 °C in air)")

        # 2 · feed (the gauge and the suggestion come from the background scan)
        self.gauge.set_speed(v)
        if self.stack.currentIndex() == 1:
            self.g_incidence.show_state(st, s, v)
        title, why = VERDICT[reg]
        vc_txt = f" The fastest clean speed is about <b>{self._vc:.1f} mm/s</b>." if self._vc else ""
        self.feed_verdict.setText(f"<span style='color:{REGIME[reg]}'>■</span> At {v:.1f} mm/s: <b>{title}</b>. "
                                  f"{why}{vc_txt}")

        # 3 · result
        self.c_clean.set(title, why, REGIME[reg])
        self.c_kerf.set(f"{kerf:.2f} mm", f"The wire removes a slot this wide, so the part comes out "
                        f"{kerf / 2:.2f} mm smaller on each side.")
        self.c_kerf.set_typical(f"{typ.kerf} (1.4–6× the wire Ø, doc §4)", typ.tip["kerf"])
        self.c_temp.set(f"{t_foam:.0f} °C", f"{t_air - t_foam:.0f} °C cooler than in free air ({t_air:.0f} °C): "
                        "the foam takes heat from the wire as it melts.")
        self.c_temp.set_typical(f"{typ.t_foam} for a clean cut (doc §1, §4)", typ.tip["t_foam"])

        # 4 · calibrate
        cal = s.calib
        if abs(cal.eta - 1) < 1e-6 and abs(cal.kappa - 1) < 1e-6:
            self.calib_status.setText("Right now the Cut Lab uses <b>typical handbook values</b> for your wire and "
                                      "foam.")
        else:
            self.calib_status.setText(f"<span style='color:{c.success}'>✓</span> The model is <b>calibrated</b> to "
                                      f"your cuts (η = {cal.eta:.2f}, κ = {cal.kappa:.2f}"
                                      + (f", {self.measurement_count} measurements" if self.measurement_count else "")
                                      + "). It is saved and loaded again next time.")
        self.g_rexp.setText(f"{r_cold:.2f} Ω for {s.span_mm:.0f} mm of {s.wire.name}, Ø {s.diameter_mm:.2f} mm")

        # 5 · your settings
        self._final()

    def set_scan(self, vc: float, scan: dict, rec: dict, v: float) -> None:
        """Background results, first stage: contact speed, the feed scan and the recommendation."""
        self._vc, self._scan, self._rec = vc, scan, rec
        self.gauge.set_scan(scan, rec.get("v"))
        win = scan.get("clean")
        self.feed_typ.setText(
            f"Clean window at this drive (model estimate): {win[0]:.1f}–{win[1]:.1f} mm/s" if win else
            "No clean speed at this drive (model estimate): change the voltage/current in step 1.")
        self.suggest_btn.setEnabled("v" in rec)
        self.suggest_why.setText(self._criterion_text(rec))
        if self._st is not None and self._s is not None:
            self.refresh(self._st, self._s, v)

    def set_profile(self, profile: SpanProfile, v: float) -> None:
        self._profile = profile
        self.g_along.show_profile(profile, v)

    def _criterion_text(self, rec: dict) -> str:
        if "v" not in rec:
            return ""
        vc, v_clean = rec["vc"], rec["v_clean"]
        txt = (f"How the suggestion is chosen: {100 * SAFE_FRACTION:.0f} % of the fastest clean speed "
               f"({vc:.1f} → {v_clean:.1f} mm/s), ")
        if rec.get("limit") == "axis":
            txt += (f"capped at {rec['vmax_axis']:g} mm/s, your machine's slowest axis (Z on a stock Ender-3), so "
                    "the wire keeps one speed on steep and flat stretches and one kerf compensation fits all of "
                    "the part.")
        else:
            txt += "below your machine's axis limits."
        txt += (" The model is optimistic about the clean limit (the 2-D solve finds contact earlier), so check it "
                "with a test cut.")
        return txt

    def _final(self) -> None:
        s, st = self._s, self._st
        if s is None or st is None:
            return
        rec = self._rec
        c = self._c
        state = rec["state"]
        knob = "current" if s.mode == "current" else "voltage"
        drive = f"{s.voltage_v:.1f} V" if s.mode == "voltage" else f"{s.current_a:.2f} A"
        lim = (f"current limit {s.current_limit_a:.1f} A" if s.mode == "voltage"
               else f"up to {s.voltage_limit_v:.0f} V")
        self.r_drive.set(drive, f"{'CV' if s.mode == 'voltage' else 'CC'}, {lim}.")
        self.r_drive.set_typical(f"draws {float(st.current_a):.2f} A · {float(st.power_w):.1f} W")
        self.sum_rows["supply"].setText(f"{drive} ({'CV' if s.mode == 'voltage' else 'CC'}, {lim}) → "
                                        f"{supply_text(s, st).split('→ ', 1)[-1]}")
        self.sum_rows["wire"].setText(f"{s.wire.name}, Ø {s.diameter_mm:.2f} mm, {s.span_mm:.0f} mm between the "
                                      f"arms ({cold_resistance_ohm(s):.2f} Ω cold)")
        self.sum_rows["foam"].setText(s.foam.name)
        cal = s.calib
        calibrated = not (abs(cal.eta - 1) < 1e-6 and abs(cal.kappa - 1) < 1e-6)
        self.sum_rows["model"].setText(
            f"calibrated to your cuts (η = {cal.eta:.2f}, κ = {cal.kappa:.2f})" if calibrated
            else "typical handbook values (not calibrated — optional step 4)")
        self.save_note.setText(
            "<b>When you save:</b><br>• everything above is stored"
            + (f" in <i>{self.save_path_text}</i>" if self.save_path_text else "")
            + " and loaded again the next time you open the Cut Lab;<br>"
            "• the <b>work feed</b> and the <b>kerf compensation</b> go to the project, for its G-code;<br>"
            "• the Cut Lab closes and you are back in the project.")
        if state == "pending":
            self.save_btn.setEnabled(False)
            for w in (self.r_speed, self.r_offset):
                w.set("…", "computing")
                w.set_typical("")
            for k in ("feed", "kerf"):
                self.sum_rows[k].setText("…")
            self.final_text.setText("Working out the best speed…")
            return
        if state in ("stall", "contact"):
            self.save_btn.setEnabled(False)
            self.r_speed.set("—", "no clean speed at this drive", REGIME[state])
            self.r_offset.set("—", "")
            for w in (self.r_speed, self.r_offset):
                w.set_typical("")
            for k in ("feed", "kerf"):
                self.sum_rows[k].setText("—")
            self.final_text.setText(
                f"<span style='color:{REGIME[state]}'>■</span> At {drive} the wire is too cold to cut cleanly at any "
                f"speed. Go back to step 1 and raise the {knob}; then come back here to save.")
            return
        self.save_btn.setEnabled(True)
        v, kerf = rec["v"], rec["kerf"]
        why = (f"{100 * SAFE_FRACTION:.0f} % of the fastest clean speed ({rec['vc']:.1f} mm/s)"
               if rec.get("limit") != "axis" else f"your machine's slowest axis ({rec['vmax_axis']:g} mm/s)")
        self.r_speed.set(f"{v:.1f} mm/s", f"limited by {why}.", REGIME["noncontact"])
        self.r_speed.set_typical(f"clean up to ~{rec['vc']:.1f} mm/s (model estimate)")
        self.r_offset.set(f"{kerf / 2:.2f} mm", f"per side, outward (slot {kerf:.2f} mm wide).", c.accent)
        typ = typical(s)
        self.r_offset.set_typical(f"kerf {typ.kerf} (doc §4)", typ.tip["kerf"])
        self.sum_rows["feed"].setText(f"<b>{v:.1f} mm/s</b> — limited by {why}")
        self.sum_rows["kerf"].setText(f"<b>{kerf / 2:.2f} mm per side</b>, outward (the slot is {kerf:.2f} mm "
                                      "wide at the work feed)")
        warn = ""
        if state == "overmelt":
            warn = (f"<br><br><span style='color:{REGIME['overmelt']}'>■</span> Even at this speed the slot is wide "
                    f"({kerf:.2f} mm): the wire is hot for this feed. For finer edges lower the {knob} in step 1.")
        if bool(st.limited):
            warn += (f"<br><br><span style='color:{c.warning}'>■</span> The supply is on its "
                     + ("current limit." if s.mode == "voltage" else "maximum voltage."))
        self.final_text.setText(
            f"Set the supply to <b>{drive}</b>, cut at <b>{v:.1f} mm/s</b>, and make the part "
            f"<b>{kerf / 2:.2f} mm bigger on each side</b> to get the size you drew.{warn}")
