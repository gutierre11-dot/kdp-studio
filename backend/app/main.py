"""API do KDP Studio: PDF -> capitulos -> (traducao) -> EPUB KDP.

Fluxo de um job:
  POST /api/jobs            valida e le o PDF, extrai os capitulos e devolve
                            `job_id`; se houver traducao, ela roda em
                            background com progresso real.
  GET  /api/jobs/{id}       status/progresso + metadados dos capitulos.
  GET  /api/jobs/{id}/chapters/{i}   texto completo de um capitulo.
  POST /api/jobs/{id}/export         gera o EPUB (aplicando edicoes).
  POST /api/jobs/{id}/cancel         cancela a traducao em andamento.
  DELETE /api/jobs/{id}              descarta o job e seus artefatos.

A extracao roda na propria requisicao (e rapida: ~4s para 417 paginas) porque
e ela que decide entre 422 (PDF sem texto) e um job valido. A traducao, que e
longa, roda em background.
"""
from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import kdp_epub, pdf_chapters, translate
from .config import get_settings
from .jobs import JobStore
from .llm import is_configured, model_candidates, provider_name
from .models import Chapter, JobState, Paragraph
from .translate import DEFAULT_SOURCE_LANG, DEFAULT_TARGET_LANG, LANG_NAMES

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]  # kdp-studio/
FRONTEND_DIR = BASE_DIR / "static"
PDF_MAGIC = b"%PDF"
PLACEHOLDERS = {"(PDF sem texto extraivel.)", "(sem conteúdo)"}
SEM_TEXTO = ("PDF sem texto extraível: não há o que converter "
             "(OCR de PDFs escaneados não é suportado).")

settings = get_settings()
store = JobStore(settings)

app = FastAPI(title="KDP Studio API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

Path(settings.output_dir).mkdir(parents=True, exist_ok=True)
app.mount("/download", StaticFiles(directory=str(settings.output_dir)),
          name="download")


# ---------------------------------------------------------------------------
# Utilitarios
# ---------------------------------------------------------------------------

def _as_bool(valor: Any, default: bool = False) -> bool:
    if valor is None or valor == "":
        return default
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in ("1", "true", "on", "yes", "sim")


def _texto(valor: Any, default: str = "") -> str:
    if valor in (None, "null", ""):
        return default
    return str(valor)


async def _ler_upload(arquivo: UploadFile) -> bytes:
    """Le o upload em blocos, respeitando MAX_UPLOAD_MB."""
    pedacos: list[bytes] = []
    total = 0
    while True:
        pedaco = await arquivo.read(1024 * 1024)
        if not pedaco:
            break
        total += len(pedaco)
        if total > settings.max_upload_bytes:
            limite = settings.max_upload_bytes // (1024 * 1024)
            raise HTTPException(413, f"arquivo maior que o limite de {limite} MB")
        pedacos.append(pedaco)
    if not total:
        raise HTTPException(400, "arquivo vazio")
    return b"".join(pedacos)


def _tem_texto(capitulos: list[Chapter]) -> bool:
    """Ha texto real (nem placeholder, nem vazio) em algum paragrafo?"""
    for capitulo in capitulos:
        for paragrafo in capitulo.paragraphs:
            texto = paragrafo.text.strip()
            if texto and texto not in PLACEHOLDERS:
                return True
    return False


def _selecionar_capitulos(job: JobState, selecao: Any, edicoes: Any) -> list[Chapter]:
    """Aplica ordem, titulos, inclusao e edicoes de texto pedidos pelo cliente."""
    edicoes = edicoes if isinstance(edicoes, dict) else {}
    itens: list[tuple[int, str | None]] = []
    if isinstance(selecao, list) and selecao:
        vistos: set[int] = set()
        for item in selecao:
            if not isinstance(item, dict):
                continue
            try:
                indice = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            if indice in vistos or not 0 <= indice < len(job.chapters):
                continue
            if item.get("included") is False:
                continue
            vistos.add(indice)
            titulo = str(item["title"]) if item.get("title") else None
            itens.append((indice, titulo))
    else:
        itens = [(i, None) for i in range(len(job.chapters))]

    saida: list[Chapter] = []
    for indice, titulo in itens:
        capitulo = job.chapters[indice]
        paragrafos = capitulo.paragraphs
        bruto = edicoes.get(str(indice))
        if isinstance(bruto, list):
            paragrafos = [Paragraph.from_text(str(p)) for p in bruto]
        saida.append(Chapter(titulo or capitulo.title, capitulo.level, paragrafos))
    return saida


def _traduzir_em_background(job: JobState, origem: str, destino: str,
                            modelo: str | None) -> None:
    def trabalho(j: JobState) -> None:
        store.update(j.id, status="translating", stage="Traduzindo…")
        try:
            traduzidos, avisos = translate.translate_chapters(
                list(j.chapters), title=j.title, source_lang=origem,
                target_lang=destino, model=modelo,
                workers=store.settings.translation_workers,
                chunk_chars=store.settings.translation_chunk_chars,
                progress=lambda p, m: store.update(j.id, progress=50 + p // 2,
                                                   message=m),
                cancel=j.cancel)
        except translate.CancelledError:
            store.update(j.id, status="cancelled", stage="Cancelado",
                         message="Cancelado pelo usuário.")
            return
        store.update(j.id, chapters=traduzidos,
                     warnings=list(j.warnings) + list(avisos),
                     status="done", stage="Concluído", progress=100,
                     message="")

    store.submit(job.id, trabalho)


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/config")
def configuracao() -> dict:
    candidatos = model_candidates()
    return {
        "provider": provider_name(),
        "configured": is_configured(),
        "translation_model": candidatos[0] if candidatos else "",
        "fallback_models": candidatos[1:],
        "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
        "chunk_chars": settings.translation_chunk_chars,
        "workers": settings.translation_workers,
        "languages": dict(LANG_NAMES),
        "default_target_lang": DEFAULT_TARGET_LANG,
    }


@app.post("/api/jobs", status_code=201)
async def criar_job(
    file: UploadFile = File(...),
    title: Any = Form(default=None),
    author: Any = Form(default=None),
    translate_: Any = Form(default=None, alias="translate"),
    source_lang: Any = Form(default=None),
    target_lang: Any = Form(default=None),
    translation_model: Any = Form(default=None),
    remove_header: Any = Form(default=None),
    remove_page_numbers: Any = Form(default=None),
) -> dict:
    dados = await _ler_upload(file)
    if not dados.lstrip()[:4].startswith(PDF_MAGIC):
        raise HTTPException(400, "o arquivo enviado não é um PDF válido")

    traduzir = _as_bool(translate_, default=False)
    if traduzir and not is_configured():
        raise HTTPException(400, "Nenhuma chave de IA configurada para traduzir "
                                 "(defina OPENAI_API_KEY ou GEMINI_API_KEY).")

    origem = _texto(source_lang, DEFAULT_SOURCE_LANG)
    destino = _texto(target_lang, DEFAULT_TARGET_LANG)
    modelo = translation_model if translation_model not in (None, "null", "") \
        else None

    descritor, caminho = tempfile.mkstemp(suffix=".pdf")
    os.close(descritor)  # o fd do mkstemp não é usado; guardá-lo vaza um por upload
    temporario = Path(caminho)
    try:
        temporario.write_bytes(dados)
        capitulos, avisos = pdf_chapters.build_chapters(
            temporario,
            remove_header=_as_bool(remove_header, default=True),
            remove_page_numbers=_as_bool(remove_page_numbers, default=True))
    except Exception as exc:  # PDF corrompido, protegido, etc.
        log.warning("falha ao ler o PDF: %s", exc)
        raise HTTPException(422, f"não foi possível ler o PDF: {exc}") from exc
    finally:
        temporario.unlink(missing_ok=True)

    if not _tem_texto(capitulos):
        raise HTTPException(422, SEM_TEXTO)

    store.prune()
    if traduzir:
        idioma = destino
    elif origem != DEFAULT_SOURCE_LANG:
        idioma = origem
    else:
        # Sem traducao e sem idioma informado: estima pelo proprio texto, senao
        # o EPUB sairia com dc:language errado no KDP.
        amostra = "\n".join(p.text for c in capitulos[:3]
                            for p in c.paragraphs[:20])
        idioma = translate.detect_language(amostra)
    job = store.create(title=_texto(title, "Livro"), author=_texto(author, "Autor"),
                       language=idioma, source_name=file.filename or "documento.pdf",
                       translated=traduzir)
    store.update(job.id, chapters=capitulos, warnings=list(avisos))

    if traduzir:
        store.update(job.id, status="translating", stage="Traduzindo…",
                     progress=50, message="Preparando a tradução…")
        _traduzir_em_background(job, origem, destino, modelo)
    else:
        store.update(job.id, status="done", stage="Concluído", progress=100)
    return {"job_id": job.id, "status": job.status}


@app.get("/api/jobs/{job_id}")
def obter_job(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id} não encontrado "
                                 "(jobs são descartados ao reiniciar o servidor)")
    return {
        "id": job.id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "message": job.message,
        "title": job.title,
        "author": job.author,
        "language": job.language,
        "translated": job.translated,
        "warnings": list(job.warnings),
        "error": job.error,
        "source_name": job.source_name,
        "chapters": [asdict(v) for v in store.views(job.id)],
    }


