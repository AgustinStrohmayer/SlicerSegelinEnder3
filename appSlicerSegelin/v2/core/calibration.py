"""Calibrating the cut model to a real machine: test cuts, measurements, fit.

**Why a staircase strip.** A kerf is hard to measure directly: the slot is
narrow, its walls are soft, and a caliper's jaws don't fit in it. A *strip*
is easy: two parallel cuts a nominal distance ``W`` apart free a slab whose
thickness is ``W − kerf`` (each cut eats half a kerf from each face of the
slab). Thickness is an outside measurement, the one a caliper is good at.

To get several feeds from one test, each cut is split into sections along Y,
each at its own feed; the slab comes out as a staircase. Both cuts run in the
same direction (the wire travels back over the top of the block in air), so
both faces of every step share the same thermal history. Measure each step
near its *end*, where the wire temperature has settled.

Repeat the test at two or three drive settings (current or voltage) and the
fit adjusts the model's heat-transfer factor ``eta`` and kerf spread
``kappa`` so the predicted kerf matches yours at every feed and drive.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from .cutting_physics import CutSetup, point_state, wire_time_constant_s


@dataclass(frozen=True, slots=True)
class StaircaseSpec:
    speeds_mm_s: tuple[float, ...] = (1.0, 2.0, 3.5, 6.0, 10.0)
    block_length_mm: float = 200.0   # Y
    block_height_mm: float = 40.0    # Z
    strip_mm: float = 10.0           # nominal distance between the two cuts
    first_cut_z_mm: float = 12.0     # height of the lower cut above the block bottom
    lead_mm: float = 5.0             # wire parked this far in front of the block
    travel_mm_s: float = 5.0
    clearance_mm: float = 8.0        # wire travels back this far over the block top

    @property
    def section_mm(self) -> float:
        return self.block_length_mm / len(self.speeds_mm_s)

    def measure_points(self) -> list[float]:
        """Where to measure each step, mm from the block's front face (80 % along the step)."""
        L = self.section_mm
        return [L * i + 0.8 * L for i in range(len(self.speeds_mm_s))]


def staircase_gcode(spec: StaircaseSpec, drive_label: str = "") -> str:
    """G-code of the staircase test. Origin: wire parked ``lead`` in front of the block, at its bottom."""
    y0 = spec.lead_mm
    L = spec.section_mm
    za, zb = spec.first_cut_z_mm, spec.first_cut_z_mm + spec.strip_mm
    top = spec.block_height_mm + spec.clearance_mm
    out_y = y0 + spec.block_length_mm + spec.lead_mm
    ft = spec.travel_mm_s * 60

    def cut(z: float) -> list[str]:
        lines = [f"G1 F{ft:.0f} Y0 Z{z:.3f}"]
        for i, v in enumerate(spec.speeds_mm_s):
            lines.append(f"G1 F{v * 60:.0f} Y{y0 + L * (i + 1):.3f} Z{z:.3f} ; step {i + 1}: {v:g} mm/s")
        lines.append(f"G1 F{ft:.0f} Y{out_y:.3f} Z{z:.3f}")
        return lines

    head = [
        "; Hot-wire kerf calibration — staircase strip",
        f"; drive: {drive_label or 'as set on the supply'}",
        f"; block {spec.block_length_mm:g} (Y) x {spec.block_height_mm:g} (Z) mm, front face at Y{y0:g}",
        f"; cuts at Z{za:g} and Z{zb:g} (nominal strip {spec.strip_mm:g} mm)",
        "; measure each step at (mm from the front face): "
        + ", ".join(f"{p:.0f}" for p in spec.measure_points()),
        "G21", "G90", "M140 S0", "M104 S0", "M107", "G92 Y0 Z0",
    ]
    body = cut(za)
    body += [f"G1 F{ft:.0f} Y{out_y:.3f} Z{top:.3f}", f"G1 Y0 Z{top:.3f}"]  # back over the block, in air
    body += cut(zb)
    body += [f"G1 F{ft:.0f} Y{out_y:.3f} Z{top:.3f}", f"G1 Y0 Z{top:.3f}", "G1 Y0 Z0", "M84"]
    return "\n".join(head + body) + "\n"


