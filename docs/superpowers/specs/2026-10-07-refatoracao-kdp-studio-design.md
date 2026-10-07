# Refatoração do KDP Studio — PDF → EPUB no padrão KDP, com tradução para pt-BR

Data: 2026-10-07
Status: aguardando revisão do usuário
Baseline versionado: commit `957c3fa`

## 1. Contexto e problema

O KDP Studio (FastAPI + SPA sem build) já tem a lógica de negócio madura, mas
falha na entrega real. Diagnóstico feito com os PDFs reais do usuário em
`~/Downloads`:

| # | Problema | Evidência medida |
|---|---|---|
| P1 | **Detecção de capítulos inviável** | *Como o Linux Funciona* (417 págs.) → **600 "capítulos"**. Sumário, cabeçalhos de página e a 1ª linha do corpo viram títulos; números de página viram títulos (`"N"`, `"2 3 4 4 5"`). |
| P2 | **EPUB pode sair corrompido** | `output/livro-1791380554.epub`: o `content.opf` declara 119 recursos, o ZIP contém 23. Faltam `nav.xhtml`, `toc.ncx` e 99 capítulos. O KDP rejeita. |
| P3 | **Tradução inviável e travável** | 1 chamada de API **por parágrafo** (≈2.200 chamadas num livro de 400 págs.). Sem timeout, o SDK OpenAI **pendura indefinidamente** num 503. `GEMINI_MODEL=gemini-flash-latest` do `.env` responde 404/503 (modelo descontinuado). |
| P4 | **Interface enganosa** | Barra de progresso falsa (incrementa 3 % a cada 400 ms, sem relação com o servidor); fallback "modo demonstração" reporta sucesso quando o backend falha; aba "Criar eBook" com IA fora do objetivo declarado. |

### Fato que viabiliza a solução

Os dois PDFs reais têm **bookmarks embutidos** (`doc.get_toc()`): 211 entradas
(3 níveis) no livro PT e 25 entradas no livro EN. Um protótipo de ancoragem
TOC-primeiro ancorou **211/211** e **24/25** entradas a blocos de texto.

## 2. Objetivo

Um pipeline confiável e verificável:

```
PDF → capítulos corretos → (tradução opcional pt-BR) → EPUB 3 válido no padrão KDP
```

com progresso real e revisão de estrutura antes de exportar.

### 2.1 Critérios de aceite (mensuráveis)

| ID | Critério | Como verificar |
|---|---|---|
| CA1 | *Como o Linux Funciona* produz entre 10 e 40 capítulos de nível 1; nenhum título casa com numeração de página (`^\d+$`) ou tem menos de 3 caracteres | teste de aceitação com PDF real |
| CA2 | *Killing the Messiah* produz entre 15 e 40 capítulos de nível 1 | teste de aceitação com PDF real |
| CA3 | ≥ 95 % dos capítulos de nível 1 detectados no livro PT coincidem com títulos do outline do PDF | teste de aceitação |
| CA4 | Todo EPUB produzido passa na validação: 0 `href` do manifest ausentes, `nav.xhtml` e `toc.ncx` presentes, `mimetype` primeiro e não comprimido | `validate_epub` em teste |
| CA5 | Nenhum arquivo EPUB inválido é publicado em `output/` (escrita atômica + validação antes do `os.replace`) | teste que injeta falha na validação |
| CA6 | O número de chamadas de LLM numa tradução é proporcional a `ceil(caracteres / CHUNK_CHARS)`, **não** ao número de parágrafos | teste com cliente LLM falso contando chamadas |
| CA7 | Uma chamada de LLM que responde 503 com timeout esgotado **não** trava o job: há timeout, retry e fallback de modelo; esgotados, o job termina com erro explícito | teste com cliente que sempre levanta exceção |
| CA8 | `GET /api/jobs/{id}` reflete o progresso real do servidor e o job pode ser cancelado | teste de ciclo de vida do job |
| CA9 | `python3 -m pytest` verde e `python3 -m uvicorn backend.app.main:app` sobe e converte um PDF real de ponta a ponta | execução local |

## 3. Escopo

### 3.1 Dentro do escopo

