# Investigation: summariser integration and top-3 selection

Date: 2026-03-22

## Scope

This report investigates two questions:

1. Why a fresh install followed by `./scripts/setup.sh` and `uv run re-ass` produces metadata-only fallback notes instead of the vendored paper summariser output.
2. How the current top-3 paper selection works, and whether it matches the intended workflow of:
   - reading categories and priorities from `preferences.md`
   - fetching all papers across the relevant date range
   - ranking the full candidate set against user priorities
   - selecting the top 3
   - downloading, summarising, and recording only those 3

## Findings

### 1. Fresh installs do not use the paper summariser by default

Current default configuration disables all LLM-backed generation:

- `re_ass.toml` sets `llm.enabled = false`
- `load_config()` defaults `llm.enabled` to `False`
- `scripts/setup.sh` does not alter config or prompt for provider setup

Relevant locations:

- `re_ass.toml:40-49`
- `src/re_ass/settings.py:190-205`
- `scripts/setup.sh:12-27`

Effect:

- `GenerationService.__init__()` only creates an LLM provider when `config.enabled` is true.
- If disabled, `self.provider` remains `None`, so `self.paper_summariser` also remains `None`.
- `build_paper_note_content()` therefore skips the vendored summariser and falls back to `_build_fallback_note()`.

Relevant locations:

- `src/re_ass/generation_service.py:38-50`
- `src/re_ass/generation_service.py:76-88`
- `src/re_ass/generation_service.py:136-148`

Conclusion:

The fresh-install behaviour reported by the user is consistent with the current implementation. It is not an accidental regression in the execution path; it is the configured default.

### 2. Even when summarisation is enabled, `re-ass` does not preserve the upstream note format exactly

The vendored summariser itself is prompted with the upstream-style template in:

- `src/re_ass/paper_summariser/project_knowledge/paper-summary-template.md`
- `src/re_ass/paper_summariser/service.py:217-218`
- `src/re_ass/paper_summariser/service.py:396-444`

However, the final note written by `re-ass` is rebuilt by `GenerationService._build_note_content()`:

- it strips everything before the first `##` heading via `extract_summary_sections()`
- it discards the summariser's title / authors / published lines
- it injects app-side metadata bullets (`- ArXiv`, `- Published`, `- Authors`, `- Categories`)
- it injects a `## Abstract` block
- it appends only the extracted `## ...` sections from the summariser output

Relevant locations:

- `src/re_ass/generation_service.py:80-81`
- `src/re_ass/generation_service.py:122-134`
- `src/re_ass/paper_summariser/service.py:554-559`

Effect:

Even a successful summariser run cannot produce an output file that exactly matches the upstream template. The app always rewrites the top matter and adds an `## Abstract` section that is not part of the vendored template.

This is a real integration mismatch relative to the stated goal of taking summarisation "exactly" from `science-paper-summariser`.

### 3. No test verifies that enabled summariser output survives intact into final paper notes

Current tests cover:

- the summariser service producing a raw summary (`tests/test_paper_summariser_service.py:33-63`)
- direct-PDF provider wiring (`tests/test_paper_summariser_service.py:66-95`)
- `extract_summary_sections()` stripping preamble (`tests/test_paper_summariser_service.py:98-107`)
- the pipeline fallback path when LLM is disabled (`tests/test_pipeline.py:74-91`)
- a mocked "enabled LLM path" that stubs out `GenerationService` entirely (`tests/test_pipeline.py:94-122`)

What is missing:

- a test that enables the real `GenerationService`, injects a fake summariser result, runs the pipeline, and asserts the written note matches the intended template contract
- a test that fails if `GenerationService` rewrites enabled summariser output incorrectly

Conclusion:

The user is correct that the critical behaviour is not currently verified.

### 4. Top-3 selection is currently heuristic keyword ranking, not full-candidate evaluation against the full preferences context

The current flow is:

1. Parse categories and numbered priorities from `preferences.md`.
2. Build an arXiv query of `cat:X OR cat:Y ...`.
3. Request at most `arxiv.max_results` recent results, sorted by submitted date descending.
4. Convert them into `ArxivPaper` objects.
5. Filter them locally by `published` time within the primary window.
6. Rank them using token overlap / substring heuristics against each priority string.
7. Drop all papers with no heuristic match.
8. Select unseen papers in ranked order up to `max_papers`.
9. Only if fewer than `max_papers` are available in the primary window, retry using a wider fallback window.

Relevant locations:

- `src/re_ass/preferences.py:19-58`
- `src/re_ass/arxiv_fetcher.py:50-51`
- `src/re_ass/arxiv_fetcher.py:112-160`
- `src/re_ass/arxiv_fetcher.py:183-230`
- `src/re_ass/pipeline.py:101-117`

