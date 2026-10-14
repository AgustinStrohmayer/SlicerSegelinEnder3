# Física del corte con hilo caliente: modelos del Cut Lab

Informe técnico de los modelos que usa el **Cut Lab** de SlicerSegelin v2: qué ecuaciones resuelve cada uno, qué supone, cómo se valida y qué dice la literatura. Está pensado para quien quiera hacer ensayos y calibraciones propias.

Código fuente:
- `appSlicerSegelin/v2/core/cutting_physics.py`: modelo reducido.
- `core/thermal2d.py`: solver 2-D.
- `core/calibration.py`: ajustes.
- `core/model_curves.py`: curvas y comparación.

---

## 1. El problema

Un hilo de NiCr de diámetro *d* (0,2–0,6 mm) está tensado entre dos brazos y lo calienta una corriente *I*. Avanza a velocidad *v* a través de espuma de poliestireno (EPS/XPS). El hilo no corta por contacto: el calor que conduce y radia hace retroceder la espuma antes de que el hilo llegue.

Las magnitudes que interesan son:

| magnitud | símbolo | qué es |
|---|---|---|
| temperatura del hilo | *T_w* | en aire libre y dentro de la espuma (más fría) |
| radio de incidencia | *r_m* | distancia del eje del hilo al frente de espuma, adelante |
| kerf | *k* | ancho total de la ranura (lo que la pieza "pierde") |
| gap | *r_m − d/2* | capa de gas caliente entre hilo y espuma |
| contacto | — | el gap se cierra: el hilo empuja la espuma, arrastra y se arquea |

Mecanismo, según la literatura (Brooks & Aitchison [3], Mehta et al. [14]):
- Por debajo de la transición vítrea (T_g ≈ 103 °C en EPS y 118 °C en XPS) la espuma se rompe mecánicamente.
- Las celdas colapsan a partir de ~110 °C y vuelven por completo al polímero macizo a **~160 °C**.
- Por encima de ~160 °C el corte es térmico y sin contacto.
- El polímero empieza a volatilizarse hacia 275 °C, con la tasa máxima a 400–420 °C.

## 2. Modelo reducido (instantáneo, en la UI)

Es estacionario y se calcula en milisegundos. Tiene tres submodelos acoplados.

### 2.1 Balance del hilo (eléctrico–térmico)

Por unidad de longitud de hilo:

    I² R'(T_w) = q'_aire(T_w) + q'_corte

Los términos son:
- **Resistencia:** `R'(T) = ρ_e(1 + α(T − 20 °C)) / (π d²/4)`.
- **Pérdida en aire libre:** `q'_aire = π d [h (T − T∞) + ε σ (T⁴ − T∞⁴)]`.
  - *h* es convección natural de un cilindro horizontal según Churchill & Chu [15]:

        Nu_D = { 0,60 + 0,387 Ra_D^(1/6) / [1 + (0,559/Pr)^(9/16)]^(8/27) }²

  - Para hilos finos, Ra_D ≈ 10⁻²–10¹. Petkov & Hattel [12] revisan correlaciones específicas para ese rango bajo; queda como mejora posible.
- **Dentro de la espuma:** la mitad trasera del hilo pierde ½ q'_aire, y la delantera entrega q'_corte al frente.

A lo largo del vano el hilo es una **aleta con generación interna**, con los extremos fijados por las mordazas (Incropera [16]):

    k_w A T'' + I² R'(T) − q'_pérdida(T, x) = 0

Por eso el hilo está más frío cerca de los brazos y dentro del bloque (el "barrelling" del kerf).

- **Fuente constante (CC):** *I* es dato.
- **Fuente de tensión:** *I* se itera porque *R* sube con la temperatura.

### 2.2 Frente de fusión

El calor cruza el gap por conducción en el gas (medio anillo) más radiación:

    q'_frente(r_m, T_w) = η · [ π k_g (T_w − T_iso) / ln(r_m / r_w)  +  ε σ π r_w (T_w⁴ − T_iso⁴) ]

Ese calor debe igualar la energía necesaria para retirar una franja de ancho 2 r_m a velocidad *v*:

    q'_frente = e_v · v · 2 r_m ,     e_v = ρ_f [ c_f (T_iso − T∞) + L_eff ]

