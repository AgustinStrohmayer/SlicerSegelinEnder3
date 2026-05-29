"""Main application window — premium shell.

Layers: top toolbar + menu, vertical-nav sidebar (left), stacked
central area (welcome ↔ canvas), bottom simulation timeline, live
status bar, floating toast host, command palette and shortcuts
overlay. Wired to a :class:`ProjectController` for all state.
"""
from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from ..core.geometry import Point
from ..io.recent_files import RecentFiles
from .controllers.project_controller import ProjectController
from .theming.effects import apply_elevation
from .theming.icons import get_icon
from .theming.qss import render_qss
from .theming.tokens import ThemeName, get_tokens
from .widgets.canvas.canvas_container import CanvasContainer
from .widgets.canvas.scene import SceneModel, ScenePalette
from .widgets.command_palette import CommandEntry, CommandPalette, CommandRegistry
from .widgets.recent_menu import RecentMenu
from .widgets.shortcuts_overlay import ShortcutsOverlay
from .widgets.sidebar.sidebar import Sidebar
from .widgets.timeline.timeline import Timeline
from .widgets.toast import ToastHost
from .widgets.welcome import WelcomeScreen


def _recents_path() -> Path:
    base = Path.home() / ".slicer_segelin"
    return base / "recent.json"


class MainWindow(QMainWindow):
    def __init__(self, initial_theme: ThemeName = "dark") -> None:
        super().__init__()
        self.setWindowTitle("SlicerSegelinEnder3")
        self.setWindowIcon(get_icon("logo", "#7C5CFF", 32))
        self.resize(1600, 980)
        self.setMinimumSize(1180, 760)
        self.setAcceptDrops(True)
        self.theme: ThemeName = initial_theme

        self.controller = ProjectController()
        self.recents = RecentFiles(_recents_path()).load()

        # Central stacked area: welcome ↔ canvas
        self.canvas = CanvasContainer(self)
        self.canvas.view.clicked.connect(self._on_canvas_click)
        self._apply_scene_palette()

        self.welcome = WelcomeScreen(self.recents, self)
        self.welcome.import_requested.connect(self._on_import_dialog)
        self.welcome.open_project_requested.connect(self._on_open_project)
        self.welcome.new_project_requested.connect(self._on_new_project)
        self.welcome.open_path_requested.connect(self._open_path)

        self.central_stack = QStackedWidget(self)
        self.central_stack.addWidget(self.welcome)
        self.central_stack.addWidget(self.canvas)
        self.setCentralWidget(self.central_stack)

        # Overlays
        self.toasts = ToastHost(self)
        self.registry = CommandRegistry()
        self.palette = CommandPalette(self, self.registry)
        apply_elevation(self.palette, get_tokens(self.theme), "lg")
        self.shortcuts_overlay: ShortcutsOverlay | None = None

        # Chrome
        self._build_sidebar()
        self._build_timeline()
        self._build_toolbar()
        self._build_menus()
        self._build_status_bar()
        self._register_commands()
        # Shortcuts overlay needs the registry populated first
        self.shortcuts_overlay = ShortcutsOverlay(self.registry, self)
        apply_elevation(self.shortcuts_overlay, get_tokens(self.theme), "lg")

        # Simulation timer
        self._sim_timer = QTimer(self)
        self._sim_timer.setInterval(30)
        self._sim_timer.timeout.connect(self._on_sim_tick)
        self._sim_start = 0.0
        self._sim_total = 0.0

        self._picking_diagonal = False
        self._diag_first: Point | None = None

        # Wire controller
        self.controller.changed.connect(self._refresh_canvas)
        self.controller.changed.connect(self._refresh_info)
        self.controller.changed.connect(self._refresh_central_stack)
        self.controller.info_changed.connect(self._refresh_info)
        self.controller.layers_changed.connect(self._refresh_canvas)
        self.controller.notify.connect(self._on_notify)
        self.canvas.view.cursorMoved.connect(self._on_cursor_moved)
        self.canvas.view.transformChanged.connect(self._on_transform_changed)

        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(self.palette.open)
        QShortcut(QKeySequence("?"), self).activated.connect(self._open_shortcuts_overlay)
        QShortcut(QKeySequence("Shift+/"), self).activated.connect(self._open_shortcuts_overlay)

        self._refresh_central_stack()
        self._refresh_info()
        QTimer.singleShot(
            800,
            lambda: self.toasts.show_toast(
                "Ready", "Drop a DXF anywhere, or press Ctrl+O to import.", "info",
            ),
        )

    # ── docks ─────────────────────────────────────────────────────────
    def _build_sidebar(self) -> None:
        self.sidebar = Sidebar(self.controller, self)
        self.sidebar.import_requested.connect(self._on_import)
        self.sidebar.save_archive_requested.connect(self._on_save_archive)
        self.sidebar.open_archive_requested.connect(self._on_open_project)
        self.sidebar.export_gcode_requested.connect(self._on_export_gcode)
        self.sidebar.export_dxf_requested.connect(self._on_export_dxf)
        self.sidebar.export_batch_requested.connect(self._on_export_batch)
        self.sidebar.diagonal_requested.connect(self._start_diagonal_pick)
        self.sidebar.toggle_theme_requested.connect(self._toggle_theme)
        self.sidebar.open_shortcuts_requested.connect(self._open_shortcuts_overlay)

        dock = QDockWidget(" ", self)
        dock.setObjectName("SidebarDock")
        dock.setTitleBarWidget(QWidget(self))  # hide default title bar
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setWidget(self.sidebar)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_timeline(self) -> None:
        self.timeline = Timeline(self)
        self.timeline.play_toggled.connect(self._on_play_toggled)
        self.timeline.scrubbed.connect(lambda _v: self._on_scrub())
        dock = QDockWidget(" ", self)
        dock.setObjectName("TimelineDock")
        dock.setTitleBarWidget(QWidget(self))
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setWidget(self.timeline)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    # ── chrome ────────────────────────────────────────────────────────
    def _build_toolbar(self) -> None:
        bar = QToolBar("Main", self)
        bar.setMovable(False)
        bar.setIconSize(QSize(18, 18))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        self._toolbar = bar

        col = get_tokens(self.theme).color.text

        def act(name, label, slot, shortcut=None, tooltip=None):
            a = QAction(get_icon(name, col), label, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
                a.setToolTip(f"{tooltip or label} ({shortcut})")
            else:
                a.setToolTip(tooltip or label)
            bar.addAction(a)
            return a

        act("folder-open", "Import DXF", self._on_import_dialog, "Ctrl+O", "Import a DXF file")
        act("save", "Save project", self._on_save_archive, "Ctrl+S", "Save project as .ssproj archive")

        # Recent files dropdown
        recent_btn = QToolButton(self)
        recent_btn.setIcon(get_icon("file", col))
        recent_btn.setText("Recent")
        recent_btn.setToolTip("Open a recent file")
        recent_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.recent_menu = RecentMenu(self.recents, self)
        self.recent_menu.file_chosen.connect(self._open_path)
        recent_btn.setMenu(self.recent_menu)
        bar.addWidget(recent_btn)

        bar.addSeparator()
        act("undo", "Undo", self._on_undo, "Ctrl+Z", "Undo last action")
        act("redo", "Redo", self._on_redo, "Ctrl+Shift+Z", "Redo last undone action")
        bar.addSeparator()
        act("rotate-cw", "Rotate 90°", lambda: self.controller.rotate(90), tooltip="Rotate 90° clockwise")
        act("flip-horizontal", "Mirror V", self.controller.mirror_vertical, tooltip="Mirror vertical")
        act("flip-vertical", "Mirror H", self.controller.mirror_horizontal, tooltip="Mirror horizontal")

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)

        act("command", "Command palette", self.palette.open, "Ctrl+K", "Open command palette")
        act("help", "Keyboard shortcuts", self._open_shortcuts_overlay, "?", "Show all shortcuts")
        self._theme_action = act(
            "moon" if self.theme == "light" else "sun",
            "Toggle theme",
            self._toggle_theme,
            "Ctrl+T",
            "Switch theme",
        )

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
        add(m, "Open project (.ssproj)…", self._on_open_project)
        add(m, "Save project (.ssproj)…", self._on_save_archive, "Ctrl+S")
        m.addSeparator()
        add(m, "Export G-code…", self._on_export_gcode, "Ctrl+E")
        add(m, "Export modified DXF…", self._on_export_dxf)
        add(m, "Export plates batch…", self._on_export_batch)
        m.addSeparator()
        add(m, "New project", self._on_new_project)
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
        add(m, "Fit to content", self.canvas.view.fit_to_content, "F")
        add(m, "Toggle theme", self._toggle_theme, "Ctrl+T")
        add(m, "Shortcuts…", self._open_shortcuts_overlay, "?")

    def _build_status_bar(self) -> None:
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self._status_state = QLabel("● Ready")
        self._status_coord = QLabel("Y   0.00   Z   0.00")
        self._status_coord.setProperty("role", "mono")
        self._status_segs = QLabel("0 segs")
        self._status_eta = QLabel("ETA --:--")
        self._status_eta.setProperty("role", "mono")
        self._status_zoom = QLabel("100%")
        self._status_zoom.setProperty("role", "mono")
        self._status_offset = QLabel("Δ 0.0, 0.0")
        self._status_offset.setProperty("role", "mono")
        for w in (
            self._status_state,
            self._status_coord,
            self._status_offset,
            self._status_segs,
            self._status_eta,
            self._status_zoom,
        ):
            sb.addPermanentWidget(w)

    def _register_commands(self) -> None:
        r = self.registry
        r.register(CommandEntry("file.import", "File: Import DXF…", self._on_import_dialog, "Ctrl+O"))
        r.register(CommandEntry("file.open", "File: Open project…", self._on_open_project))
        r.register(CommandEntry("file.save", "File: Save project…", self._on_save_archive, "Ctrl+S"))
        r.register(CommandEntry("file.new", "File: New project", self._on_new_project))
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
        r.register(CommandEntry("view.fit", "View: Fit to content", self.canvas.view.fit_to_content, "F"))
        r.register(CommandEntry("view.theme", "View: Toggle theme", self._toggle_theme, "Ctrl+T"))
        r.register(CommandEntry("view.shortcuts", "View: Shortcuts overlay", self._open_shortcuts_overlay, "?"))
        r.register(CommandEntry("preview.gen", "Preview: Generate plates/parts", self.controller.generate_preview))

    # ── file dialogs / actions ────────────────────────────────────────
    def _on_import_dialog(self) -> None:
        self.sidebar.trigger_import_dialog()

    def _on_import(self, use_units: bool, scale: float) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import DXF", filter="DXF files (*.dxf)")
        if not path:
            return
        self.controller.import_dxf(path, use_units, scale)
        self.recents.add(path)
        self.recent_menu.refresh()
        self.welcome.refresh_recents()
        self.canvas.view.fit_to_content()

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

    def _on_save_archive(self) -> None:
        suggested = self.controller.project.source_dxf_name or "project"
        suggested = Path(suggested).stem + ".ssproj"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save project archive",
            suggested,
            filter="Slicer project (*.ssproj)",
        )
        if not path:
            return
        if self.controller.save_project_archive(path, scene=self.canvas.scene):
            self.recents.add(path)
            self.recent_menu.refresh()
            self.welcome.refresh_recents()
            self._update_window_title()

    def _on_open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open project",
            filter="Slicer project (*.ssproj);;Legacy project (*.ssp)",
        )
        if path:
            self._open_path(path)

    def _open_path(self, path: str) -> None:
        ext = Path(path).suffix.lower()
        if ext == ".dxf":
            self.controller.import_dxf(path)
        elif ext == ".ssproj":
            if not self.controller.open_project_archive(path):
                return
        elif ext == ".ssp":
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
        else:
            self.toasts.show_toast("Unsupported file", f"Can't open {ext}", "warning")
            return

        self.recents.add(path)
        self.recent_menu.refresh()
        self.welcome.refresh_recents()
        self._update_window_title()
        self.canvas.view.fit_to_content()

    def _on_new_project(self) -> None:
        from ..core.project import Project

        self.controller.project = Project()
        self.controller.history.clear()
        self.controller.layers = []
        self.controller.focused_layer = -1
        self.controller._source_dxf_bytes = None
        self.controller.changed.emit()
        self.controller.info_changed.emit()
        self._update_window_title()
        self.toasts.show_toast("New project", "Cleared workspace.", "info")

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
        self.sidebar.set_diagonal_status("Click P1 on the canvas")

    def _on_canvas_click(self, scene_y: float, scene_z: float) -> None:
        if not self._picking_diagonal:
            return
        base = Point(
            scene_y - self.controller.project.offset_y,
            scene_z - self.controller.project.offset_z,
        )
        if self._diag_first is None:
            self._diag_first = base
            self.sidebar.set_diagonal_status("Click P2")
            return
        ok = self.controller.add_manual_diagonal(self._diag_first, base)
        self._picking_diagonal = False
        self._diag_first = None
        self.sidebar.set_diagonal_status("Idle" if ok else "Failed, retry")

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
            speed = self.timeline.speed_multiplier()
            self._sim_start = time.perf_counter() - start_fraction * (self._sim_total / speed)
            self._sim_timer.start()
        else:
            self._sim_timer.stop()

    def _on_sim_tick(self) -> None:
        speed = self.timeline.speed_multiplier()
        elapsed = (time.perf_counter() - self._sim_start) * speed
        fraction = elapsed / self._sim_total if self._sim_total > 0 else 1.0
        if fraction >= 1.0:
            if self.timeline.loop_enabled():
                self._sim_start = time.perf_counter()
                fraction = 0.0
            else:
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
            manual = [
                cut.to_machine_line(c.project.offset_y, c.project.offset_z)
                for cut in c.project.manual_cuts
            ]
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
        self.canvas.scene.render_model(model)
        self._status_segs.setText(f"{len(c.project.segments)} segs")

    def _refresh_info(self) -> None:
        c = self.controller
        est = c.estimated_time_s()
        fraction = self.timeline.progress_fraction()
        height = c.cut_height()
        z_min, z_max = (height if height else (None, None))
        dims = c.dimensions()
        self.timeline.set_info(est, est * fraction, z_min, z_max, dims)
        self._status_eta.setText(f"ETA {_fmt(est)}")
        self._status_offset.setText(f"Δ {c.project.offset_y:+.1f}, {c.project.offset_z:+.1f}")

    def _refresh_central_stack(self) -> None:
        has_geo = self.controller.has_geometry
        self.central_stack.setCurrentIndex(1 if has_geo else 0)
        if has_geo:
            QTimer.singleShot(0, self.canvas.view.fit_to_content)
        self._update_window_title()

    def _on_cursor_moved(self, y: float, z: float) -> None:
        self._status_coord.setText(f"Y {y:7.2f}  Z {z:7.2f}")

    def _on_transform_changed(self) -> None:
        self._status_zoom.setText(f"{self.canvas.view.zoom_percent()}%")

    def _on_notify(self, title: str, body: str, severity: str) -> None:
        self.toasts.show_toast(title, body, severity)  # type: ignore[arg-type]

    def _apply_scene_palette(self) -> None:
        t = get_tokens(self.theme)
        c = t.color
        self.canvas.scene.set_palette(
            ScenePalette(
                background=c.bg,
                grid=c.border,
                axis=c.accent,
                cut=c.accent,
                entry=c.success,
                exit=c.danger,
                travel=c.muted,
                union=c.warning,
                danger=c.danger,
                bed=c.border_strong,
                surface_alt=c.surface_alt,
            )
        )
        self.canvas.apply_ruler_palette(t)

    def _toggle_theme(self) -> None:
        self.theme = "light" if self.theme == "dark" else "dark"
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(render_qss(self.theme))
            app.setProperty("theme", self.theme)
        self._apply_scene_palette()
        self._refresh_canvas()
        self.toasts.show_toast(f"Theme: {self.theme}", "", "info", duration_ms=1200)

    def _open_shortcuts_overlay(self) -> None:
        if self.shortcuts_overlay is None:
            return
        if self.shortcuts_overlay.isVisible():
            self.shortcuts_overlay.hide_overlay()
        else:
            self.shortcuts_overlay.show_overlay()

    def _update_window_title(self) -> None:
        name = self.controller.project.source_dxf_name
        prefix = (Path(name).stem if name else "Untitled")
        self.setWindowTitle(f"{prefix} — SlicerSegelinEnder3")

    # ── drag and drop ────────────────────────────────────────────────
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                self._open_path(local)
                break
        event.acceptProposedAction()

    # Position overlays after resize.
    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if self.shortcuts_overlay and self.shortcuts_overlay.isVisible():
            self.shortcuts_overlay.setGeometry(self.rect())


def _fmt(seconds: float) -> str:
    seconds = max(0.0, seconds)
    m, s = divmod(round(seconds), 60)
    return f"{m:02d}:{s:02d}"
