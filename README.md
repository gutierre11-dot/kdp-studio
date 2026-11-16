# 📚 KDP Studio

Converta um PDF em **EPUB 3 no padrão KDP** — com capítulos detectados pelo
sumário do próprio PDF — e, opcionalmente, **traduza a obra para português
brasileiro** no mesmo fluxo.

Dois caminhos, um só pipeline:

1. **PDF → EPUB**: extrai o texto, detecta capítulos e gera um EPUB validado.
2. **PDF (outro idioma) → tradução → EPUB pt-BR**: traduz em lote com progresso
   real e gera o EPUB no idioma de destino.

Antes de exportar, o passo de **revisão** permite renomear e reordenar capítulos,
ligar/desligar cada um, **corrigir o texto parágrafo a parágrafo**, conferir as
**notas de rodapé** (que saem como endnotes) e **enviar a capa do autor**.

- **Backend:** FastAPI (`backend/app/`)
- **Frontend:** SPA sem build (`static/` — abra via backend, não como arquivo)
- **Saída:** EPUB gerado em `output/`
- **Testes:** `pytest` (`tests/`) · **Lint:** `ruff` · **CI:** GitHub Actions

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

> Sem nenhuma chave de IA o app **continua funcionando** para PDF → EPUB;
> apenas a tradução fica indisponível, e a interface avisa.

## 🔑 Configurando a IA

O caminho recomendado é o script interativo — ele pergunta a chave, valida com
uma chamada real à API e só então grava no `.env` (permissão `600`):

```bash
./configurar-ia.sh
```

A chave é digitada com **entrada oculta**: não aparece na tela, não entra no
histórico do shell e não é ecoada pelo script. Se a validação falhar, nada é
gravado.

Para configurar à mão, copie `.env.example` para `.env` na raiz do projeto.
Mantenha **um único** `.env`.

| Variável | Padrão | Uso |
|---|---|---|
| `LLM_PROVIDER` | — | força `deepseek`, `openai`, `gemini` ou `offline` quando há mais de uma chave |
| `DEEPSEEK_API_KEY` | — | provider DeepSeek (recomendado) |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | endereço da API DeepSeek |
| `DEEPSEEK_MODEL` | `deepseek-flash` | modelo principal de tradução |
| `DEEPSEEK_MODEL_FALLBACKS` | `deepseek-v4-pro` | cadeia tentada quando o principal falha |
| `DEEPSEEK_THINKING` | `0` | modo de raciocínio (ligar multiplica tempo e custo) |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | — | provider OpenAI ou compatível (OpenRouter, proxy…) |
| `GEMINI_API_KEY` | — | provider Gemini (endpoint OpenAI-compatible) |
| `GEMINI_MODEL` / `GEMINI_MODEL_FALLBACKS` | `gemini-flash-latest` / `gemini-3.8-flash,…` | modelos do Gemini |
| `TRANSLATION_MODEL` | — | força um modelo específico (ignora a cadeia do provider) |
| `TRANSLATION_CHUNK_CHARS` | `6000` | caracteres por chamada de tradução |
| `TRANSLATION_WORKERS` | `4` | chamadas de tradução em paralelo |
| `LLM_TIMEOUT_SECONDS` | `60` | timeout por chamada de LLM |
| `LLM_MAX_RETRIES` | `3` | rodadas completas pela cadeia de modelos |
| `LLM_MAX_TOTAL_SECONDS` | `180` | teto de tempo de **uma** chamada de chat, somando modelos e rodadas |
| `MAX_UPLOAD_MB` | `100` | tamanho máximo do PDF |
| `MAX_COVER_MB` | `10` | tamanho máximo da capa enviada |
| `JOB_TTL_SECONDS` / `JOB_MAX` / `JOB_WORKERS` | `7200` / `50` / `2` | retenção e paralelismo dos jobs |
| `CORS_ORIGINS` | `http://localhost:8000,http://127.0.0.1:8000` | origens permitidas |
| `HOST` / `PORT` / `RELOAD` | `127.0.0.1` / `8000` / `0` | servidor |

> **Prioridade do provider:** `LLM_PROVIDER` (se definido) → DeepSeek → OpenAI →
> Gemini → offline. Modelos de provedor mudam com frequência — por isso existe a
> cadeia de fallback: quando o principal responde 404/429/503, o próximo assume,
> e o modelo que funcionou passa a ser tentado primeiro nas chamadas seguintes.

## 🔌 API

