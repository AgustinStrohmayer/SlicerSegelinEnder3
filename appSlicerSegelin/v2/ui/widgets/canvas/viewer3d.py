"""3D slicer-style viewport for the hot-wire workflow.

Shows the real machine the way it cuts: the Ender-3 (from its CAD, see
:mod:`...core.machine_model`) with the segelín mounted on the X beam — C
clamps, T pieces, the two pivoting arms, the hot wire through the arms'
lower holes and the tension spring hooked through the upper ones — over the
foam block on the bed, with the profile on both faces and the cut revealed as
the simulation plays.

The G-code only drives Y and Z: the **bed** (and the foam on it) rides along
Y and the **gantry** (with the wire) rides along Z, so ``set_wire`` moves
those two groups exactly like the printer does.

World frame (shared with the machine simulator):
    X  along the wire, 0 = wire span centre (the foam's depth / wing span)
    Y  along the bed travel, 0 = the wire's vertical plane, + towards the back
    Z  up, 0 = bed top
In the bed group, G-code Y maps to Y unchanged; in the gantry group Z = 0 is
the wire. The machine and the foam block are the project's (``Project.rig`` /
``Project.block``), the same ones the simulator and the Cut Lab use.

Drawn through :class:`~..view3d.Scene3D` (three.js, or OpenGL where WebGL
isn't available).
"""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ....core.geometry import Segment
from ....core.hotwire_rig import DEFAULT_PRESET, PRESETS, FoamBlock, HotWireRig, bed_height
from ....core.machine_model import arm_mesh, load_machine_model, mount_mesh
from ..view3d import Scene3D
from ..view3d.scene import BOX_FACES

FOAM = "#7FB2E5"
FOAM_ALERT = "#E5484D"  # the block or the cut doesn't fit the machine
WIRE = "#FF5A1F"
PLA = "#3ec46d"
HOLE_Y = 5.5          # mid-thickness of the printed arm (its holes run across its width there)
WIRE_PAST_HOLE = 18.0  # wire beyond each arm's lower hole, to the clip
SPRING_R, SPRING_TURNS = 3.2, 13
GAP = 0.3  # mm between stacked faces (bed / spacer / foam): coincident faces flicker (z-fighting)


def _box(x0: float, y0: float, z0: float, x1: float, y1: float, z1: float) -> np.ndarray:
    return np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                     [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], np.float32)


def _seg_pts(segments: list[Segment], x: float) -> np.ndarray:
    pts = np.empty((2 * len(segments), 3), np.float32)
    for i, s in enumerate(segments):
        pts[2 * i] = (x, s.a.y, s.a.z)
        pts[2 * i + 1] = (x, s.b.y, s.b.z)
    return pts


_KIND_RGB = {"cut": (0.96, 0.62, 0.04)}  # the cut in amber; entry, exit and travel in a pale grey-blue


def _kind_rgb(kind) -> tuple[float, float, float]:  # type: ignore[no-untyped-def]
    return _KIND_RGB.get(getattr(kind, "value", kind), (0.62, 0.72, 0.82))


def _lift(colour: str) -> str:
    """The printer is mostly black: lift it a little off dark backgrounds."""
    return QColor(colour).lighter(150).name()


def rig_holes(rig: HotWireRig) -> dict[str, list[tuple[float, float]]]:
    """(x, z) of the arms' lower (wire) and upper (spring) holes, gantry frame (wire at Z = 0)."""
    a = math.radians(rig.arm_angle_deg)
    out: dict[str, list[tuple[float, float]]] = {"wire": [], "spring": []}
    for side in (-1.0, 1.0):
        px = side * rig.pivot_spacing / 2
        out["wire"].append((px + side * rig.arm_lower_length * math.cos(a), 0.0))
        out["spring"].append((px - side * rig.arm_upper_length * math.cos(a),
                              rig.wire_drop + rig.arm_upper_length * math.sin(a)))
    return out


