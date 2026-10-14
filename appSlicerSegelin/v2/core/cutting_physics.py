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


def q_front(r_m, t_k, s: CutSetup):  # type: ignore[no-untyped-def]
    """Heat delivered by the wire to the melt front at radius ``r_m`` (m), W/m."""
    rw = s.diameter_mm * 1e-3 / 2
    tiso = s.foam.iso_temp_c + K0
    dt = np.maximum(np.asarray(t_k) - tiso, 0.0)
    kg = air_conductivity(0.5 * (t_k + tiso))
    cond = np.pi * kg * dt / np.log(np.maximum(r_m / rw, 1 + 1e-9))
    rad = s.wire.emissivity * SIGMA * np.pi * rw * np.maximum(np.asarray(t_k) ** 4 - tiso**4, 0.0)
    return s.calib.eta * (cond + rad)


R_CAP_MM = 8.0  # melt radius ceiling: beyond this the steady model is meaningless (dwell)


def melt_radius(t_k, v_mm_s, s: CutSetup):  # type: ignore[no-untyped-def]
    """Steady melt-front radius (m) for wire temperature ``t_k`` and feed ``v``.

    Vectorised bisection on log(gap). Where the wire is not above the foam's
    isotherm it cannot cut: returns ``r_w`` (and the caller flags a stall).
    """
    t_k, v = np.broadcast_arrays(np.asarray(t_k, float), np.asarray(v_mm_s, float))
    rw = s.diameter_mm * 1e-3 / 2
    ev = removal_energy(s)
    vv = np.maximum(v, 1e-6) * 1e-3
    lo = np.full(t_k.shape, np.log(1e-9))
    hi = np.full(t_k.shape, np.log(R_CAP_MM * 1e-3))
    for _ in range(48):
        mid = 0.5 * (lo + hi)
        r = rw + np.exp(mid)
        surplus = q_front(r, t_k, s) - ev * vv * 2 * r
        lo = np.where(surplus > 0, mid, lo)
        hi = np.where(surplus > 0, hi, mid)
    r = rw + np.exp(0.5 * (lo + hi))
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


def _solve_uniform(i_a, v, s: CutSetup, in_foam: bool):  # type: ignore[no-untyped-def]
    """Uniform wire temperature (K) for current ``i_a``; vectorised bisection."""
    i_a, v = np.broadcast_arrays(np.asarray(i_a, float), np.asarray(v, float))
    tinf = s.ambient_c + K0
    lo = np.full(i_a.shape, tinf)
    hi = np.full(i_a.shape, s.wire.max_temp_c + 400 + K0)
    for _ in range(46):
        mid = 0.5 * (lo + hi)
        gen = i_a**2 * resistance_per_m(mid, s)
        if in_foam:
            loss = q_front(melt_radius(mid, v, s), mid, s) + 0.5 * q_air(mid, s)
        else:
            loss = q_air(mid, s)
        lo = np.where(gen > loss, mid, lo)
        hi = np.where(gen > loss, hi, mid)
    return 0.5 * (lo + hi)


def point_state(s: CutSetup, v_mm_s, *, current_a=None, voltage_v=None) -> PointState:  # type: ignore[no-untyped-def]
    """Steady state at mid-block, ignoring end conduction (fast; vectorised).

    ``current_a`` / ``voltage_v`` override the setup (arrays broadcast with
    ``v_mm_s``), so a whole operating map is one call.
    """
    mode = "voltage" if voltage_v is not None else ("current" if current_a is not None else s.mode)
    v = np.asarray(v_mm_s, float)
    span = s.span_mm * 1e-3
    b = min(s.block_width_mm, s.span_mm) * 1e-3
    if mode == "current":
        i = np.asarray(s.current_a if current_a is None else current_a, float)
        i, v = np.broadcast_arrays(i, v)
        t_air = _solve_uniform(i, v, s, False)
        t_foam = _solve_uniform(i, v, s, True)
    else:
        u = np.asarray(s.voltage_v if voltage_v is None else voltage_v, float)
        u, v = np.broadcast_arrays(u, v)
        i = u / (resistance_per_m(s.ambient_c + K0, s) * span + s.lead_resistance_ohm)
        for _ in range(30):  # the wire's resistance rises as it heats: fixed point on I
            t_air = _solve_uniform(i, v, s, False)
            t_foam = _solve_uniform(i, v, s, True)
            r_tot = resistance_per_m(t_air, s) * (span - b) + resistance_per_m(t_foam, s) * b + s.lead_resistance_ohm
            i = 0.5 * i + 0.5 * u / r_tot
    r = melt_radius(t_foam, v, s)
    rw = s.diameter_mm * 1e-3 / 2
    stall = t_foam <= s.foam.iso_temp_c + K0 + 1.0
    gap = (r - rw) * 1e3
    q = np.where(stall, 0.0, q_front(r, t_foam, s))
    power = i**2 * (resistance_per_m(t_air, s) * (span - b) + resistance_per_m(t_foam, s) * b)
    return PointState(
        t_air_c=t_air - K0, t_foam_c=t_foam - K0, r_m_mm=r * 1e3, kerf_mm=2 * s.calib.kappa * r * 1e3,
        gap_mm=gap, contact=(gap < s.calib.contact_gap_mm) | stall, stall=stall, q_cut_w_m=q,
        current_a=i, power_w=power,
    )


