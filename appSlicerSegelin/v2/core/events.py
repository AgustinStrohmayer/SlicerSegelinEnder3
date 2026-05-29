"""Tiny synchronous pub/sub bus.

Used to notify the UI layer of domain mutations without coupling
``core`` to Qt. Subscribers are weakly-referenced callables; they
receive a single payload dict.
"""
from __future__ import annotations

import weakref
from collections import defaultdict
from collections.abc import Callable
from typing import Any

Listener = Callable[[dict[str, Any]], None]


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, list[weakref.ref[Listener]]] = defaultdict(list)

    def subscribe(self, event: str, listener: Listener) -> None:
        self._listeners[event].append(weakref.ref(listener))

    def emit(self, event: str, payload: dict[str, Any] | None = None) -> None:
        data = payload or {}
        alive: list[weakref.ref[Listener]] = []
        for ref in self._listeners.get(event, ()):
            cb = ref()
            if cb is None:
                continue
            alive.append(ref)
            cb(data)
        self._listeners[event] = alive
