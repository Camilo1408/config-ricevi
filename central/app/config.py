"""
config.py - Parametros de operacion de la central en campo.

Lo que NO esta aqui: el censo de nodos, sus planes y la calibracion fisica.
Eso vive en config/censo.py y config/calibracion.json, que son los archivos que
se tocan al cambiar el montaje. Aqui solo estan los parametros del servidor.

Todo se puede sobrescribir por variable de entorno, para lanzar una jornada con
otra configuracion sin editar codigo:

    RICEVI_MODELO=ncnn RICEVI_COLA_MAX=4 systemctl restart ricevi-central
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# El censo vive fuera de central/, asi que hay que ponerlo en el path.
RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))
from config import censo  # noqa: E402

# ---------------------------------------------------------------------------
# Identidad y versiones
# ---------------------------------------------------------------------------

# Sube CONFIG_VERSION si cambias cualquier valor de este archivo que afecte a
# los datos. Es lo que permite, dentro de tres meses, saber por que dos tandas
# no son comparables.
CONFIG_VERSION = "cfg-campo-1.0.0"

# El contrato que emiten los ESP32. La central acepta las dos versiones durante
# una transicion de firmware: ver contratos.VERSIONES_ACEPTADAS.
SCHEMA_VERSION = "1.1"

MACHINE_ID = os.getenv("RICEVI_MACHINE_ID", censo.MACHINE_ID)

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
#
# DIR_DATOS DEBE APUNTAR AL SSD NVMe, no a la microSD de arranque.
# A 1 imagen/s por camara son ~17 GB por jornada: una microSD ni tiene la
# capacidad ni aguanta esa escritura dia tras dia. instalar_pi.sh comprueba
# que el punto de montaje existe y tiene sitio.

DIR_DATOS = Path(os.getenv("RICEVI_DIR_DATOS", "/datos/ricevi"))
DIR_FRAMES = DIR_DATOS / "frames"
DIR_DERIVADOS = DIR_DATOS / "derivados"
DIR_EXPORT = DIR_DATOS / "export"
RUTA_BD = Path(os.getenv("RICEVI_BD", DIR_DATOS / "ricevi.db"))
DIR_WEB = Path(__file__).resolve().parent.parent / "web"
DIR_MODELOS = Path(os.getenv("RICEVI_DIR_MODELOS", RAIZ / "modelos"))

# Archivo de tokens, fuera del repositorio. Lo genera generar_tokens.py.
RUTA_TOKENS = Path(os.getenv("RICEVI_TOKENS", DIR_DATOS / "tokens.json"))

# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------

PUERTO = int(os.getenv("RICEVI_PUERTO", "8000"))

# Limite de tamano de un frame, comprobado ANTES de leer el cuerpo completo.
# Sin el, un nodo mal configurado puede llenar la RAM de la Pi antes de que
# nadie se entere.
MAX_BYTES_FRAME = int(os.getenv("RICEVI_MAX_BYTES_FRAME", str(4 * 1024 * 1024)))

# Autenticacion por token. En campo se deja SIEMPRE activa: sin ella, cualquier
# equipo de la red puede inyectar frames con un node_id ajeno y contaminar el
# dataset sin forma de detectarlo.
EXIGIR_TOKEN = os.getenv("RICEVI_EXIGIR_TOKEN", "1") not in ("0", "false", "no")

# ---------------------------------------------------------------------------
# Almacenamiento: el guardian que protege el dataset
# ---------------------------------------------------------------------------
#
# Cuando el disco baja de RESERVA_MB, la central DEJA DE ACEPTAR FRAMES y lo
# dice en el HMI. Es preferible parar la captura de forma visible a llenar el
# disco y que el sistema empiece a fallar de formas raras.
RESERVA_MB = int(os.getenv("RICEVI_RESERVA_MB", "8192"))      # 8 GB
AVISO_MB = int(os.getenv("RICEVI_AVISO_MB", "32768"))         # 32 GB

# ---------------------------------------------------------------------------
# Turnos de subida
# ---------------------------------------------------------------------------
#
# Cuantas camaras pueden subir a la vez. Con 1 las subidas se serializan, que es
# lo que protege el medio de 2,4 GHz compartido por ocho nodos. Subirlo mide el
# punto donde el enlace deja de aguantar.
TURNOS_SIMULTANEOS = int(os.getenv("RICEVI_TURNOS", "1"))
TURNO_SEGUNDOS = float(os.getenv("RICEVI_TURNO_S", "8.0"))
REINTENTO_BASE_MS = int(os.getenv("RICEVI_REINTENTO_MS", "150"))

# ---------------------------------------------------------------------------
# Inferencia
# ---------------------------------------------------------------------------

# QUE MOTOR DE MODELO SE CARGA:
#   "ninguno"  fase de dataset. No infiere. El HMI muestra "sin modelo".
#   "ncnn"     fase de inferencia, con los pesos en modelos/pesos/.
#
# POR DEFECTO ES "ninguno" A PROPOSITO. Un sistema que arranca inventando
# porcentajes es peor que uno que no diagnostica: el numero falso acaba en la
# tesis y nadie lo nota.
MODELO = os.getenv("RICEVI_MODELO", "ninguno")

# Cola acotada, y el numero es pequeno a proposito. Una cola infinita no evita
# el problema: lo esconde. Cuando se llena se descartan frames DE INFERENCIA,
# nunca de captura, y el descarte queda contado.
COLA_MAX = int(os.getenv("RICEVI_COLA_MAX", "8"))
HILOS_INFERENCIA = int(os.getenv("RICEVI_HILOS_INF", "1"))

# Cuanto puede envejecer un frame antes de que no merezca la pena inferirlo.
# Un diagnostico de hace diez segundos presentado como actual es peor que no
# tener diagnostico.
VIGENCIA_INFERENCIA_MS = int(os.getenv("RICEVI_VIGENCIA_MS", "4000"))

# ---------------------------------------------------------------------------
# Salud termica (lazo de la seccion 16.4 del documento de arquitectura)
# ---------------------------------------------------------------------------
#
# El sistema reduce su propia carga ANTES de que el SoC se estrangule a 80 C.
# Degradar el ritmo de inferencia de forma deliberada es preferible a que el
# hardware baje la frecuencia y la cola crezca sin recuperarse.
#
# LA CAPTURA NUNCA SE DEGRADA POR TEMPERATURA. Solo el diagnostico.
VIGILAR_TEMPERATURA = os.getenv("RICEVI_VIGILAR_TEMP", "1") not in ("0", "false")
TEMP_CALIDO_C = float(os.getenv("RICEVI_TEMP_CALIDO", "65"))
TEMP_CALIENTE_C = float(os.getenv("RICEVI_TEMP_CALIENTE", "72"))
TEMP_CRITICO_C = float(os.getenv("RICEVI_TEMP_CRITICO", "78"))
TEMP_PROTECCION_C = float(os.getenv("RICEVI_TEMP_PROTECCION", "82"))
PERIODO_SALUD_S = float(os.getenv("RICEVI_PERIODO_SALUD_S", "5.0"))

# ---------------------------------------------------------------------------
# Apagado seguro
# ---------------------------------------------------------------------------
#
# GPIO donde entra la senal de contacto de la maquina, a traves de un
# optoacoplador. Al girar la llave, la central cierra archivos, sincroniza el
# disco y apaga de forma ordenada. Vacio = desactivado.
GPIO_CONTACTO = os.getenv("RICEVI_GPIO_CONTACTO", "")
SEGUNDOS_GRACIA_APAGADO = float(os.getenv("RICEVI_GRACIA_APAGADO_S", "20"))

# ---------------------------------------------------------------------------
# Sincronizacion y asociacion
# ---------------------------------------------------------------------------

CICLO_SYNC_S = censo.CICLO_SYNC_S
RANURA_S = censo.RANURA_S

_cal_central = censo.calibracion().get("central", {})
TOLERANCIA_ASOCIACION_MS = float(os.getenv(
    "RICEVI_TOL_ASOC_MS", str(_cal_central.get("tolerancia_asociacion_ms", 100))))
TOLERANCIA_EMPAREJAMIENTO_MS = float(os.getenv(
    "RICEVI_TOL_EMP_MS", str(_cal_central.get("tolerancia_emparejamiento_ms", 150))))
VELOCIDAD_MINIMA_RI = float(os.getenv(
    "RICEVI_VEL_MIN_RI", str(_cal_central.get("velocidad_minima_para_ri_mps", 0.3))))

# Cada cuanto se recalcula el estado fusionado de la maquina.
PERIODO_FUSION_S = float(os.getenv("RICEVI_PERIODO_FUSION_S", "0.5"))


def asegurar_directorios() -> None:
    for d in (DIR_DATOS, DIR_FRAMES, DIR_DERIVADOS, DIR_EXPORT):
        d.mkdir(parents=True, exist_ok=True)


def espacio_libre_mb() -> int:
    import shutil
    try:
        return shutil.disk_usage(DIR_DATOS).free // (1024 * 1024)
    except OSError:
        return 0


def resumen() -> dict:
    """Instantanea de la configuracion, para el acta de sesion."""
    return {
        "config_version": CONFIG_VERSION,
        "schema_version": SCHEMA_VERSION,
        "machine_id": MACHINE_ID,
        "dir_datos": str(DIR_DATOS),
        "exigir_token": EXIGIR_TOKEN,
        "modelo": MODELO,
        "turnos_simultaneos": TURNOS_SIMULTANEOS,
        "cola_max": COLA_MAX,
        "hilos_inferencia": HILOS_INFERENCIA,
        "vigencia_inferencia_ms": VIGENCIA_INFERENCIA_MS,
        "reserva_mb": RESERVA_MB,
        "vigilar_temperatura": VIGILAR_TEMPERATURA,
        "umbrales_temp_c": [TEMP_CALIDO_C, TEMP_CALIENTE_C,
                            TEMP_CRITICO_C, TEMP_PROTECCION_C],
        "tolerancia_asociacion_ms": TOLERANCIA_ASOCIACION_MS,
        "tolerancia_emparejamiento_ms": TOLERANCIA_EMPAREJAMIENTO_MS,
        "velocidad_minima_ri_mps": VELOCIDAD_MINIMA_RI,
    }
