# ESTADO ACTUAL DEL PROYECTO — FUENTE DE VERDAD

**Última actualización:** 21 de septiembre de 2026 (noche)
**Versiones anteriores:** `historico/00_ESTADO_ACTUAL_PROYECTO_2026-08-24.md`,
`historico/00_ESTADO_ACTUAL_PROYECTO_2026-09-21a.md`, `historico/00_ESTADO_ACTUAL_PROYECTO_2026-09-21b.md`
**Estatus:** arquitectura de captura adoptada; alcance fijado en **pre-corte, post-corte y tolva**; queda
pendiente fijar la potencia del LED de tolva (**D10a**) y aprobar el paquete de cabina (**D10b + D11**) (§4)

> Este archivo prevalece sobre cualquier otro documento del proyecto.
> `Propuesta_Proyecto_de_Grado_v2.docx` sigue **congelado**; cuando se reabra, su título, pregunta,
> objetivos y delimitación conceptual deben revisarse por C22 y C25.

### Qué cambió en esta versión

1. El equipo cerró **D4** (se harán las pruebas de los ultrasónicos), **D5** (`grupo` = fecha de la
   jornada) y **D9** (la Pi se alimenta con una batería de mayor voltaje, no con powerbank). Ahora son
   C28–C30.
2. El equipo confirmó que **las tolvas van cubiertas** (C31) y aprobó el **LED pulsado con paquete de 3
   celdas** (C32). La fuente de cabina será de **paquetes de 18650** (C33).
3. Queda **D10a** (potencia del LED, a fijar en el banco) y la recomendación de **D10b + D11**: un solo
   paquete 3S5P en cabina para la Pi y el punto de acceso (§7-A7).

---

## A. Arquitectura adoptada — RiceVi v1.0

**Documentos de referencia:** `Actualizacion/01-arquitectura-hardware`, `02-configuracion-sistema`,
`03-manual-de-campo` (.md, .pdf y .docx de igual contenido).

| Subsistema | Equipo | Observa | Produce |
|---|---|---|---|
| PRE-CORTE | `CAM01` (ESP32-S3-CAM, OV3660) frente al cabezal | Cultivo antes de entrar al cabezal | Clase ordinal de acame: erecto · moderado · severo |
| POST-CORTE | `CAM02`, `CAM03`, detrás del cabezal, izq. y der. | Franja recién cortada | Fracción visual de material útil visible tras el paso del cabezal |
| TOLVA | `CAM04` dentro de la tolva, con LED y referencia de color | Superficie del material acumulado | Fracción visual de material no grano |
| Operación | `NH01` (Hall, eje del molinete), `NH02` (Hall, rueda), `NU01`/`NU02` (ultrasónico A02YYUW, extremos del cabezal) | Molinete, rueda, distancia al suelo | `reel_rpm`, `wheel_speed` (estimada), `header_height` (sin validar), `reel_index` |
| Central | `RPI01` Raspberry Pi 5 8 GB + NVMe 512 GB, en cabina, **con alimentación propia** (C26); `AP01` 2,4 GHz fuera, por Ethernet; `HMI01` navegador | — | Ingesta, verificación, almacenamiento; inferencia y sugerencias en fase 2 |

**Dos fases:** fase 1 **dataset** (por defecto, no infiere) y fase 2 **inferencia** (NCNN en la Pi).

**Encaje con la tesis:** la fase 1 es el instrumento del dataset sincronizado (OE2); la fase 2 es la
plataforma de medición de tiempos de inferencia (OE4). El HMI es herramienta de operación de campo.

---

## 1. Propósito y límite de lo demostrable

| Nivel | Enunciado |
|---|---|
| **Motivación** | Contribuir a reducir las pérdidas asociadas a la cosecha mecanizada de arroz mediante visión artificial |
| **Lo que la tesis puede demostrar** | Diagnosticar condiciones visuales asociadas al **corte** (pre-corte y post-corte) y a la **limpieza** (tolva) mediante modelos de visión artificial |
| **Extensión opcional** | Trilla, solo si hay tiempo (C22) |

**No se afirmará:** reducción de X kg/ha · que un ajuste causa una pérdida · haber encontrado el ajuste
óptimo · control de la máquina · que seguir las sugerencias reduce pérdidas.

---

## 2. Decisiones CERRADAS

