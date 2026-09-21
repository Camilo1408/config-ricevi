"""
md_a_docx.py - Convierte los capitulos de docs/generado/ a .docx.

POR QUE UN SCRIPT PROPIO Y NO PANDOC
------------------------------------
En esta maquina no hay pandoc, y python-docx si. Ademas, un conversor propio
permite controlar lo que de verdad importa en este documento: que los bloques
de codigo no se partan de mala manera, que las tablas quepan, y que las
imagenes de los diagramas se escalen al ancho util de la pagina.

QUE SOPORTA
-----------
  # ## ### ####      titulos
  **negrita** *cursiva* `codigo` [texto](url)
  ```lenguaje       bloques de codigo con sombreado
  | tablas |        con fila de separacion
  > citas
  - listas, 1. numeradas, - [ ] casillas
  ![alt](ruta)      imagenes, escaladas al ancho util
  ---               separador
  $$ ... $$         formulas, centradas en cursiva

USO
---
    .venv\\Scripts\\python.exe herramientas\\md_a_docx.py
    .venv\\Scripts\\python.exe herramientas\\md_a_docx.py --solo 02
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "docs" / "generado"
SALIDA = RAIZ / "docs" / "entregables"

# Paleta. Coincide con la de las figuras para que el documento se lea como una
# sola pieza y no como partes pegadas.
AZUL = RGBColor(0x1D, 0x4E, 0xD8)
TINTA = RGBColor(0x0B, 0x0B, 0x0B)
TINTA2 = RGBColor(0x52, 0x51, 0x4E)
CODIGO_FONDO = "F4F4F2"
CITA_FONDO = "EEF3FB"


def empieza_bloque(desnudo: str, cruda: str) -> bool:
    """True si esta linea abre un bloque distinto de un parrafo.

    La usa el acumulador de parrafos para saber donde cortar. Tiene que
    reconocer TODO lo que el bucle principal trata por separado: si se olvida
    un caso, ese bloque acabaria absorbido dentro del parrafo anterior.
    """
    return bool(
        desnudo.startswith("```")
        or desnudo.startswith("$$")
        or desnudo.startswith("|")
        or desnudo.startswith(">")
        or desnudo.startswith("#")
        or re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", desnudo)
        or re.match(r"^-{3,}$", desnudo)
        or re.match(r"^(\s*)([-*]|\d+\.)\s+", cruda)
    )
CABECERA_FONDO = "E8EDF6"

ANCHO_UTIL_CM = 21.0 - 2.0 - 2.0  # A4 menos margenes


# ---------------------------------------------------------------------------
# Utilidades de bajo nivel sobre el XML de Word
# ---------------------------------------------------------------------------


def sombrear(elemento, color_hex: str) -> None:
    """Aplica un color de fondo a un parrafo o a una celda.

    python-docx no expone el sombreado, asi que hay que insertar el elemento
    <w:shd> a mano en las propiedades. Es la unica forma.
    """
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color_hex)
    elemento.get_or_add_pPr().append(shd) if hasattr(elemento, "get_or_add_pPr") \
        else elemento.append(shd)


def sombrear_parrafo(p, color_hex: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color_hex)
    p._p.get_or_add_pPr().append(shd)


def sombrear_celda(celda, color_hex: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color_hex)
    celda._tc.get_or_add_tcPr().append(shd)


def borde_izquierdo(p, color_hex: str = "1D4ED8") -> None:
    """Barra vertical a la izquierda: marca visual de las citas."""
    pPr = p._p.get_or_add_pPr()
    bordes = OxmlElement("w:pBdr")
    izq = OxmlElement("w:left")
    izq.set(qn("w:val"), "single")
    izq.set(qn("w:sz"), "18")
    izq.set(qn("w:space"), "8")
    izq.set(qn("w:color"), color_hex)
    bordes.append(izq)
    pPr.append(bordes)


def sin_separacion(p) -> None:
    """Evita que Word parta el parrafo entre dos paginas."""
    pPr = p._p.get_or_add_pPr()
    for etiqueta in ("w:keepNext", "w:keepLines"):
        el = OxmlElement(etiqueta)
        pPr.append(el)


# ---------------------------------------------------------------------------
# Texto en linea
# ---------------------------------------------------------------------------

# Un solo patron con alternativas: se recorre el texto una vez y cada trozo
# sabe que formato lleva. Aplicar los formatos uno detras de otro con varias
# pasadas se enreda en cuanto hay `codigo con **asteriscos**` dentro.
EN_LINEA = re.compile(
    r"(?P<codigo>`[^`]+`)"
    r"|(?P<negrita>\*\*[^*]+\*\*)"
    r"|(?P<cursiva>(?<!\*)\*(?!\*)[^*]+\*(?!\*))"
    r"|(?P<enlace>\[[^\]]+\]\([^)]+\))"
)


def escribir_inline(p, texto: str, base_pt: float = 10.5,
                    color: RGBColor = TINTA, negrita_base: bool = False,
                    cursiva_base: bool = False) -> None:
    """Escribe `texto` en el parrafo `p` resolviendo el formato en linea.

    Negrita y cursiva RECURREN sobre su contenido en vez de volcarlo tal cual.
    Sin esa recursion, un `codigo` dentro de **negrita** salia con las comillas
    invertidas impresas, que es exactamente lo que ocurre en los titulos del
    tipo **`RPI01` en cabina**: frecuentes en estos capitulos.
    """
    def marcar(r, *, mono: bool = False) -> None:
        r.font.size = Pt(base_pt - 1 if mono else base_pt)
        r.bold = negrita_base
        r.italic = cursiva_base
        if mono:
            r.font.name = "Consolas"
            r.font.color.rgb = RGBColor(0x8B, 0x2E, 0x2E)
        else:
            r.font.color.rgb = color

    pos = 0
    for m in EN_LINEA.finditer(texto):
        if m.start() > pos:
            marcar(p.add_run(texto[pos:m.start()]))
        if m.group("codigo"):
            marcar(p.add_run(m.group("codigo")[1:-1]), mono=True)
        elif m.group("negrita"):
            escribir_inline(p, m.group("negrita")[2:-2], base_pt, color,
                            negrita_base=True, cursiva_base=cursiva_base)
        elif m.group("cursiva"):
            escribir_inline(p, m.group("cursiva")[1:-1], base_pt, color,
                            negrita_base=negrita_base, cursiva_base=True)
        elif m.group("enlace"):
            txt, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", m.group("enlace")).groups()
            r = p.add_run(txt)
            marcar(r); r.font.color.rgb = AZUL; r.underline = True
            # Se anade la URL entre parentesis: el documento se va a IMPRIMIR,
            # y un enlace impreso sin su destino es texto azul inutil.
            if url.startswith("http"):
                r2 = p.add_run(f" ({url})")
                r2.font.size = Pt(base_pt - 2); r2.font.color.rgb = TINTA2
        pos = m.end()
    if pos < len(texto):
        marcar(p.add_run(texto[pos:]))


# ---------------------------------------------------------------------------
# Conversor
# ---------------------------------------------------------------------------


class Conversor:
    def __init__(self, base_md: Path) -> None:
        self.base = base_md
        self.doc = Document()
        self._configurar_pagina()
        self._configurar_estilos()

    def _configurar_pagina(self) -> None:
        s = self.doc.sections[0]
        s.page_width, s.page_height = Cm(21.0), Cm(29.7)      # A4
        s.left_margin = s.right_margin = Cm(2.0)
        s.top_margin = s.bottom_margin = Cm(2.0)
        s.footer_distance = Cm(1.2)
        self._pie(s)

    def _pie(self, seccion) -> None:
        """Pie de pagina con el nombre del capitulo y el numero de pagina.

        POR QUE IMPORTA AQUI: son casi cien paginas repartidas en cuatro
        documentos que se van a imprimir y hojear. Sin numeracion, una hoja
        suelta no se puede devolver a su sitio, y no se puede citar "ver
        pagina 34" en ninguna conversacion sobre el proyecto.

        El numero de pagina en Word no es texto: es un CAMPO que se recalcula.
        Hay que construirlo con tres elementos XML -- inicio, instruccion y
        fin -- porque python-docx no tiene API para campos.
        """
        p = seccion.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(f"{self.base.stem}   ·   ")
        r.font.size = Pt(8); r.font.color.rgb = TINTA2

        run = p.add_run()
        run.font.size = Pt(8); run.font.color.rgb = TINTA2

        inicio = OxmlElement("w:fldChar"); inicio.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = " PAGE "
        fin = OxmlElement("w:fldChar"); fin.set(qn("w:fldCharType"), "end")
        for el in (inicio, instr, fin):
            run._r.append(el)

    def _configurar_estilos(self) -> None:
        n = self.doc.styles["Normal"]
        n.font.name = "Calibri"
        n.font.size = Pt(10.5)
        n.font.color.rgb = TINTA
        n.paragraph_format.space_after = Pt(6)
        n.paragraph_format.line_spacing = 1.15

    # -- bloques -----------------------------------------------------------

    def titulo(self, nivel: int, texto: str) -> None:
        tamanos = {1: 20, 2: 15, 3: 12.5, 4: 11}
        p = self.doc.add_paragraph()
        p.paragraph_format.space_before = Pt(16 if nivel <= 2 else 10)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.keep_with_next = True
        escribir_inline(p, texto, base_pt=tamanos.get(nivel, 11),
                        color=AZUL if nivel <= 2 else TINTA, negrita_base=True)
        for r in p.runs:
            r.bold = True
            if nivel <= 2:
                r.font.color.rgb = AZUL
        # Linea bajo los titulos de nivel 1 y 2: ayuda a localizar la seccion
        # al hojear el documento impreso.
        if nivel <= 2:
            pPr = p._p.get_or_add_pPr()
            bordes = OxmlElement("w:pBdr")
            bot = OxmlElement("w:bottom")
            bot.set(qn("w:val"), "single"); bot.set(qn("w:sz"), "6")
            bot.set(qn("w:space"), "4"); bot.set(qn("w:color"), "C7D2E4")
            bordes.append(bot); pPr.append(bordes)

    def parrafo(self, texto: str) -> None:
        p = self.doc.add_paragraph()
        escribir_inline(p, texto)

    def cita(self, lineas: list[str]) -> None:
        # Las lineas de una cita se UNEN en un solo parrafo, que es lo que dice
        # Markdown. Tratarlas por separado rompia el formato en linea cuando un
        # `**negrita**` abria en una linea y cerraba en la siguiente: cada mitad
        # veia un `**` sin pareja y los asteriscos salian impresos.
        if not lineas:
            return
        p = self.doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.5)
        p.paragraph_format.space_after = Pt(8)
        sombrear_parrafo(p, CITA_FONDO)
        borde_izquierdo(p)
        escribir_inline(p, " ".join(lineas), base_pt=10)

    def codigo(self, lineas: list[str]) -> None:
        for i, ln in enumerate(lineas):
            p = self.doc.add_paragraph()
            pf = p.paragraph_format
            pf.space_before = Pt(0); pf.space_after = Pt(0)
            pf.line_spacing = 1.0
            pf.left_indent = Cm(0.3)
            sombrear_parrafo(p, CODIGO_FONDO)
            # Se sustituye el tabulador por espacios: Word lo interpreta como
            # salto de tabulacion y descoloca la indentacion del codigo.
            r = p.add_run(ln.replace("\t", "    ") or " ")
            r.font.name = "Consolas"
            r.font.size = Pt(7.5)
            r.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(4)

    def lista(self, items: list[tuple[int, str, str]]) -> None:
        """items: (sangria, marca, texto). marca: '-', '1.', '[ ]', '[x]'."""
        for sangria, marca, texto in items:
            p = self.doc.add_paragraph()
            pf = p.paragraph_format
            pf.left_indent = Cm(0.6 + 0.5 * sangria)
            pf.space_after = Pt(2)
            vineta = {"-": "•", "[ ]": "☐", "[x]": "☑"}.get(marca, marca)
            r = p.add_run(f"{vineta}  ")
            r.font.size = Pt(10.5); r.font.color.rgb = TINTA2
            escribir_inline(p, texto)

    def tabla(self, filas: list[list[str]]) -> None:
        if not filas:
            return
        cols = max(len(f) for f in filas)
        t = self.doc.add_table(rows=0, cols=cols)
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for idx, fila in enumerate(filas):
            celdas = t.add_row().cells
            for j in range(cols):
                celda = celdas[j]
                celda.text = ""
                p = celda.paragraphs[0]
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.space_before = Pt(2)
                texto = fila[j] if j < len(fila) else ""
                escribir_inline(p, texto, base_pt=9,
                                negrita_base=(idx == 0))
                if idx == 0:
                    sombrear_celda(celda, CABECERA_FONDO)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(4)

    def imagen(self, alt: str, ruta_rel: str) -> None:
        ruta = (self.base.parent / ruta_rel).resolve()
        if not ruta.exists():
            # Las rutas de docs/generado/ apuntan a docs/diagramas/
            ruta = (self.base.parent.parent / ruta_rel).resolve()
        if not ruta.exists():
            self.parrafo(f"*[falta la imagen: {ruta_rel}]*")
            return
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        # Se escala al ancho util, pero nunca por encima de el: un diagrama mas
        # ancho que la pagina se corta en la impresion sin previo aviso.
        from PIL import Image
        with Image.open(ruta) as im:
            an, al = im.size
        # Los PNG se generaron a escala 4; el ancho logico es el util.
        cm_ancho = min(ANCHO_UTIL_CM, an / 4 / 37.8 * 2.54)
        p.add_run().add_picture(str(ruta), width=Cm(cm_ancho))
        if alt:
            pc = self.doc.add_paragraph()
            pc.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = pc.add_run(alt)
            r.italic = True; r.font.size = Pt(8.5); r.font.color.rgb = TINTA2

    def formula(self, texto: str) -> None:
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(texto)
        r.font.name = "Cambria Math"; r.italic = True; r.font.size = Pt(11)

    def separador(self) -> None:
        p = self.doc.add_paragraph()
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)
        pPr = p._p.get_or_add_pPr()
        bordes = OxmlElement("w:pBdr")
        bot = OxmlElement("w:bottom")
        bot.set(qn("w:val"), "single"); bot.set(qn("w:sz"), "4")
        bot.set(qn("w:space"), "1"); bot.set(qn("w:color"), "D6D5D0")
        bordes.append(bot); pPr.append(bordes)

    # -- bucle principal ---------------------------------------------------

    def convertir(self, texto: str) -> Document:
        lineas = texto.split("\n")
        i = 0
        acumulado_lista: list[tuple[int, str, str]] = []

        def vaciar_lista() -> None:
            nonlocal acumulado_lista
            if acumulado_lista:
                self.lista(acumulado_lista)
                acumulado_lista = []

        while i < len(lineas):
            ln = lineas[i]
            desnudo = ln.strip()

            # bloque de codigo
            if desnudo.startswith("```"):
                vaciar_lista()
                i += 1
                cuerpo = []
                while i < len(lineas) and not lineas[i].strip().startswith("```"):
                    cuerpo.append(lineas[i])
                    i += 1
                i += 1
                self.codigo(cuerpo)
                continue

            # formula en bloque
            if desnudo.startswith("$$"):
                vaciar_lista()
                i += 1
                cuerpo = []
                while i < len(lineas) and not lineas[i].strip().startswith("$$"):
                    cuerpo.append(lineas[i].strip())
                    i += 1
                i += 1
                self.formula(" ".join(cuerpo))
                continue

            # tabla
            if desnudo.startswith("|") and i + 1 < len(lineas) \
                    and re.match(r"^\s*\|[\s:\-|]+\|\s*$", lineas[i + 1]):
                vaciar_lista()
                filas = []
                while i < len(lineas) and lineas[i].strip().startswith("|"):
                    cruda = lineas[i].strip().strip("|")
                    if not re.match(r"^[\s:\-|]+$", cruda):
                        filas.append([c.strip() for c in cruda.split("|")])
                    i += 1
                self.tabla(filas)
                continue

            # cita
            if desnudo.startswith(">"):
                vaciar_lista()
                cuerpo = []
                while i < len(lineas) and lineas[i].strip().startswith(">"):
                    cuerpo.append(lineas[i].strip().lstrip(">").strip())
                    i += 1
                self.cita([c for c in cuerpo if c])
                continue

            # imagen sola en su linea
            m_img = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", desnudo)
            if m_img:
                vaciar_lista()
                self.imagen(m_img.group(1), m_img.group(2))
                i += 1
                continue

            # separador
            if re.match(r"^-{3,}$", desnudo):
                vaciar_lista()
                self.separador()
                i += 1
                continue

            # titulo
            m_t = re.match(r"^(#{1,6})\s+(.*)$", desnudo)
            if m_t:
                vaciar_lista()
                self.titulo(len(m_t.group(1)), m_t.group(2))
                i += 1
                continue

            # lista
            m_l = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", ln)
            if m_l:
                sangria = len(m_l.group(1)) // 2
                marca = m_l.group(2)
                cuerpo = m_l.group(3)
                m_c = re.match(r"^\[([ xX])\]\s+(.*)$", cuerpo)
                if m_c:
                    marca = "[x]" if m_c.group(1).lower() == "x" else "[ ]"
                    cuerpo = m_c.group(2)
                elif marca == "*":
                    marca = "-"
                acumulado_lista.append((sangria, marca, cuerpo))
                i += 1
                continue

            # linea en blanco
            if not desnudo:
                vaciar_lista()
                i += 1
                continue

            # parrafo normal
            #
            # Se ACUMULAN las lineas consecutivas hasta que empieza otro bloque
            # o llega una linea en blanco. Markdown une esas lineas en un solo
            # parrafo, y tratar cada una por separado producia dos defectos:
            # interlineado irregular -- cada linea con su propio espaciado -- y
            # formato en linea roto cuando un `**negrita**` o un `` `codigo` ``
            # abria en una linea y cerraba en la siguiente.
            vaciar_lista()
            trozos = [desnudo]
            i += 1
            while i < len(lineas):
                sig = lineas[i].strip()
                if not sig or empieza_bloque(sig, lineas[i]):
                    break
                trozos.append(sig)
                i += 1
            self.parrafo(" ".join(trozos))

        vaciar_lista()
        return self.doc


def main() -> int:
    ap = argparse.ArgumentParser(description="Convierte los capítulos a .docx")
    ap.add_argument("--solo", default=None, help="prefijo, p.ej. 02")
    args = ap.parse_args()

    SALIDA.mkdir(parents=True, exist_ok=True)
    fuentes = sorted(ENTRADA.glob("*.md"))
    if args.solo:
        fuentes = [f for f in fuentes if f.name.startswith(args.solo)]
    if not fuentes:
        print(f"No hay .md en {ENTRADA}. Ejecuta antes expandir_codigo.py")
        return 1

    for md in fuentes:
        destino = SALIDA / (md.stem + ".docx")
        doc = Conversor(md).convertir(md.read_text(encoding="utf-8"))
        doc.save(destino)
        print(f"  {md.name:24s} -> {destino.name}  "
              f"({destino.stat().st_size/1024:,.0f} KB)")
    print(f"\nDocumentos en {SALIDA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
