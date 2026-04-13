import tkinter as tk
from tkinter import filedialog, messagebox
import ezdxf
try:
    from ezdxf import path
except ImportError:
    path = None
import math
import time
import os

class AppSlicerCNC:
    def __init__(self, root):
        self.root = root
        self.root.title("Slicer CNC Hilo Caliente - Ender 3")
        
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
        self.espesor_placa = tk.StringVar(value="20")
        self.nombre_lote_capas = tk.StringVar(value="corte")
        self.area_y_mm_var = tk.StringVar(value="220")
        self.area_z_mm_var = tk.StringVar(value="100")
        
        self.drag_data = {"x": 0, "y": 0}

        # Simulación en tiempo real
        self.reproduciendo = False
        self.play_after_id = None
        self.tiempo_total_seg = 0.0
        self.tiempo_inicio_play = 0.0
        self.tiempo_acumulado_seg = 0.0
        self.actualizando_slider_interno = False
        self.play_duraciones = []
        self.play_last_slider_idx = -1

        # Preview por capas (placas)
        self.capas_preview = []
        self.capa_preview_idx = -1  # -1 = vista total
        self.editando_capa_idx = None
        self.backup_dxf_completo = None

        # --- INTERFAZ GRÁFICA ---
        panel_izq = tk.Frame(root, padx=10, pady=10)
        panel_izq.pack(side=tk.LEFT, fill=tk.Y)
        
        tk.Button(panel_izq, text="1. Cargar DXF", command=self.cargar_dxf, bg="#2196F3", fg="white", font=("Arial", 11, "bold")).pack(fill=tk.X, pady=5)
        
        # Herramientas de ajuste
        tk.Label(panel_izq, text="Ajustar Forma:", font=("Arial", 9, "bold")).pack(anchor=tk.W, pady=(10,0))
        frame_herramientas = tk.Frame(panel_izq)
        frame_herramientas.pack(fill=tk.X, pady=2)
        tk.Button(frame_herramientas, text="Rotar 90°", command=lambda: self.rotar(90)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        tk.Button(frame_herramientas, text="Auto Altura", command=self.auto_ajustar).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        frame_rot_origen = tk.Frame(panel_izq)
        frame_rot_origen.pack(fill=tk.X, pady=(2, 2))
        tk.Entry(frame_rot_origen, textvariable=self.grados_origen, width=8).pack(side=tk.LEFT, padx=(0, 4))
        tk.Label(frame_rot_origen, text="°").pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(frame_rot_origen, text="↺", command=lambda: self.rotar_sobre_origen_desde_ui(-1)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        tk.Button(frame_rot_origen, text="↻", command=lambda: self.rotar_sobre_origen_desde_ui(1)).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        frame_traslado_cfg = tk.Frame(panel_izq)
        frame_traslado_cfg.pack(fill=tk.X, pady=(2, 2))
        tk.Label(frame_traslado_cfg, text="Paso Y/Z:").pack(side=tk.LEFT)
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

        tk.Button(panel_izq, text="Invertir Dirección de Corte", command=self.invertir_corte).pack(fill=tk.X, pady=(2, 5))
        tk.Button(panel_izq, text="Alinear Origen al Corte", command=self.alinear_origen_corte).pack(fill=tk.X, pady=(0, 8))

        tk.Label(panel_izq, text="Velocidad de Trabajo (mm/s):").pack(anchor=tk.W, pady=(10,0))
        tk.Entry(panel_izq, textvariable=self.vel_corte).pack(fill=tk.X)
        
        tk.Label(panel_izq, text="\nTips:", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        tk.Label(panel_izq, text="- Arrastra el dibujo para moverlo.\n- Punto VERDE = Inicio de Corte\n- Rojo = Fuera de límite", justify=tk.LEFT, font=("Arial", 8)).pack(anchor=tk.W)

        tk.Label(panel_izq, text="\nÁrea útil (Y x Z) mm:", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        frame_area = tk.Frame(panel_izq)
        frame_area.pack(fill=tk.X, pady=(2, 6))
        tk.Label(frame_area, text="Y").pack(side=tk.LEFT)
        tk.Entry(frame_area, textvariable=self.area_y_mm_var, width=6).pack(side=tk.LEFT, padx=(2, 6))
        tk.Label(frame_area, text="Z").pack(side=tk.LEFT)
        tk.Entry(frame_area, textvariable=self.area_z_mm_var, width=6).pack(side=tk.LEFT, padx=(2, 6))
        tk.Button(frame_area, text="Aplicar", command=self.aplicar_area_util).pack(side=tk.LEFT)

        # Slider simulacion interactiva
        tk.Label(panel_izq, text="\nSimulación de Corte:", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        self.slider_sim = tk.Scale(panel_izq, from_=0, to=0, orient=tk.HORIZONTAL, command=self.actualizar_simulacion, showvalue=False)
        self.slider_sim.pack(fill=tk.X, pady=(0, 10))

        frame_play = tk.Frame(panel_izq)
        frame_play.pack(fill=tk.X, pady=(0, 8))
        self.btn_play = tk.Button(frame_play, text="▶ Play", command=self.iniciar_simulacion_tiempo_real, state=tk.DISABLED)
        self.btn_play.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.btn_stop = tk.Button(frame_play, text="■ Stop", command=self.detener_simulacion_tiempo_real, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        self.lbl_tiempo = tk.Label(panel_izq, text="Tiempo estimado: --:-- | Transcurrido: 00:00", font=("Arial", 8))
        self.lbl_tiempo.pack(anchor=tk.W, pady=(0, 8))
        self.lbl_altura = tk.Label(panel_izq, text="Altura máx corte: -- mm (Zmin -- / Zmax --)", font=("Arial", 8, "bold"))
        self.lbl_altura.pack(anchor=tk.W, pady=(0, 8))

        tk.Label(panel_izq, text="Espesor placa XPS (mm):").pack(anchor=tk.W, pady=(2,0))
        tk.Entry(panel_izq, textvariable=self.espesor_placa).pack(fill=tk.X)
        tk.Label(panel_izq, text="Nombre base de archivos:").pack(anchor=tk.W, pady=(2,0))
        tk.Entry(panel_izq, textvariable=self.nombre_lote_capas).pack(fill=tk.X)

        frame_preview_capas = tk.Frame(panel_izq)
        frame_preview_capas.pack(fill=tk.X, pady=(4, 6))
        self.btn_preview_capas = tk.Button(frame_preview_capas, text="Previsualizar Capas", command=self.generar_preview_capas, state=tk.DISABLED)
        self.btn_preview_capas.pack(fill=tk.X)

        frame_nav_capas = tk.Frame(panel_izq)
        frame_nav_capas.pack(fill=tk.X, pady=(2, 2))
        self.btn_capa_prev = tk.Button(frame_nav_capas, text="◀ Capa", command=lambda: self.mover_preview_capa(-1), state=tk.DISABLED)
        self.btn_capa_prev.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        self.btn_capa_next = tk.Button(frame_nav_capas, text="Capa ▶", command=lambda: self.mover_preview_capa(1), state=tk.DISABLED)
        self.btn_capa_next.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))

        self.btn_vista_total = tk.Button(panel_izq, text="Volver Vista Total", command=self.activar_vista_total, state=tk.DISABLED)
        self.btn_vista_total.pack(fill=tk.X, pady=(0, 4))
        self.btn_editar_capa = tk.Button(panel_izq, text="Edición automática por foco", command=self.editar_capa_actual, state=tk.DISABLED)
        self.btn_editar_capa.pack(fill=tk.X, pady=(0, 2))
        self.btn_restaurar_dxf = tk.Button(panel_izq, text="Restaurar DXF Completo", command=self.restaurar_dxf_completo, state=tk.DISABLED)
        self.btn_restaurar_dxf.pack(fill=tk.X, pady=(0, 4))
        self.lbl_capa_preview = tk.Label(panel_izq, text="Preview capas: OFF", font=("Arial", 8))
        self.lbl_capa_preview.pack(anchor=tk.W, pady=(0, 6))

        self.btn_exportar = tk.Button(panel_izq, text="2. Generar G-Code", command=self.exportar_gcode, state=tk.DISABLED, bg="#4CAF50", fg="white", font=("Arial", 11, "bold"))
        self.btn_exportar.pack(fill=tk.X, pady=(8, 4))
        self.btn_exportar_capas = tk.Button(panel_izq, text="3. Generar G-Codes por Placas", command=self.exportar_gcode_por_capas, state=tk.DISABLED, bg="#2E7D32", fg="white", font=("Arial", 10, "bold"))
        self.btn_exportar_capas.pack(fill=tk.X, pady=(0, 4))
        self.btn_guardar_capa_actual = tk.Button(panel_izq, text="Guardar Capa Enfocada", command=self.guardar_capa_enfocada, state=tk.DISABLED, bg="#33691E", fg="white", font=("Arial", 10, "bold"))
        self.btn_guardar_capa_actual.pack(fill=tk.X, pady=(0, 4))
        self.btn_guardar_batch_carpeta = tk.Button(panel_izq, text="Guardar Batch en Carpeta", command=self.guardar_batch_en_carpeta, state=tk.DISABLED, bg="#1B5E20", fg="white", font=("Arial", 10, "bold"))
        self.btn_guardar_batch_carpeta.pack(fill=tk.X, pady=(0, 10))
        
        panel_der = tk.Frame(root, padx=10, pady=10)
        panel_der.pack(side=tk.RIGHT)
        
        tk.Label(panel_der, text="Vista Completa (pieza y capas)").pack()
        dim_canvas_w = int(self.limite_y_mm * self.escala_visual)
        dim_canvas_h = int(self.limite_z_mm * self.escala_visual)
        self.canvas_total = tk.Canvas(panel_der, width=dim_canvas_w, height=max(180, dim_canvas_h), bg="#f0f0f0", relief=tk.SUNKEN, bd=2)
        self.canvas_total.pack(pady=(0, 8))

        tk.Label(panel_der, text="Área de Trabajo (Vista Y-Z)").pack()
        
        self.canvas = tk.Canvas(panel_der, width=dim_canvas_w, height=dim_canvas_h, bg="#e0e0e0", relief=tk.SUNKEN, bd=2)
        self.canvas.pack()
        
        self.canvas.bind("<ButtonPress-1>", self.iniciar_arrastre)
        self.canvas.bind("<B1-Motion>", self.arrastrar)

    # --- LÓGICA DE INTERFAZ Y DIBUJO ---
    def iniciar_arrastre(self, event):
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y

    def arrastrar(self, event):
        if not self.lineas: return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
        if self.editando_capa_idx is None:
            self.invalidar_preview_capas()
        delta_x = (event.x - self.drag_data["x"]) / self.escala_visual
        delta_y = -(event.y - self.drag_data["y"]) / self.escala_visual 
        
        self.offset_y += delta_x
        self.offset_z += delta_y
        
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y
        self.sincronizar_edicion_capa_si_corresponde()
        self.dibujar(self.slider_sim.get())
        self.refrescar_info_tiempo(0.0)
        self.dibujar_canvas_total()

    def mm_a_pixel(self, y_mm, z_mm):
        py = y_mm * self.escala_visual
        pz = (self.limite_z_mm - z_mm) * self.escala_visual 
        return py, pz

    def aplicar_area_util(self):
        try:
            ly = float(self.area_y_mm_var.get().replace(",", "."))
            lz = float(self.area_z_mm_var.get().replace(",", "."))
            if ly <= 0 or lz <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Área inválida", "Ingresa dimensiones válidas mayores a 0 para Y y Z.")
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
        self.lbl_capa_preview.config(text="Preview capas: OFF")

    def sincronizar_edicion_capa_si_corresponde(self):
        """Si estamos editando una capa, bakea offsets en la geometría y actualiza el modelo de capa."""
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

        # Tomamos datos globales (sin deformación) para auto-fit con escala real 1:1 entre ejes.
        segmentos_base = []
        if self.capas_preview:
            for capa in self.capas_preview:
                for y1, z1, y2, z2 in capa.get("lineas_global_ref", capa.get("lineas_global", [])):
                    segmentos_base.append((y1, z1, y2, z2))
        else:
            for y1, z1, y2, z2 in self.lineas:
                segmentos_base.append((y1 + self.offset_y, z1 + self.offset_z, y2 + self.offset_y, z2 + self.offset_z))

        if not segmentos_base:
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

    def _trayectoria_activa(self):
        """Retorna (trayectoria, usa_offset). Si es preview de capa, ya está en coords máquina y no usa offset."""
        if 0 <= self.capa_preview_idx < len(self.capas_preview):
            return self.capas_preview[self.capa_preview_idx]["trayectoria"], False
        return self.obtener_trayectoria_completa(), True

    def _actualizar_label_capa_preview(self):
        if 0 <= self.capa_preview_idx < len(self.capas_preview):
            c = self.capas_preview[self.capa_preview_idx]
            self.lbl_capa_preview.config(
                text=(
                    f"Preview capa {self.capa_preview_idx+1}/{len(self.capas_preview)} | "
                    f"Z orig {c['z_min_orig']:.2f}..{c['z_max_orig']:.2f} mm"
                )
            )
        else:
            self.lbl_capa_preview.config(text="Preview capas: OFF")

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

        try:
            espesor = float(self.espesor_placa.get().replace(",", "."))
            if espesor <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Error", "El espesor de placa debe ser un número mayor a 0.")
            return

        corte_base = self.obtener_trayectoria_corte()
        if not corte_base:
            messagebox.showwarning("Sin trayectorias", "No hay trayectoria de corte disponible para generar preview por capas.")
            return

        corte_maquina = []
        z_vals = []
        for y1, z1, y2, z2 in corte_base:
            yy1, zz1 = y1 + self.offset_y, z1 + self.offset_z
            yy2, zz2 = y2 + self.offset_y, z2 + self.offset_z
            corte_maquina.append((yy1, zz1, yy2, zz2))
            z_vals.extend([zz1, zz2])

        if not z_vals:
            messagebox.showwarning("Sin altura", "No se pudo calcular altura para preview por capas.")
            return

        z_min = min(z_vals)
        z_max = max(z_vals)
        altura_total = max(0.0, z_max - z_min)
        if altura_total <= 1e-9:
            messagebox.showwarning("Altura nula", "La geometría no tiene altura en Z para dividir en capas.")
            return

        total_capas = int(math.ceil(altura_total / espesor))
        capas = []
        for i in range(total_capas):
            capa_z_min = z_min + (i * espesor)
            capa_z_max = min(z_min + ((i + 1) * espesor), z_max)

            segmentos_capa = []
            segmentos_globales_capa = []
            for y1, z1, y2, z2 in corte_maquina:
                rec = self._clip_segmento_a_banda_z(y1, z1, y2, z2, capa_z_min, capa_z_max)
                if rec is None:
                    continue
                cy1, cz1, cy2, cz2 = rec
                if math.hypot(cy2 - cy1, cz2 - cz1) <= 1e-6:
                    continue
                segmentos_globales_capa.append((cy1, cz1, cy2, cz2))
                segmentos_capa.append((cy1, cz1 - capa_z_min, cy2, cz2 - capa_z_min))

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
                "z_min_orig": capa_z_min,
                "z_max_orig": capa_z_max,
            })

        if not capas:
            messagebox.showwarning("Sin preview", "No se pudo generar ninguna capa visualizable con el espesor indicado.")
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
        """Convierte la capa en preview a geometría editable independiente."""
        self._cargar_capa_enfocada_para_edicion()

    def _cargar_capa_enfocada_para_edicion(self):
        """Carga automáticamente la capa enfocada para edición, sin requerir botón manual."""
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
        """Restaura la geometría completa original luego de editar capas por separado."""
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
            messagebox.showwarning("Sin capa enfocada", "Primero enfoca una capa con 'Editar Capa Actual'.")
            return

        self.sincronizar_edicion_capa_si_corresponde()
        try:
            v_corte_mms = float(self.vel_corte.get())
            if v_corte_mms <= 0:
                raise ValueError()
            v_mov_mmin = int(v_corte_mms * 60)
        except ValueError:
            messagebox.showerror("Error", "La velocidad de corte debe ser un número mayor a 0.")
            return

        base = self.nombre_lote_capas.get().strip() or "corte"
        nombre_sugerido = f"{base}_capa{self.editando_capa_idx+1:02d}.gcode"
        ruta = filedialog.asksaveasfilename(
            title="Guardar G-Code de capa enfocada",
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
            encabezado_extra=[f"Capa enfocada {self.editando_capa_idx+1}"]
        )
        with open(ruta, "w") as f:
            f.write("\n".join(gcode))
        messagebox.showinfo("Guardado", f"Capa guardada en:\n{ruta}")

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
            messagebox.showerror("Error", "La velocidad de corte debe ser un número mayor a 0.")
            return

        carpeta = filedialog.askdirectory(title="Seleccionar carpeta para guardar batch de capas")
        if not carpeta:
            return

        base = self.nombre_lote_capas.get().strip() or "corte"
        total = len(self.capas_preview)
        guardados = 0
        for i, capa in enumerate(self.capas_preview, start=1):
            tray = self._obtener_trayectoria_completa_desde(capa["lineas_edit"], agregar_uniones=True)
            gcode = self._generar_gcode_desde_trayectoria(
                tray,
                v_mov_mmin,
                encabezado_extra=[
                    f"Batch capas {i}/{total}",
                    f"Z orig {capa['z_min_orig']:.3f}..{capa['z_max_orig']:.3f}"
                ]
            )
            nombre = f"{base}_capa{i:02d}_de_{total:02d}.gcode"
            ruta = os.path.join(carpeta, nombre)
            with open(ruta, "w") as f:
                f.write("\n".join(gcode))
            guardados += 1

        messagebox.showinfo("Batch guardado", f"Se guardaron {guardados} archivos en:\n{carpeta}")

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
            text=f"Tiempo estimado: {self.formatear_tiempo(self.tiempo_total_seg)} | Transcurrido: {self.formatear_tiempo(transcurrido_seg)}"
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
            self.lbl_altura.config(text="Altura máx corte: -- mm (Zmin -- / Zmax --)")
            return

        altura, z_min, z_max = info
        self.lbl_altura.config(
            text=f"Altura máx corte: {altura:.2f} mm (Zmin {z_min:.2f} / Zmax {z_max:.2f})"
        )

    def iniciar_simulacion_tiempo_real(self):
        if not self.lineas or self.reproduciendo:
            return

        duraciones = self.calcular_duraciones_trayectoria()
        if not duraciones:
            messagebox.showwarning("Velocidad inválida", "Define una velocidad de corte mayor a 0 mm/s.")
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
        """Devuelve trayectoria continua arrancando desde el punto más a la izquierda de un conjunto de líneas."""
        if not lineas_base:
            return []

        def rotar_segmentos(segmentos, idx_inicio):
            return segmentos[idx_inicio:] + segmentos[:idx_inicio]

        # Candidatos: orden original y orden invertido global (manteniendo continuidad del loop)
        candidatos_base = [
            list(lineas_base),
            [(y2, z2, y1, z1) for (y1, z1, y2, z2) in reversed(lineas_base)]
        ]

        candidatos = []
        for segmentos in candidatos_base:
            min_y = min(min(y1, y2) for (y1, _, y2, _) in segmentos)

            idx_inicio = None
            for i, (y1, _z1, _y2, _z2) in enumerate(segmentos):
                if abs(y1 - min_y) < 1e-6:
                    idx_inicio = i
                    break

            if idx_inicio is None:
                continue

            trayectoria = rotar_segmentos(segmentos, idx_inicio)
            candidatos.append(trayectoria)

        if not candidatos:
            return list(self.lineas)

        # Desempate estable: menor Z inicial primero
        candidatos.sort(key=lambda t: (round(t[0][0], 6), round(t[0][1], 6)))
        return candidatos[0]

    def obtener_trayectoria_corte(self):
        """Devuelve una trayectoria continua, arrancando en el punto más a la izquierda del DXF."""
        return self._obtener_trayectoria_corte_desde(self.lineas)

    def _obtener_trayectoria_completa_desde(self, lineas_base, agregar_uniones=False):
        """Devuelve trayectoria completa para un conjunto de líneas.

        Criterio:
        - entrada horizontal de 10 mm hacia el inicio de corte
        - salida horizontal de 10 mm desde el final de corte
        - retorno al mismo punto de inicio (punto naranja), para que inicio y fin coincidan exactamente
        - si agregar_uniones=True, inserta tramos rectos entre segmentos desconectados.
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

        # Retorno externo al mismo punto inicial de operación (punto naranja)
        # 1) horizontal hasta Y de entrada
        # 2) vertical final solo si Z difiere
        retorno = []
        if abs(salida_y - entrada_y) > 1e-9:
            retorno.append((salida_y, fin_z, entrada_y, fin_z, "retorno_h"))
        if abs(fin_z - inicio_z) > 1e-9:
            retorno.append((entrada_y, fin_z, entrada_y, inicio_z, "retorno_v"))

        return [entrada] + corte_tipado + [salida] + retorno

    def obtener_trayectoria_completa(self):
        """Devuelve trayectoria con entrada/salida horizontal de 10 mm.

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

    def _generar_gcode_desde_trayectoria(self, trayectoria, v_mov_mmin, encabezado_extra=None):
        """Genera líneas de G-code a partir de una trayectoria ya posicionada en coordenadas máquina."""
        gcode = []
        gcode.append(";FLAVOR:Marlin")
        gcode.append(";TARGET_MACHINE.NAME:Ender-3 CNC Hilo Caliente")
        if encabezado_extra:
            for linea in encabezado_extra:
                gcode.append(f";{linea}")
        gcode.append("G21 ; Unidades en milimetros")
        gcode.append("G90 ; Posicionamiento absoluto")
        gcode.append("M140 S0 ; Apagar temperatura de la cama")
        gcode.append("M104 S0 ; Apagar temperatura del hotend")
        gcode.append("M107 ; Apagar ventilador de capa")
        gcode.append("G92 Y0 Z0 ; Establecer posicion actual como origen (0,0)")
        gcode.append(";--- INICIO DEL CORTE ---")

        y_actual, z_actual = 0.0, 0.0
        for (y1, z1, y2, z2, tipo) in trayectoria:
            y1_mod = round(y1, 3)
            z1_mod = round(z1, 3)
            y2_mod = round(y2, 3)
            z2_mod = round(z2, 3)

            if (abs(y_actual - y1_mod) > 1e-6) or (abs(z_actual - z1_mod) > 1e-6):
                gcode.append(f"G1 F{v_mov_mmin} Y{y1_mod} Z{z1_mod}")

            if tipo == "entrada":
                gcode.append("; Entrada 10mm")
            elif tipo == "salida":
                gcode.append("; Salida 10mm")
            elif tipo == "retorno_h":
                gcode.append("; Retorno horizontal a Y de origen")
            elif tipo == "retorno_v":
                gcode.append("; Ajuste final en Z para cerrar en origen exacto")
            elif tipo == "union":
                gcode.append("; Union recta entre segmentos")
            gcode.append(f"G1 F{v_mov_mmin} Y{y2_mod} Z{z2_mod}")

            y_actual, z_actual = y2_mod, z2_mod

        gcode.append(";--- FIN DEL CORTE ---")
        gcode.append(f"G1 F{v_mov_mmin} Y0 Z0 ; Volver suave a la posicion de origen inicial")
        gcode.append("M84 ; Apagar los motores")
        return gcode

    def exportar_gcode_por_capas(self):
        if not self.lineas:
            return

        try:
            espesor = float(self.espesor_placa.get().replace(",", "."))
            if espesor <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Error", "El espesor de placa debe ser un número mayor a 0.")
            return

        try:
            v_corte_mms = float(self.vel_corte.get())
            if v_corte_mms <= 0:
                raise ValueError()
            v_mov_mmin = int(v_corte_mms * 60)
        except ValueError:
            messagebox.showerror("Error", "La velocidad de corte debe ser un número mayor a 0.")
            return

        ruta_base = filedialog.asksaveasfilename(
            title="Guardar lote de G-Codes por placas",
            defaultextension=".gcode",
            filetypes=[("G-Code", "*.gcode")]
        )
        if not ruta_base:
            return

        # Tomamos solo la trayectoria de corte del perfil y la llevamos a coordenadas de máquina actuales.
        corte_base = self.obtener_trayectoria_corte()
        if not corte_base:
            messagebox.showwarning("Sin trayectorias", "No hay trayectoria de corte disponible para dividir.")
            return

        corte_maquina = []
        z_vals = []
        for y1, z1, y2, z2 in corte_base:
            yy1, zz1 = y1 + self.offset_y, z1 + self.offset_z
            yy2, zz2 = y2 + self.offset_y, z2 + self.offset_z
            corte_maquina.append((yy1, zz1, yy2, zz2))
            z_vals.extend([zz1, zz2])

        if not z_vals:
            messagebox.showwarning("Sin altura", "No se pudo calcular altura para división por placas.")
            return

        z_min = min(z_vals)
        z_max = max(z_vals)
        altura_total = max(0.0, z_max - z_min)
        if altura_total <= 1e-9:
            messagebox.showwarning("Altura nula", "La geometría no tiene altura en Z para dividir en capas.")
            return

        total_capas = int(math.ceil(altura_total / espesor))
        base_dir = os.path.dirname(ruta_base)
        base_name = os.path.splitext(os.path.basename(ruta_base))[0]

        exportados = 0
        omitidos = 0
        for i in range(total_capas):
            capa_z_min = z_min + (i * espesor)
            capa_z_max = min(z_min + ((i + 1) * espesor), z_max)

            segmentos_capa = []
            for y1, z1, y2, z2 in corte_maquina:
                rec = self._clip_segmento_a_banda_z(y1, z1, y2, z2, capa_z_min, capa_z_max)
                if rec is None:
                    continue

                cy1, cz1, cy2, cz2 = rec
                if math.hypot(cy2 - cy1, cz2 - cz1) <= 1e-6:
                    continue

                # Normalizamos Z de esta capa para cortar sobre una placa local (0..espesor)
                segmentos_capa.append((cy1, cz1 - capa_z_min, cy2, cz2 - capa_z_min))

            if not segmentos_capa:
                omitidos += 1
                continue

            tray_capa = self._obtener_trayectoria_completa_desde(segmentos_capa, agregar_uniones=True)
            if not tray_capa:
                omitidos += 1
                continue

            header = [
                f"Lote por placas - capa {i+1}/{total_capas}",
                f"Espesor placa objetivo: {espesor:.3f} mm",
                f"Rango Z original: {capa_z_min:.3f} .. {capa_z_max:.3f} mm",
                "Z de esta capa remapeado a 0..espesor para corte en placa delgada"
            ]
            gcode = self._generar_gcode_desde_trayectoria(tray_capa, v_mov_mmin, encabezado_extra=header)

            nombre = f"{base_name}_capa{i+1:02d}_de_{total_capas:02d}.gcode"
            ruta_out = os.path.join(base_dir, nombre)
            with open(ruta_out, "w") as f:
                f.write("\n".join(gcode))
            exportados += 1

        if exportados == 0:
            messagebox.showwarning(
                "Sin archivos exportados",
                "No se pudo generar ninguna capa con geometría válida para el espesor indicado."
            )
            return

        messagebox.showinfo(
            "Exportación por placas completada",
            f"Se generaron {exportados} G-Codes por capas.\n"
            f"Capas omitidas sin geometría: {omitidos}.\n"
            f"Carpeta: {base_dir}"
        )

    def alinear_origen_corte(self):
        """Hace coincidir origen operativo y origen del corte (0,0), sin validar límites."""
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
        """Aplica rotación fina usando el valor exacto ingresado por usuario."""
        texto = self.grados_origen.get().strip().replace(",", ".")
        try:
            grados = float(texto)
        except ValueError:
            messagebox.showerror("Grados inválidos", "Ingresa un número válido de grados (ej: 0.5 o 1.25).")
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
            messagebox.showerror("Paso inválido", "Ingresa un paso válido en mm (ej: 0.1 o 0.25).")
            return

        if paso <= 0:
            messagebox.showerror("Paso inválido", "El paso debe ser mayor a 0 mm.")
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
        ruta_dxf = filedialog.askopenfilename(title="Seleccionar DXF", filetypes=[("Archivos DXF", "*.dxf")])
        if not ruta_dxf: return

        self.backup_dxf_completo = None
        self.btn_restaurar_dxf.config(state=tk.DISABLED)
        self.invalidar_preview_capas()
        self.btn_exportar.config(state=tk.DISABLED)
        self.btn_exportar_capas.config(state=tk.DISABLED)
        
        try:
            doc = ezdxf.readfile(ruta_dxf)
            msp = doc.modelspace()
            self.lineas.clear()
            
            min_y, min_z = float('inf'), float('inf')
            max_y, max_z = float('-inf'), float('-inf')
            
            for e in msp:
                if e.dxftype() == 'LINE':
                    y1, z1 = e.dxf.start.x, e.dxf.start.y
                    y2, z2 = e.dxf.end.x, e.dxf.end.y
                    self.lineas.append((y1, z1, y2, z2))
                    
                    min_y, max_y = min(min_y, y1, y2), max(max_y, y1, y2)
                    min_z, max_z = min(min_z, z1, z2), max(max_z, z1, z2)
                    
                # Soporte para Polilíneas ligeras (LWPOLYLINE)
                elif e.dxftype() == 'LWPOLYLINE':
                    puntos = list(e.get_points('xy'))
                    for i in range(len(puntos)-1):
                        y1, z1 = puntos[i][0], puntos[i][1]
                        y2, z2 = puntos[i+1][0], puntos[i+1][1]
                        self.lineas.append((y1, z1, y2, z2))
                        
                        min_y, max_y = min(min_y, y1, y2), max(max_y, y1, y2)
                        min_z, max_z = min(min_z, z1, z2), max(max_z, z1, z2)
                        
                # Soporte para Polilíneas antiguas/pesadas (POLYLINE)
                elif e.dxftype() == 'POLYLINE':
                    puntos = list(e.points())
                    for i in range(len(puntos)-1):
                        y1, z1 = puntos[i][0], puntos[i][1]
                        y2, z2 = puntos[i+1][0], puntos[i+1][1]
                        self.lineas.append((y1, z1, y2, z2))
                        
                        min_y, max_y = min(min_y, y1, y2), max(max_y, y1, y2)
                        min_z, max_z = min(min_z, z1, z2), max(max_z, z1, z2)

                # Soporte para Splines, Arcos, Círculos, Elipses
                elif e.dxftype() in ('SPLINE', 'ARC', 'CIRCLE', 'ELLIPSE'):
                    if path:
                        try:
                            # Convertir la entidad a un path y luego aplanarla en pequeños segmentos de linea
                            p = path.make_path(e)
                            puntos = list(p.flattening(distance=0.1)) # 0.1 mm de precisión
                            for i in range(len(puntos)-1):
                                y1, z1 = puntos[i][0], puntos[i][1]
                                y2, z2 = puntos[i+1][0], puntos[i+1][1]
                                self.lineas.append((y1, z1, y2, z2))
                                
                                min_y, max_y = min(min_y, y1, y2), max(max_y, y1, y2)
                                min_z, max_z = min(min_z, z1, z2), max(max_z, z1, z2)
                        except Exception as spline_err:
                            print("Error aplanando entidad:", spline_err)

            if not self.lineas:
                self.btn_play.config(state=tk.DISABLED)
                self.btn_stop.config(state=tk.DISABLED)
                self.btn_preview_capas.config(state=tk.DISABLED)
                messagebox.showwarning("Vacío o Formato Incorrecto", "No se encontraron líneas, polilíneas, splines o arcos compatibles en el DXF.")
                return

            ancho = max_y - min_y
            alto = max_z - min_z
            self.offset_y = (self.limite_y_mm / 2) - (ancho / 2) - min_y
            self.offset_z = (self.limite_z_mm / 2) - (alto / 2) - min_z
            
            total_segmentos = len(self.obtener_trayectoria_completa())
            self.slider_sim.config(to=total_segmentos, state=tk.NORMAL)
            self.slider_sim.set(total_segmentos)
            self.btn_play.config(state=tk.NORMAL if total_segmentos > 0 else tk.DISABLED)
            self.btn_preview_capas.config(state=tk.NORMAL if total_segmentos > 0 else tk.DISABLED)
            self.btn_stop.config(state=tk.DISABLED)
            self.dibujar(total_segmentos)
            self.refrescar_info_tiempo(0.0)
            
        except Exception as ex:
            messagebox.showerror("Error", f"No se pudo leer el DXF:\n{ex}")

    def dibujar_grilla(self):
        dim_w = self.limite_y_mm * self.escala_visual
        dim_h = self.limite_z_mm * self.escala_visual

        for y in range(0, int(self.limite_y_mm) + 1, 10):
            px = y * self.escala_visual
            color = "#b0b0b0" if y % 50 == 0 else "#e0e0e0"
            width = 2 if y % 50 == 0 else 1
            self.canvas.create_line(px, 0, px, dim_h, fill=color, width=width)

        for z in range(0, int(self.limite_z_mm) + 1, 10):
            pz = (self.limite_z_mm - z) * self.escala_visual
            color = "#b0b0b0" if z % 50 == 0 else "#e0e0e0"
            width = 2 if z % 50 == 0 else 1
            self.canvas.create_line(0, pz, dim_w, pz, fill=color, width=width)
            
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

    def invertir_corte(self):
        if not self.lineas: return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
        if self.editando_capa_idx is None:
            self.invalidar_preview_capas()
        # Invertimos toda la lista de lineas y su inicio-fin
        self.lineas = [(y2, z2, y1, z1) for y1, z1, y2, z2 in reversed(self.lineas)]
        self.sincronizar_edicion_capa_si_corresponde()
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
                # Cabeza de corte en el último punto renderizado de la simulación
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
            self.btn_exportar.config(state=tk.DISABLED, text="¡Fuera de área!")
            self.btn_exportar_capas.config(state=tk.DISABLED, text="¡Fuera de área!")
            self.btn_preview_capas.config(state=tk.DISABLED)
            self.btn_guardar_batch_carpeta.config(state=tk.DISABLED)
            self.btn_guardar_capa_actual.config(state=tk.DISABLED)
        else:
            self.btn_exportar.config(state=tk.NORMAL, text="2. Generar G-Code")
            self.btn_exportar_capas.config(state=tk.NORMAL, text="3. Generar G-Codes por Placas")
            self.btn_preview_capas.config(state=tk.NORMAL if self.lineas else tk.DISABLED)
            self.btn_guardar_batch_carpeta.config(state=tk.NORMAL if self.capas_preview else tk.DISABLED)
            self.btn_guardar_capa_actual.config(state=tk.NORMAL if self.editando_capa_idx is not None else tk.DISABLED)

        self.dibujar_canvas_total()

    # --- GENERACIÓN DE GCODE ---
    def exportar_gcode(self):
        ruta_gcode = filedialog.asksaveasfilename(title="Guardar G-Code", defaultextension=".gcode", filetypes=[("G-Code", "*.gcode")])
        if not ruta_gcode: return

        try:
            # Convertimos mm/s a mm/min para que Marlin lo entienda
            # Todos los movimientos usan la misma velocidad para evitar cambios bruscos
            v_corte_mms = float(self.vel_corte.get())
            v_mov_mmin = int(v_corte_mms * 60)
        except ValueError:
            messagebox.showerror("Error", "Las velocidades deben ser números válidos.")
            return

        gcode = []
        gcode.append(";FLAVOR:Marlin")
        gcode.append(";TARGET_MACHINE.NAME:Ender-3 CNC Hilo Caliente")
        gcode.append("G21 ; Unidades en milimetros")
        gcode.append("G90 ; Posicionamiento absoluto")
        gcode.append("M140 S0 ; Apagar temperatura de la cama")
        gcode.append("M104 S0 ; Apagar temperatura del hotend")
        gcode.append("M107 ; Apagar ventilador de capa")
        gcode.append("G92 Y0 Z0 ; Establecer posicion actual como origen (0,0)")
        gcode.append(";--- INICIO DEL CORTE ---")

        # Partimos asumiendo que la máquina está en origen tras G92 Y0 Z0
        y_actual, z_actual = 0.0, 0.0

        for (y1, z1, y2, z2, tipo) in self.obtener_trayectoria_completa():
            y1_mod = round(y1 + self.offset_y, 3)
            z1_mod = round(z1 + self.offset_z, 3)
            y2_mod = round(y2 + self.offset_y, 3)
            z2_mod = round(z2 + self.offset_z, 3)

            # Movimiento suave de posicionamiento (sin G0) para evitar desplazamientos bruscos
            if (abs(y_actual - y1_mod) > 1e-6) or (abs(z_actual - z1_mod) > 1e-6):
                gcode.append(f"G1 F{v_mov_mmin} Y{y1_mod} Z{z1_mod}")
            
            # Movimiento de corte: Forzamos el F (Feedrate) en cada línea para mantener velocidad constante
            if tipo == "entrada":
                gcode.append("; Entrada 10mm")
            elif tipo == "salida":
                gcode.append("; Salida 10mm")
            elif tipo == "retorno_h":
                gcode.append("; Retorno horizontal a Y de origen")
            elif tipo == "retorno_v":
                gcode.append("; Ajuste final en Z para cerrar en origen exacto")
            elif tipo == "union":
                gcode.append("; Union recta entre segmentos")
            gcode.append(f"G1 F{v_mov_mmin} Y{y2_mod} Z{z2_mod}")
            
            y_actual, z_actual = y2_mod, z2_mod

        gcode.append(";--- FIN DEL CORTE ---")
        gcode.append(f"G1 F{v_mov_mmin} Y0 Z0 ; Volver suave a la posicion de origen inicial")
        gcode.append("M84 ; Apagar los motores")

        with open(ruta_gcode, 'w') as f:
            f.write("\n".join(gcode))
            
        messagebox.showinfo("Éxito", "¡G-Code generado correctamente!")

if __name__ == "__main__":
    root = tk.Tk()
    app = AppSlicerCNC(root)
    root.mainloop()