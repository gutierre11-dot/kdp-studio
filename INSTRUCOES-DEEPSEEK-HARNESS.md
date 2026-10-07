# Instrução para o DeepSeek Harness

> **Objetivo deste arquivo:** ser uma especificação autocontida e acionável. Copie o
> conteúdo da seção **“PROMPT (copiar daqui para baixo)”** e entregue ao harness
> como a tarefa a executar no repositório `kdp-studio`.

---

## Sumário do pacote de otimização (meta, para o humano)

- **Target**: agente de código (DeepSeek Harness) implementando no repo `kdp-studio`.
- **Tipo de tarefa**: especificação de nova capacidade (do zero), multi-arquivo.
- **Superfície do prompt**: `user`/tarefa (não system). Este brief é o payload.
- **Critérios de sucesso**: ver `CRITÉRIOS DE ACEITE` abaixo (mensuráveis).
- **Arquivos externos**: listados por caminho exato em `ARQUIVOS DO REPOSITÓRIO`.
- **Adapter notes**: instrução agnóstica de provider LLM; funciona com OpenAI/Gemini/offline.
- **Riscos residuais**: ver `RISCOS E LIMITAÇÕES` no fim.

---

# PROMPT (copiar daqui para baixo)

## <role>

Você é um engenheiro de software trabalhando no repositório `kdp-studio`
(Python/FastAPI + SPA sem build em `static/`). Implemente mudanças mínimas,
consistentes com o estilo existente, e **prove** que funcionam rodando testes.

## <goal>

Entregar o fluxo **"PDF (ex.: em inglês) → tradução → EPUB no padrão KDP"**,
com tradução **opcional por toggle (um clique)**, integrada à conversão de modo
que **tradução e geração do EPUB aconteçam no mesmo job**.

A capacidade deve existir em **duas entradas**:

1. **Aba Converter** — toggle "Traduzir antes de converter".
2. **Aba Traduzir** — aceitar **PDF** e toggle "Exportar EPUB KDP".

Se qualquer parte já existir, **verifique, corrija e complete**; o critério é o
comportamento descrito, não o estado atual do código.

## <contexto_do_repo>

- Backend: FastAPI em `backend/app/` — módulos:
  `main.py`, `creator.py`, `translator.py`, `pdf_cleaner.py`, `kdp_export.py`,
  `cover.py`, `llm.py`.
- Frontend: SPA sem build em `static/index.html`, `static/app.js`, `static/styles.css`
  (Tailwind servido localmente em `static/vendor/tailwind.js`).
- Dependências-chave (ver `backend/requirements.txt`): `pymupdf`, `ebooklib`, `python-docx`.
- Testes: `pytest` em `tests/` (`conftest.py`, `test_api.py`, `test_*`).
- Saída gerada em `output/`, servida em `/download/`.
- Sem chave de LLM, o app roda em **modo offline** e devolve tradução mock
  prefixada com `[<target_lang> mock] ` (ver `translator.py`).

## <arquivos_do_repositorio>

Leia antes de alterar (referências por caminho; não invente estrutura):

```text
<external_files>
- backend/app/main.py        (rotas, helpers de job/export; LOADED)
- backend/app/translator.py  (translate_chapters, defaults de idioma; LOADED)
- backend/app/pdf_cleaner.py (parse_pdf_to_chapters, placeholders; LOADED)
- backend/app/kdp_export.py  (export_epub/export_docx, KDP_CSS; LOADED)
- backend/app/llm.py         (provider ativo, modelos efetivos; REFERENCED)
- static/index.html          (markup das abas Converter/Traduzir; LOADED)
- static/app.js              (handlers, FormData, toggles; LOADED)
- tests/conftest.py          (fixtures make_pdf, offline; LOADED)
- tests/test_api.py          (integração da API; LOADED)
- README.md                  (documentar novos campos; REFERENCED)
</external_files>
```

## <fatos_do_codigo_base>

Contratos já existentes que você DEVE reutilizar:

- `translator.translate_chapters(chapters, model, source_lang, target_lang) -> list`
  recebe e devolve capítulos no shape `{title, level, paragraphs: list[str]}`.
- Defaults de idioma: `translator.DEFAULT_SOURCE_LANG == "auto"` e
  `translator.DEFAULT_TARGET_LANG == "pt-BR"`.
- `kdp_export.export_epub(chapters, title, author, out_path, cover_path=None, lang="pt-BR")`
  gera o EPUB "KDP" (Times New Roman 12pt, recuo 1.5cm, quebra de capítulo, TOC, metadados).
