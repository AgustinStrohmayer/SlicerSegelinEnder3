"""Bottom simulation timeline: play / loop / speed / scrubber + read-outs.

Visual structure (two rows):

    ▶  ⟲   [══════●══════════]   1.0× ▼
    Est 1:23 · Elapsed 0:42 · Height 45 mm (Z 0/45) · DXF 200×100 mm
"""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...theming.icons import get_icon, set_icon


def _fmt(seconds: float) -> str:
    seconds = max(0.0, seconds)
    m, s = divmod(round(seconds), 60)
    return f"{m:02d}:{s:02d}"


class Timeline(QWidget):
    play_toggled = pyqtSignal(bool)
    scrubbed = pyqtSignal(int)
    loop_changed = pyqtSignal(bool)
    speed_changed = pyqtSignal(float)

    SLIDER_MAX = 1000
    SPEEDS = (0.25, 0.5, 1.0, 1.5, 2.0, 4.0)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Timeline")
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 10)
        root.setSpacing(6)

        # Row 1 — transport
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self.btn_play = QPushButton(get_icon("play", "#FFFFFF"), "")
        self.btn_play.setCheckable(True)
        self.btn_play.setIconSize(QSize(18, 18))
        self.btn_play.setProperty("role", "primary")
        self.btn_play.setFixedSize(40, 32)
        self.btn_play.toggled.connect(self._on_play)
        row1.addWidget(self.btn_play)

        self.btn_loop = QToolButton(self)
        set_icon(self.btn_loop, "repeat", "#888888", 16)  # recoloured per theme by MainWindow
        self.btn_loop.setIconSize(QSize(16, 16))
        self.btn_loop.setCheckable(True)
        self.btn_loop.setFixedSize(32, 32)
        self.btn_loop.setToolTip("Loop simulation")
        self.btn_loop.toggled.connect(self.loop_changed.emit)
        row1.addWidget(self.btn_loop)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self.SLIDER_MAX)
        self.slider.valueChanged.connect(self.scrubbed.emit)
        row1.addWidget(self.slider, 1)

        self.speed = QComboBox(self)
        for s in self.SPEEDS:
            self.speed.addItem(f"{s:g}×", s)
        self.speed.setCurrentIndex(self.SPEEDS.index(1.0))
        self.speed.setFixedWidth(80)
        self.speed.currentIndexChanged.connect(
            lambda _i: self.speed_changed.emit(float(self.speed.currentData()))
        )
        self.speed.setToolTip("Playback speed")
        row1.addWidget(self.speed)

        root.addLayout(row1)

        # Row 2 — info
        row2 = QHBoxLayout()
        row2.setSpacing(16)
        self.lbl_time = QLabel("Est --:-- · Elapsed --:--")
        self.lbl_time.setProperty("role", "mono")
        self.lbl_height = QLabel("Height -- mm")
        self.lbl_height.setProperty("role", "mono")
        self.lbl_dims = QLabel("DXF --")
        self.lbl_dims.setProperty("role", "mono")
        for lbl in (self.lbl_time, self.lbl_height, self.lbl_dims):
            lbl.setProperty("class", "muted")
            row2.addWidget(lbl)
        row2.addStretch(1)
        root.addLayout(row2)

    # ── public ────────────────────────────────────────────────────────
    def _on_play(self, checked: bool) -> None:
        self.btn_play.setIcon(get_icon("pause" if checked else "play", "#FFFFFF"))
        self.play_toggled.emit(checked)

    def set_play_state(self, playing: bool) -> None:
        self.btn_play.blockSignals(True)
        self.btn_play.setChecked(playing)
        self.btn_play.setIcon(get_icon("pause" if playing else "play", "#FFFFFF"))
        self.btn_play.blockSignals(False)

    def set_progress_fraction(self, fraction: float) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(int(max(0.0, min(1.0, fraction)) * self.SLIDER_MAX))
        self.slider.blockSignals(False)

    def progress_fraction(self) -> float:
        return self.slider.value() / self.SLIDER_MAX

    def speed_multiplier(self) -> float:
        return float(self.speed.currentData())

    def loop_enabled(self) -> bool:
        return self.btn_loop.isChecked()

    def set_info(
        self,
        est_s: float,
        elapsed_s: float,
        z_min: float | None,
        z_max: float | None,
        dims: tuple[float, float] | None,
    ) -> None:
        self.lbl_time.setText(f"Est {_fmt(est_s)} · Elapsed {_fmt(elapsed_s)}")
        if z_min is None or z_max is None:
            self.lbl_height.setText("Height -- mm")
        else:
            self.lbl_height.setText(f"Height {z_max - z_min:.1f} mm (Z {z_min:.1f}/{z_max:.1f})")
        if dims is None:
            self.lbl_dims.setText("DXF --")
        else:
            self.lbl_dims.setText(f"DXF {dims[0]:.1f} × {dims[1]:.1f} mm")
