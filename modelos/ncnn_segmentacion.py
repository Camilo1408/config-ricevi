"""
ncnn_segmentacion.py - El motor de la fase de inferencia, sobre NCNN.

POR QUE NCNN
------------
Medido y publicado sobre Raspberry Pi 5, con YOLO11n a 640x640:

    NCNN          93,9 ms
    ONNX         181,8 ms
    TensorFlow Lite  324,2 ms
    PyTorch      524,8 ms

Mas de cinco veces entre ejecutar el mismo modelo en PyTorch y en NCNN. Es la
optimizacion mas rentable de todo el sistema y no cuesta dinero.

QUE ESPERA ESTE ARCHIVO
-----------------------
Que en `modelos/pesos/` existan, por tarea, los dos archivos que produce la
exportacion a NCNN:

    pesos/post_corte.param   pesos/post_corte.bin
    pesos/tolva.param        pesos/tolva.bin
    pesos/acame.param        pesos/acame.bin

Y un `pesos/manifiesto.json` con la version, el hash y el tamano de entrada de
cada uno. Sin manifiesto no se carga: un modelo sin version no es trazable, y
un resultado que no se puede atribuir a una version concreta no sirve para
comparar dos jornadas.

LO QUE NO HACE ESTE ARCHIVO
---------------------------
No entrena, no exporta y no cuantiza. Eso ocurre en el PC, y el resultado se
copia aqui. Y una advertencia que hay que tener presente: **el modelo que se
evalua en el PC no es exactamente el que corre aqui.** Se ha exportado y
posiblemente cuantizado a enteros. Las metricas que van a la tesis tienen que
ser las del modelo exportado, o declarar ambas.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import numpy as np

from .base import Resultado

log = logging.getLogger("ricevi.modelo")


class NcnnSegmentacion:
    nombre = "ricevi-ncnn"

    def __init__(self, dir_pesos: Path) -> None:
        self.dir_pesos = Path(dir_pesos)
        self.version = "desconocida"
        self._redes: dict[str, object] = {}
        self._manifiesto: dict = {}
        self._cv2 = None
        self._ncnn = None

    # -- carga --------------------------------------------------------------

    def cargar(self) -> None:
        import cv2  # se importa aqui para no pagarlo en la fase de dataset
        self._cv2 = cv2

        man = self.dir_pesos / "manifiesto.json"
        if not man.exists():
            raise FileNotFoundError(
                f"falta {man}. Un modelo sin manifiesto no es trazable: "
                f"no se carga.")
        self._manifiesto = json.loads(man.read_text(encoding="utf-8"))
        self.version = self._manifiesto.get("version", "desconocida")

        try:
            import ncnn
        except ImportError as e:
            raise RuntimeError(
                "falta el paquete ncnn. Instalalo en la Pi o vuelve a "
                "RICEVI_MODELO=ninguno para seguir capturando dataset."
            ) from e
        self._ncnn = ncnn

        for tarea, info in self._manifiesto.get("tareas", {}).items():
            param = self.dir_pesos / info["param"]
            bin_ = self.dir_pesos / info["bin"]
            for r in (param, bin_):
                if not r.exists():
                    raise FileNotFoundError(f"falta {r} para la tarea '{tarea}'")

            # Verificar el hash NO es paranoia: un archivo de pesos truncado
            # por una copia interrumpida carga sin error y produce basura.
            esperado = info.get("sha256_bin")
            if esperado:
                real = hashlib.sha256(bin_.read_bytes()).hexdigest()
                if real != esperado:
                    raise ValueError(
                        f"el hash de {bin_.name} no coincide con el manifiesto")

            net = ncnn.Net()
            net.opt.use_vulkan_compute = False   # la Pi 5 no tiene GPU util aqui
            net.opt.num_threads = int(info.get("hilos", 3))
            net.load_param(str(param))
            net.load_model(str(bin_))
            self._redes[tarea] = net
            log.info("Modelo '%s' cargado (%s)", tarea, info.get("nota", ""))

        self._precalentar()

    def _precalentar(self) -> None:
        """Tres pasadas en vacio por tarea.

        La primera inferencia de cualquier motor tarda varias veces mas que las
        siguientes. Sin precalentar, el primer frame de cada jornada produce
        una medida de latencia que no representa nada y contamina los
        percentiles p95 y p99.
        """
        for tarea, info in self._manifiesto.get("tareas", {}).items():
            lado = int(info.get("entrada", 512))
            vacia = np.zeros((lado, lado, 3), dtype=np.uint8)
            for _ in range(3):
                try:
                    self._ejecutar(tarea, vacia)
                except Exception:
                    log.exception("Fallo precalentando '%s'", tarea)
                    break

    def tareas(self) -> tuple[str, ...]:
        return tuple(self._redes)

    # -- inferencia ---------------------------------------------------------

    def _ejecutar(self, tarea: str, bgr: np.ndarray) -> np.ndarray:
        """Pasada cruda por la red. Devuelve el mapa de clases por pixel."""
        info = self._manifiesto["tareas"][tarea]
        lado = int(info.get("entrada", 512))
        net = self._redes[tarea]

        mat = self._ncnn.Mat.from_pixels_resize(
            bgr.tobytes(), self._ncnn.Mat.PixelType.PIXEL_BGR,
            bgr.shape[1], bgr.shape[0], lado, lado)
        media = info.get("media", [0.0, 0.0, 0.0])
        escala = info.get("escala", [1 / 255.0, 1 / 255.0, 1 / 255.0])
        mat.substract_mean_normalize(media, escala)

        ex = net.create_extractor()
        ex.input(info.get("entrada_nombre", "in0"), mat)
        _, salida = ex.extract(info.get("salida_nombre", "out0"))
        logits = np.array(salida)               # (clases, alto, ancho)
        return logits.argmax(axis=0).astype(np.uint8)

    def inferir(self, octetos: bytes, tarea: str,
                roi: tuple[float, float, float, float],
                roi_version: str) -> Resultado:
        cv2 = self._cv2
        if tarea not in self._redes:
            return Resultado(estado="error_modelo",
                             extra={"motivo": f"tarea '{tarea}' sin modelo cargado"})

        # --- decodificar ---------------------------------------------------
        t0 = time.perf_counter_ns()
        bgr = cv2.imdecode(np.frombuffer(octetos, dtype=np.uint8), cv2.IMREAD_COLOR)
        t1 = time.perf_counter_ns()
        if bgr is None:
            return Resultado(estado="error_decodificar",
                             ms_decodificar=(t1 - t0) / 1e6)

        # --- recortar el ROI -----------------------------------------------
        # El porcentaje se calcula sobre la region de interes, no sobre el
        # encuadre completo: se excluyen maquina, cielo y zonas ocultas.
        # Recortar ANTES de inferir ademas ahorra CPU proporcionalmente al area
        # descartada, que en estas vistas no es poco.
        alto, ancho = bgr.shape[:2]
        x0, y0, x1, y1 = roi
        rx0, ry0 = int(x0 * ancho), int(y0 * alto)
        rx1, ry1 = int(x1 * ancho), int(y1 * alto)
        recorte = bgr[ry0:ry1, rx0:rx1]
        if recorte.size == 0:
            return Resultado(estado="roi_vacio", ms_decodificar=(t1 - t0) / 1e6)

        # --- inferir --------------------------------------------------------
        t2 = time.perf_counter_ns()
        try:
            mapa = self._ejecutar(tarea, recorte)
        except Exception as e:
            log.exception("Fallo el modelo '%s'", tarea)
            return Resultado(estado="error_modelo",
                             ms_decodificar=(t1 - t0) / 1e6,
                             extra={"motivo": str(e)})
        t3 = time.perf_counter_ns()

        # --- porcentaje ------------------------------------------------------
        info = self._manifiesto["tareas"][tarea]
        clase_objetivo = int(info.get("clase_objetivo", 1))
        clase_ignorar = info.get("clase_ignorar")

        if clase_ignorar is None:
            validos = mapa.size
        else:
            # Los pixeles marcados como ignorados NO entran en el denominador.
            # Meterlos diluiria el porcentaje de forma distinta en cada imagen,
            # segun cuanta maquina o cielo se colara en el encuadre.
            validos = int((mapa != int(clase_ignorar)).sum())

        objetivo = int((mapa == clase_objetivo).sum())
        t4 = time.perf_counter_ns()

        if validos == 0:
            # Sin pixeles validos el resultado es NULO, no cero.
            return Resultado(estado="roi_vacio",
                             pixeles_clase=objetivo, pixeles_roi=0,
                             ms_decodificar=(t1 - t0) / 1e6,
                             ms_inferir=(t3 - t2) / 1e6,
                             ms_postproceso=(t4 - t3) / 1e6)

        return Resultado(
            estado="valido",
            porcentaje=round(100.0 * objetivo / validos, 3),
            pixeles_clase=objetivo,
            pixeles_roi=validos,
            ms_decodificar=(t1 - t0) / 1e6,
            ms_inferir=(t3 - t2) / 1e6,
            ms_postproceso=(t4 - t3) / 1e6,
            extra={"tarea": tarea, "roi_version": roi_version,
                   "modelo_version": self.version},
        )
