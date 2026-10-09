# Melhorias da conversão PDF → EPUB

Data: 2026-10-09
Status: implementado
Baseline: commit `a4590da`

## 1. Contexto

O pipeline PDF → EPUB já cobria PDFs com bookmarks, mas ainda errava em casos
reais: livros sem outline utilizável, títulos em negrito menores que o corpo,
parágrafos partidos por sobreposição de caixas do PyMuPDF, notas de rodapé
tratadas como cabeçalho corrente e um único "capítulo" gigante em PDFs sem
estrutura fina. Faltava também capa. Esta rodada corrige esses pontos mantendo
o caminho **100 % determinístico** (sem LLM): a IA continua entrando **apenas**
na tradução opcional.

## 2. Melhorias

| # | Melhoria | Onde | O que faz |
|---|---|---|---|
| 1 | Outline pelo **Índice impresso** | `pdf_chapters.parse_printed_toc`, `anchor_printed_outline`, `build_chapters` | Sem bookmarks usáveis, lê `Índice`/`Sumário`/`Contents`, ancora as entradas por similaridade (o offset da página impressa é desconhecido) e remove o bloco do corpo. |
| 2 | **Título negrito menor que o corpo** | `pdf_chapters.detect_headings` | Captura linha com negrito dominante (≥ 60 % dos caracteres) e isolada (≤ 70 % da largura máxima da fonte), que sumiria na comparação de tamanho. |
| 3 | **Junção de parágrafos** com gaps negativos | `pdf_chapters._continua_paragrafo` | Tolera a sobreposição de bboxes do PyMuPDF (~2pt) sem tratar como quebra de parágrafo. |
| 4 | Cabeçalho corrente com **padding** | `pdf_chapters.cleaning_mask` | Mede o tamanho do texto normalizado, para pegar cabeçalhos com espaços extras no texto cru. |
| 5 | Remoção de **sumário / ficha / capa** do corpo | `pdf_chapters.build_chapters` (`toc_lines` + limpeza) | A página de índice e os paratextos iniciais não viram capítulos. |
| 6 | **Capítulos longos → continuações** | `models.Chapter.continues`, `pdf_chapters._dividir_capitulos_longos` | Acima de ~15 mil palavras, divide em partes equilibradas. As demais partes repetem o título, entram no spine, mas sem heading próprio nem entrada duplicada no sumário. |
| 7 | **Notas de rodapé → endnotes** | `pdf_chapters.extract_notes`, `_notas_por_ancora`, `_notas_do_capitulo`; `kdp_epub.chapter_fragment`, `_notas_html`, `_runs_html` | A nota sai do corpo e vai ao fim do capítulo que a chama, com link de ida (`noteref`) e volta (`backlink`); notas multi-linha são agrupadas; a associação usa a **referência do chamador**; chamador na linha do título vira link no heading (`Chapter.title_refs`). |
| 8 | **Capa** | `cover.build_cover`; `kdp_epub.build_epub(cover=, cover_image=)` | Capa procedural JPEG **1600×2560** via PyMuPDF; aceita **capa externa** JPEG/PNG por caminho ou `bytes` (magic bytes). |
| 9 | **Nav sem `page-list`** | `kdp_epub._write_epub_file` (`epub3_pages=False`) | Evita despejar centenas de âncoras de nota na navegação. |
| 10 | **Chamadores na tradução** | `translate._tokenizar`, `_reconstruir_paragrafo` | Substitui cada chamador pelo token `⟦N⟧` e o reconstrói como run superscript. |

## 3. Determinístico vs. best-effort

- **Determinístico (sem IA):** itens 1–9. Testável offline, sem rede.
- **Best-effort (depende do LLM):** item 10. O token `⟦N⟧` pode ser removido
  pelo modelo; nesse caso o chamador é **reanexado ao fim do parágrafo** e o job
  registra aviso — a nota não se perde, mas pode mudar de posição.

## 4. Limitações conhecidas

- **PDFs escaneados** (sem camada de texto) são recusados; não há OCR.
- No **texto traduzido**, itálico/negrito não são preservados (o original preserva).
- O token de nota depende do modelo (ver §3).
- A heurística de fontes (sem bookmarks nem índice) é menos precisa e pode exigir
  revisão manual dos títulos.
- A capa procedural usa fontes base-14: glifos fora de Latin/Greek/Cyrillic
  (emoji, CJK) são filtrados ou convertidos para ASCII para não sair caixa vazia.

## 5. Como verificar

```bash
# Suíte completa (offline, sem chamadas de LLM)
python3 -m pytest -o addopts="" -q

# Aceitação: sintética sempre; PDFs reais só se a variável existir
KDP_REAL_PDFS_DIR="$HOME/Downloads" python3 -m pytest -o addopts="" -q -m acceptance
```

- `tests/test_acceptance_notes_cover.py` — ponta a ponta sintético (não depende
  de `KDP_REAL_PDFS_DIR`): PDF de fixture → capítulos com nota → EPUB com
  `cover=True` (e com `cover_image=`), checando capa, spine e integridade dos
  links de nota.
- `tests/test_acceptance_real_pdfs.py` — PDFs reais (pulado sem a variável):
  cada livro gera um EPUB que passa em `validate_epub`, tem capa e mantém cada
  `href="#fn-N"` com um `id="fn-N"` no mesmo arquivo.
- **EPUBCheck** (opcional, externo, exige Java): `java -jar epubcheck.jar livro.epub` — espera-se 0 erros.
