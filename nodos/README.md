# Firmware de los siete nodos

**Tres binarios, no siete.** Las cuatro cámaras corren exactamente el mismo
código y solo se distinguen por lo que tienen grabado en NVS.

| Binario | Nodos | Carpeta |
|---|---|---|
| Cámara | `CAM01` `CAM02` `CAM03` `CAM04` | `camara/` |
| Hall | `NH01` | `hall/` |
| Ultrasónico | `NU01` `NU02` | `ultrasonico/` |

La velocidad de avance no tiene firmware: la mide un GPS USB conectado a la Pi
(`central/app/gps.py`). Hasta octubre de 2026 la estimaba `NH02`, un Hall en la
rueda que corría este mismo binario; se retiró y su placa queda de repuesto.

**Por qué así.** Con un binario por nodo, copiar el equivocado convierte a
`CAM03` en `CAM02`. El síntoma sería un `409` en la central que nadie sabría
explicar, o peor: imágenes atribuidas a la vista equivocada si el conflicto no
llegara a saltar. Con la identidad en NVS, el binario es intercambiable y la
placa es la que lleva su nombre.

## Qué necesitas

| Cosa | Versión |
|---|---|
| Arduino IDE | 2.x, o `arduino-cli` |
| ESP32 Arduino core | 3.0.x o superior (necesario para `pulse_cnt.h`) |
| ArduinoJson | 7.x |
| `esp32-camera` | Viene con el core |

## Ajustes de placa

Las cámaras son **GOOUUU ESP32-S3-CAM** y los nodos de sensor (Hall y
ultrasónico) son **ESP32-C6 DevKitC**. El código es el mismo; los pines cambian
solos con `CONFIG_IDF_TARGET_ESP32C6`.

**Cámaras (ESP32-S3):**

```
Placa               ESP32S3 Dev Module
USB CDC On Boot     Disabled        <- programando por el USB-C "TTL" (CH340C) de la GOOUUU
CPU Frequency       240 MHz
Flash Size          16MB (128Mb)
PSRAM               OPI PSRAM          <- imprescindible en las cámaras
Partition Scheme    16M Flash (3MB APP/9.9MB FATFS)
Upload Speed        921600
```

**Sin `OPI PSRAM` la cámara no arranca.** El módulo N16R8 lleva PSRAM octal, y
con la opción por defecto el sistema no la inicializa: la cámara falla al
reservar el búfer del JPEG y el error no menciona la PSRAM por ninguna parte.

**Nodos de sensor (ESP32-C6 DevKitC):**

```
Placa               ESP32C6 Dev Module
Partition Scheme    Huge APP           <- con la partición por defecto, Hall y
                                          ultrasónico ocupan el 92-93 %
```

Se programan por el USB-C del conversor CH343 (en Linux aparece como
`/dev/ttyACM0`). **Si el GPS está enchufado a la Pi**, él también es un
`ttyACM`: elige el puerto de la placa en `/dev/serial/by-id/` o desconecta el GPS
mientras provisionas.

| Nodo | Pines de la ESP32-C6 |
|---|---|
| Hall | Señal en GPIO10, por un diodo 1N5819, con pull-up de 10 kΩ a 3,3 V y 100 nF a GND. El HW-477 se alimenta a 5 V |
| Ultrasónico | RCWL-1655 a 3,3 V, sin R7 (modo GPIO): Trig GPIO11, Echo GPIO10 |
| Batería | Divisor 150 kΩ / 100 kΩ al GPIO1 (aún sin montar) |
| LED de estado | RGB de la placa, GPIO8 |

**Comprueba la pull-up del Hall con el multímetro.** Una resistencia de 10 Ω
(marrón-negro-negro) en lugar de 10 kΩ deja la señal clavada en unos 2,4 V y el
nodo cuenta cero pulsos.

## Antes de compilar nada

**Ejecuta el ejemplo de cámara del fabricante en las cuatro placas** y confirma
que las cuatro dan imagen. Es media hora y detecta unidades defectuosas mientras
todavía hay plazo de devolución. Además, ese ejemplo trae el pinout real de la
placa que te llegó, que es lo que hay que comparar con el de `camara.ino`.

> El pinout de `camara.ino` está marcado con `VERIFICAR`: compáralo con el
> ejemplo de la GOOUUU ESP32-S3-CAM V1.5 antes de dar las cámaras por buenas.

## Compilar y grabar

Los tres `.ino` hacen `#include <ricevi_nodo.h>`: la carpeta `comun/` se usa
**como librería**. El IDE copia el sketch a una carpeta temporal antes de
compilar, así que una ruta relativa `../comun` no existiría allí y
`ricevi_nodo.cpp` no se compilaría.

