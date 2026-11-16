"""Testes de integracao da API (FastAPI TestClient)."""
from __future__ import annotations

import time
import zipfile
from dataclasses import replace

import pytest

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
    # A fixture autouse `ambiente_sem_ia` remove as chaves do .env real, entao
    # aqui o esperado e offline.
    corpo = client.get("/api/config").json()
    assert corpo["provider"] == "offline"
    assert corpo["configured"] is False
    assert corpo["translation_model"] == ""
    assert corpo["fallback_models"] == []
    assert corpo["max_upload_mb"] > 0
    assert corpo["chunk_chars"] > 0
    assert corpo["workers"] > 0
    assert isinstance(corpo["languages"], dict)


def test_config_endpoint_reconhece_deepseek(client, monkeypatch):
    """DeepSeek e o provider recomendado e deve ser reportado como ativo."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "chave-de-teste")
    corpo = client.get("/api/config").json()
    assert corpo["provider"] == "deepseek"
    assert corpo["configured"] is True
    assert corpo["translation_model"] == "deepseek-flash"
    assert corpo["fallback_models"] == ["deepseek-v4-pro"]


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
    detalhe = resposta.json()["detail"]
    assert "chave" in detalhe.lower()
    # O DeepSeek e o provider recomendado: a mensagem precisa cita-lo, senao
    # manda o usuario configurar uma chave que nao e a preferida do projeto.
    assert "DEEPSEEK_API_KEY" in detalhe


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


# ---------------------------------------------------------------------------
# Capa
# ---------------------------------------------------------------------------

def test_capa_procedural_por_padrao(client, pdf_bytes):
    """Sem upload, o job anuncia capa procedural e serve um JPEG de verdade."""
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    _estado(client, job_id)

    assert client.get(f"/api/jobs/{job_id}").json()["cover"] == {
        "kind": "procedural", "name": None, "bytes": 0,
        "width": 1600, "height": 2560, "aspect_ok": True, "hint": ""}

    previa = client.get(f"/api/jobs/{job_id}/cover")
    assert previa.status_code == 200
    assert previa.headers["content-type"] == "image/jpeg"
    assert previa.content[:3] == b"\xff\xd8\xff"
    # Capa KDP de referencia: 1600x2560 (proporcao 1:1.6).
    import pymupdf

    pix = pymupdf.Pixmap(previa.content)
    assert (pix.width, pix.height) == (1600, 2560)


@pytest.mark.parametrize("fixture_nome,extensao,media", [
    ("capa_png", "png", "image/png"),
    ("capa_jpg", "jpg", "image/jpeg"),
])
def test_upload_de_capa_e_previa(client, pdf_bytes, request, fixture_nome,
                                 extensao, media):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    _estado(client, job_id)
    capa = request.getfixturevalue(fixture_nome)

    resposta = client.post(f"/api/jobs/{job_id}/cover",
                           files={"file": (f"minha-capa.{extensao}", capa, media)})
    assert resposta.status_code == 200
    info = resposta.json()["cover"]
    assert info["kind"] == "upload"
    assert info["name"] == f"minha-capa.{extensao}"
    assert info["bytes"] == len(capa)

    # A previa serve exatamente os bytes enviados (mesma imagem do EPUB).
    previa = client.get(f"/api/jobs/{job_id}/cover")
    assert previa.headers["content-type"] == media
    assert previa.content == capa

    assert client.get(f"/api/jobs/{job_id}").json()["cover"]["kind"] == "upload"


def test_capa_sem_extensao_ganha_a_extensao_real(client, pdf_bytes, capa_png):
    """O nome exibido precisa carregar o formato, senão a prévia mente o tipo."""
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    resposta = client.post(f"/api/jobs/{job_id}/cover",
                           files={"file": ("minha-capa", capa_png, "image/png")})
    assert resposta.status_code == 200
    assert resposta.json()["cover"]["name"] == "minha-capa.png"

    previa = client.get(f"/api/jobs/{job_id}/cover")
    assert previa.headers["content-type"] == "image/png"


def test_capa_formato_invalido_400(client, pdf_bytes):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    resposta = client.post(
        f"/api/jobs/{job_id}/cover",
        files={"file": ("capa.pdf", b"%PDF-1.4 nao sou imagem", "application/pdf")})
    assert resposta.status_code == 400
    assert "JPEG" in resposta.json()["detail"] or "PNG" in resposta.json()["detail"]
    # A capa anterior (procedural) continua valendo.
    assert client.get(f"/api/jobs/{job_id}").json()["cover"]["kind"] == "procedural"


def test_capa_acima_do_limite_413(client, pdf_bytes, capa_png, monkeypatch):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    monkeypatch.setattr(main, "settings",
                        replace(main.settings, max_cover_bytes=10))
    resposta = client.post(f"/api/jobs/{job_id}/cover",
                           files={"file": ("capa.png", capa_png, "image/png")})
    assert resposta.status_code == 413


def test_remover_capa_volta_para_procedural(client, pdf_bytes, capa_png):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    client.post(f"/api/jobs/{job_id}/cover",
                files={"file": ("capa.png", capa_png, "image/png")})
    assert client.get(f"/api/jobs/{job_id}").json()["cover"]["kind"] == "upload"

    resposta = client.delete(f"/api/jobs/{job_id}/cover")
    assert resposta.status_code == 200
    assert resposta.json()["cover"]["kind"] == "procedural"
    assert client.get(f"/api/jobs/{job_id}").json()["cover"]["kind"] == "procedural"


def test_capa_em_job_inexistente_404(client, capa_png):
    assert client.get("/api/jobs/naoexiste/cover").status_code == 404
    assert client.post("/api/jobs/naoexiste/cover",
                       files={"file": ("c.png", capa_png, "image/png")}
                       ).status_code == 404
    assert client.delete("/api/jobs/naoexiste/cover").status_code == 404


def test_export_usa_a_capa_enviada(client, pdf_bytes, capa_png, tmp_path):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    _estado(client, job_id)
    client.post(f"/api/jobs/{job_id}/cover",
                files={"file": ("capa.png", capa_png, "image/png")})

    resposta = client.post(f"/api/jobs/{job_id}/export", json={})
    assert resposta.status_code == 200
    arquivo = tmp_path / "com-capa.epub"
    arquivo.write_bytes(resposta.content)
    validate_epub(arquivo)

    with zipfile.ZipFile(arquivo) as zf:
        nomes = set(zf.namelist())
        opf = zf.read("EPUB/content.opf").decode()
        assert "EPUB/cover.png" in nomes
        assert zf.read("EPUB/cover.png") == capa_png
    assert 'properties="cover-image"' in opf


def test_export_sem_capa(client, pdf_bytes, tmp_path):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    _estado(client, job_id)
    resposta = client.post(f"/api/jobs/{job_id}/export", json={"cover": False})
    assert resposta.status_code == 200
    arquivo = tmp_path / "sem-capa.epub"
    arquivo.write_bytes(resposta.content)
    validate_epub(arquivo)

    with zipfile.ZipFile(arquivo) as zf:
        nomes = set(zf.namelist())
        opf = zf.read("EPUB/content.opf").decode()
    assert "EPUB/cover.jpg" not in nomes
    assert "EPUB/cover.png" not in nomes
    assert "capa.xhtml" not in opf
    assert 'properties="cover-image"' not in opf


# ---------------------------------------------------------------------------
# Notas de rodape e metadados
# ---------------------------------------------------------------------------

def test_capitulo_traz_notas_e_contagem(client, pdf_com_nota_bytes):
    resposta = client.post(
        "/api/jobs",
        files={"file": ("notas.pdf", pdf_com_nota_bytes, "application/pdf")},
        data={"title": "Livro com Notas", "author": "Autora"})
    assert resposta.status_code == 201
    job_id = resposta.json()["job_id"]
    estado = _estado(client, job_id)

    capitulo = estado["chapters"][0]
    assert capitulo["notes_count"] == 1

    detalhe = client.get(f"/api/jobs/{job_id}/chapters/0").json()
    assert detalhe["notes"] == [[1, "Nota de teste."]]
    assert detalhe["paragraphs"]
    assert isinstance(detalhe["title_refs"], list)


def test_chamador_de_nota_vem_como_token_no_texto_editavel(client,
                                                          pdf_com_nota_bytes):
    """O texto do editor expõe o chamador como ⟦1⟧, não como dígito solto."""
    job_id = _criar(client, pdf_com_nota_bytes, title="Notas").json()["job_id"]
    detalhe = client.get(f"/api/jobs/{job_id}/chapters/0").json()
    corpo = " ".join(detalhe["paragraphs"])
    assert "⟦1⟧" in corpo


def test_edicao_preserva_o_link_da_nota(client, pdf_com_nota_bytes, tmp_path):
    """Salvar o texto editado não pode degradar o chamador a dígito solto.

    Sem o token, o chamador virava texto comum e a nota ficava órfã: presente
    como endnote, mas sem nenhum link apontando para ela.
    """
    job_id = _criar(client, pdf_com_nota_bytes, title="Notas").json()["job_id"]
    detalhe = client.get(f"/api/jobs/{job_id}/chapters/0").json()
    # O autor corrige o texto e mantém o chamador no lugar (como a interface
    # orienta a fazer).
    corrigido = [p.replace("Corpo com chamador", "Corpo corrigido com chamador")
                 for p in detalhe["paragraphs"]]

    resposta = client.post(f"/api/jobs/{job_id}/export",
                           json={"edit": {"0": corrigido}})
    assert resposta.status_code == 200
    arquivo = tmp_path / "nota-editada.epub"
    arquivo.write_bytes(resposta.content)
    validate_epub(arquivo)

    with zipfile.ZipFile(arquivo) as zf:
        cap1 = zf.read("EPUB/cap1.xhtml").decode()
    assert "Corpo corrigido com chamador" in cap1
    assert 'href="#fn-1"' in cap1, "o chamador perdeu o link da nota"
    assert 'id="fn-1"' in cap1
    assert 'href="#fnref-1"' in cap1, "a nota perdeu o backlink"


def test_edicao_pode_remover_o_chamador(client, pdf_com_nota_bytes, tmp_path):
    """Sem o token, a nota continua no fim do capítulo — só não tem link."""
    job_id = _criar(client, pdf_com_nota_bytes, title="Notas").json()["job_id"]
    resposta = client.post(
        f"/api/jobs/{job_id}/export",
        json={"edit": {"0": ["Texto sem chamador nenhum."]}})
    assert resposta.status_code == 200
    arquivo = tmp_path / "sem-chamador.epub"
    arquivo.write_bytes(resposta.content)
    validate_epub(arquivo)
    with zipfile.ZipFile(arquivo) as zf:
        cap1 = zf.read("EPUB/cap1.xhtml").decode()
    assert "Texto sem chamador nenhum." in cap1
    assert 'id="fn-1"' in cap1        # a nota não some
    assert 'href="#fn-1"' not in cap1  # mas não há link quebrado para lugar nenhum


def test_sem_notas_a_lista_vem_vazia(client, pdf_bytes):
    job_id = _criar(client, pdf_bytes).json()["job_id"]
    estado = _estado(client, job_id)
    assert estado["chapters"][0]["notes_count"] == 0
    detalhe = client.get(f"/api/jobs/{job_id}/chapters/0").json()
    assert detalhe["notes"] == []


def test_descricao_e_editora_entram_no_epub(client, pdf_bytes, tmp_path):
    job_id = _criar(client, pdf_bytes,
                    description="Uma sinopse curta para a loja.",
                    publisher="Editora Independente").json()["job_id"]
    estado = _estado(client, job_id)
    assert estado["description"] == "Uma sinopse curta para a loja."
    assert estado["publisher"] == "Editora Independente"

    resposta = client.post(f"/api/jobs/{job_id}/export", json={})
    assert resposta.status_code == 200
    arquivo = tmp_path / "metadados.epub"
    arquivo.write_bytes(resposta.content)
    validate_epub(arquivo)

    with zipfile.ZipFile(arquivo) as zf:
        opf = zf.read("EPUB/content.opf").decode()
    assert "Uma sinopse curta para a loja." in opf
    assert "Editora Independente" in opf


def test_descricao_longa_400(client, pdf_bytes):
    resposta = _criar(client, pdf_bytes, description="x" * (main.MAX_DESCRICAO + 1))
    assert resposta.status_code == 400
    assert "descri" in resposta.json()["detail"].lower()


def test_editora_longa_400(client, pdf_bytes):
    resposta = _criar(client, pdf_bytes, publisher="x" * (main.MAX_EDITORA + 1))
    assert resposta.status_code == 400
    assert "editora" in resposta.json()["detail"].lower()


def test_config_expoe_limite_da_capa(client):
    corpo = client.get("/api/config").json()
    assert corpo["max_cover_mb"] > 0
