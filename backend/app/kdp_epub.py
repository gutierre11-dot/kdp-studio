"""Montagem do EPUB 3 no padrao KDP.

O arquivo e escrito por `ebooklib`, que coloca o `mimetype` como primeira
entrada e sem compressao (exigencia do EPUB). A validacao de integridade e a
escrita atomica vivem no mesmo modulo e sao a garantia de que nenhum EPUB
invalido chega ao diretorio de saida.
"""
from __future__ import annotations

import html
import os
import re
import uuid
import zipfile
from pathlib import Path

from .models import Chapter, Paragraph, Run

_OBRIGATORIOS = ("META-INF/container.xml", "EPUB/content.opf",
                 "EPUB/nav.xhtml", "EPUB/toc.ncx")

# Caracteres que o XML 1.0 nao aceita: controles C0 (exceto tab/LF/CR),
# surrogates soltos e os nao-caracteres FFFE/FFFF. Sem essa limpeza, o parser
# do ebooklib engole o documento inteiro e o paragrafo sai truncado.
_XML_INVALIDO = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


class EpubValidationError(RuntimeError):
    """O EPUB gerado nao passou na verificacao de integridade."""


def sanitize_text(valor: object) -> str:
    """Remove caracteres invalidos em XML 1.0 de um texto qualquer."""
    if valor is None:
        return ""
    return _XML_INVALIDO.sub("", str(valor))

# CSS de leitura KDP: serif, justificado, recuo de primeira linha, quebra de
# pagina nos titulos de capitulo e controle de viuvas/orfas.
KDP_CSS = """
body { font-family: Georgia, 'Times New Roman', serif; font-size: 1em;
       line-height: 1.5; margin: 0 5%; text-align: justify; }
h1 { font-size: 1.7em; text-align: center; margin: 3em 0 1em;
     page-break-before: always; }
h2 { font-size: 1.3em; text-align: left; margin: 2em 0 .8em;
     page-break-before: always; }
h3 { font-size: 1.1em; text-align: left; margin: 1.5em 0 .6em; }
p  { margin: 0 0 .3em; text-indent: 1.25em; widows: 2; orphans: 2; }
p.noindent, h1 + p, h2 + p, h3 + p { text-indent: 0; }
.titulo-livro { text-align: center; font-size: 2em; margin-top: 30%; }
.autor-livro { text-align: center; font-size: 1.1em; margin-top: 1em; }
sup { font-size: .72em; vertical-align: super; line-height: 0; }
a.noteref { text-decoration: none; }
hr.notas-sep { border: 0; border-top: 1px solid #888; width: 40%;
               margin: 2em auto 1em; }
aside.notas { font-size: .9em; }
.notas-titulo { text-align: left; font-size: 1.05em; margin: 0 0 .6em;
                page-break-before: auto; }
aside.notas ol { padding-left: 1.4em; }
aside.notas li { margin-bottom: .4em; }
aside.notas p { text-indent: 0; margin: 0; }
a.noteref-back { text-decoration: none; }
.capa-img { width: 100%; height: 100%; }
"""


def _esc(valor: object) -> str:
    return html.escape(sanitize_text(valor))


def _runs_html(paragrafo: Paragraph, notas_disponiveis: set[int] | None = None,
               refs_vistos: set[int] | None = None) -> str:
    """HTML dos runs; chamador de nota vira link para a nota do capitulo.

    `notas_disponiveis` guarda os numeros de nota do capitulo; um superscript
    numerico sem nota correspondente fica so como `<sup>` (nunca link quebrado).
    `refs_vistos` evita repetir o `id` do chamador no mesmo arquivo.
    """
    disponiveis = notas_disponiveis or set()
    partes: list[str] = []
    for run in paragrafo.runs:
        texto = _esc(run.text)
        if getattr(run, "superscript", False):
            bruto = run.text.strip()
            if bruto.isdigit() and int(bruto) in disponiveis:
                n = int(bruto)
                ident = ""
                if refs_vistos is None or n not in refs_vistos:
                    ident = f' id="fnref-{n}"'
                if refs_vistos is not None:
                    refs_vistos.add(n)
                partes.append(
                    f'<a class="noteref"{ident} href="#fn-{n}" '
                    f'epub:type="noteref"><sup>{bruto}</sup></a>')
                continue
            texto = f"<sup>{texto}</sup>"
        if run.italic:
            texto = f"<em>{texto}</em>"
        if run.bold:
            texto = f"<strong>{texto}</strong>"
        partes.append(texto)
    return "".join(partes)


