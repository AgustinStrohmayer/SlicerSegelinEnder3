"""Bridges the UI to the core domain.

Holds the active :class:`Project` and an undo/redo :class:`CommandStack`.
Every mutating operation goes through here so it can be undone and so
the canvas/sidebar refresh consistently via Qt signals.
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QObject, pyqtSignal

from ...core import transforms
from ...core.commands import CommandStack, FunctionCommand
from ...core.errors import SlicerError
from ...core.geometry import BBox, Point, Segment
from ...core.manual_cuts import make_two_point_cut, make_y_cut, make_z_cut
from ...core.plates import Layer
from ...core.project import Project
from ...core.trajectory import build_full_trajectory, total_duration
from ...services import gcode_service, slicer_service


class ProjectController(QObject):
    # Emitted whenever geometry/offset/parameters change → repaint canvas.
    changed = pyqtSignal()
    # Emitted when a transient message should be shown (title, body, severity).
    notify = pyqtSignal(str, str, str)
    # Emitted when the layer set changes (preview generated / cleared).
    layers_changed = pyqtSignal()
    # Emitted when info displays should refresh (dimensions, time, etc.).
    info_changed = pyqtSignal()

    def __init__(self, project: Project | None = None) -> None:
        super().__init__()
        self.project = project or Project()
        self.history = CommandStack()
        self.layers: list[Layer] = []
        self.focused_layer: int = -1  # -1 = full view
        self.pending_diagonal: Point | None = None
        # Bytes of the original DXF, kept around so .ssproj saves embed it.
        self._source_dxf_bytes: bytes | None = None

    # ── helpers ───────────────────────────────────────────────────────
    @property
    def has_geometry(self) -> bool:
        return bool(self.project.segments)

    def _push_geometry(self, label: str, new_segments: list[Segment]) -> None:
        prev = list(self.project.segments)
        nxt = list(new_segments)

        def do() -> None:
            self.project.segments = list(nxt)
            self.changed.emit()
            self.info_changed.emit()

        def undo() -> None:
            self.project.segments = list(prev)
            self.changed.emit()
            self.info_changed.emit()

        self.history.push(FunctionCommand(label, do, undo))

    def _invalidate_layers(self) -> None:
        if self.layers or self.focused_layer != -1:
            self.layers = []
            self.focused_layer = -1
            self.layers_changed.emit()

    # ── import ────────────────────────────────────────────────────────
    def import_dxf(self, path: str, use_units: bool = True, scale: float = 1.0) -> None:
        from pathlib import Path

        from ...io.dxf_reader import DxfReadOptions, read_dxf

        try:
            segments = read_dxf(path, DxfReadOptions(apply_units=use_units, scale=scale))
            # Cache the original bytes so they can be embedded in the
            # next .ssproj save (lets a project travel between machines).
            try:
                self._source_dxf_bytes = Path(path).read_bytes()
            except OSError:
                self._source_dxf_bytes = None
        except SlicerError as exc:
            self.notify.emit("DXF import failed", str(exc), "danger")
            return
        if not segments:
            self.notify.emit("Empty DXF", "No supported geometry found.", "warning")
            return

        prev = (
            list(self.project.segments),
            self.project.offset_y,
            self.project.offset_z,
            self.project.source_dxf_name,
        )
        new_name = Path(path).name

        def do() -> None:
            self.project.segments = list(segments)
            self.project.source_dxf_name = new_name
            self.project.center_on_bed()
            self._invalidate_layers()
            self.changed.emit()
            self.info_changed.emit()

        def undo() -> None:
            (
                self.project.segments,
                self.project.offset_y,
                self.project.offset_z,
                self.project.source_dxf_name,
            ) = list(prev[0]), prev[1], prev[2], prev[3]
            self.changed.emit()
            self.info_changed.emit()

        self.history.push(FunctionCommand("Import DXF", do, undo))
        self.notify.emit("DXF imported", f"{len(segments)} segments", "success")

    # ── transforms ────────────────────────────────────────────────────
    def rotate(self, deg: float) -> None:
        if not self.has_geometry:
            return
        self._invalidate_layers()
        try:
            rotated = transforms.rotate_around_center(self.project.segments, deg)
        except SlicerError as exc:
            self.notify.emit("Cannot rotate", str(exc), "warning")
            return
        self._push_geometry(f"Rotate {deg:+g}°", rotated)

    def rotate_fine(self, deg: float) -> None:
        self.rotate(deg)

    def mirror_vertical(self) -> None:
        if not self.has_geometry:
            return
        self._invalidate_layers()
        self._push_geometry("Mirror vertical", transforms.mirror_vertical(self.project.segments))

    def mirror_horizontal(self) -> None:
        if not self.has_geometry:
            return
        self._invalidate_layers()
        self._push_geometry("Mirror horizontal", transforms.mirror_horizontal(self.project.segments))

    def translate(self, axis: str, step: float) -> None:
        if not self.has_geometry:
            return
        prev = (self.project.offset_y, self.project.offset_z)
        dy = step if axis == "y" else 0.0
        dz = step if axis == "z" else 0.0
        nxt = (prev[0] + dy, prev[1] + dz)

        def do() -> None:
            self.project.offset_y, self.project.offset_z = nxt
            self.changed.emit()

        def undo() -> None:
            self.project.offset_y, self.project.offset_z = prev
            self.changed.emit()

        self.history.push(FunctionCommand(f"Move {axis.upper()} {step:+g}", do, undo))

    def align_origin(self) -> None:
        """Set offset so the cut's entry point lands at machine (0, 0)."""
        if not self.has_geometry:
            return
        traj = build_full_trajectory(self.project.segments, reverse=self.project.reverse_cut)
        if not traj:
            return
        entry = traj[0].a
        prev = (self.project.offset_y, self.project.offset_z)
        nxt = (-entry.y, -entry.z)

        def do() -> None:
            self.project.offset_y, self.project.offset_z = nxt
            self.changed.emit()

        def undo() -> None:
            self.project.offset_y, self.project.offset_z = prev
            self.changed.emit()

        self.history.push(FunctionCommand("Align origin to cut", do, undo))

    def toggle_reverse(self) -> None:
        if not self.has_geometry:
            return
        self.project.reverse_cut = not self.project.reverse_cut
        self._invalidate_layers()
        self.changed.emit()
        self.info_changed.emit()

    def auto_height(self) -> None:
        """Rotate to the angle that minimises the Z height (legacy behaviour)."""
        if not self.has_geometry:
            return
        best_angle = 0
        min_height = math.inf
        for ang in range(0, 180):
            rad = math.radians(ang)
            cos_a, sin_a = math.cos(rad), math.sin(rad)
            zmax, zmin = -math.inf, math.inf
            for s in self.project.segments:
                for p in (s.a, s.b):
                    nz = p.y * sin_a + p.z * cos_a
                    zmax = max(zmax, nz)
                    zmin = min(zmin, nz)
            height = zmax - zmin
            if height < min_height:
                min_height, best_angle = height, ang
        if best_angle:
            self.rotate(best_angle)
        self.notify.emit("Auto height", f"Rotated {best_angle}° (min height {min_height:.1f} mm)", "info")

    # ── parameters ────────────────────────────────────────────────────
    def set_speed(self, value: float) -> None:
        self.project.speed_mm_s = max(0.0, value)
        self.info_changed.emit()

    def set_area(self, area_y: float, area_z: float) -> None:
        self.project.area_y_mm = max(0.0, area_y)
        self.project.area_z_mm = max(0.0, area_z)
        self._invalidate_layers()
        self.changed.emit()

    def set_split_plates(self, enabled: bool) -> None:
        self.project.split_into_plates = enabled
        self._invalidate_layers()

    def set_use_manual_cuts(self, enabled: bool) -> None:
        self.project.use_manual_cuts = enabled
        self._invalidate_layers()
        self.changed.emit()

    def set_auto_close(self, enabled: bool) -> None:
        self.project.auto_close_manual = enabled

    # ── manual cuts ───────────────────────────────────────────────────
    def add_manual_y(self, y_base: float) -> None:
        self.project.manual_cuts.append(make_y_cut(y_base))
        self._invalidate_layers()
        self.changed.emit()

    def add_manual_z(self, z_base: float) -> None:
        self.project.manual_cuts.append(make_z_cut(z_base))
        self._invalidate_layers()
        self.changed.emit()

    def add_manual_diagonal(self, p1: Point, p2: Point) -> bool:
        cut = make_two_point_cut(p1, p2)
        if cut is None:
            self.notify.emit("Invalid cut", "The two points are too close.", "warning")
            return False
        self.project.manual_cuts.append(cut)
        self._invalidate_layers()
        self.changed.emit()
        return True

    def clear_manual_cuts(self) -> None:
        self.project.manual_cuts = []
        self.pending_diagonal = None
        self._invalidate_layers()
        self.changed.emit()

    def delete_manual_cut(self, index: int) -> None:
        if 0 <= index < len(self.project.manual_cuts):
            self.project.manual_cuts.pop(index)
            self._invalidate_layers()
            self.changed.emit()

    # ── layers / preview ──────────────────────────────────────────────
    def generate_preview(self) -> None:
        if not self.has_geometry:
            return
        if not self.project.split_into_plates and not self.project.use_manual_cuts:
            self.notify.emit(
                "Section mode disabled",
                "Enable plate splitting or manual cuts first.",
                "info",
            )
            return
        if self.project.use_manual_cuts and not self.project.manual_cuts:
            self.notify.emit("No manual cuts", "Add at least one manual cut.", "info")
            return
        layers = slicer_service.build_layers(self.project)
        if not layers:
            self.notify.emit("No preview", "Could not generate any part.", "warning")
            return
        self.layers = layers
        self.focused_layer = 0
        self.layers_changed.emit()
        self.changed.emit()
        self.notify.emit("Preview ready", f"{len(layers)} parts", "success")

    def move_layer(self, delta: int) -> None:
        if not self.layers:
            return
        self.focused_layer = max(0, min(len(self.layers) - 1, self.focused_layer + delta))
        self.changed.emit()

    def show_full_view(self) -> None:
        self.focused_layer = -1
        self.changed.emit()

    # ── simulation info ───────────────────────────────────────────────
    def active_trajectory(self) -> list[Segment]:
        if 0 <= self.focused_layer < len(self.layers):
            return self.layers[self.focused_layer].trajectory
        return slicer_service.standard_trajectory(self.project)

    def estimated_time_s(self) -> float:
        return total_duration(self.active_trajectory(), self.project.speed_mm_s)

    def dimensions(self) -> tuple[float, float] | None:
        bbox = BBox.from_segments(self.project.segments)
        if bbox is None:
            return None
        return (bbox.width, bbox.height)

    def cut_height(self) -> tuple[float, float] | None:
        traj = self.active_trajectory()
        cut = [s for s in traj if s.kind.name == "CUT"]
        if not cut:
            return None
        zs = [p.z for s in cut for p in (s.a, s.b)]
        return (min(zs), max(zs))

    # ── undo/redo ─────────────────────────────────────────────────────
    def undo(self) -> bool:
        if self.history.undo() is None:
            return False
        self._invalidate_layers()
        return True

    def redo(self) -> bool:
        if self.history.redo() is None:
            return False
        self._invalidate_layers()
        return True

    # ── project archive (.ssproj) ────────────────────────────────────
    def save_project_archive(self, path: str, scene=None) -> bool:  # type: ignore[no-untyped-def]
        """Bundle project + source DXF + optional thumbnail into one ZIP."""
        from ...io import project_archive

        thumb = project_archive.render_thumbnail_png(scene) if scene is not None else None
        try:
            out = project_archive.save_archive(
                path,
                self.project,
                source_dxf_bytes=self._source_dxf_bytes,
                thumbnail_png=thumb,
                title=self.project.source_dxf_name or "Untitled",
            )
        except SlicerError as exc:
            self.notify.emit("Save failed", str(exc), "danger")
            return False
        self.notify.emit("Project saved", str(out), "success")
        return True

    def open_project_archive(self, path: str) -> bool:
        from ...io import project_archive

        try:
            content = project_archive.load_archive(path)
        except SlicerError as exc:
            self.notify.emit("Open failed", str(exc), "danger")
            return False
        self.project = content.project
        self._source_dxf_bytes = content.source_dxf_bytes
        self.history.clear()
        self._invalidate_layers()
        self.changed.emit()
        self.info_changed.emit()
        title = content.manifest.get("title") or self.project.source_dxf_name or "Untitled"
        self.notify.emit("Project loaded", title, "success")
        return True

    # ── export ────────────────────────────────────────────────────────
    def export_standard_gcode(self, path: str) -> bool:
        if not self.has_geometry:
            self.notify.emit("Nothing to export", "Import a DXF first.", "warning")
            return False
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(gcode_service.export_standard(self.project))
        except OSError as exc:
            self.notify.emit("Export failed", str(exc), "danger")
            return False
        self.notify.emit("G-code exported", path, "success")
        return True

    def export_layers_gcode(self, folder: str) -> int:
        import os

        files = gcode_service.export_layers(self.project)
        if not files:
            self.notify.emit("No layers", "Generate a plate/cut preview first.", "warning")
            return 0
        try:
            for f in files:
                with open(os.path.join(folder, f.filename), "w", encoding="utf-8") as fh:
                    fh.write(f.content)
        except OSError as exc:
            self.notify.emit("Batch export failed", str(exc), "danger")
            return 0
        self.notify.emit("Batch exported", f"{len(files)} files → {folder}", "success")
        return len(files)

    def export_dxf(self, path: str) -> bool:
        from ...io.dxf_writer import write_dxf

        segments = self.project.machine_segments()
        if not segments:
            self.notify.emit("Nothing to export", "Import a DXF first.", "warning")
            return False
        try:
            written = write_dxf(path, segments, self.project.machine)
        except SlicerError as exc:
            self.notify.emit("DXF export failed", str(exc), "danger")
            return False
        self.notify.emit("DXF exported", f"{written} segments → {path}", "success")
        return True
