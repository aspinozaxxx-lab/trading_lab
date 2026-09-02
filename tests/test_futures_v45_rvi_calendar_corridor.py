"""Focused tests for the sealed V45 RVI calendar corridor."""

from __future__ import annotations

import pandas as pd

from market_lab import futures_v45_rvi_calendar_corridor as v45


def test_protocol_and_source_identities_are_pinned() -> None:
    protocol = v45.load_protocol()

    assert protocol.config_sha256.startswith("2207f549")
    assert protocol.payload["signal"]["entry_absolute_z_gte"] == 1.5
    assert protocol.payload["signal"]["adverse_stop_absolute_z_gte"] == 4.0
    assert protocol.payload["live_trading_allowed"] is False


def test_point_value_preserves_missing_and_uses_turnover_identity() -> None:
    frame = pd.DataFrame(
        {
            "value": [6000.0, 10.0, 10.0],
            "volume": [2.0, 0.0, 1.0],
            "waprice": [30.0, 30.0, float("nan")],
        }
    )

    result = v45._point_value(frame)

    assert result.iloc[0] == 100.0
    assert pd.isna(result.iloc[1])
    assert pd.isna(result.iloc[2])


def test_cost_scenarios_are_monotonic_on_synthetic_trade() -> None:
    protocol = v45.load_protocol()
    state = pd.DataFrame(
        {
            "date": pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-06"]),
        }
    )
    trades = pd.DataFrame(
        {
            "exit_date": pd.to_datetime(["2021-01-06"]),
            "direction_long_front": [1],
            "front_entry": [30.0],
            "next_entry": [32.0],
            "front_exit": [32.0],
            "next_exit": [31.0],
            "point_value_proxy": [100.0],
            "contracts_each_leg": [2],
            "exit_reason": ["take_profit"],
        }
    )
    counts = {"signals": 1, "entry_rejections": 0, "unresolved_exits": 0}

    ledger, metrics = v45.evaluate(protocol, trades, counts, state)

    assert ledger.loc[2, "primary_nav"] > ledger.loc[2, "doubled_nav"]
    assert ledger.loc[2, "doubled_nav"] > ledger.loc[2, "stress_nav"]
    assert metrics["scenarios"]["primary"]["net_pnl_rub"] == 520.0
    assert metrics["live_trading_allowed"] is False
