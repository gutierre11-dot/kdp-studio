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


def test_span_superscript_gera_run_superscript(monkeypatch):
    """O bit 0 de `span["flags"]` (superscript) vira `Run.superscript`."""
    from backend.app import pdf_extract

    class _Rect:
        height = 800.0
        width = 600.0

    class _Pagina:
        rect = _Rect()

        def get_text(self, kind):
            return {"blocks": [{"type": 0, "lines": [{
                "bbox": (72.0, 100.0, 260.0, 120.0),
                "spans": [
                    {"text": "pedem", "size": 16.0, "flags": 0},
                    {"text": "7", "size": 10.6, "flags": 5},
                    {"text": ".", "size": 16.0, "flags": 0},
                ],
            }]}]}

    class _Doc:
        page_count = 1

        def __iter__(self):
            return iter([_Pagina()])

        def get_toc(self, simple=True):
            return []

        def close(self):
            pass

    monkeypatch.setattr(pdf_extract.pymupdf, "open", lambda *a, **k: _Doc())
    linhas, paginas, toc = pdf_extract.extract_lines("fake.pdf")
    assert paginas == 1
    assert toc == []
    runs = linhas[0].runs
    assert [r.text for r in runs] == ["pedem", "7", "."]
    assert runs[0].superscript is False
    assert runs[1].superscript is True
    assert runs[2].superscript is False
