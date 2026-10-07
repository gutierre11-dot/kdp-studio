"""Testes de integracao da API (FastAPI TestClient)."""
from __future__ import annotations

import io
import re
import zipfile

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from tests.conftest import PAGES_3


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Cliente apontando output/ para um diretorio temporario."""
    monkeypatch.setattr(main, "OUTPUT_DIR", tmp_path)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def pdf_bytes(make_pdf, tmp_path):
    return make_pdf(PAGES_3).read_bytes()


def _convert(client, pdf_bytes, **data):
    payload = {"title": "Livro Teste", "author": "Autora",
               "format": "epub", "remove_header": "true",
               "remove_page_numbers": "true"}
    payload.update(data)
    return client.post("/api/convert",
                       files={"file": ("teste.pdf", pdf_bytes, "application/pdf")},
                       data=payload)


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/health").json() == {"ok": True}


def test_models(client):
    d = client.get("/api/models").json()
    assert "provider_ativo" in d
    assert d["provider_ativo"] in ("openai", "gemini", "offline")


def test_spa_servida(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "KDP" in r.text


def test_convert_e_download_por_indice_original(client, pdf_bytes):
    r = _convert(client, pdf_bytes)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["job_id"]
    assert d["format"] == "epub"
    assert [c["title"] for c in d["chapters"]] == [
        "Capítulo 1 - A Chegada", "Capítulo 2 - O Segredo",
        "Capítulo 3 - A Verdade"]

    # include=1 deve trazer SOMENTE o capitulo 2 (indice original)
    dl = client.get(f"/api/convert/{d['job_id']}/download",
                    params={"format": "epub", "include": "1"})
    assert dl.status_code == 200, dl.text
    assert dl.headers["content-type"] == "application/epub+zip"
    with zipfile.ZipFile(io.BytesIO(dl.content)) as z:
        xhtml = [n for n in z.namelist() if n.endswith(".xhtml")
                 and n.startswith("EPUB/cap")]
        assert len(xhtml) == 1
        conteudo = z.read(xhtml[0]).decode()
    assert "Capítulo 2 - O Segredo" in conteudo
    assert "Capítulo 1" not in conteudo


def test_convert_toggles_respeitados(client, pdf_bytes):
    com = _convert(client, pdf_bytes, remove_header="true",
                   remove_page_numbers="true").json()
    sem = _convert(client, pdf_bytes, remove_header="false",
                   remove_page_numbers="false").json()
    texto_com = " ".join(p for c in com["chapters"] for p in c["paragraphs"])
    texto_sem = " ".join(p for c in sem["chapters"] for p in c["paragraphs"])
    assert "LIVRO DE TESTE" not in texto_com
    assert "LIVRO DE TESTE" in texto_sem


def test_convert_formato_invalido(client, pdf_bytes):
    r = _convert(client, pdf_bytes, format="pdf")
    assert r.status_code == 400


def test_convert_arquivo_nao_pdf(client):
    r = client.post("/api/convert",
                    files={"file": ("x.pdf", b"nao sou pdf", "application/pdf")},
                    data={"title": "T", "author": "A"})
    assert r.status_code == 400


def test_limite_de_upload(client, pdf_bytes, monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 100)
    r = _convert(client, pdf_bytes)
    assert r.status_code == 413


def test_download_job_inexistente(client):
    assert client.get("/api/convert/naoexiste/download").status_code == 404


def test_download_formato_invalido(client, pdf_bytes):
    job = _convert(client, pdf_bytes).json()["job_id"]
    assert client.get(f"/api/convert/{job}/download",
                      params={"format": "pdf"}).status_code == 400


def test_translate_json_respeita_target(client):
    r = client.post("/api/translate", json={
        "chapters": [{"title": "Chapter", "level": 1, "paragraphs": ["Hello."]}],
        "target_lang": "en", "source_lang": "pt-BR"})
    assert r.status_code == 200
    d = r.json()
    assert d["target_lang"] == "en"
    assert "[en mock]" in d["translated_text"]


def test_translate_formdata_respeita_target(client):
    r = client.post("/api/translate", data={"text": "Olá mundo",
                                            "target_lang": "es",
                                            "source_lang": "pt-BR"})
    assert r.status_code == 200
    assert r.json()["translated_text"].startswith("[es mock]")


def test_translate_texto_vazio(client):
    assert client.post("/api/translate", data={"text": ""}).status_code == 400


def test_ebook_export_epub_nao_gera_irmaos(client, tmp_path):
    r = client.post("/api/ebook/export", json={
        "title": "Só EPUB", "author": "A", "format": "epub",
        "chapters": [{"title": "C1", "body": "Um.\n\nDois."}]})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/epub+zip"
    nomes = sorted(p.name for p in tmp_path.iterdir())
    assert len(nomes) == 1, f"arquivos orfaos gerados: {nomes}"
    assert nomes[0].endswith(".epub")


def test_ebook_export_formato_invalido(client):
    r = client.post("/api/ebook/export", json={
        "title": "X", "author": "A", "format": "pdf",
        "chapters": [{"title": "C1", "body": "oi"}]})
    assert r.status_code == 400


def test_ebook_export_sem_capitulos(client):
    r = client.post("/api/ebook/export", json={"title": "X", "chapters": []})
    assert r.status_code == 400


def test_ebook_outline_e_chapter_offline(client):
    r = client.post("/api/ebook/outline", json={
        "idea": "Uma história de teste", "genre": "romance",
        "style": "simples", "audience": "adultos", "num_chapters": 3})
    assert r.status_code == 200
    d = r.json()
    assert len(d["outline"]) == 3
    cap = client.post("/api/ebook/chapter", json={
        "title": "Livro", "chapter_title": "Cap 2", "chapter_number": 2,
        "chapter_synopsis": "sinopse"})
    assert cap.status_code == 200
    assert cap.json()["numero"] == 2
    assert cap.json()["body"]


def test_library_lista_e_remove(client, tmp_path):
    alvo = tmp_path / "arquivo.epub"
    alvo.write_bytes(b"conteudo")
    r = client.get("/api/library")
    assert r.status_code == 200
    assert any(i["id"] == "arquivo.epub" for i in r.json()["items"])

    assert client.delete("/api/library/arquivo.epub").status_code == 200
    assert not alvo.exists()

    assert client.delete("/api/library/arquivo.epub").status_code == 404
    assert client.delete("/api/library/segredo.txt").status_code == 400


def test_library_delete_rejeita_traversal(tmp_path, monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(main, "OUTPUT_DIR", tmp_path)
    for nome in ("..", "../.env", ".env", "sub/arquivo.epub", ""):
        with pytest.raises(HTTPException) as exc:
            main.library_delete(nome)
        assert exc.value.status_code == 400


def test_convert_traducao_toggle_on(client, pdf_bytes):
    d = _convert(client, pdf_bytes, translate="true", target_lang="en").json()
    assert d["translated"] is True
    assert d["target_lang"] == "en"
    texto = " ".join(p for c in d["chapters"] for p in c["paragraphs"])
    assert "[en mock]" in texto
    # EPUB do MESMO job já contém a tradução
    dl = client.get(f"/api/convert/{d['job_id']}/download", params={"format": "epub"})
    assert dl.status_code == 200, dl.text
    with zipfile.ZipFile(io.BytesIO(dl.content)) as z:
        conteudo = "".join(z.read(n).decode() for n in z.namelist()
                           if n.startswith("EPUB/cap"))
    assert "[en mock]" in conteudo


def test_convert_traducao_off_por_padrao(client, pdf_bytes):
    d = _convert(client, pdf_bytes).json()
    assert d["translated"] is False
    texto = " ".join(p for c in d["chapters"] for p in c["paragraphs"])
    assert "[pt-BR mock]" not in texto
    assert "[en mock]" not in texto


def test_convert_traducao_recusa_pdf_sem_texto(client, make_pdf):
    pdf = make_pdf([("", "")], header=None, footer_numbers=False).read_bytes()
    assert _convert(client, pdf, translate="true").status_code == 422


def test_translate_formdata_pdf_preserva_capitulos(client, pdf_bytes):
    r = client.post("/api/translate",
                    files={"file": ("teste.pdf", pdf_bytes, "application/pdf")},
                    data={"target_lang": "en", "source_lang": "pt-BR"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["chapters_traduzidos"]) >= 3
    assert any("[en mock]" in c["title"] for c in d["chapters_traduzidos"])


def test_convert_traducao_aceita_texto_com_frase_placeholder(client, make_pdf):
    # Texto legítimo contendo "sem conteúdo" NÃO deve ser confundido com o
    # placeholder exato "(sem conteúdo)".
    pdf = make_pdf([("Capítulo Único",
                     "Este trecho fala de sem conteúdo de forma legítima.")]).read_bytes()
    r = _convert(client, pdf, translate="true", target_lang="en")
    assert r.status_code == 200, r.text
    texto = " ".join(p for c in r.json()["chapters"] for p in c["paragraphs"])
    assert "[en mock]" in texto


def test_translate_formdata_export_gera_epub(client, tmp_path):
    r = client.post("/api/translate",
                    data={"text": "Olá mundo", "source_lang": "pt-BR",
                          "target_lang": "en", "export": "true",
                          "format": "epub", "title": "Livro Trad",
                          "author": "Autora"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["export"] is True and d["job_id"]
    assert d["epub"].startswith("/download/") and d["epub"].endswith(".epub")
    epub_file = tmp_path / d["epub"].split("/")[-1]
    assert epub_file.exists(), "EPUB não gerado"
    with zipfile.ZipFile(epub_file) as z:
        assert "mimetype" in z.namelist()
        xhtml = "".join(z.read(n).decode(errors="ignore")
                        for n in z.namelist() if n.endswith(".xhtml"))
    assert "[en mock]" in xhtml
    # o mesmo job permite reexportar
    dl = client.get(f"/api/convert/{d['job_id']}/download",
                    params={"format": "epub"})
    assert dl.status_code == 200, dl.text


def test_translate_sem_export_nao_gera_job(client):
    d = client.post("/api/translate",
                    data={"text": "Olá", "target_lang": "en"}).json()
    assert not d.get("job_id")
    assert "epub" not in d


def test_translate_pdf_export_gera_epub_traduzido(client, pdf_bytes, tmp_path):
    r = client.post("/api/translate",
                    files={"file": ("livro.pdf", pdf_bytes, "application/pdf")},
                    data={"source_lang": "pt-BR", "target_lang": "en",
                          "export": "true", "title": "Livro EN",
                          "author": "Autora"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["export"] is True and d["job_id"]
    # estrutura de capítulos do PDF preservada e traduzida
    assert len(d["chapters_traduzidos"]) >= 3
    assert any("[en mock]" in c["title"] for c in d["chapters_traduzidos"])
    epub_file = tmp_path / d["epub"].split("/")[-1]
    assert epub_file.exists(), "EPUB não gerado a partir do PDF"
    with zipfile.ZipFile(epub_file) as z:
        xhtml = "".join(z.read(n).decode(errors="ignore")
                        for n in z.namelist() if n.endswith(".xhtml"))
    assert "[en mock]" in xhtml


def test_translate_pdf_sem_texto_recusa(client, make_pdf):
    """R4: PDF escaneado + export/translate ligado não pode virar EPUB vazio."""
    pdf = make_pdf([("", "")], header=None, footer_numbers=False,
                   name="escaneado.pdf").read_bytes()
    com_export = client.post(
        "/api/translate",
        files={"file": ("escaneado.pdf", pdf, "application/pdf")},
        data={"target_lang": "en", "export": "true",
              "title": "T", "author": "A"})
    assert com_export.status_code == 422, com_export.text
    assert "sem texto" in com_export.json()["detail"]
    sem_export = client.post(
        "/api/translate",
        files={"file": ("escaneado.pdf", pdf, "application/pdf")},
        data={"target_lang": "en"})
    assert sem_export.status_code == 422, sem_export.text


def test_translate_pdf_texto_com_frase_placeholder_aceito(client, make_pdf):
    """R4: match EXATO — texto legítimo com "sem conteúdo" passa (200)."""
    pdf = make_pdf([("Capítulo Único",
                     "Este trecho fala de sem conteúdo de forma legítima.")],
                   name="legit.pdf").read_bytes()
    r = client.post("/api/translate",
                    files={"file": ("legit.pdf", pdf, "application/pdf")},
                    data={"target_lang": "en", "export": "true",
                          "title": "Legítimo", "author": "Autora"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["export"] is True and d["job_id"]
    assert any("[en mock]" in p
               for c in d["chapters_traduzidos"] for p in c["paragraphs"])


def test_translate_export_formato_invalido(client):
    r = client.post("/api/translate",
                    data={"text": "Olá", "target_lang": "en",
                          "export": "true", "format": "docx"})
    assert r.status_code == 400, r.text


def test_translate_export_gera_apenas_epub(client, tmp_path):
    r = client.post("/api/translate",
                    data={"text": "Olá mundo", "source_lang": "pt-BR",
                          "target_lang": "en", "export": "true",
                          "format": "epub", "title": "Só EPUB",
                          "author": "Autora"})
    assert r.status_code == 200, r.text
    d = r.json()
    arquivos = sorted(p.name for p in tmp_path.iterdir())
    assert arquivos == [d["files"][0]], f"arquivos irmãos órfãos: {arquivos}"
    assert arquivos[0].endswith(".epub")


def test_translate_json_export_gera_epub(client, tmp_path):
    r = client.post("/api/translate", json={
        "chapters": [{"title": "Chapter", "level": 1,
                      "paragraphs": ["Hello."]}],
        "source_lang": "en", "target_lang": "pt-BR",
        "export": True, "format": "epub",
        "title": "Livro JSON", "author": "Autor"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["job_id"] and d["export"] is True and d["format"] == "epub"
    epub_file = tmp_path / d["epub"].split("/")[-1]
    assert epub_file.exists()
    with zipfile.ZipFile(epub_file) as z:
        xhtml = "".join(z.read(n).decode(errors="ignore")
                        for n in z.namelist() if n.endswith(".xhtml"))
    assert "[pt-BR mock]" in xhtml


def test_translate_json_sem_texto_export_recusa(client):
    r = client.post("/api/translate", json={
        "chapters": [{"title": "Texto", "level": 1,
                      "paragraphs": ["(PDF sem texto extraivel.)"]}],
        "target_lang": "en", "export": True})
    assert r.status_code == 422, r.text


def test_translate_json_capitulos_com_body_e_export(client):
    # A guarda não pode confundir capítulos no formato {title, body}.
    r = client.post("/api/translate", json={
        "chapters": [{"title": "C1", "body": "Olá mundo"}],
        "target_lang": "en", "export": True, "title": "T", "author": "A"})
    assert r.status_code == 200, r.text
    assert r.json()["job_id"]


def test_frontend_toggle_traducao_e_accept_pdf():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "static"
            / "index.html").read_text(encoding="utf-8")
    # R1: toggle da aba Converter começa DESLIGADO (sem a classe `on`).
    cls = re.search(r'<span id="tg-translate" class="([^"]*)"', html).group(1)
    assert "toggle" in cls.split()
    assert "on" not in cls.split()
    # R3/critério 3: a aba Traduzir aceita .pdf.
    accept = re.search(r'<input id="file-translate"[^>]*accept="([^"]+)"',
                       html).group(1)
    assert ".pdf" in accept
    # R1/R3: toggles de export/tradução usam o componente .toggle.
    assert re.search(r'<span id="tg-tr-export" class="toggle"', html)
    assert re.search(r'<button id="btn-tr-dl-epub"[^>]*class="hidden', html)
