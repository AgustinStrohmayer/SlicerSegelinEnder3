"""The full left sidebar — every legacy control, grouped and themed.

The sections follow the workflow shown by :class:`WorkflowSteps` (placed
above the sidebar by the main window): 1 create and size the foam block on
the printer → 2 load the profile and place it on the block → 3 check the cut
on the machine (3D view, simulator) → 4 Cut Lab (wire temperature, feed,
kerf) → 5 export the G-code. Only the active step's sections are shown, and
a step opens once the ones it needs are done (2 needs the block, 3–5 the
profile), so a new user sees a few tools at a time.

Buttons call the :class:`ProjectController` directly for pure-state
operations; anything that needs a file dialog, a window or the simulation
timer is emitted as a signal for the main window to handle.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ....core.hotwire_rig import PRESETS
from ...controllers.project_controller import ProjectController
from ...theming.icons import get_icon, set_icon
from ..collapsible import CollapsibleSection
from ..numfield import NumField
from .steps import WorkflowSteps


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


def _fold(label: str = "More options") -> tuple[QWidget, QVBoxLayout]:
    """A "More options ▸" toggle and the hidden box it opens: rarely needed controls stay out of the way."""
    holder = QWidget()
    outer = QVBoxLayout(holder)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(6)
    toggle = QToolButton()
    toggle.setObjectName("FoldToggle")
    toggle.setCheckable(True)
    toggle.setCursor(Qt.CursorShape.PointingHandCursor)
    toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    box = QWidget()
    inner = QVBoxLayout(box)
    inner.setContentsMargins(0, 0, 0, 0)
    inner.setSpacing(6)
    box.setVisible(False)

    def flip(on: bool) -> None:
        box.setVisible(on)
        toggle.setText(("▾  " if on else "▸  ") + label)

    toggle.toggled.connect(flip)
    flip(False)
    outer.addWidget(toggle)
    outer.addWidget(box)
    return holder, inner


def _set_status(label: QLabel, state: str, text: str) -> None:
    """A ``CheckStatus`` label: ``state`` is "ok", "warn" or "idle" (themed colours)."""
    label.setText(text)
    if label.property("state") != state:
        label.setProperty("state", state)
        label.style().unpolish(label)
        label.style().polish(label)


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
    place_cut_requested = pyqtSignal(str)  # "y" | "z"
    view3d_requested = pyqtSignal()
    simulate_requested = pyqtSignal()
    cut_lab_requested = pyqtSignal()
    step_shown = pyqtSignal(int)  # 1..5: the window shows that step's workspace (3D view, Cut Lab)

    def __init__(self, controller: ProjectController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.c = controller
        self._current_part = -1
        self._visited: set[int] = set()  # steps 3-5 the user has reached (3D/simulator, Cut Lab, export)
        self._syncing = False
        self._active = 1
        self._had_geometry = False
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

        # The step strip lives outside the scroll area (the main window docks it above) so it stays in view.
        self.steps = WorkflowSteps()
        self.steps.step_clicked.connect(self.show_step)
        self.step_sections: dict[int, list[CollapsibleSection]] = {i: [] for i in range(1, 6)}

        sections = (
            (1, self._section_block()),
            (2, self._section_file()), (2, self._section_shape()), (2, self._section_area()),
            (2, self._section_manual()), (2, self._section_part()), (2, self._section_layers()),
            (3, self._section_check()),
            (4, self._section_cut()),
            (5, self._section_export()),
        )
        for step, sec in sections:
            self.step_sections[step].append(sec)
            root.addWidget(sec)
        # step 2's rarely needed tools (plates, manual cuts, plate preview) hide behind a switch
        self.advanced_sections = self.step_sections[2][2:]
        self._advanced = False
        self.chk_advanced = QCheckBox("Show advanced tools (plates, manual cuts)")
        self.chk_advanced.setToolTip("Split a big profile into plates or cut it by hand — not needed for one part")
        self.chk_advanced.toggled.connect(self._on_advanced)

        self.nav_rows: dict[int, QWidget] = {}
        self.next_buttons: dict[int, QPushButton] = {}
        self.back_buttons: dict[int, QPushButton] = {}
        nexts = {1: "Next: load the profile  ›", 2: "Next: check it  ›", 3: "Next: wire and feed  ›",
                 4: "Next: export  ›"}
        for step in range(1, 6):
            row = QWidget()
            v = QVBoxLayout(row)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(8)
            if step == 2:
                v.addWidget(self.chk_advanced)
            h = QHBoxLayout()
            h.setSpacing(6)
            if step > 1:
                b = QPushButton("‹  Back")
                b.setToolTip(f"Back to step {step - 1}")
                b.clicked.connect(lambda _=False, n=step: self.show_step(n - 1))
                self.back_buttons[step] = b
                h.addWidget(b)
            if step in nexts:
                b = _primary(QPushButton(nexts[step]))
                b.clicked.connect(lambda _=False, n=step: self._on_next(n))
                self.next_buttons[step] = b
                h.addWidget(b, 1)
            v.addLayout(h)
            self.nav_rows[step] = row
            root.addWidget(row)
        root.addStretch(1)
        self._let_narrow(container)

        self.c.layers_changed.connect(self._refresh_layer_state)
        self.c.changed.connect(self._refresh_manual_list)
        self.c.info_changed.connect(self._refresh_manual_list)
        self.c.changed.connect(self._refresh_steps)
        self.c.setup_changed.connect(self._refresh_check)
        self._refresh_layer_state()
        self._refresh_manual_list()
        self.update_part_panel()
        self._refresh_check()
        self.show_step(1)

    @staticmethod
    def _let_narrow(root: QWidget) -> None:
        """Nothing may make the panel wider than the window gives it (it has no horizontal scroll):
        headers, long combo items and wide number ranges shrink instead of being cut off at the right."""
        from PyQt6.QtWidgets import QAbstractSpinBox

        for w in root.findChildren(QToolButton):
            if w.objectName() in ("SectionHeader", "FoldToggle"):
                w.setMinimumWidth(40)
        for cb in root.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(6)
        for sp in root.findChildren(QAbstractSpinBox):
            sp.setMinimumWidth(56)
        for b in root.findChildren(QPushButton):
            b.setMinimumWidth(min(b.minimumSizeHint().width(), 60))

    # ── workflow steps ────────────────────────────────────────────────
    def unlocked(self) -> list[bool]:
        """Which steps can be opened: 1 always, 2 once the block exists, 3–5 once there is a profile."""
        block, geo = self.c.project.block_created, self.c.has_geometry
        return [True, block, block and geo, block and geo, block and geo]

    @property
    def active_step(self) -> int:
        return self._active

    def show_step(self, step: int) -> None:
        """Show step ``step``'s tools (and only those); ignored while the step is still locked."""
        if not 1 <= step <= 5 or not self.unlocked()[step - 1]:
            return
        self._active = step
        for n, secs in self.step_sections.items():
            for sec in secs:
                sec.setVisible(n == step and (self._advanced or sec not in self.advanced_sections))
        self.part_section.setVisible(step == 2 and bool(self.c.layers))
        for n, row in self.nav_rows.items():
            row.setVisible(n == step)
        self.step_sections[step][0].set_expanded(True)
        self.verticalScrollBar().setValue(0)
        self._refresh_steps()
        self.step_shown.emit(step)

    def _on_advanced(self, on: bool) -> None:
        self._advanced = on
        for sec in self.advanced_sections:
            sec.setVisible(on and self._active == 2)

    def _on_next(self, step: int) -> None:
        if step == 3:
            self.mark_visited(3)
        self.show_step(step + 1)

    def mark_visited(self, step: int) -> None:
        """The user reached step 3 (3D view / simulator), 4 (Cut Lab) or 5 (export)."""
        if step not in self._visited:
            self._visited.add(step)
            self._refresh_steps()

    def _refresh_steps(self) -> None:
        c = self.c
        geo, block = c.has_geometry, c.project.block_created
        unlocked = self.unlocked()
        if geo and not self._had_geometry:
            self._had_geometry = True
            if self._active <= 2:
                self.show_step(2)  # a profile was loaded (Ctrl+O works from any step): place it on the block
                return
        self._had_geometry = geo
        if not unlocked[self._active - 1]:  # e.g. a new project: back to the last step that is open
            self.show_step(max(i for i, ok in enumerate(unlocked, start=1) if ok and i <= self._active))
            return
        seen = self._visited
        done = [block and not c.block_issues, geo, geo and not c.cut_issues and 3 in seen,
                geo and 4 in seen, geo and 5 in seen]
        states = ["done" if d else "pending" for d in done]
        if block and c.block_issues:
            states[0] = "warn"
        if geo and c.cut_issues:
            states[2] = "warn"
        nb, nc = len(c.block_issues), len(c.cut_issues)
        if not block:
            hint1 = "Create the foam block: it sits on the bed, between the arms, under the wire."
        elif nb:
            hint1 = f"⚠ The block doesn't fit the machine ({nb} problem{'s' if nb > 1 else ''}): resize it below."
        else:
            hint1 = "✓ The block fits the printer. Next: load the profile (step 2)."
        hint = {
            1: hint1,
            2: ("Load the DXF profile to cut (Ctrl+O)." if not geo else
                "Rotate, mirror and move the profile so it sits inside the block, then check it (step 3)."),
            3: (f"⚠ {nc} problem{'s' if nc > 1 else ''} with this cut on the machine — see below." if nc else
                "✓ The cut fits the machine. Watch it in 3D or the simulator, then go to the Cut Lab."),
            4: "Find the wire temperature, feed and kerf in the Cut Lab, then enter the feed as the work speed.",
            5: "✓ G-code exported." if 5 in seen else "Export the G-code for the printer.",
        }[self._active]
        self.steps.set_states(states, hint)
        self.steps.set_active(self._active, unlocked)
        self.nav_rows[1].setVisible(self._active == 1 and block)
        self.next_buttons[1].setEnabled(not nb)
        self.next_buttons[2].setEnabled(geo)
        self.fix_row.setVisible(geo and bool(nc))
        self.b_create.setVisible(not block)
        self.block_form.setVisible(block)

    # ── 1. Foam block ─────────────────────────────────────────────────
    def _section_block(self) -> CollapsibleSection:
        s = CollapsibleSection("1 · Foam block on the printer")
        intro = QLabel("Everything is cut out of one foam block lying on the printer's bed, under the hot wire. "
                       "Create it, then type the size of your foam: the 3D view and the check follow every change.")
        intro.setWordWrap(True)
        intro.setProperty("class", "muted")
        s.add(intro)
        self.b_create = _primary(QPushButton(get_icon("cube", "#18181B"), "  Create foam block"))
        self.b_create.setToolTip("Put a foam block on the bed, then size it to fit the printer")
        self.b_create.clicked.connect(self.c.create_block)
        s.add(self.b_create)

        self.block_form = QWidget()
        v = QVBoxLayout(self.block_form)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.block_status = QLabel()
        self.block_status.setObjectName("CheckStatus")
        self.block_status.setWordWrap(True)
        v.addWidget(self.block_status)

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        self.cmb_rig = QComboBox()
        self.cmb_rig.addItems(list(PRESETS))
        self.cmb_rig.setToolTip("The printer and arms the cut runs on (measure yours under “Your machine”)")
        self.cmb_rig.currentTextChanged.connect(self._on_rig)
        form.addRow("Machine", self.cmb_rig)

        def spin(lo: float, hi: float, step: float, tip: str) -> NumField:
            sp = NumField(lo=lo, hi=hi, step=step, suffix=" mm")
            sp.setToolTip(tip)
            sp.valueChanged.connect(self._on_block)
            return sp

        self.sp_len = spin(1, 2000, 5, "Block length along Y (the bed travel)")
        self.sp_h = spin(1, 1000, 1, "Block height (Z)")
        self.sp_w = spin(1, 2000, 5, "Block width along the wire (X) — the wing span of the part")
        self.sp_spacer = spin(0, 200, 1, "Board under the block: the arm tips hang below the wire")
        self.sp_y0 = spin(-1000, 2000, 1, "Where the block's front face is along Y, from the wire's start")
        self.sp_xoff = spin(-1000, 1000, 5, "Shift the block along the wire (X); 0 = centred between the arms")
        form.addRow("Length (Y)", self.sp_len)
        form.addRow("Height (Z)", self.sp_h)
        form.addRow("Width (X)", self.sp_w)
        v.addLayout(form)
        fold, more = _fold("Placement on the bed")
        form2 = QFormLayout()
        form2.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form2.setContentsMargins(0, 0, 0, 0)
        form2.setHorizontalSpacing(8)
        form2.setVerticalSpacing(6)
        form2.addRow("Spacer under it", self.sp_spacer)
        form2.addRow("Front face at Y", self.sp_y0)
        form2.addRow("Shift along wire", self.sp_xoff)
        more.addLayout(form2)
        v.addWidget(fold)
        v.addWidget(self._rig_fold())
        self.rig_info = QLabel()
        self.rig_info.setWordWrap(True)
        self.rig_info.setProperty("class", "muted")
        v.addWidget(self.rig_info)
        b3d = _icon_btn("cube", "  Show in 3D")
        b3d.setToolTip("Show the printer, the foam block and the wire in 3D (toolbar: 3D)")
        b3d.clicked.connect(self.view3d_requested.emit)
        v.addWidget(b3d)
        s.add(self.block_form)
        return s

    # Your segelín as built: (field, label, lo, hi, step, how to measure it). The typical value
    # shown next to each is the chosen machine's preset, so a slip (cm for mm, a swapped arm) shows.
    _RIG_FIELDS = (
        ("pivot_spacing", "Pivot spacing", 40, 400, 0.5, "Between the two arm pivots (the clamp bolts), axis to axis"),
        ("arm_lower_length", "Arm: pivot → wire", 20, 300, 1, "Along each arm, from its pivot to the wire hole"),
        ("arm_upper_length", "Arm: pivot → spring", 10, 200, 1, "Along each arm, from its pivot to the spring hole"),
        ("arm_angle_deg", "Arm angle", 30, 90, 0.5, "Arm inclination from horizontal (90 = vertical)"),
        ("origin_z", "Wire above bed at Z0", 0, 300, 0.5,
         "Height of the wire above the bed where the G-code's Z0 is set (G92); "
         "the block (on its spacer) must start below it"),
    )

    def _rig_fold(self) -> QWidget:
        fold, more = _fold("Your machine (measure it)")
        note = QLabel("Measure your segelín once; the check, the 3D view and the Cut Lab use these. "
                      "Grey: the typical value; orange: far from it, measure again.")
        note.setWordWrap(True)
        note.setProperty("class", "muted")
        more.addWidget(note)
        self.rig_fields: dict[str, tuple[NumField, QLabel]] = {}
        for key, label, lo, hi, step, tip in self._RIG_FIELDS:
            sp = NumField(lo=lo, hi=hi, step=step, suffix="°" if key.endswith("_deg") else " mm")
            sp.setToolTip(tip)
            sp.valueChanged.connect(self._on_rig_field)
            name = QLabel(label)
            name.setToolTip(tip)
            typ = QLabel()
            typ.setProperty("class", "muted")
            head = _row(name, typ)
            head.setStretch(0, 1)
            more.addLayout(head)  # the name and its typical value above, the field below: fits a narrow panel
            more.addWidget(sp)
            self.rig_fields[key] = (sp, typ)
        b_reset = QPushButton("Typical values")
        b_reset.setToolTip("Back to the chosen machine's preset")
        b_reset.clicked.connect(lambda: self.c.set_rig(PRESETS.get(self.c.project.rig.name, self.c.project.rig)))
        more.addWidget(b_reset)
        return fold

    def _on_rig_field(self) -> None:
        if self._syncing:
            return
        from dataclasses import replace

        vals = {k: sp.value() for k, (sp, _) in self.rig_fields.items()}
        self.c.set_rig(replace(self.c.project.rig, **vals))

    # ── 2. Profile: load the DXF ──────────────────────────────────────
    def _section_file(self) -> CollapsibleSection:
        s = CollapsibleSection("2 · Profile — load DXF")
        intro = QLabel("Load the outline you want to cut (a DXF drawing). It lands in the middle of the block.")
        intro.setWordWrap(True)
        intro.setProperty("class", "muted")
        s.add(intro)
        load = _primary(QPushButton(get_icon("folder-open", "#18181B"), "  Load DXF"))
        load.setToolTip("Import a DXF outline to cut (Ctrl+O)")
        load.clicked.connect(self._on_import)
        s.add(load)
        fold, more = _fold("Units and scale")
        self.chk_units = QCheckBox("Use INSUNITS auto-scale")
        self.chk_units.setToolTip("Scale the drawing using the DXF's own units header")
        self.chk_units.setChecked(True)
        more.addWidget(self.chk_units)
        self.in_scale = _num_input("1.0")
        self.in_scale.setToolTip("Extra scale multiplier applied on top of unit auto-scaling")
        more.addLayout(_row(QLabel("DXF scale ×"), self.in_scale))
        s.add(fold)
        return s

    def _on_import(self) -> None:
        try:
            scale = float(self.in_scale.text().replace(",", "."))
        except ValueError:
            scale = 1.0
        self.import_requested.emit(self.chk_units.isChecked(), scale)

    # ── 2. Adjust shape ───────────────────────────────────────────────
    def _section_shape(self) -> CollapsibleSection:
        s = CollapsibleSection("2 · Profile — shape && position")
        intro = QLabel("Turn and move the profile until it sits inside the block (watch the 3D view), and choose "
                       "where the wire comes in.")
        intro.setWordWrap(True)
        intro.setProperty("class", "muted")
        s.add(intro)
        b_corner = _primary(QPushButton("Place in the corner"))
        b_corner.setToolTip("Front-top corner of the block, 5 mm from its faces: the least foam used (the rest stays "
                            "in one piece), the shortest entry and the wire as high as possible (clears the arms)")
        b_corner.clicked.connect(self.c.place_in_block)
        b_center = QPushButton("Center")
        b_center.setToolTip("Move the profile to the middle of the foam block")
        b_center.clicked.connect(self.c.center_on_block)
        s.add_layout(_row(b_corner, b_center))
        self.cmb_entry = QComboBox()
        self.cmb_entry.addItem("From the side", "side")
        self.cmb_entry.addItem("From the top", "top")
        self.cmb_entry.setToolTip("The wire starts in front of the block, at its bottom. Side: it rises in the air and "
                                  "cuts straight in to the profile's front. Top: it goes over the block and cuts "
                                  "straight down to the profile's highest point.")
        self.cmb_entry.currentIndexChanged.connect(self._on_entry)
        s.add_layout(_row(QLabel("Wire enters"), self.cmb_entry))
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

        self.in_step = _num_input("1", 50)
        self.in_step.setToolTip("How far each arrow moves the profile, in millimetres")
        b_ym = QPushButton("←")
        b_ym.setToolTip("Move the profile towards the front of the block (−Y)")
        b_ym.clicked.connect(lambda: self.c.translate("y", -self._step()))
        b_yp = QPushButton("→")
        b_yp.setToolTip("Move the profile towards the back of the block (+Y)")
        b_yp.clicked.connect(lambda: self.c.translate("y", self._step()))
        b_zm = QPushButton("↓")
        b_zm.setToolTip("Move the profile down (−Z)")
        b_zm.clicked.connect(lambda: self.c.translate("z", -self._step()))
        b_zp = QPushButton("↑")
        b_zp.setToolTip("Move the profile up (+Z)")
        b_zp.clicked.connect(lambda: self.c.translate("z", self._step()))
        s.add_layout(_row(b_ym, b_yp, b_zm, b_zp, self.in_step, QLabel("mm")))

        fold, more = _fold()
        self.in_deg = _num_input("0.1", 60)
        self.in_deg.setToolTip("Fine rotation step in degrees")
        b_ccw = _icon_btn("rotate-ccw", "")
        b_ccw.setToolTip("Rotate counter-clockwise by the fine step")
        b_ccw.clicked.connect(lambda: self.c.rotate_fine(-self._deg()))
        b_cw = _icon_btn("rotate-cw", "")
        b_cw.setToolTip("Rotate clockwise by the fine step")
        b_cw.clicked.connect(lambda: self.c.rotate_fine(self._deg()))
        more.addLayout(_row(QLabel("Fine °"), self.in_deg, b_ccw, b_cw))
        self.b_reverse = QPushButton("Reverse cut direction")
        self.b_reverse.setToolTip("Flip the order in which the wire traverses the path")
        self.b_reverse.setCheckable(True)
        self.b_reverse.clicked.connect(self._on_reverse)
        more.addWidget(self.b_reverse)
        b_align = QPushButton("Align origin to cut")
        b_align.setToolTip("Shift the profile so cutting starts at the machine origin (without a block)")
        b_align.clicked.connect(self.c.align_origin)
        more.addWidget(b_align)
        s.add(fold)
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

    # ── 3. Check the cut on the machine ───────────────────────────────
    def _section_check(self) -> CollapsibleSection:
        s = CollapsibleSection("3 · Check the cut on the machine")
        intro = QLabel("The project's G-code run on the machine with the block from step 1: travel, collisions and "
                       "the wire leaving the block. The 3D view, the simulator and the Cut Lab share them.")
        intro.setWordWrap(True)
        intro.setProperty("class", "muted")
        s.add(intro)
        self.check_status = QLabel()
        self.check_status.setObjectName("CheckStatus")
        self.check_status.setWordWrap(True)
        s.add(self.check_status)
        self.fix_row = QWidget()
        fv = QVBoxLayout(self.fix_row)
        fv.setContentsMargins(0, 0, 0, 0)
        fv.setSpacing(6)
        fix_txt = QLabel("To fix it, change the block (smaller, or another machine) or move the profile:")
        fix_txt.setWordWrap(True)
        fv.addWidget(fix_txt)
        b_blk = QPushButton("‹  Change the block")
        b_blk.clicked.connect(lambda: self.show_step(1))
        b_prof = QPushButton("‹  Move the profile")
        b_prof.clicked.connect(lambda: self.show_step(2))
        fv.addLayout(_row(b_blk, b_prof))
        s.add(self.fix_row)
        self.chk_fit = QCheckBox("Fit the block to the cut")
        self.chk_fit.setToolTip("Keep the block just around the cut, with 5 mm margins, as the profile changes")
        self.chk_fit.toggled.connect(self._on_fit)
        s.add(self.chk_fit)
        b3d = _icon_btn("cube", "  View in 3D")
        b3d.setToolTip("Show the printer, the foam block and the wire in 3D (toolbar: 3D)")
        b3d.clicked.connect(self.view3d_requested.emit)
        bsim = _icon_btn("play", "  Play the cut")
        bsim.setToolTip("Run the wire along the whole path in the 3D view, from the start (Ctrl+Shift+M)")
        bsim.clicked.connect(self.simulate_requested.emit)
        s.add_layout(_row(b3d, bsim))
        return s

    def _refresh_check(self) -> None:
        p, c = self.c.project, self.c
        self._syncing = True
        if p.rig.name in PRESETS:
            self.cmb_rig.setCurrentText(p.rig.name)
        b = p.block
        for sp, val in ((self.sp_len, b.length_y), (self.sp_h, b.height_z), (self.sp_w, b.width_x),
                        (self.sp_spacer, b.spacer), (self.sp_y0, b.y0), (self.sp_xoff, b.x_offset)):
            sp.setValue(val)
        typical = PRESETS.get(p.rig.name, p.rig)
        for key, (sp, typ) in self.rig_fields.items():
            val, ref = getattr(p.rig, key), getattr(typical, key)
            sp.setValue(val)
            typ.setText(f"typ. {ref:g}")
            off = abs(val - ref) > max(0.15 * abs(ref), 1.0)  # far from typical: worth a second look
            typ.setStyleSheet("color: #E5A23B;" if off else "")
            typ.setToolTip("Far from the typical value: check the measurement" if off else "")
        self.chk_fit.setChecked(p.block_auto)
        self.cmb_entry.setCurrentIndex(self.cmb_entry.findData(p.entry))
        self.sp_len.setEnabled(not p.block_auto)
        self.sp_h.setEnabled(not p.block_auto)
        self.sp_y0.setEnabled(not p.block_auto)
        self._syncing = False
        edited = p.rig.name in PRESETS and p.rig != PRESETS[p.rig.name]
        rig = p.rig
        self.rig_info.setText(
            ("Your measurements (not the preset). " if edited else "") +
            f"Wire {rig.nozzle_clearance:.0f} mm under the nozzle · span {rig.wire_span:.0f} mm · "
            f"usable width at {b.height_z:.0f} mm tall: {rig.usable_width(b.height_z):.0f} mm")
        if c.block_issues:
            _set_status(self.block_status, "warn", "\n".join(f"⚠ {i}" for i in c.block_issues))
        else:
            _set_status(self.block_status, "ok", "✓ The block fits the printer: between the arms, under the "
                        "carriage, within the travel.")
        if not c.has_geometry:
            _set_status(self.check_status, "idle", "Load a profile (step 2) to check the cut on the machine.")
        elif c.cut_issues:
            _set_status(self.check_status, "warn", "\n".join(f"⚠ {i}" for i in c.cut_issues))
        else:
            _set_status(self.check_status, "ok", "✓ Fits the machine; no collisions.")
        self._refresh_steps()

    def _on_rig(self, name: str) -> None:
        if not self._syncing and name in PRESETS:
            self.c.set_rig(PRESETS[name])

    def _on_block(self) -> None:
        if self._syncing:
            return
        from dataclasses import replace

        self.c.set_block(replace(self.c.project.block, length_y=self.sp_len.value(), height_z=self.sp_h.value(),
                                 width_x=self.sp_w.value(), spacer=self.sp_spacer.value(),
                                 y0=self.sp_y0.value(), x_offset=self.sp_xoff.value()))

    def _on_entry(self) -> None:
        if not self._syncing:
            self.c.set_entry(self.cmb_entry.currentData())

    def _on_fit(self, on: bool) -> None:
        if not self._syncing:
            self.c.set_block_auto(on)

    # ── 4. Wire, feed & kerf (Cut Lab) ────────────────────────────────
    def _section_cut(self) -> CollapsibleSection:
        s = CollapsibleSection("4 · Wire && feed — Cut Lab")
        intro = QLabel("Find the wire drive and the feed that cut cleanly, and how much the kerf takes off the "
                       "part. Then enter that feed as the work speed.")
        intro.setWordWrap(True)
        intro.setProperty("class", "muted")
        s.add(intro)
        lab = _primary(QPushButton("Show the Cut Lab"))
        lab.setToolTip("Wire temperature, kerf and a slice-by-slice simulation of this cut, in the main view "
                       "(Ctrl+Shift+L)")
        lab.clicked.connect(self.cut_lab_requested.emit)
        s.add(lab)
        self.in_speed = _num_input("10", 70)
        self.in_speed.setToolTip("Wire feed speed during cutting, in mm/s")
        self.in_speed.editingFinished.connect(self._on_speed)
        s.add_layout(_row(QLabel("Work speed mm/s"), self.in_speed))
        self.cut_saved = QLabel("No calibration saved yet: the Cut Lab's guided mode finds the feed and the kerf, "
                                "and the project uses them from then on.")
        self.cut_saved.setWordWrap(True)
        self.cut_saved.setProperty("class", "muted")
        s.add(self.cut_saved)
        self.chk_kerf = QCheckBox("Keep the part at its drawn size")
        self.chk_kerf.setToolTip("The wire melts a slot (the kerf) as it cuts. With this on, the wire runs half a kerf "
                                 "outside the part (inside holes), so the part keeps its drawn size.")
        self.chk_kerf.setChecked(self.c.kerf_on)
        self.chk_kerf.setEnabled(False)  # until the Cut Lab has saved a kerf
        self.chk_kerf.toggled.connect(self.c.set_kerf_on)
        s.add(self.chk_kerf)
        return s

    def show_cut_settings(self, w) -> None:  # type: ignore[no-untyped-def]
        """The Cut Lab's saved work settings (used by the project)."""
        self.in_speed.setText(f"{w.work_feed_mm_s:g}")
        mode = (f"supply {w.voltage_v:.1f} V (≈{w.current_a:.1f} A)" if w.supply_mode == "voltage"
                else f"supply {w.current_a:.1f} A (≈{w.voltage_v:.1f} V)")
        when = f", saved {w.saved_at.replace('T', ' ')[:16]}" if w.saved_at else ""
        self.cut_saved.setText(f"✓ In use: feed {w.work_feed_mm_s:.1f} mm/s · kerf {w.kerf_mm:.2f} mm "
                               f"({w.kerf_offset_mm:.2f} per side) · {mode}"
                               f"{' · calibrated' if w.calibrated else ''}{when}.")
        self.chk_kerf.setEnabled(w.kerf_offset_mm > 0)
        self.chk_kerf.setText(f"Keep the part at its drawn size (wire {w.kerf_offset_mm:.2f} mm outside)")

    def _on_speed(self) -> None:
        try:
            self.c.set_speed(float(self.in_speed.text().replace(",", ".")))
        except ValueError:
            pass

    # ── 2. Usable area / plates ───────────────────────────────────────
    def _section_area(self) -> CollapsibleSection:
        s = CollapsibleSection("2 · Profile — plates / usable area", expanded=False)
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

    # ── 2. Manual cuts ────────────────────────────────────────────────
    def _section_manual(self) -> CollapsibleSection:
        s = CollapsibleSection("2 · Profile — manual cuts", expanded=False)
        self.in_cut_y = _num_input("", 70)
        b_y = QPushButton("+Y")
        b_y.clicked.connect(self._on_add_y)
        s.add_layout(_row(QLabel("Y"), self.in_cut_y, b_y))
        self.in_cut_z = _num_input("", 70)
        b_z = QPushButton("+Z")
        b_z.clicked.connect(self._on_add_z)
        s.add_layout(_row(QLabel("Z"), self.in_cut_z, b_z))
        b_diag = QPushButton("Diagonal cut (2 clicks)")
        b_diag.setToolTip("Click two points on the canvas to define a diagonal cut")
        b_diag.clicked.connect(self.diagonal_requested.emit)
        s.add(b_diag)
        b_py = QPushButton("Place Y on canvas")
        b_py.setToolTip("Click on the canvas to drop a Y cut where you point")
        b_py.clicked.connect(lambda: self.place_cut_requested.emit("y"))
        b_pz = QPushButton("Place Z on canvas")
        b_pz.setToolTip("Click on the canvas to drop a Z cut where you point")
        b_pz.clicked.connect(lambda: self.place_cut_requested.emit("z"))
        s.add_layout(_row(b_py, b_pz))
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
        self.part_section.setVisible(self._active == 2 and bool(self.c.layers))
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

    # ── 2. Layers / preview ───────────────────────────────────────────
    def _section_layers(self) -> CollapsibleSection:
        s = CollapsibleSection("2 · Profile — plate preview", expanded=False)
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

    # ── 5. Export ─────────────────────────────────────────────────────
    def _section_export(self) -> CollapsibleSection:
        s = CollapsibleSection("5 · Export G-code")
        b_g = _primary(QPushButton(get_icon("save", "#18181B"), "  Generate G-Code"))
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
