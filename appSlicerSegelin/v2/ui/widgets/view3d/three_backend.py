"""three.js renderer: a QWebEngineView showing ``web/index.html``, fed with batched JSON commands.

The page is served from the package through an ``app:`` URL scheme (ES modules
don't load from ``file://``) and runs in an off-the-record profile, so nothing
is written to the user's profile folder — the app stays portable.
"""
from __future__ import annotations

import base64
import json
import mimetypes
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QTimer, QUrl
from PyQt6.QtWidgets import QApplication

WEB = Path(__file__).with_name("web")
SCHEME = b"segelin3d"
READY_TIMEOUT_MS = 15000

_profile = None
_handler = None


def register_scheme() -> None:
    """Must run before the QApplication exists (Qt requirement for custom schemes)."""
    from PyQt6.QtWebEngineCore import QWebEngineUrlScheme
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401  (sets up GL context sharing)

    if bytes(QWebEngineUrlScheme.schemeByName(SCHEME).name()) == SCHEME:
        return
    s = QWebEngineUrlScheme(SCHEME)
    s.setFlags(QWebEngineUrlScheme.Flag.SecureScheme | QWebEngineUrlScheme.Flag.LocalAccessAllowed
               | QWebEngineUrlScheme.Flag.CorsEnabled)
    QWebEngineUrlScheme.registerScheme(s)


def _shared_profile():  # type: ignore[no-untyped-def]
    global _profile, _handler
    if _profile is None:
        from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineUrlRequestJob, QWebEngineUrlSchemeHandler

        class Handler(QWebEngineUrlSchemeHandler):
            def requestStarted(self, job: QWebEngineUrlRequestJob) -> None:
                root = WEB.resolve()
                p = (root / job.requestUrl().path().lstrip("/")).resolve()
                if not p.is_file() or root not in p.parents:
                    job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                    return
                mime = "text/javascript" if p.suffix == ".js" else (mimetypes.guess_type(p.name)[0] or "text/plain")
                buf = QBuffer(parent=job)
                buf.setData(QByteArray(p.read_bytes()))
                buf.open(QIODevice.OpenModeFlag.ReadOnly)
                job.reply(mime.encode(), buf)

        app = QApplication.instance()
        _profile = QWebEngineProfile(app)  # no storage name: off the record
        _handler = Handler(app)
        _profile.installUrlSchemeHandler(SCHEME, _handler)
    return _profile


def _b64(a: np.ndarray | None) -> str | None:
    return None if a is None else base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


