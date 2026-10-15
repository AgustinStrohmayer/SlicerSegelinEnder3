"""The five-step workflow strip shown above the sidebar.

1 create and size the foam block on the printer → 2 load the profile and
place it on the block → 3 check the cut on the machine (3D view, simulator)
→ 4 tune the wire in the Cut Lab → 5 export the G-code.

Each chip shows whether its step is done or has a problem; the step whose
tools the sidebar shows is highlighted, and steps that need an earlier one
are disabled. A line under the chips says what to do next. Clicking a chip
asks the sidebar to show that step.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout

STEPS = ("Block", "Profile", "Check", "Cut Lab", "Export")
TIPS = (
    "Create the foam block and size it to fit the printer",
    "Load the DXF profile and place it on the block",
    "Check the cut on the machine: foam block, collisions, 3D view and simulator",
    "Wire temperature, feed and kerf in the Cut Lab",
    "Export the G-code for the printer",
)


class WorkflowSteps(QFrame):
    step_clicked = pyqtSignal(int)  # 1..5

    def __init__(self, parent=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(parent)
        self.setObjectName("StepsBar")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.chips: list[QToolButton] = []
        for i, tip in enumerate(TIPS, start=1):
            b = QToolButton(self)
            b.setObjectName("StepChip")
            b.setToolTip(f"Step {i}: {tip}")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.clicked.connect(lambda _=False, n=i: self.step_clicked.emit(n))
            row.addWidget(b)
            self.chips.append(b)
        v.addLayout(row)
        self.hint = QLabel(self)
        self.hint.setObjectName("StepHint")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)
        self.set_states(["current", "pending", "pending", "pending", "pending"], "")

    def set_states(self, states: list[str], hint: str) -> None:
        """``states``: one of "done", "current", "warn", "pending" per step."""
        for i, (chip, state) in enumerate(zip(self.chips, states, strict=True), start=1):
            mark = {"done": "✓", "warn": "⚠"}.get(state, str(i))
            chip.setText(f"{mark}\n{STEPS[i - 1]}")
            if chip.property("state") != state:
                chip.setProperty("state", state)
                chip.style().unpolish(chip)
                chip.style().polish(chip)
        self.hint.setText(hint)

    def set_active(self, step: int, unlocked: list[bool]) -> None:
        """Highlight step ``step`` (1..5); disable the chips of steps that need an earlier one."""
        for i, (chip, ok) in enumerate(zip(self.chips, unlocked, strict=True), start=1):
            chip.setEnabled(ok)
            active = "true" if i == step else "false"
            if chip.property("active") != active:
                chip.setProperty("active", active)
                chip.style().unpolish(chip)
                chip.style().polish(chip)

    def active(self) -> int:
        return next((i for i, c in enumerate(self.chips, start=1) if c.property("active") == "true"), 1)

    def states(self) -> list[str]:
        return [str(c.property("state")) for c in self.chips]