- Novo motor de extração e detecção de capítulos (TOC-primeiro + fallback heurístico).
- Tradução em lote, paralela, com progresso real, timeout, retry e fallback de modelo.
- Exportador EPUB 3 KDP com escrita atômica e validação obrigatória.
- API de jobs assíncronos com polling, cancelamento e exportação com edições.
- SPA única em 3 passos, com progresso real e revisão de estrutura.
- Suíte de testes (unit + API + aceitação com PDFs reais).
- Atualização de `README.md`, `.env.example` e `docs/GOOGLE_GEMINI.md`.

### 3.2 Fora do escopo (removido do projeto)

- Aba e backend de criação de eBook com IA (`creator.py`, endpoints `/api/ebook/*` de criação, `/api/books/*`).
- Geração de capa (por IA ou procedural) — `cover.py`.
- Exportação DOCX (`kdp_docx`) e endpoint de DOCX.
- Aba e API de Biblioteca (`/api/library`).
- Modo demonstração falso no frontend.
- OCR de PDFs escaneados (mantém-se a recusa explícita com HTTP 422).
- PDF de impressão / paperback.

### 3.3 Próximos passos (não incluídos nesta entrega)

- Preservação de itálico/negrito **no texto traduzido** (no texto original será preservada).
- Notas de rodapé como *endnotes* com link.
- Múltiplos perfis de CSS (ficção vs. não-ficção).
- DOCX opcional para upload alternativo no KDP.

## 4. Arquitetura

### 4.1 Estrutura de arquivos

```
kdp-studio/
├── backend/app/
│   ├── config.py        # Settings: env, limites, timeouts, model fallbacks
│   ├── models.py        # Run, Line, Paragraph, Chapter, ChapterView, JobState
│   ├── jobs.py          # JobStore thread-safe + executor + TTL + cancelamento
│   ├── llm.py           # provider OpenAI-compatible: timeout, retry, fallback de modelo
│   ├── pdf_extract.py   # PyMuPDF -> Line[] com geometria e runs
│   ├── pdf_chapters.py  # outline -> âncoras; fallback; limpeza; sanidade -> Chapter[]
│   ├── translate.py     # chunks, paralelismo, validação estrutural, progresso
│   ├── kdp_epub.py      # EPUB3 KDP: montagem, escrita atômica, validate_epub
│   └── main.py          # rotas finas
├── static/{index.html,app.js,styles.css,vendor/tailwind.js}
├── tests/{conftest.py,test_pdf_extract.py,test_pdf_chapters.py,test_translate.py,
│          test_kdp_epub.py,test_jobs.py,test_api.py,test_acceptance_real_pdfs.py}
└── docs/superpowers/specs/2026-10-07-refatoracao-kdp-studio-design.md
```

**Removidos**: `backend/app/creator.py`, `backend/app/cover.py`,
`backend/app/pdf_cleaner.py`, `backend/app/kdp_export.py`,
`backend/app/translator.py` (substituído por `translate.py`),
`tests/test_kdp_export.py`, `tests/test_pdf_cleaner.py`, `tests/test_translator.py`,
`docs/GOOGLE_GEMINI.md` (conteúdo absorvido pelo README).

### 4.2 Dependências

Mantém-se `backend/requirements.txt`. `pymupdf` e `ebooklib` continuam sendo as
peças centrais. `python-docx` sai da lista. Sem novas dependências.

## 5. Modelo de dados (`models.py`)

```python
@dataclass(slots=True)
class Run:
    text: str
    italic: bool = False
    bold: bool = False

@dataclass(slots=True)
class Line:
    page: int          # 0-based
    text: str
    size: float
    bold: bool
    italic: bool
    bbox: tuple[float, float, float, float]
    page_height: float
    page_width: float
    runs: list[Run]    # spans na ordem de leitura

@dataclass(slots=True)
class Paragraph:
    runs: list[Run]

    @property
    def text(self) -> str: ...   # "".join(r.text for r in runs)

@dataclass(slots=True)
class Chapter:
    title: str
    level: int                    # 1, 2 ou 3
    paragraphs: list[Paragraph]
    @property
    def words(self) -> int: ...

@dataclass
class JobState:
    id: str
    status: str                   # queued|parsing|translating|done|error|cancelled
    stage: str                    # texto pt-BR para a UI
    progress: int                 # 0..100, real
    message: str
    cancel: threading.Event
    title: str
    author: str
    language: str
    chapters: list[Chapter]
    warnings: list[str]
    error: str | None
    translated: bool
    created_at: float
    output_files: list[str]
```