def _notas_html(notas: list[tuple[int, str]],
                refs_citados: set[int]) -> str:
    """Bloco de endnotes do capitulo, com backlink para o chamador.

    O backlink so entra quando o chamador esta no mesmo arquivo: um capitulo
    longo dividido em continuacoes repete as notas em cada parte para os links
    resolverem, e nas partes onde a nota nao e citada o voltar nao teria alvo.
    """
    blocos = ['<hr class="notas-sep"/>',
              '<aside class="notas" epub:type="footnotes">',
              '<h2 class="notas-titulo">Notas</h2>',
              "<ol>"]
    for numero, texto in notas:
        voltar = ""
        if numero in refs_citados:
            voltar = (f' <a class="noteref-back" href="#fnref-{numero}" '
                      f'epub:type="backlink">↩</a>')
        blocos.append(
            f'<li id="fn-{numero}" epub:type="footnote">'
            f'<p>{_esc(texto)}{voltar}</p></li>')
    blocos.append("</ol></aside>")
    return "\n".join(blocos)


def chapter_fragment(chapter: Chapter) -> str:
    """Fragmento de corpo XHTML de um capitulo.

    O `ebooklib` envolve o fragmento no template dele (html/head/body e o link
    do CSS), entao aqui nao entram declaracao XML nem tags de documento. Uma
    continuacao nao emite cabecalho: o titulo ja apareceu na primeira parte e
    nao deve se repetir no meio da leitura. As notas de rodape do capitulo
    entram como endnotes ao final do fragmento.
    """
    notas = list(getattr(chapter, "notes", []) or [])
    notas_disponiveis = {n for n, _ in notas}
    refs_vistos: set[int] = set()
    partes: list[str] = []
    if not getattr(chapter, "continues", False):
        nivel = min(max(int(chapter.level), 1), 3)
        tag = f"h{nivel}"
        # Chamadores que vivem na propria linha do titulo viram links logo
        # depois do texto do heading (e contam para o backlink da nota).
        title_refs = [int(r) for r in (getattr(chapter, "title_refs", []) or [])]
        sufixo = ""
        if title_refs:
            sufixo = _runs_html(
                Paragraph([Run(str(n), superscript=True) for n in title_refs]),
                notas_disponiveis, refs_vistos)
        partes.append(f"<{tag}>{_esc(chapter.title)}{sufixo}</{tag}>")
    for i, paragrafo in enumerate(chapter.paragraphs):
        classe = ' class="noindent"' if i == 0 else ""
        corpo = _runs_html(paragrafo, notas_disponiveis, refs_vistos)
        partes.append(f"<p{classe}>{corpo}</p>")
    if notas:
        partes.append(_notas_html(notas, refs_vistos))
    return "\n".join(partes)


def build_toc_tree(pares: list[tuple[int, object]]) -> list:
    """Aninha itens de indice conforme o nivel (1..3).

    Devolve a estrutura que o `ebooklib` entende: um item isolado e uma folha;
    `(item, [filhos])` e um no com subitens.
    """
    raiz: list = []
    pilha: list[tuple[int, list]] = [(0, raiz)]
    for nivel, item in pares:
        while len(pilha) > 1 and nivel <= pilha[-1][0]:
            pilha.pop()
        filhos: list = []
        pilha[-1][1].append((item, filhos))
        pilha.append((nivel, filhos))

    def converter(nos: list) -> list:
        saida: list = []
        for item, filhos in nos:
            saida.append((item, converter(filhos)) if filhos else item)
        return saida

    return converter(raiz)


