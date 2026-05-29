"""Main application window.

Assembles the sidebar (all transform/cut/export controls), the central
canvas, the bottom simulation timeline, toolbar, menus, command palette
and toast notifications, and wires them to a :class:`ProjectController`.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QSizePolicy,
    QToolBar,
    QWidget,
)

from ..core.geometry import Point
from .controllers.project_controller import ProjectController
from .theming.icons import get_icon
from .theming.qss import render_qss
from .theming.tokens import ThemeName, get_tokens
from .widgets.canvas.graphics_view import CanvasView
from .widgets.canvas.scene import SceneModel, ScenePalette, SlicerScene
from .widgets.command_palette import CommandEntry, CommandPalette, CommandRegistry
from .widgets.sidebar.sidebar import Sidebar
from .widgets.timeline.timeline import Timeline
from .widgets.toast import ToastHost


class MainWindow(QMainWindow):
    def __init__(self, initial_theme: ThemeName = "dark") -> None:
        super().__init__()
        self.setWindowTitle("SlicerSegelinEnder3")
        self.resize(1500, 940)
        self.setMinimumSize(1080, 720)
        self.theme: ThemeName = initial_theme

        self.controller = ProjectController()

        # Canvas
        self.scene = SlicerScene(self)
        self.view = CanvasView(self)
        self.view.setScene(self.scene)
        self.view.clicked.connect(self._on_canvas_click)
        self.setCentralWidget(self.view)
        self._apply_scene_palette()

        # Toasts + palette
        self.toasts = ToastHost(self)
        self.registry = CommandRegistry()
        self.palette = CommandPalette(self, self.registry)

        # Docks
        self._build_sidebar()
        self._build_timeline()

        # Chrome
        self._build_toolbar()
        self._build_menus()
        self._build_status_bar()
        self._register_commands()

        # Simulation timer
        self._sim_timer = QTimer(self)
        self._sim_timer.setInterval(30)
        self._sim_timer.timeout.connect(self._on_sim_tick)
        self._sim_start = 0.0
        self._sim_total = 0.0

        # Diagonal-cut picking state
        self._picking_diagonal = False
        self._diag_first: Point | None = None

        # Wire controller
        self.controller.changed.connect(self._refresh_canvas)
        self.controller.changed.connect(self._refresh_info)
        self.controller.info_changed.connect(self._refresh_info)
        self.controller.layers_changed.connect(self._refresh_canvas)
        self.controller.notify.connect(self._on_notify)

        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(self.palette.open)

        self._refresh_canvas()
        self._refresh_info()
        self.toasts.show_toast("Welcome", "Load a DXF (Ctrl+O) — Ctrl+K for commands.", "info")

    # ── docks ─────────────────────────────────────────────────────────
    def _build_sidebar(self) -> None:
        self.sidebar = Sidebar(self.controller, self)
        self.sidebar.import_requested.connect(self._on_import)
        self.sidebar.export_gcode_requested.connect(self._on_export_gcode)
        self.sidebar.export_dxf_requested.connect(self._on_export_dxf)
        self.sidebar.export_batch_requested.connect(self._on_export_batch)
        self.sidebar.diagonal_requested.connect(self._start_diagonal_pick)
        dock = QDockWidget("Workspace", self)
        dock.setObjectName("SidebarDock")
        dock.setWidget(self.sidebar)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        dock.setMinimumWidth(320)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_timeline(self) -> None:
        self.timeline = Timeline(self)
        self.timeline.play_toggled.connect(self._on_play_toggled)
        self.timeline.scrubbed.connect(lambda _v: self._on_scrub())
        dock = QDockWidget("Simulation", self)
        dock.setObjectName("TimelineDock")
        dock.setWidget(self.timeline)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    # ── chrome ────────────────────────────────────────────────────────
    def _build_toolbar(self) -> None:
        bar = QToolBar("Main", self)
        bar.setMovable(False)
        bar.setIconSize(QSize(18, 18))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        self._toolbar = bar
        col = get_tokens(self.theme).color.text

        def act(name, label, slot, shortcut=None):
            a = QAction(get_icon(name, col), label, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            bar.addAction(a)
            return a

        act("folder-open", "Import DXF", self._on_import_dialog, "Ctrl+O")
        act("save", "Export G-code", self._on_export_gcode, "Ctrl+E")
        bar.addSeparator()
        act("undo", "Undo", self._on_undo, "Ctrl+Z")
        act("redo", "Redo", self._on_redo, "Ctrl+Shift+Z")
        bar.addSeparator()
        act("rotate-ccw", "Rotate −90°", lambda: self.controller.rotate(-90))
        act("rotate-cw", "Rotate +90°", lambda: self.controller.rotate(90))
        act("flip-horizontal", "Mirror V", self.controller.mirror_vertical)
        act("flip-vertical", "Mirror H", self.controller.mirror_horizontal)
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        act("command", "Command palette (Ctrl+K)", self.palette.open)
        self._theme_action = act("moon" if self.theme == "light" else "sun", "Toggle theme", self._toggle_theme, "Ctrl+T")

    def _build_menus(self) -> None:
        mb = self.menuBar()

        def add(menu, text, slot, shortcut=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(slot)
            menu.addAction(a)

        m = mb.addMenu("&File")
        add(m, "Import DXF…", self._on_import_dialog, "Ctrl+O")
        add(m, "Open Project…", self._on_open_project)
        add(m, "Save Project…", self._on_save_project, "Ctrl+S")
        m.addSeparator()
        add(m, "Export G-code…", self._on_export_gcode, "Ctrl+E")
        add(m, "Export modified DXF…", self._on_export_dxf)
        add(m, "Export plates batch…", self._on_export_batch)
        m.addSeparator()
        add(m, "Exit", self.close, "Ctrl+Q")

        m = mb.addMenu("&Edit")
        add(m, "Undo", self._on_undo, "Ctrl+Z")
        add(m, "Redo", self._on_redo, "Ctrl+Shift+Z")

        m = mb.addMenu("&Transform")
        add(m, "Rotate 90°", lambda: self.controller.rotate(90))
        add(m, "Auto height", self.controller.auto_height)
        add(m, "Mirror vertical", self.controller.mirror_vertical)
        add(m, "Mirror horizontal", self.controller.mirror_horizontal)
        add(m, "Align origin to cut", self.controller.align_origin)
        add(m, "Reverse cut direction", self.controller.toggle_reverse)

        m = mb.addMenu("&View")
        add(m, "Fit to content", self.view.fit_to_content, "F")
        add(m, "Toggle theme", self._toggle_theme, "Ctrl+T")

    def _build_status_bar(self) -> None:
        self.statusBar().showMessage(f"Ready · {self.theme}")

    def _register_commands(self) -> None:
        r = self.registry
        r.register(CommandEntry("file.import", "File: Import DXF…", self._on_import_dialog, "Ctrl+O"))
        r.register(CommandEntry("file.open", "File: Open Project…", self._on_open_project))
        r.register(CommandEntry("file.save", "File: Save Project…", self._on_save_project, "Ctrl+S"))
        r.register(CommandEntry("file.gcode", "File: Export G-code…", self._on_export_gcode, "Ctrl+E"))
        r.register(CommandEntry("file.dxf", "File: Export modified DXF…", self._on_export_dxf))
        r.register(CommandEntry("file.batch", "File: Export plates batch…", self._on_export_batch))
        r.register(CommandEntry("edit.undo", "Edit: Undo", self._on_undo, "Ctrl+Z"))
        r.register(CommandEntry("edit.redo", "Edit: Redo", self._on_redo, "Ctrl+Shift+Z"))
        r.register(CommandEntry("tf.rot90", "Transform: Rotate 90°", lambda: self.controller.rotate(90)))
        r.register(CommandEntry("tf.auto", "Transform: Auto height", self.controller.auto_height))
        r.register(CommandEntry("tf.mv", "Transform: Mirror vertical", self.controller.mirror_vertical))
        r.register(CommandEntry("tf.mh", "Transform: Mirror horizontal", self.controller.mirror_horizontal))
        r.register(CommandEntry("tf.align", "Transform: Align origin to cut", self.controller.align_origin))
        r.register(CommandEntry("tf.rev", "Transform: Reverse cut direction", self.controller.toggle_reverse))
        r.register(CommandEntry("view.fit", "View: Fit to content", self.view.fit_to_content, "F"))
        r.register(CommandEntry("view.theme", "View: Toggle theme", self._toggle_theme, "Ctrl+T"))
        r.register(CommandEntry("preview.gen", "Preview: Generate plates/parts", self.controller.generate_preview))

    # ── file dialogs / actions ────────────────────────────────────────
    def _on_import_dialog(self) -> None:
        self.sidebar._on_import()

    def _on_import(self, use_units: bool, scale: float) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import DXF", filter="DXF files (*.dxf)")
        if path:
            self.controller.import_dxf(path, use_units, scale)
            self.view.fit_to_content()

    def _on_export_gcode(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export G-code", filter="G-code (*.gcode)")
        if path:
            self.controller.export_standard_gcode(path)

    def _on_export_dxf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export modified DXF", filter="DXF (*.dxf)")
        if path:
            self.controller.export_dxf(path)

    def _on_export_batch(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder for plate batch")
        if folder:
            self.controller.export_layers_gcode(folder)

    def _on_save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Project", filter="Slicer project (*.ssp)")
        if not path:
            return
        from ..io.project_io import save

        try:
            save(path, self.controller.project)
            self.toasts.show_toast("Saved", path, "success")
        except Exception as exc:
            self.toasts.show_toast("Save failed", str(exc), "danger")

    def _on_open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", filter="Slicer project (*.ssp)")
        if not path:
            return
        from ..io.project_io import load

        try:
            project = load(path)
        except Exception as exc:
            self.toasts.show_toast("Open failed", str(exc), "danger")
            return
        self.controller.project = project
        self.controller.history.clear()
        self.controller.layers = []
        self.controller.focused_layer = -1
        self.controller.changed.emit()
        self.controller.info_changed.emit()
        self.view.fit_to_content()
        self.toasts.show_toast("Project loaded", path, "success")

    def _on_undo(self) -> None:
        if not self.controller.undo():
            self.toasts.show_toast("Nothing to undo", "", "warning")

    def _on_redo(self) -> None:
        if not self.controller.redo():
            self.toasts.show_toast("Nothing to redo", "", "warning")

    # ── diagonal manual-cut picking ───────────────────────────────────
    def _start_diagonal_pick(self) -> None:
        if not self.controller.has_geometry:
            self.toasts.show_toast("Load a DXF first", "", "warning")
            return
        self._picking_diagonal = True
        self._diag_first = None
        self.sidebar.set_diagonal_status("Diagonal: click P1 on the canvas")

    def _on_canvas_click(self, scene_y: float, scene_z: float) -> None:
        if not self._picking_diagonal:
            return
        # canvas coords are machine coords → convert to base for the cut
        base = Point(scene_y - self.controller.project.offset_y, scene_z - self.controller.project.offset_z)
        if self._diag_first is None:
            self._diag_first = base
            self.sidebar.set_diagonal_status("Diagonal: click P2")
            return
        ok = self.controller.add_manual_diagonal(self._diag_first, base)
        self._picking_diagonal = False
        self._diag_first = None
        self.sidebar.set_diagonal_status("Diagonal: inactive" if ok else "Diagonal: failed, retry")

    # ── simulation ────────────────────────────────────────────────────
    def _on_play_toggled(self, playing: bool) -> None:
        if playing:
            traj = self.controller.active_trajectory()
            self._sim_total = self.controller.estimated_time_s()
            if self._sim_total <= 0 or not traj:
                self.timeline.set_play_state(False)
                return
            start_fraction = self.timeline.progress_fraction()
            if start_fraction >= 1.0:
                start_fraction = 0.0
            self._sim_start = time.perf_counter() - start_fraction * self._sim_total
            self._sim_timer.start()
        else:
            self._sim_timer.stop()

    def _on_sim_tick(self) -> None:
        elapsed = time.perf_counter() - self._sim_start
        fraction = elapsed / self._sim_total if self._sim_total > 0 else 1.0
        if fraction >= 1.0:
            fraction = 1.0
            self._sim_timer.stop()
            self.timeline.set_play_state(False)
        self.timeline.set_progress_fraction(fraction)
        self._refresh_canvas()
        self._refresh_info()

    def _on_scrub(self) -> None:
        if self._sim_timer.isActive():
            self._sim_timer.stop()
            self.timeline.set_play_state(False)
        self._refresh_canvas()
        self._refresh_info()

    # ── refresh ───────────────────────────────────────────────────────
    def _current_view_geometry(self):
        c = self.controller
        if 0 <= c.focused_layer < len(c.layers):
            layer = c.layers[c.focused_layer]
            return layer.local_segments, layer.trajectory, None, []
        machine = c.project.machine_segments()
        traj = c.active_trajectory()
        entry = traj[0].a if traj else None
        manual = []
        if c.project.use_manual_cuts:
            manual = [cut.to_machine_line(c.project.offset_y, c.project.offset_z) for cut in c.project.manual_cuts]
        return machine, traj, entry, manual

    def _refresh_canvas(self) -> None:
        c = self.controller
        segments, traj, entry, manual = self._current_view_geometry()
        fraction = self.timeline.progress_fraction()
        focused = 0 <= c.focused_layer < len(c.layers)
        model = SceneModel(
            segments=segments,
            trajectory=traj,
            progress=fraction * len(traj),
            entry_point=entry,
            manual_lines=manual,
            bed_y=c.project.area_y_mm,
            bed_z=c.project.area_z_mm,
            show_bed=not focused,
            show_grid=c.project.view.show_grid,
        )
        self.scene.render(model)

    def _refresh_info(self) -> None:
        c = self.controller
        est = c.estimated_time_s()
        fraction = self.timeline.progress_fraction()
        height = c.cut_height()
        z_min, z_max = (height if height else (None, None))
        dims = c.dimensions()
        self.timeline.set_info(est, est * fraction, z_min, z_max, dims)

    # ── notifications + theme ─────────────────────────────────────────
    def _on_notify(self, title: str, body: str, severity: str) -> None:
        self.toasts.show_toast(title, body, severity)  # type: ignore[arg-type]

    def _apply_scene_palette(self) -> None:
        t = get_tokens(self.theme).color
        self.scene.set_palette(
            ScenePalette(
                background=t.bg, grid=t.border, axis=t.accent, cut=t.accent,
                entry=t.success, exit=t.danger, travel=t.muted, union=t.warning, danger=t.danger,
            )
        )

    def _toggle_theme(self) -> None:
        self.theme = "light" if self.theme == "dark" else "dark"
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(render_qss(self.theme))
            app.setProperty("theme", self.theme)
        self._apply_scene_palette()
        self._refresh_canvas()
        self.statusBar().showMessage(f"Theme: {self.theme}", 2000)
