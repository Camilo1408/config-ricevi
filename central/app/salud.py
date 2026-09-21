"""
salud.py - El lazo termico y el guardian del disco.

EL LAZO QUE HAY QUE EVITAR
--------------------------
    CPU al 70 % sostenido -> sube la temperatura -> el SoC se estrangula a
    80 C -> cada inferencia tarda mas -> la cola crece -> CPU al 100 %
    intentando alcanzarla -> sube mas la temperatura

No se estabiliza solo. Una vez dentro, la unica salida es que baje la
temperatura ambiente o que se reduzca la carga, y la carga viene de imagenes
que siguen llegando.

LA RESPUESTA
------------
El sistema reduce su propia carga ANTES de que el hardware lo haga por el.
Degradar de forma deliberada es preferible a que el SoC baje la frecuencia,
porque asi se elige QUE se pierde.

    LA CAPTURA NUNCA SE DEGRADA POR TEMPERATURA. Solo el diagnostico.

La captura alimenta el dataset, que es el objetivo primario del proyecto y
consume muy poca CPU. La inferencia alimenta el diagnostico, que es util pero
recuperable: un frame no inferido sigue en el disco y puede procesarse despues.

EL GUARDIAN DEL DISCO
---------------------
Cuando quedan menos de RESERVA_MB, la central deja de aceptar frames y lo dice.
Es preferible parar la captura de forma visible a llenar el disco y que el
sistema empiece a fallar de maneras raras que nadie sabra diagnosticar.
"""

from __future__ import annotations

import logging
import threading
import time

from . import basedatos, config, reloj

log = logging.getLogger("ricevi.salud")

# Escalones. Cada uno multiplica el `uno_de_cada_n` de todas las camaras: con
# factor 2, una camara que inferia uno de cada 1 pasa a uno de cada 2.
ESCALONES = [
    # (temperatura minima, nombre, factor, inferencia activa)
    (config.TEMP_PROTECCION_C, "proteccion", 1,  False),
    (config.TEMP_CRITICO_C,    "critico",    4,  True),
    (config.TEMP_CALIENTE_C,   "caliente",   2,  True),
    (config.TEMP_CALIDO_C,     "calido",     1,  True),
    (-273.0,                   "nominal",    1,  True),
]


def leer_temperatura() -> float | None:
    """Temperatura del nucleo en grados. None si no se puede leer."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as fh:
            return int(fh.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def leer_throttled() -> str | None:
    """Palabra de estado del PMIC: dice si YA hubo estrangulamiento o subtension.

    Vale la pena guardarla aunque tengamos la temperatura: el bit de bajo
    voltaje es la senal temprana de un problema ELECTRICO, que es un fallo
    distinto y con otra solucion.
    """
    import shutil
    import subprocess
    if not shutil.which("vcgencmd"):
        return None
    try:
        r = subprocess.run(["vcgencmd", "get_throttled"],
                           capture_output=True, text=True, timeout=2)
        return r.stdout.strip().split("=")[-1] or None
    except Exception:
        return None


class Salud:
    def __init__(self) -> None:
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()
        self.temp_c: float | None = None
        self.throttled: str | None = None
        self.estado_termico = "nominal"
        self.factor_inferencia = 1
        self.inferencia_activa = True
        self.libre_mb = 0
        self.aceptando_frames = True
        self.motivo_rechazo = ""
        self._ultimo_estado = "nominal"
        self._ultimo_aviso_disco = ""

    # -- evaluacion ---------------------------------------------------------

    def _evaluar_temperatura(self) -> None:
        if not config.VIGILAR_TEMPERATURA:
            return
        self.temp_c = leer_temperatura()
        if self.temp_c is None:
            return

        for minimo, nombre, factor, activa in ESCALONES:
            if self.temp_c >= minimo:
                self.estado_termico = nombre
                self.factor_inferencia = factor
                self.inferencia_activa = activa
                break

        if self.estado_termico != self._ultimo_estado:
            # Cada cambio de escalon queda registrado. Un analisis posterior
            # tiene que poder explicar por que una jornada tiene huecos de
            # diagnostico, y sin el evento seria un misterio.
            detalle = (f"{self._ultimo_estado} -> {self.estado_termico} "
                       f"a {self.temp_c:.1f} C, factor x{self.factor_inferencia}, "
                       f"inferencia={'si' if self.inferencia_activa else 'PAUSADA'}")
            log.warning("Estado termico: %s", detalle)
            basedatos.guardar_evento("RPI01", "estado_termico", detalle,
                                     reloj.session_us(), reloj.utc_iso())
            self._ultimo_estado = self.estado_termico

    def _evaluar_disco(self) -> None:
        self.libre_mb = config.espacio_libre_mb()

        if self.libre_mb < config.RESERVA_MB:
            self.aceptando_frames = False
            self.motivo_rechazo = (f"quedan {self.libre_mb} MB, por debajo de la "
                                   f"reserva de {config.RESERVA_MB} MB")
            nivel = "disco_agotado"
        elif self.libre_mb < config.AVISO_MB:
            self.aceptando_frames = True
            self.motivo_rechazo = ""
            nivel = "disco_bajo"
        else:
            self.aceptando_frames = True
            self.motivo_rechazo = ""
            nivel = ""

        if nivel and nivel != self._ultimo_aviso_disco:
            detalle = f"{self.libre_mb} MB libres en {config.DIR_DATOS}"
            log.warning("%s: %s", nivel, detalle)
            basedatos.guardar_evento("RPI01", nivel, detalle,
                                     reloj.session_us(), reloj.utc_iso())
        self._ultimo_aviso_disco = nivel

    # -- ciclo de vida ------------------------------------------------------

    def arrancar(self) -> None:
        self._evaluar_disco()
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="salud", daemon=True)
        self._hilo.start()
        log.info("Vigilancia de salud cada %.1f s", config.PERIODO_SALUD_S)

    def parar(self) -> None:
        self._parar.set()
        if self._hilo:
            self._hilo.join(timeout=3)

    def _bucle(self) -> None:
        while not self._parar.is_set():
            try:
                self._evaluar_temperatura()
                self._evaluar_disco()
                self.throttled = leer_throttled()
            except Exception:
                log.exception("Fallo en la vigilancia de salud")
            self._parar.wait(config.PERIODO_SALUD_S)

    # -- consulta -----------------------------------------------------------

    def uno_de_cada_n(self, base: int) -> int:
        """Aplica el factor termico al ritmo de inferencia de una camara."""
        return max(1, base) * self.factor_inferencia

    def estado(self) -> dict:
        import psutil
        return {
            "temp_c": self.temp_c,
            "estado_termico": self.estado_termico,
            "factor_inferencia": self.factor_inferencia,
            "inferencia_activa": self.inferencia_activa,
            "throttled": self.throttled,
            "libre_mb": self.libre_mb,
            "reserva_mb": config.RESERVA_MB,
            "aceptando_frames": self.aceptando_frames,
            "motivo_rechazo": self.motivo_rechazo,
            "cpu_pct": psutil.cpu_percent(interval=None),
            "cpu_por_nucleo": psutil.cpu_percent(interval=None, percpu=True),
            "ram_pct": psutil.virtual_memory().percent,
        }


salud = Salud()
