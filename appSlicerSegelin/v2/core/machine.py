"""Machine profile: hot-wire Ender-3 defaults, fully overridable.

A single ``precision_decimals`` token is used by both the G-code and
DXF writers so re-importing an exported DXF doesn't drift from the
G-code that was generated alongside it (legacy used 6 vs 3).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MachineProfile:
    name: str = "Ender-3 Hot Wire"
    bed_y: float = 220.0
    bed_z: float = 220.0
    feed_cut_mm_min: float = 200.0
    feed_travel_mm_min: float = 800.0
    accel_mm_s2: float = 500.0
    precision_decimals: int = 3
    line_ending: str = "\n"
    entry_exit_mm: float = 10.0

    def round_coord(self, value: float) -> float:
        return round(value, self.precision_decimals)
