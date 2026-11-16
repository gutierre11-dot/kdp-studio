"""Configuracao central: .env, limites, timeouts e cadeia de modelos.

O `.env` de `kdp-studio/` (e, por compatibilidade, o de `kdp-studio/backend/`)
e carregado no import deste modulo, sem sobrescrever variaveis ja definidas no
ambiente real.
"""
from __future__ import annotations

import functools
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]  # kdp-studio/

DEFAULT_CORS = "http://localhost:8000,http://127.0.0.1:8000"
DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"
DEFAULT_DEEPSEEK_FALLBACKS = "deepseek-v4-pro"
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
DEFAULT_GEMINI_FALLBACKS = "gemini-3.8-flash,gemini-3.7-flash,gemini-3.1-flash-lite"


def load_env() -> list[str]:
    """Carrega .env da raiz e de backend/ sem sobrescrever o ambiente real.

    Nunca levanta excecao: sem python-dotenv, segue com o ambiente atual.
    """
    carregados: list[str] = []
    try:
        from dotenv import load_dotenv
    except ImportError:
        log.warning("python-dotenv nao instalado: .env ignorado")
        return carregados
    for candidato in (BASE_DIR / ".env", BASE_DIR / "backend" / ".env"):
        if candidato.is_file():
            load_dotenv(candidato, override=False)
            carregados.append(str(candidato))
    return carregados


def _raw(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_raw(name) or default)
    except ValueError:
        log.warning("valor invalido em %s=%r; usando %s", name, _raw(name), default)
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_raw(name) or default)
    except ValueError:
        log.warning("valor invalido em %s=%r; usando %s", name, _raw(name), default)
        return default


def _list(name: str, default: str) -> list[str]:
    return [p.strip() for p in (_raw(name) or default).split(",") if p.strip()]


def _flag(name: str, default: bool = False) -> bool:
    valor = _raw(name)
    if not valor:
        return default
    return valor.lower() in ("1", "true", "on", "yes", "sim")


@dataclass(frozen=True)
class Settings:
    """Configuracao efetiva da aplicacao."""

    output_dir: Path
    max_upload_bytes: int
    max_cover_bytes: int
    job_ttl_seconds: int
    job_max: int
    job_workers: int
    cors_origins: list[str]
    translation_chunk_chars: int
    translation_workers: int
    llm_timeout_seconds: float
    llm_max_retries: int
    llm_max_total_seconds: float
    deepseek_model: str
    deepseek_fallbacks: list[str]
    deepseek_thinking: bool
    gemini_model: str
    gemini_fallbacks: list[str]
    host: str
    port: int
    reload: bool


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Configuracao em cache; use get_settings.cache_clear() nos testes."""
    return Settings(
        output_dir=BASE_DIR / "output",
        max_upload_bytes=_int("MAX_UPLOAD_MB", 100) * 1024 * 1024,
        max_cover_bytes=_int("MAX_COVER_MB", 10) * 1024 * 1024,
        job_ttl_seconds=_int("JOB_TTL_SECONDS", 2 * 60 * 60),
        job_max=_int("JOB_MAX", 50),
        job_workers=_int("JOB_WORKERS", 2),
        cors_origins=_list("CORS_ORIGINS", DEFAULT_CORS),
        translation_chunk_chars=_int("TRANSLATION_CHUNK_CHARS", 6000),
        translation_workers=_int("TRANSLATION_WORKERS", 4),
        llm_timeout_seconds=_float("LLM_TIMEOUT_SECONDS", 60.0),
        llm_max_retries=_int("LLM_MAX_RETRIES", 3),
        llm_max_total_seconds=_float("LLM_MAX_TOTAL_SECONDS", 180.0),
        deepseek_model=_raw("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL,
        deepseek_fallbacks=_list("DEEPSEEK_MODEL_FALLBACKS",
                                 DEFAULT_DEEPSEEK_FALLBACKS),
        deepseek_thinking=_flag("DEEPSEEK_THINKING", False),
        gemini_model=_raw("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
        gemini_fallbacks=_list("GEMINI_MODEL_FALLBACKS", DEFAULT_GEMINI_FALLBACKS),
        host=_raw("HOST") or "127.0.0.1",
        port=_int("PORT", 8000),
        reload=_raw("RELOAD").lower() in ("1", "true", "on"),
    )


load_env()
