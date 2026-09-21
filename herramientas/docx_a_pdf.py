"""
docx_a_pdf.py - Exporta los .docx a .pdf usando Word por COM.

POR QUE WORD Y NO UNA LIBRERIA
------------------------------
En esta maquina no hay pandoc ni LibreOffice, pero si Word 16.0, accesible por
COM. Y tiene una ventaja sobre cualquier conversor: el PDF que produce es
EXACTAMENTE lo que veras al abrir el .docx, porque es el mismo motor de
composicion. Con otro conversor tendrias dos maquetaciones distintas del mismo
documento y no sabrias cual es la buena.

REQUISITO
    pip install pywin32

USO
    .venv\\Scripts\\python.exe herramientas\\docx_a_pdf.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETA = RAIZ / "docs" / "entregables"

# 17 es wdFormatPDF en la enumeracion WdSaveFormat de Word.
WD_FORMATO_PDF = 17


def main() -> int:
    try:
        import win32com.client as com
    except ImportError:
        print("Falta pywin32.  Instálalo con:")
        print("    .venv\\Scripts\\python.exe -m pip install pywin32")
        return 1

    docs = sorted(CARPETA.glob("*.docx"))
    if not docs:
        print(f"No hay .docx en {CARPETA}. Ejecuta antes md_a_docx.py")
        return 1

    word = com.Dispatch("Word.Application")
    word.Visible = False
    # Sin esto, un aviso de Word (por ejemplo "fuente no disponible") abre un
    # cuadro de dialogo que espera un clic. Como Word es invisible, el script
    # se quedaria colgado para siempre sin decir por que.
    word.DisplayAlerts = False

    codigo = 0
    try:
        for d in docs:
            pdf = d.with_suffix(".pdf")
            print(f"  {d.name} ...", end="", flush=True)
            doc = word.Documents.Open(str(d), ReadOnly=True)
            try:
                # Repagina antes de exportar: si no, los numeros de pagina y
                # los saltos pueden salir de una composicion anterior.
                doc.Repaginate()
                paginas = doc.ComputeStatistics(2)  # wdStatisticPages
                doc.SaveAs(str(pdf), FileFormat=WD_FORMATO_PDF)
                print(f" {paginas} páginas -> {pdf.name} "
                      f"({pdf.stat().st_size/1024:,.0f} KB)")
            finally:
                doc.Close(False)
    except Exception as e:  # noqa: BLE001
        print(f"\nFALLO: {e}")
        codigo = 1
    finally:
        word.Quit()
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
