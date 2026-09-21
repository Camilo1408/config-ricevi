"""
reloj.py - La referencia temporal de la central.

TRES RELOJES, Y CONFUNDIRLOS ARRUINA LAS MEDIDAS
------------------------------------------------
  1. CIVIL (UTC). El que entiende una persona, pero puede SALTAR: cuando NTP
     corrige, puede retroceder. Un intervalo medido con el puede salir negativo.
  2. MONOTONICO de cada nodo. No salta, pero su cero es arbitrario y no tiene
     nada que ver con el cero de otro equipo.
  3. SESION de la central: microsegundos desde que arranco. Es el eje comun al
     que se convierte todo.

`capture_mono_us` es (2), `capture_session_us` es (3), `capture_utc` es (1).
Los tres se guardan porque cada uno responde a una pregunta distinta.

POR QUE perf_counter_ns Y NO monotonic_ns
-----------------------------------------
Medido en el portatil del proyecto: en Python 3.11 sobre Windows,
`time.monotonic()` no avanzo en 5000 llamadas consecutivas -- su granularidad es
de ~15,6 ms. Con ese reloj, un RTT de 4 ms se mide como 0 o como 15,6 ms y el
offset queda dominado por el error de cuantizacion. `perf_counter_ns` mide
0,1 us y tambien es monotonico. En Linux los dos son buenos, asi que usar
perf_counter en los dos extremos funciona en todas partes.

CLOCK_EPOCH_ID
--------------
Si la central se reinicia, su cero de sesion cambia y todos los offsets que los
nodos habian calculado dejan de valer. Este identificador cambia en cada
arranque: un nodo que recibe un epoch distinto sabe que debe volver a
sincronizar en vez de seguir aplicando una conversion invalida. Sin el, un
reinicio de la central corrompe en silencio las marcas de tiempo posteriores.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

_T0_PERF_NS = time.perf_counter_ns()
_T0_UTC = datetime.now(timezone.utc)

CLOCK_EPOCH_ID = "E-" + uuid.uuid4().hex[:8]


def session_us() -> int:
    """Microsegundos desde que arranco la central. Nunca retrocede."""
    return (time.perf_counter_ns() - _T0_PERF_NS) // 1000


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def inicio_utc_iso() -> str:
    return _T0_UTC.isoformat(timespec="milliseconds")


def session_us_a_utc(us: int) -> str:
    """Convierte un instante de sesion a hora civil.

    Suma al UTC de arranque en vez de leer el reloj civil en ese momento. Asi la
    conversion es consistente aunque NTP haya corregido entre medias: dos frames
    separados por 1 s de sesion siguen apareciendo separados por 1 s en UTC.
    """
    return (_T0_UTC + timedelta(microseconds=us)).isoformat(timespec="milliseconds")


def calidad_utc() -> str:
    """Estima si la hora civil de esta maquina es creible: 'ntp', 'rtc' o 'desconocida'.

    HONESTIDAD SOBRE ESTA FUNCION: en la Pi 5 con bateria de RTC y sin Internet
    devuelve 'rtc', que es correcto. Sin bateria y sin red devuelve
    'desconocida', y eso es exactamente lo que debe quedar escrito en cada
    registro. Un dato con hora dudosa marcado como dudoso es utilizable; uno
    marcado como bueno, no.
    """
    import shutil
    import subprocess

    if shutil.which("timedatectl"):
        try:
            salida = subprocess.run(
                ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                capture_output=True, text=True, timeout=2,
            ).stdout.strip().lower()
            if salida == "yes":
                return "ntp"
            if os.path.exists("/dev/rtc0") or os.path.exists("/dev/rtc"):
                return "rtc"
            return "desconocida"
        except Exception:
            return "desconocida"
    return "desconocida"
