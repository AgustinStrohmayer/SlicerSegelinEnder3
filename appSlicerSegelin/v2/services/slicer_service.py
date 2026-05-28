"""Build a :class:`CutPlan` from raw segments.

The legacy app inlined this orchestration into the UI class. Here
the service is plain functions so the UI tests can call them without
spinning up Qt.
"""
from __future__ import annotations

from ..core.cutplan import CutPlan
from ..core.geometry import Segment, SegmentKind
from ..core.machine import MachineProfile
from ..core.pathing import chain_segments, flatten, order_paths


def build_cut_plan(
    segments: list[Segment],
    machine: MachineProfile,
    *,
    notes: tuple[str, ...] = (),
) -> CutPlan:
    """Chain disjoint segments into paths, then order them greedily.

    The order is deterministic — given the same input, we always
    produce the same plan. The legacy app's greedy ordering was
    order-dependent on floating-point tie-breaks, which made golden
    tests impossible.
    """
    if not segments:
        return CutPlan(segments=(), machine=machine, notes=notes)
    paths = chain_segments(segments)
    paths = order_paths(paths)
    ordered = flatten(paths)
    # Force every segment to a uniform kind for the standard slice;
    # plate-split / manual cut flows assign tags before reaching here.
    tagged = [
        Segment(s.a, s.b, s.kind if s.kind != SegmentKind.CUT else SegmentKind.CUT)
        for s in ordered
    ]
    return CutPlan(segments=tuple(tagged), machine=machine, notes=notes)
