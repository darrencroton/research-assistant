# Report: PDF Path And Paper-Selection Options

Date: 2026-03-22

## Executive Summary

Two separate issues showed up in the runs you did on March 22, 2026:

1. The Claude run used `mode = "cli"` with `provider = "claude"`, so it could not send PDFs directly to Claude. It fell back to `marker-pdf`, exactly as the current code is designed to do.
2. The weak top-3 selection on the March 20, 2026 backfill was not caused by a 100-paper fetch cap. In that run, the system collected only 6 in-range `astro-ph.CO` candidates and the LLM saw all 6. The bad outcome came from poor candidate quality and weak relevance discrimination, not from pagination truncation.

Bottom line:

- Direct PDF to Claude is possible, but only through the Claude API path, not the current Claude CLI path.
- The installed `arxiv` client already supports fetching beyond 100 results by auto-paginating when `Search.max_results=None`.
- The real architectural bottleneck is ranking quality once the candidate set grows into the hundreds.
- If the requirement is to use a Claude Pro subscription through the Claude CLI, then the correct choice is to keep the current CLI summarisation path and not switch billing modes just for direct-PDF ingestion.

My recommendation is **Option 2** below: build a **custom hybrid retrieval + reranking stack** and keep the frontier model only for the final semantic judgment on a much smaller, high-recall set.

## What Happened In The Recent Runs

### Run 1: `uv run re-ass`

Evidence from [logs/last-run.log](../logs/last-run.log) and [logs/history.log](../logs/history.log):

- Date run: March 22, 2026
- Provider used: `mode='cli'`, `provider='codex'`
- Interval searched: `2026-03-21T13:00:00+00:00` to `2026-03-22T04:47:39.703329+00:00`
- Categories searched: only `astro-ph.CO`
- Candidates found: `0`

This explains why that run produced no papers. It was not a provider problem. It was simply an empty interval for the currently configured category.

### Run 2: `uv run re-ass --date 2026-03-20`

Evidence from [logs/last-run.log](../logs/last-run.log), [state/runs/2026-03-20-2026-03-22T04-59-10Z.json](../state/runs/2026-03-20-2026-03-22T04-59-10Z.json), and generated outputs under [output/papers](../output/papers):

- Date run: March 22, 2026
- Explicit backfill target date: March 20, 2026
- Provider used: `mode='cli'`, `provider='claude'`
- Interval searched: `2026-03-19T13:00:00+00:00` to `2026-03-20T13:00:00+00:00`
- Categories searched: only `astro-ph.CO`
- Candidates found: `6`
- Shortlist size: `6`
- The LLM rerank saw all 6 candidates

Selected papers:

1. `2603.18884` Primordial black holes and the velocity acoustic oscillations features in 21 cm signals from the cosmic Dark Ages
2. `2603.18986` A calibration-free null test from anisotropic BAO
3. `2603.19154` Half-wave-plate non idealities propagated to component separated CMB B-modes

Important conclusion:

- This was **not** a case where the best papers were hidden on page 2 or page 3.
- The system ranked the full candidate set it had for that interval.
- The quality problem was that only one candidate had a meaningful match to your stated priorities, and the system still forced a top 3.

## Root Cause Of The Weak March 20 Selection

There are three separate causes.

### 1. Category scope is currently too narrow

Your current [preferences.md](../preferences.md) searches only:

- `astro-ph.CO`

But your stated priorities are:

1. Little red dots
2. Black holes and AGN
3. Semi-analytic galaxy formation models

Those interests are not confined to `astro-ph.CO`. In practice, many strong matches will land in:

- `astro-ph.GA`
- `astro-ph.HE`
- sometimes `astro-ph.IM` or cross-lists

So even a perfect ranker cannot select papers it never sees.

### 2. The current deterministic pre-ranker is too weak

The saved run summary shows several irrelevant papers receiving a non-trivial pre-rank match against:

- `Semi-analytic galaxy formation models`

That happened because the current pre-ranking logic is lexical and generic-token driven. Terms like `model` or `models` can create false positives. That is exactly the kind of failure mode that hurts recall and precision when the candidate pool gets large.

