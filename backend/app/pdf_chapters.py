"""Deteccao de capitulos de um PDF.

Estrategia principal: usar os *bookmarks* (outline) embutidos no PDF, que sao a
fonte de verdade da estrutura do livro, ancorando cada entrada a uma linha real
do texto. Sem outline utilizavel, cai numa heuristica de fontes.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher

from .models import Anchor, Chapter, Line, Paragraph, Run
from .pdf_extract import extract_lines

# Similaridade minima entre titulo do outline e texto da linha para ancorar.
SIMILARITY_MIN = 0.72
# Piso para reancorar quando a melhor correspondencia fica abaixo do ideal.
REANCHOR_MIN = 0.5
# Fracao minima de entradas ancoradas para confiar no outline.
ANCHOR_COVERAGE_MIN = 0.80
# Linhas acima desta fracao da altura da pagina sao candidatas a titulo.
_TOP_BAND = 0.6

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Minusculas, sem acentos, apenas `[a-z0-9]`, espacos colapsados."""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return _NORMALIZE_RE.sub(" ", s).strip()


def modal_body_size(lines: list[Line]) -> float:
    """Tamanho de fonte que concentra mais caracteres (o corpo do texto).

    Ponderar por caracteres, e nao por numero de linhas, evita que uma pagina
    cheia de titulos curtos seja confundida com o corpo.
    """
    contagem: Counter[float] = Counter()
    for linha in lines:
        contagem[round(linha.size, 1)] += len(linha.text)
    if not contagem:
        return 12.0
    return contagem.most_common(1)[0][0]


def _title_like(linha: Line, body_size: float) -> bool:
    return linha.size > body_size * 1.05 or linha.bold


def _score(linha: Line, titulo: str, body_size: float) -> float:
    alvo = normalize(titulo)
    atual = normalize(linha.text)
    if not alvo or not atual:
        return 0.0
    score = SequenceMatcher(None, alvo, atual).ratio()
    if alvo == atual:
        score += 0.15
    if _title_like(linha, body_size):
        score += 0.10
    return score


def _melhor(indices: list[int], titulo: str, body_size: float,
            lines: list[Line]) -> tuple[int | None, float]:
    melhor: int | None = None
    melhor_score = 0.0
    for i in indices:
        score = _score(lines[i], titulo, body_size)
        if score > melhor_score:
            melhor, melhor_score = i, score
    return melhor, melhor_score


def anchor_outline(lines: list[Line], outline: list[list],
                   body_size: float) -> list[Anchor]:
    """Ancora as entradas do outline a linhas reais do documento.

    So considera linhas na banda superior da pagina da entrada e exige ordem
    monotonica de leitura. Uma entrada que nao casa bem e reancorada a uma linha
    elegivel (similaridade >= REANCHOR_MIN); se ainda assim nao houver
    candidato, a entrada e descartada em vez de virar um capitulo fantasma.
    """
    por_pagina: dict[int, list[int]] = defaultdict(list)
    for i, linha in enumerate(lines):
        por_pagina[linha.page].append(i)

    anchors: list[Anchor] = []
    ultimo = -1
    for entrada in outline:
        if len(entrada) < 3:
            continue
        nivel, titulo, pagina = entrada[0], entrada[1], entrada[2]
        try:
            pno = int(pagina) - 1
        except (TypeError, ValueError):
            continue
        if pno < 0:
            continue
        candidatos = [i for i in por_pagina.get(pno, [])
                      if i > ultimo
                      and lines[i].bbox[1] < _TOP_BAND * lines[i].page_height]
        escolha, score = _melhor(candidatos, titulo, body_size, lines)
        if escolha is not None and score >= SIMILARITY_MIN:
            anchors.append((escolha, int(nivel), str(titulo)))
            ultimo = escolha
            continue
        if escolha is not None and score >= REANCHOR_MIN:
            anchors.append((escolha, int(nivel), str(titulo)))
            ultimo = escolha
    return anchors


def outline_coverage(anchors: list[Anchor], outline: list[list]) -> float:
    """Fracao de entradas de outline que viraram ancora."""
    total = len([e for e in outline if len(e) >= 3])
    if not total:
        return 0.0
    return len(anchors) / total


# ---------------------------------------------------------------------------
# Fallback heuristico (PDFs sem bookmarks utilizaveis)
# ---------------------------------------------------------------------------

_CHAPTER_START_RE = re.compile(r"^(cap[íi]tulo|chapter|parte|part)\b",
                               re.IGNORECASE)
