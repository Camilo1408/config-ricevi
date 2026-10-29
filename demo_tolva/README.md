# demo_tolva — demostración del modelo de tolva, aparte de la captura

Servicio web que corre en la Raspberry Pi **al lado de la central, sin tocarla**.
Pasa cuadros de la tolva por el modelo de segmentación v2 (U-Net con
MobileNetV3, exportado a NCNN) y muestra el **% de material vegetal verde
visible**, el acercamiento a la zona con más verde, la latencia, la versión del
modelo y su SHA-256.

Es el «despliegue en sombra» de `modelos/README.md`: el modelo corre al lado
del sistema y no interviene en lo que la central captura, verifica ni guarda.
**No es la fase 2**: la central sigue con `RICEVI_MODELO=ninguno`.

La landing (`sistema-arroz-front`, sección «IA en vivo») usa este servicio
cuando corre en el portátil con `npm run pitch`.

## Por qué no interfiere con la toma de datos

| Lo que comparten | Central (`ricevi-central`) | Esta demo (`ricevi-ia-demo`) |
|---|---|---|
| Carpeta | `~/config-ricevi-campo` | `~/ricevi-ia-demo` |
| Entorno de Python | `~/config-ricevi-campo/.venv` | `~/ricevi-ia-demo/.venv`, propio |
| Puerto | 8000 | **8001** |
| Prioridad de CPU | `Nice=-5` | `Nice=10`: cede la CPU a la central |
| Prioridad de disco | `best-effort`, prioridad 2 | `idle`: solo usa el disco cuando nadie más lo pide |
| Escritura en disco | Sí, en `/datos/ricevi` | **Ninguna.** `ProtectSystem=strict` y `ProtectHome=read-only`: el sistema operativo le impide escribir en cualquier sitio. Los resultados viven en memoria |
| Datos de la central | Los escribe | Solo **lee** el último JPEG de `CAM04`, y únicamente si alguien lo pide desde la página |
| Código de la central | — | No modifica ningún archivo de `central/`, `config/`, `modelos/` ni `nodos/` |

**Lo único que sí comparten es la red Wi-Fi del router.** Cada análisis manda
imágenes al navegador por el mismo punto de acceso que usan las cámaras para
subir sus JPEG. Por eso hay una regla:

> **Durante una jornada de captura, la demo va apagada.** Se enciende solo para
> mostrarla (sección «Encender y apagar»).

## Qué hay en esta carpeta

| Archivo | Qué es |
|---|---|
| `app.py` | El servicio web (FastAPI) y la página en `web/` |
| `motor_tolva.py` | Carga el modelo NCNN, verifica su SHA-256 y hace la inferencia por teselas |
| `inferir_tolva.py` | Prueba por línea de comandos: pasa una imagen por el modelo |
| `instalar_demo.sh` | Instalador para la Pi |
| `ricevi-ia-demo.service` | Servicio de systemd con las protecciones de la tabla |
| `requirements.txt` | Dependencias del entorno propio |
| `modelos/v1/`, `modelos/v2/` | Una carpeta por versión: `ficha_modelo.json` (datos, métricas y SHA-256) y los pesos |
| `repeticion/` | Los 6 cuadros de prueba de `IMG_1577`, el video que el modelo **nunca vio** al entrenar |

### Los pesos no están en git

Siguiendo la regla del repositorio (`.gitignore`), los `.bin` y `.param` se
copian aparte. Cada versión necesita dos archivos junto a su ficha:

```
modelos/v2/
  ficha_modelo.json          está en git
  tolva_unet.ncnn.param      se copia aparte
  tolva_unet.ncnn.bin        se copia aparte
```

Salen de `ricevi_tolva_modelo.zip`, el resultado del notebook de entrenamiento
(`tolva_poc/resultado_v2/` en el equipo de Alvaro). Si los pesos no coinciden con
el SHA-256 de la ficha, el servicio **no los carga** y la página dice
«sin modelo». Para comprobarlo a mano en la Pi:

```bash
sha256sum ~/ricevi-ia-demo/modelos/v2/tolva_unet.ncnn.bin
```

Tiene que empezar por `4dbe1f20acc0`.

## Instalación, paso a paso

Se hace **una vez y con internet** en la Pi, para descargar las librerías. Después
funciona sin internet. Necesitas el portátil y la Pi en la **misma red**.

Los comandos del portátil son de PowerShell. Los de la Pi se escriben después de
entrar con `ssh`. Usuario y equipo son los de la central; si cambian, ajústalos.

### 1. Encontrar la Pi

En el portátil:

```powershell
ping ricevi-rasp-01.local
```

Si no responde, usa la IP de la Pi en vez del nombre (en la red de RiceVi es
`192.168.40.2`; en otra red, búscala en el router o con `hostname -I` en la Pi).

### 2. Revisar la Pi

```powershell
ssh ricevi-rasp@ricevi-rasp-01.local
```

Ya dentro de la Pi:

```bash
uname -m              # tiene que decir aarch64
python3 --version     # anótala: 3.11 en Bookworm, 3.13 en Trixie
ls ~/ricevi-ia-demo   # ¿hay una instalación anterior?
```

**Si `ls` muestra archivos**, muévela a un lado. Si no, `scp` copiaría la carpeta
nueva *dentro* de la vieja:

