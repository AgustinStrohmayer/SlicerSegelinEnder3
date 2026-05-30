"""Bottom simulation timeline: play/pause, scrubber, time & height read-out."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QWidget

from ...theming.icons import get_icon


def _fmt(seconds: float) -> str:
    seconds = max(0.0, seconds)
    m, s = divmod(round(seconds), 60)
    return f"{m:02d}:{s:02d}"


class Timeline(QWidget):
    play_toggled = pyqtSignal(bool)
    scrubbed = pyqtSignal(int)

    SLIDER_MAX = 1000  # fine-grained internal resolution

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Timeline")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 12)
        lay.setSpacing(14)

        self.btn_play = QPushButton(get_icon("play", "#FFFFFF"), "")
        self.btn_play.setObjectName("PlayButton")
        self.btn_play.setCheckable(True)
        self.btn_play.setFixedSize(34, 34)
        self.btn_play.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_play.toggled.connect(self._on_play)
        lay.addWidget(self.btn_play)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self.SLIDER_MAX)
        self.slider.valueChanged.connect(self.scrubbed.emit)
        lay.addWidget(self.slider, 1)

        self.lbl_time = QLabel("Est. --:-- · Elapsed 00:00")
        self.lbl_time.setProperty("class", "muted")
        lay.addWidget(self.lbl_time)

        self.lbl_height = QLabel("Height -- mm")
        self.lbl_height.setProperty("class", "muted")
        lay.addWidget(self.lbl_height)

        self.lbl_dims = QLabel("DXF --")
        self.lbl_dims.setProperty("class", "muted")
        lay.addWidget(self.lbl_dims)

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

    def set_info(self, est_s: float, elapsed_s: float, z_min: float | None, z_max: float | None,
                 dims: tuple[float, float] | None) -> None:
        self.lbl_time.setText(f"Est. {_fmt(est_s)} · Elapsed {_fmt(elapsed_s)}")
        if z_min is None or z_max is None:
            self.lbl_height.setText("Height -- mm")
        else:
            self.lbl_height.setText(f"Height {z_max - z_min:.1f} mm (Z {z_min:.1f}/{z_max:.1f})")
        if dims is None:
            self.lbl_dims.setText("DXF --")
        else:
            self.lbl_dims.setText(f"DXF {dims[0]:.1f} × {dims[1]:.1f} mm")
