"""Floating widgets layered on top of the canvas.

* :class:`CanvasOverlay` — repositions its children whenever the
  container resizes (top-left controls, bottom-right coord, etc.).
* :class:`FloatingControls` — zoom in/out, fit, reset; lives in the
  top-left corner of the canvas.
* :class:`CoordReadout` — bottom-right ``Y x.xx  Z x.xx mm`` chip.
* :class:`ZoomBadge` — bottom-left zoom percentage chip.
* :class:`EmptyState` — centered call-to-action when no DXF is loaded.
"""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QResizeEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...theming.icons import get_icon, set_icon


class FloatingControls(QFrame):
    zoom_in = pyqtSignal()
    zoom_out = pyqtSignal()
    fit = pyqtSignal()
    reset = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FloatingControls")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        for icon, signal, tip in (
            ("zoom-in", self.zoom_in, "Zoom in"),
            ("zoom-out", self.zoom_out, "Zoom out"),
            ("maximize", self.fit, "Fit to content (F)"),
            ("repeat", self.reset, "Reset zoom"),
        ):
            b = QToolButton(self)
            b.setObjectName("CanvasFloatBtn")
            set_icon(b, icon, "#888888", 16)  # recoloured per theme by MainWindow._recolor_icons
            b.setIconSize(QSize(16, 16))
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(signal.emit)
            lay.addWidget(b)


class CoordReadout(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Y  0.00   Z  0.00 mm", parent)
        self.setObjectName("CoordReadout")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_coords(self, y: float, z: float) -> None:
        self.setText(f"Y {y:7.2f}  Z {z:7.2f} mm")


class ZoomBadge(QLabel):
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("100%", parent)
        self.setObjectName("ZoomBadge")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Reset zoom")

    def set_percent(self, percent: int) -> None:
        self.setText(f"{percent}%")

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class EmptyState(QFrame):
    import_requested = pyqtSignal()
    open_project_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("EmptyState")
        self.setAcceptDrops(True)

        wrap = QVBoxLayout(self)
        wrap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrap.setSpacing(14)

        icon = QLabel(self)
        icon.setObjectName("EmptyStateIcon")
        icon.setPixmap(get_icon("file", "#7C5CFF", 36).pixmap(36, 36))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrap.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Load a DXF to begin")
        title.setProperty("role", "title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrap.addWidget(title)

        cap = QLabel("Drop a .dxf or .ssproj file here, or use the button below.")
        cap.setProperty("class", "muted")
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrap.addWidget(cap)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b_import = QPushButton(get_icon("folder-open", "#FFFFFF"), "  Import DXF")
        b_import.setProperty("role", "primary")
        b_import.setProperty("size", "lg")
        b_import.clicked.connect(self.import_requested.emit)
        row.addWidget(b_import)
        b_open = QPushButton(get_icon("folder-open"), "  Open project")
        b_open.setProperty("size", "lg")
        b_open.clicked.connect(self.open_project_requested.emit)
        row.addWidget(b_open)
        wrap.addLayout(row)


class CanvasOverlay(QWidget):
    """Container that places overlay widgets at fixed corners over the canvas."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.controls = FloatingControls(self)
        self.coord = CoordReadout(self)
        self.zoom_badge = ZoomBadge(self)
        self.setStyleSheet("background: transparent;")
        parent.installEventFilter(self)
        self._reposition()

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if event.type() in (event.Type.Resize, event.Type.Show):
            self._reposition()
        return False

    def resizeEvent(self, event: QResizeEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._reposition()

    def _reposition(self) -> None:
        if self.parent() is None:
            return
        parent = self.parent()
        rect = parent.rect()  # type: ignore[union-attr]
        self.setGeometry(rect)
        m = 12
        self.controls.adjustSize()
        self.controls.move(m, m)
        self.coord.adjustSize()
        self.coord.move(rect.right() - self.coord.width() - m, rect.bottom() - self.coord.height() - m)
        self.zoom_badge.adjustSize()
        self.zoom_badge.move(m, rect.bottom() - self.zoom_badge.height() - m)