Details of the ranking heuristic:

- exact substring match on the full priority phrase gets score `10000`
- otherwise, both priority and paper text are tokenised and compared by overlap count
- a few hard-coded token expansions exist (`agn`, `llm`, `lrd`)
- ranking order is:
  - best priority rank in the numbered list
  - number of matched priorities
  - best match score
  - recency

Relevant locations:

- `src/re_ass/arxiv_fetcher.py:17-41`
- `src/re_ass/arxiv_fetcher.py:90-123`
- `src/re_ass/arxiv_fetcher.py:126-160`

Conclusion:

The implementation does read categories and priorities from the preferences file, but it does not evaluate the full candidate list using the full preference document in any semantic sense. It performs a local lexical ranking heuristic.

### 5. The current fetch logic does not guarantee complete coverage of the requested date range

There are three separate gaps here.

#### 5a. Fetching is capped before date filtering

The arXiv query requests only `max_results` items, default `200`, before any local time-window filtering:

- `re_ass.toml:33-38`
- `src/re_ass/arxiv_fetcher.py:192-199`

If the chosen categories produce more than 200 papers inside the desired window, older in-window candidates are never seen and therefore cannot be ranked.

#### 5b. Normal runs use a rolling 24-hour window, not an explicit calendar-day interval

For non-backfill runs:

- `pipeline.run()` sets `target_date = date.today()`
- `_determine_window_end(..., explicit_date=False)` returns `datetime.now(timezone.utc)`
- the fetcher then uses `window_end - fetch_window_hours`

Relevant locations:

- `src/re_ass/pipeline.py:23-28`
- `src/re_ass/pipeline.py:83-107`
- `src/re_ass/settings.py:236-239`

Effect:

- default runs cover "last 24 hours from now", not "today in local time"
- if the schedule drifts, or the tool is not run daily, coverage is not tied to a stable day boundary

#### 5c. The fallback window only tops up when the primary window returns fewer than 3 matches

The wider lookback is used only to fill empty slots:

- `src/re_ass/arxiv_fetcher.py:207-230`

Effect:

- if there are already 3 matching papers in the last 24 hours, older unseen papers inside the wider 7-day lookback are ignored
- if the tool was not run for a few days, relevant papers can be skipped permanently whenever enough newer matches exist

Conclusion:

The current implementation does not satisfy the stronger requirement of "get the full list from the correct categories across the correct date range, then rank that full list."

### 6. Existing tests only validate the current heuristic ranking, not the intended exhaustive ranking workflow

Current ranking tests verify:

- category query construction (`tests/test_arxiv_fetcher.py:10-11`)
- local time-window filtering (`tests/test_arxiv_fetcher.py:14-25`)
- heuristic preference ranking (`tests/test_arxiv_fetcher.py:28-43`)
- fallback top-up (`tests/test_arxiv_fetcher.py:46-76`)
- completed-paper suppression (`tests/test_arxiv_fetcher.py:79-126`)

Missing tests include:

- fetching beyond the first page / beyond `max_results`
- multi-category exhaustive candidate collection across a fixed interval
- normal-run date-window semantics
- ranking the whole candidate set against the full preferences context
- stable top-3 selection when many weak lexical matches compete with fewer strong semantic matches

## What should happen

If the intended product requirement is the one described by the user, the pipeline should behave as follows:

1. Read categories and ranked priorities from `preferences.md`.
2. Determine an explicit interval to cover.
   - Backfill: the exact local-day range for the requested date.
   - Scheduled/default run: either the previous successful run boundary to now, or an explicit local-day interval. It should not silently rely on a rolling 24-hour window unless that is the intended spec.
3. Fetch all candidate papers in the configured categories that fall within that interval.
   - Do not stop at the first `max_results` batch if more in-range results exist.
4. Deduplicate against retained completion state.
5. Rank the full candidate set against the user priorities.
6. Select the top 3 unseen papers.
7. Download PDFs, summarise them, write paper notes, and update daily/weekly notes.
8. Persist enough ranking metadata to audit why those 3 were selected.

## Recommended ranking approach

Using the LLM infrastructure for ranking is reasonable, but a pure "send every paper to the LLM" design will become expensive and unstable as the candidate set grows.

The pragmatic design is a two-stage ranker:

1. High-recall deterministic pre-rank
   - fetch all in-range candidates
   - score them cheaply using lexical matching / category weighting / simple embeddings
   - keep the top N candidates, where N might be 20-50

2. Structured rerank over the narrowed set
   - send the user priorities plus candidate titles/abstracts/categories to the LLM
   - require strict JSON output with per-paper scores and short rationales
   - select the top 3 from that reranked set

Why this is preferable:

- better recall than the current keyword-only filter
- much cheaper and more stable than ranking hundreds of abstracts directly with the LLM
- easier to test, because stage 1 and stage 2 have clear contracts

If local-only ranking is preferred, an embedding or cross-encoder reranker could replace the LLM rerank step, but that would add new model/runtime dependencies.

## Recommended code changes

### Summariser integration

Minimum corrections given the clarified product goal that this is an LLM-required tool:

1. Remove `llm.enabled` entirely from config, settings, docs, and tests.
2. Make provider configuration mandatory at startup and fail fast when the configured provider cannot run.
   - missing CLI binary or missing API key should be a startup error, not a silent downgrade
3. Remove `allow_local_paper_note_fallback` and the local paper-note fallback path.
   - if the configured LLM cannot be used, the run should fail hard rather than emitting a fake summary
   - per-paper failures should be recorded as failures, not emitted as "summaries"
4. Stop rewriting successful summariser output in `GenerationService._build_note_content()`.
   - preserve the summariser's title/authors/published lines if the goal is "upstream-exact" summaries
5. Add an end-to-end test covering real `GenerationService` note output with a fake summariser response.

### Ranking and candidate selection

Minimum corrections given the clarified goal that the LLM should identify papers as well as summarise them:

1. Separate candidate collection from top-3 selection.
2. Fetch the complete in-range candidate set across all configured categories.
3. Replace the current keyword-only filter with an LLM-backed ranking stage over the candidate set.
4. Use a two-stage ranker for scale and quality:
   - deterministic high-recall pre-rank over all candidates
   - structured LLM rerank over the narrowed shortlist
5. Persist ranking diagnostics for each run.
6. Add tests for:
   - exhaustive in-range fetching
   - normal-run interval semantics
   - multi-category candidate collection
   - rerank behaviour
   - top-3 stability

## Implementation plan

1. Remove optional-LLM wiring.
   - delete `llm.enabled`
   - make provider creation unconditional
   - update setup/docs so installation requires a working provider

2. Remove silent note degradation.
   - delete or disable `_build_fallback_note()`
   - make summariser failures bubble up as `GenerationError`
   - decide separately whether micro-summary and weekly synthesis may still have explicit degraded fallbacks

3. Preserve upstream summariser output.
   - stop extracting only `##` sections
   - write the summariser output directly, or apply only minimal validation/repair that does not alter structure

4. Replace top-3 heuristic ranking.
   - fetch all candidates in the requested interval
   - build a candidate list with title, abstract, authors, categories, published date, and arXiv id
   - pre-rank cheaply to control context size
   - LLM-rerank the shortlist using the full preferences file and require structured JSON output

5. Strengthen retained state and observability.
   - store interval start/end for each run
   - store candidate counts and shortlisted ids
   - store LLM ranking outputs or at least final scores and rationales

6. Add the missing tests before or alongside the refactor.
   - startup fails when provider prerequisites are missing
   - startup fails when `GenerationService` cannot construct the configured provider
   - enabled summariser output is preserved exactly
   - exhaustive in-range fetching works across multi-category queries
   - LLM ranking decides the top 3 from a larger candidate set
   - no silent fallback summaries are written

## Fresh-chat implementation brief

The work can be done in four phases. The safest order is tests first for each phase, then implementation.

### Phase 1: make the LLM mandatory

Goal:

- remove all configuration and runtime paths that allow paper-note generation without a usable provider

Files to change:

- `re_ass.toml`
- `src/re_ass/settings.py`
- `src/re_ass/generation_service.py`
- `src/re_ass/pipeline.py`
- `README.md`
- `tests/test_settings.py`
- `tests/test_pipeline.py`
- `tests/support.py`

Required behaviour:

- `llm.enabled` is removed from config and code
- `allow_local_paper_note_fallback` is removed from config and code
- `GenerationService` always constructs the configured provider
- if provider construction fails, the run exits with a fatal error before any paper note is written
- no metadata-only fallback note is ever written

Tests to add or update first:

- `tests/test_settings.py`
  - config parses without `llm.enabled`
  - config parses without `allow_local_paper_note_fallback`
- `tests/test_pipeline.py`
  - pipeline fails hard when provider construction fails
  - pipeline does not write paper notes on provider construction failure
- `tests/support.py`
  - test helper config should represent a valid mandatory-LLM config shape

### Phase 2: preserve summariser output exactly

Goal:

- ensure final paper notes are the summariser output, not an app-rewritten version

Files to change:

- `src/re_ass/generation_service.py`
- possibly `src/re_ass/paper_summariser/service.py` if minimal repair is needed
- `tests/test_paper_summariser_service.py`
- `tests/test_pipeline.py`

Required behaviour:

- successful summariser output is written verbatim, or with only minimal non-structural repair
- app-generated bullets such as `- ArXiv:` and injected `## Abstract` are not added on top of successful summariser output
- the final note structure matches the vendored template contract

Tests to add first:

- `tests/test_pipeline.py`
  - fake summariser output survives intact into the written note
- `tests/test_paper_summariser_service.py`
  - if a repair layer exists, it preserves the expected title/authors/published/section order

### Phase 3: replace heuristic top-3 selection with exhaustive candidate collection plus LLM rerank

Goal:

- collect the full in-range candidate set, then let the LLM choose the best papers from a shortlist

Files to change:

- `src/re_ass/arxiv_fetcher.py`
- `src/re_ass/pipeline.py`
- likely a new ranking module under `src/re_ass/`
- `src/re_ass/models.py`
- `tests/test_arxiv_fetcher.py`
- likely a new test module for ranking

Required behaviour:

- candidate collection is separated from final top-3 selection
- collection spans all configured categories and the full requested interval
- selection is based on LLM reranking of a shortlist, not only token overlap
- completed papers remain excluded using `state/papers/*.json`

Tests to add first:

- exhaustive candidate collection across multiple categories
- no truncation at the first in-range page of results
- explicit backfill date range uses a stable local-day interval
- LLM reranker receives the shortlist plus full user priorities
- top 3 come from reranker output, not heuristic ordering

### Phase 4: add ranking observability and tighten docs

Goal:

- make every run auditable and make setup expectations explicit

Files to change:

- `src/re_ass/state_store.py`
- `src/re_ass/pipeline.py`
- `README.md`
- possibly `docs/restructuring-plan-2026-03-22.md`
- tests covering run summary persistence

Required behaviour:

- run summaries record interval start/end
- run summaries record candidate count, shortlist size, and selected paper ids
- if practical, run summaries record LLM ranking scores or rationales
- README states clearly that the tool requires a working LLM provider

## Acceptance criteria

The refactor is complete when all of the following are true:

1. A default run cannot proceed without a usable configured provider.
2. No paper note is written from a local fallback path.
3. A successful paper note matches the summariser output format rather than an app-side rewritten format.
4. Candidate collection covers all configured categories across the intended interval.
5. Top-3 selection is driven by an LLM rerank step over the candidate shortlist.
6. The run summary is sufficient to explain why those papers were selected.
7. The automated test suite covers the fail-fast provider contract, summariser output preservation, exhaustive candidate collection, and rerank-driven top-3 selection.

## Recommended fail-fast test strategy

The useful contract is not "some LLM exists somewhere"; it is "the configured provider for this installation is usable now."

That should be tested at two levels:

1. Unit tests around provider prerequisite validation.
   - missing CLI binary raises immediately for CLI mode
   - missing API key raises immediately for API mode
   - invalid provider name raises immediately

2. Startup or pipeline-construction tests.
   - building `GenerationService` with the configured provider succeeds when prerequisites are present
   - running the CLI or pipeline fails before paper processing begins when the configured provider cannot be created

Recommended concrete test file layout:

- `tests/test_settings.py`
  - config-schema tests after removing `llm.enabled` and `allow_local_paper_note_fallback`
- `tests/test_generation_service.py` or expand `tests/test_paper_summariser_service.py`
  - provider-construction fail-fast tests
  - successful summariser output preservation tests
- `tests/test_pipeline.py`
  - fatal startup/provider failure tests
  - "no fallback note written" tests
- `tests/test_arxiv_fetcher.py`
  - exhaustive candidate collection and interval semantics
- `tests/test_ranking.py` if a new reranker module is introduced
  - shortlist construction
  - LLM rerank request/response contract
  - top-3 selection from rerank output

What should not be required in normal test runs:

- a live external API call
- a real model completion

Those are better treated as optional manual smoke checks or a separately gated integration test, because they depend on local machine credentials and network state.

## Verification performed

Commands run:

- `uv run pytest tests/test_paper_summariser_service.py tests/test_arxiv_fetcher.py tests/test_pipeline.py tests/test_preferences.py`
- `uv run pytest`

Results:

- all targeted tests passed
- full suite passed: 36 tests

Additional manual verification:

- a small `uv run python` harness injected a fake summariser result into `GenerationService`
- the resulting note still had app-generated metadata bullets and `## Abstract`, confirming that enabled summariser output is rewritten before being written

## Bottom line

1. The fallback note seen on a fresh install is explained by the current default configuration: LLM summarisation is disabled by default.
2. Based on the clarified product goal, that optional-LLM design is itself wrong and should be removed.
3. There is also a genuine integration defect relative to the stated goal: successful summariser output is not preserved exactly.
4. The current top-3 logic does not implement exhaustive full-candidate ranking over a correct explicit date range; it implements capped retrieval plus heuristic lexical ranking.
