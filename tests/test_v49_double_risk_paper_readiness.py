"""Tests for the independently sealed V49 double-risk paper arm."""

from __future__ import annotations

from pathlib import Path

from market_lab.futures import v49_double_risk_paper_readiness as subject


def test_config_pins_exactly_one_unchanged_arm() -> None:
    config = subject.load_config()

    assert config["fixed_arm"]["name"] == "double_risk"
    assert config["fixed_arm"]["V39_mapped_target_multiplier"] == 2.0
    assert config["fixed_arm"]["maximum_gross_notional_multiple"] == 4.0
    assert config["fixed_arm"]["V39_signs_zeros_windows_and_quantiles_unchanged"] is True
    assert all(value == 0 for value in config["paper_boundary"]["eligible_counts_at_seal"].values())
    assert config["live_trading_allowed"] is False


def test_empty_postseal_sources_cannot_start_economics(tmp_path: Path) -> None:
    option_root = tmp_path / "options"
    component_root = tmp_path / "components"
    option_root.mkdir()
    component_root.mkdir()

    report = subject.assess(option_root, component_root)

    assert report["postseal_valid_option_weekly_levels"] == 0
    assert report["postseal_valid_market_decision_dates"] == 0
    assert report["progress"]["paper_economics_may_start"] is False
    assert report["progress"]["cagr_reporting_allowed"] is False
    assert report["contains_signal_return_target_prediction_or_pnl"] is False
    assert report["live_trading_allowed"] is False
