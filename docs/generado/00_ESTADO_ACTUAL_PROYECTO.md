# ESTADO ACTUAL DEL PROYECTO — FUENTE DE VERDAD

**Última actualización:** 24 de octubre de 2026
**Versión anterior:** `historico/00_ESTADO_ACTUAL_PROYECTO_2026-09-21c.md` (y las que esa cita)
**Estatus:** prototipo en banco, fase 1 (dataset). Arquitectura **v1.3**: siete nodos ESP32 y la
velocidad de avance por **GPS USB**. Próximo hito: montaje completo y primera salida a campo a mediados
de noviembre (§9)

> Este archivo prevalece sobre cualquier otro documento del proyecto.
> `Propuesta_Proyecto_de_Grado_v2.docx` sigue **congelado**; cuando se reabra, su título, pregunta,
> objetivos y delimitación conceptual deben revisarse por C22, C25 y C34.

### Qué cambió en esta versión

1. **Hardware de octubre (v1.2, 22-oct).** Nodos de sensor en ESP32-C6, ultrasónico RCWL-1655, Hall
   HW-477, 4 pilas AA Ni-MH por nodo, nodos sin microSD, central con batería LiFePO4 de 12 V y router
   Tenda N301 a 9 V, LED de tolva con batería propia de 9 V. Eran decisiones dichas en chat que no
   estaban en este archivo: ahora son **C37–C41**, y cierran **D10b + D11**.
2. **Velocidad por GPS (v1.3, 22–23-oct).** Sale el Hall de rueda `NH02`: la velocidad la mide un GPS
   USB VK-162 en la Pi, con la antena en el techo de la cabina. **C34–C36**; **C24 queda reemplazada**.
   Código, configuración, guías y diagramas actualizados en el repositorio.
3. **Documentos.** Este archivo pasa al repositorio (`config-ricevi/docs/`), junto a los capítulos 01–03,
   para que la fuente de verdad viaje con el código.
4. **Primera prueba del GPS (24-oct).** El VK-162 ya está en la Pi: la central lo encuentra sola y da
   solución al aire libre. Cierra **T4**; los resultados están en §7-A9. Ese día se corrigió también la
   numeración de sesiones, que sin cámaras repetía el `session_id` en cada reinicio. La sesión **R007**
   de la mesa mezcla varias corridas y no debe usarse.

---

## A. Arquitectura adoptada — RiceVi v1.3

**Documentos de referencia:** `docs/01-arquitectura-hardware`, `02-configuracion-sistema`,
`03-manual-de-campo`, versión 1.3, en el repositorio https://github.com/Camilo1408/config-ricevi
(carpeta local `PROYECTO/config-ricevi-campo/`; copia de los `.md` en `PROYECTO/docs/`). Los `.docx` y
`.pdf` de igual contenido están en `docs/entregables/`.

| Subsistema | Equipo | Observa | Produce |
|---|---|---|---|
| PRE-CORTE | `CAM01` (GOOUUU ESP32-S3-CAM, OV3660) frente al cabezal | Cultivo antes de entrar al cabezal | Clase ordinal de acame: erecto · moderado · severo |
| POST-CORTE | `CAM02`, `CAM03`, detrás del cabezal, izq. y der. | Franja recién cortada | Fracción visual de material útil visible tras el paso del cabezal |
| TOLVA | `CAM04` dentro de la tolva, con LED pulsado y referencia de color | Superficie del material acumulado | Fracción visual de material no grano |
| Operación | `NH01` (ESP32-C6 + Hall HW-477, eje del molinete), `NU01`/`NU02` (ESP32-C6 + RCWL-1655, parte baja del cabezal), `GPS01` (VK-162 por USB en la Pi, antena en el techo de la cabina) | Molinete, avance, distancia al suelo | `reel_rpm`, `ground_speed` (medida), `header_height` (sin validar), `reel_index` |
| Central | `RPI01` Raspberry Pi 5 8 GB, arranca desde SSD NVMe de 128 GB, en cabina, con batería LiFePO4 12 V propia (C26, C40); `AP01` Tenda N301 fuera, por Ethernet; `HMI01` navegador | — | Ingesta, verificación, almacenamiento; inferencia y sugerencias en fase 2 |

**Siete ESP32** (cuatro cámaras y tres sensores) más el GPS, que no es un nodo: va por USB a la central.

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

