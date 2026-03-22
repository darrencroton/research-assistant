import json

import pytest

from re_ass.ranking import PaperRanker, RankingError, pre_rank_papers
from tests.support import make_app_config, make_paper


class RecordingProvider:
    def __init__(self, response: str) -> None:
        self.response = response
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
        return self.response


def test_pre_rank_papers_prefers_high_priority_matches_then_recency() -> None:
    papers = [
        make_paper(arxiv_id="2603.40001", title="Agents Planning", summary="Planning systems"),
        make_paper(arxiv_id="2603.40002", title="RAG Benchmarks", summary="Retrieval methods"),
        make_paper(arxiv_id="2603.40003", title="Agents and RAG", summary="Joint systems"),
        make_paper(arxiv_id="2603.40004", title="Unrelated Vision", summary="Image generation"),
    ]

    ranked = pre_rank_papers(papers, ("Agents", "RAG"))

    assert [paper.paper.title for paper in ranked] == [
        "Agents and RAG",
        "Agents Planning",
        "RAG Benchmarks",
        "Unrelated Vision",
    ]


def test_paper_ranker_uses_full_preferences_document_in_rerank_prompt(tmp_path) -> None:
    paper = make_paper(arxiv_id="2603.40011", title="Semantic Agents")
    provider = RecordingProvider(
        json.dumps(
            {
                "ranked_papers": [
                    {"candidate_id": "arxiv:2603.40011", "score": 96, "rationale": "Best matches the document."}
                ]
            }
        )
    )
    config = make_app_config(tmp_path).llm
    ranker = PaperRanker(provider=provider, config=config, shortlist_size=12)
    preferences = type(
        "Preferences",
        (),
        {
            "priorities": ("Agents",),
            "categories": ("cs.AI",),
            "raw_text": "# Priorities\n1. Agents\n2. Tool use\n",
        },
    )()

    selection = ranker.select_top_papers(preferences, [paper], max_papers=1)

    assert [item.title for item in selection.selected_papers] == ["Semantic Agents"]
    assert "# Priorities" in provider.calls[0]["user_prompt"]
    assert "Tool use" in provider.calls[0]["user_prompt"]


def test_paper_ranker_selects_top_papers_from_llm_rerank_not_prerank_order(tmp_path) -> None:
    papers = [
        make_paper(arxiv_id="2603.40021", title="Strong Lexical Match", summary="Agents agents agents"),
        make_paper(arxiv_id="2603.40022", title="Semantic Best Match", summary="General reasoning"),
        make_paper(arxiv_id="2603.40023", title="Third Choice", summary="Useful tooling"),
    ]
    provider = RecordingProvider(
        json.dumps(
            {
                "ranked_papers": [
                    {"candidate_id": "arxiv:2603.40022", "score": 99, "rationale": "Best overall fit."},
                    {"candidate_id": "arxiv:2603.40023", "score": 88, "rationale": "Second-best fit."},
                    {"candidate_id": "arxiv:2603.40021", "score": 40, "rationale": "Mostly lexical overlap."},
                ]
            }
        )
    )
    ranker = PaperRanker(provider=provider, config=make_app_config(tmp_path).llm, shortlist_size=12)
    preferences = type(
        "Preferences",
        (),
        {
            "priorities": ("Agents", "Tool use"),
            "categories": ("cs.AI",),
            "raw_text": "# Priorities\n1. Agents with strong evaluation\n2. Tool use\n",
        },
    )()

    selection = ranker.select_top_papers(preferences, papers, max_papers=2)

    assert [paper.title for paper in selection.selected_papers] == ["Semantic Best Match", "Third Choice"]


def test_paper_ranker_rejects_incomplete_rerank_payload(tmp_path) -> None:
    paper = make_paper(arxiv_id="2603.40031", title="Only Paper")
    provider = RecordingProvider(json.dumps({"ranked_papers": []}))
    ranker = PaperRanker(provider=provider, config=make_app_config(tmp_path).llm, shortlist_size=12)
    preferences = type(
        "Preferences",
        (),
        {"priorities": ("Agents",), "categories": ("cs.AI",), "raw_text": "1. Agents"},
    )()

    with pytest.raises(RankingError, match="omitted"):
        ranker.select_top_papers(preferences, [paper], max_papers=1)
