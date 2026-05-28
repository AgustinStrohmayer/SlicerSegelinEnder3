"""Project: the root aggregate held by the UI controller.

Mutable on purpose — undo/redo lives outside, in the command stack.
The serialiser in ``io/project_io.py`` turns this into JSON.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .events import EventBus
from .geometry import Segment
from .machine import MachineProfile

SCHEMA_VERSION = 1


@dataclass(slots=True)
class ViewState:
    show_grid: bool = True
    show_rulers: bool = True
    zoom: float = 1.0
    pan_y: float = 0.0
    pan_z: float = 0.0


@dataclass(slots=True)
class Project:
    machine: MachineProfile = field(default_factory=MachineProfile)
    segments: list[Segment] = field(default_factory=list)
    manual_cuts: list[Segment] = field(default_factory=list)
    plate_split: bool = False
    view: ViewState = field(default_factory=ViewState)
    bus: EventBus = field(default_factory=EventBus)

    schema_version: int = SCHEMA_VERSION

    def replace_segments(self, segments: list[Segment]) -> None:
        self.segments = list(segments)
        self.bus.emit("project.geometry_changed", {"count": len(segments)})

    def replace_manual_cuts(self, cuts: list[Segment]) -> None:
        self.manual_cuts = list(cuts)
        self.bus.emit("project.cuts_changed", {"count": len(cuts)})

    def set_machine(self, machine: MachineProfile) -> None:
        self.machine = machine
        self.bus.emit("project.machine_changed", {})
