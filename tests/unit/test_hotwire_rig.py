"""Parametric hot-wire rig: geometry, cut checks and per-frame pose."""
from __future__ import annotations

import math
from dataclasses import replace

import pytest

from appSlicerSegelin.v2.core.gcode_reader import parse_gcode
from appSlicerSegelin.v2.core.hotwire_rig import PRESETS, FoamBlock, HotWireRig, check_cut, fit_block, machine_pose


def _profile(height: float) -> str:
    """Lead in along +Y, a closed lens-shaped contour ``height`` tall, back out the same way."""
    pts = [(10 + 180 * k / 20, height * math.sin(math.pi * k / 20)) for k in range(21)]
    pts += [(10 + 180 * k / 20, -1.0 * math.sin(math.pi * k / 20)) for k in range(20, -1, -1)]
    body = "\n".join(f"G1 Y{y:.3f} Z{z:.3f}" for y, z in pts)
    return f"G92 Y0 Z0\nG1 F600 Y10 Z0\n{body}\nG1 Y0 Z0\n"


def test_arm_geometry():
    r = HotWireRig()
    assert r.wire_drop == pytest.approx(70 * math.sin(math.radians(70)))
    assert r.wire_span == pytest.approx(140.6 + 140 * math.cos(math.radians(70)))
    assert r.spring_span < r.pivot_spacing < r.wire_span
    assert r.nozzle_clearance == pytest.approx(r.wire_drop - 39.5)
    assert r.usable_width(0) > r.usable_width(40) > 0
    assert r.arm_clearance_at(0) > 0 and r.arm_clearance_at(r.wire_span) == 0


def test_long_arms_lower_the_wire_only():
    short, long_ = PRESETS["Ender-3"], PRESETS["Ender-3 (long arms)"]
    assert long_.nozzle_clearance - short.nozzle_clearance == pytest.approx(40 * math.sin(math.radians(70)))
    assert long_.spring_span == pytest.approx(short.spring_span)


def test_full_block_needs_long_arms():
    tp = parse_gcode(_profile(40.0))
    block = FoamBlock(length_y=200, height_z=50, width_x=150, y0=5, z0=-6, spacer=10)
    issues = check_cut(PRESETS["Ender-3"], block, tp)
    assert any("collide" in i for i in issues)
    assert check_cut(PRESETS["Ender-3 (long arms)"], block, tp) == []


def test_travel_and_size_checks():
    tp = parse_gcode("G92 Y0 Z0\nG1 F600 Y400 Z0\n")
    issues = check_cut(HotWireRig(), FoamBlock(length_y=420, height_z=10, width_x=300, y0=-5, z0=-5), tp)
    text = " ".join(issues)
    assert "Y travel" in text and "wire span" in text and "overhangs" in text and "starts inside" in text


def test_fit_block_puts_front_face_on_the_lead_in():
    tp = parse_gcode(_profile(20.0))
    b = fit_block(tp, margin_y=5, margin_z=5)
    assert b.y0 == pytest.approx(5.0)
    assert b.z0 == pytest.approx(-1.0)
    assert b.y1 == pytest.approx(195.0)
    assert check_cut(PRESETS["Ender-3"], replace(b, spacer=10), tp) == []


def test_machine_pose_follows_the_wire():
    tp = parse_gcode(_profile(40.0))
    block = FoamBlock(length_y=200, height_z=50, width_x=150, y0=5, z0=-6)
    p0 = machine_pose(PRESETS["Ender-3"], block, tp, 0.0)
    assert (p0.bed_shift, p0.wire_height) == pytest.approx((0.0, 6.0))
    t = tp.moves[10].t1
    p = machine_pose(PRESETS["Ender-3"], block, tp, t)
    assert p.bed_shift == pytest.approx(-tp.moves[10].y1)
    assert p.wire_height == pytest.approx(tp.moves[10].z1 + 6.0)
    assert p.pivot_height - p.wire_height == pytest.approx(PRESETS["Ender-3"].wire_drop)
    assert not p.carriage_hits_block  # wire at the top: the nozzle clears the block
    low = tp.moves[0].t1  # wire at the bottom, just inside the block
    assert machine_pose(PRESETS["Ender-3"], block, tp, low).carriage_hits_block  # 26 mm under a 50 mm block
    assert not machine_pose(PRESETS["Ender-3 (long arms)"], block, tp, low).carriage_hits_block


def test_arm_tips_need_a_spacer():
    rig = PRESETS["Ender-3 (long arms)"]
    a = math.radians(rig.arm_angle_deg)
    assert rig.arm_reach_below_wire == pytest.approx(5 * math.sin(a) + 7 * math.cos(a))  # 7.1 mm at 70°
    tp = parse_gcode(_profile(20.0))
    b = fit_block(tp)  # bottom face at the lowest pass: the wire skims the bed
    assert any("spacer of at least 7 mm" in i for i in check_cut(rig, b, tp))
    assert check_cut(rig, replace(b, spacer=8), tp) == []
    p = machine_pose(rig, replace(b, spacer=8), tp, 0.0)
    assert p.wire_height == pytest.approx(tp.start[1] - b.z0 + 8)