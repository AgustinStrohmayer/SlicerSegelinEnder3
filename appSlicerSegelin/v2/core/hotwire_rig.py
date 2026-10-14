"""Parametric hot-wire rig + foam block, and the checks a cut must pass.

The rig is a 3D printer whose X axis is locked: the gantry carries two
pivoting arms (one per side of the carriage), a tension spring between their
upper ends and the hot wire between their lower ends. The G-code drives only
Y (the bed, carrying the foam) and Z (the gantry, carrying the wire).

Everything is in millimetres. The geometry that matters for a cut is derived
from a few measured parameters, so the same model describes an Ender-3 or a
larger printer by changing the preset.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .gcode_reader import Toolpath


@dataclass(frozen=True, slots=True)
class HotWireRig:
    name: str = "Ender-3"
    bed_x: float = 235.0          # bed plate, across the wire
    bed_y: float = 235.0          # bed plate, along Y travel
    y_travel: float = 220.0
    z_travel: float = 250.0
    frame_width: float = 330.0    # outer width of the Z uprights
    frame_height: float = 440.0   # top of the Z uprights above the bed
    pivot_spacing: float = 140.6  # distance between the two arm pivots
    arm_lower_length: float = 70.0  # pivot to wire hole; longer arms lower the wire
    arm_upper_length: float = 70.0  # pivot to spring hole
    arm_angle_deg: float = 70.0   # arm inclination from horizontal
    pivot_above_nozzle: float = 39.5  # pivot axis height above the nozzle tip
    carriage_width: float = 91.1  # hotend shroud + fan below the X beam (Ender3.STEP)
    carriage_offset_x: float = 20.2  # its centre relative to the span centre (simulator X)
    carriage_depth: float = 45.0  # hotend footprint along Y, centred on the wire plane
    origin_y: float = 0.0         # machine Y where G92 Y0 was set
    origin_z: float = 30.0        # machine Z where G92 Z0 was set (wire parked above the bed)
    arm_width: float = 14.0       # printed arm, across its axis
    arm_end_beyond_hole: float = 5.0  # material past the wire hole: the arm tip hangs below the wire
    model: str = ""               # 3D model the simulator can draw ("ender3"); otherwise a schematic

    # ── derived geometry ──────────────────────────────────────────────
    @property
    def wire_drop(self) -> float:
        """Vertical distance from the pivots down to the wire."""
        return self.arm_lower_length * math.sin(math.radians(self.arm_angle_deg))

    @property
    def wire_span(self) -> float:
        return self.pivot_spacing + 2.0 * self.arm_lower_length * math.cos(math.radians(self.arm_angle_deg))

    @property
    def spring_span(self) -> float:
        return self.pivot_spacing - 2.0 * self.arm_upper_length * math.cos(math.radians(self.arm_angle_deg))

    @property
    def nozzle_clearance(self) -> float:
        """Free height above the wire under the carriage (nozzle tip)."""
        return self.wire_drop - self.pivot_above_nozzle

    @property
    def arm_reach_below_wire(self) -> float:
        """How far the arm tips hang below the wire (they reach the bed before the wire does)."""
        a = math.radians(self.arm_angle_deg)
        return self.arm_end_beyond_hole * math.sin(a) + self.arm_width / 2 * math.cos(a)

    def arm_clearance_at(self, x_from_center: float) -> float:
        """Height of the arm's lower edge above the wire at lateral position ``x``.

        Infinite between the arms' inner reach; zero at the wire tips.
        """
        half = self.wire_span / 2.0
        d = half - abs(x_from_center)  # distance inward from the nearest tip
        if d <= 0:
            return 0.0
        ang = math.radians(self.arm_angle_deg)
        edge = 7.0 / max(1e-6, math.sin(ang))  # half arm width, measured horizontally
        return max(0.0, (d - edge) * math.tan(ang))

    def usable_width(self, block_height: float) -> float:
        """Widest block (across the wire) whose ends clear both arms."""
        ang = math.radians(self.arm_angle_deg)
        edge = 7.0 / max(1e-6, math.sin(ang))
        inset = edge + block_height / max(1e-6, math.tan(ang))
        return max(0.0, self.wire_span - 2.0 * inset)


@dataclass(frozen=True, slots=True)
class FoamBlock:
    """Foam stock in G-code coordinates (its front-bottom edge on the wire's origin)."""

    length_y: float = 220.0
    height_z: float = 20.0
    width_x: float = 150.0
    y0: float = 0.0   # G-code Y of the block's front face
    z0: float = 0.0   # G-code Z of the block's bottom face
    x_offset: float = 0.0  # block centre relative to the wire span centre
    spacer: float = 0.0    # board under the block so the arm tips clear the bed at the lowest pass

    @property
    def y1(self) -> float:
        return self.y0 + self.length_y

    @property
    def z1(self) -> float:
        return self.z0 + self.height_z


PRESETS: dict[str, HotWireRig] = {
    # Ender-3 / Ender-3 Pro: 220×220×250 build volume, arms of the FiubAero segelín.
    "Ender-3": HotWireRig(model="ender3"),
    # Same printer with the wire half of each arm stretched to 110 mm: ~64 mm under the nozzle,
    # enough for a whole 50-60 mm block instead of 20 mm plates.
    "Ender-3 (long arms)": replace(HotWireRig(model="ender3"), name="Ender-3 (long arms)", arm_lower_length=110.0),
    "Ender-3 V2": replace(HotWireRig(), name="Ender-3 V2", z_travel=250.0),
    "Ender-3 S1": replace(HotWireRig(), name="Ender-3 S1", z_travel=270.0),
    "CR-10": replace(
        HotWireRig(), name="CR-10", bed_x=310.0, bed_y=310.0, y_travel=300.0, z_travel=400.0,
        frame_width=420.0, frame_height=600.0,
    ),
}


def fit_block(toolpath: Toolpath, *, margin_y: float = 5.0, margin_z: float = 5.0, width_x: float = 150.0) -> FoamBlock:
    """Smallest block that contains the cut with margins.

    If the path opens with a straight lead-in along +Y (what the slicer's
    "entry" emits), the block's front face sits halfway along it so the wire
    starts outside the foam.
    """
    y_min, y_max, z_min, z_max = toolpath.bounds()
    y0 = y_min - margin_y
    if toolpath.moves:
        first = toolpath.moves[0]
        if abs(first.z1 - first.z0) < 1e-6 and first.y1 > first.y0:
            y0 = first.y0 + min(margin_y, (first.y1 - first.y0) / 2.0)
    return FoamBlock(length_y=max(1.0, y_max + margin_y - y0), height_z=max(1.0, z_max - z_min + margin_z),
                     width_x=width_x, y0=y0, z0=z_min)


def check_cut(rig: HotWireRig, block: FoamBlock, toolpath: Toolpath) -> list[str]:
    """Human-readable problems with running ``toolpath`` on ``rig`` with ``block``."""
    issues: list[str] = []
    if not toolpath.moves:
        return ["The G-code has no Y/Z moves."]
    y_min, y_max, z_min, z_max = toolpath.bounds()
    if rig.origin_y + y_min < -1e-6 or rig.origin_y + y_max > rig.y_travel + 1e-6:
        issues.append(
            f"Y travel: the path spans {y_min:.1f}…{y_max:.1f} mm from the origin, "
            f"the machine has {rig.y_travel:.0f} mm (origin at Y{rig.origin_y:g})."
        )
    if rig.origin_z + z_min < -1e-6 or rig.origin_z + z_max > rig.z_travel + 1e-6:
        issues.append(f"Z travel: the path spans {z_min:.1f}…{z_max:.1f} mm, the machine has {rig.z_travel:.0f} mm.")
    if block.width_x > rig.wire_span - 1e-6:
        issues.append(f"Block width {block.width_x:.0f} mm exceeds the wire span ({rig.wire_span:.0f} mm).")
    above = block.z1 - z_min
    if above > rig.nozzle_clearance:
        lo, hi = block.x_offset - block.width_x / 2, block.x_offset + block.width_x / 2
        c_lo = rig.carriage_offset_x - rig.carriage_width / 2
        c_hi = rig.carriage_offset_x + rig.carriage_width / 2
        if hi > c_lo and lo < c_hi:
            issues.append(
                f"The block rises {above:.1f} mm above the lowest wire position, but the carriage/nozzle "
                f"is only {rig.nozzle_clearance:.1f} mm above the wire: they collide."
            )
    if block.width_x > rig.usable_width(above) + 1e-6:
        issues.append(
            f"Block ends hit the arms: at {above:.0f} mm tall the usable width is {rig.usable_width(above):.0f} mm."
        )
    low = bed_height(block, z_min)
    if low < rig.arm_reach_below_wire - 1e-6:
        issues.append(
            f"The arm tips hang {rig.arm_reach_below_wire:.1f} mm below the wire and hit the bed at the lowest "
            f"pass; raise the block on a spacer of at least {block.spacer + rig.arm_reach_below_wire - low:.0f} mm."
        )
    sy, sz = toolpath.start
    if block.y0 < sy < block.y1 and block.z0 < sz < block.z1:
        issues.append("The wire starts inside the block; park it outside before starting.")
    if block.length_y > rig.bed_y + 1e-6:
        issues.append(f"Block length {block.length_y:.0f} mm overhangs the {rig.bed_y:.0f} mm bed.")
    return issues


@dataclass(frozen=True, slots=True)
class MachinePose:
    """Where every moving part is at one instant, in a world frame for drawing.

    World frame: X across the bed along the wire (0 = wire span centre), Y along
    the bed travel (0 = the wire's vertical plane, + towards the back), Z up
    (0 = bed top, where the block sits). The bed frame is the world frame
    shifted by ``bed_shift`` along Y; in it, G-code Y maps to Y unchanged.
    """

    t: float
    y: float               # G-code wire position
    z: float
    line_no: int
    bed_shift: float       # world Y of the bed frame's origin (G-code Y = 0)
    wire_height: float     # world Z of the wire
    pivot_height: float
    nozzle_height: float
    carriage_hits_block: bool


def bed_height(block: FoamBlock, z: float) -> float:
    """World height of G-code ``z`` with the block's bottom face on its spacer."""
    return z - block.z0 + block.spacer


def machine_pose(rig: HotWireRig, block: FoamBlock, toolpath: Toolpath, t: float) -> MachinePose:
    s = toolpath.state_at(t)
    wire_h = bed_height(block, s.z)
    nozzle_h = wire_h + rig.nozzle_clearance
    # the block (bed frame Y y0..y1) sits under the hotend when it overlaps the hotend footprint
    by0, by1 = block.y0 - s.y, block.y1 - s.y
    under = by0 < rig.carriage_depth / 2 and by1 > -rig.carriage_depth / 2
    lo, hi = block.x_offset - block.width_x / 2, block.x_offset + block.width_x / 2
    c_lo = rig.carriage_offset_x - rig.carriage_width / 2
    c_hi = rig.carriage_offset_x + rig.carriage_width / 2
    hits = under and hi > c_lo and lo < c_hi and nozzle_h < block.spacer + block.height_z
    return MachinePose(t=s.elapsed_s, y=s.y, z=s.z, line_no=s.line_no, bed_shift=-s.y, wire_height=wire_h,
                       pivot_height=wire_h + rig.wire_drop, nozzle_height=nozzle_h, carriage_hits_block=hits)
