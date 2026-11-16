"""Testes da deteccao de capitulos a partir do PDF."""
from backend.app.models import Chapter, Line, Paragraph, Run
from backend.app.pdf_chapters import (
    anchor_outline,
    anchor_printed_outline,
    assemble_chapters,
    build_chapters,
    detect_headings,
    extract_notes,
    is_page_number,
    join_paragraphs,
    merge_empty_parents,
    modal_body_size,
    normalize,
    parse_printed_toc,
    remove_running_lines,
    sanitize,
)


def _linha(page, text, size, y, bold=False, h=800.0):
    return Line(page=page, text=text, size=size, bold=bold, italic=False,
                bbox=(72.0, y, 500.0, y + size), page_height=h, page_width=600.0,
                runs=[])


def _linha_bbox(page, text, size, y, *, x0=72.0, x1=500.0, bold=False,
                runs=None, h=800.0):
    """Linha com bbox estreito e runs explicitos (para testar isolamento)."""
    return Line(page=page, text=text, size=size, bold=bold, italic=False,
                bbox=(x0, y, x1, y + size), page_height=h, page_width=600.0,
                runs=runs if runs is not None else [])


def _linha_sup(page, texto, size, y, numero, h=800.0):
    """Linha de corpo com um chamador de nota superscript numerico."""
    return Line(page=page, text=f"{texto} {numero}.", size=size, bold=False,
                italic=False, bbox=(72.0, y, 500.0, y + size), page_height=h,
                page_width=600.0,
                runs=[Run(texto + " "), Run(str(numero), superscript=True),
                      Run(".")])


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
    assert [linha.text for linha in out] == ["corpo"] * 4


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


# ---------------------------------------------------------------------------
# Regressao: sobreposicao natural de bbox nao quebra paragrafo (F1)
# ---------------------------------------------------------------------------


def test_junta_linhas_com_sobreposicao_natural_de_bbox():
    """PyMuPDF sobrepoe bboxes de linha ~2pt; isso nao separa paragrafo."""
    linhas = [_linha(0, "a primeira linha do paragrafo que ocupa toda a coluna",
                     10.0, 100),
              _linha(0, "e continua na segunda linha logo abaixo", 10.0, 107.5)]
    paras = join_paragraphs(linhas)
    assert len(paras) == 1
    assert "segunda linha" in paras[0].text


# ---------------------------------------------------------------------------
# Heuristica: titulos negritos menores que o corpo (F2)
# ---------------------------------------------------------------------------


def test_heuristica_detecta_titulo_bold_menor_isolado():
    """Titulo negrito com fonte <= corpo mas isolado (curto) e capitulo."""
    larga = _linha(0, "linha de corpo larga que ocupa toda a coluna do livro",
                   10.0, 120)
    titulo = _linha_bbox(0, "Uma abordagem prática", 10.0, 40, x1=192.0,
                         bold=True)
    det = detect_headings([larga, titulo], 10.0)
    assert det == [(1, 2, "Uma abordagem prática")]


def test_heuristica_ignora_negrito_em_linha_larga():
    """Negrito que ocupa a coluna inteira e verso de corpo, nao titulo."""
    linhas = [_linha_bbox(
        0, "Linha inteira de corpo em negrito que ocupa toda a coluna",
        10.0, 120, x1=500.0, bold=True)]
    assert detect_headings(linhas, 10.0) == []


def test_heuristica_ignora_negrito_nao_dominante():
    """Uma unica palavra em negrito no meio da linha nao faz um titulo."""
    larga = _linha(0, "linha de corpo larga que ocupa toda a coluna do livro",
                   10.0, 120)
    candidata = _linha_bbox(
        0, "texto com uma palavra destacada apenas", 10.0, 40, x1=232.0,
        runs=[Run("texto com uma "), Run("palavra", bold=True),
              Run(" destacada apenas")])
    assert detect_headings([larga, candidata], 10.0) == []


# ---------------------------------------------------------------------------
# Indice impresso como outline (F3/F4)
# ---------------------------------------------------------------------------


def _linha_indice(page, texto, y, *, size=10.0, x1=240.0, bold=False):
    return _linha_bbox(page, texto, size, y, x1=x1, bold=bold)


