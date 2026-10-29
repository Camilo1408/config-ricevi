"""Inferencia del modelo de tolva por consola (Raspberry Pi o PC).

Usa el mismo motor que el servicio web (motor_tolva.py). Por cada imagen guarda
la superposición en naranja y un JSON con el resultado, el umbral y el SHA-256
del modelo.

Uso:
    python inferir_tolva.py --modelo modelos/v1 --entrada repeticion/ --salida resultados/
    python inferir_tolva.py ... --repetir 3     (recorre la carpeta en bucle, una imagen cada 3 s)
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from motor_tolva import ModeloTolva, reducir_a_escala, superponer


def procesar(modelo, ruta, salida):
    img = reducir_a_escala(np.array(ImageOps.exif_transpose(Image.open(ruta)).convert("RGB")))
    r = modelo.inferir(img)
    res = {"imagen": ruta.name, "hora": datetime.now().isoformat(timespec="seconds"), "estado": r["estado"],
           "verde_visible_pct": r.get("porcentaje"), "latencia_ms": r.get("latencia_ms"), "umbral": modelo.umbral,
           "modelo_version": modelo.version, "modelo_sha256": modelo.sha256_bin[:12],
           "indicador": "material vegetal verde visible en la superficie (fracción de área, no masa)"}
    if r["estado"] == "valido":
        Image.fromarray(superponer(img, r["mascara"])).save(salida / f"{ruta.stem}_resultado.jpg", quality=90)
    (salida / f"{ruta.stem}_resultado.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (salida / "ultimo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", required=True, help="carpeta con tolva_unet.ncnn.param/.bin y ficha_modelo.json")
    ap.add_argument("--entrada", required=True, help="una imagen o una carpeta de imágenes")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--hilos", type=int, default=4)
    ap.add_argument("--repetir", type=float, default=0, help="segundos entre imágenes en modo repetición (0 = una pasada)")
    a = ap.parse_args()

    salida = Path(a.salida)
    salida.mkdir(parents=True, exist_ok=True)
    try:
        modelo = ModeloTolva(a.modelo, a.hilos)
    except FileNotFoundError:
        (salida / "ultimo.json").write_text(json.dumps({"estado": "sin_modelo"}, ensure_ascii=False), encoding="utf-8")
        raise SystemExit("sin modelo: no se encontró el modelo; no se muestra ningún número")
    entrada = Path(a.entrada)
    imagenes = [entrada] if entrada.is_file() else sorted(
        p for p in entrada.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    print(f"Modelo {modelo.version} · sha256 {modelo.sha256_bin[:12]} · umbral {modelo.umbral} · {len(imagenes)} imágenes")
    while True:
        for ruta in imagenes:
            r = procesar(modelo, ruta, salida)
            pct = "—" if r["verde_visible_pct"] is None else f"{r['verde_visible_pct']:.2f} %"
            print(f"{r['imagen']}: {r['estado']} · verde visible {pct} · {r['latencia_ms']} ms")
            if a.repetir:
                time.sleep(a.repetir)
        if not a.repetir:
            break


if __name__ == "__main__":
    main()
