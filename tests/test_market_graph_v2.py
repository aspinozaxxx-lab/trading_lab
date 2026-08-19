"""Seal, target-free construction, hysteresis, and execution tests for v2."""

from __future__ import annotations

import numpy as np

from market_lab.market_graph_v1.portfolio import run_five_sleeve_backtest
from market_lab.market_graph_v2.experiment import (
    PROTOCOL_PATH,
    PROTOCOL_SHA256,
    ExecutionInputs,
    build_long_only_weights,
    load_execution_inputs,
    load_protocol,
    sha256_file,
)


def test_v2_protocol_and_inputs_are_sealed_and_pre_2026() -> None:
    config = load_protocol()
    assert sha256_file(PROTOCOL_PATH) == PROTOCOL_SHA256
    inputs = load_execution_inputs(config)
    assert inputs.scores.shape == inputs.current_mask.shape == inputs.raw_open.shape
    assert len(inputs.tickers) == 30
    assert str(inputs.dates[-1])[:10] == "2025-12-30"
    assert set(ExecutionInputs.__dataclass_fields__) == {
        "dates",
        "tickers",
        "scores",
        "current_mask",
        "raw_open",
    }


def _synthetic_inputs() -> ExecutionInputs:
    dates = np.arange(
        np.datetime64("2021-01-01"),
        np.datetime64("2021-01-21"),
        np.timedelta64(1, "D"),
    )
    assets = 20
    scores = np.tile(np.arange(assets, 0, -1, dtype=float), (len(dates), 1))
    scores[5] = np.arange(assets, 0, -1, dtype=float)
    scores[5, 0] = 13.5  # Rank eight, retained by keep-through-rank ten.
    return ExecutionInputs(
        dates=dates,
        tickers=tuple(f"T{index:02d}" for index in range(assets)),
        scores=scores,
        current_mask=np.ones_like(scores, dtype=bool),
        raw_open=np.full_like(scores, 100.0),
    )


def test_top5_hysteresis_keeps_rank_eight_and_terminal_is_cash() -> None:
    inputs = _synthetic_inputs()
    weights, concentration = build_long_only_weights(
        inputs,
        start_index=0,
        top_k=5,
        keep_rank=10,
    )
    assert weights[0, 0] == 0.20
    assert weights[5, 0] == 0.20
    assert np.all(weights >= 0.0)
    np.testing.assert_allclose(weights[:14].sum(axis=1), 1.0)
    np.testing.assert_array_equal(weights[14:], 0.0)
    assert concentration["maximum_signal_weight"] == 0.20


def test_top10_and_passive_are_fixed_long_only_allocations() -> None:
    inputs = _synthetic_inputs()
    top10, _ = build_long_only_weights(inputs, start_index=0, top_k=10, keep_rank=15)
    passive, _ = build_long_only_weights(inputs, start_index=0, top_k=None, keep_rank=None)
    assert np.max(top10) == 0.10
    assert np.max(passive) == 0.05
    assert np.min(top10) >= 0.0 and np.min(passive) >= 0.0


def test_v2_executes_next_open_and_closes_five_sessions_later() -> None:
    inputs = _synthetic_inputs()
    weights = np.zeros_like(inputs.scores)
    weights[0, 0] = 0.20
    result = run_five_sleeve_backtest(
        inputs.dates,
        inputs.tickers,
        inputs.raw_open,
        weights,
        start_index=0,
        one_way_cost_bps=0.0,
        short_borrow_rate_annual=0.0,
        maximum_stock_weight=0.20,
    )
    orders = result.orders.loc[result.orders["ticker"].eq("T00")]
    assert orders["session_date"].tolist() == [
        __import__("pandas").Timestamp(inputs.dates[1]),
        __import__("pandas").Timestamp(inputs.dates[6]),
    ]
    assert result.metrics["short_borrow_cost_rub"] == 0.0
    assert not result.metrics["gross_limit_breach"]