def contact_speed(s: CutSetup, *, current_a=None, voltage_v=None, v_max: float = 500.0) -> float:  # type: ignore[no-untyped-def]
    """Fastest feed (mm/s) that still cuts without touching the foam (0 if it never does)."""
    vs = np.geomspace(0.02, v_max, 160)
    st = point_state(s, vs, current_a=current_a, voltage_v=voltage_v)
    ok = ~st.contact
    if not ok.any():
        return 0.0
    if ok.all():
        return v_max
    k = int(np.argmin(ok))  # first contact speed
    lo, hi = vs[max(0, k - 1)], vs[k]
    for _ in range(25):
        mid = np.sqrt(lo * hi)
        if point_state(s, mid, current_a=current_a, voltage_v=voltage_v).contact:
            hi = mid
        else:
            lo = mid
    return float(lo)


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
        la = q_air(t, s)
        lf = q_front(melt_radius(t, vb, s), t, s) + 0.5 * la
        return np.where(foam_mask[None, :], lf, la)

    def solve(i_a, foam_mask, voltage=None):  # type: ignore[no-untyped-def]
        """Newton on the fin equation; with ``voltage`` the current follows the wire's resistance."""
        t = np.broadcast_to(_solve_uniform(i_a, speeds, s, False)[:, None], (nv, nodes)).copy()
        vb = np.broadcast_to(speeds[:, None], (nv, nodes))
        r0 = resistance_per_m(20 + K0, s)
        for _ in range(40):
            if voltage is not None:
                r_tot = np.trapezoid(resistance_per_m(t, s), x, axis=1) + s.lead_resistance_ohm
                i_a = 0.5 * i_a + 0.5 * voltage / r_tot
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

    if s.mode == "current":
        i_a = np.full(nv, s.current_a)
        t, _ = solve(i_a, in_foam)
        t_air, _ = solve(i_a, np.zeros(nodes, bool))
    else:
        i0 = np.full(nv, s.voltage_v / (resistance_per_m(tinf, s) * span + s.lead_resistance_ohm))
        t, i_a = solve(i0, in_foam, s.voltage_v)
        t_air, _ = solve(i0, np.zeros(nodes, bool), s.voltage_v)
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
    """Kerf and regime over a grid of drive (A or V) × feed speed."""
    if drive is None:
        if s.mode == "current":
            drive = np.linspace(max(0.05, s.current_a * 0.25), s.current_a * 2.5, 70)
        else:
            drive = np.linspace(max(0.1, s.voltage_v * 0.25), s.voltage_v * 2.5, 70)
    speeds = np.geomspace(0.2, 60.0, 80) if speeds is None else np.asarray(speeds, float)
    dd, vv = np.meshgrid(np.asarray(drive, float), speeds, indexing="ij")
    kw = {"current_a": dd} if s.mode == "current" else {"voltage_v": dd}
    st = point_state(s, vv, **kw)
    return OperatingMap(drive=np.asarray(drive, float), speeds=speeds, mode=s.mode, kerf_mm=st.kerf_mm,
                        t_foam_c=st.t_foam_c, t_air_c=st.t_air_c, contact=st.contact, stall=st.stall)
