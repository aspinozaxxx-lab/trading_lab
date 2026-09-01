"""Tests for forward option snapshot protocol readiness."""

from __future__ import annotations

import json
from pathlib import Path

from market_lab.futures import forward_option_readiness as readiness


def _manifest(snapshot: Path, source_date: str, rows: int = 100) -> None:
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text(
        json.dumps(
            {
                "counts": {"source_dates": [source_date], "rows": rows},
                "retrieved_at_utc": f"{source_date}T20:00:00+00:00",
            }
        ),
        encoding="utf-8-sig",
    )


def test_phase_progress_enforces_discovery_calibration_evaluation_order() -> None:
    minimums = {
        "discovery_snapshots": 60,
        "calibration_snapshots": 20,
        "unseen_evaluation_snapshots": 40,
    }

    discovery = readiness.phase_progress(59, minimums)
    calibration = readiness.phase_progress(60, minimums)
    evaluation = readiness.phase_progress(80, minimums)
    finished = readiness.phase_progress(120, minimums)

    assert discovery["current_phase"] == "discovery"
    assert discovery["economic_protocol_may_be_sealed"] is False
    assert calibration["current_phase"] == "calibration"
    assert calibration["economic_protocol_may_be_sealed"] is True
    assert evaluation["current_phase"] == "unseen_evaluation"
    assert finished["current_phase"] == "independent_review"
    assert finished["unseen_evaluation_complete"] is True
    assert finished["live_trading_allowed"] is False


def test_assess_counts_only_valid_unique_dates(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "snapshot_001"
    duplicate = tmp_path / "snapshot_002"
    invalid = tmp_path / "snapshot_003"
    _manifest(first, "2026-09-01")
    _manifest(duplicate, "2026-09-01")
    _manifest(invalid, "2026-09-02")

    def fake_audit(snapshot: Path) -> dict[str, bool]:
        return {"exact": snapshot != invalid}

    monkeypatch.setattr(readiness.source, "audit", fake_audit)
    report = readiness.assess(tmp_path)

    assert report["snapshot_count"] == 3
    assert report["valid_snapshot_count"] == 2
    assert report["invalid_snapshot_count"] == 1
    assert report["valid_unique_source_date_count"] == 1
    assert report["duplicate_valid_source_dates"] == {
        "2026-09-01": ["snapshot_001", "snapshot_002"]
    }
    assert report["progress"]["remaining_to_economic_protocol_seal"] == 59
