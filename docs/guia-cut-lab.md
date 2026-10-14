# Guía rápida: Cut Lab para ensayos y calibración

Para quien va a usar SlicerSegelin para estudiar el corte con hilo caliente: predecir el kerf, medirlo y comparar modelos. La física y las referencias están en [fisica-del-corte.md](fisica-del-corte.md).

## 1. Instalar

**Opción A: ejecutable portable (Windows 10/11, 64 bits).** No hace falta instalar Python.
1. Descomprimir `SlicerSegelin-portable.zip` en cualquier carpeta o en un pendrive.
2. Abrir `SlicerSegelin.exe`.
   - Si la vista 3D no arranca, usar `SlicerSegelin (modo compatible).bat`.
   - Los perfiles y la configuración se guardan en la carpeta `datos` que está junto al programa.

**Opción B: desde el repositorio** (para ver o modificar el código).

```bash
git clone https://github.com/AgustinStrohmayer/SlicerSegelinEnder3.git
```

```bash
cd SlicerSegelinEnder3
```

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt
```

```bash
.venv/Scripts/python -m appSlicerSegelin.v2
```

- Requiere Python 3.10 o superior.
- Los tests se corren con `.venv/Scripts/python -m pytest`.
- El ejecutable se reconstruye con `.venv/Scripts/python packaging/build_portable.py --zip` y queda en `dist/`.

## 2. Abrir el Cut Lab

Menú **Simulate → Cut Lab (wire–foam physics)…**, o `Ctrl+Shift+L`.

| zona | qué hay |
|---|---|
| panel izquierdo | fuente (corriente o tensión), avance, hilo (material, diámetro, vano, tensión), espuma, ambiente |
| tarjetas de arriba | temperatura del hilo en aire y en espuma, radio de incidencia, kerf, régimen (con o sin contacto), avance máximo sin contacto, flecha |
| **Explore** | perfil de temperatura a lo largo del hilo, mapa de operación corriente × avance y vista de la sección; con **2-D solve** se resuelve la conducción transitoria alrededor del hilo |
| **Curves** | curvas de cada modelo contra el avance para varias corrientes, la ley empírica y el gráfico *predicho vs medido* |
| **Cut simulation** | recorre un G-code y muestra kerf, temperatura y contacto a lo largo del corte |
| **Calibration** | asistente de 6 pasos para ajustar el modelo a la máquina |

**How it works** (arriba a la derecha) resume los modelos.

## 3. Hacer una calibración propia

Seguir la pestaña **Calibration**:

1. **What & why:** qué se va a medir.
2. **Check the wire:** medir con el multímetro la resistencia del hilo en frío, de mordaza a mordaza, y aplicarla con *Use measured resistance*. Corrige la resistividad real del hilo.
3. **Cut the test strips:** genera el G-code de una "escalera". Son tiras de espesor nominal cortadas a distintas velocidades, una por cada velocidad. Repetir para cada corriente a ensayar: al menos 3 corrientes y 4 velocidades.
4. **Measure:** medir con calibre el espesor de cada tira y cargarlo. Kerf = espesor nominal − espesor medido.
5. **Fit & apply:**
   - *Fit to my measurements* ajusta η (transferencia de calor) y κ (ancho del kerf respecto del frente).
   - También muestra la ley empírica `kerf = a·v^b·I^c`.
   - *Apply to the model* deja el modelo calibrado.
6. **Bow (optional):** si se midió la flecha del hilo en contacto, ajusta el arrastre.

Las mediciones se guardan con *Save profile…* y se recuperan con *Load profile…*.

## 4. Ver y comparar curvas

En **Curves**:
1. Elegir la magnitud: kerf, r_m, temperatura del hilo o gap.
2. Elegir las corrientes, por ejemplo `1, 1.2, 1.4`, o tocar *Use the measured drives*.
3. Elegir el rango de avance.
4. Fuentes disponibles:

   | fuente | qué es |
   |---|---|
   | **Model (calibrated)** | el modelo con η y κ ajustados |
   | **Model, handbook values** | el modelo sin calibrar (η = κ = 1) |
   | **Empirical law** | la ley de potencia ajustada directamente a las mediciones |
   | **2-D solve** | conducción 2-D sin calibrar en algunos avances; tocar *Compute 2-D points*: coarse tarda segundos por punto, normal hasta un minuto |
   | **Measured** | las mediciones |

5. Leer los resultados:
   - Los marcadores huecos indican que en ese punto el hilo toca la espuma.
   - *Predicted vs measured* da el RMS de cada fuente: la menor es la que mejor predice.
6. *Export CSV…* y *Save image…* sirven para el informe.

**Cómo leer la ley empírica:**
- Exponente del avance b:
  - b ≈ −1: kerf ∝ 1/v, potencia fija entregada al frente.
  - b ≈ −½: domina la difusión.
- Exponente de la corriente c: como P ∝ I², lo esperable es c ≈ 1–2.
- Se muestra cada exponente con su error estándar.

## 5. Ideas de proyecto

- **Ley lineal en Q_eff.** Brooks & Aitchison encontraron que el kerf es lineal en el calor efectivo Q_eff = P′/v, la potencia por metro de hilo dividida por la velocidad. Registrar tensión y corriente en cada corte, graficar kerf contra Q_eff y ver si colapsa en una recta. Compararlo con la ley de potencia.
- **Cuánto explica la física sin calibrar.** Comparar el RMS del modelo "handbook" y del 2-D contra la medición.
- **Densidad de espuma.** Repetir la calibración con EPS 15, 20 y 30 y ver cómo cambian η, κ y los exponentes.
- **Temperatura del hilo en el corte.** Medir la resistencia en caliente (tensión/corriente) mientras corta y comparar con la temperatura predicha. La app la convierte con `temperature_from_resistance`.
