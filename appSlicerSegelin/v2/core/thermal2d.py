"""High-fidelity mode: transient 2-D heat conduction around the hot wire.

The reduced-order model in :mod:`core.cutting_physics` closes the melt front
with a half-annulus formula. This module resolves the same physics on a grid:
the cross-section of the cut (``x`` along the feed, ``y`` across the kerf) in a
window that travels with the wire.

* **Frame.** The window moves with the wire, so the foam and the gas of the
  slot flow through it at ``−v``. The time step is ``Δ/v``: every step the
  fields shift by exactly one cell (advection with no numerical diffusion),
  then diffuse implicitly over the step.
* **Media.** Each cell carries a foam fraction ``φ`` (1 = intact foam,
  0 = gas in the slot). Conductivity and heat capacity mix the two; the gas
  uses air's ``k(T)`` (times ``eta``, as in the reduced model) and ``ρc`` of
  an ideal gas.
* **Melt front.** Enthalpy method: foam that reaches the collapse isotherm
  ``T_iso`` takes its latent heat ``L_eff`` before it turns into gas. The kerf
  is where the foam fraction has gone, so it comes out of the front instead of
  being imposed (no ``kappa``).
* **Wire.** A lumped node held at ``T_w`` (the cells inside its radius).
  ``C_w·dT_w/dt = I²·R'(T_w) − q_cond − q_rad − q_contact`` with the supply
  current of the reduced model. Conduction to the gas is resolved all around
  the wire, so the reduced model's ``½·q_air`` for the back half is not added
  (the slot is far too narrow for buoyant convection: its Rayleigh number is
  ≪ 1). Radiation is emitted over the whole circumference and absorbed by the
  foam faces the wire sees (``cos θ / 2πr`` line-source weights); what leaves
  through the open slot is lost. Foam that reaches the wire (contact) is
  removed by it and charged to its energy.
* **Boundaries.** Symmetry on the wire's axis (only ``y ≥ 0`` is solved),
  ambient far to the side, zero gradient where the slot leaves the window, and
  ahead a Robin condition matching the 1-D preheat profile
  ``exp(−v·x/α)``, so the window need not hold the whole thermal layer.

The window and the cell size scale with the reduced model's ``r_m`` and the
thermal length ``α/v``. Measured run times (one core, Nichrome 0.3 mm in
EPS 20, 1.2–1.6 A, 0.5–8 mm/s; the window and the step count grow at slow
feeds):

==========  ==========  ==================  =========================
grid        cell        fast feed (≥3 mm/s)  slow feed (0.5–1 mm/s)
==========  ==========  ==================  =========================
coarse      ~50 µm      < 1 s               2–5 s
normal      30–80 µm    1–8 s               25–65 s
fine        19–50 µm    ~80 s               ~190 s
ultra       12–35 µm    ~50 s               > 15 min
==========  ==========  ==================  =========================

Grid study at 3 mm/s, wire held at the model's temperature: kerf 0.743 /
0.740 / 0.753 / 0.768 mm and heat into the foam 29.5 / 28.9 / 29.0 /
29.2 W/m from coarse to 12 µm cells; the energy balance (wire heat = foam
removed + heat carried out in the walls + side loss) closes within 1 %.

Against the reduced model (κ = 1): with the wire at the model's temperature
the 2-D kerf is 0.70–0.95× the model's from 0.5 to 8 mm/s, with the same
trend; the front sits nearer the wire (r_m about half) and the walls keep
receding behind it, so kerf ≈ 3·r_m (the model's ``kappa`` ≈ 1.5). The heat
left in the walls of the cut is as large as the heat that removes the foam,
and the closed form leaves it out: solved with the wire's own Joule balance,
at 1.6 A the 2-D kerf is 0.73–1.02× the model's, but at 1.2 A the wire runs
colder and the gap closes near 3 mm/s instead of ~9 mm/s.

Pure numpy (matrix-free Jacobi-preconditioned conjugate gradient); SI inside.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .cutting_physics import (
    K0,
    SIGMA,
    CutSetup,
    air_conductivity,
    point_state,
    resistance_per_m,
)

ProgressFn = Callable[[float, str], bool]

# grid presets: cells across the wire radius and a ceiling on the cell count (half window)
QUALITY: dict[str, tuple[float, int]] = {
    "coarse": (3.0, 9_000),
    "normal": (5.0, 30_000),
    "fine": (8.0, 80_000),
    "ultra": (12.0, 200_000),
}
CP_AIR = 1010.0
RHO_AIR_T = 353.0  # ρ·T of air at 1 atm, kg·K/m³


@dataclass(frozen=True, slots=True)
class Window:
    cell_m: float
    ahead_m: float
    behind_m: float
    side_m: float
    nx: int
    ny: int


@dataclass(frozen=True, slots=True)
class Thermal2DResult:
    """Final fields (full section, mirrored) and the run's history."""

    v_mm_s: float
    x_mm: np.ndarray          # cell centres along the feed (wire at 0, foam comes from +x)
    y_mm: np.ndarray          # cell centres across the kerf (full, symmetric)
    t_c: np.ndarray           # temperature [x, y], °C
    phi: np.ndarray           # foam fraction [x, y]
    wall_mm: np.ndarray       # half-width of the slot at each x
    r_m_mm: float             # melt front ahead of the wire's axis
    kerf_mm: float            # slot width where it has settled, behind the wire
    t_wire_c: float
    q_cut_w_m: float          # heat from the wire into the section (conduction + absorbed radiation + contact),
                              # averaged over the last quarter transit
    current_a: float
    contact: bool             # foam keeps reaching the wire
    stall: bool               # the wire fell to the foam's isotherm: it cannot melt ahead of itself
    converged: bool
    steps: int
    sim_time_s: float
    runtime_s: float
    cell_um: float
    hist_t: np.ndarray        # simulated time
    hist_rm: np.ndarray
    hist_kerf: np.ndarray
    hist_tw: np.ndarray
    hist_q: np.ndarray
    model_r_m_mm: float       # reduced model at the same point, for comparison
    model_kerf_mm: float
    model_t_wire_c: float


