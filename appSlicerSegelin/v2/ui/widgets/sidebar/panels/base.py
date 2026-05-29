"""Base class for sidebar panels.

Each panel is a scrollable column with a consistent header (title +
muted caption) and helper methods to add labelled field groups and
section dividers. Keeps every panel visually aligned.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def with_role(widget: QWidget, role: str) -> QWidget:
    widget.setProperty("role", role)
    return widget


def primary(btn: QPushButton) -> QPushButton:
    btn.setProperty("role", "primary")
    return btn


def ghost(btn: QPushButton) -> QPushButton:
    btn.setProperty("role", "ghost")
    return btn


def danger(btn: QPushButton) -> QPushButton:
    btn.setProperty("role", "danger")
    return btn


def compact(btn: QPushButton) -> QPushButton:
    btn.setProperty("size", "compact")
    return btn


def field_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("FieldLabel")
    return lbl


def num_input(default: str = "", width: int | None = None) -> QLineEdit:
    e = QLineEdit(default)
    e.setValidator(QDoubleValidator())
    if width:
        e.setMaximumWidth(width)
    e.setAlignment(Qt.AlignmentFlag.AlignRight)
    return e


def divider() -> QFrame:
    f = QFrame()
    f.setObjectName("PanelDivider")
    return f


def tooltip(label: str, shortcut: str | None = None) -> str:
    return f"{label}  ({shortcut})" if shortcut else label


class PanelBase(QScrollArea):
    """Every sidebar panel inherits from this."""

    TITLE: str = ""
    CAPTION: str = ""

    def __init__(self, controller, parent: QWidget | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.c = controller
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        self.setWidget(container)
        self._root = QVBoxLayout(container)
        self._root.setContentsMargins(20, 20, 20, 24)
        self._root.setSpacing(18)

        title = QLabel(self.TITLE)
        title.setObjectName("PanelTitle")
        self._root.addWidget(title)
        if self.CAPTION:
            cap = QLabel(self.CAPTION)
            cap.setObjectName("PanelCaption")
            cap.setWordWrap(True)
            self._root.addWidget(cap)

        # Subclass populates here.
        self._body_layout = QVBoxLayout()
        self._body_layout.setContentsMargins(0, 8, 0, 0)
        self._body_layout.setSpacing(16)
        self._root.addLayout(self._body_layout)
        self._root.addStretch(1)

        self.build()

    # subclasses override.
    def build(self) -> None: ...

    # ── layout helpers ────────────────────────────────────────────────
    def add(self, widget: QWidget) -> None:
        self._body_layout.addWidget(widget)

    def add_layout(self, layout) -> None:  # type: ignore[no-untyped-def]
        self._body_layout.addLayout(layout)

    def add_field(self, label: str, widget: QWidget) -> None:
        """Label above input pattern."""
        wrap = QVBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(6)
        wrap.addWidget(field_label(label))
        wrap.addWidget(widget)
        self._body_layout.addLayout(wrap)

    def add_field_pair(self, l1: str, w1: QWidget, l2: str, w2: QWidget) -> None:
        cols = QHBoxLayout()
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(12)
        for label, w in ((l1, w1), (l2, w2)):
            col = QVBoxLayout()
            col.setSpacing(6)
            col.addWidget(field_label(label))
            col.addWidget(w)
            cols.addLayout(col)
        self._body_layout.addLayout(cols)

    def add_section_label(self, text: str) -> None:
        lbl = field_label(text)
        self._body_layout.addSpacing(4)
        self._body_layout.addWidget(lbl)

    def add_divider(self) -> None:
        self._body_layout.addWidget(divider())

    def add_button_row(self, *buttons: QPushButton) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for b in buttons:
            row.addWidget(b)
        self._body_layout.addLayout(row)
