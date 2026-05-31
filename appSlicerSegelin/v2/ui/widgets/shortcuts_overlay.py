"""Modal-style keyboard shortcuts overlay.

Triggered by ``?``. Reads from :class:`CommandRegistry` and lays the
commands out in a clean two-column grid grouped by section. Esc or a
backdrop click closes it.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..animations import fade_in, fade_out
from .command_palette import CommandRegistry


class ShortcutsOverlay(QWidget):
    def __init__(self, registry: CommandRegistry, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("OverlayBackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._registry = registry
        self.hide()

        wrap = QVBoxLayout(self)
        wrap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrap.setContentsMargins(40, 40, 40, 40)

        self._card = QFrame(self)
        self._card.setObjectName("ShortcutsOverlay")
        self._card.setMaximumWidth(720)
        wrap.addWidget(self._card, alignment=Qt.AlignmentFlag.AlignCenter)

        col = QVBoxLayout(self._card)
        col.setContentsMargins(28, 24, 28, 28)
        col.setSpacing(14)

        header = QHBoxLayout()
        title = QLabel("Keyboard shortcuts")
        title.setProperty("role", "title")
        header.addWidget(title)
        header.addStretch(1)
        esc = QLabel("ESC")
        esc.setProperty("role", "kbd")
        header.addWidget(esc)
        col.addLayout(header)

        scroll = QScrollArea(self._card)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        scroll.setWidget(inner)
        self._grid_layout = QVBoxLayout(inner)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(16)
        col.addWidget(scroll, 1)

        self._build_contents()

    # ── content ──────────────────────────────────────────────────────
    def _build_contents(self) -> None:
        groups: dict[str, list] = {}
        for entry in self._registry.all():
            section = entry.label.split(":", 1)[0] if ":" in entry.label else "General"
            groups.setdefault(section, []).append(entry)

        for section, entries in sorted(groups.items()):
            header = QLabel(section)
            header.setObjectName("FieldLabel")
            self._grid_layout.addWidget(header)

            grid = QGridLayout()
            grid.setHorizontalSpacing(20)
            grid.setVerticalSpacing(8)
            for row, entry in enumerate(entries):
                clean = entry.label.split(": ", 1)[-1]
                lbl = QLabel(clean)
                lbl.setProperty("role", "body")
                grid.addWidget(lbl, row, 0)
                if entry.shortcut:
                    kbd = QLabel(entry.shortcut)
                    kbd.setProperty("role", "kbd")
                    kbd.setAlignment(Qt.AlignmentFlag.AlignRight)
                    grid.addWidget(kbd, row, 1)
            grid.setColumnStretch(0, 1)
            self._grid_layout.addLayout(grid)
        self._grid_layout.addStretch(1)

    # ── show/hide ─────────────────────────────────────────────────────
    def show_overlay(self) -> None:
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())  # type: ignore[union-attr]
        self.raise_()
        fade_in(self, ms=160)

    def hide_overlay(self) -> None:
        fade_out(self, ms=140)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.hide_overlay()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        # Close on backdrop click; not when clicking inside the card.
        if not self._card.geometry().contains(event.position().toPoint()):
            self.hide_overlay()
            event.accept()
            return
        super().mousePressEvent(event)
