"""Tests for paired forward LQDT source readiness."""

from __future__ import annotations

import json
from pathlib import Path

from market_lab.futures import forward_lqdt_idle_cash_readiness as readiness


def _snapshot(root: Path, name: str, source_date: str, stage: str, retrieved: str) -> Path:
    path = root / name
    path.mkdir()
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "source_date": source_date,
                "stage": stage,
                "retrieved_at_utc": retrieved,
                "status": "complete_valid",
            }
        ),
        encoding="utf-8-sig",
    )
    return path


def test_assess_counts_only_ordered_audited_pairs(tmp_path: Path, monkeypatch) -> None:
    decision = _snapshot(
        tmp_path,
        "snapshot_20260902_decision",
        "2026-09-02",
        "decision",
        "2026-09-02T12:49:00Z",
    )
    fill = _snapshot(
        tmp_path,
        "snapshot_20260902_fill",
        "2026-09-02",
        "fill",
        "2026-09-02T12:59:00Z",
    )
    _snapshot(
        tmp_path,
        "snapshot_20260903_decision",
        "2026-09-03",
        "decision",
        "2026-09-03T12:49:00Z",
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
    assert report["paper_economics_allowed"] is False
