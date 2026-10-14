"""Shared bits of the Cut Lab: theme colours for plots, KPI tiles, slider+spin rows, background jobs."""
from __future__ import annotations

import math
import threading
import traceback
from collections.abc import Callable
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...theming.tokens import ColorTokens, get_tokens

# Regime colours: readable on both themes, distinct from the amber accent.
REGIME = {
    "noncontact": "#2BB673",
    "contact": "#F28C28",
    "stall": "#E5484D",
    "overmelt": "#D6B656",
}
FOAM = "#7FB2E5"


def colors(theme: str) -> ColorTokens:
    return get_tokens(theme).color  # type: ignore[arg-type]


def style_plot(pw: pg.PlotWidget | pg.PlotItem, c: ColorTokens, *, grid: bool = True) -> None:
    item = pw.getPlotItem() if isinstance(pw, pg.PlotWidget) else pw
    for name in ("left", "bottom", "right", "top"):
        ax = item.getAxis(name)
        ax.setPen(pg.mkPen(c.border_strong))
        ax.setTextPen(pg.mkPen(c.muted))
    if grid:
        item.showGrid(x=True, y=True, alpha=0.12)


def heat_cmap() -> pg.ColorMap:
    """Dark-blue → teal → amber → white: cool kerf is narrow, hot is wide."""
    pos = np.array([0.0, 0.3, 0.6, 0.85, 1.0])
    cols = np.array([
        [24, 46, 92, 255], [32, 140, 160, 255], [120, 200, 110, 255], [245, 170, 40, 255], [255, 245, 220, 255],
    ], dtype=np.ubyte)
    return pg.ColorMap(pos, cols)


def diverging_cmap() -> pg.ColorMap:
    """Material loss (red) ← 0 (white-grey) → excess (blue)."""
    pos = np.array([0.0, 0.5, 1.0])
    cols = np.array([[229, 72, 77, 255], [220, 220, 220, 255], [60, 130, 230, 255]], dtype=np.ubyte)
    return pg.ColorMap(pos, cols)


def fmt(v: float, nd: int = 2) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{v:.{nd}f}"