Notas sobre estas dos ecuaciones:
- La oferta *q'_frente* baja con *r_m* y la demanda sube con *r_m*, así que hay una única solución, que se encuentra por bisección.
- El kerf se calcula como **k = 2 κ r_m**.
- **Lento o caliente** → gap grande y kerf ancho.
- **Rápido o frío** → el gap se cierra hasta el umbral de contacto (`contact_gap`, 0,02 mm por defecto).

Valores de material por defecto:

| foam | ρ (kg/m³) | k (W/m·K) | c (J/kg·K) | T_iso (°C) | L_eff (kJ/kg) |
|---|---|---|---|---|---|
| EPS 15 / 20 / 30 | 15 / 20 / 30 | 0,037 / 0,035 / 0,034 | 1300 | 150 | 100 |
| XPS 35 | 35 | 0,032 | 1300 | 160 | 100 |

Son valores típicos de manual y se pueden calibrar.
- *T_iso* = 150–160 °C coincide con la isoterma de colapso que usan Brooks & Aitchison (160 °C, de Mehta et al.).
- Ahn et al. [1] usaron 240 °C.
- La conductividad coincide con la medida en [3]: 0,033 W/m·K en EPS y 0,032 W/m·K en XPS, a 20 °C.

### 2.3 Arco del hilo (lag)

Por encima de la velocidad de contacto *v_c*, el hilo empuja la espuma con una fuerza por unidad de longitud `F' = c_drag (v − v_c)`. Como cuerda tensada con tensión *T_N*:

    T_N δ'' = −F'(x)

Esto da la flecha a lo largo del vano. Karmakar et al. [10] describen el mismo fenómeno: el arqueo aparece cuando la corriente no alcanza para fundir delante del hilo, y lo corrigen midiendo la tensión.

### 2.4 Factores de calibración

| factor | qué corrige | se ajusta con |
|---|---|---|
| η | eficiencia de la transferencia hilo → frente | kerf medido a varias velocidades (pendiente) |
| κ | kerf / (2 r_m): la espuma sigue retrocediendo a los costados detrás del frente | nivel del kerf |
| c_drag | rigidez del arrastre en contacto | flecha medida |

`calibration.fit` ajusta η y κ por mínimos cuadrados en log(kerf) sobre las mediciones de la escalera de calibración.

## 3. Solver 2-D transitorio (botón "2-D solve")

Resuelve la misma física en una grilla sobre la sección del corte: *x* en la dirección del avance, *y* a través del kerf. La ventana se mueve con el hilo. No usa κ: el kerf **sale** del frente.

- **Ecuación:** conducción transitoria con cambio de fase por el método de entalpía (Voller & Prakash [19]; Crank [18]):

      ∂H/∂t − v ∂H/∂x = ∇·(k ∇T),     H = ρc T + φ-dependiente (calor latente en T_iso)

  - Cada celda lleva una fracción de espuma φ: 1 es espuma y 0 es gas en la ranura.
  - *k* y *ρc* mezclan espuma y aire; *k_aire(T)* va multiplicada por η.
- **Numérica:**
  - Advección exacta de una celda por paso (Δt = Δx/v), sin difusión numérica.
  - Difusión implícita (Euler hacia atrás) resuelta con gradiente conjugado precondicionado.
  - Conductancias de cara por media armónica.
- **Hilo:** es un nodo concentrado.

      C_w dT_w/dt = I² R'(T_w) − q_cond − q_rad − q_contacto

  - La conducción al gas se resuelve alrededor de todo el hilo.
  - No se suma convección en la ranura: su número de Rayleigh es ≪ 1.
  - La radiación se reparte sobre las caras de espuma que el hilo ve.
- **Condiciones de borde:**
  - Simetría en y = 0.
  - T∞ al costado.
  - Gradiente nulo donde la ranura sale de la ventana.
  - Adelante, condición de Robin que reproduce el precalentamiento 1-D `exp(−v x/α)`.

