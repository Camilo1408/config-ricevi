"""
rutas_nodos.py - Coordinacion: registro, reloj, plan y turnos.

    POST /v1/nodes/register
    POST /v1/time/exchange
    GET  /v1/nodes/{node_id}/plan
    POST /v1/upload-slots
"""

from __future__ import annotations

import logging
import sys

from fastapi import APIRouter, Header, HTTPException, Request

from . import basedatos, config, contratos, reloj, salud, seguridad, turnos

sys.path.insert(0, str(config.RAIZ))
from config import censo  # noqa: E402

log = logging.getLogger("ricevi.nodos")
router = APIRouter(prefix="/v1", tags=["nodos"])

SESION = {"id": ""}


@router.post("/nodes/register", response_model=contratos.RespuestaRegistro)
def registrar(p: contratos.PeticionRegistro, peticion: Request,
              x_ricevi_token: str = Header(default="")):
    """El nodo se presenta y recibe sesion, plan y ranura de reloj.

    El nodo NO decide casi nada: el escalonamiento del reloj y el ritmo de
    captura no estan codificados en el firmware, se reciben aqui. Cambiar el
    ritmo de una camara es editar config/censo.py y reiniciar la central, no
    desmontar una caja del cabezal.
    """
    seguridad.verificar(p.node_id, x_ricevi_token)

    # Un node_id que no esta en el censo no entra. Si entrara, produciria datos
    # con un origen que no corresponde a ninguna posicion conocida de la
    # maquina, y al analizar no habria forma de saber que miraba.
    try:
        ficha = censo.ficha(p.node_id)
    except KeyError:
        raise HTTPException(status_code=403,
                            detail=f"'{p.node_id}' no figura en el censo")

    if p.tipo != ficha["tipo"]:
        raise HTTPException(
            status_code=409,
            detail=f"{p.node_id} dice ser '{p.tipo}' y el censo dice '{ficha['tipo']}'")

    plan = censo.plan_de(p.node_id)
    us = reloj.session_us()
    ip = peticion.client.host if peticion.client else ""

    basedatos.registrar_nodo(p.node_id, p.tipo, ficha["rol"], p.boot_id,
                             plan["ranura_indice"], ip, p.firmware,
                             p.motivo_reinicio, us)

    # El motivo de reinicio se guarda como evento aparte porque es la senal
    # temprana de un problema electrico. Un brownout y un watchdog son averias
    # distintas y no se pueden distinguir despues si no se anotan ahora.
    if p.motivo_reinicio:
        basedatos.guardar_evento(p.node_id, "arranque",
                                 f"boot_id={p.boot_id} motivo={p.motivo_reinicio}",
                                 us, reloj.utc_iso())

    log.info("Registro de %s desde %s (boot %s, motivo %s)",
             p.node_id, ip, p.boot_id, p.motivo_reinicio or "-")

    return contratos.RespuestaRegistro(
        session_id=SESION["id"],
        config_version=config.CONFIG_VERSION,
        censo_version=censo.CENSO_VERSION,
        clock_epoch_id=reloj.CLOCK_EPOCH_ID,
        ranura_indice=plan["ranura_indice"],
        ranura_offset_s=plan["ranura_offset_s"],
        ciclo_sync_s=plan["ciclo_sync_s"],
        plan=plan,
        servidor_session_us=us,
        modelo_activo=config.MODELO,
    )


@router.post("/time/exchange", response_model=contratos.RespuestaTiempo)
def intercambio_tiempo(p: contratos.PeticionTiempo,
                       x_ricevi_token: str = Header(default="")):
    """Intercambio de cuatro tiempos.

    `t2` se toma LO ANTES POSIBLE y `t3` LO MAS TARDE POSIBLE. Todo lo que
    ocurra entre medias -- validar, escribir en la base -- queda DENTRO del
    intervalo (t3 - t2), que es el termino que la formula del RTT resta. Si se
    tomaran los dos al principio, el trabajo de la central se contaria como
    tiempo de red y con la CPU cargada de inferencia el RTT medido seria falso.
    """
    t2 = reloj.session_us()
    seguridad.verificar(p.node_id, x_ricevi_token)

    # El resultado del intercambio anterior, que el nodo cuelga de esta
    # peticion. La central nunca podria conocer t4 de otra forma, porque lo mide
    # el nodo al recibir la respuesta.
    if p.t4_previo_us is not None and p.rtt_previo_us is not None:
        basedatos.completar_intercambio(p.node_id, p.t4_previo_us,
                                        p.offset_previo_us or 0, p.rtt_previo_us)

    basedatos.guardar_intercambio(p.node_id, p.t1_us, t2, t2, t2)
    basedatos.tocar_nodo(p.node_id, t2)

    t3 = reloj.session_us()
    return contratos.RespuestaTiempo(t2_us=t2, t3_us=t3,
                                     clock_epoch_id=reloj.CLOCK_EPOCH_ID)


@router.get("/nodes/{node_id}/plan")
def plan(node_id: str, x_ricevi_token: str = Header(default="")):
    seguridad.verificar(node_id, x_ricevi_token)
    try:
        p = censo.plan_de(node_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"'{node_id}' no esta en el censo")

    # El ritmo de inferencia que se devuelve es el EFECTIVO, ya con el factor
    # termico aplicado. Asi el nodo no tiene que saber nada de temperaturas: si
    # la Pi esta caliente, simplemente recibe un numero mayor.
    base = int(p.get("uno_de_cada_n_infiere", 1))
    p["uno_de_cada_n_infiere"] = salud.salud.uno_de_cada_n(base)
    p["estado_termico"] = salud.salud.estado_termico
    p["aceptando_frames"] = salud.salud.aceptando_frames
    return p


@router.post("/upload-slots", response_model=contratos.RespuestaTurno)
def pedir_turno(p: contratos.PeticionTurno, x_ricevi_token: str = Header(default="")):
    seguridad.verificar(p.node_id, x_ricevi_token)

    if p.bytes_estimados > config.MAX_BYTES_FRAME:
        # Se rechaza ANTES de conceder el turno: no tiene sentido ocupar el
        # medio con una transferencia que se va a rechazar al llegar.
        raise HTTPException(
            status_code=413,
            detail=f"{p.bytes_estimados} B supera el maximo de {config.MAX_BYTES_FRAME}")

    r = turnos.gestor.pedir(p.node_id)
    r["aceptando_frames"] = salud.salud.aceptando_frames
    return contratos.RespuestaTurno(**r)
