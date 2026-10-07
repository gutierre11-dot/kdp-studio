"""KDP Studio backend — FastAPI.

Endpoints legados (mantidos):
  GET  /api/health
  GET  /api/models
  POST /api/pdf/parse
  POST /api/pdf/convert
  POST /api/translate        (JSON {chapters, model} — e FormData, ver abaixo)
  POST /api/books/plan
  POST /api/books/write
  POST /api/export
  POST /api/cover/generate

Aliases compatíveis com o frontend (static/app.js):
  POST /api/convert                 (multipart FormData, igual a /api/pdf/convert + job_id)
  GET  /api/convert/{job}/download  (?format=epub|docx&include=0,1,2)
  POST /api/ebook/outline           (-> books/plan, chaves EN ou PT)
  POST /api/ebook/chapter           (-> 1 capítulo via creator.write_chapters)
  POST /api/ebook/cover             (-> cover/generate, chaves EN ou PT)
  POST /api/ebook/export            (-> export; retorna o ARQUIVO quando format=epub|docx)
  GET  /api/library                (lista arquivos de output/)
  DEL  /api/library/{arquivo}      (remove um arquivo gerado)

Configuracao: o .env da raiz (ou de backend/) e carregado automaticamente.
Variaveis uteis: OPENAI_API_KEY, OPENAI_BASE_URL, GEMINI_API_KEY, GEMINI_MODEL,
TRANSLATION_MODEL, CREATION_MODEL, COVER_MODEL, MAX_UPLOAD_MB, CORS_ORIGINS,
JOB_TTL_SECONDS, JOB_MAX, HOST, PORT, RELOAD.

Estáticos:
  /            -> static/index.html (SPA, via mount do frontend com html=True)
  /app.js, /styles.css, ... -> arquivos de static/
  /static/*    -> output/ (legado: links /static/*.epub continuam válidos)
  /download/*  -> output/ (canônico atual)

Rode de kdp-studio/ como:
  uvicorn backend.app.main:app --reload --port 8000
  python -m backend.app.main
"""
import logging
import os
import re
import tempfile
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import cover as cover_mod
from . import creator as creator_mod
from . import kdp_export as kdp_mod
from . import pdf_cleaner as pdf_mod
from . import translator as translator_mod
from .llm import (
    active_provider,
    effective_creation_model,
    effective_translation_model,
    gemini_configured,
    load_env,
    openai_configured,
)

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]  # kdp-studio/
FRONTEND_DIR = BASE_DIR / "static"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# .env carregado tambem aqui para quem importa main sem passar pelo llm.
load_env()

# --- Limites e politicas (configuraveis por ambiente) ---
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024
JOB_TTL_SECONDS = int(os.getenv("JOB_TTL_SECONDS", str(2 * 60 * 60)))
JOB_MAX = int(os.getenv("JOB_MAX", "50"))
PDF_MAGIC = b"%PDF"
_DEFAULT_CORS = "http://localhost:8000,http://127.0.0.1:8000"
CORS_ORIGINS = [o.strip() for o in
                (os.getenv("CORS_ORIGINS") or _DEFAULT_CORS).split(",")
                if o.strip()]

