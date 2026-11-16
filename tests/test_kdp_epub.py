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
    with pytest.raises(EpubValidationError, match=r"cap1\.xhtml"):
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


def test_texto_com_surrogate_nao_trunca_paragrafo(tmp_path):
    """Caractere inválido em XML não pode fazer o ebooklib engolir o trecho."""
    caps = [Chapter("T", 1, [Paragraph.from_text("antes \ud800 depois")])]
    out = build_epub(caps, "T", "A", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        xhtml = zf.read("EPUB/cap1.xhtml").decode()
    assert "antes" in xhtml
    assert "depois" in xhtml


def test_titulo_com_controle_invalido_nao_quebra(tmp_path):
    caps = [Chapter("Cap\x0cítulo", 1, [Paragraph.from_text("ok")])]
    out = build_epub(caps, "Li\x0cvro", "Au\x01tor", "pt-BR", tmp_path / "l.epub")
    validate_epub(out)
    with zipfile.ZipFile(out) as zf:
        xhtml = zf.read("EPUB/cap1.xhtml").decode()
    assert "Cap" in xhtml and "tulo" in xhtml


def test_continuacao_sem_heading_e_fora_do_toc(tmp_path):
    """Parte de continuação vai ao spine, mas sem heading e fora do TOC."""
    caps = [Chapter("Longo", 1, [Paragraph.from_text("parte um.")]),
            Chapter("Longo", 1, [Paragraph.from_text("parte dois.")],
                    continues=True),
            Chapter("Normal", 1, [Paragraph.from_text("outro.")])]
    out = build_epub(caps, "T", "A", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        cap1 = zf.read("EPUB/cap1.xhtml").decode()
        cap2 = zf.read("EPUB/cap2.xhtml").decode()
        nav = zf.read("EPUB/nav.xhtml").decode()
        ncx = zf.read("EPUB/toc.ncx").decode()
        opf = zf.read("EPUB/content.opf").decode()
        nomes = set(zf.namelist())
    assert "<h1>Longo</h1>" in cap1
    assert "<h1" not in cap2 and "<h2" not in cap2 and "<h3" not in cap2
    assert "parte dois." in cap2
    assert nav.count("Longo") == 1
    assert ncx.count("Longo") == 1
    assert "EPUB/cap2.xhtml" in nomes
    assert "cap2.xhtml" in opf
    validate_epub(out)


# ---------------------------------------------------------------------------
# Notas de rodape como endnotes
# ---------------------------------------------------------------------------


def test_chamador_superscript_vira_link_para_nota(tmp_path):
    caps = [Chapter("Cap", 1, [
        Paragraph([Run("pedem"), Run("7", superscript=True), Run(".")])],
        notes=[(7, "Texto da nota sete.")])]
    out = build_epub(caps, "T", "A", "pt-BR", tmp_path / "l.epub", cover=False)
    with zipfile.ZipFile(out) as zf:
        xhtml = zf.read("EPUB/cap1.xhtml").decode()
    assert 'href="#fn-7"' in xhtml
    assert 'id="fnref-7"' in xhtml
    assert 'id="fn-7"' in xhtml
    assert 'href="#fnref-7"' in xhtml
    assert "Texto da nota sete." in xhtml
    # integridade dos destinos no mesmo arquivo
    for n in re.findall(r'href="#fn-(\d+)"', xhtml):
        assert f'id="fn-{n}"' in xhtml
    for n in re.findall(r'id="fnref-(\d+)"', xhtml):
        assert f'href="#fnref-{n}"' in xhtml


def test_chamador_sem_nota_fica_sem_link(tmp_path):
    caps = [Chapter("Cap", 1,
                    [Paragraph([Run("x"), Run("9", superscript=True)])])]
    out = build_epub(caps, "T", "A", "pt-BR", tmp_path / "l.epub", cover=False)
    with zipfile.ZipFile(out) as zf:
        xhtml = zf.read("EPUB/cap1.xhtml").decode()
    assert 'href="#fn-9"' not in xhtml
    assert "<sup>9</sup>" in xhtml


def test_superscript_nao_numerico_vira_sup(tmp_path):
    caps = [Chapter("Cap", 1,
                    [Paragraph([Run("a"), Run("th", superscript=True)])])]
    out = build_epub(caps, "T", "A", "pt-BR", tmp_path / "l.epub", cover=False)
    with zipfile.ZipFile(out) as zf:
        xhtml = zf.read("EPUB/cap1.xhtml").decode()
    assert "<sup>th</sup>" in xhtml


def test_heading_emite_link_do_chamador_do_titulo(tmp_path):
    """Chamador na linha do titulo vira link no proprio heading (F1/F3)."""
    caps = [Chapter("II. O Proprietário", 1,
                    [Paragraph([Run("Texto do corpo.")])],
                    title_refs=[190], notes=[(190, "Nota do titulo.")])]
    out = build_epub(caps, "T", "A", "pt-BR", tmp_path / "l.epub", cover=False)
    with zipfile.ZipFile(out) as zf:
        xhtml = zf.read("EPUB/cap1.xhtml").decode()
    assert ('<a class="noteref" id="fnref-190" href="#fn-190" '
            'epub:type="noteref"><sup>190</sup></a>') in xhtml
    assert 'href="#fnref-190"' in xhtml  # backlink da nota
    validate_epub(out)


def test_heading_title_ref_sem_nota_nao_gera_link(tmp_path):
    caps = [Chapter("T", 1, [Paragraph.from_text("x")], title_refs=[5])]
    out = build_epub(caps, "T", "A", "pt-BR", tmp_path / "l.epub", cover=False)
    with zipfile.ZipFile(out) as zf:
        xhtml = zf.read("EPUB/cap1.xhtml").decode()
    assert 'href="#fn-5"' not in xhtml


# ---------------------------------------------------------------------------
# Capa procedural
# ---------------------------------------------------------------------------


def _capa_presente(zf):
    opf = zf.read("EPUB/content.opf").decode()
    nav = zf.read("EPUB/nav.xhtml").decode()
    ncx = zf.read("EPUB/toc.ncx").decode()
    capa = zf.read("EPUB/capa.xhtml").decode()
    ids = {}
    for tag in re.findall(r"<item\b[^>]*>", opf):
        mid = re.search(r'\bid="([^"]+)"', tag)
        href = re.search(r'\bhref="([^"]+)"', tag)
        if mid and href:
            ids[mid.group(1)] = href.group(1)
    spine = [ids.get(r, "?") for r in
             re.findall(r'<itemref[^>]*idref="([^"]+)"', opf)]
    return opf, nav, ncx, capa, spine


def test_epub_com_capa_por_padrao(tmp_path):
    out = build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        nomes = set(zf.namelist())
        opf, nav, ncx, capa, spine = _capa_presente(zf)
    assert "EPUB/cover.jpg" in nomes
    assert 'properties="cover-image"' in opf
    assert '<meta name="cover"' in opf
    assert "EPUB/capa.xhtml" in nomes
    assert spine[0] == "capa.xhtml"
    assert "capa.xhtml" not in nav and "capa.xhtml" not in ncx
    assert "cover.jpg" in capa
    validate_epub(out)


def test_epub_sem_capa(tmp_path):
    out = build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "l.epub",
                     cover=False)
    with zipfile.ZipFile(out) as zf:
        nomes = set(zf.namelist())
        opf = zf.read("EPUB/content.opf").decode()
    assert "EPUB/cover.jpg" not in nomes
    assert "capa.xhtml" not in opf
    assert 'properties="cover-image"' not in opf


def test_capa_usa_classe_capa_img_e_css(tmp_path):
    out = build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        capa = zf.read("EPUB/capa.xhtml").decode()
        css = zf.read("EPUB/style/kdp.css").decode()
        nomes = set(zf.namelist())
        capa_css = (zf.read("EPUB/style/capa.css").decode()
                    if "EPUB/style/capa.css" in nomes else "")
    assert 'class="capa-img"' in capa
    assert "cover.jpg" in capa
    assert ".capa-img" in css
    assert "style/capa.css" in capa
    assert "margin: 0" in capa_css


def test_nav_nao_polui_com_ancoras_de_nota(tmp_path):
    """A page-list do ebooklib nao pode despejar as ancoras de nota no nav."""
    caps = [Chapter("Cap", 1, [
        Paragraph([Run("pedem"), Run("7", superscript=True), Run(".")])],
        notes=[(7, "Nota.")])]
    out = build_epub(caps, "T", "A", "pt-BR", tmp_path / "l.epub", cover=False)
    with zipfile.ZipFile(out) as zf:
        nav = zf.read("EPUB/nav.xhtml").decode()
    assert "page-list" not in nav
    assert "fn-" not in nav
    assert "fnref-" not in nav


# ---------------------------------------------------------------------------
# Capa externa fornecida pelo usuario
# ---------------------------------------------------------------------------

_PNG_1PX = (
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAACXBIWXMAAA7EAAAOxAGVKw4b"
    "AAAAD0lEQVR4nGP4jwMwDC0JALoev0Ewkwr8AAAAAElFTkSuQmCC")
_JPEG_1PX = (
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAIBAQEBAQIBAQECAgICAgQDAgICAgUEBAMEBgUG"
    "BgYFBgYGBwkIBgcJBwYGCAsICQoKCgoKBggLDAsKDAkKCgr/2wBDAQICAgICAgUDAwUKBwYH"
    "CgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgr/wgARCAAI"
    "AAgDAREAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACP/EABQBAQAAAAAAAAAAAAAAAAAA"
    "AAD/2gAMAwEAAhADEAAAAX8f/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QA"
    "FBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/a"
    "AAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAA"
    "AAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABAf/8QAFBEBAAAAAAAAAAAA"
    "AAAAAAAAAP/aAAgBAwEBPxB//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPxB//8QA"
    "FBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxB//9k=")


def test_capa_externa_png_por_bytes(tmp_path):
    import base64

    capa = base64.b64decode(_PNG_1PX)
    assert capa[:8] == b"\x89PNG\r\n\x1a\n"
    out = build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "l.epub",
                     cover_image=capa)
    with zipfile.ZipFile(out) as zf:
        nomes = set(zf.namelist())
        opf = zf.read("EPUB/content.opf").decode()
        pagina = zf.read("EPUB/capa.xhtml").decode()
    assert "EPUB/cover.png" in nomes
    assert 'properties="cover-image"' in opf
    assert 'media-type="image/png"' in opf
    assert 'src="cover.png"' in pagina
    validate_epub(out)


