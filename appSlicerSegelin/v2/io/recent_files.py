"""Most-recently-used file list, persisted as JSON.

Stored under the user's config dir so it survives across sessions
and bundled executables.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path as _Path

MAX_ITEMS = 10


@dataclass(slots=True)
class RecentFiles:
    path: _Path
    items: list[str] = field(default_factory=list)

    def load(self) -> RecentFiles:
        if self.path.exists():
            try:
                self.items = [p for p in json.loads(self.path.read_text(encoding="utf-8")) if isinstance(p, str)]
            except (OSError, json.JSONDecodeError):
                self.items = []
        return self

    def add(self, file_path: str | _Path) -> None:
        s = str(file_path)
        self.items = [s] + [i for i in self.items if i != s]
        self.items = self.items[:MAX_ITEMS]
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.items, indent=2), encoding="utf-8")
