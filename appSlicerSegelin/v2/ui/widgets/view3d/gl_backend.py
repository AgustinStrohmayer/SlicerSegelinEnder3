"""OpenGL renderer (pyqtgraph): the plainer fallback that runs almost anywhere."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QColor, QOffscreenSurface, QOpenGLContext, QVector3D


def _rgba(hexc: str, a: float) -> tuple[float, float, float, float]:
    r, g, b, _ = QColor(hexc).getRgbF()
    return (r, g, b, a)


def opengl_usable() -> tuple[bool, str]:
    """Can this machine make an OpenGL 2+ context (hardware or Qt's software one)?"""
    ctx = QOpenGLContext()
    if not ctx.create():
        return False, "no OpenGL context"
    surf = QOffscreenSurface()
    surf.setFormat(ctx.format())
    surf.create()
    if not ctx.makeCurrent(surf):
        return False, "OpenGL context can't be used"
    major = ctx.format().majorVersion()
    ctx.doneCurrent()
    return (major >= 2, f"OpenGL {major}.x")


def _match_qt_software_gl() -> None:
    """With Qt's software renderer (opengl32sw.dll, e.g. ``QT_OPENGL=software``) PyOpenGL must call
    that same DLL; through the system opengl32.dll every call fails and the view stays blank."""
    from PyQt6.QtCore import QCoreApplication, QLibraryInfo, Qt

    soft = (os.environ.get("QT_OPENGL") == "software"
            or QCoreApplication.testAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL))
    if sys.platform != "win32" or not soft or "OpenGL.GL" in sys.modules:
        return
    import ctypes

    from OpenGL import platform

    dll = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.BinariesPath)) / "opengl32sw.dll"
    if not dll.is_file():
        return
    plat = platform.PLATFORM
    for name in ("OpenGL", "WGL", "GetCurrentContext", "CurrentContextIsValid", "getExtensionProcedure"):
        plat.__dict__.pop(name, None)  # drop values cached from the system DLL
    plat.GL = ctypes.WinDLL(str(dll))
    plat.install(vars(platform))


class _Refit(QObject):
    """Re-frame after the widget gets its real size, until the user moves the camera."""

    def __init__(self, backend: GLBackend) -> None:
        super().__init__(backend.widget)
        self._b = backend

    def eventFilter(self, obj, ev) -> bool:  # type: ignore[no-untyped-def]
        t = ev.type()
        if t in (QEvent.Type.MouseButtonPress, QEvent.Type.Wheel):
            self._b._last_fit = None
        elif t == QEvent.Type.Resize and self._b._last_fit is not None:
            self._b.fit(**self._b._last_fit)
        return False


