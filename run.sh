#!/usr/bin/env bash
# KDP Studio — setup + run. Pode ser executado de qualquer diretorio: o script
# se move para a propria pasta antes de ler .env/requirements (antes ele rodava
# `pip install -r requirements.txt` no diretorio do chamador e falhava).
set -euo pipefail

cd "$(dirname "$0")"

# Carrega .env para o processo do servidor (o app tambem carrega sozinho).
if [ -f .env ]; then
  set -a; . ./.env; set +a
fi
if [ -f backend/.env ]; then
  set -a; . ./backend/.env; set +a
fi

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
RELOAD="${RELOAD:-1}"

# Checagem de porta: aborta se ja estiver em uso.
if python3 - "$PORT" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket()
s.settimeout(1)
sys.exit(0 if s.connect_ex(("127.0.0.1", port)) == 0 else 1)
PY
then
  echo "Erro: porta $PORT já está em uso. Encerre o processo atual antes de iniciar novamente." >&2
  exit 1
fi

# Instala dependencias somente se faltar alguma (antes rodava pip em todo start).
if ! python3 -c "import fastapi, uvicorn, pymupdf, ebooklib, openai, httpx, dotenv" 2>/dev/null; then
  echo "Instalando dependências..."
  python3 -m pip install -r requirements.txt
fi

echo "KDP Studio rodando em:"
echo "  App:    http://127.0.0.1:$PORT"
echo "  Health: http://127.0.0.1:$PORT/api/health"

if [ "$RELOAD" = "1" ]; then
  exec python3 -m uvicorn backend.app.main:app --host "$HOST" --port "$PORT" --reload
fi
exec python3 -m uvicorn backend.app.main:app --host "$HOST" --port "$PORT"
