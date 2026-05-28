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
from ..core.project import Project, SCHEMA_VERSION, ViewState


def save(path: str | _Path, project: Project) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "machine": asdict(project.machine),
        "view": asdict(project.view),
        "segments": [_seg_to_json(s) for s in project.segments],
        "manual_cuts": [_seg_to_json(s) for s in project.manual_cuts],
        "plate_split": project.plate_split,
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
            "Update the app or open the file in a newer version."
        )

    project = Project()
    if "machine" in data:
        project.machine = MachineProfile(**{**asdict(MachineProfile()), **data["machine"]})
    if "view" in data:
        project.view = ViewState(**{**asdict(ViewState()), **data["view"]})
    project.segments = [_seg_from_json(s) for s in data.get("segments", [])]
    project.manual_cuts = [_seg_from_json(s) for s in data.get("manual_cuts", [])]
    project.plate_split = bool(data.get("plate_split", False))
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
