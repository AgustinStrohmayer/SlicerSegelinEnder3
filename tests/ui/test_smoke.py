"""UI smoke tests — run headless via the offscreen Qt platform.

These don't assert pixels; they verify the window builds, a DXF round
trips through import → transform → export, and theme toggling works
without raising.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")
ezdxf = pytest.importorskip("ezdxf")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication

    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture
def demo_dxf(tmp_path):
    doc = ezdxf.new("R2010")
    doc.units = 4
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (100, 0), (100, 50), (0, 50)], close=True)
    msp.add_circle((50, 25), 8)
    path = tmp_path / "demo.dxf"
    doc.saveas(path)
    return str(path)


def test_window_builds(app):
    from appSlicerSegelin.v2.ui.main_window import MainWindow

    w = MainWindow()
    assert "SlicerSegelinEnder3" in w.windowTitle()
    assert len(list(w.registry.all())) >= 10


def test_import_transform_export(app, demo_dxf, tmp_path):
    from appSlicerSegelin.v2.ui.main_window import MainWindow

    w = MainWindow()
    w.controller.import_dxf(demo_dxf)
    assert w.controller.has_geometry
    n = len(w.controller.project.segments)

    w.controller.rotate(90)
    assert len(w.controller.project.segments) == n
    assert w.controller.undo()

    w.controller.mirror_vertical()
    w.controller.mirror_horizontal()

    gcode = tmp_path / "out.gcode"
    assert w.controller.export_standard_gcode(str(gcode))
    content = gcode.read_text()
    assert content.endswith("\n")
    assert ";FLAVOR:Marlin" in content


def test_manual_cuts_and_preview(app, demo_dxf):
    from appSlicerSegelin.v2.ui.main_window import MainWindow

    w = MainWindow()
    w.controller.import_dxf(demo_dxf)
    w.controller.set_use_manual_cuts(True)
    w.controller.add_manual_y(50.0)
    w.controller.generate_preview()
    assert len(w.controller.layers) >= 2


def test_theme_toggle(app):
    from appSlicerSegelin.v2.ui.main_window import MainWindow

    w = MainWindow(initial_theme="dark")
    w._toggle_theme()
    assert w.theme == "light"
    w._toggle_theme()
    assert w.theme == "dark"
