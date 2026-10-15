"""The project's machine and foam block: saved with it, refitted to the cut, checked on the machine."""
from __future__ import annotations

import os
from dataclasses import replace

import pytest

from appSlicerSegelin.v2.core.gcode_reader import parse_gcode
from appSlicerSegelin.v2.core.hotwire_rig import PRESETS, FoamBlock, check_block, check_cut, refit_block
from appSlicerSegelin.v2.core.project import DEFAULT_BLOCK, Project
from appSlicerSegelin.v2.io.project_io import deserialize_from_json, serialize_to_json

GCODE = "G92 Y0 Z0\nG1 F600 Y10 Z0\nG1 Y60 Z20\nG1 Y110 Z0\nG1 Y10 Z0\nG1 Y0 Z0\n"


def test_rig_and_block_round_trip():
    p = Project()
    assert p.rig == PRESETS["Ender-3 (long arms)"] and not p.block_auto and not p.block_created
    p.rig = replace(PRESETS["Ender-3"], arm_angle_deg=65.0)
    p.block = FoamBlock(length_y=120, height_z=40, width_x=90, y0=3, z0=-2, x_offset=5, spacer=12)
    p.block_created = True
    q = deserialize_from_json(serialize_to_json(p))
    assert q.rig == p.rig and q.block == p.block and not q.block_auto and q.block_created


def test_old_projects_get_the_default_setup():
    q = deserialize_from_json('{"schema_version": 2, "segments": []}')
    assert q.rig == PRESETS["Ender-3 (long arms)"] and q.block == DEFAULT_BLOCK
    assert not q.block_created and not q.block_auto  # a new user starts at step 1


def test_default_block_fits_the_default_machine():
    rig = PRESETS["Ender-3 (long arms)"]
    assert check_block(rig, DEFAULT_BLOCK) == []
    assert any("nozzle" in i for i in check_block(rig, replace(DEFAULT_BLOCK, height_z=rig.nozzle_clearance + 5)))
    assert any("arm tips" in i for i in check_block(rig, replace(DEFAULT_BLOCK, spacer=0.0)))
    assert any("wire" in i for i in check_block(rig, replace(DEFAULT_BLOCK, width_x=rig.wire_span + 10)))
    assert any("bed" in i for i in check_block(rig, replace(DEFAULT_BLOCK, length_y=rig.bed_y + 10)))


def test_refit_keeps_width_offset_and_spacer():
    b = FoamBlock(width_x=90, x_offset=5, spacer=12)
    fit = refit_block(b, parse_gcode(GCODE))
    assert (fit.width_x, fit.x_offset, fit.spacer) == (90, 5, 12)
    assert fit.y0 == pytest.approx(5.0) and fit.height_z == pytest.approx(25.0)
    assert refit_block(b, parse_gcode("")) == b


EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "..", "dxf-examples", "MSHD_100mm.dxf")


@pytest.mark.skipif(not os.path.exists(EXAMPLE), reason="example DXF not in this checkout")
def test_example_block_hits_the_carriage():
    pytest.importorskip("PyQt6")
    pytest.importorskip("ezdxf")
    from appSlicerSegelin.v2.ui.controllers.project_controller import ProjectController

    c = ProjectController()
    seen = []
    c.setup_changed.connect(lambda: seen.append(len(c.cut_issues)))
    c.import_dxf(EXAMPLE)
    c.update_cut_check()
    assert c.project.block.height_z == pytest.approx(65.2, abs=0.1)
    assert any("collide" in i for i in c.cut_issues) and seen
    # width and spacer edits keep the block following the G-code; a height edit stops it
    c.set_block(replace(c.project.block, width_x=60.0, x_offset=-60.0))
    assert c.project.block_auto and not any("collide" in i for i in c.cut_issues)  # beside the carriage
    c.set_block(replace(c.project.block, height_z=30.0))
    assert not c.project.block_auto and c.project.block.height_z == 30.0
    c.set_block_auto(True)
    assert c.project.block.height_z == pytest.approx(65.2, abs=0.1)
    c.set_rig(PRESETS["Ender-3"])
    assert c.project.rig.name == "Ender-3"


