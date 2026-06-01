# SlicerSegelin Ender 3

Python desktop application to prepare Y/Z geometry and generate G-Code for a hot-wire CNC workflow based on Ender 3.

## Overview

- Imports DXF and other entities supported by `ezdxf`.
- Lets you rotate, mirror, move, and align profiles.
- Simulates cutting paths and estimates timing.
- Exports standard G-Code, Y×Z plate-split G-Code, and manual-cut batches.
- Exports modified DXF geometry for reuse.

## Project structure

- `appSlicerSegelin/app.py` — main app UI and logic.
- `models-3d/` — CAD models and printable parts.
- `gcode-examples/` — sample and test G-Code outputs.
- `archive/` — historical variants kept for reference.
- `SlicerSegelinEnder3.spec` — standard PyInstaller build.
- `SlicerSegelinEnder3_portable.spec` — portable PyInstaller build.

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

## Getting started

From the repository root:

1. Install dependencies:
   `pip install -r requirements.txt`
2. Run the app:
   - New PyQt6 UI (recommended): `python -m appSlicerSegelin.v2`
   - Legacy Tkinter UI: `python appSlicerSegelin/app.py`

### New v2 UI

`appSlicerSegelin/v2/` is a modular rewrite with a modern PyQt6 interface
(dark/light themes, command palette via `Ctrl+K`, pan/zoom canvas, bottom
simulation timeline) and a UI-agnostic, fully tested core. It keeps full
feature parity with the legacy app: DXF import with unit auto-scaling,
rotate/auto-height/mirror/translate/align/reverse, manual Y/Z/diagonal
cuts, Y×Z plate splitting, real-time simulation, and G-code export
(standard, plate batch) plus modified-DXF export.

Run the tests with `pytest` (install dev tools via
`pip install -r requirements-dev.txt`).

## Building executables

The root `.spec` files are configured for PyInstaller using relative paths, so they work after cloning on another machine.

## Contributing

1. Create a branch for your change.
2. Keep application code in `appSlicerSegelin/`.
3. Do not commit generated artifacts from `build/`, `dist/`, or `__pycache__/`.
4. Put models and samples in `models-3d/` and `gcode-examples/`.

## License

This project is published under the MIT License. See `LICENSE`.

## Security

If you find a security issue or unsafe behavior involving DXF/G-Code handling, test it in an isolated environment and then report it.