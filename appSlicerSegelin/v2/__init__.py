"""SlicerSegelinEnder3 v2 — modular PyQt6 rewrite.

Layout:
  core/       UI-agnostic domain (geometry, transforms, gcode plan, undo).
  io/         File I/O: DXF read/write, G-code emit, project save/load.
  services/   Orchestration on top of core + io.
  ui/         PyQt6 shell. Only this layer imports Qt.

The legacy entry point (``appSlicerSegelin/app.py``) keeps working in
parallel until the v2 cutover; nothing in v2 touches it.
"""

__version__ = "2.0.0-dev"
