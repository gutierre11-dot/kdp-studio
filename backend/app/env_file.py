"""Atualização de variáveis num arquivo `.env` sem perder o resto do conteúdo.

Usado pelo `configurar-ia.sh`. Fica em Python (e não em `sed`) porque os valores
podem conter caracteres especiais e porque a permissão do arquivo precisa ser
garantida a cada gravação.
"""
from __future__ import annotations

import os
from pathlib import Path

MODO_PADRAO = 0o600


def set_var(path: str | Path, name: str, value: str,
            *, mode: int = MODO_PADRAO) -> bool:
    """Define `name=value` em `path`, preservando as demais linhas.

    Substitui a primeira ocorrência existente; se não houver, acrescenta ao
    final. Valores vazios são ignorados (devolve False) para não apagar uma
    configuração existente. Sempre reaplica a permissão do arquivo.
    """
    if not name or not value:
        return False
    caminho = Path(path)
    linhas = caminho.read_text(encoding="utf-8").splitlines() if caminho.exists() else []
    saida: list[str] = []
    substituido = False
    for linha in linhas:
        if linha.split("=", 1)[0].strip() == name:
            if not substituido:
                saida.append(f"{name}={value}")
                substituido = True
            # ocorrências duplicadas da mesma chave são descartadas
        else:
            saida.append(linha)
    if not substituido:
        saida.append(f"{name}={value}")
    caminho.write_text("\n".join(saida).rstrip("\n") + "\n", encoding="utf-8")
    os.chmod(caminho, mode)
    return True