**No se afirmará en la tesis:** reducción de X kg/ha · que un ajuste causa una pérdida · haber encontrado el
ajuste óptimo · control de la máquina · que seguir las sugerencias reduce pérdidas.

---

## 2. Decisiones CERRADAS

| # | Decisión | Consecuencia operativa |
|---|---|---|
| **C1** | **Diseño base observacional** | Se registran las condiciones normales de operación y los cambios que hace el operario, con tiempo muerto tras cada uno |
| **C2** | **Vocabulario no causal** | «Asociación», «comportamiento bajo determinada condición», «desempeño estratificado» |
| **C3** | **Humedad del grano fuera del alcance** | No se reintroduce sin que el equipo reabra la decisión |
| **C4** | **Núcleo de limpieza = superficie del material acumulado en la tolva** (`CAM04`) | Riesgos de medida en `04_REVISION` H3 |
| **C5** | **Vista B (descarga) no es requisito** | Extensión futura |
| **C6** | **La tolva no cuantifica pérdida por descarga** | Estudia la composición de lo que llega a la tolva |
| **C7** | **Dataset multimodal ≠ modelo multimodal** | Modelos solo visuales; variables físicas como contexto |
| **C8** | **Sensores propios para las variables de corte** | La lectura manual del monitor no da series continuas sincronizadas con las imágenes, y el bus CAN de una máquina ajena se descartó |
| **C9** | **Jerarquía monitor → externo → propio** | Vigente solo para variables nuevas |
| **C10** | **Norma de verificación bibliográfica** (§6) | Permanente |
| **C11** | **Nunca afirmar ausencia mundial de antecedentes** | Permanente |
| **C12** | **`02_BIBLIOGRAFIA_CANDIDATA_v1.md` es banco de candidatos** | Nada aprobado hasta que el equipo lo lea |
| **C13** | **`.docx` v2 congelado** | Ver nota de cabecera |
| **C14** | **Orden de trabajo** | Corte (pre y post) → Limpieza (tolva) → Dataset → documento |
| **C15** | **Arquitectura RiceVi adoptada** (§A) | Vigente en su versión 1.3 |
| **C16** | **Dos fases: dataset por defecto, inferencia opcional** | Sin modelo, el HMI muestra «sin modelo» |
| **C17** | **Regla del nulo** | Sin medida, el valor es nulo; muestra nula con calidad `buena` se rechaza. Vale también para el GPS sin solución (`sin_fix`) |
| **C18** | **Se guardan las magnitudes crudas** | Permiten recalcular la campaña. Del GPS se guarda la velocidad cruda y la filtrada |
| **C19** | **Acame: clasificación ordinal de 3 clases** | erecto · moderado · severo |
| **C20** | **Reel index calculado en la central** | K = ωR/V, con R al extremo de la púa y V la velocidad del GPS. La fórmula con unidades ya está en 01 §5.3 y en `central/app/fusion.py` |
| **C21** | **Partición por `grupo`**, nunca al azar sobre frames | `grupo` = fecha de la jornada (C29). `exportar_dataset.py` ya lo aplica |
| **C22** | **La trilla sale del alcance obligatorio** *(21-sep)* | Trilla solo si queda tiempo, etiquetando `grano_partido` sobre las fotos de `CAM04`. **Al reabrir el `.docx`: revisar título, pregunta y objetivos** |
| **C23** | **La cosechadora es de ruedas** | Ya no condiciona la medida de velocidad (C34) |
| ~~**C24**~~ | ~~Sin GNSS; velocidad estimada por `NH02`~~ | **Reemplazada por C34 (22-oct)** |
| **C25** | **Se mantienen las «sugerencias» al operario** | Solo en fase 2, cualitativas y desde reglas documentadas (§7-A6). **Al reabrir el `.docx`: revisar la delimitación de «diagnóstico»** |
| **C26** | **Nada se conecta a la máquina** | Sin señal de contacto; apagado manual (manual de campo §4) |
| **C27** | **Sin línea base precosecha** | El indicador de post-corte es **«material útil visible tras el paso del cabezal»**, nunca «pérdida de cabezal» |
| **C28** | **Prueba de validación de los ultrasónicos** | En la primera salida, máquina detenida en el lote sobre rastrojo, cinta a 3–4 alturas. `header_height` solo se publica si coincide (±2–3 cm) |
| **C29** | **`grupo` = fecha de la jornada** | Jornadas enteras reservadas para prueba; mínimo 2–3 jornadas de captura |
| **C30** | **La Pi no usa powerbank** | Batería de mayor voltaje + convertidor a 5 V / 5 A. Concretada en C40 |
| **C31** | **Las tolvas van cubiertas** | Caso favorable para `CAM04`: el LED no compite con el sol |
| **C32** | **LED de tolva pulsado, sincronizado con cada foto** | El encendido lo hace el ESP32 de `CAM04` con un MOSFET. La fuente cambió en C41 |
| ~~**C33**~~ | ~~Fuente de cabina con paquetes de 18650~~ | **Reemplazada por C40** |
| **C34** | **Velocidad de avance por GPS USB** *(22-oct)* | Receptor VK-162 (u-blox 7) en un USB de la Pi, antena magnética en el **techo de la cabina**. Velocidad Doppler sobre el suelo, sin patinaje ni constante que medir: deja de ser «estimada». Se lee directamente (sin `gpsd`), una solución por segundo, filtrada 3 s con umbral de reposo 0,2 m/s. Validación con tramo medido (manual de campo §7.2) |
| **C35** | **La posición del GPS no se guarda** *(22-oct)* | La central descarta latitud y longitud al leer la trama: el GPS solo mide la velocidad, y la ubicación de los lotes es dato reservado del productor |
| **C36** | **Siete nodos ESP32** *(22-oct)* | Sale `NH02` (Hall de rueda: agua y lodo). `NH01` (molinete) y `NU01`/`NU02` (ultrasónicos, parte baja del cabezal) son nodos separados. La placa C6 de `NH02` (MAC `F0:F5:BD:0E:D7:30`) queda de repuesto y su IP `.22`, libre |
| **C37** | **Nodos de sensor en ESP32-C6 DevKitC; ultrasónico RCWL-1655 (Trig/Echo); Hall HW-477** *(oct)* | Pines: Hall GPIO10; ultrasónico Trig GPIO11 · Echo GPIO10; batería GPIO1; LED GPIO8. Partición «Huge APP». La señal del Hall se toma de la pata OUT del A3144 (el pin S lleva el LED en serie) |
| **C38** | **4 pilas AA Ni-MH en serie por nodo, directo al pin de 5 V** *(5-oct)* | Sin elevador ni placa de protección. Umbrales 4,50 V aviso / 4,35 V crítico, divisor 150k/100k en GPIO1 (aún sin montar: batería nula). Cámaras ≈ 11 h estimadas |
| **C39** | **Los nodos no llevan microSD** *(5-oct)* | `RICEVI_SD_HABILITADA 0`. Si la Pi o el Wi-Fi caen, los frames de ese intervalo se pierden (LED ámbar) |
| **C40** | **Central con LiFePO4 12,8 V 12 Ah; router Tenda N301 a 9 V** *(3–5-oct)* | Cierra **D10b + D11**. Convertidor 12→5 V USB-C 5 A para la Pi (`usb_max_current_enable=1`) y 12→9 V para el router; fusibles por rama; cargador LiFePO4 14,6 V 2 A. ≈ 12 h estimadas en fase 1 |
| **C41** | **LED de tolva = módulo de inyección de 12 V con batería propia de 9 V (PP3 250 mAh)** *(15-oct)* | Sin driver ni elevador; MOSFET IRLZ44N en G14 con 200 Ω y 100 kΩ, fusible de 1 A. A 9 V da menos luz y baja con la descarga; el mismo cableado admite luego 12 V |

