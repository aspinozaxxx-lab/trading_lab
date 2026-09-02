"""Tests for timestamped forward option intraday readiness V2."""

from __future__ import annotations

from pathlib import Path

from market_lab.futures import forward_option_intraday_readiness_v2 as subject


def test_config_pins_timestamped_source_and_clean_boundary() -> None:
    config = subject.load_config()
    assert config["parent_source"]["v1_complete_sessions_at_declaration"] == 0
    assert config["parent_source"]["v1_snapshots_counted_for_v2"] is False
    assert config["session_admission"]["required_v2_observations_complete"] is True
    assert config["live_trading_allowed"] is False


def test_empty_v2_root_has_no_economics(tmp_path: Path) -> None:
    report = subject.assess(tmp_path)
    assert report["eligible_valid_snapshot_count"] == 0
    assert report["complete_session_count"] == 0
    assert report["progress"]["economic_protocol_may_be_sealed"] is False
    assert report["contains_signal_return_target_prediction_trade_position_equity_or_pnl"] is False
    assert report["live_trading_allowed"] is False
