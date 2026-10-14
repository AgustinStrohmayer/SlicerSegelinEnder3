"""Typical ranges shown next to the Cut Lab read-outs, and the work-speed recommendation.

Every range here is either taken from ``docs/fisica-del-corte.md`` (with the
section or reference it comes from) or computed by the model itself for the
current wire, and then says "model estimate". Nothing else: if a number has no
source it is not shown.

* Wire temperature: thermal, non-contact cutting from ~160 °C; polystyrene
  starts to volatilise at ~275 °C, fastest at 400–420 °C (doc §1, Mehta et
  al. [14] via Brooks & Aitchison [3]). Brooks & Aitchison's fit for EPS gives
  104–370 °C over the Q_eff range they cut (doc §4).
* Kerf: 1.4–6 × the wire diameter (Ahn et al., quoted in [3]; doc §4).
* Radius of incidence: that kerf range divided by 2·κ (the model's own
  definition, kerf = 2·κ·r_m).
* Current, voltage, power: what the model needs to hold *this* wire at
  160–400 °C in still air (closed form of I²R'(T) = q_air(T)).
* Feed: the model's clean (non-contact, not over-melting) window at the
  current drive, from the background scan.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ....core.cutting_physics import (
    K0,
    CutSetup,
    current_for_air_temp,
    point_state,
    resistance_per_m,
)

T_CUT_MIN_C = 160.0   # doc §1: above ~160 °C the cut is thermal and non-contact
T_SMOKE_C = 400.0     # doc §1: volatilisation fastest at 400–420 °C
T_BROOKS_C = (104.0, 370.0)  # doc §4: 17.7·Q_eff + 68.8 over Q_eff ≈ 2–17 kJ/m²
KERF_PER_D = (1.4, 6.0)      # doc §4: kerf 1.4–6 × wire diameter (Ahn et al. via [3])
SAFE_FRACTION = 0.8          # recommended feed: at most this share of the model's contact speed


@dataclass(frozen=True, slots=True)
class Typical:
    t_air: str
    t_foam: str
    kerf: str
    r_m: str
    current: str
    voltage: str
    power: str
    tip: dict[str, str]


def drive_window(s: CutSetup) -> dict[str, float]:
    """Current, voltage and power that hold this wire at 160–400 °C in still air (model estimate)."""
    out: dict[str, float] = {}
    span = s.span_mm * 1e-3
    for key, t in (("lo", T_CUT_MIN_C), ("hi", T_SMOKE_C)):
        i = float(current_for_air_temp(s, t))
        r = float(resistance_per_m(t + K0, s)) * span
        out[f"i_{key}"] = i
        out[f"u_{key}"] = i * (r + s.lead_resistance_ohm)
        out[f"p_{key}"] = i * i * r
    return out


def typical(s: CutSetup) -> Typical:
    d = s.diameter_mm
    k_lo, k_hi = KERF_PER_D[0] * d, KERF_PER_D[1] * d
    kap = max(s.calib.kappa, 1e-6)
    w = drive_window(s)
    return Typical(
        t_air=f"typical {T_CUT_MIN_C:.0f}–{T_SMOKE_C:.0f} °C",
        t_foam=f"typical {T_CUT_MIN_C:.0f}–{T_BROOKS_C[1]:.0f} °C",
        kerf=f"typical {k_lo:.2f}–{k_hi:.2f} mm",
        r_m=f"typical {k_lo / (2 * kap):.2f}–{k_hi / (2 * kap):.2f} mm",
        current=f"model: {w['i_lo']:.2f}–{w['i_hi']:.2f} A",
        voltage=f"model: {w['u_lo']:.1f}–{w['u_hi']:.1f} V",
        power=f"model: {w['p_lo']:.1f}–{w['p_hi']:.1f} W",
        tip={
            "t_air": "Foam cuts thermally (no contact) from about 160 °C; polystyrene volatilises fastest at "
                     "400–420 °C, so hotter only smokes and widens the slot (docs/fisica-del-corte.md §1).",
            "t_foam": "≥160 °C for a non-contact cut (doc §1). Brooks & Aitchison measured 104–370 °C over their "
                      "range of cuts (doc §4, ref. [3]).",
            "kerf": "Kerf is typically 1.4–6 times the wire diameter (Ahn et al., quoted in Brooks & Aitchison "
                    "[3]; docs/fisica-del-corte.md §4).",
            "r_m": "From the typical kerf range, since the model's kerf is 2·κ·r_m.",
            "current": "Model estimate: the current that keeps this wire at 160–400 °C in still air.",
            "voltage": "Model estimate: the supply voltage (wire + leads) for 160–400 °C in still air.",
            "power": "Model estimate: the wire's power at 160–400 °C in still air.",
        },
    )


def regime_of(st, s: CutSetup) -> str:  # type: ignore[no-untyped-def]
    """Same rule as the Explore tab (kept here so the pure logic has no Qt import)."""
    if bool(st.stall):
        return "stall"
    if bool(st.contact):
        return "contact"
    if float(st.kerf_mm) > 4 * s.diameter_mm and float(st.kerf_mm) > 1.2:
        return "overmelt"
    return "noncontact"


def feed_scan(s: CutSetup, lo: float = 0.1, hi: float = 60.0, n: int = 120) -> dict:
    """Regime along the feed axis at the current drive (for the gauge and the clean window)."""
    vs = np.geomspace(lo, hi, n)
    st = point_state(s, vs)
    kerf = np.asarray(st.kerf_mm)
    wide = (kerf > 4 * s.diameter_mm) & (kerf > 1.2)  # as regime_of
    regs = np.where(np.asarray(st.stall), "stall", np.where(np.asarray(st.contact), "contact",
                                                            np.where(wide, "overmelt", "noncontact")))
    clean = regs == "noncontact"
    win = (float(vs[clean].min()), float(vs[clean].max())) if clean.any() else None
    return {"speeds": vs, "regimes": regs, "kerf": kerf, "clean": win}


def recommend(s: CutSetup, vc: float | None, vmax_axis: float | None = None) -> dict:
    """Work speed and kerf compensation for setup ``s``.

    Criterion, in order:

    1. **clean cut** — at most ``SAFE_FRACTION`` (80 %) of the model's fastest
       non-contact feed ``vc``, a margin for the model's optimism (the 2-D
       solve finds contact earlier: doc §3.2);
    2. **the machine can hold it** — no faster than the slowest axis
       (``vmax_axis``; stock Ender-3: Z = 5 mm/s, ``core.motion``), so the
       wire keeps one speed on steep and flat stretches and one kerf
       compensation is right everywhere;
    3. rounded down to 0.1 mm/s.

    ``vc`` None: not computed yet.
    """
    if vc is None:
        return {"state": "pending"}
    if vc <= 0:
        st = point_state(s, 1.0)
        return {"state": "stall" if bool(st.stall) else "contact"}
    v_clean = SAFE_FRACTION * vc
    limit = "clean"
    v = v_clean
    if vmax_axis is not None and vmax_axis > 0 and vmax_axis < v:
        v, limit = vmax_axis, "axis"
    v = max(0.1, math.floor(10 * v + 1e-9) / 10)
    st = point_state(s, v)
    return {"state": regime_of(st, s), "v": v, "vc": vc, "v_clean": v_clean, "limit": limit,
            "vmax_axis": vmax_axis, "kerf": float(st.kerf_mm), "t_foam": float(st.t_foam_c),
            "t_air": float(st.t_air_c)}
