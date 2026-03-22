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

mkdir -p \
  output/papers \
  output/daily \
  output/weekly \
  processed \
  state/papers \
  state/runs \
  logs \
  tmp/paper_summariser \
  tmp/launchd

uv run python - <<'PY'
from re_ass.generation_service import GenerationService
from re_ass.settings import load_config

config = load_config()
GenerationService(config=config.llm)
print(f"Validated LLM provider: {config.llm.mode}/{config.llm.provider}")
PY

printf 'Setup complete.\n'