def test_parse_printed_toc_extrai_entradas_e_indices_do_bloco():
    linhas = [
        _linha_bbox(0, "Índice", 12.0, 40, x1=132.0, bold=True),
        _linha_indice(0, "Introdução ... I", 70),
        _linha_indice(0, "Primeira Parte- O ser humano", 100, x1=282.0,
                      bold=True),
        _linha_indice(0, "I. Uma vida humana ... 06", 130, x1=252.0),
        _linha_indice(0, "§1- O espírito … 25", 160, x1=202.0),
        _linha_indice(0, "a) O fantasma … 35", 190, x1=192.0),
        _linha(0, "x" * 60, 10.0, 300),  # largura maxima do corpo
        _linha(1, "Corpo do livro", 20.0, 90),
    ]
    entradas, bloco = parse_printed_toc(linhas)
    assert [t for _, t, _ in entradas] == [
        "Introdução", "Primeira Parte- O ser humano", "I. Uma vida humana",
        "§1- O espírito", "a) O fantasma"]
    assert [n for n, _, _ in entradas] == [1, 1, 2, 3, 3]
    assert bloco == {0, 1, 2, 3, 4, 5}


def test_anchor_printed_outline_ancora_por_similaridade():
    linhas = [_linha(0, "Introdução", 20.0, 50),
              _linha(0, "corpo do texto", 10.0, 120),
              _linha(1, "Uma vida humana", 20.0, 50),
              _linha(1, "corpo", 10.0, 120)]
    entradas = [(1, "Introdução", 1), (2, "Uma vida humana", 6)]
    anchors = anchor_printed_outline(linhas, entradas, 10.0)
    assert anchors == [(0, 1, "Introdução"), (2, 2, "Uma vida humana")]


def test_remove_cabecalho_com_espacos_extras_repetido():
    """Cabecalho de rodape com padding de espacos ainda e um cabecalho."""
    cabecalho = "Max Stirner" + " " * 80 + "O Único e sua Propriedade"
    linhas = [_linha(p, cabecalho, 12.0, 780, h=800.0) for p in range(4)]
    linhas += [_linha(p, "corpo", 10.0, 400, h=800.0) for p in range(4)]
    out = remove_running_lines(linhas, keep=set(), remove_header=True,
                               remove_page_numbers=True)
    assert [linha.text for linha in out] == ["corpo"] * 4


def test_linha_de_corpo_longa_nao_e_cabecalho():
    """Linha longa (>= _MAX_RUNNING_LEN normalizada) nunca e cabecalho."""
    corpo = ("palavra " * 20).strip()
    linhas = [_linha(p, corpo, 10.0, 780, h=800.0) for p in range(4)]
    out = remove_running_lines(linhas, keep=set(), remove_header=True,
                               remove_page_numbers=True)
    assert len(out) == 4


def test_dividir_capitulos_longos_marca_continuacoes():
    from backend.app.pdf_chapters import _dividir_capitulos_longos

    capitulo = Chapter("Longo", 2,
                       [Paragraph.from_text("palavra " * 100)
                        for _ in range(6)])
    partes = _dividir_capitulos_longos([capitulo], limite=200)
    assert len(partes) == 3
    assert [p.title for p in partes] == ["Longo", "Longo", "Longo"]
    assert [p.continues for p in partes] == [False, True, True]


def test_build_chapters_usa_indice_impresso_e_remove_a_pagina(tmp_path):
    import pymupdf

    p = tmp_path / "indice.pdf"
    doc = pymupdf.open()
    capa = doc.new_page()
    capa.insert_text((200, 300), "Autor Desconhecido", fontsize=24,
                     fontname="hebo")
    indice = doc.new_page()
    indice.insert_text((250, 80), "Índice", fontsize=14, fontname="hebo")
    indice.insert_text((150, 120), "Introdução ... 1", fontsize=12)
    indice.insert_text((150, 150), "Primeira Parte ... 5", fontsize=12)
    for titulo in ("Introdução", "Primeira Parte"):
        page = doc.new_page()
        page.insert_text((120, 90), titulo, fontsize=20, fontname="hebo")
        for k in range(20):
            page.insert_text((72, 140 + k * 18),
                             f"linha de corpo numero {k} do capitulo",
                             fontsize=12)
    doc.save(str(p))
    doc.close()

    chs, avisos = build_chapters(p)
    titulos = [c.title for c in chs]
    assert "Índice" not in titulos
    assert "Autor Desconhecido" not in titulos
    assert [c.title for c in chs] == ["Introdução", "Primeira Parte"]
    assert any("Índice impresso" in a for a in avisos)


# ---------------------------------------------------------------------------
# Notas de rodape (endnotes)
# ---------------------------------------------------------------------------


def test_extract_notes_agrupa_nota_multilinha():
    linhas = [
        _linha(0, "corpo do texto", 16.0, 200),
        _linha(0, "4  começa a nota e segue", 10.0, 700),
        _linha(0, "continuando na linha seguinte", 10.0, 712),
        _linha(0, "e termina aqui.", 10.0, 724),
        _linha(0, "mais corpo", 16.0, 300),
    ]
    notas, remover = extract_notes(linhas, 16.0, [(0, 1, "Cap")])
    assert len(notas) == 1
    numero, texto, indice = notas[0]
    assert numero == 4
    assert indice == 1
    assert texto == ("começa a nota e segue continuando na linha seguinte "
                     "e termina aqui.")
    assert remover == {1, 2, 3}


