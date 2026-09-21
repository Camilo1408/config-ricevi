"""
fusion.py - El estado de la maquina, y lo que ningun nodo puede calcular solo.

EL PROBLEMA
-----------
`NH01` conoce las RPM del molinete. `NH02` conoce la velocidad de avance.
Ninguno de los dos puede calcular el reel index, porque cada uno tiene la mitad
de la formula y viven en placas distintas con relojes distintos.

    v_punta = 2 * pi * R * RPM / 60
    RI      = v_punta / v_rueda

Lo calcula la central emparejando las dos muestras mas cercanas en el tiempo, y
guarda CUANTO se separan (`ri_pairing_skew_ms`). Un reel index calculado con
muestras separadas dos segundos no es el mismo dato que uno con veinte
milisegundos, y quien analice despues tiene que poder distinguirlos.

POR QUE ES UNA TABLA DERIVADA
-----------------------------
`estado_maquina` se puede borrar y regenerar entera desde `telemetria`. Eso
significa que un error en esta logica no destruye nada: se corrige y se
recalcula. Por eso la fusion va aparte de la ingesta, y por eso la ingesta
nunca depende de que la fusion funcione.
"""

from __future__ import annotations

import logging
import math
import threading
import time

from . import basedatos, config, reloj

log = logging.getLogger("ricevi.fusion")

# Que magnitud de que sensor alimenta cada campo del estado.
FUENTES = {
    "reel_rpm":        ("HALL01", "reel_rpm"),
    "wheel_speed_mps": ("HALL02", "wheel_speed"),
    "altura_izq_mm":   ("US01", "header_height"),
    "altura_der_mm":   ("US02", "header_height"),
}


def _radio_molinete() -> float | None:
    """Radio efectivo del molinete, solo si esta MEDIDO.

    Si la constante sigue siendo provisional, se devuelve None y el reel index
    queda nulo con estado 'sin_calibrar'. Publicar un RI calculado con un radio
    inventado seria dar por medido algo que no lo esta.
    """
    from config import censo
    cal = censo.calibracion().get("sensores", {}).get("HALL01", {})
    if cal.get("radio_molinete_m__medido") is not True:
        return None
    return float(cal.get("radio_molinete_m", 0)) or None


def calcular_estado() -> dict:
    """Construye una fila de estado_maquina con lo mas reciente de cada sensor."""
    ahora = reloj.session_us()
    fila: dict = {"session_id": SESION["id"], "session_us": ahora}
    ausentes: list[str] = []
    calibration_ids: set[str] = set()

    crudos: dict[str, tuple[float, int] | None] = {}
    for campo, (sensor, magnitud) in FUENTES.items():
        m = basedatos.ultima_muestra(sensor, magnitud)
        if m is None or m["valor"] is None:
            fila[campo] = None
            fila[f"{campo.replace('_mps', '').replace('_mm', '')}_edad_ms"] = None
            crudos[campo] = None
            ausentes.append(sensor)
            continue
        edad_ms = int((ahora - m["capture_session_us"]) / 1000)
        fila[campo] = float(m["valor"])
        crudos[campo] = (float(m["valor"]), m["capture_session_us"])
        if m["calibration_id"]:
            calibration_ids.add(m["calibration_id"])

    # Los nombres de columna de edad no siguen un patron regular, asi que se
    # asignan a mano en vez de con una transformacion fragil.
    def edad(campo: str) -> int | None:
        c = crudos.get(campo)
        return None if c is None else int((ahora - c[1]) / 1000)

    fila["reel_rpm_edad_ms"] = edad("reel_rpm")
    fila["wheel_speed_edad_ms"] = edad("wheel_speed_mps")
    fila["altura_izq_edad_ms"] = edad("altura_izq_mm")
    fila["altura_der_edad_ms"] = edad("altura_der_mm")

    # --- alturas ------------------------------------------------------------
    # La media SOLO si las dos son validas. Promediar una altura con un hueco
    # daria un numero que parece una media del cabezal y es la altura de un
    # solo lado.
    izq, der = fila.get("altura_izq_mm"), fila.get("altura_der_mm")
    if izq is not None and der is not None:
        fila["altura_media_mm"] = (izq + der) / 2.0
        # La diferencia entre lados es un indicador util de inclinacion lateral
        # o de terreno irregular, y no cuesta nada guardarla.
        fila["altura_dif_mm"] = izq - der
    else:
        fila["altura_media_mm"] = None
        fila["altura_dif_mm"] = None

    # --- reel index ---------------------------------------------------------
    ri, skew, estado = None, None, "sin_datos"
    r = _radio_molinete()
    a, b = crudos.get("reel_rpm"), crudos.get("wheel_speed_mps")

    if r is None:
        estado = "sin_calibrar"
    elif a is None or b is None:
        estado = "missing_input"
    else:
        (rpm, t_rpm), (vel, t_vel) = a, b
        skew = int(abs(t_rpm - t_vel) / 1000)
        if skew > config.TOLERANCIA_EMPAREJAMIENTO_MS:
            # Las dos muestras existen pero estan demasiado separadas para
            # considerarlas simultaneas.
            estado = "stale_pair"
        elif vel < config.VELOCIDAD_MINIMA_RI:
            # Dividir entre una velocidad casi nula produce numeros enormes sin
            # sentido fisico. Es mejor no dar valor que dar uno absurdo.
            estado = "speed_too_low"
        else:
            v_punta = 2.0 * math.pi * r * rpm / 60.0
            ri = v_punta / vel
            estado = "valid"

    fila["reel_index"] = ri
    fila["ri_pairing_skew_ms"] = skew
    fila["ri_estado"] = estado
    fila["nodos_ausentes"] = ",".join(sorted(set(ausentes)))
    fila["calibration_id"] = ",".join(sorted(calibration_ids))
    return fila


# ---------------------------------------------------------------------------
# Hilo de fusion
# ---------------------------------------------------------------------------

SESION = {"id": ""}


class Fusionador:
    def __init__(self) -> None:
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()
        self.ultimo: dict | None = None
        self.calculados = 0

    def arrancar(self, session_id: str) -> None:
        SESION["id"] = session_id
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="fusion", daemon=True)
        self._hilo.start()
        log.info("Fusion en marcha cada %.1f s", config.PERIODO_FUSION_S)

    def parar(self) -> None:
        self._parar.set()
        if self._hilo:
            self._hilo.join(timeout=3)

    def _bucle(self) -> None:
        while not self._parar.is_set():
            inicio = time.monotonic()
            try:
                fila = calcular_estado()
                # Solo se guarda si hay al menos una magnitud. Sin esto, una
                # jornada con los sensores apagados llenaria la tabla de filas
                # vacias a dos por segundo.
                if any(fila.get(c) is not None for c in FUENTES):
                    basedatos.guardar_estado_maquina(fila)
                    self.calculados += 1
                self.ultimo = fila
            except Exception:
                # La fusion NUNCA debe tumbar el proceso: es derivada y
                # regenerable. La ingesta sigue aunque esto falle.
                log.exception("Fallo calculando el estado de maquina")
            espera = config.PERIODO_FUSION_S - (time.monotonic() - inicio)
            self._parar.wait(max(0.05, espera))

    def estado(self) -> dict:
        return {"calculados": self.calculados, "ultimo": self.ultimo}


fusionador = Fusionador()
