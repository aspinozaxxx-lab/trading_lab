"""Tests for forward CNY relative-value readiness accounting."""

from __future__ import annotations

import json
from pathlib import Path

from market_lab.futures import forward_cny_relative_value_readiness as readiness


def _manifest(snapshot: Path, quote_date: str) -> None:
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text(
        json.dumps(
            {
                "counts": {"quote_dates": [quote_date], "quote_rows": 3, "funding_rows": 1},
                "retrieved_at_utc": f"{quote_date}T15:30:00+00:00",
            }
        ),
        encoding="utf-8-sig",
    )


def test_minimums_translate_sealed_cny_phase_names() -> None:
    translated = readiness.minimums(readiness.source.load_config())

    assert translated == {
        "discovery_snapshots": 40,
        "calibration_snapshots": 20,
        "unseen_evaluation_snapshots": 60,
    }


def test_assess_counts_only_audited_unique_quote_dates(
    tmp_path: Path, monkeypatch
) -> None:
    first = tmp_path / "snapshot_001"
    duplicate = tmp_path / "snapshot_002"
    invalid = tmp_path / "snapshot_003"
    _manifest(first, "2026-09-02")
    _manifest(duplicate, "2026-09-02")
    _manifest(invalid, "2026-09-03")

    monkeypatch.setattr(
        readiness.source,
        "audit",
        lambda snapshot: {"exact": snapshot != invalid},
    )
    report = readiness.assess(tmp_path)

    assert report["valid_snapshot_count"] == 2
    assert report["invalid_snapshot_count"] == 1
    assert report["valid_unique_quote_date_count"] == 1
    assert report["duplicate_valid_quote_dates"] == {
        "2026-09-02": ["snapshot_001", "snapshot_002"]
    }
    assert report["progress"]["remaining_to_economic_protocol_seal"] == 39
