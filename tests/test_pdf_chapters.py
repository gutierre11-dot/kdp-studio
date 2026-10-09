"""Testes da deteccao de capitulos a partir do PDF."""
from backend.app.models import Chapter, Line, Paragraph
from backend.app.pdf_chapters import (
    anchor_outline,
    assemble_chapters,
    build_chapters,
    detect_headings,
    is_page_number,
    join_paragraphs,
    merge_empty_parents,
    modal_body_size,
    normalize,
    remove_running_lines,
    sanitize,
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


def test_titulo_no_meio_da_pagina_e_ancorado():
    """Secoes comecam no meio da pagina; so o rodape deve ser descartado."""
    linhas = [_linha(0, "corpo do texto", 10.0, 200, h=800.0),
              _linha(0, "Seção no meio", 21.0, 500, h=800.0)]
    anchors = anchor_outline(linhas, [[1, "Seção no meio", 1]], 10.0)
    assert anchors == [(1, 1, "Seção no meio")]


def test_linha_de_rodape_nao_e_ancorada():
    linhas = [_linha(0, "corpo", 10.0, 760, h=800.0)]
    assert anchor_outline(linhas, [[1, "corpo", 1]], 10.0) == []


def test_heuristica_detecta_titulo_por_tamanho():
    linhas = [_linha(0, "Capítulo Um", 22.0, 40),
              _linha(0, "corpo do texto.", 10.0, 120)]
    det = detect_headings(linhas, 10.0)
    assert [(i, lv) for i, lv, _ in det] == [(0, 1)]


def test_heuristica_ignora_frase_do_corpo():
    linhas = [_linha(0, "Esta é uma frase normal do corpo do livro.", 10.0, 120)]
    assert detect_headings(linhas, 10.0) == []


def test_heuristica_ignora_capitulo_no_meio_de_frase():
    """A quebra de linha de um paragrafo pode comecar com "capitulo.".

    Sem esta guarda a linha vira titulo nivel 1, sai do corpo e parte o
    capitulo em dois no EPUB.
    """
    linhas = [_linha(0, "o fim do paragrafo anterior e o inicio do segundo", 10.0, 100),
              _linha(0, "capitulo. A narrativa segue normalmente.", 10.0, 120)]
    assert detect_headings(linhas, 10.0) == []


def test_heuristica_ainda_detecta_capitulo_numerado_e_por_extenso():
    linhas = [_linha(0, "Capítulo 7", 10.0, 40),
              _linha(0, "Capítulo Um", 10.0, 60),
              _linha(0, "Parte IV", 10.0, 80)]
    det = detect_headings(linhas, 10.0)
    assert [titulo for _, _, titulo in det] == ["Capítulo 7", "Capítulo Um",
                                                "Parte IV"]
    assert [nivel for _, nivel, _ in det] == [1, 1, 1]


def test_heuristica_ignora_materia_no_meio_de_frase():
    linhas = [_linha(0, "Conclusão. O país mudou muito desde então.", 10.0, 120)]
    assert detect_headings(linhas, 10.0) == []


def test_heuristica_detecta_materia_isolada():
    linhas = [_linha(0, "Prefácio", 10.0, 40),
              _linha(0, "Sumário", 10.0, 200)]
    det = detect_headings(linhas, 10.0)
    assert [titulo for _, _, titulo in det] == ["Prefácio", "Sumário"]


def test_heuristica_ignora_nota_de_rodape_numerada():
    """Notas comecam com "1 texto"; so "1. Titulo" e titulo numerado."""
    linhas = [_linha(0, "1 Tradução de João Barrento, cuja 2ª edição", 10.0, 120),
              _linha(0, "7 Lucas 11:13", 10.0, 200)]
    assert detect_headings(linhas, 10.0) == []


def test_heuristica_detecta_titulo_numerado_com_ponto():
    linhas = [_linha(0, "1.2 Quadro geral", 10.0, 40),
              _linha(0, "1. Os antigos", 10.0, 120)]
    det = detect_headings(linhas, 10.0)
    assert [titulo for _, _, titulo in det] == ["1.2 Quadro geral", "1. Os antigos"]


def test_heuristica_nivel_segue_profundidade_da_numeracao():
    linhas = [_linha(0, "1. Os antigos", 10.0, 40),
              _linha(0, "1.2 Quadro geral", 10.0, 80)]
    det = detect_headings(linhas, 10.0)
    assert [(titulo, nivel) for _, nivel, titulo in det] == [("1. Os antigos", 2),
                                                             ("1.2 Quadro geral", 3)]


def test_heuristica_titulo_romano_e_nivel_de_parte():
    linhas = [_linha(0, "IV. Resultados", 11.5, 40, bold=True)]
    assert detect_headings(linhas, 10.0) == [(0, 1, "IV. Resultados")]


def test_heuristica_ignora_romano_no_meio_do_corpo():
    """Sem fonte de titulo, "II. Esses lutam..." no corpo nao vira capitulo."""
    linhas = [_linha(0, "II. Esses lutam pela fé da igreja e pelas leis morais",
                     12.0, 300)]
    assert detect_headings(linhas, 12.0) == []


def test_remove_pagina_impressa_colada_ao_titulo():
    """A pagina impressa sai na mesma linha do titulo em alguns PDFs."""
    linhas = [_linha(0, "II. O Proprietário 190", 11.5, 40, bold=True),
              _linha(0, "2. Meu intercurso com os homens 237", 10.0, 120)]
    det = detect_headings(linhas, 10.0)
    assert [titulo for _, _, titulo in det] == ["II. O Proprietário",
                                                "2. Meu intercurso com os homens"]
    assert [nivel for _, nivel, _ in det] == [1, 2]


def test_numero_do_proprio_titulo_nao_e_removido():
    linhas = [_linha(0, "Capítulo 1", 10.0, 40),
              _linha(0, "Parte IV", 10.0, 80),
              _linha(0, "1. Os antigos", 10.0, 120)]
    det = detect_headings(linhas, 10.0)
    assert [titulo for _, _, titulo in det] == ["Capítulo 1", "Parte IV",
                                                "1. Os antigos"]


def test_heuristica_ignora_parte_no_meio_do_paragrafo():
    """"parte de nossa propriedade..." e prosa, nao o titulo "Parte IV"."""
    linhas = [_linha(0, "parte de nossa propriedade se torne estável, e nos", 10.0, 100),
              _linha(0, "Parte da eficácia dos intelectos sacerdotais é o que", 10.0, 140)]
    assert detect_headings(linhas, 10.0) == []


def test_heuristica_detecta_parte_com_numeral_ou_extenso():
    linhas = [_linha(0, "Parte IV", 10.0, 40),
              _linha(0, "Parte Dois", 10.0, 80)]
    det = detect_headings(linhas, 10.0)
    assert [titulo for _, _, titulo in det] == ["Parte IV", "Parte Dois"]


def test_heuristica_materia_aceita_continuacao_minuscula():
    """"Notas do tradutor" e titulo; a guarda de prosa vale so para capitulo."""
    linhas = [_linha(0, "Notas do tradutor", 10.0, 40)]
    det = detect_headings(linhas, 10.0)
    assert [titulo for _, _, titulo in det] == ["Notas do tradutor"]


def test_heuristica_ignora_linha_do_sumario_com_lideres():
    linhas = [_linha(0, "1. Os antigos … 13", 10.0, 40),
              _linha(0, "Introdução ...I", 10.0, 80)]
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


def test_is_page_number_reconhece_formatos():
    assert is_page_number("42")
    assert is_page_number(" xii ")
    assert is_page_number("Página 7")
    assert not is_page_number("O ano de 1842 foi decisivo")
    assert not is_page_number("Capítulo 42")


def test_remove_cabecalho_repetido_por_banda():
    linhas = [_linha(p, "Capítulo Um ■ Quadro geral", 10.0, 20, h=800.0)
              for p in range(4)]
    linhas += [_linha(p, "corpo", 10.0, 400, h=800.0) for p in range(4)]
    out = remove_running_lines(linhas, keep=set(), remove_header=True,
                               remove_page_numbers=True)
    assert [l.text for l in out] == ["corpo"] * 4


def test_ancora_nunca_e_removida():
    linhas = [_linha(p, "Capítulo Um", 10.0, 20, h=800.0) for p in range(4)]
    out = remove_running_lines(linhas, keep={0}, remove_header=True,
                               remove_page_numbers=True)
    assert len(out) == 1
    assert out[0].text == "Capítulo Um"


def test_toggles_desligados_preservam_tudo():
    linhas = [_linha(p, "42", 10.0, 780, h=800.0) for p in range(4)]
    out = remove_running_lines(linhas, keep=set(), remove_header=False,
                               remove_page_numbers=False)
    assert len(out) == 4


def test_des_hifeniza_palavra_quebrada():
    linhas = [_linha(0, "transfor-", 10.0, 100),
              _linha(0, "macao social", 10.0, 112)]
    paras = join_paragraphs(linhas)
    assert paras[0].text == "transformacao social"


def test_remove_soft_hyphen():
    linhas = [_linha(0, "trans\u00adformação", 10.0, 100)]
    assert join_paragraphs(linhas)[0].text == "transformação"


def test_junta_paragrafo_entre_paginas():
    linhas = [_linha(0, "primeira parte", 10.0, 700, h=800.0),
              _linha(1, "segunda parte.", 10.0, 60, h=800.0)]
    assert join_paragraphs(linhas)[0].text == "primeira parte segunda parte."


def test_separa_paragrafos_por_espaco_vertical():
    linhas = [_linha(0, "um parágrafo.", 10.0, 100),
              _linha(0, "outro parágrafo.", 10.0, 200)]
    assert [p.text for p in join_paragraphs(linhas)] == ["um parágrafo.",
                                                         "outro parágrafo."]


def test_assemble_fatia_entre_ancoras():
    linhas = [_linha(0, "Cap A", 20.0, 40), _linha(0, "texto A", 10.0, 100),
              _linha(0, "Cap B", 20.0, 200), _linha(0, "texto B", 10.0, 260)]
    chs = assemble_chapters(linhas, [(0, 1, "Cap A"), (2, 1, "Cap B")])
    assert [(c.title, c.level, [p.text for p in c.paragraphs])
            for c in chs] == [("Cap A", 1, ["texto A"]),
                              ("Cap B", 1, ["texto B"])]


def test_sanitize_descarta_capitulo_vazio_com_aviso():
    chs = [Chapter("Vazio", 1, []),
           Chapter("Cheio", 1, [Paragraph.from_text("x")])]
    out, avisos = sanitize(chs, pages=10)
    assert [c.title for c in out] == ["Cheio"]
    assert avisos


def test_sanitize_degrada_quando_explode_a_contagem():
    chs = [Chapter(f"C{i}", 1, [Paragraph.from_text("x")]) for i in range(200)]
    out, avisos = sanitize(chs, pages=20)
    assert len(out) <= 20
    assert any("conservadora" in a for a in avisos)


def test_build_chapters_pdf_sem_texto(tmp_path):
    import pymupdf

    p = tmp_path / "vazio.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(p))
    doc.close()
    chs, avisos = build_chapters(p)
    assert len(chs) == 1
    assert "sem texto" in " ".join(avisos).lower()


def test_build_chapters_nao_parte_paragrafo_com_capitulo_no_inicio(tmp_path):
    """Regressao: "capitulo." abrindo uma linha de corpo nao e um titulo."""
    import pymupdf

    p = tmp_path / "colado.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 90), "O trem chegou atrasado naquela manha fria e o",
                     fontsize=12)
    page.insert_text((72, 110), "capitulo. A narrativa segue normalmente por",
                     fontsize=12)
    page.insert_text((72, 130), "varias linhas seguidas sem titulo nenhum.",
                     fontsize=12)
    doc.save(str(p))
    doc.close()

    chs, _ = build_chapters(p)
    assert len(chs) == 1
    assert "capitulo" not in chs[0].title.lower()
    corpo = " ".join(par.text for par in chs[0].paragraphs).lower()
    assert "narrativa" in corpo


