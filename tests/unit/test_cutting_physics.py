"""Wire–foam physics: trends that must hold whatever the calibration."""
from __future__ import annotations

import numpy as np
import pytest

from appSlicerSegelin.v2.core.cutting_physics import (
    CutSetup,
    contact_speed,
    operating_map,
    point_state,
    span_profile,
    wire_time_constant_s,
)


def test_kerf_shrinks_with_speed_and_grows_with_current():
    s = CutSetup()
    v = np.array([0.5, 1, 2, 5])
    k = point_state(s, v).kerf_mm
    assert np.all(np.diff(k) < 0)
    hot = point_state(s, 2.0, current_a=1.6).kerf_mm
    cold = point_state(s, 2.0, current_a=1.0).kerf_mm
    assert hot > cold


def test_kerf_never_below_wire_and_contact_when_fast():
    s = CutSetup()
    st = point_state(s, np.geomspace(0.2, 80, 30))
    assert np.all(st.kerf_mm >= s.diameter_mm - 1e-9)
    assert not st.contact[0] and st.contact[-1]
    vc = contact_speed(s)
    assert 0 < vc < 80
    assert not point_state(s, vc * 0.8).contact and point_state(s, vc * 1.3).contact


def test_wire_temperature_scale_is_plausible():
    # 0.3 mm nichrome at ~1.2 A sits at a few hundred °C in still air
    st = point_state(CutSetup(), 5.0)
    assert 150 < float(st.t_air_c) < 450
    assert float(st.t_foam_c) < float(st.t_air_c)  # cutting draws heat out of the wire
    assert 0.5 < wire_time_constant_s(CutSetup(), float(st.t_air_c)) < 10


def test_voltage_mode_matches_equivalent_current():
    s = CutSetup(mode="voltage", voltage_v=4.0)
    st = point_state(s, 3.0)
    same = point_state(s.with_(mode="current", current_a=float(st.current_a)), 3.0)
    # same current → same in-foam state (voltage mode only differs in how I is set)
    assert float(same.kerf_mm) == pytest.approx(float(st.kerf_mm), rel=0.03)


def test_span_profile_cold_ends_and_symmetry():
    s = CutSetup(block_width_mm=120)
    p = span_profile(s, speeds=[2.0, 5.0], nodes=121)
    t = p.t_c[1]
    assert t[0] == pytest.approx(s.ambient_c, abs=0.5) and t[-1] == pytest.approx(s.ambient_c, abs=0.5)
    assert np.allclose(t, t[::-1], atol=0.5)
    mid = len(t) // 2
    air = np.nonzero(~p.in_foam)[0]
    assert t[air].max() > t[mid]  # the wire in air is hotter than inside the foam
    assert p.kerf_mm[0, mid] > p.kerf_mm[1, mid]


def test_bow_appears_only_past_contact_speed():
    s = CutSetup()
    p = span_profile(s, speeds=[1.0, 60.0], nodes=101)
    mid = 50
    assert p.bow_mm[0, mid] == pytest.approx(0.0, abs=1e-9)
    assert p.bow_mm[1, mid] > 0.1
    assert p.bow_mm[1, mid] >= p.bow_mm[1, 25]  # deepest in the middle


def test_operating_map_shapes():
    m = operating_map(CutSetup(), drive=np.linspace(0.8, 2, 5), speeds=np.array([1.0, 5.0, 20.0]))
    assert m.kerf_mm.shape == (5, 3)
    assert m.kerf_mm[-1, 0] > m.kerf_mm[0, 0]