def test_capa_externa_jpeg_por_caminho(tmp_path, capa_jpg):
    arquivo = tmp_path / "minha-capa.jpeg"
    arquivo.write_bytes(capa_jpg)
    out = build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "l.epub",
                     cover_image=arquivo)
    with zipfile.ZipFile(out) as zf:
        nomes = set(zf.namelist())
        opf = zf.read("EPUB/content.opf").decode()
        pagina = zf.read("EPUB/capa.xhtml").decode()
    assert "EPUB/cover.jpg" in nomes
    assert 'properties="cover-image"' in opf
    assert 'media-type="image/jpeg"' in opf
    assert 'src="cover.jpg"' in pagina
    validate_epub(out)


def test_capa_jpeg_ilegivel_e_recusada(tmp_path):
    """JPEG com assinatura valida que o decodificador recusa nao vira capa.

    `_JPEG_1PX` foi montado a mao e o libjpeg o rejeita: e exatamente o caso
    que a validacao existe para barrar, porque um arquivo assim sairia como
    pagina em branco no leitor.
    """
    import base64

    capa = base64.b64decode(_JPEG_1PX)
    assert capa[:3] == b"\xff\xd8\xff"
    with pytest.raises(ValueError):
        build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "l.epub",
                   cover_image=capa)


def test_capa_externa_none_mantem_capa_procedural(tmp_path):
    out = build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "l.epub",
                     cover=True, cover_image=None)
    with zipfile.ZipFile(out) as zf:
        nomes = set(zf.namelist())
    assert "EPUB/cover.jpg" in nomes


