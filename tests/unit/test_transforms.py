from __future__ import annotations

import math

import pytest

from appSlicerSegelin.v2.core.errors import GeometryError
from appSlicerSegelin.v2.core.geometry import Point, Segment
from appSlicerSegelin.v2.core.transforms import (
    Affine2D,
    align_to_origin,
    apply,
    mirror_horizontal,
    mirror_vertical,
    rotate_around,
    rotate_around_center,
    translate,
)


def _square():
    return [
        Segment(Point(0, 0), Point(10, 0)),
        Segment(Point(10, 0), Point(10, 10)),
        Segment(Point(10, 10), Point(0, 10)),
        Segment(Point(0, 10), Point(0, 0)),
    ]


def test_rotation_360_degrees_is_identity():
    segs = _square()
    rotated = rotate_around_center(segs, 360)
    for a, b in zip(segs, rotated):
        assert math.isclose(a.a.y, b.a.y, abs_tol=1e-9)
        assert math.isclose(a.a.z, b.a.z, abs_tol=1e-9)


def test_rotation_180_flips_through_center():
    segs = _square()
    rotated = rotate_around_center(segs, 180)
    # (0,0) → (10,10); (10,0) → (0,10)
    assert math.isclose(rotated[0].a.y, 10, abs_tol=1e-9)
    assert math.isclose(rotated[0].a.z, 10, abs_tol=1e-9)


def test_rotation_inverse_round_trips():
    segs = _square()
    rotated = rotate_around_center(segs, 37.5)
    back = rotate_around_center(rotated, -37.5)
    for a, b in zip(segs, back):
        assert math.isclose(a.a.y, b.a.y, abs_tol=1e-6)
        assert math.isclose(a.a.z, b.a.z, abs_tol=1e-6)


def test_rotation_degenerate_geometry_raises():
    segs = [Segment(Point(5, 5), Point(5, 5))]
    with pytest.raises(GeometryError):
        rotate_around_center(segs, 90)


def test_rotation_around_explicit_pivot():
    segs = [Segment(Point(1, 0), Point(2, 0))]
    rotated = rotate_around(segs, 90, Point(0, 0))
    assert math.isclose(rotated[0].a.y, 0, abs_tol=1e-9)
    assert math.isclose(rotated[0].a.z, 1, abs_tol=1e-9)
    assert math.isclose(rotated[0].b.y, 0, abs_tol=1e-9)
    assert math.isclose(rotated[0].b.z, 2, abs_tol=1e-9)


def test_mirror_horizontal_is_involutive():
    segs = _square()
    twice = mirror_horizontal(mirror_horizontal(segs))
    for a, b in zip(segs, twice):
        assert a.as_tuple() == pytest.approx(b.as_tuple(), abs=1e-9)


def test_mirror_vertical_is_involutive():
    segs = _square()
    twice = mirror_vertical(mirror_vertical(segs))
    for a, b in zip(segs, twice):
        assert a.as_tuple() == pytest.approx(b.as_tuple(), abs=1e-9)


def test_translate_then_align_origin_is_identity_for_origin_geometry():
    segs = _square()
    moved = translate(segs, 5.0, -3.0)
    realigned = align_to_origin(moved)
    for a, b in zip(segs, realigned):
        assert a.as_tuple() == pytest.approx(b.as_tuple(), abs=1e-9)


def test_affine_composition_is_associative():
    a = Affine2D.rotation(30)
    b = Affine2D.translation(5, 7)
    c = Affine2D.mirror_y(0)
    p = Point(3, 4)
    left = a.then(b).then(c).apply(p)
    right = a.then(b.then(c)).apply(p)
    assert math.isclose(left.y, right.y, abs_tol=1e-9)
    assert math.isclose(left.z, right.z, abs_tol=1e-9)


def test_apply_preserves_segment_kind():
    from appSlicerSegelin.v2.core.geometry import SegmentKind

    segs = [Segment(Point(0, 0), Point(1, 1), SegmentKind.ENTRY)]
    transformed = apply(segs, Affine2D.translation(10, 10))
    assert transformed[0].kind == SegmentKind.ENTRY
