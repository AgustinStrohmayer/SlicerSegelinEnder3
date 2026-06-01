"""Manual cut lines and geometry partitioning.

A manual cut is a straight line ``a*y + b*z + c = 0`` used to split the
profile into independent parts (plates). The legacy app supported Y
cuts (vertical lines), Z cuts (horizontal lines) and 2-point diagonal
cuts. This module ports that logic as pure functions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from .geometry import Point, Segment, SegmentKind

_SNAP_TOL = 1e-5
_EPS = 1e-9


class CutKind(str, Enum):
    Y = "Y"
    Z = "Z"
    TWO_POINT = "2P"


@dataclass(slots=True)
class ManualCut:
    """A cut line in DXF *base* coordinates.

    ``a*y + b*z + c_base = 0`` in base coords. ``meta`` keeps the
    user-facing value(s) for display and machine-coord conversion.
    """

    a: float
    b: float
    c_base: float
    kind: CutKind
    meta: dict = field(default_factory=dict)

    def describe(self, index: int) -> str:
        if self.kind == CutKind.Y:
            return f"{index + 1:02d}. Y = {self.meta.get('y', 0.0):.3f}"
        if self.kind == CutKind.Z:
            return f"{index + 1:02d}. Z = {self.meta.get('z', 0.0):.3f}"
        p1 = self.meta.get("p1", (0.0, 0.0))
        p2 = self.meta.get("p2", (0.0, 0.0))
        return f"{index + 1:02d}. 2P ({p1[0]:.1f},{p1[1]:.1f})→({p2[0]:.1f},{p2[1]:.1f})"

    def to_machine_line(self, offset_y: float, offset_z: float) -> tuple[float, float, float]:
        """Return ``(a, b, c)`` of the same line in machine coords."""
        if self.kind == CutKind.Y:
            return (1.0, 0.0, -(self.meta.get("y", 0.0) + offset_y))
        if self.kind == CutKind.Z:
            return (0.0, 1.0, -(self.meta.get("z", 0.0) + offset_z))
        c_m = self.c_base - (self.a * offset_y) - (self.b * offset_z)
        return (self.a, self.b, c_m)


def make_y_cut(y_base: float) -> ManualCut:
    return ManualCut(1.0, 0.0, -float(y_base), CutKind.Y, {"y": float(y_base)})


def make_z_cut(z_base: float) -> ManualCut:
    return ManualCut(0.0, 1.0, -float(z_base), CutKind.Z, {"z": float(z_base)})


def line_from_two_points(p1: Point, p2: Point) -> tuple[float, float, float] | None:
    """Normalised ``a*y + b*z + c = 0`` through two points, or ``None``."""
    a = p1.z - p2.z
    b = p2.y - p1.y
    c = (p1.y * p2.z) - (p2.y * p1.z)
    norm = math.hypot(a, b)
    if norm <= 1e-12:
        return None
    return (a / norm, b / norm, c / norm)


def make_two_point_cut(p1: Point, p2: Point) -> ManualCut | None:
    line = line_from_two_points(p1, p2)
    if line is None:
        return None
    a, b, c = line
    return ManualCut(a, b, c, CutKind.TWO_POINT, {"p1": (p1.y, p1.z), "p2": (p2.y, p2.z)})


def split_segment_by_line(seg: Segment, a: float, b: float, c: float) -> list[Segment]:
    """Split ``seg`` where it crosses ``a*y + b*z + c = 0``."""
    y1, z1, y2, z2 = seg.as_tuple()
    f1 = (a * y1) + (b * z1) + c
    f2 = (a * y2) + (b * z2) + c

    if abs(f1) <= _EPS and abs(f2) <= _EPS:
        return [seg]
    if (f1 > _EPS and f2 > _EPS) or (f1 < -_EPS and f2 < -_EPS):
        return [seg]

    den = f1 - f2
    if abs(den) <= _EPS:
        return [seg]

    t = f1 / den
    if t <= _EPS or t >= (1.0 - _EPS):
        return [seg]

    yi = y1 + ((y2 - y1) * t)
    zi = z1 + ((z2 - z1) * t)
    mid = Point(yi, zi)
    return [Segment(seg.a, mid, seg.kind), Segment(mid, seg.b, seg.kind)]


def snap_segments(segments: list[Segment], tol: float = _SNAP_TOL) -> list[Segment]:
    """Snap endpoints to shared averaged nodes; drop degenerate segments."""
    if not segments:
        return []
    nodes: dict[tuple[int, int], list[float]] = {}

    def key(y: float, z: float) -> tuple[int, int]:
        return (round(y / tol), round(z / tol))

    for s in segments:
        for p in (s.a, s.b):
            k = key(p.y, p.z)
            if k not in nodes:
                nodes[k] = [p.y, p.z, 1.0]
            else:
                nodes[k][0] += p.y
                nodes[k][1] += p.z
                nodes[k][2] += 1.0

    centers = {k: (v[0] / v[2], v[1] / v[2]) for k, v in nodes.items()}
    out: list[Segment] = []
    for s in segments:
        ay, az = centers[key(s.a.y, s.a.z)]
        by, bz = centers[key(s.b.y, s.b.z)]
        na, nb = Point(ay, az), Point(by, bz)
        if na.distance_to(nb) > 1e-6:
            out.append(Segment(na, nb, s.kind))
    return out


def close_open_contours(segments: list[Segment], tol: float = _SNAP_TOL) -> list[Segment]:
    """Join degree-1 endpoints with straight cuts (closes split contours)."""
    if not segments:
        return []

    nodes: list[dict] = []

    def get_node(y: float, z: float) -> int:
        for i, n in enumerate(nodes):
            if abs(n["y"] - y) <= tol and abs(n["z"] - z) <= tol:
                n["y"] = (n["y"] + y) * 0.5
                n["z"] = (n["z"] + z) * 0.5
                return i
        nodes.append({"y": y, "z": z, "deg": 0})
        return len(nodes) - 1

    for s in segments:
        i1 = get_node(s.a.y, s.a.z)
        i2 = get_node(s.b.y, s.b.z)
        nodes[i1]["deg"] += 1
        nodes[i2]["deg"] += 1

    ends = [i for i, n in enumerate(nodes) if n["deg"] == 1]
    used: set[int] = set()
    closures: list[Segment] = []
    for i in ends:
        if i in used:
            continue
        yi, zi = nodes[i]["y"], nodes[i]["z"]
        best: int | None = None
        best_d: float | None = None
        for j in ends:
            if j == i or j in used:
                continue
            d = math.hypot(nodes[j]["y"] - yi, nodes[j]["z"] - zi)
            if best is None or d < best_d:  # type: ignore[operator]
                best, best_d = j, d
        if best is not None:
            used.add(i)
            used.add(best)
            closures.append(
                Segment(Point(yi, zi), Point(nodes[best]["y"], nodes[best]["z"]), SegmentKind.CUT)
            )
    return segments + closures


def internal_cut_edges(
    base_segments: list[Segment],
    cut_lines: list[tuple[float, float, float]],
    eps: float = 1e-7,
) -> list[Segment]:
    """Build internal edges between paired contour/line intersections."""
    internal: list[Segment] = []
    for a, b, c in cut_lines:
        pts: list[tuple[float, float]] = []
        for s in base_segments:
            y1, z1, y2, z2 = s.as_tuple()
            f1 = (a * y1) + (b * z1) + c
            f2 = (a * y2) + (b * z2) + c
            if abs(f1) <= eps and abs(f2) <= eps:
                continue
            if abs(f1) <= eps:
                pts.append((y1, z1))
            if abs(f2) <= eps:
                pts.append((y2, z2))
            elif (f1 > eps and f2 < -eps) or (f1 < -eps and f2 > eps):
                den = f1 - f2
                if abs(den) > eps:
                    t = f1 / den
                    pts.append((y1 + (y2 - y1) * t, z1 + (z2 - z1) * t))
        # dedupe + sort along the line direction
        unique: list[tuple[float, float]] = []
        for y, z in pts:
            if all(math.hypot(y - uy, z - uz) > 1e-6 for uy, uz in unique):
                unique.append((y, z))
        # sort by projection on line direction (-b, a)
        unique.sort(key=lambda p: (-b) * p[0] + a * p[1])
        for i in range(0, len(unique) - 1, 2):
            (ay, az), (by, bz) = unique[i], unique[i + 1]
            internal.append(Segment(Point(ay, az), Point(by, bz), SegmentKind.CUT))
    return internal
