#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/benchmark-forge-cache/uv}"
if [[ ! -f apps/web/dist/index.html ]]; then
  echo 'UIビルドがありません。bash scripts/setup.sh を実行してください。' >&2
  exit 1
fi
exec uv run --no-sync forge serve --port "${FORGE_API_PORT:-8000}"
