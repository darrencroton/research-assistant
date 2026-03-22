"""Candidate pre-ranking and LLM reranking for re-ass."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any

from re_ass.models import ArxivPaper, PreferenceConfig
from re_ass.paper_identity import derive_identity
from re_ass.paper_summariser.providers.base import Provider
from re_ass.settings import LlmConfig


LOGGER = logging.getLogger(__name__)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "use",
    "using",
    "via",
    "with",
}
_TOKEN_EQUIVALENTS = {
    "agn": {"agn", "active", "galactic", "nuclei", "nucleus"},
    "llm": {"llm", "large", "language", "model"},
    "lrd": {"lrd", "little", "red", "dot"},
}


class RankingError(RuntimeError):
    """Raised when paper ranking cannot be completed."""


@dataclass(frozen=True, slots=True)
class PreRankedPaper:
    paper: ArxivPaper
    paper_key: str
    source_id: str
    pre_rank_score: int
    best_priority_index: int
    matched_priority_count: int
    best_match_score: int
    matched_priorities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RerankedPaper:
    paper: ArxivPaper
    paper_key: str
    source_id: str
    pre_rank_score: int
    rerank_score: float
    rationale: str
    best_priority_index: int
    matched_priority_count: int
    matched_priorities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RankingSelection:
    selected_papers: list[ArxivPaper]
    candidate_count: int
    shortlist: list[PreRankedPaper]
    reranked: list[RerankedPaper]


def _normalize_token(token: str) -> str:
    normalized = token.casefold()
    if normalized.endswith("s") and len(normalized) > 3:
        normalized = normalized[:-1]
    return normalized


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw_token in _TOKEN_PATTERN.findall(text):
        normalized = _normalize_token(raw_token)
        if normalized:
            tokens.add(normalized)

        for separator in ("-", "/"):
            if separator in raw_token:
                for part in raw_token.split(separator):
                    normalized_part = _normalize_token(part)
                    if normalized_part:
                        tokens.add(normalized_part)

    expanded_tokens: set[str] = set()
    for token in tokens:
        expanded_tokens.add(token)
        expanded_tokens.update(_TOKEN_EQUIVALENTS.get(token, set()))

    return {token for token in expanded_tokens if token and token not in _STOPWORDS}


def _score_preference_match(paper: ArxivPaper, preference: str) -> tuple[bool, int]:
    paper_text = paper.searchable_text.casefold()
    if preference.casefold() in paper_text:
        return True, 10_000

    preference_tokens = _tokenize(preference)
    if not preference_tokens:
        return False, 0

    paper_tokens = _tokenize(paper.searchable_text)
    overlap = len(preference_tokens & paper_tokens)
    return overlap > 0, overlap


def pre_rank_papers(papers: list[ArxivPaper], priorities: tuple[str, ...]) -> list[PreRankedPaper]:
    ranked: list[PreRankedPaper] = []

    for paper in papers:
        identity = derive_identity(paper)
        matches = [
            (index, priority, match_score)
            for index, priority in enumerate(priorities)
            for matched, match_score in [_score_preference_match(paper, priority)]
            if matched
        ]

        best_priority_index = min((index for index, _priority, _score in matches), default=len(priorities))
        matched_priority_count = len(matches)
        best_match_score = max((score for _index, _priority, score in matches), default=0)
        total_match_score = sum(score for _index, _priority, score in matches)
        pre_rank_score = 0
        if matches:
            pre_rank_score = (
                (len(priorities) - best_priority_index) * 100_000
                + matched_priority_count * 1_000
                + best_match_score * 10
                + total_match_score
            )

        ranked.append(
            PreRankedPaper(
                paper=paper,
                paper_key=identity.paper_key,
                source_id=identity.source_id,
                pre_rank_score=pre_rank_score,
                best_priority_index=best_priority_index,
                matched_priority_count=matched_priority_count,
                best_match_score=best_match_score,
                matched_priorities=tuple(priority for _index, priority, _score in matches),
            )
        )

    ranked.sort(
        key=lambda item: (
            -item.pre_rank_score,
            item.best_priority_index,
            -item.matched_priority_count,
            -item.best_match_score,
            -item.paper.published.timestamp(),
            item.paper.title.casefold(),
        )
    )
    return ranked


def _ranking_system_prompt() -> str:
    return (
        "You rank arXiv papers for a user based on the full preferences document.\n"
        "Return JSON only. Do not include markdown fences, prose, or commentary.\n"
        "Use only the provided candidate IDs.\n"
        "Consider the full preferences document, not just lexical overlap."
    )


def _ranking_user_prompt(preferences: PreferenceConfig, shortlist: list[PreRankedPaper]) -> str:
    candidates = [
        {
            "candidate_id": item.paper_key,
            "arxiv_id": item.source_id,
            "title": item.paper.title,
            "summary": item.paper.summary,
            "authors": list(item.paper.authors),
            "primary_category": item.paper.primary_category,
            "categories": list(item.paper.categories),
            "published": item.paper.published.isoformat(),
            "pre_rank_score": item.pre_rank_score,
            "matched_priorities": list(item.matched_priorities),
        }
        for item in shortlist
    ]

    return (
        "<task>\n"
        "Rank every candidate by relevance to the user's stated interests.\n"
        "Return exactly this JSON object shape:\n"
        '{"ranked_papers":[{"candidate_id":"arxiv:2603.12345","score":97,"rationale":"short reason"}]}\n'
        "Rules:\n"
        "- Include every candidate exactly once.\n"
        "- Sort ranked_papers from most relevant to least relevant.\n"
        "- score must be a number from 0 to 100.\n"
        "- rationale must be one sentence and under 30 words.\n"
        "- Prefer papers that best match the user's full priorities, not just keyword overlap.\n"
        "</task>\n\n"
        "<preferences_markdown>\n"
        f"{preferences.raw_text.strip()}\n"
        "</preferences_markdown>\n\n"
        "<candidates_json>\n"
        f"{json.dumps(candidates, indent=2)}\n"
        "</candidates_json>"
    )


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _load_ranking_payload(response_text: str) -> dict[str, Any]:
    cleaned = _strip_code_fences(response_text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise RankingError("Ranking provider did not return a JSON object.")

    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as error:
        raise RankingError(f"Ranking provider returned invalid JSON: {error}") from error

    if not isinstance(payload, dict):
        raise RankingError("Ranking provider returned a non-object JSON payload.")
    return payload


class PaperRanker:
    """Two-stage ranker: deterministic pre-rank plus structured LLM rerank."""

    def __init__(self, *, provider: Provider, config: LlmConfig, shortlist_size: int) -> None:
        self.provider = provider
        self.config = config
        self.shortlist_size = shortlist_size

    def select_top_papers(
        self,
        preferences: PreferenceConfig,
        candidates: list[ArxivPaper],
        *,
        max_papers: int,
    ) -> RankingSelection:
        if not candidates:
            return RankingSelection(selected_papers=[], candidate_count=0, shortlist=[], reranked=[])

        pre_ranked = pre_rank_papers(candidates, preferences.priorities)
        shortlist = pre_ranked[: min(len(pre_ranked), max(self.shortlist_size, max_papers))]
        reranked = self._rerank_shortlist(preferences, shortlist)
        selected = [item.paper for item in reranked[:max_papers]]
        return RankingSelection(
            selected_papers=selected,
            candidate_count=len(candidates),
            shortlist=shortlist,
            reranked=reranked,
        )

    def _rerank_shortlist(self, preferences: PreferenceConfig, shortlist: list[PreRankedPaper]) -> list[RerankedPaper]:
        system_prompt = _ranking_system_prompt()
        user_prompt = _ranking_user_prompt(preferences, shortlist)

        try:
            response = self.provider.process_document(
                content="",
                is_pdf=False,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=min(self.config.max_output_tokens, 4096),
            ).strip()
        except Exception as error:
            raise RankingError(f"Ranking provider call failed: {error}") from error

        payload = _load_ranking_payload(response)
        raw_ranked = payload.get("ranked_papers")
        if not isinstance(raw_ranked, list):
            raise RankingError("Ranking payload must contain a 'ranked_papers' list.")

        shortlist_by_key = {item.paper_key: item for item in shortlist}
        seen_ids: set[str] = set()
        reranked: list[RerankedPaper] = []
        for entry in raw_ranked:
            if not isinstance(entry, dict):
                raise RankingError("Each ranked paper entry must be a JSON object.")

            candidate_id = entry.get("candidate_id")
            if not isinstance(candidate_id, str):
                raise RankingError("Each ranked paper entry must include a string candidate_id.")
            if candidate_id in seen_ids:
                raise RankingError(f"Ranking payload repeated candidate_id '{candidate_id}'.")
            if candidate_id not in shortlist_by_key:
                raise RankingError(f"Ranking payload returned unknown candidate_id '{candidate_id}'.")

            score = entry.get("score")
            if not isinstance(score, (int, float)):
                raise RankingError(f"Ranking payload for '{candidate_id}' is missing a numeric score.")
            rationale = entry.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                raise RankingError(f"Ranking payload for '{candidate_id}' is missing a rationale.")

            item = shortlist_by_key[candidate_id]
            reranked.append(
                RerankedPaper(
                    paper=item.paper,
                    paper_key=item.paper_key,
                    source_id=item.source_id,
                    pre_rank_score=item.pre_rank_score,
                    rerank_score=float(score),
                    rationale=rationale.strip(),
                    best_priority_index=item.best_priority_index,
                    matched_priority_count=item.matched_priority_count,
                    matched_priorities=item.matched_priorities,
                )
            )
            seen_ids.add(candidate_id)

        missing_ids = [item.paper_key for item in shortlist if item.paper_key not in seen_ids]
        if missing_ids:
            raise RankingError(f"Ranking payload omitted candidate_id values: {', '.join(missing_ids)}")

        reranked.sort(key=lambda item: (-item.rerank_score, item.paper.title.casefold()))
        LOGGER.info("LLM reranked %s shortlisted paper(s).", len(reranked))
        return reranked
