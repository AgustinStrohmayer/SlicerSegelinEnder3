"""Derived plan consumed by the G-code writer.

A ``CutPlan`` is what comes out of the slicer service: a list of
segments tagged with their semantic kind, plus the machine profile
they were planned against. It is intentionally minimal — the writer
should not need to know about projects, layers or transforms.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import Segment
from .machine import MachineProfile


@dataclass(frozen=True, slots=True)
class CutPlan:
    segments: tuple[Segment, ...]
    machine: MachineProfile
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_cut_length(self) -> float:
        return sum(s.length for s in self.segments)