---

## 3. Decisiones PROVISIONALES

| # | Decisión provisional | Estado | Qué falta |
|---|---|---|---|
| **P1** | **Dataset híbrido** con partición de prueba real y sin fuga | Preferida por el equipo | Validación con el director |
| **P2** | **Dataset sincronizado visión + variables operativas** | Materializado por la arquitectura | Anotar a mano, por evento, los ajustes de limpieza que muestre el monitor (ventilador, zarandas), conforme a C9 |
| **P4** | **Altura de cabezal** por ultrasonido | Instrumentada, **sin validar** | Prueba de C28 |
| **P6** | **Posición exacta de `CAM01`** | Sin especificar | Documentar altura, orientación y si el molinete entra en el encuadre |
| **P7** | **Velocidad del ventilador** | Provisional | Bloque Limpieza (A2) |
| **P8** | **Velocidad por GPS publicable** | Instrumentada (C34), **sin validar** | Tramo medido de manual de campo §7.2, sobre todo a paso lento |

---

## 4. Decisiones y tareas PENDIENTES

| # | Pendiente | Estado | Siguiente paso |
|---|---|---|---|
| **D10a** | **Luz del LED de tolva** | Fuente cerrada (C41); potencia real del módulo sin confirmar (≈ 1–1,5 W) | Banco con la cámara, la distancia real y exposición manual, con la 9 V llena y casi vacía |
| **T1** | **LED de tolva en el firmware** | `camara.ino` todavía no lo maneja | Encender, descartar 1–2 cuadros, capturar, apagar; ventana de 150–300 ms en el plan |
| **T2** | **Divisor de batería en las placas** | `divisor_montado: False` en el censo | Soldarlo en las perforadas y pasar a `True` |
| **T3** | **MAC de `NU01` y `NU02`** | Faltan en el censo | Provisionarlos y crear sus reservas DHCP |
| **T5** | **Precio total de la lista de materiales** | 01 §9 dice *por confirmar* | Recalcular con la cotización del equipo (`Desktop/Cotizacion_depurado.xlsx`) |
| **T6** | **Cableado del Hall** | Funciona en protoboard con 10 kΩ | Confirmar si el cable OUT→col. 12 sigue haciendo falta y actualizar el diagrama de la perforada |
| **T7** | **Capacidad real de las pilas AA** | La caja dice 3600 mAh; se calcula con 2600 | Descarga completa de un juego |