def spring_points(rig: HotWireRig, y: float = HOLE_Y) -> np.ndarray:
    """Tension spring between the upper holes: an eye through each hole hugging the arm tip, then the coil."""
    a = math.radians(rig.arm_angle_deg)
    (xl, z), (xr, _) = rig_holes(rig)["spring"]
    pts: list[list[float]] = []
    eyes = []
    for side, hx in ((-1.0, xl), (1.0, xr)):
        u = np.array([-side * math.cos(a), math.sin(a)])  # along the arm, towards its upper tip
        n = np.array([u[1], -u[0]])
        c = np.array([hx, z]) + u * 2.5
        t = np.linspace(0, 2 * math.pi, 25)
        loop = c + np.outer(np.cos(t), u) * 4.75 + np.outer(np.sin(t), n) * 3.2
        eyes.append(loop)
    # left eye, coil from just inside the left hole to just inside the right one, right eye
    x0, x1 = xl + 4.0, xr - 4.0
    t = np.linspace(0, SPRING_TURNS * 2 * math.pi, SPRING_TURNS * 20 + 1)
    coil = np.column_stack([x0 + (x1 - x0) * t / t[-1], y + SPRING_R * np.sin(t), z + SPRING_R * np.cos(t)])
    for x_, z_ in eyes[0]:
        pts.append([x_, y, z_])
    pts.append([xl, y, z])
    pts += coil.tolist()
    pts.append([xr, y, z])
    for x_, z_ in eyes[1]:
        pts.append([x_, y, z_])
    return np.array(pts, np.float32)


