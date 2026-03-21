# Implementation Assumptions

This build now treats the upstream `science-paper-summariser` pipeline as the paper-note engine and adapts it at the `re-ass` orchestration boundary.

## Assumptions Implemented

1. The Obsidian vault lives inside this project by default at `obsidian_vault/`.
2. The preferences file supports:
   - `## Categories` with bullet items such as `- cs.AI`
   - `## Priorities` with numbered items such as `1. Agents`
   - backward compatibility with a plain numbered list if categories are omitted
3. If categories are not declared in the preferences file, the script falls back to `astro-ph.CO`.
4. Ranking matches free-text preferences against paper title, abstract, authors, and arXiv categories using normalized keyword overlap instead of exact-phrase matching only.
5. Institution-level matching is not implemented beyond raw text matching because standard arXiv metadata does not reliably expose affiliations.
6. Daily notes are created automatically if missing, and reruns replace the same `## Today's Top Paper` section instead of duplicating it.
7. Weekly notes use the canonical structure from the TDD template and must retain `## Synthesis` and `## Daily Additions`.
8. Sunday rotation happens at most once per calendar Sunday. If that day's archive already exists, rotation is skipped on rerun to avoid re-archiving the fresh weekly note.
9. `[llm]` configuration selects an explicit `mode` and `provider`; missing CLI binaries or missing API keys fail early during provider construction.
10. Paper-note generation follows the upstream architecture:
    - download the arXiv PDF locally
    - pass raw PDF bytes to providers that support direct PDF input
    - otherwise extract text with `marker-pdf`
    - build the upstream-style astronomy summary prompt
    - validate and repair summary metadata before writing the final note
11. `re-ass` keeps ownership of the Obsidian wrapper and writes notes to `Papers/<sanitized title>.md`.
12. If the configured provider path is disabled or fails, the app keeps the pipeline functional by:
    - creating a local fallback paper note in `Papers/`
    - deriving a deterministic micro-summary from the abstract
    - deriving a deterministic weekly synthesis under 100 words
13. The first stable default still leaves the LLM path disabled so scheduled runs do not depend on provider availability, authentication, or PDF extraction latency.
14. When widened lookbacks resurface papers that already have note files, those papers are skipped before the final top-N selection.
15. If no unseen matching papers remain after duplicate suppression, the run exits successfully without mutating the daily or weekly notes.

## Questions To Confirm Later

1. Which provider/model combinations should be treated as the preferred defaults for CLI mode and API mode?
2. Should paper note filenames stay title-based, or move to a safer format such as `{arxiv_id} - {title}`?
3. On days with no unseen matching papers, do you want the current no-op behavior, or an explicit note stating that nothing new matched?
4. Should simulations/backfills reuse cached arXiv responses instead of refetching the feed for each day?