Este enfoque es el de Brooks & Aitchison [3]: FE 2-D transitorio con el hilo moviéndose por la malla y el kerf tomado de la isoterma de colapso. Se agregan tres cosas que ellos dejan como trabajo futuro o como fuente de error:
- el hilo con su propio balance de Joule, en vez de temperatura impuesta;
- el gap de gas resuelto;
- el calor latente.

Karmakar & Subbiah [9] agregan también el acople hilo–espuma y el calor latente, en 3-D.

### 3.1 Verificación numérica

Todas las cifras de esta sección están medidas: tests en `tests/unit/test_thermal2d.py` y docstring de `thermal2d.py`.

- **Balance de energía:**

      calor del hilo = espuma removida + calor que se llevan las paredes + pérdida lateral

  Cierra dentro del 1 %.
- **Estudio de grilla** a 3 mm/s, en las calidades coarse, normal, fine y ultra:
  - kerf 0,743 / 0,740 / 0,753 / 0,768 mm;
  - q = 29,5 / 28,9 / 29,0 / 29,2 W/m.
- **Tiempos (un núcleo):**

  | grilla | avance rápido | avance lento |
  |---|---|---|
  | coarse | < 1 s | 2–5 s |
  | normal | 1–8 s | 25–65 s |
  | fine | ~80 s | ~190 s |
  | ultra | ~50 s | > 15 min |

### 3.2 Qué enseña el 2-D sobre el modelo reducido

Configuración: Nichrome 0,3 mm en EPS 20, de 0,5 a 8 mm/s.

- **Hilo a la temperatura del modelo:**
  - El kerf 2-D es 0,70–0,95× el del modelo, con la misma tendencia.
  - El frente queda más cerca del hilo (r_m es más o menos la mitad).
  - Las paredes siguen retrocediendo detrás del hilo, así que kerf ≈ 3 r_m. Equivale a **κ ≈ 1,5**, lo que justifica físicamente el factor κ.
- **Calor en las paredes:** el que queda en las paredes de la ranura es del mismo orden que el que funde la espuma, y la forma cerrada no lo cuenta.
  - Con el balance de Joule del hilo, a 1,6 A el kerf 2-D es 0,73–1,02× el del modelo.
  - A 1,2 A el hilo corre más frío y el contacto llega cerca de 3 mm/s, contra ~9 mm/s del modelo.

## 4. Comparación con datos publicados

La única correlación empírica publicada que se pudo verificar en texto completo es la de **Brooks & Aitchison [3]**. Son más de 400 cortes con hilo NiCr de 0,36, 0,64 y 0,91 mm en EPS 26 y XPS 30 kg/m³.

- **Variable que gobierna:** el *calor efectivo* Q_eff = P'/V, la potencia por metro de hilo dividida por la velocidad (J/m²).
- **Ajuste para EPS con hilo de 0,64 mm**, en el rango Q_eff ≈ 2–17 kJ/m²:

      kerf [mm]    = 0,0964 · Q_eff [kJ/m²] + 0,343     (R² = 0,93)
      T_hilo [°C]  = 17,7  · Q_eff [kJ/m²] + 68,8      (R² = 0,94)

**Prueba del modelo reducido sin calibrar** (η = κ = 1):
- **Condiciones:** EPS 26 kg/m³ con k = 0,0327 W/m·K, hilo de 0,64 mm, vano de 140 mm.
- **Barrido:** I = 3–6 A y v = 5–30 mm/s, con Q_eff calculado con la P' del propio modelo.
- **Resultado en el rango del ajuste (6 puntos sin contacto):**
  - kerf del modelo / kerf de Brooks = **0,73–0,82**;
  - pendiente 0,079 contra 0,096 mm por kJ/m²;
  - temperatura del hilo del mismo orden (p. ej. 176 contra 166 °C y 303 contra 266 °C).
- **Lectura:** el modelo sin calibrar subestima el kerf en ~20 %. Es el mismo sentido y orden que el κ ≈ 1,25–1,5 que indica el solver 2-D.
- **Reproducción:** script `brooks.py` en las notas de la sesión; vale la pena convertirlo en test.

