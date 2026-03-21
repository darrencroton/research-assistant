from datetime import datetime, timezone
from pathlib import Path

from re_ass.models import ArxivPaper
from re_ass.paper_summariser.providers.base import Provider
from re_ass.paper_summariser.service import PaperSummariser
from re_ass.settings import LlmConfig


class RecordingProvider(Provider):
    def setup(self):
        self.calls: list[dict[str, object]] = []
        self._supports_direct_pdf = bool(self.config.get("supports_direct_pdf", False))
        self.response = str(self.config["response"])

    def supports_direct_pdf(self):
        return self._supports_direct_pdf

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

    def get_max_context_size(self):
        return 200_000


def make_llm_config(tmp_path: Path) -> LlmConfig:
    return LlmConfig(
        enabled=True,
        mode="cli",
        provider="claude",
        model=None,
        timeout_seconds=60,
        max_output_tokens=2048,
        temperature=0.2,
        retry_attempts=2,
        allow_local_paper_note_fallback=True,
        prompt_debug_file=tmp_path / "archive" / "prompt.txt",
        download_timeout_seconds=120,
        max_pdf_size_mb=20,
        marker_timeout_seconds=300,
        ollama_base_url="http://localhost:11434",
    )


def make_paper() -> ArxivPaper:
    return ArxivPaper(
        title="Agents for Research",
        summary="This paper studies tool-using agents.",
        arxiv_url="https://arxiv.org/abs/1234.5678",
        entry_id="https://arxiv.org/abs/1234.5678",
        authors=("Jane Doe", "John Smith"),
        primary_category="cs.AI",
        categories=("cs.AI", "cs.CL"),
        published=datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
        updated=datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
    )


def test_summarise_paper_uses_extracted_text_and_renders_obsidian_note(tmp_path: Path) -> None:
    provider = RecordingProvider(
        {
            "response": (
                "# Agents for Research\n\n"
                "Authors: Doe J., Smith J.\n"
                "Published: March 2026 ([Link](https://example.com/wrong))\n\n"
                "## Key Ideas\n"
                "- Important point[^1]\n\n"
                "## References\n"
                '[^1]: "Quoted support" (Abstract, p.1)\n'
            )
        }
    )

    def downloader(_paper: ArxivPaper, destination_dir: Path) -> Path:
        path = destination_dir / "1234.5678.pdf"
        path.write_bytes(b"%PDF-1.4")
        return path

    def input_reader(_path: Path, _provider: Provider, _config: LlmConfig):
        return "arXiv: 1234.5678\nExtracted paper text.", None

    summariser = PaperSummariser(
        provider=provider,
        config=make_llm_config(tmp_path),
        downloader=downloader,
        input_reader=input_reader,
    )

    result = summariser.summarise_paper(make_paper())

    assert "https://arxiv.org/abs/1234.5678" in result.raw_summary
    assert "## Abstract" in result.note_content
    assert "## Key Ideas" in result.note_content
    assert provider.calls[0]["content"] == "arXiv: 1234.5678\nExtracted paper text."


def test_summarise_paper_uses_direct_pdf_when_provider_supports_it(tmp_path: Path) -> None:
    provider = RecordingProvider(
        {
            "supports_direct_pdf": True,
            "response": (
                "# Agents for Research\n\n"
                "Authors: Doe J., Smith J.\n"
                "Published: March 2026 ([Link](https://arxiv.org/abs/1234.5678))\n\n"
                "## Key Ideas\n"
                "- Important point[^1]\n\n"
                "## References\n"
                '[^1]: "Quoted support" (Abstract, p.1)\n'
            ),
        }
    )

    def downloader(_paper: ArxivPaper, destination_dir: Path) -> Path:
        path = destination_dir / "1234.5678.pdf"
        path.write_bytes(b"%PDF-1.4 direct pdf")
        return path

    def input_reader(_path: Path, _provider: Provider, _config: LlmConfig):
        return b"%PDF-1.4 direct pdf", None

    summariser = PaperSummariser(
        provider=provider,
        config=make_llm_config(tmp_path),
        downloader=downloader,
        input_reader=input_reader,
    )

    summariser.summarise_paper(make_paper())

    assert provider.calls[0]["content"] == b"%PDF-1.4 direct pdf"
    assert provider.calls[0]["is_pdf"] is True
    assert "---BEGIN PAPER---" not in str(provider.calls[0]["user_prompt"])
