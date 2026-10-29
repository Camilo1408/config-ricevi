#!/usr/bin/env bash
# instalar_demo.sh - Instala la demostración del modelo de tolva en la Raspberry Pi.
#
# Se ejecuta desde la carpeta copiada a la Pi (con Internet, una sola vez):
#     cd ~/ricevi-ia-demo && bash instalar_demo.sh
#
# No toca la central: entorno virtual propio, servicio propio, puerto 8001.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USUARIO="$(id -un)"
FRAMES="${IA_DIR_FRAMES:-/datos/ricevi/frames}"
UNIDAD=/etc/systemd/system/ricevi-ia-demo.service

echo "== RiceVi IA demo en ${RAIZ} (usuario ${USUARIO}, frames ${FRAMES})"
cd "${RAIZ}"

ls modelos/*/ficha_modelo.json >/dev/null 2>&1 || { echo "Falta modelos/<version>/ con el modelo"; exit 1; }

[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo "== Prueba del modelo con un cuadro de repetición"
.venv/bin/python inferir_tolva.py --modelo "$(ls -d modelos/*/ | sort | tail -1)" \
    --entrada "$(ls repeticion/*.jpg | head -1)" --salida /tmp/ricevi-ia-prueba

sudo cp ricevi-ia-demo.service "${UNIDAD}"
sudo sed -i "s|__RAIZ__|${RAIZ}|g; s|__USUARIO__|${USUARIO}|g; s|__FRAMES__|${FRAMES}|g" "${UNIDAD}"
sudo systemctl daemon-reload
sudo systemctl enable --now ricevi-ia-demo
sleep 3
systemctl --no-pager --lines=5 status ricevi-ia-demo || true

IP="$(hostname -I | awk '{print $1}')"
echo
echo "Listo. Página:   http://${IP}:8001   (o http://$(hostname).local:8001)"
echo "Registro:        journalctl -u ricevi-ia-demo -f"
echo "La central sigue en el puerto 8000 sin cambios."
