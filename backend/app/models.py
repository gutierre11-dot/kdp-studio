"""Modelo de dados compartilhado do pipeline PDF -> (traducao) -> EPUB.

`Paragraph` guarda *runs* para preservar italico/negrito no caminho em que o
texto nao passa pelo tradutor; quando um capitulo e traduzido, cada paragrafo
vira um unico `Run` sem formatacao inline.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# (indice da linha no fluxo de leitura, nivel do titulo, texto do titulo)
Anchor = tuple[int, int, str]


@dataclass(slots=True)
class Run:
    """Trecho de texto com formatacao inline."""

    text: str
    italic: bool = False
    bold: bool = False
    # Chamador de nota de rodape (superscript): preservado para virar link.
    superscript: bool = False
    # Hiperlink externo do PDF (http/https/mailto), quando houver.
    href: str | None = None


@dataclass(slots=True)
class Line:
    """Linha extraida do PDF, com geometria suficiente para classificacao."""

    page: int
    text: str
    size: float
    bold: bool
    italic: bool
    bbox: tuple[float, float, float, float]
    page_height: float
    page_width: float
    runs: list[Run]


@dataclass(slots=True)
class Paragraph:
    """Paragrafo como sequencia de runs."""

    runs: list[Run]

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    @classmethod
    def from_text(cls, text: str) -> Paragraph:
        return cls(runs=[Run(text)])


@dataclass(slots=True)
class Figure:
    """Imagem extraida do PDF e incorporada ao EPUB.

    `after_paragraph` e o indice (0-based) do paragrafo do capitulo depois do
    qual a figura entra; `-1` significa "logo apos o titulo / antes do primeiro
    paragrafo". A posicao e recalculada quando o capitulo e dividido ou fundido.
    """

    data: bytes
    ext: str = "jpg"
    width: int = 0
    height: int = 0
    alt: str = ""
    after_paragraph: int = -1
    # Posicao no PDF, usada apenas durante a montagem dos capitulos.
    page: int = 0
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


# Token que representa um chamador de nota superscript no texto plano. O mesmo
# formato atravessa a traducao (o modelo tende a preservar colchetes matematicos)
# e a edicao na interface — nos dois casos o run superscript e reconstruido no
# ponto exato em que o token estava.
TOKEN_NOTA_RE = re.compile(r"⟦(\d{1,3}|[*†‡§¶]+)⟧")

# Simbolos usados como chamadores/rotulos de nota. Viram chaves inteiras na
# faixa 1000+ para conviverem com a numeracao normal (1..999) no mesmo job.
SIMBOLOS_NOTA = "*†‡§¶"
_CHAVE_SIMBOLO = {"*": 1001, "†": 1002, "‡": 1003, "§": 1004, "¶": 1005}
_TEXTO_CHAVE = {chave: simbolo for simbolo, chave in _CHAVE_SIMBOLO.items()}


def chave_nota(texto: str | None) -> int | None:
    """Chave inteira de um chamador/rotulo de nota (numero ou simbolo)."""
    bruto = (texto or "").strip()
    if bruto.isdigit():
        numero = int(bruto)
        return numero if 1 <= numero <= 999 else None
    if bruto and all(c in SIMBOLOS_NOTA for c in bruto):
        if len(bruto) == 1:
            return _CHAVE_SIMBOLO[bruto]
        # Combinacoes (**, ††...) recebem uma chave estavel na mesma faixa.
        return 1000 + sum(ord(c) for c in bruto) % 900
    return None


def texto_nota(chave: int) -> str:
    """Texto visivel de uma chave de nota (usado em chamadores de titulo)."""
    return _TEXTO_CHAVE.get(int(chave), str(chave))


def texto_editavel(paragrafo: Paragraph) -> str:
    """Texto plano do paragrafo, com cada chamador de nota como `⟦N⟧`/`⟦*⟧`.

    Sem o token, o chamador viraria um digito solto no meio da frase e o link
    para a nota se perderia ao salvar o texto editado.
    """
    partes: list[str] = []
    for run in paragrafo.runs:
        texto = run.text or ""
        if run.superscript and chave_nota(texto) is not None:
            partes.append(f"⟦{texto.strip()}⟧")
        else:
            partes.append(texto)
    return "".join(partes)


def paragrafo_de_texto(texto: str) -> Paragraph:
    """Paragrafo a partir do texto plano, devolvendo `⟦N⟧` a run superscript."""
    runs: list[Run] = []
    for i, parte in enumerate(TOKEN_NOTA_RE.split(texto)):
        if i % 2 == 1:   # grupo capturado: o numero do chamador
            runs.append(Run(parte, superscript=True))
        elif parte:
            runs.append(Run(parte))
    return Paragraph(runs=runs or [Run("")])


@dataclass(slots=True)
class Chapter:
    """Capitulo/secao do livro, com nivel 1..3."""

    title: str
    level: int
    paragraphs: list[Paragraph]
    # Parte de continuacao de um capitulo longo dividido em varios arquivos:
    # entra no spine, mas sem cabecalho proprio nem entrada no sumario.
    continues: bool = False
    # Notas de rodape do capitulo, renderizadas como endnotes ao final dele.
    notes: list[tuple[int, str]] = field(default_factory=list)
    # Chamadores de nota que estao na propria linha do titulo (nao no corpo):
    # viram links no heading e entram na associacao de notas.
    title_refs: list[int] = field(default_factory=list)
    # Imagens do PDF preservadas neste capitulo, com a posicao no corpo.
    figures: list[Figure] = field(default_factory=list)

    @property
    def words(self) -> int:
        return sum(len(p.text.split()) for p in self.paragraphs)


@dataclass(slots=True)
class ChapterView:
    """Metadados de capitulo expostos pela API (sem o texto completo)."""

    index: int
    title: str
    level: int
    words: int
    preview: str
    included: bool = True
    # Quantidade de notas de rodape do capitulo, para a interface avisar que
    # ha endnotes a revisar mesmo sem carregar o texto completo.
    notes_count: int = 0
    # Quantidade de figuras preservadas do PDF.
    figures_count: int = 0


@dataclass
class JobState:
    """Estado de um job de conversao."""

    id: str
    title: str
    author: str
    language: str
    source_name: str
    translated: bool
    status: str = "queued"
    stage: str = ""
    progress: int = 0
    message: str = ""
    # Metadados opcionais do livro, que viram `dc:description` e
    # `dc:publisher` no OPF do EPUB.
    description: str = ""
    publisher: str = ""
    chapters: list[Chapter] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    # default_factory: cada job precisa do proprio Event, senao cancelar um
    # cancelaria todos.
    cancel: threading.Event = field(default_factory=threading.Event)
    created_at: float = field(default_factory=time.time)
    output_paths: list[Path] = field(default_factory=list)
    # Capa enviada pelo usuario (JPEG ou PNG). Sem ela, o EPUB recebe a capa
    # procedural gerada a partir de titulo e autor.
    cover_image: bytes | None = None
    cover_name: str | None = None
    cover_width: int = 0
    cover_height: int = 0

    @classmethod
    def new(cls, job_id: str, *, title: str, author: str, language: str,
            source_name: str, translated: bool, description: str = "",
            publisher: str = "") -> JobState:
        return cls(id=job_id, title=title, author=author, language=language,
                   source_name=source_name, translated=translated,
                   description=description, publisher=publisher)
