"""Testes da extracao/limpeza de PDF (pdf_cleaner)."""
from __future__ import annotations

import re

import pytest

from backend.app import pdf_cleaner as pc
from tests.conftest import PAGES_3


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_detecta_capitulos(make_pdf):
    pdf = make_pdf(PAGES_3)
    chapters = pc.parse_pdf_to_chapters(pdf)
    assert len(chapters) == 3
    titulos = [c["title"] for c in chapters]
    assert titulos == ["Capítulo 1 - A Chegada", "Capítulo 2 - O Segredo",
                       "Capítulo 3 - A Verdade"]
    assert all(c["level"] == 1 for c in chapters)


def test_paragrafos_nao_quebram_no_meio_da_frase(make_pdf):
    """Regressao: cada linha virava um paragrafo e cortava no meio da palavra."""
    pdf = make_pdf(PAGES_3)
    blocks = pc.extract_blocks(pdf)
    corpo = [b["text"] for b in blocks if b["text"].startswith("O trem")]
    assert len(corpo) == 1, f"corpo fragmentado em {len(corpo)} blocos: {corpo}"
    assert _norm(corpo[0]) == _norm(PAGES_3[0][1])
    # o texto nao pode terminar no meio de uma palavra
    assert not corpo[0].endswith("olha")


def test_des_hifenizacao(tmp_path):
    """'transfor-' + 'macao' (quebra de linha) devem virar 'transformacao'."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), "Capítulo 1", fontsize=22, fontname="helv")
    page.insert_text((72, 140), "Uma transfor-", fontsize=12, fontname="helv")
    page.insert_text((72, 158), "macao completa do texto.", fontsize=12, fontname="helv")
    pdf = tmp_path / "hifen.pdf"
    doc.save(str(pdf))
    doc.close()

    blocks = pc.extract_blocks(pdf)
    textos = " ".join(b["text"] for b in blocks)
    assert "transformacao" in textos
    assert "transfor- macao" not in textos


def test_remove_header_e_numeracao_por_padrao(make_pdf):
    pdf = make_pdf(PAGES_3)
    chapters = pc.parse_pdf_to_chapters(pdf)
    texto = " ".join(p for c in chapters for p in c["paragraphs"])
    assert "LIVRO DE TESTE" not in texto
    assert "|" not in texto


def test_toggle_remove_header_desligado(make_pdf):
    pdf = make_pdf(PAGES_3)
    chapters = pc.parse_pdf_to_chapters(pdf, remove_header=False)
    texto = " ".join(p for c in chapters for p in c["paragraphs"])
    assert "LIVRO DE TESTE" in texto


def test_toggle_remove_page_numbers_desligado(make_pdf):
    pdf = make_pdf(PAGES_3)
    chapters = pc.parse_pdf_to_chapters(pdf, remove_page_numbers=False)
    texto = " ".join(p for c in chapters for p in c["paragraphs"])
    # a numeracao de pagina volta a aparecer
    assert re.search(r"\b[123]\b", texto)


def test_pdf_sem_texto(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page()  # pagina em branco
    p = tmp_path / "vazio.pdf"
    doc.save(str(p))
    doc.close()
    chapters = pc.parse_pdf_to_chapters(p)
    assert chapters and chapters[0]["paragraphs"]


def test_is_page_number_nao_remove_palavras():
    assert pc.is_page_number("12") is True
    assert pc.is_page_number("Página 7") is True
    assert pc.is_page_number("civil") is False
    assert pc.is_page_number("mim") is False
    assert pc.is_page_number("Isso e um paragrafo normal.") is False


def test_is_heading_heuristica():
    assert pc.is_heading("Capítulo 12", 11, h1_thresh=20, h2_thresh=14, bold=False) == 1
    assert pc.is_heading("texto comum do corpo " * 12, 12, 20, 14, False) == 0
