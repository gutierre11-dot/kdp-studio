"""Traducao de capitulos em lote via LLM.

Divide cada capitulo em blocos de ~`chunk_chars`, cortando em fronteira de
paragrafo, e **valida a estrutura**: o numero de paragrafos do resultado tem de
bater com o da entrada. Quando o modelo desalinha, o bloco e refeito paragrafo
a paragrafo — nunca se perde texto em silencio, nem se aceita um resultado com
a estrutura errada.
"""
from __future__ import annotations

import re
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Callable

from . import llm
from .models import Chapter, Paragraph

DEFAULT_TARGET_LANG = "pt-BR"
DEFAULT_SOURCE_LANG = "auto"


class CancelledError(RuntimeError):
    """O job de traducao foi cancelado pelo usuario."""

# Nomes legiveis para o prompt (sem acento: o modelo entende igual).
LANG_NAMES = {
    "pt": "portugues",
    "pt-br": "portugues brasileiro",
    "pt-pt": "portugues europeu",
    "en": "ingles",
    "es": "espanhol",
    "fr": "frances",
    "de": "alemao",
    "it": "italiano",
    "nl": "holandes",
    "ja": "japones",
    "zh": "chines",
    "ru": "russo",
}

# Fronteiras preferenciais de corte, da melhor para a pior.
_BOUNDARIES = (r"\n\n", r"(?<=[.!?\u2026])\s", r"\s")

# Palavras funcionais por idioma: baratas e suficientes para decidir entre
# idiomas europeus comuns, sem dependencia nova.
_STOPWORDS: dict[str, set[str]] = {
    "pt": {"de", "que", "nao", "os", "as", "um", "uma", "para", "com", "por",
           "do", "da", "em", "se", "no", "na", "mais", "como"},
    "en": {"the", "of", "and", "to", "in", "is", "that", "for", "with", "as",
           "was", "his", "her", "it", "on", "at", "by"},
    "es": {"el", "la", "de", "que", "y", "en", "los", "una", "para", "con",
           "por", "del", "se", "no", "su", "al"},
    "fr": {"le", "la", "les", "des", "est", "une", "pour", "dans", "que",
           "qui", "et", "un", "du", "au", "sur"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "ein", "mit", "von",
           "den", "sich", "auf", "dem", "des"},
    "it": {"il", "la", "di", "che", "un", "una", "per", "con", "non", "del",
           "della", "sono", "come", "gli"},
}

# Codigo do detector -> codigo usado no EPUB (dc:language).
_LANG_CODES = {"pt": "pt-BR", "en": "en", "es": "es", "fr": "fr",
               "de": "de", "it": "it"}


def detect_language(text: str, default: str = DEFAULT_TARGET_LANG) -> str:
    """Estimativa simples do idioma do texto, por palavras funcionais.

    Usada apenas para preencher `dc:language` quando o usuario nao informa o
    idioma e nao ha traducao; nao afeta o texto do livro.
    """
    palavras = re.findall(r"[a-z\u00e0-\u00ff]+", (text or "").lower())[:4000]
    if not palavras:
        return default
    contagem = {codigo: sum(1 for p in palavras if p in palavras_chave)
                for codigo, palavras_chave in _STOPWORDS.items()}
    melhor = max(contagem, key=lambda c: contagem[c])
    if contagem[melhor] <= 0:
        return default
    return _LANG_CODES.get(melhor, default)


def lang_name(code: str | None) -> str:
    """Nome legivel do idioma; devolve o proprio codigo se desconhecido."""
    if not code:
        return ""
    return LANG_NAMES.get(str(code).strip().lower(), str(code).strip())


