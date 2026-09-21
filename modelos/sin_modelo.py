"""
sin_modelo.py - El motor de la fase de dataset. No calcula nada, y es lo correcto.

POR QUE ESTE ARCHIVO ES IMPORTANTE
----------------------------------
En el banco de pruebas habia un sustituto que calculaba el "ratio de verde" de
la imagen. Servia para medir la tuberia -- decodificar, recortar el ROI, contar
pixeles, guardar el resultado -- sin tener modelos. Como ejercicio de
infraestructura fue util.

En campo es peligroso, y conviene entender exactamente por que: **no falla**.
Devuelve un numero con la forma correcta, en el rango correcto, que aparece en
el HMI junto a la etiqueta "material util residual" y que acaba en una tabla de
la tesis. Nadie lo detecta mirando graficas, porque se comporta como un dato.

Asi que en campo el motor por defecto es este, y devuelve NULO.

    El HMI muestra "sin modelo". El operario ve que el sistema esta capturando
    y que todavia no diagnostica. Que es exactamente la verdad.

La tuberia se sigue ejercitando igual: el frame entra en la cola, se mide el
tiempo de espera, se registra el resultado. Lo unico que no hay es un numero
inventado.
"""

from __future__ import annotations

import time

from .base import Resultado


class SinModelo:
    nombre = "sin-modelo"
    version = "1.0.0"

    def cargar(self) -> None:
        return None

    def tareas(self) -> tuple[str, ...]:
        return ("acame", "post_corte", "tolva")

    def inferir(self, octetos: bytes, tarea: str,
                roi: tuple[float, float, float, float],
                roi_version: str) -> Resultado:
        # Se mide el tiempo aunque no se haga nada: asi la fase de dataset
        # produce la linea de base de latencia de la tuberia, contra la que se
        # comparara el coste real del modelo cuando llegue.
        t0 = time.perf_counter_ns()
        n = len(octetos)
        t1 = time.perf_counter_ns()
        return Resultado(
            estado="sin_modelo",
            porcentaje=None,
            ms_decodificar=(t1 - t0) / 1e6,
            extra={"tarea": tarea, "roi_version": roi_version, "bytes": n},
        )
