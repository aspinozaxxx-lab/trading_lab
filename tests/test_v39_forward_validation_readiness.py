"""Tests for the sealed V39 joint forward readiness gate."""

from __future__ import annotations

from datetime import date, timedelta

from market_lab.futures import v39_forward_validation_readiness as subject


def test_protocol_is_sealed_and_never_live() -> None:
    config = subject.load_config()

    assert config["protocol_id"] == "futures_v39_forward_validation_v1"
    assert config["live_trading_allowed"] is False
    assert config["warmup"]["option_unique_weekly_levels_required"] == 54
    assert config["warmup"]["futures_common_official_CLOSE_levels_required"] == 253


def test_joint_progress_requires_both_warmups_and_full_evaluation() -> None:
    config = subject.load_config()
    option = [date(2026, 9, 4) + timedelta(days=7 * index) for index in range(54)]
    futures = [date(2026, 9, 2) + timedelta(days=index) for index in range(253)]

    warm = subject.joint_progress(option, futures, config)
    assert warm["joint_warmup_complete"] is True
    assert warm["paper_economics_may_start"] is True
    assert warm["cagr_reporting_allowed"] is False

    boundary = date.fromisoformat(warm["joint_warmup_boundary"])
    extended = futures + [boundary + timedelta(days=index + 1) for index in range(728)]
    ready = subject.joint_progress(option, sorted(set(extended)), config)
    assert ready["evaluation_futures_sessions"]["complete"] == 504
    assert ready["evaluation_weekly_decisions"]["complete"] == 104
    assert ready["evaluation_complete"] is True
    assert ready["live_trading_allowed"] is False
