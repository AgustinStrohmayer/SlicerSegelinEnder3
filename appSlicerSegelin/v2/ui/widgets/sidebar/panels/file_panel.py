"""File panel — DXF import + project archive open/save + recents.

All file-dialog operations are emitted as signals because the panel
itself should not own a QFileDialog (the main window owns I/O).
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QPushButton

from ....theming.icons import get_icon
from .base import PanelBase, num_input, primary, tooltip


class FilePanel(PanelBase):
    TITLE = "File"
    CAPTION = "Bring DXF geometry in or save/open a project archive."

    import_requested = pyqtSignal(bool, float)
    save_archive_requested = pyqtSignal()
    open_archive_requested = pyqtSignal()
    export_gcode_requested = pyqtSignal()

    def build(self) -> None:
        load = primary(QPushButton(get_icon("folder-open", "#FFFFFF"), "  Import DXF"))
        load.setProperty("size", "lg")
        load.setToolTip(tooltip("Import a DXF file", "Ctrl+O"))
        load.clicked.connect(self._emit_import)
        self.add(load)

        self.chk_units = QCheckBox("Auto-scale via DXF $INSUNITS")
        self.chk_units.setChecked(True)
        self.add(self.chk_units)

        self.in_scale = num_input("1.0", 90)
        self.add_field("Extra scale multiplier", self.in_scale)

        self.add_divider()

        save = QPushButton(get_icon("save"), "  Save project (.ssproj)")
        save.setToolTip(tooltip(
            "Bundle geometry, settings and original DXF into one shareable file",
            "Ctrl+S",
        ))
        save.clicked.connect(self.save_archive_requested.emit)
        self.add(save)

        op = QPushButton(get_icon("folder-open"), "  Open project (.ssproj)")
        op.setToolTip("Resume any saved session — even from a different machine")
        op.clicked.connect(self.open_archive_requested.emit)
        self.add(op)

        self.add_divider()

        gcode = primary(QPushButton(get_icon("save", "#FFFFFF"), "  Export G-code"))
        gcode.setToolTip(tooltip("Generate the G-code for the current geometry", "Ctrl+E"))
        gcode.clicked.connect(self.export_gcode_requested.emit)
        self.add(gcode)

    def _emit_import(self) -> None:
        try:
            scale = float(self.in_scale.text().replace(",", "."))
        except ValueError:
            scale = 1.0
        self.import_requested.emit(self.chk_units.isChecked(), scale)