def build_epub(chapters: list[Chapter], title: str, author: str, language: str,
               out_path: Path | str, cover: bool = True,
               cover_image: str | Path | bytes | None = None) -> Path:
    """Escreve o EPUB 3 de forma atomica, validando antes de publicar.

    Monta num temporario no mesmo diretorio, valida a integridade e so entao
    troca pelo arquivo final. Se a validacao falhar, nenhum EPUB invalido
    aparece em `output/` e o temporario e removido. Com `cover=True` (padrao)
    a capa e embutida como imagem de capa e primeira pagina: `cover_image`
    (caminho ou bytes JPEG/PNG) usa a imagem fornecida; sem ele, gera a capa
    procedural. `cover=False` nao inclui capa.
    """
    destino = Path(out_path)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(
        f"{destino.stem}.tmp-{uuid.uuid4().hex}{destino.suffix}")
    try:
        _write_epub_file(chapters, title, author, language, temporario,
                         cover=cover, cover_image=cover_image)
        validate_epub(temporario)
        os.replace(temporario, destino)
    except BaseException:
        temporario.unlink(missing_ok=True)
        raise
    return destino


def _gerar_capa_bytes(title: str, author: str) -> bytes:
    """Gera a capa num temporario e devolve os bytes do JPEG."""
    import tempfile

    from .cover import build_cover

    with tempfile.TemporaryDirectory() as pasta:
        caminho = Path(pasta) / "cover.jpg"
        build_cover(title, author, caminho)
        return caminho.read_bytes()


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


def _ler_capa_externa(cover_image: str | Path | bytes
                      ) -> tuple[str, bytes]:
    """Le a capa fornecida e devolve `(extensao, bytes)`.

    O tipo e detectado pelos magic bytes e, na falta deles, pela extensao do
    arquivo. So JPEG e PNG sao aceitos (formatos de imagem de capa validos).
    """
    if isinstance(cover_image, (bytes, bytearray)):
        dados = bytes(cover_image)
        sufixo = ""
    else:
        caminho = Path(cover_image)
        dados = caminho.read_bytes()
        sufixo = caminho.suffix.lower().lstrip(".")
    if dados[:8] == _PNG_MAGIC:
        return "png", dados
    if dados[:3] == _JPEG_MAGIC:
        return "jpg", dados
    if sufixo in ("png",):
        return "png", dados
    if sufixo in ("jpg", "jpeg"):
        return "jpg", dados
    raise ValueError("capa deve ser uma imagem JPEG ou PNG")


def _write_epub_file(chapters: list[Chapter], title: str, author: str,
                     language: str, out_path: Path, *,
                     cover: bool = True,
                     cover_image: str | Path | bytes | None = None) -> Path:
    """Montagem crua do arquivo (sem validacao nem atomicidade)."""
    from ebooklib import epub

    destino = Path(out_path)
    destino.parent.mkdir(parents=True, exist_ok=True)

    livro = epub.EpubBook()
    titulo_limpo = sanitize_text(title) or "Sem título"
    autor_limpo = sanitize_text(author) or "Autor Desconhecido"
    idioma_limpo = sanitize_text(language) or "pt-BR"
    ident = f"{titulo_limpo}|{autor_limpo}"
    livro.set_identifier(f"kdp-{uuid.uuid5(uuid.NAMESPACE_DNS, ident).hex[:12]}")
    livro.set_title(titulo_limpo)
    livro.set_language(idioma_limpo)
    livro.add_author(autor_limpo)

    estilo = epub.EpubItem(uid="style_kdp", file_name="style/kdp.css",
                           media_type="text/css", content=KDP_CSS.encode())
    livro.add_item(estilo)

    pagina_capa = None
    if cover:
        if cover_image is not None:
            extensao, dados = _ler_capa_externa(cover_image)
        else:
            extensao, dados = "jpg", _gerar_capa_bytes(title, author)
        nome_capa = f"cover.{extensao}"
        livro.set_cover(nome_capa, dados, create_page=False)
        capa_estilo = epub.EpubItem(
            uid="style_capa", file_name="style/capa.css",
            media_type="text/css",
            content=("body { margin: 0; padding: 0; text-align: center; }\n"
                     ".capa-img { width: 100%; height: 100%; }\n").encode())
        livro.add_item(capa_estilo)
        # A capa entra como primeiro item LINEAR do spine: e assim que os
        # leitores abrem o livro. Marca-la como nao-linear exigiria um link de
        # landmark apontando para ela (o EPUBCheck acusa OPF-096 sem isso).
        pagina_capa = epub.EpubHtml(title="Capa", file_name="capa.xhtml",
                                    content=f'<img class="capa-img" '
                                            f'src="{nome_capa}" alt="Capa"/>')
        pagina_capa.add_item(estilo)
        pagina_capa.add_item(capa_estilo)
        livro.add_item(pagina_capa)

    frontis = (
        f'<div class="titulo-livro">{_esc(title)}</div>'
        f'<div class="autor-livro">{_esc(author)}</div>'
    )
    pagina_titulo = epub.EpubHtml(title="Título", file_name="titulo.xhtml",
                                  content=frontis)
    pagina_titulo.add_item(estilo)
    livro.add_item(pagina_titulo)

    itens = []
    pares: list[tuple[int, object]] = []
    for i, capitulo in enumerate(chapters, start=1):
        titulo_cap = sanitize_text(capitulo.title) or f"Capítulo {i}"
        item = epub.EpubHtml(
            title=titulo_cap,
            file_name=f"cap{i}.xhtml",
            content=chapter_fragment(capitulo),
        )
        item.add_item(estilo)
        livro.add_item(item)
        itens.append(item)
        # Continuacoes entram no spine (leitura sequencial) mas nao no TOC.
        if not getattr(capitulo, "continues", False):
            pares.append((min(max(int(capitulo.level), 1), 3), item))

    livro.toc = tuple(build_toc_tree(pares))
    spine = [pagina_titulo] + itens
    if pagina_capa is not None:
        spine = [pagina_capa] + spine
    livro.spine = spine
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    # `epub3_pages` ligado faria o ebooklib varrer todo `id` do corpo e despejar
    # uma `page-list` oculta com centenas de ancoras de nota no nav. Nao usamos
    # marcadores de pagina, entao a page-list nao tem utilidade aqui.
    epub.write_epub(str(destino), livro, {"epub3_pages": False})
    return destino


