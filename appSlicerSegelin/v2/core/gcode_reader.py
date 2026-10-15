"""G-code reader for 3D playback of a hot-wire cut.

Parses the subset of Marlin G-code the slicer emits (and that a hand-edited
file is likely to contain): ``G0``/``G1`` linear moves on Y and Z, ``G90`` /
``G91`` (absolute / relative), ``G92`` (set position), ``G20`` / ``G21``
(inch / mm) and the modal ``F`` feed. X is accepted but ignored: on the
hot-wire Ender the X axis is locked and the wire spans it.

The result is a :class:`Toolpath` with per-move timing at constant feed, so
any viewer (the Qt 3D view, a Blender animation) can ask "where is the wire
at time *t*" and get the same answer.

Pure standard library on purpose: Blender's bundled Python imports this file
directly to drive its animation.
"""
from __future__ import annotations

import bisect
import math
import re
from dataclasses import dataclass, field

_WORD = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
DEFAULT_FEED_MM_MIN = 600.0


@dataclass(frozen=True, slots=True)
class Move:
    """One straight move of the wire, in G-code (machine) coordinates."""

    y0: float
    z0: float
    y1: float
    z1: float
    feed_mm_min: float
    t0: float
    t1: float
    line_no: int  # 1-based line of the source file
    rapid: bool = False

    @property
    def length(self) -> float:
        return math.hypot(self.y1 - self.y0, self.z1 - self.z0)

    def point_at(self, t: float) -> tuple[float, float]:
        if self.t1 <= self.t0:
            return (self.y1, self.z1)
        f = min(1.0, max(0.0, (t - self.t0) / (self.t1 - self.t0)))
        return (self.y0 + (self.y1 - self.y0) * f, self.z0 + (self.z1 - self.z0) * f)


@dataclass(frozen=True, slots=True)
class WireState:
    y: float
    z: float
    move_index: int  # -1 before the first move
    line_no: int
    elapsed_s: float


@dataclass(slots=True)
class Toolpath:
    moves: list[Move] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    start: tuple[float, float] = (0.0, 0.0)

    @property
    def total_s(self) -> float:
        return self.moves[-1].t1 if self.moves else 0.0

    @property
    def cut_length(self) -> float:
        return sum(m.length for m in self.moves if not m.rapid)

    def bounds(self) -> tuple[float, float, float, float]:
        """(y_min, y_max, z_min, z_max) of every position the wire visits."""
        ys = [self.start[0]] + [m.y1 for m in self.moves]
        zs = [self.start[1]] + [m.z1 for m in self.moves]
        return (min(ys), max(ys), min(zs), max(zs))

    def state_at(self, t: float) -> WireState:
        if not self.moves or t <= 0.0:
            return WireState(self.start[0], self.start[1], -1, 0, max(0.0, t) if self.moves else 0.0)
        if t >= self.total_s:
            m = self.moves[-1]
            return WireState(m.y1, m.z1, len(self.moves) - 1, m.line_no, self.total_s)
        i = bisect.bisect_right([m.t1 for m in self.moves], t)
        i = min(i, len(self.moves) - 1)
        m = self.moves[i]
        y, z = m.point_at(t)
        return WireState(y, z, i, m.line_no, t)

    def polyline_until(self, t: float, *, include_rapid: bool = True) -> list[tuple[float, float]]:
        """Wire positions from the start up to time ``t`` (for drawing the kerf)."""
        pts = [self.start]
        for m in self.moves:
            if m.t0 >= t:
                break
            if m.rapid and not include_rapid:
                continue
            pts.append(m.point_at(t) if m.t1 > t else (m.y1, m.z1))
        return pts


def parse_gcode(text: str, *, default_feed_mm_min: float = DEFAULT_FEED_MM_MIN) -> Toolpath:
    """Parse ``text`` into a timed :class:`Toolpath`.

    Unknown commands are skipped. Moves of zero length are dropped. The wire
    starts at (0, 0) unless a ``G92`` before the first move says otherwise (the
    slicer's header labels where the operator puts the wire).
    """
    lines = text.splitlines()
    tp = Toolpath(lines=lines)
    absolute = True
    scale = 1.0
    feed = default_feed_mm_min
    y = z = 0.0
    t = 0.0
    feed_seen = False
    for n, raw in enumerate(lines, start=1):
        code = raw.split(";", 1)[0].split("(", 1)[0].strip()
        if not code:
            continue
        words = [(k.upper(), float(v)) for k, v in _WORD.findall(code)]
        gs = [int(v) for k, v in words if k == "G"]
        vals = {k: v for k, v in words if k != "G"}
        if 20 in gs:
            scale = 25.4
        if 21 in gs:
            scale = 1.0
        if 90 in gs:
            absolute = True
        if 91 in gs:
            absolute = False
        if "F" in vals and vals["F"] > 0:
            feed = vals["F"] * scale
            feed_seen = True
        if 92 in gs:
            # G92 re-labels the current position; the wire does not move.
            y = vals["Y"] * scale if "Y" in vals else y
            z = vals["Z"] * scale if "Z" in vals else z
            if not tp.moves:
                tp.start = (y, z)
            else:
                tp.warnings.append(f"Line {n}: G92 after the first move; later coordinates are re-labelled.")
            continue
        if not (0 in gs or 1 in gs):
            continue
        ny = (vals["Y"] * scale if absolute else y + vals["Y"] * scale) if "Y" in vals else y
        nz = (vals["Z"] * scale if absolute else z + vals["Z"] * scale) if "Z" in vals else z
        dist = math.hypot(ny - y, nz - z)
        if dist <= 1e-9:
            continue
        dt = dist / (feed / 60.0) if feed > 0 else 0.0
        tp.moves.append(Move(y, z, ny, nz, feed, t, t + dt, n, rapid=0 in gs and 1 not in gs))
        t += dt
        y, z = ny, nz
    if tp.moves and not feed_seen:
        tp.warnings.append(f"No feed (F) found; timing assumes {default_feed_mm_min:g} mm/min.")
    return tp


def read_gcode(path: str, **kw) -> Toolpath:  # type: ignore[no-untyped-def]
    with open(path, encoding="utf-8", errors="replace") as fh:
        return parse_gcode(fh.read(), **kw)
