"""Tests for V27 forward validation readiness accounting."""

from __future__ import annotations

import json
from pathlib import Path

from market_lab.futures import v27_forward_validation_readiness as readiness


def _manifest(snapshot: Path, kind: str, source_date: str) -> None:
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text(
        json.dumps(
            {
                "snapshot_kind": kind,
                "counts": {"source_dates": [source_date], "market_rows": 8, "macro_rows": 3},
                "retrieved_at_utc": f"{source_date}T20:45:00+00:00",
            }
        ),
        encoding="utf-8-sig",
    )


def test_phase_requires_252_warmup_then_504_evaluation_sessions() -> None:
    config = readiness.source.load_config()

    warmup = readiness.phase_progress(251, 251, config)
    evaluation = readiness.phase_progress(252, 252, config)
    finished = readiness.phase_progress(756, 756, config)

    assert warmup["current_phase"] == "signal_warmup"
    assert warmup["paper_economics_may_start"] is False
    assert evaluation["current_phase"] == "unseen_evaluation"
    assert evaluation["paper_economics_may_start"] is True
    assert finished["current_phase"] == "independent_review"
    assert finished["evaluation_complete"] is True
    assert finished["live_trading_allowed"] is False


def test_assess_counts_only_valid_unique_kind_dates(tmp_path: Path, monkeypatch) -> None:
    decision = tmp_path / "snapshot_decision_001"
    execution = tmp_path / "snapshot_execution_001"
    duplicate = tmp_path / "snapshot_decision_002"
    invalid = tmp_path / "snapshot_invalid"
    _manifest(decision, "decision_eod", "2026-09-02")
    _manifest(execution, "execution_observation", "2026-09-02")
    _manifest(duplicate, "decision_eod", "2026-09-02")
    _manifest(invalid, "decision_eod", "2026-09-03")

    monkeypatch.setattr(
        readiness.source,
        "audit",
        lambda snapshot: {"exact": snapshot != invalid},
    )
    report = readiness.assess(tmp_path)

    assert report["valid_unique_decision_date_count"] == 1
    assert report["valid_unique_execution_date_count"] == 1
    assert report["paired_same_date_count"] == 1
    assert report["invalid_snapshot_count"] == 1
    assert report["duplicate_valid_kind_dates"] == {
        "decision_eod:2026-09-02": ["snapshot_decision_001", "snapshot_decision_002"]
    }
    assert report["progress"]["remaining_to_first_paper_decision"] == 251
