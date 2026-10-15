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

Paso 4 del panel lateral (**Show the Cut Lab**), menú **Step 4 · Cut Lab (wire temperature, feed, kerf)**, o `Ctrl+Shift+L`.

El Cut Lab se abre dentro de la ventana principal, en el lugar de la vista 3D, y usa el mismo bloque y la misma máquina que el proyecto: si se cambia el bloque en el Cut Lab, cambia también en el paso 1. Al ir a otro paso vuelve la vista 3D.

Arriba a la izquierda hay dos modos: **Guided** (el que abre por defecto) y **Advanced**. Los dos usan los mismos parámetros: lo que se cambia en uno aparece en el otro.

### Modo guiado (Guided)

Cinco pantallas cortas. Cada una hace una sola pregunta, dice en una frase por qué importa y muestra el resultado al lado. Se avanza con **Next →** o tocando los pasos de arriba.

| paso | qué se pregunta | qué se ve |
|---|---|---|
| **1 Supply & wire** | cómo se regula la fuente, cuánto, qué hilo y qué espuma. Por defecto es una fuente de tensión (CV) con límite de corriente; también se puede elegir corriente (CC) hasta una tensión máxima | el hilo entre los brazos con su color de temperatura y un termómetro: muy frío para cortar, corta, demasiado caliente |
| **2 Test feed** | a qué velocidad probar (lento, medio, rápido o *Suggest a good speed for me*) | una barra de velocidades coloreada (ranura ancha, corte limpio, el hilo toca, no llega a fundir) y el hilo visto de punta dentro de la espuma |
| **3 Result** | leer el resultado | tres tarjetas: ¿corte limpio?, ancho de la ranura (kerf) y temperatura del hilo cortando; abajo, la temperatura a lo largo del hilo |
| **4 Calibrate** | opcional | chequeo rápido con la resistencia en frío medida con el multímetro, o el acceso a la calibración completa |
| **5 Your settings** | la recomendación | qué poner en la fuente, velocidad de trabajo y compensación de kerf (medio kerf por lado), más un resumen de lo que se va a guardar |

La velocidad recomendada es como mucho el 80 % del avance máximo sin contacto que predice el modelo (margen porque el modelo es optimista), no más rápida que el eje más lento de la impresora (Z del Ender 3: 5 mm/s), redondeada hacia abajo a 0,1 mm/s.

En el paso 5:
- *Save and use for the project* guarda la configuración y la aplica al proyecto: la velocidad pasa a ser la **Work speed** y la trayectoria se corre medio kerf hacia afuera de la pieza (hacia adentro en los agujeros), para que la pieza salga del tamaño dibujado. Después la app pasa sola al paso 5 (Export).
- La configuración queda guardada y se vuelve a aplicar cada vez que se abre la app. En el paso 4 se ve qué está en uso, y la casilla **Keep the part at its drawn size** permite cortar sobre la línea (sin compensar el kerf).
- *Simulate the cut of my part* abre el modo avanzado en **Cut simulation** y corre la simulación del G-code del proyecto.

### Modo avanzado (Advanced)

| zona | qué hay |
|---|---|
| panel izquierdo | fuente (corriente o tensión), avance, hilo (material, diámetro, vano, tensión), espuma, ambiente |
| tarjetas de arriba | temperatura del hilo en aire y en espuma, radio de incidencia, kerf, régimen (con o sin contacto), avance máximo sin contacto, flecha, tiempo de respuesta del hilo; **What do these numbers mean?** explica cada una en palabras simples |
| **Explore** | perfil de temperatura a lo largo del hilo, mapa de operación corriente × avance y vista de la sección; con **2-D solve** se resuelve la conducción transitoria alrededor del hilo |
| **Curves** | curvas de cada modelo contra el avance para varias corrientes, la ley empírica y el gráfico *predicho vs medido* |
| **Cut simulation** | recorre un G-code y muestra kerf, temperatura y contacto a lo largo del corte |
| **Calibration** | asistente de 6 pasos para ajustar el modelo a la máquina |

Sobre las pestañas, una línea explica qué muestra la pestaña abierta. **How it works** (arriba a la derecha) resume los modelos.

**Por qué la simulación corta varias "capas".** El hilo atraviesa todo el bloque, pero no es igual en todo su largo: está más caliente en el medio, más frío cerca de los brazos, y si toca la espuma se arquea más en el medio. Por eso cada posición a lo largo del hilo se corta un poco distinto. La simulación corta el bloque en varias posiciones (capas) y las compara. En la vista 3D se apilan los contornos de todas las capas: si difieren, la pieza sale levemente abarrilada.

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