`Paragraph` guarda *runs* para preservar itálico/negrito no caminho **não
traduzido**. Quando um capítulo é traduzido, cada parágrafo vira um único `Run`
(sem formatação inline) — a API expõe apenas texto plano.

## 6. Pipeline de extração e capítulos

### 6.1 `pdf_extract.py`

```python
def extract_lines(pdf_path: Path) -> tuple[list[Line], int, list[tuple[int,str,int]]]
```
Retorna `(linhas, total_paginas, outline)` onde `outline` é `doc.get_toc(simple=True)`.

- Abre o PDF com PyMuPDF; itera páginas; usa `page.get_text("dict")`.
- Para cada `line` com spans não vazios: `text` = spans unidos por espaço;
  `size` = maior `size`; `bold`/`italic` a partir de `flags`
  (`bold` = bit 4/16, `italic` = bit 1/2 — usar `pymupdf.TEXT_FONT_*` quando
  disponível, com fallback numérico); `runs` = spans com `text`, `italic`, `bold`.
- Ordena por `(page, y0, x0)`.
- Descarta `line`s cujo texto normalizado seja vazio.
- Grandeza de desempenho: o livro PT tem ~13 mil linhas; extração em ~2 s.

### 6.2 `pdf_chapters.py` — detecção

Função pública:
```python
def build_chapters(pdf_path: Path, *, remove_header=True, remove_page_numbers=True
                   ) -> tuple[list[Chapter], list[str]]   # (capítulos, avisos)
```

`build_chapters` chama `extract_lines(pdf_path)` internamente e trabalha sobre as
`Line`s retornadas.

**Passo 1 — tamanho de corpo modal.**
`body_size` = tamanho que concentra mais **caracteres** no documento (ponderado,
não contagem de linhas). Tolerância de agrupamento: `round(size, 1)`.

**Passo 2 — caminho principal: anchors do outline.**
Para cada entrada `(level, title, page_1based)`:
1. Candidatos = linhas da página `page-1`, com `y0 < 0.6 * page_height`.
2. `score(linha, título)` = `SequenceMatcher(None, norm(titulo), norm(linha.text)).ratio()`,
   com bônus `+0.15` se `norm(titulo) == norm(linha.text)` e `+0.10` se a linha é
   "cara de título" (`size > body_size * 1.05` ou `bold`).
3. Escolhe o maior score; aceita se `score >= 0.72`.
4. Impõe **ordem monotônica**. Quando a melhor correspondência viola a ordem, ou
   fica abaixo de 0,72, a entrada é **reancorada** à primeira linha de conteúdo
   elegível após a âncora anterior na sua página (só quando a página for igual ou
   posterior à da âncora anterior). A entrada só é descartada se não houver
   nenhuma linha elegível — descartar em silêncio faria o conteúdo dela ser
   absorvido pelo capítulo anterior.
5. Se `ancoradas / total >= 0.80`, o caminho outline é usado.

**Passo 3 — fallback heurístico** (sem outline ou ancoragem insuficiente).
- `h1_min = body_size * 1.25`, `h2_min = body_size * 1.10`.
- Uma linha é título se **todas**: `len(text) <= 90`; não termina em
  `. , ; : ! ?` (exceto `?` em títulos curtos); ou casa padrão textual numerado
  (`^(cap[íi]tulo|chapter|parte|part)\b`, `^\d+(\.\d+)*\s+\S`,
  `^(prefácio|introdução|conclusão|epílogo|apêndice|agradecimentos|bibliografia|índice|sumário)\b`);
  E (`size >= h1_min`) ou (`size >= h2_min` e (`bold` ou `text.isupper()`)).
- `level` = 1 se `size >= h1_min`, senão 2.
- Descarta títulos com menos de 3 caracteres ou que sejam apenas dígitos.

**Passo 4 — limpeza das linhas de corpo.**
- **Bandas**: `header` se `y0 < 0.06 * page_height`; `footer` se `y1 > 0.93 * page_height`.
- Remove linha em banda quando: (a) `is_page_number(text)`; ou (b) existe outra
  página com linha em banda cujo texto normalizado tem similaridade ≥ 0.9
  (`SequenceMatcher`) e a contagem de páginas distintas com esse texto ≥ 3.
  Nunca remove uma linha que seja âncora do outline.
- `is_page_number`: `^\s*\d{1,4}\s*$`, `^\s*[ivxlcdm]{1,7}\s*$` (romano, quando
  a linha inteira é isso), `^\s*p[áa]g(ina)?\.?\s*\d+\s*$`.
