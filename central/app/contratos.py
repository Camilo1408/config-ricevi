"""
contratos.py - Los contratos de datos, version 1.1, escritos como codigo ejecutable.

REGLA DE ORO: si un campo no esta aqui, no existe. Nada de diccionarios sueltos
"por ahora". La razon es poder saber, dentro de seis meses, que contienen los
datos sin tener que leer el firmware.

QUE CAMBIA RESPECTO DE LA VERSION 1.0 DEL BANCO
-----------------------------------------------
Solo `Muestra`, y por tres motivos que el hardware real impone:

  1. TIENE QUE PODER DECIR "NO SE". Un ultrasonico sin eco no tiene medida.
     Con `valor: float` no nulable se veria obligado a inventar un numero, y
     cualquier numero que invente entra en el dataset como si fuera real.
  2. TIENE QUE DISTINGUIR MAGNITUDES. Un Hall emite pulsos y rpm del mismo
     conteo. Se podria abusar de `unidad` para separarlas, pero en cuanto dos
     magnitudes comparten unidad -- `distance` y `header_height`, las dos en
     mm -- el esquema se rompe en silencio.
  3. TIENE QUE DECIR POR QUE una lectura es mala. `invalida` no distingue un
     checksum fallido (cableado, ruido) de un eco fuera de rango (geometria,
     vegetacion). Son dos averias distintas con dos soluciones distintas.

Los campos nuevos son OPCIONALES, asi que un nodo que aun hable 1.0 valida sin
tocarlo. Eso permite actualizar el firmware de ocho nodos de uno en uno.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

VERSIONES_ACEPTADAS = ("1.0", "1.1")

CalidadT = Literal["buena", "dudosa", "invalida"]
UtcQualityT = Literal["ntp", "rtc", "desconocida"]

CODIGOS_CALIDAD = (
    "ok", "fuera_rango", "checksum", "timeout",
    "sin_pulsos", "eco_dudoso", "sin_calibrar", "saturado",
)

# La gramatica del frame_id: machine-session-node-boot-seq.
# Se valida aqui para que un firmware que la incumpla falle en el primer
# mensaje, no al analizar el dataset tres meses despues.
RE_FRAME_ID = re.compile(r"^[A-Z0-9]{3}-R\d{3}-(CAM|NH|NU)\d{2}-B\d{2,4}-\d{6}$")


# ---------------------------------------------------------------------------
# Identidad comun a todo mensaje
# ---------------------------------------------------------------------------


class Identidad(BaseModel):
    schema_version: str
    machine_id: str
    node_id: str

    # `seq` se reinicia cuando el nodo arranca. Sin boot_id, el frame 36 de hoy
    # y el 36 de despues de un reinicio serian el mismo identificador.
    boot_id: str

    # `seq` NO se reinicia dentro del mismo boot_id: es lo que permite detectar
    # huecos. Si llegan el 35 y el 37, se perdio el 36 y queda contado.
    seq: int = Field(ge=0)

    @field_validator("schema_version")
    @classmethod
    def _version_soportada(cls, v: str) -> str:
        if v not in VERSIONES_ACEPTADAS:
            raise ValueError(f"schema_version '{v}' no soportada; "
                             f"aceptadas: {VERSIONES_ACEPTADAS}")
        return v


# ---------------------------------------------------------------------------
# POST /v1/nodes/register
# ---------------------------------------------------------------------------


class PeticionRegistro(BaseModel):
    schema_version: str
    machine_id: str
    node_id: str
    boot_id: str
    tipo: Literal["camara", "sensor"]
    rol: Literal["camara", "hall", "ultrasonico"] = "camara"
    firmware: str = ""
    plataforma: str = ""
    # Motivo del ultimo reinicio, tal como lo reporta el ESP32. Distinguir un
    # brownout de un watchdog es la diferencia entre un problema electrico y uno
    # de firmware, y no se puede averiguar despues.
    motivo_reinicio: str = ""


class RespuestaRegistro(BaseModel):
    session_id: str
    config_version: str
    censo_version: str
    # Cambia si la central reinicia: invalida los offsets que el nodo tenia.
    clock_epoch_id: str
    ranura_indice: int
    ranura_offset_s: float
    ciclo_sync_s: float
    plan: dict
    servidor_session_us: int
    # Si la central esta en fase de dataset, el nodo puede ahorrarse trabajo
    # sabiendolo, y el HMI lo muestra sin ambiguedad.
    modelo_activo: str


# ---------------------------------------------------------------------------
# POST /v1/time/exchange
# ---------------------------------------------------------------------------
#
#   El nodo envia en t1, la central recibe en t2, responde en t3, el nodo
#   recibe en t4.
#
#       offset ~= ((t2 - t1) + (t3 - t4)) / 2
#       RTT     = (t4 - t1) - (t3 - t2)
#
#   El termino (t3 - t2) resta lo que la central tardo en procesar, de modo que
#   el RTT mide solo el viaje. Importa: con la CPU cargada de inferencia, sin
#   ese termino se confundiria carga de CPU con mala red.
#
#   EL SUPUESTO QUE HAY QUE ESCRIBIR EN LA TESIS: la formula asume que ida y
#   vuelta tardan lo mismo. En Wi-Fi eso es falso en general. Por eso se guarda
#   sync_uncertainty_ms y el offset no se presenta como exacto.


class PeticionTiempo(BaseModel):
    node_id: str
    t1_us: int

    # PIGGYBACK: el resultado del intercambio ANTERIOR.
    # t4 lo mide el nodo al recibir la respuesta, asi que la central nunca
    # llegaria a conocerlo. El nodo lo cuelga de su siguiente peticion: cuesta
    # 40 octetos y cero viajes de red adicionales.
    t4_previo_us: int | None = None
    rtt_previo_us: int | None = None
    offset_previo_us: int | None = None


class RespuestaTiempo(BaseModel):
    t2_us: int
    t3_us: int
    clock_epoch_id: str


# ---------------------------------------------------------------------------
# POST /v1/upload-slots
# ---------------------------------------------------------------------------


class PeticionTurno(BaseModel):
    node_id: str
    bytes_estimados: int = Field(ge=0)


class RespuestaTurno(BaseModel):
    concedido: bool
    turno_id: str | None = None
    caduca_en_s: float | None = None
    reintentar_en_ms: int | None = None
    en_uso: int = 0
    maximo: int = 0
    # Si la central dejo de aceptar frames por falta de disco, el nodo debe
    # saberlo para conservar en su SD en vez de descartar.
    aceptando_frames: bool = True


# ---------------------------------------------------------------------------
# POST /v1/frames  (parte "meta" del multipart)
# ---------------------------------------------------------------------------


class MetadatosFrame(Identidad):
    session_id: str
    camera_id: str
    frame_id: str

    capture_mono_us: int          # reloj local del nodo, sin saltos
    capture_session_us: int       # el mismo instante en la referencia de la central
    sync_uncertainty_ms: float = Field(ge=0)
    clock_epoch_id: str

    capture_utc: str | None = None
    utc_quality: UtcQualityT = "desconocida"

    bytes: int = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64)
    ancho: int = Field(gt=0)
    alto: int = Field(gt=0)
    jpeg_calidad: int = Field(ge=1, le=100)
    turno_id: str | None = None
    config_version: str = ""
    censo_version: str = ""

    # Nuevo en campo: cuantos frames esperan en la SD del nodo. Es la senal
    # temprana de que el enlace no da abasto, y llega gratis con cada frame.
    pendientes_en_sd: int | None = Field(default=None, ge=0)

    @field_validator("sha256")
    @classmethod
    def _hash_minusculas(cls, v: str) -> str:
        # Un nodo que envie el hash en mayusculas haria fallar la comparacion
        # aunque los octetos sean correctos.
        return v.lower()

    @field_validator("frame_id")
    @classmethod
    def _gramatica(cls, v: str) -> str:
        if not RE_FRAME_ID.match(v):
            raise ValueError(f"frame_id '{v}' no cumple la gramatica "
                             f"machine-session-node-boot-seq")
        return v


class RespuestaFrame(BaseModel):
    frame_id: str
    persistido: bool
    ruta: str
    recibido_session_us: int
    ms_recepcion: float
    ms_escritura: float
    encolado_inferencia: bool
    cola_ocupada: int
    cola_maxima: int


# ---------------------------------------------------------------------------
# POST /v1/telemetry
# ---------------------------------------------------------------------------


class Muestra(BaseModel):
    """Una medicion individual.

    POR QUE `ventana_us` Y NO SOLO UNA MARCA DE TIEMPO: un Hall cuenta pulsos
    durante un intervalo; su RPM es un promedio sobre esa ventana, no un valor
    en un punto. Guardar la ventana permite decidir despues si la asociacion
    con una imagen es legitima.
    """

    sensor_id: str
    magnitud: str = ""            # vacio solo en nodos que aun hablen 1.0
    seq: int = Field(ge=0)
    capture_mono_us: int
    capture_session_us: int
    ventana_us: int = Field(ge=0)
    unidad: str
    calidad: CalidadT = "buena"
    codigo_calidad: str = "ok"

    # NULO CUANDO NO HAY MEDIDA. Nunca cero, nunca el ultimo valor conocido.
    valor: float | None = None

    # Con que constantes se derivo. Sin esto no se puede recalcular si se
    # corrige una calibracion, y habria que repetir la campana.
    calibration_id: str | None = None

    # Crudos del Hall
    pulsos_ventana: int | None = Field(default=None, ge=0)
    pulsos_acumulados: int | None = Field(default=None, ge=0)
    pulsos_por_vuelta: int | None = Field(default=None, gt=0)
    edad_ultimo_pulso_ms: int | None = Field(default=None, ge=0)
    periodo_ultimo_us: int | None = Field(default=None, ge=0)

    # Crudos del ultrasonico
    distancia_cruda_mm: int | None = Field(default=None, ge=0)
    offset_b_mm: int | None = None
    tramas_descartadas: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _coherencia(self):
        if self.codigo_calidad not in CODIGOS_CALIDAD:
            raise ValueError(f"codigo_calidad '{self.codigo_calidad}' "
                             f"no esta en {CODIGOS_CALIDAD}")
        # Un valor nulo con calidad "buena" es un error de firmware, no un
        # estado del mundo. Se rechaza en el primer mensaje.
        if self.valor is None and self.calidad == "buena":
            raise ValueError("valor nulo no puede tener calidad 'buena'")
        # Y al reves: declarar invalida y mandar un numero invita a que alguien
        # lo use sin mirar la calidad.
        if self.valor is not None and self.calidad == "invalida":
            raise ValueError("una muestra invalida no debe llevar valor; usa null")
        return self


class LoteTelemetria(Identidad):
    session_id: str
    sync_uncertainty_ms: float = Field(ge=0)
    clock_epoch_id: str
    config_version: str = ""
    censo_version: str = ""
    muestras: list[Muestra] = Field(min_length=1, max_length=200)


class RespuestaTelemetria(BaseModel):
    persistidas: int
    ids: list[int]
    recibido_session_us: int


# ---------------------------------------------------------------------------
# POST /v1/events
# ---------------------------------------------------------------------------


class Evento(BaseModel):
    node_id: str
    tipo: str
    detalle: str = ""
    session_us: int | None = None

    # Estado del nodo, que viaja colgado del latido. Cuesta unos octetos y cero
    # peticiones adicionales.
    #
    # POR QUE `bateria_mv` NO ES OPCIONAL DE VERDAD: con ocho nodos alimentados
    # por paquetes 18650 independientes, saber cual esta a punto de quedarse sin
    # energia es lo que evita perder una vista a mitad de jornada sin aviso. Es
    # `None` solo para nodos que aun no lo implementen.
    bateria_mv: int | None = Field(default=None, ge=0, le=6000)
    rssi_dbm: int | None = Field(default=None, ge=-120, le=0)
    heap_libre: int | None = Field(default=None, ge=0)
    pendientes_en_sd: int | None = Field(default=None, ge=0)
