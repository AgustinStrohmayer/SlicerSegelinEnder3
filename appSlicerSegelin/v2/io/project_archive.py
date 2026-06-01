"""``.ssproj`` — proprietary project archive.

A single self-contained file that bundles **everything** needed to
resume a session on another machine: the project state, the original
source DXF, and an optional preview thumbnail. The container is a
plain ZIP, so it can be unzipped with any tool and is friendly to
git LFS or cloud sync.

Layout inside the archive::

  manifest.json          # schema version, app version, timestamps,
                         #   author, the names of payload entries
  project.json           # serialised Project (segments, transforms,
                         #   cuts, machine, view, etc.)
  source.dxf             # the original DXF file as imported (optional)
  thumbnail.png          # PNG preview of the canvas (optional)

The format is forward-tolerant: unknown manifest fields are ignored,
missing optional payloads simply produce a project without them.

Why a ZIP container instead of fattening ``project.json`` with a
base64 DXF blob? Because every other modern desktop document format
(``.docx``, ``.xlsx``, ``.blend``, ``.figma``) uses the same idea —
small structured metadata + binary payloads side-by-side. It scales,
is debuggable from the shell, and survives copy/paste between tools.
"""
from __future__ import annotations

import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import ProjectIOError
from ..core.project import SCHEMA_VERSION, Project
from . import project_io

ARCHIVE_EXTENSION = ".ssproj"
ARCHIVE_MAGIC = "SlicerSegelinProject"
ARCHIVE_FORMAT_VERSION = 1

_MANIFEST = "manifest.json"
_PROJECT = "project.json"
_DXF = "source.dxf"
_THUMB = "thumbnail.png"


@dataclass(slots=True)
class ArchiveContent:
    """What you get back from :func:`load_archive`."""

    project: Project
    source_dxf_bytes: bytes | None
    thumbnail_png: bytes | None
    manifest: dict


def save_archive(
    path: str | Path,
    project: Project,
    *,
    source_dxf_bytes: bytes | None = None,
    thumbnail_png: bytes | None = None,
    title: str | None = None,
    author: str | None = None,
) -> Path:
    """Write ``project`` (and optional DXF / thumbnail) to ``path``.

    The caller is expected to pass ``source_dxf_bytes`` whenever the
    project came from a DXF import — otherwise the archive is still
    valid but can no longer reproduce the *original* geometry exactly
    if the user later wants to re-flatten with different options.
    """
    out_path = Path(path)
    if out_path.suffix.lower() != ARCHIVE_EXTENSION:
        out_path = out_path.with_suffix(ARCHIVE_EXTENSION)

    project_json = project_io.serialize_to_json(project)

    manifest = {
        "magic": ARCHIVE_MAGIC,
        "format_version": ARCHIVE_FORMAT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "app": "SlicerSegelinEnder3",
        "created_at": _now_iso(),
        "title": title or out_path.stem,
        "author": author,
        "entries": {
            "project": _PROJECT,
            "source_dxf": _DXF if source_dxf_bytes else None,
            "thumbnail": _THUMB if thumbnail_png else None,
        },
    }

    try:
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(_MANIFEST, json.dumps(manifest, indent=2))
            zf.writestr(_PROJECT, project_json)
            if source_dxf_bytes:
                zf.writestr(_DXF, source_dxf_bytes)
            if thumbnail_png:
                zf.writestr(_THUMB, thumbnail_png)
    except OSError as exc:
        raise ProjectIOError(f"Cannot write project archive: {exc}") from exc

    return out_path


def load_archive(path: str | Path) -> ArchiveContent:
    """Read an ``.ssproj`` archive. Raises :class:`ProjectIOError` if
    the file is missing, not a ZIP, or has the wrong magic string."""
    in_path = Path(path)
    if not in_path.exists():
        raise ProjectIOError(f"Project archive not found: {in_path}")
    if not zipfile.is_zipfile(in_path):
        raise ProjectIOError(f"{in_path.name} is not a valid project archive.")

    try:
        with zipfile.ZipFile(in_path, "r") as zf:
            names = set(zf.namelist())
            if _MANIFEST not in names or _PROJECT not in names:
                raise ProjectIOError("Archive is missing required entries.")
            manifest = json.loads(zf.read(_MANIFEST).decode("utf-8"))
            if manifest.get("magic") != ARCHIVE_MAGIC:
                raise ProjectIOError(
                    "This file is not a SlicerSegelinEnder3 project archive."
                )
            if int(manifest.get("format_version", 0)) > ARCHIVE_FORMAT_VERSION:
                raise ProjectIOError(
                    f"Archive format {manifest.get('format_version')} is newer than this app supports "
                    f"({ARCHIVE_FORMAT_VERSION}). Update the app to open this project."
                )
            project = project_io.deserialize_from_json(zf.read(_PROJECT).decode("utf-8"))
            dxf_bytes = zf.read(_DXF) if _DXF in names else None
            thumb_bytes = zf.read(_THUMB) if _THUMB in names else None
    except zipfile.BadZipFile as exc:
        raise ProjectIOError(f"Corrupt project archive: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectIOError(f"Manifest is not valid JSON: {exc}") from exc

    return ArchiveContent(
        project=project,
        source_dxf_bytes=dxf_bytes,
        thumbnail_png=thumb_bytes,
        manifest=manifest,
    )


def quick_inspect(path: str | Path) -> dict | None:
    """Cheap peek at the manifest, used by recent-files thumbnails.

    Returns ``None`` if the file isn't a valid archive (so callers can
    silently skip stale entries)."""
    p = Path(path)
    if not p.exists() or not zipfile.is_zipfile(p):
        return None
    try:
        with zipfile.ZipFile(p, "r") as zf:
            if _MANIFEST not in zf.namelist():
                return None
            return json.loads(zf.read(_MANIFEST).decode("utf-8"))
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError):
        return None


def extract_thumbnail(path: str | Path) -> bytes | None:
    p = Path(path)
    if not p.exists() or not zipfile.is_zipfile(p):
        return None
    try:
        with zipfile.ZipFile(p, "r") as zf:
            if _THUMB in zf.namelist():
                return zf.read(_THUMB)
    except (zipfile.BadZipFile, OSError):
        pass
    return None


def render_thumbnail_png(scene, width: int = 320, height: int = 200) -> bytes | None:  # type: ignore[no-untyped-def]
    """Render the current canvas scene to a PNG, returning the bytes.

    Best-effort: returns ``None`` instead of crashing if Qt isn't able
    to paint the scene (e.g. in headless environments without a real
    paint device, or when the scene was destroyed mid-save).
    """
    try:
        from PyQt6.QtCore import QBuffer, QIODevice, QRectF, Qt
        from PyQt6.QtGui import QImage, QPainter
    except ImportError:
        return None
    if scene is None:
        return None
    try:
        rect = scene.itemsBoundingRect()
        if rect.isEmpty():
            return None
        img = QImage(width, height, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            margin = 0.05 * max(rect.width(), rect.height())
            rect.adjust(-margin, -margin, margin, margin)
            # Call the QGraphicsScene base render to avoid clashing with
            # SlicerScene.render_model.
            from PyQt6.QtWidgets import QGraphicsScene

            QGraphicsScene.render(scene, painter, QRectF(0, 0, width, height), rect, Qt.AspectRatioMode.KeepAspectRatio)
        finally:
            painter.end()
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.ReadWrite)
        img.save(buf, "PNG")
        return bytes(buf.data())
    except Exception:
        return None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
