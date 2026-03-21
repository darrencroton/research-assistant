# research-assistant

`research-assistant` is a local arXiv-to-Obsidian workflow.

The Python package and CLI are still named `re-ass`.

## Current Scope

- reads ranked interests from `obsidian_vault/re-ass-preferences.md`
- fetches and ranks matching arXiv papers
- updates daily and weekly Obsidian notes
- supports historical backfill with `--date`
- suppresses repeated paper selection when widened lookbacks resurface already-written notes
- uses an upstream-derived paper summariser in `src/re_ass/paper_summariser/`
- fetches arXiv PDFs locally, then either:
  - sends raw PDFs to providers that support direct PDF input
  - or extracts text with `marker-pdf` before prompting the selected provider
- defaults to deterministic local fallbacks when LLM generation is disabled or unavailable

## Quick Start

```bash
uv sync --group dev
uv run pytest
uv run re-ass
```

Backfill a specific day:

```bash
uv run re-ass --date 2026-03-21
```

## Configuration

- Main config: `re_ass.toml`
- Preferences: `obsidian_vault/re-ass-preferences.md`
- Main runtime switch: `[llm]`
- Supported CLI providers: `claude`, `codex`, `gemini`, `copilot`
- Supported API providers: `claude`, `openai`, `gemini`, `perplexity`, `ollama`
- `llm.enabled = false` by default

## Validation Artifacts

- Latest validation report: `docs/validation-report-2026-03-22.md`
- Single-day live run: `archive/validation-2026-03-22/`
- Multi-day live replay: `archive/simulation-2026-03-19-to-2026-03-21/`
