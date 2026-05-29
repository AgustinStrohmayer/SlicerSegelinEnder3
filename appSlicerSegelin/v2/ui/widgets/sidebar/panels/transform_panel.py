"""Transform panel — rotate, mirror, translate, reverse, align + speed."""
from __future__ import annotations

from PyQt6.QtWidgets import QPushButton

from ....theming.icons import get_icon
from .base import PanelBase, compact, ghost, num_input


class TransformPanel(PanelBase):
    TITLE = "Transform"
    CAPTION = "Orient and place the geometry on the bed."

    def build(self) -> None:
        # Quick coarse transforms.
        self.add_section_label("Coarse")
        rot = QPushButton(get_icon("rotate-cw"), "  Rotate 90°")
        rot.clicked.connect(lambda: self.c.rotate(90))
        rot.setToolTip("Rotate the profile 90° clockwise")
        auto = QPushButton(get_icon("settings"), "  Auto height")
        auto.setToolTip("Find the rotation that minimises Z height")
        auto.clicked.connect(self.c.auto_height)
        self.add_button_row(rot, auto)

        mv = QPushButton(get_icon("flip-horizontal"), "  Mirror V")
        mv.setToolTip("Mirror across the vertical mid-line")
        mv.clicked.connect(self.c.mirror_vertical)
        mh = QPushButton(get_icon("flip-vertical"), "  Mirror H")
        mh.setToolTip("Mirror across the horizontal mid-line")
        mh.clicked.connect(self.c.mirror_horizontal)
        self.add_button_row(mv, mh)

        self.add_divider()

        # Fine rotation.
        self.add_section_label("Fine rotation")
        self.in_deg = num_input("0.1")
        self.add_field("Angle (°)", self.in_deg)
        ccw = compact(QPushButton(get_icon("rotate-ccw"), "  CCW"))
        ccw.clicked.connect(lambda: self.c.rotate_fine(-self._deg()))
        cw = compact(QPushButton(get_icon("rotate-cw"), "  CW"))
        cw.clicked.connect(lambda: self.c.rotate_fine(self._deg()))
        self.add_button_row(ccw, cw)

        self.add_divider()

        # Fine translation.
        self.add_section_label("Translate")
        self.in_step = num_input("0.1")
        self.add_field("Step (mm)", self.in_step)
        ym = compact(QPushButton("Y −"))
        ym.clicked.connect(lambda: self.c.translate("y", -self._step()))
        yp = compact(QPushButton("Y +"))
        yp.clicked.connect(lambda: self.c.translate("y", self._step()))
        zm = compact(QPushButton("Z −"))
        zm.clicked.connect(lambda: self.c.translate("z", -self._step()))
        zp = compact(QPushButton("Z +"))
        zp.clicked.connect(lambda: self.c.translate("z", self._step()))
        self.add_button_row(ym, yp, zm, zp)

        self.add_divider()

        # Cut behaviour.
        self.add_section_label("Cut")
        self.b_reverse = ghost(QPushButton("Reverse cut direction"))
        self.b_reverse.setCheckable(True)
        self.b_reverse.setToolTip("Walk the cut path backwards")
        self.b_reverse.clicked.connect(self._on_reverse)
        self.add(self.b_reverse)

        align = QPushButton("Align origin to cut")
        align.setToolTip("Translate so the cut's entry point sits at machine (0,0)")
        align.clicked.connect(self.c.align_origin)
        self.add(align)

        self.in_speed = num_input("10")
        self.in_speed.editingFinished.connect(self._on_speed)
        self.add_field("Work speed (mm/s)", self.in_speed)

    def _deg(self) -> float:
        try:
            return float(self.in_deg.text().replace(",", "."))
        except ValueError:
            return 0.0

    def _step(self) -> float:
        try:
            return float(self.in_step.text().replace(",", "."))
        except ValueError:
            return 0.0

    def _on_reverse(self) -> None:
        self.c.toggle_reverse()
        self.b_reverse.setText(
            "✓ Reversing cut path" if self.c.project.reverse_cut else "Reverse cut direction"
        )

    def _on_speed(self) -> None:
        try:
            self.c.set_speed(float(self.in_speed.text().replace(",", ".")))
        except ValueError:
            pass
