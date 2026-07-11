#!/usr/bin/env bash
# Production entrypoint: reads APP_PORT from env or .env, runs uvicorn without reload.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Prefer env injected by systemd (EnvironmentFile). Manual runs read APP_PORT only —
# do NOT `source .env` (CRLF and special chars in passwords break bash).
if [[ -z "${APP_PORT:-}" && -f .env ]]; then
  APP_PORT="$(grep -E '^APP_PORT=' .env | head -1 | cut -d= -f2- | tr -d '\r\n' | xargs)"
fi

PORT="${APP_PORT:-8005}"
UVICORN="${ROOT}/.venv/bin/uvicorn"

if [[ ! -x "${UVICORN}" ]]; then
  echo "ERROR: uvicorn not found at ${UVICORN}" >&2
  echo "Run: cd ${ROOT} && uv sync" >&2
  exit 127
fi

exec "${UVICORN}" backend.app:app --host 0.0.0.0 --port "${PORT}"
