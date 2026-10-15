"""Material-removal simulation of a hot-wire cut: what part actually comes out.

The machine is 2-axis, so the cut is an extrusion along the wire (X) — but
the wire is not the same everywhere along X: it is colder in the foam than
in the air, colder near the clamps, and it bows more in the middle. So the
block is simulated as a stack of **slices** across the wire, like the layers
of an FDM slicer. In each slice (a Y–Z grid of the block):

1. the wire follows the firmware-timed path (:mod:`core.motion`), delayed by
   its bow: a first-order lag whose distance equals the steady bow at the
   local speed — so corners get rounded where the wire drags;
2. at every step the foam within the local melt radius of the wire is removed
   (a swept, variable-radius capsule). The radius comes from the span profile
   (:func:`core.cutting_physics.span_profile`) at this slice's X and the
   current speed; a wire that has just come from air is hotter, so the kerf
   flares where the wire enters the foam and relaxes with the wire's thermal
   time constant;
3. the cells remember *when* they were removed and with what radius/regime,
   so the UI can scrub through time without re-simulating.

At the end the remaining foam is split into connected pieces; the **product**
is the piece(s) not touching the block's outer faces (the part released by a
closed cut). Its edge is compared with the nominal part (the same path cut by
an ideal zero-kerf wire) to give the deviation along the contour.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from .cutting_physics import CutSetup, SpanProfile, span_profile, wire_time_constant_s
from .gcode_reader import Toolpath
from .hotwire_rig import FoamBlock
from .motion import MotionLimits, MotionSamples, plan

MAX_CELLS = 1_400_000


@dataclass(slots=True)
class SliceResult:
    x_mm: float                 # position along the wire (0 = span centre)
    t_removed: np.ndarray       # [nz, ny] float32 s; inf = still foam
    r_removed: np.ndarray       # [nz, ny] float16 mm; kerf half-width when removed
    contact: np.ndarray         # [nz, ny] bool: removed while the wire touched the foam
    product: np.ndarray         # [nz, ny] bool
    wire_y: np.ndarray          # [samples] effective (lagged) wire position
    wire_z: np.ndarray
    radius: np.ndarray          # [samples] kerf half-width while cutting
    in_foam: np.ndarray         # [samples] bool
    contact_t: np.ndarray       # [samples] bool
    edge_y: np.ndarray = field(default_factory=lambda: np.zeros(0))  # product boundary cells
    edge_z: np.ndarray = field(default_factory=lambda: np.zeros(0))
    edge_dev: np.ndarray = field(default_factory=lambda: np.zeros(0))  # mm, + excess / − loss
    released: bool = True
    stats: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class SimResult:
    block: FoamBlock
    setup: CutSetup
    samples: MotionSamples
    profile: SpanProfile
    h: float                    # cell size, mm
    y0: float                   # grid origin (G-code), cell (0, 0) centre at y0 + h/2
    z0: float
    nominal: np.ndarray         # [nz, ny] bool: nominal product
    slices: list[SliceResult]
    warnings: list[str]
    tau_wire_s: float

    @property
    def shape(self) -> tuple[int, int]:
        return self.nominal.shape

    def summary(self) -> dict[str, float]:
        devs = np.concatenate([s.edge_dev for s in self.slices if len(s.edge_dev)]) if self.slices else np.zeros(0)
        out = {"slices": float(len(self.slices)), "released": float(all(s.released for s in self.slices))}
        if len(devs):
            out.update(dev_mean=float(devs.mean()), dev_min=float(devs.min()), dev_max=float(devs.max()))
        return out


# ── helpers ───────────────────────────────────────────────────────────
def label4(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected component labels of a boolean image (run-length union-find)."""
    nz, ny = mask.shape
    parent: list[int] = [0]

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    runs_prev: list[tuple[int, int, int]] = []
    row_runs: list[list[tuple[int, int, int]]] = []
    for r in range(nz):
        row = mask[r]
        d = np.diff(np.concatenate(([0], row.view(np.int8), [0])))
        starts = np.nonzero(d == 1)[0]
        ends = np.nonzero(d == -1)[0]
        runs = []
        j = 0
        for s, e in zip(starts.tolist(), ends.tolist(), strict=True):
            lab = 0
            while j < len(runs_prev) and runs_prev[j][1] <= s:
                j += 1
            k = j
            while k < len(runs_prev) and runs_prev[k][0] < e:
                other = find(runs_prev[k][2])
                if lab == 0:
                    lab = other
                elif other != lab:
                    parent[max(other, lab)] = min(other, lab)
                    lab = min(other, lab)
                k += 1
            if lab == 0:
                lab = len(parent)
                parent.append(lab)
            runs.append((s, e, lab))
        row_runs.append(runs)
        runs_prev = runs
    remap = np.zeros(len(parent), np.int32)
    count = 0
    for a in range(1, len(parent)):
        root = find(a)
        if remap[root] == 0:
            count += 1
            remap[root] = count
        remap[a] = remap[root]
    labels = np.zeros((nz, ny), np.int32)
    for r, runs in enumerate(row_runs):
        for s, e, lab in runs:
            labels[r, s:e] = remap[lab]
    return labels, count


