"""Armazenamento de jobs de conversao.

Estado em memoria protegido por lock, com executor proprio para nao bloquear o
event loop do servidor. Cada job carrega o proprio `threading.Event` de
cancelamento e os caminhos dos arquivos que gerou, para a limpeza apagar os
artefatos junto com o estado.
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from .config import Settings
from .models import ChapterView, JobState


def slug(texto: str) -> str:
    """Nome de arquivo seguro, sem acentos e sem espacos."""
    base = unicodedata.normalize("NFKD", texto or "livro")
    base = base.encode("ascii", "ignore").decode("ascii").lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:60] or "livro"


class JobStore:
    """Colecao de jobs com progresso, cancelamento, TTL e limite."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, int(settings.job_workers)),
            thread_name_prefix="kdp-job")

    # -- ciclo de vida -----------------------------------------------------
    def create(self, *, title: str, author: str, language: str,
               source_name: str, translated: bool) -> JobState:
        job = JobState.new(uuid.uuid4().hex[:12], title=title, author=author,
                           language=language, source_name=source_name,
                           translated=translated)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for nome, valor in fields.items():
                setattr(job, nome, valor)

    def submit(self, job_id: str, fn: Callable[[JobState], None]) -> None:
        """Executa `fn(job)` no executor; falhas viram status `error`."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return

        def runner() -> None:
            try:
                fn(job)
            except Exception as exc:  # nunca deixar o job pendurado
                self.update(job.id, status="error", stage="Falhou",
                            error=f"{type(exc).__name__}: {exc}")

        self._pool.submit(runner)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return False
        job.cancel.set()
        return True

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is None:
            return False
        self._cleanup(job)
        return True

    def _cleanup(self, job: JobState) -> None:
        """Marca o job como cancelado e apaga os arquivos que ele gerou."""
        job.cancel.set()
        for caminho in job.output_paths:
            try:
                Path(caminho).unlink(missing_ok=True)
            except OSError:
                pass

    def prune(self) -> None:
        """Remove jobs expirados e limita o total em memoria.

        Os artefatos dos jobs removidos tambem sao apagados: sem isso o
        diretorio de saida cresceria para sempre e EPUBs expirados continuariam
        acessiveis por `/download`.
        """
        agora = time.time()
        removidos: list[JobState] = []
        with self._lock:
            expirados = [jid for jid, job in self._jobs.items()
                         if agora - job.created_at > self.settings.job_ttl_seconds]
            for jid in expirados:
                removidos.append(self._jobs.pop(jid))
            excesso = len(self._jobs) - self.settings.job_max
            if excesso > 0:
                mais_antigos = sorted(self._jobs.items(),
                                      key=lambda kv: kv[1].created_at)
                for jid, job in mais_antigos[:excesso]:
                    removidos.append(self._jobs.pop(jid))
        for job in removidos:
            self._cleanup(job)

    # -- leitura para a API -----------------------------------------------
    def views(self, job_id: str) -> list[ChapterView]:
        job = self.get(job_id)
        if job is None:
            return []
        vistas: list[ChapterView] = []
        for i, capitulo in enumerate(job.chapters):
            previa = capitulo.paragraphs[0].text[:200] if capitulo.paragraphs else ""
            vistas.append(ChapterView(index=i, title=capitulo.title,
                                      level=capitulo.level, words=capitulo.words,
                                      preview=previa))
        return vistas

    def out_path_for(self, job: JobState, fmt: str) -> Path:
        """Caminho unico em `output/` para o arquivo exportado do job."""
        pasta = Path(self.settings.output_dir)
        pasta.mkdir(parents=True, exist_ok=True)
        base = pasta / f"{slug(job.title)}-{job.id}.{fmt.lstrip('.')}"
        if not base.exists():
            return base
        for n in range(1, 1000):
            candidato = base.with_name(f"{base.stem}-{n}{base.suffix}")
            if not candidato.exists():
                return candidato
        return base.with_name(f"{base.stem}-{uuid.uuid4().hex[:6]}{base.suffix}")
