from pathlib import Path

import pytest

from re_ass.config_manager import load_preferences


def test_load_preferences_parses_categories_and_priorities(tmp_path: Path) -> None:
    preferences_file = tmp_path / "re-ass-preferences.md"
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

    preferences = load_preferences(preferences_file, ("cs.LG",))

    assert preferences.categories == ("cs.AI", "cs.CL")
    assert preferences.priorities == ("Agents", "RAG")


def test_load_preferences_uses_default_categories_when_missing(tmp_path: Path) -> None:
    preferences_file = tmp_path / "re-ass-preferences.md"
    preferences_file.write_text(
        "# Arxiv Priorities\n"
        "1. Agents\n"
        "2. Tool Use\n",
        encoding="utf-8",
    )

    preferences = load_preferences(preferences_file, ("cs.AI", "cs.CL"))

    assert preferences.categories == ("cs.AI", "cs.CL")
    assert preferences.priorities == ("Agents", "Tool Use")


def test_load_preferences_requires_priorities(tmp_path: Path) -> None:
    preferences_file = tmp_path / "re-ass-preferences.md"
    preferences_file.write_text("# Empty\n\n## Categories\n- cs.AI\n", encoding="utf-8")

    with pytest.raises(ValueError, match="No priorities found"):
        load_preferences(preferences_file, ("cs.AI",))
