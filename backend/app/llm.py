"""Acesso ao LLM via endpoint OpenAI-compatible (OpenAI ou Gemini).

Camada fina e resiliente: um unico ponto (`chat`) concentra timeout por
chamada, tentativas em rodadas e **cadeia de fallback de modelos**, porque os
modelos Gemini mudam e respondem 404/503 com frequencia. Sem isso, uma
traducao de livro ficava pendurada indefinidamente.

Variaveis de ambiente: OPENAI_API_KEY, OPENAI_BASE_URL, GEMINI_API_KEY,
GEMINI_MODEL, GEMINI_MODEL_FALLBACKS, TRANSLATION_MODEL, LLM_TIMEOUT_SECONDS,
LLM_MAX_RETRIES.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from . import config

log = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENAI_DEFAULT_TRANSLATION_MODEL = "gpt-4o-mini"
OPENAI_DEFAULT_CREATION_MODEL = "gpt-4o"

_lock = threading.Lock()
_modelo_resolvido: str | None = None


class LLMError(RuntimeError):
    """Falha recuperavel ou definitiva de uma chamada de LLM."""


def openai_configured() -> bool:
    return bool((os.getenv("OPENAI_API_KEY") or "").strip())


def gemini_configured() -> bool:
    return bool((os.getenv("GEMINI_API_KEY") or "").strip())


def provider_name() -> str:
    """`openai`, `gemini` ou `offline` (sem nenhuma chave)."""
    if openai_configured():
        return "openai"
    if gemini_configured():
        return "gemini"
    return "offline"


def is_configured() -> bool:
    return provider_name() != "offline"


def reset_model_cache() -> None:
    """Esquece o modelo resolvido (usado pelos testes)."""
    global _modelo_resolvido
    with _lock:
        _modelo_resolvido = None


def resolved_model() -> str | None:
    with _lock:
        return _modelo_resolvido


def model_candidates() -> list[str]:
    """Modelos a tentar, em ordem, sem repeticoes.

    `TRANSLATION_MODEL` explicito tem prioridade absoluta; caso contrario, o
    modelo primario seguido da cadeia de fallback (so faz sentido no Gemini).
    """
    explicito = (os.getenv("TRANSLATION_MODEL") or "").strip()
    if explicito:
        return [explicito]
    if provider_name() == "openai":
        return [OPENAI_DEFAULT_TRANSLATION_MODEL]
    cfg = config.get_settings()
    vistos: set[str] = set()
    saida: list[str] = []
    for modelo in [cfg.primary_model] + list(cfg.fallback_models):
        if modelo and modelo not in vistos:
            vistos.add(modelo)
            saida.append(modelo)
    return saida


def make_client(*, timeout: float | None = None, max_retries: int = 0) -> Any:
    """Cliente OpenAI SDK apontado para o provider ativo."""
    from openai import OpenAI

    if timeout is None:
        timeout = config.get_settings().llm_timeout_seconds
    if openai_configured():
        return OpenAI(api_key=os.getenv("OPENAI_API_KEY"),
                      base_url=os.getenv("OPENAI_BASE_URL") or None,
                      timeout=timeout, max_retries=max_retries)
    if gemini_configured():
        return OpenAI(api_key=os.getenv("GEMINI_API_KEY"),
                      base_url=GEMINI_BASE_URL,
                      timeout=timeout, max_retries=max_retries)
    raise LLMError("Nenhuma chave de IA configurada "
                   "(OPENAI_API_KEY/GEMINI_API_KEY).")


def _call_once(model: str, system: str, user: str, temperature: float) -> str:
    """Uma unica chamada; converte qualquer falha do SDK em LLMError."""
    try:
        cliente = make_client(
            timeout=config.get_settings().llm_timeout_seconds)
        resposta = cliente.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=temperature,
        )
        conteudo = (resposta.choices[0].message.content or "").strip()
    except LLMError:
        raise
    except Exception as exc:  # rede, timeout, 404, 429, 503...
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc
    if not conteudo:
        raise LLMError(f"resposta vazia do modelo {model}")
    return conteudo


def chat(system: str, user: str, *, model: str | None = None,
         temperature: float = 0.3, sleep=time.sleep) -> str:
    """Executa uma chamada de chat com fallback e tentativas.

    Cada rodada percorre toda a cadeia de modelos; se nenhum responder, espera
    com backoff exponencial e repete, ate `LLM_MAX_RETRIES` rodadas.
    """
    if not is_configured():
        raise LLMError("Nenhuma chave de IA configurada "
                       "(OPENAI_API_KEY/GEMINI_API_KEY).")
    cfg = config.get_settings()
    candidatos = [model] if model else model_candidates()
    if model is None:
        # Depois do primeiro sucesso, o modelo que respondeu vai na frente: sem
        # isso cada chunk pagaria de novo a espera dos modelos indisponiveis.
        resolvido = resolved_model()
        if resolvido and resolvido in candidatos:
            candidatos = [resolvido] + [m for m in candidatos if m != resolvido]
    erros: list[str] = []
    for rodada in range(max(1, cfg.llm_max_retries)):
        if rodada:
            sleep(2 ** (rodada - 1))
        for nome in candidatos:
            try:
                texto = _call_once(nome, system, user, temperature)
            except LLMError as exc:
                erros.append(f"{nome}: {exc}")
                continue
            global _modelo_resolvido
            with _lock:
                _modelo_resolvido = nome
            return texto
    resumo = "; ".join(erros[:3]) if erros else "sem resposta"
    raise LLMError(f"Nenhum modelo respondeu ({resumo}). Verifique "
                   f"GEMINI_MODEL/GEMINI_MODEL_FALLBACKS e sua conexão.")


# ---------------------------------------------------------------------------
# Compatibilidade com os modulos legados (removida na limpeza final)
# ---------------------------------------------------------------------------

def load_env() -> list[str]:  # pragma: no cover - delegacao
    return config.load_env()


def active_provider() -> str:  # pragma: no cover - delegacao
    return provider_name()


def llm_available() -> bool:  # pragma: no cover - delegacao
    return is_configured()


def gemini_model() -> str:  # pragma: no cover - delegacao
    return config.get_settings().primary_model


def effective_translation_model() -> str:  # pragma: no cover - delegacao
    return config.get_settings().primary_model


def effective_creation_model() -> str:  # pragma: no cover - delegacao
    if provider_name() == "gemini":
        return config.get_settings().primary_model
    return OPENAI_DEFAULT_CREATION_MODEL


def resolve_chat_model(requested: str | None, kind: str = "translation") -> str:
    if active_provider() == "gemini" and (not requested or requested in (
            "gpt-4o-mini", "gpt-4o", "gpt-4o-mini-translate")):
        return config.get_settings().primary_model
    return requested or (OPENAI_DEFAULT_TRANSLATION_MODEL
                         if kind == "translation"
                         else OPENAI_DEFAULT_CREATION_MODEL)
