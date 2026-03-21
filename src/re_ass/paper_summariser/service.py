"""Upstream-derived paper summariser core adapted for re-ass."""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from datetime import timezone
import logging
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from re_ass.models import ArxivPaper
from re_ass.settings import LlmConfig

from .providers.base import Provider


# Required for marker-pdf on Apple Silicon — must be set before PyTorch is imported.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
load_dotenv()

LOGGER = logging.getLogger(__name__)
_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "project_knowledge"
_SOURCE_SCAN_CHAR_LIMIT = 4000
_marker_models = None

ARXIV_FILENAME_RE = re.compile(
    r"(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[A-Za-z.-]+/\d{7}(?:v\d+)?)"
)
ARXIV_TEXT_RE = re.compile(
    r"(?:arxiv\s*:\s*|arxiv\.org/(?:abs|pdf)/)"
    r"(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[A-Za-z.-]+/\d{7}(?:v\d+)?)",
    re.IGNORECASE,
)
ARXIV_NEW_STYLE_RE = re.compile(
    r"^(?P<yy>\d{2})(?P<mm>0[1-9]|1[0-2])\.\d{4,5}(?:v\d+)?$"
)
DOI_URL_RE = re.compile(
    r"https?://(?:dx\.)?doi\.org/(?P<doi>10\.\d{4,9}/[-._;()/:A-Z0-9]+)",
    re.IGNORECASE,
)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)

MONTH_NAMES = {
    1: "January",
    2: "February",
    3: "March",
    4: "April",
    5: "May",
    6: "June",
    7: "July",
    8: "August",
    9: "September",
    10: "October",
    11: "November",
    12: "December",
}


