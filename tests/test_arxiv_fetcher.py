from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from re_ass.arxiv_fetcher import ArxivFetcher, build_category_query, filter_papers_between, rank_papers
from re_ass.models import PreferenceConfig
from re_ass.paper_identity import derive_identity
from tests.support import make_paper


def test_build_category_query_joins_categories() -> None:
    assert build_category_query(("cs.AI", "cs.CL")) == "cat:cs.AI OR cat:cs.CL"


def test_filter_papers_between_respects_start_and_end_bounds() -> None:
    start = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
    papers = [
        make_paper(arxiv_id="2603.10001", title="Inside Window", published=start + timedelta(hours=6)),
        make_paper(arxiv_id="2603.10002", title="Too Old", published=start - timedelta(hours=6)),
        make_paper(arxiv_id="2603.10003", title="Future Paper", published=end + timedelta(hours=1)),
    ]

    recent = filter_papers_between(papers, start=start, end=end)

    assert [paper.title for paper in recent] == ["Inside Window"]


def test_rank_papers_prefers_highest_ranked_preference_then_recency() -> None:
    now = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
    papers = [
        make_paper(arxiv_id="2603.10011", title="Agents Planning", summary="Planning systems", published=now - timedelta(hours=3)),
        make_paper(arxiv_id="2603.10012", title="RAG Benchmarks", summary="Retrieval methods", published=now - timedelta(hours=1)),
        make_paper(arxiv_id="2603.10013", title="Agents and RAG", summary="Joint systems", published=now - timedelta(hours=5)),
        make_paper(arxiv_id="2603.10014", title="Unrelated Vision", summary="Image generation", published=now - timedelta(hours=2)),
    ]

    ranked = rank_papers(papers, ("Agents", "RAG"), max_papers=3)

    assert [paper.title for paper in ranked] == [
        "Agents and RAG",
        "Agents Planning",
        "RAG Benchmarks",
    ]


def test_fetch_top_papers_tops_up_from_fallback_window_when_needed() -> None:
    now = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
    result = SimpleNamespace(
        title="Primordial black holes in the early universe",
        summary="A study of black hole populations in cosmology.",
        entry_id="https://arxiv.org/abs/2603.10021",
        authors=[SimpleNamespace(name="Test Author")],
        primary_category="astro-ph.CO",
        categories=("astro-ph.CO",),
        published=now - timedelta(hours=48),
        updated=now - timedelta(hours=48),
    )

    class FakeClient:
        def results(self, _search: object):
            return [result]

    fetcher = ArxivFetcher(
        max_results=10,
        fetch_window_hours=24,
        fallback_window_hours=168,
        now_provider=lambda: now,
        client=FakeClient(),
    )

    papers = fetcher.fetch_top_papers(
        PreferenceConfig(priorities=("black holes and AGN",), categories=("astro-ph.CO",)),
        max_papers=3,
    )

    assert [paper.title for paper in papers] == ["Primordial black holes in the early universe"]


def test_fetch_top_papers_skips_completed_paper_keys() -> None:
    now = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
    results = [
        SimpleNamespace(
            title="Existing Agents Paper",
            summary="Agents and planning.",
            entry_id="https://arxiv.org/abs/2603.10031",
            authors=[SimpleNamespace(name="Author One")],
            primary_category="cs.AI",
            categories=("cs.AI",),
            published=now - timedelta(hours=48),
            updated=now - timedelta(hours=48),
        ),
        SimpleNamespace(
            title="Fresh Agents Paper",
            summary="Agents and execution.",
            entry_id="https://arxiv.org/abs/2603.10032",
            authors=[SimpleNamespace(name="Author Two")],
            primary_category="cs.AI",
            categories=("cs.AI",),
            published=now - timedelta(hours=49),
            updated=now - timedelta(hours=49),
        ),
    ]

    class FakeClient:
        def results(self, _search: object):
            return results

    excluded_key = derive_identity(
        make_paper(arxiv_id="2603.10031", title="Existing Agents Paper", summary="Agents and planning.", authors=("Author One",))
    ).paper_key

    fetcher = ArxivFetcher(
        max_results=10,
        fetch_window_hours=24,
        fallback_window_hours=168,
        now_provider=lambda: now,
        client=FakeClient(),
    )

    papers = fetcher.fetch_top_papers(
        PreferenceConfig(priorities=("Agents",), categories=("cs.AI",)),
        max_papers=1,
        excluded_paper_keys={excluded_key},
    )

    assert [paper.title for paper in papers] == ["Fresh Agents Paper"]
