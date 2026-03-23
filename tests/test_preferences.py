"""Tests for the preferences module."""

from pathlib import Path

import pytest

from re_ass.preferences import load_preferences


def test_load_preferences_parses_categories_and_priorities(tmp_path: Path) -> None:
    preferences_file = tmp_path / "preferences.md"
    preferences_file.write_text(
        "# Arxiv Priorities\n\n"
        "## Categories\n"
        "- cs.AI\n"
        "- cs.CL\n\n"
        "## Priorities\n"
        "1. Agents\n"
        "2. RAG\n",
        encoding="utf-8",
    )

    preferences = load_preferences(preferences_file)

    assert preferences.categories == ("cs.AI", "cs.CL")
    assert preferences.priorities == ("Agents", "RAG")


def test_load_preferences_requires_categories(tmp_path: Path) -> None:
    preferences_file = tmp_path / "preferences.md"
    preferences_file.write_text(
        "# Arxiv Priorities\n"
        "\n"
        "## Priorities\n"
        "1. Agents\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="No arXiv categories found"):
        load_preferences(preferences_file)


def test_load_preferences_ignores_non_category_bullets(tmp_path: Path) -> None:
    preferences_file = tmp_path / "preferences.md"
    preferences_file.write_text(
        "# Arxiv Priorities\n\n"
        "## Categories\n"
        "- cs.AI\n\n"
        "## Notes\n"
        "- Free-form bullets should not matter\n\n"
        "## Priorities\n"
        "1. Agents\n",
        encoding="utf-8",
    )

    preferences = load_preferences(preferences_file)

    assert preferences.categories == ("cs.AI",)
    assert preferences.priorities == ("Agents",)


def test_load_preferences_parses_science_and_method_sections(tmp_path: Path) -> None:
    preferences_file = tmp_path / "preferences.md"
    preferences_file.write_text(
        "# Arxiv Priorities\n\n"
        "## Categories\n"
        "- astro-ph.CO\n\n"
        "## Priorities - Science\n"
        "1. Little red dots\n"
        "2. Galaxy environments\n\n"
        "## Priorities - Methods\n"
        "1. Semi-analytic models\n"
        "2. Large surveys\n",
        encoding="utf-8",
    )

    preferences = load_preferences(preferences_file)

    assert preferences.categories == ("astro-ph.CO",)
    assert preferences.priorities == (
        "Little red dots",
        "Galaxy environments",
        "Semi-analytic models",
        "Large surveys",
    )
    assert preferences.science_priorities == ("Little red dots", "Galaxy environments")
    assert preferences.method_priorities == ("Semi-analytic models", "Large surveys")


def test_load_preferences_requires_priorities(tmp_path: Path) -> None:
    preferences_file = tmp_path / "preferences.md"
    preferences_file.write_text("# Empty\n\n## Categories\n- cs.AI\n", encoding="utf-8")

    with pytest.raises(ValueError, match="No priorities found"):
        load_preferences(preferences_file)


def test_load_preferences_requires_existing_file(tmp_path: Path) -> None:
    preferences_file = tmp_path / "missing.md"

    with pytest.raises(FileNotFoundError, match="Preferences file not found"):
        load_preferences(preferences_file)
