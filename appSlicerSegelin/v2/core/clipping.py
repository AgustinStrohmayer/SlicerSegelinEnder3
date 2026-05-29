"""Segment clipping to a rectangular region.

Uses Liang-Barsky parametric clipping. Near-zero direction components
are treated as "parallel to that axis" instead of dividing by them —
the legacy app divides by ``dy``/``dz`` only when the absolute value
is above ``1e-12`` but still proceeds if rounding nudges it back.
"""
from __future__ import annotations

from .geometry import Point, Segment

_EPS = 1e-12


def clip_segment_to_rect(
    seg: Segment,
    min_y: float,
    min_z: float,
    max_y: float,
    max_z: float,
) -> Segment | None:
    """Return the portion of ``seg`` inside the rectangle, or ``None``.

    Preserves the original ``kind`` and orientation (``a`` stays the
    side closer to the original ``seg.a``).
    """
    if min_y > max_y or min_z > max_z:
        return None

    y1, z1 = seg.a.y, seg.a.z
    y2, z2 = seg.b.y, seg.b.z
    dy = y2 - y1
    dz = z2 - z1

    t0 = 0.0
    t1 = 1.0

    for p, q in ((-dy, y1 - min_y), (dy, max_y - y1), (-dz, z1 - min_z), (dz, max_z - z1)):
        if abs(p) < _EPS:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            if t > t0:
                t0 = t
        else:
            if t < t0:
                return None
            if t < t1:
                t1 = t

    if t0 >= t1:
        return None

    new_a = Point(y1 + t0 * dy, z1 + t0 * dz)
    new_b = Point(y1 + t1 * dy, z1 + t1 * dz)
    return Segment(new_a, new_b, seg.kind)


def clip_segments_to_rect(
    segments: list[Segment],
    min_y: float,
    min_z: float,
    max_y: float,
    max_z: float,
) -> list[Segment]:
    out: list[Segment] = []
    for s in segments:
        clipped = clip_segment_to_rect(s, min_y, min_z, max_y, max_z)
        if clipped is not None and not clipped.is_degenerate:
            out.append(clipped)
    return out
