"""Save/load a Cut Lab profile: the wire, foam, supply, motion limits, calibration and measurements.

Plain JSON so a profile can be shared between machines or kept per foam batch.

The Cut Lab keeps one default profile (:func:`default_profile_path`; in
portable mode ``datos/cut_lab_profile.json`` next to the executable) that it
saves on every change and loads on start-up, so a calibration stays done. The
guided mode's last step adds the **work settings** chosen for the project (work
feed and kerf compensation); :func:`load_saved_cut_settings` reads just those,
for the main window.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from .calibration import Measurement
from .cutting_physics import FOAMS, WIRE_MATERIALS, Calibration, CutSetup, Foam, WireMaterial, point_state
from .motion import MotionLimits

VERSION = 2  # 2: bench-supply limits, CV by default, work settings
PROFILE_FILENAME = "cut_lab_profile.json"


@dataclass(frozen=True, slots=True)
class WorkSettings:
    """What the guided mode decided for the project: feed and kerf compensation, plus the supply it assumes."""

    work_feed_mm_s: float
    kerf_mm: float               # full slot width at that feed
    supply_mode: str = "voltage"  # "voltage" (CV) or "current" (CC)
    voltage_v: float = 0.0       # set on the supply (CV) / resulting at the terminals (CC)
    current_a: float = 0.0       # resulting (CV) / set (CC)
    calibrated: bool = False     # η, κ fitted to the user's own cuts
    saved_at: str = ""           # ISO date-time

    @property
    def kerf_offset_mm(self) -> float:
        """Kerf compensation per side: offset the path outward by this much."""
        return self.kerf_mm / 2


@dataclass(slots=True)
class CutProfile:
    setup: CutSetup = field(default_factory=CutSetup)
    limits: MotionLimits = field(default_factory=MotionLimits)
    measurements: list[Measurement] = field(default_factory=list)
    probe_speed_mm_s: float = 3.0
    work: WorkSettings | None = None


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
        "work": asdict(p.work) if p.work is not None else None,
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
    probe = float(d.get("probe_speed_mm_s", 3.0))
    if int(d.get("version", 1)) < 2 and setup.mode == "current":
        # v1 defaulted to CC; supplies are run in CV: same wire state, expressed as the voltage it needs
        u = float(point_state(setup, probe, limits=False).voltage_v)
        if math.isfinite(u) and u > 0:
            setup = replace(setup, mode="voltage", voltage_v=round(u, 2))
    work = d.get("work")
    return CutProfile(
        setup=setup,
        limits=_pick(MotionLimits, d.get("limits", {})),
        measurements=[_pick(Measurement, m) for m in d.get("measurements", [])],
        probe_speed_mm_s=probe,
        work=_pick(WorkSettings, work) if isinstance(work, dict) else None,
    )


def save(p: CutProfile, path: str | Path) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(to_dict(p), indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic: a crash mid-write never leaves a broken profile


def load(path: str | Path) -> CutProfile:
    return from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def default_profile_path() -> Path:
    """Where the Cut Lab keeps its default profile.

    Portable mode (:mod:`appSlicerSegelin.v2.portable`): ``datos/cut_lab_profile.json``.
    Otherwise the per-user app-config folder (Qt's ``AppConfigLocation``), or the home folder.
    """
    from ..portable import data_dir

    base = data_dir()
    if base is None:
        try:
            from PyQt6.QtCore import QStandardPaths

            loc = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
            base = Path(loc) if loc else None
        except ImportError:  # pragma: no cover - PyQt6 is a dependency of the app
            base = None
    return Path(base or Path.home()) / PROFILE_FILENAME


def load_saved_cut_settings(path: str | Path | None = None) -> WorkSettings | None:
    """The work feed and kerf compensation last saved from the Cut Lab, or ``None`` if never saved.

    ``path`` defaults to :func:`default_profile_path`. Never raises: a missing
    or broken file gives ``None``.
    """
    p = Path(path) if path is not None else default_profile_path()
    try:
        return load(p).work
    except (OSError, ValueError, TypeError, KeyError):
        return None
