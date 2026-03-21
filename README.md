# re-ass

`re-ass` is a local Python automation that pulls recent arXiv papers, ranks them against user preferences, generates paper notes, and updates an Obsidian vault's daily and weekly notes.

## What This Build Does

- Reads ranked priorities from `obsidian_vault/re-ass-preferences.md`
- Fetches recent arXiv papers from configured categories
- Keeps only the top 3 ranked matches
- Generates deterministic local paper notes and short summaries by default
- Supports delegation to a configurable CLI LLM command once the exact non-interactive invocation is confirmed
- Updates today's daily note and the rolling weekly note
- Rotates the weekly note into `Weekly_Archive/` on Sundays

## Quick Start

1. Install dependencies:

```bash
uv sync --group dev
```

2. Review defaults in `re_ass.toml`.

3. Update `obsidian_vault/re-ass-preferences.md` with your categories and priorities.

4. Run the script:

```bash
uv run re-ass
```

You can also backfill or test a specific date:

```bash
uv run re-ass --date 2026-03-21
```

## Configuration Notes

- The default vault root is `obsidian_vault/` inside this project.
- The default LLM command prefix is `["claude", "-p"]`.
- The default arXiv fetch depth is 200 recent papers across the configured categories before ranking.
- The current default category is `astro-ph.CO` (Cosmology and Nongalactic Astrophysics).
- The app prefers papers from the last 24 hours, but it can top up from the last 7 days when a niche category would otherwise return nothing.
- The current default is `llm.enabled = false` so unattended runs stay deterministic and non-blocking while the CLI integration is being finalized.
- If you enable the Claude path later, expect roughly 4-8 minutes per paper for the summarise skill, so a 3-paper run can take 15-30 minutes.
- The current paper-note prompt calls `/summarise-paper` explicitly and passes both the arXiv URL and the target papers directory.
- If you switch to another CLI, keep the command prefix compatible with the implementation model: the prompt is appended as the final argument.

## Testing

```bash
uv run pytest
```
