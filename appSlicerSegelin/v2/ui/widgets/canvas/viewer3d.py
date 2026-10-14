"""3D slicer-style viewport for the hot-wire workflow.

Renders the scene the way a printer slicer (Cura / Bambu) does, but for a
hot-wire foam cutter built on an Ender-3:

* the printer — a stylised Ender-3 frame (bed, Z uprights, top gantry);
* the heated bed with a measurement grid;
* the **foam block** sitting on the bed (the stock we cut);
* the **hot wire** — a glowing horizontal wire that spans the foam depth and
  moves through it tracing the profile;
* the **cut** — the (Y, Z) profile extruded through the block, revealed as the
  simulation plays.

The G-code only drives the machine Y and Z axes (``G1 Y.. Z..``), so the cut
lives entirely in the vertical Y–Z plane and the wire — horizontal, fixed —
runs left↔right along the gantry (machine X), spanning the foam depth a.k.a.
the wing span.

Axis convention (3D ← app):
    3D X  =  foam depth (the wire's length); the wire runs left↔right along X
             at a fixed (Y, Z) and sweeps as the machine traces the profile.
    3D Y  ← app Y   (profile horizontal / chord, 0..area_y) — recedes into the
             scene, so the airfoil is traced in the vertical Y–Z plane.
    3D Z  ← app Z   (profile height,    0..area_z)

Drawn through :class:`~..view3d.Scene3D` (three.js, or OpenGL where WebGL
isn't available).
"""
from __future__ import annotations

import numpy as np
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ....core.geometry import Segment
from ..view3d import Scene3D

BED = 220.0          # Ender-3 bed is 220×220 mm
COL_HEIGHT = 250.0   # frame height
DEFAULT_DEPTH = 80.0  # foam block depth (wire length) when unknown
FOAM = "#7FB2E5"
WIRE = "#FF5A1F"
ALU = "#9aa3ad"


def _seg_pts(segments: list[Segment], x: float) -> np.ndarray:
    pts = np.empty((2 * len(segments), 3), np.float32)
    for i, s in enumerate(segments):
        pts[2 * i] = (x, s.a.y, s.a.z)
        pts[2 * i + 1] = (x, s.b.y, s.b.z)
    return pts


class Viewer3D(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.scene = Scene3D(self)
        lay.addWidget(self.scene)
        self._depth = DEFAULT_DEPTH
        self._area_y = BED
        self._area_z = 100.0
        self._segments: list[Segment] = []
        self._cut_key: tuple = ()
        self._framed = False
        self._rebuild()

    # ── public API ────────────────────────────────────────────────────
    def set_palette(self, theme: str) -> None:
        self.scene.set_theme(theme)

    def set_model(self, segments: list[Segment], area_y: float, area_z: float, depth: float | None = None) -> None:
        self._segments = list(segments)
        self._area_y = max(10.0, area_y)
        self._area_z = max(10.0, area_z)
        if depth:
            self._depth = max(5.0, depth)
        self._rebuild()

    def set_wire(self, app_y: float, app_z: float) -> None:
        """Position the horizontal hot wire at (profile Y, profile Z)."""
        self.scene.offset("wire", (0.0, app_y, app_z))

    def set_cut(self, trajectory: list[Segment], fraction: float) -> None:
        """Reveal the cut profile (front face) up to ``fraction`` of the path."""
        cut = [s for s in trajectory if s.kind.name == "CUT"]
        if not cut:
            self.scene.remove("cut")
            return
        df, _ = self._depth_span()
        key = (len(cut), id(trajectory), cut[0].a.y, cut[-1].b.z, df)
        if key != self._cut_key or not self.scene.has("cut"):
            self._cut_key = key
            self.scene.lines("cut", _seg_pts(cut, df - 0.2), "#F59E0B", width=3.0, mode="segments")
        upto = max(0, min(len(cut), round(fraction * len(cut))))
        self.scene.progress("cut", upto)
        if upto:
            head = cut[upto - 1].b
            self.set_wire(head.y, head.z)

    # ── scene build ───────────────────────────────────────────────────
    def _depth_span(self) -> tuple[float, float]:
        """Foam depth span along 3D X (the wire's left↔right travel), centred on the bed."""
        d0 = (BED - self._depth) / 2.0
        return (d0, d0 + self._depth)

    def _rebuild(self) -> None:
        sc = self.scene
        sc.clear()
        self._cut_key = ()
        # heated bed (dark glass) with a 20 mm grid
        sc.box("bed", 0, 0, -4, BED, BED, 0, "#22272e", edges=True, roughness=0.35)
        step = 20.0
        grid: list[list[float]] = []
        for i in range(int(BED // step) + 1):
            v = i * step
            grid += [[v, 0.0, 0.05], [v, BED, 0.05], [0.0, v, 0.05], [BED, v, 0.05]]
        sc.lines("grid", np.array(grid), "#5d6773", width=1.0, mode="segments", opacity=0.55)

        # stylised Ender-3 frame (2020 extrusions)
        s = 12.0
        for name, box in {
            "rail_f": (-s, -s, -8, BED + s, 0, 2), "rail_b": (-s, BED, -8, BED + s, BED + s, 2),
            "rail_l": (-s, -s, -8, 0, BED + s, 2), "rail_r": (BED, -s, -8, BED + s, BED + s, 2),
            "up_l": (-s, BED - s, 0, 0, BED, COL_HEIGHT), "up_r": (BED, BED - s, 0, BED + s, BED, COL_HEIGHT),
            "top": (-s, BED - s, COL_HEIGHT - s, BED + s, BED, COL_HEIGHT),
        }.items():
            sc.box(name, *box, ALU, metalness=0.55, roughness=0.4, edges=True)

        # foam block, translucent, sized to the work area
        d0, d1 = self._depth_span()
        sc.box("foam", d0, 0, 0, d1, self._area_y, self._area_z, FOAM, opacity=0.28)
        e = np.array([[d0, 0, 0], [d1, 0, 0], [d1, self._area_y, 0], [d0, self._area_y, 0], [d0, 0, 0],
                      [d0, 0, self._area_z], [d1, 0, self._area_z], [d1, self._area_y, self._area_z],
                      [d0, self._area_y, self._area_z], [d0, 0, self._area_z], [np.nan] * 3,
                      [d1, 0, 0], [d1, 0, self._area_z], [np.nan] * 3,
                      [d1, self._area_y, 0], [d1, self._area_y, self._area_z], [np.nan] * 3,
                      [d0, self._area_y, 0], [d0, self._area_y, self._area_z]], np.float32)
        sc.lines("foam_edges", e, "#9cc3e6", width=1.2, opacity=0.8)

        # target profile on both faces of the foam
        if self._segments:
            sc.lines("profile_front", _seg_pts(self._segments, d0 - 0.1), "#c7ced6", width=1.6,
                     mode="segments", opacity=0.85)
            sc.lines("profile_back", _seg_pts(self._segments, d1 + 0.1), "#c7ced6", width=1.2,
                     mode="segments", opacity=0.45)

        # hot wire: spans the foam depth along X; moved with the "wire" group offset
        sc.lines("wire", np.array([[d0 - 6, 0, 0], [d1 + 6, 0, 0]]), WIRE, width=4.0, group="wire")
        start = self._segments[0].a if self._segments else None
        self.set_wire(start.y if start else self._area_y / 2, start.z if start else self._area_z / 2)
        if not self._framed:
            self._framed = True
            sc.fit(24, -65, animate=False)
