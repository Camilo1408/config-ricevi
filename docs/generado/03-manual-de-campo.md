# Manual de campo

Lo que hay que hacer, en orden, para capturar una jornada de dataset con el
sistema montado en la cosechadora. Está escrito para leerse en el campo, no en
el escritorio.

*Versión 1.2 — 22 de octubre de 2026. Los nodos van con pilas AA y sin microSD,
la central con una batería LiFePO4 de 12 V y el punto de acceso es un router
Tenda N301. La versión 1.1 añadió la prueba de los ultrasónicos (§7.1) y la
definición de grupo (§5).*

---

## 1 · Qué es cada cosa

| Equipo | Dónde va | Qué hace |
|---|---|---|
| `RPI01` | **Cabina** | Recibe, verifica, guarda, infiere y sirve la pantalla. Lleva su propia batería LiFePO4 de 12 V |
| `AP01` | Fuera, cerca del cabezal | El Wi-Fi: un router Tenda N301. Va a la Pi por cable Ethernet y se alimenta a 9 V de la misma batería de cabina |
| `CAM01` | Frente al cabezal | Cultivo antes del corte |
| `CAM02` `CAM03` | Detrás del cabezal, izq. y der. | Resultado del corte |
| `CAM04` | Dentro de la tolva | Superficie del material acumulado. El LED lleva su propia batería de 9 V, fuera de la tolva |
| `NH01` | Eje del molinete | Pulsos → rpm |
| `NH02` | Rueda instrumentada | Pulsos → velocidad |
| `NU01` `NU02` | Extremos del cabezal | Distancia al suelo → altura |
| `HMI01` | Cabina | Un navegador apuntando a `http://192.168.40.2:8000` |

---

## 2 · Antes de salir (taller)

### 2.1 Una sola vez, al recibir el hardware

| # | Paso | Cómo se comprueba |
|---|---|---|
| 1 | Ejecutar el ejemplo de cámara del fabricante en **las cuatro** placas | Las cuatro dan imagen |
| 2 | Anotar las ocho MAC en `config/censo.py` | `python config/censo.py` sin avisos de MAC |
| 3 | Configurar el punto de acceso | Ver `config/red/router.md` |
| 4 | Crear las diez reservas DHCP | Cada equipo recibe la IP esperada |
| 5 | Generar los tokens | `python herramientas/generar_tokens.py` |
| 6 | Instalar la central en la Pi | `herramientas/instalar_pi.sh` termina en verde |
| 7 | Grabar y provisionar los ocho nodos, **de uno en uno** | LED verde parpadeando en cada uno |
| 8 | **Pegar la etiqueta física en cada caja** | Las ocho etiquetadas |
| 9 | Medir las cuatro constantes de `config/calibracion.json` | Ver §7 |
| 10 | Ajustar en el banco la ventana del LED de la tolva, cuando el firmware lo maneje, con la batería de 9 V llena y casi vacía | La foto sale bien expuesta y **todas** las guardadas salen iluminadas |
| 11 | Cargar la batería LiFePO4 de la central y las pilas de los ocho nodos | Batería llena y con fusible; cada juego de pilas por encima de 4,5 V, idealmente recién cargado (≈ 5,6 V) |

**El paso 7 es de uno en uno a propósito.** Si se encienden los ocho a la vez y
algo falla, hay ocho sospechosos. Añadiéndolos en orden, el nodo que rompe el
sistema es el último que se encendió.

### 2.2 Cada vez, antes de arrancar el motor

```bash
python herramientas/verificar_campo.py
```

Tiene que terminar sin fallos. Si hay avisos de calibración, se puede capturar
igual: lo que no se podrá es publicar las magnitudes derivadas.

---

## 3 · La jornada

### 3.1 Arrancar

```bash
sudo systemctl start ricevi-central
journalctl -u ricevi-central -f
```

Y abrir `http://192.168.40.2:8000` en la tablet.

Los nodos se registran solos en cuanto encuentran la central. No hay que
encenderlos en ningún orden concreto.

### 3.2 Qué debe verse en la pantalla

| Indicador | Bien |
|---|---|
| Cabecera | `FASE DE DATASET — capturando, sin diagnóstico` |
| Nodos | Ocho puntos verdes |
| RTT | Por debajo de 30 ms en todos |
| Frames | Subiendo, en las cuatro cámaras |
| Muestras | Subiendo, en los cuatro sensores |
| Temperatura | Por debajo de 75 °C |
| Disco libre | Suficiente para las horas que quedan |

**Que las cuatro cámaras digan «sin modelo» es lo correcto** durante toda la
fase de dataset. Significa que el sistema está capturando y que todavía no
diagnostica, que es exactamente la verdad.

### 3.3 Qué hacer si algo se pone rojo

