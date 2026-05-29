"""Export panel — G-code, modified DXF, plate batch."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QLineEdit, QPushButton

from ....theming.icons import get_icon
from .base import PanelBase, primary, tooltip


class ExportPanel(PanelBase):
    TITLE = "Export"
    CAPTION = "Generate machine-ready files."

    export_gcode_requested = pyqtSignal()
    export_dxf_requested = pyqtSignal()
    export_batch_requested = pyqtSignal()

    def build(self) -> None:
        self.in_name = QLineEdit("cut")
        self.in_name.editingFinished.connect(self._on_name)
        self.add_field("Base filename for batches", self.in_name)

        self.add_divider()

        self.b_gcode = primary(QPushButton(get_icon("save", "#FFFFFF"), "  Generate G-code"))
        self.b_gcode.setToolTip(tooltip("Single G-code file", "Ctrl+E"))
        self.b_gcode.clicked.connect(self.export_gcode_requested.emit)
        self.add(self.b_gcode)

        self.b_batch = QPushButton(get_icon("save"), "  Export plates/parts batch")
        self.b_batch.setToolTip(
            "One G-code per layer or per manual-cut part. Generate the preview first."
        )
        self.b_batch.clicked.connect(self.export_batch_requested.emit)
        self.add(self.b_batch)

        self.b_dxf = QPushButton(get_icon("save"), "  Export modified DXF")
        self.b_dxf.setToolTip("Save the transformed geometry as a DXF file")
        self.b_dxf.clicked.connect(self.export_dxf_requested.emit)
        self.add(self.b_dxf)

        self.c.changed.connect(self._refresh_state)
        self.c.layers_changed.connect(self._refresh_state)
        self._refresh_state()

    def _on_name(self) -> None:
        self.c.project.batch_basename = self.in_name.text().strip() or "cut"

    def _refresh_state(self) -> None:
        has_geo = self.c.has_geometry
        for btn, hint in (
            (self.b_gcode, "Load a DXF first"),
            (self.b_dxf, "Load a DXF first"),
        ):
            btn.setEnabled(has_geo)
            btn.setToolTip(hint if not has_geo else btn.toolTip())
        self.b_batch.setEnabled(bool(self.c.layers))
        if not self.c.layers:
            self.b_batch.setToolTip("Generate a plate or manual-cut preview first")
