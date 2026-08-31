"""Causality and accounting tests for the sealed V10 triangular experiment."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from market_lab.futures_v10_triangular_relative_value.core import (
    PRIMARY_STRATEGY,
    SignalSettings,
    build_signal_frame,
    calculate_metrics,
    simulate_strategy,
)
from market_lab.futures_v10_triangular_relative_value.data import (
    CONFIG_PATH,
    CONFIG_SHA256,
    load_protocol,
    sha256_file,
)
from market_lab.futures_v11_liquidity_buffered_open import (
    CONFIG_PATH as V11_CONFIG_PATH,
)
from market_lab.futures_v11_liquidity_buffered_open import (
    CONFIG_SHA256 as V11_CONFIG_SHA256,
)
from market_lab.futures_v11_liquidity_buffered_open import (
    load_protocol as load_v11_protocol,
)
from market_lab.futures_v11_liquidity_buffered_open import simulate_buffered_open


def _panel(
    residuals: list[float],
    *,
    volumes: list[float] | None = None,
    start: str = "2025-01-02 07:00:00+00:00",
) -> pd.DataFrame:
    timestamps = pd.date_range(start, periods=len(residuals), freq="10min")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "end_timestamp": timestamps + pd.Timedelta(minutes=10),
        }
    )
    volume_values = volumes if volumes is not None else [10_000.0] * len(frame)
    closes = {
        "RI": np.exp(np.asarray(residuals, dtype=float)),
        "MIX": np.full(len(frame), 100.0),
        "SI": np.full(len(frame), 100.0),
    }
    for asset in PRIMARY_STRATEGY.assets:
        close = closes[asset]
        frame[f"{asset}_contract_id"] = f"{asset}:H5"
        frame[f"{asset}_open"] = close
        frame[f"{asset}_high"] = close + 1.0
        frame[f"{asset}_low"] = close - 1.0
        frame[f"{asset}_close"] = close
        frame[f"{asset}_volume"] = volume_values
        frame[f"{asset}_sizing_point_value"] = 1.0
        frame[f"{asset}_sizing_notional"] = 10_000.0
        frame[f"{asset}_sizing_tick_cash_value"] = 1.0
        frame[f"{asset}_conservative_fee_per_side"] = 1.0
        frame[f"{asset}_sizing_usable"] = True
    return frame


def _settings() -> SignalSettings:
    return SignalSettings(baseline_observations=3)


def _force_one_entry(signals: pd.DataFrame, index: int, *, zscore: float = 3.0) -> None:
    signals["raw_entry_signal"] = False
    signals["residual_position_side"] = 0
    signals.loc[index, "raw_entry_signal"] = True
    signals.loc[index, "zscore"] = zscore
    signals.loc[index, "residual_position_side"] = -1 if zscore > 0.0 else 1


def test_protocol_hash_and_frozen_economics() -> None:
    assert sha256_file(CONFIG_PATH) == CONFIG_SHA256
    protocol = load_protocol()
    assert protocol["signal"]["entry_absolute_z"] == 2.0
    assert protocol["signal"]["distant_adverse_stop_absolute_z"] == 4.0
    assert protocol["portfolio"]["entry_and_exit_realized_participation_limit"] == 0.01
    assert protocol["boundaries"]["protected_from"] == "2026-01-01"


def test_residual_baseline_uses_prior_values_only_and_future_mutation_is_inert() -> None:
    residuals = [4.60, 4.61, 4.59, 4.60, 4.62, 4.58, 4.61, 4.57, 4.63]
    baseline = build_signal_frame(_panel(residuals), PRIMARY_STRATEGY, _settings())
    assert baseline.loc[3, "baseline_mean"] == pytest.approx(np.mean(residuals[:3]))
    cutoff = 5
    mutated_panel = _panel(residuals)
    future = mutated_panel.index > cutoff
    mutated_panel.loc[future, "RI_close"] *= 4.0
    mutated_panel.loc[future, "RI_open"] = mutated_panel.loc[future, "RI_close"]
    mutated_panel.loc[future, "RI_high"] = mutated_panel.loc[future, "RI_close"] + 1.0
    mutated_panel.loc[future, "RI_low"] = mutated_panel.loc[future, "RI_close"] - 1.0
    replay = build_signal_frame(mutated_panel, PRIMARY_STRATEGY, _settings())
    np.testing.assert_allclose(
        baseline.loc[:cutoff, "zscore"],
        replay.loc[:cutoff, "zscore"],
        equal_nan=True,
    )


def test_any_leg_roll_resets_the_prior_window() -> None:
    panel = _panel([4.60, 4.61, 4.59, 4.62, 4.58, 4.60, 4.61, 4.59, 4.62])
    panel.loc[5:, "SI_contract_id"] = "SI:M5"
    signals = build_signal_frame(panel, PRIMARY_STRATEGY, _settings())
    assert signals.loc[5:7, "zscore"].isna().all()
    assert np.isfinite(signals.loc[8, "zscore"])


def test_three_leg_signs_adverse_fills_costs_and_profit_take() -> None:
    panel = _panel([4.60, 4.61, 4.59, 4.60, 4.60, 4.60, 4.60, 4.60])
    signals = build_signal_frame(panel, PRIMARY_STRATEGY, _settings())
    _force_one_entry(signals, 3, zscore=3.0)
    signals.loc[4, "zscore"] = 0.25
    result = simulate_strategy(signals, PRIMARY_STRATEGY, _settings())
    assert not result.halted
    assert result.counts["completed_trades"] == 1
    assert result.trades.iloc[0]["exit_reason"] == "take_profit"
    legs = result.legs.set_index("asset")
    assert legs.loc["RI", "side"] == "short"
    assert legs.loc["MIX", "side"] == "long"
    assert legs.loc["SI", "side"] == "short"
    assert legs.loc["RI", "entry_price"] == pytest.approx(panel.loc[4, "RI_low"])
    assert legs.loc["RI", "exit_price"] == pytest.approx(panel.loc[5, "RI_high"])
    assert legs.loc["MIX", "entry_price"] == pytest.approx(panel.loc[4, "MIX_high"])
    assert legs.loc["MIX", "exit_price"] == pytest.approx(panel.loc[5, "MIX_low"])
    assert set(legs["quantity"]) == {30}
    assert set(legs["costs_1x"]) == {120.0}
    assert result.trades.iloc[0]["maximum_entry_participation"] == pytest.approx(0.003)


def test_distant_stop_has_precedence_over_time_exit() -> None:
    panel = _panel([4.60, 4.61, 4.59, 4.60, 4.60, 4.60, 4.60])
    settings = replace(_settings(), maximum_holding_completed_bars=1)
    signals = build_signal_frame(panel, PRIMARY_STRATEGY, settings)
    _force_one_entry(signals, 3, zscore=3.0)
    signals.loc[4, "zscore"] = 4.5
    result = simulate_strategy(signals, PRIMARY_STRATEGY, settings)
    assert result.trades.iloc[0]["exit_reason"] == "distant_stop"


def test_clock_gap_is_never_bridged() -> None:
    panel = _panel([4.60, 4.61, 4.59, 4.60, 4.60, 4.60]).drop(index=4).reset_index(drop=True)
    signals = build_signal_frame(panel, PRIMARY_STRATEGY, _settings())
    _force_one_entry(signals, 3)
    result = simulate_strategy(signals, PRIMARY_STRATEGY, _settings())
    assert result.halted
    assert result.counts["unresolved"] == 1
    assert result.unresolved_events.iloc[0]["reason"] == "missing_exact_entry_successor"


def test_realized_entry_capacity_failure_is_no_go() -> None:
    volumes = [10_000.0] * 7
    volumes[4] = 1_000.0
    panel = _panel([4.60, 4.61, 4.59, 4.60, 4.60, 4.60, 4.60], volumes=volumes)
    signals = build_signal_frame(panel, PRIMARY_STRATEGY, _settings())
    _force_one_entry(signals, 3)
    result = simulate_strategy(signals, PRIMARY_STRATEGY, _settings())
    assert result.halted
    assert result.counts["rejected_capacity"] == 1
    assert result.unresolved_events.iloc[0]["reason"] == "insufficient_entry_window_capacity"


def test_protected_2026_rows_are_rejected() -> None:
    panel = _panel(
        [4.60, 4.61, 4.59, 4.60],
        start="2026-01-02 07:00:00+00:00",
    )
    with pytest.raises(ValueError, match="protected"):
        build_signal_frame(panel, PRIMARY_STRATEGY, _settings())


def test_metrics_include_initial_capital_in_drawdown_peak() -> None:
    signals = build_signal_frame(
        _panel([4.60, 4.61, 4.59, 4.60, 4.60, 4.60, 4.60]),
        PRIMARY_STRATEGY,
        _settings(),
    )
    trades = pd.DataFrame(
        {
            "exit_fill_at": [signals.loc[5, "end_timestamp"]],
            "pnl_1x": [-100_000.0],
            "pnl_2x": [-110_000.0],
            "costs_1x": [10_000.0],
            "maximum_entry_participation": [0.001],
            "maximum_exit_participation": [0.001],
        }
    )
    metrics = calculate_metrics(
        signals,
        trades,
        _settings(),
        cost_column="pnl_1x",
        valid=True,
    )
    assert metrics["maximum_drawdown"] == pytest.approx(-0.10)


def test_v11_protocol_is_adaptive_and_sealed() -> None:
    assert sha256_file(V11_CONFIG_PATH) == V11_CONFIG_SHA256
    protocol = load_v11_protocol()
    assert protocol["adaptive_research_notice"]["confirmatory_claim_from_2021_2025_forbidden"]
    assert protocol["execution"]["signal_bar_sizing_participation"] == 0.0025
    assert protocol["execution"]["factual_entry_and_exit_participation_cap"] == 0.01


def test_v11_uses_factual_next_opens_and_buffered_size() -> None:
    panel = _panel([4.60, 4.61, 4.59, 4.60, 4.60, 4.60, 4.60, 4.60])
    signals = build_signal_frame(panel, PRIMARY_STRATEGY, _settings())
    _force_one_entry(signals, 3, zscore=3.0)
    signals.loc[4, "zscore"] = 0.25
    result = simulate_buffered_open(signals, _settings())
    assert not result.halted
    assert result.counts["completed_trades"] == 1
    legs = result.legs.set_index("asset")
    assert set(legs["quantity"]) == {25}
    assert legs.loc["RI", "entry_price"] == pytest.approx(panel.loc[4, "RI_open"])
    assert legs.loc["RI", "exit_price"] == pytest.approx(panel.loc[5, "RI_open"])
    assert set(legs["costs_1x"]) == {100.0}


def test_v11_unfilled_entry_capacity_does_not_create_a_position() -> None:
    volumes = [10_000.0] * 7
    volumes[4] = 1_000.0
    signals = build_signal_frame(
        _panel([4.60, 4.61, 4.59, 4.60, 4.60, 4.60, 4.60], volumes=volumes),
        PRIMARY_STRATEGY,
        _settings(),
    )
    _force_one_entry(signals, 3)
    result = simulate_buffered_open(signals, _settings())
    assert not result.halted
    assert result.trades.empty
    assert result.counts["entry_orders_unfilled_capacity"] == 1
    assert result.counts["unresolved"] == 0


def test_v11_pending_exit_retries_the_next_exact_capacity_window() -> None:
    volumes = [10_000.0] * 9
    volumes[5] = 1_000.0
    panel = _panel(
        [4.60, 4.61, 4.59, 4.60, 4.60, 4.60, 4.60, 4.60, 4.60],
        volumes=volumes,
    )
    signals = build_signal_frame(panel, PRIMARY_STRATEGY, _settings())
    _force_one_entry(signals, 3)
    signals.loc[4, "zscore"] = 0.25
    result = simulate_buffered_open(signals, _settings())
    assert not result.halted
    assert result.counts["exit_capacity_retries"] == 1
    assert result.trades.iloc[0]["pending_exit_bars"] == 1
    assert result.trades.iloc[0]["exit_fill_at"] == panel.loc[6, "timestamp"]
