#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  printf 'uv is required but was not found on PATH.\n' >&2
  exit 1
fi

cd "$repo_root"

uv sync --group dev

uv run python -m re_ass.setup