| # | Decisión | Consecuencia operativa |
|---|---|---|
| **C1** | **Diseño base observacional** | Se registran las condiciones normales de operación y los cambios que hace el operario, con tiempo muerto tras cada uno |
| **C2** | **Vocabulario no causal** | «Asociación», «comportamiento bajo determinada condición», «desempeño estratificado» |
| **C3** | **Humedad del grano fuera del alcance** | No se reintroduce sin que el equipo reabra la decisión |
| **C4** | **Núcleo de limpieza = superficie del material acumulado en la tolva** (`CAM04`) | Redefinida por la arquitectura v1.0. Riesgos de medida en `04_REVISION` H3 |
| **C5** | **Vista B (descarga) no es requisito** | Extensión futura |
| **C6** | **La tolva no cuantifica pérdida por descarga** | Estudia la composición de lo que llega a la tolva |
| **C7** | **Dataset multimodal ≠ modelo multimodal** | Modelos solo visuales; variables físicas como contexto |
| **C8** | **Sensores propios para las variables de corte** (sustituye la regla de leer el monitor) | Justificación para la tesis: la lectura manual del monitor no da series continuas sincronizadas con las imágenes, y el bus CAN de una máquina ajena se descartó |
| **C9** | **Jerarquía monitor → externo → propio** | Vigente solo para variables nuevas |
| **C10** | **Norma de verificación bibliográfica** (§6) | Permanente |
| **C11** | **Nunca afirmar ausencia mundial de antecedentes** | Permanente |
| **C12** | **`02_BIBLIOGRAFIA_CANDIDATA_v1.md` es banco de candidatos** | Nada aprobado hasta que el equipo lo lea |
| **C13** | **`.docx` v2 congelado** | Ver nota de cabecera |
| **C14** | **Orden de trabajo** | Tras C22, el orden efectivo es: Corte (pre y post) → Limpieza (tolva) → Dataset → documento |
| **C15** | **Arquitectura RiceVi v1.0 adoptada** (§A) | Fuente: `Actualizacion/01–03` |
| **C16** | **Dos fases: dataset por defecto, inferencia opcional** | Sin modelo, el HMI muestra «sin modelo» |
| **C17** | **Regla del nulo** | Sin medida, el valor es nulo; muestra nula con calidad `buena` se rechaza |
| **C18** | **Se guardan las magnitudes crudas** | Permiten recalcular la campaña |
| **C19** | **Acame: clasificación ordinal de 3 clases** | erecto · moderado · severo |
| **C20** | **Reel index calculado en la central** | K = ωR/V; radio del molinete al extremo de la púa, una vez por máquina. Falta escribir la fórmula con unidades en la documentación del sistema |
| **C21** | **Partición por `grupo`**, nunca al azar sobre frames | `grupo` = fecha de la jornada (C29) |
| **C22** | **La trilla sale del alcance obligatorio** *(D1, 21-sep)* | El sistema cubre pre-corte, post-corte y tolva. Trilla se entrenará solo si queda tiempo. **Al reabrir el `.docx`: revisar título, pregunta y objetivos**, que hoy nombran la trilla. *Nota: si las imágenes de `CAM04` se capturan con calidad suficiente, la trilla podría añadirse después etiquetando `grano_partido` sobre el mismo dataset, sin nuevas salidas de campo* |
| **C23** | **La cosechadora es de ruedas** *(D2)* | `NH02` es viable |
| **C24** | **Sin GNSS** *(D3)* | La velocidad proviene solo de `NH02`. Se declara en la tesis como **velocidad estimada**, sujeta a patinaje, y el reel index hereda ese error. Estratificar el reel index por tramos, no por valores puntuales |
| **C25** | **Se mantienen las «sugerencias» al operario** *(D6)* | Solo existen en fase 2. Condiciones recomendadas para que sean defendibles: ver §7-A6. **Al reabrir el `.docx`: revisar la delimitación de «diagnóstico»**, que hoy excluye la prescripción de ajustes |
| **C26** | **La Pi no se conecta a la máquina** *(D7)* | Desaparecen la señal de contacto, el optoacoplador y `RICEVI_GPIO_CONTACTO`. El apagado pasa a ser manual (manual de campo §4). La fuente se fija en C30 |
| **C27** | **Sin línea base precosecha** *(D8)* | El indicador de post-corte se redacta como **«material útil visible tras el paso del cabezal»**. No se atribuye al cabezal ni se llama pérdida de cabezal, porque incluye el desgrane previo a la cosecha |
| **C28** | **Se harán las pruebas de validación de los ultrasónicos** *(D4)* | En la primera salida, con la máquina detenida dentro del lote y sobre rastrojo: comparar con cinta la altura real de la cuchilla y la que reporta el sistema, a 3–4 alturas del cabezal. `header_height` solo se publica si coincide (±2–3 cm); si no, queda como contexto no publicable |
| **C29** | **`grupo` = fecha de la jornada** *(D5)* | Varias jornadas de captura, no siempre en el mismo terreno. Jornadas enteras reservadas para prueba, nunca vistas en entrenamiento. No se usa `session_id` como grupo, porque un reinicio de la central a mitad del día podría partir la jornada |
| **C30** | **La Pi se alimenta con una batería de mayor voltaje, no con powerbank** *(D9)* | Batería de más voltaje + convertidor a 5 V (el DC-DC 12 V → 5 V / 6 A de la lista de materiales), que cumple la especificación de 01 §3.5. Dimensionamiento pendiente (D11) |
| **C31** | **Las tolvas de la máquina van cubiertas** *(dato de campo, 22-sep)* | Caso favorable para `CAM04`: el LED no compite con luz solar. Ver §7-A8, punto 3 |
| **C32** | **LED de tolva pulsado, sincronizado con cada foto, sobre un paquete de 3 celdas 18650** *(D10a)* | Lo enciende y apaga el ESP32 de `CAM04` con un transistor, compartiendo el paquete de la cámara ampliado de 2 a 3 celdas. Falta solo fijar la potencia en el banco (5–10 W de pico según §7-A8) |
| **C33** | **La fuente de la cabina será de paquetes de 18650** *(preferencia del equipo, 22-sep)* | Configuración y tamaño concretos en D11 |

