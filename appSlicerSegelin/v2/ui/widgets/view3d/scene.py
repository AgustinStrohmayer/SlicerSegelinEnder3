"""The renderer-independent scene and the widget that picks a renderer."""
from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import numpy as np
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import QLabel, QStackedLayout, QWidget

from .... import portable
from ...theming.tokens import get_tokens

Color = str | Sequence[float]
ORDER = ("three", "opengl", "none")
_SETTINGS_KEY = "view3d/backend"


def backend_preference() -> str:
    """``auto`` unless the user (env var or settings) asked for a renderer."""
    env = os.environ.get("SEGELIN_3D", "").strip().lower()
    if env in ORDER:
        return env
    val = portable.settings("SlicerSegelinEnder3").value(_SETTINGS_KEY, "auto")
    return val if val in ORDER else "auto"


def set_backend_preference(name: str) -> None:
    portable.settings("SlicerSegelinEnder3").setValue(_SETTINGS_KEY, name)


def prepare_app() -> None:
    """Call before creating the QApplication: lets the three.js renderer register its URL scheme.

    Compatible mode (``opengl``) also switches Qt to its bundled software OpenGL, which runs
    on computers without a usable graphics driver.
    """
    pref = backend_preference()
    if pref == "opengl" and not os.environ.get("QT_OPENGL"):
        from PyQt6.QtCore import QCoreApplication, Qt

        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    if pref in ("opengl", "none"):
        return
    try:
        from . import three_backend
    except ImportError:  # PyQt6-WebEngine not installed: OpenGL it is
        return
    three_backend.register_scheme()


def split_color(c: Color) -> tuple[str, float]:
    """Hex colour + alpha from ``'#rrggbb'`` or an (r, g, b[, a]) tuple of 0..1 floats."""
    if isinstance(c, str):
        q = QColor(c)
        return q.name(), q.alphaF() if len(c.lstrip("#")) == 8 else 1.0
    r, g, b, *a = (float(v) for v in c)
    return QColor.fromRgbF(min(max(r, 0), 1), min(max(g, 0), 1), min(max(b, 0), 1)).name(), (a[0] if a else 1.0)


def _segments_from_strip(pts: np.ndarray) -> np.ndarray:
    """A NaN-separated polyline as explicit segments (pairs of points)."""
    ok = np.isfinite(pts).all(axis=1)
    keep = ok[:-1] & ok[1:]
    a, b = pts[:-1][keep], pts[1:][keep]
    out = np.empty((2 * len(a), 3), np.float32)
    out[0::2], out[1::2] = a, b
    return out


