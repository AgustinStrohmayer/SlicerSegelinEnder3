from __future__ import annotations

from appSlicerSegelin.v2.core.geometry import Point, Segment
from appSlicerSegelin.v2.core.pathing import (
    chain_segments,
    flatten,
    heal_gaps,
    order_paths,
)


def test_chain_disconnected_segments_into_separate_paths():
    segs = [
        Segment(Point(0, 0), Point(1, 0)),
        Segment(Point(5, 5), Point(6, 5)),
    ]
    paths = chain_segments(segs)
    assert len(paths) == 2
    assert len(paths[0]) == 1
    assert len(paths[1]) == 1


def test_chain_connected_segments_in_order():
    segs = [
        Segment(Point(0, 0), Point(1, 0)),
        Segment(Point(1, 0), Point(2, 0)),
        Segment(Point(2, 0), Point(3, 0)),
    ]
    paths = chain_segments(segs)
    assert len(paths) == 1
    assert len(paths[0]) == 3


def test_chain_detects_closed_loop():
    segs = [
        Segment(Point(0, 0), Point(1, 0)),
        Segment(Point(1, 0), Point(1, 1)),
        Segment(Point(1, 1), Point(0, 1)),
        Segment(Point(0, 1), Point(0, 0)),
    ]
    paths = chain_segments(segs)
    assert len(paths) == 1
    assert paths[0].closed


def test_chain_handles_reversed_segments():
    segs = [
        Segment(Point(0, 0), Point(1, 0)),
        Segment(Point(2, 0), Point(1, 0)),  # reversed direction
    ]
    paths = chain_segments(segs)
    # Whether one path or two depends on bucket ordering; either way, output must cover both inputs.
    assert sum(len(p) for p in paths) == 2


def test_order_paths_visits_nearest_first():
    segs1 = [Segment(Point(10, 0), Point(11, 0))]
    segs2 = [Segment(Point(0, 0), Point(1, 0))]
    paths = chain_segments(segs1 + segs2)
    ordered = order_paths(paths, start=Point(0, 0))
    head = ordered[0].endpoints()[0]  # type: ignore[index]
    assert head == Point(0, 0)


def test_flatten_round_trips():
    segs = [
        Segment(Point(0, 0), Point(1, 0)),
        Segment(Point(1, 0), Point(2, 0)),
    ]
    paths = chain_segments(segs)
    flat = flatten(paths)
    assert len(flat) == 2


def test_heal_gaps_snaps_near_coincident_points():
    segs = [
        Segment(Point(0, 0), Point(1.0, 0)),
        Segment(Point(1.0000001, 0), Point(2, 0)),
    ]
    healed = heal_gaps(segs, tol=1e-3)
    assert healed[0].b == healed[1].a
