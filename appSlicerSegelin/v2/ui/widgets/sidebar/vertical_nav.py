"""Linear/VS Code-style vertical icon rail.

A narrow column of mutually-exclusive icon buttons. Clicking switches
the active panel via the ``activated(index)`` signal. The rail has a
56 px width and a left accent border on the checked tab.
"""
from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QFrame, QToolButton, QVBoxLayout, QWidget

from ...theming.icons import get_icon


@dataclass(slots=True)
class NavItem:
    icon: str
    label: str  # tooltip


class VerticalNav(QFrame):
    activated = pyqtSignal(int)

    NAV_WIDTH = 56
    ICON_SIZE = 20

    def __init__(self, items: list[NavItem], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("VerticalNav")
        self.setFixedWidth(self.NAV_WIDTH)
        self._buttons: list[QToolButton] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(2)

        for index, item in enumerate(items):
            btn = QToolButton(self)
            btn.setObjectName("NavTab")
            btn.setCheckable(True)
            btn.setIcon(get_icon(item.icon))
            btn.setIconSize(QSize(self.ICON_SIZE, self.ICON_SIZE))
            btn.setToolTip(item.label)
            btn.setFixedHeight(48)
            btn.setFixedWidth(self.NAV_WIDTH)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.toggled.connect(lambda checked, i=index: checked and self.activated.emit(i))
            self._group.addButton(btn, index)
            self._buttons.append(btn)
            layout.addWidget(btn)
        layout.addStretch(1)

        if self._buttons:
            self._buttons[0].setChecked(True)

    def set_active(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setChecked(True)

    def active_index(self) -> int:
        for i, b in enumerate(self._buttons):
            if b.isChecked():
                return i
        return 0
