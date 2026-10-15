"""Canvas + rulers + overlay assembled with a grid layout."""
from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QWidget

from .canvas_overlay import CanvasOverlay
from .graphics_view import CanvasView
from .rulers import HorizontalRuler, RulerCorner, VerticalRuler
from .scene import SlicerScene


class CanvasContainer(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CanvasContainer")

        self.scene = SlicerScene(self)
        self.view = CanvasView(self)
        self.view.setScene(self.scene)

        self.h_ruler = HorizontalRuler(self.view, self)
        self.v_ruler = VerticalRuler(self.view, self)
        self.corner = RulerCorner(self)

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.addWidget(self.corner, 0, 0)
        grid.addWidget(self.h_ruler, 0, 1)
        grid.addWidget(self.v_ruler, 1, 0)
        grid.addWidget(self.view, 1, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(1, 1)

        # Overlay parented to the view so it sits over the canvas.
        self.overlay = CanvasOverlay(self.view)
        self.overlay.controls.zoom_in.connect(lambda: self.view.zoom(1.2))
        self.overlay.controls.zoom_out.connect(lambda: self.view.zoom(1 / 1.2))
        self.overlay.controls.fit.connect(self.view.fit_to_content)
        self.overlay.controls.reset.connect(self.view.reset_zoom)
        self.overlay.zoom_badge.clicked.connect(self.view.fit_to_content)

        self.view.cursorMoved.connect(self.overlay.coord.set_coords)
        self.view.transformChanged.connect(
            lambda: self.overlay.zoom_badge.set_percent(self.view.zoom_percent())
        )

    def apply_ruler_palette(self, tokens) -> None:  # type: ignore[no-untyped-def]
        c = tokens.color
        self.h_ruler.set_palette(tick=c.border_strong, text=c.muted, accent=c.accent, bg=c.surface)
        self.v_ruler.set_palette(tick=c.border_strong, text=c.muted, accent=c.accent, bg=c.surface)
        self.corner.setStyleSheet(f"background: {c.surface}; border-right: 1px solid {c.border}; border-bottom: 1px solid {c.border};")

    def cursor_signal(self):  # type: ignore[no-untyped-def]
        return self.view.cursorMoved
