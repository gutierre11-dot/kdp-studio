"""Testes da camada de LLM: timeout, retry, fallback de modelo e offline."""
import pytest

from backend.app import config, llm


def test_provider_offline_sem_chaves(monkeypatch):
    for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY",
              "LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    llm.reset_model_cache()
    assert llm.provider_name() == "offline"
    assert not llm.is_configured()


def test_deepseek_tem_prioridade_sobre_os_outros(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "chave-deepseek")
    monkeypatch.setenv("GEMINI_API_KEY", "chave-gemini")
    monkeypatch.setenv("OPENAI_API_KEY", "chave-openai")
    assert llm.provider_name() == "deepseek"


def test_llm_provider_forca_a_escolha(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "chave-deepseek")
    monkeypatch.setenv("OPENAI_API_KEY", "chave-openai")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert llm.provider_name() == "openai"
    monkeypatch.setenv("LLM_PROVIDER", "offline")
    assert llm.provider_name() == "offline"


def test_base_url_e_chave_do_deepseek(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "chave-deepseek")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    chave, base = llm.client_settings()
    assert chave == "chave-deepseek"
    assert base == "https://api.deepseek.com"
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://proxy.local/v1")
    assert llm.client_settings()[1] == "https://proxy.local/v1"


def test_modelos_do_deepseek(monkeypatch):
    monkeypatch.delenv("TRANSLATION_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "chave-deepseek")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")
    config.get_settings.cache_clear()
    llm.reset_model_cache()
    assert llm.model_candidates() == ["deepseek-flash", "deepseek-v4-pro"]


def test_candidatos_incluem_primario_e_fallbacks(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "chave-gemini")
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
    for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY",
              "LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    llm.reset_model_cache()
    with pytest.raises(llm.LLMError, match="chave"):
        llm.chat("s", "u")


def test_modelo_resolvido_e_tentado_primeiro_depois(monkeypatch):
    """Depois do primeiro sucesso, nao se paga de novo o custo dos 503."""
    chamados = []

    def fake_call(model, system, user, temperature):
        chamados.append(model)
        if model == "lento":
            raise llm.LLMError("503")
        return "ok"

    monkeypatch.setattr(llm, "_call_once", fake_call)
    monkeypatch.setattr(llm, "model_candidates", lambda: ["lento", "rapido"])
    llm.reset_model_cache()
    assert llm.chat("s", "u", sleep=lambda s: None) == "ok"
    assert chamados == ["lento", "rapido"]
    chamados.clear()
    assert llm.chat("s", "u", sleep=lambda s: None) == "ok"
    assert chamados == ["rapido"]


def test_chat_respeita_limite_total_de_tempo(monkeypatch):
    """Sem teto de tempo, uma cadeia indisponível seguraria o job por minutos."""
    estado = {"t": 0.0}
    chamadas = []

    def fake_call(*a, **k):
        chamadas.append(1)
        estado["t"] += 1000.0
        raise llm.LLMError("503")

    monkeypatch.setattr(llm, "_call_once", fake_call)
    monkeypatch.setattr(llm, "model_candidates",
                        lambda: ["m1", "m2", "m3"])
    with pytest.raises(llm.LLMError):
        llm.chat("s", "u", sleep=lambda s: None, now=lambda: estado["t"])
    assert len(chamadas) < 9  # nao percorre 3 rodadas x 3 modelos


def test_erro_do_provedor_e_resumido(monkeypatch):
    """O corpo JSON da API nao pode virar aviso gigante na interface."""
    def fake_make_client(*, timeout, max_retries=0):
        raise RuntimeError('Error code: 429 - [{"error": "quota exceeded", '
                           '"detalhe": "' + "x" * 500 + '"}]')

    monkeypatch.setattr(llm, "make_client", fake_make_client)
    with pytest.raises(llm.LLMError) as capturado:
        llm._call_once("m", "s", "u", 0.3)
    mensagem = str(capturado.value)
    assert "429" in mensagem
    assert "cota" in mensagem
    assert len(mensagem) < 80
    assert "x" * 100 not in mensagem


def test_call_once_usa_timeout_configurado(monkeypatch):
    capturado = {}

    def fake_make_client(*, timeout, max_retries=0):
        capturado["timeout"] = timeout
        raise llm.LLMError("parou aqui")

    monkeypatch.setattr(llm, "make_client", fake_make_client)
    with pytest.raises(llm.LLMError):
        llm._call_once("m", "s", "u", 0.3)
    assert capturado["timeout"] == config.get_settings().llm_timeout_seconds
