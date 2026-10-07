"""Testes do modelo de dados compartilhado."""
from backend.app.models import Chapter, JobState, Paragraph, Run


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