def test_build_chapters_usa_outline(make_bookmark_pdf):
    chs, _ = build_chapters(make_bookmark_pdf)
    assert [c.title for c in chs] == ["Capítulo Um", "Capítulo Dois"]


def test_funde_titulo_pai_sem_conteudo_no_proximo_capitulo():
    chs = [Chapter("Capítulo 1", 1, []),
           Chapter("Quadro geral", 2, [Paragraph.from_text("texto")])]
    out = merge_empty_parents(chs)
    assert len(out) == 1
    assert out[0].title == "Capítulo 1 — Quadro geral"
    assert out[0].level == 1
    assert [p.text for p in out[0].paragraphs] == ["texto"]


def test_funde_cadeia_de_pais_vazios():
    chs = [Chapter("Parte I", 1, []),
           Chapter("Capítulo 1", 2, []),
           Chapter("A Chegada", 3, [Paragraph.from_text("texto")])]
    out = merge_empty_parents(chs)
    assert len(out) == 1
    assert out[0].title == "Parte I — Capítulo 1 — A Chegada"
    assert out[0].level == 1


def test_nao_funde_capitulo_vazio_sem_filho():
    chs = [Chapter("Cover", 1, []),
           Chapter("Texto", 1, [Paragraph.from_text("x")])]
    out = merge_empty_parents(chs)
    assert [c.title for c in out] == ["Cover", "Texto"]
