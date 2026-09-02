"""Synthetic causal tests for the sealed V37 cross-market breakout."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from market_lab import stocks_v37_cross_market_breakout as runner
from market_lab.stocks import cross_market_breakout as core

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _config() -> dict:
    return yaml.safe_load(
        (PROJECT_ROOT / "configs/stocks_v37_cross_market_breakout.yaml").read_text(
            encoding="utf-8-sig"
        )
    )


def _panel() -> core.BreakoutPanel:
    timestamps = pd.date_range("2022-01-03T07:00:00Z", periods=60, freq="10min")
    tickers = tuple(f"T{index:02d}" for index in range(30))
    common = 100.0 * np.exp(np.arange(60)[:, None] * 0.0003)
    closes = np.repeat(common, 30, axis=1)
    closes[10:, :3] *= 1.003
    entry_reference = closes[10, :3].copy()
    closes[11, :3] = entry_reference * 1.003
    closes[12, :3] = entry_reference * 1.008
    closes[13, :3] = entry_reference * 1.002
    closes[14:, :3] = closes[13, :3]
    opens = np.vstack([closes[0], closes[:-1]])
    highs = np.maximum(opens, closes) * 1.0001
    lows = np.minimum(opens, closes) * 0.9999
    values = np.repeat(np.linspace(1_000_000.0, 2_000_000.0, 30)[None, :], 60, axis=0)
    values[:, :3] = 3_000_000.0
    return core.BreakoutPanel(timestamps, tickers, opens, highs, lows, closes, values)


def test_protocol_and_source_metadata_are_byte_sealed() -> None:
    config = runner.load_protocol()
    checks = core.preflight_source(config, PROJECT_ROOT)

    assert all(checks.values())
    assert config["model"]["fixed_trade_probability_threshold"] == 0.60
    assert config["reporting"]["gates"]["primary_cagr_minimum"] == 0.20


def test_breakout_decision_enters_next_open_and_exits_after_completed_trigger() -> None:
    candidates = core.build_candidates(_panel(), _config()).frame

    row = candidates.iloc[0]
    assert row["direction"] == 1
    assert row["selected_tickers"] == ["T02", "T01", "T00"]
    assert row["entry_at"] == row["decision_at"]
    assert row["exit_reason"] == "trailing_profit"
    assert row["exit_at"] > row["entry_at"]
    assert row["execution_observed"]


def test_doubled_cost_label_requires_net_positive() -> None:
    config = _config()
    candidates = pd.DataFrame(
        {
            "gross_basket_return": [0.01, 0.001],
            "direction": [1, -1],
            "entry_at": pd.to_datetime(["2022-01-03T08:00:00Z"] * 2),
            "exit_at": pd.to_datetime(["2022-01-03T10:00:00Z"] * 2),
        }
    )

    labels = core.doubled_cost_label(candidates, config)

    assert labels.tolist() == [1, 0]


def test_ledger_is_nonoverlap_costed_and_capacity_checked() -> None:
    config = _config()
    candidate = pd.DataFrame(
        {
            "candidate_id": [1],
            "entry_at": pd.to_datetime(["2022-01-03T08:00:00Z"]),
            "exit_at": pd.to_datetime(["2022-01-03T10:00:00Z"]),
            "session_date": ["2022-01-03"],
            "direction": [1],
            "selected_tickers": [["A", "B", "C"]],
            "exit_reason": ["maximum_holding_exit"],
            "execution_observed": [True],
            "signal_values": [[100_000_000.0] * 3],
            "entry_values": [[100_000_000.0] * 3],
            "exit_values": [[100_000_000.0] * 3],
            "raw_leg_returns": [[0.01] * 3],
            "signed_leg_returns": [[0.01] * 3],
            "gross_basket_return": [0.01],
        }
    )
    parameters = core.scenario_parameters(config)["primary"]

    trades, _, metrics = core.simulate_ledger(
        candidate,
        {1},
        config,
        variant="test",
        scenario="primary",
        parameters=parameters,
        evaluation_sessions=("2022-01-03",),
    )

    assert len(trades) == 1
    assert trades.iloc[0]["trading_cost_rub"] > 0.0
    assert metrics["unresolved_count"] == 0
    assert metrics["maximum_participation"] <= 0.01
    assert metrics["ending_equity_rub"] > 1_000_000.0
