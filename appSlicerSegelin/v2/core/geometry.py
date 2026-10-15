"""Geometric primitives.

The legacy app stores geometry as tuples ``(y1, z1, y2, z2)`` scattered
through ``self.lineas`` and recomputes bbox/center in many places.
Here we collapse that into ``Point``, ``Segment``, ``Path`` and
``BBox``, all frozen so they hash and copy cheaply.

Coordinates use the hot-wire CNC convention: ``y`` is the horizontal
axis along the bed, ``z`` is the vertical axis. The third spatial
axis (``x``) is the wire and is not represented here.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import Enum


class SegmentKind(str, Enum):
    """Why a segment exists in the cut plan.

    Used downstream by the G-code writer to decide comments and feed
    rates. The string values are stable so they can be persisted in
    ``.ssp`` project files.
    """

    CUT = "cut"
    ENTRY = "entry"
    EXIT = "exit"
    RETURN_H = "return_h"
    RETURN_V = "return_v"
    UNION = "union"
    TRAVEL = "travel"


@dataclass(frozen=True, slots=True)
class Point:
    y: float
    z: float

    def __iter__(self) -> Iterator[float]:
        yield self.y
        yield self.z

    def translate(self, dy: float, dz: float) -> Point:
        return Point(self.y + dy, self.z + dz)

    def distance_to(self, other: Point) -> float:
        return math.hypot(other.y - self.y, other.z - self.z)


@dataclass(frozen=True, slots=True)
class Segment:
    a: Point
    b: Point
    kind: SegmentKind = SegmentKind.CUT

    @property
    def length(self) -> float:
        return self.a.distance_to(self.b)

    @property
    def is_degenerate(self) -> bool:
        return self.length <= 1e-9

    def reversed(self) -> Segment:
        return Segment(self.b, self.a, self.kind)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.a.y, self.a.z, self.b.y, self.b.z)

    @classmethod
    def from_tuple(cls, t: tuple[float, float, float, float], kind: SegmentKind = SegmentKind.CUT) -> Segment:
        y1, z1, y2, z2 = t
        return cls(Point(y1, z1), Point(y2, z2), kind)


@dataclass(frozen=True, slots=True)
class BBox:
    """Axis-aligned bounding box. ``None`` semantics for the empty box.

    The legacy app crashes on rotation when geometry collapses to a
    single point (centre undefined). Here :func:`center` returns
    ``None`` for the degenerate case and the UI layer is expected to
    decide what to do.
    """

    min_y: float
    min_z: float
    max_y: float
    max_z: float

    @property
    def width(self) -> float:
        return self.max_y - self.min_y

    @property
    def height(self) -> float:
        return self.max_z - self.min_z

    @property
    def is_degenerate(self) -> bool:
        return self.width <= 1e-9 and self.height <= 1e-9

    def center(self) -> Point | None:
        if self.is_degenerate:
            return None
        return Point((self.min_y + self.max_y) / 2.0, (self.min_z + self.max_z) / 2.0)

    @classmethod
    def from_points(cls, points: Iterable[Point]) -> BBox | None:
        it = iter(points)
        try:
            first = next(it)
        except StopIteration:
            return None
        min_y = max_y = first.y
        min_z = max_z = first.z
        for p in it:
            if p.y < min_y:
                min_y = p.y
            elif p.y > max_y:
                max_y = p.y
            if p.z < min_z:
                min_z = p.z
            elif p.z > max_z:
                max_z = p.z
        return cls(min_y, min_z, max_y, max_z)

    @classmethod
    def from_segments(cls, segments: Iterable[Segment]) -> BBox | None:
        points: list[Point] = []
        for s in segments:
            points.append(s.a)
            points.append(s.b)
        return cls.from_points(points)


@dataclass(frozen=True, slots=True)
class Path:
    """An ordered list of segments. ``closed`` is honoured by the writers.

    A closed LWPOLYLINE in DXF must emit a final segment that returns
    to the first point — the legacy reader silently dropped it.
    """

    segments: tuple[Segment, ...]
    closed: bool = False

    def __iter__(self) -> Iterator[Segment]:
        return iter(self.segments)

    def __len__(self) -> int:
        return len(self.segments)

    @property
    def length(self) -> float:
        return sum(s.length for s in self.segments)

    def endpoints(self) -> tuple[Point, Point] | None:
        if not self.segments:
            return None
        return self.segments[0].a, self.segments[-1].b

    @classmethod
    def from_points(
        cls,
        points: Sequence[Point],
        closed: bool = False,
        kind: SegmentKind = SegmentKind.CUT,
    ) -> Path:
        if len(points) < 2:
            return cls(segments=(), closed=closed)
        segs = [Segment(points[i], points[i + 1], kind) for i in range(len(points) - 1)]
        if closed and points[0] != points[-1]:
            segs.append(Segment(points[-1], points[0], kind))
        return cls(segments=tuple(segs), closed=closed)
