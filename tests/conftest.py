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
    """Impede que os testes criem clientes de LLM reais (custo/rede).

    Qualquer tentativa de montar um cliente vira um erro explicito em vez de
    uma requisicao de rede.
    """
    def _sem_rede(*args, **kwargs):
        raise RuntimeError("teste tentou criar um cliente de LLM real")

    monkeypatch.setattr("backend.app.llm.make_client", _sem_rede, raising=False)
    yield


# Chaves de IA que, se presentes no ambiente do desenvolvedor, mudariam o
# provider ativo e o resultado dos testes.
_ENV_IA = ("LLM_PROVIDER", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
           "GEMINI_API_KEY", "TRANSLATION_MODEL")


@pytest.fixture(autouse=True)
def ambiente_sem_ia(monkeypatch):
    """Neutraliza o `.env` real: a suite nao pode depender de segredos locais.

    Sem isto, a mesma revisao passa numa maquina sem chave e falha em outra
    configurada. Testes que precisam de um provider ligam a chave que querem.
    """
    from backend.app import config, llm

    for k in _ENV_IA:
        monkeypatch.delenv(k, raising=False)
    config.get_settings.cache_clear()
    llm.reset_model_cache()
    yield
    config.get_settings.cache_clear()
    llm.reset_model_cache()


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
def client(tmp_path, monkeypatch, settings):
    """Cliente FastAPI com output/ e JobStore isolados por teste."""
    from fastapi.testclient import TestClient

    from backend.app import main
    from backend.app.jobs import JobStore

    monkeypatch.setattr(main, "store", JobStore(settings(output_dir=tmp_path)))
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def pdf_bytes(make_pdf):
    return make_pdf(PAGES_3).read_bytes()


@pytest.fixture
def pdf_com_nota_bytes(tmp_path):
    """PDF de uma página com chamador sobrescrito no corpo e nota no pé.

    `insert_htmlbox` é usado de propósito: só ele emite o span de `<sup>1</sup>`
    com a flag de superscript de que a extração deriva o chamador de nota.
    """
    import pymupdf

    largura, altura = 595, 842
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=largura, height=altura)
        page.insert_text((72, 90), "Capítulo Um", fontsize=20, fontname="hebo")
        page.insert_htmlbox(
            pymupdf.Rect(72, 150, largura - 72, altura * 0.7),
            "<p>Corpo com chamador<sup>1</sup> aqui.</p>",
            css="p { font-size: 16px; }")
        page.insert_text((72, altura * 0.85), "1 Nota de teste.",
                         fontsize=10, fontname="helv")
        doc.set_toc([[1, "Capítulo Um", 1]])
        caminho = tmp_path / "com-nota.pdf"
        doc.save(str(caminho))
    finally:
        doc.close()
    return caminho.read_bytes()


@pytest.fixture
def capa_png():
    """PNG pequeno e real, para os testes de upload de capa."""
    import pymupdf

    doc = pymupdf.open()
    try:
        page = doc.new_page(width=100, height=160)
        page.draw_rect(pymupdf.Rect(0, 0, 100, 160), color=None,
                       fill=(0.2, 0.3, 0.5))
        return page.get_pixmap(matrix=pymupdf.Matrix(1, 1)).tobytes("png")
    finally:
        doc.close()


@pytest.fixture
def capa_jpg():
    """JPEG pequeno e real, para os testes de upload de capa."""
    import pymupdf

    doc = pymupdf.open()
    try:
        page = doc.new_page(width=100, height=160)
        page.draw_rect(pymupdf.Rect(0, 0, 100, 160), color=None,
                       fill=(0.5, 0.2, 0.2))
        return page.get_pixmap(matrix=pymupdf.Matrix(1, 1)).tobytes("jpeg")
    finally:
        doc.close()


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

