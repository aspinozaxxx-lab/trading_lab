"""Tests for V49 paper readiness with official calendar admission."""

from __future__ import annotations

from pathlib import Path

import pytest

from market_lab.futures import v49_double_risk_paper_readiness_v3 as subject


def _base(*, ready: bool, annualization: bool) -> dict[str, object]:
    return {
        "protocol_id": "v49_double_risk_paper_arm_v1",
        "readiness_version": 2,
        "progress": {
            "current_phase": "postseal_unseen_evaluation" if ready else "postseal_joint_warmup",
            "paper_economics_may_start": ready,
            "cagr_reporting_allowed": annualization,
        },
        "contains_signal_return_target_prediction_or_pnl": False,
        "live_trading_allowed": False,
    }


def _calendar(*, ready: bool) -> dict[str, object]:
    return {
        "valid_snapshot_count": int(ready),
        "invalid_snapshot_count": 0,
        "latest_causal_retrieved_at_utc": "2026-09-02T22:53:45+00:00" if ready else None,
        "next_six_trading_sessions_known": ready,
        "calendar_source_ready_for_five_session_fallback": ready,
    }


def test_config_preserves_v49_arm_and_five_session_fallback() -> None:
    config = subject.load_config()
    assert config["frozen_economic_invariants"]["V49_multiplier"] == 2.0
    assert config["frozen_economic_invariants"]["hard_fallback_sessions"] == 5
    assert config["successor_readiness_contract"][
        "calendar_can_override_false_base_readiness"
    ] is False
    assert config["live_trading_allowed"] is False


@pytest.mark.parametrize(
    ("base_ready", "calendar_ready", "expected"),
    [(False, True, False), (True, False, False), (True, True, True)],
)
def test_calendar_is_an_additional_required_condition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    base_ready: bool,
    calendar_ready: bool,
    expected: bool,
) -> None:
    monkeypatch.setattr(
        subject.parent,
        "assess",
        lambda *args, **kwargs: _base(ready=base_ready, annualization=base_ready),
    )
    monkeypatch.setattr(
        subject.calendar,
        "assess",
        lambda *args, **kwargs: _calendar(ready=calendar_ready),
    )
    report = subject.assess(tmp_path, tmp_path, tmp_path)
    assert report["progress"]["paper_economics_may_start"] is expected
    assert report["progress"]["cagr_reporting_allowed"] is expected
    assert report["contains_signal_return_target_prediction_order_position_or_pnl"] is False
    assert report["live_trading_allowed"] is False
    if base_ready and not calendar_ready:
        assert report["progress"]["current_phase"] == "postseal_official_calendar_wait"