app = FastAPI(title="KDP Studio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Output acessível no legado /static e no canônico /download (mesmo diretório).
app.mount("/static", StaticFiles(directory=str(OUTPUT_DIR)), name="static-output")
app.mount("/download", StaticFiles(directory=str(OUTPUT_DIR)), name="download")

# Jobs de conversão em memória: job_id -> {chapters, title, author, files}
JOBS: dict[str, dict[str, Any]] = {}


def _as_bool(value: Any, default: bool = True) -> bool:
    """Converte valores de FormData ('true'/'false'/'on'/'1') em booleano."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "on", "yes", "sim")


def _unique_path(path: Path) -> Path:
    """Evita sobrescrever arquivos quando duas exportacoes caem no mesmo segundo."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for n in range(1, 1000):
        cand = path.with_name(f"{stem}-{n}{suffix}")
        if not cand.exists():
            return cand
    return path.with_name(f"{stem}-{uuid.uuid4().hex[:6]}{suffix}")


def _slug(s: str) -> str:
    s = (s or "livro").strip()
    # NFKD remove acentos sem depender de unidecode (ex.: obediência -> obediencia).
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "livro"
    return s[:60]


def _latest_cover(prefer_slug: str | None = None) -> Path | None:
    """Última capa cover-*.jpg de output/.

    Quando `prefer_slug` e' informado, devolve APENAS uma capa daquele livro
    (ou None). Antes, a ausencia de correspondencia caia em `covers[0]`, o que
    embutia a capa de outro livro no EPUB exportado.
    """
    try:
        covers = sorted(OUTPUT_DIR.glob("cover-*.jpg"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    if not covers:
        return None
    if prefer_slug:
        prefixo = f"cover-{prefer_slug}-"
        for c in covers:
            if c.name.startswith(prefixo):
                return c
        return None
    return covers[0]


def _enrich_chapters(chapters: list) -> list:
    """Adiciona body/words a capítulos {title, level, paragraphs} sem quebrar o formato."""
    out = []
    for i, ch in enumerate(chapters or []):
        if not isinstance(ch, dict):
            ch = {"title": f"Capítulo {i + 1}", "paragraphs": [str(ch)]}
        paras = ch.get("paragraphs") or []
        if isinstance(paras, str):
            paras = [paras]
        # aceita capítulos vindos do frontend {title, body}
        body = ch.get("body") or ch.get("texto") or ch.get("content") or ch.get("preview") or ""
        if not body and paras:
            body = "\n\n".join(paras)
        if body and not paras:
            paras = [p.strip() for p in str(body).split("\n\n") if p.strip()] or [str(body)]
        words = ch.get("words") or ch.get("palavras") or len(str(body).split())
        out.append({
            **ch,
            "title": ch.get("title") or ch.get("titulo") or f"Capítulo {i + 1}",
            "level": int(ch.get("level", 1) or 1),
            "paragraphs": paras,
            "body": body,
            "words": words,
        })
    return out


def _norm_export_chapters(chapters: list) -> list:
    """Normaliza capítulos do frontend ({title, body}) para o formato do kdp_export."""
    norm = []
    for i, ch in enumerate(chapters or []):
        if not isinstance(ch, dict):
            norm.append({"title": f"Capítulo {i + 1}", "level": 1,
                         "paragraphs": [str(ch)]})
            continue
        paras = ch.get("paragraphs")
        if isinstance(paras, str):
            paras = [paras]
        if not paras:
            raw = ch.get("body") or ch.get("texto") or ch.get("content") or ch.get("preview") or ""
            paras = [p.strip() for p in str(raw).split("\n\n") if p.strip()] or (
                [str(raw)] if raw else ["(sem conteúdo)"])
        norm.append({
            "title": ch.get("title") or ch.get("titulo") or f"Capítulo {i + 1}",
            "level": int(ch.get("level", 1) or 1),
            "paragraphs": paras,
        })
    return norm


_PDF_PLACEHOLDERS = {"(PDF sem texto extraivel.)", "(sem conteúdo)"}


def _ensure_translatable(chapters: list) -> None:
    """Recusa traduzir quando o PDF não tem texto real (escaneados exigem OCR)."""
    textos = [(p or "").strip() for c in (chapters or [])
              for p in (c.get("paragraphs") or [])]
    if not any(t and t not in _PDF_PLACEHOLDERS for t in textos):
        raise HTTPException(
            status_code=422,
            detail="PDF sem texto extraível: não há o que traduzir "
                   "(OCR de PDFs escaneados não é suportado).")


def _save_and_urls(title: str, chapters: list, author: str,
                   cover_path: Path | None = None) -> dict:
    ts = int(time.time())
    slug = _slug(title)
    epub_path = _unique_path(OUTPUT_DIR / f"{slug}-{ts}.epub")
    docx_path = _unique_path(OUTPUT_DIR / f"{slug}-{ts}.docx")
    html_path = _unique_path(OUTPUT_DIR / f"{slug}-{ts}-preview.html")
    kdp_mod.export_epub(chapters, title, author, epub_path, cover_path)
    kdp_mod.export_docx(chapters, title, author, docx_path)
    html_path.write_text(kdp_mod.build_preview_html(chapters, title, author),
                         encoding="utf-8")
    return {
        "epub": f"/download/{epub_path.name}",
        "docx": f"/download/{docx_path.name}",
        "preview": f"/download/{html_path.name}",
        "files": [epub_path.name, docx_path.name, html_path.name],
    }


def _prune_jobs() -> None:
    """Remove jobs expirados e limita o total (evita vazamento de memoria)."""
    agora = time.time()
    expirados = [jid for jid, j in JOBS.items()
                 if agora - j.get("created_at", agora) > JOB_TTL_SECONDS]
    for jid in expirados:
        JOBS.pop(jid, None)
    if len(JOBS) > JOB_MAX:
        antigos = sorted(JOBS.items(), key=lambda kv: kv[1].get("created_at", 0))
        for jid, _ in antigos[:len(JOBS) - JOB_MAX]:
            JOBS.pop(jid, None)


def _register_job(title: str, author: str, chapters: list, files: list) -> str:
    _prune_jobs()
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"title": title, "author": author,
                    "chapters": chapters, "files": files,
                    "created_at": int(time.time())}
    return job_id


def _epub_format(value: Any) -> str:
    """Normaliza o `format` do export de traducao; apenas EPUB e' suportado."""
    fmt = (str(value).strip().lower().lstrip(".") if value not in (None, "")
           else "epub") or "epub"
    if fmt not in ("epub",):
        raise HTTPException(status_code=400,
                            detail=f"formato invalido: {fmt!r} (use epub)")
    return fmt


def _export_translation_epub(out: list, title: Any, author: Any) -> dict:
    """Gera o EPUB KDP da tradução e registra um job (mesmo fluxo do conversor)."""
    norm = _norm_export_chapters(out)
    if not norm:
        raise HTTPException(status_code=400,
                            detail="nenhum capítulo traduzido para exportar")
    t = str(title) if title not in (None, "null", "") else "Tradução"
    a = str(author) if author not in (None, "null", "") else "Autor"
    ts = int(time.time())
    slug = _slug(t)
    epub_path = _unique_path(OUTPUT_DIR / f"{slug}-{ts}.epub")
    kdp_mod.export_epub(norm, t, a, epub_path)
    job_id = _register_job(t, a, out, [epub_path.name])
    return {"job_id": job_id, "export": True, "format": "epub",
            "epub": f"/download/{epub_path.name}", "files": [epub_path.name]}


async def _read_upload_limited(upload: UploadFile) -> bytes:
    """Le o upload em blocos, respeitando MAX_UPLOAD_BYTES."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"arquivo maior que o limite de "
                       f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
        chunks.append(chunk)
    if not total:
        raise HTTPException(status_code=400, detail="arquivo vazio")
    return b"".join(chunks)


async def _pdf_to_chapters(upload: UploadFile, remove_header: bool = True,
                           remove_page_numbers: bool = True) -> list:
    dados = await _read_upload_limited(upload)
    if not dados.lstrip()[:4].startswith(PDF_MAGIC):
        raise HTTPException(status_code=400,
                            detail="o arquivo enviado nao e um PDF valido")
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(dados)
            tmp_path = Path(tmp.name)
        return pdf_mod.parse_pdf_to_chapters(
            tmp_path, remove_header=remove_header,
            remove_page_numbers=remove_page_numbers)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


# ---------- Schemas (legados) ----------
class TranslateIn(BaseModel):
    chapters: list
    model: str | None = None


class PlanIn(BaseModel):
    ideia: str
    genero: str = "romance"
    estilo: str = "envolvente"
    publico: str = "adultos"
    capitulos: int = 10


class WriteIn(BaseModel):
    outline: list
    titulo: str = "Livro"
    estilo: str = "envolvente"


class ExportIn(BaseModel):
    chapters: list
    title: str = "Livro"
    author: str = "Autor"


class CoverIn(BaseModel):
    titulo: str
    autor: str = "Autor"
    estilo: str = "premium"


# ---------- Básicos ----------
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/health")
def health_alias():
    return {"ok": True}


@app.get("/api/models")
def models():
    provider = active_provider()
    return {
        # Defaults OpenAI (mantidos por compat com frontend antigo).
        "recommended_traducao": "gpt-4o-mini",
        "recomendado_criacao": "gpt-4o",
        # Alias EN usados por alguns clientes.
        "recommended_translation": "gpt-4o-mini",
        "recommended_creation": "gpt-4o",
        "openai_configurado": openai_configured(),
        "gemini_configurado": gemini_configured(),
        "configurado": provider in ("openai", "gemini"),
        "provider_ativo": provider,  # openai | gemini | offline
        "translation_model": effective_translation_model(),
        "creation_model": effective_creation_model(),
    }


# ---------- PDF (legados) ----------
@app.post("/api/pdf/parse")
async def pdf_parse(file: UploadFile = File(...),
                    remove_header: Any = Form(default=None),
                    remove_page_numbers: Any = Form(default=None)):
    chapters = await _pdf_to_chapters(
        file, _as_bool(remove_header), _as_bool(remove_page_numbers))
    return {"chapters": _enrich_chapters(chapters)}


@app.post("/api/pdf/convert")
async def pdf_convert(file: UploadFile = File(...),
                      title: str = "Livro", author: str = "Autor",
                      remove_header: Any = Form(default=None),
                      remove_page_numbers: Any = Form(default=None),
                      translate: Any = Form(default=None),
                      source_lang: Any = Form(default=None),
                      target_lang: Any = Form(default=None),
                      translation_model: Any = Form(default=None)):
    do_translate = _as_bool(translate, default=False)
    src = (str(source_lang) if source_lang not in (None, "null", "")
           else translator_mod.DEFAULT_SOURCE_LANG)
    tgt = (str(target_lang) if target_lang not in (None, "null", "")
           else translator_mod.DEFAULT_TARGET_LANG)
    model_used = None
    chapters = await _pdf_to_chapters(
        file, _as_bool(remove_header), _as_bool(remove_page_numbers))
    if do_translate:
        _ensure_translatable(chapters)
        model_used = (str(translation_model)
                      if translation_model not in (None, "null", "")
                      else effective_translation_model())
        chapters = translator_mod.translate_chapters(
            chapters, model_used, source_lang=src, target_lang=tgt)
    urls = _save_and_urls(title, chapters, author)
    enriched = _enrich_chapters(chapters)
    job_id = _register_job(title, author, chapters, urls["files"])
    return {"chapters": enriched, "job_id": job_id, "id": job_id,
            "translated": do_translate, "source_lang": src,
            "target_lang": tgt, "translation_model": model_used, **urls}


# ---------- Alias: POST /api/convert (frontend FormData) ----------
@app.post("/api/convert")
async def convert_alias(
    file: UploadFile = File(...),
    title: Any = Form(default=None),
    author: Any = Form(default=None),
    fmt: Any = Form(default=None, alias="format"),
    remove_header: Any = Form(default=None),
    remove_page_numbers: Any = Form(default=None),
    translate: Any = Form(default=None),
    source_lang: Any = Form(default=None),
    target_lang: Any = Form(default=None),
    translation_model: Any = Form(default=None),
):
    # FormData do frontend envia tudo como str; normaliza com tolerância.
    t = str(title) if title not in (None, "null", "") else "Livro"
    a = str(author) if author not in (None, "null", "") else "Autor"
    formato = str(fmt or "all").strip().lower().lstrip(".") or "all"
    if formato not in ("all", "epub", "docx"):
        raise HTTPException(status_code=400,
                            detail=f"formato invalido: {formato!r}")
    do_translate = _as_bool(translate, default=False)
    src = (str(source_lang) if source_lang not in (None, "null", "")
           else translator_mod.DEFAULT_SOURCE_LANG)
    tgt = (str(target_lang) if target_lang not in (None, "null", "")
           else translator_mod.DEFAULT_TARGET_LANG)
    model_used = None
    # Os toggles do frontend agora sao respeitados de verdade (antes eram
    # recebidos e ignorados; a limpeza era sempre aplicada).
    chapters = await _pdf_to_chapters(
        file, _as_bool(remove_header), _as_bool(remove_page_numbers))
    if do_translate:
        _ensure_translatable(chapters)
        model_used = (str(translation_model)
                      if translation_model not in (None, "null", "")
                      else effective_translation_model())
        chapters = translator_mod.translate_chapters(
            chapters, model_used, source_lang=src, target_lang=tgt)
    urls = _save_and_urls(t, chapters, a)
    enriched = _enrich_chapters(chapters)
    job_id = _register_job(t, a, chapters, urls["files"])
    return {"job_id": job_id, "id": job_id, "format": formato,
            "remove_header": _as_bool(remove_header),
            "remove_page_numbers": _as_bool(remove_page_numbers),
            "translated": do_translate, "source_lang": src,
            "target_lang": tgt, "translation_model": model_used,
            "chapters": enriched, "capitulos": enriched, **urls}


# ---------- Download do job ----------
@app.get("/api/convert/{job_id}/download")
def convert_download(job_id: str, fmt: str = Query("epub", alias="format"),
                     include: str | None = None):
    """Baixa EPUB/DOCX do job.

    `include` usa os INDICES ORIGINAIS dos capitulos (ex.: include=1,2).
    """
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404,
                            detail=f"job {job_id} não encontrado "
                                   "(jobs expiram ou somem ao reiniciar)")
    chapters = job["chapters"]
    if include:
        idx = {int(x) for x in include.split(",") if x.strip().lstrip("-").isdigit()}
        if idx:
            chapters = [c for i, c in enumerate(chapters) if i in idx]
    if not chapters:
        raise HTTPException(status_code=400, detail="nenhum capítulo selecionado")
    ts = int(time.time())
    slug = _slug(job.get("title") or "livro")
    formato = (fmt or "epub").lower().lstrip(".")
    if formato == "docx":
        out = _unique_path(OUTPUT_DIR / f"{slug}-{job_id}-{ts}.docx")
        kdp_mod.export_docx(chapters, job.get("title") or "Livro",
                            job.get("author") or "Autor", out)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif formato in ("epub", "html", "preview"):
        out = _unique_path(OUTPUT_DIR / f"{slug}-{job_id}-{ts}.epub")
        kdp_mod.export_epub(chapters, job.get("title") or "Livro",
                            job.get("author") or "Autor", out)
        media = "application/epub+zip"
    else:
        raise HTTPException(status_code=400,
                            detail=f"formato invalido: {formato!r} "
                                   "(use epub ou docx)")
    return FileResponse(str(out), media_type=media, filename=out.name)


# ---------- Translate: JSON legado + FormData do frontend (rota única) ----------
@app.post("/api/translate")
async def translate(request: Request):
    ct = (request.headers.get("content-type") or "").lower()
    if "multipart" in ct or "x-www-form-urlencoded" in ct:
        form = await request.form()
        text = str(form.get("text") or "")
        model = str(form.get("model") or "") or effective_translation_model()
        source_lang = str(form.get("source_lang")
                          or translator_mod.DEFAULT_SOURCE_LANG)
        target_lang = str(form.get("target_lang")
                          or translator_mod.DEFAULT_TARGET_LANG)
        do_export = _as_bool(form.get("export"), default=False)
        if do_export:
            _epub_format(form.get("format"))
        src_chapters: list[dict] = []
        if text.strip():
            src_chapters.append({"title": "", "level": 1, "paragraphs": [text]})
        raw_file = form.get("file")
        pdf_enviado = False
        if raw_file is not None and hasattr(raw_file, "read"):
            raw = await raw_file.read()
            name = (getattr(raw_file, "filename", "") or "").lower()
            if name.endswith(".pdf"):
                pdf_enviado = True
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(raw)
                    tmp_path = Path(tmp.name)
                try:
                    src_chapters.extend(pdf_mod.parse_pdf_to_chapters(tmp_path))
                finally:
                    tmp_path.unlink(missing_ok=True)
            else:
                decoded = raw.decode("utf-8", errors="replace")
                if decoded.strip():
                    src_chapters.append({"title": "", "level": 1, "paragraphs": [decoded]})
        if not src_chapters:
            raise HTTPException(status_code=400, detail="texto vazio para traduzir")
        # PDF escaneado (sem texto real) nao tem o que traduzir: OCR esta fora
        # de escopo -> 422, em vez de "traduzir" placeholders.
        if pdf_enviado:
            _ensure_translatable(src_chapters)
        out = translator_mod.translate_chapters(
            src_chapters, model, source_lang=source_lang, target_lang=target_lang)
        joined = "\n\n".join(
            (c.get("title", "") + "\n" if c.get("title") else "")
            + "\n".join(c.get("paragraphs", []))
            for c in out)
        payload = {"translated_text": joined, "result": joined, "text": joined,
                   "chapters_traduzidos": out, "model": model,
                   "source_lang": source_lang, "target_lang": target_lang}
        if do_export:
            payload.update(_export_translation_epub(
                out, form.get("title"), form.get("author")))
        return payload
    # JSON legado: {chapters, model}
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400,
                            detail="envie JSON {chapters[]} ou FormData {text, file}")
    chapters = payload.get("chapters") or []
    if not chapters:
        raise HTTPException(status_code=400,
                            detail="envie JSON {chapters[]} ou FormData {text, file}")
    model = payload.get("model") or effective_translation_model()
    source_lang = payload.get("source_lang") or translator_mod.DEFAULT_SOURCE_LANG
    target_lang = payload.get("target_lang") or translator_mod.DEFAULT_TARGET_LANG
    do_export = _as_bool(payload.get("export"), default=False)
    if do_export:
        _epub_format(payload.get("format"))
        # Sem texto real nao ha EPUB a exportar (mesma guarda do fluxo PDF).
        _ensure_translatable(_enrich_chapters(chapters))
    out = translator_mod.translate_chapters(chapters, model,
                                            source_lang=source_lang,
                                            target_lang=target_lang)
    joined = "\n\n".join(
        c.get("title", "") + "\n" + "\n".join(c.get("paragraphs", [])) for c in out)
    resp = {"chapters_traduzidos": out, "translated_text": joined,
            "result": joined, "text": joined,
            "model": model, "source_lang": source_lang,
            "target_lang": target_lang}
    if do_export:
        resp.update(_export_translation_epub(
            out, payload.get("title"), payload.get("author")))
    return resp


# ---------- Books (legados) ----------
@app.post("/api/books/plan")
def books_plan(body: PlanIn):
    return creator_mod.plan_book(body.ideia, body.genero, body.estilo,
                                 body.publico, body.capitulos)


@app.post("/api/books/write")
def books_write(body: WriteIn):
    chapters = creator_mod.write_chapters(body.outline, body.titulo, body.estilo)
    return {"chapters": chapters}


# ---------- Aliases /api/ebook/* ----------
@app.post("/api/ebook/outline")
async def ebook_outline(data: dict):
    idea = data.get("idea") or data.get("ideia") or ""
    genre = data.get("genre") or data.get("genero") or "romance"
    style = data.get("style") or data.get("estilo") or "envolvente"
    audience = data.get("audience") or data.get("publico") or "adultos"
    num = (data.get("num_chapters") or data.get("capitulos") or data.get("size")
           or data.get("num_capitulos") or 10)
    try:
        num = int(num)
    except (TypeError, ValueError):
        num = 10
    plan = creator_mod.plan_book(str(idea), str(genre), str(style),
                                 str(audience), num)
    titulo = plan.get("titulo") or data.get("title") or "Livro"
    outline = []
    for i, item in enumerate(plan.get("outline", [])):
        t = item.get("titulo") or item.get("title") or f"Capítulo {i + 1}"
        s = item.get("resumo") or item.get("synopsis") or item.get("sinopse") or ""
        outline.append({"title": t, "titulo": t, "synopsis": s, "sinopse": s,
                        "resumo": s})
    return {"titulo": titulo, "title": titulo, "outline": outline,
            "chapters": outline}


@app.post("/api/ebook/chapter")
async def ebook_chapter(data: dict):
    ch_title = (data.get("chapter_title") or data.get("titulo") or
                data.get("title") or "Capítulo")
    syn = (data.get("chapter_synopsis") or data.get("synopsis") or
           data.get("sinopse") or data.get("resumo") or "")
    book_title = data.get("title") or data.get("titulo") or data.get("book_title") or "Livro"
    style = data.get("style") or data.get("estilo") or "envolvente"
    # Número real do capítulo (o fluxo single-item vinha sempre como 1).
    try:
        numero = int(data.get("numero") or data.get("numero_capitulo")
                     or data.get("chapter_number") or data.get("num") or 1)
    except (TypeError, ValueError):
        numero = 1
    chapters = creator_mod.write_chapters(
        [{"titulo": str(ch_title), "resumo": str(syn), "numero": numero}],
        str(book_title), str(style), numero_capitulo_inicial=numero)
    ch = chapters[0] if chapters else {"title": ch_title, "paragraphs": []}
    body = "\n\n".join(ch.get("paragraphs", []))
    return {"text": body, "body": body, "content": body,
            "chapter": ch, "title": ch.get("title", ch_title),
            "mock": bool(ch.get("mock", False)), "numero": numero}


@app.post("/api/ebook/cover")
async def ebook_cover(data: dict):
    title = data.get("title") or data.get("titulo") or "Livro"
    author = data.get("author") or data.get("autor") or "Autor"
    estilo = (data.get("estilo") or data.get("style") or
              data.get("prompt") or "premium")
    ts = int(time.time())
    out = OUTPUT_DIR / f"cover-{_slug(str(title))}-{ts}.jpg"
    cover_mod.generate_cover(str(title), str(author), str(estilo)[:200], out)
    return {"image_url": f"/download/{out.name}", "url": f"/download/{out.name}"}


def _resolve_cover(data: dict, slug: str) -> Path | None:
    """Capa explicita do request (se valida) ou a capa DESTE livro (ou None).

    Nunca reaproveita a capa de outro livro.
    """
    cover_path = (data.get("cover_path") or data.get("cover")
                  or data.get("image_url"))
    if cover_path:
        cand = OUTPUT_DIR / Path(str(cover_path)).name  # basename: sem traversal
        if cand.is_file() and cand.suffix.lower() in (".jpg", ".jpeg", ".png"):
            return cand
    return _latest_cover(prefer_slug=slug)


@app.post("/api/ebook/export")
async def ebook_export(data: dict):
    title = data.get("title") or data.get("titulo") or "Livro"
    author = data.get("author") or data.get("autor") or "Autor"
    fmt = str(data.get("format") or data.get("formato") or "all").lower().lstrip(".")
    chapters = _norm_export_chapters(data.get("chapters") or data.get("capitulos") or [])
    if not chapters:
        raise HTTPException(status_code=400, detail="nenhum capítulo para exportar")
    ts = int(time.time())
    slug = _slug(str(title))
    cover = _resolve_cover(data, slug)

    if fmt in ("all", "trio", "todos", "both", "json", ""):
        # Trio canônico: epub + docx + preview (mesmo slug, capa embutida).
        return _save_and_urls(str(title), chapters, str(author), cover)
    if fmt in ("epub", "html", "preview"):
        # Apenas o arquivo pedido: antes este ramo gerava tambem o trio
        # (docx/epub/preview) com outro timestamp, deixando orfaos.
        out = _unique_path(OUTPUT_DIR / f"{slug}-{ts}.epub")
        kdp_mod.export_epub(chapters, str(title), str(author), out, cover)
        return FileResponse(str(out), filename=out.name,
                            media_type="application/epub+zip")
    if fmt == "docx":
        out = _unique_path(OUTPUT_DIR / f"{slug}-{ts}.docx")
        kdp_mod.export_docx(chapters, str(title), str(author), out)
        return FileResponse(
            str(out), filename=out.name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    raise HTTPException(status_code=400,
                        detail=f"formato invalido: {fmt!r} "
                               "(use epub, docx ou all)")


# ---------- Export / Cover (legados) ----------
@app.post("/api/export")
def export(body: ExportIn):
    urls = _save_and_urls(body.title, body.chapters, body.author)
    return urls


@app.post("/api/cover/generate")
def cover_generate(body: CoverIn):
    ts = int(time.time())
    out = OUTPUT_DIR / f"cover-{_slug(body.titulo)}-{ts}.jpg"
    cover_mod.generate_cover(body.titulo, body.autor, body.estilo, out)
    return {"image_url": f"/download/{out.name}", "url": f"/download/{out.name}"}


# ---------- Biblioteca ----------
_KIND_BY_EXT = {".epub": "eBook", ".docx": "Documento", ".doc": "Documento",
                ".html": "Prévia", ".jpg": "Capa", ".jpeg": "Capa", ".png": "Capa"}


@app.get("/api/library")
def library():
    items = []
    for p in sorted(OUTPUT_DIR.iterdir(), key=lambda x: x.stat().st_mtime,
                    reverse=True):
        if not p.is_file() or p.suffix.lower() not in _KIND_BY_EXT:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        items.append({
            "id": p.name,
            "kind": _KIND_BY_EXT[p.suffix.lower()],
            "type": _KIND_BY_EXT[p.suffix.lower()],
            "title": p.stem,
            "name": p.name,
            "detail": f"{st.st_size / 1024:.0f} KB",
            "description": f"{st.st_size / 1024:.0f} KB",
            "date": time.strftime("%d/%m/%Y %H:%M", time.localtime(st.st_mtime)),
            "created_at": time.strftime("%d/%m/%Y %H:%M", time.localtime(st.st_mtime)),
            "download": f"/download/{p.name}",
            "download_url": f"/download/{p.name}",
        })
    return {"items": items, "outputs": items, "total": len(items)}


@app.delete("/api/library/{name}")
def library_delete(name: str):
    """Remove um arquivo gerado de output/ (apenas basename, extensao conhecida).

    Antes o botao de excluir da Biblioteca so apagava o item do localStorage e
    o arquivo reaparecia no proximo refresh.
    """
    if (not name or name.startswith(".") or Path(name).name != name
            or "/" in name or "\\" in name):
        raise HTTPException(status_code=400, detail="nome invalido")
    if Path(name).suffix.lower() not in _KIND_BY_EXT:
        raise HTTPException(status_code=400,
                            detail="tipo de arquivo nao permitido")
    target = OUTPUT_DIR / name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="arquivo nao encontrado")
    try:
        target.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500,
                            detail=f"falha ao remover: {exc}")
    return {"ok": True, "removed": name}


# ---------- Frontend (SPA) servido em / — mount por ÚLTIMO ----------
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True),
              name="frontend")


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    porta = int(os.getenv("PORT", "8000"))
    reload_on = (os.getenv("RELOAD", "0") or "").strip().lower() in ("1", "true", "on")
    uvicorn.run("backend.app.main:app", host=host, port=porta, reload=reload_on)
