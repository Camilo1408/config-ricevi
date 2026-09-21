"""
rutas_ingesta.py - Los endpoints que mueven datos.

    POST /v1/frames      imagen + metadatos, multipart
    POST /v1/telemetry   lote de muestras de sensor
    POST /v1/events      latido, descarga de tolva, cambio de ajuste, error

AQUI VIVE LA REGLA CENTRAL DEL PROYECTO
---------------------------------------
    Responder 201 en cuanto el archivo esta en disco y su fila en la base.
    Encolar la inferencia DESPUES. No esperarla nunca.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time

from fastapi import APIRouter, File, Form, Header, HTTPException, Response, UploadFile
from pydantic import ValidationError

from . import (basedatos, config, contratos, inferencia, reloj, salud,
               seguridad, turnos)

sys.path.insert(0, str(config.RAIZ))
from config import censo  # noqa: E402

log = logging.getLogger("ricevi.ingesta")
router = APIRouter(prefix="/v1", tags=["ingesta"])


@router.post("/frames", status_code=201, response_model=contratos.RespuestaFrame)
async def recibir_frame(
    respuesta: Response,
    meta: str = Form(..., description="JSON con los metadatos del frame"),
    imagen: UploadFile = File(..., description="JPEG original, sin recomprimir"),
    x_ricevi_token: str = Header(default=""),
):
    t_inicio = time.perf_counter_ns()

    # --- 1. Metadatos --------------------------------------------------------
    try:
        m = contratos.MetadatosFrame(**json.loads(meta))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"meta no es JSON valido: {e}")
    except ValidationError as e:
        # Hay que capturarlo a mano: `meta` llega como CADENA dentro del
        # multipart, asi que FastAPI no la valida por su cuenta y su excepcion
        # se convertiria en un 500. Un 500 le dice al nodo "reintenta", cuando
        # el mensaje esta mal y reintentarlo dara siempre lo mismo. El 422 es
        # lo que evita que malgaste tiempo de aire.
        raise HTTPException(status_code=422,
                            detail=f"meta no cumple el contrato: {e.errors()}")

    seguridad.verificar(m.node_id, x_ricevi_token)

    # El frame_id tiene que corresponder al nodo que lo envia. Sin esta
    # comprobacion, un nodo mal provisionado podria escribir en el espacio de
    # otro y el dataset quedaria con imagenes atribuidas a la camara
    # equivocada -- el peor error posible aqui, porque no se detecta mirando.
    if f"-{m.node_id}-" not in m.frame_id:
        raise HTTPException(
            status_code=409,
            detail=f"frame_id {m.frame_id} no corresponde al nodo {m.node_id}")
    if m.camera_id != m.node_id:
        raise HTTPException(status_code=409,
                            detail="camera_id y node_id no coinciden")

    # --- 2. Guardian del disco ----------------------------------------------
    # Se comprueba ANTES de leer el cuerpo: si no hay sitio, no tiene sentido
    # gastar tiempo de aire y RAM en recibir algo que no se va a guardar. El
    # nodo lo conserva en su microSD y lo reenvia cuando se libere espacio.
    if not salud.salud.aceptando_frames:
        raise HTTPException(status_code=507,
                            detail=f"sin espacio: {salud.salud.motivo_rechazo}")

    # --- 3. Idempotencia -----------------------------------------------------
    # Un nodo que no recibio el 201 REENVIARA el mismo frame. Es lo correcto por
    # su parte: no puede saber si llego.
    #
    #   mismo frame_id + mismo hash  -> reenvio legitimo. 200, sin duplicar.
    #   mismo frame_id + otro hash   -> conflicto real: dos contenidos distintos
    #                                   reclaman la misma identidad. 409.
    previo = basedatos.existe_frame(m.frame_id)
    if previo is not None:
        if previo["sha256"] == m.sha256:
            # 200 y no 201: el recurso ya existia. La distincion permite al nodo
            # CONTAR sus reenvios, que es una medida directa de la fiabilidad
            # del enlace.
            respuesta.status_code = 200
            return contratos.RespuestaFrame(
                frame_id=m.frame_id, persistido=True, ruta=previo["ruta"],
                recibido_session_us=reloj.session_us(), ms_recepcion=0.0,
                ms_escritura=0.0, encolado_inferencia=False,
                cola_ocupada=inferencia.motor.cola.qsize(),
                cola_maxima=config.COLA_MAX)
        basedatos.guardar_evento(m.node_id, "conflicto_frame_id",
                                 f"{m.frame_id}: hash distinto al almacenado",
                                 reloj.session_us(), reloj.utc_iso())
        raise HTTPException(status_code=409,
                            detail=f"frame_id {m.frame_id} ya existe con otro contenido")

    # --- 4. Leer los octetos -------------------------------------------------
    octetos = await imagen.read()
    t_leido = time.perf_counter_ns()
    recibido_us = reloj.session_us()

    if len(octetos) > config.MAX_BYTES_FRAME:
        raise HTTPException(status_code=413, detail=f"{len(octetos)} B supera el maximo")

    # --- 5. Integridad --------------------------------------------------------
    # El nodo ya calculo el hash, pero eso solo prueba lo que el nodo CREE haber
    # enviado. Recalcularlo sobre lo recibido prueba que el viaje no los altero.
    #
    # LO QUE EL HASH NO GARANTIZA, y conviene decirlo en la tesis: que la escena
    # sea util, que este enfocada o que la lente no estuviera sucia. Es
    # integridad de octetos, no calidad de imagen.
    digest = hashlib.sha256(octetos).hexdigest()
    if digest != m.sha256:
        basedatos.guardar_evento(
            m.node_id, "hash_no_coincide",
            f"{m.frame_id}: esperado {m.sha256[:12]}, calculado {digest[:12]}",
            recibido_us, reloj.utc_iso())
        raise HTTPException(status_code=422,
                            detail="el SHA-256 no coincide: los octetos se alteraron")
    if len(octetos) != m.bytes:
        raise HTTPException(
            status_code=422,
            detail=f"bytes declarados {m.bytes} != recibidos {len(octetos)}")

    # --- 6. Escritura atomica -------------------------------------------------
    carpeta = config.DIR_FRAMES / m.session_id / m.camera_id
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{m.frame_id}.jpg"
    temporal = carpeta / f".{m.frame_id}.parcial"

    t_esc0 = time.perf_counter_ns()
    # Se escribe a un temporal, se fuerza a disco y se renombra. El renombrado
    # dentro del mismo sistema de archivos es atomico, asi que NUNCA existe un
    # .jpg a medio escribir: si la Pi se apaga en mitad, queda un .parcial que
    # se barre, no un JPEG truncado que parece valido.
    with open(temporal, "wb") as fh:
        fh.write(octetos)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(temporal, destino)
    t_esc1 = time.perf_counter_ns()

    ms_recepcion = (t_leido - t_inicio) / 1e6
    ms_escritura = (t_esc1 - t_esc0) / 1e6

    # --- 7. Fila en la base ---------------------------------------------------
    try:
        basedatos.guardar_frame({
            "frame_id": m.frame_id, "session_id": m.session_id, "node_id": m.node_id,
            "camera_id": m.camera_id, "boot_id": m.boot_id, "seq": m.seq,
            "capture_mono_us": m.capture_mono_us,
            "capture_session_us": m.capture_session_us,
            "sync_uncertainty_ms": m.sync_uncertainty_ms,
            "clock_epoch_id": m.clock_epoch_id,
            "capture_utc": m.capture_utc, "utc_quality": m.utc_quality,
            "recibido_session_us": recibido_us, "bytes": len(octetos),
            "sha256": digest, "ruta": str(destino.relative_to(config.DIR_DATOS)),
            "ancho": m.ancho, "alto": m.alto, "jpeg_calidad": m.jpeg_calidad,
            "pendientes_en_sd": m.pendientes_en_sd,
            "ms_recepcion": ms_recepcion, "ms_escritura": ms_escritura,
            "config_version": m.config_version or config.CONFIG_VERSION,
            "censo_version": m.censo_version or censo.CENSO_VERSION,
        })
    except Exception:
        # Si la fila falla, se borra el archivo: mejor nada que dataset huerfano
        # del que nadie tiene registro.
        destino.unlink(missing_ok=True)
        raise

    # --- 8. Liberar el turno --------------------------------------------------
    # AQUI, no antes: el turno protege el medio radio, y el medio sigue ocupado
    # hasta que ha llegado el ultimo octeto.
    turnos.gestor.liberar(m.turno_id)

    # --- 9. Encolar la inferencia ---------------------------------------------
    # Sin bloquear, y la respuesta sale inmediatamente despues. El nodo queda
    # libre para capturar aunque la inferencia vaya con retraso.
    encolado = False
    plan = censo.PLANES.get(m.camera_id, {})
    base_n = int(plan.get("uno_de_cada_n_infiere", 1))
    cada_n = salud.salud.uno_de_cada_n(base_n)
    if m.seq % max(1, cada_n) == 0:
        encolado = inferencia.motor.encolar(
            m.frame_id, octetos,
            plan.get("tarea", "post_corte"),
            tuple(plan.get("roi", (0.0, 0.0, 1.0, 1.0))),
            plan.get("roi_version", ""),
            m.capture_session_us)

    return contratos.RespuestaFrame(
        frame_id=m.frame_id, persistido=True,
        ruta=str(destino.relative_to(config.DIR_DATOS)),
        recibido_session_us=recibido_us,
        ms_recepcion=round(ms_recepcion, 3), ms_escritura=round(ms_escritura, 3),
        encolado_inferencia=encolado,
        cola_ocupada=inferencia.motor.cola.qsize(),
        cola_maxima=config.COLA_MAX)


@router.post("/telemetry", status_code=201,
             response_model=contratos.RespuestaTelemetria)
def recibir_telemetria(lote: contratos.LoteTelemetria,
                       x_ricevi_token: str = Header(default="")):
    """Recibe un lote corto de muestras.

    POR LOTES Y NO UNA A UNA: a 10 Hz, una peticion por muestra son 10 por
    segundo y por nodo, 40 en total, sobre el mismo radio que las camaras
    necesitan. Con lotes de 10 son 4. El coste es que la muestra mas antigua
    llega hasta 1 s tarde, y NO afecta a la precision del dato porque cada
    muestra lleva su propio `capture_session_us`: se retrasa la entrega, no se
    degrada la medida.
    """
    seguridad.verificar(lote.node_id, x_ricevi_token)

    esperados = set(censo.SENSORES_POR_NODO.get(lote.node_id, []))
    recibido_us = reloj.session_us()
    filas = []

    for mu in lote.muestras:
        # Un nodo solo puede publicar por los sensores que el censo le asigna.
        # Sin esto, un nodo mal provisionado podria escribir muestras a nombre
        # de otro sensor y falsear una variable operativa.
        if esperados and mu.sensor_id not in esperados:
            raise HTTPException(
                status_code=409,
                detail=f"{lote.node_id} no puede publicar por '{mu.sensor_id}'")

        filas.append((
            lote.session_id, lote.node_id, mu.sensor_id, mu.magnitud, lote.boot_id,
            mu.seq, mu.capture_mono_us, mu.capture_session_us, mu.ventana_us,
            mu.valor, mu.unidad, mu.calidad, mu.codigo_calidad, mu.calibration_id,
            mu.pulsos_ventana, mu.pulsos_acumulados, mu.pulsos_por_vuelta,
            mu.edad_ultimo_pulso_ms, mu.periodo_ultimo_us, mu.distancia_cruda_mm,
            mu.offset_b_mm, mu.tramas_descartadas, lote.sync_uncertainty_ms,
            recibido_us, lote.config_version or config.CONFIG_VERSION,
            lote.censo_version or censo.CENSO_VERSION))

    ids = basedatos.guardar_telemetria(filas)
    try:
        f = censo.ficha(lote.node_id)
        basedatos.tocar_nodo(lote.node_id, recibido_us, tipo=f["tipo"], rol=f["rol"])
    except KeyError:
        basedatos.tocar_nodo(lote.node_id, recibido_us)
    return contratos.RespuestaTelemetria(persistidas=len(ids), ids=ids,
                                         recibido_session_us=recibido_us)


@router.post("/events", status_code=201)
def recibir_evento(ev: contratos.Evento, x_ricevi_token: str = Header(default="")):
    seguridad.verificar(ev.node_id, x_ricevi_token)
    us = ev.session_us if ev.session_us is not None else reloj.session_us()
    # El latido es el evento mas frecuente y el menos interesante de guardar
    # uno a uno: solo actualiza la marca de "visto por ultima vez". Un nodo
    # ultrasonico averiado sigue enviando lotes invalidos, asi que el latido y
    # la telemetria dicen cosas distintas: la placa vive, el sensor no.
    # tipo y rol salen del censo, no del mensaje: es lo que permite que un nodo
    # que aun no se ha registrado aparezca igualmente en el HMI.
    try:
        f = censo.ficha(ev.node_id)
        tipo, rol = f["tipo"], f["rol"]
    except KeyError:
        tipo = rol = ""
    basedatos.tocar_nodo(ev.node_id, us, ev.bateria_mv, ev.rssi_dbm,
                         ev.heap_libre, ev.pendientes_en_sd, tipo, rol)
    if ev.tipo == "latido":
        return {"registrado": True, "session_us": us}
    basedatos.guardar_evento(ev.node_id, ev.tipo, ev.detalle, us, reloj.utc_iso())
    return {"registrado": True, "session_us": us}