---

## 3. Decisiones PROVISIONALES

| # | Decisión provisional | Estado | Qué falta |
|---|---|---|---|
| **P1** | **Dataset híbrido** con partición de prueba real y sin fuga | Preferida por el equipo | Validación con profesor/director |
| **P2** | **Dataset sincronizado visión + variables operativas** | Materializado por la arquitectura | Anotar a mano, por evento, los ajustes de limpieza que muestre el monitor (ventilador, zarandas), conforme a C9 |
| **P4** | **Altura de cabezal** por ultrasonido | Instrumentada, **sin validar** | Resultado de la prueba de C28 |
| **P6** | **Posición exacta de `CAM01`** | Sin especificar | Documentar altura, orientación y si el molinete entra en el encuadre |
| **P7** | **Velocidad del ventilador** | Provisional | Se revisa en el bloque Limpieza (A2) |

---

## 4. Decisiones PENDIENTES

| # | Decisión | Estado | Recomendación |
|---|---|---|---|
| **D10a** | **Potencia del LED de tolva** | Método cerrado (C32); falta solo la potencia | Prueba de banco con la cámara, la distancia real y exposición manual. Partir de **5 W de pico**; subir a 10 W si la foto sale corta de luz. El pulso hace que subir la potencia cueste poco (§7-A8) |
| **D10b + D11** | **Batería de cabina: Pi y punto de acceso** | Abiertas; recomendación en §7-A7 | **Un solo paquete 3S de 18650 en cabina** para las dos cosas: **3S5P (15 celdas)** cubre una jornada de 12 h en fase 1 con el AP colgado del mismo paquete. Pi por el DC-DC de 5 V / 6 A ya presupuestado; AP por un segundo convertidor pequeño, con el cable de alimentación junto al de Ethernet |

**Heredadas:**

| # | Pendiente | Estado |
|---|---|---|
| **X1** | Terminología de la «altura de corte» | La arquitectura mide `header_height`. Si la tesis habla de altura de corte, revisar `03_CORTE` §7 (longitud de rastrojo, ISO 6689) |
| **X9** | Trazabilidad | Resuelta (arquitectura 01 §5 + C29) |
| **X11** | Instrumentar el ventilador | Bloque Limpieza |

*Resueltas o sin objeto: X2–X8, X10 (trilla fuera, C22).*

---

