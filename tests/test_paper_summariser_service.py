from pathlib import Path

from re_ass.paper_summariser.providers.base import Provider
from re_ass.paper_summariser.service import PaperSummariser, extract_summary_sections
from tests.support import make_paper, make_app_config


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


def test_summarise_source_uses_extracted_text(tmp_path: Path) -> None:
    provider = RecordingProvider(
        {
            "response": (
                "# Agents for Research\n\n"
                "Authors: Doe J., Smith J.\n"
                "Published: March 2026 ([Link](https://arxiv.org/abs/1234.5678))\n\n"
                "## Key Ideas\n"
                "- Important point[^1]\n\n"
                "## References\n"
                '[^1]: "Quoted support" (Abstract, p.1)\n'
            )
        }
    )
    source_path = tmp_path / "1234.5678.pdf"
    source_path.write_bytes(b"%PDF-1.4")

    def input_reader(_path: Path, _provider: Provider, _config):
        return "arXiv: 1234.5678\nExtracted paper text.", None

    summariser = PaperSummariser(
        provider=provider,
        config=make_app_config(tmp_path).llm,
        input_reader=input_reader,
    )

    result = summariser.summarise_source(make_paper(arxiv_id="1234.5678", title="Agents for Research"), source_path)

    assert "## Key Ideas" in result.raw_summary
    assert result.pdf_url == "https://arxiv.org/pdf/1234.5678.pdf"
    assert provider.calls[0]["content"] == "arXiv: 1234.5678\nExtracted paper text."


def test_summarise_source_uses_direct_pdf_when_provider_supports_it(tmp_path: Path) -> None:
    provider = RecordingProvider(
        {
            "supports_direct_pdf": True,
            "response": (
                "# Agents for Research\n\n"
                "Authors: Doe J., Smith J.\n"
                "Published: March 2026 ([Link](https://arxiv.org/abs/1234.5678))\n\n"
                "## Key Ideas\n"
                "- Important point[^1]\n"
            ),
        }
    )
    source_path = tmp_path / "1234.5678.pdf"
    source_path.write_bytes(b"%PDF-1.4 direct pdf")

    def input_reader(_path: Path, _provider: Provider, _config):
        return b"%PDF-1.4 direct pdf", None

    summariser = PaperSummariser(
        provider=provider,
        config=make_app_config(tmp_path).llm,
        input_reader=input_reader,
    )

    summariser.summarise_source(make_paper(arxiv_id="1234.5678", title="Agents for Research"), source_path)

    assert provider.calls[0]["content"] == b"%PDF-1.4 direct pdf"
    assert provider.calls[0]["is_pdf"] is True
    assert "---BEGIN PAPER---" not in str(provider.calls[0]["user_prompt"])


def test_extract_summary_sections_drops_preamble_text() -> None:
    summary = (
        "# Example Paper\n\n"
        "Authors: Jane Doe\n"
        "Published: March 2026\n\n"
        "## Key Ideas\n"
        "- Point one.\n"
    )

    assert extract_summary_sections(summary) == "## Key Ideas\n- Point one.\n"