class PaperSummariserError(RuntimeError):
    """Raised when the adapted paper summariser cannot produce a note."""


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Structured source metadata that can guide or repair summary top matter."""

    source_type: str | None = None
    identifier: str | None = None
    canonical_url: str | None = None
    published_label: str | None = None
    detection_method: str | None = None


@dataclass(frozen=True, slots=True)
class GeneratedPaperSummary:
    raw_summary: str
    note_content: str
    source_metadata: SourceMetadata
    pdf_url: str


class PaperSummariser:
    def __init__(
        self,
        *,
        provider: Provider,
        config: LlmConfig,
        downloader: callable | None = None,
        input_reader: callable | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.downloader = downloader or self._download_arxiv_pdf
        self.input_reader = input_reader or read_input_file

    def summarise_paper(self, paper: ArxivPaper) -> GeneratedPaperSummary:
        keywords, template = read_project_knowledge()

        with tempfile.TemporaryDirectory(prefix="re-ass-paper-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            source_path = self.downloader(paper, temp_dir)
            pdf_url = self._build_pdf_url(paper.arxiv_url)

            content, error = self.input_reader(source_path, self.provider, self.config)
            if error:
                raise PaperSummariserError(error)
            if content is None:
                raise PaperSummariserError(f"No content returned for {paper.title}.")

            is_pdf = source_path.suffix.lower() == ".pdf"
            if is_pdf and self.provider.supports_direct_pdf():
                paper_text = ""
            elif isinstance(content, bytes):
                paper_text = content.decode("utf-8", errors="ignore")
            else:
                paper_text = content

            source_metadata = extract_source_metadata(source_path, paper_text)
            system_prompt = create_system_prompt(keywords)
            user_prompt = create_user_prompt(
                paper_text,
                template,
                source_metadata=source_metadata,
                is_pdf=is_pdf,
            )
            write_debug_prompt(self.config.prompt_debug_file, system_prompt, user_prompt)

            summary = call_llm_with_retry(
                self.provider,
                content,
                is_pdf,
                system_prompt,
                user_prompt,
                max_tokens=self.config.max_output_tokens,
                max_retries=self.config.retry_attempts,
            )
            summary = strip_preamble(summary)
            summary = enforce_source_metadata(summary, source_metadata)
            validate_summary(summary, source_metadata=source_metadata)
            note_content = render_obsidian_note(paper, summary)

        return GeneratedPaperSummary(
            raw_summary=summary,
            note_content=note_content,
            source_metadata=source_metadata,
            pdf_url=pdf_url,
        )

    def _download_arxiv_pdf(self, paper: ArxivPaper, destination_dir: Path) -> Path:
        destination_dir.mkdir(parents=True, exist_ok=True)
        pdf_url = self._build_pdf_url(paper.arxiv_url)
        identifier = self._extract_arxiv_identifier(paper.arxiv_url) or "paper"
        destination = destination_dir / f"{identifier}.pdf"
        request = Request(pdf_url, headers={"User-Agent": "re-ass/0.1"})

        try:
            with urlopen(request, timeout=self.config.download_timeout_seconds) as response:
                payload = response.read(self.config.max_pdf_size_mb * 1024 * 1024 + 1)
        except HTTPError as error:
            raise PaperSummariserError(f"Downloading {pdf_url} returned HTTP {error.code}.") from error
        except URLError as error:
            raise PaperSummariserError(f"Downloading {pdf_url} failed: {error.reason}.") from error
        except OSError as error:
            raise PaperSummariserError(f"Downloading {pdf_url} failed: {error}.") from error

        if not payload:
            raise PaperSummariserError(f"Downloading {pdf_url} returned no content.")
        if len(payload) > self.config.max_pdf_size_mb * 1024 * 1024:
            raise PaperSummariserError(
                f"Downloaded PDF exceeds {self.config.max_pdf_size_mb}MB limit."
            )

        destination.write_bytes(payload)
        LOGGER.info("Downloaded %s to %s.", pdf_url, destination)
        return destination

    def _build_pdf_url(self, paper_url: str) -> str:
        parsed = urlparse(paper_url)
        if not parsed.netloc.casefold().endswith("arxiv.org"):
            raise PaperSummariserError(f"Unsupported paper URL for PDF fetch: {paper_url}")

        path = parsed.path.rstrip("/")
        if path.startswith("/abs/"):
            identifier = path.removeprefix("/abs/")
        elif path.startswith("/pdf/"):
            identifier = path.removeprefix("/pdf/")
        else:
            raise PaperSummariserError(f"Unsupported arXiv URL format: {paper_url}")

        identifier = identifier.removesuffix(".pdf")
        if not identifier:
            raise PaperSummariserError(f"Could not determine an arXiv identifier from {paper_url}")
        return f"https://arxiv.org/pdf/{identifier}.pdf"

    def _extract_arxiv_identifier(self, paper_url: str) -> str | None:
        parsed = urlparse(paper_url)
        path = parsed.path.rstrip("/")
        if path.startswith("/abs/"):
            return path.removeprefix("/abs/")
        if path.startswith("/pdf/"):
            return path.removeprefix("/pdf/").removesuffix(".pdf")
        return None


def read_project_knowledge() -> tuple[str, str]:
    """Read keywords and template files needed for prompts."""
    keywords_path = _KNOWLEDGE_DIR / "astronomy-keywords.txt"
    template_path = _KNOWLEDGE_DIR / "paper-summary-template.md"
    return (
        keywords_path.read_text(encoding="utf-8"),
        template_path.read_text(encoding="utf-8"),
    )


def _get_marker_models():
    """Lazy-load and cache marker-pdf models. Only called when text extraction is needed."""
    global _marker_models
    if _marker_models is None:
        from marker.models import create_model_dict

        LOGGER.info("Loading marker-pdf models (one-time initialisation)...")
        _marker_models = create_model_dict()
        LOGGER.info("marker-pdf models loaded.")
    return _marker_models


def read_input_file(
    file_path: Path,
    provider: Provider,
    config: LlmConfig,
) -> tuple[bytes | str | None, str | None]:
    """Read content from a local PDF or text file using the upstream extraction path."""
    try:
        file_size = file_path.stat().st_size
        if file_size > config.max_pdf_size_mb * 1024 * 1024:
            return None, f"File too large: {file_size / 1024 / 1024:.1f}MB (max {config.max_pdf_size_mb}MB)"

        file_suffix = file_path.suffix.lower()
        if file_suffix == ".pdf":
            if provider.supports_direct_pdf():
                LOGGER.info("Reading PDF binary for direct upload: %s", file_path.name)
                return file_path.read_bytes(), None

            LOGGER.info("Extracting text from PDF using marker-pdf: %s", file_path.name)
            from marker.config.parser import ConfigParser
            from marker.output import text_from_rendered

            marker_config = {
                "output_format": "markdown",
                "disable_image_extraction": True,
                "use_llm": False,
            }
            config_parser = ConfigParser(marker_config)
            converter_cls = config_parser.get_converter_cls()
            converter = converter_cls(
                config=config_parser.generate_config_dict(),
                artifact_dict=_get_marker_models(),
                processor_list=config_parser.get_processors(),
                renderer=config_parser.get_renderer(),
                llm_service=config_parser.get_llm_service(),
            )

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(converter, str(file_path))
                try:
                    rendered = future.result(timeout=config.marker_timeout_seconds)
                except concurrent.futures.TimeoutError as error:
                    raise RuntimeError(
                        f"marker-pdf timed out after {config.marker_timeout_seconds}s "
                        f"processing {file_path.name}"
                    ) from error

            text, _, _ = text_from_rendered(rendered)
            LOGGER.info("Extracted ~%s words from PDF", len(text.split()))
            return text, None

        if file_suffix == ".txt":
            LOGGER.info("Reading text file: %s", file_path.name)
            return file_path.read_text(encoding="utf-8"), None

        return None, f"Unsupported file type: {file_path.suffix}"
    except Exception as error:  # pragma: no cover - exercised by integration paths
        LOGGER.error("Error reading input file %s: %s", file_path.name, error, exc_info=True)
        return None, f"File read/processing error: {error}"


def _trim_trailing_punctuation(value: str) -> str:
    return value.rstrip(").,;:]")


def _extract_arxiv_id_from_filename(input_path: Path) -> str | None:
    stem = input_path.stem.strip()
    if not stem:
        return None
    if full_match := ARXIV_FILENAME_RE.fullmatch(stem):
        return full_match.group("id")
    if search_match := ARXIV_FILENAME_RE.search(stem):
        return search_match.group("id")
    return None


def _extract_arxiv_id_from_text(paper_text: str) -> str | None:
    if not paper_text:
        return None
    header_window = paper_text[:_SOURCE_SCAN_CHAR_LIMIT]
    if match := ARXIV_TEXT_RE.search(header_window):
        return match.group("id")
    return None


def _extract_doi_from_text(paper_text: str) -> str | None:
    if not paper_text:
        return None
    header_window = paper_text[:_SOURCE_SCAN_CHAR_LIMIT]
    if url_match := DOI_URL_RE.search(header_window):
        return _trim_trailing_punctuation(url_match.group("doi"))
    if doi_match := DOI_RE.search(header_window):
        return _trim_trailing_punctuation(doi_match.group(0))
    return None


def _published_label_from_arxiv_id(arxiv_id: str | None) -> str | None:
    if not arxiv_id:
        return None
    if match := ARXIV_NEW_STYLE_RE.match(arxiv_id):
        year = 2000 + int(match.group("yy"))
        month = MONTH_NAMES[int(match.group("mm"))]
        return f"{month} {year}"
    return None


def _canonical_arxiv_url(arxiv_id: str | None) -> str | None:
    if not arxiv_id:
        return None
    versionless_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)
    return f"https://arxiv.org/abs/{versionless_id}"


def extract_source_metadata(input_path: Path, paper_text: str) -> SourceMetadata:
    if arxiv_id := _extract_arxiv_id_from_filename(input_path):
        return SourceMetadata(
            source_type="arxiv",
            identifier=arxiv_id,
            canonical_url=_canonical_arxiv_url(arxiv_id),
            published_label=_published_label_from_arxiv_id(arxiv_id),
            detection_method="filename",
        )
    if arxiv_id := _extract_arxiv_id_from_text(paper_text):
        return SourceMetadata(
            source_type="arxiv",
            identifier=arxiv_id,
            canonical_url=_canonical_arxiv_url(arxiv_id),
            published_label=_published_label_from_arxiv_id(arxiv_id),
            detection_method="paper_text",
        )
    if doi := _extract_doi_from_text(paper_text):
        return SourceMetadata(
            source_type="doi",
            identifier=doi,
            canonical_url=f"https://doi.org/{doi}",
            detection_method="paper_text",
        )
    return SourceMetadata()


def _extract_existing_published_text(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("Published:"):
        stripped = stripped[len("Published:") :].strip()
    return re.sub(r"\s*\(?\[[^\]]+\]\([^)]+\)\)?\s*$", "", stripped).strip()


def build_published_line(existing_line: str, source_metadata: SourceMetadata) -> str:
    published_text = source_metadata.published_label or _extract_existing_published_text(existing_line)
    if not published_text:
        return existing_line
    if source_metadata.canonical_url:
        return f"Published: {published_text} ([Link]({source_metadata.canonical_url}))"
    return f"Published: {published_text}"


def enforce_source_metadata(summary_content: str, source_metadata: SourceMetadata) -> str:
    if not (source_metadata.canonical_url or source_metadata.published_label):
        return summary_content

    lines = summary_content.split("\n")
    authors_index = None
    published_index = None
    for index, line in enumerate(lines[:12]):
        stripped = line.strip()
        if authors_index is None and stripped.startswith("Authors:"):
            authors_index = index
        if published_index is None and stripped.startswith("Published:"):
            published_index = index

    if published_index is not None:
        replacement = build_published_line(lines[published_index], source_metadata)
        if replacement and replacement != lines[published_index]:
            lines[published_index] = replacement
        return "\n".join(lines)

    replacement = build_published_line("", source_metadata)
    if replacement and authors_index is not None:
        lines.insert(authors_index + 1, replacement)
        return "\n".join(lines)
    return summary_content


def create_system_prompt(keywords: str) -> str:
    return (
        "<role>\n"
        "You are an esteemed professor of astrophysics at Harvard University "
        "specializing in analyzing research papers. Your are an expert in \n"
        "identifying key scientific results and their significance.\n"
        "</role>\n\n"
        "<rules>\n"
        "1. Write only in UK English using clear technical language\n"
        "2. Use markdown formatting throughout\n"
        "3. Use LaTeX for all mathematical expressions\n"
        "4. Only include content from the provided paper\n"
        "5. Every bullet point must have a supporting footnote\n"
        "6. Footnotes must contain EXACT quotes - never paraphrase\n"
        "7. Always enclose footnote quotes in quotation marks\n"
        "8. Include page/section reference for every quote\n"
        "9. Use bold for key terms on first mention\n"
        "10. Use italics for emphasis and paper names\n"
        "11. If you cannot find an exact supporting quote, do not make the statement\n"
        "12. ALWAYS include a Glossary section with a table of technical terms\n"
        "</rules>\n\n"
        "<knowledgeBase>\n"
        f"Available astronomy keywords by category:\n{keywords}\n"
        "</knowledgeBase>"
    )


def create_user_prompt(
    paper_text: str,
    template: str,
    *,
    source_metadata: SourceMetadata | None = None,
    is_pdf: bool = False,
) -> str:
    del is_pdf  # The upstream API keeps this argument for call-site clarity.

    base_prompt = (
        "<task>\n"
        "Summarize this research paper following these EXACT requirements:\n\n"
        "<format>\n"
        "1. THE VERY FIRST LINE must be the paper title as '# Title'\n"
        "2. NO TEXT before the title - not even a greeting\n"
        "3. Below title, exactly one blank line, then:\n"
        "   - Line starting 'Authors: ' with FULL author list\n"
        "   - Line starting 'Published: ' with month, year, and link\n"
        "   - One blank line before starting sections\n"
        "4. Include EVERY author (surname and initials with period, comma separated)\n"
        "5. Never truncate author list with 'et al.'\n"
        "6. MUST include publication month and year\n"
        "7. Follow the exact section order specified\n"
        "</format>\n\n"
        "<template>\n"
        f"Use this exact structure:\n{template}\n"
        "</template>\n\n"
        "<tags>\n"
        "The Tags section must have two parts:\n"
        "1. First line: Hashtags for telescopes, surveys, datasets, models (proper nouns only)\n"
        "2. Second line: Science area hashtags (use ONLY provided keywords, only the best ones)\n"
        "</tags>\n"
        "</task>\n\n"
    )

    if source_metadata and source_metadata.canonical_url:
        base_prompt += (
            "<source_metadata>\n"
            f"Detected source identifier: {source_metadata.source_type}:{source_metadata.identifier}\n"
            f"Canonical paper link: {source_metadata.canonical_url}\n"
        )
        if source_metadata.published_label:
            base_prompt += f"Published line date: {source_metadata.published_label}\n"
        base_prompt += "You MUST use this exact link in the Published line.\n"
        if source_metadata.published_label:
            base_prompt += "You MUST use this exact month and year in the Published line.\n"
        base_prompt += "</source_metadata>\n\n"

    if paper_text:
        base_prompt += (
            "<input>\n"
            "Paper to summarize:\n\n"
            f"---BEGIN PAPER---\n{paper_text}\n---END PAPER---\n"
            "</input>"
        )
    return base_prompt


def write_debug_prompt(prompt_path: Path, system_prompt: str, user_prompt: str) -> None:
    try:
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        full_prompt = f"SYSTEM PROMPT\n{system_prompt}\n\n---\n\nUSER PROMPT\n{user_prompt}"
        prompt_path.write_text(full_prompt, encoding="utf-8")
        LOGGER.info("Debug prompt written to %s", prompt_path)
    except Exception as error:  # pragma: no cover - debug-path best effort
        LOGGER.warning("Could not write debug prompt file: %s", error)


def _is_retryable_llm_error(error: Exception) -> bool:
    message = str(error).lower()
    non_retryable_markers = (
        "credit balance is too low",
        "api key",
        "authentication",
        "logged out",
        "login required",
        "not found on path",
    )
    return not any(marker in message for marker in non_retryable_markers)


def call_llm_with_retry(
    provider: Provider,
    content: bytes | str,
    is_pdf: bool,
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int,
    max_retries: int,
) -> str:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            LOGGER.info("Attempt %s/%s calling LLM...", attempt + 1, max_retries)
            summary = provider.process_document(
                content=content,
                is_pdf=is_pdf,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens,
            )
            if not summary or not summary.strip():
                raise ValueError("LLM returned empty or whitespace-only response")
            LOGGER.info("LLM call successful (received ~%s chars)", len(summary))
            return summary
        except Exception as error:
            last_error = error
            LOGGER.error(
                "Attempt %s failed — %s: %s",
                attempt + 1,
                provider.__class__.__name__,
                error,
            )
            if not _is_retryable_llm_error(error) or attempt == max_retries - 1:
                break
            wait_time = 2 ** (attempt + 1)
            LOGGER.info("Waiting %ss before retry...", wait_time)
            time.sleep(wait_time)

    raise PaperSummariserError(str(last_error or "Unknown LLM failure"))


def strip_preamble(summary_content: str) -> str:
    lines = summary_content.split("\n")
    title_index = -1
    for index, line in enumerate(lines):
        if line.strip().startswith("# "):
            title_index = index
            break
    if title_index >= 0:
        return "\n".join(lines[title_index:])
    LOGGER.warning("Could not find title heading ('# ') to strip preamble.")
    return summary_content


def validate_summary(summary_content: str, *, source_metadata: SourceMetadata | None = None) -> None:
    lines = [line.strip() for line in summary_content.split("\n") if line.strip()]
    if not lines:
        LOGGER.warning("VALIDATION WARNING: Summary content is empty.")
        return

    start_with_title = lines[0].startswith("# ")
    published_line = next((line for line in lines[:6] if line.startswith("Published:")), "")
    year_found = any(re.search(r"\b(19|20)\d{2}\b", line) for line in lines[:5])
    author_complete = not any(
        "et al" in line.lower() for line in lines[:5] if line.startswith("Authors:")
    )
    published_has_link = bool(re.search(r"\[[^\]]+\]\(https?://[^)]+\)", published_line))
    expected_link_ok = (
        source_metadata.canonical_url in published_line
        if source_metadata and source_metadata.canonical_url
        else published_has_link
    )
    expected_date_ok = (
        source_metadata.published_label in published_line
        if source_metadata and source_metadata.published_label
        else year_found
    )

    LOGGER.info("Validation results:")
    LOGGER.info("  Starts with title: %s", start_with_title)
    LOGGER.info("  Has Published line: %s", bool(published_line))
    LOGGER.info("  Year found: %s", year_found)
    LOGGER.info("  Author list complete: %s", author_complete)
    if source_metadata and source_metadata.canonical_url:
        LOGGER.info("  Expected paper link present: %s", expected_link_ok)
    elif published_line:
        LOGGER.info("  Published line has link: %s", published_has_link)
    if source_metadata and source_metadata.published_label:
        LOGGER.info("  Expected publication date present: %s", expected_date_ok)

    if not start_with_title:
        LOGGER.warning("VALIDATION WARNING: Summary does not start with title heading '# '")
    if not published_line:
        LOGGER.warning("VALIDATION WARNING: Missing 'Published:' line near top of summary")
    if not year_found:
        LOGGER.warning("VALIDATION WARNING: No year found near top of summary")
    if source_metadata and source_metadata.published_label and not expected_date_ok:
        LOGGER.warning(
            "VALIDATION WARNING: Published line does not include expected month/year '%s'",
            source_metadata.published_label,
        )
    if source_metadata and source_metadata.canonical_url and not expected_link_ok:
        LOGGER.warning(
            "VALIDATION WARNING: Published line missing expected canonical link '%s'",
            source_metadata.canonical_url,
        )
    if not author_complete:
        LOGGER.warning("VALIDATION WARNING: Author list might be truncated ('et al.' found)")


def render_obsidian_note(paper: ArxivPaper, summary_content: str) -> str:
    summary_sections = extract_summary_sections(summary_content)
    published_date = paper.published.astimezone(timezone.utc).date().isoformat()
    return (
        f"# {paper.title}\n\n"
        f"- ArXiv: [{paper.arxiv_url}]({paper.arxiv_url})\n"
        f"- Published: {published_date}\n"
        f"- Authors: {', '.join(paper.authors)}\n"
        f"- Categories: {', '.join(paper.categories)}\n\n"
        "## Abstract\n"
        f"{paper.summary}\n\n"
        f"{summary_sections}\n"
    )


def extract_summary_sections(summary_content: str) -> str:
    lines = summary_content.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith("## "):
            return "\n".join(lines[index:]).strip() + "\n"
    return summary_content.strip() + "\n"
