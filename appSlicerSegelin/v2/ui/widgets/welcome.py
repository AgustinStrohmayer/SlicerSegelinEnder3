"""First-run / cold-start welcome screen.

Centered card with the brand mark, three big CTAs (Import DXF, Open
Project, New project) and a list of recent files. Accepts drag-and-
drop of ``.dxf`` and ``.ssproj``. Hidden as soon as geometry exists.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...io.recent_files import RecentFiles
from ..theming.icons import get_icon


class WelcomeScreen(QFrame):
    import_requested = pyqtSignal()
    open_project_requested = pyqtSignal()
    new_project_requested = pyqtSignal()
    open_path_requested = pyqtSignal(str)

    def __init__(self, recents: RecentFiles, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Welcome")
        self.setAcceptDrops(True)
        self._recents = recents

        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("WelcomeCard")
        card.setMaximumWidth(720)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

        col = QVBoxLayout(card)
        col.setSpacing(16)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(get_icon("logo", "#7C5CFF", 36).pixmap(36, 36))
        brand.addWidget(logo)
        brand.addWidget(self._title("SlicerSegelinEnder3"))
        brand.addStretch(1)
        col.addLayout(brand)

        col.addWidget(self._caption(
            "Hot-wire CNC slicer for Ender-3 — turn DXFs into machine-ready G-code."
        ))

        # CTA buttons
        cta = QHBoxLayout()
        cta.setSpacing(10)
        b_dxf = self._primary_btn(get_icon("folder-open", "#FFFFFF"), "Import DXF")
        b_dxf.clicked.connect(self.import_requested.emit)
        cta.addWidget(b_dxf)
        b_open = self._secondary_btn(get_icon("folder-open"), "Open project")
        b_open.clicked.connect(self.open_project_requested.emit)
        cta.addWidget(b_open)
        b_new = self._ghost_btn("New project")
        b_new.clicked.connect(self.new_project_requested.emit)
        cta.addWidget(b_new)
        cta.addStretch(1)
        col.addLayout(cta)

        # Recents
        col.addSpacing(6)
        col.addWidget(self._section_label("Recent"))
        self._recent_container = QVBoxLayout()
        self._recent_container.setSpacing(6)
        col.addLayout(self._recent_container)

        col.addStretch(1)
        col.addWidget(self._hint("Tip: drop a .dxf or .ssproj anywhere on this window."))
        self.refresh_recents()

    # ── recents ──────────────────────────────────────────────────────
    def refresh_recents(self) -> None:
        while self._recent_container.count():
            item = self._recent_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        items = list(self._recents.items)
        if not items:
            empty = QLabel("No recent files yet — your imports and projects will appear here.")
            empty.setProperty("class", "muted")
            self._recent_container.addWidget(empty)
            return
        for path in items[:6]:
            self._recent_container.addWidget(self._recent_row(path))

    def _recent_row(self, path: str) -> QFrame:
        row = QFrame()
        row.setObjectName("RecentItem")
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        p = Path(path)
        icon = QLabel()
        icon_name = "file"
        if p.suffix.lower() == ".ssproj":
            icon_name = "save"
        elif p.suffix.lower() == ".dxf":
            icon_name = "file"
        icon.setPixmap(get_icon(icon_name, "#7C5CFF", 18).pixmap(18, 18))
        lay.addWidget(icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name = QLabel(p.name)
        name.setProperty("role", "title")
        text_col.addWidget(name)
        sub = QLabel(str(p.parent))
        sub.setProperty("class", "muted")
        text_col.addWidget(sub)
        lay.addLayout(text_col, 1)

        kind = QLabel(p.suffix.lstrip(".").upper() or "FILE")
        kind.setProperty("class", "muted")
        lay.addWidget(kind)

        row.mousePressEvent = lambda _e, _p=str(p): self.open_path_requested.emit(_p)  # type: ignore[method-assign]
        return row

    # ── drag and drop ────────────────────────────────────────────────
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self.open_path_requested.emit(local)
                break
        event.acceptProposedAction()

    # ── style helpers ────────────────────────────────────────────────
    def _title(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("role", "display")
        return lbl

    def _caption(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("class", "muted")
        return lbl

    def _hint(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("class", "muted")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lbl

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("FieldLabel")
        return lbl

    def _primary_btn(self, icon, text: str) -> QPushButton:  # type: ignore[no-untyped-def]
        b = QPushButton(icon, "  " + text)
        b.setProperty("role", "primary")
        b.setProperty("size", "lg")
        b.setIconSize(QSize(16, 16))
        return b

    def _secondary_btn(self, icon, text: str) -> QPushButton:  # type: ignore[no-untyped-def]
        b = QPushButton(icon, "  " + text)
        b.setProperty("size", "lg")
        b.setIconSize(QSize(16, 16))
        return b

    def _ghost_btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("role", "ghost")
        b.setProperty("size", "lg")
        return b
