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
    # Where the wire is when the file starts, in G-code coordinates. None: the
    # legacy origin (0, 0), returned to at the end. Otherwise the wire touches the
    # block there and the path itself ends clear of the foam.
    origin: tuple[float, float] | None = None

    @property
    def total_cut_length(self) -> float:
        return sum(s.length for s in self.segments)
