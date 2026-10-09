"""Testes da capa procedural (JPEG 1600x2560 via PyMuPDF)."""
from pathlib import Path

import pymupdf

from backend.app.cover import build_cover


def test_build_cover_gera_jpeg_1600x2560(tmp_path):
    out = build_cover("O Único e Sua Propriedade", "Max Stirner",
                      tmp_path / "capa.jpg")
    assert Path(out).is_file()
    pix = pymupdf.Pixmap(str(out))
    assert (pix.width, pix.height) == (1600, 2560)
    assert pix.n in (3, 4)


def test_build_cover_com_emoji_e_aspas_nao_lanca(tmp_path):
    out = build_cover('Título 📚🎉 "aspas" & <tags>', "Autor & Cia",
                      tmp_path / "c.jpg")
    assert Path(out).is_file()
    pix = pymupdf.Pixmap(str(out))
    assert (pix.width, pix.height) == (1600, 2560)


def test_build_cover_aceita_subtitulo(tmp_path):
    out = build_cover("Título", "Autor", tmp_path / "c.jpg",
                      subtitle="Um subtítulo qualquer")
    assert Path(out).is_file()


def test_build_cover_titulo_so_emoji_nao_lanca(tmp_path):
    out = build_cover("📚🎉🚀", "🎨", tmp_path / "c.jpg")
    assert Path(out).is_file()
    pix = pymupdf.Pixmap(str(out))
    assert (pix.width, pix.height) == (1600, 2560)