def test_extract_notes_ignora_linha_de_corpo_e_cabecalho():
    linhas = [
        _linha(0, "linha de corpo normal", 16.0, 700),
        _linha(0, "Cabecalho corrente", 12.0, 720),
    ]
    notas, remover = extract_notes(linhas, 16.0, [(0, 1, "Cap")])
    assert notas == []
    assert remover == set()


def _pdf_com_notas(tmp_path):
    import pymupdf

    p = tmp_path / "notas.pdf"
    doc = pymupdf.open()
    for titulo, nota in (("Capítulo Um", "Primeira nota do capítulo um."),
                         ("Capítulo Dois", "Segunda nota do capítulo dois.")):
        page = doc.new_page()
        page.insert_text((120, 90), titulo, fontsize=20, fontname="hebo")
        for k in range(6):
            page.insert_text((72, 150 + k * 18),
                             f"corpo do capitulo {k} com varias palavras aqui",
                             fontsize=12)
        page.insert_text((72, 720), f"1  {nota}", fontsize=8)
    doc.save(str(p))
    doc.close()
    return p


def test_build_chapters_associa_notas_ao_capitulo_e_remove_do_corpo(tmp_path):
    p = _pdf_com_notas(tmp_path)
    chs, _ = build_chapters(p)
    assert [c.title for c in chs] == ["Capítulo Um", "Capítulo Dois"]
    assert [n for n, _ in chs[0].notes] == [1]
    assert [n for n, _ in chs[1].notes] == [1]
    assert chs[0].notes[0][1] == "Primeira nota do capítulo um."
    assert chs[1].notes[0][1] == "Segunda nota do capítulo dois."
    corpo = " ".join(par.text for c in chs for par in c.paragraphs)
    assert "Primeira nota" not in corpo
    assert "Segunda nota" not in corpo


def test_build_chapters_nota_multilinha_agrupada(tmp_path):
    import pymupdf

    p = tmp_path / "nota_longa.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((120, 90), "Capítulo", fontsize=20, fontname="hebo")
    for k in range(6):
        page.insert_text((72, 150 + k * 18), f"corpo numero {k}", fontsize=12)
    page.insert_text((72, 700), "1  a nota comeca aqui e", fontsize=8)
    page.insert_text((72, 714), "segue nesta segunda linha", fontsize=8)
    page.insert_text((72, 728), "e fecha na terceira.", fontsize=8)
    doc.save(str(p))
    doc.close()

    chs, _ = build_chapters(p)
    assert len(chs) == 1
    assert len(chs[0].notes) == 1
    numero, texto = chs[0].notes[0]
    assert numero == 1
    assert texto == ("a nota comeca aqui e segue nesta segunda linha "
                     "e fecha na terceira.")


def test_extract_notes_aceita_numero_sozinho_e_pontuacao():
    linhas = [
        _linha(0, "corpo", 16.0, 200),
        _linha(0, "7", 10.0, 700),
        _linha(0, "texto que vem depois do numero sozinho", 10.0, 712),
        _linha(0, "8) outra nota", 10.0, 724),
        _linha(0, "9.mais uma nota colada", 10.0, 736),
    ]
    notas, remover = extract_notes(linhas, 16.0, [(0, 1, "Cap")])
    por_numero = {n: t for n, t, _ in notas}
    assert por_numero[7] == "texto que vem depois do numero sozinho"
    assert por_numero[8] == "outra nota"
    assert por_numero[9] == "mais uma nota colada"
    assert remover == {1, 2, 3, 4}


def test_extract_notes_nao_confunde_ano_de_quatro_digitos():
    linhas = [_linha(0, "corpo", 16.0, 200),
              _linha(0, "1844 foi um ano importante", 10.0, 700)]
    notas, _ = extract_notes(linhas, 16.0, [(0, 1, "Cap")])
    assert notas == []


def test_dividir_capitulos_distribui_notas_por_chamador():
    from backend.app.pdf_chapters import _dividir_capitulos_longos

    def par(*refs):
        runs = [Run("texto ")]
        for ref in refs:
            runs.append(Run(str(ref), superscript=True))
        return Paragraph(runs=runs)

    cap = Chapter("Longo", 2,
                  [par(1), par(2), par(3), par(4)],
                  notes=[(1, "n1"), (2, "n2"), (3, "n3"), (4, "n4"),
                         (5, "orfa")])
    partes = _dividir_capitulos_longos([cap], limite=4)
    assert len(partes) == 2
    assert [[n for n, _ in p.notes] for p in partes] == [[1, 2, 5], [3, 4]]
    todas = [n for p in partes for n, _ in p.notes]
    assert sorted(todas) == [1, 2, 3, 4, 5]  # nenhuma nota duplicada