- Remove linhas de *junk* óbvias: `^(www\.|https?://|\S+@\S+|ISBN\b|©|copyright\b|todos os direitos reservados)`, com `len <= 120`.
- **Páginas de sumário**: descarta o intervalo de linhas entre uma linha que casa
  `^(sum[áa]rio|conte[úu]do|contents|table of contents)\s*$` e a próxima âncora de
  outline, quando ≥ 60 % das linhas do intervalo têm `len <= 70`. Só se aplica
  quando o caminho outline está ativo.

**Passo 5 — montagem dos parágrafos.**
- Agrupa linhas consecutivas (na ordem de leitura, **atravessando páginas**) em parágrafos:
  - Continua o parágrafo anterior se: mesmo `round(size,1)`; `gap = y0(cur) - y1(prev)` entre `-2` e `max(1.8 * size, 6.0)`; e a linha anterior ocupa ≥ 80 % da largura máxima de coluna observada **ou** termina em hífen.
  - Quebra o parágrafo se `gap` maior (linha em branco) ou mudança de tamanho/fonte.
  - Se a página muda e a linha anterior não termina em hífen nem ocupa a largura, quebra (evita colar parágrafos de páginas diferentes).
- Junta linhas em `Paragraph`:
  - Se a última run termina em `-` e a próxima linha começa com minúscula não-acentuada → remove o hífen e concatena **sem espaço**.
  - Caso contrário, insere um `Run(" ")` entre as runs das duas linhas.
  - Remove *soft hyphen* `\u00ad` de todo texto.
- Normaliza espaços múltiplos para um único espaço.

**Passo 6 — corte dos capítulos.**
- Com outline: as âncoras (todas as entradas ancoradas, ordenadas por leitura)
  dividem o fluxo de parágrafos. Cada capítulo recebe os parágrafos entre a sua
  âncora e a seguinte. A âncora é removida do corpo do capítulo (`Chapter.title`).
- Sem outline: divisões pelos títulos heurísticos; se não houver nenhum, o
  documento vira **um único capítulo** e um aviso é emitido.
- `level` do capítulo = nível do outline (limitado a 1..3) ou o do heurístico.

**Passo 7 — validação de sanidade.**
- Capítulos com **zero parágrafos** são descartados e geram aviso (isso remove
  naturalmente entradas de outline como "Cover", que não têm corpo no texto
  extraído). Se o descarte zerar a lista, mantém-se um único capítulo com todo o
  texto.
- Emite aviso (em `warnings`, exibido na UI) e degrada para estratégia
  conservadora quando:
- `len(capítulos_nivel_1) > 60`, ou
- `len(capítulos_total) > max(50, pages / 1.5)`, ou
- mais de 50 % dos capítulos têm menos de 2 parágrafos.

Estratégia conservadora: usar apenas entradas de outline de **nível 1**; se ainda
insatisfatório, um capítulo por página com `title = f"Página {n}"`.

### 6.3 Avisos exibidos ao usuário

Exemplos: `"PDF sem sumário embutido: capítulos detectados por heurística de fontes."`,
`"Sumário detectado e removido do corpo."`,
`"Detecção instável; usada a estratégia conservadora."`,
`"N páginas sem texto extraível foram ignoradas."`

## 7. Tradução (`translate.py`)

### 7.1 Configuração

| Variável | Padrão | Papel |
|---|---|---|
| `TRANSLATION_CHUNK_CHARS` | `6000` | Alvo de caracteres por chamada |
| `TRANSLATION_WORKERS` | `4` | Chamadas em paralelo |
| `LLM_TIMEOUT_SECONDS` | `120` | Timeout por chamada |
| `LLM_MAX_RETRIES` | `3` | Tentativas por chunk |
| `GEMINI_MODEL` | `gemini-flash-latest` | Modelo primário |
| `GEMINI_MODEL_FALLBACKS` | `gemini-3.8-flash,gemini-3.7-flash,gemini-3.1-flash-lite` | Cadeia em caso de 404/503 |

### 7.2 Chunking

`split_chunks(text, limit)`:
- Corta preferencialmente em `\n\n` (fronteira de parágrafo); depois em fim de
  frase (`[.!?…]\s`); por último em espaço.