- `pdf_cleaner.parse_pdf_to_chapters(pdf_path, remove_header=True, remove_page_numbers=True)`
  devolve `[{title, level, paragraphs}]`. Para PDF sem texto devolve
  `[{"title":"Texto","level":1,"paragraphs":["(PDF sem texto extraivel.)"]}]`;
  capítulos vazios recebem `"(sem conteúdo)"`.
- Helpers em `main.py`: `_as_bool(value, default)`, `_enrich_chapters`,
  `_norm_export_chapters`, `_save_and_urls`, `_register_job`, `_unique_path`, `_slug`.
- O fluxo de conversão usado pela UI é `POST /api/convert`; ele já recebe os toggles
  `remove_header`/`remove_page_numbers` e gera EPUB+DOCX+preview, registrando um job.
- Padrão de toggle na UI: `<span class="toggle" role="switch" aria-checked>`
  alternando a classe `on`; o estado é lido via `classList.contains('on')`.
- `conftest.py` possui fixture `offline` (autouse) que força `llm_available=False`,
  então testes de tradução usam o mock `[<target> mock]`.

## <requisitos>

**R1 — Toggle de tradução no conversor (default DESLIGADO).**
- Novo toggle na aba Converter, componente `.toggle` (sem `on` no estado inicial).
- Ao ligar, opcionalmente revele seletores De/Para/Modelo; com o painel oculto,
  o backend usa `auto → pt-BR`.
- O valor é enviado no FormData como `translate=true|false`.

**R2 — Tradução integrada ao job de conversão.**
- `POST /api/convert` aceita `translate`, `source_lang`, `target_lang`,
  `translation_model` (todos opcionais).
- Quando `translate` é verdadeiro: traduza os capítulos **antes** de gerar
  arquivos e de registrar o job, de modo que o **download do mesmo `job_id`**
  já entregue o EPUB/DOCX traduzidos.
- Defaults quando ausentes: `source_lang="auto"`, `target_lang="pt-BR"`,
  `translation_model=effective_translation_model()`.
- A resposta deve indicar `translated`, `source_lang`, `target_lang`,
  `translation_model`.

**R3 — Aba Traduzir aceita PDF e exporta EPUB KDP no mesmo job.**
- O input de arquivo da aba Traduzir deve aceitar **`.pdf`** (além de `.txt/.md/.docx`).
- `POST /api/translate` (ramo FormData **e** ramo JSON) aceita `export` (bool),
  `format` (`epub`), `title`, `author`.
- Quando `export` é verdadeiro: gere **apenas o EPUB** (não DOCX/prévia), registre
  um job e devolva `job_id`, `export: true`, `format: "epub"`, `epub` (URL
  `/download/<arquivo>.epub`) e `files`.
- A UI mostra um botão de download do EPUB apenas quando houver export.
- Ao traduzir um PDF, **preserve a estrutura de capítulos** do PDF (não achate em
  um único bloco de texto).

**R4 — Guarda para PDF sem texto.**
- Se `translate`/`export` estiver ligado e o PDF não tiver texto real (parágrafos
  são exatamente os placeholders `"(PDF sem texto extraivel.)"` ou `"(sem conteúdo)"`),
  responda **HTTP 422** com mensagem clara (OCR de PDFs escaneados não é suportado).
- A comparação deve ser **exata** (não substring): texto legítimo que apenas
  contenha a frase "sem conteúdo" NÃO deve ser rejeitado.

**R5 — Metadados KDP.**
- O EPUB gerado deve sair no padrão KDP já implementado em `kdp_export.KDP_CSS`
  (não introduza um novo pipeline de exportação).
- `title`/`author` vazios usam defaults (`"Tradução"`/`"Autor"`).

## <contrato_de_api>

| Rota | Campos novos (opcionais) | Retorno adicional |
|---|---|---|
| `POST /api/convert` | `translate`, `source_lang`, `target_lang`, `translation_model` | `translated`, `source_lang`, `target_lang`, `translation_model` |
| `POST /api/translate` (FormData/JSON) | `export`, `format`, `title`, `author` | `job_id`, `export`, `format`, `epub`, `files` |

## <critérios_de_aceite>

Marque cada item com evidência (comando + saída):

1. `translate` **off** (default): `/api/convert` não traduz e a resposta tem
   `translated=false` (sem marcador mock no texto).
