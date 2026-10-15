"""Reduced-order physics of a hot wire cutting foam.

The model answers, for a wire carrying a current (or driven by a voltage)
and moving through foam at a feed speed:

* how hot the wire gets, in air and inside the foam, along its whole span;
* how far ahead of the wire the foam retreats — the **melt radius** ``r_m``,
  i.e. the radius of incidence of the wire. The kerf is ``2·κ·r_m``;
* whether the wire cuts **without contact** (a gap of hot air/vapour between
  wire and foam) or **in contact** (the gap closes: the wire pushes the foam,
  drags and bows);
* how much the tensioned wire bows (lags) behind the commanded position.

Three coupled sub-models, all steady-state (quasi-static along a cut):

1. **Wire, electrical–thermal.** Per unit length,
   ``I²·R'(T) = q'_air(T) + q'_cut``, with ``R'`` growing linearly with
   temperature, natural convection from a thin horizontal cylinder
   (Churchill & Chu, 1975) plus radiation. Along the span the wire is a fin:
   ``kA·T'' + I²R'(T) − q'_loss(T, x) = 0`` with the ends held by the clamps,
   so the wire is colder near the arms and its in-foam part is colder than the
   part in air (the "barrelling" reported for hot-wire cuts).
2. **Melt front.** Heat crosses the gap between the wire and the foam ahead
   of it by conduction through the hot gas (half an annulus) plus radiation,
   and must equal the energy needed to remove a swath ``2·r_m`` wide at the
   feed speed: ``q'_front(r_m, T) = e_v · v · 2·r_m`` with
   ``e_v = ρ·(c·(T_iso − T∞) + L_eff)``. ``q'_front`` falls with ``r_m`` and
   the demand rises with it, so there is one solution. Slow or hot → large
   gap (wide kerf); fast or cold → the gap shrinks to the contact threshold.
3. **Bow (lag).** Past the contact speed the wire pushes the foam with a
   force per length ``F' = c_drag·(v − v_c)``. The wire is a string under the
   spring tension, so ``T_N·δ'' = −F'(x)`` gives its deflection along the span.

The model follows the thermal view of the literature (kerf = the foam's
collapse isotherm around the wire; current and feed are the dominant
parameters; a mass-specific effective heat input ties foam and cutting
conditions), reduced to closed forms that are fast enough for an interactive
UI. Material values below are typical handbook values; the calibration
factors (``eta``, ``kappa``, ``L_eff``, ``c_drag``) are meant to be fitted
to the user's own test cuts (see :mod:`core.calibration`).

Units: SI inside (m, K, W, N); the dataclasses take the units a user thinks
in (mm, °C, A, V) and say so in their field names.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

SIGMA = 5.670374419e-8  # Stefan–Boltzmann, W/m²K⁴
G = 9.81
K0 = 273.15


# ── materials ─────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class WireMaterial:
    name: str
    resistivity_ohm_m: float  # at 20 °C
    alpha_per_k: float        # linear temperature coefficient of resistance
    conductivity_w_mk: float
    emissivity: float
    density_kg_m3: float
    specific_heat_j_kgk: float
    max_temp_c: float         # oxidation/strength limit, for warnings


# Typical handbook values (vary with alloy, temper and oxidation): calibrate.
WIRE_MATERIALS: dict[str, WireMaterial] = {
    "Nichrome 80/20": WireMaterial("Nichrome 80/20", 1.09e-6, 1.0e-4, 11.3, 0.70, 8400, 450, 1150),
    "Kanthal A1": WireMaterial("Kanthal A1", 1.45e-6, 3.0e-5, 11.0, 0.70, 7100, 460, 1400),
    "Stainless 304": WireMaterial("Stainless 304", 0.72e-6, 9.0e-4, 16.0, 0.45, 7900, 500, 870),
    "Steel (guitar string)": WireMaterial("Steel (guitar string)", 0.20e-6, 4.0e-3, 45.0, 0.35, 7850, 470, 550),
}


@dataclass(frozen=True, slots=True)
class Foam:
    name: str
    density_kg_m3: float
    conductivity_w_mk: float
    specific_heat_j_kgk: float
    iso_temp_c: float        # collapse isotherm: the foam retreats where it gets this hot
    latent_j_kg: float       # effective extra energy to remove it (melt + partial ablation)
    compressive_kpa: float   # for reference / drag scale


# Polystyrene: Tg ≈ 100 °C, melts ≈ 240 °C; EPS cells collapse in between.
FOAMS: dict[str, Foam] = {
    "EPS 15 kg/m³": Foam("EPS 15 kg/m³", 15, 0.037, 1300, 150, 100e3, 70),
    "EPS 20 kg/m³": Foam("EPS 20 kg/m³", 20, 0.035, 1300, 150, 100e3, 100),
    "EPS 30 kg/m³": Foam("EPS 30 kg/m³", 30, 0.034, 1300, 150, 100e3, 150),
    "XPS 35 kg/m³": Foam("XPS 35 kg/m³", 35, 0.032, 1300, 160, 100e3, 250),
}


@dataclass(frozen=True, slots=True)
class Calibration:
    """Factors that close the gap between this simple model and a real machine."""

    eta: float = 1.0           # multiplies the wire→foam heat transfer
    kappa: float = 1.0         # kerf / (2·r_m): lateral spread of the melt beyond the front radius
    contact_gap_mm: float = 0.02  # gap under which the wire is considered touching the foam
    c_drag_n_m_per_mm_s: float = 0.5  # bow force per metre of foam per mm/s over the contact speed


@dataclass(frozen=True, slots=True)
class CutSetup:
    """Everything the physics needs, in user units."""

    wire: WireMaterial = field(default_factory=lambda: WIRE_MATERIALS["Nichrome 80/20"])
    diameter_mm: float = 0.30
    span_mm: float = 216.0          # clamp to clamp
    tension_n: float = 8.0
    foam: Foam = field(default_factory=lambda: FOAMS["EPS 20 kg/m³"])
    block_width_mm: float = 150.0   # foam along the wire
    block_offset_mm: float = 0.0    # block centre relative to the span centre
    mode: str = "current"           # "current" (constant-current supply) or "voltage"
    current_a: float = 1.2
    voltage_v: float = 4.0
    lead_resistance_ohm: float = 0.10
    current_limit_a: float = 5.0    # CV: the supply's current limit (it drops into CC there)
    voltage_limit_v: float = 30.0   # CC: the supply's top voltage (bench supplies top out near 30 V)
    ambient_c: float = 22.0
    clamp_temp_c: float | None = None  # None: clamps at ambient
    calib: Calibration = field(default_factory=Calibration)

    def with_(self, **kw) -> CutSetup:  # type: ignore[no-untyped-def]
        return replace(self, **kw)


# ── air & elementary heat transfer (vectorised) ───────────────────────
def air_conductivity(t_k):  # type: ignore[no-untyped-def]
    return 0.0241 * (np.asarray(t_k) / K0) ** 0.81


def air_viscosity(t_k):  # type: ignore[no-untyped-def]
    """Kinematic viscosity of air at 1 atm, m²/s."""
    return 1.33e-5 * (np.asarray(t_k) / K0) ** 1.72


def h_natural(t_wire_k, t_inf_k, d_m):  # type: ignore[no-untyped-def]
    """Natural-convection coefficient of a thin horizontal cylinder (Churchill & Chu)."""
    t_wire_k = np.maximum(t_wire_k, t_inf_k + 1e-3)
    tf = 0.5 * (t_wire_k + t_inf_k)
    pr = 0.70
    nu = air_viscosity(tf)
    ra = G * (1.0 / tf) * (t_wire_k - t_inf_k) * d_m**3 * pr / nu**2
    nusselt = (0.60 + 0.387 * ra ** (1 / 6) / (1 + (0.559 / pr) ** (9 / 16)) ** (8 / 27)) ** 2
    return nusselt * air_conductivity(tf) / d_m


def q_air(t_k, s: CutSetup):  # type: ignore[no-untyped-def]
    """Heat lost per metre of wire in still air (convection + radiation), W/m."""
    d = s.diameter_mm * 1e-3
    tinf = s.ambient_c + K0
    t = np.maximum(t_k, tinf)
    return np.pi * d * (h_natural(t, tinf, d) * (t - tinf) + s.wire.emissivity * SIGMA * (t**4 - tinf**4))


def resistance_per_m(t_k, s: CutSetup):  # type: ignore[no-untyped-def]
    area = np.pi * (s.diameter_mm * 1e-3) ** 2 / 4
    return s.wire.resistivity_ohm_m * (1 + s.wire.alpha_per_k * (np.asarray(t_k) - (20 + K0))) / area


def removal_energy(s: CutSetup) -> float:
    """Energy to remove one m³ of foam, J/m³ (heat to the isotherm + effective latent)."""
    f = s.foam
    return f.density_kg_m3 * (f.specific_heat_j_kgk * max(1.0, f.iso_temp_c - s.ambient_c) + f.latent_j_kg)


def _front_coeffs(t_k, s: CutSetup):  # type: ignore[no-untyped-def]
    """``q_front = a / ln(r_m/r_w) + b``: the two terms that do not depend on ``r_m``."""
    rw = s.diameter_mm * 1e-3 / 2
    tiso = s.foam.iso_temp_c + K0
    t_k = np.asarray(t_k, float)
    dt = np.maximum(t_k - tiso, 0.0)
    kg = air_conductivity(0.5 * (t_k + tiso))
    a = s.calib.eta * np.pi * kg * dt
    b = s.calib.eta * s.wire.emissivity * SIGMA * np.pi * rw * np.maximum(t_k**4 - tiso**4, 0.0)
    return a, b


def q_front(r_m, t_k, s: CutSetup):  # type: ignore[no-untyped-def]
    """Heat delivered by the wire to the melt front at radius ``r_m`` (m), W/m."""
    rw = s.diameter_mm * 1e-3 / 2
    a, b = _front_coeffs(t_k, s)
    return a / np.log(np.maximum(r_m / rw, 1 + 1e-9)) + b


R_CAP_MM = 8.0  # melt radius ceiling: beyond this the steady model is meaningless (dwell)
GAP_MIN_M = 1e-9  # melt radius floor: r_w + this
MELT_ITERS = 22   # bisection on log(gap) (range ≈ 16 → 4e-6), then one false-position step


def melt_radius(t_k, v_mm_s, s: CutSetup):  # type: ignore[no-untyped-def]
    """Steady melt-front radius (m) for wire temperature ``t_k`` and feed ``v``.

    Vectorised bisection on log(gap) (the temperature-only terms of
    ``q_front`` are computed once). Where the wire is not above the foam's
    isotherm it cannot cut: returns ``r_w`` (and the caller flags a stall).
    """
    t_k, v = np.broadcast_arrays(np.asarray(t_k, float), np.asarray(v_mm_s, float))
    rw = s.diameter_mm * 1e-3 / 2
    a, b = _front_coeffs(t_k, s)
    c = 2 * removal_energy(s) * np.maximum(v, 1e-6) * 1e-3
    floor = np.log(1 + 1e-9)

    def surplus(log_gap):  # type: ignore[no-untyped-def]
        gap = np.exp(log_gap)
        return a / np.maximum(np.log1p(gap / rw), floor) + b - c * (rw + gap)

    lo = np.full(t_k.shape, np.log(GAP_MIN_M))
    hi = np.full(t_k.shape, np.log(R_CAP_MM * 1e-3))
    f_lo, f_hi = surplus(lo), surplus(hi)
    for _ in range(MELT_ITERS):
        mid = 0.5 * (lo + hi)
        f = surplus(mid)
        up = f > 0
        lo, f_lo = np.where(up, mid, lo), np.where(up, f, f_lo)
        hi, f_hi = np.where(up, hi, mid), np.where(up, f_hi, f)
    # one false-position step inside the final bracket (where it brackets a root)
    brk = (f_lo > 0) & (f_hi <= 0)
    w = np.where(brk, f_lo / np.where(brk, f_lo - f_hi, 1.0), 0.5)
    r = rw + np.exp(lo + np.clip(w, 0.0, 1.0) * (hi - lo))
    return np.where(t_k > s.foam.iso_temp_c + K0, r, rw)


# ── the wire at one point (0-D) ───────────────────────────────────────
@dataclass(frozen=True, slots=True)
class PointState:
    """Wire state far from the clamps, vectorised over whatever was broadcast."""

    t_air_c: np.ndarray       # wire temperature in free air
    t_foam_c: np.ndarray      # wire temperature inside the foam, cutting
    r_m_mm: np.ndarray        # melt radius (radius of incidence)
    kerf_mm: np.ndarray
    gap_mm: np.ndarray        # r_m − r_wire
    contact: np.ndarray       # bool
    stall: np.ndarray         # bool: the wire is not hot enough to cut
    q_cut_w_m: np.ndarray     # heat into the foam per metre of wire
    current_a: np.ndarray
    power_w: np.ndarray       # electrical power of the whole wire
    voltage_v: np.ndarray     # at the supply terminals (wire + leads)
    limited: np.ndarray       # bool: the supply sits on its other limit (CV: current limit; CC: voltage limit)


T_SOLVE_ITERS = 34  # bisection on the wire temperature: ~1 500 K bracket / 2^34 ≈ 1e-7 K


def _solve_uniform(i_a, v, s: CutSetup, in_foam: bool):  # type: ignore[no-untyped-def]
    """Uniform wire temperature (K) for current ``i_a``; vectorised bisection.

    In the foam, ``I²R'(T) = q_front(r_m(T), T) + ½·q_air(T)`` is solved
    without nesting the melt-radius solve: the heat left for the front,
    ``D = I²R' − ½·q_air``, fixes the radius the foam *demands*,
    ``r_D = D / (2·e_v·v)``; the wire is still too cold exactly when the front
    would take less than ``D`` at that radius (``q_front(r_D) < D``), because
    the front's surplus ``q_front(r) − 2·e_v·v·r`` falls monotonically with r.
    """
    i_a, v = np.broadcast_arrays(np.asarray(i_a, float), np.asarray(v, float))
    tinf = s.ambient_c + K0
    lo = np.full(i_a.shape, tinf)
    hi = np.full(i_a.shape, s.wire.max_temp_c + 400 + K0)
    i2 = i_a**2
    rw = s.diameter_mm * 1e-3 / 2
    c = 2 * removal_energy(s) * np.maximum(v, 1e-6) * 1e-3
    r_lo, r_hi = rw + GAP_MIN_M, rw + R_CAP_MM * 1e-3
    for _ in range(T_SOLVE_ITERS):
        mid = 0.5 * (lo + hi)
        gen = i2 * resistance_per_m(mid, s)
        if in_foam:
            d_front = gen - 0.5 * q_air(mid, s)
            r_d = np.clip(d_front / c, r_lo, r_hi)
            heats = d_front > q_front(r_d, mid, s)
        else:
            heats = gen > q_air(mid, s)
        lo = np.where(heats, mid, lo)
        hi = np.where(heats, hi, mid)
    return 0.5 * (lo + hi)


def _current_state(i, v, s: CutSetup):  # type: ignore[no-untyped-def]
    """(T_air, T_foam, R_total incl. leads) at current ``i`` (arrays broadcast with ``v``)."""
    span = s.span_mm * 1e-3
    b = min(s.block_width_mm, s.span_mm) * 1e-3
    t_air = _solve_uniform(i, v, s, False)
    t_foam = _solve_uniform(i, v, s, True)
    r_tot = resistance_per_m(t_air, s) * (span - b) + resistance_per_m(t_foam, s) * b + s.lead_resistance_ohm
    return t_air, t_foam, r_tot


VOLT_ITERS = 40    # hard cap: the voltage solve can never hang
VOLT_RTOL = 1e-7


def _voltage_state(u, v, s: CutSetup):  # type: ignore[no-untyped-def]
    """Current drawn at supply voltage ``u``: the root of ``I·R_tot(I) − U``.

    ``I·R_tot(I)`` grows monotonically with ``I`` (R rises with temperature),
    so the root sits in the bracket [U / R_hot, U / R_cold], R_hot being the
    resistance at the solver's temperature ceiling. Illinois (safeguarded false
    position): typically 4–8 steps, never more than ``VOLT_ITERS``.
    Returns (I, T_air, T_foam, R_total).
    """
    u, v = np.broadcast_arrays(np.asarray(u, float), np.asarray(v, float))
    u = np.maximum(u, 0.0)
    span = s.span_mm * 1e-3
    r_cold = float(resistance_per_m(s.ambient_c + K0, s)) * span + s.lead_resistance_ohm
    r_hot = float(resistance_per_m(s.wire.max_temp_c + 400 + K0, s)) * span + s.lead_resistance_ohm
    a = u / max(r_hot, r_cold)
    b = u / max(min(r_hot, r_cold), 1e-9)
    fa = a * _current_state(a, v, s)[2] - u   # ≤ 0
    fb = b * _current_state(b, v, s)[2] - u   # ≥ 0
    side = np.zeros(u.shape)
    i = 0.5 * (a + b)
    for _ in range(VOLT_ITERS):
        if np.all(b - a <= VOLT_RTOL * np.maximum(b, 1e-12)):
            break
        den = fb - fa
        safe = np.abs(den) > 1e-300
        i = np.where(safe, b - fb * (b - a) / np.where(safe, den, 1.0), 0.5 * (a + b))
        i = np.where((i > a) & (i < b), i, 0.5 * (a + b))
        f = i * _current_state(i, v, s)[2] - u
        if np.all(np.abs(f) <= VOLT_RTOL * np.maximum(u, 1e-12)):
            break
        neg = f < 0
        # Illinois: halve the stale end's value when the same end survives twice
        fb = np.where(neg & (side == -1), 0.5 * fb, fb)
        fa = np.where(~neg & (side == 1), 0.5 * fa, fa)
        a, fa = np.where(neg, i, a), np.where(neg, f, fa)
        b, fb = np.where(neg, b, i), np.where(neg, fb, f)
        side = np.where(neg, -1, 1)
    t_air, t_foam, r_tot = _current_state(i, v, s)
    return i, t_air, t_foam, r_tot


def point_state(s: CutSetup, v_mm_s, *, current_a=None, voltage_v=None,  # type: ignore[no-untyped-def]
                limits: bool = True) -> PointState:
    """Steady state at mid-block, ignoring end conduction (fast; vectorised).

    ``current_a`` / ``voltage_v`` override the setup (arrays broadcast with
    ``v_mm_s``), so a whole operating map is one call. With ``limits`` the
    supply behaves like a bench supply: in CV it never gives more than
    ``s.current_limit_a`` (it drops into CC there), in CC never more than
    ``s.voltage_limit_v`` (it drops into CV).
    """
    mode = "voltage" if voltage_v is not None else ("current" if current_a is not None else s.mode)
    v = np.asarray(v_mm_s, float)
    if mode == "current":
        i = np.asarray(s.current_a if current_a is None else current_a, float)
        i, v = np.broadcast_arrays(i, v)
        t_air, t_foam, r_tot = _current_state(i, v, s)
        limited = (i * r_tot > s.voltage_limit_v) if limits else np.zeros(i.shape, bool)
        if np.any(limited):
            i2, ta2, tf2, rt2 = _voltage_state(np.full(i.shape, s.voltage_limit_v), v, s)
            i, t_air, t_foam, r_tot = (np.where(limited, x2, x1) for x1, x2 in
                                       ((i, i2), (t_air, ta2), (t_foam, tf2), (r_tot, rt2)))
    else:
        u = np.asarray(s.voltage_v if voltage_v is None else voltage_v, float)
        u, v = np.broadcast_arrays(u, v)
        i, t_air, t_foam, r_tot = _voltage_state(u, v, s)
        limited = (i > s.current_limit_a) if limits else np.zeros(i.shape, bool)
        if np.any(limited):
            i2 = np.full(i.shape, s.current_limit_a)
            ta2, tf2, rt2 = _current_state(i2, v, s)
            i, t_air, t_foam, r_tot = (np.where(limited, x2, x1) for x1, x2 in
                                       ((i, i2), (t_air, ta2), (t_foam, tf2), (r_tot, rt2)))
    r = melt_radius(t_foam, v, s)
    rw = s.diameter_mm * 1e-3 / 2
    stall = t_foam <= s.foam.iso_temp_c + K0 + 1.0
    gap = (r - rw) * 1e3
    q = np.where(stall, 0.0, q_front(r, t_foam, s))
    power = i**2 * (r_tot - s.lead_resistance_ohm)
    return PointState(
        t_air_c=t_air - K0, t_foam_c=t_foam - K0, r_m_mm=r * 1e3, kerf_mm=2 * s.calib.kappa * r * 1e3,
        gap_mm=gap, contact=(gap < s.calib.contact_gap_mm) | stall, stall=stall, q_cut_w_m=q,
        current_a=i, power_w=power, voltage_v=i * r_tot, limited=np.asarray(limited),
    )


def cold_resistance_ohm(s: CutSetup) -> float:
    """Wire resistance between the clamps at room temperature, ρ(T∞)·L / A (leads excluded)."""
    return float(resistance_per_m(s.ambient_c + K0, s)) * s.span_mm * 1e-3


def current_for_air_temp(s: CutSetup, t_c):  # type: ignore[no-untyped-def]
    """Current that holds the wire at ``t_c`` in still air (closed form of I²·R'(T) = q_air(T))."""
    tk = np.asarray(t_c, float) + K0
    return np.sqrt(q_air(tk, s) / resistance_per_m(tk, s))


def contact_speed(s: CutSetup, *, current_a=None, voltage_v=None, v_max: float = 500.0) -> float:  # type: ignore[no-untyped-def]
    """Fastest feed (mm/s) that still cuts without touching the foam (0 if it never does).

    A log-spaced scan, then two vectorised refinements of the bracket (to
    about 0.01 %): three model calls in all, in either supply mode.
    """
    vs = np.geomspace(0.02, v_max, 120)
    ok = ~np.asarray(point_state(s, vs, current_a=current_a, voltage_v=voltage_v).contact)
    if not ok.any():
        return 0.0
    if ok.all():
        return v_max
    for _ in range(2):
        k = int(np.argmin(ok))  # first contact speed
        if k == 0:
            return float(vs[0])
        vs = np.geomspace(vs[k - 1], vs[k], 24)
        ok = ~np.asarray(point_state(s, vs, current_a=current_a, voltage_v=voltage_v).contact)
        ok[0] = True  # the bracket's low end was clean
        if ok.all():
            return float(vs[-1])
    return float(vs[int(np.argmin(ok)) - 1])


def wire_time_constant_s(s: CutSetup, t_c: float) -> float:
    """How fast the wire's temperature follows a change (in air), seconds."""
    d = s.diameter_mm * 1e-3
    tk = t_c + K0
    tinf = s.ambient_c + K0
    h_eff = float(q_air(tk, s)) / (np.pi * d * max(1.0, tk - tinf))
    return s.wire.density_kg_m3 * s.wire.specific_heat_j_kgk * d / (4 * h_eff)


# ── the whole span (1-D fin) ──────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class SpanProfile:
    """Wire along its span for a batch of feed speeds. Arrays are [speed, node]."""

    x_mm: np.ndarray          # node positions, 0 = span centre
    in_foam: np.ndarray       # bool per node
    speeds: np.ndarray        # mm/s
    t_c: np.ndarray
    r_m_mm: np.ndarray
    kerf_mm: np.ndarray
    gap_mm: np.ndarray
    stall: np.ndarray
    contact: np.ndarray
    t_air_ref_c: np.ndarray   # [speed]: same wire entirely in air (entry state)
    r_entry_mm: np.ndarray    # [speed, node]: melt radius of a wire just arrived from air
    v_contact: np.ndarray     # [node]: contact speed at each node
    bow_mm: np.ndarray        # [speed, node]: deflection behind the commanded position
    current_a: np.ndarray     # [speed]
    power_w: np.ndarray       # [speed]

    def at(self, v: float, x_mm: float) -> dict[str, float]:
        """Interpolated state at feed ``v`` and wire position ``x`` (for read-outs)."""
        lv = np.log(np.clip(v, self.speeds[0], self.speeds[-1]))
        ls = np.log(self.speeds)
        k = int(np.clip(np.searchsorted(ls, lv) - 1, 0, len(ls) - 2))
        f = (lv - ls[k]) / (ls[k + 1] - ls[k])
        j = int(np.clip(np.searchsorted(self.x_mm, x_mm), 0, len(self.x_mm) - 1))
        out = {}
        for name in ("t_c", "r_m_mm", "kerf_mm", "gap_mm", "bow_mm", "r_entry_mm"):
            a = getattr(self, name)
            out[name] = float(a[k, j] * (1 - f) + a[k + 1, j] * f)
        out["contact"] = bool(self.contact[k if f < 0.5 else k + 1, j])
        out["stall"] = bool(self.stall[k, j] or self.stall[k + 1, j])
        return out


def _thomas(a, b, c, d):  # type: ignore[no-untyped-def]
    """Batched tridiagonal solve along the last axis (a: sub, b: diag, c: super)."""
    n = b.shape[-1]
    cp = np.empty_like(b)
    dp = np.empty_like(d)
    cp[..., 0] = c[..., 0] / b[..., 0]
    dp[..., 0] = d[..., 0] / b[..., 0]
    for i in range(1, n):
        m = b[..., i] - a[..., i] * cp[..., i - 1]
        cp[..., i] = c[..., i] / m
        dp[..., i] = (d[..., i] - a[..., i] * dp[..., i - 1]) / m
    x = np.empty_like(d)
    x[..., -1] = dp[..., -1]
    for i in range(n - 2, -1, -1):
        x[..., i] = dp[..., i] - cp[..., i] * x[..., i + 1]
    return x


def span_profile(s: CutSetup, speeds=None, nodes: int = 241) -> SpanProfile:  # type: ignore[no-untyped-def]
    """Temperature, melt radius and bow along the wire for each feed speed.

    Newton iteration on the fin equation (losses and Joule heat linearised,
    the slope floored so the tridiagonal system stays dominant), batched over
    the speeds.
    """
    speeds = np.geomspace(0.05, 200.0, 44) if speeds is None else np.asarray(speeds, float)
    span = s.span_mm * 1e-3
    x = np.linspace(-span / 2, span / 2, nodes)
    dx = x[1] - x[0]
    b = min(s.block_width_mm, s.span_mm - 2) * 1e-3
    xc = s.block_offset_mm * 1e-3
    in_foam = np.abs(x - xc) <= b / 2
    d = s.diameter_mm * 1e-3
    ka = s.wire.conductivity_w_mk * np.pi * d**2 / 4
    tinf = s.ambient_c + K0
    tclamp = (s.ambient_c if s.clamp_temp_c is None else s.clamp_temp_c) + K0
    nv = len(speeds)

    def loss_of(t, vb, foam_mask):  # type: ignore[no-untyped-def]
        loss = q_air(t, s)
        if foam_mask.any():  # the melt front only where the wire is in the foam
            tf, vf = t[:, foam_mask], vb[:, foam_mask]
            loss[:, foam_mask] = q_front(melt_radius(tf, vf, s), tf, s) + 0.5 * loss[:, foam_mask]
        return loss

    def solve(i_a, foam_mask, u_rows):  # type: ignore[no-untyped-def]
        """Newton on the fin equation. Rows with a finite ``u_rows`` are voltage-driven (the current
        follows the wire's resistance); the others hold ``i_a``."""
        cv = np.isfinite(u_rows)
        t_a = _solve_uniform(i_a, speeds, s, False)
        t_f = _solve_uniform(i_a, speeds, s, True) if foam_mask.any() else t_a
        t = np.where(foam_mask[None, :], t_f[:, None], t_a[:, None])
        vb = np.broadcast_to(speeds[:, None], (nv, nodes))
        r0 = resistance_per_m(20 + K0, s)
        for _ in range(40):
            if cv.any():
                r_tot = np.trapezoid(resistance_per_m(t, s), x, axis=1) + s.lead_resistance_ohm
                i_a = np.where(cv, 0.5 * i_a + 0.5 * np.where(cv, u_rows, 0.0) / r_tot, i_a)
            i2 = (i_a**2)[:, None]
            gen = i2 * resistance_per_m(t, s)
            dgen = i2 * r0 * s.wire.alpha_per_k
            loss = loss_of(t, vb, foam_mask)
            dloss = (loss_of(t + 0.5, vb, foam_mask) - loss) / 0.5
            slope = np.maximum(dloss - dgen, 1e-4)  # >0: stable branch, keeps the system dominant
            sub = np.full((nv, nodes), ka / dx**2)
            sup = sub.copy()
            diag = -2 * ka / dx**2 - slope
            rhs = -(gen - loss) - slope * t
            for j in (0, nodes - 1):  # Dirichlet ends at the clamps
                sub[:, j] = 0
                sup[:, j] = 0
                diag[:, j] = 1
                rhs[:, j] = tclamp
            t_new = np.clip(_thomas(sub, diag, sup, rhs), tinf, s.wire.max_temp_c + 600 + K0)
            step = np.clip(t_new - t, -80, 80)
            t = t + step
            if np.max(np.abs(step)) < 0.02:
                break
        return t, i_a

    # the supply: the mid-block model says which rows sit on the other limit (bench-supply behaviour)
    pst = point_state(s, speeds)
    lim = np.asarray(pst.limited, bool)
    i_seed = np.asarray(pst.current_a, float)
    if s.mode == "current":
        u_rows = np.where(lim, s.voltage_limit_v, np.nan)
        i0 = np.where(lim, i_seed, s.current_a)
    else:
        u_rows = np.where(lim, np.nan, s.voltage_v)
        i0 = np.where(lim, s.current_limit_a, i_seed)
    t, i_a = solve(i0, in_foam, u_rows)
    t_air, _ = solve(i0, np.zeros(nodes, bool), u_rows)
    vb = np.broadcast_to(speeds[:, None], (nv, nodes))
    r = melt_radius(t, vb, s)
    rw = d / 2
    stall = (t <= s.foam.iso_temp_c + K0 + 1.0) & in_foam[None, :]
    gap = (r - rw) * 1e3
    contact = ((gap < s.calib.contact_gap_mm) | stall) & in_foam[None, :]
    r_entry = melt_radius(t_air, vb, s)

    # contact speed per node: first speed whose gap drops under the threshold
    v_c = np.full(nodes, speeds[-1])
    for j in np.nonzero(in_foam)[0]:
        bad = np.nonzero(gap[:, j] < s.calib.contact_gap_mm)[0]
        if len(bad):
            v_c[j] = speeds[bad[0]] if bad[0] == 0 else np.sqrt(speeds[bad[0]] * speeds[bad[0] - 1])
    # bow: T·δ'' = −F'(x), δ = 0 at the clamps
    force = np.where(in_foam[None, :], s.calib.c_drag_n_m_per_mm_s * np.maximum(0.0, speeds[:, None] - v_c[None, :]), 0.0)
    sub = np.full((nv, nodes), 1 / dx**2)
    sup = sub.copy()
    diag = np.full((nv, nodes), -2 / dx**2)
    rhs = -force / max(s.tension_n, 1e-3)
    for j in (0, nodes - 1):
        sub[:, j] = sup[:, j] = 0
        diag[:, j] = 1
        rhs[:, j] = 0
    bow = _thomas(sub, diag, sup, rhs)

    power = (i_a**2) * np.trapezoid(resistance_per_m(t, s), x, axis=1)
    return SpanProfile(
        x_mm=x * 1e3, in_foam=in_foam, speeds=speeds, t_c=t - K0, r_m_mm=np.where(in_foam, r, rw) * 1e3,
        kerf_mm=np.where(in_foam, 2 * s.calib.kappa * r, d) * 1e3, gap_mm=np.where(in_foam, gap, 0.0),
        stall=stall, contact=contact, t_air_ref_c=t_air[:, nodes // 2] - K0, r_entry_mm=r_entry * 1e3,
        v_contact=v_c, bow_mm=bow * 1e3, current_a=i_a, power_w=power,
    )


# ── operating map ─────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class OperatingMap:
    drive: np.ndarray   # current (A) or voltage (V) axis
    speeds: np.ndarray  # mm/s axis
    mode: str
    kerf_mm: np.ndarray  # [drive, speed]
    t_foam_c: np.ndarray
    t_air_c: np.ndarray
    contact: np.ndarray
    stall: np.ndarray


def operating_map(s: CutSetup, drive=None, speeds=None) -> OperatingMap:  # type: ignore[no-untyped-def]
    """Kerf and regime over a grid of drive (A or V) × feed speed.

    By default the drive axis runs from 0.25× to 2.5× the setting (in CV, no
    higher than the supply's ``voltage_limit_v``). In CV the map is
    computed on a current grid (one vectorised CC call) and read back at each
    voltage through the monotone U(I) of each feed column, so it costs about
    as much as a CC map; the current limit is applied on the way.
    """
    if drive is None:
        if s.mode == "current":
            drive = np.linspace(max(0.05, s.current_a * 0.25), s.current_a * 2.5, 70)
        else:
            top = min(s.voltage_v * 2.5, max(s.voltage_limit_v, s.voltage_v))
            drive = np.linspace(max(0.1, s.voltage_v * 0.25), top, 70)
    drive = np.asarray(drive, float)
    speeds = np.geomspace(0.2, 60.0, 80) if speeds is None else np.asarray(speeds, float)
    if s.mode == "current":
        dd, vv = np.meshgrid(drive, speeds, indexing="ij")
        st = point_state(s, vv, current_a=dd)
        return OperatingMap(drive=drive, speeds=speeds, mode=s.mode, kerf_mm=st.kerf_mm,
                            t_foam_c=st.t_foam_c, t_air_c=st.t_air_c, contact=st.contact, stall=st.stall)
    # CV: a CC grid wide enough for every voltage, then U(I) → I per column
    span = s.span_mm * 1e-3
    r_cold = float(resistance_per_m(s.ambient_c + K0, s)) * span + s.lead_resistance_ohm
    r_hot = float(resistance_per_m(s.wire.max_temp_c + 400 + K0, s)) * span + s.lead_resistance_ohm
    i_lo = max(1e-3, float(drive.min()) / max(r_hot, r_cold))
    i_hi = max(i_lo * 1.01, float(drive.max()) / max(min(r_hot, r_cold), 1e-9))
    i_hi = min(i_hi, max(s.current_limit_a, i_lo * 1.01))
    ig = np.linspace(i_lo, i_hi, 140)
    gi, gv = np.meshgrid(ig, speeds, indexing="ij")
    g = point_state(s, gv, current_a=gi, limits=False)
    u_grid = np.asarray(g.voltage_v)  # [current, speed], increasing along the current axis
    out = {k: np.empty((len(drive), len(speeds))) for k in ("t_air", "t_foam", "r_m")}
    for j in range(len(speeds)):
        uj = np.maximum.accumulate(u_grid[:, j])  # guard tiny non-monotone wiggles
        i_at = np.interp(drive, uj, ig)
        i_at = np.minimum(i_at, s.current_limit_a)
        out["t_air"][:, j] = np.interp(i_at, ig, np.asarray(g.t_air_c)[:, j])
        out["t_foam"][:, j] = np.interp(i_at, ig, np.asarray(g.t_foam_c)[:, j])
        out["r_m"][:, j] = np.interp(i_at, ig, np.asarray(g.r_m_mm)[:, j])
    rw = s.diameter_mm / 2
    stall = out["t_foam"] <= s.foam.iso_temp_c + 1.0
    contact = ((out["r_m"] - rw) < s.calib.contact_gap_mm) | stall
    return OperatingMap(drive=drive, speeds=speeds, mode=s.mode, kerf_mm=2 * s.calib.kappa * out["r_m"],
                        t_foam_c=out["t_foam"], t_air_c=out["t_air"], contact=contact, stall=stall)
