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
