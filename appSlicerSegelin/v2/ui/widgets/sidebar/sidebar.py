"""The full left sidebar — every legacy control, grouped and themed.

Buttons call the :class:`ProjectController` directly for pure-state
operations; anything that needs a file dialog or the simulation timer
is emitted as a signal for the main window to handle.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...controllers.project_controller import ProjectController
from ...theming.icons import get_icon, set_icon
from ..collapsible import CollapsibleSection


def _primary(btn: QPushButton) -> QPushButton:
    btn.setProperty("role", "primary")
    return btn


def _icon_btn(name: str, label: str) -> QPushButton:
    """Outline button whose icon recolours with the theme.

    The colour passed here is a placeholder; ``MainWindow._recolor_icons``
    re-tints every ``_icon_name``-tagged button on load and theme change.
    """
    btn = QPushButton(label)
    set_icon(btn, name, "#969FB2")
    return btn


def _row(*widgets: QWidget) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for w in widgets:
        lay.addWidget(w)
    return lay


def _num_input(default: str, width: int = 70) -> QLineEdit:
    e = QLineEdit(default)
    e.setValidator(QDoubleValidator())
    e.setMaximumWidth(width)
    e.setAlignment(Qt.AlignmentFlag.AlignRight)
    return e


class Sidebar(QScrollArea):
    import_requested = pyqtSignal(bool, float)
    export_gcode_requested = pyqtSignal()
    export_dxf_requested = pyqtSignal()
    export_batch_requested = pyqtSignal()
    export_part_requested = pyqtSignal(int)
    diagonal_requested = pyqtSignal()

    def __init__(self, controller: ProjectController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.c = controller
        self._current_part = -1
        self.setObjectName("Sidebar")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        container.setObjectName("SidebarBody")
        self.setWidget(container)
        root = QVBoxLayout(container)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        root.addWidget(self._section_file())
        root.addWidget(self._section_shape())
        root.addWidget(self._section_cut())
        root.addWidget(self._section_area())
        root.addWidget(self._section_manual())
        root.addWidget(self._section_part())
        root.addWidget(self._section_layers())
        root.addWidget(self._section_export())
        root.addStretch(1)

        self.c.layers_changed.connect(self._refresh_layer_state)
        self.c.changed.connect(self._refresh_manual_list)
        self.c.info_changed.connect(self._refresh_manual_list)
        self._refresh_layer_state()
        self._refresh_manual_list()
        self.update_part_panel()

    # ── 1. File ───────────────────────────────────────────────────────
    def _section_file(self) -> CollapsibleSection:
        s = CollapsibleSection("1 · Load DXF")
        load = _primary(QPushButton(get_icon("folder-open", "#FFFFFF"), "  Load DXF"))
        load.setToolTip("Import a DXF outline to cut (Ctrl+O)")
        load.clicked.connect(self._on_import)
        s.add(load)
        self.chk_units = QCheckBox("Use INSUNITS auto-scale")
        self.chk_units.setToolTip("Scale the drawing using the DXF's own units header")
        self.chk_units.setChecked(True)
        s.add(self.chk_units)
        self.in_scale = _num_input("1.0")
        self.in_scale.setToolTip("Extra scale multiplier applied on top of unit auto-scaling")
        s.add_layout(_row(QLabel("DXF scale ×"), self.in_scale))
        return s

    def _on_import(self) -> None:
        try:
            scale = float(self.in_scale.text().replace(",", "."))
        except ValueError:
            scale = 1.0
        self.import_requested.emit(self.chk_units.isChecked(), scale)

    # ── 2. Adjust shape ───────────────────────────────────────────────
    def _section_shape(self) -> CollapsibleSection:
        s = CollapsibleSection("2 · Adjust shape")
        b_rot = _icon_btn("rotate-cw", "  Rotate 90°")
        b_rot.setToolTip("Rotate the profile 90° clockwise")
        b_rot.clicked.connect(lambda: self.c.rotate(90))
        b_auto = QPushButton("Auto height")
        b_auto.setToolTip("Rotate so the profile's longest span is horizontal")
        b_auto.clicked.connect(self.c.auto_height)
        s.add_layout(_row(b_rot, b_auto))

        b_mv = _icon_btn("flip-horizontal", "  Mirror V")
        b_mv.setToolTip("Mirror across the vertical axis")
        b_mv.clicked.connect(self.c.mirror_vertical)
        b_mh = _icon_btn("flip-vertical", "  Mirror H")
        b_mh.setToolTip("Mirror across the horizontal axis")
        b_mh.clicked.connect(self.c.mirror_horizontal)
        s.add_layout(_row(b_mv, b_mh))

        self.in_deg = _num_input("0.1", 60)
        self.in_deg.setToolTip("Fine rotation step in degrees")
        b_ccw = _icon_btn("rotate-ccw", "")
        b_ccw.setToolTip("Rotate counter-clockwise by the fine step")
        b_ccw.clicked.connect(lambda: self.c.rotate_fine(-self._deg()))
        b_cw = _icon_btn("rotate-cw", "")
        b_cw.setToolTip("Rotate clockwise by the fine step")
        b_cw.clicked.connect(lambda: self.c.rotate_fine(self._deg()))
        s.add_layout(_row(QLabel("Fine °"), self.in_deg, b_ccw, b_cw))

        self.in_step = _num_input("0.1", 60)
        self.in_step.setToolTip("Translation step in millimetres for the Y/Z nudge buttons")
        s.add_layout(_row(QLabel("Y/Z step mm"), self.in_step))
        b_ym = QPushButton("Y −")
        b_ym.setToolTip("Move the profile left by the Y/Z step")
        b_ym.clicked.connect(lambda: self.c.translate("y", -self._step()))
        b_yp = QPushButton("Y +")
        b_yp.setToolTip("Move the profile right by the Y/Z step")
        b_yp.clicked.connect(lambda: self.c.translate("y", self._step()))
        b_zm = QPushButton("Z −")
        b_zm.setToolTip("Move the profile down by the Y/Z step")
        b_zm.clicked.connect(lambda: self.c.translate("z", -self._step()))
        b_zp = QPushButton("Z +")
        b_zp.setToolTip("Move the profile up by the Y/Z step")
        b_zp.clicked.connect(lambda: self.c.translate("z", self._step()))
        s.add_layout(_row(b_ym, b_yp, b_zm, b_zp))

        self.b_reverse = QPushButton("Reverse cut direction")
        self.b_reverse.setToolTip("Flip the order in which the wire traverses the path")
        self.b_reverse.setCheckable(True)
        self.b_reverse.clicked.connect(self._on_reverse)
        s.add(self.b_reverse)
        b_align = QPushButton("Align origin to cut")
        b_align.setToolTip("Shift the profile so cutting starts at the machine origin")
        b_align.clicked.connect(self.c.align_origin)
        s.add(b_align)
        return s

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
            "Reverse cut direction (ON)" if self.c.project.reverse_cut else "Reverse cut direction"
        )

    # ── 3. Cut params ─────────────────────────────────────────────────
    def _section_cut(self) -> CollapsibleSection:
        s = CollapsibleSection("3 · Cut speed")
        self.in_speed = _num_input("10", 70)
        self.in_speed.setToolTip("Wire feed speed during cutting, in mm/s")
        self.in_speed.editingFinished.connect(self._on_speed)
        s.add_layout(_row(QLabel("Work speed mm/s"), self.in_speed))
        return s

    def _on_speed(self) -> None:
        try:
            self.c.set_speed(float(self.in_speed.text().replace(",", ".")))
        except ValueError:
            pass

    # ── 4. Usable area / plates ───────────────────────────────────────
    def _section_area(self) -> CollapsibleSection:
        s = CollapsibleSection("4 · Plate / usable area")
        self.in_area_y = _num_input("220", 60)
        self.in_area_y.setToolTip("Usable bed width (Y) in mm")
        self.in_area_z = _num_input("100", 60)
        self.in_area_z.setToolTip("Usable bed height (Z) in mm")
        b_apply = QPushButton("Apply")
        b_apply.setToolTip("Apply the usable-area dimensions")
        b_apply.clicked.connect(self._on_area)
        s.add_layout(_row(QLabel("Y"), self.in_area_y, QLabel("Z"), self.in_area_z, b_apply))

        self.chk_split = QCheckBox("Split into plates if area exceeded")
        self.chk_split.setToolTip("Tile the profile into plate-sized pieces when it doesn't fit")
        self.chk_split.toggled.connect(self.c.set_split_plates)
        s.add(self.chk_split)
        self.chk_manual = QCheckBox("Use manual cuts")
        self.chk_manual.setToolTip("Honour the manual Y/Z/diagonal cut lines below")
        self.chk_manual.toggled.connect(self.c.set_use_manual_cuts)
        s.add(self.chk_manual)
        self.chk_close = QCheckBox("Close contours in manual cuts")
        self.chk_close.setToolTip("Automatically close open contours produced by manual cuts")
        self.chk_close.setChecked(True)
        self.chk_close.toggled.connect(self.c.set_auto_close)
        s.add(self.chk_close)
        return s

    def _on_area(self) -> None:
        try:
            self.c.set_area(
                float(self.in_area_y.text().replace(",", ".")),
                float(self.in_area_z.text().replace(",", ".")),
            )
        except ValueError:
            pass

    # ── 5. Manual cuts ────────────────────────────────────────────────
    def _section_manual(self) -> CollapsibleSection:
        s = CollapsibleSection("5 · Manual cuts", expanded=False)
        self.in_cut_y = _num_input("", 70)
        b_y = QPushButton("+Y")
        b_y.clicked.connect(self._on_add_y)
        s.add_layout(_row(QLabel("Y"), self.in_cut_y, b_y))
        self.in_cut_z = _num_input("", 70)
        b_z = QPushButton("+Z")
        b_z.clicked.connect(self._on_add_z)
        s.add_layout(_row(QLabel("Z"), self.in_cut_z, b_z))
        b_diag = QPushButton("Diagonal cut (2 clicks)")
        b_diag.clicked.connect(self.diagonal_requested.emit)
        s.add(b_diag)
        self.list_cuts = QListWidget()
        self.list_cuts.setMaximumHeight(110)
        s.add(self.list_cuts)
        b_del = QPushButton("Delete selected")
        b_del.clicked.connect(self._on_del_cut)
        b_clear = QPushButton("Clear")
        b_clear.clicked.connect(self.c.clear_manual_cuts)
        s.add_layout(_row(b_del, b_clear))
        self.lbl_diag = QLabel("Diagonal: inactive")
        self.lbl_diag.setProperty("class", "muted")
        s.add(self.lbl_diag)
        return s

    def _on_add_y(self) -> None:
        try:
            self.c.add_manual_y(float(self.in_cut_y.text().replace(",", ".")))
            self.in_cut_y.clear()
        except ValueError:
            self.c.notify.emit("Invalid value", "Enter a valid Y.", "warning")

    def _on_add_z(self) -> None:
        try:
            self.c.add_manual_z(float(self.in_cut_z.text().replace(",", ".")))
            self.in_cut_z.clear()
        except ValueError:
            self.c.notify.emit("Invalid value", "Enter a valid Z.", "warning")

    def _on_del_cut(self) -> None:
        row = self.list_cuts.currentRow()
        if row >= 0:
            self.c.delete_manual_cut(row)

    def _refresh_manual_list(self) -> None:
        self.list_cuts.clear()
        for i, cut in enumerate(self.c.project.manual_cuts):
            self.list_cuts.addItem(cut.describe(i))

    def set_diagonal_status(self, text: str) -> None:
        self.lbl_diag.setText(text)

    # ── Selected part (per-part overrides) ────────────────────────────
    _SWATCHES = ("#7C5CFF", "#34D399", "#F59E0B", "#F2585B", "#38BDF8", "#E879F9")

    def _section_part(self) -> CollapsibleSection:
        s = CollapsibleSection("Selected part", expanded=True)
        self.part_section = s
        self.lbl_part = QLabel("Select a part in the grid")
        self.lbl_part.setProperty("class", "muted")
        s.add(self.lbl_part)

        self.in_part_label = QLineEdit()
        self.in_part_label.setPlaceholderText("Part name")
        self.in_part_label.setToolTip("Rename this part (used in the grid and export filenames)")
        self.in_part_label.editingFinished.connect(self._on_part_label)
        s.add_layout(_row(QLabel("Name"), self.in_part_label))

        self.chk_part_enabled = QCheckBox("Include in export & simulation")
        self.chk_part_enabled.setToolTip("Uncheck to skip this part everywhere")
        self.chk_part_enabled.toggled.connect(self._on_part_enabled)
        s.add(self.chk_part_enabled)

        self.chk_part_reverse = QCheckBox("Reverse cut direction")
        self.chk_part_reverse.setToolTip("Reverse the wire path for this part only")
        self.chk_part_reverse.toggled.connect(self._on_part_reverse)
        s.add(self.chk_part_reverse)

        self.in_part_speed = _num_input("", 70)
        self.in_part_speed.setPlaceholderText("global")
        self.in_part_speed.setToolTip("Override the cut speed for this part (blank = use global)")
        self.in_part_speed.editingFinished.connect(self._on_part_speed)
        s.add_layout(_row(QLabel("Speed mm/s"), self.in_part_speed))

        swatches = QHBoxLayout()
        swatches.setContentsMargins(0, 0, 0, 0)
        swatches.setSpacing(5)
        swatches.addWidget(QLabel("Colour"))
        for hexc in (None, *self._SWATCHES):
            b = QPushButton()
            b.setFixedSize(20, 20)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            if hexc is None:
                b.setText("○")
                b.setToolTip("Default colour")
            else:
                b.setStyleSheet(
                    f"background:{hexc}; border-radius:10px; border:1px solid rgba(0,0,0,0.25);"
                )
                b.setToolTip(hexc)
            b.clicked.connect(lambda _checked=False, c=hexc: self._on_part_color(c))
            swatches.addWidget(b)
        swatches.addStretch(1)
        s.add_layout(swatches)

        self.b_export_part = QPushButton("Export this part…")
        self.b_export_part.setToolTip("Save G-code for just this part")
        self.b_export_part.clicked.connect(self._on_export_part)
        s.add(self.b_export_part)
        return s

    def update_part_panel(self) -> None:
        idx = self.c.focused_layer
        has = 0 <= idx < len(self.c.layers)
        self._current_part = idx if has else -1
        self.part_section.setVisible(bool(self.c.layers))
        for w in (
            self.in_part_label, self.chk_part_enabled, self.chk_part_reverse,
            self.in_part_speed, self.b_export_part,
        ):
            w.setEnabled(has)
        if not has:
            self.lbl_part.setText("Select a part in the grid")
            return
        ps = self.c.part_settings[idx]
        self.lbl_part.setText(f"{self.c.part_label(idx)}  ·  {idx + 1}/{len(self.c.layers)}")
        for w, value in (
            (self.in_part_label, ps.label or ""),
            (self.in_part_speed, "" if ps.speed_mm_s is None else f"{ps.speed_mm_s:g}"),
        ):
            w.blockSignals(True)
            w.setText(value)
            w.blockSignals(False)
        for chk, on in ((self.chk_part_enabled, ps.enabled), (self.chk_part_reverse, ps.reverse)):
            chk.blockSignals(True)
            chk.setChecked(on)
            chk.blockSignals(False)

    def _on_part_enabled(self, on: bool) -> None:
        if self._current_part >= 0:
            self.c.set_part_enabled(self._current_part, on)

    def _on_part_reverse(self, on: bool) -> None:
        if self._current_part >= 0:
            self.c.set_part_reverse(self._current_part, on)

    def _on_part_speed(self) -> None:
        if self._current_part < 0:
            return
        text = self.in_part_speed.text().replace(",", ".").strip()
        if not text:
            self.c.set_part_speed(self._current_part, None)
            return
        try:
            self.c.set_part_speed(self._current_part, float(text))
        except ValueError:
            pass

    def _on_part_label(self) -> None:
        if self._current_part >= 0:
            self.c.set_part_label(self._current_part, self.in_part_label.text().strip())

    def _on_part_color(self, color: str | None) -> None:
        if self._current_part >= 0:
            self.c.set_part_color(self._current_part, color)

    def _on_export_part(self) -> None:
        if self._current_part >= 0:
            self.export_part_requested.emit(self._current_part)

    # ── 6. Layers / preview ───────────────────────────────────────────
    def _section_layers(self) -> CollapsibleSection:
        s = CollapsibleSection("6 · Plate preview", expanded=False)
        self.b_preview = QPushButton("Preview Y×Z plates / parts")
        self.b_preview.clicked.connect(self.c.generate_preview)
        s.add(self.b_preview)
        self.b_prev = QPushButton("◀ Part")
        self.b_prev.clicked.connect(lambda: self.c.move_layer(-1))
        self.b_next = QPushButton("Part ▶")
        self.b_next.clicked.connect(lambda: self.c.move_layer(1))
        s.add_layout(_row(self.b_prev, self.b_next))
        self.b_full = QPushButton("Back to full view")
        self.b_full.clicked.connect(self.c.show_full_view)
        s.add(self.b_full)
        self.lbl_layer = QLabel("Preview: OFF")
        self.lbl_layer.setProperty("class", "muted")
        s.add(self.lbl_layer)
        return s

    def _refresh_layer_state(self) -> None:
        has = bool(self.c.layers)
        self.b_prev.setEnabled(has)
        self.b_next.setEnabled(has)
        self.b_full.setEnabled(has)
        if not has:
            self.lbl_layer.setText("Preview: OFF")
        else:
            idx = self.c.focused_layer
            if idx < 0:
                self.lbl_layer.setText(f"Preview: {len(self.c.layers)} parts (full view)")
            else:
                layer = self.c.layers[idx]
                self.lbl_layer.setText(f"Part {idx + 1}/{len(self.c.layers)} · {layer.label}")

    # ── 7. Export ─────────────────────────────────────────────────────
    def _section_export(self) -> CollapsibleSection:
        s = CollapsibleSection("7 · Export")
        b_g = _primary(QPushButton(get_icon("save", "#FFFFFF"), "  Generate G-Code"))
        b_g.setToolTip("Export machine-ready G-code for the current profile (Ctrl+E)")
        b_g.clicked.connect(self.export_gcode_requested.emit)
        s.add(b_g)
        b_dxf = QPushButton("Export modified DXF")
        b_dxf.setToolTip("Save the transformed geometry back out as a DXF")
        b_dxf.clicked.connect(self.export_dxf_requested.emit)
        s.add(b_dxf)
        self.in_basename = QLineEdit("cut")
        self.in_basename.setToolTip("Filename prefix used for each plate in a batch export")
        self.in_basename.editingFinished.connect(
            lambda: setattr(self.c.project, "batch_basename", self.in_basename.text() or "cut")
        )
        s.add_layout(_row(QLabel("Base filename"), self.in_basename))
        b_batch = QPushButton("Generate G-Codes by plates (batch)")
        b_batch.setToolTip("Export one G-code file per plate/part into a folder")
        b_batch.clicked.connect(self.export_batch_requested.emit)
        s.add(b_batch)
        return s
