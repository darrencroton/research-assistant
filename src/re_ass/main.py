"""CLI entry point for re-ass."""

from __future__ import annotations

import argparse
from datetime import date
import logging
from pathlib import Path
import sys

from re_ass.settings import AppConfig, load_config


LOGGER = logging.getLogger(__name__)


class _MaxLevelFilter(logging.Filter):
    """Allow records up to and including a maximum level."""

    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(description="Fetch, rank, and summarise daily arXiv papers.")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to a settings TOML configuration file.",
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=None,
        help="Run the workflow for a specific ISO date (YYYY-MM-DD).",
    )
    return parser


def configure_logging(config: AppConfig | None = None) -> None:
    """Set up console and optional file logging."""
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.addFilter(_MaxLevelFilter(logging.INFO))

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)

    handlers: list[logging.Handler] = [stdout_handler, stderr_handler]

    if config is not None:
        config.logs_root.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(config.last_run_log_file, mode="w", encoding="utf-8")
        handlers.append(file_handler)

        history_handler = logging.FileHandler(config.history_log_file, mode="a", encoding="utf-8")
        handlers.append(history_handler)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _run_mode_label(*, backfill: bool) -> str:
    return "backfill" if backfill else "automatic"


def _append_file_log_separator() -> None:
    for handler in logging.getLogger().handlers:
        if not isinstance(handler, logging.FileHandler):
            continue
        handler.acquire()
        try:
            if handler.stream is None:
                continue
            handler.stream.write("\n")
            handler.flush()
        finally:
            handler.release()


def _log_run_started(*, invocation_date: date, backfill: bool) -> None:
    LOGGER.info(
        "===== re-ass run started (%s, invocation date %s) =====",
        _run_mode_label(backfill=backfill),
        invocation_date.isoformat(),
    )


def _log_run_finished(*, invocation_date: date, backfill: bool, exit_code: int) -> None:
    LOGGER.info(
        "===== re-ass run finished (%s, invocation date %s, exit code %s) =====",
        _run_mode_label(backfill=backfill),
        invocation_date.isoformat(),
        exit_code,
    )
    _append_file_log_separator()


def cli(argv: list[str] | None = None) -> int:
    """Parse arguments, load config, and hand off to the pipeline."""
    parser = build_parser()
    args = parser.parse_args(argv)
    backfill = args.date is not None
    invocation_date = args.date or date.today()

    config = load_config(args.config)

    configure_logging(config)
    _log_run_started(invocation_date=invocation_date, backfill=backfill)

    from re_ass.pipeline import run

    try:
        exit_code = run(config, args.date, backfill=backfill)
    except Exception:
        LOGGER.exception(
            "re-ass run crashed unexpectedly before a normal exit (%s, invocation date %s).",
            _run_mode_label(backfill=backfill),
            invocation_date.isoformat(),
        )
        _append_file_log_separator()
        raise

    _log_run_finished(invocation_date=invocation_date, backfill=backfill, exit_code=exit_code)
    return exit_code