2. `translate` **on**: a resposta de `/api/convert` contém `translated=true` e
   capítulos traduzidos; o EPUB baixado via `/api/convert/{job}/download` contém
   o texto traduzido (no modo offline, o marcador `[pt-BR mock]`).
3. Aba Traduzir aceita `.pdf` (atributo `accept` inclui `.pdf`).
4. `/api/translate` com `export=true` e um PDF devolve `job_id` + `epub`; o
   arquivo `.epub` existe e contém o texto traduzido; `chapters_traduzidos`
   preserva a estrutura (≥ nº de capítulos do PDF).
5. `/api/translate` **sem** `export` continua retornando só o texto (sem
   `job_id`/`epub`).
6. PDF sem texto + tradução → HTTP **422**; texto legítimo com a frase
   "sem conteúdo" → HTTP **200**.
7. Toda a suíte de testes passa.

## <casos_de_falha>

- Toggle meramente cosmético que não muda o job.
- EPUB que perde metadados/TOC/estilo KDP.
- Traduzir reenviando o texto duas vezes (retradução) — use os capítulos já
  traduzidos na própria requisição.
- Gerar arquivos irmãos órfãos quando só o EPUB foi pedido.
- Reportar sucesso sem de fato traduzir.

## <plano_sugerido>

1. Inspecione `main.py` (rotas de conversão e de tradução), `translator.py`,
   `pdf_cleaner.py`, `kdp_export.py`, `static/index.html`, `static/app.js`.
2. Backend:
   - Adicione a guarda de PDF sem texto (match exato dos placeholders).
   - Estenda `POST /api/convert` com os campos de tradução (R2).
   - Estenda `POST /api/translate` (FormData + JSON) com `export` (R3), reusando
     `_norm_export_chapters` + `kdp_export.export_epub` + `_register_job`.
3. Frontend:
   - Toggle no conversor (R1) + envio no FormData.
   - `accept=".pdf,..."` na aba Traduzir + toggle de export + botão de download.
4. Testes em `tests/test_api.py` cobrindo os critérios 1–6.
5. Documente os novos campos no `README.md`.

## <testes_obrigatorios>

Adicione testes de integração (TestClient) que cubram, no mínimo:
- conversão com `translate=true` → EPUB do mesmo `job_id` contém tradução;
- conversão sem `translate` → sem tradução;
- PDF sem texto + `translate=true` → 422;
- texto legítimo com "sem conteúdo" + `translate=true` → 200;
- `/api/translate` com PDF + `export=true` → EPUB traduzido gerado;
- `/api/translate` sem `export` → sem `job_id`/`epub`.

## <validacao>

Rode e cole a saída (deve estar tudo verde):

```bash
cd kdp-studio
python3 -m py_compile backend/app/*.py
node --check static/app.js        # se Node estiver disponível
python3 -m pytest
```

## <restricoes>

- Não reescreva a arquitetura nem troque o pipeline KDP existente.
- Não introduza dependências novas sem necessidade.
- Faça edições mínimas e coesas com o estilo do repositório.
- Se algo estiver ambíguo, prefira o comportamento descrito nos critérios de aceite.
- Não faça `git commit` sem instrução explícita.

## <fora_de_escopo>

- OCR de PDFs escaneados.
- Novos formatos de saída além de EPUB/DOCX já existentes.
- Fila/processamento assíncrono (o pipeline atual é síncrono).

## <definition_of_done>

- Os 7 critérios de aceite demonstrados com evidência.
- `pytest` 100% verde (incluindo os testes novos).
- `py_compile` OK e `node --check` OK.
- Relatório final listando arquivos alterados com referências `caminho:linha`
  e os comandos executados com suas saídas.

---

## Notes de otimização (para o humano, não para o harness)

- **Mudanças vs. pedido original**: separamos *descritivo* (contexto do repo) de
  *diretivas* (requisitos/restrições); fixamos o gate de aceite mensurável
  (evita “toggle cosmético” e “falso sucesso”); enumeramos arquivos por caminho.
- **Eval set**: os 7 critérios de aceite + os testes obrigatórios funcionam como
  conjunto de avaliação reprodutível.
- **Riscos residuais**:
  - Tradução real depende de chave de API; sem chave, o comportamento é o mock
    offline (`[<target> mock]`) — não confundir com falha.
  - O pipeline é síncrono; PDFs grandes aumentam a latência da requisição.
  - O export da aba Traduzir gera **apenas o EPUB** por design (evita órfãos);
    se DOCX for necessário ali, estender explicitamente.
