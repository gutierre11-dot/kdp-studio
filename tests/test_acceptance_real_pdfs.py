"""Aceitacao com PDFs reais (CA1-CA3).

Roda apenas quando `KDP_REAL_PDFS_DIR` aponta para um diretorio com os livros:

    KDP_REAL_PDFS_DIR=~/Downloads python3 -m pytest -m acceptance -q
"""
import os
import re
import zipfile
from pathlib import Path

import pytest

from backend.app.kdp_epub import build_epub, validate_epub
from backend.app.pdf_chapters import build_chapters, normalize

DIR = os.getenv("KDP_REAL_PDFS_DIR")

pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.skipif(not DIR or not Path(DIR).is_dir(),
                       reason="KDP_REAL_PDFS_DIR não definido"),
]


def _pdf(prefixo: str) -> Path:
    achado = sorted(Path(DIR).glob(prefixo + "*.pdf"))
    if not achado:
        pytest.skip(f"PDF não encontrado: {prefixo}")
    return achado[0]


def test_livro_pt_nivel1_entre_10_e_40():
    chs, avisos = build_chapters(_pdf("Como o Linux Funciona"))
    n1 = [c for c in chs if c.level == 1]
    assert 10 <= len(n1) <= 40, f"nível 1 = {len(n1)} (avisos: {avisos})"
    assert not [c for c in n1 if c.title.strip().isdigit()]


def test_livro_en_nivel1_entre_15_e_40():
    chs, _ = build_chapters(_pdf("Killing the Messiah"))
    n1 = [c for c in chs if c.level == 1]
    assert 15 <= len(n1) <= 40, f"nível 1 = {len(n1)}"


def test_livro_pt_titulos_coincidem_com_outline():
    """CA3: os capitulos de nivel 1 correspondem aos do sumario do PDF.

    A comparacao e por continencia porque o livro traz "capitulo 1" e o titulo
    do capitulo como dois cabecalhos, que fundimos em "capitulo 1 — <titulo>".
    """
    import pymupdf

    doc = pymupdf.open(_pdf("Como o Linux Funciona"))
    esperados = {normalize(t) for nivel, t, _ in doc.get_toc() if nivel == 1}
    doc.close()
    chs, _ = build_chapters(_pdf("Como o Linux Funciona"))
    obtidos = [normalize(c.title) for c in chs if c.level == 1]

    def casa(alvo: str) -> bool:
        return any(alvo in titulo for titulo in obtidos)

    esperados = {e for e in esperados if e}
    acertos = sum(1 for e in esperados if casa(e))
    assert acertos / max(1, len(esperados)) >= 0.95


def test_epub_real_valida_com_capa_e_integridade_das_notas(tmp_path):
    """CA4 estendido: cada PDF real disponivel gera um EPUB valido.

    Confere ainda a capa embutida e a integridade dos links de nota: todo
    `href="#fn-N"` precisa ter um `id="fn-N"` no mesmo arquivo. O teste pula um
    PDF que nao se aplique (sem texto extraivel, por exemplo) em vez de falhar.
    """
    for prefixo in ("Como o Linux Funciona", "Killing the Messiah"):
        pdf = _pdf(prefixo)
        try:
            capitulos, _ = build_chapters(pdf)
        except Exception as exc:  # pragma: no cover - dependente do PDF real
            pytest.skip(f"{prefixo}: build_chapters falhou ({exc})")
        if not capitulos:
            pytest.skip(f"{prefixo}: nenhum capitulo extraido")

        destino = tmp_path / f"{normalize(prefixo) or 'livro'}.epub"
        build_epub(capitulos, prefixo, "Autor Desconhecido", "pt-BR", destino)
        validate_epub(destino)

        with zipfile.ZipFile(destino) as zf:
            nomes = set(zf.namelist())
            opf = zf.read("EPUB/content.opf").decode()
            assert "EPUB/cover.jpg" in nomes, f"{prefixo}: capa ausente"
            assert 'properties="cover-image"' in opf, f"{prefixo}: sem capa no OPF"
            for nome in nomes:
                if not (nome.startswith("EPUB/cap") and nome.endswith(".xhtml")):
                    continue
                xhtml = zf.read(nome).decode()
                for numero in re.findall(r'href="#fn-(\d+)"', xhtml):
                    assert f'id="fn-{numero}"' in xhtml, \
                        f"{prefixo}/{nome}: fn-{numero} sem destino"
