"""Extrai e limpa PDFs com PyMuPDF.

Pipeline:
- extrai blocos de texto com font sizes (dict blocks);
- junta as linhas de um mesmo paragrafo (evita quebrar no meio da frase,
  inclusive com des-hifenizacao: "transfor-" + "macao" -> "transformacao");
- detecta H1/H2 por percentil de tamanhos;
- remove header/footer repetidos e numeracao (cada limpeza e' opcional).
"""
import logging
import re
from pathlib import Path

try:  # PyMuPDF >= 1.24 expoe `pymupdf`; `fitz` esta em desuso.
    import pymupdf as fitz
except ImportError:  # pragma: no cover - compatibilidade com versoes antigas
    import fitz  # type: ignore

log = logging.getLogger(__name__)

# Numeracao de pagina: apenas linhas curtas e claramente numericas.
PAGE_NUM_RE = re.compile(
    r"^(?:\d{1,6}|p[aá]gina\s+\d{1,6}|\d{1,6}\s*\|\s*.+|.+\s*\|\s*\d{1,6})$",
    re.IGNORECASE,
)

# Linhas que sao quase certamente header/footer
JUNK_RE = re.compile(
    r"^(www\.|http|\S+@\S+|todos os direitos reservados|copyright|©|isbn)",
    re.IGNORECASE,
)

# Titulos de capitulo sem destaque de fonte
CHAPTER_RE = re.compile(
    r"^(cap[ií]tulo|chapter|parte|part\s+\d+|cap\.?)\s+[\divxlc]+",
    re.IGNORECASE,
)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 12.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(len(s) * pct / 100)))
    return s[idx]


def _join_lines(lines: list[str]) -> str:
    """Une linhas de um mesmo paragrafo em um unico texto."""
    out = ""
    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue
        if not out:
            out = ln
            continue
        if out.endswith("-") and ln[:1].islower():
            # palavra hifenizada quebrada entre linhas
            out = out[:-1] + ln
        else:
            out = out + " " + ln
    return out.strip()


def _largura(bbox) -> float:
    try:
        return max(0.0, float(bbox[2]) - float(bbox[0]))
    except (TypeError, IndexError, ValueError):
        return 0.0


def _continua_paragrafo(prev: dict, cur: dict, largura_max: float) -> bool:
    """Decide se `cur` e' a continuacao do paragrafo `prev` (mesma pagina).

    Criterios: mesma fonte/tamanho, sem salto vertical grande e a linha
    anterior ocupando quase toda a largura da coluna (sinal classico de que a
    frase continua na linha seguinte). Um paragrafo terminado (ultima linha
    curta) nao "puxa" o proximo.
    """
    if abs(prev["size"] - cur["size"]) > 0.5 or prev["bold"] != cur["bold"]:
        return False
    texto_cur = cur["lines"][0] if cur["lines"] else ""
    if CHAPTER_RE.match(texto_cur):
        return False
    if texto_cur.isupper() and len(texto_cur) < 80:
        return False
    gap = float(cur["bbox"][1]) - float(prev["bbox"][3])
    if gap < -2 or gap > max(1.8 * cur["size"], 6.0):
        return False
    larga = largura_max > 0 and prev.get("last_w", 0) >= 0.8 * largura_max
    return larga or prev["lines"][-1].endswith("-")


def _merge_runs(runs: list[dict]) -> list[dict]:
    """Agrupa runs consecutivos de um mesmo paragrafo (por pagina)."""
    if not runs:
        return []
    max_por_tamanho: dict[float, float] = {}
    for r in runs:
        chave = round(r["size"], 1)
        max_por_tamanho[chave] = max(max_por_tamanho.get(chave, 0.0),
                                     r.get("last_w", 0.0))
    merged: list[dict] = []
    for r in runs:
        max_w = max_por_tamanho.get(round(r["size"], 1), 0.0)
        if merged and _continua_paragrafo(merged[-1], r, max_w):
            alvo = merged[-1]
            alvo["lines"].extend(r["lines"])
            alvo["last_w"] = r.get("last_w", alvo.get("last_w", 0.0))
            alvo["bbox"] = [
                min(alvo["bbox"][0], r["bbox"][0]),
                alvo["bbox"][1],
                max(alvo["bbox"][2], r["bbox"][2]),
                max(alvo["bbox"][3], r["bbox"][3]),
            ]
        else:
            merged.append(dict(r))
    return merged


