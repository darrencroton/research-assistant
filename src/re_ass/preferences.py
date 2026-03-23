"""Preferences parsing for re-ass.

Reads user categories and flat or grouped priorities from a Markdown preferences file.
Optional science and methods sections are parsed explicitly when present.
"""

from __future__ import annotations

from pathlib import Path
import re

from re_ass.models import PreferenceConfig


_NUMBERED_ITEM_PATTERN = re.compile(r"^\s*\d+\.\s+(?P<value>.+?)\s*$")
_BULLET_ITEM_PATTERN = re.compile(r"^\s*[-*]\s+(?P<value>.+?)\s*$")
_HEADING_PATTERN = re.compile(r"^\s*#{1,6}\s+(?P<value>.+?)\s*$")


def _section_from_heading(heading: str) -> str:
    normalized = heading.strip().lower()
    if "categor" in normalized:
        return "categories"
    if "priorit" in normalized and "science" in normalized:
        return "science_priorities"
    if "priorit" in normalized and "method" in normalized:
        return "method_priorities"
    if "priorit" in normalized:
        return "priorities"
    return "ignore"


def load_preferences(preferences_path: Path) -> PreferenceConfig:
    """Parse a Markdown preferences file into a PreferenceConfig."""
    try:
        lines = preferences_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"Preferences file not found: {preferences_path}. Run ./scripts/setup.sh or create it from user_preferences/defaults/preferences.md."
        ) from error

    categories: list[str] = []
    priorities: list[str] = []
    science_priorities: list[str] = []
    method_priorities: list[str] = []
    current_section: str | None = None

    for line in lines:
        heading_match = _HEADING_PATTERN.match(line)
        if heading_match:
            current_section = _section_from_heading(heading_match.group("value"))
            continue

        numbered_match = _NUMBERED_ITEM_PATTERN.match(line)
        if numbered_match:
            if current_section in {"categories", "ignore"}:
                continue
            value = numbered_match.group("value").strip()
            priorities.append(value)
            if current_section == "science_priorities":
                science_priorities.append(value)
            elif current_section == "method_priorities":
                method_priorities.append(value)
            continue

        bullet_match = _BULLET_ITEM_PATTERN.match(line)
        if bullet_match and current_section == "categories":
            categories.append(bullet_match.group("value").strip())

    if not categories:
        raise ValueError(
            f"No arXiv categories found in {preferences_path}. Add at least one bullet under a categories heading."
        )
    if not priorities:
        raise ValueError(
            f"No priorities found in {preferences_path}. Add a numbered list under a priorities heading."
        )

    return PreferenceConfig(
        priorities=tuple(priorities),
        categories=tuple(categories),
        science_priorities=tuple(science_priorities),
        method_priorities=tuple(method_priorities),
    )
