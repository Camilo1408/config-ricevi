"""
inferencia.py - La cola acotada y el hilo que ejecuta los modelos.

LA DECISION DE DISENO MAS IMPORTANTE DEL SISTEMA ESTA AQUI
----------------------------------------------------------
    `encolar()` NUNCA bloquea. Si la cola esta llena, descarta y lo cuenta.

La ingesta llama a `encolar()` justo antes de responder 201 al nodo. Si esa
llamada pudiera bloquearse esperando sitio, un pico de carga de CPU se
propagaria hacia atras: la cola llena -> la ingesta esperando -> la camara sin
respuesta -> la camara sin capturar el siguiente frame. Un problema de
diagnostico se habria convertido en una perdida de dataset.

    Cuando el sistema se satura se pierde DIAGNOSTICO, nunca DATASET.

Y el descarte queda contado, que es lo que convierte una degradacion silenciosa
en un numero medible: `descartados_cola` es la respuesta honesta a "cabe el
modelo en esta CPU".

POR QUE HILOS Y NO PROCESOS
---------------------------
El trabajo pesado ocurre dentro de NCNN y de OpenCV, que liberan el GIL durante
el calculo. Un proceso aparte obligaria a copiar los octetos del JPEG por una
tuberia en cada frame y a gestionar su ciclo de vida, a cambio de un paralelismo
que estas bibliotecas ya dan.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import time
from pathlib import Path

from . import basedatos, config, reloj, salud

log = logging.getLogger("ricevi.inferencia")

sys.path.insert(0, str(config.RAIZ))
from modelos.base import Resultado  # noqa: E402


class Tarea:
    __slots__ = ("frame_id", "octetos", "tarea", "roi", "roi_version",
                 "encolado_us", "capture_us")

    def __init__(self, frame_id: str, octetos: bytes, tarea: str,
                 roi: tuple, roi_version: str, capture_us: int) -> None:
        self.frame_id = frame_id
        self.octetos = octetos
        self.tarea = tarea
        self.roi = roi
        self.roi_version = roi_version
        self.capture_us = capture_us
        self.encolado_us = reloj.session_us()


def _crear_modelo():
    """Elige el motor segun RICEVI_MODELO.

    Si el motor real falla al cargar -- faltan pesos, falta la biblioteca, el
    hash no cuadra -- se CAE AL MOTOR NULO en vez de tumbar el proceso. Es
    deliberado: perder el diagnostico es aceptable, perder la jornada de
    captura no.
    """
    from modelos.sin_modelo import SinModelo

    if config.MODELO in ("ninguno", "", "none"):
        log.info("Fase de dataset: no se cargan modelos")
        return SinModelo()

    if config.MODELO == "ncnn":
        from modelos.ncnn_segmentacion import NcnnSegmentacion
        try:
            m = NcnnSegmentacion(Path(config.DIR_MODELOS) / "pesos")
            m.cargar()
            log.info("Modelo NCNN '%s' cargado, tareas: %s", m.version, m.tareas())
            return m
        except Exception:
            log.exception("No se pudo cargar el modelo NCNN. "
                          "Se sigue capturando SIN diagnostico.")
            basedatos.guardar_evento(
                "RPI01", "modelo_no_cargado",
                "fallo cargando NCNN; el sistema sigue en fase de dataset",
                reloj.session_us(), reloj.utc_iso())
            return SinModelo()

    log.error("RICEVI_MODELO='%s' desconocido; se usa el motor nulo", config.MODELO)
    return SinModelo()


class Motor:
    def __init__(self) -> None:
        self.cola: queue.Queue[Tarea] = queue.Queue(maxsize=config.COLA_MAX)
        self.modelo = None
        self._hilos: list[threading.Thread] = []
        self._parar = threading.Event()
        self.session_id = ""
        # Contadores. Son el resultado experimental del sistema, no adorno.
        self.procesados = 0
        self.descartados_cola = 0
        self.descartados_vencidos = 0
        self.descartados_termico = 0
        self.errores = 0

    # -- ciclo de vida ------------------------------------------------------

    def arrancar(self, session_id: str) -> None:
        self.session_id = session_id
        self.modelo = _crear_modelo()
        self._parar.clear()
        for i in range(config.HILOS_INFERENCIA):
            h = threading.Thread(target=self._bucle, name=f"inferencia-{i}", daemon=True)
            h.start()
            self._hilos.append(h)
        log.info("Motor en marcha: %d hilo(s), cola de %d",
                 config.HILOS_INFERENCIA, config.COLA_MAX)

    def parar(self) -> None:
        self._parar.set()
        for h in self._hilos:
            h.join(timeout=5)

    # -- entrada ------------------------------------------------------------

    def encolar(self, frame_id: str, octetos: bytes, tarea: str,
                roi: tuple, roi_version: str, capture_us: int) -> bool:
        """Devuelve True si entro en la cola. NUNCA bloquea."""
        if not salud.salud.inferencia_activa:
            # Estado termico de proteccion: se pausa el diagnostico para que la
            # CPU baje. La captura no se toca.
            self.descartados_termico += 1
            return False
        try:
            self.cola.put_nowait(
                Tarea(frame_id, octetos, tarea, roi, roi_version, capture_us))
            return True
        except queue.Full:
            self.descartados_cola += 1
            return False

    # -- proceso ------------------------------------------------------------

    def _bucle(self) -> None:
        while not self._parar.is_set():
            try:
                t = self.cola.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._procesar(t)
            except Exception:
                self.errores += 1
                log.exception("Fallo procesando %s", t.frame_id)
            finally:
                self.cola.task_done()

    def _procesar(self, t: Tarea) -> None:
        inicio_us = reloj.session_us()
        espera_ms = (inicio_us - t.encolado_us) / 1000.0
        edad_ms = (inicio_us - t.capture_us) / 1000.0

        # Un frame que espero demasiado ya no sirve como diagnostico. Se
        # registra el resultado con estado 'vencido' en vez de descartarlo en
        # silencio: asi la tasa de vencidos es medible, y ese numero dice si el
        # sistema va sobrado o justo.
        if edad_ms > config.VIGENCIA_INFERENCIA_MS:
            self.descartados_vencidos += 1
            r = Resultado(estado="vencido", extra={"edad_ms": round(edad_ms, 1)})
        else:
            r = self.modelo.inferir(t.octetos, t.tarea, t.roi, t.roi_version)

        fin_us = reloj.session_us()
        basedatos.guardar_resultado({
            "frame_id": t.frame_id,
            "tarea": t.tarea,
            "modelo": self.modelo.nombre,
            "modelo_version": self.modelo.version,
            "porcentaje": r.porcentaje,
            "estado": r.estado,
            "clase": r.clase,
            "confianza": r.confianza,
            "pixeles_clase": r.pixeles_clase,
            "pixeles_roi": r.pixeles_roi,
            "roi_version": t.roi_version,
            "ruta_mascara": r.ruta_mascara,
            "encolado_session_us": t.encolado_us,
            "inicio_session_us": inicio_us,
            "fin_session_us": fin_us,
            "ms_espera_cola": round(espera_ms, 3),
            "ms_decodificar": round(r.ms_decodificar, 3),
            "ms_inferir": round(r.ms_inferir, 3),
            "ms_postproceso": round(r.ms_postproceso, 3),
            "temp_c": salud.salud.temp_c,
            "estado_termico": salud.salud.estado_termico,
        })
        self.procesados += 1

    # -- consulta -----------------------------------------------------------

    def estado(self) -> dict:
        return {
            "modelo": getattr(self.modelo, "nombre", "?"),
            "modelo_version": getattr(self.modelo, "version", "?"),
            "tareas": list(self.modelo.tareas()) if self.modelo else [],
            "cola_ocupada": self.cola.qsize(),
            "cola_maxima": config.COLA_MAX,
            "hilos": config.HILOS_INFERENCIA,
            "procesados": self.procesados,
            "descartados_cola": self.descartados_cola,
            "descartados_vencidos": self.descartados_vencidos,
            "descartados_termico": self.descartados_termico,
            "errores": self.errores,
        }


motor = Motor()
