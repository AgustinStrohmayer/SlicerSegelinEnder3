"""Main application window.

Hosts the canvas, dock widgets (sidebar / inspector / timeline),
menubar, toolbar and status bar. State of the world lives in
``Project``; this class only translates user gestures into commands.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..core.commands import CommandStack, FunctionCommand
from ..core.errors import DxfImportError
from ..core.project import Project
from .theming.icons import get_icon
from .theming.qss import render_qss
from .theming.tokens import ThemeName, get_tokens
from .widgets.canvas.graphics_view import CanvasView
from .widgets.canvas.scene import SlicerScene
from .widgets.command_palette import CommandEntry, CommandPalette, CommandRegistry
from .widgets.toast import ToastHost


class MainWindow(QMainWindow):
    def __init__(self, initial_theme: ThemeName = "dark") -> None:
        super().__init__()
        self.setWindowTitle("SlicerSegelinEnder3")
        self.resize(1440, 900)
        self.setMinimumSize(1024, 720)

        self.project = Project()
        self.history = CommandStack()
        self.theme: ThemeName = initial_theme

        # Canvas
        self.scene = SlicerScene(self)
        self.view = CanvasView(self)
        self.view.setScene(self.scene)
        self._apply_canvas_palette()
        self.setCentralWidget(self.view)

        # Toasts overlay
        self.toasts = ToastHost(self)

        # Command palette
        self.registry = CommandRegistry()
        self.palette = CommandPalette(self, self.registry)

        # Build chrome
        self._build_toolbar()
        self._build_menus()
        self._build_status_bar()
        self._build_docks()
        self._register_commands()

        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(self.palette.open)

        # Welcome
        self.toasts.show_toast(
            "Welcome to v2",
            "Press Ctrl+K to open the command palette.",
            severity="info",
        )

    # ─────────────────────────── chrome ───────────────────────────

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main toolbar", self)
        bar.setMovable(False)
        bar.setIconSize(self._icon_size())
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        self._toolbar = bar

        accent_color = get_tokens(self.theme).color.text

        def act(name: str, label: str, slot, shortcut: str | None = None) -> QAction:
            a = QAction(get_icon(name, accent_color), label, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            bar.addAction(a)
            return a

        act("folder-open", "Import DXF", self.action_import_dxf, "Ctrl+O")
        act("save", "Save project", self.action_save_project, "Ctrl+S")
        bar.addSeparator()
        act("undo", "Undo", self.action_undo, "Ctrl+Z")
        act("redo", "Redo", self.action_redo, "Ctrl+Shift+Z")
        bar.addSeparator()
        act("rotate-ccw", "Rotate −90°", lambda: self.action_rotate(-90))
        act("rotate-cw", "Rotate +90°", lambda: self.action_rotate(90))
        act("flip-horizontal", "Mirror horizontal", self.action_mirror_h)
        act("flip-vertical", "Mirror vertical", self.action_mirror_v)
        bar.addSeparator()

        from PyQt6.QtWidgets import QSizePolicy

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)

        act("command", "Command palette (Ctrl+K)", self.palette.open)
        self._theme_action = act(
            "moon" if self.theme == "light" else "sun",
            "Toggle theme",
            self.action_toggle_theme,
        )

    def _build_menus(self) -> None:
        mb = self.menuBar()

        def add(menu, text: str, slot, shortcut: str | None = None) -> QAction:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            menu.addAction(action)
            return action

        file_menu = mb.addMenu("&File")
        add(file_menu, "Import DXF…", self.action_import_dxf, "Ctrl+O")
        add(file_menu, "Save Project…", self.action_save_project, "Ctrl+S")
        add(file_menu, "Open Project…", self.action_open_project)
        add(file_menu, "Export G-code…", self.action_export_gcode, "Ctrl+E")
        file_menu.addSeparator()
        add(file_menu, "Exit", self.close, "Ctrl+Q")

        edit_menu = mb.addMenu("&Edit")
        add(edit_menu, "Undo", self.action_undo, "Ctrl+Z")
        add(edit_menu, "Redo", self.action_redo, "Ctrl+Shift+Z")

        view_menu = mb.addMenu("&View")
        add(view_menu, "Fit to content", lambda: self.view.fit_to_content(), "F")
        add(view_menu, "Toggle theme", self.action_toggle_theme, "Ctrl+T")

        transform_menu = mb.addMenu("&Transform")
        add(transform_menu, "Rotate −90°", lambda: self.action_rotate(-90))
        add(transform_menu, "Rotate +90°", lambda: self.action_rotate(90))
        add(transform_menu, "Mirror horizontal", self.action_mirror_h)
        add(transform_menu, "Mirror vertical", self.action_mirror_v)
        add(transform_menu, "Align to origin", self.action_align_origin)

    def _build_status_bar(self) -> None:
        sb = self.statusBar()
        self._coord_label = QLabel("Y 0.00   Z 0.00")
        self._coord_label.setProperty("class", "muted")
        self._count_label = QLabel("0 segments")
        self._count_label.setProperty("class", "muted")
        sb.addPermanentWidget(self._coord_label)
        sb.addPermanentWidget(self._count_label)
        sb.showMessage(f"Ready · theme: {self.theme}")

    def _build_docks(self) -> None:
        # Left sidebar
        sidebar = QWidget(self)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(12, 12, 12, 12)
        sl.setSpacing(12)
        title = QLabel("Layers & transforms")
        title.setObjectName("TitleLabel")
        sl.addWidget(title)
        hint = QLabel("Import a DXF to begin. The sidebar will populate with transform controls.")
        hint.setWordWrap(True)
        hint.setProperty("class", "muted")
        sl.addWidget(hint)
        sl.addStretch(1)
        left_dock = QDockWidget("Workspace", self)
        left_dock.setWidget(sidebar)
        left_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left_dock)

        # Right inspector
        inspector = QWidget(self)
        il = QVBoxLayout(inspector)
        il.setContentsMargins(12, 12, 12, 12)
        title2 = QLabel("Inspector")
        title2.setObjectName("TitleLabel")
        il.addWidget(title2)
        muted = QLabel("Select a segment in the canvas to view its properties.")
        muted.setWordWrap(True)
        muted.setProperty("class", "muted")
        il.addWidget(muted)
        il.addStretch(1)
        right_dock = QDockWidget("Inspector", self)
        right_dock.setWidget(inspector)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right_dock)

    def _register_commands(self) -> None:
        r = self.registry
        r.register(CommandEntry("file.import_dxf", "File: Import DXF…", self.action_import_dxf, "Ctrl+O"))
        r.register(CommandEntry("file.save_project", "File: Save Project…", self.action_save_project, "Ctrl+S"))
        r.register(CommandEntry("file.open_project", "File: Open Project…", self.action_open_project))
        r.register(CommandEntry("file.export_gcode", "File: Export G-code…", self.action_export_gcode, "Ctrl+E"))
        r.register(CommandEntry("edit.undo", "Edit: Undo", self.action_undo, "Ctrl+Z"))
        r.register(CommandEntry("edit.redo", "Edit: Redo", self.action_redo, "Ctrl+Shift+Z"))
        r.register(CommandEntry("transform.rotate_ccw", "Transform: Rotate −90°", lambda: self.action_rotate(-90)))
        r.register(CommandEntry("transform.rotate_cw", "Transform: Rotate +90°", lambda: self.action_rotate(90)))
        r.register(CommandEntry("transform.mirror_h", "Transform: Mirror horizontal", self.action_mirror_h))
        r.register(CommandEntry("transform.mirror_v", "Transform: Mirror vertical", self.action_mirror_v))
        r.register(CommandEntry("transform.align_origin", "Transform: Align to origin", self.action_align_origin))
        r.register(CommandEntry("view.fit", "View: Fit to content", lambda: self.view.fit_to_content(), "F"))
        r.register(CommandEntry("view.toggle_theme", "View: Toggle theme", self.action_toggle_theme, "Ctrl+T"))

    # ─────────────────────────── actions ───────────────────────────

    def action_import_dxf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import DXF", filter="DXF files (*.dxf)")
        if not path:
            return
        try:
            from ..io.dxf_reader import read_dxf

            segments = read_dxf(path)
        except DxfImportError as exc:
            self.toasts.show_toast("DXF import failed", str(exc), severity="danger")
            return

        previous = list(self.project.segments)

        def do() -> None:
            self.project.replace_segments(segments)
            self._refresh_scene()

        def undo() -> None:
            self.project.replace_segments(previous)
            self._refresh_scene()

        self.history.push(FunctionCommand(label="Import DXF", do_fn=do, undo_fn=undo))
        self.toasts.show_toast("DXF imported", f"{len(segments)} segments", severity="success")

    def action_save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", filter="Slicer project (*.ssp)")
        if not path:
            return
        from ..io.project_io import save

        try:
            save(path, self.project)
            self.toasts.show_toast("Saved", path, severity="success")
        except Exception as exc:  # noqa: BLE001
            self.toasts.show_toast("Save failed", str(exc), severity="danger")

    def action_open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", filter="Slicer project (*.ssp)")
        if not path:
            return
        from ..io.project_io import load

        try:
            project = load(path)
        except Exception as exc:  # noqa: BLE001
            self.toasts.show_toast("Open failed", str(exc), severity="danger")
            return
        self.project = project
        self.history.clear()
        self._refresh_scene()
        self.toasts.show_toast("Project loaded", path, severity="success")

    def action_export_gcode(self) -> None:
        if not self.project.segments:
            self.toasts.show_toast("Nothing to export", "Import a DXF first.", severity="warning")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export G-code", filter="G-code (*.gcode)")
        if not path:
            return
        from ..io.gcode_writer import emit_gcode
        from ..services.slicer_service import build_cut_plan

        plan = build_cut_plan(self.project.segments, self.project.machine)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(emit_gcode(plan))
            self.toasts.show_toast("G-code exported", path, severity="success")
        except Exception as exc:  # noqa: BLE001
            self.toasts.show_toast("Export failed", str(exc), severity="danger")

    def action_undo(self) -> None:
        cmd = self.history.undo()
        if cmd is None:
            self.toasts.show_toast("Nothing to undo", severity="warning")

    def action_redo(self) -> None:
        cmd = self.history.redo()
        if cmd is None:
            self.toasts.show_toast("Nothing to redo", severity="warning")

    def action_rotate(self, deg: float) -> None:
        from ..core.transforms import rotate_around_center

        previous = list(self.project.segments)
        try:
            rotated = rotate_around_center(previous, deg)
        except Exception as exc:  # noqa: BLE001
            self.toasts.show_toast("Cannot rotate", str(exc), severity="warning")
            return

        def do() -> None:
            self.project.replace_segments(rotated)
            self._refresh_scene()

        def undo() -> None:
            self.project.replace_segments(previous)
            self._refresh_scene()

        self.history.push(FunctionCommand(label=f"Rotate {deg:+g}°", do_fn=do, undo_fn=undo))

    def action_mirror_h(self) -> None:
        self._mirror_command(horizontal=True)

    def action_mirror_v(self) -> None:
        self._mirror_command(horizontal=False)

    def _mirror_command(self, horizontal: bool) -> None:
        from ..core.transforms import mirror_horizontal, mirror_vertical

        previous = list(self.project.segments)
        new = mirror_horizontal(previous) if horizontal else mirror_vertical(previous)
        label = "Mirror horizontal" if horizontal else "Mirror vertical"

        def do() -> None:
            self.project.replace_segments(new)
            self._refresh_scene()

        def undo() -> None:
            self.project.replace_segments(previous)
            self._refresh_scene()

        self.history.push(FunctionCommand(label=label, do_fn=do, undo_fn=undo))

    def action_align_origin(self) -> None:
        from ..core.transforms import align_to_origin

        previous = list(self.project.segments)
        new = align_to_origin(previous)

        def do() -> None:
            self.project.replace_segments(new)
            self._refresh_scene()

        def undo() -> None:
            self.project.replace_segments(previous)
            self._refresh_scene()

        self.history.push(FunctionCommand(label="Align to origin", do_fn=do, undo_fn=undo))

    def action_toggle_theme(self) -> None:
        self.theme = "light" if self.theme == "dark" else "dark"
        app = self._app()
        if app is not None:
            app.setStyleSheet(render_qss(self.theme))
            app.setProperty("theme", self.theme)
        self._apply_canvas_palette()
        self.statusBar().showMessage(f"Theme: {self.theme}", 2000)
        self.toasts.show_toast(f"Theme: {self.theme}", severity="info", duration_ms=1500)

    # ─────────────────────────── helpers ───────────────────────────

    def _refresh_scene(self) -> None:
        self.scene.render_segments(self.project.segments)
        self._count_label.setText(f"{len(self.project.segments)} segments")
        self.view.fit_to_content()

    def _apply_canvas_palette(self) -> None:
        tokens = get_tokens(self.theme)
        self.scene.set_palette(background=tokens.color.bg, grid=tokens.color.border)

    def _icon_size(self):
        from PyQt6.QtCore import QSize

        return QSize(18, 18)

    def _app(self):
        from PyQt6.QtWidgets import QApplication

        return QApplication.instance()
