"""DXF exporter.

Rounds coordinates using the active ``MachineProfile`` so the file
matches the precision of the G-code that was emitted alongside it.
"""
from __future__ import annotations

from pathlib import Path as _Path

try:
    import ezdxf
except ImportError as exc:  # pragma: no cover
    ezdxf = None  # type: ignore[assignment]
    _IMPORT_ERROR: ImportError | None = exc
else:
    _IMPORT_ERROR = None

from ..core.errors import DxfImportError
from ..core.geometry import Segment
from ..core.machine import MachineProfile


def write_dxf(path: str | _Path, segments: list[Segment], machine: MachineProfile) -> int:
    """Write ``segments`` to ``path`` and return how many were written."""
    if ezdxf is None:
        raise DxfImportError(f"ezdxf is not installed: {_IMPORT_ERROR}")
    doc = ezdxf.new("R2010")
    doc.units = 4  # millimeters
    msp = doc.modelspace()
    written = 0
    for s in segments:
        if s.is_degenerate:
            continue
        msp.add_line(
            (machine.round_coord(s.a.y), machine.round_coord(s.a.z)),
            (machine.round_coord(s.b.y), machine.round_coord(s.b.z)),
        )
        written += 1
    doc.saveas(str(path))
    return written
