from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v34_relative_corridor_barrier as runner
from market_lab.futures.relative_corridor_barrier import (
    MODEL_FIXED_RULE,
    CorridorSettings,
    MetaModelSettings,
    _corridor_state,
    _future_barrier_path,
    select_probability_threshold,
    simulate_atomic_pair_portfolio,
)


def _state_panel() -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-02 07:00:00+00:00", periods=180, freq="10min")
    frame = pd.DataFrame({"timestamp": timestamps})
    index = np.arange(len(frame), dtype=float)
    for offset, asset in enumerate(("SI", "RI", "BR", "MIX")):
        frame[f"{asset}_contract_id"] = f"{asset}:H5"
        frame[f"{asset}_close"] = 100.0 + offset * 20.0 + index * (0.02 + offset * 0.001)
    return frame


def _execution_panel(*, low_exit_volume: bool = True) -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-02 07:00:00+00:00", periods=5, freq="10min")
    frame = pd.DataFrame({"timestamp": timestamps, "local_date": pd.Timestamp("2025-01-02")})
    for asset in ("RI", "MIX"):
        frame[f"{asset}_contract_id"] = f"{asset}:H5"
        frame[f"{asset}_open"] = [100.0, 100.0, 101.0, 102.0, 102.0]
        frame[f"{asset}_volume"] = 100_000.0
        frame[f"{asset}_sizing_notional"] = 1_000.0
        frame[f"{asset}_sizing_point_value"] = 1.0
        frame[f"{asset}_sizing_tick_cash_value"] = 1.0
        frame[f"{asset}_conservative_fee_per_side"] = 1.0
        frame[f"{asset}_modeled_initial_margin"] = 100.0
    if low_exit_volume:
        frame.loc[2, "MIX_volume"] = 100.0
    return frame


def _prediction() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model_id": MODEL_FIXED_RULE,
                "active_signal": True,
                "decision_at": pd.Timestamp("2025-01-02 07:00:00+00:00"),
                "entry_at": pd.Timestamp("2025-01-02 07:10:00+00:00"),
                "barrier_exit_at": pd.Timestamp("2025-01-02 07:20:00+00:00"),
                "barrier_exit_reason": "take_profit",
                "decision_local_date": pd.Timestamp("2025-01-02"),
                "corridor_side": 1.0,
                "corridor_beta": 1.0,
                "corridor_stop_barrier": 0.03,
                "RI_contract_id": "RI:H5",
                "MIX_contract_id": "MIX:H5",
                "RI_volume": 100_000.0,
                "MIX_volume": 100_000.0,
            }
        ]
    )


def test_corridor_state_is_causal_under_future_mutation() -> None:
    panel = _state_panel()
    cutoff = pd.Timestamp("2025-01-03 03:00:00+00:00")
    baseline = _corridor_state(panel, CorridorSettings())
    mutated = panel.copy()
    future = mutated["timestamp"].gt(cutoff)
    mutated.loc[future, "RI_close"] *= 4.0
    mutated.loc[future, "MIX_close"] *= 0.25
    replay = _corridor_state(mutated, CorridorSettings())
    columns = [
        "corridor_z",
        "corridor_beta",
        "corridor_residual_sigma",
        "corridor_take_profit_barrier",
        "corridor_stop_barrier",
        "corridor_side",
    ]

    pd.testing.assert_frame_equal(
        baseline.loc[baseline["decision_at"].le(cutoff), columns].reset_index(drop=True),
        replay.loc[replay["decision_at"].le(cutoff), columns].reset_index(drop=True),
    )


def test_protocol_is_byte_sealed_before_outcomes() -> None:
    expected = runner.SIDECAR_PATH.read_text(encoding="utf-8-sig").split()[0]

    assert runner.sha256_file(runner.CONFIG_PATH) == expected
    protocol = runner.load_protocol()
    assert protocol["sealed_before_outcomes"] is True
    assert protocol["live_trading_allowed"] is False
    assert protocol["outcome_boundary"]["post_outcome_parameter_tuning_inside_V34"] == (
        "forbidden"
    )