_NUMBERED_RE = re.compile(r"^\d+(?:\.\d+)*\s+\S")
_FRONT_MATTER_RE = re.compile(
    r"^(pref[áa]cio|introdu[çc][ãa]o|conclus[ãa]o|ep[íi]logo|ap[êe]ndice|"
    r"agradecimentos|bibliografia|[íi]ndice|sum[áa]rio|notas?)\b",
    re.IGNORECASE,
)
_MAX_TITLE_LEN = 90
_FOOTER_BAND = 0.9


def detect_headings(lines: list[Line], body_size: float) -> list[Anchor]:
    """Detecta titulos por heuristica de fonte e padrao textual.

    Usado apenas quando nao ha outline confiavel. Prefere poucos falsos
    positivos: linhas longas, frases terminadas em pontuacao e numeracao de
    pagina ficam de fora.
    """
    h1_min = body_size * 1.25
    h2_min = body_size * 1.10
    achados: list[Anchor] = []
    for i, linha in enumerate(lines):
        texto = linha.text.strip()
        if len(texto) < 3 or len(texto) > _MAX_TITLE_LEN:
            continue
        if linha.bbox[1] > _FOOTER_BAND * linha.page_height:
            continue
        if texto.isdigit():
            continue
        capitulo = bool(_CHAPTER_START_RE.match(texto))
        materias = bool(_FRONT_MATTER_RE.match(texto))
        numerado = bool(_NUMBERED_RE.match(texto))
        grande = linha.size >= h1_min
        medio = linha.size >= h2_min and (linha.bold or texto.isupper())
        if not (capitulo or materias or numerado or grande or medio):
            continue
        if capitulo or materias or grande:
            nivel = 1
        else:
            nivel = 2
        achados.append((i, nivel, texto))
    return achados


__all__ = [
    "ANCHOR_COVERAGE_MIN",
    "REANCHOR_MIN",
    "SIMILARITY_MIN",
    "anchor_outline",
    "assemble_chapters",
    "build_chapters",
    "cleaning_mask",
    "detect_headings",
    "is_page_number",
    "join_paragraphs",
    "modal_body_size",
    "normalize",
    "outline_coverage",
    "remove_running_lines",
    "sanitize",
]

# ---------------------------------------------------------------------------
# Limpeza e juncao de paragrafos
# ---------------------------------------------------------------------------

_PAGE_NUM_RE = re.compile(
    r"^(?:\d{1,4}|[ivxlcdm]{1,7}|p[áa]g(?:ina)?\.?\s*\d+)$", re.IGNORECASE)

_JUNK_RE = re.compile(
    r"^(?:www\.|https?://|\S+@\S+|isbn\b|©|copyright\b|"
    r"todos os direitos reservados)",
    re.IGNORECASE,
)

_HEADER_BAND = 0.06
_FOOTER_BAND = 0.93
_MAX_RUNNING_LEN = 110
_MIN_RUNNING_PAGES = 3


def is_page_number(text: str) -> bool:
    """Numeracao de pagina isolada (arabica, romana ou 'Pagina N')."""
    return bool(_PAGE_NUM_RE.match((text or "").strip()))


def _banda(linha: Line) -> str:
    if linha.bbox[1] < _HEADER_BAND * linha.page_height:
        return "top"
    if linha.bbox[3] > _FOOTER_BAND * linha.page_height:
        return "bot"
    return "mid"


def cleaning_mask(lines: list[Line], keep: set[int], *,
                  remove_header: bool,
                  remove_page_numbers: bool) -> list[bool]:
    """Mascara de linhas que sobrevivem a limpeza (mesma ordem de `lines`).

    Exposta porque `build_chapters` precisa remapear os indices das ancoras do
    outline apos o filtro.
    """
    exatas: dict[tuple[str, str], set[int]] = defaultdict(set)
    mascaras: dict[tuple[str, str], set[int]] = defaultdict(set)
    for linha in lines:
        faixa = _banda(linha)
        if faixa == "mid" or len(linha.text) >= _MAX_RUNNING_LEN:
            continue
        base = normalize(linha.text)
        if not base:
            continue
        exatas[(faixa, base)].add(linha.page)
        mascaras[(faixa, re.sub(r"\d+", "#", base))].add(linha.page)

    def repetida(linha: Line) -> bool:
        faixa = _banda(linha)
        if faixa == "mid" or len(linha.text) >= _MAX_RUNNING_LEN:
            return False
        base = normalize(linha.text)
        return (len(exatas.get((faixa, base), ())) >= _MIN_RUNNING_PAGES
                or len(mascaras.get((faixa, re.sub(r"\d+", "#", base)), ()))
                >= _MIN_RUNNING_PAGES)

    manter: list[bool] = []
    for i, linha in enumerate(lines):
        texto = linha.text.strip()
        if not texto:
            manter.append(False)
            continue
        if i in keep:
            manter.append(True)
            continue
        if remove_page_numbers and is_page_number(texto):
            manter.append(False)
            continue
        if len(texto) <= 120 and _JUNK_RE.match(texto):
            manter.append(False)
            continue
        if remove_header and repetida(linha):
            manter.append(False)
            continue
        manter.append(True)
    return manter


