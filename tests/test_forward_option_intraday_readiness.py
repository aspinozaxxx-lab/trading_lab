"""Tests for source-only high-frequency option readiness."""

from __future__ import annotations

from pathlib import Path

from market_lab.futures import forward_option_intraday_readiness as subject


def test_config_pins_source_only_intraday_admission() -> None:
    config = subject.load_config()

    assert config["session_admission"]["minimum_valid_snapshots"] == 30
    assert config["sequential_phases"]["discovery_complete_sessions"] == 20
    assert (
        config["future_hypothesis_comparisons_fixed_before_values"]["defined_risk_spreads_only"]
        is True
    )
    assert config["live_trading_allowed"] is False


def test_empty_source_has_no_complete_session_or_economics(tmp_path: Path) -> None:
    report = subject.assess(tmp_path)

    assert report["eligible_valid_snapshot_count"] == 0
    assert report["complete_session_count"] == 0
    assert report["progress"]["economic_protocol_may_be_sealed"] is False
    assert report["contains_signal_return_target_prediction_trade_position_equity_or_pnl"] is False
    assert report["live_trading_allowed"] is False


def test_phase_progress_is_strictly_sequential() -> None:
    phases = {
        "discovery_complete_sessions": 20,
        "calibration_complete_sessions": 20,
        "unseen_evaluation_complete_sessions": 60,
    }

    assert subject.phase_progress(19, phases)["current_phase"] == "discovery"
    assert subject.phase_progress(20, phases)["current_phase"] == "calibration"
    assert subject.phase_progress(40, phases)["current_phase"] == "unseen_evaluation"
    assert subject.phase_progress(100, phases)["current_phase"] == "independent_review"
