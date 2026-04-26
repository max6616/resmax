#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

if [[ -f "$ROOT_DIR/.secrets/deepseek.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.secrets/deepseek.env"
  set +a
fi

exec python3 "$ROOT_DIR/scripts/mcp/resmax_multimodel/server.py"