def remove_running_lines(lines: list[Line], keep: set[int], *,
                         remove_header: bool,
                         remove_page_numbers: bool) -> list[Line]:
    """Remove cabecalho/rodape repetidos, numeracao e linhas de junk.

    Cabecalhos sao detectados por banda (topo/rodape) + repeticao em paginas
    distintas, o que pega titulos correntes que mudam de texto a cada capitulo.
    Indices em `keep` (as ancoras do outline) nunca sao removidos.
    """
    manter = cleaning_mask(lines, keep, remove_header=remove_header,
                           remove_page_numbers=remove_page_numbers)
    return [linha for linha, fica in zip(lines, manter) if fica]


def _largura(linha: Line) -> float:
    return max(0.0, float(linha.bbox[2]) - float(linha.bbox[0]))


def _runs_da_linha(linha: Line) -> list[Run]:
    origem = list(linha.runs) if linha.runs else [Run(linha.text)]
    limpos: list[Run] = []
    for run in origem:
        texto = re.sub(r"\s+", " ", (run.text or "").replace("\u00ad", ""))
        limpos.append(Run(texto, italic=run.italic, bold=run.bold))
    if limpos:
        limpos[0].text = limpos[0].text.lstrip()
        limpos[-1].text = limpos[-1].text.rstrip()
    return [r for r in limpos if r.text]


def _sem_espaco_final(runs: list[Run]) -> None:
    while runs and not runs[-1].text:
        runs.pop()
    if runs:
        runs[-1].text = runs[-1].text.rstrip()


def _sem_espaco_inicial(runs: list[Run]) -> None:
    while runs and not runs[0].text:
        runs.pop(0)
    if runs:
        runs[0].text = runs[0].text.lstrip()


def _juntar_runs(destino: list[Run], novas: list[Run], separador: str) -> None:
    _sem_espaco_final(destino)
    _sem_espaco_inicial(novas)
    if not novas:
        return
    if destino and separador:
        destino.append(Run(separador))
    destino.extend(novas)


def _tirar_hifen_final(runs: list[Run]) -> None:
    if runs and runs[-1].text.endswith("-"):
        runs[-1].text = runs[-1].text[:-1]


def _continua_paragrafo(prev: Line, cur: Line, largura_max: float) -> bool:
    """Decide se `cur` continua o paragrafo iniciado em `prev`."""
    if abs(prev.size - cur.size) > 0.5 or prev.bold != cur.bold:
        return False
    if cur.page == prev.page:
        gap = float(cur.bbox[1]) - float(prev.bbox[3])
        if gap < -2 or gap > max(1.8 * cur.size, 6.0):
            return False
    larga = largura_max > 0 and _largura(prev) >= 0.8 * largura_max
    return larga or prev.text.rstrip().endswith("-")


def join_paragraphs(lines: list[Line]) -> list[Paragraph]:
    """Transforma linhas em paragrafos, atravessando paginas.

    Uma linha continua a anterior quando tem a mesma fonte, esta logo abaixo e
    ocupa quase toda a largura da coluna (sinal de que a frase continua). Na
    virada de pagina a checagem de espaco vertical e ignorada, porque o gap
    entre paginas nao tem significado.
    """
    larguras: dict[float, float] = {}
    for linha in lines:
        chave = round(linha.size, 1)
        larguras[chave] = max(larguras.get(chave, 0.0), _largura(linha))

    paragrafos: list[Paragraph] = []
    ultima: Line | None = None
    for linha in lines:
        novas = _runs_da_linha(linha)
        if not novas:
            continue
        largura_max = larguras.get(round(linha.size, 1), 0.0)
        if ultima is not None and _continua_paragrafo(ultima, linha, largura_max):
            primeiro = novas[0].text
            if (paragrafos[-1].text.endswith("-") and primeiro[:1].islower()
                    and primeiro[:1].isascii()):
                _tirar_hifen_final(paragrafos[-1].runs)
                _juntar_runs(paragrafos[-1].runs, novas, "")
            else:
                _juntar_runs(paragrafos[-1].runs, novas, " ")
        else:
            paragrafos.append(Paragraph(runs=novas))
        ultima = linha
    return paragrafos