**Heredadas:**

| # | Pendiente | Estado |
|---|---|---|
| **X1** | Terminología de la «altura de corte» | La arquitectura mide `header_height`. Si la tesis habla de altura de corte, revisar `03_CORTE` §7 (longitud de rastrojo, ISO 6689) |
| **X11** | Instrumentar el ventilador | Bloque Limpieza |

*Resueltas o sin objeto: X2–X10; D4, D5, D9 (C28–C30); D10b + D11 (C40); H5 y A4, por C34; T4, el GPS
comprado y probado en la Pi (24-oct).*

---

## 5. Variables vigentes del proceso de CORTE

| Categoría | Variable | Fuente | Estado |
|---|---|---|---|
| Visual | Clase ordinal de acame | `CAM01` + anotación | Vigente (C19) |
| Visual | Material útil visible tras el paso del cabezal | `CAM02`, `CAM03` + segmentación | Vigente; definición de la clase pendiente de OE1 (`04_REVISION` H4) |
| Operativa | RPM del molinete | `NH01` | Vigente; falta medir `pulsos_por_vuelta` y `radio_molinete_m` |
| Operativa | Velocidad de avance, **medida sobre el suelo** | `GPS01` (C34) | Vigente; validación pendiente (P8) |
| Operativa | Altura de cabezal, izq. y der. | `NU01`, `NU02` | **Sin validar**; prueba decidida (C28) |
| Derivada | Reel index | Central | Vigente (C20) |

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
No aplica: la velocidad viene del GPS, independiente de las cámaras.

### A6 · Condiciones para que las «sugerencias» sean defendibles (C25)
1. Cada sugerencia sale de una **regla documentada** —manual de la máquina o literatura citada—, no de
   correlaciones halladas en los propios datos, que por C1 y C2 no permiten inferir causas.
2. **Cualitativas, no numéricas**: «considere aumentar el reel index», no «ponga K = 1,7».
3. La tesis **no evalúa** si seguir las sugerencias reduce pérdidas; eso requeriría un experimento controlado.
4. El operario decide; el sistema no acciona nada.

### A7 · Energía: lo que queda por medir
Las autonomías (≈ 11 h cámaras, ≈ 28–29 h sensores, ≈ 12 h central) son **cálculos, no medidas**
(01 §10). Las cámaras quedan justas para una jornada larga: si pasa de diez horas, se cambian pilas entre
tolvadas. El GPS añade ≈ 0,25 W a la central (estimado). El análisis de opciones 18650/3S5P quedó en el
histórico.

### A8 · Iluminación de la tolva
Siguen valiendo las condiciones de la versión anterior: **sincronía** (descartar 1–2 cuadros tras
encender), **exposición manual** en `CAM04`, LED **en oblicuo y separado** de la cámara por el polvo,
**batería fuera de la tolva** y lejos del motor, y la **luz cambia con el llenado** (entre 1,5 m y 0,5 m la
iluminación se multiplica por nueve), lo que refuerza acotar el análisis por nivel de llenado (H3).