@app.get("/api/jobs/{job_id}/chapters/{index}")
def obter_capitulo(job_id: str, index: int) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id} não encontrado")
    if not 0 <= index < len(job.chapters):
        raise HTTPException(404, f"o capítulo {index} não existe neste job")
    capitulo = job.chapters[index]
    return {"index": index, "title": capitulo.title, "level": capitulo.level,
            "paragraphs": [p.text for p in capitulo.paragraphs]}


@app.post("/api/jobs/{job_id}/export")
async def exportar_job(job_id: str, request: Request) -> FileResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id} não encontrado")
    if job.status == "translating":
        raise HTTPException(409, f"job {job_id} ainda está sendo traduzido; "
                                 "aguarde terminar para exportar")
    if job.status in ("error", "cancelled"):
        raise HTTPException(409, f"job {job_id} está '{job.status}': "
                                 "não há conteúdo para exportar")
    try:
        corpo = await request.json()
    except Exception:
        corpo = {}
    if not isinstance(corpo, dict):
        corpo = {}

    capitulos = _selecionar_capitulos(job, corpo.get("chapters"),
                                      corpo.get("edit"))
    if not capitulos:
        raise HTTPException(400, "nenhum capítulo selecionado para exportar")

    destino = store.out_path_for(job, "epub")
    kdp_epub.build_epub(capitulos, job.title, job.author, job.language, destino)
    job.output_paths.append(destino)
    return FileResponse(str(destino), filename=destino.name,
                        media_type="application/epub+zip")


@app.post("/api/jobs/{job_id}/cancel")
def cancelar_job(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id} não encontrado")
    store.cancel(job_id)
    return {"ok": True, "status": job.status}


@app.delete("/api/jobs/{job_id}")
def remover_job(job_id: str) -> dict:
    if not store.delete(job_id):
        raise HTTPException(404, f"job {job_id} não encontrado")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Frontend (SPA) — mount por ultimo, para nao capturar /api
# ---------------------------------------------------------------------------
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True),
              name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app.main:app", host=settings.host, port=settings.port,
                reload=settings.reload)
