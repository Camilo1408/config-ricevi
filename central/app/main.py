"""
main.py - Arranque y parada ordenada de la central.

EL ORDEN DE ARRANQUE IMPORTA
----------------------------
  1. Verificar el censo. Si hay algo BLOQUEANTE, no se arranca. Es preferible
     que la central se niegue en el taller a descubrir en el arrozal que dos
     nodos comparten IP.
  2. Crear directorios y comprobar espacio.
  3. Cargar los tokens.
  4. Abrir la base y escribir el ACTA de la sesion, avisos incluidos.
  5. Arrancar salud -> GPS -> fusion -> inferencia.
  6. Solo entonces empezar a aceptar nodos.

El paso 4 antes que el 6 no es casual: si un frame llegara antes de que exista
la fila de sesion, quedaria huerfano de contexto y no habria forma de saber con
que configuracion se capturo.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI

from . import (basedatos, config, fusion, gps, inferencia, reloj, rutas_hmi,
               rutas_ingesta, rutas_nodos, salud, seguridad)

sys.path.insert(0, str(config.RAIZ))
from config import censo  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)-18s %(message)s",
    datefmt="%H:%M:%S")
log = logging.getLogger("ricevi")


def _nuevo_session_id() -> str:
    """R001, R002... y no un UUID.

    El session_id aparece en el frame_id, en los nombres de carpeta y en las
    conversaciones ("la R003 salio mal"). Un UUID seria ilegible y haria
    imposible teclear una ruta de memoria.
    """
    base = config.DIR_FRAMES
    existentes = []
    if base.exists():
        for d in base.iterdir():
            if d.is_dir() and d.name.startswith("R") and d.name[1:].isdigit():
                existentes.append(int(d.name[1:]))
    return f"R{(max(existentes) + 1) if existentes else 1:03d}"


def _acta(session_id: str) -> dict:
    """Instantanea completa de con que se capturo esta jornada."""
    return {
        "session_id": session_id,
        "inicio_utc": reloj.inicio_utc_iso(),
        "clock_epoch_id": reloj.CLOCK_EPOCH_ID,
        "utc_quality": reloj.calidad_utc(),
        "config": config.resumen(),
        "censo": censo.resumen(),
        "python": sys.version.split()[0],
    }


@asynccontextmanager
async def ciclo_vida(app: FastAPI):
    # --- 1. Censo ----------------------------------------------------------
    v = censo.verificar()
    for b in v["bloqueantes"]:
        log.error("CENSO BLOQUEANTE: %s", b)
    for a in v["avisos"]:
        log.warning("censo: %s", a)
    if not v["apto_para_arrancar"]:
        raise SystemExit(
            f"El censo tiene {len(v['bloqueantes'])} problema(s) bloqueante(s). "
            f"Corrige config/censo.py antes de arrancar.")

    # --- 2. Disco ----------------------------------------------------------
    config.asegurar_directorios()
    libre = config.espacio_libre_mb()
    log.info("Datos en %s, %d MB libres", config.DIR_DATOS, libre)
    if libre < config.RESERVA_MB:
        log.error("Solo %d MB libres, por debajo de la reserva de %d MB. "
                  "Se arranca SIN aceptar frames.", libre, config.RESERVA_MB)

    # --- 3. Tokens ---------------------------------------------------------
    n = seguridad.cargar()
    if config.EXIGIR_TOKEN and n == 0:
        raise SystemExit(
            f"No hay tokens en {config.RUTA_TOKENS} y la autenticacion esta "
            f"activa. Ejecuta herramientas/generar_tokens.py, o arranca con "
            f"RICEVI_EXIGIR_TOKEN=0 solo para pruebas de banco.")
    log.info("Tokens cargados: %d  (exigir=%s)", n, config.EXIGIR_TOKEN)

    # --- 4. Sesion y acta ---------------------------------------------------
    session_id = _nuevo_session_id()
    acta = _acta(session_id)
    basedatos.inicializar(
        session_id, reloj.CLOCK_EPOCH_ID, reloj.inicio_utc_iso(),
        censo.CENSO_VERSION, config.MODELO,
        json.dumps(acta, ensure_ascii=False, indent=2))

    rutas_nodos.SESION["id"] = session_id
    rutas_hmi.SESION["id"] = session_id

    log.info("Sesion %s | maquina %s | modelo '%s' | epoch %s",
             session_id, config.MACHINE_ID, config.MODELO, reloj.CLOCK_EPOCH_ID)
    if config.MODELO in ("ninguno", ""):
        log.info("FASE DE DATASET: se captura y no se infiere. "
                 "El HMI mostrara 'sin modelo', que es lo correcto.")

    # --- 5. Hilos -----------------------------------------------------------
    salud.salud.arrancar()
    gps.lector.arrancar(session_id)
    fusion.fusionador.arrancar(session_id)
    inferencia.motor.arrancar(session_id)

    basedatos.guardar_evento("RPI01", "sesion_inicio",
                             f"{session_id} modelo={config.MODELO}",
                             reloj.session_us(), reloj.utc_iso())

    _instalar_apagado(session_id)

    yield

    # --- parada ordenada ----------------------------------------------------
    log.info("Parando...")
    inferencia.motor.parar()
    fusion.fusionador.parar()
    gps.lector.parar()
    salud.salud.parar()
    basedatos.guardar_evento("RPI01", "sesion_fin", session_id,
                             reloj.session_us(), reloj.utc_iso())
    basedatos.cerrar_sesion(session_id, reloj.utc_iso())
    try:
        basedatos.conexion().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        log.exception("No se pudo consolidar el WAL")
    log.info("Sesion %s cerrada limpiamente", session_id)


def _instalar_apagado(session_id: str) -> None:
    """Vigila la senal de contacto de la maquina, si esta configurada.

    Al girar la llave, la central cierra archivos, consolida la base y apaga de
    forma ordenada. Sin esto, cortar la energia con escrituras en vuelo puede
    dejar la base inconsistente -- el fallo nuevo que introduce usar una Pi en
    lugar de un microcontrolador.
    """
    if not config.GPIO_CONTACTO:
        return
    try:
        from gpiozero import Button
    except ImportError:
        log.warning("GPIO_CONTACTO=%s pero falta gpiozero: apagado por llave "
                    "DESACTIVADO", config.GPIO_CONTACTO)
        return

    import os
    import threading

    def apagar():
        log.warning("Senal de contacto: apagado ordenado en %.0f s",
                    config.SEGUNDOS_GRACIA_APAGADO)
        basedatos.guardar_evento("RPI01", "apagado_por_contacto", session_id,
                                 reloj.session_us(), reloj.utc_iso())
        threading.Timer(config.SEGUNDOS_GRACIA_APAGADO,
                        lambda: os.kill(os.getpid(), signal.SIGTERM)).start()

    try:
        boton = Button(int(config.GPIO_CONTACTO), pull_up=True, bounce_time=0.2)
        boton.when_released = apagar
        log.info("Apagado por contacto vigilando GPIO %s", config.GPIO_CONTACTO)
        _instalar_apagado._boton = boton  # evita que lo recoja el GC
    except Exception:
        log.exception("No se pudo vigilar el GPIO de contacto")


app = FastAPI(title="RiceVi · central de campo", version=config.CONFIG_VERSION,
              lifespan=ciclo_vida)
app.include_router(rutas_nodos.router)
app.include_router(rutas_ingesta.router)
app.include_router(rutas_hmi.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=config.PUERTO, log_level="info")