- **Nunca** corta no meio de um parágrafo, salvo parágrafo único maior que
  `limit` (aí usa `split` por frase/espaço).
- Nenhum caractere é perdido e nenhum trecho aparece em dois chunks.

### 7.3 Chamada e prompt

- `system`: tradutor literário profissional; traduzir para `lang_name(target)`
  (padrão `portugues brasileiro`); preservar nomes próprios e o número exato de
  parágrafos separados por linha em branco; retornar **somente** a tradução.
- Inclui contexto curto: `"Livro: {title}. Capítulo: {chapter_title}."`.
- `user`: o chunk.

### 7.4 Validação estrutural

1. `n_src = len(split_paragrafos(src))`; `n_out = len(split_paragrafos(out))`.
2. Se `n_src == n_out` → aceita.
3. Se difere → **refaz o chunk parágrafo a parágrafo** (uma chamada por
   parágrafo, só nesse chunk). Se ainda divergir ou falhar, mantém o **texto
   original** dos parágrafos problemáticos e registra aviso.
4. Nunca descarta conteúdo em silêncio: toda perda vira aviso no job.

### 7.5 Resiliência

- `max_retries=LLM_MAX_RETRIES`, backoff exponencial `1s, 2s, 4s`.
- Falha de modelo (404/503) avança na cadeia de fallback; a primeira chamada que
  responder "fixa" o modelo efetivo para o resto do job (com lock).
- Esgotadas todas as tentativas para um chunk: mantém o original e acumula aviso.
- Se **todos** os chunks falharem, o job termina em `error` com mensagem
  acionável (ex.: `"Nenhum modelo Gemini respondeu (503). Verifique
  GEMINI_MODEL/GEMINI_MODEL_FALLBACKS ou tente novamente."`).
- Cancelamento: o `threading.Event` do job é verificado antes de cada chamada;
  se setado, o job vira `cancelled` e o EPUB não é gerado.

### 7.6 Progresso

`progress` do job é atualizado a cada chunk concluído:
`50 + int(45 * chunks_done / chunks_total)` (a extração ocupa 0–50).

## 8. Exportação EPUB (`kdp_epub.py`)

```python
def build_epub(chapters, title, author, language, out_path) -> Path
def validate_epub(path: Path) -> None   # levanta EpubValidationError
```

### 8.1 Conteúdo

- `mimetype` (conteúdo `application/epub+zip`) como **primeira** entrada e
  **sem compressão** (`ZIP_STORED`); demais entradas com deflate.
- `EPUB/nav.xhtml` (EPUB3, `properties="nav"`) e `EPUB/toc.ncx` (compatibilidade
  Kindle/legado).
- TOC **aninhada** conforme `level` (1→2→3).
- `EPUB/titulo.xhtml` (página de título) + um `EPUB/cap{N}.xhtml` por capítulo.
- CSS `EPUB/style/kdp.css`:

```css
body { font-family: Georgia, 'Times New Roman', serif; font-size: 1em; line-height: 1.5;
       margin: 0 5%; text-align: justify; }
h1 { font-size: 1.7em; text-align: center; margin: 3em 0 1em; page-break-before: always; }
h2 { font-size: 1.3em; margin: 2em 0 .8em; }
h3 { font-size: 1.1em; margin: 1.5em 0 .6em; }
p  { margin: 0 0 .3em; text-indent: 1.25em; widows: 2; orphans: 2; }
p.noindent, h1 + p, h2 + p, h3 + p { text-indent: 0; }
```

- A página de título é um arquivo separado (`titulo.xhtml`), não um bloco oculto
  no primeiro capítulo.
- Metadados: `dc:title`, `dc:creator`, `dc:language` (`pt-BR` por padrão),
  `dc:identifier` (UUID5 estável de `titulo|autor`), `dcterms:modified`,
  `meta name="generator"`.
- Capa: **fora do escopo** (não há upload de capa nesta entrega).
- Todo texto passa por `html.escape`; runs viram `<em>`/`<strong>`.

### 8.2 Escrita atômica e validação (CA4, CA5)

1. Monta o EPUB num arquivo temporário no **mesmo diretório** do destino:
   `out_path.with_suffix(".epub.tmp-<uuid>")`.
2. Chama `validate_epub(tmp)`.
3. Só então `os.replace(tmp, out_path)`.
4. Em qualquer exceção, remove o temporário e **não** cria o destino.

