"""Acesso ao LLM via endpoint OpenAI-compatible (DeepSeek, OpenAI ou Gemini).

Camada fina e resiliente: um unico ponto (`chat`) concentra timeout por
chamada, tentativas em rodadas e **cadeia de fallback de modelos**, porque os
modelos dos provedores mudam e respondem 404/429/503 com frequencia. Sem isso,
uma traducao de livro ficava pendurada indefinidamente.

Prioridade do provider ativo: `LLM_PROVIDER` (se definido) -> DeepSeek ->
OpenAI -> Gemini -> offline.

Variaveis de ambiente: LLM_PROVIDER, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL,
DEEPSEEK_MODEL, DEEPSEEK_MODEL_FALLBACKS, DEEPSEEK_THINKING, OPENAI_API_KEY,
OPENAI_BASE_URL, GEMINI_API_KEY, GEMINI_MODEL, GEMINI_MODEL_FALLBACKS,
TRANSLATION_MODEL, LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES, LLM_MAX_TOTAL_SECONDS.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any

from . import config

log = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENAI_DEFAULT_TRANSLATION_MODEL = "gpt-4o-mini"

_PROVIDERS = ("deepseek", "openai", "gemini", "offline")

_lock = threading.Lock()
_modelo_resolvido: str | None = None


class LLMError(RuntimeError):
    """Falha recuperavel ou definitiva de uma chamada de LLM."""


def deepseek_configured() -> bool:
    return bool((os.getenv("DEEPSEEK_API_KEY") or "").strip())


def openai_configured() -> bool:
    return bool((os.getenv("OPENAI_API_KEY") or "").strip())


def gemini_configured() -> bool:
    return bool((os.getenv("GEMINI_API_KEY") or "").strip())


def provider_name() -> str:
    """`deepseek`, `openai`, `gemini` ou `offline`.

    `LLM_PROVIDER` manda quando define um dos valores conhecidos; assim o
    usuario pode forcar um provider mesmo tendo chaves de varios.
    """
    forcado = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if forcado in _PROVIDERS:
        return forcado
    if deepseek_configured():
        return "deepseek"
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
    modelo principal do provider ativo seguido da cadeia de fallback dele.
    """
    explicito = (os.getenv("TRANSLATION_MODEL") or "").strip()
    if explicito:
        return [explicito]
    cfg = config.get_settings()
    provider = provider_name()
    if provider == "deepseek":
        modelos = [cfg.deepseek_model, *cfg.deepseek_fallbacks]
    elif provider == "gemini":
        modelos = [cfg.gemini_model, *cfg.gemini_fallbacks]
    elif provider == "openai":
        modelos = [OPENAI_DEFAULT_TRANSLATION_MODEL]
    else:
        return []
    vistos: set[str] = set()
    saida: list[str] = []
    for modelo in modelos:
        if modelo and modelo not in vistos:
            vistos.add(modelo)
            saida.append(modelo)
    return saida


def client_settings() -> tuple[str, str | None]:
    """`(api_key, base_url)` do provider ativo; levanta LLMError se offline."""
    provider = provider_name()
    if provider == "deepseek":
        return (os.getenv("DEEPSEEK_API_KEY", "").strip(),
                (os.getenv("DEEPSEEK_BASE_URL") or "").strip()
                or DEEPSEEK_BASE_URL)
    if provider == "openai":
        return (os.getenv("OPENAI_API_KEY", "").strip(),
                (os.getenv("OPENAI_BASE_URL") or "").strip() or None)
    if provider == "gemini":
        return (os.getenv("GEMINI_API_KEY", "").strip(), GEMINI_BASE_URL)
    raise LLMError("Nenhuma chave de IA configurada (DEEPSEEK_API_KEY, "
                   "OPENAI_API_KEY ou GEMINI_API_KEY).")


