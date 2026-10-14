"""Save/load a Cut Lab profile: the wire, foam, supply, motion limits, calibration and measurements.

Plain JSON so a profile can be shared between machines or kept per foam batch.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from .calibration import Measurement
from .cutting_physics import FOAMS, WIRE_MATERIALS, Calibration, CutSetup, Foam, WireMaterial
from .motion import MotionLimits

VERSION = 1


@dataclass(slots=True)
class CutProfile:
    setup: CutSetup = field(default_factory=CutSetup)
    limits: MotionLimits = field(default_factory=MotionLimits)
    measurements: list[Measurement] = field(default_factory=list)
    probe_speed_mm_s: float = 3.0


def _pick(cls, data: dict[str, Any]):  # type: ignore[no-untyped-def]
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


def to_dict(p: CutProfile) -> dict[str, Any]:
    return {
        "version": VERSION,
        "setup": asdict(p.setup),
        "limits": asdict(p.limits),
        "measurements": [asdict(m) for m in p.measurements],
        "probe_speed_mm_s": p.probe_speed_mm_s,
    }


def from_dict(d: dict[str, Any]) -> CutProfile:
    s = dict(d.get("setup", {}))
    wire = s.pop("wire", None)
    foam = s.pop("foam", None)
    calib = s.pop("calib", None)
    setup = _pick(CutSetup, s)
    if isinstance(wire, dict):
        setup = replace(setup, wire=_pick(WireMaterial, wire))
    elif isinstance(wire, str) and wire in WIRE_MATERIALS:
        setup = replace(setup, wire=WIRE_MATERIALS[wire])
    if isinstance(foam, dict):
        setup = replace(setup, foam=_pick(Foam, foam))
    elif isinstance(foam, str) and foam in FOAMS:
        setup = replace(setup, foam=FOAMS[foam])
    if isinstance(calib, dict):
        setup = replace(setup, calib=_pick(Calibration, calib))
    return CutProfile(
        setup=setup,
        limits=_pick(MotionLimits, d.get("limits", {})),
        measurements=[_pick(Measurement, m) for m in d.get("measurements", [])],
        probe_speed_mm_s=float(d.get("probe_speed_mm_s", 3.0)),
    )


def save(p: CutProfile, path: str | Path) -> None:
    Path(path).write_text(json.dumps(to_dict(p), indent=2), encoding="utf-8")


def load(path: str | Path) -> CutProfile:
    return from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
