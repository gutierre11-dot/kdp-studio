# Resumo

Descreva o problema e a solução proposta. Se o PR alterar o comportamento do
produto, explique a decisão de produto e o impacto para quem usa.

## Tipo de mudança

- [ ] Correção de bug
- [ ] Nova funcionalidade
- [ ] Refatoração sem mudança de comportamento
- [ ] Documentação
- [ ] CI, build ou ferramentas

## Checklist

- [ ] `python3 -m pytest -q` passa.
- [ ] `python3 -m ruff check .` passa sem erros.
- [ ] `node --check static/app.js` passa (ou `npm run check` passa por completo).
- [ ] O diff não inclui `.env`, chaves, tokens, PDFs de terceiros ou artefatos gerados.
- [ ] A documentação foi atualizada quando necessário (README, SECURITY, CHANGELOG ou docstrings).
- [ ] Mudanças de comportamento estão descritas acima, com o motivo da decisão de produto.
- [ ] Adicionei ou atualizei testes para o novo comportamento ou para a correção.

## Como testar

Descreva os passos usados para validar a mudança, incluindo dados sintéticos
quando o caso depender de um PDF.
