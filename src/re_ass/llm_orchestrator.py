from __future__ import annotations

import logging
from pathlib import Path
import re

from re_ass.models import ArxivPaper, ProcessedPaper, sanitize_note_name
from re_ass.paper_summariser import PaperSummariser, PaperSummariserError
from re_ass.paper_summariser.providers import create_provider
from re_ass.paper_summariser.providers.base import Provider
from re_ass.settings import LlmConfig


LOGGER = logging.getLogger(__name__)
_PROMPT_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")


class LlmCommandError(RuntimeError):
    """Raised when the configured LLM provider returns a failure."""


class LlmOrchestrator:
    def __init__(
        self,
        *,
        config: LlmConfig,
        provider: Provider | None = None,
        paper_summariser: PaperSummariser | None = None,
    ) -> None:
        self.config = config
        self.provider = provider

        if self.config.enabled and self.provider is None:
            self.provider = create_provider(
                self.config.mode,
                self.config.provider,
                config=self.config.provider_config(),
            )

        if paper_summariser is not None:
            self.paper_summariser = paper_summariser
        elif self.provider is not None:
            self.paper_summariser = PaperSummariser(provider=self.provider, config=self.config)
        else:
            self.paper_summariser = None

    def process_paper(self, paper: ArxivPaper, papers_dir: Path) -> ProcessedPaper:
        note_path = self.ensure_paper_note(paper, papers_dir)
        micro_summary = self.generate_micro_summary(paper)
        return ProcessedPaper(
            paper=paper,
            note_name=note_path.stem,
            note_path=note_path,
            micro_summary=micro_summary,
        )

    def ensure_paper_note(self, paper: ArxivPaper, papers_dir: Path) -> Path:
        papers_dir.mkdir(parents=True, exist_ok=True)
        expected_note_path = papers_dir / f"{sanitize_note_name(paper.title)}.md"
        if expected_note_path.exists():
            return expected_note_path

        if self.paper_summariser is not None:
            try:
                summary = self.paper_summariser.summarise_paper(paper)
                expected_note_path.write_text(summary.note_content, encoding="utf-8")
                return expected_note_path
            except PaperSummariserError as error:
                LOGGER.warning("Paper note generation failed for %s: %s", paper.title, error)

        if not self.config.allow_local_paper_note_fallback:
            raise LlmCommandError(f"Unable to create paper note for {paper.title}.")

        self._write_fallback_paper_note(expected_note_path, paper)
        return expected_note_path

    def generate_micro_summary(self, paper: ArxivPaper) -> str:
        if self.provider is not None:
            try:
                response = self._run_text_prompt(
                    "Summarise the following arXiv abstract in 1-2 sentences. Return plain text only.",
                    f"Title: {paper.title}\nAbstract: {paper.summary}",
                    max_tokens=min(self.config.max_output_tokens, 512),
                )
                cleaned = self._clean_summary(response)
                if cleaned:
                    return cleaned
            except LlmCommandError as error:
                LOGGER.warning("Micro-summary generation failed for %s: %s", paper.title, error)

        return self._fallback_micro_summary(paper.summary)

    def generate_weekly_synthesis(self, existing_synthesis: str, papers: list[ProcessedPaper]) -> str:
        if self.provider is not None:
            bullet_summaries = "\n".join(f"- {paper.micro_summary}" for paper in papers)
            try:
                response = self._run_text_prompt(
                    "Update this weekly synthesis incorporating these new papers. Max 100 words. Return plain text only.",
                    f"Current synthesis:\n{existing_synthesis}\n\nNew paper summaries:\n{bullet_summaries}",
                    max_tokens=min(self.config.max_output_tokens, 512),
                )
                cleaned = self._truncate_words(self._clean_summary(response), limit=100)
                if cleaned:
                    return cleaned
            except LlmCommandError as error:
                LOGGER.warning("Weekly synthesis generation failed: %s", error)

        return self._fallback_weekly_synthesis(existing_synthesis, papers)

    def _run_text_prompt(self, system_prompt: str, user_prompt: str, *, max_tokens: int) -> str:
        if self.provider is None:
            raise LlmCommandError("No LLM provider configured.")
        try:
            return self.provider.process_document(
                content="",
                is_pdf=False,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            ).strip()
        except Exception as error:
            raise LlmCommandError(str(error)) from error

    def _write_fallback_paper_note(self, note_path: Path, paper: ArxivPaper) -> None:
        published_date = paper.published.date().isoformat()
        content = (
            f"# {paper.title}\n\n"
            f"- ArXiv: [{paper.arxiv_url}]({paper.arxiv_url})\n"
            f"- Published: {published_date}\n"
            f"- Authors: {', '.join(paper.authors)}\n"
            f"- Categories: {', '.join(paper.categories)}\n\n"
            "## Abstract\n"
            f"{paper.summary}\n\n"
            "## Notes\n"
            "LLM-generated note creation was unavailable, so this fallback note preserves the core metadata.\n"
        )
        note_path.write_text(content, encoding="utf-8")

    def _fallback_micro_summary(self, abstract: str) -> str:
        sentences = [sentence.strip() for sentence in _PROMPT_SPLIT_PATTERN.split(abstract.strip()) if sentence.strip()]
        candidate = " ".join(sentences[:2]) if sentences else abstract.strip()
        return self._truncate_words(candidate, limit=45)

    def _fallback_weekly_synthesis(self, existing_synthesis: str, papers: list[ProcessedPaper]) -> str:
        summaries = [paper.micro_summary.rstrip(".") for paper in papers if paper.micro_summary.strip()]
        if not summaries:
            return self._truncate_words(existing_synthesis.strip(), limit=100)

        if self._is_placeholder_synthesis(existing_synthesis):
            base_text = "This week's notable papers include " + "; ".join(summaries) + "."
        else:
            base_text = existing_synthesis.strip().rstrip(".") + ". New additions include " + "; ".join(summaries) + "."
        return self._truncate_words(base_text, limit=100)

    def _clean_summary(self, text: str) -> str:
        cleaned = text.strip().strip('"').strip("'")
        cleaned = re.sub(r"^\s*[-*]\s*", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    def _truncate_words(self, text: str, *, limit: int) -> str:
        words = text.split()
        if len(words) <= limit:
            return " ".join(words).strip()
        return " ".join(words[:limit]).rstrip(".,;:") + "..."

    def _is_placeholder_synthesis(self, synthesis: str) -> bool:
        normalized = synthesis.casefold()
        return "automatically generated here" in normalized or normalized.startswith("*(")
