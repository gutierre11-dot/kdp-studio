# Política de segurança

## Modelo de ameaça

O KDP Studio é uma aplicação **local-first**. Por padrão, o servidor escuta
apenas em `127.0.0.1` (`HOST=127.0.0.1`) e o CORS aceita somente as origens
locais padrão (`http://localhost:8000` e `http://127.0.0.1:8000`). Não há
autenticação, contas de usuário nem telemetria.

Isso significa que:

- Qualquer pessoa com acesso à máquina onde o servidor roda pode acessar a
  interface e os jobs em memória.
- Uploads, textos extraídos, capas e EPUBs gerados ficam na máquina local; com
  tradução ativada, o texto do livro é enviado ao provedor de IA configurado.
- O servidor **não foi projetado para ser exposto à internet ou a uma rede
  compartilhada**. Se `HOST` for alterado para `0.0.0.0` ou para o IP da
  máquina, não há autenticação ou controle de acesso para impedir o uso por
  terceiros.

## Versões suportadas

| Versão | Suporte a correções de segurança |
|---|---|
| 1.x | Sim |
| < 1.0 | Não |

## Como reportar uma vulnerabilidade

Reporte de forma **privada** pelo GitHub Security Advisories:

<https://github.com/gutierre11-dot/kdp-studio/security/advisories/new>

Inclua, se possível:

- versão do projeto e sistema operacional;
- descrição do impacto e do cenário de exploração;
- passos para reproduzir, com dados sintéticos;
- sugestão de correção, se houver.

Não abra issue pública, discussão ou pull request com detalhes de exploração
antes de a correção ser publicada. Os mantenedores avaliam o relato e combinam
o prazo de divulgação com quem reportou, conforme o caso.

## O que não publicar em issue pública

- Chaves de API, tokens, cookies ou qualquer credencial (mesmo revogadas).
- PDFs, capas, trechos de livros ou dados pessoais de terceiros.
- Logs com caminhos pessoais, chaves, prompts ou conteúdo protegido.
- Detalhes de exploração de uma vulnerabilidade ainda não corrigida.

Ao relatar um bug comum, remova esses dados dos logs e use um PDF sintético
para reproduzir o problema. Se o relato depender de um arquivo real, descreva o
formato em vez de anexá-lo.

## Recomendações de operação

- Mantenha o padrão `HOST=127.0.0.1`. Para acesso remoto, use um proxy reverso
  com autenticação e TLS, além de restringir as origens permitidas em
  `CORS_ORIGINS`.
- Não exponha o servidor na rede sem autenticação; não há controle de usuários.
- Guarde as chaves de IA **somente no `.env` local**, com permissão `600`
  (`chmod 600 .env`), e nunca as versione.
- Ao terminar de usar ou ao trocar de máquina, apague o `.env` e os artefatos em
  `output/` que contenham obras de terceiros.
- Mantenha as dependências atualizadas; o `requirements-dev.txt` fixa as
  ferramentas de desenvolvimento e o CI valida Python 3.10 e 3.13.

## Escopo

Falhas de segurança no backend FastAPI, no pipeline de PDF/EPUB, na tradução, no
frontend servido localmente e nos scripts auxiliares são de interesse. Problemas
que dependem de o servidor já estar exposto publicamente, de acesso físico à
máquina ou de um ambiente comprometido podem ser tratados como configuração
insegura, mas ainda são bem-vindos no relato privado.