def test_nota_associa_ao_capitulo_do_chamador(monkeypatch):
    """A nota pertence ao capitulo que chama, mesmo se a linha vier depois."""
    from backend.app import pdf_chapters

    linhas = [
        _linha(0, "Capítulo Um", 24.0, 90),
        _linha_sup(0, "a" * 80, 16.0, 150, 1),
        _linha(0, "Capítulo Dois", 24.0, 300),
        _linha_sup(0, "b" * 80, 16.0, 360, 2),
        _linha(0, "1  nota do primeiro capitulo no rodape", 10.0, 700),
    ]
    monkeypatch.setattr(pdf_chapters, "extract_lines",
                        lambda _p: (linhas, 1, []))
    chs, _ = pdf_chapters.build_chapters("x.pdf")
    um = next(c for c in chs if c.title == "Capítulo Um")
    dois = next(c for c in chs if c.title == "Capítulo Dois")
    assert [n for n, _ in um.notes] == [1]
    assert dois.notes == []


# ---------------------------------------------------------------------------
# Chamador de nota na linha do TITULO (F1/F3)
# ---------------------------------------------------------------------------


def _linha_titulo_sup(page, texto, numero, y, *, size=24.0, h=800.0):
    """Linha de titulo terminada por um run superscript numerico."""
    return Line(page=page, text=f"{texto} {numero}", size=size, bold=True,
                italic=False, bbox=(72.0, y, 500.0, y + size), page_height=h,
                page_width=600.0,
                runs=[Run(texto), Run(str(numero), superscript=True)])


def test_assemble_coleta_title_refs_da_linha_da_ancora():
    linhas = [
        _linha_titulo_sup(0, "II. O Proprietário", 190, 90),
        _linha(0, "corpo do capitulo", 16.0, 150),
    ]
    chs = assemble_chapters(linhas, [(0, 1, "II. O Proprietário")])
    assert chs[0].title_refs == [190]


def test_nota_chamada_no_titulo_deixa_de_ser_orfa(monkeypatch):
    """O chamador na linha do titulo conta como referencia da nota."""
    from backend.app import pdf_chapters

    linhas = [
        _linha_titulo_sup(0, "II. O Proprietário", 190, 90),
        _linha(0, "a" * 80, 16.0, 150),
        _linha(0, "190  nota chamada apenas no titulo", 10.0, 700),
    ]
    monkeypatch.setattr(pdf_chapters, "extract_lines",
                        lambda _p: (linhas, 1, []))
    chs, _ = pdf_chapters.build_chapters("x.pdf")
    assert len(chs) == 1
    assert chs[0].title_refs == [190]
    assert [n for n, _ in chs[0].notes] == [190]
    assert chs[0].notes[0][1] == "nota chamada apenas no titulo"


def test_dividir_capitulos_preserva_title_refs_so_na_primeira_parte():
    from backend.app.pdf_chapters import _dividir_capitulos_longos

    cap = Chapter("Longo", 1,
                  [Paragraph.from_text("palavra " * 100) for _ in range(6)],
                  title_refs=[9], notes=[(9, "nota do titulo")])
    partes = _dividir_capitulos_longos([cap], limite=200)
    assert len(partes) == 3
    assert partes[0].title_refs == [9]
    assert all(p.title_refs == [] for p in partes[1:])
    # a nota citada so no titulo fica com a primeira parte (que tem o heading)
    assert [n for n, _ in partes[0].notes] == [9]


def test_merge_empty_parents_soma_title_refs():
    chs = [Chapter("II. Parte", 1, [], title_refs=[190]),
           Chapter("O Proprietário", 2, [Paragraph.from_text("texto")],
                   title_refs=[191])]
    out = merge_empty_parents(chs)
    assert len(out) == 1
    assert out[0].title_refs == [190, 191]


def test_agrupar_ate_soma_title_refs():
    from backend.app.pdf_chapters import _agrupar_ate

    chs = [Chapter("A", 1, [Paragraph.from_text("x")], title_refs=[1]),
           Chapter("B", 1, [Paragraph.from_text("y")], title_refs=[2])]
    out = _agrupar_ate(chs, limite=1)
    assert len(out) == 1
    assert out[0].title_refs == [1, 2]
