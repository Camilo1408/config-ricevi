"""
rutas_hmi.py - Lo que ve el operario y lo que consulta el analista.

LA EDAD ES PARTE DEL DATO
-------------------------
Ningun valor se devuelve solo: va con su antiguedad. Una altura de 30 cm medida
hace 100 ms y una medida hace 4 s son dos cosas distintas, y el operario tiene
que poder distinguirlas de un vistazo. Un HMI que muestra "30 cm" sin decir
cuando se midio invita a confiar en un dato vencido.

Y LA SEGUNDA REGLA
------------------
Un porcentaje NULO no se dibuja como cero. Se dibuja como "sin modelo" o "no
evaluable", segun el estado. Es la unica forma de que la fase de dataset no
produzca una pantalla llena de ceros que alguien acabe interpretando como
mediciones.
"""

from __future__ import annotations

import logging
import sys

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from . import basedatos, config, fusion, gps, inferencia, reloj, salud, seguridad, turnos

sys.path.insert(0, str(config.RAIZ))
from config import censo  # noqa: E402

log = logging.getLogger("ricevi.hmi")
router = APIRouter(tags=["hmi"])

SESION = {"id": ""}


@router.get("/", response_class=HTMLResponse)
def pantalla():
    ruta = config.DIR_WEB / "hmi.html"
    if not ruta.exists():
        return HTMLResponse("<h1>Falta central/web/hmi.html</h1>", status_code=500)
    return HTMLResponse(ruta.read_text(encoding="utf-8"))


@router.get("/salud")
def salud_simple():
    """Prueba de vida para el descubrimiento de los nodos.

    Es lo que los nodos consultan en cascada al arrancar. Responde 200 SOLO
    cuando el servicio esta operativo: que el puerto 8000 acepte una conexion
    TCP no significa que la central este lista, porque uvicorn escucha antes de
    que el motor este cargado.
    """
    return {"ok": True, "session_id": SESION["id"],
            "clock_epoch_id": reloj.CLOCK_EPOCH_ID,
            "modelo": config.MODELO,
            "aceptando_frames": salud.salud.aceptando_frames}


@router.get("/api/status")
def estado():
    """Todo el estado del sistema en una llamada."""
    ahora = reloj.session_us()

    nodos = basedatos.estado_nodos()
    esperados = {n["node_id"] for n in censo.NODOS}
    vistos = {n["node_id"] for n in nodos}
    for n in nodos:
        uv = n.get("ultimo_visto_us")
        n["edad_s"] = None if uv is None else round((ahora - uv) / 1e6, 1)
        # Un nodo que no da senales en 30 s esta caido a efectos practicos:
        # el latido es cada 10 s.
        n["en_linea"] = n["edad_s"] is not None and n["edad_s"] < 30
        try:
            n["etiqueta"] = censo.ficha(n["node_id"])["etiqueta"]
        except KeyError:
            n["etiqueta"] = n["node_id"]

        # Estado de la bateria del nodo. Se clasifica aqui y no en el navegador
        # para que el umbral viva en un solo sitio, el censo.
        mv = n.get("bateria_mv")
        b = censo.BATERIA
        if mv is None:
            n["bateria_estado"] = "sin_dato"
            n["bateria_pct"] = None
        else:
            n["bateria_estado"] = ("critico" if mv < b["critico_mv"]
                                   else "aviso" if mv < b["aviso_mv"]
                                   else "ok")
            # Porcentaje muy aproximado, lineal entre corte y plena carga. La
            # descarga de una Ni-MH no es lineal, asi que sirve para ver la tendencia
            # y NO para decidir si llega a fin de jornada: para eso esta la
            # autonomia estimada del censo.
            corte = b["tension_corte_v"] * 1000
            plena = b["tension_plena_v"] * 1000
            n["bateria_pct"] = max(0, min(100, round(
                100 * (mv - corte) / (plena - corte))))

    em = fusion.fusionador.ultimo or {}

    return {
        "session_id": SESION["id"],
        "utc": reloj.utc_iso(),
        "session_us": ahora,
        "machine_id": config.MACHINE_ID,
        "config_version": config.CONFIG_VERSION,
        "censo_version": censo.CENSO_VERSION,
        "utc_quality": reloj.calidad_utc(),
        "nodos": nodos,
        "nodos_ausentes": sorted(esperados - vistos),
        "bateria": {"umbrales": censo.BATERIA,
                    "autonomia": {r: censo.autonomia_estimada(r)
                                  for r in censo.CONSUMO}},
        "estado_maquina": em,
        "gps": gps.lector.estado(),
        "resultados": basedatos.resultado_por_camara(),
        "inferencia": inferencia.motor.estado(),
        "turnos": turnos.gestor.estado(),
        "salud": salud.salud.estado(),
        "seguridad": seguridad.estado(),
        "contadores": basedatos.contadores(),
    }


