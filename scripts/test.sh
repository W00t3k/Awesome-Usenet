#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTEST_BIN="$ROOT_DIR/.venv/bin/pytest"

if [[ ! -x "$PYTEST_BIN" ]]; then
  echo "Missing .venv test environment." >&2
  echo "Run: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi

exec "$PYTEST_BIN" -q "$@"
