"""3D machine simulator: play any hot-wire G-code on a parametric printer.

Unlike :mod:`viewer3d` (which previews the current project's profile), this
view animates the *machine*: the bed carries the foam block back and forth
along Y, the gantry carries the arms, spring and hot wire up and down along Z,
and the kerf grows on the block's side faces exactly where the wire has been.

Everything comes from pure models so the numbers match the Blender
animation and the checks:

* :mod:`core.gcode_reader` — the timed toolpath (where is the wire at *t*);
* :mod:`core.hotwire_rig` — the printer + arms (preset, editable) and the
  foam block, :func:`check_cut` warnings and :func:`machine_pose` per frame;
* :mod:`core.machine_model` — the printer's CAD (Ender-3 presets), with the
  real printed arms stretched and swung to the rig's lengths and angle. Other
  presets fall back to a schematic frame.

World frame (mm): X across the bed along the wire (0 = wire span centre),
Y along the bed travel (0 = the wire's vertical plane), Z up (0 = bed top).
"""
from __future__ import annotations

import bisect
import math
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ....core.gcode_reader import Toolpath, parse_gcode
from ....core.hotwire_rig import PRESETS, FoamBlock, HotWireRig, bed_height, check_cut, fit_block, machine_pose
from ....core.machine_model import arm_mesh, load_machine_model, mount_mesh
from ...theming.tokens import get_tokens
from ..view3d import Scene3D
from ..view3d.scene import BOX_FACES

_FACES = BOX_FACES
SPEEDS = (1.0, 2.0, 5.0, 10.0, 20.0)


