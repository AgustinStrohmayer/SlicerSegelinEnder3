"""Cut Lab window: live model, a small cut simulation and the calibration fit (headless)."""
from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
pytest.importorskip("pyqtgraph.opengl")

SQUARE = ("G92 Y0 Z0\nG1 F300 Y5 Z5\nG1 Y25 Z5\nG1 Y25 Z25\nG1 Y5 Z25\nG1 Y5 Z5\n"
          "G1 Y0 Z5\nG1 Y0 Z0\n")


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


def _wait(app, cond, timeout=60.0):  # type: ignore[no-untyped-def]
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        app.processEvents()
        time.sleep(0.02)


def test_cut_lab_live_model_simulation_and_fit(app):
    from appSlicerSegelin.v2.core.calibration import Measurement
    from appSlicerSegelin.v2.ui.widgets.cutlab.cut_lab import CutLab

    lab = CutLab(theme="dark", load_saved=False)
    lab.resize(1500, 900)
    lab.show()
    _wait(app, lambda: getattr(lab, "_last_profile", None) is not None)
    assert lab.k_vc._val.text() not in ("…", "—")  # contact speed computed in the background

    lab.load_text(SQUARE, "square.gcode")
    lab.sim.slices.setValue(3)
    lab.run_simulation()
    _wait(app, lambda: lab._sim_job is None, timeout=120)
    res = lab.sim.res
    assert res is not None and len(res.slices) == 3
    assert all(sl.released for sl in res.slices)
    assert res.slices[1].stats["dev_mean"] < 0  # the part comes out smaller than drawn
    lab.sim.set_time(res.samples.total_s)
    assert "kerf" in lab.sim.readout.text()

    s = lab.params.setup()
    ms = [Measurement(v, d, "current", 10 - k, 10.0)
          for d, ks in ((1.0, (1.1, 0.7, 0.5)), (1.4, (1.6, 1.0, 0.7)))
          for v, k in zip((1.0, 2.0, 4.0), ks, strict=True)]
    assert s.mode == "current"
    lab.calib.set_measurements(ms)
    lab.calib._do_fit()
    assert "η =" in lab.calib.fit_out.text()
    lab.calib._apply_fit()
    assert lab.params.setup().calib.eta == pytest.approx(lab.calib._fit.eta, rel=1e-2)
    lab.close()


def test_cut_lab_2d_solve_runs_shows_and_cancels(app):
    from appSlicerSegelin.v2.ui.widgets.cutlab.cut_lab import CutLab

    lab = CutLab(theme="light", load_saved=False)
    lab.resize(1500, 900)
    lab.show()
    ex = lab.explore
    ex.quality.setCurrentIndex(0)  # coarse: a couple of seconds
    ex.run_btn.click()
    assert lab._hifi_job is not None and not ex.run_btn.isEnabled()
    _wait(app, lambda: lab._hifi_job is None, timeout=120)
    r = ex.hifi_result
    assert r is not None and r.kerf_mm > 0
    assert ex.stack.currentIndex() == 1 and "kerf" in ex.hifi_note.text()
    lab.params.set_probe_speed(lab.params.probe_speed() * 1.5)
    _wait(app, lambda: ex.hifi_note.text().startswith("Parameters changed"), timeout=10)
    ex.view_btns[0].click()
    assert ex.stack.currentIndex() == 0

    ex.quality.setCurrentIndex(3)  # ultra, then cancel at once
    ex.run_btn.click()
    ex.cancel_btn.click()
    _wait(app, lambda: lab._hifi_job is None, timeout=60)
    assert "cancelled" in ex.progress.format()
    assert ex.run_btn.isEnabled()
    lab.close()


def test_cut_lab_curves_tab(app):
    from appSlicerSegelin.v2.core.calibration import Measurement
    from appSlicerSegelin.v2.ui.widgets.cutlab.cut_lab import CutLab

    lab = CutLab(theme="dark", load_saved=False)
    lab.resize(1500, 900)
    lab.show()
    cv = lab.curves
    lab.tabs.setCurrentWidget(cv)
    app.processEvents()
    assert "No measurements yet" in cv.emp_text.text()
    ms = [Measurement(v, d, "current", 10 - k, 10.0)
          for d, ks in ((1.0, (1.1, 0.7, 0.5)), (1.4, (1.6, 1.0, 0.7)))
          for v, k in zip((1.0, 2.0, 4.0), ks, strict=True)]
    lab.calib.set_measurements(ms)
    cv._drives_from_measurements()
    assert cv.drive_list() == [1.0, 1.4]
    assert "kerf =" in cv.emp_text.text() and "R²" in cv.emp_text.text()
    for i in range(cv.quantity.count()):
        cv.quantity.setCurrentIndex(i)
    assert "measured" in cv.csv_text() and "empirical" in cv.csv_text()
    cv.n2d.setValue(2)
    cv.run_2d()
    _wait(app, lambda: cv._job is None, timeout=120)
    assert cv._two_d and "2-D,1.4," in cv.csv_text()
    lab.params.set_drive(1.3)  # a physics edit invalidates the 2-D points
    _wait(app, lambda: not cv._two_d, timeout=10)
    lab.close()
