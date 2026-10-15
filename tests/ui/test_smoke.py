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


def test_per_part_settings_and_exclude(app, demo_dxf, tmp_path):
    from appSlicerSegelin.v2.ui.main_window import MainWindow

    w = MainWindow()
    c = w.controller
    c.import_dxf(demo_dxf)
    c.set_use_manual_cuts(True)
    c.add_manual_y(50.0)
    c.generate_preview()
    n = len(c.layers)
    assert n >= 2
    # One settings record per part.
    assert len(c.part_settings) == n

    # Per-part overrides take effect.
    base = c.part_duration_s(0)
    c.set_part_speed(0, c.part_speed(0) * 2)
    assert c.part_duration_s(0) < base + 1e-6
    c.set_part_color(0, "#34D399")
    assert c.part_settings[0].color == "#34D399"
    c.set_part_reverse(0, True)  # rebuilds the trajectory without raising

    # Excluding a part drops it from the batch export.
    c.set_part_enabled(0, False)
    exported = c.export_layers_gcode(str(tmp_path))
    assert exported == n - 1
    assert len(list(tmp_path.glob("*.gcode"))) == n - 1


def test_canvas_overlay_is_mouse_transparent(app):
    """The canvas overlay must not eat mouse events meant for the view."""
    from PyQt6.QtCore import Qt

    from appSlicerSegelin.v2.ui.main_window import MainWindow

    w = MainWindow()
    assert w.canvas.overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_view_modes(app):
    from appSlicerSegelin.v2.ui.main_window import MainWindow

    w = MainWindow()
    for mode in ("grid", "split", "single"):
        w._set_view_mode(mode)
        assert w.view_mode == mode


def test_drag_part_and_cut(app, demo_dxf):
    from appSlicerSegelin.v2.ui.main_window import MainWindow

    w = MainWindow()
    c = w.controller
    c.import_dxf(demo_dxf)

    # Drag the part: offsets move, and undo restores them.
    oy, oz = c.project.offset_y, c.project.offset_z
    c.begin_part_move()
    c.move_part_to(oy + 10.0, oz + 5.0)
    c.end_part_move()
    assert abs(c.project.offset_y - (oy + 10.0)) < 1e-6
    assert abs(c.project.offset_z - (oz + 5.0)) < 1e-6
    assert c.undo()
    assert abs(c.project.offset_y - oy) < 1e-6 and abs(c.project.offset_z - oz) < 1e-6

    # Drag a manual Y cut: its value moves, and undo restores it.
    c.set_use_manual_cuts(True)
    c.add_manual_y(40.0)
    y0 = c.project.manual_cuts[0].meta["y"]
    c.begin_cut_move(0)
    c.move_cut(0, 7.0, 0.0)
    c.end_cut_move(0)
    assert abs(c.project.manual_cuts[0].meta["y"] - (y0 + 7.0)) < 1e-6
    assert c.undo()
    assert abs(c.project.manual_cuts[0].meta["y"] - y0) < 1e-6
