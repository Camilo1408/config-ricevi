#!/usr/bin/env bash
#
# instalar_pi.sh - Deja la Raspberry Pi 5 lista para capturar en campo.
#
#   ssh ricevi-rasp@ricevi-rasp-01.local "~/config-ricevi-campo/herramientas/instalar_pi.sh"
#
# Es idempotente: se puede volver a ejecutar sin romper nada.
#
# LO QUE COMPRUEBA Y NO DA POR HECHO
# ----------------------------------
#   - Que DIR_DATOS este en el NVMe y no en la microSD de arranque. A 1 img/s
#     por camara son ~17 GB por jornada: una microSD ni tiene la capacidad ni
#     aguanta esa escritura dia tras dia.
#   - Que haya bateria de RTC, porque de ella depende que la hora de los datos
#     sea fiable sin Internet.
#   - Que el ventilador exista, porque sin el la CPU se estrangula bajo carga.

set -euo pipefail

verde() { printf "\033[32m%s\033[0m\n" "$*"; }
rojo()  { printf "\033[31m%s\033[0m\n" "$*"; }
amar()  { printf "\033[33m%s\033[0m\n" "$*"; }

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATOS="${RICEVI_DIR_DATOS:-/datos/ricevi}"
USUARIO="$(id -un)"

echo "=== RiceVi · instalacion de campo ==="
echo "Proyecto : ${RAIZ}"
echo "Datos    : ${DATOS}"
echo

# ---------------------------------------------------------------- 1. sistema
echo "1/7  Paquetes del sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-venv python3-dev build-essential \
    libjpeg-dev zlib1g-dev libopenblas0 \
    avahi-daemon sqlite3 rsync
sudo systemctl enable --now avahi-daemon
verde "    avahi-daemon: $(systemctl is-active avahi-daemon)"

# ------------------------------------------------------------ 2. almacenamiento
echo
echo "2/7  Almacenamiento"
sudo mkdir -p "${DATOS}"
sudo chown -R "${USUARIO}:${USUARIO}" "$(dirname "${DATOS}")" 2>/dev/null || true
sudo chown -R "${USUARIO}:${USUARIO}" "${DATOS}"
mkdir -p "${DATOS}/frames" "${DATOS}/derivados" "${DATOS}/export"

DISPOSITIVO="$(df --output=source "${DATOS}" | tail -1)"
LIBRE_GB="$(df -BG --output=avail "${DATOS}" | tail -1 | tr -dc '0-9')"
echo "    dispositivo: ${DISPOSITIVO}"
echo "    libre      : ${LIBRE_GB} GB"

if [[ "${DISPOSITIVO}" == *"mmcblk"* ]]; then
    rojo "    LOS DATOS ESTAN EN LA microSD."
    rojo "    Una jornada son ~17 GB y la microSD no aguanta esa escritura a diario."
    rojo "    Monta el NVMe y exporta RICEVI_DIR_DATOS apuntando ahi."
elif [[ "${DISPOSITIVO}" == *"nvme"* ]]; then
    verde "    en NVMe, correcto"
else
    amar "    dispositivo no reconocido; comprueba que no sea la microSD"
fi

if (( LIBRE_GB < 40 )); then
    amar "    menos de 40 GB libres: no cabe una jornada completa con margen"
fi

# ------------------------------------------------------------------- 3. reloj
echo
echo "3/7  Reloj"
if [[ -e /dev/rtc0 || -e /dev/rtc ]]; then
    verde "    RTC presente"
    if command -v hwclock >/dev/null; then
        echo "    hwclock: $(sudo hwclock -r 2>/dev/null || echo 'sin leer')"
    fi
else
    amar "    SIN RTC. Sin Internet, la hora civil de los datos sera 'desconocida'."
    amar "    Conecta la bateria de reloj de la Pi 5 antes de salir a campo."
fi
echo "    NTP sincronizado: $(timedatectl show -p NTPSynchronized --value)"

# -------------------------------------------------------------- 4. refrigeracion
echo
echo "4/7  Refrigeracion"
TEMP="$(vcgencmd measure_temp 2>/dev/null | tr -dc '0-9.' || echo '?')"
echo "    temperatura en reposo: ${TEMP} C"
if ls /sys/class/hwmon/*/pwm1 >/dev/null 2>&1; then
    verde "    control de ventilador presente"
else
    amar "    no se detecta ventilador. Bajo carga sostenida la CPU se estrangulara a 80 C."
fi
THROT="$(vcgencmd get_throttled 2>/dev/null || echo 'throttled=?')"
echo "    ${THROT}"
[[ "${THROT}" == "throttled=0x0" ]] || amar "    ya hubo estrangulamiento o bajo voltaje"

# ------------------------------------------------------------------ 5. entorno
echo
echo "5/7  Entorno de Python"
cd "${RAIZ}"
[[ -d .venv ]] || python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
if [[ -d wheelhouse ]]; then
    pip install --quiet --no-index --find-links wheelhouse -r central/requirements.txt
    verde "    instalado sin red desde wheelhouse/"
else
    pip install --quiet -r central/requirements.txt
    verde "    instalado desde la red"
fi
python -c "import fastapi, uvicorn, pydantic, psutil; print('    librerias OK')"

# -------------------------------------------------------------------- 6. censo
echo
echo "6/7  Censo y tokens"
if python config/censo.py >/dev/null 2>&1; then
    verde "    censo coherente"
else
    amar "    el censo tiene avisos; ejecuta: python config/censo.py"
fi

if [[ -f "${DATOS}/tokens.json" ]]; then
    verde "    tokens presentes"
else
    amar "    faltan tokens. Ejecuta: python herramientas/generar_tokens.py"
fi

# ------------------------------------------------------------------ 7. servicio
echo
echo "7/7  Servicio del sistema"
UNIDAD=/etc/systemd/system/ricevi-central.service
sudo cp "${RAIZ}/herramientas/ricevi-central.service" "${UNIDAD}"
sudo sed -i "s|__RAIZ__|${RAIZ}|g;  s|__USUARIO__|${USUARIO}|g;  s|__DATOS__|${DATOS}|g" "${UNIDAD}"
sudo systemctl daemon-reload
sudo systemctl enable ricevi-central
verde "    ricevi-central instalado y habilitado"

echo
verde "=== Listo ==="
echo
echo "Arrancar:      sudo systemctl start ricevi-central"
echo "Ver registro:  journalctl -u ricevi-central -f"
echo "Comprobar:     curl -s localhost:8000/salud"
echo
echo "Para pasar a la fase de inferencia, cuando haya pesos en modelos/pesos/:"
echo "  sudo systemctl edit ricevi-central   ->   Environment=RICEVI_MODELO=ncnn"
