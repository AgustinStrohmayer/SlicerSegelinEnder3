from __future__ import annotations

import pytest

from appSlicerSegelin.v2.core.geometry import Point, Segment, SegmentKind
from appSlicerSegelin.v2.core.machine import MachineProfile
from appSlicerSegelin.v2.core.manual_cuts import make_y_cut
from appSlicerSegelin.v2.core.project import Project
from appSlicerSegelin.v2.io.project_io import load, save


def test_save_load_round_trips(tmp_path):
    p = Project()
    p.machine = MachineProfile(name="Bench", feed_cut_mm_min=150)
    p.segments = [
        Segment(Point(0, 0), Point(10, 0), SegmentKind.CUT),
        Segment(Point(10, 0), Point(10, 5), SegmentKind.ENTRY),
    ]
    p.manual_cuts = [make_y_cut(25.0)]
    p.split_into_plates = True
    p.use_manual_cuts = True
    p.offset_y = 12.5
    p.offset_z = -3.0
    p.speed_mm_s = 15.0
    p.reverse_cut = True
    p.batch_basename = "wing"

    path = tmp_path / "project.ssp"
    save(path, p)

    reloaded = load(path)
    assert reloaded.machine.name == "Bench"
    assert reloaded.machine.feed_cut_mm_min == 150
    assert len(reloaded.segments) == 2
    assert reloaded.segments[1].kind == SegmentKind.ENTRY
    assert len(reloaded.manual_cuts) == 1
    assert reloaded.manual_cuts[0].meta["y"] == 25.0
    assert reloaded.split_into_plates is True
    assert reloaded.use_manual_cuts is True
    assert reloaded.offset_y == 12.5
    assert reloaded.offset_z == -3.0
    assert reloaded.speed_mm_s == 15.0
    assert reloaded.reverse_cut is True
    assert reloaded.batch_basename == "wing"


def test_load_rejects_newer_schema(tmp_path):
    import json

    from appSlicerSegelin.v2.core.errors import ProjectIOError

    path = tmp_path / "p.ssp"
    path.write_text(json.dumps({"schema_version": 999, "segments": []}), encoding="utf-8")
    with pytest.raises(ProjectIOError):
        load(path)
