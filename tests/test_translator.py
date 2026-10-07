"""Testes da traducao (translator): idioma de destino e nao-duplicacao."""
from __future__ import annotations

from backend.app import translator as tr


def test_chunk_text_sem_perda_e_sem_sobreposicao():
    # tokens unicos: se houvesse overlap, a soma dos tamanhos excederia o texto
    texto = " ".join(f"palavra{i}" for i in range(400))
    chunks = tr.chunk_text(texto, size=300)
    assert len(chunks) > 1
    assert "".join(chunks) == texto
    assert sum(len(c) for c in chunks) == len(texto)
    assert all(len(c) <= 300 for c in chunks)


def test_chunk_text_respeita_paragrafos():
    texto = ("alpha " * 100) + "\n\n" + ("beta " * 100)
    chunks = tr.chunk_text(texto, size=300)
    assert "".join(chunks) == texto


def test_chunk_text_texto_curto():
    assert tr.chunk_text("curto") == ["curto"]


def test_chunk_text_size_invalido():
    import pytest
    with pytest.raises(ValueError):
        tr.chunk_text("abc", size=0)


def test_prompt_respeita_idioma_de_destino():
    prompt_en = tr.build_system_prompt("pt-BR", "en")
    assert "para ingles" in prompt_en
    assert "para portugues brasileiro" not in prompt_en
    prompt_pt = tr.build_system_prompt("en", "pt-BR")
    assert "para portugues brasileiro" in prompt_pt
    assert "O texto de origem esta em ingles" in prompt_pt


def test_translate_text_offline_respeita_target():
    out = tr.translate_text("Hello world", target_lang="en")
    assert out.startswith("[en mock]")
    out_pt = tr.translate_text("Hello world", target_lang="pt-BR")
    assert out_pt.startswith("[pt-BR mock]")


def test_translate_text_preserva_paragrafos():
    out = tr.translate_text("Primeiro paragrafo.\n\nSegundo paragrafo.",
                            target_lang="en")
    assert "\n\n" in out
    assert out.count("[en mock]") == 2


def test_translate_chapters_mantem_estrutura():
    chapters = [
        {"title": "Chapter 1", "level": 1, "paragraphs": ["Hello.", "World."]},
        {"title": "", "level": 1, "paragraphs": ["Bye."]},
    ]
    out = tr.translate_chapters(chapters, model="gpt-4o-mini", target_lang="en")
    assert len(out) == 2
    assert out[0]["title"].startswith("[en mock]")
    assert len(out[0]["paragraphs"]) == 2
    assert out[1]["title"] == ""
    assert out[1]["paragraphs"][0].startswith("[en mock]")


def test_mock_nao_duplica_marcador():
    uma = tr._mock_translate("Texto.", "en")
    duas = tr._mock_translate(uma, "en")
    assert duas.count("[en mock]") == 1
