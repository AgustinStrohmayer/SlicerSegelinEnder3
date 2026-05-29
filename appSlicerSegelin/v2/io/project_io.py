"""Project save/load to ``.ssp`` (JSON).

Carries a ``schema_version`` from day one so future migrations are
straightforward. Reads are forward-tolerant: unknown fields are
ignored, missing ones fall back to defaults.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path as _Path

from ..core.errors import ProjectIOError
from ..core.geometry import Point, Segment, SegmentKind
from ..core.machine import MachineProfile
from ..core.manual_cuts import CutKind, ManualCut
from ..core.project import SCHEMA_VERSION, Project, ViewState


def save(path: str | _Path, project: Project) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "machine": asdict(project.machine),
        "view": asdict(project.view),
        "segments": [_seg_to_json(s) for s in project.segments],
        "manual_cuts": [_cut_to_json(c) for c in project.manual_cuts],
        "offset_y": project.offset_y,
        "offset_z": project.offset_z,
        "speed_mm_s": project.speed_mm_s,
        "reverse_cut": project.reverse_cut,
        "area_y_mm": project.area_y_mm,
        "area_z_mm": project.area_z_mm,
        "split_into_plates": project.split_into_plates,
        "use_manual_cuts": project.use_manual_cuts,
        "auto_close_manual": project.auto_close_manual,
        "batch_basename": project.batch_basename,
    }
    try:
        _Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        raise ProjectIOError(f"Cannot save project: {exc}") from exc


def load(path: str | _Path) -> Project:
    try:
        raw = _Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectIOError(f"Cannot open project: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProjectIOError(f"Project is not valid JSON: {exc}") from exc

    version = data.get("schema_version", SCHEMA_VERSION)
    if version > SCHEMA_VERSION:
        raise ProjectIOError(
            f"Project schema {version} is newer than this app supports ({SCHEMA_VERSION}). "
            "Update the app to open this file."
        )

    project = Project()
    if "machine" in data:
        project.machine = MachineProfile(**{**asdict(MachineProfile()), **data["machine"]})
    if "view" in data:
        project.view = ViewState(**{**asdict(ViewState()), **data["view"]})
    project.segments = [_seg_from_json(s) for s in data.get("segments", [])]
    project.manual_cuts = [_cut_from_json(c) for c in data.get("manual_cuts", [])]
    project.offset_y = float(data.get("offset_y", 0.0))
    project.offset_z = float(data.get("offset_z", 0.0))
    project.speed_mm_s = float(data.get("speed_mm_s", 10.0))
    project.reverse_cut = bool(data.get("reverse_cut", False))
    project.area_y_mm = float(data.get("area_y_mm", 220.0))
    project.area_z_mm = float(data.get("area_z_mm", 100.0))
    project.split_into_plates = bool(data.get("split_into_plates", False))
    project.use_manual_cuts = bool(data.get("use_manual_cuts", False))
    project.auto_close_manual = bool(data.get("auto_close_manual", True))
    project.batch_basename = str(data.get("batch_basename", "cut"))
    return project


def _seg_to_json(s: Segment) -> dict[str, object]:
    return {"a": [s.a.y, s.a.z], "b": [s.b.y, s.b.z], "kind": s.kind.value}


def _seg_from_json(data: dict[str, object]) -> Segment:
    a = data["a"]
    b = data["b"]
    return Segment(
        Point(float(a[0]), float(a[1])),  # type: ignore[index]
        Point(float(b[0]), float(b[1])),  # type: ignore[index]
        SegmentKind(data.get("kind", "cut")),
    )


def _cut_to_json(c: ManualCut) -> dict[str, object]:
    return {"a": c.a, "b": c.b, "c_base": c.c_base, "kind": c.kind.value, "meta": c.meta}


def _cut_from_json(data: dict[str, object]) -> ManualCut:
    return ManualCut(
        float(data["a"]),  # type: ignore[arg-type]
        float(data["b"]),  # type: ignore[arg-type]
        float(data["c_base"]),  # type: ignore[arg-type]
        CutKind(data.get("kind", "Y")),
        dict(data.get("meta", {})),  # type: ignore[arg-type]
    )
