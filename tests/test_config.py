"""Testes das configurações do KDP Studio."""
from backend.app import config


def test_settings_defaults(monkeypatch):
    for k in ("MAX_UPLOAD_MB", "JOB_TTL_SECONDS", "JOB_MAX", "JOB_WORKERS",
              "TRANSLATION_CHUNK_CHARS", "TRANSLATION_WORKERS",
              "LLM_TIMEOUT_SECONDS", "LLM_MAX_RETRIES", "GEMINI_MODEL",
              "GEMINI_MODEL_FALLBACKS", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert s.max_upload_bytes == 100 * 1024 * 1024
    assert (s.job_ttl_seconds, s.job_max, s.job_workers) == (7200, 50, 2)
    assert (s.translation_chunk_chars, s.translation_workers) == (6000, 4)
    assert (s.llm_timeout_seconds, s.llm_max_retries) == (120.0, 3)
    assert s.primary_model == "gemini-flash-latest"
    assert s.fallback_models == ["gemini-3.8-flash", "gemini-3.7-flash",
                                 "gemini-3.1-flash-lite"]


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("TRANSLATION_WORKERS", "7")
    monkeypatch.setenv("GEMINI_MODEL_FALLBACKS", "a, b ,c")
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert s.translation_workers == 7
    assert s.fallback_models == ["a", "b", "c"]
