"""Tests for forward MOEX RMS readiness accounting."""

from market_lab.futures import forward_rms_readiness as readiness


def test_phase_is_60_discovery_20_calibration_60_evaluation() -> None:
    config = readiness.source.load_config()

    discovery = readiness.phase_progress(59, config)
    calibration = readiness.phase_progress(60, config)
    evaluation = readiness.phase_progress(80, config)
    complete = readiness.phase_progress(140, config)

    assert discovery["current_phase"] == "discovery"
    assert calibration["current_phase"] == "calibration"
    assert calibration["economic_protocol_may_be_designed"] is True
    assert evaluation["current_phase"] == "unseen_evaluation"
    assert complete["current_phase"] == "independent_review"
    assert complete["evaluation_complete"] is True
    assert complete["live_trading_allowed"] is False