Otros datos útiles de la literatura:
- **Kerf típico:** 1,4–6 veces el diámetro del hilo (atribuido a Ahn et al. en [3]).
- **Enfriamiento:** el hilo puede enfriarse hasta ~400 °C al entrar en espuma gruesa respecto del aire libre, de modo que el acople hilo–espuma es imprescindible ([3], [9]).
- **Sesgos de un modelo de pura conducción** [3]:
  - subestima el kerf a Q_eff bajo, donde hay contacto mecánico;
  - lo sobreestima a Q_eff alto, porque ignora el gap de gas.
  - El modelo de esta app incluye el gap.
- **Bordes del bloque:** el kerf es más ancho cerca de los bordes [9], y la convección pesa en láminas delgadas.

## 5. Ley empírica directa (pestaña Curves / Calibration)

Sin física: se ajusta una ley de potencia por mínimos cuadrados en log–log.

    kerf = a · v^b · I^c          (o U^c en modo tensión)

- Se reporta *b* y *c* con su error estándar, R² en log, RMS en mm y una ley por cada corriente.
- **Interpretación de b:**
  - b ≈ −1: el hilo entrega potencia fija al frente y el kerf es ∝ 1/v.
  - b ≈ −½: domina la difusión.
  - Valores intermedios son lo habitual.
- **Interpretación de c:** como P ∝ I², un c ≈ 1–2 es lo esperable.

**Nota importante:** no se encontró ninguna correlación publicada del tipo kerf ∝ v^b I^c. La forma publicada es lineal en Q_eff (sección 4). Las dos formas son razonables y los ensayos pueden decidir cuál describe mejor los datos. Ver sección 6.

## 6. Propuesta de ensayos (para Juan y Julián)

1. **Preparación del hilo:**
   - Medir con multímetro la resistencia en frío del hilo; en Calibration, "resistivity from cold" ajusta ρ_e.
   - Con el hilo caliente, la resistencia da la temperatura media (`temperature_from_resistance`).
2. **Escalera de calibración:** generarla desde la pestaña Calibration.
   - Al menos 4 velocidades por corriente y al menos 3 corrientes.
   - Medir el espesor de cada escalón con calibre y cargar las mediciones.
3. **Ajustes:**
   - Ajustar η y κ del modelo.
   - Mirar la ley empírica y el gráfico *Predicted vs measured*: el RMS de cada fuente dice qué modelo predice mejor.
4. **Comparar contra Brooks & Aitchison:** registrar también tensión y corriente para calcular P' = U I / vano y Q_eff = P'/v. Graficar el kerf contra Q_eff para ver si los puntos de distintas corrientes colapsan en una sola recta, como en [3]. La app todavía no hace este ajuste; es una extensión directa.
5. **Corrida 2-D:** en algunos puntos, comparar kerf y temperatura del hilo. Si la medición coincide con el 2-D sin calibrar, el modelo físico explica el corte. Si no, la diferencia mide lo que falta: contacto, convección o propiedades del material.
6. **Exportar:** con *Export CSV* y *Save image*, para el informe.

## 7. Limitaciones conocidas

- Todo es estacionario por punto. El transitorio del hilo, con constante de tiempo de algunos segundos, solo se considera en la simulación de corte.
- Las propiedades de la espuma son de manual, y c_p tiene un salto en T_g que aquí no se modela [3].
- La convección natural usa Churchill & Chu fuera de su rango típico de Ra [12].
- El modelo 2-D es una sección media: no incluye el enfriamiento del hilo cerca de las mordazas, que sí está en el perfil a lo largo del vano del modelo reducido. Tampoco incluye los efectos de borde del bloque [9].
- La ablación por encima de ~275 °C está dentro de L_eff, no se modela por separado.

---

## Referencias

Verificadas contra Crossref, el repositorio institucional o el texto completo. Solo [3] se leyó completo; de las demás se usó el resumen o los metadatos.

