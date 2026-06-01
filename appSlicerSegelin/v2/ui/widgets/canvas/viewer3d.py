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

Axis convention (3D ← app):
    3D X  ← app Y   (profile horizontal, 0..area_y)
    3D Z  ← app Z   (profile height,    0..area_z)
    3D Y  =  foam depth (the wire's length); the wire runs along Y at a fixed
             (X, Z) and sweeps as the machine traces the profile.

Built on pyqtgraph.opengl so it embeds cleanly in the Qt window and renders
through the GPU. Degrades gracefully when no geometry is loaded.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph.opengl as gl
from PyQt6.QtGui import QVector3D
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ....core.geometry import Segment
from ...theming.tokens import Tokens, get_tokens

BED = 220.0          # Ender-3 bed is 220×220 mm
COL_HEIGHT = 250.0   # frame height
DEFAULT_DEPTH = 80.0  # foam block depth (wire length) when unknown

_FACES = np.array([
    [0, 1, 2], [0, 2, 3],  # bottom
    [4, 5, 6], [4, 6, 7],  # top
    [0, 1, 5], [0, 5, 4],  # sides
    [2, 3, 7], [2, 7, 6],
    [1, 2, 6], [1, 6, 5],
    [0, 3, 7], [0, 7, 4],
])


def _hex_rgba(hex_str: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    h = hex_str.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (r, g, b, alpha)


def _box_verts(x0, y0, z0, x1, y1, z1) -> np.ndarray:
    return np.array([
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
    ], dtype=float)


class Viewer3D(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = gl.GLViewWidget()
        self.view.setCameraPosition(distance=430, elevation=24, azimuth=-65)
        lay.addWidget(self.view)

        self._tokens: Tokens = get_tokens("dark")
        self._depth = DEFAULT_DEPTH
        self._area_y = BED
        self._area_z = 100.0
        self._segments: list[Segment] = []
        self._items: list = []
        self._wire = None
        self._cut = None
        self._rebuild()

    # ── public API ────────────────────────────────────────────────────
    def set_palette(self, theme: str) -> None:
        self._tokens = get_tokens(theme)  # type: ignore[arg-type]
        c = self._tokens.color
        self.view.setBackgroundColor(c.bg)
        self._rebuild()

    def set_model(self, segments: list[Segment], area_y: float, area_z: float, depth: float | None = None) -> None:
        self._segments = list(segments)
        self._area_y = max(10.0, area_y)
        self._area_z = max(10.0, area_z)
        if depth:
            self._depth = max(5.0, depth)
        self._rebuild()

    def set_wire(self, app_y: float, app_z: float) -> None:
        """Position the horizontal hot wire at (profile Y, profile Z)."""
        if self._wire is None:
            return
        y0, y1 = self._foam_depth_span()
        self._wire.setData(pos=np.array([[app_y, y0 - 6, app_z], [app_y, y1 + 6, app_z]]))

    def set_cut(self, trajectory: list[Segment], fraction: float) -> None:
        """Reveal the cut profile (front face) up to ``fraction`` of the path."""
        cut = [s for s in trajectory if s.kind.name == "CUT"]
        if not cut or self._cut is None:
            if self._cut is not None:
                self._cut.setData(pos=np.zeros((0, 3)))
            return
        n = len(cut)
        upto = max(0, min(n, round(fraction * n)))
        yf, _ = self._foam_depth_span()
        pts: list[list[float]] = []
        for s in cut[:upto]:
            pts.append([s.a.y, yf, s.a.z])
            pts.append([s.b.y, yf, s.b.z])
        self._cut.setData(pos=np.array(pts) if pts else np.zeros((0, 3)))
        if cut and upto:
            head = cut[upto - 1].b
            self.set_wire(head.y, head.z)

    # ── scene build ───────────────────────────────────────────────────
    def _foam_depth_span(self) -> tuple[float, float]:
        y0 = (BED - self._depth) / 2.0
        return (y0, y0 + self._depth)

    def _add(self, item) -> None:
        self.view.addItem(item)
        self._items.append(item)

    def _box(self, x0, y0, z0, x1, y1, z1, color, gl_opts="opaque") -> None:
        verts = _box_verts(x0, y0, z0, x1, y1, z1)
        m = gl.GLMeshItem(vertexes=verts, faces=_FACES, smooth=False, color=color,
                          glOptions=gl_opts, drawEdges=False)
        self._add(m)

    def _rebuild(self) -> None:
        for it in self._items:
            self.view.removeItem(it)
        self._items = []
        self._wire = None
        self._cut = None
        c = self._tokens.color
        self.view.setBackgroundColor(c.bg)

        # Heated bed + measurement grid.
        bed_top = _hex_rgba(c.surface_alt, 1.0)
        self._box(0, 0, -4, BED, BED, 0, bed_top)
        grid = gl.GLGridItem()
        grid.setSize(BED, BED)
        grid.setSpacing(20, 20)
        grid.translate(BED / 2, BED / 2, 0.5)
        gr, gg, gb, _ = _hex_rgba(c.muted)
        grid.setColor((gr, gg, gb, 0.8))
        self._add(grid)

        # Stylised Ender-3 frame (2020 extrusions) behind the bed.
        frame = _hex_rgba(c.muted, 1.0)
        s = 12.0  # extrusion thickness
        # base rails
        self._box(-s, -s, -8, BED + s, 0, 2, frame)
        self._box(-s, BED, -8, BED + s, BED + s, 2, frame)
        self._box(-s, -s, -8, 0, BED + s, 2, frame)
        self._box(BED, -s, -8, BED + s, BED + s, 2, frame)
        # back Z uprights + top gantry
        self._box(-s, BED - s, 0, 0, BED, COL_HEIGHT, frame)
        self._box(BED, BED - s, 0, BED + s, BED, COL_HEIGHT, frame)
        self._box(-s, BED - s, COL_HEIGHT - s, BED + s, BED, COL_HEIGHT, frame)

        # Foam block (the stock), translucent, sized to the work area.
        yf0, yf1 = self._foam_depth_span()
        foam = _hex_rgba(c.accent, 0.16)
        self._box(0, yf0, 0, self._area_y, yf1, self._area_z, foam, gl_opts="translucent")
        # foam wireframe edges for definition
        edges = gl.GLBoxItem(size=QVector3D(self._area_y, self._depth, self._area_z),
                             color=_pg_color(c.muted))
        edges.translate(0, yf0, 0)
        self._add(edges)

        # Target profile (full), faint, on the front face.
        if self._segments:
            pts = []
            for sg in self._segments:
                pts.append([sg.a.y, yf0, sg.a.z])
                pts.append([sg.b.y, yf0, sg.b.z])
            faint = _hex_rgba(c.muted, 0.55)
            self._add(gl.GLLinePlotItem(pos=np.array(pts), color=faint, width=1.4,
                                        antialias=True, mode="lines"))
            # back-face copy + a few depth connectors for the extruded look
            backp = [[p[0], yf1, p[2]] for p in pts]
            self._add(gl.GLLinePlotItem(pos=np.array(backp), color=_hex_rgba(c.muted, 0.3),
                                        width=1.0, antialias=True, mode="lines"))

        # Cut-so-far polyline (front face), bright accent.
        self._cut = gl.GLLinePlotItem(pos=np.zeros((0, 3)), color=_hex_rgba(c.accent, 1.0),
                                      width=3.0, antialias=True, mode="lines")
        self._add(self._cut)

        # Hot wire — bright, spans the foam depth, parked at the profile start.
        yf0, yf1 = self._foam_depth_span()
        start = self._segments[0].a if self._segments else None
        wy = start.y if start else self._area_y / 2
        wz = start.z if start else self._area_z / 2
        self._wire = gl.GLLinePlotItem(
            pos=np.array([[wy, yf0 - 6, wz], [wy, yf1 + 6, wz]]),
            color=(1.0, 0.32, 0.12, 1.0), width=5.0, antialias=True,
        )
        self._add(self._wire)

        # Aim the camera at the foam centre.
        self.view.opts["center"] = QVector3D(self._area_y / 2, BED / 2, self._area_z / 2)
        self.view.update()


def _pg_color(hex_str: str):
    from pyqtgraph import mkColor

    return mkColor(hex_str)
