"""Bake the Ender-3 CAD into the light mesh the machine simulator draws.

Run with Blender (it does the decimation)::

    blender -b -P models-3d/build_sim_asset.py -- <ender3_obj_dir> <groups.json> <parts_dir> <out.npz>

* ``ender3_obj_dir``: one OBJ per solid of ``Ender3.STEP`` in the STEP frame (mm, Y up, front -Z),
  e.g. from the OCP tessellator used for the thesis renders (``step_a_mallas.py``).
* ``groups.json``: ``{"portico": [...], "cama": [...]}`` file stems that ride on the gantry / bed.
* ``parts_dir``: ``clampC.obj``, ``piezaT.obj``, ``pivot.obj`` (the printed segelín parts) placed on the
  left pivot as in the working assembly (clamp on the X beam, arm vertical on the T's stem).

The output is in the simulator's frame (X along the wire, Y towards the back, Z up; mirrored from the
STEP frame, which is left-handed in these terms) and split by colour so each group is a handful of
GL meshes. Group origins: ``frame`` bed top / wire plane, ``bed`` bed-plate centre, ``gantry`` and the
segelín parts the left pivot axis.
"""
import json
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np

args = sys.argv[sys.argv.index("--") + 1:]
ENDER, GROUPS, PARTS, OUT = Path(args[0]), Path(args[1]), Path(args[2]), Path(args[3])

# measured on the STEP (mm): pivot axis of the left arm, wire plane, bed top and bed-plate centre
PIVOT_X, PIVOT_Y, PIVOT_SPACING = 5.0, 163.5, 140.6
WIRE_Z = -143.7           # wire plane: 1.5 mm in front of the arms
BED_TOP, BED_CZ = 101.0, -79.7
MID_X = PIVOT_X - PIVOT_SPACING / 2  # wire-span centre
ARM_HALF = 70.0           # pivot to each end hole of the stock arm
MIN_DIAG = 6.0            # drop screws, washers and the like
RATIO, MIN_FACES = 0.05, 48

RULES = [  # (substring in the part name, colour); first match wins
    ("profile", "#2a2d33"), ("Endcap", "#1e1f22"), ("belt", "#151515"), ("Rollers", "#202020"),
    ("threaded_rod", "#b8bcc2"), ("Spacers", "#c9ccd1"), ("coupler", "#c9ccd1"), ("pulley", "#c9ccd1"),
    ("E_gear", "#c9a24a"), ("z_nut", "#c9a24a"), ("Copper", "#c9a24a"), ("nozzle", "#c9a24a"),
    ("Heat_block", "#c9ccd1"), ("Radiator", "#c9ccd1"), ("Teflon", "#eeeeee"),
    ("Bed_level_springs", "#e8b923"), ("Hand_Twisted", "#d8d0bf"), ("Hot_bed", "#26272b"),
    ("Y_plate", "#c9ccd1"), ("motor_bracket", "#2f3237"), ("motor", "#3a3d42"),
    ("power_supply", "#8b8e93"), ("Support_tube", "#c9ccd1"), ("Fan_cover", "#2f3237"),
    ("fan", "#1e1f22"), ("Fan", "#1e1f22"), ("Screw", "#b8bcc2"), ("Eccentric", "#b8bcc2"),
]
PLA = "#3ec46d"


def colour(name: str) -> str:
    return next((c for k, c in RULES if k in name), "#2f3237")


def load(path: Path, decimate: bool = True):
    """Vertices (N,3) and triangles (M,3) of one OBJ, decimated; None for tiny parts."""
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.wm.obj_import(filepath=str(path), forward_axis="Y", up_axis="Z")
    objs = list(bpy.context.selected_objects)
    vs, fs, n = [], [], 0
    for o in objs:
        if decimate and len(o.data.polygons) > MIN_FACES:
            m = o.modifiers.new("dec", "DECIMATE")
            m.ratio = max(RATIO, MIN_FACES / len(o.data.polygons))
        dg = bpy.context.evaluated_depsgraph_get()
        me = o.evaluated_get(dg).to_mesh()
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.triangulate(bm, faces=bm.faces)
        v = np.array([p.co[:] for p in bm.verts], dtype=np.float32)
        f = np.array([[p.index for p in t.verts] for t in bm.faces], dtype=np.int64).reshape(-1, 3)
        bm.free()
        o.evaluated_get(dg).to_mesh_clear()
        vs.append(v)
        fs.append(f + n)
        n += len(v)
    for o in objs:
        bpy.data.objects.remove(o)
    if not vs:
        return None
    v, f = np.vstack(vs), np.vstack(fs)
    if np.linalg.norm(v.max(0) - v.min(0)) < MIN_DIAG:
        return None
    return v, f


def to_sim(v: np.ndarray, x0: float, y0: float, z0: float) -> np.ndarray:
    """STEP (x, y up, z back) -> simulator (X mirrored, Y back, Z up), shifted to an origin."""
    return np.column_stack([-(v[:, 0] - x0), v[:, 2] - z0, v[:, 1] - y0]).astype(np.float32)


out: dict[str, np.ndarray] = {}
buckets: dict[tuple[str, str], list] = {}
groups = json.load(open(GROUPS))
origin = {"frame": (MID_X, BED_TOP, WIRE_Z), "bed": (MID_X, BED_TOP, BED_CZ), "gantry": (MID_X, PIVOT_Y, WIRE_Z)}
for path in sorted(ENDER.glob("*.obj")):
    name = path.stem
    if name in groups["portico"]:
        g = "gantry"
    elif name in groups["cama"] and not any(k in name for k in ("pulley", "2GT")):
        g = "bed"
    else:
        g = "frame"
    mesh = load(path)
    if mesh is None:
        continue
    v, f = mesh
    buckets.setdefault((g, colour(name)), []).append((to_sim(v, *origin[g]), f[:, ::-1]))  # mirror: flip winding

for (g, col), parts in sorted(buckets.items()):
    vs, fs, n = [], [], 0
    for v, f in parts:
        vs.append(v)
        fs.append(f + n)
        n += len(v)
    key = f"{g}|{col}"
    out[key + "|v"] = np.vstack(vs)
    out[key + "|f"] = np.vstack(fs).astype(np.uint32)

# segelín parts, in the left pivot's frame: x mirrored about the pivot, z = 0 on the axis
clamp = load(PARTS / "clampC.obj", decimate=False)
tee = load(PARTS / "piezaT.obj", decimate=False)
arm = load(PARTS / "pivot.obj", decimate=False)
clamp[0][:, 1] -= 2.5  # centres the C's opening on the 2020 X beam
c = (arm[0].max(0) + arm[0].min(0)) / 2
arm[0][:, 0] += PIVOT_X - c[0]
arm[0][:, 1] += PIVOT_Y - c[1]
for key, (v, f) in (("clamp", clamp), ("tee", tee), ("arm", arm)):
    out[f"part|{key}|v"] = to_sim(v, PIVOT_X, PIVOT_Y, WIRE_Z)
    out[f"part|{key}|f"] = f[:, ::-1].astype(np.uint32)
meta = {"source": "Ender3.STEP + clampC/piezaT/pivot", "pivot_spacing": PIVOT_SPACING, "arm_half": ARM_HALF,
        "stretch_from": 15.0, "colours": {"pla": PLA}}
out["meta"] = np.frombuffer(json.dumps(meta).encode(), dtype=np.uint8)
np.savez_compressed(OUT, **out)
tri = sum(len(a) for k, a in out.items() if k.endswith("|f"))
print(f"wrote {OUT}: {tri} triangles in {sum(1 for k in out if k.endswith('|f'))} meshes")
