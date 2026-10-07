"""Testes de integracao da API (FastAPI TestClient)."""
from __future__ import annotations

import time
import zipfile
from dataclasses import replace

from backend.app import main
from backend.app.kdp_epub import validate_epub


def _criar(client, pdf_bytes, **data):
    payload = {"title": "Livro Teste", "author": "Autora"}
    payload.update(data)
    return client.post("/api/jobs",
                       files={"file": ("teste.pdf", pdf_bytes,
                                       "application/pdf")},
                       data=payload)


def _estado(client, job_id, limite=15.0):
    fim = time.time() + limite
    while time.time() < fim:
        resposta = client.get(f"/api/jobs/{job_id}")
        assert resposta.status_code == 200
        corpo = resposta.json()
        if corpo["status"] in ("done", "error", "cancelled"):
            return corpo
        time.sleep(0.05)
    raise AssertionError("job não terminou a tempo")


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_config_endpoint(client):
    corpo = client.get("/api/config").json()
    assert corpo["provider"] in ("openai", "gemini", "offline")
    assert isinstance(corpo["fallback_models"], list)
    assert corpo["max_upload_mb"] > 0
    assert corpo["chunk_chars"] > 0
    assert corpo["workers"] > 0
    assert isinstance(corpo["languages"], dict)


def test_criar_job_e_acompanhar(client, pdf_bytes):
    resposta = _criar(client, pdf_bytes)
    assert resposta.status_code == 201
    job_id = resposta.json()["job_id"]
    assert job_id

    estado = _estado(client, job_id)
    assert estado["status"] == "done"
    assert estado["progress"] == 100
    assert estado["chapters"]
    assert estado["title"] == "Livro Teste"
    # a lista de capitulos nao carrega o texto completo
    assert "paragraphs" not in estado["chapters"][0]
    assert {"index", "title", "level", "words", "preview", "included"} <= set(
        estado["chapters"][0])


def test_detalhe_de_capitulo_traz_paragrafos(client, pdf_bytes):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    _estado(client, job_id)
    detalhe = client.get(f"/api/jobs/{job_id}/chapters/0").json()
    assert detalhe["index"] == 0
    assert detalhe["title"]
    assert detalhe["paragraphs"]
    assert isinstance(detalhe["paragraphs"][0], str)


def test_export_gera_epub_valido(client, pdf_bytes, tmp_path):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    _estado(client, job_id)
    resposta = client.post(f"/api/jobs/{job_id}/export", json={})
    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "application/epub+zip"
    arquivo = tmp_path / "baixado.epub"
    arquivo.write_bytes(resposta.content)
    validate_epub(arquivo)


def test_export_com_edicao_de_titulo_e_exclusao(client, pdf_bytes, tmp_path):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    estado = _estado(client, job_id)
    chapters = estado["chapters"]
    assert len(chapters) >= 2
    payload = {"chapters": [
        {"index": c["index"], "title": "NOVO " + c["title"],
         "included": c["index"] != 0}
        for c in chapters
    ]}
    resposta = client.post(f"/api/jobs/{job_id}/export", json=payload)
    assert resposta.status_code == 200
    arquivo = tmp_path / "editado.epub"
    arquivo.write_bytes(resposta.content)
    validate_epub(arquivo)
    with zipfile.ZipFile(arquivo) as zf:
        juntos = b"".join(zf.read(n) for n in zf.namelist()
                          if n.startswith("EPUB/cap")).decode()
    assert "NOVO" in juntos
    # o capitulo excluido nao entra no EPUB
    assert ("NOVO " + chapters[0]["title"]) not in juntos


def test_export_com_texto_editado(client, pdf_bytes, tmp_path):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    _estado(client, job_id)
    payload = {"edit": {"0": ["Parágrafo totalmente reescrito."]}}
    resposta = client.post(f"/api/jobs/{job_id}/export", json=payload)
    assert resposta.status_code == 200
    arquivo = tmp_path / "texto.epub"
    arquivo.write_bytes(resposta.content)
    with zipfile.ZipFile(arquivo) as zf:
        cap1 = zf.read("EPUB/cap1.xhtml").decode()
    assert "Parágrafo totalmente reescrito." in cap1


def test_job_inexistente_404(client):
    assert client.get("/api/jobs/naoexiste").status_code == 404
    assert client.get("/api/jobs/naoexiste/chapters/0").status_code == 404
    assert client.post("/api/jobs/naoexiste/export", json={}).status_code == 404
    assert client.post("/api/jobs/naoexiste/cancel").status_code == 404
    assert client.delete("/api/jobs/naoexiste").status_code == 404


def test_arquivo_nao_pdf_400(client):
    resposta = client.post("/api/jobs",
                           files={"file": ("a.txt", b"nao sou pdf", "text/plain")},
                           data={"title": "X", "author": "Y"})
    assert resposta.status_code == 400


def test_upload_grande_413(client, pdf_bytes, monkeypatch):
    monkeypatch.setattr(main, "settings",
                        replace(main.settings, max_upload_bytes=10))
    resposta = _criar(client, pdf_bytes)
    assert resposta.status_code == 413


def test_pdf_sem_texto_422(client, make_pdf):
    vazio = make_pdf([("", "")], header=None, footer_numbers=False)
    resposta = client.post("/api/jobs",
                           files={"file": ("vazio.pdf", vazio.read_bytes(),
                                           "application/pdf")},
                           data={"title": "X", "author": "Y"})
    assert resposta.status_code == 422
    detalhe = resposta.json()["detail"].lower()
    assert "extra" in detalhe


def test_traducao_sem_chave_400(client, pdf_bytes, monkeypatch):
    monkeypatch.setattr(main, "is_configured", lambda: False)
    resposta = _criar(client, pdf_bytes, translate="true")
    assert resposta.status_code == 400
    assert "chave" in resposta.json()["detail"].lower()


def test_cancelar_job(client, pdf_bytes):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    _estado(client, job_id)
    resposta = client.post(f"/api/jobs/{job_id}/cancel")
    assert resposta.status_code == 200
    assert resposta.json()["ok"] is True


def test_deletar_job(client, pdf_bytes):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    _estado(client, job_id)
    assert client.delete(f"/api/jobs/{job_id}").json()["ok"] is True
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_spa_servida(client):
    resposta = client.get("/")
    assert resposta.status_code == 200
    assert "text/html" in resposta.headers["content-type"]


def test_upload_nao_vaza_file_descriptor(client, pdf_bytes):
    """O fd do mkstemp precisa ser fechado, senao vaza um por upload."""
    import os

    def abertos() -> int:
        return len(os.listdir("/proc/self/fd"))

    antes = abertos()
    for _ in range(5):
        assert _criar(client, pdf_bytes).status_code == 201
    depois = abertos()
    assert depois <= antes + 3, f"fds: {antes} -> {depois}"


def test_export_bloqueado_durante_traducao(client, pdf_bytes):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    main.store.update(job_id, status="translating")
    resposta = client.post(f"/api/jobs/{job_id}/export", json={})
    assert resposta.status_code == 409
    assert "traduzido" in resposta.json()["detail"] or \
           "traduzindo" in resposta.json()["detail"]
