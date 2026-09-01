"""Outcome-free unit tests for V35 cross-sectional intraday mechanics."""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pandas as pd

from market_lab import stocks_v35_cross_sectional_intraday as runner
from market_lab.stocks import cross_sectional_intraday as core


def _candidate(
    candidate_id: int,
    entry: str,
    exit_: str,
    gross_return: float,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "session_date": entry[:10],
        "year": int(entry[:4]),
        "decision_at": pd.Timestamp(entry) - pd.Timedelta(minutes=10),
        "entry_at": pd.Timestamp(entry),
        "exit_at": pd.Timestamp(exit_),
        "long_tickers": ["A", "B", "C"],
        "short_tickers": ["D", "E", "F"],
        "signal_values": [10_000_000.0] * 6,
        "entry_values": [10_000_000.0] * 6,
        "exit_values": [10_000_000.0] * 6,
        "raw_leg_returns": [gross_return] * 3 + [-gross_return] * 3,
        "signed_leg_returns": [gross_return] * 6,
        "gross_basket_return": gross_return,
        "execution_observed": True,
    }


def test_sealed_config_keeps_protected_data_and_live_trading_disabled() -> None:
    config = runner.load_config()

    assert config["source"]["protected_2026_read_allowed"] is False
    assert config["reporting"]["live_promotion_allowed"] is False
    assert config["timing"]["entry"] == "next_exact_common_bar_open"
    assert config["timing"]["maximum_concurrent_baskets"] == 1


def test_doubled_cost_label_requires_return_above_round_trip_cost() -> None:
    config = runner.load_config()
    candidates = pd.DataFrame(
        [
            _candidate(0, "2022-01-10T07:30:00Z", "2022-01-10T08:30:00Z", 0.010),
            _candidate(1, "2022-01-11T07:30:00Z", "2022-01-11T08:30:00Z", 0.001),
        ]
    )

    labels = core.doubled_cost_label(candidates, config)

    assert labels.tolist() == [1, 0]


def test_ledger_enforces_nonoverlap_and_accounts_costs() -> None:
    config = runner.load_config()
    candidates = pd.DataFrame(
        [
            _candidate(0, "2022-01-10T07:30:00Z", "2022-01-10T08:30:00Z", 0.010),
            _candidate(1, "2022-01-10T08:00:00Z", "2022-01-10T09:00:00Z", 0.010),
        ]
    )
    parameters = core.scenario_parameters(config)["primary"]

    trades, _, metrics = core.simulate_ledger(
        candidates,
        {0, 1},
        config,
        variant="synthetic",
        scenario="primary",
        parameters=parameters,
    )

    assert len(trades) == 1
    assert metrics["overlapping_skipped_count"] == 1
    assert metrics["unresolved_count"] == 0
    assert metrics["costs_rub"] > 0
    assert metrics["total_return"] > 0


def test_threshold_selection_uses_only_nonoverlapping_calibration_trades() -> None:
    config = copy.deepcopy(runner.load_config())
    config["model"]["calibration_minimum_completed_trades"] = 2
    rows = []
    probabilities = []
    for index in range(8):
        rows.append(
            _candidate(
                index,
                f"2021-01-{10 + index:02d}T07:30:00Z",
                f"2021-01-{10 + index:02d}T08:30:00Z",
                0.008 + index * 0.002 if index < 4 else -0.004,
            )
        )
        probabilities.append(0.80 if index < 4 else 0.60)
    candidates = pd.DataFrame(rows)

    threshold, record = core.select_probability_threshold(
        candidates, np.asarray(probabilities), config
    )

    assert threshold == 0.75
    assert record["status"] == "active"


def test_panel_rejects_any_protected_timestamp() -> None:
    timestamps = pd.DatetimeIndex([pd.Timestamp("2026-01-01T00:00:00Z")])
    matrix = np.ones((1, 1))

    try:
        core.StockPanel(timestamps, ("AAA",), matrix, matrix, matrix)
    except ValueError as error:
        assert "protected" in str(error)
    else:
        raise AssertionError("protected timestamp must fail closed")


def test_source_preflight_reads_only_metadata_contract() -> None:
    config = runner.load_config()
    result = core.preflight_source(config, Path(r"D:\Projects\trading_lab"))

    assert all(result["checks"].values())
    assert result["ticker_count"] == 30
    assert result["maximum_timestamp"].startswith("2025-12-30")
