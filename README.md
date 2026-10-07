# 📚 KDP Studio

Converta um PDF em **EPUB 3 no padrão KDP** — com capítulos detectados pelo
sumário do próprio PDF — e, opcionalmente, **traduza a obra para português
brasileiro** no mesmo fluxo.

Dois caminhos, um só pipeline:

1. **PDF → EPUB**: extrai o texto, detecta capítulos e gera um EPUB validado.
2. **PDF (outro idioma) → tradução → EPUB pt-BR**: traduz em lote com progresso
   real e gera o EPUB no idioma de destino.

- **Backend:** FastAPI (`backend/app/`)
- **Frontend:** SPA sem build (`static/` — abra via backend, não como arquivo)
- **Saída:** EPUB gerado em `output/`
- **Testes:** `pytest` (`tests/`)

## 🚀 Como rodar

```bash
cd kdp-studio
./run.sh                      # instala deps se faltarem e sobe o servidor
# variações:
PORT=9000 ./run.sh            # outra porta
RELOAD=0 ./run.sh             # sem --reload
# manual (o .env é carregado pela própria app):
python3 -m pip install -r requirements.txt
python3 -m uvicorn backend.app.main:app --port 8000
```

Abra **http://127.0.0.1:8000** — o backend serve o frontend em `/`.

> Sem `OPENAI_API_KEY` e sem `GEMINI_API_KEY` o app **continua funcionando**
> para PDF → EPUB; apenas a tradução fica indisponível, e a interface avisa.

## ⚙️ Configuração

Copie `.env.example` para `.env` na raiz do projeto. Mantenha **um único** `.env`.

