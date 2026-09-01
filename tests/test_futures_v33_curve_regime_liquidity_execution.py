"""Execution-only tests for V33 capacity carry and risk-first reversals."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab import futures_v33_curve_regime_liquidity_execution as source
from market_lab.futures.curve_regime_intraday import ASSETS, LedgerSettings


def _panel(volumes: list[float]) -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-02 07:00:00+00:00", periods=len(volumes), freq="10min")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "local_date": pd.Timestamp("2025-01-02"),
        }
    )
    for asset in ASSETS:
        frame[f"{asset}_contract_id"] = f"{asset}:H5"
        frame[f"{asset}_open"] = 100.0
        frame[f"{asset}_volume"] = 100_000.0
        frame[f"{asset}_sizing_point_value"] = 1.0
        frame[f"{asset}_sizing_tick_cash_value"] = 1.0
        frame[f"{asset}_conservative_fee_per_side"] = 1.0
        frame[f"{asset}_modeled_initial_margin"] = 100.0
        frame[f"{asset}_sizing_notional"] = 1_000.0
    frame["SI_volume"] = volumes
    return frame


def _target_rows(
    timestamps: list[pd.Timestamp],
    si_weights: list[float],
    *,
    forced_flat_index: int | None = None,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for index, (timestamp, si_weight) in enumerate(zip(timestamps, si_weights, strict=True)):
        forced_flat = index == forced_flat_index
        for asset in ASSETS:
            records.append(
                {
                    "entry_at": timestamp,
                    "asset": asset,
                    "contract_id": f"{asset}:H5",
                    "target_weight": si_weight if asset == "SI" else 0.0,
                    "signal_volume": 100_000.0,
                    "sizing_notional": 1_000.0,
                    "sizing_point_value": 1.0,
                    "sizing_tick_cash_value": 1.0,
                    "conservative_fee_per_side": 1.0,
                    "modeled_initial_margin": 100.0,
                    "forced_flat": forced_flat,
                }
            )
    return pd.DataFrame(records)


def test_order_phases_split_a_reversal_close_first() -> None:
    assert source._order_phases(2, -3) == [(0, -2, False), (1, -3, True)]
    assert source._order_phases(-2, -1) == [(0, 1, False)]
    assert source._order_phases(0, 2) == [(1, 2, False)]


def test_zero_capacity_derisk_carries_to_the_next_target_bucket() -> None:
    panel = _panel([100_000.0, 100_000.0, 50.0, 200.0])
    timestamps = list(panel.loc[1:3, "timestamp"])
    targets = _target_rows(timestamps, [0.0011, 0.0, 0.0])

    result = source.simulate_retry_portfolio(panel, targets, LedgerSettings())

    assert result.execution_complete
    assert result.metrics["zero_capacity_retries"] == 1
    assert result.metrics["filled_order_legs"] == 2
    assert result.ledger.iloc[-1]["position_si"] == 0
    retry = result.orders.loc[result.orders["reason"].eq("zero_factual_capacity")].iloc[0]
    assert retry["requested_quantity_delta"] == -1
    assert retry["filled_quantity_delta"] == 0


def test_reversal_does_not_cross_zero_until_the_close_leg_fills() -> None:
    panel = _panel([100_000.0, 100_000.0, 100.0, 200.0, 200.0])
    timestamps = list(panel.loc[1:4, "timestamp"])
    targets = _target_rows(timestamps, [0.0011, -0.0011, -0.0011, 0.0])

    result = source.simulate_retry_portfolio(panel, targets)

    assert result.execution_complete
    at_reversal = result.ledger.loc[result.ledger["timestamp"].eq(timestamps[1])].iloc[0]
    assert at_reversal["position_si"] == 0
    reversal_orders = result.orders.loc[result.orders["timestamp"].eq(timestamps[1])]
    assert list(reversal_orders["phase"]) == [0, 1]
    assert list(reversal_orders["filled_quantity_delta"]) == [-1, 0]
    assert result.ledger.iloc[-1]["position_si"] == 0


def test_forced_flat_uses_the_first_exact_retry_with_capacity() -> None:
    panel = _panel([100_000.0, 100_000.0, 50.0, 200.0, 200.0, 200.0, 200.0, 200.0, 200.0])
    timestamps = [panel.loc[1, "timestamp"], panel.loc[2, "timestamp"]]
    targets = _target_rows(timestamps, [0.0011, 0.0], forced_flat_index=1)

    result = source.simulate_retry_portfolio(panel, targets)

    assert result.execution_complete
    exit_order = result.orders.loc[result.orders["filled_quantity_delta"].eq(-1)].iloc[0]
    assert exit_order["flat_retry_index"] == 1
    assert bool(exit_order["forced_flat"])
    assert result.ledger.iloc[-1]["position_si"] == 0


def test_forced_flat_fails_closed_after_six_zero_capacity_retries() -> None:
    panel = _panel([100_000.0, 100_000.0, *([50.0] * 7)])
    timestamps = [panel.loc[1, "timestamp"], panel.loc[2, "timestamp"]]
    targets = _target_rows(timestamps, [0.0011, 0.0], forced_flat_index=1)

    result = source.simulate_retry_portfolio(panel, targets)

    assert not result.execution_complete
    assert result.unresolved.to_dict("records") == [
        {
            "timestamp": panel.loc[8, "timestamp"],
            "asset": "PORTFOLIO",
            "reason": "flat_retry_exhausted",
        }
    ]


def test_retry_schedule_remains_before_protected_2026() -> None:
    panel = _panel([100_000.0] * 9)
    targets = _target_rows(
        [pd.Timestamp("2026-01-02 07:10:00+00:00")],
        [0.0],
        forced_flat_index=0,
    )

    with pytest.raises(ValueError, match="protected"):
        source.simulate_retry_portfolio(panel, targets)


def test_protocol_hash_is_checked_once_config_exists() -> None:
    if not source.CONFIG_PATH.exists() or not source.SIDECAR_PATH.exists():
        pytest.skip("V33 byte-sealed protocol is added after execution unit tests")
    expected = source.SIDECAR_PATH.read_text(encoding="utf-8-sig").split()[0]
    assert source.sha256_file(source.CONFIG_PATH) == expected
    assert source.load_protocol()["signals_models_and_target_weights_changed"] is False


def test_parent_target_paths_remain_external_to_git_payload() -> None:
    if not source.CONFIG_PATH.exists():
        pytest.skip("V33 protocol is added after execution unit tests")
    protocol = source.load_protocol()
    for record in protocol["target_artifacts"].values():
        path = source.PROJECT_ROOT / Path(record["path"])
        assert "runs" in path.parts
        assert path.is_file()
