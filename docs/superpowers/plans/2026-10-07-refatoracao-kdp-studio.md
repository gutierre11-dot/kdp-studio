# Refatoração do KDP Studio — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reescrever o KDP Studio para entregar PDF → EPUB 3 no padrão KDP com capítulos corretos, e PDF em outro idioma → tradução pt-BR → EPUB no mesmo job.

**Architecture:** Backend FastAPI com pipeline em fases (extrair → capítulos → traduzir → exportar) rodando em jobs assíncronos com progresso real; parser guiado pelos bookmarks do PDF com fallback heurístico; EPUB montado com escrita atômica e validado antes de ser publicado; SPA sem build em 3 passos consumindo a API de jobs.

**Tech Stack:** Python 3.10+, FastAPI, PyMuPDF, ebooklib, `openai` SDK (endpoint OpenAI-compatible do Gemini), HTML/CSS/JS sem build (Tailwind local).

**Spec:** [`docs/superpowers/specs/2026-10-07-refatoracao-kdp-studio-design.md`](../specs/2026-10-07-refatoracao-kdp-studio-design.md)

## Global Constraints

- Python `>= 3.10`; sem novas dependências; `python-docx` é removido de `backend/requirements.txt`.
- Nenhuma mensagem de erro visível ao usuário em inglês: tudo em **pt-BR**.
- Nenhum EPUB inválido pode chegar a `output/`: `validate_epub` roda sobre o temporário e só então `os.replace`.
- Toda chamada de LLM tem timeout, retry e cadeia de fallback de modelos.
- Idioma de destino padrão: `pt-BR`.
- Códigos HTTP: 400 (requisição inválida), 404 (job inexistente), 409 (job em `error`/`cancelled`), 413 (upload grande), 422 (PDF sem texto extraível).
- Testes rodam **offline**: nenhum teste pode chamar API de LLM real. Sempre monkeypatchar o cliente.
- Comandos rodam a partir de `kdp-studio/`.
- `output/` e `.env` nunca são versionados (já estão no `.gitignore`).

## Review Focus

Cinco entradas/condições que a spec implica mas cujos testes exigem atenção deliberada — cada uma tem teste na tarefa dona do código:

1. **PDF escaneado (sem texto)** → deve terminar em HTTP 422 com mensagem acionável, nunca gerar EPUB vazio ou travado.
2. **Bookmark apontando para página vazia/inexistente ou entradas duplicadas** → não pode derrubar o parser nem gerar capítulo vazio.
3. **Modelo de tradução devolve parágrafos mesclados/separados** → a contagem de parágrafos deve ser restaurada ou o trecho mantido no original, com aviso; nunca perder texto em silêncio.
4. **Título de capítulo com `&`, `<`, aspas ou emoji** → deve sair escapado no XHTML e não corromper o EPUB.
5. **Cancelamento no meio da conversão** → nenhum arquivo parcial em `output/`.

---

## Fase 1 — Núcleo do parser

### Task 1: Fundação — `config.py` e `models.py`

**Files:**
- Create: `backend/app/config.py`
- Create: `backend/app/models.py`
- Test: `tests/test_config.py`, `tests/test_models.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `config.Settings` (frozen dataclass): `output_dir:Path` (default `Path(__file__).resolve().parents[2] / "output"`), `max_upload_bytes:int`, `job_ttl_seconds:int`, `job_max:int`, `job_workers:int`, `cors_origins:list[str]`, `translation_chunk_chars:int`, `translation_workers:int`, `llm_timeout_seconds:float`, `llm_max_retries:int`, `primary_model:str`, `fallback_models:list[str]`, `host:str`, `port:int`, `reload:bool`.
  - `config.get_settings() -> Settings` — em cache, lê o ambiente; `config.get_settings.cache_clear()` disponível nos testes.
  - `config.load_env() -> list[str]` — carrega `kdp-studio/.env` e depois `kdp-studio/backend/.env` sem sobrescrever o ambiente real (`override=False`); nunca levanta exceção.
  - `models.Run(text:str, italic:bool=False, bold:bool=False)`
  - `models.Line(page:int, text:str, size:float, bold:bool, italic:bool, bbox:tuple[float,float,float,float], page_height:float, page_width:float, runs:list[Run])`
  - `models.Paragraph(runs:list[Run])` com `.text -> str` e `Paragraph.from_text(text:str) -> Paragraph`
  - `models.Chapter(title:str, level:int, paragraphs:list[Paragraph])` com `.words -> int`
  - `models.ChapterView(index:int, title:str, level:int, words:int, preview:str, included:bool=True)`
  - `models.JobState` com campos `id, status, stage, progress, message, title, author, language, translated, chapters, warnings, error, cancel, created_at, source_name, output_paths` e `JobState.new(job_id, *, title, author, language, source_name, translated) -> JobState`.
  - `Anchor = tuple[int, int, str]` (índice da linha, level, title) é definido em `models.py` e reexportado por `pdf_chapters`.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:

```python
import importlib
from backend.app import config

