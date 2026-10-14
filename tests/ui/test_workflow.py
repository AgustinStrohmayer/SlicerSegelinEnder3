"""Main window: block-first steps, one block and one machine for the 3D view, simulator and Cut Lab (headless)."""
from __future__ import annotations

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
pytest.importorskip("pyqtgraph.opengl")
ezdxf = pytest.importorskip("ezdxf")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def _plate(tmp_path, h: float):
    doc = ezdxf.new("R2010")
    doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, h), (0, h)], close=True)
    path = tmp_path / f"plate{h:g}.dxf"
    doc.saveas(path)
    return str(path)


def _shown(w, step: int) -> bool:
    return any(sec.isVisibleTo(w.sidebar) for sec in w.sidebar.step_sections[step])


@pytest.fixture()
def window(app, tmp_path):
    """A 70 mm tall plate imported straight away (step 1 skipped): the block is made around it."""
    from appSlicerSegelin.v2.ui.main_window import MainWindow

    w = MainWindow()
    w.controller.import_dxf(_plate(tmp_path, 70))
    w._flush_check()
    return w


def test_block_first(app, tmp_path):
    from appSlicerSegelin.v2.core.geometry import BBox
    from appSlicerSegelin.v2.ui.main_window import MainWindow

    w = MainWindow()
    sb, c = w.sidebar, w.controller
    assert sb.active_step == 1 and _shown(w, 1) and not _shown(w, 2)
    assert sb.unlocked() == [True, False, False, False, False]
    assert not sb.steps.chips[1].isEnabled()
    sb.show_step(2)  # locked: stays on step 1
    assert sb.active_step == 1
    assert sb.b_create.isVisibleTo(sb) and not sb.block_form.isVisibleTo(sb)
    assert not w._status_check.text()

    sb.b_create.click()
    assert c.project.block_created and not c.project.block_auto
    assert sb.block_form.isVisibleTo(sb) and not sb.b_create.isVisibleTo(sb)
    assert c.block_issues == [] and "fits the printer" in sb.block_status.text()
    assert sb.steps.states()[0] == "done" and sb.steps.chips[1].isEnabled()
    assert w._status_check.text() == "✓ Fits the machine"

    sb.sp_h.setValue(c.project.rig.nozzle_clearance + 10)  # taller than the gap under the carriage
    assert any("nozzle" in i for i in c.block_issues)
    assert sb.steps.states()[0] == "warn" and "⚠" in sb.block_status.text()
    assert not sb.next_buttons[1].isEnabled()
    assert "machine problem" in w._status_check.text()
    sb.sp_h.setValue(40.0)
    assert c.block_issues == [] and sb.next_buttons[1].isEnabled()

    sb.next_buttons[1].click()
    assert sb.active_step == 2 and _shown(w, 2) and not _shown(w, 1)
    assert not sb.steps.chips[2].isEnabled()  # no profile yet
    c.import_dxf(_plate(tmp_path, 20))
    w._flush_check()
    b, box = c.project.block, BBox.from_segments(c.project.machine_segments())
    assert box.min_y + box.width / 2 == pytest.approx((b.y0 + b.y1) / 2)  # dropped in the middle of the block
    assert box.min_z + box.height / 2 == pytest.approx((b.z0 + b.z1) / 2)
    assert not c.project.block_auto and b.height_z == 40.0  # the user's block is kept
    assert sb.steps.chips[2].isEnabled()
    sb.next_buttons[2].click()
    assert sb.active_step == 3 and _shown(w, 3)


def test_import_without_block(window):
    w = window
    c, sb = w.controller, w.sidebar
    assert c.project.block_created and c.project.block_auto  # made around the profile
    assert sb.active_step == 2
    assert any("collide" in i for i in c.cut_issues)
    assert "machine problem" in w._status_check.text()
    assert sb.steps.states()[2] == "warn"
    sb.show_step(3)
    assert "collide" in sb.check_status.text()
    assert not sb.sp_h.isEnabled()  # follows the G-code
    sb.chk_fit.setChecked(False)
    assert sb.sp_h.isEnabled()
    sb.sp_h.setValue(30.0)
    assert c.project.block.height_z == 30.0 and not c.project.block_auto


def test_screens_share_block_and_machine(window):
    w = window
    p = w.controller.project
    w._on_cut_lab()  # step 4: the Cut Lab replaces the 3D view in the main window
    lab = w._cut_lab
    assert w._canvas_stack.currentWidget() is lab and w.sidebar.active_step == 4
    assert lab.linked and lab.block == p.block
    assert lab.params.span.value() == pytest.approx(p.rig.wire_span, abs=0.1)
    lab.sim.b_h.setValue(72.0)  # edit the block in the Cut Lab
    assert p.block.height_z == 72.0

    w.sidebar.sp_spacer.setValue(15.0)  # and in the main window (step 1)
    assert lab.block.spacer == 15.0
    w.sidebar.show_step(1)
    assert w._canvas_stack.currentWidget() is not lab  # leaving step 4 brings the workspace back

    w._view3d_action.setChecked(True)
    v = w._viewer3d
    assert v.block == p.block and v.rig == p.rig and v.block_shown
    assert v.alert  # this block collides with the carriage: the foam is drawn red
    assert w.sidebar.steps.states()[3] == "done"  # Cut Lab visited
    w._view3d_action.setChecked(False)


def test_chips_show_one_step(window):
    w = window
    for step in (5, 1, 3):
        w.sidebar.steps.chips[step - 1].click()
        assert w.sidebar.active_step == step
        assert all(_shown(w, n) == (n == step) for n in range(1, 6))


def test_fit_gives_back_the_users_block_and_edits_undo(window):
    c, sb = window.controller, window.sidebar
    sb.show_step(3)
    sb.chk_fit.setChecked(False)
    mine = replace(c.project.block, length_y=180.0, height_z=45.0, y0=8.0)
    c.set_block(mine)
    sb.chk_fit.setChecked(True)  # fitted to the cut…
    assert c.project.block != mine
    sb.chk_fit.setChecked(False)  # …and back to what the user had
    assert c.project.block == mine
    sb.sp_w.plus.click()  # one undo step per edit, even when the button is clicked again and again
    sb.sp_w.plus.click()
    assert c.project.block.width_x == mine.width_x + 10
    c.undo()
    assert c.project.block == mine and sb.sp_w.value() == mine.width_x


def test_beginner_sees_only_the_essentials(window):
    sb = window.sidebar
    sb.show_step(2)
    assert not any(sec.isVisibleTo(sb) for sec in sb.advanced_sections)
    sb.chk_advanced.setChecked(True)
    assert all(sec.isVisibleTo(sb) for sec in sb.advanced_sections)
    sb.show_step(3)
    assert sb.fix_row.isVisibleTo(sb)  # the 70 mm plate hits the carriage: offer the way back
    sb.show_step(2)
    sb.cmb_entry.setCurrentIndex(sb.cmb_entry.findData("top"))
    assert window.controller.project.entry == "top"
