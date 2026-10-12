#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/benchmark-forge-cache/uv}"
export npm_config_cache="${npm_config_cache:-/tmp/benchmark-forge-cache/npm}"
command -v uv >/dev/null || { echo 'uvをインストールしてください。READMEを参照。' >&2; exit 1; }
command -v npm >/dev/null || { echo 'Node.js 22/24をインストールしてください。' >&2; exit 1; }
uv sync --locked
npm --prefix apps/web ci --no-audit --no-fund
npm --prefix apps/web run build