1. D.G. Ahn, S.H. Lee, D.Y. Yang, "Investigation into thermal characteristics of linear hotwire cutting system for variable lamination manufacturing (VLM) process by using expandable polystyrene foam", *Int. J. Machine Tools and Manufacture* 42(4), 427–439, 2002. doi:10.1016/S0890-6955(01)00144-4
2. D.G. Ahn, S.H. Lee, D.Y. Yang, "A study on the influence of the sloped cutting angle on kerfwidth and part quality in the hotwire cutting of EPS foam for the VLM-s rapid prototyping process", *Int. J. Machine Tools and Manufacture* 43, 1447–1464, 2003. doi:10.1016/S0890-6955(03)00170-6
3. H. Brooks, D. Aitchison, "Using the Finite Element Method to Determine the Temperature Distributions in Hot-wire Polystyrene Cutting", conference paper, University of Canterbury. https://clok.uclan.ac.uk/id/eprint/3874/ (el PDF no indica congreso ni año; cita trabajos de 2011).
4. D.R. Aitchison, H.L. Brooks, J.D. Bain, D. Pons, "Rapid manufacturing facilitation through optimal machining prediction of polystyrene foam", *Virtual and Physical Prototyping* 6(1), 41–46, 2011. doi:10.1080/17452759.2010.533961
6. H.L. Brooks, D. Aitchison, "Force feedback temperature control for hot-tool plastic foam cutting", *Proc. IMechE Part B* 224(5), 709–719, 2010. doi:10.1243/09544054JEM1717
7. H. Brooks, D. Aitchison, "A review of state-of-the-art large sized foam cutting rapid prototyping and manufacturing technologies", *Rapid Prototyping Journal* 16(5), 318–327, 2010. doi:10.1108/13552541011065713
9. N. Karmakar, S. Subbiah, "A comprehensive numerical model for kerf width prediction in hot wire cutting of expanded polystyrene", *J. Manufacturing Processes* 61, 322–333, 2021. doi:10.1016/j.jmapro.2020.08.056
10. N. Karmakar, H. Chitikena, M. Venkateshwaran, S. Subbiah, "Direct Wire-Tension Measurement Based Bowing Correction in Hot Wire Cutting of Polystyrene", *Procedia Manufacturing* 48, 230–236, 2020. doi:10.1016/j.promfg.2020.05.042
11. K.P. Petkov, J.H. Hattel, "A thermo-electro-mechanical simulation model for hot wire cutting of EPS foam", *Int. J. Machine Tools and Manufacture* 107, 50–59, 2016. doi:10.1016/j.ijmachtools.2016.05.002
12. K. Petkov, J.H. Hattel, "Thermo-Electrical Mathematical Model for Prediction of Ni-Cr Hot-Wire Temperature in Free Air and Inside Small Circular Cavities", *Heat Transfer Engineering* 38(9), 881–891, 2017. doi:10.1080/01457632.2016.1211919
14. S. Mehta, S. Biederman, S. Shivkumar, "Thermal degradation of foamed polystyrene", *J. Materials Science* 30, 2944–2949, 1995. doi:10.1007/BF00349667
15. S.W. Churchill, H.H.S. Chu, "Correlating equations for laminar and turbulent free convection from a horizontal cylinder", *Int. J. Heat and Mass Transfer* 18(9), 1049–1053, 1975. doi:10.1016/0017-9310(75)90222-7. Los coeficientes de §2.1 son la forma habitual de los libros de texto; no se releyeron en el original.
16. T.L. Bergman, A.S. Lavine, F.P. Incropera, D.P. DeWitt, *Fundamentals of Heat and Mass Transfer*, 7th ed., Wiley, 2011. ISBN 978-0-470-50197-9.
18. J. Crank, *Free and Moving Boundary Problems*, Clarendon Press, Oxford, 1984. ISBN 0-19-853357-8.
19. V.R. Voller, C. Prakash, "A fixed grid numerical modelling methodology for convection-diffusion mushy region phase-change problems", *Int. J. Heat and Mass Transfer* 30(8), 1709–1719, 1987. doi:10.1016/0017-9310(87)90317-6

La numeración sigue las notas bibliográficas; se omiten las entradas no citadas. Otros trabajos relacionados, verificados solo por metadatos: Tanaka & Saito, *Trans. JSME C* 72 (2006), doi:10.1299/kikaic.72.3383; Gallina, *J. Manuf. Sci. Eng.* 128 (2006), doi:10.1115/1.2124990.
