"""Project: the root aggregate held by the UI controller.

Mutable on purpose — undo/redo lives outside, in the command stack.
The serialiser in ``io/project_io.py`` turns this into JSON.

Coordinate model (matches legacy):
  * ``segments`` are *base* geometry in DXF/mm coordinates, mutated by
    geometric transforms (rotate, mirror).
  * ``offset_y`` / ``offset_z`` place the geometry onto the bed; they are
    changed by fine translation and "align origin", and applied when
    building machine-coordinate trajectories.
  * machine coords = base + offset.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .events import EventBus
from .geometry import Segment
from .machine import MachineProfile
from .manual_cuts import ManualCut

SCHEMA_VERSION = 2


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

    # Placement on the bed (machine coords = base + offset).
    offset_y: float = 0.0
    offset_z: float = 0.0

    # Cut parameters.
    speed_mm_s: float = 10.0
    reverse_cut: bool = False

    # Plate / usable area (mm). Defaults match the legacy app.
    area_y_mm: float = 220.0
    area_z_mm: float = 100.0
    split_into_plates: bool = False

    # Manual cuts.
    use_manual_cuts: bool = False
    auto_close_manual: bool = True
    manual_cuts: list[ManualCut] = field(default_factory=list)

    # Export.
    batch_basename: str = "cut"

    # Origin file traceability — set on DXF import, kept so .ssproj archives
    # can record where the geometry came from.
    source_dxf_name: str | None = None

    view: ViewState = field(default_factory=ViewState)
    bus: EventBus = field(default_factory=EventBus)
    schema_version: int = SCHEMA_VERSION

    # ── derived helpers ───────────────────────────────────────────────
    def machine_segments(self) -> list[Segment]:
        """Base geometry translated onto the bed."""
        from .transforms import translate

        return translate(self.segments, self.offset_y, self.offset_z)

    def center_on_bed(self) -> None:
        """Center the geometry on the usable area (legacy import behaviour)."""
        from .geometry import BBox

        bbox = BBox.from_segments(self.segments)
        if bbox is None:
            self.offset_y = self.offset_z = 0.0
            return
        self.offset_y = (self.area_y_mm / 2.0) - (bbox.width / 2.0) - bbox.min_y
        self.offset_z = (self.area_z_mm / 2.0) - (bbox.height / 2.0) - bbox.min_z

    # ── mutations that emit events ────────────────────────────────────
    def replace_segments(self, segments: list[Segment]) -> None:
        self.segments = list(segments)
        self.bus.emit("project.geometry_changed", {"count": len(segments)})

    def set_offset(self, offset_y: float, offset_z: float) -> None:
        self.offset_y = offset_y
        self.offset_z = offset_z
        self.bus.emit("project.geometry_changed", {"count": len(self.segments)})

    def set_machine(self, machine: MachineProfile) -> None:
        self.machine = machine
        self.bus.emit("project.machine_changed", {})
