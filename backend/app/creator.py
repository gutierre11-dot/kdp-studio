"""Criacao de livros: plan (outline) + write (capitulos). Usa LLM se houver chave."""
import logging
import re
import unicodedata

from .llm import (
    effective_creation_model,
    llm_available,
    make_client,
    resolve_chat_model,
)

GENEROS = ["romance", "fantasia", "ficcao", "suspense", "autoajuda", "infantil", "poesia", "biografia"]

TEMPLATE_ARCS = [
    "A jornada começa com um incidente que muda tudo.",
    "O protagonista enfrenta um dilema moral profundo.",
    "Uma revelação inesperada vira a história de cabeça para baixo.",
    "O conflito atinge o auge e exige sacrifício.",
    "A resolução traz aprendizado e um novo começo.",
]

# Pool amplo (12+) para o fallback offline nunca repetir título em livros de 12 caps.
FALLBACK_TITLE_POOL = [
    "O Começo", "A Virada", "O Segredo", "A Travessia", "O Reencontro",
    "A Decisão", "A Queda", "O Despertar", "A Profecia", "O Julgamento",
    "A Revelação", "O Retorno", "A Sentença", "O Véu", "A Chama",
    "O Silêncio", "A Herança", "O Pacto",
]

log = logging.getLogger(__name__)


def sanitize_ideia(ideia: str, limite: int = 200) -> str:
    """Sinopse curta e segura: nunca interpola prompt cru (ex. '# PROJETO...').

    Remove linhas de cabeçalho markdown, diretivas e colapsa espaços.
    """
    txt = (ideia or "").strip()
    linhas = []
    for ln in txt.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#") or s.upper().startswith("PROJETO"):
            continue
        if re.match(r"^(IDEIA|PROMPT|SYSTEM|CONTEXTO)\s*:", s, re.I):
            continue
        linhas.append(s)
    txt = " ".join(linhas) or "Uma história de transformação e coragem."
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:limite]


def _llm_available() -> bool:
    # Compat: True se OpenAI ou Gemini configurado; senao offline.
    return llm_available()


def _llm_chat(system: str, user: str, model: str, temperature: float = 0.8) -> str:
    client = make_client()
    model = resolve_chat_model(model, kind="creation")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()


def _titulo_do_fallback(ideia: str) -> str:
    """Titulo derivado da ideia SANITIZADA (nunca do prompt cru).

    Antes o fallback usava `ideia[:60]`, podendo vazar cabecalhos markdown e
    diretivas de prompt como titulo do livro.
    """
    base = sanitize_ideia(ideia)
    base = base.split(".")[0].strip() or "Nova história"
    return unicodedata.normalize("NFC", base.strip().capitalize()[:70])


def plan_book(ideia: str, genero: str = "romance", estilo: str = "envolvente",
              publico: str = "adultos", capitulos: int = 10) -> dict:
    capitulos = max(1, min(int(capitulos or 10), 40))
    model = effective_creation_model()
    if _llm_available():
        try:
            txt = _llm_chat(
                "Voce e um editor e ghostwriter premiado. Responda em portugues.",
                f"Crie titulo + outline de {capitulos} capitulos para livro.\n"
                f"Ideia: {ideia}\nGenero: {genero}\nEstilo: {estilo}\nPublico: {publico}\n"
                "Formato:\nTITULO: <titulo>\n1. <titulo cap> - <resumo 1-2 frases>\n2. ...",
                model,
                temperature=0.8,
            )
            titulo = _titulo_do_fallback(ideia)
            outline = []
            for line in txt.splitlines():
                line = line.strip(" -*\t")
                if not line:
                    continue
                if line.upper().startswith("TITULO"):
                    titulo = line.split(":", 1)[-1].strip() or titulo
                    continue
                # remove numeracao "1. "
                m = re.match(r"^(\d+)[\.\)\-:]\s*(.+)$", line)
                if m:
                    body = m.group(2)
                    if " - " in body:
                        t, r = body.split(" - ", 1)
                    elif ":" in body:
                        t, r = body.split(":", 1)
                    else:
                        t, r = body, ""
                    outline.append({"titulo": t.strip(), "resumo": r.strip()})
            while len(outline) < capitulos:
                outline.append({
                    "titulo": f"Capítulo {len(outline)+1}",
                    "resumo": "Desenvolvimento da trama com tensão crescente.",
                })
            # Validação de unicidade: sufixa II, III... se o LLM repetir títulos.
            vistos: dict[str, int] = {}
            for item in outline:
                base = (item.get("titulo") or "").strip() or "Capítulo"
                n = vistos.get(base, 0) + 1
                vistos[base] = n
                if n > 1:
                    sufixo = {2: " II", 3: " III", 4: " IV", 5: " V"}.get(n, f" ({n})")
                    item["titulo"] = f"{base}{sufixo}"
            return {"titulo": titulo, "outline": outline[:capitulos]}
        except Exception as exc:
            log.warning("plan_book: LLM falhou, usando fallback offline: %s", exc)
            print(f"[creator] plan_book LLM falhou: {exc} — fallback offline")
    # Fallback offline rico (UTF-8 correto, títulos únicos, sem vazar prompt cru)
    sinopse = sanitize_ideia(ideia)
    titulo = _titulo_do_fallback(ideia)
    outline = []
    for i in range(capitulos):
        arc = TEMPLATE_ARCS[i % len(TEMPLATE_ARCS)]
        nome = FALLBACK_TITLE_POOL[i % len(FALLBACK_TITLE_POOL)]
        outline.append({
            "titulo": f"Capítulo {i+1}: {nome}",
            "resumo": f"{arc} Contexto: {sinopse}. Tom {estilo}, público {publico}, gênero {genero}.",
        })
    return {"titulo": titulo, "outline": outline}


