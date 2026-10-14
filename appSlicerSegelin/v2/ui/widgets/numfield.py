"""A number field that is easy to hit: big − / + buttons, typing, and no accidental scrolling.

Replaces ``QDoubleSpinBox`` where people size things by hand. The tiny native
arrows are gone. The − / + buttons repeat while held; Shift steps ×10 and Ctrl
×0.1. Typing a value applies on Enter or when leaving the field. The mouse
wheel changes the value only while the field has focus, so scrolling a panel
never edits it by accident.

It forwards the ``QDoubleSpinBox`` API (``value``, ``setValue``, ``setRange``,
``setDecimals``, ``setSuffix``, ``setSingleStep``, ``blockSignals``…), so it
drops in where a spin box was.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QAbstractSpinBox, QApplication, QDoubleSpinBox, QHBoxLayout, QToolButton, QWidget


class NumField(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None, *, lo: float = 0.0, hi: float = 1000.0, step: float = 1.0,
                 decimals: int = 1, suffix: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("NumField")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.spin = QDoubleSpinBox(self)
        self.spin.setObjectName("NumValue")
        self.spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin.setKeyboardTracking(False)
        self.spin.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.spin.setRange(lo, hi)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.installEventFilter(self)
        self.spin.valueChanged.connect(self.valueChanged.emit)
        self.minus = self._button("−", -1)
        self.plus = self._button("+", 1)
        lay.addWidget(self.minus)
        lay.addWidget(self.spin, 1)
        lay.addWidget(self.plus)

    def _button(self, text: str, sign: int) -> QToolButton:
        b = QToolButton(self)
        b.setObjectName("NumStep")
        b.setText(text)
        b.setAutoRepeat(True)
        b.setAutoRepeatDelay(350)
        b.setAutoRepeatInterval(60)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setToolTip("Hold to repeat · Shift: ×10 · Ctrl: ×0.1")
        b.clicked.connect(lambda: self._step(sign))
        return b

    def _step(self, sign: int) -> None:
        mods = QApplication.keyboardModifiers()
        step = self.spin.singleStep()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            step *= 10
        elif mods & Qt.KeyboardModifier.ControlModifier:
            step /= 10
        self.spin.setValue(self.spin.value() + sign * step)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        spin = self.__dict__.get("spin")  # None while Qt tears the widget down
        if spin is not None and obj is spin and event.type() == QEvent.Type.Wheel and not spin.hasFocus():
            event.ignore()  # let the panel scroll instead
            return True
        return super().eventFilter(obj, event)

    # ── QDoubleSpinBox API ────────────────────────────────────────────
    def value(self) -> float:
        return self.spin.value()

    def setValue(self, v: float) -> None:
        self.spin.setValue(v)

    def setRange(self, lo: float, hi: float) -> None:
        self.spin.setRange(lo, hi)

    def setDecimals(self, n: int) -> None:
        self.spin.setDecimals(n)

    def setSuffix(self, s: str) -> None:
        self.spin.setSuffix(s)

    def setSingleStep(self, s: float) -> None:
        self.spin.setSingleStep(s)

    def singleStep(self) -> float:
        return self.spin.singleStep()

    def setKeyboardTracking(self, on: bool) -> None:
        self.spin.setKeyboardTracking(on)

    def minimum(self) -> float:
        return self.spin.minimum()

    def maximum(self) -> float:
        return self.spin.maximum()

    def setToolTip(self, tip: str) -> None:
        super().setToolTip(tip)
        self.spin.setToolTip(tip)

    def blockSignals(self, b: bool) -> bool:
        self.spin.blockSignals(b)
        return super().blockSignals(b)

    def __getattr__(self, name: str):
        # anything else a spin box has (setAlignment, editingFinished…) goes to the inner one
        if name == "spin":
            raise AttributeError(name)
        return getattr(self.spin, name)
