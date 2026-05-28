"""Typed domain exceptions.

The legacy app swallowed errors with bare ``except Exception: pass``
blocks that hid malformed DXFs and unit-detection failures. v2 raises
narrow, typed exceptions and lets the UI layer turn them into toasts.
"""
from __future__ import annotations


class SlicerError(Exception):
    """Base class for every domain error raised by the slicer."""


class DxfImportError(SlicerError):
    """A DXF could not be parsed, or contained an unsupported entity.

    ``entity`` is the DXF entity DXF type (e.g. ``"SPLINE"``) when known,
    so the UI can show ``Failed to import LWPOLYLINE on layer "0"``.
    """

    def __init__(self, message: str, *, entity: str | None = None, handle: str | None = None) -> None:
        super().__init__(message)
        self.entity = entity
        self.handle = handle


class GcodeExportError(SlicerError):
    """Raised when a CutPlan cannot be serialised to G-code."""


class GeometryError(SlicerError):
    """Raised on degenerate / impossible geometry operations."""


class ProjectIOError(SlicerError):
    """Raised when a project file cannot be read or written."""