class Scene3D(QWidget):
    """A 3D viewport. Z is up, units are mm. Objects have string ids and live in named groups."""

    backendChanged = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None, theme: str = "dark", *, prefer: str | None = None) -> None:
        super().__init__(parent)
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._objects: dict[str, tuple[str, dict[str, Any]]] = {}
        self._state: dict[str, dict[str, Any]] = {}       # per-object: progress / colour / visibility
        self._offsets: dict[str, tuple[float, float, float]] = {}
        self._view: tuple[str, dict[str, Any]] | None = None
        self._theme = theme
        self.backend: Any = None
        self.backend_name = ""
        self.fallback_reason = ""
        pref = prefer or backend_preference()
        self._candidates = list(ORDER[ORDER.index(pref):]) if pref in ORDER else list(ORDER)
        self._next_backend()

    # ── renderer selection ────────────────────────────────────────────
    def _next_backend(self, reason: str = "") -> None:
        if reason:
            self.fallback_reason = f"{self.backend_name}: {reason}"
        if self.backend is not None:
            old = self.backend.widget
            self._stack.removeWidget(old)
            old.deleteLater()
            self.backend = None
        while self._candidates:
            name = self._candidates.pop(0)
            try:
                be = self._make(name)
            except Exception as exc:  # this renderer can't run here: try the next one
                self.fallback_reason = f"{name}: {exc}"
                continue
            self.backend, self.backend_name = be, name
            self._stack.addWidget(be.widget)
            self._stack.setCurrentWidget(be.widget)
            self._replay()
            self.backendChanged.emit(name)
            return

    def _make(self, name: str) -> Any:
        if name == "three":
            from .three_backend import ThreeBackend

            return ThreeBackend(self, on_fail=self._next_backend)
        if name == "opengl":
            from .gl_backend import GLBackend

            return GLBackend(self)
        return _NoBackend(self)

    def _replay(self) -> None:
        be = self.backend
        be.theme(self._theme_payload())
        for oid, (kind, kw) in self._objects.items():
            getattr(be, kind)(oid, **kw)
            st = self._state.get(oid, {})
            if "progress" in st:
                be.progress(oid, *st["progress"])
            if "color" in st:
                be.color(oid, *st["color"])
            if "visible" in st:
                be.visible(oid, st["visible"])
        for g, xyz in self._offsets.items():
            be.offset(g, xyz)
        if self._view is not None:
            op, kw = self._view
            getattr(be, op)(**{**kw, "animate": False})

    # ── theme ─────────────────────────────────────────────────────────
    def _theme_payload(self) -> dict[str, Any]:
        c = get_tokens(self._theme).color  # type: ignore[arg-type]
        dark = QColor(c.bg).lightnessF() < 0.5
        return {"dark": dark, "bg": c.bg, "bg2": c.surface_alt if dark else c.surface, "text": c.text,
                "muted": c.muted, "surface": c.surface, "border": c.border, "accent": c.accent}

    def set_theme(self, theme: str) -> None:
        self._theme = theme
        self.backend.theme(self._theme_payload())

    # ── objects ───────────────────────────────────────────────────────
    def _put(self, kind: str, oid: str, kw: dict[str, Any]) -> None:
        self._objects[oid] = (kind, kw)
        self._state.pop(oid, None)
        getattr(self.backend, kind)(oid, **kw)

    def mesh(self, oid: str, verts: np.ndarray, faces: np.ndarray, color: Color, *, group: str = "",
             opacity: float | None = None, edges: bool = False, shadow: bool = True, flat: bool = True,
             emissive: str | None = None, roughness: float = 0.55, metalness: float = 0.08) -> None:
        hexc, a = split_color(color)
        self._put("mesh", oid, {
            "verts": np.ascontiguousarray(verts, np.float32).reshape(-1, 3),
            "faces": np.ascontiguousarray(faces, np.uint32).reshape(-1, 3),
            "color": hexc, "opacity": a if opacity is None else opacity, "group": group, "edges": edges,
            "shadow": shadow, "flat": flat, "emissive": emissive, "roughness": roughness, "metalness": metalness})

    def box(self, oid: str, x0: float, y0: float, z0: float, x1: float, y1: float, z1: float, color: Color,
            **kw: Any) -> None:
        v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                      [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], np.float32)
        self.mesh(oid, v, BOX_FACES, color, **kw)

    def lines(self, oid: str, pts: np.ndarray, color: Color, *, width: float = 1.5, mode: str = "strip",
              group: str = "", opacity: float | None = None, colors: np.ndarray | None = None) -> None:
        """A polyline (``strip``; NaN rows break it) or independent ``segments`` (point pairs)."""
        p = np.asarray(pts, np.float32).reshape(-1, 3)
        if mode == "strip" and len(p) and not np.isfinite(p).all():
            p, mode, colors = _segments_from_strip(p), "segments", None
        hexc, a = split_color(color)
        cols = None if colors is None else np.ascontiguousarray(np.asarray(colors, np.float32)[:, :3])
        self._put("lines", oid, {"pts": p, "color": hexc, "width": width, "mode": mode, "group": group,
                                 "opacity": a if opacity is None else opacity, "colors": cols})

    def points(self, oid: str, pts: np.ndarray, *, colors: np.ndarray | None = None, color: Color = "#ffffff",
               size: float = 3.0, group: str = "") -> None:
        """Round screen-sized dots; ``colors`` is (N, 4) RGBA in 0..1."""
        hexc, a = split_color(color)
        cols = None if colors is None else np.ascontiguousarray(np.asarray(colors, np.float32).reshape(-1, 4))
        self._put("points", oid, {"pts": np.asarray(pts, np.float32).reshape(-1, 3), "colors": cols,
                                  "color": hexc, "opacity": a, "size": size, "group": group})

    def progress(self, oid: str, n: int, head: Sequence[float] | None = None) -> None:
        """Show only the first ``n`` points (strip) / segments of a line, plus a segment to ``head``."""
        if oid not in self._objects:
            return
        h = None if head is None else tuple(float(v) for v in head)
        self._state.setdefault(oid, {})["progress"] = (int(n), h)
        self.backend.progress(oid, int(n), h)

    def color(self, oid: str, color: Color | None = None, opacity: float | None = None) -> None:
        if oid not in self._objects:
            return
        hexc, a = split_color(color) if color is not None else (None, None)
        op = opacity if opacity is not None else (a if color is not None and not isinstance(color, str) else None)
        self._state.setdefault(oid, {})["color"] = (hexc, op)
        self.backend.color(oid, hexc, op)

    def visible(self, oid: str, on: bool) -> None:
        if oid in self._objects:
            self._state.setdefault(oid, {})["visible"] = bool(on)
            self.backend.visible(oid, bool(on))

    def offset(self, group: str, xyz: Sequence[float]) -> None:
        t = (float(xyz[0]), float(xyz[1]), float(xyz[2]))
        if self._offsets.get(group) == t:
            return
        self._offsets[group] = t
        self.backend.offset(group, t)

    def remove(self, oid: str) -> None:
        if self._objects.pop(oid, None) is not None:
            self._state.pop(oid, None)
            self.backend.remove(oid)

    def clear(self, group: str | None = None) -> None:
        drop = [k for k, (_, kw) in self._objects.items() if group is None or kw.get("group", "") == group]
        for k in drop:
            del self._objects[k]
            self._state.pop(k, None)
        if group is None:
            self._offsets.clear()
        self.backend.clear(group)

    def has(self, oid: str) -> bool:
        return oid in self._objects

    # ── camera ────────────────────────────────────────────────────────
    def camera(self, center: Sequence[float], distance: float, elevation: float = 25.0, azimuth: float = -60.0,
               *, animate: bool = False) -> None:
        """Look at ``center`` from ``distance`` mm; elevation above the XY plane, azimuth from +X (degrees)."""
        kw = {"center": tuple(float(v) for v in center), "distance": float(distance),
              "elevation": float(elevation), "azimuth": float(azimuth)}
        self._view = ("camera", kw)
        self.backend.camera(**kw, animate=animate)

    def fit(self, elevation: float | None = None, azimuth: float | None = None, *, animate: bool = True) -> None:
        """Frame everything visible, from the given direction (or the current one)."""
        kw = {"elevation": elevation, "azimuth": azimuth}
        self._view = ("fit", kw)
        self.backend.fit(**kw, animate=animate)

    def bounds(self) -> tuple[np.ndarray, np.ndarray] | None:
        """Axis-aligned bounds of every object, offsets included."""
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        for kind, kw in self._objects.values():
            p = kw["verts"] if kind == "mesh" else kw["pts"]
            p = p[np.isfinite(p).all(axis=1)]
            if not len(p):
                continue
            off = np.array(self._offsets.get(kw.get("group", ""), (0, 0, 0)))
            lo, hi = np.minimum(lo, p.min(0) + off), np.maximum(hi, p.max(0) + off)
        return None if not np.isfinite(lo).all() else (lo, hi)

    def snapshot(self, path: str, callback: Any = None) -> None:
        """Save what the renderer shows to a PNG (asynchronous for three.js)."""
        self.backend.snapshot(path, callback)


BOX_FACES = np.array([
    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
    [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6],
    [1, 2, 6], [1, 6, 5], [0, 4, 7], [0, 7, 3],
], np.uint32)


class _NoBackend:
    """Last resort: say so, keep the rest of the app working."""

    def __init__(self, owner: Scene3D) -> None:
        reason = owner.fallback_reason or "no renderer available"
        hint = ""
        on_screen = QGuiApplication.platformName() in ("windows", "xcb", "wayland", "cocoa")  # not offscreen tests
        if on_screen and backend_preference() == "auto":  # next start: compatible mode (software OpenGL)
            set_backend_preference("opengl")
            hint = "Restart the app to use the simpler 3D view (compatible mode).\n"
        self.widget = QLabel(
            "The 3D view can't run on this computer right now.\n"
            f"{hint}Everything else works normally.\n\n({reason})")
        self.widget.setWordWrap(True)
        self.widget.setMargin(24)

    def __getattr__(self, name: str) -> Any:
        if name == "snapshot":
            return lambda path, cb=None: cb and cb(False)
        return lambda *a, **k: None
