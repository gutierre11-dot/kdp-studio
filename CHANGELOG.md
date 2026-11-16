# Changelog

Todas as mudanças notáveis deste projeto são documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/)
e este projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Changed

- Atualizada a dependência `lxml` para 6.1.3, disponibilizando wheel para o
  runtime Python atual e evitando a necessidade de bibliotecas de compilação
  locais em instalações compatíveis.
- O CI agora provisiona explicitamente Node.js e também faz byte-compile do
  backend, evitando depender de ferramentas pré-instaladas no runner.

## [1.0.0] - 2026-11-16

### Added

- Conversão de PDF para EPUB 3 no padrão KDP, com capítulos, sumário e metadados
  Dublin Core.
- Detecção de capítulos por bookmarks do PDF, índice impresso e heurística de
  fontes, com limpeza de cabeçalhos, rodapés e numeração de página.
- Notas de rodapé convertidas em endnotes ao fim de cada capítulo, com
  `epub:type="noteref"` no chamador e `epub:type="backlink"` na nota.
- Capa procedural de 1600×2560 (proporção 1:1.6) e upload de capa própria em
  JPEG ou PNG, com validação real do formato e prévia servida pelo backend.
- Tradução paralela por lotes, com cadeia de fallback de modelos e preservação
  *best-effort* dos chamadores de nota.
- Jobs assíncronos com progresso, etapas, cancelamento e expiração por TTL.
- Etapa de revisão com edição do texto parágrafo a parágrafo, inclusão e
  reordenação de capítulos e conferência das notas.
- Metadados `dc:description` e `dc:publisher` no OPF, além de título e autor.
- Validação do EPUB gerado e escrita atômica em `output/`.
- CI no GitHub Actions com lint, testes em Python 3.10 e 3.13 e checagem de
  sintaxe do frontend.

### Changed

- A exportação passou a validar o EPUB antes de disponibilizá-lo e a gravar em
  arquivo temporário com substituição atômica, evitando downloads incompletos.
- A tradução passou a rodar em chamadas paralelas com fallback automático de
  modelo quando o principal falha.
- Os jobs passaram a expor progresso real, mensagens de etapa, cancelamento e
  retenção configurável.
- A revisão passou a editar o capítulo por parágrafo, com as notas visíveis no
  fim da prévia.
- O EPUB passou a incluir descrição e editora quando informadas, sem gerar tags
  vazias.
- A capa passou a usar a imagem enviada quando existir e a procedural como
  padrão.

### Fixed

- Arquivos EPUB truncados ou corrompidos em caso de falha durante a escrita.
- Chamadores de nota sem vínculo com a nota correspondente no EPUB.
- Capítulos fora de ordem quando os bookmarks não coincidem com as linhas do
  texto, agora ancorados por similaridade.
- EPUBs sem capa em jobs que não enviam imagem.
- Falhas intermitentes de tradução por modelo indisponível, agora contornadas
  pela cadeia de fallback.

[Unreleased]: https://github.com/gutierre11-dot/kdp-studio/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/gutierre11-dot/kdp-studio/releases/tag/v1.0.0
