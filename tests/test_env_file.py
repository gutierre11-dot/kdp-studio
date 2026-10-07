"""Testes do atualizador de `.env` usado pelo configurar-ia.sh."""
import os
import stat

from backend.app.env_file import set_var


def test_cria_arquivo_com_permissao_600(tmp_path):
    alvo = tmp_path / ".env"
    assert set_var(alvo, "DEEPSEEK_API_KEY", "sk-teste") is True
    assert alvo.read_text(encoding="utf-8") == "DEEPSEEK_API_KEY=sk-teste\n"
    assert stat.S_IMODE(alvo.stat().st_mode) == 0o600


def test_substitui_a_chave_preservando_o_resto(tmp_path):
    alvo = tmp_path / ".env"
    alvo.write_text("# comentario\nDEEPSEEK_API_KEY=antiga\nMAX_UPLOAD_MB=50\n")
    set_var(alvo, "DEEPSEEK_API_KEY", "nova")
    conteudo = alvo.read_text(encoding="utf-8")
    assert "# comentario" in conteudo
    assert "MAX_UPLOAD_MB=50" in conteudo
    assert "DEEPSEEK_API_KEY=nova" in conteudo
    assert "antiga" not in conteudo


def test_acrescenta_quando_ausente(tmp_path):
    alvo = tmp_path / ".env"
    alvo.write_text("MAX_UPLOAD_MB=50\n")
    set_var(alvo, "LLM_PROVIDER", "deepseek")
    assert alvo.read_text(encoding="utf-8") == "MAX_UPLOAD_MB=50\nLLM_PROVIDER=deepseek\n"


def test_valor_vazio_nao_apaga_configuracao(tmp_path):
    alvo = tmp_path / ".env"
    alvo.write_text("GEMINI_API_KEY=existente\n")
    assert set_var(alvo, "GEMINI_BASE_URL", "") is False
    assert alvo.read_text(encoding="utf-8") == "GEMINI_API_KEY=existente\n"


def test_chave_duplicada_e_reduzida_a_uma(tmp_path):
    alvo = tmp_path / ".env"
    alvo.write_text("A=1\nA=2\nB=3\n")
    set_var(alvo, "A", "9")
    assert alvo.read_text(encoding="utf-8") == "A=9\nB=3\n"


def test_valor_com_espacos_e_iguais_e_preservado(tmp_path):
    alvo = tmp_path / ".env"
    set_var(alvo, "OPENAI_BASE_URL", "https://x.local/v1?a=b")
    assert "OPENAI_BASE_URL=https://x.local/v1?a=b" in alvo.read_text(encoding="utf-8")
    assert stat.S_IMODE(os.stat(alvo).st_mode) == 0o600
