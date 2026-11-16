"""Testes do modelo de dados compartilhado."""
from backend.app.models import (
    Chapter,
    JobState,
    Paragraph,
    Run,
    paragrafo_de_texto,
    texto_editavel,
)


def test_paragraph_text_concatena_runs():
    assert Paragraph([Run("Olá"), Run(" "), Run("mundo")]).text == "Olá mundo"


def test_paragraph_from_text_cria_run_plano():
    p = Paragraph.from_text("abc")
    assert p.text == "abc"
    assert p.runs == [Run("abc")]


def test_chapter_words_soma_palavras():
    ch = Chapter("T", 1, [Paragraph.from_text("um dois três"),
                          Paragraph.from_text("quatro")])
    assert ch.words == 4


def test_jobstate_nao_compartilha_evento_de_cancelamento():
    a = JobState.new("a", title="t", author="x", language="pt-BR",
                     source_name="f.pdf", translated=False)
    b = JobState.new("b", title="t", author="x", language="pt-BR",
                     source_name="f.pdf", translated=False)
    a.cancel.set()
    assert not b.cancel.is_set()
    assert a.status == "queued"
    assert a.progress == 0
    assert a.warnings == []


# ---------------------------------------------------------------------------
# Texto editavel: ida e volta do chamador de nota
# ---------------------------------------------------------------------------

def test_texto_editavel_marca_o_chamador_com_token():
    p = Paragraph([Run("Corpo com chamador"), Run("1", superscript=True),
                   Run(" aqui.")])
    assert texto_editavel(p) == "Corpo com chamador⟦1⟧ aqui."


def test_texto_editavel_ignora_superscript_nao_numerico():
    p = Paragraph([Run("x"), Run("a)", superscript=True)])
    assert texto_editavel(p) == "xa)"


def test_paragrafo_de_texto_devolve_o_chamador_a_superscript():
    p = paragrafo_de_texto("Corpo com chamador⟦1⟧ aqui.")
    assert [(r.text, r.superscript) for r in p.runs] == [
        ("Corpo com chamador", False), ("1", True), (" aqui.", False)]


def test_ida_e_volta_preserva_o_chamador():
    original = Paragraph([Run("Antes "), Run("7", superscript=True),
                          Run(" depois"), Run("8", superscript=True)])
    voltou = paragrafo_de_texto(texto_editavel(original))
    assert texto_editavel(voltou) == texto_editavel(original)
    assert [r.text for r in voltou.runs if r.superscript] == ["7", "8"]
    assert voltou.text == "Antes 7 depois8"


def test_paragrafo_de_texto_sem_token_fica_plano():
    p = paragrafo_de_texto("Texto comum.")
    assert p.runs == [Run("Texto comum.")]


def test_paragrafo_de_texto_vazio_nao_gera_paragrafo_sem_run():
    assert paragrafo_de_texto("").runs == [Run("")]


def test_texto_editavel_nao_confunde_numero_do_corpo_com_chamador():
    """Só run marcado como superscript vira token."""
    p = Paragraph([Run("A safra de 2026 foi boa.")])
    assert texto_editavel(p) == "A safra de 2026 foi boa."
    assert paragrafo_de_texto(texto_editavel(p)).runs == p.runs
