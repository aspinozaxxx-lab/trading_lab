"""Tests for the sealed V48 frontier forward readiness gate."""

from __future__ import annotations

from pathlib import Path

from market_lab.futures import v48_frontier_forward_readiness as subject


def test_protocol_pins_the_single_historical_pass_before_forward_outcomes() -> None:
    config = subject.load_config()

    assert config["protocol_id"] == "v48_frontier_forward_validation_v1"
    assert config["live_trading_allowed"] is False
    assert config["fixed_mode"] == {
        "name": "frontier",
        "V39_mapped_target_multiplier": 1.5,
        "maximum_gross_notional_multiple": 3.0,
        "initial_margin_buffer_multiplier": 2.0,
        "maximum_prior_official_volume_participation": 0.01,
        "broad_carry_cash_fraction": 0.0,
        "exact_integer_contracts": True,
        "zero_target_and_direction_preserved": True,
        "selection_after_forward_outcome": "forbidden",
    }


def test_empty_sources_remain_source_only_and_fail_closed(tmp_path: Path) -> None:
    option_root = tmp_path / "option"
    futures_root = tmp_path / "futures"
    option_root.mkdir()
    futures_root.mkdir()

    report = subject.assess(option_root, futures_root)

    assert report["valid_option_weekly_levels"] == 0
    assert report["valid_futures_decision_dates"] == 0
    assert report["paper_economics_may_start"] is False
    assert report["annualization_allowed"] is False
    assert report["contains_signal_return_or_pnl"] is False
    assert report["live_trading_allowed"] is False