| Método | Rota | Uso |
|---|---|---|
| GET | `/api/health` | status |
| GET | `/api/config` | provider ativo, modelos, limites e idiomas |
| POST | `/api/jobs` | multipart `file`, `title`, `author`, `description`, `publisher`, `translate`, `source_lang`, `target_lang`, `translation_model`, `remove_header`, `remove_page_numbers` → `201 {job_id}` |
| GET | `/api/jobs/{id}` | `status`, `stage`, `progress`, `message`, `description`, `publisher`, `cover`, `warnings`, `error` e metadados dos capítulos |
| GET | `/api/jobs/{id}/chapters/{i}` | texto completo do capítulo, com `notes` e `title_refs` |
| GET | `/api/jobs/{id}/cover` | imagem efetiva do job (a enviada, ou a procedural) como `image/jpeg`/`image/png` |
| POST | `/api/jobs/{id}/cover` | multipart `file` (JPEG/PNG) → substitui a capa do job |
| DELETE | `/api/jobs/{id}/cover` | descarta a capa enviada e volta para a procedural |
| POST | `/api/jobs/{id}/export` | JSON `{chapters:[{index,title,included}], edit?, cover?}` → arquivo `application/epub+zip` |
| POST | `/api/jobs/{id}/cancel` | cancela a tradução em andamento |
| DELETE | `/api/jobs/{id}` | descarta o job e seus artefatos |
| GET | `/download/{arquivo}` | arquivos gerados |

Códigos de erro: `400` requisição inválida, `404` job inexistente, `409` job em
`error`/`cancelled`, `413` arquivo acima do limite, `422` PDF sem texto
extraível (OCR de PDFs escaneados não é suportado).

A ordem de precedência da capa é: **imagem enviada** → capa procedural; o
`cover: false` no corpo da exportação remove a capa do EPUB, enviada ou não.

## 🧠 Como os capítulos são detectados

1. **Bookmarks primeiro.** PDFs costumam trazer o sumário embutido
   (`doc.get_toc()`); cada entrada é ancorada à linha real do texto por
   similaridade normalizada, preservando a ordem de leitura.
2. **Índice impresso.** Sem bookmarks utilizáveis, procura-se o **Índice**
   impresso no próprio PDF (`Índice`/`Sumário`/`Contents`): cada entrada
   (`Título ..... 12`) é ancorada a uma linha do corpo por similaridade, já que
   o deslocamento entre a página impressa e a página interna é desconhecido. O
   bloco do índice é removido do corpo do livro.
3. **Heurística de fontes como último recurso.** Sem bookmarks nem índice, os
   títulos são inferidos pelo tamanho modal do corpo, negrito, caixa-alta e
   padrões textuais (`Capítulo N`, `1.2 Título`, `Prefácio`…). Também captura
   **títulos em negrito menores que o corpo**, que sumiriam na comparação de
   tamanho: além do negrito dominar a linha, ela precisa estar isolada (curta
   face à largura da coluna).
4. **Limpeza.** Cabeçalhos e rodapés repetidos são removidos por banda +
   repetição entre páginas (o tamanho é medido no texto normalizado, para não
   escapar cabeçalhos com padding de espaços); a numeração de página sai; a
   página de sumário e as fichas/capas iniciais saem do corpo; palavras
   quebradas por hífen são reunidas; parágrafos são juntados inclusive entre
   páginas (o PyMuPDF às vezes devolve caixas de linha sobrepostas — o gap
   negativo é tolerado sem partir o parágrafo).
5. **Capítulos longos viram continuações.** Um capítulo acima de ~15 mil
   palavras é dividido em partes equilibradas. As demais partes repetem o
   título base e viram **arquivos de continuação**: entram no fluxo de leitura,
   mas sem cabeçalho próprio e sem entrada duplicada no sumário.
6. **Validação de sanidade.** Se a contagem de capítulos explodir (sinal de
   detecção errada), o pipeline degrada para a estratégia conservadora e
   registra um aviso visível na interface.

## 📝 Notas de rodapé (endnotes)

Notas de rodapé (linha curta, fonte ≤ 70 % do corpo, na banda inferior da
página) são extraídas do corpo e viram **endnotes ao fim do capítulo** a que
pertencem. A associação é feita pela **referência do chamador** — o número
sobrescrito no texto — e não pela posição da nota, então cada nota vai para o
capítulo certo mesmo quando a linha está no pé da página. Notas de várias
linhas são agrupadas; um chamador na **linha do título** vira link no próprio
heading.

No EPUB, o chamador vira um `<a epub:type="noteref">` para o `id` da nota e
cada nota traz o **link de volta** ao chamador (`epub:type="backlink"`). Quando
um capítulo é dividido em continuações, as notas são distribuídas pela parte que
as chama para os links continuarem resolvendo dentro do mesmo arquivo.

## 🔎 Revisão antes de exportar

O passo 3 é onde o livro é conferido: cada capítulo aparece com o título editável,
o interruptor de inclusão e a contagem de notas. O botão **editar** abre o texto
completo do capítulo em um campo por parágrafo — corrigir, apagar um trecho ou
reescrever é local ao navegador e entra no EPUB pelo campo `edit` da exportação.
Esgotar todos os parágrafos de um capítulo é recusado: para tirá-lo do livro, use
o interruptor.

As **notas de rodapé aparecem no fim da prévia do capítulo**, na mesma ordem em
que saem no EPUB. Sem isso, a única forma de conferir a associação das notas era
abrir o arquivo já exportado.

## 🎨 Capa

Com `cover=True` (padrão), uma **capa procedural** de **1600×2560** (proporção
KDP 1:1.6) é gerada em JPEG com PyMuPDF — sem dependência extra — com título e
autor sobre fundo e moldura sóbrios.

