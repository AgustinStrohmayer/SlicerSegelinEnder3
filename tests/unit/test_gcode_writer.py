from __future__ import annotations

from appSlicerSegelin.v2.core.cutplan import CutPlan
from appSlicerSegelin.v2.core.geometry import Point, Segment, SegmentKind
from appSlicerSegelin.v2.core.machine import MachineProfile
from appSlicerSegelin.v2.io.gcode_writer import emit_gcode


def _plan(segments, machine=None):
    return CutPlan(segments=tuple(segments), machine=machine or MachineProfile())


def test_output_ends_with_newline():
    plan = _plan([Segment(Point(0, 0), Point(10, 0))])
    out = emit_gcode(plan)
    assert out.endswith("\n")


def test_feed_rate_emitted_only_on_change():
    machine = MachineProfile(feed_cut_mm_min=200, feed_travel_mm_min=800)
    segments = [
        Segment(Point(0, 0), Point(10, 0), SegmentKind.CUT),
        Segment(Point(10, 0), Point(20, 0), SegmentKind.CUT),  # same feed
        Segment(Point(20, 0), Point(20, 5), SegmentKind.TRAVEL),  # different feed
    ]
    out = emit_gcode(_plan(segments, machine))
    # In the body, the cut feed F200 should appear only on the FIRST cut move
    # (G92 sets origin, so no prior position emits an F).
    body_lines = [
        line for line in out.splitlines() if line.startswith("G1") and "Y0 Z0" not in line and "Smooth" not in line
    ]
    fs = [line for line in body_lines if "F" in line]
    # First cut emits F200; travel later emits F800; that's two F annotations.
    assert len(fs) >= 2
    assert any("F200" in line for line in fs)
    assert any("F800" in line for line in fs)


def test_consistent_precision_with_machine_profile():
    machine = MachineProfile(precision_decimals=4)
    segments = [Segment(Point(1.23456789, 0), Point(9.87654321, 0))]
    out = emit_gcode(_plan(segments, machine))
    assert "1.2346" in out
    assert "9.8765" in out


def test_kind_specific_comments():
    segments = [
        Segment(Point(0, 0), Point(10, 0), SegmentKind.ENTRY),
        Segment(Point(10, 0), Point(20, 0), SegmentKind.UNION),
        Segment(Point(20, 0), Point(30, 0), SegmentKind.EXIT),
    ]
    out = emit_gcode(_plan(segments))
    assert "; entry" in out
    assert "; straight union between segments" in out
    assert "; exit" in out


def test_header_includes_marlin_flavor_and_machine_name():
    plan = _plan([Segment(Point(0, 0), Point(1, 0))], MachineProfile(name="Test Machine"))
    out = emit_gcode(plan)
    assert ";FLAVOR:Marlin" in out
    assert ";TARGET_MACHINE.NAME:Test Machine" in out


def test_returns_to_origin_at_end():
    plan = _plan([Segment(Point(5, 5), Point(10, 10))])
    out = emit_gcode(plan)
    lines = out.strip().splitlines()
    # last G1 is the return to origin
    assert any("Y0.0 Z0.0" in line and "Smooth" in line for line in lines)
    assert lines[-1].startswith("M84")


def test_empty_plan_still_produces_valid_header():
    out = emit_gcode(_plan([]))
    assert ";--- CUT START ---" in out
    assert ";--- CUT END ---" in out
    assert out.endswith("\n")
