#!/usr/bin/env bash
#
# respaldo_jornada.sh - Copia la jornada a dos sitios y verifica por hash.
#
#   ./herramientas/respaldo_jornada.sh /media/disco-externo
#   ./herramientas/respaldo_jornada.sh /media/disco-externo R003
#
# POR QUE ESTE SCRIPT EXISTE
# --------------------------
# Una jornada de cosecha no se repite. Si el SSD falla el martes, no hay forma
# de volver a capturar el lunes: esa combinacion de lote, variedad, humedad y
# hora no vuelve. La copia se hace AL TERMINAR CADA JORNADA, no al final de la
# campana.
#
# Y SE VERIFICA. Una copia que nadie comprobo es una copia que no se sabe si
# existe. `rsync` puede terminar sin error y dejar un archivo truncado si el
# disco de destino se llena a mitad; la verificacion por SHA-256 lo detecta.

set -euo pipefail

verde() { printf "\033[32m%s\033[0m\n" "$*"; }
rojo()  { printf "\033[31m%s\033[0m\n" "$*"; }
amar()  { printf "\033[33m%s\033[0m\n" "$*"; }

DESTINO="${1:-}"
SESION="${2:-}"
DATOS="${RICEVI_DIR_DATOS:-/datos/ricevi}"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${DESTINO}" ]]; then
    echo "Uso: $0 <destino> [session_id]"
    echo "Ej.: $0 /media/respaldo R003"
    exit 1
fi
[[ -d "${DESTINO}" ]] || { rojo "No existe ${DESTINO}"; exit 1; }

# Si no se indica sesion, la ultima.
if [[ -z "${SESION}" ]]; then
    SESION="$(ls -1 "${DATOS}/frames" 2>/dev/null | sort | tail -1)"
    [[ -n "${SESION}" ]] || { rojo "No hay sesiones en ${DATOS}/frames"; exit 1; }
fi

FECHA="$(date -u +%Y%m%d)"
CARPETA="${DESTINO}/ricevi-${FECHA}-${SESION}"
echo "=== Respaldo de ${SESION} ==="
echo "Origen : ${DATOS}"
echo "Destino: ${CARPETA}"
echo

# ------------------------------------------------- 1. detener escrituras nuevas
echo "1/6  Consolidando la base"
if systemctl is-active --quiet ricevi-central; then
    amar "    la central esta corriendo: se respalda una foto consistente,"
    amar "    pero lo limpio es pararla antes."
fi
# Consolida el WAL para que el .db copiado sea coherente por si mismo.
sqlite3 "${DATOS}/ricevi.db" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
verde "    WAL consolidado"

# --------------------------------------------------------- 2. espacio suficiente
echo
echo "2/6  Comprobando espacio"
NECESARIO_KB="$(du -sk "${DATOS}/frames/${SESION}" | cut -f1)"
LIBRE_KB="$(df -k --output=avail "${DESTINO}" | tail -1)"
echo "    hacen falta $((NECESARIO_KB/1024)) MB, hay $((LIBRE_KB/1024)) MB"
if (( LIBRE_KB < NECESARIO_KB + 1048576 )); then
    rojo "    no cabe con margen. Libera espacio o usa otro disco."
    exit 1
fi

# ------------------------------------------------------------------- 3. copiar
echo
echo "3/6  Copiando"
mkdir -p "${CARPETA}"
rsync -a --info=progress2 \
      "${DATOS}/frames/${SESION}" "${CARPETA}/frames/"
cp "${DATOS}/ricevi.db" "${CARPETA}/"
# Los tokens viajan con el respaldo: perderlos cuesta volver a provisionar los
# ocho nodos, y conservarlos no cuesta nada.
[[ -f "${DATOS}/tokens.json" ]] && cp "${DATOS}/tokens.json" "${CARPETA}/"
# Y la configuracion con la que se capturo: sin ella, dentro de tres meses no
# se sabra que ROI ni que calibracion habia ese dia.
cp -r "${RAIZ}/config" "${CARPETA}/config-usada"
verde "    copiado"

# --------------------------------------------------------- 4. exportar tablas
echo
echo "4/6  Exportando las tablas a CSV"
mkdir -p "${CARPETA}/export"
for t in frames telemetria estado_maquina resultados intercambios_tiempo nodos eventos sesiones; do
    sqlite3 -header -csv "${CARPETA}/ricevi.db" "SELECT * FROM ${t};" \
        > "${CARPETA}/export/${t}.csv" 2>/dev/null || true
done
verde "    $(ls -1 "${CARPETA}/export" | wc -l) tabla(s)"

# ------------------------------------------------------------- 5. verificar
echo
echo "5/6  Verificando por SHA-256"
# Se comparan los hashes que la central guardo al recibir cada frame contra los
# archivos copiados. Asi se verifica la cadena entera de una vez: nodo -> red ->
# disco de la Pi -> disco de respaldo.
MAL=0
TOTAL=0
while IFS='|' read -r ruta hash_esperado; do
    ARCHIVO="${CARPETA}/${ruta}"
    [[ -f "${ARCHIVO}" ]] || { rojo "    FALTA ${ruta}"; MAL=$((MAL+1)); continue; }
    REAL="$(sha256sum "${ARCHIVO}" | cut -d' ' -f1)"
    TOTAL=$((TOTAL+1))
    if [[ "${REAL}" != "${hash_esperado}" ]]; then
        rojo "    HASH DISTINTO ${ruta}"
        MAL=$((MAL+1))
    fi
done < <(sqlite3 "${CARPETA}/ricevi.db" \
         "SELECT ruta, sha256 FROM frames WHERE session_id='${SESION}';")

echo "    ${TOTAL} archivos verificados, ${MAL} con problema"
if (( MAL > 0 )); then
    rojo "    LA COPIA NO ES FIABLE. No borres el original."
    exit 1
fi
verde "    todos los octetos coinciden"

# --------------------------------------------------------------- 6. inventario
echo
echo "6/6  Inventario"
{
    echo "sesion: ${SESION}"
    echo "fecha_respaldo_utc: $(date -u --iso-8601=seconds)"
    echo "origen: ${DATOS}"
    echo "frames_verificados: ${TOTAL}"
    sqlite3 "${CARPETA}/ricevi.db" <<SQL
.mode line
SELECT COUNT(*) AS frames, SUM(bytes) AS bytes FROM frames WHERE session_id='${SESION}';
SELECT COUNT(*) AS muestras FROM telemetria WHERE session_id='${SESION}';
SELECT COUNT(*) AS resultados FROM resultados;
SQL
} > "${CARPETA}/INVENTARIO.txt"
cat "${CARPETA}/INVENTARIO.txt"

echo
verde "=== Respaldo verificado en ${CARPETA} ==="
amar "Haz AHORA la segunda copia en otro soporte. Una sola copia no es un respaldo."
