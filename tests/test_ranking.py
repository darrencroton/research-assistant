import json

import pytest

from re_ass.models import PreferenceConfig
from re_ass.ranking import PaperRanker, RankingError
from tests.support import make_app_config, make_paper


class RecordingProvider:
    def __init__(self, response: str | list[str]) -> None:
        self.responses = [response] if isinstance(response, str) else list(response)
        self.calls = []

    def process_document(self, content, is_pdf, system_prompt, user_prompt, max_tokens=12288):
        self.calls.append(
            {
                "content": content,
                "is_pdf": is_pdf,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "max_tokens": max_tokens,
            }
        )
        if not self.responses:
            raise AssertionError("provider was called more times than expected")
        return self.responses.pop(0)


def _preferences(*priorities: str) -> PreferenceConfig:
    return PreferenceConfig(
        priorities=priorities,
        categories=("astro-ph.GA",),
    )


def test_ranker_uses_ordered_priorities_and_compact_candidate_payload(tmp_path) -> None:
    paper = make_paper(
        arxiv_id="2603.40011",
        title="Semantic Agents",
        summary="Agentic workflows for tool use.",
        authors=("Author One", "Author Two"),
    )
    provider = RecordingProvider(
        json.dumps(
            {
                "ranked_papers": [
                    {"candidate_id": "arxiv:2603.40011", "score": 96, "rationale": "Best match to the highest priorities."}
                ]
            }
        )
    )
    ranker = PaperRanker(
        provider=provider,
        config=make_app_config(tmp_path).llm,
        max_papers=3,
        min_selection_score=80.0,
    )

    selection = ranker.rank_papers(_preferences("Agents", "Tool use"), [paper])

    assert [item.paper.title for item in selection.selected] == ["Semantic Agents"]
    prompt = provider.calls[0]["user_prompt"]
    assert "1. Agents" in prompt
    assert "2. Tool use" in prompt
    assert "Semantic Agents" in prompt
    assert "Agentic workflows for tool use." in prompt
    assert "Author One" not in prompt
    assert "Matching multiple priorities is a bonus, not a requirement." in prompt


def test_ranker_requires_science_and_method_matches_when_sections_are_present(tmp_path) -> None:
    papers = [
        make_paper(arxiv_id="2603.40015", title="Dual Match"),
        make_paper(arxiv_id="2603.40016", title="Science Only"),
    ]
    provider = RecordingProvider(
        json.dumps(
            {
                "ranked_papers": [
                    {
                        "candidate_id": "arxiv:2603.40015",
                        "score": 91,
                        "science_match": True,
                        "method_match": True,
                        "rationale": "Matches the target science and method priorities directly.",
                    },
                    {
                        "candidate_id": "arxiv:2603.40016",
                        "score": 95,
                        "science_match": True,
                        "method_match": False,
                        "rationale": "Strong science topic but lacks the requested method angle.",
                    },
                ]
            }
        )
    )
    ranker = PaperRanker(
        provider=provider,
        config=make_app_config(tmp_path).llm,
        max_papers=5,
        min_selection_score=80.0,
    )
    preferences = PreferenceConfig(
        priorities=("Little red dots", "Semi-analytic models"),
        categories=("astro-ph.GA",),
        science_priorities=("Little red dots",),
        method_priorities=("Semi-analytic models",),
    )

    selection = ranker.rank_papers(preferences, papers)

    assert [paper.title for paper in selection.selected_papers] == ["Dual Match"]
    prompt = provider.calls[0]["user_prompt"]
    assert "<science_priorities>" in prompt
    assert "<method_priorities>" in prompt
    assert "A paper should only receive a strong score if both science_match and method_match are true." in prompt
    assert '"science_match":true' in prompt


