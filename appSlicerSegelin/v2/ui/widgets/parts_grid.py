"""Gallery of every plate/part, each in its own mini-canvas.

When a profile is split (by plate size or manual cuts) the controller
produces a list of :class:`Layer` parts. This widget shows them all at
once so the operator can compare, toggle, recolour and pick a part to
edit — instead of stepping through one at a time.

Each tile paints the part's own geometry (fit to the tile, Y up), tinted
with the part's colour, dimmed when the part is excluded, and outlined
in the accent when selected.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..controllers.project_controller import ProjectController

TILE_W = 210
TILE_H = 188


def _fmt_dur(seconds: float) -> str:
    m, s = divmod(round(max(0.0, seconds)), 60)
    return f"{m:02d}:{s:02d}"


class _PartPreview(QWidget):
    """Paints one part's cut segments, scaled to fit, mathematical Y up."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(108)
        self._segs: list = []
        self._color = QColor("#7C5CFF")
        self._enabled = True

    def set_data(self, segments, color: str, enabled: bool) -> None:  # type: ignore[no-untyped-def]
        self._segs = segments
        self._color = QColor(color)
        self._enabled = enabled
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        if not self._segs:
            return
        ys = [p for s in self._segs for p in (s.a.y, s.b.y)]
        zs = [p for s in self._segs for p in (s.a.z, s.b.z)]
        y0, y1, z0, z1 = min(ys), max(ys), min(zs), max(zs)
        bw = max(1e-6, y1 - y0)
        bh = max(1e-6, z1 - z0)

        area = self.rect().adjusted(10, 10, -10, -10)
        scale = min(area.width() / bw, area.height() / bh)
        off_x = area.left() + (area.width() - bw * scale) / 2
        off_y = area.top() + (area.height() - bh * scale) / 2

        def to_px(py: float, pz: float) -> tuple[float, float]:
            x = off_x + (py - y0) * scale
            y = off_y + (bh - (pz - z0)) * scale  # flip Y (up)
            return x, y

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(self._color)
        if not self._enabled:
            color.setAlpha(60)
        pen = QPen(color, 1.8)
        pen.setCosmetic(True)
        painter.setPen(pen)
        for s in self._segs:
            ax, ay = to_px(s.a.y, s.a.z)
            bx, by = to_px(s.b.y, s.b.z)
            painter.drawLine(round(ax), round(ay), round(bx), round(by))


class PartTile(QFrame):
    clicked = pyqtSignal(int)
    enabled_toggled = pyqtSignal(int, bool)

    def __init__(self, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PartTile")
        self.setFixedSize(TILE_W, TILE_H)
        self.setProperty("selected", False)
        self.index = index

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        self._title = QLabel("Part")
        self._title.setProperty("role", "title")
        head.addWidget(self._title)
        head.addStretch(1)
        self._chk = QCheckBox(self)
        self._chk.setToolTip("Include this part in simulation and export")
        self._chk.toggled.connect(lambda on: self.enabled_toggled.emit(self.index, on))
        head.addWidget(self._chk)
        lay.addLayout(head)

        self._preview = _PartPreview(self)
        lay.addWidget(self._preview, 1)

        self._foot = QLabel("")
        self._foot.setProperty("class", "muted")
        lay.addWidget(self._foot)

    def set_content(self, *, label: str, dims: tuple[float, float], duration: float,
                    segments, color: str, enabled: bool) -> None:  # type: ignore[no-untyped-def]
        self._title.setText(label)
        self._foot.setText(f"{dims[0]:.0f} × {dims[1]:.0f} mm · {_fmt_dur(duration)}")
        self._chk.blockSignals(True)
        self._chk.setChecked(enabled)
        self._chk.blockSignals(False)
        self._preview.set_data(segments, color, enabled)

    def set_selected(self, selected: bool) -> None:
        if self.property("selected") == selected:
            return
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.clicked.emit(self.index)
        super().mousePressEvent(event)


class PartsGrid(QScrollArea):
    part_selected = pyqtSignal(int)
    part_enabled_toggled = pyqtSignal(int, bool)

    def __init__(self, controller: ProjectController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PartsGrid")
        self.c = controller
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._accent = "#7C5CFF"

        self._body = QWidget()
        self._body.setObjectName("PartsGridBody")
        self.setWidget(self._body)
        self._grid = QGridLayout(self._body)
        self._grid.setContentsMargins(16, 16, 16, 16)
        self._grid.setSpacing(14)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._tiles: list[PartTile] = []
        self._empty = QLabel("No parts yet — enable plate splitting or manual cuts, then Preview.")
        self._empty.setProperty("class", "muted")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._grid.addWidget(self._empty, 0, 0)

    def set_palette(self, accent: str) -> None:
        self._accent = accent
        self.refresh()

    # ── build / refresh ───────────────────────────────────────────────
    def rebuild(self) -> None:
        for t in self._tiles:
            t.setParent(None)
            t.deleteLater()
        self._tiles = []
        self._empty.setVisible(not self.c.layers)
        for i, _layer in enumerate(self.c.layers):
            tile = PartTile(i, self._body)
            tile.clicked.connect(self.part_selected.emit)
            tile.enabled_toggled.connect(self.part_enabled_toggled.emit)
            self._tiles.append(tile)
        self._reflow()
        self.refresh()

    def refresh(self) -> None:
        """Re-apply per-part content (label/color/enabled/selection)."""
        for i, tile in enumerate(self._tiles):
            if i >= len(self.c.layers):
                continue
            layer = self.c.layers[i]
            ps = self.c.part_settings[i]
            dims = (layer.y_max - layer.y_min, layer.z_max - layer.z_min)
            tile.set_content(
                label=self.c.part_label(i),
                dims=dims,
                duration=self.c.part_duration_s(i),
                segments=layer.local_segments,
                color=ps.color or self._accent,
                enabled=ps.enabled,
            )
            tile.set_selected(i == self.c.focused_layer)

    def set_selected(self, index: int) -> None:
        for tile in self._tiles:
            tile.set_selected(tile.index == index)

    # ── responsive reflow ─────────────────────────────────────────────
    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        if not self._tiles:
            return
        width = self.viewport().width()
        cols = max(1, (width - 32) // (TILE_W + 14))
        for idx, tile in enumerate(self._tiles):
            self._grid.removeWidget(tile)
            self._grid.addWidget(tile, idx // cols, idx % cols)