@router.get("/api/results/latest")
def ultimos(limite: int = 20):
    """Ultimos resultados, con su edad ya calculada."""
    ahora = reloj.session_us()
    filas = basedatos.resultado_por_camara()
    for f in filas:
        f["edad_s"] = round((ahora - f["capture_session_us"]) / 1e6, 1)
        # El HMI necesita saber si puede dibujar un numero o si tiene que
        # escribir un texto. Se decide aqui y no en el navegador, para que la
        # regla viva en un solo sitio.
        f["mostrar"] = ("numero" if f["estado"] == "valido" and f["porcentaje"] is not None
                        else f["estado"])
    return {"resultados": filas, "limite": limite,
            "modelo": config.MODELO,
            "vigencia_ms": config.VIGENCIA_INFERENCIA_MS}


@router.get("/api/maquina")
def maquina():
    """Estado operativo fusionado, con la edad de cada campo."""
    e = basedatos.ultimo_estado_maquina()
    if e is None:
        return {"disponible": False}
    d = dict(e)
    d["disponible"] = True
    d["edad_s"] = round((reloj.session_us() - d["session_us"]) / 1e6, 1)
    return d


@router.get("/api/frame/{frame_id}/asociacion")
def asociacion(frame_id: str):
    r = basedatos.asociar(frame_id, config.TOLERANCIA_ASOCIACION_MS)
    if not r.get("encontrado"):
        raise HTTPException(status_code=404, detail="frame no encontrado")
    return r


@router.get("/api/frame/{frame_id}/imagen")
def imagen(frame_id: str):
    """Devuelve el JPEG ORIGINAL, tal cual llego. Nunca recomprimido."""
    f = basedatos.frame(frame_id)
    if f is None:
        raise HTTPException(status_code=404, detail="frame no encontrado")
    ruta = config.DIR_DATOS / f["ruta"]
    if not ruta.exists():
        # 410 y no 404: el registro existe, el archivo ya no. Es una distincion
        # util al diagnosticar, porque significa que alguien borro datos.
        raise HTTPException(status_code=410, detail="el archivo ya no esta en disco")
    return FileResponse(ruta, media_type="image/jpeg")


@router.get("/api/sensores/salud")
def sensores_salud():
    """Tasa de cada codigo de calidad por sensor: dice a que nodo hay que ir.

    Una tasa de invalidas del 20 % no se puede arreglar sin saber si es
    `checksum` -- cableado, ruido, conector flojo -- o `fuera_rango` --
    geometria de montaje, vegetacion, terreno.
    """
    filas = basedatos.salud_sensores()
    por_sensor: dict[str, dict] = {}
    for f in filas:
        clave = f"{f['sensor_id']}.{f['magnitud']}"
        d = por_sensor.setdefault(clave, {"total": 0, "codigos": {}})
        d["codigos"][f["codigo_calidad"]] = f["n"]
        d["total"] += f["n"]
    for d in por_sensor.values():
        d["pct"] = {k: round(100.0 * v / d["total"], 1)
                    for k, v in d["codigos"].items()}
    return por_sensor


@router.get("/api/huecos/{camera_id}")
def huecos(camera_id: str):
    """Saltos en la secuencia de una camara: asi se detecta una perdida."""
    h = basedatos.huecos_secuencia(camera_id)
    perdidos = sum(x["salto"] - 1 for x in h)
    return {"camera_id": camera_id, "huecos": h, "frames_perdidos": perdidos}


@router.post("/api/exportar")
def exportar():
    conteo = basedatos.exportar_csv(config.DIR_EXPORT)
    return {"destino": str(config.DIR_EXPORT), "filas": conteo}
