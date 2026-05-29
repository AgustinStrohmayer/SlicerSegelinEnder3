"""Plates panel — usable area + plate split + part navigation."""
from __future__ import annotations

from PyQt6.QtWidgets import QCheckBox, QLabel, QPushButton

from ....theming.icons import get_icon
from .base import PanelBase, compact, num_input, primary


class PlatesPanel(PanelBase):
    TITLE = "Plates & parts"
    CAPTION = "Define the usable bed and split the cut into shippable pieces."

    def build(self) -> None:
        self.in_y = num_input("220")
        self.in_z = num_input("100")
        self.add_field_pair("Bed Y (mm)", self.in_y, "Bed Z (mm)", self.in_z)
        apply_btn = QPushButton("Apply bed size")
        apply_btn.clicked.connect(self._apply_area)
        self.add(apply_btn)

        self.add_divider()

        self.chk_split = QCheckBox("Auto-split if geometry exceeds the bed")
        self.chk_split.toggled.connect(self.c.set_split_plates)
        self.add(self.chk_split)

        self.add_divider()

        gen = primary(QPushButton(get_icon("settings", "#FFFFFF"), "  Generate preview"))
        gen.setToolTip("Compute parts using either plate split or manual cuts")
        gen.clicked.connect(self.c.generate_preview)
        self.add(gen)

        self.b_prev = compact(QPushButton(get_icon("chevron-left"), "  Prev"))
        self.b_prev.clicked.connect(lambda: self.c.move_layer(-1))
        self.b_next = compact(QPushButton(get_icon("chevron-right"), "  Next"))
        self.b_next.clicked.connect(lambda: self.c.move_layer(1))
        self.add_button_row(self.b_prev, self.b_next)

        self.b_full = QPushButton("Back to full view")
        self.b_full.clicked.connect(self.c.show_full_view)
        self.add(self.b_full)

        self.lbl = QLabel("No preview yet")
        self.lbl.setProperty("class", "muted")
        self.add(self.lbl)

        self.c.layers_changed.connect(self._refresh)
        self.c.changed.connect(self._refresh)
        self._refresh()

    def _apply_area(self) -> None:
        try:
            self.c.set_area(
                float(self.in_y.text().replace(",", ".")),
                float(self.in_z.text().replace(",", ".")),
            )
        except ValueError:
            self.c.notify.emit("Invalid value", "Enter numeric bed dimensions.", "warning")

    def _refresh(self) -> None:
        has = bool(self.c.layers)
        self.b_prev.setEnabled(has)
        self.b_next.setEnabled(has)
        self.b_full.setEnabled(has)
        if not has:
            self.lbl.setText("No preview yet — press Generate")
            return
        idx = self.c.focused_layer
        total = len(self.c.layers)
        if idx < 0:
            self.lbl.setText(f"{total} parts ready (full view)")
        else:
            layer = self.c.layers[idx]
            self.lbl.setText(f"Part {idx + 1}/{total} · {layer.label}")
