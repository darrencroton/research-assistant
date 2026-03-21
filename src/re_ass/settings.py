from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


DEFAULT_WEEKLY_TEMPLATE = """# This Week's ArXiv Overview

## Synthesis
*(A synthesis of this week's papers will be automatically generated here. Max 100 words.)*

---
## Daily Additions
"""

DEFAULT_PREFERENCES_FILE = """# Arxiv Priorities

## Categories
- astro-ph.CO

## Priorities
1. Little red dots
2. black holes and AGN
3. semi-analytic galaxy formation models
"""


@dataclass(frozen=True, slots=True)
class LlmConfig:
    enabled: bool
    mode: str
    provider: str
    model: str | None
    timeout_seconds: int
    max_output_tokens: int
    temperature: float
    retry_attempts: int
    allow_local_paper_note_fallback: bool
    prompt_debug_file: Path
    download_timeout_seconds: int
    max_pdf_size_mb: int
    marker_timeout_seconds: int
    ollama_base_url: str

    def provider_config(self) -> dict[str, object]:
        config: dict[str, object] = {
            "temperature": self.temperature,
            "timeout": self.timeout_seconds,
        }
        if self.model:
            config["model"] = self.model
        if self.provider == "ollama":
            config["base_url"] = self.ollama_base_url
        return config


@dataclass(frozen=True, slots=True)
class AppConfig:
    project_root: Path
    vault_root: Path
    preferences_file: Path
    weekly_note_file: Path
    daily_dir: Path
    papers_dir: Path
    weekly_archive_dir: Path
    templates_dir: Path
    weekly_template_file: Path
    max_papers: int
    fetch_window_hours: int
    fallback_window_hours: int
    arxiv_max_results: int
    default_categories: tuple[str, ...]
    llm: LlmConfig


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_path(base_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (base_path / candidate).resolve()


def _infer_legacy_provider(llm_data: dict[str, object]) -> tuple[str, str]:
    raw_prefix = llm_data.get("command_prefix")
    if not isinstance(raw_prefix, list) or not raw_prefix:
        return "cli", "claude"
    command = str(raw_prefix[0]).strip().lower()
    if command in {"claude", "codex", "gemini", "copilot"}:
        return "cli", command
    return "cli", "claude"


def load_config(config_path: Path | None = None, project_root: Path | None = None) -> AppConfig:
    root = (project_root or _default_project_root()).resolve()
    candidate = Path(config_path).expanduser().resolve() if config_path else (root / "re_ass.toml").resolve()
    data: dict[str, object] = {}

    if candidate.exists():
        with candidate.open("rb") as handle:
            data = tomllib.load(handle)
        if project_root is None:
            root = candidate.parent.resolve()

    vault_data = data.get("vault", {})
    arxiv_data = data.get("arxiv", {})
    llm_data = data.get("llm", {})
    if not isinstance(vault_data, dict) or not isinstance(arxiv_data, dict) or not isinstance(llm_data, dict):
        raise ValueError("Invalid configuration format in re_ass.toml.")

    vault_root = _resolve_path(root, str(vault_data.get("root", "obsidian_vault")))
    templates_dir = _resolve_path(vault_root, str(vault_data.get("templates_dir", "Templates")))
    default_categories = tuple(str(category) for category in arxiv_data.get("default_categories", ["astro-ph.CO"]))
    if not default_categories:
        raise ValueError("arxiv.default_categories must contain at least one category.")

    legacy_mode, legacy_provider = _infer_legacy_provider(llm_data)
    mode = str(llm_data.get("mode", legacy_mode)).strip().lower()
    provider = str(llm_data.get("provider", legacy_provider)).strip().lower()
    raw_model = llm_data.get("model")
    model = str(raw_model).strip() if raw_model not in (None, "") else None

    llm = LlmConfig(
        enabled=bool(llm_data.get("enabled", False)),
        mode=mode,
        provider=provider,
        model=model,
        timeout_seconds=int(llm_data.get("timeout_seconds", 900)),
        max_output_tokens=int(llm_data.get("max_output_tokens", 12288)),
        temperature=float(llm_data.get("temperature", 0.2)),
        retry_attempts=int(llm_data.get("retry_attempts", 3)),
        allow_local_paper_note_fallback=bool(llm_data.get("allow_local_paper_note_fallback", True)),
        prompt_debug_file=_resolve_path(
            root,
            str(llm_data.get("prompt_debug_file", "archive/paper_summariser/prompt.txt")),
        ),
        download_timeout_seconds=int(llm_data.get("download_timeout_seconds", 120)),
        max_pdf_size_mb=int(llm_data.get("max_pdf_size_mb", 100)),
        marker_timeout_seconds=int(llm_data.get("marker_timeout_seconds", 300)),
        ollama_base_url=str(llm_data.get("ollama_base_url", "http://localhost:11434")),
    )

    return AppConfig(
        project_root=root,
        vault_root=vault_root,
        preferences_file=_resolve_path(vault_root, str(vault_data.get("preferences_file", "re-ass-preferences.md"))),
        weekly_note_file=_resolve_path(vault_root, str(vault_data.get("weekly_note_file", "this-weeks-arxiv-papers.md"))),
        daily_dir=_resolve_path(vault_root, str(vault_data.get("daily_dir", "Daily"))),
        papers_dir=_resolve_path(vault_root, str(vault_data.get("papers_dir", "Papers"))),
        weekly_archive_dir=_resolve_path(vault_root, str(vault_data.get("weekly_archive_dir", "Weekly_Archive"))),
        templates_dir=templates_dir,
        weekly_template_file=_resolve_path(templates_dir, str(vault_data.get("weekly_template_file", "weekly-arxiv-template.md"))),
        max_papers=int(arxiv_data.get("max_papers", 3)),
        fetch_window_hours=int(arxiv_data.get("fetch_window_hours", 24)),
        fallback_window_hours=int(arxiv_data.get("fallback_window_hours", 168)),
        arxiv_max_results=int(arxiv_data.get("max_results", 200)),
        default_categories=default_categories,
        llm=llm,
    )