### 3. The pipeline currently always takes 3 papers

For the March 20, 2026 interval, the saved ranking results show one moderately relevant paper and then a steep drop in relevance. Even so, the pipeline still selected three papers.

If quality is paramount, a future design should support a **minimum relevance threshold** or **confidence gate** so the system can return fewer than 3 when the candidate pool is weak.

## PDF Ingestion: Can Claude Take The PDF Directly?

### Current behavior

Current config in [re_ass.toml](../re_ass.toml):

```toml
[llm]
mode = "cli"
provider = "claude"
```

Current code behavior:

- [src/re_ass/paper_summariser/providers/cli.py](../src/re_ass/paper_summariser/providers/cli.py) explicitly states that CLI providers never support direct PDF input.
- [src/re_ass/paper_summariser/providers/api.py](../src/re_ass/paper_summariser/providers/api.py) marks `ClaudeAPI.supports_direct_pdf()` as `True`.

So the March 20 run used `marker-pdf` because that is the only possible path for the current Claude CLI configuration.

### Verified result

Anthropic’s official docs say:

- PDF support is available via **direct API access**
- PDFs can be sent as a URL, as base64 in a `document` block, or via the Files API
- Claude processes both extracted text and page images for PDF understanding

That means:

- **Yes**, sending the PDF directly is possible with Claude
- **No**, it is not available via the current Claude CLI setup in this repo
- **Yes**, it is likely the better path for summarisation quality and latency when you have API credentials

### Why the API PDF path is better here

The March 20 logs show the local extraction overhead clearly:

- paper 1: roughly 93 seconds from extraction start to extracted text
- paper 2: roughly 15 seconds
- paper 3: roughly 74 seconds

Direct PDF to Claude API avoids:

- local `marker-pdf` startup
- local extraction latency
- extraction failures from OCR / layout reconstruction
- losing visual layout information before the model sees the paper

For a scientific-paper summariser, that is a meaningful improvement.

### Constraint on this machine right now

I checked the environment and `ANTHROPIC_API_KEY` is **not** currently set.

So the immediate operational state is:

- current Claude CLI setup: works, but requires `marker-pdf`
- recommended Claude API setup: better, but blocked until credentials are available

### Recommendation for summarisation path

If you want the technically strongest Claude PDF ingestion path for paper summarisation:

```toml
[llm]
mode = "api"
provider = "claude"
model = "claude-sonnet-4-latest"
```

Do that only after setting `ANTHROPIC_API_KEY`.

No major code change is required for that switch. The direct-PDF path already exists in the codebase.

### Revised recommendation if Claude Pro via CLI is a hard requirement

If the non-negotiable requirement is:

- use the `claude` CLI
- use the Claude Pro subscription you already pay for
- keep the current successful summary quality

then I do **not** recommend switching to the API just for direct-PDF support.

In that case the practical recommendation is:

- keep `mode = "cli"` and `provider = "claude"`
- accept `marker-pdf` as the local extraction layer
- spend engineering effort on ranking, not on the PDF path

Given your latest clarification, this is now my operational recommendation.

## Can The Current Fetch Path Handle More Than 100 Papers?

Yes.

I verified the installed `arxiv` Python library locally:

- `arxiv.Search(max_results=None)` means “fetch every result available”
- `arxiv.Client.results()` auto-paginates internally through `_results()`
- pagination continues until the total result set is exhausted

So the current fetch path can already go beyond 100 results.

Important nuance:

- `page_size = 100` is only the request page size
- it is **not** a global cap
- the real risk is not fetching
- the real risk is **shortlist recall**

Today’s shortlist is only `24`, so a semantically relevant paper can still be lost before the final LLM rerank if the pre-ranker is weak.

## Three Options For Ranking 500 Candidates Reliably

### Option 1: Strengthen The Existing Two-Stage Pipeline

Keep the current architecture shape, but make it much less brittle:

- fetch all candidates across the interval and categories
- expand categories to reflect your true interests
- decompose the preferences into multiple subqueries
- enforce per-priority quotas into the shortlist
- add better lexical weighting and remove generic-token false positives
- increase shortlist size substantially, for example `24 -> 100` or `150`
- let the frontier model do the final rerank on that larger shortlist
- add a minimum relevance threshold so weak candidates do not automatically fill the top 3

Pros:

- Lowest engineering cost
- Reuses the current code structure
- No new external dependencies required
- Fastest path to “less bad than today”

Cons:

- Still too dependent on a hand-built pre-ranker
- Still exposes you to recall failures when lexical overlap is weak
- Not the strongest option if “absolutely optimal” selection is the goal

Assessment:

- Good short-term patch
- Not good enough as the long-term architecture

### Option 2: Build A Custom Hybrid Retrieval + Reranking Stack

This is the strongest option and my recommendation.

Architecture:

1. Fetch **all** candidates for the interval across **all configured categories**
2. Build a temporary local candidate index for the run
3. Use **high-recall hybrid retrieval** over all candidates:
   - lexical retrieval over title, abstract, categories, comments
   - dense embedding retrieval over title + abstract
   - multiple queries derived from:
     - each numbered priority
     - the full preferences document
     - optional hand-curated astrophysics aliases
4. Take the union of the top results from those retrieval channels
5. Run a **cross-encoder reranker** over the union set
6. Send only the top 20-40 papers to the frontier LLM for the final top-3 decision and rationale
7. Apply a relevance/confidence threshold before accepting the final 3

Practical implementation choices:

- lexical index: built-in SQLite FTS5 or another local BM25-capable index
- dense retrieval and cross-encoder reranking: local models via [Sentence Transformers CrossEncoder docs](https://sbert.net/docs/package_reference/cross_encoder/cross_encoder.html)
- final semantic judge: Claude or another frontier model

Pros:

- Best balance of recall, precision, cost, and auditability
- Scales comfortably to 500+ candidates
- Stronger than pure lexical pre-ranking
- Much cheaper and more stable than asking a frontier model to score 500 papers directly
- Can be built as a custom local tool without sending all metadata to a third-party ranking vendor

Cons:

- More engineering work
- Introduces local ML-model dependencies if done fully in-house
- Requires careful evaluation to tune union sizes and thresholds

Assessment:

- Best long-term architecture
- This is the option I recommend

### Option 3: Use A Managed External Rerank Service

Use a dedicated ranking API after exhaustive fetch, then keep the frontier model only for the final semantic top 3.

Examples:

- [Cohere Rerank docs](https://docs.cohere.com/docs/reranking)
- [Voyage reranker docs](https://docs.voyageai.com/docs/reranker)

Architecture:

1. Fetch all candidates
2. Use a simple high-recall lexical/embedding recall stage
3. Send the recall set to a managed rerank API
4. Send the best 20-40 to the frontier model for final selection

Pros:

- Fastest path to a strong reranking stage
- Good semantic ranking quality out of the box
- Lower engineering effort than building the full local reranking stack yourself

Cons:

- Another vendor dependency
- Additional per-call cost
- Metadata leaves your local environment
- Less control and harder to customise for astrophysics-specific edge cases

Assessment:

- Strong pragmatic choice if speed of implementation matters more than full local control
- Still not my top recommendation for this project

## Recommendation

I recommend **Option 2: a custom hybrid retrieval + reranking stack**, with these non-negotiable design rules:

1. **Exhaustive candidate collection**
   - keep fetching all candidates in-range across all configured categories
   - no hard cap at 100, 200, or one page

2. **Correct category coverage**
   - categories must match the real interests
   - with your current interests, `astro-ph.GA` should almost certainly be considered

3. **High-recall first stage**
   - do not trust a single lexical score
   - use hybrid retrieval and per-priority query decomposition

4. **Stronger second stage**
   - rerank the recall set with a real reranker, not only a handcrafted token matcher

5. **Frontier model only at the end**
   - use the frontier model where it adds the most value: nuanced final judgment over a small, strong candidate pool

6. **Confidence gating**
   - do not force three weak papers when the pool is poor

If the goal is “no compromises”, this is the right architecture.

## Immediate Next Steps I Recommend

### For ranking

1. Expand categories in [preferences.md](../preferences.md) to match the actual interests
2. Stop forcing top 3 when relevance is weak
3. Replace the current lexical pre-ranker with Option 2

## Implementation Brief For A New Chat

This section is the execution handoff. A new chat should be able to start implementation directly from here.

### User Constraints

- Use `claude` CLI with the user’s Claude Pro subscription for summarisation.
- Do not switch to Anthropic API just to get direct-PDF support.
- The ranking step is the top priority of the tool.
- Quality matters more than minimizing engineering effort.
- Custom local tools are acceptable if they materially improve paper selection quality.

### Current Confirmed State In Code

- Exhaustive in-range fetch already exists in [src/re_ass/arxiv_fetcher.py](../src/re_ass/arxiv_fetcher.py).
- The pipeline already records interval bounds, candidate counts, shortlist diagnostics, and rerank output in [src/re_ass/pipeline.py](../src/re_ass/pipeline.py).
- The current weak point is the lexical pre-ranker in [src/re_ass/ranking.py](../src/re_ass/ranking.py).
- Summarisation is already working well enough with Claude CLI plus `marker-pdf`.

### What Must Change

1. Replace the current lexical pre-ranker with a true high-recall retrieval stage.
2. Add a stronger reranking stage before the final Claude judgment.
3. Add a confidence threshold so the pipeline can return fewer than 3 papers when the pool is weak.
4. Expand category coverage to match the user’s scientific interests.
5. Add evaluation fixtures and tests focused on ranking quality, not just plumbing.

### Recommended Architecture To Implement

Phase 1: retrieval and indexing

- Build a per-run local candidate index after exhaustive fetch.
- Candidate fields to index:
  - title
  - abstract
  - primary category
  - all categories
  - authors
  - arXiv comments if available in fetched metadata
  - published date
  - source id / paper key
- Use SQLite FTS5 for lexical retrieval.
- Add query decomposition:
  - each numbered priority from `preferences.md`
  - the full preferences text
  - optional generated aliases for astrophysics-specific terms

Phase 2: dense recall

- Add dense embedding retrieval over title + abstract.
- Keep this local if practical.
- Preferred first implementation:
  - `sentence-transformers`
  - a strong general embedding model already supported by that stack
- Use reciprocal-rank fusion or weighted union to merge lexical and dense recall results.

Phase 3: reranking

- Add a cross-encoder reranker over the fused recall set.
- Preferred first implementation:
  - `sentence-transformers` cross-encoder
- Target rerank input size:
  - recall set around 50-150 papers
- Output:
  - numeric rerank score
  - per-paper explanation string for saved diagnostics

Phase 4: final Claude decision

- Send only the top 20-40 reranked papers to Claude CLI.
- Claude should:
  - pick up to 3 papers
  - justify each choice against the user’s priorities
  - optionally return fewer than 3 if the pool is weak
- The pipeline should respect that output rather than always filling all 3 slots.

### Files To Change

- [src/re_ass/arxiv_fetcher.py](../src/re_ass/arxiv_fetcher.py)
  - likely minimal changes
  - possibly enrich fetched metadata if comments or other useful fields are available

- [src/re_ass/ranking.py](../src/re_ass/ranking.py)
  - main replacement target
  - split into:
    - lexical retrieval
    - dense retrieval
    - fusion
    - cross-encoder rerank
    - final Claude selection

- [src/re_ass/pipeline.py](../src/re_ass/pipeline.py)
  - accept “fewer than 3 selected papers”
  - persist richer ranking diagnostics

- [src/re_ass/models.py](../src/re_ass/models.py)
  - add structured types for retrieval hits, fused candidates, rerank results, and final selection confidence

- [src/re_ass/settings.py](../src/re_ass/settings.py)
  - add config for:
    - retrieval pool sizes
    - rerank pool size
    - confidence threshold
    - local model names / paths if introduced

- [re_ass.toml](../re_ass.toml)
  - expose the new ranking knobs

- [tests/test_ranking.py](../tests/test_ranking.py)
  - expand heavily for quality-sensitive ranking behavior

- New likely test fixture modules
  - curated candidate sets where the correct top 3 are known
  - adversarial lexical-false-positive cases

### Concrete Design Requirements

- The shortlist must not depend on a single token-overlap score.
- Generic terms like `model`, `models`, `formation`, `galaxy` must not create strong false positives by themselves.
- The system must support 200-500 candidates in one run without frontier-model cost blow-up.
- Final selection must be auditable from saved state.
- Daily runs should remain fast enough for regular use.

### Acceptance Criteria

The implementation is complete when all of the following are true:

1. The pipeline can fetch and process at least 500 metadata candidates without trying to send all 500 directly to Claude.
2. Ranking recall is meaningfully improved on curated test cases containing weak lexical but strong semantic matches.
3. The system can return fewer than 3 papers when all remaining candidates are below the acceptance threshold.
4. Saved run summaries include:
   - full candidate count
   - retrieval pool size
   - fused recall ids
   - rerank scores
   - final selected ids
   - final rationales
5. Claude CLI remains the summarisation path.

### Tests The Next Chat Should Add

- Exhaustive fetch with more than 100 results still collects the full interval candidate set.
- Fusion beats lexical-only ranking on a curated false-positive-heavy fixture.
- Cross-encoder reranking changes the order relative to the retrieval stage.
- Final Claude selection can return 1 or 2 papers instead of always 3.
- Category expansion changes recall as expected for priorities like AGN / little red dots / semi-analytic models.

### Best Next Action

The next chat should do this first:

1. Refactor [src/re_ass/ranking.py](../src/re_ass/ranking.py) into explicit stages with interfaces for lexical retrieval, dense retrieval, fusion, reranking, and final Claude selection.
2. Add failing tests in [tests/test_ranking.py](../tests/test_ranking.py) that capture the current false-positive problem and the “fewer than 3 papers” requirement.
3. Only then implement the hybrid retrieval stack.

### Important Warnings

- Do not spend time changing the summariser path unless the user later asks for it. Claude CLI is the chosen operational mode.
- Do not assume `astro-ph.CO` alone is sufficient for the current interests.
- Do not rely on the March 20 run as evidence that pagination is already perfect under all category combinations; it only proves the bad ranking that day was not caused by page truncation.
- The current repo already has uncommitted local changes; do not revert unrelated work.

## Sources

External:

- [Anthropic PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support)
- [Anthropic Files API](https://platform.claude.com/docs/en/build-with-claude/files)
- [arXiv recent astro-ph.CO](https://arxiv.org/list/astro-ph.CO/recent)
- [arXiv recent astro-ph.GA](https://arxiv.org/list/astro-ph.GA/recent)
- [Sentence Transformers CrossEncoder docs](https://sbert.net/docs/package_reference/cross_encoder/cross_encoder.html)
- [Cohere rerank docs](https://docs.cohere.com/docs/reranking)
- [Voyage reranker docs](https://docs.voyageai.com/docs/reranker)

Local evidence:

- [re_ass.toml](../re_ass.toml)
- [preferences.md](../preferences.md)
- [logs/last-run.log](../logs/last-run.log)
- [logs/history.log](../logs/history.log)
- [state/runs/2026-03-20-2026-03-22T04-59-10Z.json](../state/runs/2026-03-20-2026-03-22T04-59-10Z.json)
- [src/re_ass/paper_summariser/providers/cli.py](../src/re_ass/paper_summariser/providers/cli.py)
- [src/re_ass/paper_summariser/providers/api.py](../src/re_ass/paper_summariser/providers/api.py)
- [src/re_ass/arxiv_fetcher.py](../src/re_ass/arxiv_fetcher.py)
- [src/re_ass/ranking.py](../src/re_ass/ranking.py)
- [src/re_ass/pipeline.py](../src/re_ass/pipeline.py)
