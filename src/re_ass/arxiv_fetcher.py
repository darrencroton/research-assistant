"""arXiv paper fetching and interval-based candidate collection for re-ass."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
import logging
from typing import Any

import arxiv

from re_ass.models import ArxivPaper, PreferenceConfig
from re_ass.paper_identity import derive_identity


LOGGER = logging.getLogger(__name__)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_category_query(categories: tuple[str, ...]) -> str:
    return " OR ".join(f"cat:{category}" for category in categories)


def _to_paper(result: Any) -> ArxivPaper:
    return ArxivPaper(
        title=result.title.strip(),
        summary=result.summary.strip(),
        arxiv_url=result.entry_id.strip(),
        entry_id=result.entry_id.strip(),
        authors=tuple(author.name for author in result.authors),
        primary_category=result.primary_category,
        categories=tuple(result.categories),
        published=_ensure_utc(result.published),
        updated=_ensure_utc(result.updated) if result.updated else None,
    )


def filter_papers_between(
    papers: Iterable[ArxivPaper],
    *,
    start: datetime,
    end: datetime,
) -> list[ArxivPaper]:
    start_utc = _ensure_utc(start)
    end_utc = _ensure_utc(end)
    return [
        paper
        for paper in papers
        if start_utc <= _ensure_utc(paper.published) < end_utc
    ]


class ArxivFetcher:
    def __init__(
        self,
        *,
        page_size: int,
        client: arxiv.Client | None = None,
    ) -> None:
        self.page_size = max(1, min(page_size, 100))
        self.client = client or arxiv.Client(page_size=self.page_size, num_retries=3, delay_seconds=3)

    def collect_candidates(
        self,
        preferences: PreferenceConfig,
        *,
        start: datetime,
        end: datetime,
        excluded_paper_keys: set[str] | None = None,
    ) -> list[ArxivPaper]:
        """Fetch all in-range candidate papers, suppressing duplicates by paper_key."""
        start_utc = _ensure_utc(start)
        end_utc = _ensure_utc(end)
        query = build_category_query(preferences.categories)
        search = arxiv.Search(
            query=query,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        combined: list[ArxivPaper] = []
        seen_keys: set[str] = set()
        excluded = excluded_paper_keys or set()

        for result in self.client.results(search):
            paper = _to_paper(result)
            published = _ensure_utc(paper.published)
            if published >= end_utc:
                continue
            if published < start_utc:
                break
            try:
                identity = derive_identity(paper)
            except ValueError as error:
                LOGGER.warning("Skipping paper with invalid arXiv identity (%s): %s", paper.title, error)
                continue
            if identity.paper_key in seen_keys:
                continue
            if identity.paper_key in excluded:
                continue
            combined.append(paper)
            seen_keys.add(identity.paper_key)
        LOGGER.info(
            "Collected %s candidate paper(s) between %s and %s for categories %s.",
            len(combined),
            start_utc.isoformat(),
            end_utc.isoformat(),
            ", ".join(preferences.categories),
        )
        return combined
