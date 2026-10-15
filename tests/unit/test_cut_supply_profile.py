"""Bench-supply model (CV/CC with limits), the speed suggestion and the saved Cut Lab settings."""
import json
import math
from dataclasses import replace

from appSlicerSegelin.v2.core import cut_profile
from appSlicerSegelin.v2.core.cutting_physics import CutSetup, contact_speed, point_state
from appSlicerSegelin.v2.ui.widgets.cutlab.typical import recommend


def test_voltage_mode_is_consistent_with_current_mode():
    s = CutSetup(mode="voltage", voltage_v=4.0)
    st = point_state(s, 3.0)
    assert not bool(st.limited)
    cc = point_state(replace(s, mode="current", current_a=float(st.current_a)), 3.0)
    assert math.isclose(float(cc.voltage_v), 4.0, rel_tol=1e-3)
    assert math.isclose(float(cc.t_air_c), float(st.t_air_c), rel_tol=1e-3)


def test_current_limit_caps_cv_and_voltage_limit_caps_cc():
    s = CutSetup(mode="voltage", voltage_v=20.0, current_limit_a=1.0)
    st = point_state(s, 3.0)
    assert bool(st.limited) and math.isclose(float(st.current_a), 1.0, rel_tol=1e-6)
    assert float(st.voltage_v) < 20.0
    c = CutSetup(mode="current", current_a=10.0, voltage_limit_v=3.0)
    sc = point_state(c, 3.0)
    assert bool(sc.limited) and float(sc.voltage_v) <= 3.0 + 1e-6 and float(sc.current_a) < 10.0


def test_recommend_respects_axis_limit_and_clean_margin():
    s = CutSetup(mode="voltage", voltage_v=4.0)
    vc = contact_speed(s)
    capped = recommend(s, vc, vmax_axis=5.0)
    free = recommend(s, vc, vmax_axis=None)
    assert free["v"] <= 0.8 * vc + 1e-9 and free["limit"] == "clean"
    assert capped["v"] <= 5.0
    if 0.8 * vc > 5.0:
        assert capped["limit"] == "axis"


def test_work_settings_round_trip_and_loader(tmp_path):
    p = tmp_path / cut_profile.PROFILE_FILENAME
    assert cut_profile.load_saved_cut_settings(p) is None  # never saved
    work = cut_profile.WorkSettings(work_feed_mm_s=4.2, kerf_mm=0.6, voltage_v=4.0, current_a=1.1)
    cut_profile.save(cut_profile.CutProfile(setup=CutSetup(mode="voltage"), work=work), p)
    got = cut_profile.load_saved_cut_settings(p)
    assert got == work and math.isclose(got.kerf_offset_mm, 0.3)
    p.write_text("{broken", encoding="utf-8")
    assert cut_profile.load_saved_cut_settings(p) is None


def test_v1_current_profile_migrates_to_cv(tmp_path):
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"version": 1, "setup": {"mode": "current", "current_a": 1.2},
                             "probe_speed_mm_s": 3.0}), encoding="utf-8")
    prof = cut_profile.load(p)
    assert prof.setup.mode == "voltage" and prof.setup.voltage_v > 0 and prof.work is None
    cc = point_state(CutSetup(mode="current", current_a=1.2), 3.0)
    assert math.isclose(prof.setup.voltage_v, float(cc.voltage_v), abs_tol=0.01)