def extract_blocks(pdf_path: Path | str) -> list[dict]:
    """Retorna blocos: [{page, text, size, bold, bbox}].

    Linhas consecutivas de mesmo tamanho/fonte que continuam a mesma frase sao
    unidas em um paragrafo (antes, cada linha virava um paragrafo e as frases
    chegavam cortadas no meio).
    """
    doc = fitz.open(str(pdf_path))
    blocks: list[dict] = []
    try:
        for pno, page in enumerate(doc):
            d = page.get_text("dict")
            runs: list[dict] = []
            for b in d.get("blocks", []):
                if b.get("type", 0) != 0:
                    continue
                # um bloco pode misturar titulo + corpo: agrupa por tamanho
                for line in b.get("lines", []):
                    texts: list[str] = []
                    sizes: list[float] = []
                    bold = False
                    for span in line.get("spans", []):
                        t = span.get("text", "")
                        if not t.strip():
                            continue
                        texts.append(t)
                        sizes.append(float(span.get("size", 12)))
                        if int(span.get("flags", 0)) & 16:  # bold
                            bold = True
                    if not texts:
                        continue
                    text = " ".join(texts).strip()
                    if not text:
                        continue
                    size = max(sizes) if sizes else 12.0
                    bbox = list(line.get("bbox", [0, 0, 0, 0]))
                    if (runs and abs(runs[-1]["size"] - size) <= 0.5
                            and runs[-1]["bold"] == bold):
                        runs[-1]["lines"].append(text)
                    else:
                        runs.append({"lines": [text], "size": size,
                                     "bold": bold, "bbox": bbox})
                    runs[-1]["last_w"] = _largura(bbox)
            # ordem de leitura (topo -> base) antes de juntar paragrafos
            runs.sort(key=lambda r: (float(r["bbox"][1]), float(r["bbox"][0])))
            for run in _merge_runs(runs):
                texto = _join_lines(run["lines"])
                if not texto:
                    continue
                blocks.append({
                    "page": pno,
                    "text": texto,
                    "size": run["size"],
                    "bold": run["bold"],
                    "bbox": run["bbox"],
                })
    finally:
        doc.close()
    return blocks


def detect_repeated_lines(blocks: list[dict], min_ratio: float = 0.3) -> set[str]:
    """Detecta linhas repetidas em muitas paginas (header/footer)."""
    from collections import Counter, defaultdict

    pages = defaultdict(set)
    for b in blocks:
        pages[b["page"]].add(b["text"].strip().lower())
    total_pages = len(pages) or 1
    counts: Counter = Counter()
    for _pno, lines in pages.items():
        for line in lines:
            counts[line] += 1
    repeated = {line for line, c in counts.items()
                if c / total_pages >= min_ratio and c >= 3}
    return repeated


def is_page_number(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 80:
        return False
    return bool(PAGE_NUM_RE.match(t))


def clean_blocks(blocks: list[dict], remove_header: bool = True,
                 remove_page_numbers: bool = True) -> list[dict]:
    """Remove header/footer repetidos, numeracao e linhas de rodape.

    As duas limpezas sao opcionais e refletem os toggles do frontend
    (antes, os parametros eram recebidos pela API e ignorados).
    """
    repeated = detect_repeated_lines(blocks) if remove_header else set()
    cleaned: list[dict] = []
    for b in blocks:
        t = b["text"].strip()
        if not t:
            continue
        low = t.lower()
        if remove_header and low in repeated:
            continue
        if remove_page_numbers and is_page_number(t):
            continue
        if JUNK_RE.match(t) and len(t) < 120:
            continue
        cleaned.append(b)
    return cleaned


def is_heading(text: str, size: float, h1_thresh: float, h2_thresh: float,
               bold: bool) -> int:
    """Retorna 1 (H1), 2 (H2) ou 0 (corpo)."""
    t = text.strip()
    if not t or len(t) > 200:
        return 0
    if size >= h1_thresh:
        return 1
    if size >= h2_thresh:
        return 2
    # Heuristica textual para capitulos mesmo sem destaque de fonte
    if CHAPTER_RE.match(t):
        return 1
    if bold and len(t) < 100 and t.istitle():
        return 2
    return 0


def parse_pdf_to_chapters(pdf_path: Path | str, remove_header: bool = True,
                          remove_page_numbers: bool = True) -> list[dict]:
    """Pipeline completo: blocos -> limpeza -> capitulos.

    Retorna: [{title, level, paragraphs[]}]
    """
    blocks = extract_blocks(pdf_path)
    if not blocks:
        return [{"title": "Texto", "level": 1,
                 "paragraphs": ["(PDF sem texto extraivel.)"]}]
    sizes = [b["size"] for b in blocks]
    h1_thresh = max(_percentile(sizes, 95), _percentile(sizes, 50) + 2.0)
    h2_thresh = max(_percentile(sizes, 80), _percentile(sizes, 50) + 0.5)

    cleaned = clean_blocks(blocks, remove_header=remove_header,
                           remove_page_numbers=remove_page_numbers)

    chapters: list[dict] = []
    current = {"title": "Início", "level": 1, "paragraphs": []}

    for b in cleaned:
        lvl = is_heading(b["text"], b["size"], h1_thresh, h2_thresh, b["bold"])
        if lvl in (1, 2) and b["text"].strip():
            if current["paragraphs"] or current["title"] != "Início":
                chapters.append(current)
            current = {"title": b["text"].strip(), "level": lvl,
                       "paragraphs": []}
        else:
            current["paragraphs"].append(b["text"].strip())

    if current["paragraphs"] or not chapters:
        chapters.append(current)
    # Se o primeiro capitulo "Início" ficou vazio e ha outros, descarta
    if (len(chapters) > 1 and chapters[0]["title"] == "Início"
            and not chapters[0]["paragraphs"]):
        chapters = chapters[1:]
    # Garante paragrafos nao vazios
    for ch in chapters:
        ch["paragraphs"] = [p for p in ch["paragraphs"] if p]
        if not ch["paragraphs"]:
            ch["paragraphs"] = ["(sem conteúdo)"]
    return chapters