## 5. Variables vigentes del proceso de CORTE

| Categoría | Variable | Fuente | Estado |
|---|---|---|---|
| Visual | Clase ordinal de acame | `CAM01` + anotación | Vigente (C19) |
| Visual | Material útil visible tras el paso del cabezal | `CAM02`, `CAM03` + segmentación | Vigente; definición de la clase pendiente de OE1 (`04_REVISION` H4) |
| Operativa | RPM del molinete | `NH01` | Vigente |
| Operativa | Velocidad de avance, **estimada** | `NH02` (rueda) | Vigente (C23, C24) |
| Operativa | Altura de cabezal, izq. y der. | `NU01`, `NU02` | **Sin validar**; prueba decidida (C28) |
| Derivada | Reel index | Central | Vigente (C20); por tramos (C24) |

---

## 6. Norma de verificación bibliográfica (permanente)

Para cada afirmación: título exacto · autores · año · DOI · enlace · base · **afirmación exacta** ·
**página/sección/tabla** · **limitaciones de aplicación**. Nunca afirmar «no existe»: «en la revisión
realizada no se identificaron…», con bases, fecha, términos, filtros y criterios.

---

## 7. Advertencias técnicas abiertas

### A1 · Riesgo potencial de variabilidad limitada en la metadata operativa
Mitigación de costo cero: estratificar también por jornada, hora, lote, variedad, condición de acame y
velocidad de avance.

### A2 · Velocidad del ventilador
«En estudios específicos, la velocidad del ventilador aparece junto con otras variables operativas entre los
factores relevantes para explicar el contenido de material distinto al grano en el tanque.» Se revisa en
Limpieza.

### A3 · Observabilidad del rastrojo
Abordada por `CAM02`/`CAM03` (franja recién cortada, pasada actual).

### A4 · Circularidad de la velocidad por visión
No aplica mientras la velocidad venga de `NH02`.

### A6 · Condiciones para que las «sugerencias» sean defendibles (C25)
Recomendaciones, no decisiones:
1. Cada sugerencia debe salir de una **regla documentada** —manual de la máquina o literatura citada—, no de
   correlaciones halladas en los propios datos, que por C1 y C2 no permiten inferir causas.
2. **Cualitativas, no numéricas**: «considere aumentar el reel index», no «ponga K = 1,7». La literatura
   revisada no ofrece un óptimo universal (`03_CORTE` §10.3).
3. La tesis **no evalúa** si seguir las sugerencias reduce pérdidas; eso requeriría un experimento controlado.
4. El operario decide; el sistema no acciona nada (ya lo dice 01 §1).

### A7 · Batería de la Pi 5 (C30, D11)
*La powerbank quedó descartada (C30): la Pi 5 espera 5 V / 5 A y la mayoría de powerbanks dan 5 V / 3 A, lo
que 01 §3.5 identifica como causa de reinicios por subtensión.*

Dimensionamiento **estimado, no medido**, con celdas 18650 de 3000 mAh (85 % aprovechable) en 3S y
convertidor a 5 V con rendimiento del 90 %, para 12 h:

| Carga | Consumo en batería | Energía en 12 h | Paquete que la cubre |
|---|---|---|---|
| Pi sola, fase 1 (7 W supuesto, sin inferencia) | 7,8 W | ≈ 93 Wh | 3S4P (12 celdas) → 14,6 h |
| **Pi + AP, fase 1** (7 W + 3 W) | 11,1 W | ≈ 133 Wh | **3S5P (15 celdas) → 12,7 h** |
| Pi + AP, fase 2 (9–12 W + 3 W) | 13,3–16,7 W | 160–200 Wh | 3S5P da 8,5–10,6 h: suficiente para sesiones cortas de medición |

**Recomendación (D10b + D11): un solo paquete 3S5P en cabina para la Pi y el punto de acceso.** La campaña
de captura es fase 1, sin inferencia, así que el consumo alto de 01 §3.5 solo aparece en las sesiones de
medición de la fase 2, que no necesitan durar una jornada entera.

- **Serie sí, para la Pi.** La Pi pide unos 2,5 A a 5 V; desde un paquete 1S habría que sacar casi 4 A de las
  celdas por un elevador. Desde 3S, el convertidor toma poco más de 1 A. Por eso aquí conviene la serie que
  01 §3.1 descartó con razón para los nodos.
