"""Exportacao KDP: EPUB (ebooklib) + DOCX (python-docx).

Estilos KDP: Times 12pt, first-line 1.5cm, chapter-break, TOC, metadados, capa 1600x2560.
"""
import html
import uuid
from pathlib import Path

KDP_CSS = """
body { font-family: 'Times New Roman', Times, serif; font-size: 12pt; line-height: 1.5; margin: 0 5%; }
h1 { font-size: 20pt; text-align: center; margin-top: 3em; margin-bottom: 1em; page-break-before: always; }
h2 { font-size: 16pt; text-align: left; margin-top: 2em; margin-bottom: 0.8em; }
p { text-indent: 1.5cm; margin: 0 0 0.3em 0; text-align: justify; }
p.noindent, h1 + p, h2 + p { text-indent: 0; }
.titulo-livro { text-align: center; font-size: 24pt; margin-top: 30%; }
.autor-livro { text-align: center; font-size: 14pt; margin-top: 1em; }
"""


def _esc(s: str) -> str:
    return html.escape(s or "")


def _chapter_html(title: str, level: int, paragraphs: list[str]) -> str:
    tag = "h1" if level == 1 else "h2"
    parts = [f"<{tag}>{_esc(title)}</{tag}>"]
    for i, p in enumerate(paragraphs):
        cls = ' class="noindent"' if i == 0 else ""
        parts.append(f"<p{cls}>{_esc(p)}</p>")
    return "\n".join(parts)


def export_epub(chapters: list, title: str, author: str, out_path: Path,
                cover_path: Path | None = None, lang: str = "pt-BR") -> Path:
    from ebooklib import epub

    out_path.parent.mkdir(parents=True, exist_ok=True)
    book = epub.EpubBook()
    # Identificador estavel por (titulo, autor). Antes usava so o titulo, o que
    # colidia para livros homonimos de autores diferentes.
    ident = f"{title or 'livro'}|{author or 'autor'}"
    book.set_identifier(f"kdp-{uuid.uuid5(uuid.NAMESPACE_DNS, ident).hex[:12]}")
    book.set_title(title or "Sem titulo")
    book.set_language(lang)
    book.add_author(author or "Autor Desconhecido")

    if cover_path and Path(cover_path).exists():
        with open(cover_path, "rb") as f:
            book.set_cover("cover.jpg", f.read())

    style = epub.EpubItem(uid="style_kdp", file_name="style/kdp.css",
                          media_type="text/css", content=KDP_CSS.encode())
    book.add_item(style)

    spine: list = []
    toc: list = []
    # Pagina de titulo
    title_html = (
        f'<div class="titulo-livro">{_esc(title)}</div>'
        f'<div class="autor-livro">{_esc(author)}</div>'
    )
    c0 = epub.EpubHtml(title="Titulo", file_name="titulo.xhtml", content=f"<html><body>{title_html}</body></html>")
    c0.add_item(style)
    book.add_item(c0)
    spine.append(c0)

    for i, ch in enumerate(chapters):
        fname = f"cap{i+1}.xhtml"
        content = (
            "<html><head></head><body>"
            + _chapter_html(ch.get("title", f"Capitulo {i+1}"),
                            int(ch.get("level", 1)),
                            ch.get("paragraphs", []))
            + "</body></html>"
        )
        item = epub.EpubHtml(title=ch.get("title", f"Capitulo {i+1}"),
                             file_name=fname, content=content)
        item.add_item(style)
        book.add_item(item)
        spine.append(item)
        toc.append(item)

    book.toc = tuple(toc)
    # nav.xhtml fica no manifest com properties="nav" (TOC único via NCX+Nav);
    # fora do spine para não duplicar entrada linear no OPF.
    book.spine = spine
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(out_path), book)
    return out_path


def export_docx(chapters: list, title: str, author: str, out_path: Path) -> Path:
    from docx import Document
    from docx.shared import Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()

    # Estilo Normal KDP: Times 12pt, justificado, first-line 1.5cm
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    pf = normal.paragraph_format
    pf.first_line_indent = Cm(1.5)
    pf.space_after = Pt(4)
    pf.line_spacing = 1.5
    for p in doc.paragraphs:
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    core = doc.core_properties
    core.title = title
    core.author = author
    core.language = "pt-BR"

    t = doc.add_heading(title or "Sem titulo", level=0)
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    a = doc.add_paragraph(author or "")
    a.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for ch in chapters:
        lvl = int(ch.get("level", 1))
        h = doc.add_heading(ch.get("title", ""), level=min(max(lvl, 1), 2))
        # chapter-break: cada H1 comeca em nova pagina
        if lvl == 1:
            h.paragraph_format.page_break_before = True
        for i, para in enumerate(ch.get("paragraphs", [])):
            p = doc.add_paragraph(para)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            if i == 0:
                p.paragraph_format.first_line_indent = Cm(0)

    doc.save(str(out_path))
    return out_path


def build_preview_html(chapters: list, title: str, author: str, limit_chapters: int = 3) -> str:
    parts = [f"<h1>{_esc(title)}</h1><p><em>{_esc(author)}</em></p>"]
    for ch in chapters[:limit_chapters]:
        parts.append(_chapter_html(ch.get("title", ""), int(ch.get("level", 1)),
                                   (ch.get("paragraphs", [])[:4])))
    return f"<html><head><style>{KDP_CSS}</style></head><body>{''.join(parts)}</body></html>"
