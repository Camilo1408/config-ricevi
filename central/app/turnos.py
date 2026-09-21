"""
turnos.py - Control de admision de subidas.

POR QUE EXISTE
--------------
Ocho nodos comparten un unico canal de 2,4 GHz. Si las cuatro camaras suben a
la vez, no van cuatro veces mas rapido: compiten, colisionan, retransmiten, y
las cuatro tardan mas que si hubieran ido en fila. Serializar las subidas es lo
que convierte un medio compartido en un recurso previsible.

Y hay un segundo efecto, menos obvio y mas importante: mientras las camaras
compiten, la TELEMETRIA tambien compite. Los nodos de sensor no piden turno --
su trafico es pequeno -- pero si el aire esta saturado por cuatro JPEG
simultaneos, sus lotes se retrasan. El turno protege tambien el dato que da
contexto a las imagenes.

LA CADUCIDAD NO ES OPCIONAL
---------------------------
Si un nodo pide turno y se cuelga, se queda sin bateria o pierde el enlace,
sin caducidad bloquearia a los demas para siempre. El turno se libera solo.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from . import config

log = logging.getLogger("ricevi.turnos")


class GestorTurnos:
    def __init__(self, maximo: int, duracion_s: float) -> None:
        self.maximo = maximo
        self.duracion_s = duracion_s
        self._lock = threading.Lock()
        self._activos: dict[str, tuple[str, float]] = {}   # turno_id -> (node_id, vence)
        # Contadores que alimentan el HMI y el analisis posterior. La tasa de
        # denegaciones es la medida directa de si el enlace da abasto.
        self.concedidos = 0
        self.denegados = 0
        self.caducados = 0

    def _barrer(self, ahora: float) -> None:
        """Libera los turnos vencidos. Se llama con el lock tomado."""
        vencidos = [t for t, (_, v) in self._activos.items() if v <= ahora]
        for t in vencidos:
            node_id, _ = self._activos.pop(t)
            self.caducados += 1
            log.warning("Turno caducado de %s (%s)", node_id, t[:8])

    def pedir(self, node_id: str) -> dict:
        ahora = time.monotonic()
        with self._lock:
            self._barrer(ahora)

            # Un nodo que vuelve a pedir turno teniendo uno abierto es un nodo
            # que se reinicio a mitad de subida. Se le devuelve el suyo en vez
            # de acumular turnos fantasma que ocupan cupo hasta caducar.
            for t, (n, v) in self._activos.items():
                if n == node_id:
                    return {"concedido": True, "turno_id": t,
                            "caduca_en_s": round(v - ahora, 2),
                            "en_uso": len(self._activos), "maximo": self.maximo}

            if len(self._activos) >= self.maximo:
                self.denegados += 1
                # Retroceso con jitter calculado en el nodo a partir de esta
                # base. Sin jitter, cuatro camaras denegadas reintentan en el
                # mismo milisegundo y reproducen la colision.
                return {"concedido": False,
                        "reintentar_en_ms": config.REINTENTO_BASE_MS,
                        "en_uso": len(self._activos), "maximo": self.maximo}

            turno_id = uuid.uuid4().hex
            self._activos[turno_id] = (node_id, ahora + self.duracion_s)
            self.concedidos += 1
            return {"concedido": True, "turno_id": turno_id,
                    "caduca_en_s": self.duracion_s,
                    "en_uso": len(self._activos), "maximo": self.maximo}

    def liberar(self, turno_id: str | None) -> None:
        """Se llama cuando el ultimo octeto ya esta en disco, no antes.

        El turno protege el medio radio, y el medio sigue ocupado hasta que la
        transferencia termina.
        """
        if not turno_id:
            return
        with self._lock:
            self._activos.pop(turno_id, None)

    def estado(self) -> dict:
        with self._lock:
            self._barrer(time.monotonic())
            return {"en_uso": len(self._activos), "maximo": self.maximo,
                    "concedidos": self.concedidos, "denegados": self.denegados,
                    "caducados": self.caducados,
                    "nodos": [n for n, _ in self._activos.values()]}


gestor = GestorTurnos(config.TURNOS_SIMULTANEOS, config.TURNO_SEGUNDOS)
