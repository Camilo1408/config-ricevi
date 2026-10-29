"""app.py - Servicio de demostración del modelo de tolva, aparte de la central.

Corre en su propio proceso y puerto (8001) para no tocar la central (8000):
si se cae o se satura, la captura sigue igual. Es el «despliegue en sombra» de
modelos/README.md: el modelo corre al lado del sistema sin afectarlo.

Solo LEE los datos de la central (el último JPEG de la CAM04). No escribe en su
base, ni en su cola, ni en su carpeta de datos.

Variables de entorno:
    IA_DIR_MODELOS     carpeta con una subcarpeta por versión (v1, v2...)   [./modelos]
    IA_MODELO          versión que se carga al arrancar                     [la última por nombre]
    IA_DIR_REPETICION  cuadros para el modo repetición                      [./repeticion]
    IA_DIR_FRAMES      frames de la central (solo lectura)                  [/datos/ricevi/frames]
    IA_CAMARA          cámara de la tolva                                   [CAM04]
    IA_HILOS           hilos de NCNN                                        [4]

Arranque:
    uvicorn app:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import io
import os
import platform
import socket
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from PIL import Image, ImageOps

from motor_tolva import ModeloTolva, reducir_a_escala, superponer

RAIZ = Path(__file__).resolve().parent
DIR_MODELOS = Path(os.getenv("IA_DIR_MODELOS", RAIZ / "modelos"))
DIR_REPETICION = Path(os.getenv("IA_DIR_REPETICION", RAIZ / "repeticion"))
DIR_FRAMES = Path(os.getenv("IA_DIR_FRAMES", "/datos/ricevi/frames"))
CAMARA = os.getenv("IA_CAMARA", "CAM04")
HILOS = int(os.getenv("IA_HILOS", "4"))
MAX_BYTES_SUBIDA = 25 * 1024 * 1024
EXTENSIONES = {".jpg", ".jpeg", ".png"}

app = FastAPI(title="RiceVi · IA tolva (demo)")

# La landing (sistema-arroz-front) corre en el portátil del pitch y llama a esta API
# desde otro origen. Solo se aceptan orígenes locales y la landing publicada.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?|https://sistema-arroz-front\.vercel\.app)$",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_lock_modelo = threading.Lock()      # una inferencia a la vez: la CPU es de la central
_modelo: ModeloTolva | None = None
_motivo_sin_modelo = "no se ha cargado ningún modelo"
_cache: OrderedDict[str, dict] = OrderedDict()
_indice_repeticion = 0


def versiones() -> list[str]:
    if not DIR_MODELOS.is_dir():
        return []
    return sorted(p.name for p in DIR_MODELOS.iterdir() if (p / "ficha_modelo.json").exists())


def cargar(version: str | None) -> None:
    """Carga una versión. Si falla, el servicio queda en «sin modelo» y dice por qué."""
    global _modelo, _motivo_sin_modelo
    disponibles = versiones()
    version = version or (disponibles[-1] if disponibles else None)
    if not version:
        _modelo, _motivo_sin_modelo = None, f"no hay modelos en {DIR_MODELOS}"
        return
    try:
        _modelo = ModeloTolva(DIR_MODELOS / version, HILOS)
    except Exception as e:  # pesos ausentes, hash distinto, ncnn sin instalar...
        _modelo, _motivo_sin_modelo = None, f"{version}: {e}"


cargar(os.getenv("IA_MODELO") or None)


def _cuadros_repeticion() -> list[Path]:
    if not DIR_REPETICION.is_dir():
        return []
    return sorted(p for p in DIR_REPETICION.iterdir() if p.suffix.lower() in EXTENSIONES)


def _ultimo_cuadro_camara() -> Path | None:
    """El JPEG más reciente de la cámara de la tolva, en la sesión más reciente."""
    if not DIR_FRAMES.is_dir():
        return None
    sesiones = [d for d in DIR_FRAMES.iterdir() if (d / CAMARA).is_dir()]
    if not sesiones:
        return None
    carpeta = max(sesiones, key=lambda d: (d / CAMARA).stat().st_mtime) / CAMARA
    mejor, t_mejor = None, -1.0
    with os.scandir(carpeta) as it:
        for e in it:
            if e.name.endswith(".jpg") and e.is_file():
                t = e.stat().st_mtime
                if t > t_mejor:
                    mejor, t_mejor = Path(e.path), t
    return mejor


def _jpeg(arr: np.ndarray, escala: int = 1) -> bytes:
    im = Image.fromarray(arr)
    if escala > 1:
        im = im.resize((im.width * escala, im.height * escala), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "JPEG", quality=88)
    return b.getvalue()


def _zona_densa(mascara: np.ndarray, lado: int = 360, paso: int = 24) -> tuple[int, int]:
    """Esquina de la ventana lado x lado con más píxeles verdes (imagen integral).

    Solo sirve para el acercamiento de la pantalla: las hojas miden pocos píxeles
    y en la imagen completa no se alcanzan a ver. El porcentaje no cambia.
    """
    H, W = mascara.shape
    lado = min(lado, H, W)
    ii = np.pad(mascara.astype(np.int32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    ys = np.arange(0, H - lado + 1, paso)
    xs = np.arange(0, W - lado + 1, paso)
    Y, X = np.meshgrid(ys, xs, indexing="ij")
    suma = ii[Y + lado, X + lado] - ii[Y, X + lado] - ii[Y + lado, X] + ii[Y, X]
    k = np.unravel_index(int(suma.argmax()), suma.shape)
    if suma[k] == 0:
        return (H - lado) // 2, (W - lado) // 2
    return int(ys[k[0]]), int(xs[k[1]])


def _procesar(octetos: bytes, fuente: str, nombre: str) -> dict:
    base = {"fuente": fuente, "nombre": nombre, "hora": datetime.now().isoformat(timespec="seconds"),
            "porcentaje": None}
    if _modelo is None:
        return {**base, "estado": "sin_modelo", "motivo": _motivo_sin_modelo}
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(octetos))).convert("RGB")
    except Exception:
        return {**base, "estado": "error_decodificar"}
    rgb = reducir_a_escala(np.array(img))
    if not _lock_modelo.acquire(blocking=False):
        raise HTTPException(409, "el modelo está procesando otra imagen")
    try:
        modelo = _modelo
        r = modelo.inferir(rgb)
    finally:
        _lock_modelo.release()
    res = {**base, "estado": r["estado"], "ancho": rgb.shape[1], "alto": rgb.shape[0],
           "modelo": {"version": modelo.version, "sha256": modelo.sha256_bin[:12], "umbral": modelo.umbral}}
    if r["estado"] != "valido":
        return {**res, "motivo": r.get("motivo")}
    ident = uuid.uuid4().hex[:12]
    sup = superponer(rgb, r["mascara"])
    y0, x0 = _zona_densa(r["mascara"])
    lado = min(360, rgb.shape[0], rgb.shape[1])
    zona = (slice(y0, y0 + lado), slice(x0, x0 + lado))
    _cache[ident] = {"original": _jpeg(rgb), "resultado": _jpeg(sup),
                     "zoom_original": _jpeg(rgb[zona], 2), "zoom_resultado": _jpeg(sup[zona], 2)}
    while len(_cache) > 12:
        _cache.popitem(last=False)
    return {**res, "id": ident, "porcentaje": r["porcentaje"], "pixeles_clase": r["pixeles_clase"],
            "pixeles_total": r["pixeles_total"], "latencia_ms": r["latencia_ms"], "teselas": r["teselas"],
            "zona": {"x": x0, "y": y0, "lado": lado}}


@app.get("/")
def pagina():
    return FileResponse(RAIZ / "web" / "index.html")


@app.get("/api/estado")
def estado():
    ultimo = _ultimo_cuadro_camara()
    return {
        "modelo": _modelo.resumen() if _modelo else None,
        "sin_modelo": None if _modelo else _motivo_sin_modelo,
        "versiones": versiones(),
        "repeticion": len(_cuadros_repeticion()),
        "equipo": {"nombre": socket.gethostname(), "arquitectura": platform.machine()},
        "camara": {"id": CAMARA, "ultimo": ultimo.name if ultimo else None,
                   "edad_s": round(time.time() - ultimo.stat().st_mtime) if ultimo else None},
    }


@app.post("/api/modelo/{version}")
def cambiar_modelo(version: str):
    if version not in versiones():
        raise HTTPException(404, f"no existe la versión {version}")
    with _lock_modelo:
        cargar(version)
    return estado()


@app.post("/api/inferir/repeticion")
def inferir_repeticion():
    global _indice_repeticion
    cuadros = _cuadros_repeticion()
    if not cuadros:
        raise HTTPException(404, f"no hay cuadros en {DIR_REPETICION}")
    ruta = cuadros[_indice_repeticion % len(cuadros)]
    _indice_repeticion += 1
    return _procesar(ruta.read_bytes(), "repeticion", ruta.name)


@app.post("/api/inferir/camara")
def inferir_camara():
    ruta = _ultimo_cuadro_camara()
    if ruta is None:
        raise HTTPException(404, f"no hay cuadros de {CAMARA} en {DIR_FRAMES}")
    r = _procesar(ruta.read_bytes(), "camara", ruta.name)
    r["edad_s"] = round(time.time() - ruta.stat().st_mtime)
    return r


@app.post("/api/inferir/subir")
async def inferir_subir(foto: UploadFile = File(...)):
    octetos = await foto.read(MAX_BYTES_SUBIDA + 1)
    if len(octetos) > MAX_BYTES_SUBIDA:
        raise HTTPException(413, "la foto pesa más de 25 MB")
    # La inferencia tarda segundos: fuera del bucle de eventos, para que la página siga respondiendo.
    return JSONResponse(await run_in_threadpool(_procesar, octetos, "subida", foto.filename or "foto"))


@app.get("/api/imagen/{ident}/{tipo}.jpg")
def imagen(ident: str, tipo: str):
    if tipo not in ("original", "resultado", "zoom_original", "zoom_resultado") or ident not in _cache:
        raise HTTPException(404)
    return Response(_cache[ident][tipo], media_type="image/jpeg", headers={"Cache-Control": "no-store"})
