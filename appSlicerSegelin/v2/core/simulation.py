"""Deterministic step-based simulation of a cut plan.

The legacy timer accumulates float drift because it stores ``time -
last_time`` and increments a path index from a wall-clock reading.
Here we precompute per-segment durations and address time as
``step * dt``, so 60 seconds of playback always lands at the same
fractional segment regardless of how many ticks the UI thread missed.
"""
from __future__ import annotations

from dataclasses import dataclass

from .geometry import Segment
from .machine import MachineProfile


@dataclass(frozen=True, slots=True)
class SimulationFrame:
    segment_index: int
    fraction: float  # 0..1 inside the current segment
    elapsed_s: float


@dataclass(frozen=True, slots=True)
class SimulationPlan:
    durations_s: tuple[float, ...]

    @property
    def total_s(self) -> float:
        return sum(self.durations_s)

    def frame_at(self, t_s: float) -> SimulationFrame:
        if not self.durations_s:
            return SimulationFrame(0, 0.0, 0.0)
        if t_s <= 0.0:
            return SimulationFrame(0, 0.0, 0.0)
        if t_s >= self.total_s:
            return SimulationFrame(len(self.durations_s) - 1, 1.0, self.total_s)
        acc = 0.0
        for i, d in enumerate(self.durations_s):
            if acc + d >= t_s:
                fraction = (t_s - acc) / d if d > 0 else 0.0
                return SimulationFrame(i, fraction, t_s)
            acc += d
        return SimulationFrame(len(self.durations_s) - 1, 1.0, self.total_s)


def build_plan(segments: list[Segment], machine: MachineProfile) -> SimulationPlan:
    """Constant-velocity per-segment timing.

    A future iteration can add an acceleration ramp, but the legacy
    estimate ignored it too, so we stay deterministic for now.
    """
    if machine.feed_cut_mm_min <= 0:
        return SimulationPlan(durations_s=())
    cut_mm_s = machine.feed_cut_mm_min / 60.0
    travel_mm_s = max(machine.feed_travel_mm_min, machine.feed_cut_mm_min) / 60.0
    durs = []
    for s in segments:
        v = travel_mm_s if s.kind.name == "TRAVEL" else cut_mm_s
        durs.append(s.length / v if v > 0 else 0.0)
    return SimulationPlan(durations_s=tuple(durs))
