"""G-code export in the three legacy modes.

* standard  — one file for the whole part
* by plates — one file per Y×Z plate (geometry already localised)
* manual    — one file per manual-cut part

Feed rate comes from the project's cut speed (mm/s → mm/min), matching
the legacy ``v_mov_mmin = int(vel * 60)``.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from ..core.project import Project
from ..io.gcode_writer import emit_gcode
from . import slicer_service


@dataclass(slots=True)
class GcodeFile:
    filename: str
    content: str


def _machine_with_feed(project: Project):
    feed = max(1.0, project.speed_mm_s * 60.0)
    return replace(project.machine, feed_cut_mm_min=feed, feed_travel_mm_min=feed)


def export_standard(project: Project) -> str:
    machine = _machine_with_feed(project)
    plan = slicer_service.cut_plan(slicer_service.standard_trajectory(project), machine)
    return emit_gcode(plan)


def export_single(project: Project, trajectory, speed_mm_s: float, notes: tuple[str, ...] = ()) -> str:  # type: ignore[no-untyped-def]
    """G-code for one pre-built trajectory at a specific feed (mm/s)."""
    from dataclasses import replace as _replace

    feed = max(1.0, speed_mm_s * 60.0)
    machine = _replace(project.machine, feed_cut_mm_min=feed, feed_travel_mm_min=feed)
    plan = slicer_service.cut_plan(list(trajectory), machine, notes=notes)
    return emit_gcode(plan)


def export_layers(project: Project) -> list[GcodeFile]:
    """One G-code file per layer/part. Returns ``[]`` if no layers."""
    layers = slicer_service.build_layers(project)
    if not layers:
        return []
    machine = _machine_with_feed(project)
    base = project.batch_basename or "cut"
    total = len(layers)
    files: list[GcodeFile] = []
    for i, layer in enumerate(layers, start=1):
        notes = (f"Part {i} of {total} — {layer.label}",)
        plan = slicer_service.cut_plan(layer.trajectory, machine, notes=notes)
        kind = "manual_part" if layer.part_index else "plate"
        files.append(GcodeFile(f"{base}_{kind}{i:02d}_of_{total:02d}.gcode", emit_gcode(plan)))
    return files
