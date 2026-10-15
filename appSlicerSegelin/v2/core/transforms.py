"""Affine transformations on geometry.

Single 2D rotation matrix used everywhere. The legacy app duplicated
the rotation math in multiple methods (``rotar_sobre_origen_corte``,
``rotar_geometria``, etc.) and each one re-derived the centre,
producing inconsistencies on degenerate geometry. Here the matrix
lives in one place and every transform is composable.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from .errors import GeometryError
from .geometry import BBox, Point, Segment


@dataclass(frozen=True, slots=True)
class Affine2D:
    """2x3 affine matrix: ``[[a, b, tx], [c, d, tz]]``.

    Stored as six scalars to keep dataclasses hashable. Compose with
    ``then`` (left-to-right reading order, like CSS transforms).
    """

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    tx: float = 0.0
    tz: float = 0.0

    def apply(self, p: Point) -> Point:
        return Point(self.a * p.y + self.b * p.z + self.tx, self.c * p.y + self.d * p.z + self.tz)

    def then(self, other: Affine2D) -> Affine2D:
        """Return ``other ∘ self`` so ``self.then(other).apply(p)`` reads
        as "first ``self``, then ``other``"."""
        return Affine2D(
            a=other.a * self.a + other.b * self.c,
            b=other.a * self.b + other.b * self.d,
            c=other.c * self.a + other.d * self.c,
            d=other.c * self.b + other.d * self.d,
            tx=other.a * self.tx + other.b * self.tz + other.tx,
            tz=other.c * self.tx + other.d * self.tz + other.tz,
        )

    @classmethod
    def identity(cls) -> Affine2D:
        return cls()

    @classmethod
    def translation(cls, dy: float, dz: float) -> Affine2D:
        return cls(tx=dy, tz=dz)

    @classmethod
    def rotation(cls, angle_deg: float, around: Point | None = None) -> Affine2D:
        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        base = cls(a=cos_a, b=-sin_a, c=sin_a, d=cos_a)
        if around is None:
            return base
        return (
            cls.translation(-around.y, -around.z)
            .then(base)
            .then(cls.translation(around.y, around.z))
        )

    @classmethod
    def scaling(cls, sy: float, sz: float, around: Point | None = None) -> Affine2D:
        base = cls(a=sy, d=sz)
        if around is None:
            return base
        return (
            cls.translation(-around.y, -around.z)
            .then(base)
            .then(cls.translation(around.y, around.z))
        )

    @classmethod
    def mirror_y(cls, axis_z: float = 0.0) -> Affine2D:
        """Mirror across a horizontal line ``z == axis_z`` (flips Z)."""
        return cls(d=-1.0, tz=2.0 * axis_z)

    @classmethod
    def mirror_z(cls, axis_y: float = 0.0) -> Affine2D:
        """Mirror across a vertical line ``y == axis_y`` (flips Y)."""
        return cls(a=-1.0, tx=2.0 * axis_y)


def apply(segments: Iterable[Segment], tr: Affine2D) -> list[Segment]:
    return [Segment(tr.apply(s.a), tr.apply(s.b), s.kind) for s in segments]


def rotate_around_center(segments: Iterable[Segment], angle_deg: float) -> list[Segment]:
    """Rotate ``segments`` around their bbox centre. Raises ``GeometryError``
    if geometry is degenerate (legacy app crashed silently here)."""
    segs = list(segments)
    bbox = BBox.from_segments(segs)
    if bbox is None:
        return []
    centre = bbox.center()
    if centre is None:
        raise GeometryError("cannot rotate: geometry collapsed to a single point")
    return apply(segs, Affine2D.rotation(angle_deg, centre))


def rotate_around(segments: Iterable[Segment], angle_deg: float, pivot: Point) -> list[Segment]:
    return apply(segments, Affine2D.rotation(angle_deg, pivot))


def scale_around_center(segments: Iterable[Segment], factor: float) -> list[Segment]:
    """Uniformly scale ``segments`` about their bbox centre."""
    segs = list(segments)
    bbox = BBox.from_segments(segs)
    if bbox is None:
        return []
    centre = bbox.center()
    if centre is None:
        return segs
    return apply(segs, Affine2D.scaling(factor, factor, centre))


def translate(segments: Iterable[Segment], dy: float, dz: float) -> list[Segment]:
    return apply(segments, Affine2D.translation(dy, dz))


def mirror_horizontal(segments: Iterable[Segment]) -> list[Segment]:
    """Flip the geometry vertically (mirror across its horizontal mid-line)."""
    segs = list(segments)
    bbox = BBox.from_segments(segs)
    if bbox is None:
        return []
    axis = (bbox.min_z + bbox.max_z) / 2.0
    return apply(segs, Affine2D.mirror_y(axis))


def mirror_vertical(segments: Iterable[Segment]) -> list[Segment]:
    """Flip the geometry horizontally (mirror across its vertical mid-line)."""
    segs = list(segments)
    bbox = BBox.from_segments(segs)
    if bbox is None:
        return []
    axis = (bbox.min_y + bbox.max_y) / 2.0
    return apply(segs, Affine2D.mirror_z(axis))


def align_to_origin(segments: Iterable[Segment]) -> list[Segment]:
    """Translate so the bbox's bottom-left corner is at ``(0, 0)``."""
    segs = list(segments)
    bbox = BBox.from_segments(segs)
    if bbox is None:
        return []
    return translate(segs, -bbox.min_y, -bbox.min_z)
