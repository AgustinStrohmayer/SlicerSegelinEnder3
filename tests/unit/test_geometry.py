from __future__ import annotations

import math

from appSlicerSegelin.v2.core.geometry import BBox, Path, Point, Segment, SegmentKind


def test_point_distance_and_translation():
    a = Point(0, 0)
    b = Point(3, 4)
    assert math.isclose(a.distance_to(b), 5.0)
    assert a.translate(1, 2) == Point(1, 2)


def test_segment_length_and_degenerate():
    s = Segment(Point(0, 0), Point(3, 4))
    assert math.isclose(s.length, 5.0)
    assert not s.is_degenerate
    assert Segment(Point(0, 0), Point(0, 0)).is_degenerate


def test_segment_reversed_preserves_kind():
    s = Segment(Point(1, 2), Point(3, 4), SegmentKind.ENTRY)
    assert s.reversed() == Segment(Point(3, 4), Point(1, 2), SegmentKind.ENTRY)


def test_bbox_from_segments_and_center():
    segs = [
        Segment(Point(0, 0), Point(10, 0)),
        Segment(Point(10, 0), Point(10, 5)),
    ]
    bbox = BBox.from_segments(segs)
    assert bbox == BBox(0, 0, 10, 5)
    assert bbox.center() == Point(5, 2.5)


def test_bbox_center_returns_none_for_degenerate():
    bbox = BBox.from_segments([Segment(Point(1, 1), Point(1, 1))])
    assert bbox is not None
    assert bbox.is_degenerate
    assert bbox.center() is None


def test_path_from_points_closed_appends_closing_segment():
    pts = [Point(0, 0), Point(10, 0), Point(10, 10)]
    path = Path.from_points(pts, closed=True)
    assert len(path) == 3
    assert path.segments[-1].b == pts[0]


def test_path_endpoints():
    p = Path.from_points([Point(0, 0), Point(1, 0), Point(1, 1)])
    head, tail = p.endpoints()  # type: ignore[misc]
    assert head == Point(0, 0)
    assert tail == Point(1, 1)
