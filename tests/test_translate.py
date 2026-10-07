"""Testes do motor de traducao em lote."""
import threading

import pytest

from backend.app.llm import LLMError
from backend.app.models import Chapter, Paragraph
from backend.app.translate import (
    CancelledError,
    build_system_prompt,
    detect_language,
    split_chunks,
    translate_chapter,
    translate_chapters,
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
    assert len(chamadas) == 4  # 1 título + 1 lote + 2 parágrafos


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


def test_numero_de_chamadas_proporcional_a_chunks_nao_a_paragrafos(monkeypatch):
    chamadas = []

    def fake(text, **k):
        chamadas.append(text)
        return text.upper()

    monkeypatch.setattr("backend.app.translate._translate_text", fake)
    chs = [Chapter(f"C{i}", 1, [Paragraph.from_text(f"p{j}") for j in range(50)])
           for i in range(3)]
    out, avisos = translate_chapters(chs, title="L", source_lang="en",
                                     target_lang="pt-BR", model=None, workers=1,
                                     chunk_chars=6000)
    # no maximo 2 chamadas por capitulo (titulo + corpo), nunca 1 por paragrafo
    assert len(chamadas) <= 2 * len(chs)
    assert len(chamadas) < 20
    assert len(out) == 3
    assert not avisos


def test_progresso_e_reportado(monkeypatch):
    monkeypatch.setattr("backend.app.translate._translate_text",
                        lambda t, **k: t)
    vistos = []
    chs = [Chapter(f"C{i}", 1, [Paragraph.from_text("x" * 4000)])
           for i in range(4)]
    translate_chapters(chs, title="L", source_lang="en", target_lang="pt-BR",
                       model=None, workers=2, chunk_chars=2000,
                       progress=lambda p, msg: vistos.append(p))
    assert vistos
    assert vistos == sorted(vistos)
    assert vistos[-1] == 100


def test_cancelamento_interrompe(monkeypatch):
    monkeypatch.setattr("backend.app.translate._translate_text",
                        lambda t, **k: t)
    evento = threading.Event()

    def prog(p, msg):
        if p >= 30:
            evento.set()

    chs = [Chapter(f"C{i}", 1, [Paragraph.from_text("x" * 9000)])
           for i in range(6)]
    with pytest.raises(CancelledError):
        translate_chapters(chs, title="L", source_lang="en", target_lang="pt-BR",
                           model=None, workers=1, chunk_chars=1000,
                           progress=prog, cancel=evento)


def test_falha_de_um_capitulo_nao_aborta_os_outros(monkeypatch):
    def fake(text, **k):
        if "BOM" in text:
            raise LLMError("503")
        return text.upper()

    monkeypatch.setattr("backend.app.translate._translate_text", fake)
    chs = [Chapter("A", 1, [Paragraph.from_text("ok")]),
           Chapter("B", 1, [Paragraph.from_text("BOM falha")]),
           Chapter("C", 1, [Paragraph.from_text("ok2")])]
    out, avisos = translate_chapters(chs, title="L", source_lang="en",
                                     target_lang="pt-BR", model=None, workers=1,
                                     chunk_chars=6000)
    assert len(out) == 3
    assert out[1].paragraphs[0].text == "BOM falha"
    assert avisos


def test_lista_vazia_nao_quebra():
    out, avisos = translate_chapters([], title="L", source_lang="en",
                                     target_lang="pt-BR", model=None, workers=1,
                                     chunk_chars=6000)
    assert out == [] and avisos == []


def test_detect_language_reconhece_ingles_e_portugues():
    ingles = ("The cellar smelled of oak and time. She held the letter with her "
              "fingertips, as if the paper might dissolve. There are truths "
              "that wine keeps better than men, and that is why the letter "
              "matters to her.")
    portugues = ("A adega cheirava a carvalho e tempo. Ela segurou a carta com "
                 "as pontas dos dedos, como se o papel pudesse se desfazer. "
                 "Existem verdades que o vinho guarda melhor que os homens, e "
                 "por isso a carta importa para ela.")
    assert detect_language(ingles) == "en"
    assert detect_language(portugues) == "pt-BR"


def test_detect_language_sem_texto_usa_o_padrao():
    assert detect_language("") == "pt-BR"
    assert detect_language("1234 5678") == "pt-BR"


def test_titulo_do_capitulo_e_traduzido(monkeypatch):
    def fake(text, **k):
        if text == "Chapter One":
            return "Capítulo Um"
        return text.upper()

    monkeypatch.setattr("backend.app.translate._translate_text", fake)
    ch = Chapter("Chapter One", 1, [Paragraph.from_text("alpha")])
    out = translate_chapter(ch, title="L", source_lang="en", target_lang="pt-BR",
                            model=None, chunk_chars=6000, warn=lambda m: None)
    assert out.title == "Capítulo Um"
    assert [p.text for p in out.paragraphs] == ["ALPHA"]


def test_titulos_tambem_sao_traduzidos_em_lote(monkeypatch):
    def fake(text, **k):
        return text.replace("Chapter", "Capítulo").replace("body", "corpo")

    monkeypatch.setattr("backend.app.translate._translate_text", fake)
    chs = [Chapter("Chapter One", 1, [Paragraph.from_text("body one")]),
           Chapter("Chapter Two", 1, [Paragraph.from_text("body two")])]
    out, _ = translate_chapters(chs, title="L", source_lang="en",
                                target_lang="pt-BR", model=None, workers=1,
                                chunk_chars=6000)
    assert [c.title for c in out] == ["Capítulo One", "Capítulo Two"]
    assert [[p.text for p in c.paragraphs] for c in out] == [["corpo one"],
                                                             ["corpo two"]]


def test_traducao_totalmente_falha_levanta_erro(monkeypatch):
    def fake(text, **k):
        raise LLMError("503 UNAVAILABLE")

    monkeypatch.setattr("backend.app.translate._translate_text", fake)
    chs = [Chapter("A", 1, [Paragraph.from_text("alpha")])]
    with pytest.raises(LLMError, match="não produziu"):
        translate_chapters(chs, title="L", source_lang="en", target_lang="pt-BR",
                           model=None, workers=1, chunk_chars=6000)


def test_sem_reparo_paragrafo_a_paragrafo_quando_a_cadeia_esta_fora(monkeypatch):
    """Com a cadeia de modelos fora, nao se gastam N chamadas condenadas."""
    chamadas = []

    def fake(text, **k):
        chamadas.append(text)
        raise LLMError("503")

    monkeypatch.setattr("backend.app.translate._translate_text", fake)
    avisos = []
    capitulo = Chapter("T", 1, [Paragraph.from_text(f"p{i}") for i in range(10)])
    out = translate_chapter(capitulo, title="L", source_lang="en",
                            target_lang="pt-BR", model=None, chunk_chars=6000,
                            warn=avisos.append)
    # 1 chamada para o titulo + 1 para o lote; nenhuma por paragrafo
    assert len(chamadas) == 2
    assert [p.text for p in out.paragraphs] == [f"p{i}" for i in range(10)]
    assert avisos