- **Cargar sin equipo nuevo.** Con celdas protegidas en portapilas, se sacan y se cargan una a una en el
  cargador de bahía que ya está presupuestado: no hace falta cargador con balanceo. Como todas salen llenas,
  el paquete arranca equilibrado. Son 15 celdas por noche: conviene un cargador de más bahías o dos.
- Comprobar que la entrada del convertidor admita desde **9 V** (3S descargado) y no solo 12 V.
- Para el AP conviene elegirlo **alimentado por USB a 5 V** y colgarlo de un segundo convertidor pequeño; un
  AP de 12 V conectado directo al paquete vería entre 12,6 y 9 V según la carga.
- Alternativa más simple si prefieren no armar el paquete: **batería comercial de 12 V con protección
  integrada**.
- La Pi 5 permite declarar que una fuente sin PD entrega 5 A (`PSU_MAX_CURRENT` en su configuración de
  arranque); **confirmar en la documentación oficial antes de usarlo**.
- Como las demás baterías: fuera del sol, en caja clara, y **nunca cargarla dentro de la máquina** (01 §3.4).

### A8 · Alimentación de la zona de tolva con 18650 (D10a)
Cálculo con las cifras de 01 §3.1–3.2 (celda 3000 mAh, 85 % aprovechable, nodo de cámara 1,11 W, driver del
LED al 90 %, jornada de 12 h). **Ningún documento indica la potencia del LED**, así que se calcula para 1, 3 y
5 W.

**LED encendido todo el tiempo:**

| LED | Cámara + LED en el paquete actual (2 celdas) | Celdas para 12 h (cámara + LED) | O paquete aparte solo para el LED |
|---|---|---|---|
| 1 W | ≈ 8,5 h | 3 | 2 |
| 3 W | ≈ 4,2 h | 6 | 5 |
| 5 W | ≈ 2,8 h | 9 | 8 |

**LED pulsado** —encendido solo alrededor de cada foto; `CAM04` toma una cada 2 s—, con 150–300 ms de
encendido por foto:

| LED | 2 celdas (actual) | **3 celdas** | 4 celdas |
|---|---|---|---|
| 1 W | 14,8–15,8 h | 22–24 h | 30–32 h |
| 3 W | 11,7–13,9 h | **17,6–20,8 h** | 23–28 h |
| 5 W | 9,7–12,4 h | **14,6–18,5 h** | 19–25 h |

**Recomendación (no decisión):** LED **pulsado**, encendido y apagado por el propio ESP32 de `CAM04` con un
transistor, compartiendo el paquete de la cámara ampliado a **3 celdas**. Coste: 2 celdas más en total (una
por cada juego de paquetes) y un portapilas de 3.

Condiciones técnicas:
1. **Sincronía.** El driver de cámara del ESP32 guarda cuadros en memoria: si se enciende el LED y se captura
   de inmediato, la foto puede ser de antes del encendido. Encender, **descartar uno o dos cuadros**, capturar
   y apagar. Verificarlo en el banco: todas las fotos guardadas deben salir iluminadas.
2. **Exposición manual**, que 02 §4.4 ya fija para `CAM04`: es la que hace compatible el pulso con fotos
   comparables.
3. **Luz ambiente: resuelta, y a favor.** El equipo confirmó que **las tolvas van cubiertas** (C31). Es el
   caso favorable: el LED no compite con el sol, solo tiene que iluminar un recinto oscuro, de modo que hace
   falta **menos** potencia, no más. Estimación —con supuestos de 100 lm/W, 60 % de aprovechamiento y
   reflectancia del grano de 0,35—:

   | LED | Zona de ~0,35 m² (cámara a ~0,7 m) | Zona de ~0,9 m² (cámara a ~1,2 m) |
   |---|---|---|
   | 3 W | ≈ 510 lux → ~1/115 s a ISO 100 | ≈ 200 lux → ~1/45 s |
   | 5 W | ≈ 860 lux → ~1/190 s | ≈ 330 lux → ~1/75 s |
   | 10 W | ≈ 1700 lux → ~1/380 s | ≈ 670 lux → ~1/150 s |

   Como la cámara y la superficie vibran juntas, exposiciones de 1/100–1/200 s bastan. **5 W de pico ya
   sobran; 10 W dan margen de sobra.** Con el pulso, 10 W de pico cuestan lo mismo en batería que 5 W
   continuos a la mitad del ciclo: 3 celdas dan ~15 h con 10 W a 150 ms por foto. La cifra final se fija en
   el banco, con la cámara, la distancia real y la exposición manual.