def _rgba(color: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    r, g, b, _ = QColor(color).getRgbF()
    return (r, g, b, alpha)


def _box(x0: float, y0: float, z0: float, x1: float, y1: float, z1: float) -> np.ndarray:
    return np.array([
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
    ], dtype=float)


def _beam(p0: tuple[float, float], p1: tuple[float, float], width: float, y0: float, y1: float) -> np.ndarray:
    """Box between two (x, z) points, ``width`` wide in the XZ plane, spanning ``y0..y1``."""
    dx, dz = p1[0] - p0[0], p1[1] - p0[1]
    n = math.hypot(dx, dz) or 1.0
    ox, oz = -dz / n * width / 2, dx / n * width / 2
    q = [(p0[0] + ox, p0[1] + oz), (p1[0] + ox, p1[1] + oz), (p1[0] - ox, p1[1] - oz), (p0[0] - ox, p0[1] - oz)]
    return np.array([[x, y0, z] for x, z in q] + [[x, y1, z] for x, z in q], dtype=float)


def rig_points(rig: HotWireRig) -> dict[str, list[tuple[float, float]]]:
    """(x, z) of pivots, wire tips and spring tips, relative to the wire height."""
    a = math.radians(rig.arm_angle_deg)
    piv = rig.wire_drop
    out: dict[str, list[tuple[float, float]]] = {"pivots": [], "wire": [], "spring": []}
    for side in (-1.0, 1.0):
        px = side * rig.pivot_spacing / 2
        out["pivots"].append((px, piv))
        out["wire"].append((px + side * rig.arm_lower_length * math.cos(a), 0.0))
        out["spring"].append((px - side * rig.arm_upper_length * math.cos(a), piv + rig.arm_upper_length * math.sin(a)))
    return out


class MachineSimulator(QWidget):
    """3D playback of a G-code on a parametric hot-wire printer, with its controls."""

    def __init__(self, parent: QWidget | None = None, theme: str = "dark") -> None:
        super().__init__(parent)
        self._theme = theme
        self._c = get_tokens(theme).color  # type: ignore[arg-type]
        self.rig: HotWireRig = PRESETS["Ender-3 (long arms)"]
        self.toolpath: Toolpath = parse_gcode("")
        self.block = FoamBlock(spacer=10.0)
        self.name = ""
        self.t = 0.0
        self._last = 0.0
        self._bed_items: list = []
        self._gantry_items: list = []
        self._static_items: list = []
        self._kerf: list = []
        self._carriage = None
        self._carriage_ok = (0.0, 0.0, 0.0, 0.0)
        self._syncing = False
        self._n = 0
        self._framed = False
        self._kerf_t1: list[float] = []
        self._kerf_x: tuple[float, ...] = ()

        self.view = Scene3D(self, theme)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        left = QWidget(self)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.view, 1)
        lv.addLayout(self._build_transport())
        split.addWidget(left)
        split.addWidget(self._build_panel())
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([900, 340])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split)

        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._apply_preset("Ender-3 (long arms)")

    # ── public API ────────────────────────────────────────────────────
    def load_text(self, text: str, name: str = "G-code") -> None:
        self.toolpath = parse_gcode(text)
        self.name = name
        self.code.setPlainText(text)
        if self.toolpath.moves:
            self.block = replace(fit_block(self.toolpath, width_x=min(150.0, self.rig.usable_width(30.0))),
                                 spacer=self.block.spacer)
        self._sync_block_controls()
        self.t = 0.0
        self._rebuild()
        self._set_time(0.0)

    def load_file(self, path: str) -> None:
        with open(path, encoding="utf-8", errors="replace") as fh:
            self.load_text(fh.read(), Path(path).name)

    def set_rig(self, rig: HotWireRig) -> None:
        self.rig = rig
        self._rebuild()
        self._set_time(self.t)

    def set_block(self, block: FoamBlock) -> None:
        self.block = block
        self._sync_block_controls()
        self._rebuild()
        self._set_time(self.t)

    # ── controls ──────────────────────────────────────────────────────
    def _build_transport(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(6, 4, 6, 6)
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setCheckable(True)
        self.play_btn.toggled.connect(self._toggle_play)
        self.speed = QComboBox()
        self.speed.addItems([f"{s:g}×" for s in SPEEDS])
        self.speed.setCurrentIndex(2)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(lambda v: self._set_time(v / 1000 * self.toolpath.total_s))
        self.clock = QLabel("0.0 / 0.0 s")
        self.clock.setMinimumWidth(110)
        for w in (self.play_btn, self.speed):
            row.addWidget(w)
        row.addWidget(self.slider, 1)
        row.addWidget(self.clock)
        return row

    def _spin(self, lo: float, hi: float, val: float, step: float = 1.0, suffix: str = " mm") -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(1)
        s.setSingleStep(step)
        s.setValue(val)
        s.setSuffix(suffix)
        s.setKeyboardTracking(False)
        return s

    def _build_panel(self) -> QWidget:
        panel = QWidget(self)
        v = QVBoxLayout(panel)
        v.setContentsMargins(8, 8, 8, 8)

        open_btn = QPushButton("Open G-code…")
        open_btn.clicked.connect(self._on_open)
        v.addWidget(open_btn)

        g = QGroupBox("Machine")
        f = QFormLayout(g)
        self.preset = QComboBox()
        self.preset.addItems(list(PRESETS))
        self.preset.currentTextChanged.connect(self._apply_preset)
        f.addRow("Preset", self.preset)
        self.sp_ang = self._spin(30, 89, 70, 1, " °")
        self.sp_low = self._spin(30, 250, 70)
        self.sp_up = self._spin(30, 150, 70)
        self.sp_piv = self._spin(40, 400, 140.6)
        self.sp_ytr = self._spin(50, 1000, 220)
        self.sp_ztr = self._spin(50, 1000, 250)
        for label, sp in (("Arm angle", self.sp_ang), ("Arm, pivot→wire", self.sp_low),
                          ("Arm, pivot→spring", self.sp_up), ("Pivot spacing", self.sp_piv),
                          ("Y travel", self.sp_ytr), ("Z travel", self.sp_ztr)):
            f.addRow(label, sp)
            sp.valueChanged.connect(self._on_rig_edit)
        self.real = QCheckBox("Draw the printer's 3D model")
        self.real.setChecked(True)
        self.real.setToolTip("Ender-3 presets: the CAD of the printer and of the printed arms.\n"
                             "Other presets, or unchecked: a schematic frame.")
        self.real.toggled.connect(lambda _: (self._rebuild(), self._set_time(self.t)))
        f.addRow(self.real)
        self.rig_info = QLabel()
        self.rig_info.setWordWrap(True)
        f.addRow(self.rig_info)
        v.addWidget(g)

        g = QGroupBox("Foam block (G-code coordinates)")
        f = QFormLayout(g)
        self.sp_len = self._spin(5, 1000, 220)
        self.sp_h = self._spin(5, 500, 20)
        self.sp_w = self._spin(5, 1000, 150)
        self.sp_y0 = self._spin(-500, 500, 0)
        self.sp_z0 = self._spin(-500, 500, 0)
        self.sp_spacer = self._spin(0, 200, 10)
        self.sp_spacer.setToolTip("Board under the block: the arm tips hang below the wire and need it to clear the bed.")
        for label, sp in (("Length (Y)", self.sp_len), ("Height (Z)", self.sp_h), ("Width (X)", self.sp_w),
                          ("Front face at Y", self.sp_y0), ("Bottom face at Z", self.sp_z0),
                          ("Spacer under block", self.sp_spacer)):
            f.addRow(label, sp)
            sp.valueChanged.connect(self._on_block_edit)
        fit = QPushButton("Fit block to G-code")
        fit.clicked.connect(lambda: self.set_block(
            replace(fit_block(self.toolpath, width_x=self.sp_w.value()), spacer=self.sp_spacer.value())))
        f.addRow(fit)
        v.addWidget(g)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.status)
        self.readout = QLabel()
        self.readout.setProperty("role", "mono")
        v.addWidget(self.readout)
        self.code = QPlainTextEdit()
        self.code.setReadOnly(True)
        self.code.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.code.setProperty("role", "mono")
        v.addWidget(self.code, 1)
        return panel

    def _apply_preset(self, name: str) -> None:
        self.rig = PRESETS[name]
        self._syncing = True
        for sp, val in ((self.sp_ang, self.rig.arm_angle_deg), (self.sp_low, self.rig.arm_lower_length),
                        (self.sp_up, self.rig.arm_upper_length), (self.sp_piv, self.rig.pivot_spacing),
                        (self.sp_ytr, self.rig.y_travel), (self.sp_ztr, self.rig.z_travel)):
            sp.setValue(val)
        self._syncing = False
        if self.preset.currentText() != name:
            self.preset.blockSignals(True)
            self.preset.setCurrentText(name)
            self.preset.blockSignals(False)
        self.set_rig(self.rig)

    def _on_rig_edit(self) -> None:
        if self._syncing:
            return
        self.set_rig(replace(self.rig, arm_angle_deg=self.sp_ang.value(), arm_lower_length=self.sp_low.value(),
                             arm_upper_length=self.sp_up.value(), pivot_spacing=self.sp_piv.value(),
                             y_travel=self.sp_ytr.value(), z_travel=self.sp_ztr.value()))

    def _sync_block_controls(self) -> None:
        self._syncing = True
        b = self.block
        for sp, val in ((self.sp_len, b.length_y), (self.sp_h, b.height_z), (self.sp_w, b.width_x),
                        (self.sp_y0, b.y0), (self.sp_z0, b.z0), (self.sp_spacer, b.spacer)):
            sp.setValue(val)
        self._syncing = False

    def _on_block_edit(self) -> None:
        if self._syncing:
            return
        self.block = FoamBlock(length_y=self.sp_len.value(), height_z=self.sp_h.value(), width_x=self.sp_w.value(),
                               y0=self.sp_y0.value(), z0=self.sp_z0.value(), x_offset=self.block.x_offset,
                               spacer=self.sp_spacer.value())
        self._rebuild()
        self._set_time(self.t)

    def _on_open(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open G-code", filter="G-code (*.gcode *.nc *.txt);;All files (*)")
        if path:
            self.load_file(path)

    def _toggle_play(self, on: bool) -> None:
        self.play_btn.setText("❚❚ Pause" if on else "▶ Play")
        if on:
            if self.t >= self.toolpath.total_s:
                self.t = 0.0
            self._last = time.perf_counter()
            self._timer.start()
        else:
            self._timer.stop()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt, self._last = now - self._last, now
        t = self.t + dt * SPEEDS[self.speed.currentIndex()]
        if t >= self.toolpath.total_s:
            t = self.toolpath.total_s
            self.play_btn.setChecked(False)
        self._set_time(t)

    # ── scene ─────────────────────────────────────────────────────────
    def _id(self, group: list) -> str:
        self._n += 1
        return f"o{self._n}"

    def _scene_group(self, group: list) -> str:
        return "bed" if group is self._bed_items else ("gantry" if group is self._gantry_items else "")

    def _mesh(self, verts: np.ndarray, color, group: list, translucent: bool = False):
        return self._raw_mesh(verts, _FACES, color, group, translucent=translucent)

    def _line(self, pts, color, width: float, group: list, mode: str = "line_strip"):
        oid = self._id(group)
        self.view.lines(oid, np.array(pts, dtype=float).reshape(-1, 3), color, width=width,
                        mode="strip" if mode == "line_strip" else "segments", group=self._scene_group(group))
        group.append(oid)
        return oid

    def _rebuild(self) -> None:
        self.view.clear()
        self._bed_items, self._gantry_items, self._static_items, self._kerf = [], [], [], []
        c, rig, b = self._c, self.rig, self.block
        model = load_machine_model(rig.model) if self.real.isChecked() else None
        self.real.setEnabled(load_machine_model(rig.model) is not None)
        yc = (b.y0 + b.y1) / 2
        if model is not None:
            wy = 0.0  # wire and spring just in front of the real arms
            self._build_model(model, yc)
        else:
            wy = -10.0
            self._build_schematic(yc)

        # bed frame: spacer, foam block, kerf on both side faces and the full path, faint
        xl, xr = b.x_offset - b.width_x / 2, b.x_offset + b.width_x / 2
        z0, z1 = b.spacer, b.spacer + b.height_z
        if b.spacer > 0:
            self._mesh(_box(xl - 5, b.y0 - 5, 0, xr + 5, b.y1 + 5, b.spacer), _rgba("#9a7a55"), self._bed_items)
        self._mesh(_box(xl, b.y0, z0, xr, b.y1, z1), _rgba("#6fa8dc", 0.30), self._bed_items, translucent=True)
        self._line([[xl, b.y0, z0], [xr, b.y0, z0], [xr, b.y1, z0], [xl, b.y1, z0], [xl, b.y0, z0],
                    [xl, b.y0, z1], [xr, b.y0, z1], [xr, b.y1, z1], [xl, b.y1, z1],
                    [xl, b.y0, z1]], _rgba("#9cc3e6", 0.9), 1.2, self._bed_items)
        path = [self.toolpath.start] + [(m.y1, m.z1) for m in self.toolpath.moves]
        if len(path) > 1:
            for x in (xl - 0.3, xr + 0.3):
                self._line([[x, y, bed_height(b, z)] for y, z in path], _rgba(c.muted, 0.45), 1.0, self._bed_items)
            self._kerf_x = (xl - 0.5, xr + 0.5)
            for x in self._kerf_x:
                self._kerf.append(self._line([[x, y, bed_height(b, z)] for y, z in path], _rgba("#ff6a2a"),
                                             3.0, self._bed_items))
            self._kerf_t1 = [m.t1 for m in self.toolpath.moves]

        # gantry frame (Z = 0 at the wire): wire, spring and clips over either drawing
        pts = rig_points(rig)
        (wl, _), (wr, _) = pts["wire"]
        self._line([[wl - 12, wy, 0], [wr + 12, wy, 0]], _rgba("#ff6a2a"), 3.0, self._gantry_items)
        (sl, sz), (sr, _) = pts["spring"]
        coils = 24
        spring = [[sl + (sr - sl) * k / (2 * coils), wy, sz + (2.5 if k % 2 else -2.5)] for k in range(2 * coils + 1)]
        self._line(spring, _rgba("#c8ccd2"), 1.6, self._gantry_items)
        for x, col in ((wl - 12, "#d33"), (wr + 12, "#222")):
            self._mesh(_box(x - 14 if x < 0 else x, wy - 4, -4, x if x < 0 else x + 14, wy + 4, 4), _rgba(col),
                       self._gantry_items)

        if not self._framed:
            self._framed = True
            self.view.fit(22, -58, animate=False)
        self._check()

    def _build_schematic(self, yc: float) -> None:
        rig, b = self.rig, self.block
        metal, dark = _rgba("#2b2f36"), _rgba("#1b1d22")
        pla = _rgba("#3ec46d")
        # static frame: base rails, Z uprights, top bar (Ender-style 2040 extrusions)
        half = rig.frame_width / 2
        ylen = rig.bed_y + rig.y_travel
        for sx in (-1, 1):
            x0 = sx * half
            self._mesh(_box(min(x0, x0 - sx * 40), -ylen / 2, -60, max(x0, x0 - sx * 40), ylen / 2, -20), metal, self._static_items)
            self._mesh(_box(min(x0, x0 - sx * 20), 25, -60, max(x0, x0 - sx * 20), 65, rig.frame_height - 60), metal, self._static_items)
        self._mesh(_box(-half, 25, rig.frame_height - 80, half, 45, rig.frame_height - 60), metal, self._static_items)
        self._mesh(_box(-40, -ylen / 2, -60, 40, ylen / 2, -20), metal, self._static_items)  # Y rail
        self._mesh(_box(b.x_offset - rig.bed_x / 2, yc - rig.bed_y / 2, -6, b.x_offset + rig.bed_x / 2,
                        yc + rig.bed_y / 2, 0), dark, self._bed_items)
        # gantry: X beam, carriage, arms and clamps
        pts = rig_points(rig)
        piv = rig.wire_drop
        self._mesh(_box(-half + 20, 5, piv - 10, half - 20, 25, piv + 10), metal, self._gantry_items)
        cx0 = rig.carriage_offset_x - rig.carriage_width / 2
        noz = rig.nozzle_clearance
        self._carriage = self._mesh(_box(cx0, -rig.carriage_depth / 2, noz + 8, cx0 + rig.carriage_width,
                                         rig.carriage_depth / 2, noz + 70), _rgba("#3a3f48"), self._gantry_items)
        self._carriage_ok = _rgba("#3a3f48")
        self._mesh(_box(rig.carriage_offset_x - 3, -3, noz, rig.carriage_offset_x + 3, 3, noz + 8),
                   _rgba("#c9a24a"), self._gantry_items)
        for p, w, s in zip(pts["pivots"], pts["wire"], pts["spring"], strict=True):
            self._mesh(_beam(w, s, 14, -8, -2), pla, self._gantry_items)
            self._mesh(_box(p[0] - 9, -2, p[1] - 9, p[0] + 9, 25, p[1] + 9), pla, self._gantry_items)  # clamp

    def _build_model(self, model, yc: float) -> None:
        """The printer's CAD: frame static, bed centred under the block, gantry and real arms on the pivots."""
        rig = self.rig
        lift = np.array([0.0, 0.0, rig.wire_drop], dtype=np.float32)  # gantry meshes: pivot axis -> wire frame
        for name, group, shift in (("frame", self._static_items, np.zeros(3, np.float32)),
                                   ("bed", self._bed_items, np.array([0.0, yc, 0.0], np.float32)),
                                   ("gantry", self._gantry_items, lift)):
            for part in model.groups.get(name, []):
                # the printer is mostly black: lift it off the dark viewport background
                self._raw_mesh(part.vertices + shift, part.faces, _rgba(QColor(part.colour).lighter(170).name()), group)
        pla = _rgba(model.parts["arm"].colour)
        for side in (-1.0, 1.0):
            for mount in ("clamp", "tee"):
                self._raw_mesh(mount_mesh(model, mount, rig, side) + lift, model.parts[mount].faces, pla,
                               self._gantry_items)
            self._raw_mesh(arm_mesh(model, rig, side) + lift, model.parts["arm"].faces, pla, self._gantry_items)
        # the hotend turns red when it would hit the block: a translucent shell over the carriage
        cx0 = rig.carriage_offset_x - rig.carriage_width / 2
        noz = rig.nozzle_clearance
        self._carriage = self._mesh(_box(cx0, -rig.carriage_depth / 2, noz, cx0 + rig.carriage_width,
                                         rig.carriage_depth / 2, noz + 70), (0, 0, 0, 0), self._gantry_items,
                                    translucent=True)
        self._carriage_ok = (0.0, 0.0, 0.0, 0.0)

    def _raw_mesh(self, verts: np.ndarray, faces: np.ndarray, color, group: list, translucent: bool = False,
                  edges: bool = False):
        oid = self._id(group)
        self.view.mesh(oid, verts, faces, color, group=self._scene_group(group), edges=edges,
                       opacity=color[3] if translucent else 1.0, metalness=0.25, roughness=0.5)
        group.append(oid)
        return oid

    def _check(self) -> None:
        rig = self.rig
        self.rig_info.setText(
            f"Wire {rig.wire_drop:.0f} mm below the pivots · {rig.nozzle_clearance:.0f} mm under the nozzle · "
            f"span {rig.wire_span:.0f} mm · usable width at {self.block.height_z:.0f} mm: "
            f"{rig.usable_width(self.block.height_z):.0f} mm")
        if not self.toolpath.moves:
            self.status.setText("Open a G-code to simulate it.")
            return
        issues = check_cut(rig, self.block, self.toolpath) + self.toolpath.warnings
        ok, warn = self._c.success, self._c.warning
        head = (f"<b>{self.name}</b> · {len(self.toolpath.moves)} moves · {self.toolpath.total_s:.0f} s · "
                f"cut {self.toolpath.cut_length:.0f} mm<br>")
        if issues:
            self.status.setText(head + "".join(f"<span style='color:{warn}'>⚠ {i}</span><br>" for i in issues))
        else:
            self.status.setText(head + f"<span style='color:{ok}'>✓ Fits the machine; no collisions.</span>")

    def _set_time(self, t: float) -> None:
        self.t = max(0.0, min(t, self.toolpath.total_s))
        pose = machine_pose(self.rig, self.block, self.toolpath, self.t)
        self.view.offset("bed", (0, pose.bed_shift, 0))
        self.view.offset("gantry", (0, 0, pose.wire_height))
        if self._carriage is not None:
            self.view.color(self._carriage, _rgba(self._c.danger, 0.55) if pose.carriage_hits_block else self._carriage_ok)
        if self._kerf:
            # points already reached, plus the wire's current position on the move in progress
            n = 1 + bisect.bisect_right(self._kerf_t1, self.t)
            head = None
            if n - 1 < len(self.toolpath.moves) and self.toolpath.moves[n - 1].t0 < self.t:
                y, z = self.toolpath.moves[n - 1].point_at(self.t)
                head = (y, z)
            for k, x in zip(self._kerf, self._kerf_x, strict=True):
                self.view.progress(k, n, None if head is None else (x, head[0], bed_height(self.block, head[1])))
        total = self.toolpath.total_s
        self.clock.setText(f"{self.t:5.1f} / {total:.1f} s")
        if not self.slider.isSliderDown():
            self.slider.setValue(int(1000 * self.t / total) if total else 0)
        self.readout.setText(f"Y {pose.y:7.2f}   Z {pose.z:7.2f}   line {pose.line_no}")
        self._highlight(pose.line_no)

    def _highlight(self, line_no: int) -> None:
        if line_no <= 0:
            self.code.setExtraSelections([])
            return
        block = self.code.document().findBlockByNumber(line_no - 1)
        sel = QTextEdit.ExtraSelection()
        fmt = QTextCharFormat()
        bg = QColor(self._c.accent)
        bg.setAlpha(70)  # readable on light and dark panels
        fmt.setBackground(bg)
        fmt.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
        sel.format = fmt
        sel.cursor = QTextCursor(block)
        self.code.setExtraSelections([sel])
        self.code.setTextCursor(QTextCursor(block))
        self.code.centerCursor()


class MachineSimDialog(QDialog):
    """Non-modal window hosting the simulator."""

    def __init__(self, parent: QWidget | None = None, theme: str = "dark") -> None:
        super().__init__(parent)
        self.setWindowTitle("Hot-wire machine simulator")
        self.resize(1320, 820)
        self.sim = MachineSimulator(self, theme)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.sim)
