# Firmware de los ocho nodos

**Tres binarios, no ocho.** Las cuatro cámaras corren exactamente el mismo
código y solo se distinguen por lo que tienen grabado en NVS.

| Binario | Nodos | Carpeta |
|---|---|---|
| Cámara | `CAM01` `CAM02` `CAM03` `CAM04` | `camara/` |
| Hall | `NH01` `NH02` | `hall/` |
| Ultrasónico | `NU01` `NU02` | `ultrasonico/` |

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

Los mismos para los tres binarios, salvo lo indicado:

```
Placa               ESP32S3 Dev Module
USB CDC On Boot     Enabled
CPU Frequency       240 MHz
Flash Size          16MB (128Mb)
PSRAM               OPI PSRAM          <- imprescindible en las cámaras
Partition Scheme    16M Flash (3MB APP/9.9MB FATFS)
Upload Speed        921600
```

**Sin `OPI PSRAM` la cámara no arranca.** El módulo N16R8 lleva PSRAM octal, y
con la opción por defecto el sistema no la inicializa: la cámara falla al
reservar el búfer del JPEG y el error no menciona la PSRAM por ninguna parte.

## Antes de compilar nada

**Ejecuta el ejemplo de cámara del fabricante en las cuatro placas** y confirma
que las cuatro dan imagen. Es media hora y detecta unidades defectuosas mientras
todavía hay plazo de devolución. Además, ese ejemplo trae el pinout real de la
placa que te llegó, que es lo que hay que comparar con el de `camara.ino`.

> El pinout de `camara.ino` y `ultrasonico.ino` está marcado con `VERIFICAR`.
> Son valores habituales de estas placas, no datos del fabricante de la tuya.

## Compilar y grabar

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3:PSRAM=opi,FlashSize=16M,PartitionScheme=app3M_fat9M_16MB nodos/camara
arduino-cli upload  --fqbn esp32:esp32:esp32s3 -p COM7 nodos/camara
```

Los tres `.ino` incluyen `../comun/ricevi_nodo.h` con ruta relativa, así que la
carpeta `comun/` tiene que estar al lado. Si tu IDE no acepta rutas relativas
hacia arriba, copia `comun/*.h` y `comun/*.cpp` dentro de cada carpeta de
sketch, o instálalos como librería.

## Provisionar

Con el binario ya grabado, cada placa recibe su identidad por consola serie:

```bash
python ../herramientas/provisionar_nodo.py --node-id CAM01 --puerto COM7 --pass "<la del Wi-Fi>"
```

El script escribe `node_id`, `token`, SSID, contraseña e IP de la central en la
NVS, e imprime la MAC. **Copia esa MAC a `config/censo.py`**: sin ella no se
puede crear la reserva DHCP.

Y **pega la etiqueta en la caja antes de montarla**. Ocho placas iguales dentro
de ocho cajas atornilladas a una cosechadora son indistinguibles, y averiguar
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
| Morado | Pendientes en la microSD por reenviar |

## Lo que cada nodo hace, en una línea

**Cámara** — captura, escribe el JPEG en su microSD, pide turno, sube, y borra
de la SD solo cuando la central confirma. Si el enlace cae, el frame sobrevive
y se reenvía con el mismo `frame_id`.

**Hall** — cuenta pulsos por hardware en ventanas de 100 ms y publica **dos**
magnitudes: los pulsos crudos y la derivada (rpm o m/s). Si no hay pulsos, el
valor va **nulo** y marcado `sin_pulsos`: el nodo no puede distinguir una parada
real de un sensor caído, así que no inventa un cero.

**Ultrasónico** — lee tramas de cuatro octetos del A02YYUW, valida la suma de
verificación y publica distancia cruda y altura. Sin eco válido o sin
`offset_b_mm` medido, el valor va **nulo** con su código de causa.

## Cosas que se rompen y cómo se ven

| Síntoma | Causa probable |
|---|---|
| LED rojo fijo al arrancar | Falta provisionar la NVS |
| LED rojo parpadeando siempre | El AP está en 5 GHz, o contraseña mal |
| LED ámbar permanente | Aislamiento de clientes activado en el router |
| `409` al subir frames | Dos placas con el mismo `node_id` en NVS |
| `401` / `403` | Token mal grabado, o `generar_tokens.py --rotar` sin re-provisionar |
| La cámara no arranca | PSRAM no configurada como OPI |
| Muchas `checksum` en el ultrasónico | Cableado, conector flojo o ruido eléctrico |
| Muchas `fuera_rango` | Geometría de montaje, vegetación o terreno |
