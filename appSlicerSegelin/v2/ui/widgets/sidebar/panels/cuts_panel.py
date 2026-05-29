"""Manual cuts panel — Y/Z/diagonal cuts and the list of defined cuts."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QLabel, QListWidget, QMessageBox, QPushButton

from ....theming.icons import get_icon
from .base import PanelBase, compact, danger, num_input, primary


class CutsPanel(PanelBase):
    TITLE = "Manual cuts"
    CAPTION = "Split the profile into independent parts with Y, Z or diagonal cuts."

    diagonal_requested = pyqtSignal()

    def build(self) -> None:
        self.chk_use = QCheckBox("Use manual cuts when generating parts")
        self.chk_use.toggled.connect(self.c.set_use_manual_cuts)
        self.add(self.chk_use)

        self.chk_close = QCheckBox("Auto-close open contours")
        self.chk_close.setChecked(True)
        self.chk_close.toggled.connect(self.c.set_auto_close)
        self.add(self.chk_close)

        self.add_divider()

        self.in_y = num_input()
        self.add_field("Vertical cut at Y (mm)", self.in_y)
        add_y = primary(QPushButton(get_icon("scissors", "#FFFFFF"), "  Add Y cut"))
        add_y.clicked.connect(self._on_add_y)
        self.add(add_y)

        self.in_z = num_input()
        self.add_field("Horizontal cut at Z (mm)", self.in_z)
        add_z = primary(QPushButton(get_icon("scissors", "#FFFFFF"), "  Add Z cut"))
        add_z.clicked.connect(self._on_add_z)
        self.add(add_z)

        self.add_divider()

        diag = QPushButton("Diagonal cut (pick 2 points)")
        diag.setToolTip("Click two points on the canvas to define a diagonal cut")
        diag.clicked.connect(self.diagonal_requested.emit)
        self.add(diag)

        self.lbl_diag = QLabel("Idle")
        self.lbl_diag.setProperty("class", "muted")
        self.add(self.lbl_diag)

        self.add_divider()

        self.add_section_label("Defined cuts")
        self.list_cuts = QListWidget()
        self.list_cuts.setMinimumHeight(160)
        self.add(self.list_cuts)

        del_btn = compact(QPushButton("Delete selected"))
        del_btn.clicked.connect(self._on_del)
        clr_btn = compact(danger(QPushButton("Clear all")))
        clr_btn.clicked.connect(self._on_clear)
        self.add_button_row(del_btn, clr_btn)

        self.c.changed.connect(self._refresh)
        self.c.info_changed.connect(self._refresh)
        self._refresh()

    def _on_add_y(self) -> None:
        try:
            self.c.add_manual_y(float(self.in_y.text().replace(",", ".")))
            self.in_y.clear()
        except ValueError:
            self.c.notify.emit("Invalid value", "Enter a numeric Y.", "warning")

    def _on_add_z(self) -> None:
        try:
            self.c.add_manual_z(float(self.in_z.text().replace(",", ".")))
            self.in_z.clear()
        except ValueError:
            self.c.notify.emit("Invalid value", "Enter a numeric Z.", "warning")

    def _on_del(self) -> None:
        row = self.list_cuts.currentRow()
        if row >= 0:
            self.c.delete_manual_cut(row)

    def _on_clear(self) -> None:
        if not self.c.project.manual_cuts:
            return
        ok = QMessageBox.question(
            self,
            "Clear manual cuts?",
            "This will remove every manual cut from the project. Continue?",
        )
        if ok == QMessageBox.StandardButton.Yes:
            self.c.clear_manual_cuts()

    def _refresh(self) -> None:
        self.list_cuts.clear()
        for i, cut in enumerate(self.c.project.manual_cuts):
            self.list_cuts.addItem(cut.describe(i))

    def set_diagonal_status(self, text: str) -> None:
        self.lbl_diag.setText(text)
