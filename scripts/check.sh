#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/benchmark-forge-cache/uv}"
uv run --no-sync ruff check src tests scripts
uv run --no-sync ruff format --check src tests scripts
uv run --no-sync mypy src
uv run --no-sync pytest -q
uv run --no-sync python scripts/secret_scan.py
npm --prefix apps/web run test
npm --prefix apps/web run build
