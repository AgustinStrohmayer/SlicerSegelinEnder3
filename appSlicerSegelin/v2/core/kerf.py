"""Kerf compensation: move the wire half a kerf away from the part.

The hot wire melts a slot ``kerf`` wide centred on its path, so cutting right
on the drawn line leaves the part ``kerf/2`` smaller all round. Offsetting each
closed contour by ``kerf/2`` away from the material keeps the part at its
drawn size: outer contours grow, holes shrink. Which is which comes from
nesting (a contour inside an odd number of others is a hole).

Convex corners get a round join (the wire's slot is round there too), concave
ones a miter. Open chains are left alone: there is no "outside" to go to.
A hole too small for the offset is left as drawn.
"""
from __future__ import annotations

import math

from .geometry import Point, Segment, SegmentKind
from .pathing import chain_segments

_TOL = 1e-5
_ARC_STEP = math.radians(20.0)


def _area(pts: list[Point]) -> float:
    return 0.5 * sum(p.y * q.z - q.y * p.z for p, q in zip(pts, pts[1:] + pts[:1], strict=True))


def _inside(p: Point, poly: list[Point]) -> bool:
    hit = False
    for a, b in zip(poly, poly[1:] + poly[:1], strict=True):
        if (a.z > p.z) != (b.z > p.z) and p.y < a.y + (p.z - a.z) * (b.y - a.y) / (b.z - a.z):
            hit = not hit
    return hit


def _offset_loop(pts: list[Point], d: float) -> list[Point]:
    """Offset a counter-clockwise loop by ``d`` (> 0 grows it, < 0 shrinks it)."""
    n = len(pts)
    normals = []  # outward normal of edge i (pts[i] → pts[i+1]) for a CCW loop
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        dy, dz = b.y - a.y, b.z - a.z
        ln = math.hypot(dy, dz)
        normals.append((dz / ln, -dy / ln))
    out: list[Point] = []
    for i in range(n):
        p = pts[i]
        n0, n1 = normals[i - 1], normals[i]
        cross = n0[0] * n1[1] - n0[1] * n1[0]  # > 0: the loop turns left here (convex for CCW)
        dot = max(-1.0, min(1.0, n0[0] * n1[0] + n0[1] * n1[1]))
        if cross * d > 1e-12 and dot < math.cos(_ARC_STEP / 2):
            # the offset opens a gap at this corner: bridge it with an arc around p
            a0, a1 = math.atan2(n0[1], n0[0]), math.atan2(n1[1], n1[0])
            sweep = a1 - a0
            sweep -= 2 * math.pi * round(sweep / (2 * math.pi))
            k = max(1, math.ceil(abs(sweep) / _ARC_STEP))
            r = abs(d)
            sign = 1.0 if d > 0 else -1.0
            for j in range(k + 1):
                t = a0 + sweep * j / k
                out.append(Point(p.y + sign * r * math.cos(t), p.z + sign * r * math.sin(t)))
        else:
            # miter: where the two offset edges meet
            my, mz = n0[0] + n1[0], n0[1] + n1[1]
            s = d / max(1e-6, 1.0 + dot)
            out.append(Point(p.y + my * s, p.z + mz * s))
    return out


def compensate_kerf(segments: list[Segment], offset_mm: float) -> list[Segment]:
    """``segments`` with every closed contour moved ``offset_mm`` away from the part."""
    if offset_mm <= 0 or not segments:
        return list(segments)
    loops: list[list[Point]] = []
    rest: list[Segment] = []
    for path in chain_segments([s for s in segments if not s.is_degenerate], tol=_TOL):
        if path.closed and len(path) >= 3:
            loops.append([s.a for s in path.segments])
        else:
            rest.extend(path.segments)
    out: list[Segment] = []
    for i, pts in enumerate(loops):
        depth = sum(1 for j, other in enumerate(loops) if j != i and _inside(pts[0], other))
        area = _area(pts)
        if area < 0:
            pts = pts[::-1]
        d = offset_mm if depth % 2 == 0 else -offset_mm
        moved = _offset_loop(pts, d)
        new_area = _area(moved)
        if new_area <= 0 or (d < 0 and new_area >= abs(area)):
            moved = pts  # a hole too small for the wire: cut it as drawn
        if area < 0:
            moved = moved[::-1]  # keep the drawn direction
        out.extend(Segment(a, b, SegmentKind.CUT) for a, b in zip(moved, moved[1:] + moved[:1], strict=True)
                   if a.distance_to(b) > 1e-9)
    return out + rest
