"""Tests for V27 component source readiness without economic outputs."""

from __future__ import annotations

from pathlib import Path

from market_lab.futures import moex_v27_forward_component_source as source
from market_lab.futures import v27_forward_component_readiness as readiness


def test_empty_component_root_is_fail_closed(tmp_path: Path) -> None:
    report = readiness.assess(tmp_path)

    assert report["protocol_id"] == "futures_v27_forward_components_v1"
    assert report["valid_market_execution_dates"] == 0
    assert report["valid_market_decision_dates"] == 0
    assert report["valid_macro_FRED_snapshots"] == 0
    assert report["valid_macro_CBR_snapshots"] == 0
    assert report["contains_signal_return_target_prediction_or_pnl"] is False
    assert report["progress"]["paper_economics_may_start"] is False
    assert report["progress"]["annualization_allowed"] is False


def test_price_warmup_does_not_bypass_missing_macro_or_execution() -> None:
    config = source.load_config()

    blocked = readiness.phase_progress(253, 0, 0, 1, config)
    admitted = readiness.phase_progress(253, 1, 1, 1, config)

    assert blocked["price_warmup"]["complete"] == 253
    assert blocked["macro_state_ready"] is False
    assert blocked["paper_economics_may_start"] is False
    assert admitted["paper_economics_may_start"] is True
    assert admitted["annualization_allowed"] is False
