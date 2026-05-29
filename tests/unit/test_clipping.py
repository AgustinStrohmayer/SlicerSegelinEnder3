from __future__ import annotations

from appSlicerSegelin.v2.core.clipping import clip_segment_to_rect, clip_segments_to_rect
from appSlicerSegelin.v2.core.geometry import Point, Segment


def test_segment_fully_inside_is_unchanged():
    s = Segment(Point(2, 2), Point(5, 5))
    clipped = clip_segment_to_rect(s, 0, 0, 10, 10)
    assert clipped is not None
    assert clipped.a == s.a
    assert clipped.b == s.b


def test_segment_fully_outside_returns_none():
    s = Segment(Point(-5, -5), Point(-1, -1))
    assert clip_segment_to_rect(s, 0, 0, 10, 10) is None


def test_segment_clipped_at_one_end():
    s = Segment(Point(-2, 5), Point(5, 5))
    clipped = clip_segment_to_rect(s, 0, 0, 10, 10)
    assert clipped is not None
    assert clipped.a == Point(0.0, 5.0)
    assert clipped.b == Point(5.0, 5.0)


def test_horizontal_segment_no_division_by_zero():
    # dz == 0; legacy code would divide by zero. New code treats as parallel.
    s = Segment(Point(-5, 5), Point(15, 5))
    clipped = clip_segment_to_rect(s, 0, 0, 10, 10)
    assert clipped is not None
    assert clipped.a == Point(0.0, 5.0)
    assert clipped.b == Point(10.0, 5.0)


def test_vertical_segment_no_division_by_zero():
    s = Segment(Point(5, -5), Point(5, 15))
    clipped = clip_segment_to_rect(s, 0, 0, 10, 10)
    assert clipped is not None
    assert clipped.a == Point(5.0, 0.0)
    assert clipped.b == Point(5.0, 10.0)


def test_clip_segments_filters_degenerate_results():
    segs = [
        Segment(Point(-1, -1), Point(-2, -2)),  # outside
        Segment(Point(2, 2), Point(8, 8)),  # inside
    ]
    out = clip_segments_to_rect(segs, 0, 0, 10, 10)
    assert len(out) == 1


def test_segment_touching_edge_only():
    # Endpoint exactly on edge — should be considered inside.
    s = Segment(Point(0, 5), Point(10, 5))
    clipped = clip_segment_to_rect(s, 0, 0, 10, 10)
    assert clipped is not None
    assert clipped.a == Point(0.0, 5.0)
    assert clipped.b == Point(10.0, 5.0)


def test_bad_rect_returns_none():
    s = Segment(Point(0, 0), Point(1, 1))
    assert clip_segment_to_rect(s, 10, 10, 0, 0) is None