def section_warnings(spec: StaircaseSpec, setup: CutSetup) -> list[str]:
    """Steps too short for the wire temperature to settle (needs ~3 time constants)."""
    tau = wire_time_constant_s(setup, float(point_state(setup, 1.0).t_air_c))
    out = []
    for v in spec.speeds_mm_s:
        need = 3 * v * tau
        if need > 0.8 * spec.section_mm:
            out.append(f"{v:g} mm/s: the wire needs ~{need:.0f} mm to settle; the step is {spec.section_mm:.0f} mm.")
    return out


@dataclass(frozen=True, slots=True)
class Measurement:
    speed_mm_s: float
    drive: float             # A in current mode, V in voltage mode
    mode: str                # "current" | "voltage"
    thickness_mm: float      # measured strip thickness
    strip_mm: float = 10.0   # nominal

    @property
    def kerf_mm(self) -> float:
        return self.strip_mm - self.thickness_mm


@dataclass(frozen=True, slots=True)
class FitResult:
    eta: float
    kappa: float
    rms_mm: float
    predicted: tuple[float, ...]
    measured: tuple[float, ...]
    note: str = ""
    used: tuple[int, ...] = field(default_factory=tuple)


def _predict(setup: CutSetup, data: list[Measurement]) -> np.ndarray:
    v = np.array([m.speed_mm_s for m in data])
    out = np.empty(len(data))
    for mode in ("current", "voltage"):
        idx = [i for i, m in enumerate(data) if m.mode == mode]
        if not idx:
            continue
        drive = np.array([data[i].drive for i in idx])
        kw = {"current_a": drive} if mode == "current" else {"voltage_v": drive}
        out[idx] = point_state(replace(setup, mode=mode), v[idx], **kw).r_m_mm * 2
    return out  # kerf with kappa = 1


def fit(setup: CutSetup, data: list[Measurement]) -> FitResult:
    """Least-squares (in log kerf) fit of ``eta`` and ``kappa`` to measured kerfs."""
    good = [i for i, m in enumerate(data) if m.kerf_mm > 0.01]
    pts = [data[i] for i in good]
    if not pts:
        raise ValueError("No usable measurement: thickness must be less than the nominal strip.")
    meas = np.array([m.kerf_mm for m in pts])
    distinct = len({(round(m.speed_mm_s, 3), m.mode, round(m.drive, 3)) for m in pts})

    def evaluate(eta: float) -> tuple[float, float, np.ndarray]:
        s = replace(setup, calib=replace(setup.calib, eta=eta, kappa=1.0))
        base = _predict(s, pts)
        kappa = float(np.clip(np.exp(np.mean(np.log(meas) - np.log(base))), 0.3, 3.0))
        pred = kappa * base
        return float(np.sqrt(np.mean((np.log(pred) - np.log(meas)) ** 2))), kappa, pred

    if distinct < 2:
        _, kappa, pred = evaluate(setup.calib.eta)
        eta, note = setup.calib.eta, "One operating point: only the kerf scale (kappa) was fitted."
    else:
        grid = np.geomspace(0.1, 10.0, 31)
        errs = [evaluate(e)[0] for e in grid]
        k = int(np.argmin(errs))
        lo, hi = math.log(grid[max(0, k - 1)]), math.log(grid[min(len(grid) - 1, k + 1)])
        for _ in range(20):  # golden-section refine in log(eta)
            a = hi - 0.618 * (hi - lo)
            b = lo + 0.618 * (hi - lo)
            if evaluate(math.exp(a))[0] < evaluate(math.exp(b))[0]:
                hi = b
            else:
                lo = a
        eta = math.exp(0.5 * (lo + hi))
        _err, kappa, pred = evaluate(eta)
        note = ""
    rms = float(np.sqrt(np.mean((pred - meas) ** 2)))
    return FitResult(eta=eta, kappa=kappa, rms_mm=rms, predicted=tuple(pred.tolist()),
                     measured=tuple(meas.tolist()), note=note, used=tuple(good))


def resistivity_from_cold(r_cold_ohm: float, setup: CutSetup, ambient_c: float | None = None) -> float:
    """Wire resistivity at 20 °C implied by a multimeter reading of the whole span."""
    a = math.pi * (setup.diameter_mm * 1e-3) ** 2 / 4
    t = setup.ambient_c if ambient_c is None else ambient_c
    rho_t = r_cold_ohm * a / (setup.span_mm * 1e-3)
    return rho_t / (1 + setup.wire.alpha_per_k * (t - 20))


