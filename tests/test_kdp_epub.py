"""Testes da montagem e validacao do EPUB KDP."""
import re
import zipfile

from backend.app.kdp_epub import build_epub
from backend.app.models import Chapter, Paragraph, Run


def _caps():
    return [
        Chapter("Capítulo & Um", 1, [
            Paragraph.from_text("Corpo."),
            Paragraph([Run("com "), Run("ênfase", italic=True)]),
        ]),
        Chapter("Seção", 2, [Paragraph.from_text("Sub.")]),
    ]


def test_epub_mimetype_primeiro_e_sem_compressao(tmp_path):
    out = build_epub(_caps(), "Título", "Autor", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        infos = zf.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"


def test_epub_tem_nav_e_ncx_e_todo_manifest_existe(tmp_path):
    out = build_epub(_caps(), "Título", "Autor", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        nomes = set(zf.namelist())
        assert {"EPUB/nav.xhtml", "EPUB/toc.ncx", "META-INF/container.xml",
                "EPUB/content.opf"} <= nomes
        opf = zf.read("EPUB/content.opf").decode()
        assert all("EPUB/" + h in nomes
                   for h in re.findall(r'href="([^"]+)"', opf))


def test_epub_escapa_caracteres_especiais(tmp_path):
    out = build_epub(_caps(), "Título <b>&", "Autor", "pt-BR",
                     tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        xhtml = zf.read("EPUB/cap1.xhtml").decode()
    assert "Capítulo &amp; Um" in xhtml
    assert "<em>ênfase</em>" in xhtml


def test_epub_aceita_emoji_aspas_e_apostrofo_no_titulo(tmp_path):
    caps = [Chapter('Aspas "duplas" & \'simples\' 📚 🎉', 1,
                    [Paragraph.from_text("ok")])]
    out = build_epub(caps, 'Livro "X" 📚', "A & B", "pt-BR",
                     tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        xhtml = zf.read("EPUB/cap1.xhtml").decode()
        nav = zf.read("EPUB/nav.xhtml").decode()
    assert "&quot;" in xhtml or "&#x27;" in xhtml or "&amp;" in xhtml
    assert "📚" in xhtml
    assert "📚" in nav


def test_epub_toc_aninha_por_nivel(tmp_path):
    out = build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        ncx = zf.read("EPUB/toc.ncx").decode()
        nav = zf.read("EPUB/nav.xhtml").decode()
    assert ncx.count("<navPoint") >= 2
    assert nav.count("<ol") >= 2  # um <ol> aninhado por nivel


def test_epub_metadados_e_idioma(tmp_path):
    out = build_epub(_caps(), "Meu Livro", "Maria Silva", "pt-BR",
                     tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        opf = zf.read("EPUB/content.opf").decode()
    assert "Meu Livro" in opf
    assert "Maria Silva" in opf
    assert "pt-BR" in opf
    assert "dcterms:modified" in opf
