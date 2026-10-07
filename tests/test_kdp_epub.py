"""Testes da montagem e validacao do EPUB KDP."""
import re
import zipfile

import pytest

from backend.app.kdp_epub import (
    EpubValidationError,
    build_epub,
    validate_epub,
)
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


def test_validate_epub_aceita_epub_valido(tmp_path):
    out = build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "ok.epub")
    validate_epub(out)  # não levanta


def test_validate_epub_rejeita_zip_inconsistente(tmp_path):
    ruim = tmp_path / "ruim.epub"
    with zipfile.ZipFile(ruim, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", "<container/>")
        zf.writestr("EPUB/content.opf", "<package><manifest>"
                    '<item href="cap1.xhtml"/></manifest></package>')
    with pytest.raises(EpubValidationError, match="cap1.xhtml"):
        validate_epub(ruim)


def test_validate_epub_rejeita_mimetype_comprimido(tmp_path):
    ruim = tmp_path / "ruim.epub"
    with zipfile.ZipFile(ruim, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", "<container/>")
        zf.writestr("EPUB/content.opf", "<package><manifest/></package>")
        zf.writestr("EPUB/nav.xhtml", "<html><body/></html>")
        zf.writestr("EPUB/toc.ncx", "<ncx/>")
    with pytest.raises(EpubValidationError, match="mimetype"):
        validate_epub(ruim)


def test_validate_epub_rejeita_arquivo_inexistente(tmp_path):
    with pytest.raises(EpubValidationError, match="não encontrado"):
        validate_epub(tmp_path / "nao_existe.epub")


def test_falha_de_validacao_nao_cria_destino(tmp_path, monkeypatch):
    def explode(_path):
        raise EpubValidationError("boom")

    monkeypatch.setattr("backend.app.kdp_epub.validate_epub", explode)
    destino = tmp_path / "saida.epub"
    with pytest.raises(EpubValidationError):
        build_epub(_caps(), "T", "A", "pt-BR", destino)
    assert not destino.exists()
    assert not list(tmp_path.glob("*.tmp-*"))