O autor pode enviar a **própria capa** pelo passo 3 (JPEG ou PNG, até
`MAX_COVER_MB`): a imagem é validada pelos *magic bytes* **e** por uma
decodificação real com PyMuPDF, então um PDF renomeado para `.jpg` é recusado na
hora, com mensagem clara, em vez de virar página em branco no leitor. A prévia
mostrada na tela vem do próprio servidor — é exatamente a imagem que entra no
EPUB. O botão “usar capa gerada” descarta o envio.

Programaticamente, `build_epub(..., cover_image=...)` aceita caminho
(`str`/`Path`) ou `bytes`; `cover=False` omite a capa. A capa entra como imagem
de capa, `capa.xhtml` é o primeiro item do spine e a página de título vem logo
depois.

Título, autor, **descrição** e **editora** viram metadados Dublin Core do OPF
(`dc:title`, `dc:creator`, `dc:description`, `dc:publisher`), que a KDP usa no
preview da loja. Descrição e editora são opcionais e não geram tag vazia quando
não informadas.

## 📁 Estrutura

```
kdp-studio/
├── backend/app/
│   ├── config.py        # Settings: env, limites, timeouts, modelos por provider
│   ├── env_file.py      # atualização segura do .env (usado pelo configurar-ia.sh)
│   ├── models.py        # Run, Line, Paragraph, Chapter, ChapterView, JobState
│   ├── jobs.py          # JobStore: progresso, cancelamento, TTL
│   ├── llm.py           # provider + timeout + retry + fallback de modelos
│   ├── pdf_extract.py   # PyMuPDF -> linhas com geometria e formatação inline
│   ├── pdf_chapters.py  # bookmarks + índice impresso + heurística + notas
│   ├── translate.py     # tradução em lote, paralela, com progresso
│   ├── kdp_epub.py      # EPUB 3 (notas, capa), escrita atômica e validação
│   ├── cover.py         # capa procedural, validação de capa enviada
│   └── main.py          # rotas
├── static/{index.html,app.js,styles.css,vendor/tailwind.js}
├── tests/               # unitários, API e aceitação (sintética + PDFs reais)
├── configurar-ia.sh     # configuração interativa da chave de IA
├── .github/workflows/   # CI: lint + testes + byte-compile em Python 3.10 e 3.13
└── docs/superpowers/    # specs e plano (o que ficou obsoleto vai em archive/)
```

## 🧪 Testes e lint

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q          # suíte completa (offline, sem chamadas de LLM)

npm run lint                  # ruff, com o conjunto de regras do pyproject.toml
npm run check                 # lint + byte-compile do backend + sintaxe do app.js

# aceitação: roda a sintética (notas + capa) sempre e a de PDFs reais só se a
# variável apontar para um diretório com os livros:
KDP_REAL_PDFS_DIR="$HOME/Downloads" python3 -m pytest -q -m acceptance
```

O marcador `acceptance` inclui um teste sintético ponta a ponta (PDF de fixture
gerado no próprio teste → capítulos → EPUB com notas e capa) que **não** depende
de `KDP_REAL_PDFS_DIR`. A verificação dos PDFs reais é pulada graciosamente
quando a variável não existe.

A suíte nunca chama a API real: a fixture `offline` transforma qualquer criação
de cliente de LLM em erro.

O CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) roda lint, testes e
byte-compile do backend em Python 3.10 e 3.13, além da sintaxe do frontend, a
cada push e pull request.

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
- Os **chamadores de nota são preservados na tradução em modo *best-effort***:
  o pipeline troca cada chamador pelo token `⟦N⟧` e pede ao modelo que o
  mantenha. Se o modelo remover o token, o chamador é reanexado ao fim do
  parágrafo e o job registra um aviso — a nota não se perde, mas pode sair de
  posição.
- A detecção por heurística (PDFs sem bookmarks nem índice) é menos precisa que
  a via bookmarks e pode exigir revisão manual dos títulos.
- A **capa enviada** é validada quanto ao formato e à legibilidade, não quanto à
  proporção: uma imagem fora de 1:1.6 é aceita como está e a KDP pode recusá-la
  no upload.
- A **edição de texto** vive no navegador até a exportação: recarregar a página
  descarta as correções não exportadas.
- Os **jobs vivem em memória**: reiniciar o servidor descarta jobs, capas
  enviadas e edições pendentes. O EPUB já baixado não é afetado.
- Com **tradução ativada**, o texto do livro é enviado à API do provedor de IA
  escolhido; sem o toggle, nada sai da máquina.

## 📌 Escopo

Esta versão foca em **PDF → EPUB**, **revisão do texto e dos capítulos** e
**tradução**. A **capa** faz parte do escopo, procedural e por imagem enviada
pelo autor (ver “🎨 Capa”). Foram removidos da base anterior: o assistente de
criação de livros com IA, a exportação DOCX e a biblioteca de arquivos. O
histórico está no git (o estado anterior à refatoração é o commit `957c3fa`).