def _product(material: np.ndarray) -> tuple[np.ndarray, bool]:
    """Pieces not touching the block border; ``released`` is False if there are none."""
    labels, n = label4(material)
    if n == 0:
        return np.zeros_like(material), False
    border = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    inner = np.setdiff1d(np.arange(1, n + 1), border)
    if len(inner) == 0:
        return np.zeros_like(material), False
    return np.isin(labels, inner), True


def _edges(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Row/col indices of mask cells with a 4-neighbour outside the mask."""
    p = np.pad(mask, 1)
    inner = p[1:-1, 1:-1] & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    return np.nonzero(mask & ~inner)


def _dist_to_polyline(py: np.ndarray, pz: np.ndarray, ly: np.ndarray, lz: np.ndarray) -> np.ndarray:
    """Distance from each point to the polyline (chunked to bound memory)."""
    ay, az = ly[:-1], lz[:-1]
    dy, dz = ly[1:] - ay, lz[1:] - az
    ll = np.maximum(dy * dy + dz * dz, 1e-18)
    out = np.empty(len(py))
    step = max(1, 4_000_000 // max(1, len(ay)))
    for i in range(0, len(py), step):
        qy, qz = py[i:i + step, None], pz[i:i + step, None]
        u = np.clip(((qy - ay) * dy + (qz - az) * dz) / ll, 0, 1)
        out[i:i + step] = np.sqrt(np.min((ay + u * dy - qy) ** 2 + (az + u * dz - qz) ** 2, axis=1))
    return out


class _Grid:
    def __init__(self, block: FoamBlock, h: float) -> None:
        self.h = h
        self.y0, self.z0 = block.y0, block.z0
        self.ny = max(2, math.ceil(block.length_y / h))
        self.nz = max(2, math.ceil(block.height_z / h))
        self.yc = self.y0 + (np.arange(self.ny) + 0.5) * h
        self.zc = self.z0 + (np.arange(self.nz) + 0.5) * h

    def cell(self, y: float, z: float) -> tuple[int, int]:
        return math.floor((z - self.z0) / self.h), math.floor((y - self.y0) / self.h)

    def window(self, ya: float, za: float, yb: float, zb: float, r: float):  # type: ignore[no-untyped-def]
        h = self.h
        j0 = max(0, math.floor((min(ya, yb) - r - self.y0) / h))
        j1 = min(self.ny, math.ceil((max(ya, yb) + r - self.y0) / h) + 1)
        i0 = max(0, math.floor((min(za, zb) - r - self.z0) / h))
        i1 = min(self.nz, math.ceil((max(za, zb) + r - self.z0) / h) + 1)
        if j0 >= j1 or i0 >= i1:
            return None
        qy = self.yc[j0:j1][None, :]
        qz = self.zc[i0:i1][:, None]
        dy, dz = yb - ya, zb - za
        ll = dy * dy + dz * dz
        if ll < 1e-18:
            d2 = (qy - ya) ** 2 + (qz - za) ** 2
        else:
            u = np.clip(((qy - ya) * dy + (qz - za) * dz) / ll, 0, 1)
            d2 = (ya + u * dy - qy) ** 2 + (za + u * dz - qz) ** 2
        return (slice(i0, i1), slice(j0, j1)), d2 <= r * r


def choose_cell(block: FoamBlock, requested: float | None = None) -> float:
    h = requested or max(block.length_y, block.height_z) / 1600
    h = max(0.02, min(0.25, h))
    while (block.length_y / h) * (block.height_z / h) > MAX_CELLS:
        h *= 1.15
    return h


def _nominal(block: FoamBlock, samples: MotionSamples, h: float) -> np.ndarray:
    g = _Grid(block, h)
    removed = np.zeros((g.nz, g.ny), bool)
    r = 0.75 * h
    for i in range(1, len(samples.t)):
        w = g.window(samples.y[i - 1], samples.z[i - 1], samples.y[i], samples.z[i], r)
        if w is not None:
            removed[w[0]] |= w[1]
    prod, _ = _product(~removed)
    return prod


def _at_x(prof: SpanProfile, table: np.ndarray, x: float) -> np.ndarray:
    """Column of a [speed, node] table at wire position ``x`` (linear between in-foam nodes)."""
    xs = prof.x_mm[prof.in_foam]
    cols = table[:, prof.in_foam]
    if len(xs) == 0:
        return table[:, len(prof.x_mm) // 2]
    x = float(np.clip(x, xs[0], xs[-1]))
    j = int(np.clip(np.searchsorted(xs, x), 1, len(xs) - 1))
    f = (x - xs[j - 1]) / max(xs[j] - xs[j - 1], 1e-12)
    return cols[:, j - 1] * (1 - f) + cols[:, j] * f


def _interp_v(v: np.ndarray, speeds: np.ndarray, table: np.ndarray) -> np.ndarray:
    lv = np.log(np.clip(v, speeds[0], speeds[-1]))
    return np.interp(lv, np.log(speeds), table)


def simulate(
    toolpath: Toolpath,
    block: FoamBlock,
    setup: CutSetup,
    *,
    limits: MotionLimits | None = None,
    n_slices: int = 7,
    cell_mm: float | None = None,
    profile: SpanProfile | None = None,
    progress: Callable[[float, str], bool] | None = None,
) -> SimResult:
    """Run the removal simulation. ``progress(frac, msg)`` returning False cancels."""

    def tick(f: float, msg: str) -> None:
        if progress is not None and progress(f, msg) is False:
            raise InterruptedError("cancelled")

    h = choose_cell(block, cell_mm)
    tick(0.02, "Planning motion…")
    samples = plan(toolpath, limits, ds_mm=min(0.25, max(h, 0.05)))
    setup = setup.with_(block_width_mm=block.width_x, block_offset_mm=block.x_offset)
    tick(0.05, "Solving the wire along its span…")
    prof = profile if profile is not None else span_profile(setup)
    tau = wire_time_constant_s(setup, float(prof.t_air_ref_c[len(prof.speeds) // 2]))
    warnings: list[str] = []
    v_typ = float(np.median(samples.v)) if len(samples.v) else 1.0
    k_typ = int(np.clip(np.searchsorted(prof.speeds, v_typ), 0, len(prof.speeds) - 1))
    if prof.stall[k_typ].any():
        warnings.append("At the typical feed the wire is not hot enough to melt the foam: it will tear or stall.")
    tick(0.10, "Nominal part…")
    nominal = _nominal(block, samples, h)
    g = _Grid(block, h)

    half = block.width_x / 2
    edge = min(0.5, half / 4)
    xs = block.x_offset + (np.linspace(-half + edge, half - edge, n_slices) if n_slices > 1 else np.zeros(1))
    dt = np.diff(samples.t, prepend=samples.t[0])
    slices: list[SliceResult] = []
    ly, lz = samples.y, samples.z
    for k, x in enumerate(xs):
        tick(0.12 + 0.85 * k / len(xs), f"Slice {k + 1}/{len(xs)} at X {x:+.1f} mm…")
        r_of_v = _at_x(prof, prof.r_m_mm, x) * setup.calib.kappa
        r_f = _interp_v(samples.v, prof.speeds, r_of_v)
        # the melt front can't jump out to the wide steady radius of a near-standstill: it grows at the speed
        # whose steady radius is the current one (r_m falls with speed, so invert the reversed table)
        rv_r, rv_v = r_of_v[::-1], prof.speeds[::-1]
        r_e = _interp_v(samples.v, prof.speeds, _at_x(prof, prof.r_entry_mm, x)) * setup.calib.kappa
        bow = _interp_v(samples.v, prof.speeds, _at_x(prof, prof.bow_mm, x))
        con = _interp_v(samples.v, prof.speeds, _at_x(prof, prof.contact.astype(float), x)) > 0.5
        # lagged wire: first-order follower whose steady lag at speed v is the bow
        wy, wz = np.empty_like(ly), np.empty_like(lz)
        wy[0], wz[0] = ly[0], lz[0]
        for i in range(1, len(ly)):
            if bow[i] > 1e-4 and samples.v[i] > 1e-6:
                a = 1 - math.exp(-dt[i] * samples.v[i] / bow[i])
                wy[i] = wy[i - 1] + a * (ly[i] - wy[i - 1])
                wz[i] = wz[i - 1] + a * (lz[i] - wz[i - 1])
            else:
                wy[i], wz[i] = ly[i], lz[i]
        t_rem = np.full((g.nz, g.ny), np.inf, np.float32)
        r_rem = np.zeros((g.nz, g.ny), np.float16)
        c_rem = np.zeros((g.nz, g.ny), bool)
        radius = np.zeros(len(ly))
        in_foam = np.zeros(len(ly), bool)
        t_in = 0.0
        r_prev = setup.diameter_mm / 2
        for i in range(1, len(ly)):
            ya, za, yb, zb = wy[i - 1], wz[i - 1], wy[i], wz[i]
            seg = math.hypot(yb - ya, zb - za)
            r = r_f[i] + (r_e[i] - r_f[i]) * math.exp(-t_in / max(tau, 1e-3))
            if r > r_prev:
                v_grow = float(np.interp(r_prev, rv_r, rv_v))
                r = min(r, r_prev + v_grow * dt[i])
            r_prev = r
            # the foam just ahead of the wire decides if it is cutting or in its own kerf/air
            if seg > 1e-9:
                fy, fz = yb + (yb - ya) / seg * (r + h), zb + (zb - za) / seg * (r + h)
            else:
                fy, fz = yb, zb
            ci, cj = g.cell(fy, fz)
            cutting = 0 <= ci < g.nz and 0 <= cj < g.ny and bool(np.isinf(t_rem[ci, cj]))
            t_in = t_in + dt[i] if cutting else 0.0
            in_foam[i] = cutting
            radius[i] = r
            w = g.window(ya, za, yb, zb, r)
            if w is None:
                continue
            sl, hit = w
            new = hit & np.isinf(t_rem[sl])
            if new.any():
                t_rem[sl][new] = samples.t[i]
                r_rem[sl][new] = r
                c_rem[sl][new] = con[i]
        material = np.isinf(t_rem)
        product, released = _product(material)
        sr = SliceResult(float(x), t_rem, r_rem, c_rem, product, wy, wz, radius, in_foam, con & in_foam,
                         released=released)
        _deviation(sr, g, nominal, ly, lz, samples)
        slices.append(sr)
    if not all(s.released for s in slices):
        warnings.append("The part is not released in every slice (open path, or the cut stalls).")
    tick(1.0, "Done")
    return SimResult(block, setup, samples, prof, h, g.y0, g.z0, nominal, slices, warnings, tau)


def _deviation(sr: SliceResult, g: _Grid, nominal: np.ndarray, ly: np.ndarray, lz: np.ndarray,
               samples: MotionSamples) -> None:
    rows, cols = _edges(sr.product)
    if len(rows) == 0:
        sr.stats = {"area_mm2": 0.0, "nominal_area_mm2": float(nominal.sum() * g.h**2)}
        return
    py, pz = g.yc[cols], g.zc[rows]
    cut = ~samples.rapid
    d = _dist_to_polyline(py, pz, ly[cut] if cut.sum() > 1 else ly, lz[cut] if cut.sum() > 1 else lz)
    outside = ~nominal[rows, cols]
    dev = np.where(outside, d, -d)
    sr.edge_y, sr.edge_z, sr.edge_dev = py, pz, dev
    zz, yy = np.nonzero(sr.product)
    nz_, ny_ = np.nonzero(nominal)
    h = g.h
    sr.stats = {
        "area_mm2": float(sr.product.sum() * h * h),
        "nominal_area_mm2": float(nominal.sum() * h * h),
        "length_y": float((yy.max() - yy.min() + 1) * h),
        "height_z": float((zz.max() - zz.min() + 1) * h),
        "nominal_length_y": float((ny_.max() - ny_.min() + 1) * h) if len(ny_) else 0.0,
        "nominal_height_z": float((nz_.max() - nz_.min() + 1) * h) if len(nz_) else 0.0,
        "dev_mean": float(dev.mean()),
        "dev_min": float(dev.min()),
        "dev_max": float(dev.max()),
        "contact_frac": float(sr.contact_t[sr.in_foam].mean()) if sr.in_foam.any() else 0.0,
    }
