"""Persistent settings backed by ``QSettings``.

A thin wrapper so ``core`` can stay UI-agnostic — the rest of v2
only sees the ``Settings`` protocol below. A JSON-file fallback is
provided for headless tests.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path as _Path
from typing import Any, Protocol


class Settings(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any) -> None: ...
    def all(self) -> dict[str, Any]: ...


@dataclass(slots=True)
class JsonSettings:
    """Headless backend; used in tests and as a fallback when Qt is unavailable."""

    path: _Path
    _data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def all(self) -> dict[str, Any]:
        return dict(self._data)


def qsettings_backed() -> Settings:
    """Return a ``QSettings``-backed implementation. Imports Qt lazily."""
    from PyQt6.QtCore import QSettings

    class _Qt:
        def __init__(self) -> None:
            self._s = QSettings("SlicerSegelin", "Ender3")

        def get(self, key: str, default: Any = None) -> Any:
            return self._s.value(key, default)

        def set(self, key: str, value: Any) -> None:
            self._s.setValue(key, value)

        def all(self) -> dict[str, Any]:
            return {k: self._s.value(k) for k in self._s.allKeys()}

    return _Qt()
