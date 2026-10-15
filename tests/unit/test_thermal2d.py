"""2-D thermal solve of the cut: agreement with the reduced model, energy balance, cancellation."""
from __future__ import annotations

import numpy as np
import pytest

from appSlicerSegelin.v2.core.cutting_physics import K0, CutSetup, air_conductivity, point_state, removal_energy
from appSlicerSegelin.v2.core.thermal2d import solve_section, window_for

SPEEDS = (1.0, 2.0, 4.0)


@pytest.fixture(scope="module")
def fixed_sweep():
    s = CutSetup()
    return s, [solve_section(s, v, quality="coarse", wire="fixed") for v in SPEEDS]


def test_kerf_trend_with_speed_follows_the_reduced_model(fixed_sweep):
    """Same wire temperature as the model: the 2-D kerf falls with feed like the model's, within a factor."""
    s, runs = fixed_sweep
    k2d = np.array([r.kerf_mm for r in runs])
    k0 = np.array([float(point_state(s, v).kerf_mm) for v in SPEEDS])
    assert np.all(np.diff(k2d) < 0)
    assert np.all((k2d / k0 > 0.5) & (k2d / k0 < 1.5))
    slope2d = np.polyfit(np.log(SPEEDS), np.log(k2d), 1)[0]
    slope0 = np.polyfit(np.log(SPEEDS), np.log(k0), 1)[0]
    assert slope2d < 0 and 0.67 < slope2d / slope0 < 1.5
    # the front sits closer to the wire than the closed form says, and the walls keep receding behind it:
    # the 2-D kerf is wider than 2·r_m (the model's κ > 1)
    for r in runs:
        assert r.converged and not r.stall
        assert r.r_m_mm < r.model_r_m_mm
        assert r.kerf_mm > 2.2 * r.r_m_mm


def test_energy_balance_closes(fixed_sweep):
    """Heat from the wire = foam removed + heat carried out in the walls + heat through the side boundary."""
    s, runs = fixed_sweep
    r = runs[1]
    f = s.foam
    d, v = r.cell_um * 1e-6, r.v_mm_s * 1e-3
    ny = r.t_c.shape[1] // 2
    T, phi = r.t_c[:, ny:] + K0, r.phi[:, ny:]
    tinf = s.ambient_c + K0
    rc = f.density_kg_m3 * f.specific_heat_j_kgk
    cap = phi * rc + (1 - phi) * 353 * 1010 / T
    removed = removal_energy(s) * v * r.kerf_mm * 1e-3
    walls = 2 * v * float(np.sum(cap[0] * (T[0] - tinf))) * d
    k = phi * f.conductivity_w_mk + (1 - phi) * air_conductivity(T)
    side = 2 * float(np.sum(2 * k[:, -1] * (T[:, -1] - tinf)))
    assert removed + walls + side == pytest.approx(r.q_cut_w_m, rel=0.12)
    assert walls > 0.3 * removed  # the heat left in the walls is what the closed form leaves out


def test_joule_wire_with_enough_drive_matches_the_model():
    s = CutSetup(current_a=1.6)
    for v in (2.0, 4.0):
        r = solve_section(s, v, quality="coarse")
        st = point_state(s, v)
        assert not r.contact and not r.stall
        assert 0.6 < r.kerf_mm / float(st.kerf_mm) < 1.4
        assert r.t_wire_c == pytest.approx(float(st.t_foam_c), rel=0.2)
        assert r.current_a == pytest.approx(1.6)


def test_low_drive_fast_feed_closes_the_gap():
    r = solve_section(CutSetup(current_a=1.0), 8.0, quality="coarse")
    assert r.contact or r.stall


def test_window_scales_with_the_melt_radius_and_cancel_raises():
    s = CutSetup()
    slow, fast = window_for(s, 0.5), window_for(s, 8.0)
    assert slow.ahead_m > fast.ahead_m and slow.side_m > fast.side_m
    assert slow.nx * slow.ny <= 30_000 * 1.05
    calls = []

    def stop(f: float, msg: str) -> bool:
        calls.append(msg)
        return False

    with pytest.raises(InterruptedError):
        solve_section(s, 3.0, quality="coarse", progress=stop)
    assert calls and "kerf" in calls[0]