# ---------------------------------------------------------------------------
# Montagem, sanidade e entrada publica
# ---------------------------------------------------------------------------

_MAX_NIVEL1 = 60


def assemble_chapters(lines: list[Line], anchors: list[Anchor]) -> list[Chapter]:
    """Fatia o fluxo de linhas entre ancoras consecutivas.

    A linha da ancora vira o titulo do capitulo e nao entra no corpo.
    """
    if not anchors:
        paragrafos = join_paragraphs(lines)
        return [Chapter("Conteúdo", 1, paragrafos)] if paragrafos else []
    ordem = sorted(anchors, key=lambda a: a[0])
    capitulos: list[Chapter] = []
    for pos, (indice, nivel, titulo) in enumerate(ordem):
        fim = ordem[pos + 1][0] if pos + 1 < len(ordem) else len(lines)
        corpo = lines[indice + 1:fim]
        capitulos.append(Chapter(titulo, min(max(int(nivel), 1), 3),
                                 join_paragraphs(corpo)))
    return capitulos


def _agrupar_ate(chapters: list[Chapter], limite: int) -> list[Chapter]:
    """Junta capitulos consecutivos em no maximo `limite` grupos."""
    if limite <= 0 or len(chapters) <= limite:
        return chapters
    passo = -(-len(chapters) // limite)  # teto da divisao
    agrupados: list[Chapter] = []
    for i in range(0, len(chapters), passo):
        grupo = chapters[i:i + passo]
        agrupados.append(Chapter(
            grupo[0].title,
            min(c.level for c in grupo),
            [p for c in grupo for p in c.paragraphs],
        ))
    return agrupados


def sanitize(chapters: list[Chapter],
             pages: int) -> tuple[list[Chapter], list[str]]:
    """Descarta capitulos vazios e degrada quando a deteccao explode.

    A degradacao so dispara por contagem absurda de capitulos: um livro real
    tem muito menos titulos do que paginas. Isso evita entregar um EPUB com
    centenas de "capitulos" gerados por um PDF que confundiu cabecalho com
    titulo.
    """
    avisos: list[str] = []
    vazios = [c for c in chapters if not c.paragraphs]
    validos = [c for c in chapters if c.paragraphs]
    if vazios:
        avisos.append(f"{len(vazios)} capítulo(s) sem conteúdo foram descartados.")
    if not validos:
        return [], ["Nenhum conteúdo extraído do PDF."]
    nivel1 = [c for c in validos if c.level == 1]
    limite = max(50.0, (pages or 1) / 1.5)
    if len(nivel1) > _MAX_NIVEL1 or len(validos) > limite:
        avisos.append("Detecção instável; usada a estratégia conservadora.")
        if nivel1 and len(nivel1) != len(validos):
            validos = nivel1
        validos = _agrupar_ate(validos, max(1, int(pages or 1)))
    return validos, avisos


def build_chapters(pdf_path, *, remove_header: bool = True,
                   remove_page_numbers: bool = True
                   ) -> tuple[list[Chapter], list[str]]:
    """Pipeline completo: PDF -> capitulos + avisos para o usuario."""
    lines, pages, outline = extract_lines(pdf_path)
    if not lines:
        return [Chapter("Texto", 1, [])], ["PDF sem texto extraível."]

    body_size = modal_body_size(lines)
    anchors: list[Anchor] = []
    avisos: list[str] = []
    if outline:
        anchors = anchor_outline(lines, outline, body_size)
    if not anchors or outline_coverage(anchors, outline) < ANCHOR_COVERAGE_MIN:
        anchors = detect_headings(lines, body_size)
        avisos.append("PDF sem sumário embutido: capítulos detectados por "
                      "heurística de fontes.")

    keep = {indice for indice, _, _ in anchors}
    manter = cleaning_mask(lines, keep, remove_header=remove_header,
                           remove_page_numbers=remove_page_numbers)
    limpas = [linha for linha, fica in zip(lines, manter) if fica]

    novo_indice: dict[int, int] = {}
    for antigo, fica in enumerate(manter):
        if fica:
            novo_indice[antigo] = len(novo_indice)
    anchors_limpos: list[Anchor] = [(novo_indice[i], nivel, titulo)
                                    for i, nivel, titulo in anchors
                                    if i in novo_indice]

    capitulos = assemble_chapters(limpas, anchors_limpos)
    capitulos, avisos_sanidade = sanitize(capitulos, pages)
    return capitulos, avisos + avisos_sanidade
