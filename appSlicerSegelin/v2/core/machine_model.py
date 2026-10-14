"""The printer's real 3D model for the simulator, posed by the rig parameters.

``assets/<name>_sim.npz`` is baked from the CAD by ``models-3d/build_sim_asset.py``: the printer split
into ``frame`` (static), ``bed`` (rides on Y) and ``gantry`` (rides on Z), each as a few single-colour
meshes, plus the printed segelín parts (clamp, T piece, arm). Everything is in the simulator frame
(X along the wire, 0 = span centre; Y towards the back, 0 = wire plane; Z up). Origins:

* ``frame``: Z = 0 on the bed top;
* ``bed``: bed-plate centre, Z = 0 on the bed top;
* ``gantry`` and the parts: the left arm's pivot axis (Z = 0 there).

The arm is stored straight down; :func:`arm_mesh` stretches its two halves to the rig's lengths and
swings it to the rig's angle, so longer or re-angled arms are drawn with the real part.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .hotwire_rig import HotWireRig

ASSETS = Path(__file__).resolve().parent.parent / "assets"


@dataclass(frozen=True, slots=True)
class MeshPart:
    colour: str
    vertices: np.ndarray  # (N, 3) float32
    faces: np.ndarray     # (M, 3) uint32


@dataclass(frozen=True, slots=True)
class MachineModel:
    groups: dict[str, list[MeshPart]]  # "frame", "bed", "gantry"
    parts: dict[str, MeshPart]         # "clamp", "tee", "arm"
    meta: dict

    @property
    def triangles(self) -> int:
        return sum(len(p.faces) for g in self.groups.values() for p in g)


@lru_cache(maxsize=4)
def load_machine_model(name: str) -> MachineModel | None:
    """The baked model ``name`` (e.g. ``"ender3"``), or None if the rig has none."""
    path = ASSETS / f"{name}_sim.npz"
    if not name or not path.exists():
        return None
    data = np.load(path)
    meta = json.loads(bytes(data["meta"]).decode())
    pla = meta.get("colours", {}).get("pla", "#3ec46d")
    groups: dict[str, list[MeshPart]] = {}
    parts: dict[str, MeshPart] = {}
    for key in data.files:
        if not key.endswith("|v"):
            continue
        head, tail, _ = key.split("|")
        v, f = data[key], data[f"{head}|{tail}|f"]
        if head == "part":
            parts[tail] = MeshPart(pla, v, f)
        else:
            groups.setdefault(head, []).append(MeshPart(tail, v, f))
    return MachineModel(groups, parts, meta)


def mount_mesh(model: MachineModel, part: str, rig: HotWireRig, side: float) -> np.ndarray:
    """Clamp or T piece on the ``side`` (-1 left, +1 right) pivot, in the gantry frame (pivot axis Z = 0)."""
    v = model.parts[part].vertices.copy()
    v[:, 0] += side * rig.pivot_spacing / 2
    return v


def arm_mesh(model: MachineModel, rig: HotWireRig, side: float) -> np.ndarray:
    """The arm on the ``side`` pivot: halves stretched to the rig's lengths, swung to its angle."""
    v = model.parts["arm"].vertices.astype(float)
    half, hub = model.meta.get("arm_half", 70.0), model.meta.get("stretch_from", 15.0)
    v[v[:, 2] < -hub, 2] -= rig.arm_lower_length - half
    v[v[:, 2] > hub, 2] += rig.arm_upper_length - half
    # straight down -> wire end out and down at the arm angle: rotate about Y by side * (90° - angle)
    th = side * math.radians(90.0 - rig.arm_angle_deg)
    x, z = v[:, 0].copy(), v[:, 2].copy()
    v[:, 0] = x * math.cos(th) - z * math.sin(th) + side * rig.pivot_spacing / 2
    v[:, 2] = x * math.sin(th) + z * math.cos(th)
    return v.astype(np.float32)
