"""QApplication bootstrap + theme initialisation."""
from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, QTimer
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
    from .. import portable
    from .widgets.view3d import prepare_app

    if portable.data_dir() is not None:  # nothing written outside the app folder (USB stick)
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DisableShaderDiskCache)
    prepare_app()  # the 3D renderer's URL scheme must exist before the QApplication
    app = QApplication(argv)
    app.setApplicationName("SlicerSegelinEnder3")
    app.setOrganizationName("SlicerSegelin")
    initial_theme = detect_initial_theme()
    apply_theme(app, initial_theme)
    window = MainWindow(initial_theme=initial_theme)
    window.show()
    # The block, the printer and the wire are the workspace: start in the 3D view (once the window has a size).
    QTimer.singleShot(0, lambda: window._view3d_action.setChecked(True))
    if "--selftest" in argv:
        _selftest(app, window)
    return app.exec()


def _selftest(app: QApplication, window: MainWindow) -> None:
    """``SlicerSegelin.exe --selftest``: open the 3D view, report which renderer runs, save a picture, quit.

    Writes ``selftest.txt`` and ``selftest_3d.png`` next to the program (or the working folder).
    """
    import platform
    import time
    from pathlib import Path

    from PyQt6.QtCore import QTimer

    out = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    t0 = time.perf_counter()
    window._view3d_action.setChecked(True)
    scene = window._viewer3d.scene if window._viewer3d is not None else None

    def finish(ok: bool = False) -> None:
        lines = [f"python {platform.python_version()} · {platform.platform()}",
                 f"3D renderer: {scene.backend_name if scene else 'none'}",
                 f"fallback reason: {scene.fallback_reason if scene else '-'}",
                 f"3D picture saved: {ok}", f"seconds: {time.perf_counter() - t0:.1f}"]
        (out / "selftest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        app.quit()

    def snap() -> None:
        if scene is None:
            finish()
            return
        scene.snapshot(str(out / "selftest_3d.png"), finish)
        QTimer.singleShot(5000, finish)

    QTimer.singleShot(6000, snap)


if __name__ == "__main__":
    sys.exit(run(sys.argv))
