from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from pathlib import Path


_INVALID_NOTE_CHARACTERS = '/\\:*?"<>|#[]'


def sanitize_note_name(title: str) -> str:
    translation_table = str.maketrans({character: " " for character in _INVALID_NOTE_CHARACTERS})
    normalized = title.translate(translation_table).replace("]]", " ").replace("[[", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    return normalized or "Untitled Paper"


@dataclass(frozen=True, slots=True)
class PreferenceConfig:
    priorities: tuple[str, ...]
    categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArxivPaper:
    title: str
    summary: str
    arxiv_url: str
    entry_id: str
    authors: tuple[str, ...]
    primary_category: str
    categories: tuple[str, ...]
    published: datetime
    updated: datetime | None = None

    @property
    def searchable_text(self) -> str:
        parts = [
            self.title,
            self.summary,
            " ".join(self.authors),
            self.primary_category,
            " ".join(self.categories),
        ]
        return " ".join(part for part in parts if part).lower()


@dataclass(frozen=True, slots=True)
class ProcessedPaper:
    paper: ArxivPaper
    note_name: str
    note_path: Path
    micro_summary: str

    @property
    def wikilink(self) -> str:
        if self.note_name == self.paper.title:
            return f"[[{self.note_name}]]"
        return f"[[{self.note_name}|{self.paper.title}]]"
