"""Kerf compensation: the wire runs half a kerf away from the part, so it keeps its drawn size."""
from __future__ import annotations

import pytest

from appSlicerSegelin.v2.core.geometry import BBox, Point, Segment
from appSlicerSegelin.v2.core.kerf import compensate_kerf
from appSlicerSegelin.v2.core.project import Project
from appSlicerSegelin.v2.services import slicer_service


def _loop(pts):
    return [Segment(Point(*a), Point(*b)) for a, b in zip(pts, pts[1:] + pts[:1], strict=True)]


SQUARE = [(0, 0), (100, 0), (100, 50), (0, 50)]
HOLE = [(40, 20), (40, 30), (60, 30), (60, 20)]  # drawn the other way round on purpose


def _box(segs):
    return BBox.from_segments(segs)


def test_outer_contour_grows_and_hole_shrinks():
    out = compensate_kerf(_loop(SQUARE) + _loop(HOLE), 0.5)
    outer = _box(out)
    assert (outer.min_y, outer.min_z, outer.max_y, outer.max_z) == pytest.approx((-0.5, -0.5, 100.5, 50.5))
    hole = _box([s for s in out if 30 < s.a.y < 70 and 10 < s.a.z < 40])
    assert (hole.min_y, hole.min_z, hole.max_y, hole.max_z) == pytest.approx((40.5, 20.5, 59.5, 29.5))


def test_corners_stay_half_a_kerf_away():
    out = compensate_kerf(_loop(SQUARE), 0.5)
    corner = Point(100, 50)
    assert min(s.a.distance_to(corner) for s in out) == pytest.approx(0.5)  # round join, not a cut-in bevel
    assert out[0].a.distance_to(out[-1].b) < 1e-9  # still closed


def test_tiny_hole_and_open_lines_are_left_alone():
    tiny = [(10, 10), (10.4, 10), (10.4, 10.4), (10, 10.4)]
    line = [Segment(Point(0, 60), Point(50, 60))]
    out = compensate_kerf(_loop(SQUARE) + _loop(tiny) + line, 0.5)
    assert _box([s for s in out if 9 < s.a.y < 11 and 9 < s.a.z < 11]) == _box(_loop(tiny))
    assert line[0] in out
    assert compensate_kerf(_loop(SQUARE), 0.0) == _loop(SQUARE)


def test_the_project_trajectory_uses_it():
    p = Project(segments=_loop(SQUARE))
    plain = _box(slicer_service.standard_trajectory(p))
    p.kerf_comp_mm = 0.4
    moved = _box([s for s in slicer_service.standard_trajectory(p) if s.kind.value == "cut"])
    assert moved.max_y == pytest.approx(plain.max_y + 0.4)
