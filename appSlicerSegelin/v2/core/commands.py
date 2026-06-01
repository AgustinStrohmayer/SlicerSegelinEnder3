"""Command pattern for undo/redo.

Each user action becomes a ``Command`` with ``do`` / ``undo``
callables capturing the minimal delta — we don't snapshot the whole
project, which would balloon memory on big DXFs (think 50k segments).

``CompositeCommand`` groups multi-step actions (e.g. "rotate then
align to origin") so a single Ctrl+Z reverses the whole macro.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


class Command(Protocol):
    label: str

    def do(self) -> None: ...
    def undo(self) -> None: ...


@dataclass(slots=True)
class FunctionCommand:
    label: str
    do_fn: Callable[[], None]
    undo_fn: Callable[[], None]

    def do(self) -> None:
        self.do_fn()

    def undo(self) -> None:
        self.undo_fn()


@dataclass(slots=True)
class CompositeCommand:
    label: str
    children: list[Command]

    def do(self) -> None:
        for c in self.children:
            c.do()

    def undo(self) -> None:
        for c in reversed(self.children):
            c.undo()


@dataclass(slots=True)
class CommandStack:
    """Bounded undo/redo stack.

    Pushing a new command after some undos clears the redo branch,
    matching the standard editor model.
    """

    max_depth: int = 200
    _undo: list[Command] = field(default_factory=list)
    _redo: list[Command] = field(default_factory=list)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def push(self, command: Command, *, execute: bool = True) -> None:
        if execute:
            command.do()
        self._undo.append(command)
        self._redo.clear()
        if len(self._undo) > self.max_depth:
            self._undo.pop(0)

    def undo(self) -> Command | None:
        if not self._undo:
            return None
        cmd = self._undo.pop()
        cmd.undo()
        self._redo.append(cmd)
        return cmd

    def redo(self) -> Command | None:
        if not self._redo:
            return None
        cmd = self._redo.pop()
        cmd.do()
        self._undo.append(cmd)
        return cmd

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