`validate_epub` confere:
- o arquivo é um ZIP legível;
- `mimetype` é a primeira entrada e está `ZIP_STORED`;
- `META-INF/container.xml` e `EPUB/content.opf` existem;
- **todo** `href` do manifest existe no ZIP;
- `toc.ncx` e `nav.xhtml` existem e estão no manifest;
- `nav.xhtml` tem `properties="nav"`;
- cada itemref do spine aponta para um `id` do manifest.

## 9. API (`main.py`)

| Método | Rota | Entrada | Saída |
|---|---|---|---|
| GET | `/api/health` | — | `{ok: true}` |
| GET | `/api/config` | — | `{provider, configured, translation_model, fallback_models, max_upload_mb, languages, chunk_chars, workers}` |
| POST | `/api/jobs` | multipart: `file`, `title`, `author`, `translate`, `source_lang`, `target_lang`, `model`, `remove_header`, `remove_page_numbers` | `201 {job_id}` |
| GET | `/api/jobs/{id}` | — | `{id, status, stage, progress, message, title, author, language, translated, warnings, error, chapters:[{index,title,level,words,preview,included}]}` |
| GET | `/api/jobs/{id}/chapters/{index}` | — | `{index, title, level, paragraphs:[str]}` |
| POST | `/api/jobs/{id}/export` | JSON `{chapters:[{index,title,included}], edit?{index: [str]}}` | arquivo `application/epub+zip` |
| POST | `/api/jobs/{id}/cancel` | — | `{ok, status}` |
| DELETE | `/api/jobs/{id}` | — | `{ok}` (remove da memória e apaga artefatos) |

Regras:
- `POST /api/jobs` valida magic bytes `%PDF`, limite `MAX_UPLOAD_MB` (413),
  arquivo vazio (400), formato inválido (400) e devolve `job_id` imediatamente.
- Tradução exige texto extraível: sem texto real → **422** com mensagem
  acionável (mantém o comportamento atual).
- Corpo de `export`: `chapters` é a lista **na ordem final** de exportação; cada
  item `{index, title, included}` referencia o índice do capítulo no job. Itens
  com `included: false` são descartados. `edit` é opcional e mapeia
  `index → lista de parágrafos em texto plano`; quando presente, substitui os
  parágrafos daquele capítulo (perdendo formatação inline, que é documentado na
  UI). Ausente, preserva os *runs* originais.
- `export` aplica, nesta ordem: filtro de `included`, ordem da lista enviada,
  títulos enviados, `edit` (substitui os parágrafos por texto plano).
- `export` com job inexistente → 404; job em `error`/`cancelled` → 409.
- Erros sempre em `{detail: "<mensagem em pt-BR>"}`.

## 10. Jobs (`jobs.py`)

- `JobStore`: `dict[str, JobState]` + `threading.RLock`.
- `ThreadPoolExecutor(max_workers=JOB_WORKERS, default 2)` executa o pipeline.
- Estados: `queued → parsing → translating → done` | `error` | `cancelled`.
- `cancel()` seta o `threading.Event`; o pipeline verifica entre páginas e chunks.
- Limpeza: remove artefatos de jobs mais antigos que `JOB_TTL_SECONDS` (padrão
  7200) e mantém no máximo `JOB_MAX` (padrão 50) jobs em memória.
- Arquivos gerados vão para `output/` com nome `{slug}-{job_id}-{formato}`.

## 11. Configuração (`config.py`)

| Variável | Padrão |
|---|---|
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | — |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | — / `gemini-flash-latest` |
| `GEMINI_MODEL_FALLBACKS` | `gemini-3.8-flash,gemini-3.7-flash,gemini-3.1-flash-lite` |
| `TRANSLATION_MODEL` | — (override explícito) |
| `TRANSLATION_CHUNK_CHARS` | `6000` |
| `TRANSLATION_WORKERS` | `4` |
| `LLM_TIMEOUT_SECONDS` | `120` |
| `LLM_MAX_RETRIES` | `3` |
| `MAX_UPLOAD_MB` | `100` |
| `JOB_TTL_SECONDS` / `JOB_MAX` / `JOB_WORKERS` | `7200` / `50` / `2` |
| `CORS_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` |
| `HOST` / `PORT` / `RELOAD` | `127.0.0.1` / `8000` / `0` |

`CREATION_MODEL` e `COVER_MODEL` deixam de existir.

## 12. Interface (`static/`)

