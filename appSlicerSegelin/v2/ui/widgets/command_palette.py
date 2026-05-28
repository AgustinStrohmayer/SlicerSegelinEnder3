"""Ctrl+K command palette.

Single registry of commands (label + callable + optional shortcut).
Menu items, toolbar actions and the palette all read from the same
registry, so a new feature is added once and discoverable everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass(slots=True)
class CommandEntry:
    id: str
    label: str
    callback: Callable[[], None]
    shortcut: str | None = None
    section: str = "Commands"


class CommandRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, CommandEntry] = {}

    def register(self, entry: CommandEntry) -> None:
        self._entries[entry.id] = entry

    def all(self) -> Iterable[CommandEntry]:
        return self._entries.values()

    def filter(self, query: str) -> list[CommandEntry]:
        if not query.strip():
            return list(self._entries.values())
        q = query.lower()
        scored: list[tuple[int, CommandEntry]] = []
        for e in self._entries.values():
            label = e.label.lower()
            score = _fuzzy_score(label, q)
            if score >= 0:
                scored.append((score, e))
        scored.sort(key=lambda t: (-t[0], t[1].label))
        return [e for _, e in scored]


def _fuzzy_score(haystack: str, needle: str) -> int:
    """Tiny subsequence-match scorer: higher is better, -1 means no match."""
    i = 0
    score = 0
    last_match = -2
    for ch in haystack:
        if i >= len(needle):
            break
        if ch == needle[i]:
            score += 2 if last_match == -2 or last_match == -1 else 5
            last_match = score
            i += 1
        else:
            last_match = -1
    if i < len(needle):
        return -1
    return score - (len(haystack) - len(needle))


class CommandPalette(QFrame):
    def __init__(self, parent: QWidget, registry: CommandRegistry) -> None:
        super().__init__(parent)
        self.setObjectName("CommandPalette")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._registry = registry

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._input = QLineEdit(self)
        self._input.setPlaceholderText("Type a command…")
        layout.addWidget(self._input)

        self._list = QListWidget(self)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._list)

        self._input.textChanged.connect(self._refresh)
        self._input.returnPressed.connect(self._activate_current)
        self._list.itemActivated.connect(lambda _it: self._activate_current())

        self.hide()
        self.setFixedWidth(520)

        QShortcut(QKeySequence("Esc"), self).activated.connect(self.hide)

    def _refresh(self) -> None:
        self._list.clear()
        for e in self._registry.filter(self._input.text()):
            item = QListWidgetItem(e.label + (f"    {e.shortcut}" if e.shortcut else ""))
            item.setData(Qt.ItemDataRole.UserRole, e.id)
            self._list.addItem(item)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _activate_current(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        entry = next((e for e in self._registry.all() if e.id == entry_id), None)
        self.hide()
        if entry is not None:
            entry.callback()

    def open(self) -> None:
        self._input.clear()
        self._refresh()
        parent = self.parent()
        if parent is not None:
            geo = parent.rect()  # type: ignore[union-attr]
            self.move(geo.center().x() - self.width() // 2, geo.top() + 80)
        self.show()
        self.raise_()
        self._input.setFocus()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() in (Qt.Key.Key_Down,):
            row = min(self._list.currentRow() + 1, self._list.count() - 1)
            self._list.setCurrentRow(row)
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Up,):
            row = max(self._list.currentRow() - 1, 0)
            self._list.setCurrentRow(row)
            event.accept()
            return
        super().keyPressEvent(event)
