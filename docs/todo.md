# TODO

- Run live API-provider validation for the target non-CLI providers once credentials are available.
- Cache arXiv query results or add a replay harness so multi-day simulations and backfills do not refetch the full feed for every day.
- Consider switching paper-note filenames to an arXiv-ID-prefixed scheme if math-heavy titles become a practical problem.
- Evaluate bounded concurrency or extraction-result caching if `max_papers > 1` makes full-paper summarisation too slow in regular use.
