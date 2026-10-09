"""Extracao de linhas e bookmarks de um PDF via PyMuPDF.

A saida preserva geometria (bbox + dimensoes da pagina) e formatacao inline
(runs) porque a deteccao de titulos e a limpeza dependem de posicao, tamanho de
fonte e negrito, e o EPUB final reaproveita italico/negrito do original.
"""
from __future__ import annotations

from pathlib import Path

try:  # PyMuPDF >= 1.24 expoe `pymupdf`; `fitz` esta em desuso.
    import pymupdf
except ImportError:  # pragma: no cover - compatibilidade com versoes antigas
    import fitz as pymupdf  # type: ignore

from .models import Line, Run

# Bits de `span["flags"]` (PyMuPDF): 1<<4 = negrito, 1<<1 = italico,
# 1<<0 = superscript (chamador de nota).
_FLAG_BOLD = 1 << 4
_FLAG_ITALIC = 1 << 1
_FLAG_SUPERSCRIPT = 1 << 0


def extract_lines(pdf_path: Path | str) -> tuple[list[Line], int, list[list]]:
    """Extrai as linhas do PDF em ordem de leitura.

    Retorna `(linhas, total_de_paginas, outline)`, onde `outline` segue o
    formato de `Doc.get_toc(simple=True)`: `[[nivel, titulo, pagina], ...]`.
    """
    doc = pymupdf.open(str(pdf_path))
    linhas: list[Line] = []
    try:
        paginas = doc.page_count
        for pno, page in enumerate(doc):
            altura = float(page.rect.height)
            largura = float(page.rect.width)
            for bloco in page.get_text("dict").get("blocks", []):
                if bloco.get("type", 0) != 0:  # 0 = bloco de texto
                    continue
                for linha in bloco.get("lines", []):
                    spans = [s for s in linha.get("spans", [])
                             if (s.get("text") or "").strip()]
                    if not spans:
                        continue
                    texto = " ".join(str(s["text"]) for s in spans).strip()
                    if not texto:
                        continue
                    runs: list[Run] = []
                    bold = italic = False
                    for s in spans:
                        flags = int(s.get("flags", 0))
                        s_bold = bool(flags & _FLAG_BOLD)
                        s_italic = bool(flags & _FLAG_ITALIC)
                        s_sup = bool(flags & _FLAG_SUPERSCRIPT)
                        bold = bold or s_bold
                        italic = italic or s_italic
                        runs.append(Run(str(s["text"]), italic=s_italic,
                                        bold=s_bold, superscript=s_sup))
                    bbox = tuple(float(v) for v in linha.get("bbox", (0, 0, 0, 0)))
                    linhas.append(Line(
                        page=pno,
                        text=texto,
                        size=max(float(s.get("size", 12.0)) for s in spans),
                        bold=bold,
                        italic=italic,
                        bbox=bbox,  # type: ignore[arg-type]
                        page_height=altura,
                        page_width=largura,
                        runs=runs,
                    ))
        outline = [list(t) for t in doc.get_toc(simple=True)]
    finally:
        doc.close()
    linhas.sort(key=lambda l: (l.page, l.bbox[1], l.bbox[0]))
    return linhas, paginas, outline
