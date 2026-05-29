"""Cut-path and full-trajectory construction.

Faithful port of the legacy ``_obtener_trayectoria_corte_desde`` and
``_obtener_trayectoria_completa_desde`` so the generated G-code matches
the original tool. The algorithm is intentionally the legacy greedy
chain (leftmost start, nearest-endpoint continuation) rather than the
cleaner :mod:`pathing` one, because the *order* of moves must match
the legacy output for golden parity.

Everything here is pure: it takes and returns plain ``Segment`` lists.
"""
from __future__ import annotations

import math

from .geometry import Point, Segment, SegmentKind

_CHAIN_TOL = 1e-5
_ENTRY_EXIT_MM = 10.0


def build_cut_path(segments: list[Segment], reverse: bool = False) -> list[Segment]:
    """Order ``segments`` into one continuous chain.

    Starts from the leftmost endpoint (lowest ``(y, z)`` lexicographically),
    then repeatedly appends the unused segment whose endpoint is closest to
    the current chain tail, flipping it when needed. Mirrors the legacy
    behaviour exactly, including ``reverse``.
    """
    if not segments:
        return []

    tuples = [s.as_tuple() for s in segments]
    used = [False] * len(tuples)

    best_idx = 0
    best_inv = False
    best_key: tuple[float, float] | None = None
    for i, (y1, z1, y2, z2) in enumerate(tuples):
        k1 = (y1, z1)
        k2 = (y2, z2)
        if best_key is None or k1 < best_key:
            best_key, best_idx, best_inv = k1, i, False
        if k2 < best_key:
            best_key, best_idx, best_inv = k2, i, True

    chain: list[tuple[float, float, float, float]] = []
    y1, z1, y2, z2 = tuples[best_idx]
    if best_inv:
        y1, z1, y2, z2 = y2, z2, y1, z1
    chain.append((y1, z1, y2, z2))
    used[best_idx] = True
    end_y, end_z = y2, z2

    for _ in range(len(tuples) - 1):
        chosen: int | None = None
        inv = False
        best_d: float | None = None
        for i, (a1, b1, a2, b2) in enumerate(tuples):
            if used[i]:
                continue
            d1 = math.hypot(a1 - end_y, b1 - end_z)
            d2 = math.hypot(a2 - end_y, b2 - end_z)
            if d1 <= _CHAIN_TOL:
                chosen, inv, best_d = i, False, d1
                break
            if d2 <= _CHAIN_TOL:
                chosen, inv, best_d = i, True, d2
                break
            d = min(d1, d2)
            if best_d is None or d < best_d:
                best_d, chosen, inv = d, i, (d2 < d1)
        if chosen is None:
            break
        used[chosen] = True
        a1, b1, a2, b2 = tuples[chosen]
        if inv:
            a1, b1, a2, b2 = a2, b2, a1, b1
        chain.append((a1, b1, a2, b2))
        end_y, end_z = a2, b2

    if reverse:
        chain = [(y2, z2, y1, z1) for (y1, z1, y2, z2) in reversed(chain)]

    return [Segment(Point(t[0], t[1]), Point(t[2], t[3]), SegmentKind.CUT) for t in chain]


def build_full_trajectory(
    segments: list[Segment],
    *,
    add_unions: bool = False,
    reverse: bool = False,
    entry_exit_mm: float = _ENTRY_EXIT_MM,
) -> list[Segment]:
    """Build the machine path: entry → cut (+unions) → exit → returns.

    Segment kinds: ENTRY, CUT, UNION, EXIT, RETURN_H, RETURN_V.
    """
    cut = build_cut_path(segments, reverse=reverse)
    if not cut:
        return []

    tagged: list[Segment] = [Segment(s.a, s.b, SegmentKind.CUT) for s in cut]

    if add_unions:
        with_unions: list[Segment] = []
        for i, s in enumerate(tagged):
            with_unions.append(s)
            if i < len(tagged) - 1:
                nxt = tagged[i + 1]
                if s.b.distance_to(nxt.a) > 1e-6:
                    with_unions.append(Segment(s.b, nxt.a, SegmentKind.UNION))
        tagged = with_unions

    if not tagged:
        return []

    start_y, start_z = tagged[0].a.y, tagged[0].a.z
    dir_start = tagged[0].b.y - tagged[0].a.y
    sign_start = 1.0 if dir_start >= 0 else -1.0
    entry_y = start_y - (entry_exit_mm * sign_start)
    entry = Segment(Point(entry_y, start_z), Point(start_y, start_z), SegmentKind.ENTRY)

    end_y, end_z = tagged[-1].b.y, tagged[-1].b.z
    dir_end = tagged[-1].b.y - tagged[-1].a.y
    sign_end = 1.0 if dir_end >= 0 else -1.0
    exit_y = end_y + (entry_exit_mm * sign_end)
    exit_seg = Segment(Point(end_y, end_z), Point(exit_y, end_z), SegmentKind.EXIT)

    returns: list[Segment] = []
    if abs(exit_y - entry_y) > 1e-9:
        returns.append(Segment(Point(exit_y, end_z), Point(entry_y, end_z), SegmentKind.RETURN_H))
    if abs(end_z - start_z) > 1e-9:
        returns.append(Segment(Point(entry_y, end_z), Point(entry_y, start_z), SegmentKind.RETURN_V))

    return [entry, *tagged, exit_seg, *returns]


def trajectory_durations(trajectory: list[Segment], speed_mm_s: float) -> list[float]:
    """Per-segment durations in seconds at a constant feed of ``speed_mm_s``."""
    if speed_mm_s <= 0:
        return []
    return [s.length / speed_mm_s for s in trajectory]


def total_duration(trajectory: list[Segment], speed_mm_s: float) -> float:
    return sum(trajectory_durations(trajectory, speed_mm_s))
