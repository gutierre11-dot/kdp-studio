"""Helper compartilhado de LLM: OpenAI -> Gemini (fallback) -> offline.

Prioridade do provider ativo:
  1. openai  — se OPENAI_API_KEY presente (vale também para bases
     OpenAI-compatible: OpenRouter, DeepSeek, etc. via OPENAI_BASE_URL).
  2. gemini  — se OPENAI_API_KEY ausente mas GEMINI_API_KEY presente.
     Usa o endpoint OpenAI-compatible do Google:
       https://generativelanguage.googleapis.com/v1beta/openai/
     com o SDK `openai` (>=1.0), sem dependencia extra.
  3. offline — sem nenhuma chave: callers devem usar fallback/mock local.

Variaveis de ambiente:
  OPENAI_API_KEY, OPENAI_BASE_URL,
  GEMINI_API_KEY, GEMINI_MODEL (default gemini-flash-latest),
  TRANSLATION_MODEL, CREATION_MODEL (override explicito, tem prioridade).

O arquivo .env (kdp-studio/.env ou kdp-studio/backend/.env) e carregado
automaticamente no import deste modulo. Antes, somente o run.sh carregava
o .env, entao `uvicorn backend.app.main:app` (comando do README) subia em
modo offline sem avisar o usuario.
"""
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]  # kdp-studio/


def load_env() -> list[str]:
    """Carrega .env da raiz e de backend/ sem sobrescrever o ambiente real.

    Variaveis ja definidas no shell/container tem prioridade (override=False).
    Retorna a lista de arquivos carregados; nunca levanta excecao.
    """
    carregados: list[str] = []
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv ausente: segue com o ambiente atual
        log.warning("python-dotenv nao instalado: .env ignorado")
        return carregados
    for candidato in (BASE_DIR / ".env", BASE_DIR / "backend" / ".env"):
        if candidato.is_file():
            load_dotenv(candidato, override=False)
            carregados.append(str(candidato))
    return carregados


load_env()

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_DEFAULT_MODEL = "gemini-flash-latest"

OPENAI_DEFAULT_TRANSLATION_MODEL = "gpt-4o-mini"
OPENAI_DEFAULT_CREATION_MODEL = "gpt-4o"


def openai_configured() -> bool:
    return bool((os.getenv("OPENAI_API_KEY") or "").strip())


def gemini_configured() -> bool:
    return bool((os.getenv("GEMINI_API_KEY") or "").strip())


def active_provider() -> str:
    """Retorna 'openai' | 'gemini' | 'offline'."""
    if openai_configured():
        return "openai"
    if gemini_configured():
        return "gemini"
    return "offline"


def llm_available() -> bool:
    return active_provider() in ("openai", "gemini")


def gemini_model() -> str:
    return (os.getenv("GEMINI_MODEL") or "").strip() or GEMINI_DEFAULT_MODEL


def effective_translation_model() -> str:
    """Modelo efetivo de traducao respeitando provider ativo."""
    m = (os.getenv("TRANSLATION_MODEL") or "").strip()
    if m:
        return m
    if active_provider() == "gemini":
        return gemini_model()
    return OPENAI_DEFAULT_TRANSLATION_MODEL


def effective_creation_model() -> str:
    """Modelo efetivo de criacao respeitando provider ativo."""
    m = (os.getenv("CREATION_MODEL") or "").strip()
    if m:
        return m
    if active_provider() == "gemini":
        return gemini_model()
    return OPENAI_DEFAULT_CREATION_MODEL


def resolve_chat_model(requested: str | None, kind: str = "translation") -> str:
    """Troca defaults OpenAI pelo modelo Gemini quando provider ativo e gemini.

    Evita enviar 'gpt-4o-mini'/'gpt-4o' ao endpoint do Google, que os
    rejeitaria (404 model not found). Override explicito via env ou
    parametro nao-default e preservado.
    """
    default_openai = (OPENAI_DEFAULT_TRANSLATION_MODEL
                      if kind == "translation"
                      else OPENAI_DEFAULT_CREATION_MODEL)
    if active_provider() == "gemini" and (not requested or requested in (
            "gpt-4o-mini", "gpt-4o", "gpt-4o-mini-translate")):
        return gemini_model()
    return requested or default_openai


def make_client():
    """Cria client OpenAI SDK configurado para o provider ativo."""
    from openai import OpenAI

    if openai_configured():
        return OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL") or None,
        )
    if gemini_configured():
        return OpenAI(
            api_key=os.getenv("GEMINI_API_KEY"),
            base_url=GEMINI_BASE_URL,
        )
    raise RuntimeError("nenhum provider LLM configurado (offline)")