| Qué se ve | Qué significa | Qué hacer |
|---|---|---|
| Un nodo en rojo | Perdió el enlace | Mirar su LED. Si está ámbar, es el AP; si rojo, es Wi-Fi |
| `SIN DISCO` en la cabecera | El disco llegó a la reserva | **Parar y descargar.** No se está capturando |
| Temperatura en `caliente` o peor | La Pi se está estrangulando | Normal en cabina sin aire. La captura no se detiene |
| Turnos denegados subiendo | El enlace no da abasto | Mirar la cobertura del AP |
| Muchas muestras nulas en un sensor | El sensor, no la placa | `GET /api/sensores/salud` dice el código |
| Huecos en los frames de una cámara | Se cortó el enlace. Sin microSD, esos frames se perdieron | Mirar la cobertura del AP y anotar el intervalo |
| Aviso de batería en una cámara | Las pilas se acercan al límite: unas 11 h estimadas | Parar entre tolvadas y cambiar el juego |

### 3.4 Registrar lo que pasa

Cada vez que el operario cambia un ajuste —altura, velocidad, molinete— hay que
anotarlo. Sin eso, el dataset tiene variación que nadie puede explicar.

Y **hay un tiempo muerto tras cada cambio**: la máquina está en transición y el
material que sale todavía corresponde al ajuste anterior. Unos 15 s para el
corte; varios minutos para la tolva.

---

## 4 · Al terminar la jornada

```bash
sudo systemctl stop ricevi-central
sudo shutdown -h now
```

**Esperar a que la Pi se apague del todo antes de desconectar la batería.** Y
lo mismo si hay que cambiarla a mitad de jornada: parar, apagar, cambiar y
volver a arrancar. **Los nodos no llevan microSD:** mientras la central está
apagada, los frames que capturan se pierden. Por eso el cambio se hace con la
máquina parada, entre tolvadas, y abre una sesión nueva al volver (§5).

Ya con la Pi encendida otra vez, o en el taller:

```bash
./herramientas/respaldo_jornada.sh /media/disco-externo
```

El script copia, exporta las tablas a CSV y **verifica los hashes uno a uno**
contra lo que la central registró al recibir cada frame. Si la verificación
falla, **no borres el original**.

> **Haz la segunda copia en otro soporte.** Una sola copia no es un respaldo, y
> una jornada de cosecha no se repite: esa combinación de lote, variedad,
> humedad y hora no vuelve.

---

## 5 · Preparar el dataset para entrenar

```bash
python herramientas/exportar_dataset.py --sesion R003 --destino /media/dataset
```

Produce las imágenes, un manifiesto con todo el contexto operativo de cada
frame, y un `RESUMEN.md` que dice qué hay y **qué no se puede publicar**.

**La columna `grupo` del manifiesto es la más importante.** Dividir
entrenamiento, validación y prueba al azar sobre estas filas da métricas
infladas y falsas: dos frames consecutivos de la misma pasada son casi la misma
imagen, y si uno cae en entrenamiento y otro en prueba, el modelo ya ha visto la
respuesta. La división va por grupo.

**Un grupo es una jornada, identificada por su fecha.** No la pasada: dos
pasadas del mismo lote, con minutos de diferencia, la misma luz y el mismo
cultivo, siguen siendo casi la misma imagen. Y tampoco el `session_id`: si la
central se reinicia a mitad del día —al cambiar la batería, por ejemplo— abre
una sesión nueva y partiría la jornada entre entrenamiento y prueba.

De ahí una consecuencia para planear las salidas: hacen falta **al menos dos o
tres jornadas de captura**, porque una entera se reserva para la prueba y no
puede aparecer en el entrenamiento. Si además son en lotes distintos, mejor: el
examen se parece menos todavía a la práctica.

---

## 6 · Pasar a la fase de inferencia

Cuando existan los pesos:

1. Copiarlos a `modelos/pesos/` con su `manifiesto.json`.
2. `sudo systemctl edit ricevi-central` → `Environment=RICEVI_MODELO=ncnn`
3. `sudo systemctl restart ricevi-central`

La cabecera del HMI pasará de «FASE DE DATASET» al nombre y versión del modelo,
y los porcentajes empezarán a aparecer.

**Si el modelo no carga —faltan pesos, falta la biblioteca, el hash no cuadra—
la central vuelve sola a la fase de dataset y lo registra como evento.** Es
deliberado: perder el diagnóstico es aceptable, perder la jornada de captura no.

---

## 7 · Las cuatro constantes que hay que medir con un metro

El sistema captura dataset válido sin ellas, porque guarda siempre la magnitud
cruda. Pero hasta que estén medidas y anotadas en `config/calibracion.json`,
**`reel_rpm`, `wheel_speed`, `header_height` y `reel_index` no se pueden
publicar**.