def test_ranker_filters_by_threshold_and_cap(tmp_path) -> None:
    papers = [
        make_paper(arxiv_id="2603.40021", title="Strong Fit"),
        make_paper(arxiv_id="2603.40022", title="Second Fit"),
        make_paper(arxiv_id="2603.40023", title="Weak Fit"),
    ]
    provider = RecordingProvider(
        json.dumps(
            {
                "ranked_papers": [
                    {"candidate_id": "arxiv:2603.40021", "score": 94, "rationale": "Strongest match."},
                    {"candidate_id": "arxiv:2603.40022", "score": 81, "rationale": "Solid secondary match."},
                    {"candidate_id": "arxiv:2603.40023", "score": 61, "rationale": "Only a borderline fit."},
                ]
            }
        )
    )
    ranker = PaperRanker(
        provider=provider,
        config=make_app_config(tmp_path).llm,
        max_papers=2,
        min_selection_score=80.0,
    )

    selection = ranker.rank_papers(_preferences("Agents"), papers)

    assert [paper.title for paper in selection.selected_papers] == ["Strong Fit", "Second Fit"]
    assert [item.paper.title for item in selection.ranked] == ["Strong Fit", "Second Fit", "Weak Fit"]


def test_ranker_sorts_by_score_when_provider_returns_unsorted_payload(tmp_path) -> None:
    papers = [
        make_paper(arxiv_id="2603.40031", title="Lower Score"),
        make_paper(arxiv_id="2603.40032", title="Higher Score"),
    ]
    provider = RecordingProvider(
        json.dumps(
            {
                "ranked_papers": [
                    {"candidate_id": "arxiv:2603.40031", "score": 60, "rationale": "Lower relevance."},
                    {"candidate_id": "arxiv:2603.40032", "score": 95, "rationale": "Highest relevance."},
                ]
            }
        )
    )
    ranker = PaperRanker(
        provider=provider,
        config=make_app_config(tmp_path).llm,
        max_papers=1,
        min_selection_score=80.0,
    )

    selection = ranker.rank_papers(_preferences("Agents"), papers)

    assert [item.paper.title for item in selection.ranked] == ["Higher Score", "Lower Score"]
    assert [paper.title for paper in selection.selected_papers] == ["Higher Score"]


def test_ranker_repairs_invalid_payload_once(tmp_path) -> None:
    papers = [
        make_paper(arxiv_id="2603.40041", title="Paper One"),
        make_paper(arxiv_id="2603.40042", title="Paper Two"),
    ]
    provider = RecordingProvider(
        [
            json.dumps(
                {
                    "ranked_papers": [
                        {"candidate_id": "arxiv:2603.49999", "score": 97, "rationale": "Unknown id."},
                        {"candidate_id": "arxiv:2603.40042", "score": 75, "rationale": "Known id."},
                    ]
                }
            ),
            json.dumps(
                {
                    "ranked_papers": [
                        {"candidate_id": "arxiv:2603.40041", "score": 97, "rationale": "Best match."},
                        {"candidate_id": "arxiv:2603.40042", "score": 75, "rationale": "Secondary match."},
                    ]
                }
            ),
        ]
    )
    ranker = PaperRanker(
        provider=provider,
        config=make_app_config(tmp_path).llm,
        max_papers=2,
        min_selection_score=70.0,
    )

    selection = ranker.rank_papers(_preferences("Agents"), papers)

    assert [paper.title for paper in selection.selected_papers] == ["Paper One", "Paper Two"]
    assert len(provider.calls) == 2
    assert "validation_error" in provider.calls[1]["user_prompt"]


def test_ranker_requires_full_ranked_list_after_repair(tmp_path) -> None:
    paper = make_paper(arxiv_id="2603.40051", title="Only Paper")
    provider = RecordingProvider(
        [
            json.dumps({"ranked_papers": []}),
            json.dumps({"ranked_papers": []}),
        ]
    )
    ranker = PaperRanker(
        provider=provider,
        config=make_app_config(tmp_path).llm,
        max_papers=1,
        min_selection_score=80.0,
    )

    with pytest.raises(RankingError, match="remained invalid after repair attempt"):
        ranker.rank_papers(_preferences("Agents"), [paper])
    assert len(provider.calls) == 2
