"""The printer's baked CAD and the real arms posed by the rig parameters."""
from __future__ import annotations

import pytest

from appSlicerSegelin.v2.core.hotwire_rig import PRESETS
from appSlicerSegelin.v2.core.machine_model import arm_mesh, load_machine_model, mount_mesh

MODEL = load_machine_model("ender3")
pytestmark = pytest.mark.skipif(MODEL is None, reason="assets/ender3_sim.npz not built")


def test_model_groups_and_budget():
    assert set(MODEL.groups) == {"frame", "bed", "gantry"}
    assert set(MODEL.parts) == {"clamp", "tee", "arm"}
    assert 50_000 < MODEL.triangles < 300_000  # light enough for the GL view
    assert load_machine_model("") is None and load_machine_model("cr10") is None


@pytest.mark.parametrize("preset", ["Ender-3", "Ender-3 (long arms)"])
def test_arm_follows_the_rig(preset):
    rig = PRESETS[preset]
    for side in (-1.0, 1.0):
        v = arm_mesh(MODEL, rig, side)
        assert v[:, 2].min() == pytest.approx(-rig.wire_drop - rig.arm_reach_below_wire, abs=0.6)
        assert side * v[v[:, 2].argmin(), 0] == pytest.approx(rig.wire_span / 2, abs=8.0)  # tip at the wire end
        top = v[v[:, 2].argmax()]  # spring end leans inwards
        assert side * top[0] < rig.pivot_spacing / 2


def test_arm_angle_and_mounts():
    rig = PRESETS["Ender-3 (long arms)"]
    steep = arm_mesh(MODEL, replace_angle(rig, 85.0), 1.0)
    assert steep[:, 0].max() < arm_mesh(MODEL, rig, 1.0)[:, 0].max()
    c = mount_mesh(MODEL, "clamp", rig, 1.0)
    assert c[:, 0].mean() == pytest.approx(rig.pivot_spacing / 2, abs=3.0)
    assert c[:, 2].min() < 0 < c[:, 2].max()  # the clamp grips the beam around the pivot height


def replace_angle(rig, deg):
    from dataclasses import replace

    return replace(rig, arm_angle_deg=deg)
