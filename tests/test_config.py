"""Testes das configurações do KDP Studio."""
from backend.app import config


def test_settings_defaults(monkeypatch):
    for k in ("MAX_UPLOAD_MB", "JOB_TTL_SECONDS", "JOB_MAX", "JOB_WORKERS",
              "TRANSLATION_CHUNK_CHARS", "TRANSLATION_WORKERS",
              "LLM_TIMEOUT_SECONDS", "LLM_MAX_RETRIES", "LLM_MAX_TOTAL_SECONDS",
              "GEMINI_MODEL", "GEMINI_MODEL_FALLBACKS", "GEMINI_API_KEY",
              "DEEPSEEK_MODEL", "DEEPSEEK_MODEL_FALLBACKS", "DEEPSEEK_THINKING",
              "DEEPSEEK_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert s.max_upload_bytes == 100 * 1024 * 1024
    assert (s.job_ttl_seconds, s.job_max, s.job_workers) == (7200, 50, 2)
    assert (s.translation_chunk_chars, s.translation_workers) == (6000, 4)
    assert (s.llm_timeout_seconds, s.llm_max_retries) == (60.0, 3)
    assert s.llm_max_total_seconds == 180.0
    assert s.deepseek_model == "deepseek-flash"
    assert s.deepseek_fallbacks == ["deepseek-v4-pro"]
    assert s.deepseek_thinking is False
    assert s.gemini_model == "gemini-flash-latest"
    assert s.gemini_fallbacks == ["gemini-3.8-flash", "gemini-3.7-flash",
                                  "gemini-3.1-flash-lite"]


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("TRANSLATION_WORKERS", "7")
    monkeypatch.setenv("DEEPSEEK_MODEL_FALLBACKS", "a, b ,c")
    monkeypatch.setenv("DEEPSEEK_THINKING", "1")
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert s.translation_workers == 7
    assert s.deepseek_fallbacks == ["a", "b", "c"]
    assert s.deepseek_thinking is True
