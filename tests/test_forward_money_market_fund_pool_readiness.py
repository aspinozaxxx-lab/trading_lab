"""Tests for forward money-market fund pool readiness."""

from __future__ import annotations

from pathlib import Path

from market_lab.futures import forward_money_market_fund_pool_readiness as readiness
from market_lab.futures import moex_forward_money_market_fund_pool_source as source
from tests.test_moex_forward_money_market_fund_pool_source import _Client


def test_empty_readiness_is_discovery_and_forbids_ranking(tmp_path: Path) -> None:
    report = readiness.assess(tmp_path)

    assert report["complete_valid_pair_count"] == 0
    assert report["progress"]["current_phase"] == "discovery"
    assert report["fund_ranking_allowed"] is False
    assert report["paper_economics_allowed"] is False


def test_complete_pair_counts_only_when_fill_is_later(tmp_path: Path) -> None:
    source.collect(
        "decision", tmp_path, client=_Client(), retrieved_at="2026-09-02T13:00:00Z"
    )
    source.collect(
        "fill", tmp_path, client=_Client(), retrieved_at="2026-09-02T13:10:00Z"
    )

    report = readiness.assess(tmp_path)

    assert report["complete_valid_pair_count"] == 1
    assert report["invalid_snapshot_count"] == 0
    assert report["fill_not_after_decision_dates"] == []
