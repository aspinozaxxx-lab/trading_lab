"""Regression tests for the breadth-first V9 structural futures proxy."""

from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
import yaml

from market_lab.futures_v9_structural.run import paginate_history
from market_lab.futures_v9_structural.structural import (
    backtest_strategy,
    build_asset_panel,
    build_continuous_asset,
    build_synchronized_panel,
    truncate_contract_rows,
    validate_contract_rows,
)


def _config() -> dict:
    with open("configs/futures_v9_structural.yaml", encoding="utf-8-sig") as stream:
        return yaml.safe_load(stream)


def _row(
    day: str,
    contract: str,
    close: float,
    value: float,
    expiration: str,
) -> dict:
    return {
        "asset_code": "TEST",
        "contract_id": f"TEST:{contract}:{expiration}",
        "secid": contract,
        "trade_date": pd.Timestamp(day),
        "expiration_date": pd.Timestamp(expiration),
        "close": close,
        "value": value,
        "volume": value / 100.0,
    }


def test_roll_selection_is_lagged_for_realized_return() -> None:
    rows = pd.DataFrame(
        [
            _row("2025-01-02", "AAH5", 100.0, 1000.0, "2025-03-20"),
            _row("2025-01-02", "AAM5", 200.0, 100.0, "2025-06-19"),
            _row("2025-01-03", "AAH5", 101.0, 100.0, "2025-03-20"),
            _row("2025-01-03", "AAM5", 202.0, 2000.0, "2025-06-19"),
            _row("2025-01-06", "AAH5", 102.0, 50.0, "2025-03-20"),
            _row("2025-01-06", "AAM5", 200.0, 2100.0, "2025-06-19"),
        ]
    )
    panel = build_continuous_asset(
        rows,
        roll_buffer_days=5,
        carry_minimum_gap_days=20,
        carry_maximum_abs=5.0,
    ).set_index("trade_date")
    assert panel.loc[pd.Timestamp("2025-01-03"), "asset_return"] == pytest.approx(0.01)
    assert panel.loc[pd.Timestamp("2025-01-06"), "asset_return"] == pytest.approx(
        200.0 / 202.0 - 1.0
    )
    assert bool(panel.loc[pd.Timestamp("2025-01-03"), "roll_flag"])


def _history_payload(offset: int, total: int, rows: list[list[object]]) -> dict:
    return {
        "history": {
            "columns": ["BOARDID", "TRADEDATE", "SECID"],
            "data": rows,
        },
        "history.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[offset, total, 2]],
        },
    }


def test_history_pagination_requires_exact_cursor_completion() -> None:
    pages = {
        0: _history_payload(
            0,
            3,
            [["RFUD", "2025-01-02", "AAH5"], ["RFUD", "2025-01-03", "AAH5"]],
        ),
        2: _history_payload(2, 3, [["RFUD", "2025-01-06", "AAH5"]]),
    }
    frame, archived = paginate_history(lambda offset: (f"u?start={offset}", pages[offset]))
    assert len(frame) == 3
    assert len(archived) == 2
    broken = {0: _history_payload(0, 2, [["RFUD", "2025-01-02", "AAH5"]])}
    with pytest.raises(ValueError, match="truncated"):
        paginate_history(lambda offset: ("broken", broken[offset]))


def test_future_mutation_cannot_change_truncated_panel() -> None:
    config = deepcopy(_config())
    config["eligibility"]["minimum_return_observations"] = 2
    config["eligibility"]["trailing_liquidity_days"] = 2
    config["signals"]["momentum_horizons_sessions"] = [2, 3, 4, 5]
    config["signals"]["volatility_lookback_sessions"] = 2
    days = pd.bdate_range("2025-01-02", periods=12)
    rows = pd.DataFrame(
        [
            _row(day.date().isoformat(), "AAH5", 100.0 + index, 10_000_000.0, "2025-03-20")
            for index, day in enumerate(days)
        ]
    )
    cutoff = days[7]
    baseline = build_asset_panel(truncate_contract_rows(rows, cutoff), config)
    mutated = rows.copy()
    mutated.loc[mutated["trade_date"] > cutoff, "close"] *= 100.0
    replay = build_asset_panel(truncate_contract_rows(mutated, cutoff), config)
    pd.testing.assert_frame_equal(baseline, replay)


def test_no_2026_contract_history_is_admitted() -> None:
    rows = pd.DataFrame([_row("2026-01-02", "AAH6", 100.0, 1000.0, "2026-03-19")])
    with pytest.raises(ValueError, match="2026"):
        validate_contract_rows(rows, pd.Timestamp("2026-01-01"))


def test_synchronized_panel_has_explicit_masks_and_no_target() -> None:
    dates = pd.to_datetime(["2025-01-02", "2025-01-03"])
    rows = []
    for asset in ("A", "B"):
        for day in dates:
            row = {
                "trade_date": day,
                "asset_code": asset,
                "active_contract": f"{asset}1",
                "asset_return": 0.01,
                "volatility": 0.2,
                "curve_carry": 0.1,
                "eligible": True,
            }
            for field in (
                "signal_tsmom_21",
                "signal_tsmom_63",
                "signal_tsmom_126",
                "signal_tsmom_252",
                "signal_tsmom_multi",
                "signal_risk_adjusted_momentum",
                "signal_curve_carry",
                "signal_carry_momentum_confirmation",
            ):
                row[field] = 1.0
            rows.append(row)
    synchronized, schema = build_synchronized_panel(pd.DataFrame(rows))
    assert {"A__observed", "A__eligible", "B__return_available"}.issubset(synchronized.columns)
    assert schema["target_columns"] == []
    assert schema["point_in_time_universe"] is True


def test_portfolio_gross_cap_holds_when_an_asset_is_absent_on_rebalance() -> None:
    config = _config()
    config["dates"]["development_start"] = "2025-01-01"
    dates = pd.bdate_range("2025-01-02", periods=20)
    rows = []
    for asset_index in range(6):
        asset = f"A{asset_index}"
        for day in dates:
            if asset == "A5" and day.weekday() == 4:
                continue
            rows.append(
                {
                    "trade_date": day,
                    "asset_code": asset,
                    "asset_return": 0.001 * (-1.0 if asset_index % 2 else 1.0),
                    "volatility": 0.2,
                    "eligible": True,
                    "roll_flag": False,
                    "signal": 1.0,
                }
            )
    ledger, metrics = backtest_strategy(pd.DataFrame(rows), "signal", config)
    assert metrics["maximum_gross"] <= 1.0 + 1e-12
    assert np.isfinite(ledger["primary_net_return"]).all()
