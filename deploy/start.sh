#!/usr/bin/env bash
# Production entrypoint: reads APP_PORT from .env, runs uvicorn without reload.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PORT="${APP_PORT:-8005}"
UVICORN="${ROOT}/.venv/bin/uvicorn"

if [[ ! -x "${UVICORN}" ]]; then
  echo "ERROR: uvicorn not found at ${UVICORN}" >&2
  echo "Run: cd ${ROOT} && uv sync" >&2
  exit 127
fi

exec "${UVICORN}" backend.app:app --host 0.0.0.0 --port "${PORT}"
