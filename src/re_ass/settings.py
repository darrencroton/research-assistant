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
    llm_enabled: bool
    llm_command_prefix: tuple[str, ...]
    llm_timeout_seconds: int
    allow_local_paper_note_fallback: bool


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_path(base_path: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (base_path / candidate).resolve()


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

    command_prefix = tuple(str(part) for part in llm_data.get("command_prefix", ["claude", "-p"]))
    if not command_prefix:
        raise ValueError("llm.command_prefix must contain at least one command segment.")

    default_categories = tuple(str(category) for category in arxiv_data.get("default_categories", ["astro-ph.CO"]))
    if not default_categories:
        raise ValueError("arxiv.default_categories must contain at least one category.")

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
        llm_enabled=bool(llm_data.get("enabled", False)),
        llm_command_prefix=command_prefix,
        llm_timeout_seconds=int(llm_data.get("timeout_seconds", 900)),
        allow_local_paper_note_fallback=bool(llm_data.get("allow_local_paper_note_fallback", True)),
    )