6. **Montar el LED separado de la cámara, iluminando en oblicuo.** Dentro de una tolva cubierta hay mucho
   polvo: un LED junto al objetivo devuelve luz dispersa —el efecto de los faros en la niebla— y refleja
   brillos en el grano. La luz lateral además realza la textura, que es lo que distingue grano de paja y
   cascarilla.

7. **La luz cambia al llenarse la tolva.** Con el LED fijo, la superficie sube y se acerca: entre 1,5 m y
   0,5 m la iluminación se multiplica por nueve (más de tres pasos de diafragma). Con exposición manual fija,
   las fotos del final de la tolvada saldrán mucho más claras que las del principio. Es la misma variable que
   ya obliga a acotar el análisis por nivel de llenado (H3), ahora por dos motivos: resolución y brillo. La
   referencia de color servirá además para detectar la pérdida de luz por polvo acumulado sobre el LED.
4. **No colgar el LED del elevador de 5 V del nodo**, dimensionado solo para la cámara: usar un driver propio
   alimentado del paquete. Comprobar que la placa de protección 1S admite el pico de corriente del LED
   (≈ 1,5 A con un LED de 5 W).
5. **El paquete, fuera de la tolva.** Solo la cámara y el LED van dentro. Afuera, a la sombra y en caja clara
   (01 §3.4). Dentro hay polvo de grano, que es combustible, y grano que puede golpear o enterrar la caja. En
   muchas cosechadoras el motor queda detrás o debajo de la tolva: **ver dónde está en la máquina** y alejar el
   paquete de esa fuente de calor.

*A5 eliminada por indicación del equipo.*

### Hallazgos de la revisión de arquitectura todavía abiertos
**H3** nivel de llenado de la tolva · **H7** energía del LED (D10a) · **H8** anotación y ground truth — el
mayor riesgo de calendario · **E1–E7** errores menores.
*Resueltos: H1 por C22; H2 por C28 (prueba decidida); H4 por C27; H5 por C23/C24; H6 por C26; H9 por C25;
H10 por C29.*

---

## 8. Índice de archivos del proyecto

| Archivo | Estatus |
|---|---|
| `00_ESTADO_ACTUAL_PROYECTO.md` | **Fuente de verdad** |
| `01_ANALISIS_TECNICO_v2.md` | Histórico |
| `02_BIBLIOGRAFIA_CANDIDATA_v1.md` | Banco de candidatos |
| `03_INVESTIGACION_CORTE_v1.md` | Parcialmente adoptado (C19, C20); resto histórico |
| `04_REVISION_ARQUITECTURA_v1.md` | Revisión de la arquitectura v1.0; decisiones en este archivo |
| `Actualizacion/01–03.md` | **Arquitectura adoptada, versión 1.1** (24-sep): incorpora C22–C33 y las correcciones E1–E7 |
| `Actualizacion/01–03.pdf` | **Al día**, regenerados desde los `.md` el 24-sep con `Actualizacion/generar_pdf.py` |
| `Actualizacion/generar_pdf.py` | Genera los PDF desde los `.md`. Ejecutar tras cada edición: `python generar_pdf.py` |
| `Actualizacion/diagramas/` | Fuentes `.mmd` y PNG de los seis diagramas. `01-mapa-fisico` se regeneró con mermaid-cli para reflejar la batería propia de la Pi |
| Copias `.docx` en la raíz | **Desactualizadas** (versión 1.0). Los PDF ya no dependen de ellas: se pueden borrar o rehacer |
| `historico/` | Versiones anteriores de este archivo |
| `Propuesta_Proyecto_de_Grado_v2.docx` | **Congelado** |
| `build_propuesta_v2.js` | No ejecutar por ahora |

---

## 9. Próximo paso

Fijar la potencia del LED en el banco (**D10a**) y aprobar el paquete 3S5P de cabina (**D10b + D11**).
Después, el pendiente de mayor riesgo es **H8**: definir cómo se anotarán y validarán las tres tareas
(acame, post-corte, tolva).
