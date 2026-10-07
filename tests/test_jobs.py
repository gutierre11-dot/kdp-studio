"""Testes do armazenamento de jobs."""
import threading

from backend.app.jobs import JobStore
from backend.app.models import Chapter, Paragraph


def test_create_e_get(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path))
    job = store.create(title="Livro", author="A", language="pt-BR",
                       source_name="f.pdf", translated=False)
    assert job.status == "queued"
    assert store.get(job.id) is job
    assert store.get("inexistente") is None


def test_prune_remove_expirados(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path, job_ttl_seconds=0))
    job = store.create(title="t", author="a", language="pt-BR",
                       source_name="f.pdf", translated=False)
    job.created_at -= 10
    store.prune()
    assert store.get(job.id) is None


def test_prune_respeita_job_max(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path, job_max=2))
    ids = [store.create(title="t", author="a", language="pt-BR",
                        source_name="f.pdf", translated=False).id
           for _ in range(4)]
    store.prune()
    assert len([i for i in ids if store.get(i)]) == 2


def test_cancel_e_delete(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path))
    job = store.create(title="t", author="a", language="pt-BR",
                       source_name="f.pdf", translated=False)
    assert store.cancel(job.id)
    assert job.cancel.is_set()
    assert store.delete(job.id)
    assert store.get(job.id) is None
    assert not store.cancel("inexistente")
    assert not store.delete("inexistente")


def test_submit_roda_em_background_e_atualiza_estado(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path, job_workers=1))
    job = store.create(title="t", author="a", language="pt-BR",
                       source_name="f.pdf", translated=False)
    pronto = threading.Event()

    def trabalho(j):
        store.update(j.id, status="done", progress=100)
        pronto.set()

    store.submit(job.id, trabalho)
    assert pronto.wait(5)
    assert store.get(job.id).status == "done"


def test_submit_captura_excecao(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path, job_workers=1))
    job = store.create(title="t", author="a", language="pt-BR",
                       source_name="f.pdf", translated=False)
    pronto = threading.Event()

    def trabalho(_j):
        pronto.set()
        raise RuntimeError("quebrou")

    store.submit(job.id, trabalho)
    assert pronto.wait(5)
    for _ in range(50):
        if store.get(job.id).status == "error":
            break
        threading.Event().wait(0.05)
    assert store.get(job.id).status == "error"
    assert "quebrou" in (store.get(job.id).error or "")


def test_views_traz_metadados_sem_texto_completo(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path))
    job = store.create(title="t", author="a", language="pt-BR",
                       source_name="f.pdf", translated=False)
    store.update(job.id, chapters=[Chapter("Cap", 1,
                                           [Paragraph.from_text("a b c")])])
    view = store.views(job.id)[0]
    assert view.index == 0
    assert view.title == "Cap"
    assert view.words == 3
    assert view.preview.startswith("a b c")
    assert not hasattr(view, "paragraphs")


def test_out_path_for_gera_caminho_unico(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path))
    job = store.create(title="Meu Livro! Ótimo", author="a", language="pt-BR",
                       source_name="f.pdf", translated=False)
    primeiro = store.out_path_for(job, "epub")
    primeiro.write_text("x")
    segundo = store.out_path_for(job, "epub")
    assert primeiro.name.endswith(".epub")
    assert primeiro != segundo
    assert primeiro.parent == tmp_path


def test_prune_apaga_artefatos_dos_jobs_removidos(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path, job_ttl_seconds=0))
    job = store.create(title="t", author="a", language="pt-BR",
                       source_name="f.pdf", translated=False)
    arquivo = store.out_path_for(job, "epub")
    arquivo.write_text("conteudo")
    job.output_paths.append(arquivo)
    job.created_at -= 10
    store.prune()
    assert store.get(job.id) is None
    assert not arquivo.exists()
