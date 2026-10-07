"""Testes da exportacao KDP (kdp_export): EPUB, DOCX, previa e capa."""
from __future__ import annotations

import re
import zipfile

from backend.app import kdp_export as kx


CHAPTERS = [
    {"title": "Capítulo 1", "level": 1,
     "paragraphs": ["Primeiro parágrafo.", "Segundo parágrafo."]},
    {"title": "Seção 1.1", "level": 2, "paragraphs": ["Texto da seção."]},
    {"title": "Capítulo 2", "level": 1, "paragraphs": ["Fim."]},
]


def test_export_epub_estrutura_basica(tmp_path):
    out = tmp_path / "livro.epub"
    kx.export_epub(CHAPTERS, "Meu Livro", "Autora", out)
    assert out.exists()
    with zipfile.ZipFile(out) as z:
        nomes = z.namelist()
        assert "mimetype" in nomes
        assert z.read("mimetype").decode() == "application/epub+zip"
        assert "EPUB/content.opf" in nomes
        assert "EPUB/nav.xhtml" in nomes
        assert "EPUB/toc.ncx" in nomes
        opf = z.read("EPUB/content.opf").decode()
        assert "<dc:title>Meu Livro</dc:title>" in opf
        assert "<dc:language>pt-BR</dc:language>" in opf
        cap1 = z.read("EPUB/cap1.xhtml").decode()
        assert "<h1>Capítulo 1</h1>" in cap1
        sec = z.read("EPUB/cap2.xhtml").decode()
        assert "<h2>Seção 1.1</h2>" in sec


def test_identificador_distingue_autores(tmp_path):
    def ident(path, autor):
        kx.export_epub(CHAPTERS, "Título Igual", autor, path)
        with zipfile.ZipFile(path) as z:
            opf = z.read("EPUB/content.opf").decode()
        return re.search(r'<dc:identifier id="id">([^<]+)</dc:identifier>', opf).group(1)

    a = ident(tmp_path / "a.epub", "Autor A")
    b = ident(tmp_path / "b.epub", "Autor B")
    assert a != b


def test_export_epub_embute_capa(tmp_path):
    from PIL import Image
    capa = tmp_path / "capa.jpg"
    Image.new("RGB", (80, 128), (20, 30, 60)).save(capa, "JPEG")
    out = tmp_path / "com-capa.epub"
    kx.export_epub(CHAPTERS, "Livro", "Autor", out, cover_path=capa)
    with zipfile.ZipFile(out) as z:
        assert any(n.lower().endswith("cover.jpg") for n in z.namelist())


def test_export_docx_gera_arquivo(tmp_path):
    out = tmp_path / "livro.docx"
    kx.export_docx(CHAPTERS, "Meu Livro", "Autora", out)
    assert out.exists() and out.stat().st_size > 0
    with zipfile.ZipFile(out) as z:
        doc = z.read("word/document.xml").decode()
    assert "Capítulo 1" in doc
    assert "Meu Livro" in doc


def test_preview_escapa_html():
    html = kx.build_preview_html(
        [{"title": "<script>alert(1)</script>", "level": 1,
          "paragraphs": ["<b>oi</b> & tchau"]}],
        "Título & Cia", "Autor <x>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_css_kdp_presente_no_epub(tmp_path):
    out = tmp_path / "css.epub"
    kx.export_epub(CHAPTERS, "L", "A", out)
    with zipfile.ZipFile(out) as z:
        css = z.read("EPUB/style/kdp.css").decode()
    assert "Times New Roman" in css
    assert "text-indent: 1.5cm" in css
