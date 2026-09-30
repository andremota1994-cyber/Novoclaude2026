#!/bin/sh
# Roda o painel localmente em http://localhost:5050
cd "$(dirname "$0")"
set -a; [ -f .env.local ] && . ./.env.local; set +a
export PORT=5050 FLASK_DEBUG=1
exec .venv/bin/python main.py
