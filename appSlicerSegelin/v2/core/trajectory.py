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

    # Endpoints bucketed on a grid wider than the tolerance: the usual case (the next segment
    # touches the tail) is found without scanning every segment (O(n) instead of O(n²)).
    cell = _CHAIN_TOL * 4
    grid: dict[tuple[int, int], list[int]] = {}
    for i, (a1, b1, a2, b2) in enumerate(tuples):
        for y, z in ((a1, b1), (a2, b2)):
            grid.setdefault((round(y / cell), round(z / cell)), []).append(i)

    def touching(y: float, z: float) -> tuple[int, bool] | None:
        """The first unused segment (lowest index, start before end) within tolerance of (y, z)."""
        gy, gz = round(y / cell), round(z / cell)
        hits = {i for dy in (-1, 0, 1) for dz in (-1, 0, 1) for i in grid.get((gy + dy, gz + dz), ())
                if not used[i]}
        for i in sorted(hits):
            a1, b1, a2, b2 = tuples[i]
            if math.hypot(a1 - y, b1 - z) <= _CHAIN_TOL:
                return i, False
            if math.hypot(a2 - y, b2 - z) <= _CHAIN_TOL:
                return i, True
        return None

    for _ in range(len(tuples) - 1):
        chosen: int | None = None
        inv = False
        best_d: float | None = None
        hit = touching(end_y, end_z)
        for i, (a1, b1, a2, b2) in enumerate(() if hit else tuples):
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
        if hit:
            chosen, inv = hit
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


ENTRIES = ("side", "top")
_TOP_CLEARANCE_MM = 5.0


def _closed(cut: list[Segment]) -> bool:
    return len(cut) > 2 and cut[0].a.distance_to(cut[-1].b) <= _CHAIN_TOL and all(
        cut[i].b.distance_to(cut[i + 1].a) <= _CHAIN_TOL for i in range(len(cut) - 1))


def build_block_trajectory(segments: list[Segment], block, *, entry: str = "side",  # type: ignore[no-untyped-def]
                           origin: str = "bottom", reverse: bool = False) -> list[Segment]:
    """The machine path for a profile inside a foam block, starting where the operator put the wire.

    ``origin`` is that spot:

    * ``"top"``: touching the block's front-top edge, (y0, z1). The wire first
      steps ``_TOP_CLEARANCE_MM`` forward, works from that line in front of the
      block and ends back on it, level with the top: clear of the foam and of
      the spacer under it.
    * ``"bottom"`` (legacy): at (0, 0), in front of the block, level with its
      bottom face. It works from the line Y = 0 and ends back at (0, 0).

    ``entry`` picks how it gets in from that front line:

    * ``"side"``: straight in (horizontally) to the profile's front-most point;
    * ``"top"``: up above the block, over it, then straight down to the
      profile's highest point.

    It leaves the same way it came in. A closed profile is started at that
    front-most / highest point, so the entry slit is as short as possible.
    """
    cut = build_cut_path(segments, reverse=reverse)
    if not cut:
        return []
    if _closed(cut):
        key = (lambda s: (s.a.y, -s.a.z)) if entry == "side" else (lambda s: (-s.a.z, s.a.y))
        i = min(range(len(cut)), key=lambda k: key(cut[k]))
        cut = cut[i:] + cut[:i]
    start, end = cut[0].a, cut[-1].b
    path: list[Segment] = []

    def go(a: Point, b: Point, kind: SegmentKind) -> None:
        if a.distance_to(b) > 1e-9:
            path.append(Segment(a, b, kind))

    if origin == "top":
        yf = min(block.y0, start.y, end.y) - _TOP_CLEARANCE_MM
        home = Point(yf, block.z1)
        go(Point(block.y0, block.z1), home, SegmentKind.ENTRY)
    else:
        yf = 0.0
        home = Point(0.0, 0.0)
    if entry == "top":
        top = max(block.z1, max(max(s.a.z, s.b.z) for s in cut)) + _TOP_CLEARANCE_MM
        go(home, Point(yf, top), SegmentKind.ENTRY)
        go(Point(yf, top), Point(start.y, top), SegmentKind.ENTRY)
        go(Point(start.y, top), start, SegmentKind.ENTRY)
        path += cut
        go(end, Point(end.y, top), SegmentKind.EXIT)
        go(Point(end.y, top), Point(yf, top), SegmentKind.RETURN_H)
        go(Point(yf, top), home, SegmentKind.RETURN_V)
    else:
        go(home, Point(yf, start.z), SegmentKind.ENTRY)
        go(Point(yf, start.z), start, SegmentKind.ENTRY)
        path += cut
        go(end, Point(yf, end.z), SegmentKind.EXIT)
        go(Point(yf, end.z), home, SegmentKind.RETURN_V)
    return path
