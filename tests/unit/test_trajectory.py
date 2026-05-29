from __future__ import annotations

import itertools
import math

from appSlicerSegelin.v2.core.geometry import Point, Segment, SegmentKind
from appSlicerSegelin.v2.core.trajectory import (
    build_cut_path,
    build_full_trajectory,
    total_duration,
    trajectory_durations,
)


def _line(y1, z1, y2, z2):
    return Segment(Point(y1, z1), Point(y2, z2))


def test_cut_path_starts_from_leftmost_point():
    segs = [_line(10, 0, 20, 0), _line(0, 0, 10, 0)]
    path = build_cut_path(segs)
    assert path[0].a == Point(0, 0)
    assert path[-1].b == Point(20, 0)


def test_cut_path_chains_in_continuity_order():
    segs = [_line(0, 0, 10, 0), _line(10, 0, 10, 10), _line(10, 10, 0, 10)]
    path = build_cut_path(segs)
    assert len(path) == 3
    # endpoints must connect
    for a, b in itertools.pairwise(path):
        assert a.b.distance_to(b.a) < 1e-6


def test_cut_path_reverse_flips_direction():
    segs = [_line(0, 0, 10, 0), _line(10, 0, 20, 0)]
    forward = build_cut_path(segs)
    backward = build_cut_path(segs, reverse=True)
    assert forward[0].a == backward[-1].b
    assert backward[0].a == forward[-1].b


def test_full_trajectory_has_entry_and_exit_margins():
    segs = [_line(0, 0, 10, 0)]
    traj = build_full_trajectory(segs, entry_exit_mm=10.0)
    kinds = [s.kind for s in traj]
    assert SegmentKind.ENTRY in kinds
    assert SegmentKind.EXIT in kinds
    entry = next(s for s in traj if s.kind == SegmentKind.ENTRY)
    # entry approaches the start point from 10mm before it
    assert math.isclose(entry.a.y, -10.0)
    assert entry.b == Point(0, 0)


def test_full_trajectory_returns_to_start_when_z_differs():
    segs = [_line(0, 0, 10, 10)]
    traj = build_full_trajectory(segs)
    kinds = [s.kind for s in traj]
    assert SegmentKind.RETURN_H in kinds
    assert SegmentKind.RETURN_V in kinds


def test_full_trajectory_unions_bridge_disjoint_pieces():
    segs = [_line(0, 0, 10, 0), _line(20, 0, 30, 0)]
    traj = build_full_trajectory(segs, add_unions=True)
    assert any(s.kind == SegmentKind.UNION for s in traj)


def test_durations_scale_with_speed():
    traj = [_line(0, 0, 100, 0)]  # 100 mm
    assert total_duration(traj, 10.0) == 10.0
    assert total_duration(traj, 20.0) == 5.0
    assert trajectory_durations(traj, 0.0) == []


def test_empty_segments_give_empty_trajectory():
    assert build_cut_path([]) == []
    assert build_full_trajectory([]) == []
