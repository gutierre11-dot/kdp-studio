"""Testes da deteccao de capitulos a partir do PDF."""
from backend.app.models import Line
from backend.app.pdf_chapters import (
    anchor_outline,
    detect_headings,
    modal_body_size,
    normalize,
)


def _linha(page, text, size, y, bold=False, h=800.0):
    return Line(page=page, text=text, size=size, bold=bold, italic=False,
                bbox=(72.0, y, 500.0, y + size), page_height=h, page_width=600.0,
                runs=[])


def test_normalize_remove_acentos_pontuacao_e_caixa():
    assert normalize("Capítulo 1 — Quadro geral!") == "capitulo 1 quadro geral"


def test_modal_body_size_usa_caracteres_nao_linhas():
    linhas = ([_linha(0, "titulo", 20.0, 10)]
              + [_linha(0, "x" * 200, 10.0, 100 + i) for i in range(5)])
    assert modal_body_size(linhas) == 10.0


def test_ancora_entrada_de_outline_na_linha_correta():
    linhas = [_linha(0, "Prefácio", 22.0, 50), _linha(0, "corpo", 10.0, 120),
              _linha(1, "Capítulo Um", 22.0, 50), _linha(1, "corpo", 10.0, 120)]
    anchors = anchor_outline(linhas,
                             [[1, "Prefácio", 1], [1, "Capítulo Um", 2]], 10.0)
    assert anchors == [(0, 1, "Prefácio"), (2, 1, "Capítulo Um")]


def test_reancora_quando_titulo_nao_casa_perfeitamente():
    linhas = [_linha(0, "Prefácio geral", 22.0, 50)]
    anchors = anchor_outline(linhas, [[1, "Prefácio geral da obra", 1]], 10.0)
    assert anchors and anchors[0][0] == 0


def test_descarta_entrada_sem_nenhuma_linha_na_pagina():
    linhas = [_linha(0, "corpo", 10.0, 120)]
    assert anchor_outline(linhas, [[1, "Inexistente", 5]], 10.0) == []


def test_entradas_duplicadas_nao_produzem_ancoras_repetidas():
    linhas = [_linha(0, "Capítulo Um", 22.0, 50), _linha(0, "corpo", 10.0, 120)]
    anchors = anchor_outline(linhas,
                             [[1, "Capítulo Um", 1], [1, "Capítulo Um", 1]], 10.0)
    assert len({i for i, _, _ in anchors}) == len(anchors)
    assert [i for i, _, _ in anchors] == sorted(i for i, _, _ in anchors)


def test_candidato_abaixo_da_banda_de_topo_nao_e_ancorado():
    linhas = [_linha(0, "corpo", 10.0, 700, h=800.0)]
    assert anchor_outline(linhas, [[1, "corpo", 1]], 10.0) == []


def test_heuristica_detecta_titulo_por_tamanho():
    linhas = [_linha(0, "Capítulo Um", 22.0, 40),
              _linha(0, "corpo do texto.", 10.0, 120)]
    det = detect_headings(linhas, 10.0)
    assert [(i, lv) for i, lv, _ in det] == [(0, 1)]


def test_heuristica_ignora_frase_do_corpo():
    linhas = [_linha(0, "Esta é uma frase normal do corpo do livro.", 10.0, 120)]
    assert detect_headings(linhas, 10.0) == []


def test_heuristica_ignora_numero_de_pagina():
    linhas = [_linha(0, "42", 10.0, 780, h=800.0)]
    assert detect_headings(linhas, 10.0) == []


def test_heuristica_detecta_capitulo_numerado_mesmo_sem_fonte_maior():
    linhas = [_linha(0, "CAPÍTULO 7", 10.0, 40),
              _linha(0, "corpo do texto.", 10.0, 120)]
    det = detect_headings(linhas, 10.0)
    assert det and det[0][1] == 1


def test_heuristica_detecta_subtitulo_bold_pequeno():
    linhas = [_linha(0, "Uma abordagem prática", 11.5, 40, bold=True),
              _linha(0, "corpo do texto.", 10.0, 120)]
    det = detect_headings(linhas, 10.0)
    assert det and det[0][1] == 2
