"""Segment chaining and ordering.

The legacy app picks the next segment by greedy nearest-neighbour
search over an unordered list, which is O(n²) and order-dependent on
floating-point ties. We replace it with a deterministic two-phase
algorithm:

1. **Hashmap chain**: bucket endpoints by a quantised key so we can
   pull connected segments in O(n).
2. **Greedy assembly between disjoint chains**: when nothing is
   connected, pick the nearest open endpoint deterministically by
   (distance, index) so test runs are stable.
"""
from __future__ import annotations

import math
from collections import defaultdict

from .geometry import Path, Point, Segment, SegmentKind

_SNAP_TOL = 1e-6


def _key(p: Point, tol: float) -> tuple[int, int]:
    return (round(p.y / tol), round(p.z / tol))


def chain_segments(segments: list[Segment], tol: float = _SNAP_TOL) -> list[Path]:
    """Group connected segments into ``Path`` objects.

    Two segments are connected when one's endpoint matches the other's
    endpoint within ``tol`` (quantised hashing — no quadratic scan).
    """
    if not segments:
        return []

    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, s in enumerate(segments):
        if s.is_degenerate:
            continue
        buckets[_key(s.a, tol)].append(i)
        buckets[_key(s.b, tol)].append(i)

    visited: set[int] = set()
    paths: list[Path] = []

    for start_i, start_seg in enumerate(segments):
        if start_i in visited or start_seg.is_degenerate:
            continue
        visited.add(start_i)
        chain: list[Segment] = [start_seg]

        # Extend forward from chain[-1].b
        while True:
            tail = chain[-1]
            nexts = [j for j in buckets[_key(tail.b, tol)] if j not in visited]
            if not nexts:
                break
            j = nexts[0]
            visited.add(j)
            cand = segments[j]
            if cand.a.distance_to(tail.b) <= tol:
                chain.append(cand)
            else:
                chain.append(cand.reversed())

        # Extend backward from chain[0].a
        while True:
            head = chain[0]
            prevs = [j for j in buckets[_key(head.a, tol)] if j not in visited]
            if not prevs:
                break
            j = prevs[0]
            visited.add(j)
            cand = segments[j]
            if cand.b.distance_to(head.a) <= tol:
                chain.insert(0, cand)
            else:
                chain.insert(0, cand.reversed())

        head_pt = chain[0].a
        tail_pt = chain[-1].b
        closed = head_pt.distance_to(tail_pt) <= tol
        paths.append(Path(segments=tuple(chain), closed=closed))

    return paths


def order_paths(paths: list[Path], start: Point | None = None) -> list[Path]:
    """Greedy nearest-endpoint ordering with deterministic tie-break.

    The order is stable: ties resolve by the path's original index,
    so unit tests are reproducible.
    """
    if not paths:
        return []
    remaining = list(enumerate(paths))
    current = start if start is not None else Point(0.0, 0.0)
    out: list[Path] = []
    while remaining:
        best_idx = 0
        best_dist = math.inf
        best_reverse = False
        for k, (_orig, path) in enumerate(remaining):
            endpoints = path.endpoints()
            if endpoints is None:
                continue
            head, tail = endpoints
            d_head = current.distance_to(head)
            d_tail = current.distance_to(tail)
            if d_head < best_dist:
                best_dist = d_head
                best_idx = k
                best_reverse = False
            if d_tail < best_dist:
                best_dist = d_tail
                best_idx = k
                best_reverse = True
        _orig, chosen = remaining.pop(best_idx)
        if best_reverse:
            chosen = Path(
                segments=tuple(s.reversed() for s in reversed(chosen.segments)),
                closed=chosen.closed,
            )
        out.append(chosen)
        endpoints = chosen.endpoints()
        if endpoints is not None:
            current = endpoints[1]
    return out


def flatten(paths: list[Path]) -> list[Segment]:
    """Flatten ordered paths back into a single segment list."""
    out: list[Segment] = []
    for p in paths:
        out.extend(p.segments)
    return out


def heal_gaps(segments: list[Segment], tol: float) -> list[Segment]:
    """Snap near-coincident endpoints to a shared location.

    Experimental — toggleable in settings. Useful when a DXF was
    drawn with sloppy snaps and segments don't quite meet.
    """
    if tol <= 0 or not segments:
        return list(segments)
    canonical: dict[tuple[int, int], Point] = {}
    out: list[Segment] = []
    for s in segments:
        ka = _key(s.a, tol)
        kb = _key(s.b, tol)
        a = canonical.setdefault(ka, s.a)
        b = canonical.setdefault(kb, s.b)
        out.append(Segment(a, b, s.kind))
    return out


def chain_kind(segments: list[Segment], kind: SegmentKind) -> list[Segment]:
    """Re-tag every segment in a list with the given kind."""
    return [Segment(s.a, s.b, kind) for s in segments]
