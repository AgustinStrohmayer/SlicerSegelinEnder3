"""3D viewport with automatic fallback.

:class:`Scene3D` keeps the scene (meshes, lines, points, group offsets, camera)
in Python and draws it with the best renderer this computer can run:

1. ``three`` — three.js (WebGL) inside QtWebEngine: studio lighting, soft
   shadows, smooth orbit, view gizmo. Needs PyQt6-WebEngine and a GPU driver.
2. ``opengl`` — pyqtgraph's OpenGL view. Plainer, but runs almost anywhere
   (Qt falls back to its software OpenGL, ``opengl32sw.dll``, without a GPU).
3. ``none`` — no 3D at all: a short note; the rest of the app keeps working.

If three.js fails while running (no WebGL, lost context, crashed renderer)
the scene is replayed into the next renderer, so callers never notice.
Force a renderer with the ``SEGELIN_3D`` environment variable
(``three`` / ``opengl`` / ``none``); the portable package's "compatible mode"
launcher uses ``opengl`` with software OpenGL.
"""
from __future__ import annotations

from .scene import Scene3D, backend_preference, prepare_app

__all__ = ["Scene3D", "backend_preference", "prepare_app"]
