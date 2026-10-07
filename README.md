# 📚 KDP Studio

Converta PDFs em eBooks, traduza obras e crie livros com IA — exporte **EPUB** e **DOCX** prontos para o KDP da Amazon.

- **Backend:** FastAPI (`backend/app/`)
- **Frontend:** SPA sem build (`static/` — abra via backend, não como arquivo)
- **Saída:** arquivos gerados em `output/` (servidos em `/download/`)
- **Testes:** `pytest` (`tests/`)

## 🚀 Como rodar

```bash
cd kdp-studio
./run.sh                      # instala deps se faltarem e sobe o servidor
# variações:
PORT=9000 ./run.sh            # outra porta
RELOAD=0 ./run.sh             # sem --reload (uso "produção" local)
# manual (também funciona: o .env é carregado pela própria app):
python3 -m pip install -r requirements.txt
python3 -m uvicorn backend.app.main:app --reload --port 8000
# alternativa:
python3 -m backend.app.main   # usa HOST/PORT/RELOAD do ambiente
```

Abra **http://127.0.0.1:8000** (o backend serve o frontend em `/`).

> O backend é **Python/FastAPI** — não há dependências Node no projeto.
> Se você preferir digitar `npm`, o [`package.json`](package.json) existe
> apenas como atalho para os mesmos comandos:
> `npm run dev` (= `bash run.sh`), `npm start` (= `RELOAD=0 bash run.sh`),
> `npm test` (= `pytest`) e `npm run check` (compila Python + valida o JS).

> **Configuração:** o arquivo `.env` **na raiz** do projeto é carregado
> automaticamente pela aplicação (via `python-dotenv`), tanto por `./run.sh`
> quanto por `uvicorn backend.app.main:app`. Copie `.env.example` para `.env`
> e preencha. Mantenha **um único** `.env` (evite duplicar chaves em
> `backend/.env`).

> Sem `OPENAI_API_KEY` e sem `GEMINI_API_KEY` o app funciona em **modo offline**
> (mocks locais de tradução/criação e capa gerada com Pillow). Quando a chave
> existe mas a chamada falha, o fallback local assume e a UI avisa.

### Variáveis de ambiente