def test_barrier_uses_completed_close_and_exits_at_next_open() -> None:
    timestamps = pd.date_range("2025-01-02 07:00:00+00:00", periods=14, freq="10min")
    common = pd.DataFrame({"timestamp": timestamps})
    common["RI_contract_id"] = "RI:H5"
    common["MIX_contract_id"] = "MIX:H5"
    common["RI_open"] = 100.0
    common["MIX_open"] = 100.0
    common["RI_close"] = 100.0
    common["MIX_close"] = 100.0
    common.loc[0, "RI_close"] = 102.0
    common.loc[1, "RI_open"] = 102.0
    row = pd.Series(
        {
            "entry_at": timestamps[0],
            "RI_contract_id": "RI:H5",
            "MIX_contract_id": "MIX:H5",
            "corridor_beta": 1.0,
            "corridor_side": 1.0,
            "corridor_take_profit_barrier": 0.01,
            "corridor_stop_barrier": 0.03,
            "stress_roundtrip_cost_ri": 0.0,
            "stress_roundtrip_cost_mix": 0.0,
        }
    )

    outcome = _future_barrier_path(
        row,
        common,
        {timestamp: index for index, timestamp in enumerate(timestamps)},
        settings=CorridorSettings(),
    )

    assert outcome is not None
    assert outcome["barrier_exit_reason"] == "take_profit"
    assert outcome["barrier_exit_at"] == timestamps[1]
    assert outcome["barrier_target"] == 1


def test_threshold_selection_respects_frozen_nonoverlap_gate() -> None:
    dates = pd.date_range("2025-01-01", periods=50, freq="D")
    entry = dates.tz_localize("UTC") + pd.Timedelta(hours=7)
    calibration = pd.DataFrame(
        {
            "decision_local_date": dates,
            "entry_at": entry,
            "barrier_exit_at": entry + pd.Timedelta(minutes=20),
            "barrier_net_stress_return": 0.002 + 0.0001 * (np.arange(len(dates)) % 5),
        }
    )

    threshold, candidates = select_probability_threshold(
        calibration,
        np.full(len(calibration), 0.80),
        MetaModelSettings(),
    )

    assert threshold == 0.75
    assert all(record["calibration_trades"] == 50 for record in candidates)
    assert all(record["positive_calibration_months"] == 2 for record in candidates)


def test_atomic_exit_retries_both_legs_without_partial_fill() -> None:
    result = simulate_atomic_pair_portfolio(
        _execution_panel(low_exit_volume=True),
        _prediction(),
        MODEL_FIXED_RULE,
    )

    assert result.execution_complete
    assert len(result.trades) == 1
    assert result.trades.iloc[0]["actual_exit_at"] == pd.Timestamp("2025-01-02 07:30Z")
    assert result.trades.iloc[0]["exit_retry_index"] == 1
    attempted = result.orders.loc[result.orders["timestamp"].eq(pd.Timestamp("2025-01-02 07:20Z"))]
    assert set(attempted["phase"]) == {"atomic_exit"}
    assert not attempted["filled"].any()
    assert (
        result.ledger.loc[
            result.ledger["timestamp"].eq(pd.Timestamp("2025-01-02 07:20Z")),
            ["position_ri", "position_mix"],
        ]
        .abs()
        .gt(0)
        .all(axis=None)
    )


def test_pair_execution_rejects_protected_2026() -> None:
    prediction = _prediction()
    for column in ("decision_at", "entry_at", "barrier_exit_at"):
        prediction[column] = prediction[column] + pd.DateOffset(years=1)

    with pytest.raises(ValueError, match="protected"):
        simulate_atomic_pair_portfolio(
            _execution_panel(low_exit_volume=False),
            prediction,
            MODEL_FIXED_RULE,
        )