def validate_epub(path: Path | str) -> None:
    """Verifica a integridade do EPUB; levanta EpubValidationError se falhar.

    Cobre as causas de rejeicao que ja apareceram na pratica: manifest
    apontando para arquivos que nao existem no ZIP e ausencia de nav/ncx.
    """
    arquivo = Path(path)
    if not arquivo.is_file():
        raise EpubValidationError(f"EPUB não encontrado: {arquivo}")
    try:
        zf = zipfile.ZipFile(arquivo)
    except zipfile.BadZipFile as exc:
        raise EpubValidationError(f"EPUB não é um ZIP válido: {exc}") from exc

    with zf:
        infos = zf.infolist()
        if not infos:
            raise EpubValidationError("EPUB vazio.")
        primeira = infos[0]
        if primeira.filename != "mimetype":
            raise EpubValidationError(
                "A primeira entrada do EPUB deve ser 'mimetype'.")
        if primeira.compress_type != zipfile.ZIP_STORED:
            raise EpubValidationError(
                "A entrada 'mimetype' deve estar sem compressão.")
        if zf.read("mimetype") != b"application/epub+zip":
            raise EpubValidationError("Conteúdo de 'mimetype' inválido.")

        nomes = set(zf.namelist())
        for obrigatorio in ("META-INF/container.xml", "EPUB/content.opf"):
            if obrigatorio not in nomes:
                raise EpubValidationError(
                    f"EPUB sem o arquivo obrigatório {obrigatorio!r}.")

        opf = zf.read("EPUB/content.opf").decode("utf-8", errors="replace")

        hrefs = re.findall(r'href="([^"]+)"', opf)
        ausentes = sorted({h for h in hrefs
                           if not h.startswith(("http:", "https:", "#"))
                           and f"EPUB/{h}" not in nomes})
        if ausentes:
            raise EpubValidationError(
                "EPUB referencia arquivos ausentes: " + ", ".join(ausentes[:5]))

        for obrigatorio in _OBRIGATORIOS[2:]:
            if obrigatorio not in nomes:
                raise EpubValidationError(
                    f"EPUB sem o arquivo obrigatório {obrigatorio!r}.")

        if 'properties="nav"' not in opf:
            raise EpubValidationError(
                "O item de navegação não está declarado com properties=\"nav\".")

        ids = set(re.findall(r'<item\b[^>]*\bid="([^"]+)"', opf))
        idrefs = re.findall(r'<itemref\b[^>]*\bidref="([^"]+)"', opf)
        orfaos = sorted({i for i in idrefs if i not in ids})
        if orfaos:
            raise EpubValidationError(
                "O spine referencia itens fora do manifest: " + ", ".join(orfaos))
