import tkinter as tk
from tkinter import filedialog, messagebox
import ezdxf
try:
    from ezdxf import path
except ImportError:
    path = None
try:
    from ezdxf import units as ezunits
except ImportError:
    ezunits = None
import math
import time
import os

class AppSlicerCNC:
    def __init__(self, root):
        self.root = root
        self.root.title("Hot Wire CNC Slicer - Ender 3")
        self.root.minsize(1080, 700)
        
        # --- VARIABLES ---
        self.lineas = [] 
        self.offset_y = 0.0
        self.offset_z = 0.0
        self.escala_visual = 2.0 
        self.limite_y_mm = 220.0
        self.limite_z_mm = 100.0
        self.tolerancia_limite_mm = 0.2
        
        # Velocidades por defecto en mm/s
        self.vel_corte = tk.StringVar(value="10")
        self.grados_origen = tk.StringVar(value="0.1")
        self.paso_traslado = tk.StringVar(value="0.1")
        self.nombre_lote_capas = tk.StringVar(value="cut")
        self.area_y_mm_var = tk.StringVar(value="220")
        self.area_z_mm_var = tk.StringVar(value="100")
        self.dividir_en_placas = tk.BooleanVar(value=False)
        self.usar_cortes_manuales = tk.BooleanVar(value=False)
        self.auto_cerrar_cortes_manuales = tk.BooleanVar(value=True)
        self.usar_insunits_auto = tk.BooleanVar(value=True)
        self.escala_importacion_dxf = tk.StringVar(value="1.0")
        self.corte_y_var = tk.StringVar(value="")
        self.corte_z_var = tk.StringVar(value="")
        self.referencia_cortes_var = tk.StringVar(value="DXF Base")
        
        self.drag_data = {"x": 0, "y": 0}

        # Real-time simulation
        self.reproduciendo = False
        self.play_after_id = None
        self.tiempo_total_seg = 0.0
        self.tiempo_inicio_play = 0.0
        self.tiempo_acumulado_seg = 0.0
        self.actualizando_slider_interno = False
        self.play_duraciones = []
        self.play_last_slider_idx = -1

        # Layer preview (plates)
        self.capas_preview = []
        self.capa_preview_idx = -1  # -1 = full view
        self.editando_capa_idx = None
        self.backup_dxf_completo = None

        # Manual cuts (partition lines)
        # each cut: {"a":..., "b":..., "c":..., "tipo":"Y|Z|2P", "meta":...}
        self.cortes_manuales = []
        self.pendiente_corte_diag_p1 = None
        self.total_view_transform = None
        self.lineas_dxf_base = []
        self.info_unidades_dxf = "INSUNITS: --"
        self.corte_invertido = False

        # --- GRAPHICAL INTERFACE ---
        # Scrollable left sidebar so controls remain accessible on smaller screens
        sidebar_container = tk.Frame(root)
        sidebar_container.pack(side=tk.LEFT, fill=tk.Y)

        self.sidebar_canvas = tk.Canvas(sidebar_container, width=320, highlightthickness=0, bd=0)
        self.sidebar_scrollbar = tk.Scrollbar(sidebar_container, orient=tk.VERTICAL, command=self.sidebar_canvas.yview)
        self.sidebar_canvas.configure(yscrollcommand=self.sidebar_scrollbar.set)

        self.sidebar_canvas.pack(side=tk.LEFT, fill=tk.Y, expand=False)
        self.sidebar_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        panel_izq = tk.Frame(self.sidebar_canvas, padx=10, pady=10)
        self.sidebar_window_id = self.sidebar_canvas.create_window((0, 0), window=panel_izq, anchor="nw")

        def _actualizar_scroll_sidebar(_event=None):
            self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all"))

        def _ajustar_ancho_sidebar(event):
            self.sidebar_canvas.itemconfig(self.sidebar_window_id, width=event.width)

        def _sidebar_mousewheel(event):
            self.sidebar_canvas.yview_scroll(int(-event.delta / 120), "units")

        def _bind_sidebar_mousewheel(_event=None):
            self.sidebar_canvas.bind_all("<MouseWheel>", _sidebar_mousewheel)

        def _unbind_sidebar_mousewheel(_event=None):
            self.sidebar_canvas.unbind_all("<MouseWheel>")

        panel_izq.bind("<Configure>", _actualizar_scroll_sidebar)
        self.sidebar_canvas.bind("<Configure>", _ajustar_ancho_sidebar)
        self.sidebar_canvas.bind("<Enter>", _bind_sidebar_mousewheel)
        self.sidebar_canvas.bind("<Leave>", _unbind_sidebar_mousewheel)
        panel_izq.bind("<Enter>", _bind_sidebar_mousewheel)
        panel_izq.bind("<Leave>", _unbind_sidebar_mousewheel)
        
        tk.Button(panel_izq, text="1. Load DXF", command=self.cargar_dxf, bg="#2196F3", fg="white", font=("Arial", 11, "bold")).pack(fill=tk.X, pady=5)

        frame_import = tk.Frame(panel_izq)
        frame_import.pack(fill=tk.X, pady=(0, 6))
        tk.Checkbutton(frame_import, text="Use INSUNITS", variable=self.usar_insunits_auto).pack(side=tk.LEFT)
        tk.Label(frame_import, text="DXF Scale x").pack(side=tk.LEFT, padx=(8, 2))
        tk.Entry(frame_import, textvariable=self.escala_importacion_dxf, width=6).pack(side=tk.LEFT)
        
        # Adjustment tools
        tk.Label(panel_izq, text="Adjust Shape:", font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(10,0))
        frame_herramientas = tk.Frame(panel_izq)
        frame_herramientas.pack(fill=tk.X, pady=2)
        tk.Button(frame_herramientas, text="Rotate 90°", command=lambda: self.rotar(90)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        tk.Button(frame_herramientas, text="Auto Height", command=self.auto_ajustar).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        frame_herramientas_2 = tk.Frame(panel_izq)
        frame_herramientas_2.pack(fill=tk.X, pady=(2, 2))
        tk.Button(frame_herramientas_2, text="Mirror Vertical", command=self.reflejar_vertical).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        tk.Button(frame_herramientas_2, text="Mirror Horizontal", command=self.reflejar_horizontal).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        frame_rot_origen = tk.Frame(panel_izq)
        frame_rot_origen.pack(fill=tk.X, pady=(2, 2))
        tk.Entry(frame_rot_origen, textvariable=self.grados_origen, width=8).pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(frame_rot_origen, text="°").pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(frame_rot_origen, text="↺", command=lambda: self.rotar_sobre_origen_desde_ui(-1)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        tk.Button(frame_rot_origen, text="↻", command=lambda: self.rotar_sobre_origen_desde_ui(1)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        frame_traslado_cfg = tk.Frame(panel_izq)
        frame_traslado_cfg.pack(fill=tk.X, pady=(2, 2))
        tk.Label(frame_traslado_cfg, text="Y/Z step:").pack(side=tk.LEFT)
        tk.Entry(frame_traslado_cfg, textvariable=self.paso_traslado, width=8).pack(side=tk.LEFT, padx=(4, 4))
        tk.Label(frame_traslado_cfg, text="mm").pack(side=tk.LEFT)

        frame_traslado_y = tk.Frame(panel_izq)
        frame_traslado_y.pack(fill=tk.X, pady=(2, 0))
        tk.Button(frame_traslado_y, text="Y -", command=lambda: self.trasladar_fino_desde_ui("y", -1)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        tk.Button(frame_traslado_y, text="Y +", command=lambda: self.trasladar_fino_desde_ui("y", 1)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        frame_traslado_z = tk.Frame(panel_izq)
        frame_traslado_z.pack(fill=tk.X, pady=(2, 2))
        tk.Button(frame_traslado_z, text="Z -", command=lambda: self.trasladar_fino_desde_ui("z", -1)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        tk.Button(frame_traslado_z, text="Z +", command=lambda: self.trasladar_fino_desde_ui("z", 1)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        self.btn_invertir_corte = tk.Button(panel_izq, text="Reverse Cut Direction", command=self.invertir_corte)
        self.btn_invertir_corte.pack(fill=tk.X, pady=(2, 5))
        tk.Button(panel_izq, text="Align Origin to Cut", command=self.alinear_origen_corte).pack(fill=tk.X, pady=(0, 8))

        tk.Label(panel_izq, text="Work Speed (mm/s):").pack(anchor=tk.W, pady=(10,0))
        tk.Entry(panel_izq, textvariable=self.vel_corte).pack(fill=tk.X)
        
        tk.Label(panel_izq, text="\nTips:", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        tk.Label(panel_izq, text="- Drag the drawing to move it.\n- GREEN point = Cut Start\n- Red = Out of bounds", justify=tk.LEFT, font=("Arial", 8)).pack(anchor=tk.W)

        tk.Label(panel_izq, text="\nUsable area / plate size (Y x Z) mm:", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        frame_area = tk.Frame(panel_izq)
        frame_area.pack(fill=tk.X, pady=(2, 6))
        tk.Label(frame_area, text="Y").pack(side=tk.LEFT)
        tk.Entry(frame_area, textvariable=self.area_y_mm_var, width=6).pack(side=tk.LEFT, padx=(2, 6))
        tk.Label(frame_area, text="Z").pack(side=tk.LEFT)
        tk.Entry(frame_area, textvariable=self.area_z_mm_var, width=6).pack(side=tk.LEFT, padx=(2, 6))
        tk.Button(frame_area, text="Apply", command=self.aplicar_area_util).pack(side=tk.LEFT)

        self.chk_dividir_placas = tk.Checkbutton(
            panel_izq,
            text="Split into plates if area is exceeded",
            variable=self.dividir_en_placas,
            command=self.cambiar_modo_dividir_placas
        )
        self.chk_dividir_placas.pack(anchor=tk.W, pady=(0, 6))

        self.chk_cortes_manuales = tk.Checkbutton(
            panel_izq,
            text="Use manual cuts",
            variable=self.usar_cortes_manuales,
            command=self.cambiar_modo_cortes_manuales
        )
        self.chk_cortes_manuales.pack(anchor=tk.W, pady=(0, 4))

        self.chk_cierre_manual = tk.Checkbutton(
            panel_izq,
            text="Close contours in manual cuts",
            variable=self.auto_cerrar_cortes_manuales,
            command=lambda: self.dibujar(self.slider_sim.get() if self.lineas else 0)
        )
        self.chk_cierre_manual.pack(anchor=tk.W, pady=(0, 2))

        self._construir_panel_cortes_manuales(panel_izq)

        # Slider simulacion interactiva
        tk.Label(panel_izq, text="\nCut Simulation:", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        self.slider_sim = tk.Scale(panel_izq, from_=0, to=0, orient=tk.HORIZONTAL, command=self.actualizar_simulacion, showvalue=False)
        self.slider_sim.pack(fill=tk.X, pady=(0, 10))

        frame_play = tk.Frame(panel_izq)
        frame_play.pack(fill=tk.X, pady=(0, 8))
        self.btn_play = tk.Button(frame_play, text="▶ Play", command=self.iniciar_simulacion_tiempo_real, state=tk.DISABLED)
        self.btn_play.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.btn_stop = tk.Button(frame_play, text="■ Stop", command=self.detener_simulacion_tiempo_real, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        self.lbl_tiempo = tk.Label(panel_izq, text="Estimated time: --:-- | Elapsed: 00:00", font=("Arial", 8))
        self.lbl_tiempo.pack(anchor=tk.W, pady=(0, 8))
        self.lbl_altura = tk.Label(panel_izq, text="Max cut height: -- mm (Zmin -- / Zmax --)", font=("Arial", 8, "bold"))
        self.lbl_altura.pack(anchor=tk.W, pady=(0, 8))

        tk.Label(panel_izq, text="Base filename:").pack(anchor=tk.W, pady=(2,0))
        tk.Entry(panel_izq, textvariable=self.nombre_lote_capas).pack(fill=tk.X)

        frame_preview_capas = tk.Frame(panel_izq)
        frame_preview_capas.pack(fill=tk.X, pady=(4, 6))
        self.btn_preview_capas = tk.Button(frame_preview_capas, text="Preview YxZ Plates", command=self.generar_preview_capas, state=tk.DISABLED)
        self.btn_preview_capas.pack(fill=tk.X)

        frame_nav_capas = tk.Frame(panel_izq)
        frame_nav_capas.pack(fill=tk.X, pady=(2, 2))
        self.btn_capa_prev = tk.Button(frame_nav_capas, text="◀ Layer", command=lambda: self.mover_preview_capa(-1), state=tk.DISABLED)
        self.btn_capa_prev.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.btn_capa_next = tk.Button(frame_nav_capas, text="Layer ▶", command=lambda: self.mover_preview_capa(1), state=tk.DISABLED)
        self.btn_capa_next.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        self.btn_vista_total = tk.Button(panel_izq, text="Back to Full View", command=self.activar_vista_total, state=tk.DISABLED)
        self.btn_vista_total.pack(fill=tk.X, pady=(0, 4))
        self.btn_editar_capa = tk.Button(panel_izq, text="Auto-edit focused layer", command=self.editar_capa_actual, state=tk.DISABLED)
        self.btn_editar_capa.pack(fill=tk.X, pady=(0, 2))
        self.btn_restaurar_dxf = tk.Button(panel_izq, text="Restore Full DXF", command=self.restaurar_dxf_completo, state=tk.DISABLED)
        self.btn_restaurar_dxf.pack(fill=tk.X, pady=(0, 4))
        self.lbl_capa_preview = tk.Label(panel_izq, text="YxZ plate preview: OFF", font=("Arial", 8))
        self.lbl_capa_preview.pack(anchor=tk.W, pady=(0, 6))

        self.btn_exportar = tk.Button(panel_izq, text="2. Generate G-Code", command=self.exportar_gcode, state=tk.DISABLED, bg="#4CAF50", fg="white", font=("Arial", 11, "bold"))
        self.btn_exportar.pack(fill=tk.X, pady=(8, 4))
        self.btn_exportar_dxf = tk.Button(
            panel_izq,
            text="2b. Export Modified DXF",
            command=self.exportar_dxf_modificado,
            state=tk.DISABLED,
            bg="#1565C0",
            fg="white",
            font=("Arial", 10, "bold")
        )
        self.btn_exportar_dxf.pack(fill=tk.X, pady=(0, 4))
        self.btn_exportar_capas = tk.Button(panel_izq, text="3. Generate G-Codes by Plates", command=self.exportar_gcode_por_capas, state=tk.DISABLED, bg="#2E7D32", fg="white", font=("Arial", 10, "bold"))
        self.btn_exportar_capas.pack(fill=tk.X, pady=(0, 4))
        self.btn_guardar_capa_actual = tk.Button(panel_izq, text="Save Focused Layer", command=self.guardar_capa_enfocada, state=tk.DISABLED, bg="#33691E", fg="white", font=("Arial", 10, "bold"))
        self.btn_guardar_capa_actual.pack(fill=tk.X, pady=(0, 4))
        self.btn_guardar_batch_carpeta = tk.Button(panel_izq, text="Save Batch to Folder", command=self.guardar_batch_en_carpeta, state=tk.DISABLED, bg="#1B5E20", fg="white", font=("Arial", 10, "bold"))
        self.btn_guardar_batch_carpeta.pack(fill=tk.X, pady=(0, 10))
        
        panel_der = tk.Frame(root, padx=10, pady=10)
        panel_der.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        tk.Label(panel_der, text="Full View (part and layers)").pack()
        self.lbl_dimensiones_dxf = tk.Label(panel_der, text="DXF: --", font=("Arial", 8, "bold"), anchor="w", justify=tk.LEFT)
        self.lbl_dimensiones_dxf.pack(fill=tk.X, pady=(0, 4))
        dim_canvas_w = int(self.limite_y_mm * self.escala_visual)
        dim_canvas_h = int(self.limite_z_mm * self.escala_visual)
        self.canvas_total = tk.Canvas(panel_der, width=dim_canvas_w, height=max(180, dim_canvas_h), bg="#f0f0f0", relief=tk.SUNKEN, bd=2)
        self.canvas_total.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        tk.Label(panel_der, text="Work Area (Y-Z View)").pack()
        
        self.canvas = tk.Canvas(panel_der, width=dim_canvas_w, height=dim_canvas_h, bg="#e0e0e0", relief=tk.SUNKEN, bd=2)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.canvas.bind("<ButtonPress-1>", self.iniciar_arrastre)
        self.canvas.bind("<B1-Motion>", self.arrastrar)
        self.canvas_total.bind("<Button-1>", self.click_canvas_total)
        self._actualizar_label_cortes_manuales()

    def _construir_panel_cortes_manuales(self, panel_izq):
        """Manual cut management panel (list + basic editing)."""
        tk.Label(panel_izq, text="Manual Cuts", font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(2, 0))

        frame_ref = tk.Frame(panel_izq)
        frame_ref.pack(fill=tk.X, pady=(2, 2))
        tk.Label(frame_ref, text="Reference:").pack(side=tk.LEFT)
        self.menu_ref_cortes = tk.OptionMenu(
            frame_ref,
            self.referencia_cortes_var,
            "DXF Base",
            "Current machine",
            command=lambda _v=None: self._on_cambio_referencia_cortes()
        )
        self.menu_ref_cortes.pack(side=tk.LEFT, padx=(4, 0))

        frame_inputs = tk.Frame(panel_izq)
        frame_inputs.pack(fill=tk.X, pady=(2, 2))
        tk.Label(frame_inputs, text="Y:").pack(side=tk.LEFT)
        self.entry_corte_y = tk.Entry(frame_inputs, textvariable=self.corte_y_var, width=7)
        self.entry_corte_y.pack(side=tk.LEFT, padx=(2, 4))
        self.btn_add_corte_y = tk.Button(frame_inputs, text="+Y", command=self.agregar_corte_manual_y, state=tk.DISABLED)
        self.btn_add_corte_y.pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(frame_inputs, text="Z:").pack(side=tk.LEFT)
        self.entry_corte_z = tk.Entry(frame_inputs, textvariable=self.corte_z_var, width=7)
        self.entry_corte_z.pack(side=tk.LEFT, padx=(2, 4))
        self.btn_add_corte_z = tk.Button(frame_inputs, text="+Z", command=self.agregar_corte_manual_z, state=tk.DISABLED)
        self.btn_add_corte_z.pack(side=tk.LEFT)

        frame_diag = tk.Frame(panel_izq)
        frame_diag.pack(fill=tk.X, pady=(0, 2))
        self.btn_add_corte_diag = tk.Button(frame_diag, text="Diagonal cut (2 clicks)", command=self.iniciar_corte_manual_dos_puntos, state=tk.DISABLED)
        self.btn_add_corte_diag.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.btn_limpiar_cortes = tk.Button(frame_diag, text="Clear", command=self.limpiar_cortes_manuales, state=tk.DISABLED)
        self.btn_limpiar_cortes.pack(side=tk.LEFT, padx=(2, 0))

        frame_lista = tk.Frame(panel_izq)
        frame_lista.pack(fill=tk.X, pady=(2, 2))
        self.listbox_cortes = tk.Listbox(frame_lista, height=4, exportselection=False)
        self.listbox_cortes.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.listbox_cortes.bind("<<ListboxSelect>>", self.on_select_corte_manual)
        sb = tk.Scrollbar(frame_lista, orient=tk.VERTICAL, command=self.listbox_cortes.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox_cortes.config(yscrollcommand=sb.set)

        frame_lista_btns = tk.Frame(panel_izq)
        frame_lista_btns.pack(fill=tk.X, pady=(0, 4))
        self.btn_editar_corte = tk.Button(frame_lista_btns, text="Edit", command=self.editar_corte_manual_seleccionado, state=tk.DISABLED)
        self.btn_editar_corte.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.btn_eliminar_corte = tk.Button(frame_lista_btns, text="Delete", command=self.eliminar_corte_manual_seleccionado, state=tk.DISABLED)
        self.btn_eliminar_corte.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        self.lbl_cortes_manuales = tk.Label(panel_izq, text="Manual cuts: 0", font=("Arial", 8))
        self.lbl_cortes_manuales.pack(anchor=tk.W, pady=(0, 2))

        self.lbl_estado_corte_diag = tk.Label(panel_izq, text="Diagonal: inactive", font=("Arial", 8), fg="#666")
        self.lbl_estado_corte_diag.pack(anchor=tk.W, pady=(0, 4))

    # --- UI AND DRAWING LOGIC ---
    def iniciar_arrastre(self, event):
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y

    def arrastrar(self, event):
        if not self.lineas: return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
        if self.editando_capa_idx is None:
            self.invalidar_preview_capas()
        t = self._get_work_view_transform()
        s = max(1e-9, t["s"])
        delta_x = (event.x - self.drag_data["x"]) / s
        delta_y = -(event.y - self.drag_data["y"]) / s 
        
        self.offset_y += delta_x
        self.offset_z += delta_y
        
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y
        self.sincronizar_edicion_capa_si_corresponde()
        self.dibujar(self.slider_sim.get())
        self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def mm_a_pixel(self, y_mm, z_mm):
        t = self._get_work_view_transform()
        px = t["ox"] + (y_mm * t["s"])
        py = t["oy"] + ((self.limite_z_mm - z_mm) * t["s"])
        return px, py

    def _get_canvas_size(self, canvas):
        w = int(canvas.winfo_width())
        h = int(canvas.winfo_height())
        if w <= 2:
            w = int(float(canvas.cget("width")))
        if h <= 2:
            h = int(float(canvas.cget("height")))
        return max(1, w), max(1, h)

    def _get_work_view_transform(self):
        """Transform used to draw the work area and maximize the visible canvas."""
        w, h = self._get_canvas_size(self.canvas)
        pad = 10.0
        ly = max(1e-6, float(self.limite_y_mm))
        lz = max(1e-6, float(self.limite_z_mm))

        sx = max(1e-9, (w - (2.0 * pad)) / ly)
        sz = max(1e-9, (h - (2.0 * pad)) / lz)
        s = min(sx, sz)

        used_w = ly * s
        used_h = lz * s
        ox = (w - used_w) / 2.0
        oy = (h - used_h) / 2.0

        return {"w": w, "h": h, "s": s, "ox": ox, "oy": oy}

    def _factor_unidades_a_mm(self, doc):
        """Returns conversion factor from DXF coordinates to millimeters."""
        insunits = 0
        try:
            insunits = int(getattr(doc, "units", 0) or 0)
        except Exception:
            try:
                insunits = int(doc.header.get("$INSUNITS", 0) or 0)
            except Exception:
                insunits = 0

        # 0=unitless -> asumimos mm para no romper archivos legacy.
        if insunits in (0, 4):
            return 1.0

        # Try ezdxf API when available
        if ezunits is not None:
            try:
                return float(ezunits.conversion_factor(insunits, ezunits.MM))
            except Exception:
                pass

        # Simple fallback for common units
        tabla = {
            1: 25.4,        # inch
            2: 304.8,       # foot
            3: 1609344.0,   # mile
            4: 1.0,         # mm
            5: 10.0,        # cm
            6: 1000.0,      # m
            7: 1000000.0,   # km
            14: 1e-7,       # angstrom
            15: 1e-6,       # nanometer
            16: 1e-3,       # micron
            17: 1.0,        # decimeter? (conservador a mm no fiable)
            18: 100.0,      # decameter
            19: 1000.0,     # hectometer
            20: 1000000.0,  # gigameter
            21: 149597870700000.0, # astronomical unit
            22: 9460730472580800000.0, # light year
            23: 30856775814913700000.0, # parsec
            24: 0.0000000254, # microinch
            25: 0.0000254,    # mil
            26: 914.4,        # yard
        }
        return float(tabla.get(insunits, 1.0))

    def _actualizar_label_dimensiones_dxf(self):
        if not hasattr(self, "lbl_dimensiones_dxf"):
            return
        if not self.lineas_dxf_base:
            self.lbl_dimensiones_dxf.config(text=f"DXF: -- | {self.info_unidades_dxf}")
            return

        ys = []
        zs = []
        for y1, z1, y2, z2 in self.lineas_dxf_base:
            ys.extend([y1, y2])
            zs.extend([z1, z2])

        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)
        ancho = max_y - min_y
        alto = max_z - min_z
        self.lbl_dimensiones_dxf.config(
            text=(
                f"DXF base size: Y={ancho:.2f} mm | Z={alto:.2f} mm | "
                f"Y[{min_y:.2f}..{max_y:.2f}] Z[{min_z:.2f}..{max_z:.2f}] | {self.info_unidades_dxf}"
            )
        )

    def aplicar_area_util(self):
        try:
            ly = float(self.area_y_mm_var.get().replace(",", "."))
            lz = float(self.area_z_mm_var.get().replace(",", "."))
            if ly <= 0 or lz <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Invalid area", "Enter valid dimensions greater than 0 for Y and Z.")
            return

        self.limite_y_mm = ly
        self.limite_z_mm = lz

        dim_canvas_w = int(self.limite_y_mm * self.escala_visual)
        dim_canvas_h = int(self.limite_z_mm * self.escala_visual)
        self.canvas.config(width=dim_canvas_w, height=dim_canvas_h)
        self.canvas_total.config(width=dim_canvas_w, height=max(180, dim_canvas_h))

        if self.lineas:
            self.dibujar(self.slider_sim.get())
            self.refrescar_info_tiempo(0.0)
        else:
            self.canvas.delete("all")
            self.dibujar_grilla()
            self.dibujar_canvas_total()

    def cambiar_modo_cortes_manuales(self):
        activo = self.usar_cortes_manuales.get()
        estado = tk.NORMAL if activo else tk.DISABLED
        self.btn_add_corte_y.config(state=estado)
        self.btn_add_corte_z.config(state=estado)
        self.btn_add_corte_diag.config(state=estado)
        self.btn_limpiar_cortes.config(state=estado)
        self.menu_ref_cortes.config(state=estado)
        self.btn_editar_corte.config(state=estado if self._obtener_indice_corte_seleccionado() is not None else tk.DISABLED)
        self.btn_eliminar_corte.config(state=estado if self._obtener_indice_corte_seleccionado() is not None else tk.DISABLED)
        self.chk_cierre_manual.config(state=estado)
        self.pendiente_corte_diag_p1 = None
        self.lbl_estado_corte_diag.config(text="Diagonal: inactive", fg="#666")
        self.invalidar_preview_capas()
        self.dibujar(self.slider_sim.get() if self.lineas else 0)

    def _linea_a_partir_de_dos_puntos(self, y1, z1, y2, z2):
        # a*y + b*z + c = 0
        a = z1 - z2
        b = y2 - y1
        c = (y1 * z2) - (y2 * z1)
        norma = math.hypot(a, b)
        if norma <= 1e-12:
            return None
        return (a / norma, b / norma, c / norma)

    def _modo_referencia_cortes(self):
        v = (self.referencia_cortes_var.get() or "").strip().lower()
        if "machine" in v:
            return "maquina"
        return "base"

    def _entrada_y_a_base(self, y_val):
        if self._modo_referencia_cortes() == "maquina":
            return float(y_val) - self.offset_y
        return float(y_val)

    def _entrada_z_a_base(self, z_val):
        if self._modo_referencia_cortes() == "maquina":
            return float(z_val) - self.offset_z
        return float(z_val)

    def _base_y_a_entrada(self, y_base):
        if self._modo_referencia_cortes() == "maquina":
            return float(y_base) + self.offset_y
        return float(y_base)

    def _base_z_a_entrada(self, z_base):
        if self._modo_referencia_cortes() == "maquina":
            return float(z_base) + self.offset_z
        return float(z_base)

    def _on_cambio_referencia_cortes(self):
        self._refrescar_lista_cortes_manuales()
        self.on_select_corte_manual()
        if self.lineas:
            self.dibujar(self.slider_sim.get())

    def _coords_maquina_a_base(self, y_m, z_m):
        """Convert machine coordinates to base DXF coordinates using current offsets."""
        return (y_m - self.offset_y, z_m - self.offset_z)

    def _corte_manual_a_linea_maquina(self, corte):
        """Convert a manual cut (defined in DXF base) to machine-line form: a*y+b*z+c=0."""
        tipo = corte.get("tipo")

        if tipo == "Y":
            yb = float(corte.get("meta", {}).get("y", 0.0))
            ym = yb + self.offset_y
            return (1.0, 0.0, -ym)

        if tipo == "Z":
            zb = float(corte.get("meta", {}).get("z", 0.0))
            zm = zb + self.offset_z
            return (0.0, 1.0, -zm)

        # 2P (or legacy fallback): transform c_base by translation.
        a = float(corte.get("a", 0.0))
        b = float(corte.get("b", 0.0))
        c_base = float(corte.get("c_base", corte.get("c", 0.0)))
        c_m = c_base - (a * self.offset_y) - (b * self.offset_z)
        return (a, b, c_m)

    def _actualizar_label_cortes_manuales(self):
        if hasattr(self, "lbl_cortes_manuales"):
            self.lbl_cortes_manuales.config(text=f"Manual cuts: {len(self.cortes_manuales)}")

    def _descripcion_corte_manual(self, corte, idx):
        tipo = corte.get("tipo", "?")
        if tipo == "Y":
            yb = float(corte.get('meta', {}).get('y', 0.0))
            yv = self._base_y_a_entrada(yb)
            suf = "mach" if self._modo_referencia_cortes() == "maquina" else "base"
            return f"{idx+1:02d}. Y = {yv:.3f} [{suf}]"
        if tipo == "Z":
            zb = float(corte.get('meta', {}).get('z', 0.0))
            zv = self._base_z_a_entrada(zb)
            suf = "mach" if self._modo_referencia_cortes() == "maquina" else "base"
            return f"{idx+1:02d}. Z = {zv:.3f} [{suf}]"
        if tipo == "2P":
            p1 = corte.get("meta", {}).get("p1", (0.0, 0.0))
            p2 = corte.get("meta", {}).get("p2", (0.0, 0.0))
            return f"{idx+1:02d}. 2P ({p1[0]:.1f},{p1[1]:.1f})→({p2[0]:.1f},{p2[1]:.1f})"
        return f"{idx+1:02d}. Cut"

    def _refrescar_lista_cortes_manuales(self):
        if not hasattr(self, "listbox_cortes"):
            return
        self.listbox_cortes.delete(0, tk.END)
        for i, c in enumerate(self.cortes_manuales):
            self.listbox_cortes.insert(tk.END, self._descripcion_corte_manual(c, i))
        self.on_select_corte_manual()

    def _obtener_indice_corte_seleccionado(self):
        if not hasattr(self, "listbox_cortes"):
            return None
        sel = self.listbox_cortes.curselection()
        if not sel:
            return None
        idx = int(sel[0])
        if 0 <= idx < len(self.cortes_manuales):
            return idx
        return None

    def on_select_corte_manual(self, _event=None):
        idx = self._obtener_indice_corte_seleccionado()
        activo = self.usar_cortes_manuales.get()
        estado_sel = tk.NORMAL if (activo and idx is not None) else tk.DISABLED
        self.btn_editar_corte.config(state=estado_sel)
        self.btn_eliminar_corte.config(state=estado_sel)

        if idx is None:
            return
        corte = self.cortes_manuales[idx]
        if corte.get("tipo") == "Y":
            yb = float(corte.get('meta', {}).get('y', 0.0))
            self.corte_y_var.set(f"{self._base_y_a_entrada(yb):.3f}")
        elif corte.get("tipo") == "Z":
            zb = float(corte.get('meta', {}).get('z', 0.0))
            self.corte_z_var.set(f"{self._base_z_a_entrada(zb):.3f}")

    def eliminar_corte_manual_seleccionado(self):
        idx = self._obtener_indice_corte_seleccionado()
        if idx is None:
            return
        del self.cortes_manuales[idx]
        self.invalidar_preview_capas()
        self._actualizar_label_cortes_manuales()
        self._refrescar_lista_cortes_manuales()
        self.dibujar(self.slider_sim.get() if self.lineas else 0)

    def editar_corte_manual_seleccionado(self):
        idx = self._obtener_indice_corte_seleccionado()
        if idx is None:
            return
        corte = self.cortes_manuales[idx]
        tipo = corte.get("tipo")
        if tipo == "Y":
            try:
                y_val = float(self.corte_y_var.get().replace(",", "."))
            except ValueError:
                messagebox.showerror("Invalid value", "Enter a valid Y value.")
                return
            y_base = self._entrada_y_a_base(y_val)
            corte.update({"a": 1.0, "b": 0.0, "c_base": -y_base, "tipo": "Y", "meta": {"y": y_base}})
        elif tipo == "Z":
            try:
                z_val = float(self.corte_z_var.get().replace(",", "."))
            except ValueError:
                messagebox.showerror("Invalid value", "Enter a valid Z value.")
                return
            z_base = self._entrada_z_a_base(z_val)
            corte.update({"a": 0.0, "b": 1.0, "c_base": -z_base, "tipo": "Z", "meta": {"z": z_base}})
        else:
            messagebox.showinfo("Edit 2-point cut", "For 2-point cuts, delete and recreate it with clicks.")
            return

        self.invalidar_preview_capas()
        self._refrescar_lista_cortes_manuales()
        self.dibujar(self.slider_sim.get() if self.lineas else 0)

    def agregar_corte_manual_y(self):
        if not self.lineas:
            return
        try:
            y_val = float(self.corte_y_var.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Invalid value", "Enter a valid Y value to add the cut.")
            return
        y_base = self._entrada_y_a_base(y_val)
        self.cortes_manuales.append({
            "a": 1.0, "b": 0.0, "c_base": -float(y_base),
            "tipo": "Y", "meta": {"y": float(y_base)}
        })
        self.invalidar_preview_capas()
        self._actualizar_label_cortes_manuales()
        self._refrescar_lista_cortes_manuales()
        self.dibujar(self.slider_sim.get())

    def agregar_corte_manual_z(self):
        if not self.lineas:
            return
        try:
            z_val = float(self.corte_z_var.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Invalid value", "Enter a valid Z value to add the cut.")
            return
        z_base = self._entrada_z_a_base(z_val)
        self.cortes_manuales.append({
            "a": 0.0, "b": 1.0, "c_base": -float(z_base),
            "tipo": "Z", "meta": {"z": float(z_base)}
        })
        self.invalidar_preview_capas()
        self._actualizar_label_cortes_manuales()
        self._refrescar_lista_cortes_manuales()
        self.dibujar(self.slider_sim.get())

    def iniciar_corte_manual_dos_puntos(self):
        if not self.lineas:
            return
        self.pendiente_corte_diag_p1 = None
        self.lbl_estado_corte_diag.config(text="Diagonal: select P1", fg="#9C27B0")

    def limpiar_cortes_manuales(self):
        self.cortes_manuales = []
        self.pendiente_corte_diag_p1 = None
        self.lbl_estado_corte_diag.config(text="Diagonal: inactive", fg="#666")
        self.invalidar_preview_capas()
        self._actualizar_label_cortes_manuales()
        self._refrescar_lista_cortes_manuales()
        self.dibujar(self.slider_sim.get() if self.lineas else 0)

    def _pixel_a_mm_canvas_total(self, px, py):
        t = self.total_view_transform
        if not t:
            return None
        s = t.get("s", 0.0)
        if s <= 1e-12:
            return None
        y_mm = t["min_y"] + ((px - t["ox"]) / s)
        z_mm = t["max_z"] - ((py - t["oy"]) / s)
        return (y_mm, z_mm)

    def click_canvas_total(self, event):
        if not self.usar_cortes_manuales.get():
            return
        if not self.lineas:
            return

        p = self._pixel_a_mm_canvas_total(event.x, event.y)
        if p is None:
            return
        y_mm, z_mm = p
        y_base, z_base = self._coords_maquina_a_base(y_mm, z_mm)

        if self.pendiente_corte_diag_p1 is None:
            self.pendiente_corte_diag_p1 = (y_base, z_base)
            self.lbl_estado_corte_diag.config(text="Diagonal: select P2", fg="#9C27B0")
            self.dibujar_canvas_total()
            return

        y1, z1 = self.pendiente_corte_diag_p1
        y2, z2 = y_base, z_base
        self.pendiente_corte_diag_p1 = None

        linea = self._linea_a_partir_de_dos_puntos(y1, z1, y2, z2)
        if linea is None:
            messagebox.showwarning("Invalid cut", "The two points are too close. Try again.")
            return

        a, b, c = linea
        self.cortes_manuales.append({
            "a": a, "b": b, "c_base": c,
            "tipo": "2P", "meta": {"p1": (y1, z1), "p2": (y2, z2)}
        })
        self.lbl_estado_corte_diag.config(text="Diagonal: inactive", fg="#666")
        self.invalidar_preview_capas()
        self._actualizar_label_cortes_manuales()
        self._refrescar_lista_cortes_manuales()
        self.dibujar(self.slider_sim.get())

    def cambiar_modo_dividir_placas(self):
        """Enable/disable plate sectioning and reset previews to avoid mixed states."""
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()

        # If a layer was being edited, return to the full DXF
        if self.backup_dxf_completo is not None:
            self.lineas = list(self.backup_dxf_completo["lineas"])
            self.offset_y = self.backup_dxf_completo["offset_y"]
            self.offset_z = self.backup_dxf_completo["offset_z"]
            self.editando_capa_idx = None
            self.backup_dxf_completo = None
            self.btn_restaurar_dxf.config(state=tk.DISABLED)
            self.btn_guardar_capa_actual.config(state=tk.DISABLED)

        self.invalidar_preview_capas()
        if self.lineas:
            total_segmentos = len(self.obtener_trayectoria_completa())
            self.slider_sim.config(to=total_segmentos, state=tk.NORMAL)
            self.slider_sim.set(min(self.slider_sim.get(), total_segmentos))
            self.dibujar(self.slider_sim.get())
            self.refrescar_info_tiempo(0.0)
        else:
            self.canvas.delete("all")
            self.dibujar_grilla()
            self.dibujar_canvas_total()

    def invalidar_preview_capas(self):
        self.capas_preview = []
        self.capa_preview_idx = -1
        self.editando_capa_idx = None
        self.btn_capa_prev.config(state=tk.DISABLED)
        self.btn_capa_next.config(state=tk.DISABLED)
        self.btn_vista_total.config(state=tk.DISABLED)
        self.btn_editar_capa.config(state=tk.DISABLED)
        self.btn_guardar_batch_carpeta.config(state=tk.DISABLED)
        self.btn_guardar_capa_actual.config(state=tk.DISABLED)
        self.lbl_capa_preview.config(text="YxZ plate preview: OFF")

    def sincronizar_edicion_capa_si_corresponde(self):
        """If editing a layer, bake offsets into geometry and update layer model data."""
        if self.editando_capa_idx is None:
            return
        if not (0 <= self.editando_capa_idx < len(self.capas_preview)):
            return

        if abs(self.offset_y) > 1e-12 or abs(self.offset_z) > 1e-12:
            self.lineas = [
                (y1 + self.offset_y, z1 + self.offset_z, y2 + self.offset_y, z2 + self.offset_z)
                for (y1, z1, y2, z2) in self.lineas
            ]
            self.offset_y = 0.0
            self.offset_z = 0.0

        self.capas_preview[self.editando_capa_idx]["lineas_edit"] = list(self.lineas)
        self.capas_preview[self.editando_capa_idx]["trayectoria"] = self._obtener_trayectoria_completa_desde(self.lineas, agregar_uniones=True)
        z_base = self.capas_preview[self.editando_capa_idx].get("z_min_orig", 0.0)
        self.capas_preview[self.editando_capa_idx]["lineas_global_edit"] = [
            (y1, z1 + z_base, y2, z2 + z_base)
            for (y1, z1, y2, z2) in self.lineas
        ]

    def dibujar_canvas_total(self):
        if not hasattr(self, "canvas_total"):
            return

        self.canvas_total.delete("all")
        w = int(float(self.canvas_total.cget("width")))
        h = int(float(self.canvas_total.cget("height")))
        self.canvas_total.create_rectangle(0, 0, w, h, outline="#999999")

        # Use global data (no distortion) for auto-fit with real 1:1 axis scale.
        segmentos_base = []
        if self.capas_preview:
            for capa in self.capas_preview:
                for y1, z1, y2, z2 in capa.get("lineas_global_ref", capa.get("lineas_global", [])):
                    segmentos_base.append((y1, z1, y2, z2))
        else:
            for y1, z1, y2, z2 in self.lineas:
                segmentos_base.append((y1 + self.offset_y, z1 + self.offset_z, y2 + self.offset_y, z2 + self.offset_z))

        if not segmentos_base:
            self._actualizar_label_dimensiones_dxf()
            return

        ys = []
        zs = []
        for y1, z1, y2, z2 in segmentos_base:
            ys.extend([y1, y2])
            zs.extend([z1, z2])

        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)
        span_y = max(1e-6, max_y - min_y)
        span_z = max(1e-6, max_z - min_z)

        pad = 10
        sx = (w - 2 * pad) / span_y
        sz = (h - 2 * pad) / span_z
        s = min(sx, sz)

        # Centramos manteniendo aspecto real.
        used_w = span_y * s
        used_h = span_z * s
        ox = pad + (w - 2 * pad - used_w) / 2.0
        oy = pad + (h - 2 * pad - used_h) / 2.0

        def y_to_x(y):
            return ox + (y - min_y) * s

        def z_to_y(z):
            return oy + (max_z - z) * s

        self.total_view_transform = {
            "min_y": min_y,
            "max_y": max_y,
            "min_z": min_z,
            "max_z": max_z,
            "s": s,
            "ox": ox,
            "oy": oy,
            "w": w,
            "h": h,
        }

        # Dibuja referencias de la envolvente
        self.canvas_total.create_rectangle(y_to_x(min_y), z_to_y(max_z), y_to_x(max_y), z_to_y(min_z), outline="#d0d0d0")

        if self.capas_preview:
            paleta = ["#1E88E5", "#43A047", "#F4511E", "#8E24AA", "#00897B", "#6D4C41"]
            for idx, capa in enumerate(self.capas_preview):
                color = paleta[idx % len(paleta)]
                if self.editando_capa_idx == idx:
                    color = "#FFB300"
                for y1, z1, y2, z2 in capa.get("lineas_global_ref", capa.get("lineas_global", [])):
                    self.canvas_total.create_line(y_to_x(y1), z_to_y(z1), y_to_x(y2), z_to_y(z2), fill=color, width=2)
        else:
            for y1, z1, y2, z2 in segmentos_base:
                self.canvas_total.create_line(y_to_x(y1), z_to_y(z1), y_to_x(y2), z_to_y(z2), fill="#1976D2", width=2)

        # Draw manual cuts (reference only)
        if self.usar_cortes_manuales.get() and self.cortes_manuales:
            margen = max(span_y, span_z) * 2.0 + 1000.0
            for c in self.cortes_manuales:
                a, b, cc = self._corte_manual_a_linea_maquina(c)
                pts = []
                if abs(b) > 1e-12:
                    for yv in (min_y - margen, max_y + margen):
                        zv = (-(a * yv) - cc) / b
                        pts.append((yv, zv))
                elif abs(a) > 1e-12:
                    yv = (-cc) / a
                    pts.append((yv, min_z - margen))
                    pts.append((yv, max_z + margen))

                if len(pts) >= 2:
                    (y1, z1), (y2, z2) = pts[0], pts[1]
                    self.canvas_total.create_line(
                        y_to_x(y1), z_to_y(z1), y_to_x(y2), z_to_y(z2),
                        fill="#9C27B0", width=2, dash=(6, 4)
                    )

            if self.pendiente_corte_diag_p1 is not None:
                pyb, pzb = self.pendiente_corte_diag_p1
                py = pyb + self.offset_y
                pz = pzb + self.offset_z
                self.canvas_total.create_oval(
                    y_to_x(py)-4, z_to_y(pz)-4, y_to_x(py)+4, z_to_y(pz)+4,
                    fill="#9C27B0", outline="black"
                )

        self._actualizar_label_dimensiones_dxf()

    def _trayectoria_activa(self):
        """Return (path, uses_offset). Layer previews are already in machine coordinates."""
        if 0 <= self.capa_preview_idx < len(self.capas_preview):
            return self.capas_preview[self.capa_preview_idx]["trayectoria"], False
        return self.obtener_trayectoria_completa(), True

    def _actualizar_label_capa_preview(self):
        if 0 <= self.capa_preview_idx < len(self.capas_preview):
            c = self.capas_preview[self.capa_preview_idx]
            y_info = ""
            if "y_min_orig" in c and "y_max_orig" in c:
                y_info = f"Y orig {c['y_min_orig']:.2f}..{c['y_max_orig']:.2f} mm | "
            self.lbl_capa_preview.config(
                text=(
                    f"Layer preview {self.capa_preview_idx+1}/{len(self.capas_preview)} | "
                    f"{y_info}"
                    f"Z orig {c['z_min_orig']:.2f}..{c['z_max_orig']:.2f} mm"
                )
            )
        else:
            self.lbl_capa_preview.config(text="YxZ plate preview: OFF")

    def activar_vista_total(self):
        self.capa_preview_idx = -1
        self.editando_capa_idx = None
        if self.backup_dxf_completo is not None:
            self.lineas = list(self.backup_dxf_completo["lineas"])
            self.offset_y = self.backup_dxf_completo["offset_y"]
            self.offset_z = self.backup_dxf_completo["offset_z"]
        self.btn_vista_total.config(state=tk.DISABLED)
        self.btn_editar_capa.config(state=tk.DISABLED)
        estado_nav = tk.NORMAL if self.capas_preview else tk.DISABLED
        self.btn_capa_prev.config(state=estado_nav)
        self.btn_capa_next.config(state=estado_nav)
        self._actualizar_label_capa_preview()
        tray, _ = self._trayectoria_activa()
        self.slider_sim.config(to=max(0, len(tray)))
        self.slider_sim.set(len(tray))
        self.dibujar(len(tray))
        self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def mover_preview_capa(self, paso):
        if not self.capas_preview:
            return
        if self.capa_preview_idx < 0:
            self.capa_preview_idx = 0
        else:
            self.capa_preview_idx = (self.capa_preview_idx + paso) % len(self.capas_preview)
        self.btn_vista_total.config(state=tk.NORMAL)
        self.btn_editar_capa.config(state=tk.DISABLED)
        self._cargar_capa_enfocada_para_edicion()
        self._actualizar_label_capa_preview()
        tray, _ = self._trayectoria_activa()
        self.slider_sim.config(to=max(0, len(tray)))
        self.slider_sim.set(len(tray))
        self.dibujar(len(tray))
        self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def generar_preview_capas(self):
        if not self.lineas:
            return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
        if not self.dividir_en_placas.get() and not self.usar_cortes_manuales.get():
            messagebox.showinfo(
                "Section mode disabled",
                "Enable 'Split into plates if area is exceeded' or 'Use manual cuts' to generate split parts."
            )
            return

        corte_base = self.obtener_trayectoria_corte()
        if not corte_base:
            messagebox.showwarning("No paths", "No cut path available to generate layer preview.")
            return

        placa_y = self.limite_y_mm
        placa_z = self.limite_z_mm
        if placa_y <= 0 or placa_z <= 0:
            messagebox.showerror("Invalid usable area", "Set a usable Y and Z area greater than 0 to split by plates.")
            return
        margen_entrada_salida_y = 10.0
        ancho_util_y = placa_y - (2.0 * margen_entrada_salida_y)
        if ancho_util_y <= 1e-9:
            messagebox.showerror(
                "Insufficient Y usable area",
                "The plate Y length must be greater than 20 mm to keep 10 mm entry/exit per plate."
            )
            return

        corte_maquina = []
        z_vals = []
        for y1, z1, y2, z2 in corte_base:
            yy1, zz1 = y1 + self.offset_y, z1 + self.offset_z
            yy2, zz2 = y2 + self.offset_y, z2 + self.offset_z
            corte_maquina.append((yy1, zz1, yy2, zz2))
            z_vals.extend([zz1, zz2])

        if not z_vals:
            messagebox.showwarning("No height", "Could not calculate height for layer preview.")
            return

        # Manual-cut mode: partition by user lines and use normal per-part workflow.
        if self.usar_cortes_manuales.get():
            if not self.cortes_manuales:
                messagebox.showinfo(
                    "No manual cuts",
                    "Add at least one manual cut (Y, Z, or 2-point) in Full View."
                )
                return

            capas = self._construir_capas_desde_cortes_manuales(corte_maquina)
            if not capas:
                messagebox.showwarning("No preview", "Could not generate parts from the defined manual cuts.")
                return

            self.capas_preview = capas
            self.capa_preview_idx = 0
            self._cargar_capa_enfocada_para_edicion()
            self.btn_capa_prev.config(state=tk.NORMAL)
            self.btn_capa_next.config(state=tk.NORMAL)
            self.btn_vista_total.config(state=tk.NORMAL)
            self.btn_editar_capa.config(state=tk.DISABLED)
            self.btn_guardar_batch_carpeta.config(state=tk.NORMAL)
            self._actualizar_label_capa_preview()

            tray, _ = self._trayectoria_activa()
            self.slider_sim.config(to=max(0, len(tray)))
            self.slider_sim.set(len(tray))
            self.dibujar(len(tray))
            self.refrescar_info_tiempo(0.0)
            return

        ys = []
        for y1, _z1, y2, _z2 in corte_maquina:
            ys.extend([y1, y2])
        y_min = min(ys)
        y_max = max(ys)
        z_min = min(z_vals)
        z_max = max(z_vals)

        ancho_total = max(0.0, y_max - y_min)
        alto_total = max(0.0, z_max - z_min)
        if ancho_total <= 1e-9 and alto_total <= 1e-9:
            messagebox.showwarning("Null geometry", "Could not detect cut width/height to split by plates.")
            return

        total_cols = max(1, int(math.ceil(max(1e-9, ancho_total) / ancho_util_y)))
        total_rows = max(1, int(math.ceil(max(1e-9, alto_total) / placa_z)))

        capas = []
        for fila in range(total_rows):
            capa_z_min = z_min + (fila * placa_z)
            capa_z_max = min(z_min + ((fila + 1) * placa_z), z_max)
            for col in range(total_cols):
                capa_y_min = y_min + (col * ancho_util_y)
                capa_y_max = min(y_min + ((col + 1) * ancho_util_y), y_max)

                segmentos_capa = []
                segmentos_globales_capa = []
                for y1, z1, y2, z2 in corte_maquina:
                    rec = self._clip_segmento_a_rect(y1, z1, y2, z2, capa_y_min, capa_y_max, capa_z_min, capa_z_max)
                    if rec is None:
                        continue
                    cy1, cz1, cy2, cz2 = rec
                    if math.hypot(cy2 - cy1, cz2 - cz1) <= 1e-6:
                        continue
                    segmentos_globales_capa.append((cy1, cz1, cy2, cz2))
                    # Reservamos 10 mm al inicio y 10 mm al final en Y para entrada/salida segura.
                    segmentos_capa.append((
                        (cy1 - capa_y_min) + margen_entrada_salida_y,
                        cz1 - capa_z_min,
                        (cy2 - capa_y_min) + margen_entrada_salida_y,
                        cz2 - capa_z_min,
                    ))

                if not segmentos_capa:
                    continue

                tray_capa = self._obtener_trayectoria_completa_desde(segmentos_capa, agregar_uniones=True)
                if not tray_capa:
                    continue

                capas.append({
                    "trayectoria": tray_capa,
                    "lineas_edit": segmentos_capa,
                    "lineas_global_ref": list(segmentos_globales_capa),
                    "lineas_global_edit": list(segmentos_globales_capa),
                    "y_min_orig": capa_y_min,
                    "y_max_orig": capa_y_max,
                    "z_min_orig": capa_z_min,
                    "z_max_orig": capa_z_max,
                    "fila": fila + 1,
                    "columna": col + 1,
                })

        if not capas:
            messagebox.showwarning("No preview", "Could not generate any viewable plate with the specified YxZ usable area.")
            return

        self.capas_preview = capas
        self.capa_preview_idx = 0
        self._cargar_capa_enfocada_para_edicion()
        self.btn_capa_prev.config(state=tk.NORMAL)
        self.btn_capa_next.config(state=tk.NORMAL)
        self.btn_vista_total.config(state=tk.NORMAL)
        self.btn_editar_capa.config(state=tk.DISABLED)
        self.btn_guardar_batch_carpeta.config(state=tk.NORMAL)
        self._actualizar_label_capa_preview()

        tray, _ = self._trayectoria_activa()
        self.slider_sim.config(to=max(0, len(tray)))
        self.slider_sim.set(len(tray))
        self.dibujar(len(tray))
        self.refrescar_info_tiempo(0.0)

    def editar_capa_actual(self):
        """Convert the previewed layer into independently editable geometry."""
        self._cargar_capa_enfocada_para_edicion()

    def _cargar_capa_enfocada_para_edicion(self):
        """Automatically load the focused layer for editing (no manual button needed)."""
        if not (0 <= self.capa_preview_idx < len(self.capas_preview)):
            return

        if self.backup_dxf_completo is None:
            self.backup_dxf_completo = {
                "lineas": list(self.lineas),
                "offset_y": self.offset_y,
                "offset_z": self.offset_z,
            }

        capa = self.capas_preview[self.capa_preview_idx]
        self.lineas = list(capa["lineas_edit"])
        self.offset_y = 0.0
        self.offset_z = 0.0
        self.editando_capa_idx = self.capa_preview_idx
        self.btn_restaurar_dxf.config(state=tk.NORMAL)
        self.btn_guardar_capa_actual.config(state=tk.NORMAL)

    def restaurar_dxf_completo(self):
        """Restore full original geometry after editing layers individually."""
        if self.backup_dxf_completo is None:
            return

        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()

        self.lineas = list(self.backup_dxf_completo["lineas"])
        self.offset_y = self.backup_dxf_completo["offset_y"]
        self.offset_z = self.backup_dxf_completo["offset_z"]
        self.editando_capa_idx = None
        self.backup_dxf_completo = None
        self.btn_restaurar_dxf.config(state=tk.DISABLED)
        self.btn_guardar_capa_actual.config(state=tk.DISABLED)

        self.invalidar_preview_capas()
        total_segmentos = len(self.obtener_trayectoria_completa())
        self.slider_sim.config(to=total_segmentos, state=tk.NORMAL)
        self.slider_sim.set(total_segmentos)
        self.dibujar(total_segmentos)
        self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def guardar_capa_enfocada(self):
        if self.editando_capa_idx is None:
            messagebox.showwarning("No focused layer", "Focus a layer first with 'Auto-edit focused layer'.")
            return

        self.sincronizar_edicion_capa_si_corresponde()
        try:
            v_corte_mms = float(self.vel_corte.get())
            if v_corte_mms <= 0:
                raise ValueError()
            v_mov_mmin = int(v_corte_mms * 60)
        except ValueError:
            messagebox.showerror("Error", "Cut speed must be a number greater than 0.")
            return

        base = self.nombre_lote_capas.get().strip() or "cut"
        nombre_sugerido = f"{base}_layer{self.editando_capa_idx+1:02d}.gcode"
        ruta = filedialog.asksaveasfilename(
            title="Save focused layer G-Code",
            initialfile=nombre_sugerido,
            defaultextension=".gcode",
            filetypes=[("G-Code", "*.gcode")]
        )
        if not ruta:
            return

        tray = self.obtener_trayectoria_completa()
        gcode = self._generar_gcode_desde_trayectoria(
            tray,
            v_mov_mmin,
            encabezado_extra=[f"Focused layer {self.editando_capa_idx+1}"]
        )
        with open(ruta, "w") as f:
            f.write("\n".join(gcode))
        messagebox.showinfo("Saved", f"Layer saved to:\n{ruta}")

    def guardar_batch_en_carpeta(self):
        if self.editando_capa_idx is not None:
            self.sincronizar_edicion_capa_si_corresponde()

        if not self.capas_preview:
            self.generar_preview_capas()
            if not self.capas_preview:
                return

        try:
            v_corte_mms = float(self.vel_corte.get())
            if v_corte_mms <= 0:
                raise ValueError()
            v_mov_mmin = int(v_corte_mms * 60)
        except ValueError:
            messagebox.showerror("Error", "Cut speed must be a number greater than 0.")
            return

        carpeta = filedialog.askdirectory(title="Select folder to save layer batch")
        if not carpeta:
            return

        base = self.nombre_lote_capas.get().strip() or "cut"
        total = len(self.capas_preview)
        guardados = 0
        for i, capa in enumerate(self.capas_preview, start=1):
            tray = self._obtener_trayectoria_completa_desde(capa["lineas_edit"], agregar_uniones=False)
            gcode = self._generar_gcode_desde_trayectoria(
                tray,
                v_mov_mmin,
                encabezado_extra=[
                    f"Layer batch {i}/{total}",
                    f"Z orig {capa['z_min_orig']:.3f}..{capa['z_max_orig']:.3f}"
                ]
            )
            nombre = f"{base}_layer{i:02d}_of_{total:02d}.gcode"
            ruta = os.path.join(carpeta, nombre)
            with open(ruta, "w") as f:
                f.write("\n".join(gcode))
            guardados += 1

        messagebox.showinfo("Batch saved", f"Saved {guardados} files in:\n{carpeta}")

    def formatear_tiempo(self, segundos):
        total = max(0, int(round(segundos)))
        mm = total // 60
        ss = total % 60
        return f"{mm:02d}:{ss:02d}"

    def calcular_duraciones_trayectoria(self):
        trayectoria, _usa_offset = self._trayectoria_activa()
        if not trayectoria:
            return []

        try:
            vel_mms = float(self.vel_corte.get())
            if vel_mms <= 0:
                return []
        except ValueError:
            return []

        duraciones = []
        for (y1, z1, y2, z2, _tipo) in trayectoria:
            dist = math.hypot(y2 - y1, z2 - z1)
            duraciones.append(dist / vel_mms)
        return duraciones

    def refrescar_info_tiempo(self, transcurrido_seg=0.0):
        duraciones = self.calcular_duraciones_trayectoria()
        self.tiempo_total_seg = sum(duraciones)
        self.lbl_tiempo.config(
            text=f"Estimated time: {self.formatear_tiempo(self.tiempo_total_seg)} | Elapsed: {self.formatear_tiempo(transcurrido_seg)}"
        )
        self.refrescar_info_altura()

    def calcular_altura_corte_actual(self):
        trayectoria, usa_offset = self._trayectoria_activa()
        if not trayectoria:
            return None

        z_vals = []
        for y1, z1, y2, z2, tipo in trayectoria:
            if tipo == "corte":
                if usa_offset:
                    z_vals.extend([z1 + self.offset_z, z2 + self.offset_z])
                else:
                    z_vals.extend([z1, z2])

        if not z_vals:
            for _y1, z1, _y2, z2, _tipo in trayectoria:
                if usa_offset:
                    z_vals.extend([z1 + self.offset_z, z2 + self.offset_z])
                else:
                    z_vals.extend([z1, z2])

        z_min = min(z_vals)
        z_max = max(z_vals)
        return z_max - z_min, z_min, z_max

    def refrescar_info_altura(self):
        info = self.calcular_altura_corte_actual()
        if info is None:
            self.lbl_altura.config(text="Max cut height: -- mm (Zmin -- / Zmax --)")
            return

        altura, z_min, z_max = info
        self.lbl_altura.config(
            text=f"Max cut height: {altura:.2f} mm (Zmin {z_min:.2f} / Zmax {z_max:.2f})"
        )

    def iniciar_simulacion_tiempo_real(self):
        if not self.lineas or self.reproduciendo:
            return

        duraciones = self.calcular_duraciones_trayectoria()
        if not duraciones:
            messagebox.showwarning("Invalid speed", "Set a cut speed greater than 0 mm/s.")
            return

        self.reproduciendo = True
        self.tiempo_acumulado_seg = 0.0
        self.tiempo_inicio_play = time.perf_counter()
        self.play_last_slider_idx = -1
        self.play_duraciones = duraciones
        self.actualizando_slider_interno = True
        self.slider_sim.set(0)
        self.actualizando_slider_interno = False
        self.dibujar(0)
        self.btn_play.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.refrescar_info_tiempo(0.0)
        self._paso_simulacion_tiempo_real()

    def _paso_simulacion_tiempo_real(self):
        if not self.reproduciendo:
            return

        duraciones = self.play_duraciones
        total_segmentos = len(duraciones)
        tiempo_total = sum(duraciones)
        transcurrido = max(0.0, time.perf_counter() - self.tiempo_inicio_play)

        if transcurrido >= tiempo_total:
            self.reproduciendo = False
            self.btn_play.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            self.play_last_slider_idx = total_segmentos
            self.actualizando_slider_interno = True
            self.slider_sim.set(total_segmentos)
            self.actualizando_slider_interno = False
            self.dibujar(total_segmentos)
            self.refrescar_info_tiempo(self.tiempo_total_seg)
            self.play_after_id = None
            return

        acumulado = 0.0
        progreso = 0.0
        for i, d in enumerate(duraciones):
            siguiente = acumulado + d
            if transcurrido <= siguiente:
                if d <= 1e-9:
                    progreso = float(i + 1)
                else:
                    progreso = i + ((transcurrido - acumulado) / d)
                break
            acumulado = siguiente
        else:
            progreso = float(total_segmentos)

        idx_slider = int(math.floor(progreso))
        if idx_slider != self.play_last_slider_idx:
            self.play_last_slider_idx = idx_slider
            self.actualizando_slider_interno = True
            self.slider_sim.set(idx_slider)
            self.actualizando_slider_interno = False
        self.dibujar(progreso)
        self.refrescar_info_tiempo(transcurrido)

        self.play_after_id = self.root.after(30, self._paso_simulacion_tiempo_real)

    def detener_simulacion_tiempo_real(self):
        self.reproduciendo = False
        if self.play_after_id is not None:
            self.root.after_cancel(self.play_after_id)
            self.play_after_id = None
        self.play_duraciones = []
        self.play_last_slider_idx = -1
        self.btn_play.config(state=tk.NORMAL if self.lineas else tk.DISABLED)
        self.btn_stop.config(state=tk.DISABLED)
        self.refrescar_info_tiempo(0.0)

    def _rotar_lineas_sobre_origen(self, lineas, angulo_grados):
        ang_rad = math.radians(angulo_grados)
        cos_a = math.cos(ang_rad)
        sin_a = math.sin(ang_rad)
        rotadas = []
        for y1, z1, y2, z2 in lineas:
            ry1 = (y1 * cos_a) - (z1 * sin_a)
            rz1 = (y1 * sin_a) + (z1 * cos_a)
            ry2 = (y2 * cos_a) - (z2 * sin_a)
            rz2 = (y2 * sin_a) + (z2 * cos_a)
            rotadas.append((ry1, rz1, ry2, rz2))
        return rotadas

    def _obtener_trayectoria_corte_desde(self, lineas_base):
        """Return a continuous path starting from the leftmost endpoint in a segment set."""
        if not lineas_base:
            return []

        tol = 1e-5
        segmentos = list(lineas_base)
        usados = [False] * len(segmentos)

        # Start from the leftmost endpoint across all segment ends
        mejor_idx = 0
        mejor_inv = False
        mejor_key = None
        for i, (y1, z1, y2, z2) in enumerate(segmentos):
            k1 = (y1, z1)
            k2 = (y2, z2)
            if mejor_key is None or k1 < mejor_key:
                mejor_key = k1
                mejor_idx = i
                mejor_inv = False
            if k2 < mejor_key:
                mejor_key = k2
                mejor_idx = i
                mejor_inv = True

        trayectoria = []
        y1, z1, y2, z2 = segmentos[mejor_idx]
        if mejor_inv:
            y1, z1, y2, z2 = y2, z2, y1, z1
        trayectoria.append((y1, z1, y2, z2))
        usados[mejor_idx] = True
        fin_y, fin_z = y2, z2

        # Chain segments by geometric continuity
        for _ in range(len(segmentos) - 1):
            elegido = None
            inv = False
            mejor_d = None

            for i, (a1, b1, a2, b2) in enumerate(segmentos):
                if usados[i]:
                    continue

                d1 = math.hypot(a1 - fin_y, b1 - fin_z)
                d2 = math.hypot(a2 - fin_y, b2 - fin_z)

                # preferimos continuidad exacta o casi exacta
                if d1 <= tol:
                    elegido = i
                    inv = False
                    mejor_d = d1
                    break
                if d2 <= tol:
                    elegido = i
                    inv = True
                    mejor_d = d2
                    break

                d = min(d1, d2)
                if mejor_d is None or d < mejor_d:
                    mejor_d = d
                    elegido = i
                    inv = (d2 < d1)

            if elegido is None:
                break

            usados[elegido] = True
            a1, b1, a2, b2 = segmentos[elegido]
            if inv:
                a1, b1, a2, b2 = a2, b2, a1, b1
            trayectoria.append((a1, b1, a2, b2))
            fin_y, fin_z = a2, b2

        if self.corte_invertido:
            trayectoria = [(y2, z2, y1, z1) for (y1, z1, y2, z2) in reversed(trayectoria)]

        return trayectoria

    def obtener_trayectoria_corte(self):
        """Return a continuous path starting from the leftmost point in the DXF."""
        return self._obtener_trayectoria_corte_desde(self.lineas)

    def _obtener_trayectoria_completa_desde(self, lineas_base, agregar_uniones=False):
        """Return full path for a segment set.

        Rules:
        - 10 mm horizontal entry toward the cut start
        - 10 mm horizontal exit from the cut end
        - return to the same start point (orange point), so start/end match exactly
        - if agregar_uniones=True, insert straight links between disconnected segments.
        """
        corte = self._obtener_trayectoria_corte_desde(lineas_base)
        if not corte:
            return []

        corte_tipado = [(y1, z1, y2, z2, "corte") for (y1, z1, y2, z2) in corte]

        if agregar_uniones:
            corte_con_uniones = []
            for i, (y1, z1, y2, z2, _tipo) in enumerate(corte_tipado):
                corte_con_uniones.append((y1, z1, y2, z2, "corte"))
                if i < len(corte_tipado) - 1:
                    ny1, nz1, _ny2, _nz2, _nt = corte_tipado[i + 1]
                    if math.hypot(ny1 - y2, nz1 - z2) > 1e-6:
                        corte_con_uniones.append((y2, z2, ny1, nz1, "union"))
            corte_tipado = corte_con_uniones

        if not corte_tipado:
            return []

        inicio_y, inicio_z = corte_tipado[0][0], corte_tipado[0][1]
        dir_inicio = corte_tipado[0][2] - corte_tipado[0][0]
        signo_inicio = 1.0 if dir_inicio >= 0 else -1.0
        entrada_y = inicio_y - (10.0 * signo_inicio)
        entrada = (entrada_y, inicio_z, inicio_y, inicio_z, "entrada")

        fin_y, fin_z = corte_tipado[-1][2], corte_tipado[-1][3]
        dir_fin = corte_tipado[-1][2] - corte_tipado[-1][0]
        signo_fin = 1.0 if dir_fin >= 0 else -1.0
        salida_y = fin_y + (10.0 * signo_fin)
        salida = (fin_y, fin_z, salida_y, fin_z, "salida")

        # External return to the same operational start point (orange point)
        # 1) horizontal hasta Y de entrada
        # 2) vertical final solo si Z difiere
        retorno = []
        if abs(salida_y - entrada_y) > 1e-9:
            retorno.append((salida_y, fin_z, entrada_y, fin_z, "retorno_h"))
        if abs(fin_z - inicio_z) > 1e-9:
            retorno.append((entrada_y, fin_z, entrada_y, inicio_z, "retorno_v"))

        return [entrada] + corte_tipado + [salida] + retorno

    def obtener_trayectoria_completa(self):
        """Return path with 10 mm horizontal entry/exit.

        Cada item: (y1, z1, y2, z2, tipo)
        tipo: 'entrada' | 'corte' | 'salida' | 'retorno_h' | 'retorno_v'
        """
        return self._obtener_trayectoria_completa_desde(self.lineas, agregar_uniones=False)

    def _clip_segmento_a_banda_z(self, y1, z1, y2, z2, z_min, z_max):
        """Recorta un segmento a la banda horizontal [z_min, z_max]. Devuelve None si no intersecta."""
        dz = z2 - z1
        t0, t1 = 0.0, 1.0

        # Restricción inferior: z(t) >= z_min
        if abs(dz) < 1e-12:
            if z1 < z_min:
                return None
        else:
            t = (z_min - z1) / dz
            if dz > 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)

        # Restricción superior: z(t) <= z_max
        if abs(dz) < 1e-12:
            if z1 > z_max:
                return None
        else:
            t = (z_max - z1) / dz
            if dz > 0:
                t1 = min(t1, t)
            else:
                t0 = max(t0, t)

        if t0 > t1:
            return None

        cy1 = y1 + (y2 - y1) * t0
        cz1 = z1 + (z2 - z1) * t0
        cy2 = y1 + (y2 - y1) * t1
        cz2 = z1 + (z2 - z1) * t1
        return (cy1, cz1, cy2, cz2)

    def _clip_segmento_a_banda_y(self, y1, z1, y2, z2, y_min, y_max):
        """Recorta un segmento a la banda vertical [y_min, y_max]. Devuelve None si no intersecta."""
        dy = y2 - y1
        t0, t1 = 0.0, 1.0

        # Restricción inferior: y(t) >= y_min
        if abs(dy) < 1e-12:
            if y1 < y_min:
                return None
        else:
            t = (y_min - y1) / dy
            if dy > 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)

        # Restricción superior: y(t) <= y_max
        if abs(dy) < 1e-12:
            if y1 > y_max:
                return None
        else:
            t = (y_max - y1) / dy
            if dy > 0:
                t1 = min(t1, t)
            else:
                t0 = max(t0, t)

        if t0 > t1:
            return None

        cy1 = y1 + (y2 - y1) * t0
        cz1 = z1 + (z2 - z1) * t0
        cy2 = y1 + (y2 - y1) * t1
        cz2 = z1 + (z2 - z1) * t1
        return (cy1, cz1, cy2, cz2)

    def _clip_segmento_a_rect(self, y1, z1, y2, z2, y_min, y_max, z_min, z_max):
        """Clip a segment to rectangle [y_min,y_max] x [z_min,z_max]."""
        rec_y = self._clip_segmento_a_banda_y(y1, z1, y2, z2, y_min, y_max)
        if rec_y is None:
            return None
        ry1, rz1, ry2, rz2 = rec_y
        rec_z = self._clip_segmento_a_banda_z(ry1, rz1, ry2, rz2, z_min, z_max)
        return rec_z

    def _split_segmento_por_linea(self, y1, z1, y2, z2, a, b, c):
        """Return subsegment list when splitting by line a*y+b*z+c=0."""
        eps = 1e-9

        f1 = (a * y1) + (b * z1) + c
        f2 = (a * y2) + (b * z2) + c

        # Full segment on line or same side: no real split
        if abs(f1) <= eps and abs(f2) <= eps:
            return [(y1, z1, y2, z2)]
        if (f1 > eps and f2 > eps) or (f1 < -eps and f2 < -eps):
            return [(y1, z1, y2, z2)]

        den = (f1 - f2)
        if abs(den) <= eps:
            return [(y1, z1, y2, z2)]

        t = f1 / den
        if t <= eps or t >= (1.0 - eps):
            return [(y1, z1, y2, z2)]

        yi = y1 + ((y2 - y1) * t)
        zi = z1 + ((z2 - z1) * t)
        return [(y1, z1, yi, zi), (yi, zi, y2, z2)]

    def _deduplicar_puntos(self, puntos, tol=1e-6):
        """Deduplicate 2D points by proximity and return stable list."""
        unicos = []
        for y, z in puntos:
            repetido = False
            for uy, uz in unicos:
                if math.hypot(y - uy, z - uz) <= tol:
                    repetido = True
                    break
            if not repetido:
                unicos.append((y, z))
        return unicos

    def _segmentos_corte_internos_desde_intersecciones(self, segmentos_base, lineas_corte, eps=1e-7):
        """Construye aristas internas de corte entre pares de intersecciones del contorno.

        Emula el comportamiento de regiones/caras de un sketch CAD.
        """
        internos = []
        for a, b, c in lineas_corte:
            pts = []
            for y1, z1, y2, z2 in segmentos_base:
                f1 = (a * y1) + (b * z1) + c
                f2 = (a * y2) + (b * z2) + c

                if abs(f1) <= eps and abs(f2) <= eps:
                    continue

                if abs(f1) <= eps:
                    pts.append((y1, z1))
                if abs(f2) <= eps:
                    pts.append((y2, z2))

                if (f1 > eps and f2 < -eps) or (f1 < -eps and f2 > eps):
                    den = (f1 - f2)
                    if abs(den) > eps:
                        t = f1 / den
                        if -eps <= t <= (1.0 + eps):
                            yi = y1 + ((y2 - y1) * t)
                            zi = z1 + ((z2 - z1) * t)
                            pts.append((yi, zi))

            pts = self._deduplicar_puntos(pts, tol=1e-5)
            if len(pts) < 2:
                continue

            dy, dz = -b, a
            pts_orden = sorted(pts, key=lambda p: (p[0] * dy) + (p[1] * dz))

            for i in range(0, len(pts_orden) - 1, 2):
                (y1, z1), (y2, z2) = pts_orden[i], pts_orden[i + 1]
                if math.hypot(y2 - y1, z2 - z1) > 1e-6:
                    internos.append((y1, z1, y2, z2))

        return internos

    def _snap_segmentos(self, segmentos, tol=1e-5):
        """Snap segment endpoints to shared nodes to avoid numerical micro-gaps."""
        if not segmentos:
            return []

        nodos = {}

        def key(y, z):
            return (int(round(y / tol)), int(round(z / tol)))

        for y1, z1, y2, z2 in segmentos:
            for y, z in ((y1, z1), (y2, z2)):
                k = key(y, z)
                if k not in nodos:
                    nodos[k] = [y, z, 1]
                else:
                    nodos[k][0] += y
                    nodos[k][1] += z
                    nodos[k][2] += 1

        centros = {k: (v[0] / v[2], v[1] / v[2]) for k, v in nodos.items()}

        out = []
        for y1, z1, y2, z2 in segmentos:
            ny1, nz1 = centros[key(y1, z1)]
            ny2, nz2 = centros[key(y2, z2)]
            if math.hypot(ny2 - ny1, nz2 - nz1) > 1e-6:
                out.append((ny1, nz1, ny2, nz2))
        return out

    def _construir_capas_desde_cortes_manuales(self, corte_maquina):
        """Partition cut geometry by manual lines and return layers/parts for standard flow."""
        if not corte_maquina:
            return []
        if not self.cortes_manuales:
            return []

        lineas_corte_maquina = [self._corte_manual_a_linea_maquina(c) for c in self.cortes_manuales]

        # 1) split contour by all cut lines
        segmentitos = list(corte_maquina)
        for a, b, c in lineas_corte_maquina:
            nuevos = []
            for y1, z1, y2, z2 in segmentitos:
                nuevos.extend(self._split_segmento_por_linea(y1, z1, y2, z2, a, b, c))
            segmentitos = nuevos

        # 2) internal cut edges (contour-line intersection paired)
        aristas_internas = self._segmentos_corte_internos_desde_intersecciones(corte_maquina, lineas_corte_maquina)

        # 3) unify and split again to insert nodes at crossings
        todos = segmentitos + aristas_internas
        for a, b, c in lineas_corte_maquina:
            nuevos = []
            for y1, z1, y2, z2 in todos:
                nuevos.extend(self._split_segmento_por_linea(y1, z1, y2, z2, a, b, c))
            todos = nuevos
        todos = self._snap_segmentos(todos)

        # 4) group by region (side signature with respect to each cut)
        #    on-line segments (state 0) are assigned to both neighboring regions.
        eps = 1e-7
        regiones = {}
        firmas_existentes = set()
        segs_estados = []

        for y1, z1, y2, z2 in todos:
            if math.hypot(y2 - y1, z2 - z1) <= 1e-6:
                continue

            ym = (y1 + y2) * 0.5
            zm = (z1 + z2) * 0.5
            estados = []
            for a, b, c in lineas_corte_maquina:
                fv = (a * ym) + (b * zm) + c
                if fv > eps:
                    estados.append(1)
                elif fv < -eps:
                    estados.append(-1)
                else:
                    estados.append(0)

            if all(s != 0 for s in estados):
                firmas_existentes.add(tuple(estados))
            segs_estados.append((y1, z1, y2, z2, estados))

        if not firmas_existentes:
            firmas_existentes = {tuple([1] * len(lineas_corte_maquina))}

        for y1, z1, y2, z2, estados in segs_estados:
            candidatas = [()]
            for s in estados:
                if s == 0:
                    candidatas = [c + (-1,) for c in candidatas] + [c + (1,) for c in candidatas]
                else:
                    candidatas = [c + (s,) for c in candidatas]

            candidatas = [f for f in candidatas if f in firmas_existentes]
            if not candidatas:
                candidatas = [tuple(1 if s == 0 else s for s in estados)]

            for firma in candidatas:
                regiones.setdefault(firma, []).append((y1, z1, y2, z2))

        capas = []
        for idx, (_firma, segs) in enumerate(regiones.items(), start=1):
            if not segs:
                continue

            segs = self._snap_segmentos(segs)

            if self.auto_cerrar_cortes_manuales.get():
                segs = self._cerrar_contornos_abiertos(segs)

            ys = []
            zs = []
            for y1, z1, y2, z2 in segs:
                ys.extend([y1, y2])
                zs.extend([z1, z2])

            y_min = min(ys)
            y_max = max(ys)
            z_min = min(zs)
            z_max = max(zs)

            segs_local = [
                (y1 - y_min, z1 - z_min, y2 - y_min, z2 - z_min)
                for (y1, z1, y2, z2) in segs
            ]
            segs_local = self._snap_segmentos(segs_local)

            # In manual cuts, avoid automatic diagonal unions between islands.
            tray = self._obtener_trayectoria_completa_desde(segs_local, agregar_uniones=False)
            if not tray:
                continue

            capas.append({
                "trayectoria": tray,
                "lineas_edit": segs_local,
                "lineas_global_ref": list(segs),
                "lineas_global_edit": list(segs),
                "y_min_orig": y_min,
                "y_max_orig": y_max,
                "z_min_orig": z_min,
                "z_max_orig": z_max,
                "pieza_idx": idx,
            })

        return capas

    def _cerrar_contornos_abiertos(self, segmentos, tol=1e-5):
        """Close open contours by connecting degree-1 endpoints with straight cuts.

        Useful after splitting a closed profile with manual lines to avoid diagonal travels.
        """
        if not segmentos:
            return []

        nodos = []  # [{"y":...,"z":...,"deg":...}]

        def obtener_nodo(y, z):
            for i, n in enumerate(nodos):
                if abs(n["y"] - y) <= tol and abs(n["z"] - z) <= tol:
                    # Smooth average to stabilize accumulation
                    n["y"] = (n["y"] + y) * 0.5
                    n["z"] = (n["z"] + z) * 0.5
                    return i
            nodos.append({"y": y, "z": z, "deg": 0})
            return len(nodos) - 1

        segs = list(segmentos)
        for y1, z1, y2, z2 in segs:
            i1 = obtener_nodo(y1, z1)
            i2 = obtener_nodo(y2, z2)
            nodos[i1]["deg"] += 1
            nodos[i2]["deg"] += 1

        extremos = [i for i, n in enumerate(nodos) if n["deg"] == 1]
        usados = set()
        cierres = []

        for i in extremos:
            if i in usados:
                continue
            yi, zi = nodos[i]["y"], nodos[i]["z"]
            mejor = None
            mejor_d = None
            for j in extremos:
                if j == i or j in usados:
                    continue
                yj, zj = nodos[j]["y"], nodos[j]["z"]
                d = math.hypot(yj - yi, zj - zi)
                if mejor is None or d < mejor_d:
                    mejor = j
                    mejor_d = d
            if mejor is None:
                continue
            usados.add(i)
            usados.add(mejor)
            yj, zj = nodos[mejor]["y"], nodos[mejor]["z"]
            if math.hypot(yj - yi, zj - zi) > tol:
                cierres.append((yi, zi, yj, zj))

        return segs + cierres

    def _generar_gcode_desde_trayectoria(self, trayectoria, v_mov_mmin, encabezado_extra=None):
        """Generate G-code lines from a path already positioned in machine coordinates."""
        gcode = []
        gcode.append(";FLAVOR:Marlin")
        gcode.append(";TARGET_MACHINE.NAME:Ender-3 Hot Wire CNC")
        if encabezado_extra:
            for linea in encabezado_extra:
                gcode.append(f";{linea}")
        gcode.append("G21 ; Units in millimeters")
        gcode.append("G90 ; Absolute positioning")
        gcode.append("M140 S0 ; Turn off bed temperature")
        gcode.append("M104 S0 ; Turn off hotend temperature")
        gcode.append("M107 ; Turn off layer fan")
        gcode.append("G92 Y0 Z0 ; Set current position as origin (0,0)")
        gcode.append(";--- CUT START ---")

        y_actual, z_actual = 0.0, 0.0
        for (y1, z1, y2, z2, tipo) in trayectoria:
            y1_mod = round(y1, 3)
            z1_mod = round(z1, 3)
            y2_mod = round(y2, 3)
            z2_mod = round(z2, 3)

            if (abs(y_actual - y1_mod) > 1e-6) or (abs(z_actual - z1_mod) > 1e-6):
                gcode.append(f"G1 F{v_mov_mmin} Y{y1_mod} Z{z1_mod}")

            if tipo == "entrada":
                gcode.append("; 10mm entry")
            elif tipo == "salida":
                gcode.append("; 10mm exit")
            elif tipo == "retorno_h":
                gcode.append("; Horizontal return to origin Y")
            elif tipo == "retorno_v":
                gcode.append("; Final Z adjustment to close exactly at origin")
            elif tipo == "union":
                gcode.append("; Straight union between segments")
            gcode.append(f"G1 F{v_mov_mmin} Y{y2_mod} Z{z2_mod}")

            y_actual, z_actual = y2_mod, z2_mod

        gcode.append(";--- CUT END ---")
        gcode.append(f"G1 F{v_mov_mmin} Y0 Z0 ; Smooth return to initial origin")
        gcode.append("M84 ; Turn off motors")
        return gcode

    def _obtener_segmentos_para_exportar_dxf(self):
        """Return segments (y1,z1,y2,z2) for DXF export in active view/state."""
        if 0 <= self.capa_preview_idx < len(self.capas_preview):
            capa = self.capas_preview[self.capa_preview_idx]
            return list(capa.get("lineas_edit", []))

        return [
            (y1 + self.offset_y, z1 + self.offset_z, y2 + self.offset_y, z2 + self.offset_z)
            for (y1, z1, y2, z2) in self.lineas
        ]

    def exportar_dxf_modificado(self):
        """Export current modified geometry to DXF (not G-code)."""
        segmentos = self._obtener_segmentos_para_exportar_dxf()
        if not segmentos:
            messagebox.showwarning("No geometry", "No segments available to export to DXF.")
            return

        ruta_dxf = filedialog.asksaveasfilename(
            title="Save Modified DXF",
            defaultextension=".dxf",
            filetypes=[("DXF files", "*.dxf")]
        )
        if not ruta_dxf:
            return

        try:
            doc_out = ezdxf.new("R2010")
            try:
                doc_out.units = 4  # millimeters
            except Exception:
                pass
            msp_out = doc_out.modelspace()

            agregados = 0
            for y1, z1, y2, z2 in segmentos:
                if math.hypot(y2 - y1, z2 - z1) <= 1e-9:
                    continue
                msp_out.add_line((round(y1, 6), round(z1, 6)), (round(y2, 6), round(z2, 6)))
                agregados += 1

            if agregados <= 0:
                messagebox.showwarning("No valid segments", "No valid segments were found to export to DXF.")
                return

            doc_out.saveas(ruta_dxf)
            messagebox.showinfo("DXF exported", f"Modified DXF exported with {agregados} segments.\n\n{ruta_dxf}")
        except Exception as ex:
            messagebox.showerror("DXF error", f"Could not export modified DXF:\n{ex}")

    def exportar_gcode_por_capas(self):
        if not self.lineas:
            return
        if not self.dividir_en_placas.get() and not self.usar_cortes_manuales.get():
            messagebox.showinfo(
                "Section mode disabled",
                "Enable 'Split into plates if area is exceeded' or 'Use manual cuts' to export split parts."
            )
            return

        # Si estamos en modo manual, reutilizamos preview para obtener las piezas seccionadas.
        if self.usar_cortes_manuales.get():
            if self.editando_capa_idx is not None:
                self.sincronizar_edicion_capa_si_corresponde()

            if not self.capas_preview:
                self.generar_preview_capas()
                if not self.capas_preview:
                    return

            try:
                v_corte_mms = float(self.vel_corte.get())
                if v_corte_mms <= 0:
                    raise ValueError()
                v_mov_mmin = int(v_corte_mms * 60)
            except ValueError:
                messagebox.showerror("Error", "Cut speed must be a number greater than 0.")
                return

            ruta_base = filedialog.asksaveasfilename(
                title="Save manual-cut G-Code batch",
                defaultextension=".gcode",
                filetypes=[("G-Code", "*.gcode")]
            )
            if not ruta_base:
                return

            base_dir = os.path.dirname(ruta_base)
            base_name = os.path.splitext(os.path.basename(ruta_base))[0]
            total = len(self.capas_preview)
            exportados = 0

            for i, capa in enumerate(self.capas_preview, start=1):
                tray = self._obtener_trayectoria_completa_desde(capa["lineas_edit"], agregar_uniones=False)
                gcode = self._generar_gcode_desde_trayectoria(
                    tray,
                    v_mov_mmin,
                    encabezado_extra=[
                        f"Manual cuts - part {i}/{total}",
                        f"Original Y range: {capa.get('y_min_orig', 0.0):.3f} .. {capa.get('y_max_orig', 0.0):.3f}",
                        f"Original Z range: {capa.get('z_min_orig', 0.0):.3f} .. {capa.get('z_max_orig', 0.0):.3f}"
                    ]
                )
                ruta_out = os.path.join(base_dir, f"{base_name}_manual_part{i:02d}_of_{total:02d}.gcode")
                with open(ruta_out, "w") as f:
                    f.write("\n".join(gcode))
                exportados += 1

            messagebox.showinfo(
                "Manual export completed",
                f"Generated {exportados} G-Codes from manual cuts.\nFolder: {base_dir}"
            )
            return

        placa_y = self.limite_y_mm
        placa_z = self.limite_z_mm
        if placa_y <= 0 or placa_z <= 0:
            messagebox.showerror("Invalid usable area", "Set a usable Y and Z area greater than 0 to split by plates.")
            return
        margen_entrada_salida_y = 10.0
        ancho_util_y = placa_y - (2.0 * margen_entrada_salida_y)
        if ancho_util_y <= 1e-9:
            messagebox.showerror(
                "Insufficient Y usable area",
                "The plate Y length must be greater than 20 mm to keep 10 mm entry/exit per plate."
            )
            return

        try:
            v_corte_mms = float(self.vel_corte.get())
            if v_corte_mms <= 0:
                raise ValueError()
            v_mov_mmin = int(v_corte_mms * 60)
        except ValueError:
            messagebox.showerror("Error", "Cut speed must be a number greater than 0.")
            return

        ruta_base = filedialog.asksaveasfilename(
            title="Save plate G-Code batch",
            defaultextension=".gcode",
            filetypes=[("G-Code", "*.gcode")]
        )
        if not ruta_base:
            return

        # Use only profile cut path and move it to current machine coordinates.
        corte_base = self.obtener_trayectoria_corte()
        if not corte_base:
            messagebox.showwarning("No paths", "No cut path available to split.")
            return

        corte_maquina = []
        z_vals = []
        for y1, z1, y2, z2 in corte_base:
            yy1, zz1 = y1 + self.offset_y, z1 + self.offset_z
            yy2, zz2 = y2 + self.offset_y, z2 + self.offset_z
            corte_maquina.append((yy1, zz1, yy2, zz2))
            z_vals.extend([zz1, zz2])

        if not z_vals:
            messagebox.showwarning("No height", "Could not calculate height for plate splitting.")
            return

        ys = []
        for y1, _z1, y2, _z2 in corte_maquina:
            ys.extend([y1, y2])
        y_min = min(ys)
        y_max = max(ys)
        z_min = min(z_vals)
        z_max = max(z_vals)

        ancho_total = max(0.0, y_max - y_min)
        alto_total = max(0.0, z_max - z_min)
        total_cols = max(1, int(math.ceil(max(1e-9, ancho_total) / ancho_util_y)))
        total_rows = max(1, int(math.ceil(max(1e-9, alto_total) / placa_z)))
        total_capas = total_rows * total_cols
        base_dir = os.path.dirname(ruta_base)
        base_name = os.path.splitext(os.path.basename(ruta_base))[0]

        exportados = 0
        omitidos = 0
        idx_global = 0
        for fila in range(total_rows):
            capa_z_min = z_min + (fila * placa_z)
            capa_z_max = min(z_min + ((fila + 1) * placa_z), z_max)
            for col in range(total_cols):
                capa_y_min = y_min + (col * ancho_util_y)
                capa_y_max = min(y_min + ((col + 1) * ancho_util_y), y_max)
                idx_global += 1

                segmentos_capa = []
                for y1, z1, y2, z2 in corte_maquina:
                    rec = self._clip_segmento_a_rect(y1, z1, y2, z2, capa_y_min, capa_y_max, capa_z_min, capa_z_max)
                    if rec is None:
                        continue

                    cy1, cz1, cy2, cz2 = rec
                    if math.hypot(cy2 - cy1, cz2 - cz1) <= 1e-6:
                        continue

                    # Normalizamos Y y Z de esta placa para cortar localmente dentro de [0..placa_y]x[0..placa_z]
                    segmentos_capa.append((
                        (cy1 - capa_y_min) + margen_entrada_salida_y,
                        cz1 - capa_z_min,
                        (cy2 - capa_y_min) + margen_entrada_salida_y,
                        cz2 - capa_z_min,
                    ))

                if not segmentos_capa:
                    omitidos += 1
                    continue

                tray_capa = self._obtener_trayectoria_completa_desde(segmentos_capa, agregar_uniones=True)
                if not tray_capa:
                    omitidos += 1
                    continue

                header = [
                    f"YxZ plate batch - plate {idx_global}/{total_capas}",
                    f"Target usable area (plate): Y={placa_y:.3f} mm | Z={placa_z:.3f} mm",
                    f"Y entry/exit margin per plate: {margen_entrada_salida_y:.1f} mm per side",
                    f"Original Y range: {capa_y_min:.3f} .. {capa_y_max:.3f} mm",
                    f"Original Z range: {capa_z_min:.3f} .. {capa_z_max:.3f} mm",
                    "Y and Z remapped to local plate coordinates"
                ]
                gcode = self._generar_gcode_desde_trayectoria(tray_capa, v_mov_mmin, encabezado_extra=header)

                nombre = f"{base_name}_plate_r{fila+1:02d}_c{col+1:02d}_of_{total_rows:02d}x{total_cols:02d}.gcode"
                ruta_out = os.path.join(base_dir, nombre)
                with open(ruta_out, "w") as f:
                    f.write("\n".join(gcode))
                exportados += 1

        if exportados == 0:
            messagebox.showwarning(
                "No files exported",
                "Could not generate any plate with valid geometry for the specified usable area."
            )
            return

        messagebox.showinfo(
            "Plate export completed",
            f"Generated {exportados} G-Codes by YxZ plates.\n"
            f"Skipped plates without geometry: {omitidos}.\n"
            f"Folder: {base_dir}"
        )

    def alinear_origen_corte(self):
        """Match operational origin and cut origin (0,0), without boundary validation."""
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
        if self.editando_capa_idx is None:
            self.invalidar_preview_capas()

        trayectoria = self.obtener_trayectoria_completa()
        if not trayectoria:
            return

        # Traslada el dibujo para que el inicio operativo actual quede en (0,0)
        y0, z0 = trayectoria[0][0], trayectoria[0][1]
        self.offset_y = -y0
        self.offset_z = -z0
        self.sincronizar_edicion_capa_si_corresponde()
        self.slider_sim.set(0)
        self.dibujar(0)
        self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def rotar_sobre_origen_corte(self, angulo_grados):
        """Rota manualmente la pieza alrededor del origen operativo actual del corte."""
        if not self.lineas:
            return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
        if self.editando_capa_idx is None:
            self.invalidar_preview_capas()

        trayectoria = self.obtener_trayectoria_completa()
        if not trayectoria:
            return

        # Origen operativo actual (inicio de trayectoria completa: entrada)
        piv_y, piv_z = trayectoria[0][0], trayectoria[0][1]

        ang_rad = math.radians(angulo_grados)
        cos_a = math.cos(ang_rad)
        sin_a = math.sin(ang_rad)

        nuevas_lineas = []
        for y1, z1, y2, z2 in self.lineas:
            ry1 = piv_y + ((y1 - piv_y) * cos_a) - ((z1 - piv_z) * sin_a)
            rz1 = piv_z + ((y1 - piv_y) * sin_a) + ((z1 - piv_z) * cos_a)
            ry2 = piv_y + ((y2 - piv_y) * cos_a) - ((z2 - piv_z) * sin_a)
            rz2 = piv_z + ((y2 - piv_y) * sin_a) + ((z2 - piv_z) * cos_a)
            nuevas_lineas.append((ry1, rz1, ry2, rz2))

        self.lineas = nuevas_lineas
        self.sincronizar_edicion_capa_si_corresponde()
        self.dibujar(self.slider_sim.get())
        self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def rotar_sobre_origen_desde_ui(self, signo):
        """Apply fine rotation using exact user-entered value."""
        texto = self.grados_origen.get().strip().replace(",", ".")
        try:
            grados = float(texto)
        except ValueError:
            messagebox.showerror("Invalid degrees", "Enter a valid degree value (e.g. 0.5 or 1.25).")
            return

        if grados == 0:
            return

        self.rotar_sobre_origen_corte(signo * grados)

    def trasladar_fino_desde_ui(self, eje, signo):
        """Traslada el perfil en Y o Z usando un paso fino configurable."""
        if not self.lineas:
            return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()

        texto = self.paso_traslado.get().strip().replace(",", ".")
        try:
            paso = float(texto)
        except ValueError:
            messagebox.showerror("Invalid step", "Enter a valid step in mm (e.g. 0.1 or 0.25).")
            return

        if paso <= 0:
            messagebox.showerror("Invalid step", "Step must be greater than 0 mm.")
            return

        delta = signo * paso
        if eje == "y":
            self.offset_y += delta
        elif eje == "z":
            self.offset_z += delta
        else:
            return

        self.sincronizar_edicion_capa_si_corresponde()
        self.dibujar(self.slider_sim.get())
        duraciones = self.calcular_duraciones_trayectoria()
        if duraciones:
            idx = min(self.slider_sim.get(), len(duraciones))
            self.refrescar_info_tiempo(sum(duraciones[:idx]))
        else:
            self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def cargar_dxf(self):
        ruta_dxf = filedialog.askopenfilename(title="Select DXF", filetypes=[("DXF files", "*.dxf")])
        if not ruta_dxf: return

        self.backup_dxf_completo = None
        self.btn_restaurar_dxf.config(state=tk.DISABLED)
        self.invalidar_preview_capas()
        self.btn_exportar.config(state=tk.DISABLED)
        self.btn_exportar_dxf.config(state=tk.DISABLED)
        self.btn_exportar_capas.config(state=tk.DISABLED)
        
        try:
            doc = ezdxf.readfile(ruta_dxf)
            msp = doc.modelspace()
            factor_mm_sugerido = self._factor_unidades_a_mm(doc)
            try:
                ins = int(getattr(doc, "units", 0) or 0)
            except Exception:
                ins = 0

            try:
                escala_usuario = float(self.escala_importacion_dxf.get().replace(",", "."))
                if escala_usuario <= 0:
                    raise ValueError()
            except ValueError:
                messagebox.showerror("Invalid scale", "DXF import scale must be a number greater than 0.")
                return

            factor_insunits_aplicado = factor_mm_sugerido if self.usar_insunits_auto.get() else 1.0
            factor_mm = factor_insunits_aplicado * escala_usuario

            if ins == 0:
                base_info = "INSUNITS=0 (unitless)"
            else:
                base_info = f"INSUNITS={ins} (suggested x{factor_mm_sugerido:.6g})"
            modo_ins = "ON" if self.usar_insunits_auto.get() else "OFF"
            self.info_unidades_dxf = (
                f"{base_info} | auto={modo_ins} | scale={escala_usuario:.6g} | applied x{factor_mm:.6g}"
            )
            self.lineas.clear()
            
            min_y, min_z = float('inf'), float('inf')
            max_y, max_z = float('-inf'), float('-inf')
            
            for e in msp:
                if e.dxftype() == 'LINE':
                    y1, z1 = e.dxf.start.x * factor_mm, e.dxf.start.y * factor_mm
                    y2, z2 = e.dxf.end.x * factor_mm, e.dxf.end.y * factor_mm
                    self.lineas.append((y1, z1, y2, z2))
                    
                    min_y, max_y = min(min_y, y1, y2), max(max_y, y1, y2)
                    min_z, max_z = min(min_z, z1, z2), max(max_z, z1, z2)
                    
                # Support for lightweight polylines (LWPOLYLINE)
                elif e.dxftype() == 'LWPOLYLINE':
                    puntos = list(e.get_points('xy'))
                    for i in range(len(puntos)-1):
                        y1, z1 = puntos[i][0] * factor_mm, puntos[i][1] * factor_mm
                        y2, z2 = puntos[i+1][0] * factor_mm, puntos[i+1][1] * factor_mm
                        self.lineas.append((y1, z1, y2, z2))
                        
                        min_y, max_y = min(min_y, y1, y2), max(max_y, y1, y2)
                        min_z, max_z = min(min_z, z1, z2), max(max_z, z1, z2)
                        
                # Support for old/heavy polylines (POLYLINE)
                elif e.dxftype() == 'POLYLINE':
                    puntos = list(e.points())
                    for i in range(len(puntos)-1):
                        y1, z1 = puntos[i][0] * factor_mm, puntos[i][1] * factor_mm
                        y2, z2 = puntos[i+1][0] * factor_mm, puntos[i+1][1] * factor_mm
                        self.lineas.append((y1, z1, y2, z2))
                        
                        min_y, max_y = min(min_y, y1, y2), max(max_y, y1, y2)
                        min_z, max_z = min(min_z, z1, z2), max(max_z, z1, z2)

                # Support for splines, arcs, circles, ellipses
                elif e.dxftype() in ('SPLINE', 'ARC', 'CIRCLE', 'ELLIPSE'):
                    if path:
                        try:
                            # Convert entity to a path and flatten into small line segments
                            p = path.make_path(e)
                            puntos = list(p.flattening(distance=0.1)) # 0.1 mm precision
                            for i in range(len(puntos)-1):
                                y1, z1 = puntos[i][0] * factor_mm, puntos[i][1] * factor_mm
                                y2, z2 = puntos[i+1][0] * factor_mm, puntos[i+1][1] * factor_mm
                                self.lineas.append((y1, z1, y2, z2))
                                
                                min_y, max_y = min(min_y, y1, y2), max(max_y, y1, y2)
                                min_z, max_z = min(min_z, z1, z2), max(max_z, z1, z2)
                        except Exception as spline_err:
                            print("Error flattening entity:", spline_err)

            if not self.lineas:
                self.btn_play.config(state=tk.DISABLED)
                self.btn_stop.config(state=tk.DISABLED)
                self.btn_preview_capas.config(state=tk.DISABLED)
                messagebox.showwarning("Empty or unsupported format", "No compatible lines, polylines, splines, or arcs were found in the DXF.")
                return

            # Cada DXF nuevo arranca en sentido normal.
            self.corte_invertido = False
            if hasattr(self, "btn_invertir_corte"):
                self.btn_invertir_corte.config(text="Reverse Cut Direction")

            ancho = max_y - min_y
            alto = max_z - min_z
            self.offset_y = (self.limite_y_mm / 2) - (ancho / 2) - min_y
            self.offset_z = (self.limite_z_mm / 2) - (alto / 2) - min_z
            
            total_segmentos = len(self.obtener_trayectoria_completa())
            self.lineas_dxf_base = list(self.lineas)
            self._actualizar_label_dimensiones_dxf()
            self.slider_sim.config(to=total_segmentos, state=tk.NORMAL)
            self.slider_sim.set(total_segmentos)
            self.btn_play.config(state=tk.NORMAL if total_segmentos > 0 else tk.DISABLED)
            self.btn_exportar_dxf.config(state=tk.NORMAL if self.lineas else tk.DISABLED)
            self.btn_preview_capas.config(state=tk.NORMAL if total_segmentos > 0 else tk.DISABLED)
            self.btn_stop.config(state=tk.DISABLED)
            self.dibujar(total_segmentos)
            self.refrescar_info_tiempo(0.0)
            
        except Exception as ex:
            messagebox.showerror("Error", f"Could not read DXF:\n{ex}")

    def dibujar_grilla(self):
        t = self._get_work_view_transform()
        s = t["s"]
        ox, oy = t["ox"], t["oy"]
        dim_w = self.limite_y_mm * s
        dim_h = self.limite_z_mm * s

        for y in range(0, int(self.limite_y_mm) + 1, 10):
            px = ox + (y * s)
            color = "#b0b0b0" if y % 50 == 0 else "#e0e0e0"
            width = 2 if y % 50 == 0 else 1
            self.canvas.create_line(px, oy, px, oy + dim_h, fill=color, width=width)

        for z in range(0, int(self.limite_z_mm) + 1, 10):
            pz = oy + ((self.limite_z_mm - z) * s)
            color = "#b0b0b0" if z % 50 == 0 else "#e0e0e0"
            width = 2 if z % 50 == 0 else 1
            self.canvas.create_line(ox, pz, ox + dim_w, pz, fill=color, width=width)

        self.canvas.create_rectangle(ox, oy, ox + dim_w, oy + dim_h, outline="#888")
            
        # Origen (Y=0, Z=0)
        oy, oz = self.mm_a_pixel(0, 0)
        self.canvas.create_oval(oy-6, oz-6, oy+6, oz+6, fill="red")
        self.canvas.create_text(oy+20, oz-15, text="(0,0)", fill="red", font=("Arial", 10, "bold"))

    def actualizar_simulacion(self, val):
        if self.reproduciendo:
            return
        sim = float(val)
        self.dibujar(sim_val=sim)
        duraciones = self.calcular_duraciones_trayectoria()
        if duraciones:
            base = int(math.floor(sim))
            frac = sim - base
            t = sum(duraciones[:base])
            if base < len(duraciones):
                t += frac * duraciones[base]
            self.refrescar_info_tiempo(t)
        else:
            self.refrescar_info_tiempo(0.0)

    def rotar(self, angulo_grados):
        if not self.lineas: return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
        if self.editando_capa_idx is None:
            self.invalidar_preview_capas()
        
        # Encontrar el centro de la figura
        min_y = min(min(l[0], l[2]) for l in self.lineas)
        max_y = max(max(l[0], l[2]) for l in self.lineas)
        min_z = min(min(l[1], l[3]) for l in self.lineas)
        max_z = max(max(l[1], l[3]) for l in self.lineas)
        
        cy, cz = (min_y + max_y)/2, (min_z + max_z)/2
        ang_rad = math.radians(angulo_grados)
        cos_a = math.cos(ang_rad)
        sin_a = math.sin(ang_rad)
        
        nuevas_lineas = []
        for y1, z1, y2, z2 in self.lineas:
            ny1 = cy + (y1 - cy) * cos_a - (z1 - cz) * sin_a
            nz1 = cz + (y1 - cy) * sin_a + (z1 - cz) * cos_a
            ny2 = cy + (y2 - cy) * cos_a - (z2 - cz) * sin_a
            nz2 = cz + (y2 - cy) * sin_a + (z2 - cz) * cos_a
            nuevas_lineas.append((ny1, nz1, ny2, nz2))
            
        self.lineas = nuevas_lineas
        self.sincronizar_edicion_capa_si_corresponde()
        self.dibujar()
        self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def reflejar_vertical(self):
        """Refleja el perfil en Y respecto al eje vertical que pasa por el centro de la figura."""
        if not self.lineas:
            return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
        if self.editando_capa_idx is None:
            self.invalidar_preview_capas()

        min_y = min(min(l[0], l[2]) for l in self.lineas)
        max_y = max(max(l[0], l[2]) for l in self.lineas)
        cy = (min_y + max_y) / 2.0

        nuevas_lineas = []
        for y1, z1, y2, z2 in self.lineas:
            ny1 = (2.0 * cy) - y1
            ny2 = (2.0 * cy) - y2
            nuevas_lineas.append((ny1, z1, ny2, z2))

        self.lineas = nuevas_lineas
        self.sincronizar_edicion_capa_si_corresponde()
        self.dibujar(self.slider_sim.get())
        self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def reflejar_horizontal(self):
        """Refleja el perfil en Z respecto al eje horizontal que pasa por el centro de la figura."""
        if not self.lineas:
            return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
        if self.editando_capa_idx is None:
            self.invalidar_preview_capas()

        min_z = min(min(l[1], l[3]) for l in self.lineas)
        max_z = max(max(l[1], l[3]) for l in self.lineas)
        cz = (min_z + max_z) / 2.0

        nuevas_lineas = []
        for y1, z1, y2, z2 in self.lineas:
            nz1 = (2.0 * cz) - z1
            nz2 = (2.0 * cz) - z2
            nuevas_lineas.append((y1, nz1, y2, nz2))

        self.lineas = nuevas_lineas
        self.sincronizar_edicion_capa_si_corresponde()
        self.dibujar(self.slider_sim.get())
        self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def invertir_corte(self):
        if not self.lineas: return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
        if self.editando_capa_idx is None:
            self.invalidar_preview_capas()

        # Invertimos el sentido de la trayectoria (mismo corte, camino inverso).
        self.corte_invertido = not self.corte_invertido
        if hasattr(self, "btn_invertir_corte"):
            suf = " (REVERSED)" if self.corte_invertido else ""
            self.btn_invertir_corte.config(text=f"Reverse Cut Direction{suf}")

        self.slider_sim.set(0)
        self.dibujar(0)
        self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def auto_ajustar(self):
        if not self.lineas: return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
        if self.editando_capa_idx is None:
            self.invalidar_preview_capas()
        mejor_angulo = 0
        min_altura = float('inf')
        
        # Prueba rotaciones para encontrar la de menor altura en Z
        for ang in range(0, 180):
            ang_rad = math.radians(ang)
            cos_a = math.cos(ang_rad)
            sin_a = math.sin(ang_rad)
            
            max_z_rot = float('-inf')
            min_z_rot = float('inf')
            
            for y1, z1, y2, z2 in self.lineas:
                # Solo nos importa Z para chequear la altura
                nz1 = (y1) * sin_a + (z1) * cos_a
                nz2 = (y2) * sin_a + (z2) * cos_a
                max_z_rot = max(max_z_rot, nz1, nz2)
                min_z_rot = min(min_z_rot, nz1, nz2)
                
            altura = max_z_rot - min_z_rot
            if altura < min_altura:
                min_altura = altura
                mejor_angulo = ang
                
        self.rotar(mejor_angulo)
        
        # Recrar visualmente
        min_y = min(min(l[0], l[2]) for l in self.lineas)
        max_y = max(max(l[0], l[2]) for l in self.lineas)
        min_z = min(min(l[1], l[3]) for l in self.lineas)
        max_z = max(max(l[1], l[3]) for l in self.lineas)
        ancho = max_y - min_y
        alto = max_z - min_z
        self.offset_y = (self.limite_y_mm / 2) - (ancho / 2) - min_y
        self.offset_z = (self.limite_z_mm / 2) - (alto / 2) - min_z
        self.sincronizar_edicion_capa_si_corresponde()
        self.dibujar()
        self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def dibujar(self, sim_val=None):
        self.canvas.delete("all")
        self.dibujar_grilla()
        if not self.lineas: return

        lineas_render, usa_offset = self._trayectoria_activa()
        if not lineas_render:
            return

        fuera_de_limite = False
        
        limite_sim = float(len(lineas_render)) if sim_val is None else float(sim_val)
        limite_sim = max(0.0, min(limite_sim, float(len(lineas_render))))
        seg_completos = int(math.floor(limite_sim))
        frac = limite_sim - seg_completos

        # Punto verde = inicio real del corte del perfil (no la entrada)
        primer_corte = next((seg for seg in lineas_render if seg[4] == "corte"), None)
        if primer_corte:
            if usa_offset:
                pyc, pzc = self.mm_a_pixel(primer_corte[0] + self.offset_y, primer_corte[1] + self.offset_z)
            else:
                pyc, pzc = self.mm_a_pixel(primer_corte[0], primer_corte[1])
            r = 4
            self.canvas.create_oval(pyc-r, pzc-r, pyc+r, pzc+r, fill="#4CAF50", outline="black")

        for i, (y1, z1, y2, z2, tipo) in enumerate(lineas_render):
            if usa_offset:
                y1_mod, z1_mod = y1 + self.offset_y, z1 + self.offset_z
                y2_mod, z2_mod = y2 + self.offset_y, z2 + self.offset_z
            else:
                y1_mod, z1_mod = y1, z1
                y2_mod, z2_mod = y2, z2
            tol = self.tolerancia_limite_mm
            
            if (y1_mod < -tol or y1_mod > self.limite_y_mm + tol or z1_mod < -tol or z1_mod > self.limite_z_mm + tol or
                y2_mod < -tol or y2_mod > self.limite_y_mm + tol or z2_mod < -tol or z2_mod > self.limite_z_mm + tol):
                fuera_de_limite = True
                color = "green" if tipo in ("entrada", "salida") else "red"
            else:
                if tipo in ("entrada", "salida", "retorno_h", "retorno_v"):
                    color = "green"
                elif tipo == "union":
                    color = "#00BCD4"
                else:
                    color = "blue"
                
            py1, pz1 = self.mm_a_pixel(y1_mod, z1_mod)
            py2, pz2 = self.mm_a_pixel(y2_mod, z2_mod)

            if i < seg_completos:
                self.canvas.create_line(py1, pz1, py2, pz2, fill=color, width=2)
                # Cut head at the last rendered simulation point
                if i == seg_completos - 1 and frac == 0:
                    self.canvas.create_oval(py2-5, pz2-5, py2+5, pz2+5, fill="orange", outline="black")
            elif i == seg_completos and frac > 0:
                px = py1 + (py2 - py1) * frac
                pz = pz1 + (pz2 - pz1) * frac
                self.canvas.create_line(py1, pz1, px, pz, fill=color, width=2)
                self.canvas.create_oval(px-5, pz-5, px+5, pz+5, fill="orange", outline="black")
            else:
                # Dibuja la ruta restante tenue y punteada
                self.canvas.create_line(py1, pz1, py2, pz2, fill=color, width=1, dash=(2,4))

        # Si el slider es 0, muestra la cabeza en el origen de la trayectoria completa
        if limite_sim <= 0:
            if usa_offset:
                oy_start, oz_start = self.mm_a_pixel(lineas_render[0][0] + self.offset_y, lineas_render[0][1] + self.offset_z)
            else:
                oy_start, oz_start = self.mm_a_pixel(lineas_render[0][0], lineas_render[0][1])
            self.canvas.create_oval(oy_start-5, oz_start-5, oy_start+5, oz_start+5, fill="orange", outline="black")

        if fuera_de_limite:
            self.btn_exportar.config(state=tk.DISABLED, text="Out of bounds!")
            if self.dividir_en_placas.get() or self.usar_cortes_manuales.get():
                self.btn_exportar_capas.config(state=tk.NORMAL, text="3. Generate G-Codes by Plates")
                self.btn_preview_capas.config(state=tk.NORMAL if self.lineas else tk.DISABLED)
                self.btn_guardar_batch_carpeta.config(state=tk.NORMAL if self.capas_preview else tk.DISABLED)
            else:
                self.btn_exportar_capas.config(state=tk.DISABLED, text="Enable section mode (plates/manual)")
                self.btn_preview_capas.config(state=tk.DISABLED)
                self.btn_guardar_batch_carpeta.config(state=tk.DISABLED)
            self.btn_guardar_capa_actual.config(state=tk.DISABLED)
        else:
            self.btn_exportar.config(state=tk.NORMAL, text="2. Generate G-Code")
            if self.dividir_en_placas.get() or self.usar_cortes_manuales.get():
                self.btn_exportar_capas.config(state=tk.NORMAL, text="3. Generate G-Codes by Plates")
                self.btn_preview_capas.config(state=tk.NORMAL if self.lineas else tk.DISABLED)
                self.btn_guardar_batch_carpeta.config(state=tk.NORMAL if self.capas_preview else tk.DISABLED)
            else:
                self.btn_exportar_capas.config(state=tk.DISABLED, text="3. Generate G-Codes by Plates")
                self.btn_preview_capas.config(state=tk.DISABLED)
                self.btn_guardar_batch_carpeta.config(state=tk.DISABLED)
            self.btn_guardar_capa_actual.config(state=tk.NORMAL if self.editando_capa_idx is not None else tk.DISABLED)

        self.dibujar_canvas_total()

    # --- G-CODE GENERATION ---
    def exportar_gcode(self):
        ruta_gcode = filedialog.asksaveasfilename(title="Save G-Code", defaultextension=".gcode", filetypes=[("G-Code", "*.gcode")])
        if not ruta_gcode: return

        try:
            # Convertimos mm/s a mm/min para que Marlin lo entienda
            # Todos los movimientos usan la misma velocidad para evitar cambios bruscos
            v_corte_mms = float(self.vel_corte.get())
            v_mov_mmin = int(v_corte_mms * 60)
        except ValueError:
            messagebox.showerror("Error", "Speeds must be valid numbers.")
            return

        gcode = []
        gcode.append(";FLAVOR:Marlin")
        gcode.append(";TARGET_MACHINE.NAME:Ender-3 Hot Wire CNC")
        gcode.append("G21 ; Units in millimeters")
        gcode.append("G90 ; Absolute positioning")
        gcode.append("M140 S0 ; Turn off bed temperature")
        gcode.append("M104 S0 ; Turn off hotend temperature")
        gcode.append("M107 ; Turn off layer fan")
        gcode.append("G92 Y0 Z0 ; Set current position as origin (0,0)")
        gcode.append(";--- CUT START ---")

        # Start assuming machine is at origin after G92 Y0 Z0
        y_actual, z_actual = 0.0, 0.0

        for (y1, z1, y2, z2, tipo) in self.obtener_trayectoria_completa():
            y1_mod = round(y1 + self.offset_y, 3)
            z1_mod = round(z1 + self.offset_z, 3)
            y2_mod = round(y2 + self.offset_y, 3)
            z2_mod = round(z2 + self.offset_z, 3)

            # Movimiento suave de posicionamiento (sin G0) para evitar desplazamientos bruscos
            if (abs(y_actual - y1_mod) > 1e-6) or (abs(z_actual - z1_mod) > 1e-6):
                gcode.append(f"G1 F{v_mov_mmin} Y{y1_mod} Z{z1_mod}")
            
            # Cut movement: force F (feedrate) on each line to keep constant speed
            if tipo == "entrada":
                gcode.append("; 10mm entry")
            elif tipo == "salida":
                gcode.append("; 10mm exit")
            elif tipo == "retorno_h":
                gcode.append("; Horizontal return to origin Y")
            elif tipo == "retorno_v":
                gcode.append("; Final Z adjustment to close exactly at origin")
            elif tipo == "union":
                gcode.append("; Straight union between segments")
            gcode.append(f"G1 F{v_mov_mmin} Y{y2_mod} Z{z2_mod}")
            
            y_actual, z_actual = y2_mod, z2_mod

        gcode.append(";--- CUT END ---")
        gcode.append(f"G1 F{v_mov_mmin} Y0 Z0 ; Smooth return to initial origin")
        gcode.append("M84 ; Turn off motors")

        with open(ruta_gcode, 'w') as f:
            f.write("\n".join(gcode))
            
        messagebox.showinfo("Success", "G-Code generated successfully!")

if __name__ == "__main__":
    root = tk.Tk()
    app = AppSlicerCNC(root)
    root.mainloop()