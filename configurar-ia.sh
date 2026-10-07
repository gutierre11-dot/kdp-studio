#!/usr/bin/env bash
# KDP Studio — configuração interativa da chave de IA.
#
# A chave é lida com entrada oculta (não aparece na tela nem no histórico do
# shell), validada com uma chamada real à API e só então gravada em `.env` com
# permissão 600. Se a validação falhar, nada é gravado.
#
#   ./configurar-ia.sh
set -euo pipefail

cd "$(dirname "$0")"

ENV_FILE=".env"
PY=python3
VERDE=$'\033[0;32m'; VERMELHO=$'\033[0;31m'; AMARELO=$'\033[1;33m'; NC=$'\033[0m'

DEEPSEEK_BASE_PADRAO="https://api.deepseek.com"
DEEPSEEK_MODELO_PADRAO="deepseek-flash"

echo
echo "  KDP Studio — configuração da chave de IA"
echo "  ───────────────────────────────────────"
echo

# ---------------------------------------------------------------- estado atual
if [ -f "$ENV_FILE" ]; then
  echo "  Situação atual do $ENV_FILE:"
  for var in DEEPSEEK_API_KEY OPENAI_API_KEY GEMINI_API_KEY; do
    if grep -qE "^${var}=.+" "$ENV_FILE" 2>/dev/null; then
      echo "    • ${var}: definida"
    fi
  done
  echo
fi

# ------------------------------------------------------------------- provider
echo "  Qual provider você quer usar?"
echo "    1) DeepSeek           (recomendado)"
echo "    2) OpenAI ou compatível (OpenRouter, DeepSeek via proxy, ...)"
echo "    3) Gemini"
echo
read -rp "  Escolha [1]: " opcao
opcao="${opcao:-1}"

case "$opcao" in
  1)
    provider="deepseek"
    var_chave="DEEPSEEK_API_KEY"
    var_base="DEEPSEEK_BASE_URL"
    var_modelo="DEEPSEEK_MODEL"
    base_padrao="$DEEPSEEK_BASE_PADRAO"
    modelo_padrao="$DEEPSEEK_MODELO_PADRAO"
    ;;
  2)
    provider="openai"
    var_chave="OPENAI_API_KEY"
    var_base="OPENAI_BASE_URL"
    var_modelo="TRANSLATION_MODEL"
    base_padrao=""
    modelo_padrao=""
    ;;
  3)
    provider="gemini"
    var_chave="GEMINI_API_KEY"
    var_base="GEMINI_BASE_URL"
    var_modelo="GEMINI_MODEL"
    base_padrao=""
    modelo_padrao="gemini-flash-latest"
    ;;
  *)
    echo "  Opção inválida." >&2
    exit 1
    ;;
esac

# ------------------------------------------------------------------------ base
if [ -n "$base_padrao" ]; then
  read -rp "  Endereço da API [$base_padrao]: " base_url
  base_url="${base_url:-$base_padrao}"
elif [ "$provider" = "openai" ]; then
  read -rp "  Endereço da API (vazio = api.openai.com): " base_url
else
  base_url=""
fi

# ---------------------------------------------------------------------- modelo
if [ -n "$modelo_padrao" ]; then
  read -rp "  Modelo [$modelo_padrao]: " modelo
  modelo="${modelo:-$modelo_padrao}"
else
  read -rp "  Modelo (ex.: gpt-4o-mini): " modelo
fi

if [ "$provider" != "gemini" ] && [ -z "$modelo" ]; then
  echo "  ${VERMELHO}O modelo é obrigatório para este provider.${NC}" >&2
  exit 1
fi

# ------------------------------------------------------------------- chave
echo
echo "  Cole a chave da API e pressione Enter."
echo "  ${AMARELO}(a digitação fica oculta — nada aparece na tela)${NC}"
read -rsp "  Chave: " chave
echo
echo

if [ -z "$chave" ]; then
  echo "  ${VERMELHO}Nenhuma chave informada. Nada foi gravado.${NC}" >&2
  exit 1
fi

# --------------------------------------------------------------- validação real
echo "  Validando a chave com uma chamada real (pode levar alguns segundos)…"

if KDP_PROVIDER="$provider" KDP_BASE="$base_url" KDP_MODELO="$modelo" \
   KDP_CHAVE="$chave" "$PY" - <<'PY'
import os
import sys

from openai import OpenAI

try:
    cliente = OpenAI(
        api_key=os.environ["KDP_CHAVE"],
        base_url=os.environ["KDP_BASE"] or None,
        timeout=30,
        max_retries=0,
    )
    extras = {}
    if os.environ["KDP_PROVIDER"] == "deepseek":
        extras = {"extra_body": {"thinking": {"type": "disabled"}}}
    resposta = cliente.chat.completions.create(
        model=os.environ["KDP_MODELO"],
        messages=[{"role": "user", "content": "Responda apenas: OK"}],
        temperature=0,
        **extras,
    )
    texto = (resposta.choices[0].message.content or "").strip()
    print(f"  modelo respondeu: {texto[:40]!r}")
except Exception as exc:  # noqa: BLE001 - queremos o motivo bruto aqui
    print(f"  ERRO: {str(exc)[:400]}", file=sys.stderr)
    sys.exit(1)
PY
then
  echo "  ${VERDE}Chave válida.${NC}"
else
  echo
  echo "  ${VERMELHO}A validação falhou — nada foi gravado.${NC}" >&2
  echo "  Confira a chave, o endereço e o modelo e rode o script de novo." >&2
  exit 1
fi

# ------------------------------------------------------------------- gravação
KDP_ENV_FILE="$ENV_FILE" KDP_CHAVE="$chave" KDP_VAR="$var_chave" \
KDP_BASE="$base_url" KDP_VAR_BASE="$var_base" \
KDP_MODELO="$modelo" KDP_VAR_MODELO="$var_modelo" \
KDP_PROVIDER="$provider" "$PY" - <<'PY'
import os

from backend.app.env_file import set_var

arquivo = os.environ["KDP_ENV_FILE"]
set_var(arquivo, os.environ["KDP_VAR"], os.environ["KDP_CHAVE"])
set_var(arquivo, os.environ["KDP_VAR_BASE"], os.environ["KDP_BASE"])
set_var(arquivo, os.environ["KDP_VAR_MODELO"], os.environ["KDP_MODELO"])
# LLM_PROVIDER evita ambiguidade quando há mais de uma chave no .env
set_var(arquivo, "LLM_PROVIDER", os.environ["KDP_PROVIDER"])
PY

echo "  ${VERDE}Configuração gravada em $ENV_FILE (permissão 600).${NC}"
echo
echo "  Provider: $provider"
[ -n "$base_url" ] && echo "  Endereço: $base_url"
echo "  Modelo:   $modelo"
echo
echo "  Agora suba o servidor:  ./run.sh"
echo