def _plate_project(entry: str) -> Project:
    from appSlicerSegelin.v2.core.geometry import Point, Segment

    pts = [(0, 0), (60, 0), (60, 20), (0, 20)]
    p = Project()
    p.segments = [Segment(Point(*pts[i]), Point(*pts[(i + 1) % 4])) for i in range(4)]
    p.block_created, p.entry = True, entry
    p.center_on_block()
    return p


@pytest.mark.parametrize("entry", ["side", "top"])
def test_wire_never_starts_under_or_inside_the_block(entry):
    from appSlicerSegelin.v2.services import gcode_service

    p = _plate_project(entry)
    p.origin = "bottom"
    b = p.block
    tp = parse_gcode(gcode_service.export_standard(p))
    first, second, last = tp.moves[0], tp.moves[1], [m for m in tp.moves if (m.y0, m.z0) != (m.y1, m.z1)][-1]
    assert (first.y0, first.z0) == (0, 0) and first.y1 == 0 < b.y0  # straight up, in front of the block
    assert (last.y1, last.z1) == (0, 0) and last.y0 == 0  # and back down there
    if entry == "side":
        assert second.z0 == second.z1 == first.z1 and second.y1 > b.y0  # then straight in
    else:
        assert first.z1 > b.z1 and second.z0 == second.z1 == first.z1  # over the top, then down
        assert tp.moves[2].y0 == tp.moves[2].y1 and tp.moves[2].z1 < b.z1
    assert check_cut(p.rig, b, tp) == []
    fit = refit_block(b, tp)
    assert 0 < fit.y0 and fit.z1 < (first.z1 if entry == "top" else 1e9)  # the fit keeps the wire's way in clear


@pytest.mark.parametrize("entry", ["side", "top"])
def test_wire_starts_touching_the_block_top_edge(entry):
    from appSlicerSegelin.v2.services import gcode_service

    p = _plate_project(entry)
    assert p.origin == "top"
    b = p.block
    text = gcode_service.export_standard(p)
    assert text.count("G92 ") == 1 and "front-top edge" in text
    assert "Smooth return to origin" not in text
    tp = parse_gcode(text)
    assert tp.start == (pytest.approx(b.y0), pytest.approx(b.z1))  # the wire touches the front-top edge
    first = tp.moves[0]
    assert first.z1 == pytest.approx(b.z1) and first.y1 == pytest.approx(b.y0 - 5)  # steps 5 mm forward first
    last = tp.moves[-1]
    assert (last.y1, last.z1) == (pytest.approx(b.y0 - 5), pytest.approx(b.z1))  # ends clear, level with the top
    assert min(m.z1 for m in tp.moves if m.y1 < b.y0) >= min(m.z1 for m in tp.moves) - 1e-9
    assert check_cut(p.rig, b, tp) == []
    p.block_auto = True  # a block that follows the G-code can't be the reference
    assert parse_gcode(gcode_service.export_standard(p)).start == (0, 0)


def test_block_behind_the_wire_is_flagged():
    assert any("Front face" in i for i in check_block(PRESETS["Ender-3"], replace(DEFAULT_BLOCK, y0=-5.0)))


def test_profile_goes_to_the_blocks_front_top_corner():
    from appSlicerSegelin.v2.core.geometry import BBox, Point, Segment
    from appSlicerSegelin.v2.core.hotwire_rig import FoamBlock
    from appSlicerSegelin.v2.core.project import Project

    p = Project()
    p.segments = [Segment(Point(0, 0), Point(100, 0)), Segment(Point(100, 0), Point(100, 20)),
                  Segment(Point(100, 20), Point(0, 0))]
    p.block = FoamBlock(length_y=200.0, height_z=50.0, y0=5.0)
    p.place_in_block()
    bb = BBox.from_segments(p.machine_segments())
    assert bb.min_y == pytest.approx(10.0) and bb.min_z + bb.height == pytest.approx(45.0)
