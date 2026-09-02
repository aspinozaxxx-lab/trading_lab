"""Tests for paired forward cash-carry source readiness."""

from __future__ import annotations

import json
from pathlib import Path

from market_lab.futures import forward_stock_futures_cash_carry_readiness as readiness


def _snapshot(root: Path, name: str, source_date: str, stage: str, retrieved_at: str) -> Path:
    path = root / name
    path.mkdir()
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "source_date": source_date,
                "stage": stage,
                "retrieved_at_utc": retrieved_at,
                "status": "complete_valid",
            }
        ),
        encoding="utf-8-sig",
    )
    return path


def test_phase_progress_matches_sealed_60_20_60() -> None:
    report = readiness.phase_progress(
        61,
        {
            "discovery_complete_decision_fill_pairs": 60,
            "calibration_pairs_after_discovery": 20,
            "unseen_evaluation_pairs_after_calibration": 60,
        },
    )

    assert report["current_phase"] == "calibration"
    assert report["discovery"]["complete"] == 60
    assert report["calibration"]["complete"] == 1
    assert report["annualization_allowed"] is False


def test_assess_counts_only_ordered_audited_pairs(tmp_path: Path, monkeypatch) -> None:
    decision = _snapshot(
        tmp_path,
        "snapshot_20260902_decision",
        "2026-09-02",
        "decision",
        "2026-09-02T12:50:00+00:00",
    )
    fill = _snapshot(
        tmp_path,
        "snapshot_20260902_fill",
        "2026-09-02",
        "fill",
        "2026-09-02T13:00:00+00:00",
    )
    _snapshot(
        tmp_path,
        "snapshot_20260903_decision",
        "2026-09-03",
        "decision",
        "2026-09-03T12:50:00+00:00",
    )
    monkeypatch.setattr(
        readiness.source,
        "audit",
        lambda snapshot: {"exact": snapshot in {decision, fill}},
    )

    report = readiness.assess(tmp_path)

    assert report["complete_valid_pair_count"] == 1
    assert report["invalid_snapshot_count"] == 1
    assert report["progress"]["remaining_to_economic_protocol_seal"] == 59
    assert report["paper_signal_or_pnl_allowed"] is False
