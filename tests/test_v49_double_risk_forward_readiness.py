"""Tests for the sealed post-boundary V49 source-only readiness."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from market_lab.futures import v49_double_risk_forward_readiness as subject


def test_config_pins_single_arm_and_resets_eligibility() -> None:
    config = subject.load_config()

    assert config["fixed_arm"]["V39_mapped_target_multiplier"] == 2.0
    assert config["fixed_arm"]["maximum_gross_notional_multiple"] == 4.0
    assert config["fixed_arm"]["comparison_or_selection_against_V48_after_forward_outcome"] == (
        "forbidden"
    )
    assert config["current_state_at_seal"]["V49_eligible_counts_reset_to_zero"] is True
    assert config["live_trading_allowed"] is False


def test_empty_sources_cannot_start_paper_or_report_cagr(tmp_path: Path) -> None:
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


def test_component_filter_excludes_preseal_and_duplicate_market_dates() -> None:
    report = {
        "duplicate_market_component_dates": {
            "market_decision:2026-09-03": ["duplicate-a", "duplicate-b"]
        },
        "valid_snapshots": [
            {
                "component": "macro_cbr",
                "retrieved_at_utc": "2026-09-02T12:29:59Z",
                "source_dates": ["2026-09-02"],
            },
            {
                "component": "market_decision",
                "retrieved_at_utc": "2026-09-03T12:00:00Z",
                "source_dates": ["2026-09-03"],
            },
            {
                "component": "macro_fred",
                "retrieved_at_utc": "2026-09-03T12:00:00Z",
                "source_dates": ["2026-09-01"],
            },
        ],
    }

    eligible, excluded = subject._postseal_components(report, pd.Timestamp("2026-09-02T12:30:04Z"))

    assert excluded == 1
    assert [item["component"] for item in eligible] == ["macro_fred"]
