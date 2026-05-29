"""Settings panel — theme, shortcuts hint, machine profile placeholder."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QLabel, QPushButton

from ....theming.icons import get_icon
from .base import PanelBase, ghost, tooltip


class SettingsPanel(PanelBase):
    TITLE = "Settings"
    CAPTION = "Appearance and reference."

    toggle_theme_requested = pyqtSignal()
    open_shortcuts_requested = pyqtSignal()

    def build(self) -> None:
        self.b_theme = QPushButton(get_icon("sun"), "  Toggle theme")
        self.b_theme.setToolTip(tooltip("Switch between light and dark", "Ctrl+T"))
        self.b_theme.clicked.connect(self.toggle_theme_requested.emit)
        self.add(self.b_theme)

        self.b_help = ghost(QPushButton(get_icon("command"), "  Keyboard shortcuts"))
        self.b_help.setToolTip(tooltip("Show every shortcut", "?"))
        self.b_help.clicked.connect(self.open_shortcuts_requested.emit)
        self.add(self.b_help)

        self.add_divider()

        # Machine profile read-out (display only for now; full editor planned).
        m = self.c.project.machine
        info = QLabel(
            f"Machine: {m.name}\nBed Y/Z: {m.bed_y:g} × {m.bed_z:g} mm\n"
            f"Feed cut: {m.feed_cut_mm_min:g} mm/min\nPrecision: {m.precision_decimals} decimals"
        )
        info.setProperty("role", "mono")
        self.add(info)