def split_chunks(text: str, limit: int) -> list[str]:
    """Divide `text` em blocos de ate `limit` caracteres, sem perder nada.

    O corte e feito em fim de paragrafo, depois em fim de frase e por ultimo em
    espaco; nenhum caractere aparece em dois blocos.
    """
    if limit <= 0:
        raise ValueError("limit deve ser positivo")
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    inicio = 0
    total = len(text)
    while inicio < total:
        fim = min(inicio + limit, total)
        if fim < total:
            janela = text[inicio:fim]
            corte = 0
            for padrao in _BOUNDARIES:
                achados = list(re.finditer(padrao, janela))
                if achados:
                    corte = achados[-1].end()
                    break
            if corte > len(janela) * 0.5:
                fim = inicio + corte
        if fim <= inicio:  # seguranca: sempre avanca
            fim = min(inicio + limit, total)
        chunks.append(text[inicio:fim])
        inicio = fim
    return chunks


def build_system_prompt(source_lang: str | None = None,
                        target_lang: str | None = None, *,
                        title: str = "", chapter_title: str = "") -> str:
    """Prompt de traducao literaria para o par de idiomas informado."""
    destino = lang_name(target_lang) or lang_name(DEFAULT_TARGET_LANG)
    origem = lang_name(source_lang)
    partes = ["Você é um tradutor literário profissional."]
    if origem and str(source_lang or "").strip().lower() != "auto":
        partes.append(f"O texto de origem está em {origem}.")
    partes.append(f"Traduza o texto a seguir para {destino}, preservando nomes "
                  "próprios, tom literário e formatação.")
    partes.append("Mantenha EXATAMENTE a mesma quantidade de parágrafos, "
                  "separados por uma linha em branco.")
    partes.append("Retorne APENAS a tradução, sem comentários, títulos ou notas.")
    contexto = []
    if title:
        contexto.append(f"Livro: {title}.")
    if chapter_title:
        contexto.append(f"Capítulo: {chapter_title}.")
    if contexto:
        partes.append(" ".join(contexto))
    return " ".join(partes)


def build_title_prompt(target_lang: str | None = None) -> str:
    """Prompt curto para traduzir o titulo de um capitulo."""
    destino = lang_name(target_lang) or lang_name(DEFAULT_TARGET_LANG)
    return ("Você é um tradutor literário profissional. Traduza apenas o título "
            f"a seguir para {destino}. Retorne somente o título traduzido, em uma "
            "única linha, sem comentários e sem aspas.")


def _translate_text(text: str, *, system: str,
                    model: str | None = None) -> str:
    """Ponto unico de chamada ao LLM (isolado para facilitar teste)."""
    return llm.chat(system, text, model=model)


def _traduzir_titulo(titulo: str, sistema: str, model: str | None,
                     warn: Callable[[str], None], contexto: str) -> str:
    if not titulo.strip():
        return titulo
    try:
        saida = _translate_text(titulo, system=sistema, model=model)
    except llm.LLMError as exc:
        warn(f"Capítulo {contexto!r}: título mantido no idioma original ({exc}).")
        return titulo
    primeira = saida.strip().split("\n")[0].strip()
    return primeira or titulo


def _traduzir_um(texto: str, sistema: str, model: str | None,
                 warn: Callable[[str], None], contexto: str) -> str:
    """Traduz um unico paragrafo (ou pedaco de paragrafo gigante)."""
    if not texto.strip():
        return texto
    try:
        saida = _translate_text(texto, system=sistema, model=model)
    except llm.LLMError as exc:
        warn(f"Capítulo {contexto!r}: trecho mantido no idioma original ({exc}).")
        return texto
    partes = [p.strip() for p in saida.split("\n\n") if p.strip()]
    return " ".join(partes) or texto


