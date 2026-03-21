# Implementation Assumptions

This first build follows the TDD closely, with explicit assumptions where the document leaves behavior open.

## Assumptions Implemented

1. The Obsidian vault lives inside this project by default at `obsidian_vault/`.
2. The preferences file supports:
   - `## Categories` with bullet items such as `- cs.AI`
   - `## Priorities` with numbered items such as `1. Agents`
   - Backward compatibility with a plain numbered list if categories are omitted
3. If categories are not declared in the preferences file, the script falls back to `astro-ph.CO`.
4. Ranking matches free-text preferences against paper title, abstract, authors, and arXiv categories using normalized keyword overlap instead of exact-phrase matching only.
5. Institution-level matching is not implemented beyond raw text matching because standard arXiv metadata does not reliably expose affiliations.
6. Daily notes are created automatically if missing, and reruns replace the same `## Today's Top Paper` section instead of duplicating it.
7. Weekly notes use the canonical structure from the TDD template and must retain `## Synthesis` and `## Daily Additions`.
8. Sunday rotation happens at most once per calendar Sunday. If that day's archive already exists, rotation is skipped on rerun to avoid re-archiving the fresh weekly note.
9. If the configured LLM CLI is unavailable or fails, the app keeps the pipeline functional by:
   - creating a local fallback paper note in `Papers/`
   - deriving a deterministic micro-summary from the abstract
   - deriving a deterministic weekly synthesis under 100 words
10. The first stable default leaves the external LLM path disabled so scheduled runs do not block on CLI behavior that still needs environment-specific tuning.
11. When the Claude path is enabled, the per-paper summarise step is expected to take roughly 4-8 minutes, so the configured timeout remains long even though the default mode is local-only.
12. The app prefers the last 24 hours of papers, but for lower-volume categories it can top up from the last 7 days so the workflow still produces useful output.
13. The configurable LLM command model is a command-prefix list where the generated prompt is appended as the last argument. This is exact for `claude -p` and intended as the extension point for other CLIs.

## Questions To Confirm Later

1. Do you want preference matching to stay free-text, or should we support typed rules such as `author:`, `category:`, and `keyword:`?
2. What exact CLI invocation should we support for non-Claude providers such as Codex CLI, Gemini CLI, or Copilot CLI?
3. Should Sunday's papers belong to the archived week or the new week? The current build follows the TDD literally and puts them into the fresh weekly note after rotation.
4. Do you want paper note filenames based on the generated note title, the raw arXiv title, or a stable arXiv ID convention?
