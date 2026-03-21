from datetime import datetime, timezone
from pathlib import Path

import pytest

from re_ass.llm_orchestrator import LlmOrchestrator
from re_ass.models import ArxivPaper
from re_ass.paper_summariser import GeneratedPaperSummary, PaperSummariserError
from re_ass.paper_summariser.providers.base import Provider
from re_ass.paper_summariser.service import SourceMetadata
from re_ass.settings import LlmConfig


class FakeProvider(Provider):
    def setup(self):
        self.responses = dict(self.config.get("responses", {}))

    def process_document(self, content, is_pdf, system_prompt, user_prompt, max_tokens=12288):
        del content, is_pdf, system_prompt, max_tokens
        for prefix, response in self.responses.items():
            if user_prompt.startswith(prefix):
                return response
        raise AssertionError(f"Unexpected prompt: {user_prompt}")

    def get_max_context_size(self):
        return 200_000


class FakePaperSummariser:
    def __init__(self, summary: GeneratedPaperSummary | None = None, error: Exception | None = None) -> None:
        self.summary = summary
        self.error = error

    def summarise_paper(self, _paper: ArxivPaper) -> GeneratedPaperSummary:
        if self.error is not None:
            raise self.error
        assert self.summary is not None
        return self.summary


def make_paper() -> ArxivPaper:
    return ArxivPaper(
        title="Agents for Research",
        summary="This paper studies tool-using agents. It compares planning and execution loops.",
        arxiv_url="https://arxiv.org/abs/1234.5678",
        entry_id="https://arxiv.org/abs/1234.5678",
        authors=("Jane Doe", "John Smith"),
        primary_category="cs.AI",
        categories=("cs.AI", "cs.CL"),
        published=datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
        updated=datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
    )


def make_llm_config(tmp_path: Path, *, enabled: bool) -> LlmConfig:
    return LlmConfig(
        enabled=enabled,
        mode="cli",
        provider="claude",
        model=None,
        timeout_seconds=60,
        max_output_tokens=12288,
        temperature=0.2,
        retry_attempts=3,
        allow_local_paper_note_fallback=True,
        prompt_debug_file=tmp_path / "archive" / "prompt.txt",
        download_timeout_seconds=120,
        max_pdf_size_mb=100,
        marker_timeout_seconds=300,
        ollama_base_url="http://localhost:11434",
    )


def test_process_paper_falls_back_when_llm_is_disabled(tmp_path: Path) -> None:
    orchestrator = LlmOrchestrator(config=make_llm_config(tmp_path, enabled=False))

    processed = orchestrator.process_paper(make_paper(), tmp_path)

    assert processed.note_path.exists()
    assert "## Abstract" in processed.note_path.read_text(encoding="utf-8")
    assert processed.micro_summary.startswith("This paper studies tool-using agents.")


def test_process_paper_uses_generated_summary_when_summariser_succeeds(tmp_path: Path) -> None:
    provider = FakeProvider(
        {
            "responses": {
                "Title: Agents for Research\nAbstract:": "Short LLM summary.",
            }
        }
    )
    paper_summariser = FakePaperSummariser(
        summary=GeneratedPaperSummary(
            raw_summary="# Agents for Research\n\nAuthors: Jane Doe, John Smith\nPublished: March 2026 ([Link](https://arxiv.org/abs/1234.5678))\n\n## Key Ideas\n- Important point.\n",
            note_content=(
                "# Agents for Research\n\n"
                "- ArXiv: [https://arxiv.org/abs/1234.5678](https://arxiv.org/abs/1234.5678)\n"
                "- Published: 2026-03-21\n"
                "- Authors: Jane Doe, John Smith\n"
                "- Categories: cs.AI, cs.CL\n\n"
                "## Abstract\n"
                "This paper studies tool-using agents. It compares planning and execution loops.\n\n"
                "## Key Ideas\n"
                "- Important point.\n"
            ),
            source_metadata=SourceMetadata(
                source_type="arxiv",
                identifier="1234.5678",
                canonical_url="https://arxiv.org/abs/1234.5678",
                published_label="March 2026",
                detection_method="filename",
            ),
            pdf_url="https://arxiv.org/pdf/1234.5678.pdf",
        )
    )
    orchestrator = LlmOrchestrator(
        config=make_llm_config(tmp_path, enabled=True),
        provider=provider,
        paper_summariser=paper_summariser,
    )

    processed = orchestrator.process_paper(make_paper(), tmp_path)

    assert processed.note_name == "Agents for Research"
    assert "## Key Ideas" in processed.note_path.read_text(encoding="utf-8")
    assert processed.micro_summary == "Short LLM summary."


def test_process_paper_logs_and_falls_back_when_summariser_fails(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FakeProvider(
        {
            "responses": {
                "Title: Agents for Research\nAbstract:": "Short LLM summary.",
            }
        }
    )
    paper_summariser = FakePaperSummariser(error=PaperSummariserError("marker-pdf timed out"))
    orchestrator = LlmOrchestrator(
        config=make_llm_config(tmp_path, enabled=True),
        provider=provider,
        paper_summariser=paper_summariser,
    )

    processed = orchestrator.process_paper(make_paper(), tmp_path)

    assert processed.note_path.exists()
    assert "Paper note generation failed for Agents for Research" in caplog.text
    assert "marker-pdf timed out" in caplog.text
    assert "## Abstract" in processed.note_path.read_text(encoding="utf-8")
