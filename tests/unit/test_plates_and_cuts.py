from __future__ import annotations

from appSlicerSegelin.v2.core.geometry import Point, Segment
from appSlicerSegelin.v2.core.manual_cuts import (
    CutKind,
    line_from_two_points,
    make_two_point_cut,
    make_y_cut,
    make_z_cut,
    snap_segments,
    split_segment_by_line,
)
from appSlicerSegelin.v2.core.plates import partition_by_manual_cuts, split_into_plates


def _line(y1, z1, y2, z2):
    return Segment(Point(y1, z1), Point(y2, z2))


def _rect(width, height):
    return [
        _line(0, 0, width, 0),
        _line(width, 0, width, height),
        _line(width, height, 0, height),
        _line(0, height, 0, 0),
    ]


# ── manual cut primitives ────────────────────────────────────────────


def test_make_y_cut_line_equation():
    cut = make_y_cut(50.0)
    assert cut.kind == CutKind.Y
    assert cut.a == 1.0 and cut.b == 0.0 and cut.c_base == -50.0


def test_make_z_cut_line_equation():
    cut = make_z_cut(30.0)
    assert cut.kind == CutKind.Z
    assert cut.a == 0.0 and cut.b == 1.0 and cut.c_base == -30.0


def test_two_point_cut_and_line_normalised():
    line = line_from_two_points(Point(0, 0), Point(10, 0))
    assert line is not None
    a, b, _c = line
    assert abs(a * a + b * b - 1.0) < 1e-9  # normalised
    assert make_two_point_cut(Point(0, 0), Point(0, 0)) is None  # degenerate


def test_split_segment_by_vertical_line():
    seg = _line(0, 0, 100, 0)
    parts = split_segment_by_line(seg, 1.0, 0.0, -50.0)  # y = 50
    assert len(parts) == 2
    assert parts[0].b == Point(50.0, 0.0)


def test_split_segment_not_crossing_is_unchanged():
    seg = _line(0, 0, 10, 0)
    parts = split_segment_by_line(seg, 1.0, 0.0, -50.0)
    assert parts == [seg]


def test_snap_segments_merges_near_nodes():
    segs = [_line(0, 0, 10, 0), _line(10.000001, 0, 20, 0)]
    snapped = snap_segments(segs)
    assert snapped[0].b == snapped[1].a


# ── plate splitting ──────────────────────────────────────────────────


def test_split_into_plates_single_plate_when_fits():
    geom = _rect(100, 50)
    layers = split_into_plates(geom, plate_y=220, plate_z=100)
    assert len(layers) == 1
    assert layers[0].trajectory  # has a full trajectory


def test_split_into_plates_multiple_columns_when_too_wide():
    geom = _rect(500, 50)  # wider than usable 200mm (220-20)
    layers = split_into_plates(geom, plate_y=220, plate_z=100)
    assert len(layers) >= 3


def test_split_into_plates_rejects_tiny_plate():
    geom = _rect(100, 50)
    assert split_into_plates(geom, plate_y=15, plate_z=100) == []  # <20mm Y


def test_split_into_plates_empty_geometry():
    assert split_into_plates([], 220, 100) == []


# ── manual partitioning ──────────────────────────────────────────────


def test_partition_by_manual_y_cut_makes_two_parts():
    geom = _rect(100, 50)
    cut = make_y_cut(50.0)
    layers = partition_by_manual_cuts(geom, [cut], offset_y=0.0, offset_z=0.0)
    assert len(layers) >= 2


def test_partition_no_cuts_returns_empty():
    geom = _rect(100, 50)
    assert partition_by_manual_cuts(geom, [], 0.0, 0.0) == []