### A9 · GPS
1. **Necesita cielo.** Bajo árboles o junto a galpones pierde la solución y la velocidad queda nula; arranque
   en frío de 1–2 min, por eso `verificar_campo.py` lo comprueba al aire libre.
2. **A paso lento el Doppler tiembla.** La filtrada promedia 3 s (retraso ≈ 1,5 s) y publica 0 bajo 0,2 m/s.
   Hay que validar la velocidad de trabajo más baja (P8).
3. **Puerto.** En la Pi, la ESP32-C6 y el GPS son ambos `ttyACM`: la central busca el GPS por
   `/dev/serial/by-id/` y la provisión de nodos debe elegir el puerto por nombre.
4. **El tiempo GPS no se usa todavía para la hora civil.** Sería una mejora para `utc_quality` sin RTC ni
   Internet; hoy la hora sigue saliendo del RTC.
5. **Primera prueba (24-oct), en mesa y al aire libre.** Solución desde el primer minuto, una por segundo,
   con solo 5 satélites y HDOP 2,6, que pasaron a 6 y 1,9 en unos diez minutos. Sin mover la antena a
   propósito, la cruda tuvo media de 0,07 m/s y picos de 0,47 m/s, y 4 de 311 filtradas pasaron el umbral
   de reposo (0,22–0,30 m/s). Al moverla a mano marcó picos de 0,86 m/s. Antes de tocar el umbral o la
   ventana hay que repetir la medida con la antena plana, lejos de la Pi y con ocho o más satélites (02 §3.4).

### Hallazgos de la revisión de arquitectura todavía abiertos
**H3** nivel de llenado de la tolva · **H7** energía y luz del LED (D10a) · **H8** anotación y ground truth —
el mayor riesgo de calendario.
*Resueltos: H1 por C22; H2 por C28; H4 por C27; H5 por C34; H6 por C26; H9 por C25; H10 por C29.*

---

## 8. Índice de archivos del proyecto

| Archivo o carpeta | Estatus |
|---|---|
| `config-ricevi-campo/` = repo `github.com/Camilo1408/config-ricevi` | **El sistema que va a la cosechadora** y su documentación vigente |
| `config-ricevi-campo/docs/00_ESTADO_ACTUAL_PROYECTO.md` | **Fuente de verdad** (este archivo; copia en `PROYECTO/docs/`) |
| `config-ricevi-campo/docs/01–03.md` | **Arquitectura v1.3** (23-oct, revisada el 24). `.docx`/`.pdf` en `docs/entregables/`, generados con `herramientas/generar_documentos.ps1` |
| `config-ricevi-campo/docs/historico/` | Versiones anteriores de este archivo |
| `PROYECTO/docs/conexiones_nodos_y_central.html`, `puesta_en_marcha.html` | Páginas de cableado y de puesta en mesa (15–21-oct). **Todavía muestran `NH02`**, ahora con un aviso arriba: el cableado de `NH01`, `NU01`/`NU02` y cámaras sigue valiendo; lo de la rueda no |
| `sistema-arroz-front/` | Landing informativa (Vercel), ya con GPS y siete nodos |
| `modelos-3d/` | Soporte 3D del nodo de cámara (FreeCAD, borrador) |
| Raíz de `PROYECTO/`: `RiceVi_arquitectura_*.md/.docx/.pdf` | Histórico (septiembre) |
| `Propuesta_Proyecto_de_Grado_v2.docx` | **Congelado** |

---

## 9. Próximo paso

1. **Mesa (hasta mediados de noviembre):** LED de tolva en el firmware (T1), divisores de batería (T2),
   `NU01`/`NU02` provisionados (T3), los siete nodos en placa perforada y una segunda medida del GPS en
   reposo con la antena en su sitio (§7-A9). Cerrar con `prueba_humo.py` (52/52) y `verificar_campo.py`
   al aire libre.
2. **Primera salida:** prueba de ultrasónicos (C28), tramo medido del GPS (P8) y las cuatro constantes de
   `calibracion.json`.
3. **Captura (mediados de noviembre a diciembre):** al menos 2–3 jornadas, una reservada para prueba (C29).
4. **H8:** definir cómo se anotan y validan las tres tareas (acame, post-corte, tolva). Es el mayor riesgo de
   calendario.