class GLBackend:
    def __init__(self, owner: Any) -> None:
        ok, why = opengl_usable()
        if not ok:
            raise RuntimeError(why)
        _match_qt_software_gl()
        import pyqtgraph.opengl as gl

        self._gl = gl
        self._owner = owner
        self.widget = gl.GLViewWidget(owner)
        self.widget.setCameraPosition(distance=400, elevation=25, azimuth=-60)
        self._items: dict[str, Any] = {}
        self._group_of: dict[str, str] = {}
        self._full: dict[str, tuple[np.ndarray, str, Any]] = {}
        self._offsets: dict[str, tuple[float, float, float]] = {}
        self._last_fit: dict[str, Any] | None = None
        self.widget.installEventFilter(_Refit(self))

    def _add(self, oid: str, group: str, item: Any) -> None:
        self.remove(oid)
        self._items[oid] = item
        self._group_of[oid] = group
        off = self._offsets.get(group)
        if off:
            item.translate(*off)
        self.widget.addItem(item)

    def theme(self, t: dict[str, Any]) -> None:
        self.widget.setBackgroundColor(t["bg"])

    def mesh(self, oid: str, *, verts, faces, color, opacity, group, edges, shadow, flat, emissive, roughness,
             metalness) -> None:  # type: ignore[no-untyped-def]
        see = opacity < 1
        item = self._gl.GLMeshItem(vertexes=verts, faces=faces, smooth=not flat, color=_rgba(emissive or color, opacity),
                                   shader="shaded", glOptions="translucent" if see else "opaque", drawEdges=False)
        self._add(oid, group, item)

    def lines(self, oid: str, *, pts, color, width, mode, group, opacity, colors) -> None:  # type: ignore[no-untyped-def]
        col: Any = _rgba(color, opacity)
        if colors is not None:
            col = np.column_stack([colors, np.full(len(colors), opacity)])
        glmode = "line_strip" if mode == "strip" else "lines"
        item = self._gl.GLLinePlotItem(pos=pts if len(pts) else np.zeros((0, 3)), color=col, width=width,
                                       antialias=True, mode=glmode)
        self._add(oid, group, item)
        self._full[oid] = (pts, mode, col)

    def points(self, oid: str, *, pts, colors, color, opacity, size, group) -> None:  # type: ignore[no-untyped-def]
        col: Any = colors if colors is not None else _rgba(color, opacity)
        self._add(oid, group, self._gl.GLScatterPlotItem(pos=pts, color=col, size=size, pxMode=True))

    def progress(self, oid: str, n: int, head) -> None:  # type: ignore[no-untyped-def]
        item, full = self._items.get(oid), self._full.get(oid)
        if item is None or full is None:
            return
        pts, mode, col = full
        k = n if mode == "strip" else 2 * n
        p = pts[:k]
        if head is not None and len(p):
            tail = np.array([p[-1], head], np.float32) if mode == "segments" else np.array([head], np.float32)
            p = np.vstack([p, tail])
        if isinstance(col, np.ndarray):
            col = col[: len(p)] if len(col) >= len(p) else np.vstack([col, np.repeat(col[-1:], len(p) - len(col), 0)])
        item.setData(pos=p if len(p) else np.zeros((0, 3)), color=col)

    def color(self, oid: str, color, opacity) -> None:  # type: ignore[no-untyped-def]
        item = self._items.get(oid)
        if item is None or not hasattr(item, "setColor"):
            return
        cur = item.opts.get("color", (1, 1, 1, 1))
        base = _rgba(color, 1.0) if color is not None else tuple(cur)
        a = opacity if opacity is not None else (base[3] if len(base) > 3 else 1.0)
        item.setColor((*base[:3], a))

    def visible(self, oid: str, on: bool) -> None:
        item = self._items.get(oid)
        if item is not None:
            item.setVisible(on)

    def offset(self, group: str, xyz) -> None:  # type: ignore[no-untyped-def]
        self._offsets[group] = tuple(xyz)
        for oid, g in self._group_of.items():
            if g == group:
                it = self._items[oid]
                it.resetTransform()
                it.translate(*xyz)

    def remove(self, oid: str) -> None:
        item = self._items.pop(oid, None)
        self._group_of.pop(oid, None)
        self._full.pop(oid, None)
        if item is not None:
            self.widget.removeItem(item)

    def clear(self, group: str | None) -> None:
        for oid in [k for k, g in self._group_of.items() if group is None or g == group]:
            self.remove(oid)
        if group is None:
            self._offsets.clear()

    def camera(self, *, center, distance, elevation, azimuth, animate) -> None:  # type: ignore[no-untyped-def]
        self._last_fit = None
        self.widget.setCameraPosition(pos=QVector3D(*center), distance=distance, elevation=elevation,
                                      azimuth=azimuth)

    def fit(self, *, elevation, azimuth, animate) -> None:  # type: ignore[no-untyped-def]
        b = self._owner.bounds()
        if b is None:
            return
        self._last_fit = {"elevation": elevation, "azimuth": azimuth, "animate": False}
        lo, hi = b
        c = (lo + hi) / 2
        r = float(np.linalg.norm(hi - lo)) / 2
        # pyqtgraph's fov is horizontal: the vertical half-angle shrinks on wide views
        w, h = max(1, self.widget.width()), max(1, self.widget.height())
        half = np.arctan(np.tan(np.radians(self.widget.opts["fov"] / 2)) * min(1.0, h / w))
        kw: dict[str, Any] = {"pos": QVector3D(*c), "distance": max(r, 1.0) / np.sin(half) * 1.02}
        if elevation is not None:
            kw.update(elevation=elevation, azimuth=azimuth if azimuth is not None else -60.0)
        self.widget.setCameraPosition(**kw)

    def snapshot(self, path: str, callback=None) -> None:  # type: ignore[no-untyped-def]
        ok = self.widget.grabFramebuffer().save(path)
        if callback:
            callback(ok)
