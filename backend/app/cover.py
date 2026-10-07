"""Geracao de capa: OpenAI Images se houver chave OpenAI, senao Pillow gradiente premium.

Nota Gemini/Imagen: o endpoint OpenAI-compatible do Gemini
(https://generativelanguage.googleapis.com/v1beta/openai/) cobre apenas
modelos de linguagem (chat/completions). Geracao de imagem (Imagen) usa API
separada e NAO esta inclusa aqui. Por isso, mesmo com GEMINI_API_KEY
configurado, a capa usa o fallback Pillow local (sem custo, offline).
Apenas OPENAI_API_KEY (+ COVER_MODEL, ex. dall-e-3) tenta images.generate.
"""
import logging
import os
import textwrap
from pathlib import Path

from .llm import gemini_configured, openai_configured

log = logging.getLogger(__name__)

COVER_W, COVER_H = 1600, 2560


def _llm_available() -> bool:
    # Apenas OpenAI tem images.generate aqui. Gemini (GEMINI_API_KEY) nao
    # oferece endpoint compativel de imagem, entao retorna False nesse caso
    # para cair direto no Pillow. Mantido por compat com imports externos.
    return openai_configured()


def generate_cover(titulo: str, autor: str, estilo: str = "premium",
                   out_path: Path | None = None) -> Path:
    from PIL import Image

    if out_path is None:
        raise ValueError("out_path obrigatorio")

    # Tenta OpenAI Images
    if _llm_available():
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL") or None,
            )
            model = os.getenv("COVER_MODEL", "dall-e-3")
            prompt = (
                f"Capa de livro profissional estilo {estilo}, titulo '{titulo}', "
                f"autor '{autor}', composicao premium, alta qualidade, sem texto distorcido"
            )
            # images API pode variar; tenta o padrao openai>=1.0
            result = client.images.generate(model=model, prompt=prompt, size="1024x1792")
            import httpx

            url = result.data[0].url
            if url:
                r = httpx.get(url, timeout=60)
                r.raise_for_status()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(r.content)
                # redimensiona para 1600x2560
                img = Image.open(out_path).convert("RGB").resize((COVER_W, COVER_H))
                img.save(out_path, "JPEG", quality=92)
                return out_path
        except Exception as exc:
            # Antes era `except Exception: pass` (falha silenciosa).
            log.warning("geracao de capa via OpenAI falhou (%s) - "
                        "usando fallback Pillow", exc)

    return pillow_cover(titulo, autor, estilo, out_path)


def pillow_cover(titulo: str, autor: str, estilo: str, out_path: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Gradiente premium vertical (azul-noite -> vinho)
    top = (18, 24, 60)
    bottom = (110, 30, 60)
    img = Image.new("RGB", (COVER_W, COVER_H), top)
    draw = ImageDraw.Draw(img)
    for y in range(COVER_H):
        r = int(top[0] + (bottom[0] - top[0]) * y / COVER_H)
        g = int(top[1] + (bottom[1] - top[1]) * y / COVER_H)
        b = int(top[2] + (bottom[2] - top[2]) * y / COVER_H)
        draw.line([(0, y), (COVER_W, y)], fill=(r, g, b))
    # Moldura dourada
    margin = 80
    draw.rectangle([margin, margin, COVER_W - margin, COVER_H - margin],
                   outline=(212, 175, 55), width=6)
    draw.rectangle([margin + 24, margin + 24, COVER_W - margin - 24, COVER_H - margin - 24],
                   outline=(212, 175, 55), width=2)

    def font(size: int):
        for name in ("DejaVuSerif-Bold.ttf", "DejaVuSans-Bold.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    # Titulo centralizado com wrap
    wrapped = textwrap.fill(titulo.upper() or "SEM TITULO", width=16)
    f_title = font(130)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=f_title, align="center")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.multiline_text(((COVER_W - tw) / 2, COVER_H * 0.32), wrapped,
                        font=f_title, fill=(245, 240, 220), align="center")
    # Autor
    f_autor = font(72)
    abox = draw.textbbox((0, 0), autor, font=f_autor)
    aw = abox[2] - abox[0]
    draw.text(((COVER_W - aw) / 2, COVER_H * 0.68), autor, font=f_autor, fill=(212, 175, 55))
    # Estilo
    f_sub = font(48)
    sub = estilo.upper()
    sbox = draw.textbbox((0, 0), sub, font=f_sub)
    sw = sbox[2] - sbox[0]
    draw.text(((COVER_W - sw) / 2, COVER_H * 0.75), sub, font=f_sub, fill=(200, 200, 200))

    img.save(out_path, "JPEG", quality=92)
    return out_path
