"""Fixtures compartilhadas dos testes do KDP Studio."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Impede que os testes chamem APIs de LLM reais (custo/rede).

    Forca o modo offline em todos os modulos que consultam provider e torna
    qualquer chamada de rede um erro explicito em vez de uma requisicao.
    """
    def _sem_rede(*args, **kwargs):
        raise RuntimeError("teste tentou criar um cliente de LLM real")

    monkeypatch.setattr("backend.app.llm.make_client", _sem_rede, raising=False)
    monkeypatch.setattr("backend.app.translator.llm_available", lambda: False,
                        raising=False)
    monkeypatch.setattr("backend.app.creator.llm_available", lambda: False,
                        raising=False)
    monkeypatch.setattr("backend.app.cover.openai_configured", lambda: False,
                        raising=False)
    yield


def _wrap(text: str, width: int) -> list[str]:
    """Quebra o texto em linhas de ate `width` chars, sempre em fim de palavra.

    PDFs reais quebram linhas em espacos (ou com hifen); quebrar no meio de uma
    palavra seria um artefato do teste.
    """
    linhas: list[str] = []
    atual = ""
    for palavra in text.split():
        cand = palavra if not atual else f"{atual} {palavra}"
        if len(cand) <= width:
            atual = cand
        else:
            if atual:
                linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas or [""]


@pytest.fixture
def make_pdf(tmp_path):
    """Cria um PDF de teste com titulos, corpo, header e numeracao repetidos."""
    import pymupdf

    def _make(pages, header: str | None = "LIVRO DE TESTE",
              footer_numbers: bool = True, name: str = "book.pdf") -> Path:
        doc = pymupdf.open()
        for i, (title, body) in enumerate(pages):
            page = doc.new_page()
            y = 90
            if title:
                page.insert_text((72, y), title, fontsize=22, fontname="helv")
                y = 150
            for line in _wrap(body, 70):
                page.insert_text((72, y), line, fontsize=12)
                y += 20
            if header:
                page.insert_text((72, 40), header, fontsize=9)
            if footer_numbers:
                page.insert_text((300, 780), str(i + 1), fontsize=10)
        out = tmp_path / name
        doc.save(str(out))
        doc.close()
        return out

    return _make


PAGES_3 = [
    ("Capítulo 1 - A Chegada",
     "O trem chegou atrasado naquela manhã fria. Helena desceu devagar, "
     "olhando a plataforma vazia e o céu cinzento."),
    ("Capítulo 2 - O Segredo",
     "A carta estava escondida no fundo da gaveta. Ninguém imaginava o que "
     "ela revelaria naquela noite."),
    ("Capítulo 3 - A Verdade",
     "Tudo veio à tona durante a tempestade, entre relâmpagos e silêncios "
     "que ninguém ousava quebrar."),
]


@pytest.fixture
def settings():
    """Fabrica de `Settings` com overrides (usa dataclasses.replace)."""
    from dataclasses import replace

    from backend.app.config import get_settings

    base = get_settings()

    def _settings(**overrides):
        return replace(base, **overrides)

    return _settings


@pytest.fixture
def make_bookmark_pdf(tmp_path):
    """PDF de 2 páginas cujos títulos têm bookmarks correspondentes."""
    import pymupdf

    doc = pymupdf.open()
    for titulo, corpo in (("Capítulo Um", "primeiro corpo do texto"),
                          ("Capítulo Dois", "segundo corpo do texto")):
        page = doc.new_page()
        page.insert_text((72, 90), titulo, fontsize=20, fontname="helv")
        page.insert_text((72, 150), corpo, fontsize=12, fontname="helv")
    doc.set_toc([[1, "Capítulo Um", 1], [1, "Capítulo Dois", 2]])
    out = tmp_path / "bookmarks.pdf"
    doc.save(str(out))
    doc.close()
    return out