def test_capa_invalida_nao_gera_epub(tmp_path):
    """PDF renomeado para .jpg nao pode virar capa de um EPUB publicavel."""
    destino = tmp_path / "l.epub"
    with pytest.raises(ValueError):
        build_epub(_caps(), "T", "A", "pt-BR", destino,
                   cover_image=b"%PDF-1.4 nao sou imagem")
    assert not destino.exists()


def test_descricao_e_editora_viram_dublin_core(tmp_path):
    out = build_epub(_caps(), "Título", "Autora", "pt-BR", tmp_path / "l.epub",
                     description="Sinopse do livro.", publisher="Editora X")
    with zipfile.ZipFile(out) as zf:
        opf = zf.read("EPUB/content.opf").decode()
    assert "<dc:description>Sinopse do livro.</dc:description>" in opf
    assert "<dc:publisher>Editora X</dc:publisher>" in opf
    validate_epub(out)


def test_metadados_ausentes_nao_viram_tag_vazia(tmp_path):
    out = build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        opf = zf.read("EPUB/content.opf").decode()
    assert "dc:description" not in opf
    assert "dc:publisher" not in opf


def test_descricao_com_caractere_invalido_e_saneada(tmp_path):
    """O XML 1.0 nao aceita \\x00: sem saneamento o OPF inteiro quebra."""
    out = build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "l.epub",
                     description="antes\x00depois", publisher="E\x07ditora")
    with zipfile.ZipFile(out) as zf:
        opf = zf.read("EPUB/content.opf").decode()
    assert "antesdepois" in opf
    assert "Editora" in opf
    validate_epub(out)