def write_chapters(outline: list, titulo: str = "Livro", estilo: str = "envolvente",
                   numero_capitulo_inicial: int = 1) -> list:
    """Escreve capítulos via LLM; em falha parcial marca o capítulo com mock:true.

    numero_capitulo_inicial: número real do primeiro item (o fluxo single-chapter
    do /api/ebook/chapter envia 1 item que pode ser o cap N, não o 1).
    Também respeita item.get("numero") quando presente.
    """
    model = effective_creation_model()
    chapters = []
    for i, item in enumerate(outline):
        numero = item.get("numero") if isinstance(item, dict) else None
        try:
            numero = int(numero) if numero is not None else numero_capitulo_inicial + i
        except (TypeError, ValueError):
            numero = numero_capitulo_inicial + i
        cap_titulo = item.get("titulo", f"Capítulo {numero}") if isinstance(item, dict) else f"Capítulo {numero}"
        resumo = item.get("resumo", "") if isinstance(item, dict) else ""
        if _llm_available():
            try:
                txt = _llm_chat(
                    "Você é um escritor best-seller. Escreva em português brasileiro com acentuação correta.",
                    f"Livro: {titulo}\nEstilo: {estilo}\nCapítulo {numero}: {cap_titulo}\nResumo: {resumo}\n"
                    "Escreva o capítulo completo com 4-8 parágrafos, diálogos e cliffhanger. "
                    "Separe parágrafos com linha em branco.",
                    model,
                )
                paras = [p.strip() for p in txt.split("\n\n") if p.strip()]
                chapters.append({"title": cap_titulo, "level": 1, "paragraphs": paras,
                                 "numero": numero})
                continue
            except Exception as exc:
                log.warning("write_chapters cap %s: LLM falhou, fallback mock: %s", numero, exc)
                print(f"[creator] write_chapters cap {numero} LLM falhou: {exc} — fallback mock:true")
                paras = _fallback_paragraphs(cap_titulo, resumo, titulo, estilo, numero)
                chapters.append({"title": cap_titulo, "level": 1,
                                 "paragraphs": paras, "mock": True,
                                 "numero": numero})
                continue
        # Template offline rico e interativo (UTF-8 correto)
        paras = _fallback_paragraphs(cap_titulo, resumo, titulo, estilo, numero)
        chapters.append({"title": cap_titulo, "level": 1, "paragraphs": paras,
                         "mock": True, "numero": numero})
    return chapters


def _fallback_paragraphs(cap_titulo: str, resumo: str, titulo: str,
                         estilo: str, numero: int) -> list:
    """Fallback offline com acentuação UTF-8 correta (nunca ASCII sem acento)."""
    return [
        f"{cap_titulo} abre com o peso do que veio antes. {resumo}",
        f"O ar parecia carregar {estilo} em cada detalhe: sons, cheiros e memórias se misturavam enquanto a história de \"{titulo}\" avançava.",
        "— Você tem certeza disso? — perguntou a voz ao fundo, rompendo o silêncio.",
        "— Nunca tive. Mas é exatamente por isso que preciso continuar — foi a resposta, firme, quase um sussurro.",
        f"A cada passo, o capítulo {numero} revela uma camada nova: escolhas, consequências e aquele frio na barriga que só uma boa história provoca.",
        f"E quando tudo parecia resolvido, um último acontecimento muda o rumo: nada será como antes em \"{titulo}\".",
    ]
