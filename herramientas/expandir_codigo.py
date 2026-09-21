"""
expandir_codigo.py - Inserta el codigo fuente real dentro de los .md de docs/.

POR QUE EXISTE
--------------
Los capitulos de la guia llevan el codigo completo. Si ese codigo estuviera
copiado a mano dentro del markdown, en cuanto arreglaras un fallo en
`referencia/` la guia quedaria mintiendo -- y no habria forma de notarlo.

Con marcadores, el markdown dice DONDE va cada archivo y este script pega el
contenido real en el momento de generar el documento. La guia no puede
desincronizarse del codigo porque no tiene una copia propia.

MARCADOR
--------
    <!--CODIGO: referencia/central/app/config.py | python-->

Genera `docs/generado/NN-*.md` con los marcadores sustituidos. Los originales
de `docs/` no se tocan.

USO
---
    .venv\\Scripts\\python.exe herramientas\\expandir_codigo.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
SALIDA = DOCS / "generado"

MARCADOR = re.compile(r"<!--CODIGO:\s*(?P<ruta>[^|]+?)\s*\|\s*(?P<leng>\w+)\s*-->")


def expandir(texto: str, origen: Path) -> tuple[str, list[str]]:
    avisos: list[str] = []

    def sustituir(m: re.Match) -> str:
        ruta = RAIZ / m.group("ruta").strip()
        leng = m.group("leng")
        if not ruta.exists():
            avisos.append(f"{origen.name}: NO EXISTE {ruta}")
            return f"> **FALTA EL ARCHIVO `{m.group('ruta')}`**"
        codigo = ruta.read_text(encoding="utf-8").rstrip()
        lineas = codigo.count("\n") + 1
        # Se antepone la ruta como titulo: al leer el PDF impreso, sin el no se
        # sabe en que archivo va cada bloque.
        return (f"**`{m.group('ruta').strip()}`**  ·  {lineas} líneas\n\n"
                f"```{leng}\n{codigo}\n```")

    return MARCADOR.sub(sustituir, texto), avisos


def main() -> int:
    SALIDA.mkdir(parents=True, exist_ok=True)
    todos_avisos: list[str] = []
    for md in sorted(DOCS.glob("*.md")):
        texto = md.read_text(encoding="utf-8")
        nuevo, avisos = expandir(texto, md)
        todos_avisos += avisos
        destino = SALIDA / md.name
        destino.write_text(nuevo, encoding="utf-8")
        n = len(MARCADOR.findall(texto))
        print(f"  {md.name:24s} {n} bloque(s) de código  ->  {destino.relative_to(RAIZ)}")

    if todos_avisos:
        print("\nAVISOS:")
        for a in todos_avisos:
            print("  " + a)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