Uma tela única, três passos:

1. **Arquivo e opções** — drag&drop do PDF; título; autor; toggles "Remover
   cabeçalhos" e "Remover numeração"; toggle "Traduzir para português (BR)" que
   revela idioma de origem e seletor de modelo (populado por `/api/config`).
2. **Processando** — barra de progresso **real** alimentada por
   `GET /api/jobs/{id}` a cada 800 ms, com `stage`/`message` do servidor e botão
   **Cancelar**.
3. **Revisar e exportar** — agrupamento por capítulo de nível 1 (subníveis
   recolhíveis); renomear título; reordenar ↑↓; incluir/excluir (com cascata para
   subníveis); contagem de palavras; prévia carregada sob demanda por
   `GET /api/jobs/{id}/chapters/{i}`; botão "Exportar EPUB" que envia
   `POST /api/jobs/{id}/export`.

Regras de UX:
- Erros do backend são exibidos **com a mensagem real**; não há fallback que
  simule sucesso.
- Sem provider configurado, o toggle de tradução fica desabilitado com aviso
  "nenhuma chave de IA configurada".
- Avisos do job (`warnings`) aparecem num bloco âmbar na etapa 3.
- Acessibilidade: foco visível, `aria-live` nos toasts, teclado nos toggles.

## 13. Testes e verificação

### 13.1 Unitários

| Arquivo | Cobre |
|---|---|
| `test_pdf_extract.py` | extração de linhas, tamanhos, runs, outline |
| `test_pdf_chapters.py` | ancoragem de outline; fallback heurístico sem outline; remoção de header/footer por banda+repetição; numeração de página; des-hifenização; junção entre páginas; páginas de sumário; validação de sanidade; aviso de PDF sem texto |
| `test_translate.py` | chunking sem perda/sobreposição; preservação estrutural; fallback parágrafo-a-parágrafo quando a contagem diverge; contagem de chamadas (CA6); timeout/retry/fallback de modelo (CA7); cancelamento |
| `test_kdp_epub.py` | estrutura (mimetype primeiro/stored, nav, ncx, TOC aninhada); validação detecta ZIP inconsistente (CA4); falha de validação não cria destino (CA5); escaping HTML; runs → `<em>`/`<strong>` |
| `test_jobs.py` | ciclo de vida, TTL, limite, cancelamento, concorrência do store |
| `test_api.py` | todas as rotas, códigos de erro, export com edições |

### 13.2 Aceitação com PDFs reais

`tests/test_acceptance_real_pdfs.py`, marcado `@pytest.mark.acceptance`,
**pulado** se `KDP_REAL_PDFS_DIR` não apontar para um diretório com os PDFs.
O marcador é registrado em `pyproject.toml` (`markers = ["acceptance: ..."]`) para
não emitir aviso. Roda em `/home/gutierredesouza/Downloads` nesta máquina e
valida CA1–CA4.

### 13.3 Verificação manual final

```bash
cd kdp-studio
python3 -m pytest -q
KDP_REAL_PDFS_DIR=~/Downloads python3 -m pytest -q -m acceptance
./run.sh
# GUI: enviar "Killing the Messiah", marcar tradução EN→pt-BR, revisar, exportar
# e abrir o EPUB gerado (validação automática já garante a integridade)
```

## 14. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| PDF sem bookmarks → heurística falha | Fallback por fontes + validação de sanidade + avisos explícitos na UI; nunca entrega lixo silenciosamente |
| Modelos Gemini instáveis (503) | Timeout + retry + cadeia de fallback; erro acionável; parte já traduzida é preservada |
| Livro grande estoura memória/tempo | Chunks e progresso; `ThreadPoolExecutor`; limites configuráveis; ~13 mil linhas do livro PT são leves |
| Remoção de recursos quebrar o usuário | Baseline em git (`957c3fa`); README documenta a mudança de escopo |
| Escrita atômica em FS sem permissão | Temporário no mesmo diretório; erro claro se não puder escrever |

## 15. Documentação

- `README.md` reescrito: escopo, como rodar, API, configuração, testes.
- `.env.example` atualizado (novas variáveis; removidas `CREATION_MODEL`/`COVER_MODEL`).
- `docs/GOOGLE_GEMINI.md` removido (conteúdo absorvido pelo README).
- `INSTRUCOES-DEEPSEEK-HARNESS.md` mantido como registro histórico do brief anterior.
