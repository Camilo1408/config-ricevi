"""
exportar_dataset.py - Prepara una sesion para etiquetar y entrenar.

    python herramientas/exportar_dataset.py --sesion R003 --destino /media/dataset

QUE PRODUCE
-----------
    <destino>/R003/
      imagenes/CAM02/*.jpg        enlaces o copias de los originales
      manifiesto.csv              una fila por frame, con TODO su contexto
      manifiesto.jsonl            lo mismo en JSONL
      grupos.csv                  a que grupo pertenece cada frame
      RESUMEN.md                  que hay, que falta y que NO se puede publicar

POR QUE UN MANIFIESTO Y NO SOLO LAS IMAGENES
--------------------------------------------
Una carpeta con 28.000 JPEG no es un dataset: es una carpeta. Lo que la
convierte en dataset es saber, de cada imagen, en que instante se tomo, con que
velocidad y altura iba la maquina, con que ROI, con que calibracion y en que
pasada. Todo eso esta en la base y aqui se junta en una tabla.

LA COLUMNA `grupo` ES LA MAS IMPORTANTE
---------------------------------------
Separar entrenamiento, validacion y prueba AL AZAR sobre estos datos da
metricas infladas y falsas: dos frames consecutivos de la misma pasada son casi
la misma imagen, y si uno cae en entrenamiento y otro en prueba, el modelo ya
ha visto la respuesta. La division tiene que hacerse POR GRUPO -- lote, jornada
y pasada -- y esta columna es la que lo permite.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from config import censo  # noqa: E402

DATOS = Path(os.getenv("RICEVI_DIR_DATOS", "/datos/ricevi"))

CAMPOS = [
    "frame_id", "session_id", "camera_id", "tarea", "grupo",
    "capture_utc", "capture_session_us", "utc_quality", "sync_uncertainty_ms",
    "ruta_relativa", "bytes", "sha256", "ancho", "alto", "jpeg_calidad",
    "roi_version", "roi",
    "reel_rpm", "reel_rpm_edad_ms",
    "wheel_speed_mps", "wheel_speed_edad_ms",
    "altura_izq_mm", "altura_izq_edad_ms",
    "altura_der_mm", "altura_der_edad_ms",
    "altura_media_mm", "reel_index", "ri_estado",
    "contexto_completo", "nodos_ausentes",
    "config_version", "censo_version", "calibration_id",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sesion", required=True)
    ap.add_argument("--destino", required=True)
    ap.add_argument("--tolerancia-ms", type=float, default=100.0)
    ap.add_argument("--copiar", action="store_true",
                    help="copia los JPEG en vez de enlazarlos")
    a = ap.parse_args()

    bd = DATOS / "ricevi.db"
    if not bd.exists():
        print(f"No hay base en {bd}")
        return 1

    destino = Path(a.destino) / a.sesion
    (destino / "imagenes").mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(bd)
    con.row_factory = sqlite3.Row

    frames = con.execute(
        "SELECT * FROM frames WHERE session_id=? ORDER BY capture_session_us",
        (a.sesion,)).fetchall()
    if not frames:
        print(f"La sesion {a.sesion} no tiene frames")
        return 1

    tol_us = int(a.tolerancia_ms * 1000)
    filas: list[dict] = []
    sin_contexto = 0

    for f in frames:
        plan = censo.PLANES.get(f["camera_id"], {})

        # Contexto operativo mas cercano dentro de la tolerancia.
        e = con.execute(
            """SELECT * FROM estado_maquina
                WHERE session_us BETWEEN ? AND ?
             ORDER BY ABS(session_us - ?) LIMIT 1""",
            (f["capture_session_us"] - tol_us,
             f["capture_session_us"] + tol_us,
             f["capture_session_us"])).fetchone()
        em = dict(e) if e else {}
        if not em:
            sin_contexto += 1

        # El grupo. Sin pass_id explicito se usa el boot del nodo como
        # aproximacion de "tramo continuo de trabajo": es lo que hay, y es mejor
        # que no agrupar nada. Cuando el HMI registre pasadas, esto mejora solo.
        grupo = f"{a.sesion}-{f['camera_id']}-{f['boot_id']}"

        completo = all(em.get(c) is not None for c in
                       ("reel_rpm", "wheel_speed_mps",
                        "altura_izq_mm", "altura_der_mm"))

        filas.append({
            "frame_id": f["frame_id"], "session_id": f["session_id"],
            "camera_id": f["camera_id"], "tarea": plan.get("tarea", ""),
            "grupo": grupo,
            "capture_utc": f["capture_utc"] or "",
            "capture_session_us": f["capture_session_us"],
            "utc_quality": f["utc_quality"],
            "sync_uncertainty_ms": f["sync_uncertainty_ms"],
            "ruta_relativa": f["ruta"], "bytes": f["bytes"], "sha256": f["sha256"],
            "ancho": f["ancho"], "alto": f["alto"], "jpeg_calidad": f["jpeg_calidad"],
            "roi_version": plan.get("roi_version", ""),
            "roi": json.dumps(plan.get("roi", [])),
            "reel_rpm": em.get("reel_rpm"),
            "reel_rpm_edad_ms": em.get("reel_rpm_edad_ms"),
            "wheel_speed_mps": em.get("wheel_speed_mps"),
            "wheel_speed_edad_ms": em.get("wheel_speed_edad_ms"),
            "altura_izq_mm": em.get("altura_izq_mm"),
            "altura_izq_edad_ms": em.get("altura_izq_edad_ms"),
            "altura_der_mm": em.get("altura_der_mm"),
            "altura_der_edad_ms": em.get("altura_der_edad_ms"),
            "altura_media_mm": em.get("altura_media_mm"),
            "reel_index": em.get("reel_index"),
            "ri_estado": em.get("ri_estado", "sin_datos"),
            "contexto_completo": int(completo),
            "nodos_ausentes": em.get("nodos_ausentes", ""),
            "config_version": f["config_version"],
            "censo_version": f["censo_version"],
            "calibration_id": em.get("calibration_id", ""),
        })

        # Enlace duro por defecto: no duplica los octetos en disco y sigue
        # siendo el mismo archivo. Si el destino esta en otro sistema de
        # archivos, no se puede, y se copia.
        orig = DATOS / f["ruta"]
        dst = destino / "imagenes" / f["camera_id"] / f"{f['frame_id']}.jpg"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() and orig.exists():
            try:
                if a.copiar:
                    raise OSError
                os.link(orig, dst)
            except OSError:
                import shutil
                shutil.copy2(orig, dst)

    # --- manifiestos --------------------------------------------------------
    with open(destino / "manifiesto.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(filas)

    with open(destino / "manifiesto.jsonl", "w", encoding="utf-8") as fh:
        for r in filas:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    grupos: dict[str, int] = {}
    for r in filas:
        grupos[r["grupo"]] = grupos.get(r["grupo"], 0) + 1
    with open(destino / "grupos.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["grupo", "frames"])
        w.writerows(sorted(grupos.items()))

    # --- resumen honesto ----------------------------------------------------
    v = censo.verificar()
    por_camara: dict[str, int] = {}
    for r in filas:
        por_camara[r["camera_id"]] = por_camara.get(r["camera_id"], 0) + 1

    provisionales = [x for x in v["avisos"] if "PROVISIONAL" in x]

    with open(destino / "RESUMEN.md", "w", encoding="utf-8") as fh:
        fh.write(f"# Dataset {a.sesion}\n\n")
        fh.write(f"- Frames: **{len(filas)}**\n")
        for c, n in sorted(por_camara.items()):
            fh.write(f"  - {c}: {n}\n")
        fh.write(f"- Grupos distintos: **{len(grupos)}**\n")
        fh.write(f"- Con contexto operativo completo: "
                 f"**{sum(r['contexto_completo'] for r in filas)}** "
                 f"de {len(filas)}\n")
        fh.write(f"- Sin ningun contexto: {sin_contexto}\n\n")

        fh.write("## Como dividir en entrenamiento, validacion y prueba\n\n")
        fh.write("**Por la columna `grupo`, nunca al azar sobre las filas.** Dos "
                 "frames consecutivos de la misma pasada son casi la misma "
                 "imagen; si uno cae en entrenamiento y otro en prueba, el "
                 "modelo ya ha visto la respuesta y las metricas salen "
                 "infladas.\n\n")
        fh.write("```python\nfrom sklearn.model_selection import GroupShuffleSplit\n"
                 "# usar manifiesto['grupo'] como `groups`\n```\n\n")

        if provisionales:
            fh.write("## LO QUE NO SE PUEDE PUBLICAR CON ESTOS DATOS\n\n")
            fh.write("Las siguientes magnitudes se calcularon con constantes "
                     "**provisionales, sin medir**. Los valores crudos SI son "
                     "validos y la magnitud se puede recalcular cuando se midan, "
                     "pero tal cual no deben ir a la tesis:\n\n")
            for p in provisionales:
                fh.write(f"- {p}\n")
            fh.write("\n")
        else:
            fh.write("## Calibraciones\n\nTodas medidas. Las magnitudes "
                     "derivadas son publicables.\n\n")

        fh.write("## Trazabilidad\n\n")
        fh.write("Cada fila lleva `sha256`. Para comprobar que un JPEG no se "
                 "altero desde que salio de la camara:\n\n")
        fh.write("```bash\nsha256sum imagenes/CAM02/<frame_id>.jpg\n```\n")

    print(f"Exportado a {destino}")
    print(f"  {len(filas)} frames, {len(grupos)} grupos")
    print(f"  con contexto completo: {sum(r['contexto_completo'] for r in filas)}")
    if provisionales:
        print(f"  AVISO: {len(provisionales)} magnitud(es) con calibracion "
              f"provisional. Ver RESUMEN.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
