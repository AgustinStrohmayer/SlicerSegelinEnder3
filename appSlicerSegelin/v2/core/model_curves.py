"""Prediction curves of every model against feed, for a set of drives, plus the measurements.

One place gathers what the Cut Lab can say about a cut so it can be plotted
side by side and exported:

* the reduced model as set (with the calibration ``eta``/``kappa``),
* the same model uncalibrated (``eta = kappa = 1``: handbook values only),
* the empirical power law fitted to the measurements (:func:`fit_empirical`),
* the 2-D thermal solve at a few feeds (first principles, uncalibrated),
* the measured kerfs.

Quantities: ``kerf_mm``, ``r_m_mm`` (radius of incidence), ``t_wire_c`` (wire
in the foam) and ``gap_mm``. Not every source has every quantity (a caliper
gives the kerf only).
"""
from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass, field, replace

import numpy as np

from .calibration import EmpiricalFit, Measurement
from .cutting_physics import Calibration, CutSetup, point_state
from .thermal2d import solve_section

QUANTITIES: dict[str, str] = {
    "kerf_mm": "Kerf (mm)",
    "r_m_mm": "Radius of incidence r_m (mm)",
    "t_wire_c": "Wire temperature in the foam (°C)",
    "gap_mm": "Gap wire–foam (mm)",
}


@dataclass(slots=True)
class Series:
    source: str                 # "model", "uncalibrated", "empirical", "2-D", "measured"
    drive: float
    speeds: np.ndarray
    values: dict[str, np.ndarray] = field(default_factory=dict)
    flags: dict[str, np.ndarray] = field(default_factory=dict)  # e.g. contact per point


def drive_kw(setup: CutSetup, drive: float) -> dict[str, float]:
    return {"current_a": drive} if setup.mode == "current" else {"voltage_v": drive}


def with_drive(setup: CutSetup, drive: float) -> CutSetup:
    return replace(setup, current_a=drive) if setup.mode == "current" else replace(setup, voltage_v=drive)


def uncalibrated(setup: CutSetup) -> CutSetup:
    c = setup.calib
    return replace(setup, calib=Calibration(contact_gap_mm=c.contact_gap_mm, c_drag_n_m_per_mm_s=c.c_drag_n_m_per_mm_s))


def model_series(setup: CutSetup, drives, speeds, source: str = "model") -> list[Series]:  # type: ignore[no-untyped-def]
    s = uncalibrated(setup) if source == "uncalibrated" else setup
    vs = np.asarray(speeds, float)
    out = []
    for d in drives:
        st = point_state(s, vs, **drive_kw(s, float(d)))
        out.append(Series(source, float(d), vs, {"kerf_mm": st.kerf_mm, "r_m_mm": st.r_m_mm, "t_wire_c": st.t_foam_c,
                                                  "gap_mm": st.gap_mm},
                          {"contact": st.contact, "stall": st.stall}))
    return out


def empirical_series(fit: EmpiricalFit, drives, speeds) -> list[Series]:  # type: ignore[no-untyped-def]
    vs = np.asarray(speeds, float)
    return [Series("empirical", float(d), vs, {"kerf_mm": fit.predict(vs, float(d))}) for d in drives]


def measured_series(ms: list[Measurement], mode: str) -> list[Series]:
    out = []
    for d in sorted({m.drive for m in ms if m.mode == mode}):
        pts = sorted((m for m in ms if m.mode == mode and m.drive == d), key=lambda m: m.speed_mm_s)
        out.append(Series("measured", float(d), np.array([m.speed_mm_s for m in pts]),
                          {"kerf_mm": np.array([m.kerf_mm for m in pts])}))
    return out


def thermal2d_series(setup: CutSetup, drives, speeds, *, quality: str = "coarse",  # type: ignore[no-untyped-def]
                     progress: Callable[[float, str], bool] | None = None) -> list[Series]:
    """2-D solve at every (drive, feed), uncalibrated. Raises InterruptedError when ``progress`` says stop."""
    s0 = uncalibrated(setup)
    vs = np.asarray(speeds, float)
    total = len(drives) * len(vs)
    out = []
    k = 0
    for d in drives:
        s = with_drive(s0, float(d))
        cols: dict[str, list[float]] = {q: [] for q in QUANTITIES}
        contact, stall = [], []
        for v in vs:

            def sub(f: float, msg: str, k=k, d=d, v=v) -> bool:  # type: ignore[no-untyped-def]
                if progress is None:
                    return True
                return progress((k + f) / total, f"2-D {k + 1}/{total} · {d:g} at {v:g} mm/s — {msg}")

            r = solve_section(s, float(v), quality=quality, progress=sub)
            cols["kerf_mm"].append(r.kerf_mm)
            cols["r_m_mm"].append(r.r_m_mm)
            cols["t_wire_c"].append(r.t_wire_c)
            cols["gap_mm"].append(r.r_m_mm - s.diameter_mm / 2)
            contact.append(r.contact)
            stall.append(r.stall)
            k += 1
        out.append(Series("2-D", float(d), vs, {q: np.array(a) for q, a in cols.items()},
                          {"contact": np.array(contact), "stall": np.array(stall)}))
    return out


def errors_vs_measured(series: list[Series], ms: list[Measurement], mode: str) -> dict[str, float]:
    """RMS kerf error (mm) of each source at the measured points (log-interpolated in feed)."""
    out: dict[str, float] = {}
    by_src: dict[str, list[float]] = {}
    for sr in series:
        if sr.source == "measured" or "kerf_mm" not in sr.values or len(sr.speeds) < 2:
            continue
        for m in ms:
            if m.mode != mode or abs(m.drive - sr.drive) > 1e-9:
                continue
            if not sr.speeds[0] <= m.speed_mm_s <= sr.speeds[-1]:
                continue
            pred = float(np.exp(np.interp(np.log(m.speed_mm_s), np.log(sr.speeds), np.log(sr.values["kerf_mm"]))))
            by_src.setdefault(sr.source, []).append(pred - m.kerf_mm)
    for src, err in by_src.items():
        out[src] = float(np.sqrt(np.mean(np.square(err))))
    return out


def to_csv(series: list[Series], mode: str) -> str:
    unit = "A" if mode == "current" else "V"
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["source", f"drive_{unit}", "feed_mm_s", *QUANTITIES, "contact", "stall"])
    for sr in series:
        for i, v in enumerate(sr.speeds):
            row = [sr.source, f"{sr.drive:g}", f"{v:.4g}"]
            row += [f"{sr.values[q][i]:.5g}" if q in sr.values else "" for q in QUANTITIES]
            row += [str(bool(sr.flags[f][i])) if f in sr.flags else "" for f in ("contact", "stall")]
            w.writerow(row)
    return buf.getvalue()