class Viewer3D(QWidget):
    def __init__(self, parent: QWidget | None = None, rig: HotWireRig | None = None,
                 block: FoamBlock | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.scene = Scene3D(self)
        lay.addWidget(self.scene)
        self.rig = rig or PRESETS[DEFAULT_PRESET]
        self.block = block or FoamBlock(spacer=10.0)
        self.block_shown = True  # False until step 1 puts the block on the bed: just the printer
        self.alert = False  # the block or the cut doesn't fit the machine: foam drawn red
        self._segments: list[Segment] = []
        self._cut_key: tuple = ()
        self._framed = False
        self._rig_ids: list[str] = []
        self._printer_ids: list[str] = []
        self._printer_model: str | None = None
        self._path: list[Segment] = []
        self._cum = np.zeros(1)
        self._fraction = 0.0
        self._preview = QTimer(self)
        self._preview.setInterval(16)
        self._preview.timeout.connect(self._preview_tick)
        self._rebuild()

    # ── public API ────────────────────────────────────────────────────
    def set_palette(self, theme: str) -> None:
        self.scene.set_theme(theme)

    def set_setup(self, rig: HotWireRig, block: FoamBlock, shown: bool = True, alert: bool = False) -> None:
        """The project's machine and foam block; ``shown``: the block is on the bed; ``alert``: it has problems."""
        if (rig, block, shown, alert) == (self.rig, self.block, self.block_shown, self.alert):
            return
        appeared = shown and not self.block_shown
        rig_changed = rig != self.rig
        self.rig, self.block, self.block_shown, self.alert = rig, block, shown, alert
        if rig_changed:  # only a new machine resends the printer's meshes (the heavy part)
            self._build_rig()
        self._build_block()
        self._place()
        if appeared:  # the block was just put on the bed: frame the printer with it
            self.scene.fit(20, -62)

    def set_model(self, segments: list[Segment]) -> None:
        segments = list(segments)
        if segments == self._segments and self.scene.has("profile_front") == bool(segments and self.block_shown):
            return
        self._segments = segments
        self._build_block()
        self._place()

    def set_wire(self, app_y: float, app_z: float) -> None:
        """Put the wire at (G-code Y, G-code Z): the bed slides along Y, the gantry along Z."""
        b = self.block
        # the wire runs through the arms' holes at HOLE_Y: G-code Y lands there, so the cut drawn on the
        # block passes exactly under the wire
        self.scene.offset("bed", (0.0, HOLE_Y - app_y, 0.0))
        self.scene.offset("bedplate", (0.0, HOLE_Y + (b.y0 + b.y1) / 2 - app_y, 0.0))  # centred under the block
        h = bed_height(self.block, app_z)
        self.scene.offset("gantry", (0.0, 0.0, h))
        self.scene.offset("gantry_cad", (0.0, 0.0, h + self.rig.wire_drop))

    def set_cut(self, trajectory: list[Segment], fraction: float) -> None:
        """The wire's whole path on both foam faces — entry, cut and exit — revealed up to ``fraction``
        of its length (the feed is constant, so that is also the fraction of the time)."""
        path = [sg for sg in trajectory if sg.a.distance_to(sg.b) > 1e-9]
        if not path or not self.block_shown:
            self._path = []
            for oid in ("path", "cut", "cut_back"):
                self.scene.remove(oid)
            return
        b = self.block
        key = (len(path), path[0], path[-1], b)
        if key != self._cut_key or not self.scene.has("cut"):
            self._cut_key = key
            self._path = path
            lens = np.array([sg.a.distance_to(sg.b) for sg in path])
            self._cum = np.concatenate([[0.0], np.cumsum(lens)])
            cols = np.repeat(np.array([_kind_rgb(sg.kind) for sg in path], np.float32), 2, axis=0)
            xf, xb = b.x_offset - b.width_x / 2 - 0.4, b.x_offset + b.width_x / 2 + 0.4
            # the whole path, thin and grey, always visible: where the wire will go; what it has cut
            # so far is drawn over it in colour, up to the wire
            self.scene.lines("path", self._bed_pts(_seg_pts(path, xf - 0.2)), "#8A94A3", width=1.4, mode="segments",
                             opacity=0.7, group="bed")
            for oid, x in (("cut", xf), ("cut_back", xb)):
                self.scene.lines(oid, self._bed_pts(_seg_pts(path, x)), "#F59E0B", width=3.0, mode="segments",
                                 colors=cols, group="bed")
        if self._preview.isActive():
            if fraction == self._fraction:
                return  # a refresh during the preview: let it play
            self._preview.stop()
        self._fraction = fraction
        self._show(fraction)

    def preview(self, seconds: float = 3.5) -> None:
        """Play the wire along its whole path once (entry, cut, exit), then back to the timeline's state."""
        if not self._path:
            return
        import time

        self._preview_t0, self._preview_s = time.perf_counter(), seconds
        self._preview.start()

    def _preview_tick(self) -> None:
        import time

        f = (time.perf_counter() - self._preview_t0) / self._preview_s
        if f >= 1.0:
            self._preview.stop()
            f = self._fraction
        self._show(f)

    def _show(self, fraction: float) -> None:
        """Reveal the path up to ``fraction`` of its length, the wire at the head."""
        if not self._path:
            return
        total = float(self._cum[-1])
        d = max(0.0, min(1.0, fraction)) * total
        k = int(np.searchsorted(self._cum, d, side="right")) - 1  # segments fully done
        k = max(0, min(k, len(self._path)))
        head = None
        if k < len(self._path) and d > 0:
            sg = self._path[k]
            t = (d - self._cum[k]) / max(self._cum[k + 1] - self._cum[k], 1e-9)
            y, z = sg.a.y + (sg.b.y - sg.a.y) * t, sg.a.z + (sg.b.z - sg.a.z) * t
        elif k:
            y, z = self._path[k - 1].b.y, self._path[k - 1].b.z
        else:
            y, z = self._path[0].a.y, self._path[0].a.z
        b = self.block
        for oid, x in (("cut", b.x_offset - b.width_x / 2 - 0.4), ("cut_back", b.x_offset + b.width_x / 2 + 0.4)):
            if d > 0 and k < len(self._path):
                head = (x, y, bed_height(b, z))
            self.scene.progress(oid, k, head)
        self.set_wire(y, z)

    # ── scene build ───────────────────────────────────────────────────
    def _bed_pts(self, pts: np.ndarray) -> np.ndarray:
        """G-code (x, y, z) -> bed frame: the block's bottom face sits on the spacer."""
        out = np.array(pts, np.float32)
        out[:, 2] = bed_height(self.block, out[:, 2])
        return out

    def _rebuild(self) -> None:
        self.scene.clear()
        self._printer_ids, self._rig_ids = [], []
        self._build_rig()
        self._build_block()
        self._place()

    def _place(self) -> None:
        """Wire at the profile's start (or mid-block), framing the view once."""
        self._path = []  # the path lines were cleared with the block: set_cut redraws them
        b = self.block
        start = self._segments[0].a if self._segments and self.block_shown else None
        self.set_wire(start.y if start else (b.y0 + b.y1) / 2, start.z if start else (b.z0 + b.z1) / 2)
        if not self._framed:
            self._framed = True
            self.scene.fit(20, -62, animate=False)

    def _build_rig(self) -> None:
        """Printer + segelín. The printer's meshes (the heavy part) are only resent for another model;
        new measurements of the segelín just redraw its arms, wire and spring."""
        sc, rig = self.scene, self.rig
        model = load_machine_model(rig.model)
        if rig.model != self._printer_model or not self._printer_ids:
            for oid in self._printer_ids:
                sc.remove(oid)
            before = set(sc._objects)
            if model is not None:
                self._build_printer(model)
            else:
                self._build_plain()
            self._printer_ids = [k for k in sc._objects if k not in before]
            self._printer_model = rig.model
        for oid in self._rig_ids:
            sc.remove(oid)
        before = set(sc._objects)
        if model is not None:
            self._build_segelin(model)
        (wl, _), (wr, _) = rig_holes(rig)["wire"]
        ends = (wl - WIRE_PAST_HOLE, wr + WIRE_PAST_HOLE)
        sc.lines("wire", np.array([[ends[0], HOLE_Y, 0], [ends[1], HOLE_Y, 0]]), WIRE, width=3.5, group="gantry")
        for oid, x, col in (("clip_l", ends[0], "#d33b3b"), ("clip_r", ends[1], "#2a2a2a")):
            x0, x1 = (x - 12, x) if x < 0 else (x, x + 12)
            sc.mesh(oid, _box(x0, HOLE_Y - 3.5, -3.5, x1, HOLE_Y + 3.5, 3.5), BOX_FACES, col, group="gantry",
                    roughness=0.6)
        sc.lines("spring", spring_points(rig), "#c8ccd2", width=1.6, group="gantry")
        self._rig_ids = [k for k in sc._objects if k not in before]

    def _build_block(self) -> None:
        """Bed group: spacer board, translucent foam block, its edges, the target profile on both faces."""
        sc, b = self.scene, self.block
        sc.clear("bed")  # spacer, foam, edges, profiles, cut: cheap to resend
        self._cut_key = ()
        if not self.block_shown:
            return
        xl, xr = b.x_offset - b.width_x / 2, b.x_offset + b.width_x / 2
        ya, yb = b.y0, b.y1
        z0, z1 = b.spacer, b.spacer + b.height_z
        if b.spacer > 0:
            sc.box("spacer", xl - 5, ya - 5, GAP, xr + 5, yb + 5, b.spacer - GAP, "#9a7a55", group="bed", roughness=0.8)
        sc.box("foam", xl, ya, z0 + GAP, xr, yb, z1, FOAM_ALERT if self.alert else FOAM,
               opacity=0.34 if self.alert else 0.28, group="bed")
        e = np.array([[xl, ya, z0], [xr, ya, z0], [xr, yb, z0], [xl, yb, z0], [xl, ya, z0],
                      [xl, ya, z1], [xr, ya, z1], [xr, yb, z1], [xl, yb, z1], [xl, ya, z1], [np.nan] * 3,
                      [xr, ya, z0], [xr, ya, z1], [np.nan] * 3, [xr, yb, z0], [xr, yb, z1], [np.nan] * 3,
                      [xl, yb, z0], [xl, yb, z1]], np.float32)
        sc.lines("foam_edges", e, "#f08a8c" if self.alert else "#9cc3e6", width=1.2, opacity=0.8, group="bed")
        if self._segments:
            for oid, x in (("profile_front", xl - 0.2), ("profile_back", xr + 0.2)):
                sc.lines(oid, self._bed_pts(_seg_pts(self._segments, x)), "#c7ced6", width=1.4,
                         mode="segments", opacity=0.7, group="bed")

    def _build_printer(self, model) -> None:  # type: ignore[no-untyped-def]
        """The printer's CAD (depends only on the model): frame static, bed plate, gantry ("gantry_cad",
        raised to the pivots in ``set_wire``)."""
        for name, group in (("frame", ""), ("bed", "bedplate"), ("gantry", "gantry_cad")):
            for i, part in enumerate(model.groups.get(name, [])):
                self.scene.mesh(f"{name}{i}", part.vertices, part.faces, _lift(part.colour), group=group,
                                metalness=0.3, roughness=0.5)

    def _build_segelin(self, model) -> None:  # type: ignore[no-untyped-def]
        """The printed parts on the gantry: C clamps, T pieces and arms, placed for this rig."""
        sc, rig = self.scene, self.rig
        lift = np.array([0.0, 0.0, rig.wire_drop], np.float32)  # pivot axis -> wire frame
        pla = model.parts["arm"].colour if "arm" in model.parts else PLA
        for side, tag in ((-1.0, "l"), (1.0, "r")):
            for mount in ("clamp", "tee"):
                sc.mesh(f"{mount}_{tag}", mount_mesh(model, mount, rig, side) + lift, model.parts[mount].faces, pla,
                        group="gantry", roughness=0.7)
            sc.mesh(f"arm_{tag}", arm_mesh(model, rig, side) + lift, model.parts["arm"].faces, pla,
                    group="gantry", roughness=0.7)

    def _build_plain(self) -> None:
        """No CAD for this rig: a plain bed and uprights so the cut still has context."""
        sc, rig = self.scene, self.rig
        half = rig.frame_width / 2
        sc.box("bed_plate", -rig.bed_x / 2, -rig.bed_y / 2, -6, rig.bed_x / 2, rig.bed_y / 2, 0,
               "#26272b", group="bedplate", edges=True)
        for tag, sx in (("l", -1), ("r", 1)):
            x0 = sx * half
            sc.box(f"upright_{tag}", min(x0, x0 - sx * 20), 25, -40, max(x0, x0 - sx * 20), 65, rig.frame_height,
                   "#9aa3ad", metalness=0.55, roughness=0.4)
        sc.box("top", -half, 25, rig.frame_height - 20, half, 45, rig.frame_height, "#9aa3ad", metalness=0.55)
