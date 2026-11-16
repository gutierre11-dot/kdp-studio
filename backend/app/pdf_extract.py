"""Extracao de linhas e bookmarks de um PDF via PyMuPDF.

A saida preserva geometria (bbox + dimensoes da pagina) e formatacao inline
(runs) porque a deteccao de titulos e a limpeza dependem de posicao, tamanho de
fonte e negrito, e o EPUB final reaproveita italico/negrito do original.
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

try:  # PyMuPDF >= 1.24 expoe `pymupdf`; `fitz` esta em desuso.
    import pymupdf
except ImportError:  # pragma: no cover - compatibilidade com versoes antigas
    import fitz as pymupdf  # type: ignore

from .models import Figure, Line, Run

# Bits de `span["flags"]` (PyMuPDF): 1<<4 = negrito, 1<<1 = italico,
# 1<<0 = superscript (chamador de nota).
_FLAG_BOLD = 1 << 4
_FLAG_ITALIC = 1 << 1
_FLAG_SUPERSCRIPT = 1 << 0


def _links_da_pagina(page) -> list[tuple[tuple[float, float, float, float], str]]:
    """Links externos da pagina, como `(bbox, uri)`."""
    saida: list[tuple[tuple[float, float, float, float], str]] = []
    try:
        for link in page.get_links():
            uri = (link.get("uri") or "").strip()
            if not uri.lower().startswith(("http://", "https://", "mailto:")):
                continue
            origem = link.get("from")
            if origem is None:
                continue
            saida.append((tuple(float(v) for v in origem), uri))
    except Exception:  # pragma: no cover - pagina sem links
        return []
    return saida


def _href_do_span(bbox, links) -> str | None:
    """URI do primeiro link que cobre o span (area de intersecao > 0)."""
    if not bbox or not links:
        return None
    x0, y0, x1, y1 = (float(v) for v in bbox)
    for (lx0, ly0, lx1, ly1), uri in links:
        if min(x1, lx1) > max(x0, lx0) and min(y1, ly1) > max(y0, ly0):
            return uri
    return None


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
                    links = _links_da_pagina(page)
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
                                        bold=s_bold, superscript=s_sup,
                                        href=_href_do_span(s.get("bbox"),
                                                           links)))
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
    linhas.sort(key=lambda linha: (linha.page, linha.bbox[1], linha.bbox[0]))
    return linhas, paginas, outline


# ---------------------------------------------------------------------------
# Figuras
# ---------------------------------------------------------------------------

_FIG_MIN_SIDE = 40.0            # pt: menor lado aceitavel
_FIG_MIN_AREA_FRAC = 0.012      # fracao minima da pagina
_FIG_MAX_AREA_FRAC = 0.85       # acima disso e fundo de pagina, nao figura
_FIG_MAX_PIXELS = 40_000_000    # 40 MP: protege contra bombas de descompressao
_FIG_MAX_LONG_EDGE = 1600       # px: suficiente para leitor e KDP
_FIG_MAX_BYTES = 8 * 1024 * 1024
_FIG_MAX_COUNT = 200
_FIG_TEXT_OVERLAP = 0.30        # texto cobrindo a area: provavel tabela/fundo


def _line_rects(page) -> list[tuple[float, float, float, float]]:
    """BBoxes das linhas de texto da pagina (para detectar sobreposicao)."""
    saida: list[tuple[float, float, float, float]] = []
    try:
        for bloco in page.get_text("dict").get("blocks", []):
            if bloco.get("type", 0) != 0:
                continue
            for linha in bloco.get("lines", []):
                if (linha.get("bbox") and
                        any((s.get("text") or "").strip()
                            for s in linha.get("spans", []))):
                    saida.append(tuple(float(v) for v in linha["bbox"]))
    except Exception:  # pragma: no cover - pagina corrompida
        return []
    return saida


def _sobreposicao(rect, caixas) -> float:
    """Fracao da area de `rect` coberta por texto (0..1)."""
    area = max(0.0, rect.width * rect.height)
    if area <= 0:
        return 1.0
    coberta = 0.0
    for caixa in caixas:
        x0 = max(rect.x0, caixa[0])
        y0 = max(rect.y0, caixa[1])
        x1 = min(rect.x1, caixa[2])
        y1 = min(rect.y1, caixa[3])
        if x1 > x0 and y1 > y0:
            coberta += (x1 - x0) * (y1 - y0)
    return min(1.0, coberta / area)


def _figura_de_pixmap(pix, *, page: int, bbox: tuple[float, ...],
                      ext: str = "", alt: str = "") -> Figure | None:
    """Normaliza um Pixmap para JPEG/PNG dentro dos limites do EPUB."""
    try:
        if pix.width * pix.height > _FIG_MAX_PIXELS:
            return None
        # CMYK/índice/1-bit viram RGB para o leitor nao abrir a imagem errada.
        if pix.colorspace is None or pix.colorspace.n not in (1, 3):
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        maior = max(pix.width, pix.height)
        if maior > _FIG_MAX_LONG_EDGE:
            pix.shrink(math.ceil(maior / _FIG_MAX_LONG_EDGE))
        usa_png = bool(pix.alpha) or (pix.n == 1 and
                                      pix.width * pix.height <= 2_000_000)
        formato = "png" if usa_png else "jpeg"
        dados = pix.tobytes(formato, jpg_quality=85)
        tentativas = 0
        while len(dados) > _FIG_MAX_BYTES and tentativas < 3:
            fator = math.ceil(max(pix.width, pix.height) / 900)
            pix.shrink(max(2, fator))
            dados = pix.tobytes(formato, jpg_quality=82)
            tentativas += 1
        if len(dados) > _FIG_MAX_BYTES:
            return None
        return Figure(data=dados, ext="png" if usa_png else "jpg",
                      width=pix.width, height=pix.height, alt=alt,
                      page=page, bbox=(float(bbox[0]), float(bbox[1]),
                                       float(bbox[2]), float(bbox[3])))
    except Exception:  # pragma: no cover - imagem exotica/corrompida
        return None


def _render_region(page, rect, *, page_no: int) -> Figure | None:
    """Rasteriza uma regiao vetorial (grafico, mapa, ilustracao vetorial)."""
    try:
        maior = max(rect.width, rect.height)
        zoom = max(1.5, min(3.0, _FIG_MAX_LONG_EDGE / max(1.0, maior)))
        clip = pymupdf.Rect(rect)
        clip.x0 = max(0.0, clip.x0 - 3)
        clip.y0 = max(0.0, clip.y0 - 3)
        clip.x1 = min(page.rect.width, clip.x1 + 3)
        clip.y1 = min(page.rect.height, clip.y1 + 3)
        pix = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(zoom, zoom),
                              alpha=False, colorspace=pymupdf.csRGB)
        return _figura_de_pixmap(pix, page=page_no, bbox=tuple(clip))
    except Exception:  # pragma: no cover - desenho exotico
        return None


def extract_figures(pdf_path: Path | str) -> tuple[list[Figure], list[str]]:
    """Extrai imagens raster e figuras vetoriais do PDF, em ordem de leitura.

    Filtra o que costuma ser decoracao (logos repetidos, filetes, fundos de
    pagina, cabecalhos/rodapes) e rasteriza grupos de desenhos vetoriais que
    parecem figuras (graficos, mapas) sem texto suficiente para serem tabelas.
    Retorna `(figuras, avisos)`; a posicao no capitulo e atribuida depois.
    """
    figuras: list[Figure] = []
    avisos: list[str] = []
    ignoradas = 0
    try:
        doc = pymupdf.open(str(pdf_path))
    except Exception as exc:  # pragma: no cover - ja validado antes
        return [], [f"Não foi possível extrair figuras: {exc}"]
    try:
        paginas = doc.page_count
        imagens_por_xref: dict[int, list[int]] = defaultdict(list)
        infos_por_pagina: list[tuple[object, list[dict]]] = []
        for pno, page in enumerate(doc):
            infos = page.get_image_info(xrefs=True)
            infos_por_pagina.append((page, infos))
            for info in infos:
                xref = int(info.get("xref") or 0)
                if xref > 0:
                    imagens_por_xref[xref].append(pno)

        for pno, (page, infos) in enumerate(infos_por_pagina):
            altura = float(page.rect.height) or 1.0
            area_pagina = max(1.0, page.rect.width * altura)
            textos = _line_rects(page)
            caixas_imagem: list[pymupdf.Rect] = []
            for info in infos:
                xref = int(info.get("xref") or 0)
                if xref <= 0:  # imagem inline: sem xref para extrair com seguranca
                    continue
                bbox = tuple(float(v) for v in info.get("bbox", (0, 0, 0, 0)))
                rect = pymupdf.Rect(bbox) & page.rect
                if rect.is_empty or rect.width < _FIG_MIN_SIDE \
                        or rect.height < _FIG_MIN_SIDE:
                    continue
                fracao = (rect.width * rect.height) / area_pagina
                if fracao < _FIG_MIN_AREA_FRAC:
                    continue
                # Logo/imagem corrente repetida em varias paginas.
                repeticoes = len(imagens_por_xref.get(xref, []))
                if (repeticoes >= max(3, int(paginas * 0.25))
                        and rect.height < 0.2 * altura):
                    continue
                # Filete/ornamento na banda de cabecalho ou rodape.
                if (rect.height < 0.18 * altura
                        and (rect.y1 < 0.12 * altura
                             or rect.y0 > 0.88 * altura)):
                    continue
                sobreposicao = _sobreposicao(rect, textos)
                if fracao > _FIG_MAX_AREA_FRAC and sobreposicao > 0.02:
                    continue  # fundo de pagina com texto por cima
                if sobreposicao > 0.5:
                    continue  # imagem atras de texto: decoracao
                if (int(info.get("width", 0)) * int(info.get("height", 0))
                        > _FIG_MAX_PIXELS):
                    ignoradas += 1
                    continue
                # Imagem colocada em resolucao baixa (menos de ~86 dpi no
                # tamanho impresso): rasterizar a area entrega uma figura
                # nítida no leitor, sem depender do bitmap original pequeno.
                largura_px = int(info.get("width", 0))
                altura_px = int(info.get("height", 0))
                if (largura_px < rect.width * 1.2
                        or altura_px < rect.height * 1.2):
                    figura = _render_region(page, rect, page_no=pno)
                    if figura is not None:
                        figura.alt = str(info.get("alt") or "").strip()
                else:
                    try:
                        pix = pymupdf.Pixmap(doc, xref)
                    except Exception:
                        ignoradas += 1
                        continue
                    figura = _figura_de_pixmap(
                        pix, page=pno, bbox=bbox,
                        alt=str(info.get("alt") or "").strip())
                if figura is None:
                    ignoradas += 1
                    continue
                figuras.append(figura)
                caixas_imagem.append(rect)

            # Desenhos vetoriais agrupados (graficos, mapas, ilustracoes).
            try:
                grupos = page.cluster_drawings()
            except Exception:  # pragma: no cover - PDF sem desenhos
                grupos = []
            for grupo in grupos:
                rect = pymupdf.Rect(grupo) & page.rect
                if rect.is_empty or rect.width < 60 or rect.height < 60:
                    continue
                fracao = (rect.width * rect.height) / area_pagina
                if fracao < 0.02 or fracao > _FIG_MAX_AREA_FRAC:
                    continue
                if (rect.height < 0.18 * altura
                        and (rect.y1 < 0.12 * altura
                             or rect.y0 > 0.88 * altura)):
                    continue
                if _sobreposicao(rect, textos) > _FIG_TEXT_OVERLAP:
                    continue  # tabela/caixa de texto, nao figura
                if any(rect.intersects(caixa) for caixa in caixas_imagem):
                    continue  # ja coberta por uma imagem raster
                figura = _render_region(page, rect, page_no=pno)
                if figura is not None:
                    figuras.append(figura)
                    caixas_imagem.append(rect)

        figuras.sort(key=lambda f: (f.page, f.bbox[1], f.bbox[0]))
        if len(figuras) > _FIG_MAX_COUNT:
            avisos.append(f"Limite de {_FIG_MAX_COUNT} figuras atingido; "
                          "as demais foram ignoradas.")
            figuras = figuras[:_FIG_MAX_COUNT]
        if ignoradas:
            avisos.append(f"{ignoradas} imagem(ns) não puderam ser preservadas "
                          "(formato ou tamanho não suportado).")
        return figuras, avisos
    finally:
        doc.close()
