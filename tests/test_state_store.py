import json
from pathlib import Path

from re_ass.state_store import StateStore
from tests.support import make_app_config


def test_state_store_tracks_completed_paper_keys(tmp_path: Path) -> None:
    store = StateStore(make_app_config(tmp_path))
    store.bootstrap()

    store.save_paper_record(
        paper_key="arxiv:2603.15732",
        source_id="2603.15732",
        title="Example Paper",
        published="2026-03-21T12:00:00+00:00",
        filename_stem="Doe - 2026 - Example Paper [arXiv 2603.15732]",
        status="completed",
    )

    assert store.is_completed("arxiv:2603.15732") is True
    assert store.completed_paper_keys() == {"arxiv:2603.15732"}


def test_state_store_preserves_first_completed_timestamp(tmp_path: Path) -> None:
    store = StateStore(make_app_config(tmp_path))
    store.bootstrap()

    store.save_paper_record(
        paper_key="arxiv:2603.15732",
        source_id="2603.15732",
        title="Example Paper",
        published="2026-03-21T12:00:00+00:00",
        filename_stem="Doe - 2026 - Example Paper [arXiv 2603.15732]",
        status="completed",
    )
    first_completed_at = store.load_paper_record("arxiv:2603.15732")["first_completed_at"]

    store.save_paper_record(
        paper_key="arxiv:2603.15732",
        source_id="2603.15732",
        title="Example Paper",
        published="2026-03-21T12:00:00+00:00",
        filename_stem="Doe - 2026 - Example Paper [arXiv 2603.15732]",
        status="completed",
    )

    assert store.load_paper_record("arxiv:2603.15732")["first_completed_at"] == first_completed_at


def test_state_store_saves_run_summary_json(tmp_path: Path) -> None:
    store = StateStore(make_app_config(tmp_path))
    store.bootstrap()

    path = store.save_run_summary("2026-03-22", {"run_date": "2026-03-22", "completed_papers": 1})

    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["completed_papers"] == 1


def test_state_store_returns_latest_successful_run_end(tmp_path: Path) -> None:
    store = StateStore(make_app_config(tmp_path))
    store.bootstrap()

    store.save_run_summary(
        "2026-03-21",
        {
            "run_date": "2026-03-21",
            "interval_end": "2026-03-21T10:00:00+00:00",
            "fatal_error": "boom",
        },
    )
    store.save_run_summary(
        "2026-03-22",
        {
            "run_date": "2026-03-22",
            "interval_end": "2026-03-22T11:00:00+00:00",
            "fatal_error": None,
        },
    )

    assert store.latest_successful_run_end().isoformat() == "2026-03-22T11:00:00+00:00"
