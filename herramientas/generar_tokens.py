"""
generar_tokens.py - Un token por nodo, generado una sola vez.

    python herramientas/generar_tokens.py                  crea los que falten
    python herramientas/generar_tokens.py --rotar CAM02    renueva uno
    python herramientas/generar_tokens.py --rotar-todos    renueva los ocho

POR QUE EL ARCHIVO NO VA AL REPOSITORIO
---------------------------------------
Se escribe en el directorio de datos, no en el proyecto. Si estuviera
versionado, el primer `git push` publicaria las credenciales de los ocho nodos,
y a partir de ahi cualquiera con acceso al repositorio podria inyectar datos en
el dataset.

QUE PASA SI SE PIERDE
---------------------
Hay que regenerarlo y volver a provisionar los ocho nodos. Molesto, no grave.
Por eso el archivo se copia junto al respaldo de cada jornada: conservarlo
cuesta nada y perderlo cuesta una tarde de provisiones.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from config import censo  # noqa: E402

DESTINO = Path(os.getenv("RICEVI_TOKENS",
                         os.getenv("RICEVI_DIR_DATOS", "/datos/ricevi")) )
if DESTINO.is_dir() or not DESTINO.suffix:
    DESTINO = DESTINO / "tokens.json"


def cargar() -> dict:
    if DESTINO.exists():
        return json.loads(DESTINO.read_text(encoding="utf-8"))
    return {"generado_utc": "", "tokens": {}}


def guardar(d: dict) -> None:
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    d["generado_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    DESTINO.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    # Solo el dueno puede leerlo. En la Pi eso es el usuario que corre la
    # central; en Windows chmod no hace gran cosa, pero no estorba.
    try:
        DESTINO.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="Tokens por nodo de RiceVi")
    ap.add_argument("--rotar", metavar="NODE_ID", help="renueva el token de un nodo")
    ap.add_argument("--rotar-todos", action="store_true")
    ap.add_argument("--mostrar", action="store_true",
                    help="imprime los tokens (para provisionar a mano)")
    a = ap.parse_args()

    d = cargar()
    ids = [n["node_id"] for n in censo.NODOS]
    nuevos: list[str] = []

    if a.rotar_todos:
        for i in ids:
            d["tokens"][i] = secrets.token_hex(32)
            nuevos.append(i)
    elif a.rotar:
        if a.rotar not in ids:
            print(f"'{a.rotar}' no esta en el censo")
            return 1
        d["tokens"][a.rotar] = secrets.token_hex(32)
        nuevos.append(a.rotar)
    else:
        for i in ids:
            if i not in d["tokens"]:
                d["tokens"][i] = secrets.token_hex(32)
                nuevos.append(i)

    # Un token de un nodo que ya no existe en el censo es una credencial viva
    # que nadie vigila. Se avisa para que se borre a mano, no se borra solo:
    # podria ser un nodo que se va a reincorporar.
    sobrantes = [k for k in d["tokens"] if k not in ids]

    guardar(d)

    print(f"Archivo: {DESTINO}")
    print(f"Tokens en total: {len(d['tokens'])}")
    print(f"Nuevos o rotados: {len(nuevos)}" + (f"  -> {', '.join(nuevos)}" if nuevos else ""))
    if sobrantes:
        print(f"AVISO: hay tokens de nodos que no estan en el censo: {sobrantes}")
    if nuevos:
        print("\nHay que volver a provisionar esos nodos: sus tokens cambiaron.")
    if a.mostrar:
        print()
        for k, v in sorted(d["tokens"].items()):
            print(f"  {k}  {v}")
    else:
        print("\n(usa --mostrar para verlos; provisionar_nodo.py los lee solo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