def test_settings_defaults(monkeypatch):
    for k in ("MAX_UPLOAD_MB","JOB_TTL_SECONDS","JOB_MAX","JOB_WORKERS",
              "TRANSLATION_CHUNK_CHARS","TRANSLATION_WORKERS","LLM_TIMEOUT_SECONDS",
              "LLM_MAX_RETRIES","GEMINI_MODEL","GEMINI_MODEL_FALLBACKS","GEMINI_API_KEY","OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert s.max_upload_bytes == 100 * 1024 * 1024
    assert (s.job_ttl_seconds, s.job_max, s.job_workers) == (7200, 50, 2)
    assert (s.translation_chunk_chars, s.translation_workers) == (6000, 4)
    assert (s.llm_timeout_seconds, s.llm_max_retries) == (120.0, 3)
    assert s.primary_model == "gemini-flash-latest"
    assert s.fallback_models == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.1-flash-lite"]

def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("TRANSLATION_WORKERS", "7")
    monkeypatch.setenv("GEMINI_MODEL_FALLBACKS", "a, b ,c")
    config.get_settings.cache_clear()
    s = config.get_settings()
    assert s.translation_workers == 7
    assert s.fallback_models == ["a", "b", "c"]
```

`tests/test_models.py`:

```python
from backend.app.models import Chapter, JobState, Paragraph, Run

def test_paragraph_text_concatena_runs():
    assert Paragraph([Run("Olá"), Run(" "), Run("mundo")]).text == "Olá mundo"

def test_paragraph_from_text_cria_run_plano():
    p = Paragraph.from_text("abc")
    assert p.text == "abc" and p.runs == [Run("abc")]

def test_chapter_words_soma_palavras():
    ch = Chapter("T", 1, [Paragraph.from_text("um dois três"), Paragraph.from_text("quatro")])
    assert ch.words == 4

def test_jobstate_nao_compartilha_evento_de_cancelamento():
    a = JobState.new("a", title="t", author="x", language="pt-BR",
                     source_name="f.pdf", translated=False)
    b = JobState.new("b", title="t", author="x", language="pt-BR",
                     source_name="f.pdf", translated=False)
    a.cancel.set()
    assert not b.cancel.is_set()
    assert a.status == "queued" and a.progress == 0 and a.warnings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_config.py tests/test_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.app.config'`

- [ ] **Step 3: Implement `backend/app/models.py` and `backend/app/config.py`**

`models.py`: dataclasses as above; `Line.bbox` como tupla de 4 floats; `Paragraph.text` = `"".join(r.text for r in self.runs)`; `words` = `len(self.text.split())` somado por capítulo; `JobState.cancel` usa `field(default_factory=threading.Event)`.

`config.py`: `load_env()` usa `dotenv.load_dotenv(..., override=False)`; `get_settings()` é decorada com `functools.lru_cache` e monta `Settings` a partir de `os.getenv`, com um helper `_int(name, default)` / `_float` e `_list(name, default)` que quebra por vírgula, faz `strip` e descarta vazios. `fallback_models` usa `GEMINI_MODEL_FALLBACKS` com o default da spec. `CORS_ORIGINS` default `http://localhost:8000,http://127.0.0.1:8000`. Chame `load_env()` no import do módulo.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_config.py tests/test_models.py -q`
Expected: PASS (7 testes)

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/models.py tests/test_config.py tests/test_models.py
git commit -m "feat(parser): configuração e modelo de dados da refatoração"
```

---

### Task 2: Extração de linhas e bookmarks — `pdf_extract.py`

**Files:**
- Create: `backend/app/pdf_extract.py`
- Modify: `tests/conftest.py` (adicionar fixture `make_bookmark_pdf`)
- Test: `tests/test_pdf_extract.py`

**Interfaces:**
- Consumes: `models.Line`, `models.Run`.
- Produces: `pdf_extract.extract_lines(pdf_path: Path | str) -> tuple[list[Line], int, list[tuple[int, str, int]]]` — `(linhas, total_páginas, outline)` com `outline` no formato de `doc.get_toc(simple=True)`.

- [ ] **Step 1: Write the failing tests**

Adicione em `tests/conftest.py` a fixture `make_bookmark_pdf(tmp_path)` que gera um PDF de 2 páginas com `pymupdf`, insere os títulos "Capítulo Um" (página 1, 20pt) e "Capítulo Dois" (página 2, 20pt) e define `doc.set_toc([[1, "Capítulo Um", 1], [1, "Capítulo Dois", 2]])`; devolve o `Path`.

`tests/test_pdf_extract.py`:

```python
from backend.app.pdf_extract import extract_lines

def test_extrai_linhas_com_pagina_tamanho_e_runs(make_pdf):
    path = make_pdf
    lines, pages, toc = extract_lines(path)
    assert pages >= 1
    assert toc == [] or isinstance(toc, list)
    titulos = [l for l in lines if l.text == "Capítulo Um"]
    assert titulos and titulos[0].size >= 18.0
    assert titulos[0].runs and "".join(r.text for r in titulos[0].runs).strip()

def test_extrai_bookmarks(make_bookmark_pdf):
    lines, pages, toc = extract_lines(make_bookmark_pdf)
    assert pages == 2
    assert toc == [[1, "Capítulo Um", 1], [1, "Capítulo Dois", 2]]
    assert [l.text for l in lines if l.size >= 18] == ["Capítulo Um", "Capítulo Dois"]

def test_linhas_em_ordem_de_leitura(make_pdf):
    lines, _, _ = extract_lines(make_pdf)
    chave = [(l.page, l.bbox[1]) for l in lines]
    assert chave == sorted(chave)
```

> A fixture `make_pdf` já existe em `tests/conftest.py` e cria títulos, corpo, cabeçalho e numeração repetidos. Reaproveite; se ela devolver bytes em vez de `Path`, ajuste para devolver `Path` e adapte `pdf_bytes` para ler esse arquivo.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pdf_extract.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.app.pdf_extract'`

- [ ] **Step 3: Implement `extract_lines`**

Abre com `pymupdf.open`; para cada página usa `page.get_text("dict")`. Para cada `line` com spans não vazios: `text = " ".join(span["text"] for span in spans).strip()`, `size = max(float(s["size"]))`, `bold`/`italic` a partir de `int(s["flags"])` (bit `16` = bold, bit `2` = italic), `runs = [Run(span_text, italic, bold) ...]` só dos spans não vazios, `bbox = tuple(line["bbox"])`, `page_height = float(page.rect.height)`, `page_width = float(page.rect.width)`. Ordena por `(page, bbox[1], bbox[0])`. Lê `doc.get_toc(simple=True)` antes de fechar. `finally: doc.close()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pdf_extract.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pdf_extract.py tests/test_pdf_extract.py tests/conftest.py
git commit -m "feat(parser): extração de linhas com geometria e bookmarks"
```

---

### Task 3: Ancoragem do outline — `pdf_chapters.py` (parte 1)

**Files:**
- Create: `backend/app/pdf_chapters.py`
- Test: `tests/test_pdf_chapters.py`

**Interfaces:**
- Consumes: `extract_lines`, `Line`, `Anchor`.
- Produces:
  - `pdf_chapters.normalize(text: str) -> str` — NFKD, sem acentos, minúsculas, só `[a-z0-9 ]`, espaços colapsados.
  - `pdf_chapters.modal_body_size(lines: list[Line]) -> float` — tamanho (arredondado a 1 casa) que concentra mais caracteres.
  - `pdf_chapters.anchor_outline(lines: list[Line], outline: list[tuple[int,str,int]], body_size: float) -> list[Anchor]`.
  - `pdf_chapters.SIMILARITY_MIN: float = 0.72` e `pdf_chapters.ANCHOR_COVERAGE_MIN: float = 0.80`.

- [ ] **Step 1: Write the failing tests**

```python
import pymupdf
from backend.app.pdf_chapters import anchor_outline, modal_body_size, normalize

def _linha(page, text, size, y, bold=False, h=800.0):
    from backend.app.models import Line
    return Line(page=page, text=text, size=size, bold=bold, italic=False,
                bbox=(72.0, y, 500.0, y + size), page_height=h, page_width=600.0,
                runs=[])

def test_normalize_remove_acentos_pontuacao_e_caixa():
    assert normalize("Capítulo 1 — Quadro geral!") == "capitulo 1 quadro geral"

def test_modal_body_size_usa_caracteres_nao_linhas():
    linhas = [_linha(0, "titulo", 20.0, 10)] + [_linha(0, "x" * 200, 10.0, 100 + i) for i in range(5)]
    assert modal_body_size(linhas) == 10.0

def test_ancora_entrada_de_outline_na_linha_correta():
    linhas = [_linha(0, "Prefácio", 22.0, 50), _linha(0, "corpo", 10.0, 120),
              _linha(1, "Capítulo Um", 22.0, 50), _linha(1, "corpo", 10.0, 120)]
    anchors = anchor_outline(linhas, [[1, "Prefácio", 1], [1, "Capítulo Um", 2]], 10.0)
    assert anchors == [(0, 1, "Prefácio"), (2, 1, "Capítulo Um")]

def test_reancora_quando_titulo_nao_casa_perfeitamente():
    linhas = [_linha(0, "Prefácio geral", 22.0, 50)]
    anchors = anchor_outline(linhas, [[1, "Prefácio geral da obra", 1]], 10.0)
    assert anchors and anchors[0][0] == 0

def test_descarta_entrada_sem_nenhuma_linha_na_pagina():
    linhas = [_linha(0, "corpo", 10.0, 120)]
    assert anchor_outline(linhas, [[1, "Inexistente", 5]], 10.0) == []

def test_entradas_duplicadas_nao_produzem_ancoras_repetidas():
    linhas = [_linha(0, "Capítulo Um", 22.0, 50), _linha(0, "corpo", 10.0, 120)]
    anchors = anchor_outline(linhas, [[1, "Capítulo Um", 1], [1, "Capítulo Um", 1]], 10.0)
    assert len({i for i, _, _ in anchors}) == len(anchors)
    assert [i for i, _, _ in anchors] == sorted(i for i, _, _ in anchors)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pdf_chapters.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.app.pdf_chapters'`

- [ ] **Step 3: Implement**

`modal_body_size`: `Counter` somando `len(line.text)` por `round(line.size, 1)`; devolve o mais comum; `12.0` se vazio.

`anchor_outline`: para cada `(level, title, page_1based)` indexe os candidatos da página `page-1` com `bbox[1] < 0.6 * page_height`; `score = SequenceMatcher(None, normalize(title), normalize(line.text)).ratio()` + `0.15` se iguais + `0.10` se "cara de título" (`size > body_size*1.05 or bold`). Aceita `score >= SIMILARITY_MIN`. Garante **ordem monotônica** pelo índice da linha; quando a melhor escolha viola a ordem ou fica abaixo do limiar, **reancora** à primeira linha elegível da página com índice maior que a âncora anterior (só se `page >= página da âncora anterior`); se não houver, descarta a entrada. Devolve `[(line_index, level, title), ...]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pdf_chapters.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pdf_chapters.py tests/test_pdf_chapters.py
git commit -m "feat(parser): ancoragem de bookmarks com reancoragem e ordem monotônica"
```

---

### Task 4: Fallback heurístico de títulos — `pdf_chapters.py` (parte 2)

**Files:**
- Modify: `backend/app/pdf_chapters.py`
- Test: `tests/test_pdf_chapters.py`

**Interfaces:**
- Consumes: `normalize`, `modal_body_size`, `Anchor`, `Line`.
- Produces: `pdf_chapters.detect_headings(lines: list[Line], body_size: float) -> list[Anchor]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_heuristica_detecta_titulo_por_tamanho():
    linhas = [_linha(0, "Capítulo Um", 22.0, 40), _linha(0, "corpo do texto.", 10.0, 120)]
    det = detect_headings(linhas, 10.0)
    assert [(i, lv) for i, lv, _ in det] == [(0, 1)]

def test_heuristica_ignora_frase_do_corpo():
    linhas = [_linha(0, "Esta é uma frase normal do corpo do livro.", 10.0, 120)]
    assert detect_headings(linhas, 10.0) == []

def test_heuristica_ignora_numero_de_pagina():
    linhas = [_linha(0, "42", 10.0, 780, h=800.0)]
    assert detect_headings(linhas, 10.0) == []

def test_heuristica_detecta_capitulo_numerado_mesmo_sem_fonte_maior():
    linhas = [_linha(0, "CAPÍTULO 7", 10.0, 40), _linha(0, "corpo do texto.", 10.0, 120)]
    det = detect_headings(linhas, 10.0)
    assert det and det[0][1] == 1

def test_heuristica_detecta_subtitulo_bold_pequeno():
    linhas = [_linha(0, "Uma abordagem prática", 11.5, 40, bold=True),
              _linha(0, "corpo do texto.", 10.0, 120)]
    det = detect_headings(linhas, 10.0)
    assert det and det[0][1] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pdf_chapters.py -q -k heuristica`
Expected: FAIL — `NameError: name 'detect_headings' is not defined`

- [ ] **Step 3: Implement `detect_headings`**

Uma linha é candidata se `len(text) <= 90`; não está na banda de rodapé (`bbox[1] > 0.9 * page_height`); e (casa um dos padrões textuais **ou** `size >= body*1.25` **ou** (`size >= body*1.10` e (`bold` ou `text.isupper()`))). Padrões: `^(cap[íi]tulo|chapter|parte|part)\b`, `^\d+(\.\d+)*\s+\S`, `^(prefácio|introdução|conclusão|epílogo|apêndice|agradecimentos|bibliografia|índice|sumário)\b` (case-insensitive). Descarta título com menos de 3 caracteres ou composto só de dígitos. `level = 1` se `size >= body*1.25` ou casou padrão de capítulo/parte; senão `2`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pdf_chapters.py -q -k heuristica`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pdf_chapters.py tests/test_pdf_chapters.py
git commit -m "feat(parser): fallback heurístico de detecção de títulos"
```

---

### Task 5: Limpeza e junção de parágrafos — `pdf_chapters.py` (parte 3)

**Files:**
- Modify: `backend/app/pdf_chapters.py`
- Test: `tests/test_pdf_chapters.py`

**Interfaces:**
- Consumes: `Line`, `Paragraph`, `Run`, `Anchor`.
- Produces:
  - `pdf_chapters.is_page_number(text: str) -> bool`
  - `pdf_chapters.remove_running_lines(lines: list[Line], keep: set[int], *, remove_header: bool, remove_page_numbers: bool) -> list[Line]` — `keep` são os índices-âncora que nunca podem ser removidos.
  - `pdf_chapters.join_paragraphs(lines: list[Line]) -> list[Paragraph]`

- [ ] **Step 1: Write the failing tests**

```python
def test_is_page_number_reconhece_formatos():
    assert is_page_number("42") and is_page_number(" xii ") and is_page_number("Página 7")
    assert not is_page_number("O ano de 1842 foi decisivo")
    assert not is_page_number("Capítulo 42")

def test_remove_cabecalho_repetido_por_banda():
    linhas = [_linha(p, "Capítulo Um ■ Quadro geral", 10.0, 20, h=800.0) for p in range(4)]
    linhas += [_linha(p, "corpo", 10.0, 400, h=800.0) for p in range(4)]
    out = remove_running_lines(linhas, keep=set(), remove_header=True, remove_page_numbers=True)
    assert [l.text for l in out] == ["corpo"] * 4

def test_ancora_nunca_e_removida():
    linhas = [_linha(p, "Capítulo Um", 10.0, 20, h=800.0) for p in range(4)]
    out = remove_running_lines(linhas, keep={0}, remove_header=True, remove_page_numbers=True)
    assert len(out) == 1 and out[0].text == "Capítulo Um"

def test_toggles_desligados_preservam_tudo():
    linhas = [_linha(p, "42", 10.0, 780, h=800.0) for p in range(4)]
    out = remove_running_lines(linhas, keep=set(), remove_header=False, remove_page_numbers=False)
    assert len(out) == 4

def test_des_hifeniza_palavra_quebrada():
    linhas = [_linha(0, "transfor-", 10.0, 100), _linha(0, "macao social", 10.0, 112)]
    paras = join_paragraphs(linhas)
    assert paras[0].text == "transformacao social"

def test_remove_soft_hyphen():
    linhas = [_linha(0, "trans\u00adformação", 10.0, 100)]
    assert join_paragraphs(linhas)[0].text == "transformação"

def test_junta_paragrafo_entre_paginas():
    linhas = [_linha(0, "primeira parte", 10.0, 700, h=800.0),
              _linha(1, "segunda parte.", 10.0, 60, h=800.0)]
    assert join_paragraphs(linhas)[0].text == "primeira parte segunda parte."

def test_separa_paragrafos_por_espaco_vertical():
    linhas = [_linha(0, "um parágrafo.", 10.0, 100),
              _linha(0, "outro parágrafo.", 10.0, 200)]
    assert [p.text for p in join_paragraphs(linhas)] == ["um parágrafo.", "outro parágrafo."]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pdf_chapters.py -q -k "page_number or running or ancora or hifeniz or soft or paragrafo"`
Expected: FAIL — nome não definido

- [ ] **Step 3: Implement**

- `is_page_number`: casa `^\s*\d{1,4}\s*$`, `^\s*[ivxlcdm]{1,7}\s*$`, `^\s*p[áa]g(ina)?\.?\s*\d+\s*$` (case-insensitive).
- `remove_running_lines`: banda de topo `bbox[1] < 0.06 * page_height`, rodapé `bbox[3] > 0.93 * page_height`; para linhas em banda com `len(text) < 110`, conta páginas distintas com texto de similaridade `>= 0.9` (`SequenceMatcher`) **na mesma banda**; remove se `>= 3` páginas distintas. Remove numeração quando `remove_page_numbers`. Remove junk (`^(www\.|https?://|\S+@\S+|isbn|©|copyright|todos os direitos reservados)`, `len <= 120`). Nunca remove índice presente em `keep`.
- `join_paragraphs`: agrupa linhas consecutivas quando `round(size,1)` igual e `-2 <= gap <= max(1.8*size, 6.0)` e (`largura da anterior >= 0.8 * maior largura observada daquele tamanho` **ou** termina em hífen **ou** a página mudou e a anterior está nessa banda larga); ao juntar, se a última run termina em `-` e a próxima linha começa com minúscula não-acentuada, remove o hífen e concatena sem espaço; senão insere `Run(" ")`. Substitui `\u00ad` por vazio e colapsa espaços múltiplos.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pdf_chapters.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pdf_chapters.py tests/test_pdf_chapters.py
git commit -m "feat(parser): limpeza de cabeçalho/rodapé, des-hifenização e junção entre páginas"
```

---

### Task 6: Montagem, sanidade e `build_chapters` — `pdf_chapters.py` (parte 4)

**Files:**
- Modify: `backend/app/pdf_chapters.py`
- Test: `tests/test_pdf_chapters.py`

**Interfaces:**
- Consumes: tudo das Tasks 3–5.
- Produces:
  - `pdf_chapters.assemble_chapters(lines: list[Line], anchors: list[Anchor]) -> list[Chapter]`
  - `pdf_chapters.sanitize(chapters: list[Chapter], pages: int) -> tuple[list[Chapter], list[str]]`
  - `pdf_chapters.build_chapters(pdf_path: Path | str, *, remove_header: bool = True, remove_page_numbers: bool = True) -> tuple[list[Chapter], list[str]]`

- [ ] **Step 1: Write the failing tests**

```python
def test_assemble_fatia_entre_ancoras():
    linhas = [_linha(0, "Cap A", 20.0, 40), _linha(0, "texto A", 10.0, 100),
              _linha(0, "Cap B", 20.0, 200), _linha(0, "texto B", 10.0, 260)]
    chs = assemble_chapters(linhas, [(0, 1, "Cap A"), (2, 1, "Cap B")])
    assert [(c.title, c.level, [p.text for p in c.paragraphs]) for c in chs] == [
        ("Cap A", 1, ["texto A"]), ("Cap B", 1, ["texto B"])]

def test_sanitize_descarta_capitulo_vazio_com_aviso():
    from backend.app.models import Chapter
    chs = [Chapter("Vazio", 1, []), Chapter("Cheio", 1, [Paragraph.from_text("x")])]
    out, avisos = sanitize(chs, pages=10)
    assert [c.title for c in out] == ["Cheio"] and avisos

def test_sanitize_degrada_quando_explode_a_contagem():
    chs = [Chapter(f"C{i}", 1, [Paragraph.from_text("x")]) for i in range(200)]
    out, avisos = sanitize(chs, pages=20)
    assert len(out) <= 20 and any("conservadora" in a for a in avisos)

def test_build_chapters_pdf_sem_texto(tmp_path):
    import pymupdf
    p = tmp_path / "vazio.pdf"
    d = pymupdf.open(); d.new_page(); d.save(str(p)); d.close()
    chs, avisos = build_chapters(p)
    assert len(chs) == 1 and "sem texto" in " ".join(avisos).lower()

def test_build_chapters_usa_outline(make_bookmark_pdf):
    chs, avisos = build_chapters(make_bookmark_pdf)
    assert [c.title for c in chs] == ["Capítulo Um", "Capítulo Dois"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_pdf_chapters.py -q -k "assemble or sanitize or build_chapters"`
Expected: FAIL — nome não definido

- [ ] **Step 3: Implement**

`assemble_chapters`: fatia `join_paragraphs` do bloco de linhas entre âncoras; a linha da âncora é removida do corpo; `level` limitado a `1..3`.

`sanitize`: descarta capítulos sem parágrafos (aviso `"N capítulos sem conteúdo foram descartados."`); se zerar, devolve um capítulo único com o texto integral; degrada (`"Detecção instável; usada a estratégia conservadora."`) quando `len(nível 1) > 60` **ou** `len(total) > max(50, pages / 1.5)` **ou** mais de 50 % dos capítulos têm < 2 parágrafos — na degradação, mantém só âncoras de nível 1 (se já for esse o caso, mantém um capítulo por página, `title=f"Página {n}"`).

`build_chapters`: `extract_lines` → se `outline` e cobertura `>= ANCHOR_COVERAGE_MIN` usa `anchor_outline`, senão `detect_headings` + aviso `"PDF sem sumário embutido: capítulos detectados por heurística de fontes."`; `remove_running_lines` com `keep={índices das âncoras}`; `assemble_chapters`; `sanitize`. Se as linhas estiverem vazias, devolve `([Chapter("Texto", 1, [])], ["PDF sem texto extraível."])`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_pdf_chapters.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/pdf_chapters.py tests/test_pdf_chapters.py
git commit -m "feat(parser): montagem de capítulos com validação de sanidade"
```

---

### Task 7: Aceitação com os PDFs reais (checkpoint da Fase 1)

**Files:**
- Create: `tests/test_acceptance_real_pdfs.py`
- Modify: `pyproject.toml` (registrar o marcador `acceptance`)

**Interfaces:**
- Consumes: `build_chapters`.
- Produces: nada (teste).

- [ ] **Step 1: Write the acceptance test**

Os nomes reais dos arquivos têm sufixo `(z-library.sk, 1lib.sk, z-lib.sk)`, então
resolva o caminho por **glob por prefixo**, nunca por nome exato.

```python
import os
from pathlib import Path

import pytest

from backend.app.pdf_chapters import build_chapters, normalize

DIR = os.getenv("KDP_REAL_PDFS_DIR")

pytestmark = [pytest.mark.acceptance,
              pytest.mark.skipif(not DIR or not Path(DIR).is_dir(),
                                 reason="KDP_REAL_PDFS_DIR não definido")]


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
    import pymupdf

    doc = pymupdf.open(_pdf("Como o Linux Funciona"))
    esperados = {normalize(t) for lvl, t, _ in doc.get_toc() if lvl == 1}
    doc.close()
    chs, _ = build_chapters(_pdf("Como o Linux Funciona"))
    obtidos = {normalize(c.title) for c in chs if c.level == 1}
    assert len(obtidos & esperados) / max(1, len(esperados)) >= 0.95
```

Registre em `pyproject.toml`, na seção `[tool.pytest.ini_options]`:
`markers = ["acceptance: testes que exigem PDFs reais (KDP_REAL_PDFS_DIR)"]`.

- [ ] **Step 2: Run the acceptance test**

Run: `KDP_REAL_PDFS_DIR="$HOME/Downloads" python3 -m pytest tests/test_acceptance_real_pdfs.py -q -m acceptance`
Expected: PASS nos três testes.

- [ ] **Step 3: Registrar os números medidos no README (temporário)**

Anote no commit a contagem real obtida para cada livro (ex.: `PT: 20 nível 1 / 211 total`). Se algum teste falhar, **ajuste os limiares do parser**, não o teste: o teste codifica o critério de aceite CA1–CA3 da spec.

- [ ] **Step 4: Commit**

```bash
git add tests/test_acceptance_real_pdfs.py pyproject.toml
git commit -m "test(parser): aceitação com PDFs reais (CA1-CA3)"
```

---

## Fase 2 — Exportação EPUB

### Task 8: Montagem do EPUB 3 — `kdp_epub.py` (parte 1)

**Files:**
- Create: `backend/app/kdp_epub.py`
- Test: `tests/test_kdp_epub.py`

**Interfaces:**
- Consumes: `Chapter`, `Paragraph`, `Run`.
- Produces: `kdp_epub.build_epub(chapters: list[Chapter], title: str, author: str, language: str, out_path: Path) -> Path`.

- [ ] **Step 1: Write the failing tests**

```python
import re, zipfile
from backend.app.kdp_epub import build_epub
from backend.app.models import Chapter, Paragraph, Run

def _caps():
    return [Chapter("Capítulo & Um", 1, [Paragraph.from_text("Corpo."),
                                         Paragraph([Run("com "), Run("ênfase", italic=True)])]),
            Chapter("Seção", 2, [Paragraph.from_text("Sub.")])]

def test_epub_mimetype_primeiro_e_sem_compressao(tmp_path):
    out = build_epub(_caps(), "Título", "Autor", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        infos = zf.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert zf.read("mimetype") == b"application/epub+zip"

def test_epub_tem_nav_e_ncx_e_todo_manifest_existe(tmp_path):
    out = build_epub(_caps(), "Título", "Autor", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        nomes = set(zf.namelist())
        assert {"EPUB/nav.xhtml", "EPUB/toc.ncx", "META-INF/container.xml",
                "EPUB/content.opf"} <= nomes
        opf = zf.read("EPUB/content.opf").decode()
        assert all("EPUB/" + h in nomes for h in re.findall(r'href="([^"]+)"', opf))

def test_epub_escapa_caracteres_especiais(tmp_path):
    out = build_epub(_caps(), "Título <b>&", "Autor", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        html = zf.read("EPUB/cap1.xhtml").decode()
    assert "Capítulo &amp; Um" in html
    assert "<em>ênfase</em>" in html

def test_epub_aceita_emoji_aspas_e_apostrofo_no_titulo(tmp_path):
    caps = [Chapter('Aspas "duplas" & \'simples\' 📚 🎉', 1, [Paragraph.from_text("ok")])]
    out = build_epub(caps, 'Livro "X" 📚', "A & B", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        html = zf.read("EPUB/cap1.xhtml").decode()
        nav = zf.read("EPUB/nav.xhtml").decode()
    assert "&#x27;" in html or "&quot;" in html or "&amp;" in html
    assert "📚" in html and "📚" in nav

def test_epub_toc_aninha_por_nivel(tmp_path):
    out = build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "l.epub")
    with zipfile.ZipFile(out) as zf:
        ncx = zf.read("EPUB/toc.ncx").decode()
    assert ncx.count("<navPoint") >= 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_kdp_epub.py -q`
Expected: FAIL — módulo inexistente

- [ ] **Step 3: Implement `build_epub`**

Use `ebooklib` (`epub.EpubBook`, `EpubHtml`, `EpubNav`, `EpubNcx`, `write_epub`). Configure: `set_identifier(f"kdp-{uuid.uuid5(uuid.NAMESPACE_DNS, f'{title}|{author}').hex[:12]}")`, `set_title`, `set_language(language)`, `add_author`. Crie `titulo.xhtml` e `cap{N}.xhtml` com `html.escape` em títulos e no texto das runs — runs com `italic=True` viram `<em>…</em>`, `bold=True` viram `<strong>…</strong>`. CSS `style/kdp.css` com o conteúdo exato da §8.1 da spec. `book.toc` como tupla de `EpubHtml` (o ebooklib aninha por `book.toc`; para aninhar de verdade, monte a lista como `[(EpubHtml_H1, [EpubHtml_H2, ...]), ...])` a partir dos `level`s).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_kdp_epub.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/kdp_epub.py tests/test_kdp_epub.py
git commit -m "feat(epub): montagem de EPUB 3 com nav, ncx e TOC aninhada"
```

---

### Task 9: Validação e escrita atômica — `kdp_epub.py` (parte 2)

**Files:**
- Modify: `backend/app/kdp_epub.py`
- Test: `tests/test_kdp_epub.py`

**Interfaces:**
- Consumes: `build_epub` (Task 8).
- Produces:
  - `kdp_epub.EpubValidationError(RuntimeError)`
  - `kdp_epub.validate_epub(path: Path) -> None`
  - `kdp_epub.build_epub(...)` passa a ser **atômico**: monta num temporário, valida e só então `os.replace`. A montagem crua vira o auxiliar privado `_write_epub_file(...)`. A assinatura pública não muda, então os testes da Task 8 continuam válidos.

- [ ] **Step 1: Write the failing tests**

```python
def test_validate_epub_aceita_epub_valido(tmp_path):
    out = build_epub(_caps(), "T", "A", "pt-BR", tmp_path / "ok.epub")
    validate_epub(out)  # não levanta

def test_validate_epub_rejeita_zip_inconsistente(tmp_path):
    ruim = tmp_path / "ruim.epub"
    with zipfile.ZipFile(ruim, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", "<container/>")
        zf.writestr("EPUB/content.opf", '<package><manifest>'
                    '<item href="cap1.xhtml"/></manifest></package>')
    with pytest.raises(EpubValidationError, match="cap1.xhtml"):
        validate_epub(ruim)

def test_validate_epub_rejeita_mimetype_comprimido(tmp_path):
    ruim = tmp_path / "ruim.epub"
    with zipfile.ZipFile(ruim, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", "<container/>")
        zf.writestr("EPUB/content.opf", '<package><manifest/></package>')
        zf.writestr("EPUB/nav.xhtml", "<html><body/></html>")
        zf.writestr("EPUB/toc.ncx", "<ncx/>")
    with pytest.raises(EpubValidationError, match="mimetype"):
        validate_epub(ruim)

def test_falha_de_validacao_nao_cria_destino(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.kdp_epub.validate_epub",
                        lambda p: (_ for _ in ()).throw(EpubValidationError("boom")))
    destino = tmp_path / "saida.epub"
    with pytest.raises(EpubValidationError):
        build_epub(_caps(), "T", "A", "pt-BR", destino)
    assert not destino.exists()
    assert not list(tmp_path.glob("*.tmp-*"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_kdp_epub.py -q -k "validate or falha"`
Expected: FAIL — `validate_epub` não definido

- [ ] **Step 3: Implement**

`validate_epub`: abre o ZIP; exige `mimetype` como primeira entrada com `compress_type == ZIP_STORED` e conteúdo `application/epub+zip`; exige `META-INF/container.xml`, `EPUB/content.opf`, `EPUB/nav.xhtml`, `EPUB/toc.ncx`; extrai todos os `href` de `content.opf` e exige que existam em `EPUB/<href>` (acumulando os ausentes na mensagem); exige `properties="nav"` no item do nav e que todo `idref` do spine exista no manifest. Cada falha levanta `EpubValidationError` com mensagem em pt-BR que cita o item problemático.

`build_epub` passa a: escrever no temporário `out_path.with_name(f"{out_path.stem}.tmp-{uuid4().hex}{out_path.suffix}")` via `_write_epub_file`; chamar `validate_epub(tmp)`; `os.replace(tmp, out_path)`. Em `except`, `tmp.unlink(missing_ok=True)` e re-levanta. O diretório do temporário é o mesmo do destino, para o `os.replace` ser atômico.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_kdp_epub.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/kdp_epub.py tests/test_kdp_epub.py
git commit -m "feat(epub): validação obrigatória e escrita atômica (CA4, CA5)"
```

---

## Fase 3 — Tradução

### Task 10: Camada de LLM resiliente — `llm.py`

**Files:**
- Modify (reescrever): `backend/app/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `config.get_settings`, `config.load_env`.
- Produces:
  - `llm.LLMError(RuntimeError)`
  - `llm.provider_name() -> str` (`"openai" | "gemini" | "offline"`)
  - `llm.is_configured() -> bool`
  - `llm.model_candidates() -> list[str]`
  - `llm.chat(system: str, user: str, *, model: str | None = None, temperature: float = 0.3, sleep=time.sleep) -> str`
  - `llm.reset_model_cache() -> None` (usado pelos testes)

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from backend.app import llm

def test_provider_offline_sem_chaves(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert llm.provider_name() == "offline" and not llm.is_configured()

def test_candidatos_incluem_primario_e_fallbacks(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-flash-latest")
    config.get_settings.cache_clear(); llm.reset_model_cache()
    assert llm.model_candidates()[0] == "gemini-flash-latest"
    assert "gemini-3.1-flash-lite" in llm.model_candidates()

def test_chat_faz_fallback_quando_modelo_falha(monkeypatch):
    chamados = []
    def fake_call(model, system, user, temperature):
        chamados.append(model)
        if model == "gemini-flash-latest":
            raise llm.LLMError("503 UNAVAILABLE")
        return "traduzido"
    monkeypatch.setattr(llm, "_call_once", fake_call)
    monkeypatch.setattr(llm, "_candidates", lambda: ["gemini-flash-latest", "gemini-3.1-flash-lite"])
    assert llm.chat("s", "u", sleep=lambda s: None) == "traduzido"
    assert chamados == ["gemini-flash-latest", "gemini-3.1-flash-lite"]

def test_chat_esgota_tentativas_e_levanta_llmerror(monkeypatch):
    monkeypatch.setattr(llm, "_call_once",
                        lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("503")))
    monkeypatch.setattr(llm, "_candidates", lambda: ["m1", "m2"])
    with pytest.raises(llm.LLMError, match="Nenhum modelo"):
        llm.chat("s", "u", sleep=lambda s: None)

def test_chat_offline_levanta_erro_explicito(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    llm.reset_model_cache()
    with pytest.raises(llm.LLMError, match="chave"):
        llm.chat("s", "u")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_llm.py -q`
Expected: FAIL — `ImportError`/atributo inexistente

- [ ] **Step 3: Implement**

- `_candidates()`: se `TRANSLATION_MODEL` definido, devolve `[esse]`; senão primário (`GEMINI_MODEL` quando provider gemini, `gpt-4o-mini` quando openai) + `fallback_models` apenas no provider gemini.
- `_call_once(model, system, user, temperature)`: cria o cliente via `make_client()` com `timeout=settings.llm_timeout_seconds` e `max_retries=0`; uma chamada `chat.completions.create`; converte qualquer exceção do SDK em `llm.LLMError(str(exc))`.
- `chat(...)`: se `provider_name() == "offline"` levanta `LLMError("Nenhuma chave de IA configurada (OPENAI_API_KEY/GEMINI_API_KEY).")`; itera os candidatos; para cada um tenta `settings.llm_max_retries` vezes com backoff `sleep(1, 2, 4)`; no primeiro sucesso guarda o modelo em cache (`_resolved_model`) para as chamadas seguintes; se todos falharem levanta `LLMError("Nenhum modelo respondeu (…). Verifique GEMINI_MODEL/GEMINI_MODEL_FALLBACKS.")`.
- Mantenha `make_client()` (usado por `chat`), com a mesma lógica de provider OpenAI-compatible/Gemini da versão atual, mas adicionando `timeout` e `max_retries=0`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_llm.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm.py tests/test_llm.py
git commit -m "feat(llm): timeout, retry e cadeia de fallback de modelos (CA7)"
```

---

### Task 11: Chunking e preservação estrutural — `translate.py` (parte 1)

**Files:**
- Create: `backend/app/translate.py`
- Test: `tests/test_translate.py`

**Interfaces:**
- Consumes: `Chapter`, `Paragraph`, `llm`.
- Produces:
  - `translate.LANG_NAMES: dict[str,str]`, `translate.DEFAULT_TARGET_LANG = "pt-BR"`, `translate.DEFAULT_SOURCE_LANG = "auto"`
  - `translate.lang_name(code: str | None) -> str`
  - `translate.split_chunks(text: str, limit: int) -> list[str]`
  - `translate.build_system_prompt(source_lang, target_lang, *, title, chapter_title) -> str`
  - `translate.translate_chapter(chapter: Chapter, *, title: str, source_lang: str, target_lang: str, model: str | None, chunk_chars: int, warn: Callable[[str], None]) -> Chapter`

- [ ] **Step 1: Write the failing tests**

Cabeçalho do arquivo:

```python
import pytest

from backend.app.llm import LLMError
from backend.app.models import Chapter, Paragraph
from backend.app.translate import (
    build_system_prompt,
    split_chunks,
    translate_chapter,
)
```

```python
def test_split_chunks_sem_perda_nem_sobreposicao():
    texto = ("Parágrafo um. " * 40 + "\n\n") * 5
    chunks = split_chunks(texto, 300)
    assert "".join(chunks) == texto
    assert all(len(c) <= 300 for c in chunks)

def test_split_chunks_corta_em_fronteira_de_paragrafo():
    texto = "A" * 200 + "\n\n" + "B" * 200
    chunks = split_chunks(texto, 300)
    assert chunks[0].endswith("A" * 200)

def test_split_chunks_limite_invalido():
    import pytest
    with pytest.raises(ValueError):
        split_chunks("x", 0)

def test_prompt_menciona_destino_e_contexto():
    p = build_system_prompt("en", "pt-BR", title="Livro X", chapter_title="Cap 1")
    assert "portugues brasileiro" in p and "Livro X" in p and "Cap 1" in p

def test_traducao_preserva_contagem_de_paragrafos(monkeypatch):
    monkeypatch.setattr("backend.app.translate._translate_text",
                        lambda t, **k: t.upper())
    from backend.app.models import Chapter, Paragraph
    ch = Chapter("T", 1, [Paragraph.from_text("alpha"), Paragraph.from_text("beta")])
    out = translate_chapter(ch, title="L", source_lang="en", target_lang="pt-BR",
                            model=None, chunk_chars=6000, warn=lambda m: None)
    assert [p.text for p in out.paragraphs] == ["ALPHA", "BETA"]

def test_refaz_paragrafo_a_paragrafo_quando_o_lote_desalinha(monkeypatch):
    chamadas = []
    def fake(text, **k):
        chamadas.append(text)
        if "\n\n" in text:
            return "só um parágrafo"
        return text.upper()
    monkeypatch.setattr("backend.app.translate._translate_text", fake)
    ch = Chapter("T", 1, [Paragraph.from_text("alpha"), Paragraph.from_text("beta")])
    out = translate_chapter(ch, title="L", source_lang="en", target_lang="pt-BR",
                            model=None, chunk_chars=6000, warn=lambda m: None)
    assert [p.text for p in out.paragraphs] == ["ALPHA", "BETA"]
    assert len(chamadas) == 3  # 1 lote + 2 parágrafos

def test_conteudo_preservado_quando_a_traducao_falha(monkeypatch):
    def fake(text, **k):
        raise LLMError("503")
    monkeypatch.setattr("backend.app.translate._translate_text", fake)
    avisos = []
    ch = Chapter("T", 1, [Paragraph.from_text("alpha")])
    out = translate_chapter(ch, title="L", source_lang="en", target_lang="pt-BR",
                            model=None, chunk_chars=6000, warn=avisos.append)
    assert [p.text for p in out.paragraphs] == ["alpha"] and avisos
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_translate.py -q`
Expected: FAIL — módulo inexistente

- [ ] **Step 3: Implement**

- `split_chunks`: fronteiras preferenciais `\n\n`, depois `(?<=[.!?…])\s`, depois `\s`; aceita o corte só se ele preservar mais de 50 % da janela, senão corta no limite; garante avanço (`end > start`); nunca perde caractere.
- `_translate_text(text, *, system, model) -> str` — wrapper fino sobre `llm.chat(system, text, model=model)`, isolado para facilitar monkeypatch.
- `translate_chapter`: achata os parágrafos em texto (`"\n\n".join(p.text ...)`); para cada chunk, chama `_translate_text`; valida `len(out.split("\n\n")) == len(src.split("\n\n"))`; se divergir, refaz **parágrafo a parágrafo** naquele chunk; se um parágrafo falhar, mantém o original e chama `warn(...)`. Devolve `Chapter` com os mesmos `title`/`level` e um `Paragraph.from_text` por parágrafo.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_translate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/translate.py tests/test_translate.py
git commit -m "feat(translate): chunking e preservação estrutural com reparo parágrafo a parágrafo"
```

---

### Task 12: Paralelismo, progresso e cancelamento — `translate.py` (parte 2)

**Files:**
- Modify: `backend/app/translate.py`
- Test: `tests/test_translate.py`

**Interfaces:**
- Consumes: `translate_chapter`, `split_chunks`.
- Produces: `translate.translate_chapters(chapters: list[Chapter], *, title: str, source_lang: str, target_lang: str, model: str | None, workers: int, chunk_chars: int, progress: Callable[[int, str], None] | None = None, cancel: threading.Event | None = None) -> tuple[list[Chapter], list[str]]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_numero_de_chamadas_proporcional_a_chunks_nao_a_paragrafos(monkeypatch):
    chamadas = []
    def fake(text, **k):
        chamadas.append(text)
        return text.upper()
    monkeypatch.setattr("backend.app.translate._translate_text", fake)
    chs = [Chapter(f"C{i}", 1, [Paragraph.from_text(f"p{j}") for j in range(50)]) for i in range(3)]
    out, avisos = translate_chapters(chs, title="L", source_lang="en", target_lang="pt-BR",
                                     model=None, workers=1, chunk_chars=6000)
    assert len(chamadas) == 3          # 1 por capítulo, não 150
    assert len(out) == 3 and not avisos

def test_progresso_e_reportado(monkeypatch):
    monkeypatch.setattr("backend.app.translate._translate_text", lambda t, **k: t)
    vistos = []
    chs = [Chapter(f"C{i}", 1, [Paragraph.from_text("x" * 4000)]) for i in range(4)]
    translate_chapters(chs, title="L", source_lang="en", target_lang="pt-BR", model=None,
                       workers=2, chunk_chars=2000,
                       progress=lambda p, msg: vistos.append(p))
    assert vistos and vistos == sorted(vistos) and vistos[-1] == 100

def test_cancelamento_interrompe(monkeypatch):
    import threading
    monkeypatch.setattr("backend.app.translate._translate_text", lambda t, **k: t)
    ev = threading.Event()
    def prog(p, msg):
        if p >= 30:
            ev.set()
    chs = [Chapter(f"C{i}", 1, [Paragraph.from_text("x" * 9000)]) for i in range(6)]
    with pytest.raises(CancelledError):
        translate_chapters(chs, title="L", source_lang="en", target_lang="pt-BR", model=None,
                           workers=1, chunk_chars=1000, progress=prog, cancel=ev)

def test_falha_de_um_capitulo_nao_aborta_os_outros(monkeypatch):
    def fake(text, **k):
        if "BOM" in text:
            raise LLMError("503")
        return text.upper()
    monkeypatch.setattr("backend.app.translate._translate_text", fake)
    chs = [Chapter("A", 1, [Paragraph.from_text("ok")]),
           Chapter("B", 1, [Paragraph.from_text("BOM falha")]),
           Chapter("C", 1, [Paragraph.from_text("ok2")])]
    out, avisos = translate_chapters(chs, title="L", source_lang="en", target_lang="pt-BR",
                                     model=None, workers=1, chunk_chars=6000)
    assert len(out) == 3
    assert out[1].paragraphs[0].text == "BOM falha"   # original preservado
    assert any("B" in a or "trecho" in a for a in avisos)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_translate.py -q -k "chamadas or progresso or cancelamento or aborta"`
Expected: FAIL — nome não definido

- [ ] **Step 3: Implement**

Defina `translate.CancelledError(RuntimeError)`. Achate as unidades de trabalho como `(chapter_index, chunk_index, chunk_text)`. Execute com `concurrent.futures.ThreadPoolExecutor(max_workers=workers)` usando **janela deslizante**: mantenha no máximo `workers` futuros em voo e, antes de submeter cada novo chunk, verifique `cancel.is_set()`; se setado, cancele os futuros pendentes e levante `CancelledError`. O incremento de `concluidos` e a chamada a `progress` acontecem **sob o mesmo `threading.Lock`** (mesmo lock que acumula avisos), garantindo que a sequência de percentuais seja não decrescente mesmo com completions fora de ordem. `progress(pct, msg)` com `pct = int(100 * concluidos / total)` e `msg = f"Traduzindo {concluidos}/{total}"`. Falha de um chunk após o reparo parágrafo-a-parágrafo → mantém o original e gera aviso `"Capítulo {title}: trecho {k} mantido no idioma original."`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_translate.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/translate.py tests/test_translate.py
git commit -m "feat(translate): paralelismo, progresso real e cancelamento (CA6)"
```

---

## Fase 4 — Jobs e API

### Task 13: `JobStore` — `jobs.py`

**Files:**
- Create: `backend/app/jobs.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes: `Settings`, `JobState`, `Chapter`.
- Produces:
  - `jobs.JobStore(settings: Settings)` com `create(*, title, author, language, source_name, translated) -> JobState`, `get(job_id) -> JobState | None`, `update(job_id, **fields) -> None`, `submit(job_id, fn: Callable[[JobState], None]) -> None`, `cancel(job_id) -> bool`, `delete(job_id) -> bool`, `prune() -> None`, `views(job_id) -> list[ChapterView]`.
  - `jobs.out_path_for(job, fmt: str) -> Path` — nome `{slug}-{job_id}-{n}.{fmt}` único em `output/`.

- [ ] **Step 1: Write the failing tests**

```python
def test_create_e_get(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path))
    job = store.create(title="Livro", author="A", language="pt-BR",
                       source_name="f.pdf", translated=False)
    assert job.status == "queued" and store.get(job.id) is job

def test_prune_remove_expirados(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path, job_ttl_seconds=0))
    job = store.create(title="t", author="a", language="pt-BR", source_name="f.pdf", translated=False)
    job.created_at -= 10
    store.prune()
    assert store.get(job.id) is None

def test_prune_respeita_job_max(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path, job_max=2))
    ids = [store.create(title="t", author="a", language="pt-BR", source_name="f.pdf",
                        translated=False).id for _ in range(4)]
    store.prune()
    assert len([i for i in ids if store.get(i)]) == 2

def test_cancel_e_delete(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path))
    job = store.create(title="t", author="a", language="pt-BR", source_name="f.pdf", translated=False)
    assert store.cancel(job.id) and job.cancel.is_set()
    assert store.delete(job.id) and store.get(job.id) is None

def test_submit_roda_em_background_e_atualiza_estado(tmp_path, settings):
    store = JobStore(settings(output_dir=tmp_path, job_workers=1))
    job = store.create(title="t", author="a", language="pt-BR", source_name="f.pdf", translated=False)
    done = threading.Event()
    def work(j):
        store.update(j.id, status="done", progress=100)
        done.set()
    store.submit(job.id, work)
    assert done.wait(5)
    assert store.get(job.id).status == "done"

def test_views_traz_metadados_sem_texto_completo(tmp_path, settings):
    from backend.app.models import Chapter, Paragraph
    store = JobStore(settings(output_dir=tmp_path))
    job = store.create(title="t", author="a", language="pt-BR", source_name="f.pdf", translated=False)
    store.update(job.id, chapters=[Chapter("Cap", 1, [Paragraph.from_text("a b c")])])
    v = store.views(job.id)[0]
    assert v.title == "Cap" and v.words == 3 and v.preview.startswith("a b c")
```

A fixture `settings` em `tests/conftest.py` deve devolver uma função que cria um `Settings` (definido na Task 1, que já inclui `output_dir`) com overrides via `dataclasses.replace`, aceitando `output_dir`, `job_ttl_seconds`, `job_max` e `job_workers`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_jobs.py -q`
Expected: FAIL — módulo inexistente

- [ ] **Step 3: Implement**

`JobStore` guarda `dict[str, JobState]` sob `threading.RLock`, possui um `ThreadPoolExecutor(max_workers=settings.job_workers)` criado no `__init__`. `submit` faz `executor.submit(fn, job)` envolvendo em `try/except` que grava `status="error"` e `error=str(exc)`. `prune` remove por TTL e por `job_max` (mais antigos primeiro) e apaga os `output_paths` dos removidos. `views` monta `ChapterView` com `preview` = primeiros 200 caracteres do primeiro parágrafo.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_jobs.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs.py tests/test_jobs.py tests/conftest.py backend/app/config.py
git commit -m "feat(jobs): JobStore thread-safe com progresso, cancelamento e TTL"
```

---

### Task 14: API — `main.py`

**Files:**
- Modify (reescrever): `backend/app/main.py`
- Test: `tests/test_api.py` (reescrever)

**Interfaces:**
- Consumes: `config`, `jobs`, `pdf_chapters`, `translate`, `kdp_epub`, `llm`.
- Produces: as rotas da §9 da spec.

- [ ] **Step 1: Write the failing tests**

Cubra, no mínimo:

```python
def test_health(client): ...
def test_config_endpoint(client): ...            # provider, fallback_models, max_upload_mb
def test_criar_job_e_acompanhar(client, pdf_bytes):
    r = client.post("/api/jobs", files={"file": ("l.pdf", pdf_bytes, "application/pdf")},
                    data={"title": "L", "author": "A"})
    assert r.status_code == 201 and r.json()["job_id"]
    job_id = r.json()["job_id"]
    for _ in range(50):
        s = client.get(f"/api/jobs/{job_id}").json()
        if s["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert s["status"] == "done" and s["progress"] == 100
    assert s["chapters"] and "paragraphs" not in s["chapters"][0]

def test_detalhe_de_capitulo_traz_paragrafos(client, pdf_bytes): ...
def test_export_gera_epub_valido(client, pdf_bytes): ...   # baixa e chama validate_epub
def test_export_com_edicao_de_titulo_e_exclusao(client, pdf_bytes): ...
def test_job_inexistente_404(client): ...
def test_arquivo_nao_pdf_400(client): ...
def test_upload_grande_413(client, pdf_bytes, monkeypatch): ...
def test_pdf_sem_texto_422(client, make_pdf): ...          # PDF escaneado (Task 7 do Review Focus 1)
def test_cancelar_job(client, pdf_bytes): ...
def test_spa_servida(client): ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_api.py -q`
Expected: FAIL

- [ ] **Step 3: Implement `main.py`**

Rotas exatamente como a §9 da spec. `POST /api/jobs` grava o upload em `tempfile`, cria o job, e submete ao store um pipeline que: `update(status="parsing", stage="Lendo PDF…", progress=5)` → `build_chapters` → atualiza `chapters`/`warnings` → se `translated`: `update(status="translating", progress=50)` e chama `translate_chapters(..., progress=lambda p, m: store.update(job.id, progress=50 + p // 2, message=m), cancel=job.cancel)` → `update(status="done", progress=100, stage="Concluído")`. `CancelledError` → `status="cancelled"`, `"Cancelado."`. Nenhum arquivo é gerado nesse estágio (a exportação acontece sob demanda em `/export`), o que também garante o Review Focus 5 (cancelar não deixa arquivo parcial).

Monte `/static` e `/download` apontando para `settings.output_dir` a partir do nome do arquivo (validar basename, sem traversal), e o SPA por último com `StaticFiles(html=True)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py tests/test_api.py
git commit -m "feat(api): jobs assíncronos, progresso real, cancelamento e exportação com edições (CA8)"
```

---

## Fase 5 — Interface

### Task 15: Marcação e estilo da SPA em 3 passos

**Files:**
- Modify (reescrever): `static/index.html`, `static/styles.css`
- Keep: `static/vendor/tailwind.js`

**Interfaces:**
- Consumes: nada.
- Produces: os IDs que `app.js` consome — `#api-status`, `#dz-file`, `#file-input`, `#inp-title`, `#inp-author`, `#tg-header`, `#tg-pagenum`, `#tg-translate`, `#tr-opts`, `#tr-from`, `#tr-model`, `#btn-start`, `#step-1`, `#step-2`, `#step-3`, `#progress-bar`, `#progress-msg`, `#btn-cancel`, `#warn-box`, `#chapters-list`, `#chapter-reader`, `#btn-export`, `#status-msg`, `#toast-root`.

- [ ] **Step 1: Reescrever a marcação**

Mantenha a linguagem visual atual (paleta violeta/âmbar, `glass`, `gradient-text`, `blob`) e o Tailwind local. Substitua as 4 abas por uma única seção com os 3 passos; remova **todo** markup de wizard, biblioteca, capa, DOCX e "modo demonstração" (`#btn-demo-convert`, `#btn-demo-book`, `#lib-*`, `#book-*`, `#cover-*`, `#btn-dl-docx`, `#btn-print`).

- [ ] **Step 2: Ajustar `styles.css`**

Remova estilos órfãos das telas removidas; mantenha `glass`, `progress-*`, `toggle`, `dropzone`, `anim-*`, `paper`. Adicione `.chapter-row.excluded { opacity:.45 }` e um estado `[aria-busy="true"]` para os botões.

- [ ] **Step 3: Verificar que não sobrou referência às telas removidas**

Run: `grep -nE 'lib-|book-|cover-|btn-demo|btn-print|docx' static/index.html static/styles.css`
Expected: nenhuma linha

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/styles.css
git commit -m "feat(ui): marcação enxuta em 3 passos, sem wizard/biblioteca/capa/DOCX"
```

---

### Task 16: Lógica da SPA — `app.js`

**Files:**
- Modify (reescrever): `static/app.js`
- Modify: `package.json` (mantém `node --check static/app.js` no `check`)

**Interfaces:**
- Consumes: a API da §9 e os IDs da Task 15.

- [ ] **Step 1: Escrever a lógica**

- `checkApi()` → `GET /api/health`; exibe provider via `GET /api/config`; desabilita `#tg-translate` com aviso quando `configured === false`.
- `startJob()` → `POST /api/jobs` com FormData; guarda `jobId`; vai para o passo 2; inicia `poll()`.
- `poll()` → `setInterval` de 800 ms em `GET /api/jobs/{id}`: atualiza `#progress-bar`, `#progress-msg`, `warnings`; em `done` chama `renderChapters()` e vai ao passo 3; em `error`/`cancelled` mostra a mensagem **real** e volta ao passo 1.
- `renderChapters()` → agrupa por `level === 1`; subníveis recolhíveis; renomear (input), ↑↓, incluir/excluir com cascata; carrega `GET /api/jobs/{id}/chapters/{i}` ao abrir a prévia.
- `exportEpub()` → `POST /api/jobs/{id}/export` com `{chapters:[{index,title,included}]}`; baixa o blob via `URL.createObjectURL`.
- `cancel()` → `POST /api/jobs/{id}/cancel`.
- Remova todo fallback que simule sucesso (`demoChapters`, `demoTranslate`, `exportLocal`); erros usam a mensagem do backend.
- Mantenha `escapeHtml`/`escapeAttr` e use-os em **todo** ponto que injeta texto do servidor em `innerHTML`.

- [ ] **Step 2: Validar sintaxe**

Run: `node --check static/app.js`
Expected: sem saída (sucesso)

- [ ] **Step 3: Verificar ausência de restos**

Run: `grep -nE 'demo|localStorage|/api/library|/api/ebook|docx' static/app.js`
Expected: nenhuma linha

- [ ] **Step 4: Commit**

```bash
git add static/app.js package.json
git commit -m "feat(ui): fluxo em 3 passos com progresso real e sem modo demonstração"
```

---

## Fase 6 — Limpeza, documentação e verificação final

### Task 17: Remover o escopo cortado e atualizar a documentação

**Files:**
- Delete: `backend/app/creator.py`, `backend/app/cover.py`, `backend/app/pdf_cleaner.py`, `backend/app/kdp_export.py`, `backend/app/translator.py`, `docs/GOOGLE_GEMINI.md`, `tests/test_kdp_export.py`, `tests/test_pdf_cleaner.py`, `tests/test_translator.py`
- Modify: `backend/requirements.txt` (remover `python-docx`), `pyproject.toml` (deps), `.env.example`, `backend/.env.example`, `README.md`, `run.sh` (manter `python-docx` fora da checagem de import)

- [ ] **Step 1: Remover arquivos e referências**

Run: `grep -rnE 'creator|cover|pdf_cleaner|kdp_export|translator|docx' backend/app tests/*.py static/*.js | grep -v test_acceptance`
Expected: nenhuma referência restante (ajuste o que aparecer)

- [ ] **Step 2: Rodar a suíte completa**

Run: `python3 -m pytest -q`
Expected: PASS, sem warnings de import

- [ ] **Step 3: Reescrever o README e o `.env.example`**

README com: objetivo (2 fluxos), como rodar, tabela de API, tabela de variáveis de ambiente (a §11 da spec), estrutura de arquivos, como rodar os testes (incluindo `KDP_REAL_PDFS_DIR`), limitações conhecidas (itálico no texto traduzido, OCR fora de escopo) e a nota de que o wizard/DOCX/Biblioteca/capa saíram de escopo. `.env.example` só com as variáveis da §11.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove escopo cortado e atualiza documentação"
```

---

### Task 18: Verificação final ponta a ponta

**Files:** nenhum (verificação).

- [ ] **Step 1: Suíte completa + aceitação real**

```bash
python3 -m pytest -q
KDP_REAL_PDFS_DIR="$HOME/Downloads" python3 -m pytest -q -m acceptance
```
Expected: PASS em ambas.

- [ ] **Step 2: Compilação e sintaxe**

```bash
python3 -m py_compile backend/app/*.py
node --check static/app.js
```
Expected: sem erros.

- [ ] **Step 3: Smoke test do servidor**

```bash
./run.sh &  # ou uvicorn em background
sleep 5
curl -s localhost:8000/api/health
curl -s localhost:8000/api/config
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/
```
Expected: `{"ok": true}`, JSON com `provider`, `200`.

- [ ] **Step 4: Conversão real de ponta a ponta pelo servidor**

Enviar um dos PDFs reais por `curl -F` para `/api/jobs`, acompanhar até `done`, exportar o EPUB e validá-lo:
```bash
python3 -c "from backend.app.kdp_epub import validate_epub; validate_epub('output/<arquivo>.epub'); print('EPUB válido')"
```
Expected: `EPUB válido`.

- [ ] **Step 5: Registrar os números reais e commitar**

Anote no README/mensagem final: capítulos detectados em cada livro, chamadas de LLM numa tradução de capítulo, tempo de conversão.

```bash
git add -A
git commit -m "test: verificação ponta a ponta e números medidos"
```

---

## Notas para quem executa

- **Ordem importa nas Fases 1–3**: cada tarefa consome a anterior. Não pule.
- **Nunca** deixe um teste chamar a API real de LLM; a fixture autouse `offline` em `tests/conftest.py` deve ser estendida para mockar `llm._call_once`.
- Se um limiar do parser precisar mudar para passar nos PDFs reais, mude o limiar **no código**, mantendo os critérios CA1–CA3 do teste.
- Commits por tarefa: cada um é um ponto de reversão.