| Variável | Padrão | Uso |
|---|---|---|
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | — | provider OpenAI (ou compatível: OpenRouter, DeepSeek…) |
| `GEMINI_API_KEY` | — | provider Gemini (endpoint OpenAI-compatible) |
| `GEMINI_MODEL` | `gemini-flash-latest` | modelo primário de tradução |
| `GEMINI_MODEL_FALLBACKS` | `gemini-3.8-flash,gemini-3.7-flash,gemini-3.1-flash-lite` | cadeia tentada quando o primário falha (404/503) |
| `TRANSLATION_MODEL` | — | força um modelo específico (ignora a cadeia) |
| `TRANSLATION_CHUNK_CHARS` | `6000` | caracteres por chamada de tradução |
| `TRANSLATION_WORKERS` | `4` | chamadas de tradução em paralelo |
| `LLM_TIMEOUT_SECONDS` | `120` | timeout por chamada de LLM |
| `LLM_MAX_RETRIES` | `3` | rodadas completas pela cadeia de modelos |
| `MAX_UPLOAD_MB` | `100` | tamanho máximo do PDF |
| `JOB_TTL_SECONDS` / `JOB_MAX` / `JOB_WORKERS` | `7200` / `50` / `2` | retenção e paralelismo dos jobs |
| `CORS_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | origens permitidas |
| `HOST` / `PORT` / `RELOAD` | `127.0.0.1` / `8000` / `0` | servidor |

> **Provider:** se `OPENAI_API_KEY` existir, ele ganha; senão vale o
> `GEMINI_API_KEY`. Modelos Gemini mudam com frequência — por isso existe a
> cadeia de fallback: quando um modelo responde 404/503, o próximo assume, e o
> modelo que funcionou passa a ser tentado primeiro nas chamadas seguintes.

## 🔌 API

| Método | Rota | Uso |
|---|---|---|
| GET | `/api/health` | status |
| GET | `/api/config` | provider ativo, modelos, limites e idiomas |
| POST | `/api/jobs` | multipart `file`, `title`, `author`, `translate`, `source_lang`, `target_lang`, `translation_model`, `remove_header`, `remove_page_numbers` → `201 {job_id}` |
| GET | `/api/jobs/{id}` | `status`, `stage`, `progress`, `message`, `warnings`, `error` e metadados dos capítulos |
| GET | `/api/jobs/{id}/chapters/{i}` | texto completo de um capítulo |
| POST | `/api/jobs/{id}/export` | JSON `{chapters:[{index,title,included}], edit?}` → arquivo `application/epub+zip` |
| POST | `/api/jobs/{id}/cancel` | cancela a tradução em andamento |
| DELETE | `/api/jobs/{id}` | descarta o job e seus artefatos |
| GET | `/download/{arquivo}` | arquivos gerados |

Códigos de erro: `400` requisição inválida, `404` job inexistente, `409` job em
`error`/`cancelled`, `413` arquivo acima do limite, `422` PDF sem texto
extraível (OCR de PDFs escaneados não é suportado).

## 🧠 Como os capítulos são detectados

1. **Bookmarks primeiro.** PDFs costumam trazer o sumário embutido
   (`doc.get_toc()`); cada entrada é ancorada à linha real do texto por
   similaridade normalizada, preservando a ordem de leitura.
2. **Heurística de fontes como fallback.** Sem bookmarks utilizáveis, os títulos
   são inferidos pelo tamanho modal do corpo, negrito, caixa-alta e padrões
   textuais (`Capítulo N`, `1.2 Título`, `Prefácio`…).
3. **Limpeza.** Cabeçalhos e rodapés repetidos são removidos por banda +
   repetição entre páginas; a numeração de página sai; palavras quebradas por
   hífen são reunidas; parágrafos são juntados inclusive entre páginas.
4. **Validação de sanidade.** Se a contagem de capítulos explodir (sinal de
   detecção errada), o pipeline degrada para a estratégia conservadora e
   registra um aviso visível na interface.

## 📁 Estrutura

```
kdp-studio/
├── backend/app/
│   ├── config.py        # Settings: env, limites, timeouts, cadeia de modelos
│   ├── models.py        # Run, Line, Paragraph, Chapter, ChapterView, JobState
│   ├── jobs.py          # JobStore: progresso, cancelamento, TTL
│   ├── llm.py           # provider + timeout + retry + fallback de modelos
│   ├── pdf_extract.py   # PyMuPDF -> linhas com geometria e formatação inline
│   ├── pdf_chapters.py  # bookmarks + heurística + limpeza -> capítulos
│   ├── translate.py     # tradução em lote, paralela, com progresso
│   ├── kdp_epub.py      # EPUB 3, escrita atômica e validação
│   └── main.py          # rotas
├── static/{index.html,app.js,styles.css,vendor/tailwind.js}
├── tests/               # unitários, API e aceitação com PDFs reais
└── docs/superpowers/    # spec e plano da refatoração
```

## 🧪 Testes

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q          # suíte completa (offline, sem chamadas de LLM)

# aceitação com PDFs reais (pulada se a variável não existir):
KDP_REAL_PDFS_DIR="$HOME/Downloads" python3 -m pytest -q -m acceptance
```

A suíte nunca chama a API real: a fixture `offline` transforma qualquer criação
de cliente de LLM em erro.

Smoke test:

```bash
./run.sh & sleep 5
curl -s localhost:8000/api/health     # {"ok": true}
curl -s localhost:8000/api/config     # provider, modelos, limites
```

## ⚠️ Limitações conhecidas

- **PDFs escaneados** (sem camada de texto) são recusados com HTTP 422; não há OCR.
- No **texto traduzido** não se preserva itálico/negrito: o modelo não mapeia
  formatação inline de forma confiável. No texto original ela é preservada.
- A detecção por heurística (PDFs sem bookmarks) é menos precisa que a via
  bookmarks e pode exigir revisão manual dos títulos.

## 📌 Escopo

Esta versão foca em **PDF → EPUB** e **tradução**. Foram removidos da base
anterior: o assistente de criação de livros com IA, a geração de capa, a
exportação DOCX e a biblioteca de arquivos. O histórico está no git
(o estado anterior à refatoração é o commit `957c3fa`).