def _traduzir_bloco(texto: str, esperados: int, sistema: str,
                    model: str | None, warn: Callable[[str], None],
                    contexto: str) -> list[str]:
    """Traduz um bloco de N paragrafos, garantindo N paragrafos na saida."""
    if esperados <= 1:
        return [_traduzir_um(texto, sistema, model, warn, contexto)]
    try:
        saida = _translate_text(texto, system=sistema, model=model)
    except llm.LLMError as exc:
        # Cadeia de modelos fora: insistir paragrafo a paragrafo gastaria N
        # chamadas ja condenadas (cada uma com timeout). Mantem o original.
        warn(f"Capítulo {contexto!r}: trecho mantido no idioma original ({exc}).")
        return list(texto.split("\n\n"))
    novos = [p for p in saida.split("\n\n") if p.strip()]
    if len(novos) == esperados:
        return novos
    warn(f"Capítulo {contexto!r}: o modelo desalinhou os parágrafos; "
         "refazendo parágrafo a parágrafo.")
    return [_traduzir_um(p, sistema, model, warn, contexto)
            for p in texto.split("\n\n")]


def montar_unidades(paragrafos: list[str],
                    limite: int) -> list[tuple[list[int], str]]:
    """Agrupa paragrafos em blocos de ate `limite` caracteres.

    Um paragrafo sozinho maior que o limite e dividido por `split_chunks`; todos
    os pedacos apontam para o mesmo indice e sao reunidos depois.
    """
    unidades: list[tuple[list[int], str]] = []
    indices: list[int] = []
    textos: list[str] = []
    for i, paragrafo in enumerate(paragrafos):
        if len(paragrafo) > limite:
            if indices:
                unidades.append((indices, "\n\n".join(textos)))
                indices, textos = [], []
            unidades.extend(([i], parte)
                            for parte in split_chunks(paragrafo, limite))
            continue
        candidato = "\n\n".join(textos + [paragrafo])
        if indices and len(candidato) > limite:
            unidades.append((indices, "\n\n".join(textos)))
            indices, textos = [i], [paragrafo]
        else:
            indices.append(i)
            textos.append(paragrafo)
    if indices:
        unidades.append((indices, "\n\n".join(textos)))
    return unidades


def translate_chapter(chapter: Chapter, *, title: str, source_lang: str,
                      target_lang: str, model: str | None, chunk_chars: int,
                      warn: Callable[[str], None]) -> Chapter:
    """Traduz um capitulo preservando a contagem de paragrafos."""
    paragrafos = [p.text for p in chapter.paragraphs]
    if not paragrafos:
        return Chapter(chapter.title, chapter.level, [])
    sistema = build_system_prompt(source_lang, target_lang, title=title,
                                  chapter_title=chapter.title)
    titulo = _traduzir_titulo(chapter.title, build_title_prompt(target_lang),
                              model, warn, chapter.title)

    por_indice: dict[int, list[str]] = {}
    for indices, texto in montar_unidades(paragrafos, chunk_chars):
        traduzidos = _traduzir_bloco(texto, len(indices), sistema, model,
                                     warn, chapter.title)
        for i, trecho in zip(indices, traduzidos):
            por_indice.setdefault(i, []).append(trecho)

    novos: list[str] = []
    for i, original in enumerate(paragrafos):
        partes = [p.strip() for p in por_indice.get(i, []) if p.strip()]
        novos.append(" ".join(partes) if partes else original)
    return Chapter(titulo, chapter.level, [Paragraph.from_text(t) for t in novos])


