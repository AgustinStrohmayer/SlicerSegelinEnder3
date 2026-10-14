"""Portable mode: when running from the packaged folder (e.g. a USB stick), keep every
setting and saved profile inside that folder instead of the Windows profile.

Portable when the app is frozen (PyInstaller) or ``SEGELIN_PORTABLE_DIR`` is set.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

DATA_DIRNAME = "datos"


def data_dir() -> Path | None:
    """Folder for settings/profiles in portable mode, else ``None``."""
    env = os.environ.get("SEGELIN_PORTABLE_DIR")
    if env:
        base = Path(env)
    elif getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent / DATA_DIRNAME
    else:
        return None
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:  # read-only medium: fall back to the user profile
        return None
    return base


def settings(app_name: str):  # type: ignore[no-untyped-def]
    """A ``QSettings`` for ``app_name``: an .ini in the portable folder, or the registry."""
    from PyQt6.QtCore import QSettings

    d = data_dir()
    if d is None:
        return QSettings("SlicerSegelin", app_name)
    return QSettings(str(d / f"{app_name}.ini"), QSettings.Format.IniFormat)
