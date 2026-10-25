#!/usr/bin/env bash
# Run the platform without Docker: every built service in one process with an in-memory
# bus in place of RabbitMQ (see scripts/dev_stack.py). Then, in web/, `npm run dev`
# serves the editor on :5173 (it proxies /api to the gateway on :8000).
set -euo pipefail
cd "$(dirname "$0")/.."
# Import packages and services from source: macOS can hide the venv's .pth files,
# which Python 3.13 then skips.
PYTHONPATH="$PWD/packages/pathway-core/src:$PWD/packages/care-events/src"
for svc in services/*/; do PYTHONPATH="$PYTHONPATH:$PWD/${svc%/}"; done
export PYTHONPATH
exec .venv/bin/python scripts/dev_stack.py
