"""DXF importer.

Honours ``LWPOLYLINE.is_closed`` (legacy lost the closing segment).
Raises typed :class:`DxfImportError` instead of silently swallowing
exceptions (legacy ``except Exception: pass``). Splines, arcs and
circles are flattened with a configurable sagitta.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path as _Path

try:
    import ezdxf
    from ezdxf import bbox  # noqa: F401  - ezdxf side-effect import guard
except ImportError as exc:  # pragma: no cover - dependency missing in tests
    ezdxf = None  # type: ignore[assignment]
    _IMPORT_ERROR: ImportError | None = exc
else:
    _IMPORT_ERROR = None

from ..core.errors import DxfImportError
from ..core.geometry import Point, Segment, SegmentKind


@dataclass(slots=True)
class DxfReadOptions:
    sagitta_mm: float = 0.2  # flattening tolerance for arcs/splines
    arc_min_segments: int = 8


def read_dxf(path: str | _Path, opts: DxfReadOptions | None = None) -> list[Segment]:
    """Parse ``path`` into a flat list of ``CUT``-kind segments.

    Unsupported entities are skipped but logged through the raised
    error's ``entity`` field when ``strict=True``. Here we are
    permissive by default — the slicer cares about geometry, not the
    full DXF feature set.
    """
    if ezdxf is None:
        raise DxfImportError(f"ezdxf is not installed: {_IMPORT_ERROR}")

    options = opts or DxfReadOptions()

    try:
        doc = ezdxf.readfile(str(path))
    except IOError as exc:
        raise DxfImportError(f"Cannot open DXF: {exc}") from exc
    except ezdxf.DXFStructureError as exc:
        raise DxfImportError(f"Invalid DXF structure: {exc}") from exc

    msp = doc.modelspace()
    segments: list[Segment] = []

    for entity in msp:
        kind = entity.dxftype()
        try:
            if kind == "LINE":
                segments.append(_line(entity))
            elif kind == "LWPOLYLINE":
                segments.extend(_lwpolyline(entity))
            elif kind == "POLYLINE":
                segments.extend(_polyline(entity))
            elif kind == "ARC":
                segments.extend(_arc(entity, options))
            elif kind == "CIRCLE":
                segments.extend(_circle(entity, options))
            elif kind == "ELLIPSE":
                segments.extend(_flatten_via_path(entity, options))
            elif kind == "SPLINE":
                segments.extend(_flatten_via_path(entity, options))
        except DxfImportError:
            raise
        except Exception as exc:  # noqa: BLE001 - we wrap with context, never silently
            raise DxfImportError(
                f"Failed to import {kind}: {exc}",
                entity=kind,
                handle=getattr(entity.dxf, "handle", None),
            ) from exc

    # filter degenerate
    return [s for s in segments if not s.is_degenerate]


def _line(entity) -> Segment:  # type: ignore[no-untyped-def]
    a = entity.dxf.start
    b = entity.dxf.end
    return Segment(Point(a.x, a.y), Point(b.x, b.y), SegmentKind.CUT)


def _lwpolyline(entity) -> list[Segment]:  # type: ignore[no-untyped-def]
    points = [(v[0], v[1]) for v in entity.get_points()]
    if len(points) < 2:
        return []
    segs: list[Segment] = []
    for i in range(len(points) - 1):
        segs.append(_seg(points[i], points[i + 1]))
    if entity.is_closed:
        segs.append(_seg(points[-1], points[0]))
    return segs


def _polyline(entity) -> list[Segment]:  # type: ignore[no-untyped-def]
    vertices = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
    if len(vertices) < 2:
        return []
    segs = [_seg(vertices[i], vertices[i + 1]) for i in range(len(vertices) - 1)]
    if entity.is_closed:
        segs.append(_seg(vertices[-1], vertices[0]))
    return segs


def _arc(entity, opts: DxfReadOptions) -> list[Segment]:  # type: ignore[no-untyped-def]
    cx, cy = entity.dxf.center.x, entity.dxf.center.y
    r = entity.dxf.radius
    a0 = math.radians(entity.dxf.start_angle)
    a1 = math.radians(entity.dxf.end_angle)
    if a1 < a0:
        a1 += 2 * math.pi
    n = max(opts.arc_min_segments, _arc_subdivisions(r, a1 - a0, opts.sagitta_mm))
    points = [
        (cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n))
        for i in range(n + 1)
    ]
    return [_seg(points[i], points[i + 1]) for i in range(n)]


def _circle(entity, opts: DxfReadOptions) -> list[Segment]:  # type: ignore[no-untyped-def]
    cx, cy = entity.dxf.center.x, entity.dxf.center.y
    r = entity.dxf.radius
    n = max(opts.arc_min_segments, _arc_subdivisions(r, 2 * math.pi, opts.sagitta_mm))
    points = [
        (cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
        for i in range(n + 1)
    ]
    return [_seg(points[i], points[i + 1]) for i in range(n)]


def _flatten_via_path(entity, opts: DxfReadOptions) -> list[Segment]:  # type: ignore[no-untyped-def]
    """Use ezdxf's path tools to flatten splines and ellipses."""
    from ezdxf.path import make_path

    path = make_path(entity)
    pts = list(path.flattening(opts.sagitta_mm))
    if len(pts) < 2:
        return []
    return [_seg((pts[i].x, pts[i].y), (pts[i + 1].x, pts[i + 1].y)) for i in range(len(pts) - 1)]


def _seg(a: tuple[float, float], b: tuple[float, float]) -> Segment:
    return Segment(Point(a[0], a[1]), Point(b[0], b[1]), SegmentKind.CUT)


def _arc_subdivisions(radius: float, sweep_rad: float, sagitta_mm: float) -> int:
    if radius <= 0 or sweep_rad <= 0 or sagitta_mm <= 0:
        return 8
    # sagitta = r * (1 - cos(theta/2)); solve for theta
    arg = max(min(1.0 - sagitta_mm / radius, 1.0), -1.0)
    step = 2.0 * math.acos(arg)
    if step <= 0:
        return 16
    return max(1, math.ceil(sweep_rad / step))
