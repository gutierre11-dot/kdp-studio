# Como contribuir com o KDP Studio

Obrigado pelo interesse em contribuir. Este documento descreve o ambiente de
desenvolvimento, o padrão de commits e o que esperamos de um pull request.

## Antes de começar

- O projeto é **local-first**: roda na máquina de quem usa e **não envia
  telemetria**. Contribuições devem preservar esse princípio — nada de
  analytics, rastreamento ou chamadas externas que não sejam a API de tradução
  configurada explicitamente pelo usuário.
- Abra uma issue antes de mudanças grandes, para alinhar o escopo e a decisão de
  produto antes de escrever código.
- Para vulnerabilidades, **não abra issue pública**: siga o
  [SECURITY.md](SECURITY.md).

## Como rodar

Pré-requisitos: Python 3.10 ou superior e Node.js (apenas para a checagem de
sintaxe do frontend).

```bash
./run.sh
```

O script instala as dependências de runtime se faltarem e sobe o servidor em
`http://127.0.0.1:8000`. Variáveis úteis:

```bash
PORT=9000 ./run.sh      # outra porta
RELOAD=0 ./run.sh       # sem recarregamento automático
```

Sem chave de IA o fluxo PDF → EPUB continua funcionando; apenas a tradução fica
indisponível.

## Ambiente de desenvolvimento

```bash
python3 -m pip install -r requirements-dev.txt
```

Isso instala o runtime, o `pytest` e o `ruff` nas versões fixadas pelo projeto.

## Testes, lint e checagem completa

```bash
python3 -m pytest -q          # suíte completa, offline
python3 -m ruff check .       # lint
npm run check                 # lint + byte-compile do backend + node --check
```

A suíte não chama a API real de nenhum provedor. Testes de aceitação com PDFs
reais são opcionais e só rodam quando `KDP_REAL_PDFS_DIR` aponta para um
diretório com os arquivos:

```bash
KDP_REAL_PDFS_DIR="$HOME/Downloads" python3 -m pytest -q -m acceptance
```

## Padrão de commits

Use [Conventional Commits](https://www.conventionalcommits.org/pt-br/):

```text
<tipo>(<escopo opcional>): <descrição no imperativo>

<corpo opcional>

<rodapé opcional>
```

Tipos mais usados: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`,
`ci`, `chore`. Exemplos:

```text
feat(epub): preserva chamadores de nota na tradução
fix(jobs): libera artefatos ao cancelar
docs: explica a detecção por índice impresso
```

Commits pequenos e com uma única intenção são mais fáceis de revisar. Se o
commit alterar comportamento, diga no corpo o que muda para quem usa.

## Segredos

- **Nunca commite `.env`, `backend/.env` ou qualquer arquivo com chaves.**
  Eles já estão no `.gitignore`; não remova essas entradas.
- Use `.env.example` como referência e mantenha as chaves apenas no seu `.env`
  local, com permissão `600` (`chmod 600 .env`).
- Não inclua PDFs, capas ou logs de clientes em issues, commits ou testes sem
  autorização. Prefira exemplos sintéticos.
- Se uma chave vazar em um commit ou issue, revogue-a no provedor e avise os
  mantenedores; remover o arquivo do commit não basta.

## Como propor mudanças

1. Faça um fork do repositório.
2. Crie um branch descritivo a partir de `main`:
   `git checkout -b feat/endnotes-multilinha`.
3. Implemente a mudança com testes quando o comportamento for alterado.
4. Rode `python3 -m pytest -q`, `python3 -m ruff check .` e `npm run check`.
5. Abra um pull request descrevendo o problema, a solução e a decisão de
   produto envolvida.

## Requisitos de pull request

- Testes e lint verdes; `npm run check` sem erros.
- Mudança de comportamento descrita no PR, com o motivo da decisão de produto
  (por que esse fluxo, esse padrão ou esse limite).
- Testes cobrindo o novo comportamento ou a correção.
- Nenhum segredo, dado pessoal, PDF protegido ou artefato gerado no diff.
- Documentação atualizada quando a interface, a API, a configuração ou o
  processo mudarem.
- Um PR por assunto, com histórico de commits legível.

## Dúvidas

Use as [issues do repositório](https://github.com/gutierre11-dot/kdp-studio/issues)
para dúvidas de uso e propostas. Para falhas de segurança, use o canal privado
descrito em [SECURITY.md](SECURITY.md).
