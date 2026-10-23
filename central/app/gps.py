"""
gps.py - La velocidad de avance, medida por el GPS USB de la central.

POR QUE GPS Y NO UN HALL EN LA RUEDA
------------------------------------
Hasta oct-2026 la velocidad salia de `NH02`, un Hall con imanes en la rueda. Se
retiro por dos razones. La mecanica: la rueda va metida en agua y lodo, y no
habia forma de que el iman y el sensor sobrevivieran una jornada. Y la de
medida: la rueda patina, se hunde y deforma el neumatico, asi que lo que daba
era una velocidad ESTIMADA, sin referencia con la que contrastarla.

El receptor (VK-162, chip u-blox 7) va por USB a la Pi, con la antena en el
techo de la cabina, y entrega la velocidad sobre el suelo calculada con el
desplazamiento Doppler. Mide lo que la maquina avanza de verdad, sin patinaje y
sin ninguna constante que medir con un metro.

COMO ENTRA EN LA BASE
---------------------
Como un sensor mas: filas de `telemetria` con node_id `RPI01` y sensor_id
`GPS01`, una por magnitud y por solucion (una por segundo). Asi la fusion, la
asociacion imagen-telemetria y la exportacion lo tratan igual que a los demas,
y `estado_maquina` sigue siendo regenerable desde `telemetria`.

  ground_speed            la velocidad que da el receptor, cruda
  ground_speed_filtrada   media movil de `ventana_filtro_s`, con umbral de
                          reposo. Es la que usa el reel index
  satelites, hdop         la calidad de la solucion, para poder filtrar despues

El instante de cada muestra es el reloj de la propia central al leer la trama:
no hay sincronia por red que hacer, solo la latencia de la trama, que se
declara en `sync_uncertainty_ms`.

LA POSICION NO SE GUARDA
------------------------
La trama trae latitud y longitud; se leen solo para validar la trama y se
descartan. En la base no queda donde estaba el lote. Es una decision de
proteccion de datos del proyecto, no una limitacion del receptor.

POR QUE SIN gpsd
----------------
gpsd haria lo mismo con un servicio mas que instalar, configurar y vigilar.
Aqui solo hace falta la velocidad de una trama por segundo, y leerla
directamente evita que dos programas se disputen el puerto.
"""

from __future__ import annotations

import collections
import glob
import logging
import sys
import threading
import time

from . import basedatos, config, reloj

sys.path.insert(0, str(config.RAIZ))
from config import censo  # noqa: E402

log = logging.getLogger("ricevi.gps")

NUDO_A_MPS = 1852.0 / 3600.0


# ---------------------------------------------------------------------------
# Tramas NMEA
# ---------------------------------------------------------------------------


def suma_valida(linea: str) -> bool:
    """Comprueba la suma de verificacion de una trama `$....*HH`.

    Una trama cortada por el USB o mezclada con otra tiene que descartarse y
    contarse, no interpretarse a medias: un campo de velocidad truncado ("1.")
    se leeria como un numero perfectamente creible.
    """
    if not linea.startswith("$") or "*" not in linea:
        return False
    cuerpo, _, suma = linea[1:].partition("*")
    calc = 0
    for c in cuerpo:
        calc ^= ord(c)
    try:
        return calc == int(suma[:2], 16)
    except ValueError:
        return False


def _float(x: str) -> float | None:
    try:
        return float(x) if x != "" else None
    except ValueError:
        return None


def parsear(linea: str) -> dict | None:
    """Interpreta las tramas que importan. Devuelve None si no sirve.

    RMC da la velocidad y si hay solucion; GGA, satelites y HDOP. El resto
    (GSA, GSV, GLL, VTG) se ignora: VTG repite la misma velocidad de RMC y
    usar las dos produciria dos muestras por solucion.
    """
    linea = linea.strip()
    if not suma_valida(linea):
        return {"tipo": "mala"} if linea.startswith("$") else None
    campos = linea[1:linea.index("*")].split(",")
    tipo = campos[0][-3:]

    if tipo == "RMC" and len(campos) >= 10:
        # $GPRMC,hhmmss,A,lat,N,lon,W,nudos,rumbo,ddmmyy,var,E[,modo]
        modo = campos[12] if len(campos) > 12 else ""
        valido = campos[2] == "A" and modo != "N"
        nudos = _float(campos[7])
        return {"tipo": "RMC", "valido": valido,
                "vel_mps": None if nudos is None else nudos * NUDO_A_MPS}

    if tipo == "GGA" and len(campos) >= 9:
        # $GPGGA,hhmmss,lat,N,lon,W,calidad,satelites,hdop,...
        cal = int(campos[6]) if campos[6].isdigit() else 0
        sats = int(campos[7]) if campos[7].isdigit() else None
        return {"tipo": "GGA", "fix": cal > 0, "satelites": sats,
                "hdop": _float(campos[8])}

    return None


