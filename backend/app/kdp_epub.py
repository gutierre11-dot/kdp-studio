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


class EpubValidationError(RuntimeError):
    """O EPUB gerado nao passou na verificacao de integridade."""

# CSS de leitura KDP: serif, justificado, recuo de primeira linha, quebra de
# pagina nos titulos de capitulo e controle de viuvas/orfas.
KDP_CSS = """
body { font-family: Georgia, 'Times New Roman', serif; font-size: 1em;
       line-height: 1.5; margin: 0 5%; text-align: justify; }
h1 { font-size: 1.7em; text-align: center; margin: 3em 0 1em;
     page-break-before: always; }
h2 { font-size: 1.3em; margin: 2em 0 .8em; }
h3 { font-size: 1.1em; margin: 1.5em 0 .6em; }
p  { margin: 0 0 .3em; text-indent: 1.25em; widows: 2; orphans: 2; }
p.noindent, h1 + p, h2 + p, h3 + p { text-indent: 0; }
.titulo-livro { text-align: center; font-size: 2em; margin-top: 30%; }
.autor-livro { text-align: center; font-size: 1.1em; margin-top: 1em; }
"""


def _esc(valor: object) -> str:
    return html.escape("" if valor is None else str(valor))


def _runs_html(paragrafo: Paragraph) -> str:
    partes: list[str] = []
    for run in paragrafo.runs:
        texto = _esc(run.text)
        if run.italic:
            texto = f"<em>{texto}</em>"
        if run.bold:
            texto = f"<strong>{texto}</strong>"
        partes.append(texto)
    return "".join(partes)


def chapter_fragment(chapter: Chapter) -> str:
    """Fragmento de corpo XHTML de um capitulo.

    O `ebooklib` envolve o fragmento no template dele (html/head/body e o link
    do CSS), entao aqui nao entram declaracao XML nem tags de documento.
    """
    nivel = min(max(int(chapter.level), 1), 3)
    tag = f"h{nivel}"
    partes = [f"<{tag}>{_esc(chapter.title)}</{tag}>"]
    for i, paragrafo in enumerate(chapter.paragraphs):
        classe = ' class="noindent"' if i == 0 else ""
        partes.append(f"<p{classe}>{_runs_html(paragrafo)}</p>")
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
               out_path: Path | str) -> Path:
    """Escreve o EPUB 3 de forma atomica, validando antes de publicar.

    Monta num temporario no mesmo diretorio, valida a integridade e so entao
    troca pelo arquivo final. Se a validacao falhar, nenhum EPUB invalido
    aparece em `output/` e o temporario e removido.
    """
    destino = Path(out_path)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(
        f"{destino.stem}.tmp-{uuid.uuid4().hex}{destino.suffix}")
    try:
        _write_epub_file(chapters, title, author, language, temporario)
        validate_epub(temporario)
        os.replace(temporario, destino)
    except BaseException:
        temporario.unlink(missing_ok=True)
        raise
    return destino


def _write_epub_file(chapters: list[Chapter], title: str, author: str,
                     language: str, out_path: Path) -> Path:
    """Montagem crua do arquivo (sem validacao nem atomicidade)."""
    from ebooklib import epub

    destino = Path(out_path)
    destino.parent.mkdir(parents=True, exist_ok=True)

    livro = epub.EpubBook()
    ident = f"{title or 'livro'}|{author or 'autor'}"
    livro.set_identifier(f"kdp-{uuid.uuid5(uuid.NAMESPACE_DNS, ident).hex[:12]}")
    livro.set_title(title or "Sem título")
    livro.set_language(language or "pt-BR")
    livro.add_author(author or "Autor Desconhecido")

    estilo = epub.EpubItem(uid="style_kdp", file_name="style/kdp.css",
                           media_type="text/css", content=KDP_CSS.encode())
    livro.add_item(estilo)

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
        item = epub.EpubHtml(
            title=capitulo.title or f"Capítulo {i}",
            file_name=f"cap{i}.xhtml",
            content=chapter_fragment(capitulo),
        )
        item.add_item(estilo)
        livro.add_item(item)
        itens.append(item)
        pares.append((min(max(int(capitulo.level), 1), 3), item))

    livro.toc = tuple(build_toc_tree(pares))
    livro.spine = [pagina_titulo] + itens
    livro.add_item(epub.EpubNcx())
    livro.add_item(epub.EpubNav())
    epub.write_epub(str(destino), livro)
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
