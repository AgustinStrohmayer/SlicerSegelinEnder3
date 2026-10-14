"""Firmware-like motion profile of a G-code toolpath.

:mod:`core.gcode_reader` times every move at its programmed feed. A real
Marlin machine does not: each axis has its own top speed and acceleration
(stock Ender-3: Z tops out at 5 mm/s), moves accelerate and decelerate, and
corners are taken at a junction speed set by the junction deviation. For a
hot wire that matters — wherever the wire slows down it melts more foam.

This module re-times a :class:`Toolpath` with a trapezoidal planner (look-ahead
over the whole path, like Marlin's planner with an unlimited buffer) and
samples it at a fixed arc-length step.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .gcode_reader import Toolpath


@dataclass(frozen=True, slots=True)
class MotionLimits:
    """Per-axis limits, mm/s and mm/s². Defaults: stock Ender-3 Marlin."""

    vmax_y: float = 500.0
    vmax_z: float = 5.0
    accel_y: float = 500.0
    accel_z: float = 100.0
    junction_deviation_mm: float = 0.013
    honor_axis_limits: bool = True
    feed_scale: float = 1.0  # feed override (Marlin M220), 1 = as programmed


@dataclass(frozen=True, slots=True)
class MotionSamples:
    """The wire sampled along its path; arrays share one index."""

    t: np.ndarray       # s
    y: np.ndarray       # mm, G-code coordinates
    z: np.ndarray
    v: np.ndarray       # mm/s, actual speed
    v_cmd: np.ndarray   # mm/s, programmed feed of the move
    move: np.ndarray    # index into toolpath.moves
    rapid: np.ndarray   # bool

    @property
    def total_s(self) -> float:
        return float(self.t[-1]) if len(self.t) else 0.0

    def index_at(self, t: float) -> int:
        return int(np.clip(np.searchsorted(self.t, t, side="right") - 1, 0, max(0, len(self.t) - 1)))


def _move_limits(dy: float, dz: float, feed_mm_s: float, lim: MotionLimits) -> tuple[float, float]:
    n = math.hypot(dy, dz)
    uy, uz = abs(dy) / n, abs(dz) / n
    v, a = feed_mm_s, float("inf")
    for u, vm, am in ((uy, lim.vmax_y, lim.accel_y), (uz, lim.vmax_z, lim.accel_z)):
        if u > 1e-9:
            if lim.honor_axis_limits:
                v = min(v, vm / u)
            a = min(a, am / u)
    return v, a


def plan(toolpath: Toolpath, lim: MotionLimits | None = None, ds_mm: float = 0.25) -> MotionSamples:
    """Trapezoidal look-ahead profile of ``toolpath`` sampled every ``ds_mm`` of path."""
    lim = lim or MotionLimits()
    moves = toolpath.moves
    if not moves:
        z = np.zeros(1)
        sy, sz = toolpath.start
        return MotionSamples(z, z + sy, z + sz, z.copy(), z.copy(), np.zeros(1, int), np.zeros(1, bool))
    n = len(moves)
    length = np.array([m.length for m in moves])
    vmax = np.empty(n)
    acc = np.empty(n)
    units = []
    for i, m in enumerate(moves):
        vmax[i], acc[i] = _move_limits(m.y1 - m.y0, m.z1 - m.z0, m.feed_mm_min / 60.0 * lim.feed_scale, lim)
        units.append(((m.y1 - m.y0) / length[i], (m.z1 - m.z0) / length[i]))
    # junction speed limits (Marlin junction deviation)
    v_junc = np.zeros(n + 1)
    for i in range(1, n):
        (ay, az), (by, bz) = units[i - 1], units[i]
        cos_t = -(ay * by + az * bz)
        if cos_t < -0.999999:  # straight on
            vj = min(vmax[i - 1], vmax[i])
        else:
            sin_h = math.sqrt(max(0.0, 0.5 * (1 - cos_t)))
            a = min(acc[i - 1], acc[i])
            vj = math.sqrt(a * lim.junction_deviation_mm * sin_h / max(1e-9, 1 - sin_h)) if sin_h > 1e-9 else 0.0
        v_junc[i] = min(vj, vmax[i - 1], vmax[i])
    # backward then forward pass
    for i in range(n - 1, -1, -1):
        v_junc[i] = min(v_junc[i], math.sqrt(v_junc[i + 1] ** 2 + 2 * acc[i] * length[i]))
    for i in range(n):
        v_junc[i + 1] = min(v_junc[i + 1], math.sqrt(v_junc[i] ** 2 + 2 * acc[i] * length[i]))

    ts, ys, zs, vs, vc, mv, rp = [], [], [], [], [], [], []
    t = 0.0
    for i, m in enumerate(moves):
        k = max(2, math.ceil(length[i] / ds_mm) + 1)
        s = np.linspace(0.0, length[i], k)
        v0, v1, a = v_junc[i], v_junc[i + 1], acc[i]
        v = np.minimum(np.minimum(np.sqrt(v0**2 + 2 * a * s), vmax[i]), np.sqrt(np.maximum(0, v1**2 + 2 * a * (length[i] - s))))
        dt = np.diff(s) * 2 / np.maximum(v[:-1] + v[1:], 1e-9)
        tt = t + np.concatenate([[0.0], np.cumsum(dt)])
        f = s / length[i]
        sl = slice(0 if i == 0 else 1, None)  # don't repeat the shared junction sample
        ts.append(tt[sl])
        ys.append((m.y0 + (m.y1 - m.y0) * f)[sl])
        zs.append((m.z0 + (m.z1 - m.z0) * f)[sl])
        vs.append(v[sl])
        vc.append(np.full(k, m.feed_mm_min / 60.0 * lim.feed_scale)[sl])
        mv.append(np.full(k, i)[sl])
        rp.append(np.full(k, m.rapid)[sl])
        t = float(tt[-1])
    return MotionSamples(np.concatenate(ts), np.concatenate(ys), np.concatenate(zs), np.concatenate(vs),
                         np.concatenate(vc), np.concatenate(mv), np.concatenate(rp))
