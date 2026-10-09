"""Geracao de capa procedural (JPEG) com PyMuPDF, sem dependencia extra.

A capa e desenhada numa pagina de tamanho exato e renderizada 1:1 (`Matrix(1,1)`),
entao as dimensoes finais batem com as do JPEG. O texto e saneado e filtrado
para os glifos que as fontes base-14 (Times) suportam; `build_cover` nunca
lanca por causa do conteudo do titulo/autor.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

try:  # PyMuPDF >= 1.24 expoe `pymupdf`; `fitz` esta em desuso.
    import pymupdf
except ImportError:  # pragma: no cover - compatibilidade com versoes antigas
    import fitz as pymupdf  # type: ignore

from .kdp_epub import sanitize_text

LARGURA = 1600
ALTURA = 2560

_FUNDO = (0.10, 0.12, 0.18)      # azul-grafite sobrio
_TINTA = (0.94, 0.93, 0.89)      # off-white
_MOLDURA = (0.72, 0.66, 0.48)    # dourado discreto

# Times base-14 cobre Latin/Greek/Cyrillic ate ~U+2FFF. Fora disso (emoji, CJK)
# nao ha glifo; filtramos para a capa nao sair com caixas vazias.
_MAX_CODEPOINT = 0x2FFF


def _ascii(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def _texto_renderizavel(texto: object) -> str:
    """Saneia e remove caracteres sem glifo nas fontes base-14."""
    limpo = sanitize_text(texto)
    saida = "".join(ch for ch in limpo
                    if ch.isprintable() and ord(ch) <= _MAX_CODEPOINT)
    saida = " ".join(saida.split())
    if saida:
        return saida
    return " ".join(_ascii(limpo).split())


def _desenhar_texto(page, rect, texto: str, fontname: str, tam_max: int,
                    tam_min: int, cor) -> None:
    """Desenha `texto` centralizado em `rect`, encolhendo ate caber.

    Se a fonte base-14 nao tiver algum glifo, cai para a versao ASCII e, em
    ultimo caso, desiste em silencio (a capa continua valida).
    """
    candidatos = [texto]
    simples = _ascii(texto)
    if simples.strip() and simples != texto:
        candidatos.append(simples)
    for candidato in candidatos:
        if not candidato.strip():
            continue
        try:
            tamanho = tam_max
            while tamanho >= tam_min:
                sobra = page.insert_textbox(
                    rect, candidato, fontname=fontname, fontsize=tamanho,
                    color=cor, align=pymupdf.TEXT_ALIGN_CENTER)
                if sobra >= 0:
                    return
                tamanho -= 2
            page.insert_textbox(rect, candidato, fontname=fontname,
                                fontsize=tam_min, color=cor,
                                align=pymupdf.TEXT_ALIGN_CENTER)
            return
        except Exception:  # pragma: no cover - fallback defensivo
            continue


def build_cover(title: str, author: str, out_path: Path | str,
                width: int = LARGURA, height: int = ALTURA,
                subtitle: str | None = None) -> Path:
    """Gera uma capa JPEG `width` x `height` e devolve o caminho."""
    destino = Path(out_path)
    destino.parent.mkdir(parents=True, exist_ok=True)

    titulo = _texto_renderizavel(title) or "Capa"
    autor = _texto_renderizavel(author) or "Autor Desconhecido"
    sub = _texto_renderizavel(subtitle) if subtitle else ""

    doc = pymupdf.open()
    try:
        page = doc.new_page(width=width, height=height)
        page.draw_rect(pymupdf.Rect(0, 0, width, height), color=None,
                       fill=_FUNDO)
        margem = width * 0.08
        page.draw_rect(pymupdf.Rect(margem, margem, width - margem,
                                    height - margem), color=_MOLDURA,
                       width=max(2, width // 400))

        faixa_titulo = pymupdf.Rect(margem * 1.6, height * 0.10,
                                    width - margem * 1.6, height * 0.52)
        _desenhar_texto(page, faixa_titulo, titulo, "tibo", int(width * 0.13),
                        28, _TINTA)

        if sub:
            faixa_sub = pymupdf.Rect(margem * 1.6, height * 0.60,
                                     width - margem * 1.6, height * 0.70)
            _desenhar_texto(page, faixa_sub, sub, "tiro", int(width * 0.045),
                            20, _MOLDURA)

        faixa_autor = pymupdf.Rect(margem * 1.6, height * 0.72,
                                   width - margem * 1.6, height * 0.86)
        _desenhar_texto(page, faixa_autor, autor, "tiro", int(width * 0.055),
                        18, _TINTA)

        pix = page.get_pixmap(matrix=pymupdf.Matrix(1, 1))
        destino.write_bytes(pix.tobytes("jpeg"))
    finally:
        doc.close()
    return destino
