"""motor_tolva.py - El modelo de tolva sobre NCNN, compartido por el servicio web y la consola.

Recorre la imagen con el mismo teselado del notebook 09 (teselas solapadas de
512 x 512, probabilidad promediada en los solapes), así que el porcentaje que
se muestra es el mismo que se evaluó.

Antes de cargar, comprueba el SHA-256 de los pesos contra la ficha del modelo:
un .bin truncado por una copia interrumpida carga sin error y produce basura.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np

NARANJA = np.array([242, 140, 60], dtype=np.uint8)

# El modelo se entrenó con cuadros de 1080 x 1920. Una foto de celular en 4K
# muestra las hojas al doble de ancho de lo que el modelo vio, así que se reduce
# a ese lado largo antes de inferir.
LADO_LARGO_ENTRENAMIENTO = 1920


def posiciones(n: int, t: int) -> list[int]:
    return sorted(set(list(range(0, max(n - t, 0), t)) + [max(n - t, 0)]))


def superponer(img_u8: np.ndarray, mascara: np.ndarray) -> np.ndarray:
    out = img_u8.copy()
    out[mascara] = NARANJA
    return out


class ModeloTolva:
    def __init__(self, carpeta: Path | str, hilos: int = 4) -> None:
        import ncnn  # se importa aquí para que la página arranque aunque falte

        carpeta = Path(carpeta)
        self.carpeta = carpeta
        self.ficha = json.loads((carpeta / "ficha_modelo.json").read_text(encoding="utf-8"))
        param, binf = carpeta / "tolva_unet.ncnn.param", carpeta / "tolva_unet.ncnn.bin"
        for f in (param, binf):
            esperado = self.ficha["sha256"][f.name]
            if hashlib.sha256(f.read_bytes()).hexdigest() != esperado:
                raise ValueError(f"{f.name} no coincide con el SHA-256 de la ficha: no se usa")
        self.umbral = float(self.ficha["umbral"])
        self.tile = int(self.ficha["tile"])
        self.version = self.ficha["version"]
        self.sha256_bin = self.ficha["sha256"][binf.name]
        self._ncnn = ncnn
        self.net = ncnn.Net()
        self.net.opt.use_vulkan_compute = False
        self.net.opt.num_threads = hilos
        self.net.load_param(str(param))
        self.net.load_model(str(binf))
        # Precalentar: la primera pasada de cualquier motor tarda varias veces más
        # que las siguientes y daría una latencia que no representa nada.
        vacia = np.zeros((self.tile, self.tile, 3), dtype=np.uint8)
        for _ in range(2):
            self._tesela(vacia)

    def _tesela(self, t: np.ndarray) -> np.ndarray:
        ex = self.net.create_extractor()
        # from_pixels entrega la tesela RGB como float 0-255, que es lo que espera el modelo exportado.
        ex.input("in0", self._ncnn.Mat.from_pixels(np.ascontiguousarray(t), self._ncnn.Mat.PixelType.PIXEL_RGB,
                                                   self.tile, self.tile))
        _, m = ex.extract("out0")
        return np.array(m).reshape(self.tile, self.tile)

    def probabilidad(self, img_u8: np.ndarray) -> np.ndarray:
        H, W, _ = img_u8.shape
        t = self.tile
        acc = np.zeros((H, W), np.float32)
        cnt = np.zeros((H, W), np.float32)
        for y in posiciones(H, t):
            for x in posiciones(W, t):
                acc[y:y + t, x:x + t] += self._tesela(img_u8[y:y + t, x:x + t])
                cnt[y:y + t, x:x + t] += 1
        return acc / cnt

    def inferir(self, img_u8: np.ndarray) -> dict:
        """Devuelve la máscara y las cifras. La imagen debe medir al menos tile x tile."""
        H, W, _ = img_u8.shape
        if H < self.tile or W < self.tile:
            return {"estado": "no_evaluable", "motivo": f"imagen de {W}x{H}: debe medir al menos {self.tile}x{self.tile}"}
        t0 = time.perf_counter()
        mascara = self.probabilidad(img_u8) > self.umbral
        ms = (time.perf_counter() - t0) * 1000
        return {
            "estado": "valido",
            "mascara": mascara,
            "porcentaje": round(100 * float(mascara.mean()), 3),
            "pixeles_clase": int(mascara.sum()),
            "pixeles_total": int(mascara.size),
            "latencia_ms": round(ms),
            "teselas": len(posiciones(H, self.tile)) * len(posiciones(W, self.tile)),
        }

    def resumen(self) -> dict:
        f = self.ficha
        return {
            "version": self.version,
            "carpeta": self.carpeta.name,
            "sha256": self.sha256_bin[:12],
            "umbral": self.umbral,
            "tile": self.tile,
            "arquitectura": f.get("arquitectura"),
            "metricas_prueba_modelo": f.get("metricas_prueba_modelo"),
            "metricas_prueba_regla_color": f.get("metricas_prueba_regla_color"),
            "datos": {k: f.get("datos", {}).get(k) for k in ("origen", "particion", "fragmentos_anotados")},
            "limites": f.get("limites"),
        }


def reducir_a_escala(img_u8: np.ndarray) -> np.ndarray:
    """Lleva una imagen más grande que la de entrenamiento a su escala (lado largo 1920)."""
    from PIL import Image

    H, W, _ = img_u8.shape
    largo = max(H, W)
    if largo <= LADO_LARGO_ENTRENAMIENTO:
        return img_u8
    k = LADO_LARGO_ENTRENAMIENTO / largo
    return np.array(Image.fromarray(img_u8).resize((round(W * k), round(H * k)), Image.LANCZOS))
