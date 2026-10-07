"""Testes da camada de LLM: timeout, retry, fallback de modelo e offline."""
import pytest

from backend.app import config, llm


def test_provider_offline_sem_chaves(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    llm.reset_model_cache()
    assert llm.provider_name() == "offline"
    assert not llm.is_configured()


def test_candidatos_incluem_primario_e_fallbacks(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-latest")
    monkeypatch.delenv("TRANSLATION_MODEL", raising=False)
    config.get_settings.cache_clear()
    llm.reset_model_cache()
    candidatos = llm.model_candidates()
    assert candidatos[0] == "gemini-flash-latest"
    assert "gemini-3.1-flash-lite" in candidatos


def test_translation_model_explicito_tem_prioridade(monkeypatch):
    monkeypatch.setenv("TRANSLATION_MODEL", "meu-modelo")
    config.get_settings.cache_clear()
    assert llm.model_candidates() == ["meu-modelo"]


def test_chat_faz_fallback_quando_modelo_falha(monkeypatch):
    chamados = []

    def fake_call(model, system, user, temperature):
        chamados.append(model)
        if model == "gemini-flash-latest":
            raise llm.LLMError("503 UNAVAILABLE")
        return "traduzido"

    monkeypatch.setattr(llm, "_call_once", fake_call)
    monkeypatch.setattr(llm, "model_candidates",
                        lambda: ["gemini-flash-latest", "gemini-3.1-flash-lite"])
    assert llm.chat("s", "u", sleep=lambda s: None) == "traduzido"
    assert chamados == ["gemini-flash-latest", "gemini-3.1-flash-lite"]


def test_chat_esgota_tentativas_e_levanta_llmerror(monkeypatch):
    def sempre_falha(*a, **k):
        raise llm.LLMError("503")

    monkeypatch.setattr(llm, "_call_once", sempre_falha)
    monkeypatch.setattr(llm, "model_candidates", lambda: ["m1", "m2"])
    with pytest.raises(llm.LLMError, match="Nenhum modelo"):
        llm.chat("s", "u", sleep=lambda s: None)


def test_chat_offline_levanta_erro_explicito(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    llm.reset_model_cache()
    with pytest.raises(llm.LLMError, match="chave"):
        llm.chat("s", "u")


def test_call_once_usa_timeout_configurado(monkeypatch):
    capturado = {}

    def fake_make_client(*, timeout, max_retries=0):
        capturado["timeout"] = timeout
        raise llm.LLMError("parou aqui")

    monkeypatch.setattr(llm, "make_client", fake_make_client)
    with pytest.raises(llm.LLMError):
        llm._call_once("m", "s", "u", 0.3)
    assert capturado["timeout"] == config.get_settings().llm_timeout_seconds
