# Validation Report: 2026-03-22

## Scope

- Confirm the upstream-derived paper summariser is the active paper-note path.
- Validate the explicit provider architecture and `marker-pdf` extraction path in real runs.
- Confirm widened-lookback duplicate suppression against the `obsidian_vault/Papers` output contract.

## Commands Run

- `uv sync --group dev`
- `uv run python -m compileall src tests`
- `uv run pytest`
- `uv run re-ass --config archive/validation-2026-03-22/re_ass.claude.toml --date 2026-03-21`
- `uv run re-ass --config archive/simulation-2026-03-19-to-2026-03-21/re_ass.claude.toml --date 2026-03-19`
- `uv run re-ass --config archive/simulation-2026-03-19-to-2026-03-21/re_ass.claude.toml --date 2026-03-20`
- `uv run re-ass --config archive/simulation-2026-03-19-to-2026-03-21/re_ass.claude.toml --date 2026-03-21`

## Results

- `uv run pytest` passed with `23` tests.
- The single-day live validation completed successfully end-to-end:
  - arXiv fetch
  - local PDF download
  - `marker-pdf` extraction
  - Claude CLI summary generation
  - summary validation
  - paper note write
  - daily note update
  - weekly synthesis update
- The generated single-run artifacts are in `archive/validation-2026-03-22/`.
- The multi-day replay completed successfully for three consecutive dates using the same live provider configuration.
- The replay vault contains three distinct paper notes:
  - `QCD and electroweak phase transitions with hidden scale invariance: implications for primordial black holes, quark-lepton nuggets and gravitational waves`
  - `Primordial black holes and the velocity acoustic oscillations features in 21 cm signals from the cosmic Dark Ages`
  - `Halo assembly bias in the early Universe: a clustering probe of the origin of the Little Red Dots`
- The replay also produced:
  - `Daily/2026-03-19.md`
  - `Daily/2026-03-20.md`
  - `Daily/2026-03-21.md`
  - a weekly note with all three additions and a synthesized overview

## Observations

- The active architecture is now upstream-first:
  - explicit provider selection
  - provider prerequisite checks
  - direct-PDF support where available
  - `marker-pdf` fallback extraction where direct PDF is unavailable
  - upstream-style prompt construction and metadata validation
- The duplicate-suppression path worked during the replay. The widened lookback on `2026-03-21` still produced an unseen paper instead of repeating one of the notes already written on `2026-03-19` or `2026-03-20`.
- End-to-end runtime for live full-paper generation is measured in minutes per paper, which is consistent with the design and materially slower than the rejected lightweight path.

## Artifact Locations

- Single-day validation: `archive/validation-2026-03-22/`
- Multi-day replay: `archive/simulation-2026-03-19-to-2026-03-21/`
- Latest replay weekly note: `archive/simulation-2026-03-19-to-2026-03-21/vault/this-weeks-arxiv-papers.md`

## Remaining Follow-up

- Live API-provider validation when credentials are available.
- Faster replay/backfill support via cached arXiv data.
- Possible filename hardening if long math-heavy titles become operationally awkward.