def window_for(s: CutSetup, v_mm_s: float, quality: str = "normal", extent: float = 1.0) -> Window:
    """Window and cell size from the reduced model's melt radius and the thermal length α/v.

    ``extent`` scales the margins (for checking that the boundaries are far enough).
    """
    per_rw, n_max = QUALITY[quality]
    st = point_state(s, v_mm_s)
    rw = s.diameter_mm * 1e-3 / 2
    rm = float(max(st.r_m_mm * 1e-3, rw * 1.05))
    f = s.foam
    alpha = f.conductivity_w_mk / (f.density_kg_m3 * f.specific_heat_j_kgk)
    v = max(v_mm_s, 1e-3) * 1e-3
    delta = alpha / v
    ahead = rm + extent * min(2.0 * delta, 5e-3) + 4 * rw
    behind = extent * max(4.0 * rm, 1.6e-3)
    side = rm + extent * min(max(1.0e-3, 2.0 * math.sqrt(alpha * behind / v)), 5e-3)
    cell = max(rw / per_rw, math.sqrt((ahead + behind) * side / n_max))
    nx = max(16, round((ahead + behind) / cell))
    ny = max(8, round(side / cell))
    return Window(cell, ahead, behind, side, nx, ny)


def _harm(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return 2 * a * b / np.maximum(a + b, 1e-30)


def _offdiag(p: np.ndarray, gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
    """Σ G·p_neighbour over the interior faces."""
    out = np.zeros_like(p)
    out[:-1, :] += gx * p[1:, :]
    out[1:, :] += gx * p[:-1, :]
    out[:, :-1] += gy * p[:, 1:]
    out[:, 1:] += gy * p[:, :-1]
    return out


def _pcg(diag, gx, gy, b, x0, free, tol_k: float, max_iter: int):  # type: ignore[no-untyped-def]
    """Jacobi-preconditioned CG on the free cells; fixed cells keep ``x0``.

    The faces between free and fixed cells carry no conductance here (their
    contribution is already in ``b``), so the free block is decoupled.
    """
    x = x0.copy()
    inv = np.where(free, 1.0 / diag, 0.0)
    r = np.where(free, b - (diag * x - _offdiag(np.where(free, x, 0.0), gx, gy)), 0.0)
    z = inv * r
    p = z.copy()
    rz = float(np.vdot(r, z))
    for it in range(max_iter):
        if np.max(np.abs(r) * inv) < tol_k:
            return x, it
        ap = np.where(free, diag * p - _offdiag(p, gx, gy), 0.0)
        a = rz / float(np.vdot(p, ap))
        x += a * p
        r -= a * ap
        z = inv * r
        rz_new = float(np.vdot(r, z))
        p = z + (rz_new / rz) * p
        rz = rz_new
    return x, max_iter


def solve_section(s: CutSetup, v_mm_s: float, *, quality: str = "normal", wire: str = "joule", extent: float = 1.0,
                  max_transits: float = 4.0, tol: float = 2e-3,
                  progress: ProgressFn | None = None) -> Thermal2DResult:
    """March the 2-D section to a steady cut at feed ``v``.

    ``wire="joule"`` solves the wire's temperature from its power balance;
    ``"fixed"`` holds it at the reduced model's in-foam temperature (isolates
    the front physics). Raises :class:`InterruptedError` when ``progress``
    returns False.
    """
    t0 = time.perf_counter()
    win = window_for(s, v_mm_s, quality, extent)
    st = point_state(s, v_mm_s)
    f = s.foam
    eta = s.calib.eta
    d = win.cell_m
    nx, ny = win.nx, win.ny
    v = max(v_mm_s, 1e-3) * 1e-3
    dt = d / v
    rw = s.diameter_mm * 1e-3 / 2
    tinf = s.ambient_c + K0
    tiso = f.iso_temp_c + K0
    rc_f = f.density_kg_m3 * f.specific_heat_j_kgk
    rl_f = f.density_kg_m3 * f.latent_j_kg
    alpha_f = f.conductivity_w_mk / rc_f
    current = float(st.current_a)

    x = win.ahead_m - (np.arange(nx)[::-1] + 0.5) * d          # ascending; foam enters at the last column
    y = (np.arange(ny) + 0.5) * d
    X, Y = np.meshgrid(x, y, indexing="ij")
    R = np.hypot(X, Y)
    wire_mask = R <= max(rw, 0.75 * d)
    free = ~wire_mask

    # start from the reduced model's slot and a preheat layer, so the transient is short
    rm0 = float(st.r_m_mm) * 1e-3
    hw0 = float(st.kerf_mm) * 1e-3 / 2
    slot = ((X <= 0) & (Y <= hw0)) | (R <= rm0)
    phi = np.where(slot | wire_mask, 0.0, 1.0)
    dist = np.where(X > 0, np.maximum(R - rm0, 0.0), np.maximum(Y - hw0, 0.0))
    T = np.where(slot, tiso, tinf + (tiso - tinf) * np.exp(-dist * v / alpha_f))
    t_w = float(st.t_foam_c) + K0
    T[wire_mask] = t_w

    c_wire = s.wire.density_kg_m3 * s.wire.specific_heat_j_kgk * math.pi * rw**2
    eps = s.wire.emissivity

    def own(tk: float) -> float:
        """Joule heat minus what the wire radiates (absorbed by the foam or lost through the slot), W/m."""
        emit = eps * SIGMA * 2 * math.pi * rw * max(tk**4 - tiso**4, 0.0) * eta
        return current**2 * float(resistance_per_m(tk, s)) - emit

    # faces between a free cell and the wire (Dirichlet at the face: half-cell distance)
    wx = wire_mask[1:, :] ^ wire_mask[:-1, :]
    wy = wire_mask[:, 1:] ^ wire_mask[:, :-1]
    robin_g = rc_f * v * d                                        # ahead: ρc·v per face area
    rad_dir = (-X / np.maximum(R, 1e-12), -Y / np.maximum(R, 1e-12))
    shift_decay = math.exp(-d * v / alpha_f)

    n_transit = max(1, round((win.ahead_m + win.behind_m) / d))
    max_steps = int(max_transits * n_transit + 6 * 1.0 / dt)
    min_steps = int(2.0 * n_transit)
    k_meas = max(2, round(0.12 * win.behind_m / d))              # columns averaged at the rear
    hist_t, hist_rm, hist_kerf, hist_tw, hist_q = [], [], [], [], []
    touched: list[bool] = []
    q_cut = 0.0
    step = 0
    converged = False
    i0 = int(np.searchsorted(x, 0.0))                             # first column ahead of the axis

    def measures() -> tuple[float, float]:
        rm = float(np.sum(1.0 - phi[i0:, 0]) * d + x[i0] - 0.5 * d) if i0 < nx else 0.0
        half = np.sum(1.0 - phi, axis=1) * d
        return max(rm, rw), 2.0 * float(np.mean(half[:k_meas]))

    while step < max_steps:
        # 1) advect by one cell toward −x; fresh, preheated foam enters ahead
        T[:-1] = T[1:].copy()
        phi[:-1] = phi[1:].copy()
        T[-1] = tinf + (T[-1] - tinf) * shift_decay
        phi[-1] = 1.0
        # foam that reaches the wire is melted by it (contact)
        eaten = phi[wire_mask]
        q_contact = 0.0
        if np.any(eaten > 1e-6):
            e = eaten * (rc_f * np.maximum(tiso - T[wire_mask], 0.0) + rl_f) * d * d
            q_contact = 2.0 * float(np.sum(e)) / dt
        phi[wire_mask] = 0.0
        T[wire_mask] = t_w

        # 2) properties (lagged)
        tg = np.maximum(T, tinf)
        k = phi * f.conductivity_w_mk + (1 - phi) * eta * air_conductivity(tg)
        cap = phi * rc_f + (1 - phi) * RHO_AIR_T * CP_AIR / tg
        gx = _harm(k[1:, :], k[:-1, :])
        gy = _harm(k[:, 1:], k[:, :-1])
        gx_w = np.where(wx, 2 * np.where(wire_mask[1:, :], k[:-1, :], k[1:, :]), 0.0)
        gy_w = np.where(wy, 2 * np.where(wire_mask[:, 1:], k[:, :-1], k[:, 1:]), 0.0)
        gx = np.where(wx, 0.0, gx)
        gy = np.where(wy, 0.0, gy)
        store = cap * d * d / dt
        diag = store.copy()
        diag[:-1, :] += gx + gx_w
        diag[1:, :] += gx + gx_w
        diag[:, :-1] += gy + gy_w
        diag[:, 1:] += gy + gy_w
        diag[-1, :] += robin_g
        diag[:, -1] += 2 * k[:, -1]

        # radiation from the wire, absorbed by the foam faces it sees
        foam = phi > 0.5
        src = np.zeros_like(T)
        q_rad_abs = 0.0
        e_rad = current**2 * float(resistance_per_m(t_w, s)) - own(t_w)
        if e_rad > 0:
            w = np.zeros_like(T)
            # face between cell i (foam) and i−1 (gas): normal −x; and the mirror cases
            fx = foam[1:, :] & ~foam[:-1, :] & ~wire_mask[1:, :]
            w[1:, :] += np.where(fx, np.maximum(0.0, -rad_dir[0][1:, :]), 0.0)
            bx = foam[:-1, :] & ~foam[1:, :] & ~wire_mask[:-1, :]
            w[:-1, :] += np.where(bx, np.maximum(0.0, rad_dir[0][:-1, :]), 0.0)
            fy = foam[:, 1:] & ~foam[:, :-1] & ~wire_mask[:, 1:]
            w[:, 1:] += np.where(fy, np.maximum(0.0, -rad_dir[1][:, 1:]), 0.0)
            w *= d / (2 * math.pi * np.maximum(R, rw))
            tot = 2.0 * float(np.sum(w))                           # both halves
            if tot > 1.0:
                w /= tot
                tot = 1.0
            src = w * e_rad
            q_rad_abs = tot * e_rad

        b = store * T + src
        b[-1, :] += robin_g * tinf
        b[:, -1] += 2 * k[:, -1] * tinf
        tw_field = np.where(wire_mask, t_w, 0.0)
        b[:-1, :] += gx_w * tw_field[1:, :]
        b[1:, :] += gx_w * tw_field[:-1, :]
        b[:, :-1] += gy_w * tw_field[:, 1:]
        b[:, 1:] += gy_w * tw_field[:, :-1]

        # 3) implicit diffusion over the step
        T, _ = _pcg(diag, gx, gy, b, T, free, 1e-3, 600)
        # heat the wire gave over the step (measured before the melt step reassigns temperatures)
        q_cond = 2.0 * float(np.sum(gx_w * (t_w - np.where(wire_mask[1:, :], T[:-1, :], T[1:, :])))
                             + np.sum(gy_w * (t_w - np.where(wire_mask[:, 1:], T[:, :-1], T[:, 1:]))))

        # 4) melt: heat above the isotherm goes into the latent heat first
        over = (phi > 0) & (T > tiso) & free
        if np.any(over):
            e = cap[over] * (T[over] - tiso)
            ph = phi[over] - e / rl_f
            left = np.maximum(-ph, 0.0) * rl_f
            ph = np.maximum(ph, 0.0)
            cap_g = RHO_AIR_T * CP_AIR / tiso
            phi[over] = ph
            T[over] = np.where(ph > 0, tiso, tiso + left / (cap_g + ph * rc_f))

        # 5) the wire
        q_cut = q_cond + q_rad_abs + q_contact
        if wire == "joule":
            g_lin = 2.0 * float(np.sum(gx_w) + np.sum(gy_w))
            d_own = own(t_w + 0.5) - own(t_w - 0.5)
            net = own(t_w) - q_cond - q_contact
            t_w = t_w + dt * net / (c_wire + dt * max(g_lin - d_own, 0.0))
            t_w = min(max(t_w, tinf), s.wire.max_temp_c + 600 + K0)
        T[wire_mask] = t_w

        step += 1
        rm_now, kerf_now = measures()
        hist_t.append(step * dt)
        hist_rm.append(rm_now)
        hist_kerf.append(kerf_now)
        hist_tw.append(t_w)
        hist_q.append(q_cut)
        touched.append(q_contact > 0)

        if step >= min_steps and step % max(4, n_transit // 8) == 0:
            lag = max(4, n_transit // 4)
            a = np.array([hist_rm[-lag], hist_kerf[-lag], hist_tw[-lag] - tinf])
            bb = np.array([rm_now, kerf_now, t_w - tinf])
            if np.all(np.abs(bb - a) <= tol * np.maximum(np.abs(bb), 1e-9)):
                converged = True
                break
        if progress is not None and step % 5 == 0:
            msg = (f"2-D solve {step * dt:.1f} s simulated · r_m {rm_now * 1e3:.3f} mm · "
                   f"kerf {kerf_now * 1e3:.2f} mm · wire {t_w - K0:.0f} °C")
            if not progress(min(0.99, step / max_steps), msg):
                raise InterruptedError("cancelled")

    rm_f, kerf_f = measures()
    q_mean = float(np.mean(hist_q[-max(4, n_transit // 4):]))
    # touching now and then is the staircase wire grazing a front one cell away; contact is a closed gap
    gap = rm_f - rw
    contact = gap < max(s.calib.contact_gap_mm * 1e-3, 0.5 * d) or float(np.mean(touched[-max(4, n_transit // 2):])) > 0.5
    half_wall = np.sum(1.0 - phi, axis=1) * d
    full_t = np.concatenate([T[:, ::-1], T], axis=1) - K0
    full_phi = np.concatenate([phi[:, ::-1], phi], axis=1)
    full_y = np.concatenate([-y[::-1], y])
    if progress is not None:
        progress(1.0, "2-D solve done")
    return Thermal2DResult(
        v_mm_s=v_mm_s, x_mm=x * 1e3, y_mm=full_y * 1e3, t_c=full_t, phi=full_phi, wall_mm=half_wall * 1e3,
        r_m_mm=rm_f * 1e3, kerf_mm=kerf_f * 1e3, t_wire_c=t_w - K0, q_cut_w_m=q_mean, current_a=current,
        contact=contact, stall=t_w <= tiso + 1.0, converged=converged, steps=step,
        sim_time_s=step * dt, runtime_s=time.perf_counter() - t0, cell_um=d * 1e6,
        hist_t=np.array(hist_t), hist_rm=np.array(hist_rm) * 1e3, hist_kerf=np.array(hist_kerf) * 1e3,
        hist_tw=np.array(hist_tw) - K0, hist_q=np.array(hist_q), model_r_m_mm=float(st.r_m_mm), model_kerf_mm=float(st.kerf_mm),
        model_t_wire_c=float(st.t_foam_c),
    )
