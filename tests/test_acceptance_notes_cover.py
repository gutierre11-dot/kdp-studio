"""Aceitacao sintetica ponta a ponta: notas de rodape (endnotes) + capa.

Nao depende de `KDP_REAL_PDFS_DIR`: constroi o PDF de fixture com PyMuPDF e
roda o pipeline completo PDF -> capitulos -> EPUB 3. O marcador `acceptance`
permite roda-la junto das demais aceitacoes:

    python3 -m pytest -q -m acceptance
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pymupdf
import pytest

from backend.app.kdp_epub import build_epub, validate_epub
from backend.app.pdf_chapters import build_chapters

pytestmark = pytest.mark.acceptance

# Dimensoes de uma pagina A4 em pontos: com 842pt de altura, a banda inferior
# das notas comeca em 0.80 * 842 ~= 673pt.
_W, _H = 595, 842


def _pdf_com_nota(tmp_path: Path) -> Path:
    """PDF de uma pagina: capitulo por bookmark, chamador no corpo e nota no pe.

    O corpo usa `insert_htmlbox`, que de fato emite o span de `<sup>1</sup>` com
    a flag de superscript (bit 0) — e dela que a extracao deriva o chamador de
    nota. A nota fica em 10pt (<= 70% do corpo de 16pt) na banda inferior.
    """
    caminho = tmp_path / "sintetico.pdf"
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=_W, height=_H)
        page.insert_text((72, 90), "Capítulo Um", fontsize=20, fontname="hebo")
        page.insert_htmlbox(
            pymupdf.Rect(72, 150, _W - 72, _H * 0.7),
            "<p>Corpo com chamador<sup>1</sup> aqui.</p>",
            css="p { font-size: 16px; }")
        page.insert_text((72, _H * 0.85), "1 Nota de teste.",
                         fontsize=10, fontname="helv")
        doc.set_toc([[1, "Capítulo Um", 1]])
        doc.save(str(caminho))
    finally:
        doc.close()
    return caminho


def _imagem_capa(tmp_path: Path, extensao: str) -> Path:
    """Gera uma imagem de capa real (PNG ou JPEG) com PyMuPDF."""
    destino = tmp_path / f"capa-externa.{extensao}"
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=100, height=160)
        page.draw_rect(pymupdf.Rect(0, 0, 100, 160), color=None,
                       fill=(0.18, 0.28, 0.46))
        page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(str(destino))
    finally:
        doc.close()
    return destino


def _spine(opf: str) -> list[str]:
    """Sequencia de `href`s do spine, na ordem declarada no OPF."""
    href_por_id: dict[str, str] = {}
    for tag in re.findall(r"<item\b[^>]*>", opf):
        mid = re.search(r'\bid="([^"]+)"', tag)
        href = re.search(r'\bhref="([^"]+)"', tag)
        if mid and href:
            href_por_id[mid.group(1)] = href.group(1)
    return [href_por_id.get(ref, "?")
            for ref in re.findall(r'<itemref[^>]*idref="([^"]+)"', opf)]


def test_pipeline_sintetico_notas_e_capa_procedural(tmp_path):
    pdf = _pdf_com_nota(tmp_path)

    capitulos, _ = build_chapters(pdf)
    assert len(capitulos) == 1
    capitulo = capitulos[0]
    assert capitulo.title == "Capítulo Um"
    assert [numero for numero, _ in capitulo.notes] == [1]
    assert capitulo.notes[0][1] == "Nota de teste."
    chamador = [run for paragrafo in capitulo.paragraphs
                for run in paragrafo.runs
                if getattr(run, "superscript", False)
                and run.text.strip() == "1"]
    assert chamador, "o chamador superscript sumiu do corpo extraido"

    destino = tmp_path / "livro.epub"
    out = build_epub(capitulos, "Livro Sintético", "Autora Teste", "pt-BR",
                     destino, cover=True)
    assert out == destino
    validate_epub(out)

    with zipfile.ZipFile(out) as zf:
        nomes = set(zf.namelist())
        xhtml = zf.read("EPUB/cap1.xhtml").decode()
        opf = zf.read("EPUB/content.opf").decode()

    assert "EPUB/cover.jpg" in nomes
    assert 'properties="cover-image"' in opf
    assert '<meta name="cover"' in opf
    assert _spine(opf)[0] == "capa.xhtml"

    assert 'href="#fn-1"' in xhtml and 'id="fn-1"' in xhtml
    assert 'href="#fnref-1"' in xhtml and 'id="fnref-1"' in xhtml
    for numero in re.findall(r'href="#fn-(\d+)"', xhtml):
        assert f'id="fn-{numero}"' in xhtml, f"fn-{numero} sem destino no arquivo"
    for numero in re.findall(r'href="#fnref-(\d+)"', xhtml):
        assert f'id="fnref-{numero}"' in xhtml, f"fnref-{numero} sem destino"


@pytest.mark.parametrize("extensao,esperado", [("png", "cover.png"),
                                               ("jpg", "cover.jpg")])
def test_pipeline_sintetico_capa_externa(tmp_path, extensao, esperado):
    pdf = _pdf_com_nota(tmp_path)
    capitulos, _ = build_chapters(pdf)
    capa = _imagem_capa(tmp_path, extensao)

    out = build_epub(capitulos, "Livro", "Autora", "pt-BR",
                     tmp_path / "livro.epub", cover_image=capa)
    validate_epub(out)

    with zipfile.ZipFile(out) as zf:
        nomes = set(zf.namelist())
        opf = zf.read("EPUB/content.opf").decode()
        pagina = zf.read("EPUB/capa.xhtml").decode()

    assert f"EPUB/{esperado}" in nomes
    assert 'properties="cover-image"' in opf
    assert f'src="{esperado}"' in pagina
    assert _spine(opf)[0] == "capa.xhtml"
