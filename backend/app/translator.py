"""Traducao via LLM OpenAI-compatible (OpenAI ou Gemini) + fallback offline.

Regras:
- O idioma de destino e' respeitado (antes o SYSTEM_PROMPT fixava pt-BR e o
  parametro target_lang do frontend era ignorado).
- A divisao em blocos nao usa sobreposicao (overlap), portanto nao duplica
  texto no resultado final.
"""
import logging
import re
from typing import List

from .llm import llm_available, make_client, resolve_chat_model

log = logging.getLogger(__name__)

CHUNK_SIZE = 3000

# Nomes legiveis para o prompt e para o mock offline.
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

DEFAULT_TARGET_LANG = "pt-BR"
DEFAULT_SOURCE_LANG = "auto"

# Fronteiras preferenciais de corte, da melhor para a pior.
_BOUNDARIES = (r"\n\n", r"(?<=[.!?\u2026])\s", r"\s")


def lang_name(code: str | None) -> str:
    """Nome legivel do idioma; devolve o proprio codigo se desconhecido."""
    if not code:
        return ""
    return LANG_NAMES.get(str(code).strip().lower(), str(code).strip())


def build_system_prompt(source_lang: str | None = None,
                        target_lang: str | None = None) -> str:
    """Prompt do tradutor para o par de idiomas informado."""
    destino = lang_name(target_lang) or lang_name(DEFAULT_TARGET_LANG)
    origem = lang_name(source_lang)
    ctx = ""
    if origem and str(source_lang).strip().lower() != "auto":
        ctx = f"O texto de origem esta em {origem}. "
    return (
        "Voce e um tradutor literario profissional. "
        f"{ctx}Traduza o texto a seguir para {destino}, preservando paragrafos, "
        "tom literario, nomes proprios e formatacao. "
        "Retorne APENAS a traducao, sem comentarios."
    )


def chunk_text(text: str, size: int = CHUNK_SIZE) -> List[str]:
    """Divide `text` em blocos de ate `size` caracteres, SEM sobreposicao.

    O corte e' feito preferencialmente em fim de paragrafo, depois em fim de
    frase e, por ultimo, em espaco. Nenhum caractere e' perdido e nenhum
    trecho aparece em dois blocos.
    """
    if size <= 0:
        raise ValueError("size deve ser positivo")
    if len(text) <= size:
        return [text]
    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            window = text[start:end]
            corte = 0
            for pattern in _BOUNDARIES:
                matches = list(re.finditer(pattern, window))
                if matches:
                    corte = matches[-1].end()
                    break
            # so aceita o corte se ele nao desperdicar a maior parte do bloco
            if corte > len(window) * 0.5:
                end = start + corte
        if end <= start:  # seguranca: sempre avanca
            end = min(start + size, n)
        chunks.append(text[start:end])
        start = end
    return chunks


def _llm_available() -> bool:
    # Compat: True se OpenAI ou Gemini configurado; senao offline (mock).
    return llm_available()


def _translate_chunk_llm(chunk: str, model: str, source_lang: str | None,
                         target_lang: str | None) -> str:
    client = make_client()
    model = resolve_chat_model(model, kind="translation")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system",
             "content": build_system_prompt(source_lang, target_lang)},
            {"role": "user", "content": chunk},
        ],
        temperature=0.3,
    )
    return (resp.choices[0].message.content or "").strip()


def _mock_translate(text: str, target_lang: str | None = None) -> str:
    """Fallback offline: marca o idioma de destino e mantem a estrutura."""
    marker = f"[{target_lang or DEFAULT_TARGET_LANG} mock] "
    lines = text.split("\n")
    out = []
    for ln in lines:
        if ln.strip():
            out.append(ln if ln.startswith(marker) else marker + ln)
        else:
            out.append(ln)
    return "\n".join(out)


def _translate_block(text: str, model: str, source_lang: str | None,
                     target_lang: str | None) -> str:
    """Traduz um paragrafo, dividindo apenas se exceder CHUNK_SIZE."""
    if len(text) <= CHUNK_SIZE:
        return _translate_chunk_llm(text, model, source_lang, target_lang)
    partes = [_translate_chunk_llm(c, model, source_lang, target_lang)
              for c in chunk_text(text)]
    return " ".join(p.strip() for p in partes if p.strip())


def translate_text(text: str, model: str = "gpt-4o-mini",
                   source_lang: str | None = DEFAULT_SOURCE_LANG,
                   target_lang: str | None = DEFAULT_TARGET_LANG) -> str:
    """Traduz um texto preservando quebras de paragrafo.

    Em modo offline devolve o mock marcado; em falha do LLM tambem.
    """
    if not text or not text.strip():
        return text
    if not _llm_available():
        return _mock_translate(text, target_lang)
    try:
        blocos = text.split("\n\n")
        traduzidos = []
        for bloco in blocos:
            if not bloco.strip():
                traduzidos.append(bloco)
                continue
            traduzidos.append(_translate_block(bloco, model, source_lang,
                                               target_lang))
        return "\n\n".join(traduzidos)
    except Exception as exc:
        log.warning("traducao via LLM falhou (%s) - usando mock offline", exc)
        return _mock_translate(text, target_lang)


# Compat: nome antigo usado por testes/clientes externos.
def translate_paragraph(text: str, model: str = "gpt-4o-mini",
                        source_lang: str | None = DEFAULT_SOURCE_LANG,
                        target_lang: str | None = DEFAULT_TARGET_LANG) -> str:
    return translate_text(text, model, source_lang, target_lang)


def translate_chapters(chapters: list, model: str = "gpt-4o-mini",
                       source_lang: str | None = DEFAULT_SOURCE_LANG,
                       target_lang: str | None = DEFAULT_TARGET_LANG) -> list:
    out = []
    for ch in chapters or []:
        title = ch.get("title", "")
        paras = ch.get("paragraphs", []) or []
        t_title = (translate_text(title, model, source_lang, target_lang)
                   if title else title)
        t_paras = [translate_text(p, model, source_lang, target_lang)
                   for p in paras]
        out.append({"title": t_title, "level": ch.get("level", 1),
                    "paragraphs": t_paras})
    return out
