from __future__ import annotations

from appSlicerSegelin.v2.core.geometry import Point, Segment, SegmentKind
from appSlicerSegelin.v2.core.machine import MachineProfile
from appSlicerSegelin.v2.core.project import Project
from appSlicerSegelin.v2.io.project_io import load, save


def test_save_load_round_trips(tmp_path):
    p = Project()
    p.machine = MachineProfile(name="Bench", feed_cut_mm_min=150)
    p.segments = [
        Segment(Point(0, 0), Point(10, 0), SegmentKind.CUT),
        Segment(Point(10, 0), Point(10, 5), SegmentKind.ENTRY),
    ]
    p.manual_cuts = [Segment(Point(0, 0), Point(0, 5), SegmentKind.CUT)]
    p.plate_split = True

    path = tmp_path / "project.ssp"
    save(path, p)

    reloaded = load(path)
    assert reloaded.machine.name == "Bench"
    assert reloaded.machine.feed_cut_mm_min == 150
    assert len(reloaded.segments) == 2
    assert reloaded.segments[1].kind == SegmentKind.ENTRY
    assert len(reloaded.manual_cuts) == 1
    assert reloaded.plate_split is True


def test_load_rejects_newer_schema(tmp_path):
    import json

    path = tmp_path / "p.ssp"
    path.write_text(json.dumps({"schema_version": 999, "segments": []}), encoding="utf-8")
    from appSlicerSegelin.v2.core.errors import ProjectIOError
    import pytest

    with pytest.raises(ProjectIOError):
        load(path)