class ThreeBackend:
    def __init__(self, owner: Any, on_fail: Callable[[str], None]) -> None:
        from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineUrlScheme
        from PyQt6.QtWebEngineWidgets import QWebEngineView

        if bytes(QWebEngineUrlScheme.schemeByName(SCHEME).name()) != SCHEME:
            raise RuntimeError("three.js renderer not prepared (call view3d.prepare_app() before QApplication)")
        if not QApplication.arguments():  # Chromium aborts the whole process without an argv[0]
            raise RuntimeError("QApplication was created without arguments")
        self._on_fail = on_fail
        self._ready = False
        self._dead = False
        self._queue: list[tuple[str, dict[str, Any]]] = []
        self._coalesce: dict[tuple[str, str], int] = {}
        self.widget = QWebEngineView(owner)
        self.page = QWebEnginePage(_shared_profile(), self.widget)
        self.widget.setPage(self.page)
        self.widget.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)  # right-drag pans
        self.page.setBackgroundColor(owner.palette().window().color())
        self.page.titleChanged.connect(self._title)
        self.page.renderProcessTerminated.connect(lambda *_: self._fail("the 3D page stopped"))
        self.page.load(QUrl(f"{SCHEME.decode()}:///index.html"))
        self._timer = QTimer(self.widget)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._fail("WebGL did not start in time"))
        self._timer.start(READY_TIMEOUT_MS)
        self._flush_timer = QTimer(self.widget)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(0)
        self._flush_timer.timeout.connect(self._flush)

    # ── page life ─────────────────────────────────────────────────────
    def _title(self, t: str) -> None:
        if t == "ready" and not self._ready:
            self._ready = True
            self._timer.stop()
            self._flush()
        elif t.startswith("fail:"):
            self._fail(t[5:] or "WebGL unavailable")

    def _fail(self, reason: str) -> None:
        if self._dead:
            return
        self._dead = True
        self._timer.stop()
        QTimer.singleShot(0, lambda: self._on_fail(reason))

    def _send(self, op: str, args: dict[str, Any], key: str | None = None) -> None:
        if self._dead:
            return
        if key is not None:
            k = (op, key)
            i = self._coalesce.get(k)
            if i is not None and i < len(self._queue):
                self._queue[i] = (op, args)  # only the latest position matters
                return
            self._coalesce[k] = len(self._queue)
        self._queue.append((op, args))
        if self._ready and not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush(self) -> None:
        if not self._queue or self._dead:
            return
        batch, self._queue, self._coalesce = self._queue, [], {}
        self.page.runJavaScript(f"window.S && S.run({json.dumps(batch, separators=(',', ':'))})")

    # ── scene protocol ────────────────────────────────────────────────
    def theme(self, t: dict[str, Any]) -> None:
        self._send("theme", t)

    def mesh(self, oid: str, *, verts, faces, color, opacity, group, edges, shadow, flat, emissive, roughness,
             metalness) -> None:  # type: ignore[no-untyped-def]
        self._send("mesh", {"id": oid, "group": group, "pos": _b64(verts), "idx": _b64(faces), "color": color,
                            "opacity": opacity, "edges": edges, "shadow": shadow, "flat": flat,
                            "emissive": emissive, "roughness": roughness, "metalness": metalness})

    def lines(self, oid: str, *, pts, color, width, mode, group, opacity, colors) -> None:  # type: ignore[no-untyped-def]
        self._send("lines", {"id": oid, "group": group, "pos": _b64(pts), "color": color, "width": width,
                             "mode": mode, "opacity": opacity, "colors": _b64(colors)})

    def points(self, oid: str, *, pts, colors, color, opacity, size, group) -> None:  # type: ignore[no-untyped-def]
        self._send("points", {"id": oid, "group": group, "pos": _b64(pts), "colors": _b64(colors), "color": color,
                              "opacity": opacity, "size": size})

    def progress(self, oid: str, n: int, head) -> None:  # type: ignore[no-untyped-def]
        self._send("progress", {"id": oid, "n": n, "head": head}, key=oid)

    def color(self, oid: str, color, opacity) -> None:  # type: ignore[no-untyped-def]
        a: dict[str, Any] = {"id": oid}
        if color is not None:
            a["color"] = color
        if opacity is not None:
            a["opacity"] = opacity
        self._send("color", a, key=oid)

    def visible(self, oid: str, on: bool) -> None:
        self._send("visible", {"id": oid, "on": on}, key=oid)

    def offset(self, group: str, xyz) -> None:  # type: ignore[no-untyped-def]
        self._send("offset", {"group": group, "xyz": list(xyz)}, key=group)

    def remove(self, oid: str) -> None:
        self._send("remove", {"id": oid})

    def clear(self, group: str | None) -> None:
        self._send("clear", {} if group is None else {"group": group})

    def camera(self, *, center, distance, elevation, azimuth, animate) -> None:  # type: ignore[no-untyped-def]
        self._send("camera", {"center": list(center), "distance": distance, "elevation": elevation,
                              "azimuth": azimuth, "animate": animate}, key="view")

    def fit(self, *, elevation, azimuth, animate) -> None:  # type: ignore[no-untyped-def]
        a: dict[str, Any] = {"animate": animate}
        if elevation is not None:
            a.update(elevation=elevation, azimuth=azimuth if azimuth is not None else -60.0)
        self._send("fit", a, key="view")

    def snapshot(self, path: str, callback=None) -> None:  # type: ignore[no-untyped-def]
        def got(url: Any) -> None:
            ok = isinstance(url, str) and url.startswith("data:image/png;base64,")
            if ok:
                Path(path).write_bytes(base64.b64decode(url.split(",", 1)[1]))
            if callback:
                callback(ok)

        self._flush()
        self.page.runJavaScript("window.S ? S.snapshot() : null", got)
