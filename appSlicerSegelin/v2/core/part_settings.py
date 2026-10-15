"""Per-part overrides for a generated plate/part.

A :class:`~appSlicerSegelin.v2.core.plates.Layer` is regenerated from
scratch every time the preview is rebuilt, so user choices that should
*survive* a rebuild (skip this plate, cut it faster, tint it) live here
instead, keyed by part index in the controller.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PartSettings:
    enabled: bool = True
    reverse: bool = False
    speed_mm_s: float | None = None  # None → inherit the project's speed
    color: str | None = None         # None → default cut colour
    label: str | None = None         # None → the layer's own label
