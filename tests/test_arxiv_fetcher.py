from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from re_ass.arxiv_fetcher import ArxivFetcher, build_category_query, filter_papers_between
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


def test_collect_candidates_fetches_all_in_range_results_across_categories() -> None:
    now = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)
    results = [
        SimpleNamespace(
            title="Too New",
            summary="Outside the end bound.",
            entry_id="https://arxiv.org/abs/2603.10020",
            authors=[SimpleNamespace(name="Test Author")],
            primary_category="cs.AI",
            categories=("cs.AI",),
            published=now + timedelta(hours=1),
            updated=now + timedelta(hours=1),
        ),
        SimpleNamespace(
            title="In Range One",
            summary="Agents and tools.",
            entry_id="https://arxiv.org/abs/2603.10021",
            authors=[SimpleNamespace(name="Test Author")],
            primary_category="cs.AI",
            categories=("cs.AI",),
            published=now - timedelta(hours=1),
            updated=now - timedelta(hours=1),
        ),
        SimpleNamespace(
            title="In Range Two",
            summary="Language models.",
            entry_id="https://arxiv.org/abs/2603.10022",
            authors=[SimpleNamespace(name="Test Author")],
            primary_category="cs.CL",
            categories=("cs.CL",),
            published=now - timedelta(hours=2),
            updated=now - timedelta(hours=2),
        ),
        SimpleNamespace(
            title="Too Old",
            summary="Outside the start bound.",
            entry_id="https://arxiv.org/abs/2603.10023",
            authors=[SimpleNamespace(name="Test Author")],
            primary_category="cs.CL",
            categories=("cs.CL",),
            published=now - timedelta(days=2),
            updated=now - timedelta(days=2),
        ),
    ]

    class FakeClient:
        def __init__(self) -> None:
            self.searches = []

        def results(self, _search: object):
            self.searches.append(_search)
            return results

    client = FakeClient()

    fetcher = ArxivFetcher(
        page_size=1,
        client=client,
    )

    papers = fetcher.collect_candidates(
        PreferenceConfig(priorities=("Agents",), categories=("cs.AI", "cs.CL"), raw_text="1. Agents"),
        start=now - timedelta(hours=3),
        end=now,
    )

    assert [paper.title for paper in papers] == ["In Range One", "In Range Two"]
    assert client.searches[0].query == "cat:cs.AI OR cat:cs.CL"


def test_collect_candidates_skips_completed_paper_keys() -> None:
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
        page_size=10,
        client=FakeClient(),
    )

    papers = fetcher.collect_candidates(
        PreferenceConfig(priorities=("Agents",), categories=("cs.AI",), raw_text="1. Agents"),
        start=now - timedelta(days=3),
        end=now,
        excluded_paper_keys={excluded_key},
    )

    assert [paper.title for paper in papers] == ["Fresh Agents Paper"]
