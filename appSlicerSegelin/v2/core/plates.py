"""Plate splitting: automatic Y×Z grid and manual-cut partitioning.

Ports the legacy ``generar_preview_capas`` grid logic and
``_construir_capas_desde_cortes_manuales`` partitioning into pure
functions returning :class:`Layer` objects. All inputs/outputs are in
*machine* coordinates (geometry already offset onto the bed).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .clipping import clip_segment_to_rect
from .geometry import Point, Segment, SegmentKind
from .manual_cuts import (
    ManualCut,
    close_open_contours,
    internal_cut_edges,
    snap_segments,
    split_segment_by_line,
)
from .trajectory import build_full_trajectory

_MARGIN = 10.0


@dataclass(slots=True)
class Layer:
    """One plate/part: local editable geometry + its machine-coord ref."""

    trajectory: list[Segment]
    local_segments: list[Segment]
    global_segments: list[Segment]
    y_min: float
    y_max: float
    z_min: float
    z_max: float
    row: int = 0
    col: int = 0
    part_index: int = 0
    add_unions: bool = True  # how this part's trajectory was built (for rebuilds)

    @property
    def label(self) -> str:
        if self.part_index:
            return f"Part {self.part_index}"
        return f"R{self.row} · C{self.col}"


def split_into_plates(
    machine_cut: list[Segment],
    plate_y: float,
    plate_z: float,
    *,
    margin: float = _MARGIN,
) -> list[Layer]:
    """Grid-split ``machine_cut`` into plates of ``plate_y × plate_z``.

    ``margin`` mm is reserved at each Y end of every plate for safe
    entry/exit, matching the legacy 10 mm convention.
    """
    if not machine_cut or plate_y <= 0 or plate_z <= 0:
        return []
    usable_y = plate_y - (2.0 * margin)
    if usable_y <= 1e-9:
        return []

    ys: list[float] = []
    zs: list[float] = []
    for s in machine_cut:
        ys.extend([s.a.y, s.b.y])
        zs.extend([s.a.z, s.b.z])
    y_min, y_max = min(ys), max(ys)
    z_min, z_max = min(zs), max(zs)

    width = max(0.0, y_max - y_min)
    height = max(0.0, z_max - z_min)
    if width <= 1e-9 and height <= 1e-9:
        return []

    total_cols = max(1, math.ceil(max(1e-9, width) / usable_y))
    total_rows = max(1, math.ceil(max(1e-9, height) / plate_z))

    layers: list[Layer] = []
    for row in range(total_rows):
        cz_min = z_min + (row * plate_z)
        cz_max = min(z_min + ((row + 1) * plate_z), z_max)
        for col in range(total_cols):
            cy_min = y_min + (col * usable_y)
            cy_max = min(y_min + ((col + 1) * usable_y), y_max)

            local: list[Segment] = []
            global_ref: list[Segment] = []
            for s in machine_cut:
                clipped = clip_segment_to_rect(s, cy_min, cz_min, cy_max, cz_max)
                if clipped is None or clipped.is_degenerate:
                    continue
                global_ref.append(clipped)
                local.append(
                    Segment(
                        Point((clipped.a.y - cy_min) + margin, clipped.a.z - cz_min),
                        Point((clipped.b.y - cy_min) + margin, clipped.b.z - cz_min),
                        SegmentKind.CUT,
                    )
                )
            if not local:
                continue
            traj = build_full_trajectory(local, add_unions=True)
            if not traj:
                continue
            layers.append(
                Layer(
                    trajectory=traj,
                    local_segments=local,
                    global_segments=global_ref,
                    y_min=cy_min,
                    y_max=cy_max,
                    z_min=cz_min,
                    z_max=cz_max,
                    row=row + 1,
                    col=col + 1,
                    add_unions=True,
                )
            )
    return layers


def partition_by_manual_cuts(
    machine_cut: list[Segment],
    cuts: list[ManualCut],
    offset_y: float,
    offset_z: float,
    *,
    auto_close: bool = True,
) -> list[Layer]:
    """Split ``machine_cut`` into parts using manual cut lines."""
    if not machine_cut or not cuts:
        return []

    cut_lines = [c.to_machine_line(offset_y, offset_z) for c in cuts]

    # 1) split contour by all cut lines
    pieces = list(machine_cut)
    for a, b, c in cut_lines:
        nxt: list[Segment] = []
        for s in pieces:
            nxt.extend(split_segment_by_line(s, a, b, c))
        pieces = nxt

    # 2) internal cut edges
    internal = internal_cut_edges(machine_cut, cut_lines)

    # 3) unify and re-split at crossings, then snap
    everything = pieces + internal
    for a, b, c in cut_lines:
        nxt = []
        for s in everything:
            nxt.extend(split_segment_by_line(s, a, b, c))
        everything = nxt
    everything = snap_segments(everything)

    # 4) group by region signature (side of each cut)
    eps = 1e-7
    regions: dict[tuple[int, ...], list[Segment]] = {}
    existing: set[tuple[int, ...]] = set()
    seg_states: list[tuple[Segment, list[int]]] = []

    for s in everything:
        if s.is_degenerate:
            continue
        ym = (s.a.y + s.b.y) * 0.5
        zm = (s.a.z + s.b.z) * 0.5
        states: list[int] = []
        for a, b, c in cut_lines:
            fv = (a * ym) + (b * zm) + c
            states.append(1 if fv > eps else (-1 if fv < -eps else 0))
        if all(v != 0 for v in states):
            existing.add(tuple(states))
        seg_states.append((s, states))

    if not existing:
        existing = {tuple([1] * len(cut_lines))}

    for s, states in seg_states:
        candidates: list[tuple[int, ...]] = [()]
        for v in states:
            if v == 0:
                candidates = [(*c, -1) for c in candidates] + [(*c, 1) for c in candidates]
            else:
                candidates = [(*c, v) for c in candidates]
        candidates = [f for f in candidates if f in existing]
        if not candidates:
            candidates = [tuple(1 if v == 0 else v for v in states)]
        for sig in candidates:
            regions.setdefault(sig, []).append(s)

    layers: list[Layer] = []
    for idx, (_sig, segs) in enumerate(regions.items(), start=1):
        if not segs:
            continue
        segs = snap_segments(segs)
        if auto_close:
            segs = close_open_contours(segs)
        ys: list[float] = []
        zs: list[float] = []
        for s in segs:
            ys.extend([s.a.y, s.b.y])
            zs.extend([s.a.z, s.b.z])
        y_min, y_max = min(ys), max(ys)
        z_min, z_max = min(zs), max(zs)
        local = snap_segments(
            [
                Segment(
                    Point(s.a.y - y_min, s.a.z - z_min),
                    Point(s.b.y - y_min, s.b.z - z_min),
                    s.kind,
                )
                for s in segs
            ]
        )
        traj = build_full_trajectory(local, add_unions=False)
        if not traj:
            continue
        layers.append(
            Layer(
                trajectory=traj,
                local_segments=local,
                global_segments=list(segs),
                y_min=y_min,
                y_max=y_max,
                z_min=z_min,
                z_max=z_max,
                part_index=idx,
                add_unions=False,
            )
        )
    return layers