**Arduino IDE:** copia `nodos/comun` a la carpeta de librerías del sketchbook
con el nombre `RiceViComun` y reinicia el IDE. **Cada vez que cambies algo en
`comun/`, vuelve a copiarla.**

```powershell
Copy-Item -Recurse -Force nodos\comun "$env:USERPROFILE\Documents\Arduino\libraries\RiceViComun"
```

**arduino-cli:** pásala con `--library`.

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3:PSRAM=opi,FlashSize=16M,PartitionScheme=app3M_fat9M_16MB --library nodos/comun nodos/camara
arduino-cli upload  --fqbn esp32:esp32:esp32s3 -p COM7 nodos/camara
```

## Provisionar

Con el binario ya grabado, cada placa recibe su identidad por consola serie:

```bash
python ../herramientas/provisionar_nodo.py --node-id CAM01 --puerto COM7 --pass "<la del Wi-Fi>"
```

El script escribe `node_id`, `token`, SSID, contraseña e IP de la central en la
NVS, e imprime la MAC. **Copia esa MAC a `config/censo.py`**: sin ella no se
puede crear la reserva DHCP.

Y **pega la etiqueta en la caja antes de montarla**. Siete placas iguales dentro
de siete cajas atornilladas a una cosechadora son indistinguibles, y averiguar
cuál es `NU01` desmontándolas es una tarde perdida.

## El código de colores del LED

Es el único diagnóstico disponible con el nodo dentro de una caja cerrada.
Conviene pegar esta tabla en la cabina:

| Color | Significado |
|---|---|
| Rojo fijo | **Sin identidad en NVS.** No está enviando nada, y es correcto |
| Rojo parpadeando | Sin Wi-Fi |
| Ámbar parpadeando | Con Wi-Fi, sin encontrar la central |
| Verde parpadeando | Registrado y operando |
| Verde doble | Subiendo un frame |
| Azul | Sincronizando reloj |
| Morado | Pendientes en la microSD por reenviar (solo con `RICEVI_SD_HABILITADA 1`) |
| Ámbar tras una captura | No se pudo subir el frame y, sin microSD, se perdió |

## Lo que cada nodo hace, en una línea

**Cámara** — captura, pide turno y sube el JPEG a la Pi, que lo guarda en su SSD.
Los nodos **no llevan microSD** (`RICEVI_SD_HABILITADA 0`): si el enlace cae, los
frames de ese intervalo se pierden. Con microSD (valor 1), el frame se guardaría
antes de subirlo y se reenviaría con el mismo `frame_id`.

**Hall** — cuenta pulsos por hardware en ventanas de 100 ms y publica **dos**
magnitudes: los pulsos crudos de cada ventana y la derivada (rpm o m/s). La
derivada se calcula sobre una ventana deslizante (`ventana_derivada_ms`, 1 s por
defecto): con 100 ms y 8 pulsos por vuelta solo saldrían 0, 75 rpm o «fuera de
rango». Si no hay pulsos, el valor va **nulo** y marcado `sin_pulsos`: el nodo
no puede distinguir una parada real de un sensor caído, así que no inventa un
cero.

**Ultrasónico** — dispara el RCWL-1655 por Trig, mide cuánto dura el eco en
Echo y lo convierte a milímetros con la velocidad del sonido del plan
(`velocidad_sonido_mps`). Publica distancia cruda y altura. Sin eco dentro de
`timeout_eco_us`, o sin `offset_b_mm` medido, el valor va **nulo** con su código
de causa.

## Cosas que se rompen y cómo se ven

| Síntoma | Causa probable |
|---|---|
| LED rojo fijo al arrancar | Falta provisionar la NVS |
| LED rojo parpadeando siempre | El AP está en 5 GHz, o contraseña mal |
| LED ámbar permanente | Aislamiento de clientes activado en el router |
| `409` al subir frames | Dos placas con el mismo `node_id` en NVS |
| `401` / `403` | Token mal grabado, o `generar_tokens.py --rotar` sin re-provisionar |
| La cámara no arranca | PSRAM no configurada como OPI |
| Muchos `timeout` en el ultrasónico | Cableado de Trig/Echo, conector flojo, o la superficie no devuelve eco |
| El Hall cuenta cero pulsos | Pull-up equivocada (10 Ω en vez de 10 kΩ) o diodo al revés |
| Muchas `fuera_rango` | Geometría de montaje, vegetación o terreno |
