"""Testes da extração de linhas do PDF."""
from backend.app.pdf_extract import extract_lines


def test_extrai_linhas_com_pagina_tamanho_e_runs(make_pdf):
    path = make_pdf([("Capítulo Um", "O corpo do texto segue aqui.")],
                    header=None, footer_numbers=False)
    lines, pages, toc = extract_lines(path)
    assert pages == 1
    assert toc == []
    titulos = [l for l in lines if l.text == "Capítulo Um"]
    assert titulos and titulos[0].size >= 18.0
    assert titulos[0].runs
    assert "".join(r.text for r in titulos[0].runs).strip()


def test_extrai_bookmarks(make_bookmark_pdf):
    lines, pages, toc = extract_lines(make_bookmark_pdf)
    assert pages == 2
    assert toc == [[1, "Capítulo Um", 1], [1, "Capítulo Dois", 2]]
    assert [l.text for l in lines if l.size >= 18] == ["Capítulo Um",
                                                       "Capítulo Dois"]


def test_linhas_em_ordem_de_leitura(make_pdf):
    path = make_pdf([("Capítulo Um", "corpo do texto"), ("Capítulo Dois", "outro")],
                    header=None, footer_numbers=False)
    lines, _, _ = extract_lines(path)
    chave = [(l.page, l.bbox[1], l.bbox[0]) for l in lines]
    assert chave == sorted(chave)
