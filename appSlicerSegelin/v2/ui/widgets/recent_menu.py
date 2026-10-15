"""Recent files dropdown used in the toolbar."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QWidget

from ...io.recent_files import RecentFiles


class RecentMenu(QMenu):
    file_chosen = pyqtSignal(str)

    def __init__(self, recents: RecentFiles, parent: QWidget | None = None) -> None:
        super().__init__("Recent", parent)
        self._recents = recents
        self.refresh()

    def refresh(self) -> None:
        self.clear()
        items = self._recents.items
        if not items:
            empty = QAction("No recent files", self)
            empty.setEnabled(False)
            self.addAction(empty)
            return
        for path in items:
            display = f"{Path(path).name}    {Path(path).parent}"
            action = QAction(display, self)
            action.triggered.connect(lambda _checked, p=path: self.file_chosen.emit(p))
            self.addAction(action)
        self.addSeparator()
        clear = QAction("Clear recent", self)

        def _clear() -> None:
            self._recents.items = []
            self._recents._save()
            self.refresh()

        clear.triggered.connect(_clear)
        self.addAction(clear)
