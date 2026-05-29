"""Sidebar shell: vertical icon nav + stacked panel."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QStackedWidget, QWidget

from ...controllers.project_controller import ProjectController
from .panels.cuts_panel import CutsPanel
from .panels.export_panel import ExportPanel
from .panels.file_panel import FilePanel
from .panels.plates_panel import PlatesPanel
from .panels.settings_panel import SettingsPanel
from .panels.transform_panel import TransformPanel
from .vertical_nav import NavItem, VerticalNav

PANEL_WIDTH = 320

_NAV_ITEMS = [
    NavItem("file", "File"),
    NavItem("wrench", "Transform"),
    NavItem("scissors", "Manual cuts"),
    NavItem("layers", "Plates & parts"),
    NavItem("download", "Export"),
    NavItem("settings", "Settings"),
]


class Sidebar(QFrame):
    # Bubbled-up dialogs the main window owns.
    import_requested = pyqtSignal(bool, float)
    save_archive_requested = pyqtSignal()
    open_archive_requested = pyqtSignal()
    export_gcode_requested = pyqtSignal()
    export_dxf_requested = pyqtSignal()
    export_batch_requested = pyqtSignal()
    diagonal_requested = pyqtSignal()
    toggle_theme_requested = pyqtSignal()
    open_shortcuts_requested = pyqtSignal()

    def __init__(self, controller: ProjectController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SidebarFrame")
        self.c = controller
        self.setFixedWidth(VerticalNav.NAV_WIDTH + PANEL_WIDTH)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.nav = VerticalNav(_NAV_ITEMS, self)
        outer.addWidget(self.nav)

        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack, 1)

        # Build panels.
        self.file_panel = FilePanel(controller, self)
        self.transform_panel = TransformPanel(controller, self)
        self.cuts_panel = CutsPanel(controller, self)
        self.plates_panel = PlatesPanel(controller, self)
        self.export_panel = ExportPanel(controller, self)
        self.settings_panel = SettingsPanel(controller, self)
        for p in (
            self.file_panel,
            self.transform_panel,
            self.cuts_panel,
            self.plates_panel,
            self.export_panel,
            self.settings_panel,
        ):
            self.stack.addWidget(p)

        self.nav.activated.connect(self.stack.setCurrentIndex)

        # Bubble panel signals up.
        self.file_panel.import_requested.connect(self.import_requested.emit)
        self.file_panel.save_archive_requested.connect(self.save_archive_requested.emit)
        self.file_panel.open_archive_requested.connect(self.open_archive_requested.emit)
        self.file_panel.export_gcode_requested.connect(self.export_gcode_requested.emit)
        self.cuts_panel.diagonal_requested.connect(self.diagonal_requested.emit)
        self.export_panel.export_gcode_requested.connect(self.export_gcode_requested.emit)
        self.export_panel.export_dxf_requested.connect(self.export_dxf_requested.emit)
        self.export_panel.export_batch_requested.connect(self.export_batch_requested.emit)
        self.settings_panel.toggle_theme_requested.connect(self.toggle_theme_requested.emit)
        self.settings_panel.open_shortcuts_requested.connect(self.open_shortcuts_requested.emit)

    def open_section(self, index: int) -> None:
        """Programmatically focus a panel (used by tab shortcuts)."""
        self.nav.set_active(index)
        self.stack.setCurrentIndex(index)

    def set_diagonal_status(self, text: str) -> None:
        self.cuts_panel.set_diagonal_status(text)

    def trigger_import_dialog(self) -> None:
        self.file_panel._emit_import()
