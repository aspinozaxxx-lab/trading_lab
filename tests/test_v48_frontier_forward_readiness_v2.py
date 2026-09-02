"""Tests for V48 readiness over componentized V27 sources."""

from __future__ import annotations

from pathlib import Path

from market_lab.futures import v48_frontier_forward_readiness_v2 as subject


def test_component_correction_preserves_fixed_frontier_economics() -> None:
    config = subject.load_config()

    assert config["protocol_id"] == "v48_frontier_forward_component_correction_v1"
    assert config["live_trading_allowed"] is False
    assert config["source_correction"]["economic_hypothesis_changed"] is False
    assert config["source_correction"]["V48_mode_or_parameter_changed"] is False
    assert config["causal_admission"]["future_macro_may_repair_past_decision"] is False


def test_empty_component_sources_cannot_start_paper_economics(tmp_path: Path) -> None:
    option_root = tmp_path / "option"
    component_root = tmp_path / "components"
    option_root.mkdir()
    component_root.mkdir()

    report = subject.assess(option_root, component_root)

    assert report["fixed_mode"]["name"] == "frontier"
    assert report["fixed_mode"]["V39_mapped_target_multiplier"] == 1.5
    assert report["valid_option_weekly_levels"] == 0
    assert report["valid_market_decision_dates"] == 0
    assert report["valid_macro_FRED_snapshots"] == 0
    assert report["progress"]["paper_economics_may_start"] is False
    assert report["progress"]["cagr_reporting_allowed"] is False
    assert report["contains_signal_return_target_prediction_or_pnl"] is False
    assert report["live_trading_allowed"] is False

