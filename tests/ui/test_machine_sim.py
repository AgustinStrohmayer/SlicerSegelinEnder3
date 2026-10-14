"""Machine simulator window: builds, loads G-code, scrubs and plays (headless)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
pytest.importorskip("pyqtgraph.opengl")

GCODE = "G92 Y0 Z0\nG1 F600 Y10 Z0\nG1 Y60 Z20\nG1 Y110 Z0\nG1 Y10 Z0\nG1 Y0 Z0\n"


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def test_simulator_loads_and_scrubs(app):
    from appSlicerSegelin.v2.ui.widgets.canvas.machine_sim import MachineSimulator

    sim = MachineSimulator()
    sim.load_text(GCODE, "demo.gcode")
    assert sim.toolpath.total_s > 0
    assert sim.block.y0 == pytest.approx(5.0)
    sim._set_time(sim.toolpath.total_s / 2)
    assert "line" in sim.readout.text()
    assert "Fits the machine" in sim.status.text()
    assert sim.real.isEnabled() and len(sim._static_items) > 4  # the Ender's CAD is drawn
    sim.sp_spacer.setValue(0)
    assert "spacer of at least" in sim.status.text()
    sim.sp_spacer.setValue(10)
    sim.preset.setCurrentText("Ender-3")
    sim.sp_h.setValue(60)  # a block taller than the nozzle clearance
    assert "collide" in sim.status.text()
    sim.sp_low.setValue(110)
    assert sim.rig.arm_lower_length == 110
    sim.preset.setCurrentText("CR-10")
    assert not sim.real.isEnabled()  # no CAD for it: schematic
    sim.play_btn.setChecked(True)
    sim._tick()
    sim.play_btn.setChecked(False)


def test_main_window_simulates_project(app, tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    from appSlicerSegelin.v2.ui.main_window import MainWindow

    doc = ezdxf.new("R2010")
    doc.modelspace().add_lwpolyline([(0, 0), (100, 0), (100, 20), (0, 20)], close=True)
    path = tmp_path / "plate.dxf"
    doc.saveas(path)
    w = MainWindow()
    w.controller.import_dxf(str(path))
    w._on_simulate_project()
    assert w._sim_dialog.sim.toolpath.moves
