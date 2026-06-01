"""G-code emitter.

Three legacy bugs are fixed here at the boundary:

* ``F`` is emitted only when the feed rate actually changes, instead
  of being repeated on every move (legacy line 1986).
* The output always ends with a newline (legacy line 2826) — some
  CNC firmwares reject the last line without one.
* Coordinate precision is taken from the active ``MachineProfile``,
  not hardcoded — keeps DXF and G-code in lock-step (legacy
  rounded 6 decimals into DXF and 3 into G-code, so re-importing a
  file produced silent drift).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.cutplan import CutPlan
from ..core.geometry import SegmentKind
from ..core.machine import MachineProfile

_KIND_COMMENT = {
    SegmentKind.ENTRY: "; entry",
    SegmentKind.EXIT: "; exit",
    SegmentKind.RETURN_H: "; horizontal return to origin Y",
    SegmentKind.RETURN_V: "; final Z adjustment to origin",
    SegmentKind.UNION: "; straight union between segments",
}


@dataclass(slots=True)
class GcodeEmitter:
    machine: MachineProfile

    def emit(self, plan: CutPlan, header_extra: list[str] | None = None) -> str:
        m = plan.machine
        lines: list[str] = []
        lines.append(";FLAVOR:Marlin")
        lines.append(f";TARGET_MACHINE.NAME:{m.name}")
        for extra in plan.notes or ():
            lines.append(f";{extra}")
        if header_extra:
            for extra in header_extra:
                lines.append(f";{extra}")
        lines.append("G21 ; Units in millimeters")
        lines.append("G90 ; Absolute positioning")
        lines.append("M140 S0 ; Turn off bed temperature")
        lines.append("M104 S0 ; Turn off hotend temperature")
        lines.append("M107 ; Turn off layer fan")
        lines.append("G92 Y0 Z0 ; Set current position as origin")
        lines.append(";--- CUT START ---")

        y_cur, z_cur = 0.0, 0.0
        last_feed: float | None = None

        for seg in plan.segments:
            y1 = m.round_coord(seg.a.y)
            z1 = m.round_coord(seg.a.z)
            y2 = m.round_coord(seg.b.y)
            z2 = m.round_coord(seg.b.z)
            feed = m.feed_travel_mm_min if seg.kind == SegmentKind.TRAVEL else m.feed_cut_mm_min

            if abs(y_cur - y1) > 1e-6 or abs(z_cur - z1) > 1e-6:
                lines.append(_format_move(y1, z1, feed, last_feed))
                last_feed = feed

            comment = _KIND_COMMENT.get(seg.kind)
            if comment:
                lines.append(comment)

            lines.append(_format_move(y2, z2, feed, last_feed))
            last_feed = feed
            y_cur, z_cur = y2, z2

        lines.append(";--- CUT END ---")
        lines.append(_format_move(0.0, 0.0, m.feed_travel_mm_min, last_feed, suffix=" ; Smooth return to origin"))
        lines.append("M84 ; Turn off motors")
        return m.line_ending.join(lines) + m.line_ending


def _format_move(
    y: float,
    z: float,
    feed: float,
    last_feed: float | None,
    *,
    suffix: str = "",
) -> str:
    if last_feed is None or abs(feed - last_feed) > 1e-9:
        return f"G1 F{feed:g} Y{y} Z{z}{suffix}"
    return f"G1 Y{y} Z{z}{suffix}"


def emit_gcode(plan: CutPlan, header_extra: list[str] | None = None) -> str:
    return GcodeEmitter(plan.machine).emit(plan, header_extra)