def make_client(*, timeout: float | None = None, max_retries: int = 0) -> Any:
    """Cliente OpenAI SDK apontado para o provider ativo."""
    from openai import OpenAI

    if timeout is None:
        timeout = config.get_settings().llm_timeout_seconds
    api_key, base_url = client_settings()
    return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout,
                  max_retries=max_retries)


def _extras_do_provider() -> dict:
    """Parametros extra por provider (hoje: modo de raciocinio do DeepSeek).

    Ligar o raciocinio numa traducao de livro multiplica tempo e custo sem
    ganho proporcional, entao o padrao e desligado.
    """
    if provider_name() == "deepseek" and not config.get_settings().deepseek_thinking:
        return {"thinking": {"type": "disabled"}}
    return {}


# Bits de status HTTP -> explicacao curta para o usuario.
_DICAS_HTTP = {
    "401": "chave inválida",
    "403": "acesso negado à API",
    "404": "modelo inexistente ou descontinuado",
    "429": "cota da API esgotada",
    "500": "erro interno do provedor",
    "503": "modelo indisponível no momento",
}
_CODIGO_RE = re.compile(r"Error code:\s*(\d{3})")


def resumir_erro(exc: Exception) -> str:
    """Mensagem curta e acionavel para um erro do provedor.

    As excecoes do SDK carregam o corpo JSON inteiro da API (centenas de
    caracteres, com links e detalhes de cota). Isso nao cabe num aviso de
    interface, entao so o codigo e a dica sobrevivem.
    """
    achado = _CODIGO_RE.search(str(exc))
    if achado:
        codigo = achado.group(1)
        dica = _DICAS_HTTP.get(codigo, "")
        return f"HTTP {codigo}" + (f" ({dica})" if dica else "")
    return type(exc).__name__


def _call_once(model: str, system: str, user: str, temperature: float) -> str:
    """Uma unica chamada; converte qualquer falha do SDK em LLMError."""
    try:
        cliente = make_client(
            timeout=config.get_settings().llm_timeout_seconds)
        extras = _extras_do_provider()
        resposta = cliente.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=temperature,
            **({"extra_body": extras} if extras else {}),
        )
        conteudo = (resposta.choices[0].message.content or "").strip()
    except LLMError:
        raise
    except Exception as exc:  # rede, timeout, 404, 429, 503...
        raise LLMError(resumir_erro(exc)) from exc
    if not conteudo:
        raise LLMError(f"resposta vazia do modelo {model}")
    return conteudo


def chat(system: str, user: str, *, model: str | None = None,
         temperature: float = 0.3, sleep=time.sleep,
         now=time.monotonic) -> str:
    """Executa uma chamada de chat com fallback e tentativas.

    Cada rodada percorre toda a cadeia de modelos; se nenhum responder, espera
    com backoff exponencial e repete, ate `LLM_MAX_RETRIES` rodadas. O tempo
    total e limitado por `LLM_MAX_TOTAL_SECONDS`: sem esse teto, uma cadeia de
    modelos indisponiveis poderia segurar um chunk por dezenas de minutos.
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
    inicio = now()
    limite = cfg.llm_max_total_seconds
    esgotado = False
    for rodada in range(max(1, cfg.llm_max_retries)):
        if rodada:
            sleep(2 ** (rodada - 1))
        for nome in candidatos:
            if now() - inicio >= limite:
                erros.append(f"limite de {limite:.0f}s esgotado")
                esgotado = True
                break
            try:
                texto = _call_once(nome, system, user, temperature)
            except LLMError as exc:
                erros.append(f"{nome}: {exc}")
                continue
            global _modelo_resolvido
            with _lock:
                _modelo_resolvido = nome
            return texto
        if esgotado:
            break
    resumo = "; ".join(erros[:3]) if erros else "sem resposta"
    raise LLMError(f"Nenhum modelo respondeu ({resumo}). Verifique "
                   f"GEMINI_MODEL/GEMINI_MODEL_FALLBACKS e sua conexão.")
