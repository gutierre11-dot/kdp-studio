# Google Gemini no KDP Studio

Guia objetivo (PT-BR) para usar o Google Gemini como IA generativa de
tradução pt-BR e criação de ebooks, mantendo compatibilidade com OpenAI
e modo offline.

## 1. Onde pegar a chave

1. Acesse https://aistudio.google.com (Google AI Studio).
2. Entre com sua conta Google.
3. Clique em **Get API key** / **Create API key**.
4. Copie a chave (começa com `AIza...`).

Sem a chave, o app continua funcionando em **modo offline** (mock local,
capa Pillow).

## 2. Como preencher o `.env`

Na raiz `kdp-studio/`, copie o exemplo e preencha:

```bash
cp .env.example .env
```

O arquivo é carregado **automaticamente** pela aplicação
(`backend/app/llm.py`), tanto por `./run.sh` quanto por
`uvicorn backend.app.main:app`. Use **um único** `.env` (na raiz) para
não duplicar o segredo; `backend/.env` continua sendo lido por
compatibilidade, mas não é necessário.

Conteúdo mínimo para Gemini:

```dotenv
# Deixe OPENAI vazio para ativar o Gemini automaticamente
OPENAI_API_KEY=
TRANSLATION_MODEL=
CREATION_MODEL=
COVER_MODEL=dall-e-3

GEMINI_API_KEY=AIza...sua-chave...
GEMINI_MODEL=gemini-2.0-flash
```

Regras de prioridade (`backend/app/llm.py`):

- `OPENAI_API_KEY` presente → provider `openai` (vale para OpenAI,
  OpenRouter, DeepSeek via `OPENAI_BASE_URL`).
- `OPENAI_API_KEY` vazio + `GEMINI_API_KEY` presente → provider `gemini`,
  via endpoint OpenAI-compatible
  `https://generativelanguage.googleapis.com/v1beta/openai/`.
- Nenhuma chave → provider `offline` (mock + Pillow, sem custo).

Alternativa sem `GEMINI_API_KEY` (avan­çado): aponte o cliente
OpenAI-compatible diretamente para o Google:

```dotenv
OPENAI_API_KEY=AIza...sua-chave...
OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
TRANSLATION_MODEL=gemini-2.0-flash
CREATION_MODEL=gemini-1.5-pro
```

## 3. Modelos recomendados

| Uso      | Modelo             | Motivo                              |
|----------|--------------------|-------------------------------------|
| Tradução | `gemini-2.0-flash` | Rápido, barato, bom em pt-BR       |
| Criação  | `gemini-1.5-pro`   | Janela longa, melhor narrativa      |
| Padrão   | `gemini-2.0-flash` | Default de `GEMINI_MODEL`           |

`TRANSLATION_MODEL` / `CREATION_MODEL` têm prioridade sobre
`GEMINI_MODEL` quando preenchidos. Exemplo para usar Pro na criação:

```dotenv
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.0-flash
CREATION_MODEL=gemini-1.5-pro
```

Modelos OpenAI continuam válidos (`gpt-4o-mini` tradução,
`gpt-4o` criação) quando `OPENAI_API_KEY` está configurado.

## 4. Custo

- Google AI Studio oferece **cota gratuita** generosa para testes
  (limites por minuto/dia variam por modelo e região).
- Tradução/criação de livros consomem muitos tokens: acompanhe o uso em
  https://aistudio.google.com (Usage/Billing).
- Sem chave: custo zero (modo offline + capa Pillow local).

## 5. Como testar

Com o backend rodando (`uvicorn backend.app.main:app --port 8000`
a partir de `kdp-studio/`):

```bash
# Status do provider
curl -s http://localhost:8000/api/models | python3 -m json.tool
# Esperado com Gemini: {"provider_ativo": "gemini", "gemini_configurado": true, ...}

# Tradução (JSON legado)
curl -s -X POST http://localhost:8000/api/translate \
  -H 'Content-Type: application/json' \
  -d '{"chapters": [{"title": "Chapter 1", "paragraphs": ["Hello world"]}]}' \
  | python3 -m json.tool

# Tradução (FormData, igual ao frontend) — destino pt-BR
curl -s -X POST http://localhost:8000/api/translate \
  -F 'text=Hello world' -F 'source_lang=en' -F 'target_lang=pt-BR' | python3 -m json.tool

# Tradução para inglês (target_lang é respeitado de verdade)
curl -s -X POST http://localhost:8000/api/translate \
  -F 'text=Olá mundo' -F 'source_lang=pt-BR' -F 'target_lang=en' | python3 -m json.tool
```

> Sem chave válida, a resposta vem do mock offline marcada com o idioma de
> destino (ex.: `[en mock] ...`) — prova de que `target_lang` chegou ao
> tradutor.

Com `GEMINI_API_KEY` inválida/fake, o app **não quebra**: a chamada LLM
falha e cai no fallback offline (`[PT-BR mock]`), e `/api/models`
continua respondendo `provider_ativo=gemini`.

## 6. Capas (Imagen não incluso)

O endpoint OpenAI-compatible do Gemini cobre só linguagem
(chat/completions). Geração de imagem (Imagen) usa API separada e
**não está inclusa**: mesmo com `GEMINI_API_KEY`, `cover.py` usa o
fallback Pillow local (gradiente premium, sem custo). Só `OPENAI_API_KEY`
+ `COVER_MODEL=dall-e-3` tenta `images.generate`.
