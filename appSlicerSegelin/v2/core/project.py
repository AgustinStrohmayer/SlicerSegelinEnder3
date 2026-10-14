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
from .hotwire_rig import DEFAULT_PRESET, PRESETS, FoamBlock, HotWireRig
from .machine import MachineProfile
from .manual_cuts import ManualCut

SCHEMA_VERSION = 2

# A typical slab of stock: 200 mm along the bed, 50 mm tall, 150 mm along the wire,
# its front face 5 mm past the wire's parking spot, on a 10 mm board.
DEFAULT_BLOCK = FoamBlock(length_y=200.0, height_z=50.0, width_x=150.0, y0=5.0, z0=0.0, spacer=10.0)


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

    # The hot-wire machine and the foam block, shared by the 3D view, the
    # machine simulator and the Cut Lab. The workflow starts by creating the
    # block (``block_created``) as the physical stock, then places the profile
    # on it. While ``block_auto`` is on, the block instead follows the G-code
    # (see ``hotwire_rig.refit_block``).
    rig: HotWireRig = field(default_factory=lambda: PRESETS[DEFAULT_PRESET])
    block: FoamBlock = field(default_factory=lambda: DEFAULT_BLOCK)
    block_auto: bool = False
    block_created: bool = False
    # How the wire gets into the block from its parking spot at the origin:
    # "side" (in front, then straight in) or "top" (over it, then down).
    # Only used once the block exists; see ``trajectory.build_block_trajectory``.
    entry: str = "side"

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

    def center_on_block(self) -> None:
        """Center the geometry in the foam block's Y–Z face."""
        from .geometry import BBox

        bbox = BBox.from_segments(self.segments)
        if bbox is None:
            return
        b = self.block
        self.offset_y = (b.y0 + b.y1) / 2.0 - (bbox.min_y + bbox.width / 2.0)
        self.offset_z = (b.z0 + b.z1) / 2.0 - (bbox.min_z + bbox.height / 2.0)

    def place_in_block(self, margin: float = 5.0) -> None:
        """Put the profile in the block's front-top corner, ``margin`` mm from both faces.

        Saves foam: the rest of the block stays in one piece for the next part. It
        also keeps the wire high (the arms clear wider blocks) and the entry slit
        short from either side. An axis where the profile doesn't fit is centred.
        """
        from .geometry import BBox

        bbox = BBox.from_segments(self.segments)
        if bbox is None:
            return
        b = self.block
        if bbox.width + 2 * margin <= b.length_y:
            self.offset_y = b.y0 + margin - bbox.min_y
        else:
            self.offset_y = (b.y0 + b.y1) / 2.0 - (bbox.min_y + bbox.width / 2.0)
        if bbox.height + 2 * margin <= b.height_z:
            self.offset_z = b.z1 - margin - (bbox.min_z + bbox.height)
        else:
            self.offset_z = (b.z0 + b.z1) / 2.0 - (bbox.min_z + bbox.height / 2.0)

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