def temperature_from_resistance(r_hot_ohm: float, r_cold_ohm: float, setup: CutSetup) -> float | None:
    """Mean wire temperature from hot/cold resistance (only meaningful for alloys with a large α)."""
    alpha = setup.wire.alpha_per_k
    if alpha < 5e-4 or r_cold_ohm <= 0:
        return None
    return setup.ambient_c + (r_hot_ohm / r_cold_ohm - 1) / alpha


# ── empirical law, no physics ─────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class EmpiricalFit:
    """``kerf = a · v^b · D^c`` fitted to the measurements (``D``: current in A or voltage in V).

    A straight line in log–log, so its exponents read directly: ``b`` says how
    fast the kerf narrows with feed (≈ −1 if the wire delivers a fixed power
    to the foam, ≈ −½ if diffusion dominates), ``c`` how fast it widens with
    drive. With a single drive ``c`` cannot be fitted and is reported as 0.
    """

    a: float
    b: float
    c: float
    se_b: float               # standard errors (nan when there are no spare points)
    se_c: float
    r2: float                 # in log space
    rms_mm: float
    n: int
    mode: str
    per_drive: tuple[tuple[float, float, float], ...]  # (drive, a, b): one power law per drive

    def predict(self, v_mm_s, drive):  # type: ignore[no-untyped-def]
        v, d = np.broadcast_arrays(np.asarray(v_mm_s, float), np.asarray(drive, float))
        return self.a * v**self.b * (d**self.c if self.c else 1.0)

    def equation(self) -> str:
        unit = "I" if self.mode == "current" else "U"
        drive = f" · {unit}^{self.c:.2f}" if self.c else ""
        return f"kerf = {self.a:.3g} · v^{self.b:.2f}{drive}"


def fit_empirical(data: list[Measurement]) -> EmpiricalFit:
    """Least squares on ``log kerf = log a + b·log v + c·log D`` (one supply mode)."""
    pts = [m for m in data if m.kerf_mm > 0.01 and m.speed_mm_s > 0 and m.drive > 0]
    if not pts:
        raise ValueError("No usable measurement: thickness must be less than the nominal strip.")
    modes = {m.mode for m in pts}
    if len(modes) > 1:
        raise ValueError("Measurements mix current and voltage mode: fit one mode at a time.")
    y = np.log([m.kerf_mm for m in pts])
    lv = np.log([m.speed_mm_s for m in pts])
    ld = np.log([m.drive for m in pts])
    if len({round(m.speed_mm_s, 6) for m in pts}) < 2:
        raise ValueError("Need at least two different feeds.")
    with_drive = len({round(m.drive, 6) for m in pts}) >= 2
    cols = [np.ones_like(lv), lv] + ([ld] if with_drive else [])
    X = np.column_stack(cols)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ coef
    n, p = X.shape
    dof = n - p
    if dof > 0:
        cov = np.linalg.pinv(X.T @ X) * float(res @ res) / dof
        se = np.sqrt(np.maximum(np.diag(cov), 0.0))
    else:
        se = np.full(p, np.nan)
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(res @ res) / ss_tot if ss_tot > 0 else 1.0
    per = []
    for d in sorted({m.drive for m in pts}):
        sel = [i for i, m in enumerate(pts) if m.drive == d]
        if len({round(pts[i].speed_mm_s, 6) for i in sel}) >= 2:
            bb, la = np.polyfit(lv[sel], y[sel], 1)
            per.append((float(d), float(np.exp(la)), float(bb)))
    fitd = EmpiricalFit(a=float(np.exp(coef[0])), b=float(coef[1]), c=float(coef[2]) if with_drive else 0.0,
                        se_b=float(se[1]), se_c=float(se[2]) if with_drive else float("nan"), r2=r2, rms_mm=0.0,
                        n=n, mode=pts[0].mode, per_drive=tuple(per))
    pred = fitd.predict([m.speed_mm_s for m in pts], [m.drive for m in pts])
    rms = float(np.sqrt(np.mean((pred - np.exp(y)) ** 2)))
    return replace(fitd, rms_mm=rms)