def translate_chapters(
    chapters: list[Chapter], *, title: str, source_lang: str, target_lang: str,
    model: str | None, workers: int, chunk_chars: int,
    progress: Callable[[int, str], None] | None = None,
    cancel: threading.Event | None = None,
) -> tuple[list[Chapter], list[str]]:
    """Traduz todos os capitulos com paralelismo limitado e progresso real.

    Usa janela deslizante (no maximo `workers` unidades em voo) para que o
    cancelamento tenha efeito rapido. O contador de concluidos e a chamada a
    `progress` ficam sob o mesmo lock, garantindo percentuais nao decrescentes
    mesmo com completions fora de ordem.
    """
    if not chapters:
        return [], []

    unidades: list[tuple[int, list[int] | None, str]] = []
    for ci, capitulo in enumerate(chapters):
        if capitulo.title.strip():
            unidades.append((ci, None, capitulo.title))
        for indices, texto in montar_unidades([p.text for p in capitulo.paragraphs],
                                              chunk_chars):
            unidades.append((ci, indices, texto))
    if not unidades:
        if progress is not None:
            progress(100, "Nada a traduzir")
        return list(chapters), []

    total = len(unidades)
    traducao: dict[int, dict[int, list[str]]] = {i: {} for i in range(len(chapters))}
    titulos: dict[int, str] = {}
    avisos: list[str] = []
    lock = threading.Lock()
    concluidos = 0

    def trabalho(ci: int, indices: list[int] | None,
                 texto: str) -> tuple[int, list[int] | None, list[str], list[str]]:
        capitulo = chapters[ci]
        locais: list[str] = []

        def warn(msg: str) -> None:
            locais.append(msg)

        try:
            if indices is None:
                return ci, None, [_traduzir_titulo(
                    texto, build_title_prompt(target_lang), model, warn,
                    capitulo.title)], locais
            sistema = build_system_prompt(source_lang, target_lang, title=title,
                                          chapter_title=capitulo.title)
            resultado = _traduzir_bloco(texto, len(indices), sistema, model,
                                        warn, capitulo.title)
        except Exception as exc:  # erro inesperado: nao derruba o livro
            warn(f"Capítulo {capitulo.title!r}: trecho mantido no idioma "
                 f"original ({exc}).")
            resultado = texto.split("\n\n")
        return ci, indices, resultado, locais

    n_workers = max(1, int(workers))
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        em_voo: dict[Future, tuple[int, list[int], str]] = {}
        proximo = 0
        try:
            while proximo < total or em_voo:
                while proximo < total and len(em_voo) < n_workers:
                    if cancel is not None and cancel.is_set():
                        raise CancelledError("tradução cancelada")
                    em_voo[pool.submit(trabalho, *unidades[proximo])] = \
                        unidades[proximo]
                    proximo += 1
                if not em_voo:
                    break
                concluidos_agora, _ = wait(em_voo, return_when=FIRST_COMPLETED)
                for futuro in concluidos_agora:
                    ci, indices, resultado, locais = futuro.result()
                    em_voo.pop(futuro, None)
                    with lock:
                        concluidos += 1
                        if indices is None:
                            titulos[ci] = resultado[0]
                        else:
                            for i, trecho in zip(indices, resultado):
                                traducao[ci].setdefault(i, []).append(trecho)
                        avisos.extend(locais)
                        if progress is not None:
                            progress(int(100 * concluidos / total),
                                     f"Traduzindo {concluidos}/{total}")
        except CancelledError:
            for futuro in em_voo:
                futuro.cancel()
            raise

    saida: list[Chapter] = []
    for ci, capitulo in enumerate(chapters):
        paragrafos = [p.text for p in capitulo.paragraphs]
        novos: list[str] = []
        for i, original in enumerate(paragrafos):
            partes = [p.strip() for p in traducao[ci].get(i, []) if p.strip()]
            novos.append(" ".join(partes) if partes else original)
        saida.append(Chapter(titulos.get(ci, capitulo.title), capitulo.level,
                             [Paragraph.from_text(t) for t in novos]))

    mudou = any(
        novo != original
        for cap_original, cap_novo in zip(chapters, saida)
        for original, novo in zip((p.text for p in cap_original.paragraphs),
                                  (p.text for p in cap_novo.paragraphs))
    )
    if not mudou and any(c.paragraphs for c in chapters):
        # Nada mudou: nenhum modelo respondeu. Reportar sucesso aqui seria
        # entregar o livro no idioma original como se estivesse traduzido.
        raise llm.LLMError("A tradução não produziu texto novo: nenhum modelo "
                           "respondeu. Tente novamente mais tarde.")
    return saida, avisos