| Constante | Cómo se mide |
|---|---|
| `circunferencia_rueda_m` | Marcar el neumático, avanzar **diez vueltas en campo y con carga**, medir y dividir. Con la máquina vacía o sobre asfalto sale otro número |
| `radio_molinete_m` | Del centro del eje a la **punta de la púa**, máquina parada y bloqueada |
| `offset_b_mm` de `US01` | De la cara del sensor al plano de la cuchilla, con el cabezal en el suelo |
| `offset_b_mm` de `US02` | Igual, lado derecho. **No asumir que es el mismo número**: el montaje rara vez es simétrico |

Al medir una: poner el valor, poner su `__medido` en `true`, rellenar
`medido_por` y `medido_utc`, y **subir `CENSO_VERSION`** en `config/censo.py`.

### 7.1 La prueba de los ultrasónicos

Medir el `offset_b_mm` responde a «¿a qué distancia está la cuchilla del
sensor?». Queda otra pregunta, que ninguna calibración responde: **¿la distancia
que mide el sensor en el lote llega de verdad hasta el suelo?**

El sensor mide hasta lo primero en que rebota su sonido. Si el eco vuelve de las
puntas del rastrojo —que quedan justo a la altura de la cuchilla—, la altura
calculada sale cerca de cero; si vuelve de hojas a media altura, sale un valor
intermedio. En los tres casos el número es estable y está en rango, así que
entra con calidad `buena` y nadie lo nota: es exactamente el error silencioso
que la regla del nulo quiere evitar.

La prueba es media hora en la primera salida, solo con la cinta:

| # | Paso |
|---|---|
| 1 | Máquina detenida **dentro del lote y sobre rastrojo**, no en el patio |
| 2 | Medir con cinta la altura real de la cuchilla al suelo, justo debajo de cada sensor |
| 3 | Anotar lo que reporta el sistema para `NU01` y `NU02` |
| 4 | Repetir a tres o cuatro alturas distintas del cabezal |

Cómo se lee el resultado:

| Lo que sale | Qué significa |
|---|---|
| Coincide con la cinta (±2–3 cm) a todas las alturas | El sensor ve el suelo. `header_height` se puede publicar |
| Sale cerca de cero, o apenas cambia al subir el cabezal | Está viendo el rastrojo. **No se publica** |
| Coincide a unas alturas y a otras no | Depende de lo que haya debajo: queda como dato de contexto |

Si la prueba falla no se pierde nada del dataset: la distancia cruda se sigue
guardando, y `header_height` queda como contexto no publicable, igual que una
constante sin medir.

---

## 8 · Las reglas que no se negocian

1. **La captura tiene prioridad sobre el diagnóstico.** Cuando algo se satura se
   pierde diagnóstico, nunca dataset.
2. **Los JPEG son los octetos recibidos, byte a byte.** Nunca se recomprimen.
3. **Cuando no hay medida, el valor es nulo.** Nunca cero, nunca el último valor
   conocido.
4. **Sin modelo, la pantalla dice «sin modelo».** Nunca un número.
5. **La identidad de un nodo es su `node_id`, no su IP.**
6. **Nada se da por instalado hasta que un programa lo demuestra.**
7. **Nada se conecta a la instalación eléctrica de la cosechadora.** Ni la
   central. Todo va con batería propia.
8. **La Pi se apaga antes de quitarle la batería.**

---

## 9 · Diagnóstico rápido

```bash
# ¿vive la central?
curl -s 192.168.40.2:8000/salud

# ¿quién está conectado y cómo?
curl -s 192.168.40.2:8000/api/status | python -m json.tool

# ¿qué le pasa a un sensor?
curl -s 192.168.40.2:8000/api/sensores/salud | python -m json.tool

# ¿se están perdiendo frames de una cámara?
curl -s 192.168.40.2:8000/api/huecos/CAM02

# ¿qué ha pasado hoy?
journalctl -u ricevi-central --since today | grep -E "WARNING|ERROR"

# eventos registrados
sqlite3 /datos/ricevi/ricevi.db \
  "SELECT utc, node_id, tipo, detalle FROM eventos ORDER BY id DESC LIMIT 30;"
```

### Trazar un número hasta sus octetos

```sql
SELECT r.porcentaje, r.modelo, r.modelo_version,
       f.ruta, f.sha256, f.capture_utc,
       e.wheel_speed_mps, e.altura_izq_mm, e.reel_index, e.ri_estado
FROM resultados r
JOIN frames f USING (frame_id)
LEFT JOIN estado_maquina e
       ON ABS(e.session_us - f.capture_session_us) < 100000
WHERE r.frame_id = 'M01-R003-CAM02-B03-000036';
```

Y comprobar que el archivo no se alteró:

```bash
sha256sum /datos/ricevi/frames/R003/CAM02/M01-R003-CAM02-B03-000036.jpg
```

Si el hash no coincide con el de la base, **ese frame no entra al dataset**. No
se arregla ni se acepta con una nota: se marca y se excluye.
