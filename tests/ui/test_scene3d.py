"""Scene3D: renderer fallback keeps the scene, and the last resort keeps the app usable (headless)."""
from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication(["test"])


def _fill(sc):
    sc.box("foam", 0, 0, 0, 100, 50, 20, "#7FB2E5", opacity=0.3)
    sc.lines("path", np.array([[0, 0, 0], [0, 50, 20], [np.nan] * 3, [0, 10, 10], [0, 20, 5]]), "#ff5a1f")
    sc.progress("path", 1)
    sc.offset("wire", (0, 5, 5))


def test_no_renderer_still_works(app):
    from appSlicerSegelin.v2.ui.widgets.view3d import Scene3D

    sc = Scene3D(prefer="none")
    _fill(sc)
    assert sc.backend_name == "none"
    lo, hi = sc.bounds()
    assert np.allclose(lo, 0) and np.allclose(hi, [100, 50, 20])
    got = []
    sc.snapshot("unused.png", got.append)
    assert got == [False]
    sc.remove("path")
    assert not sc.has("path") and sc.has("foam")


def test_three_without_scheme_falls_back(app):
    from appSlicerSegelin.v2.ui.widgets.view3d import Scene3D

    sc = Scene3D(prefer="three")  # scheme not registered before QApplication -> next renderer
    _fill(sc)
    assert sc.backend_name in ("opengl", "none")
    assert sc.fallback_reason.startswith(("three", "opengl"))
    assert sc.has("foam") and sc.has("path")


def test_main_view_draws_the_real_machine(app):
    from appSlicerSegelin.v2.ui.widgets.canvas.viewer3d import Viewer3D, spring_points

    v = Viewer3D()
    assert v.scene.has("arm_l") and v.scene.has("arm_r") and v.scene.has("clamp_l") and v.scene.has("spring")
    v.set_wire(30.0, 12.0)
    assert v.scene._offsets["bed"] == (0.0, -30.0, 0.0)  # the bed carries the foam along Y
    assert v.scene._offsets["gantry"][2] > 12.0          # the gantry carries the wire along Z (above the spacer)
    sp = spring_points(v.rig)
    assert np.isfinite(sp).all() and len(sp) > 200


def test_block_edits_leave_the_printer_alone(app):
    """Editing the block or measuring the arms must not resend the printer's meshes (the heavy part)."""
    from dataclasses import replace

    from appSlicerSegelin.v2.core.geometry import Point, Segment, SegmentKind
    from appSlicerSegelin.v2.ui.widgets.canvas.viewer3d import Viewer3D

    v = Viewer3D()
    sent: list[str] = []
    real = v.scene.backend.mesh
    v.scene.backend.mesh = lambda oid, **kw: (sent.append(oid), real(oid, **kw))
    v.set_setup(v.rig, replace(v.block, width_x=120.0, height_z=40.0))
    assert set(sent) <= {"spacer", "foam"}
    sent.clear()
    v.set_setup(replace(v.rig, pivot_spacing=176.0), v.block)
    assert sent and all(not o.startswith(("frame", "bed", "gantry")) for o in sent)  # only the segelín
    v.set_wire(10.0, 5.0)
    assert v.scene._offsets["gantry_cad"][2] == pytest.approx(v.scene._offsets["gantry"][2] + v.rig.wire_drop)

    path = [Segment(Point(0, 0), Point(0, 30), SegmentKind.ENTRY), Segment(Point(0, 30), Point(40, 30), SegmentKind.CUT)]
    v.set_cut(path, 0.5)  # the whole path (entry too) is drawn and half of its length revealed
    assert v.scene.has("path") and v.scene._state["cut"]["progress"][0] == 1
