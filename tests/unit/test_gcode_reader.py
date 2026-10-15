"""G-code reader used by the machine simulator and the Blender animation."""
from __future__ import annotations

import math

import pytest

from appSlicerSegelin.v2.core.gcode_reader import parse_gcode

SQUARE = """G21
G90
G92 Y0 Z0
G1 F600 Y10 Z0 ; 10 mm at 10 mm/s
G1 Y10 Z10
G0 Y0 Z10
G1 Y0 Z0
"""


def test_moves_and_timing():
    tp = parse_gcode(SQUARE)
    assert len(tp.moves) == 4
    assert tp.total_s == pytest.approx(4.0)
    assert tp.cut_length == pytest.approx(30.0)  # the G0 is a rapid
    assert tp.moves[2].rapid and not tp.moves[0].rapid
    assert tp.bounds() == (0.0, 10.0, 0.0, 10.0)
    assert tp.moves[0].line_no == 4


def test_state_at_interpolates_and_clamps():
    tp = parse_gcode(SQUARE)
    s = tp.state_at(1.5)
    assert (s.y, s.z) == pytest.approx((10.0, 5.0))
    assert s.line_no == 5 and s.move_index == 1
    assert tp.state_at(-1).move_index == -1
    end = tp.state_at(99)
    assert (end.y, end.z, end.elapsed_s) == pytest.approx((0.0, 0.0, 4.0))


def test_polyline_until_stops_mid_move():
    tp = parse_gcode(SQUARE)
    assert tp.polyline_until(1.5) == [(0.0, 0.0), (10.0, 0.0), pytest.approx((10.0, 5.0))]
    assert len(tp.polyline_until(1.5, include_rapid=False)) == 3


def test_relative_inches_and_g92():
    tp = parse_gcode("G92 Y5 Z5\nG20\nG91\nG1 F60 Y1\nG1 Z-1\nG90\nG21\nG1 Y0 Z0\nG92 Y0")
    assert tp.start == (5.0, 5.0)
    assert (tp.moves[0].y1, tp.moves[1].z1) == pytest.approx((30.4, 5 - 25.4))
    assert tp.moves[0].feed_mm_min == pytest.approx(60 * 25.4)
    assert any("G92" in w for w in tp.warnings)


def test_comments_x_axis_and_missing_feed():
    tp = parse_gcode("G1 X50 Y3 Z4 (move) ; comment\nG1 X0\n")
    assert len(tp.moves) == 1  # X is ignored; the X-only move has zero length
    assert tp.moves[0].length == pytest.approx(5.0)
    assert tp.total_s == pytest.approx(5.0 / 10.0)  # default 600 mm/min
    assert any("feed" in w for w in tp.warnings)
    assert math.isclose(parse_gcode("").total_s, 0.0)
