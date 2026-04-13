import tkinter as tk
from tkinter import filedialog, messagebox
import ezdxf
try:
    from ezdxf import path
except ImportError:
    path = None
import math
import time

class AppSlicerCNC:
    def __init__(self, root):
        self.root = root
        self.root.title("Slicer CNC Hilo Caliente - Ender 3")
        
        # --- VARIABLES ---
        self.lineas = [] 
        self.offset_y = 0.0
        self.offset_z = 0.0
        self.escala_visual = 2.0 
        self.limite_mm = 220.0
        self.tolerancia_limite_mm = 0.2
        
        # Velocidades por defecto en mm/s
        self.vel_corte = tk.StringVar(value="30")
        self.vel_viaje = tk.StringVar(value="30")
        self.grados_origen = tk.StringVar(value="0.5")
        self.paso_traslado = tk.StringVar(value="0.1")
        
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

        tk.Label(panel_izq, text="Velocidad Corte (mm/s):").pack(anchor=tk.W, pady=(10,0))
        tk.Entry(panel_izq, textvariable=self.vel_corte).pack(fill=tk.X)
        
        tk.Label(panel_izq, text="Vel. Desplazamiento (mm/s):").pack(anchor=tk.W, pady=(5,0))
        tk.Entry(panel_izq, textvariable=self.vel_viaje).pack(fill=tk.X)
        
        tk.Label(panel_izq, text="\nTips:", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        tk.Label(panel_izq, text="- Arrastra el dibujo para moverlo.\n- Punto VERDE = Inicio de Corte\n- Rojo = Fuera de límite", justify=tk.LEFT, font=("Arial", 8)).pack(anchor=tk.W)

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

        self.btn_exportar = tk.Button(panel_izq, text="2. Generar G-Code", command=self.exportar_gcode, state=tk.DISABLED, bg="#4CAF50", fg="white", font=("Arial", 11, "bold"))
        self.btn_exportar.pack(fill=tk.X, pady=10)
        
        panel_der = tk.Frame(root, padx=10, pady=10)
        panel_der.pack(side=tk.RIGHT)
        
        tk.Label(panel_der, text="Área de Trabajo: 220x220 mm (Vista Y-Z)").pack()
        
        dim_canvas = int(self.limite_mm * self.escala_visual)
        self.canvas = tk.Canvas(panel_der, width=dim_canvas, height=dim_canvas, bg="#e0e0e0", relief=tk.SUNKEN, bd=2)
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
        delta_x = (event.x - self.drag_data["x"]) / self.escala_visual
        delta_y = -(event.y - self.drag_data["y"]) / self.escala_visual 
        
        self.offset_y += delta_x
        self.offset_z += delta_y
        
        self.drag_data["x"] = event.x
        self.drag_data["y"] = event.y
        self.dibujar(self.slider_sim.get())
        self.refrescar_info_tiempo(0.0)

    def mm_a_pixel(self, y_mm, z_mm):
        py = y_mm * self.escala_visual
        pz = (self.limite_mm - z_mm) * self.escala_visual 
        return py, pz

    def formatear_tiempo(self, segundos):
        total = max(0, int(round(segundos)))
        mm = total // 60
        ss = total % 60
        return f"{mm:02d}:{ss:02d}"

    def calcular_duraciones_trayectoria(self):
        trayectoria = self.obtener_trayectoria_completa()
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
        trayectoria = self.obtener_trayectoria_completa()
        if not trayectoria:
            return None

        z_vals = []
        for y1, z1, y2, z2, tipo in trayectoria:
            if tipo == "corte":
                z_vals.extend([z1 + self.offset_z, z2 + self.offset_z])

        if not z_vals:
            for _y1, z1, _y2, z2, _tipo in trayectoria:
                z_vals.extend([z1 + self.offset_z, z2 + self.offset_z])

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

    def _obtener_trayectoria_completa_desde(self, lineas_base):
        """Devuelve trayectoria con entrada/salida horizontal de 10 mm para un conjunto de líneas."""
        corte = self._obtener_trayectoria_corte_desde(lineas_base)
        if not corte:
            return []

        inicio_y, inicio_z = corte[0][0], corte[0][1]
        if len(corte) >= 1:
            dir_inicio = corte[0][2] - corte[0][0]
        else:
            dir_inicio = 1.0
        signo_inicio = 1.0 if dir_inicio >= 0 else -1.0

        entrada_y = inicio_y - (10.0 * signo_inicio)
        entrada = (entrada_y, inicio_z, inicio_y, inicio_z, "entrada")

        fin_y, fin_z = corte[-1][2], corte[-1][3]
        dir_fin = corte[-1][2] - corte[-1][0]
        signo_fin = 1.0 if dir_fin >= 0 else -1.0

        salida_y = fin_y + (10.0 * signo_fin)
        salida = (fin_y, fin_z, salida_y, fin_z, "salida")

        corte_tipado = [(y1, z1, y2, z2, "corte") for (y1, z1, y2, z2) in corte]
        return [entrada] + corte_tipado + [salida]

    def obtener_trayectoria_completa(self):
        """Devuelve trayectoria con entrada/salida horizontal de 10 mm.

        Cada item: (y1, z1, y2, z2, tipo)
        tipo: 'entrada' | 'corte' | 'salida'
        """
        return self._obtener_trayectoria_completa_desde(self.lineas)

    def alinear_origen_corte(self):
        """Hace coincidir origen operativo y origen del corte (0,0), sin validar límites."""
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()

        trayectoria = self.obtener_trayectoria_completa()
        if not trayectoria:
            return

        # Traslada el dibujo para que el inicio operativo actual quede en (0,0)
        y0, z0 = trayectoria[0][0], trayectoria[0][1]
        self.offset_y = -y0
        self.offset_z = -z0
        self.slider_sim.set(0)
        self.dibujar(0)
        self.refrescar_info_tiempo(0.0)

    def rotar_sobre_origen_corte(self, angulo_grados):
        """Rota manualmente la pieza alrededor del origen operativo actual del corte."""
        if not self.lineas:
            return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()

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
        self.dibujar(self.slider_sim.get())
        self.refrescar_info_tiempo(0.0)

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

        self.dibujar(self.slider_sim.get())
        duraciones = self.calcular_duraciones_trayectoria()
        if duraciones:
            idx = min(self.slider_sim.get(), len(duraciones))
            self.refrescar_info_tiempo(sum(duraciones[:idx]))
        else:
            self.refrescar_info_tiempo(0.0)

    def cargar_dxf(self):
        ruta_dxf = filedialog.askopenfilename(title="Seleccionar DXF", filetypes=[("Archivos DXF", "*.dxf")])
        if not ruta_dxf: return
        
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
                messagebox.showwarning("Vacío o Formato Incorrecto", "No se encontraron líneas, polilíneas, splines o arcos compatibles en el DXF.")
                return

            ancho = max_y - min_y
            alto = max_z - min_z
            self.offset_y = (self.limite_mm / 2) - (ancho / 2) - min_y
            self.offset_z = (self.limite_mm / 2) - (alto / 2) - min_z
            
            total_segmentos = len(self.obtener_trayectoria_completa())
            self.slider_sim.config(to=total_segmentos, state=tk.NORMAL)
            self.slider_sim.set(total_segmentos)
            self.btn_play.config(state=tk.NORMAL if total_segmentos > 0 else tk.DISABLED)
            self.btn_stop.config(state=tk.DISABLED)
            self.dibujar(total_segmentos)
            self.refrescar_info_tiempo(0.0)
            
        except Exception as ex:
            messagebox.showerror("Error", f"No se pudo leer el DXF:\n{ex}")

    def dibujar_grilla(self):
        dim = self.limite_mm * self.escala_visual
        for i in range(0, int(self.limite_mm) + 1, 10):
            p = i * self.escala_visual
            color = "#b0b0b0" if i % 50 == 0 else "#e0e0e0"
            width = 2 if i % 50 == 0 else 1
            # Verticales (marcando posiciones en Y)
            self.canvas.create_line(p, 0, p, dim, fill=color, width=width)
            # Horizontales (marcando posiciones en Z)
            self.canvas.create_line(0, p, dim, p, fill=color, width=width)
            
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
        self.dibujar()
        self.refrescar_info_tiempo(0.0)

    def invertir_corte(self):
        if not self.lineas: return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
        # Invertimos toda la lista de lineas y su inicio-fin
        self.lineas = [(y2, z2, y1, z1) for y1, z1, y2, z2 in reversed(self.lineas)]
        self.slider_sim.set(0)
        self.dibujar(0)
        self.refrescar_info_tiempo(0.0)

    def auto_ajustar(self):
        if not self.lineas: return
        if self.reproduciendo:
            self.detener_simulacion_tiempo_real()
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
        self.offset_y = (self.limite_mm / 2) - (ancho / 2) - min_y
        self.offset_z = (self.limite_mm / 2) - (alto / 2) - min_z
        self.dibujar()
        self.refrescar_info_tiempo(0.0)

    def dibujar(self, sim_val=None):
        self.canvas.delete("all")
        self.dibujar_grilla()
        if not self.lineas: return

        lineas_render = self.obtener_trayectoria_completa()
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
            pyc, pzc = self.mm_a_pixel(primer_corte[0] + self.offset_y, primer_corte[1] + self.offset_z)
            r = 4
            self.canvas.create_oval(pyc-r, pzc-r, pyc+r, pzc+r, fill="#4CAF50", outline="black")

        for i, (y1, z1, y2, z2, tipo) in enumerate(lineas_render):
            y1_mod, z1_mod = y1 + self.offset_y, z1 + self.offset_z
            y2_mod, z2_mod = y2 + self.offset_y, z2 + self.offset_z
            tol = self.tolerancia_limite_mm
            
            if (y1_mod < -tol or y1_mod > self.limite_mm + tol or z1_mod < -tol or z1_mod > self.limite_mm + tol or
                y2_mod < -tol or y2_mod > self.limite_mm + tol or z2_mod < -tol or z2_mod > self.limite_mm + tol):
                fuera_de_limite = True
                color = "green" if tipo in ("entrada", "salida") else "red"
            else:
                color = "green" if tipo in ("entrada", "salida") else "blue"
                
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
            oy_start, oz_start = self.mm_a_pixel(lineas_render[0][0] + self.offset_y, lineas_render[0][1] + self.offset_z)
            self.canvas.create_oval(oy_start-5, oz_start-5, oy_start+5, oz_start+5, fill="orange", outline="black")

        if fuera_de_limite:
            self.btn_exportar.config(state=tk.DISABLED, text="¡Fuera de área!")
        else:
            self.btn_exportar.config(state=tk.NORMAL, text="2. Generar G-Code")

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