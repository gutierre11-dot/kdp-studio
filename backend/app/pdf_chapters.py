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

from .models import Anchor, Line
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


__all__ = [
    "ANCHOR_COVERAGE_MIN",
    "REANCHOR_MIN",
    "SIMILARITY_MIN",
    "anchor_outline",
    "modal_body_size",
    "normalize",
    "outline_coverage",
]