```bash
mv ~/ricevi-ia-demo ~/ricevi-ia-demo-anterior
```

Sal con `exit`.

### 3. Comprobar que los pesos están en la carpeta del portátil

```powershell
Get-ChildItem C:\ruta\a\config-ricevi\demo_tolva\modelos\v2
```

Tienen que aparecer `ficha_modelo.json`, `tolva_unet.ncnn.param` y
`tolva_unet.ncnn.bin` (unos 16 MB). Si faltan los dos últimos, cópialos primero
(ver «Los pesos no están en git»).

### 4. Copiar la carpeta a la Pi

```powershell
scp -r C:\ruta\a\config-ricevi\demo_tolva ricevi-rasp@ricevi-rasp-01.local:~/ricevi-ia-demo
```

### 5. Instalar

```powershell
ssh ricevi-rasp@ricevi-rasp-01.local
```

En la Pi:

```bash
cd ~/ricevi-ia-demo && bash instalar_demo.sh
```

Tarda unos minutos y pide la contraseña para `sudo`. El instalador:

1. Crea el entorno de Python propio e instala `requirements.txt`.
2. Pasa un cuadro de `repeticion/` por el modelo, para probar que carga y responde.
3. Instala el servicio `ricevi-ia-demo` y lo deja encendido y activado al arrancar.

Terminó bien si al final dice `Listo. Página: http://<IP>:8001`.

### 6. Verificar

1. **La central sigue igual:** en la Pi, `curl -s localhost:8000/salud` responde
   como antes de instalar.
2. **La demo responde:** en el navegador del portátil, `http://<IP>:8001`.
   Pulsa «Siguiente cuadro de prueba». La versión tiene que ser **v2** y el hash
   empezar por **`4dbe1f20acc0`**.
3. **Anota la latencia** que muestra la página. En la CPU del PC son 1,4 s; en la
   Pi 5 todavía no se ha medido (se esperan 2 a 4 s).
4. **Con la landing:** en `sistema-arroz-front`, `npm run pitch`, y abrir
   `http://localhost:4173/?demo=http://<IP>:8001`. Con `192.168.40.2` no hace
   falta `?demo=`. La píldora de «IA en vivo» tiene que estar **verde**:
   «En vivo desde la Raspberry Pi · v2 · 4dbe1f20acc0».
5. **Arranca sola:** `sudo reboot`, esperar 1 o 2 minutos, y repetir el punto 2.

## Encender y apagar

| Para | Comando en la Pi |
|---|---|
| **Jornada de captura** (apagada y sin arrancar con la Pi) | `sudo systemctl disable --now ricevi-ia-demo` |
| **Una demostración** (encendida y arranca con la Pi) | `sudo systemctl enable --now ricevi-ia-demo` |
| Ver si está corriendo | `systemctl status ricevi-ia-demo --no-pager` |
| Ver su registro | `journalctl -u ricevi-ia-demo -n 50 --no-pager` |

Ninguno de estos comandos toca `ricevi-central`.

## Cambiar la versión del modelo

Cada versión es una carpeta en `modelos/` con su ficha y sus dos archivos de
pesos. La página tiene un selector para pasar de una a otra. Al arrancar se
carga la última por nombre (hoy `v2`), salvo que se fije otra:

```bash
sudo systemctl edit ricevi-ia-demo
```

```ini
[Service]
Environment=IA_MODELO=v1
```

## Desinstalar

En la Pi, sin tocar la central:

```bash
sudo systemctl disable --now ricevi-ia-demo
sudo rm /etc/systemd/system/ricevi-ia-demo.service
sudo systemctl daemon-reload
rm -rf ~/ricevi-ia-demo
```

## Si algo falla

| Síntoma | Qué revisar |
|---|---|
| `ping` o `ssh` no encuentra `ricevi-rasp-01.local` | Usar la IP en vez del nombre |
| El instalador dice «Falta modelos/» | La copia quedó incompleta o dentro de la carpeta vieja: repetir los pasos 2 a 4 |
| El instalador falla al instalar `ncnn` | Anotar la versión de Python del paso 2 y el mensaje completo. `ncnn==1.0.20261020` tiene ruedas aarch64 para Python 3.11; con 3.13 no está comprobado |
| La página dice «sin modelo» | Faltan los pesos o el SHA-256 no coincide con la ficha (`sha256sum`, sección de pesos) |
| `http://<IP>:8001` no abre | `systemctl status ricevi-ia-demo` y `journalctl -u ricevi-ia-demo -n 50 --no-pager` |
| La píldora de la landing sale amarilla | Portátil y Pi en redes distintas, la IP del `?demo=` está mal, o el servicio está apagado |

## Límites del modelo (decirlos antes de que los pregunten)

- Prueba de concepto: entrenado con 1.557 hojas anotadas por una persona en 24
  cuadros, con imágenes de celular, no de la `CAM04`.
- Entrenamiento y prueba son de la misma jornada (8 de mayo de 2026, Palermo).
- Mide fracción del área de la imagen, no peso. Hoy marca más del doble del área
  anotada a mano: es un detector de hojas, no un medidor calibrado.
- No ve la paja seca ni la cascarilla, que tienen el color del grano.
