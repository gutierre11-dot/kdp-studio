"""Testes do motor de traducao em lote."""
import pytest

from backend.app.llm import LLMError
from backend.app.models import Chapter, Paragraph
from backend.app.translate import (
    build_system_prompt,
    split_chunks,
    translate_chapter,
)


def test_split_chunks_sem_perda_nem_sobreposicao():
    texto = ("Parágrafo um. " * 40 + "\n\n") * 5
    chunks = split_chunks(texto, 300)
    assert "".join(chunks) == texto
    assert all(len(c) <= 300 for c in chunks)


def test_split_chunks_corta_em_fronteira_de_paragrafo():
    texto = "A" * 200 + "\n\n" + "B" * 200
    chunks = split_chunks(texto, 300)
    # o corte fica na fronteira do paragrafo, nao no meio dos "A"
    assert chunks[0].rstrip("\n") == "A" * 200


def test_split_chunks_limite_invalido():
    with pytest.raises(ValueError):
        split_chunks("x", 0)


def test_prompt_menciona_destino_e_contexto():
    p = build_system_prompt("en", "pt-BR", title="Livro X", chapter_title="Cap 1")
    assert "portugues brasileiro" in p
    assert "Livro X" in p
    assert "Cap 1" in p


def test_traducao_preserva_contagem_de_paragrafos(monkeypatch):
    monkeypatch.setattr("backend.app.translate._translate_text",
                        lambda t, **k: t.upper())
    ch = Chapter("T", 1, [Paragraph.from_text("alpha"),
                          Paragraph.from_text("beta")])
    out = translate_chapter(ch, title="L", source_lang="en", target_lang="pt-BR",
                            model=None, chunk_chars=6000, warn=lambda m: None)
    assert [p.text for p in out.paragraphs] == ["ALPHA", "BETA"]


def test_refaz_paragrafo_a_paragrafo_quando_o_lote_desalinha(monkeypatch):
    chamadas = []

    def fake(text, **k):
        chamadas.append(text)
        if "\n\n" in text:
            return "só um parágrafo"
        return text.upper()

    monkeypatch.setattr("backend.app.translate._translate_text", fake)
    ch = Chapter("T", 1, [Paragraph.from_text("alpha"),
                          Paragraph.from_text("beta")])
    out = translate_chapter(ch, title="L", source_lang="en", target_lang="pt-BR",
                            model=None, chunk_chars=6000, warn=lambda m: None)
    assert [p.text for p in out.paragraphs] == ["ALPHA", "BETA"]
    assert len(chamadas) == 3  # 1 lote + 2 parágrafos


def test_conteudo_preservado_quando_a_traducao_falha(monkeypatch):
    def fake(text, **k):
        raise LLMError("503")

    monkeypatch.setattr("backend.app.translate._translate_text", fake)
    avisos = []
    ch = Chapter("T", 1, [Paragraph.from_text("alpha")])
    out = translate_chapter(ch, title="L", source_lang="en", target_lang="pt-BR",
                            model=None, chunk_chars=6000, warn=avisos.append)
    assert [p.text for p in out.paragraphs] == ["alpha"]
    assert avisos


def test_paragrafo_gigante_e_dividido_e_reunido(monkeypatch):
    monkeypatch.setattr("backend.app.translate._translate_text",
                        lambda t, **k: "T" + t)
    grande = "palavra " * 400  # ~3200 chars, acima do limite de 1000
    ch = Chapter("T", 1, [Paragraph.from_text(grande)])
    out = translate_chapter(ch, title="L", source_lang="en", target_lang="pt-BR",
                            model=None, chunk_chars=1000, warn=lambda m: None)
    assert len(out.paragraphs) == 1
    assert out.paragraphs[0].text.startswith("T")
    assert out.paragraphs[0].text.count("palavra") == 400


def test_chapter_vazio_nao_quebra(monkeypatch):
    ch = Chapter("Vazio", 1, [])
    out = translate_chapter(ch, title="L", source_lang="en", target_lang="pt-BR",
                            model=None, chunk_chars=6000, warn=lambda m: None)
    assert out.paragraphs == []
