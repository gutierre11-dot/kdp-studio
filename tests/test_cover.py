"""Testes da capa procedural (JPEG 1600x2560 via PyMuPDF)."""
from pathlib import Path

import pymupdf
import pytest

from backend.app.cover import build_cover, build_cover_bytes, detectar_capa


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


def test_build_cover_bytes_devolve_jpeg_sem_tocar_no_disco():
    dados = build_cover_bytes("Título", "Autora")
    assert dados[:3] == b"\xff\xd8\xff"
    pix = pymupdf.Pixmap(dados)
    assert (pix.width, pix.height) == (1600, 2560)


def test_detectar_capa_reconhece_png_e_jpeg(capa_png, capa_jpg):
    assert detectar_capa(capa_png) == "png"
    assert detectar_capa(capa_jpg) == "jpg"


def test_detectar_capa_recusa_o_que_nao_e_imagem():
    with pytest.raises(ValueError):
        detectar_capa(b"%PDF-1.4")
    with pytest.raises(ValueError):
        detectar_capa(b"")


def test_detectar_capa_ignora_a_extensao_e_olha_os_bytes():
    """Assinatura de JPEG com conteudo invalido nao pode passar como capa."""
    with pytest.raises(ValueError):
        detectar_capa(b"\xff\xd8\xff" + b"isto nao e um jpeg de verdade")


def test_detectar_capa_recusa_imagem_ilegivel(capa_png):
    """Cortar o PNG bem no inicio deixa a assinatura, mas nao ha imagem.

    A checagem e por magic bytes + decodificacao real: e o que separa uma
    imagem de um arquivo qualquer renomeado. Truncamento no meio do fluxo
    pode passar aqui (o cabecalho ja tem as dimensoes), e por isso a mensagem
    de erro fala de arquivo corrompido ou incompleto.
    """
    with pytest.raises(ValueError):
        detectar_capa(capa_png[:12])
