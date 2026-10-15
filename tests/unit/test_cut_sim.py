"""Motion planning, material removal and calibration."""
from __future__ import annotations

import numpy as np
import pytest

from appSlicerSegelin.v2.core.calibration import (
    Measurement,
    StaircaseSpec,
    fit,
    staircase_gcode,
)
from appSlicerSegelin.v2.core.cut_sim import label4, simulate
from appSlicerSegelin.v2.core.cutting_physics import Calibration, CutSetup, point_state
from appSlicerSegelin.v2.core.gcode_reader import parse_gcode
from appSlicerSegelin.v2.core.hotwire_rig import FoamBlock
from appSlicerSegelin.v2.core.motion import MotionLimits, plan

SQUARE = (
    "G92 Y0 Z0\nG1 F180 Y0 Z10\nG1 Y10 Z10\nG1 Y30 Z10\nG1 Y30 Z30\nG1 Y10 Z30\nG1 Y10 Z10\nG1 Y0 Z10\nG1 Y0 Z0\n"
)


def test_motion_respects_axis_limits_and_slows_at_corners():
    tp = parse_gcode(SQUARE)
    m = plan(tp, MotionLimits(vmax_z=2.0))
    assert m.v.max() <= 3.0 + 1e-6
    vertical = np.abs(np.gradient(m.z)) > np.abs(np.gradient(m.y)) * 5
    assert m.v[vertical].max() <= 2.0 + 1e-6
    assert m.total_s > tp.total_s  # acceleration and the Z limit only add time
    corner = np.argmin(np.hypot(m.y - 30, m.z - 10))
    assert m.v[corner] < 1.9  # Marlin junction speed for 90°: sqrt(a·jd·sin(θ/2)/(1−sin(θ/2)))


def test_label4_counts_components():
    a = np.zeros((6, 6), bool)
    a[0:2, 0:2] = True
    a[4:6, 3:6] = True
    a[3, 0] = True
    _, n = label4(a)
    assert n == 3


def test_square_part_is_released_and_shrinks_by_half_kerf():
    tp = parse_gcode(SQUARE)
    block = FoamBlock(length_y=40, height_z=40, width_x=60, y0=5, z0=0)
    res = simulate(tp, block, CutSetup(), n_slices=3, cell_mm=0.05)
    assert all(s.released for s in res.slices)
    mid = res.slices[1]
    expected = float(point_state(CutSetup(), 3.0).kerf_mm) / 2
    assert -mid.stats["dev_mean"] == pytest.approx(expected, rel=0.35)
    assert mid.stats["length_y"] < 20 and mid.stats["length_y"] > 18
    # scrubbing: nothing removed at t=0, everything by the end
    assert not (mid.t_removed <= 0).any()
    assert np.isfinite(mid.t_removed).sum() > 0


def test_staircase_gcode_runs_both_cuts_forward():
    spec = StaircaseSpec(speeds_mm_s=(1, 2, 4))
    tp = parse_gcode(staircase_gcode(spec, "1.2 A"))
    cuts = [m for m in tp.moves if abs(m.z0 - m.z1) < 1e-9 and m.y1 > m.y0 and m.z0 in (12.0, 22.0)]
    feeds = sorted({m.feed_mm_min for m in cuts})
    assert {60, 120, 240} <= set(feeds)
    # the wire travels back over the block, never through it
    back = [m for m in tp.moves if m.y1 < m.y0]
    assert all(min(m.z0, m.z1) >= spec.block_height_mm for m in back)


def test_fit_recovers_synthetic_calibration():
    truth = CutSetup(calib=Calibration(eta=2.0, kappa=1.2))
    data = []
    for amps in (1.0, 1.4):
        for v in (1.0, 2.0, 4.0):
            k = float(point_state(truth, v, current_a=amps).kerf_mm)
            data.append(Measurement(v, amps, "current", thickness_mm=10.0 - k))
    r = fit(CutSetup(), data)
    assert r.eta == pytest.approx(2.0, rel=0.1)
    assert r.kappa == pytest.approx(1.2, rel=0.05)
    assert r.rms_mm < 0.01