# ---------------------------------------------------------------------------
# Lector
# ---------------------------------------------------------------------------


def buscar_puerto(preferido: str, patron: str) -> str | None:
    """El puerto del receptor.

    Con "auto" se busca por /dev/serial/by-id/, que lleva el fabricante en el
    nombre. NUNCA se toma /dev/ttyACM0 a ciegas: la ESP32-C6 tambien aparece
    como ttyACM0 al provisionarla desde la Pi.
    """
    if preferido and preferido != "auto":
        return preferido
    candidatos = sorted(glob.glob(f"/dev/serial/by-id/{patron}"))
    return candidatos[0] if candidatos else None


class LectorGPS:
    def __init__(self) -> None:
        self.cfg = dict(censo.GPS)
        self._hilo: threading.Thread | None = None
        self._parar = threading.Event()
        self._sesion = ""
        self._seq = 0
        self._ventana: collections.deque = collections.deque()
        self._gga: dict | None = None
        self._gga_us = 0
        self._malas_desde_ultima = 0
        # Estado visible en /api/status.
        self.puerto: str | None = None
        self.conectado = False
        self.motivo = "sin arrancar"
        self.tramas_ok = 0
        self.tramas_malas = 0
        self.soluciones = 0
        self.ultima: dict | None = None
        self.ultima_us: int | None = None

    # --- ciclo de vida -------------------------------------------------------

    def arrancar(self, session_id: str) -> None:
        self._sesion = session_id
        if not config.GPS_ACTIVO:
            self.motivo = "desactivado (RICEVI_GPS=0)"
            log.info("GPS desactivado: no habra velocidad de avance")
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="gps", daemon=True)
        self._hilo.start()

    def parar(self) -> None:
        self._parar.set()
        if self._hilo:
            self._hilo.join(timeout=3)

    def _bucle(self) -> None:
        try:
            import serial  # pyserial
        except ImportError:
            self.motivo = "falta pyserial"
            log.error("Falta pyserial: el GPS no se puede leer. "
                      "pip install -r central/requirements.txt")
            return

        while not self._parar.is_set():
            puerto = buscar_puerto(config.GPS_PUERTO, self.cfg["patron_by_id"])
            if puerto is None:
                self._marcar_caido("receptor no encontrado")
                self._parar.wait(5.0)
                continue
            try:
                with serial.Serial(puerto, self.cfg["baudios"], timeout=1.5) as sp:
                    self.puerto, self.conectado, self.motivo = puerto, True, "leyendo"
                    log.info("GPS en %s", puerto)
                    basedatos.guardar_evento("RPI01", "gps_conectado", puerto,
                                             reloj.session_us(), reloj.utc_iso())
                    while not self._parar.is_set():
                        crudo = sp.readline()
                        if crudo:
                            self.procesar_linea(crudo.decode("ascii", "replace"))
            except Exception as e:
                # Desenchufar el USB en marcha es lo esperable, no un fallo del
                # proceso: se registra y se vuelve a buscar el receptor.
                self._marcar_caido(f"{type(e).__name__}: {e}")
                self._parar.wait(5.0)

    def _marcar_caido(self, motivo: str) -> None:
        if self.conectado:
            log.warning("GPS perdido: %s", motivo)
            basedatos.guardar_evento("RPI01", "gps_perdido", motivo[:200],
                                     reloj.session_us(), reloj.utc_iso())
        self.conectado = False
        self.motivo = motivo

    # --- tramas --------------------------------------------------------------

    def procesar_linea(self, linea: str, ahora_us: int | None = None) -> int:
        """Procesa una trama. Devuelve cuantas muestras se guardaron.

        Esta separado del bucle de lectura para que prueba_humo.py pueda
        alimentarlo con tramas escritas a mano, sin receptor.
        """
        t = parsear(linea)
        if t is None:
            return 0
        if t["tipo"] == "mala":
            self.tramas_malas += 1
            self._malas_desde_ultima += 1
            return 0
        self.tramas_ok += 1
        ahora = reloj.session_us() if ahora_us is None else ahora_us
        if t["tipo"] == "GGA":
            self._gga, self._gga_us = t, ahora
            return 0
        return self._epoca(t, ahora)

    def _epoca(self, rmc: dict, ahora: int) -> int:
        """Una solucion del receptor: cuatro muestras con el mismo seq."""
        c = self.cfg
        self._seq += 1
        # La GGA de la misma solucion llega pegada a la RMC. Una de hace mas de
        # dos periodos ya es de otra solucion y no se usa.
        gga = self._gga if self._gga and ahora - self._gga_us < 2.5e6 * c["periodo_s"] else None
        hdop = gga["hdop"] if gga else None
        sats = gga["satelites"] if gga else None

        v = rmc["vel_mps"] if rmc["valido"] else None
        if v is None:
            cal, cod = "invalida", "sin_fix"
        elif v > 8.0:
            cal, cod = "invalida", "fuera_rango"
        elif hdop is not None and hdop > c["hdop_max"]:
            cal, cod = "dudosa", "hdop_alto"
        else:
            cal, cod = "buena", "ok"

        # Ventana de la filtrada: solo muestras usables, y solo las recientes.
        ventana_us = int(c["ventana_filtro_s"] * 1e6)
        if cal != "invalida":
            self._ventana.append((ahora, v))
        while self._ventana and ahora - self._ventana[0][0] > ventana_us:
            self._ventana.popleft()
        if cal == "invalida" or not self._ventana:
            # Sin solucion no hay velocidad, ni filtrada. No se arrastra la
            # media de hace unos segundos como si fuera de ahora.
            vf, calf, codf = None, "invalida", cod
        else:
            vf = sum(x for _, x in self._ventana) / len(self._ventana)
            calf, codf = cal, cod
            if vf < c["umbral_reposo_mps"]:
                vf, codf = 0.0, "reposo"

        mono = time.monotonic_ns() // 1000
        periodo_us = int(c["periodo_s"] * 1e6)
        malas, self._malas_desde_ultima = self._malas_desde_ultima, 0

        def fila(mag, valor, unidad, calidad, codigo, ventana):
            return (self._sesion, c["node_id"], c["sensor_id"], mag, self._sesion,
                    self._seq, mono, ahora, ventana, valor, unidad, calidad, codigo,
                    None, None, None, None, None, None, None, None, malas,
                    c["incertidumbre_ms"], ahora, config.CONFIG_VERSION,
                    censo.CENSO_VERSION)

        filas = [
            fila("ground_speed", v, "m/s", cal, cod, periodo_us),
            fila("ground_speed_filtrada", vf, "m/s", calf, codf, ventana_us),
        ]
        if gga:
            filas.append(fila("satelites", sats, "count",
                              "buena" if sats is not None else "invalida",
                              "ok" if sats is not None else "sin_fix", periodo_us))
            filas.append(fila("hdop", hdop, "1",
                              "buena" if hdop is not None and gga["fix"] else "invalida",
                              "ok" if hdop is not None and gga["fix"] else "sin_fix",
                              periodo_us))
        ids = basedatos.guardar_telemetria(filas)

        self.soluciones += 1
        self.ultima = {"fix": rmc["valido"], "ground_speed_mps": v,
                       "ground_speed_filtrada_mps": vf, "codigo": codf,
                       "satelites": sats, "hdop": hdop}
        self.ultima_us = ahora
        return len(ids)

    def estado(self) -> dict:
        ahora = reloj.session_us()
        return {
            "activo": config.GPS_ACTIVO,
            "modelo": self.cfg["modelo"],
            "puerto": self.puerto,
            "conectado": self.conectado,
            "motivo": self.motivo,
            "tramas_ok": self.tramas_ok,
            "tramas_malas": self.tramas_malas,
            "soluciones": self.soluciones,
            "ultima": self.ultima,
            "edad_s": None if self.ultima_us is None
                      else round((ahora - self.ultima_us) / 1e6, 1),
        }


lector = LectorGPS()
