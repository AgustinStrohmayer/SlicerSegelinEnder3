"""QApplication bootstrap + theme initialisation."""
from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication

from .main_window import MainWindow
from .theming.qss import render_qss
from .theming.tokens import ThemeName


def apply_theme(app: QApplication, theme: ThemeName) -> None:
    app.setStyleSheet(render_qss(theme))
    app.setProperty("theme", theme)


def detect_initial_theme() -> ThemeName:
    """Default to the OS scheme; fall back to dark."""
    hints = QGuiApplication.styleHints()
    try:
        scheme = hints.colorScheme()
    except AttributeError:  # Qt < 6.5
        return "dark"
    return "dark" if scheme == Qt.ColorScheme.Dark else "light"


def run(argv: list[str]) -> int:
    app = QApplication(argv)
    app.setApplicationName("SlicerSegelinEnder3")
    app.setOrganizationName("SlicerSegelin")
    initial_theme = detect_initial_theme()
    apply_theme(app, initial_theme)
    window = MainWindow(initial_theme=initial_theme)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run(sys.argv))
