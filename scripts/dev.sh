#!/usr/bin/env bash
# Run the built services without Docker: gateway :8000, auth :8001, designer :8002,
# verifier :8003, patient :8004, each with uvicorn --reload and a SQLite file in .dev/. Then, in web/,
# `npm run dev` serves the editor on :5173 (it proxies /api to the gateway).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .dev
set -a; source .env.example; [ -f .env ] && source .env; set +a
PY="$PWD/.venv/bin"
# Import pathway-core from source: macOS can hide the venv's .pth files, which Python 3.13 then skips.
export PYTHONPATH="$PWD/packages/pathway-core/src"
export AUTH_URL=http://localhost:8001 DESIGNER_URL=http://localhost:8002 VERIFIER_URL=http://localhost:8003 \
  PATIENT_URL=http://localhost:8004

start() {  # name port [--factory]
  (cd "services/$1" && DATABASE_URL="sqlite:///$PWD/../../.dev/$1.db" \
    "$PY/uvicorn" "$1.main:${4:-app}" ${3:-} --port "$2" --reload --log-level warning) &
}
start auth 8001 --factory create_app
start designer 8002 --factory create_app
start verifier 8003
start patient 8004 --factory create_app
start gateway 8000 --factory create_app
trap 'kill 0' EXIT
echo "gateway http://localhost:8000  (Ctrl-C stops all)"
wait