class KpiTile(QFrame):
    """A read-out card: small caption, big value, unit and a hint line."""

    def __init__(self, caption: str, unit: str = "", tip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("KpiTile")
        self.setToolTip(tip)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(0)
        self._cap = QLabel(caption.upper())
        self._cap.setObjectName("KpiCaption")
        row = QHBoxLayout()
        row.setSpacing(4)
        self._val = QLabel("—")
        self._val.setObjectName("KpiValue")
        self._unit = QLabel(unit)
        self._unit.setObjectName("KpiUnit")
        row.addWidget(self._val)
        row.addWidget(self._unit, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch(1)
        self._hint = QLabel("")
        self._hint.setObjectName("KpiHint")
        lay.addWidget(self._cap)
        lay.addLayout(row)
        lay.addWidget(self._hint)

    def set(self, value: str, hint: str = "", color: str | None = None) -> None:
        self._val.setText(value)
        self._hint.setText(hint)
        self._val.setStyleSheet(f"color: {color};" if color else "")


def kpi_qss(c: ColorTokens) -> str:
    return f"""
    QWidget#CutLab {{ background: {c.bg}; }}
    QFrame#KpiTile {{ background: {c.surface_alt}; border: 1px solid {c.border}; border-radius: 10px; }}
    QLabel#KpiCaption {{ color: {c.muted}; font-size: 10px; letter-spacing: 1px; font-weight: 600; }}
    QLabel#KpiValue {{ color: {c.text}; font-size: 22px; font-weight: 600; }}
    QLabel#KpiUnit {{ color: {c.muted}; font-size: 12px; padding-bottom: 3px; }}
    QLabel#KpiHint {{ color: {c.muted}; font-size: 11px; }}
    QLabel#RegimeChip {{ border-radius: 11px; padding: 3px 12px; font-weight: 700; color: #111; }}
    QLabel#Advice {{ color: {c.text}; font-size: 12px; padding: 2px 4px; }}
    QFrame#LabCard {{ background: {c.surface}; border: 1px solid {c.border}; border-radius: 10px; }}
    QLabel#CardTitle {{ color: {c.text}; font-weight: 600; font-size: 12px; }}
    QLabel#CardSub {{ color: {c.muted}; font-size: 11px; }}
    QLabel#StepTitle {{ color: {c.text}; font-size: 16px; font-weight: 600; }}
    QLabel#StepBody {{ color: {c.text}; font-size: 12px; }}
    QWidget#CutLab QTabBar::tab {{ color: {c.muted}; background: transparent; padding: 6px 14px;
        border: none; border-bottom: 2px solid transparent; }}
    QWidget#CutLab QTabBar::tab:hover {{ color: {c.text}; }}
    QWidget#CutLab QTabBar::tab:selected {{ color: {c.text}; border-bottom: 2px solid {c.accent}; }}
    """


def card(title: str, sub: str = "", parent: QWidget | None = None) -> tuple[QFrame, QVBoxLayout]:
    """A titled panel; returns the frame and the layout to fill."""
    f = QFrame(parent)
    f.setObjectName("LabCard")
    v = QVBoxLayout(f)
    v.setContentsMargins(10, 8, 10, 10)
    v.setSpacing(4)
    t = QLabel(title)
    t.setObjectName("CardTitle")
    v.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setObjectName("CardSub")
        s.setWordWrap(True)
        v.addWidget(s)
    return f, v


class ParamRow(QWidget):
    """Label + slider + spin box bound together. ``log`` makes the slider logarithmic."""

    valueChanged = pyqtSignal(float)

    def __init__(self, label: str, lo: float, hi: float, value: float, *, step: float = 0.1, decimals: int = 2,
                 suffix: str = "", tip: str = "", log: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lo, self._hi, self._log = lo, hi, log
        self.setToolTip(tip)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        lab = QLabel(label)
        lab.setToolTip(tip)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setKeyboardTracking(False)
        self.spin.setMinimumWidth(96)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        top.addWidget(lab, 1)
        top.addWidget(self.spin)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        v.addLayout(top)
        v.addWidget(self.slider)
        self._sync = False
        self.slider.valueChanged.connect(self._from_slider)
        self.spin.valueChanged.connect(self._from_spin)
        self.setValue(value)

    def _to_pos(self, x: float) -> int:
        if self._log:
            f = (math.log(max(x, self._lo)) - math.log(self._lo)) / (math.log(self._hi) - math.log(self._lo))
        else:
            f = (x - self._lo) / (self._hi - self._lo)
        return round(1000 * min(1.0, max(0.0, f)))

    def _from_pos(self, p: int) -> float:
        f = p / 1000
        if self._log:
            return math.exp(math.log(self._lo) + f * (math.log(self._hi) - math.log(self._lo)))
        return self._lo + f * (self._hi - self._lo)

    def _from_slider(self, p: int) -> None:
        if self._sync:
            return
        self._sync = True
        self.spin.setValue(self._from_pos(p))
        self._sync = False
        self.valueChanged.emit(self.spin.value())

    def _from_spin(self, x: float) -> None:
        if self._sync:
            return
        self._sync = True
        self.slider.setValue(self._to_pos(x))
        self._sync = False
        self.valueChanged.emit(x)

    def value(self) -> float:
        return self.spin.value()

    def setValue(self, x: float) -> None:
        self._sync = True
        self.spin.setValue(x)
        self.slider.setValue(self._to_pos(x))
        self._sync = False


class Job(QObject):
    """Run ``fn`` on a Python thread; ``done``/``failed`` arrive on the GUI thread."""

    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(float, str)

    def __init__(self, fn: Callable[..., Any], *args: Any, parent: QObject | None = None, **kw: Any) -> None:
        super().__init__(parent)
        self._fn, self._args, self._kw = fn, args, kw
        self.cancelled = False

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def report(self, frac: float, msg: str) -> bool:
        self.progress.emit(frac, msg)
        return not self.cancelled

    def _run(self) -> None:
        try:
            out = self._fn(*self._args, **self._kw)
        except InterruptedError:
            self.failed.emit("cancelled")
            return
        except Exception:  # surfaced in the UI rather than lost in a thread
            self.failed.emit(traceback.format_exc(limit=4))
            return
        self.done.emit(out)


def qcolor(hex_: str, alpha: int = 255) -> QColor:
    c = QColor(hex_)
    c.setAlpha(alpha)
    return c
