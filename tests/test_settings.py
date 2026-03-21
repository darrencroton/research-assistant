from pathlib import Path

from re_ass.settings import load_config


def test_load_config_parses_explicit_llm_provider_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "re_ass.toml"
    config_path.write_text(
        "[vault]\nroot = 'vault'\n\n"
        "[arxiv]\ndefault_categories = ['astro-ph.CO']\n\n"
        "[llm]\n"
        "enabled = true\n"
        "mode = 'api'\n"
        "provider = 'openai'\n"
        "model = 'gpt-5.2'\n"
        "timeout_seconds = 1200\n"
        "max_output_tokens = 4096\n"
        "temperature = 0.1\n"
        "retry_attempts = 4\n"
        "allow_local_paper_note_fallback = false\n"
        "prompt_debug_file = 'archive/prompts/last.txt'\n"
        "download_timeout_seconds = 45\n"
        "max_pdf_size_mb = 20\n"
        "marker_timeout_seconds = 180\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.llm.enabled is True
    assert config.llm.mode == "api"
    assert config.llm.provider == "openai"
    assert config.llm.model == "gpt-5.2"
    assert config.llm.timeout_seconds == 1200
    assert config.llm.max_output_tokens == 4096
    assert config.llm.temperature == 0.1
    assert config.llm.retry_attempts == 4
    assert config.llm.allow_local_paper_note_fallback is False
    assert config.llm.prompt_debug_file == (tmp_path / "archive" / "prompts" / "last.txt").resolve()


def test_load_config_infers_legacy_cli_provider_from_command_prefix(tmp_path: Path) -> None:
    config_path = tmp_path / "re_ass.toml"
    config_path.write_text(
        "[vault]\nroot = 'vault'\n\n"
        "[arxiv]\ndefault_categories = ['astro-ph.CO']\n\n"
        "[llm]\n"
        "enabled = true\n"
        "command_prefix = ['codex', 'exec']\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.llm.mode == "cli"
    assert config.llm.provider == "codex"
