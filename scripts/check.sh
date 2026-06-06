#!/usr/bin/env bash
set -euo pipefail

uv run --extra dev pytest -q
rg -n "rezn-live|redoing" README.md CLEAN_ROOM.md PROVENANCE.md docs src tests apps services pyproject.toml && {
  echo "Forbidden clean-room boundary language found."
  exit 1
} || true