| Variável | Padrão | Uso |
|---|---|---|
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | — | provider OpenAI (ou compatível: OpenRouter, DeepSeek…) |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | `gemini-flash-latest` | provider Gemini (endpoint OpenAI-compatible) |
| `TRANSLATION_MODEL` / `CREATION_MODEL` | `gpt-4o-mini` / `gpt-4o` | override explícito de modelo |
| `COVER_MODEL` | `dall-e-3` | modelo de imagem (só OpenAI) |
| `MAX_UPLOAD_MB` | `100` | tamanho máximo de PDF aceito |
| `CORS_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | origens permitidas |
| `JOB_TTL_SECONDS` / `JOB_MAX` | `7200` / `50` | retenção dos jobs de conversão em memória |
| `HOST` / `PORT` / `RELOAD` | `127.0.0.1` / `8000` / `0` | servidor (`run.sh` usa `RELOAD=1`) |

## 🔌 API

| Método | Rota | Uso |
|---|---|---|
| GET | `/api/health` (e `/health`) | status |
| GET | `/api/models` | provider ativo, modelos efetivos e se há chave |
| POST | `/api/pdf/parse` | extrai capítulos de um PDF (multipart `file`; toggles opcionais) |
| POST | `/api/pdf/convert` | PDF → EPUB+DOCX+prévia (multipart `file`, `title`, `author`, toggles) |
| POST | `/api/convert` | **alias frontend**: FormData `file, title, author, format, remove_header, remove_page_numbers` e opcionais `translate, source_lang, target_lang, translation_model` → `{job_id, chapters, epub, docx, preview, translated, source_lang, target_lang, translation_model}` |
| GET | `/api/convert/{job}/download?format=epub&include=0,1` | baixa o EPUB/DOCX do job (`include` = **índices originais**) |
| POST | `/api/translate` | JSON `{chapters[], model, source_lang, target_lang}` **ou** FormData `{text, file (PDF/.txt/.md/.docx), source_lang, target_lang, model}`; opcionais `export` (bool), `format` (só `epub`), `title`, `author` — com `export` ligado a resposta também inclui `job_id`, `epub` e `files`; PDF sem texto real → **422** (OCR fora de escopo) |
| POST | `/api/books/plan` | `{ideia, genero, estilo, publico, capitulos}` → `{titulo, outline}` |
| POST | `/api/books/write` | `{outline[], titulo, estilo}` → `{chapters}` |
| POST | `/api/ebook/outline` | alias: `{idea\|ideia, genre\|genero, style\|estilo, audience\|publico, num_chapters\|capitulos}` |
| POST | `/api/ebook/chapter` | alias: `{chapter_title, chapter_synopsis, title, style, chapter_number, …}` → `{text, body, chapter, mock}` |
| POST | `/api/ebook/cover` | alias: `{prompt\|title\|titulo, author\|autor}` → `{image_url, url}` |
| POST | `/api/ebook/export` | alias: `{title, author, format, chapters[{title, body}]}` → **arquivo** (blob) quando `format=epub\|docx`; `all` devolve o trio |
| POST | `/api/export` | `{chapters, title, author}` → `{epub, docx, preview}` (URLs `/download/*`) |
| POST | `/api/cover/generate` | `{titulo, autor, estilo}` → `{image_url, url}` |
| GET | `/api/library` | `{items[{id, kind, title, detail, date, download_url}]}` |
| DELETE | `/api/library/{arquivo}` | remove um arquivo gerado de `output/` |
| GET | `/download/{arquivo}` | arquivos gerados (canônico) |
| GET | `/static/{arquivo}` | mesmos arquivos (legado) |

**Idiomas na tradução:** `source_lang` (`auto` por padrão) e `target_lang`
(`pt-BR` por padrão) são realmente aplicados ao prompt do modelo.

## 📁 Estrutura

```
kdp-studio/
├── backend/app/{main,creator,translator,pdf_cleaner,kdp_export,cover,llm}.py
├── backend/requirements.txt   (canônico; a raiz referencia com -r)
├── requirements-dev.txt       (runtime + pytest)
├── pyproject.toml             (metadados + config do pytest/ruff)
├── static/{index.html,app.js,styles.css}
├── static/vendor/tailwind.js  (Tailwind servido localmente — sem CDN)
├── tests/                     (pytest: pdf_cleaner, translator, kdp_export, API)
├── output/                    (gerados: .epub/.docx/.html/.jpg — ignorado no git)
├── docs/GOOGLE_GEMINI.md
├── package.json               (atalhos npm: dev/start/test/check — sem deps Node)
├── run.sh  .env.example  README.md
```

## 🧪 Testes e smoke test

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q                      # suíte completa

python3 -m py_compile backend/app/*.py
python3 -m uvicorn backend.app.main:app --port 8000 & sleep 4
curl -s localhost:8000/api/health         # {"ok": true}
curl -s localhost:8000/api/models         # provider_ativo: openai|gemini|offline
curl -s localhost:8000/api/library        # {"items": [...]}
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/   # 200 (SPA)
```

## 🔒 Segurança

- O `.env` fica fora do versionamento (`.gitignore`) e deve ter permissão `600`.
  Mantenha **apenas um** arquivo com chaves reais.
- O backend escuta em `127.0.0.1` por padrão e o CORS é restrito às origens
  locais (ajustável em `CORS_ORIGINS`).
- Downloads e a biblioteca operam apenas sobre nomes de arquivo dentro de
  `output/` (sem path traversal).
- O frontend usa **Tailwind local** (`static/vendor/tailwind.js`), servido pelo
  próprio backend — funciona offline e não depende de CDN/CORS. As fontes vêm
  do Google Fonts com fallback do sistema.
