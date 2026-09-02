"""Tests for strict-prior timestamp-block BBO context."""

from __future__ import annotations

import pandas as pd

from market_lab.futures import moex_type_b_core4_bbo_derived_v1 as parent
from market_lab.futures import moex_type_b_core4_bbo_derived_v2 as subject


def _row(
    row_number: int,
    timestamp: str,
    event_kind: str,
    side: str,
    price: float | None,
    volume: int | None,
    trade_id: int | None = None,
) -> tuple[object, ...]:
    return (
        pd.Timestamp("2024-10-01"),
        pd.Timestamp(timestamp),
        row_number,
        "SiTest",
        "SI",
        100.0,
        "Call",
        "C",
        side,
        event_kind,
        trade_id,
        price,
        volume,
    )


def test_protocol_seal_is_exact() -> None:
    assert subject.load_config()["protocol_id"].endswith("_v2")


def test_same_timestamp_crossing_quote_is_not_trade_context() -> None:
    old = pd.Timestamp("2024-09-30T19:00:00+03:00")
    states = {"SiTest": parent.QuoteState(90.0, 2, old, 110.0, 3, old)}
    block = [
        _row(10, "2024-09-30T19:01:00+03:00", "best_quote_update", "S", 100.0, 1),
        _row(11, "2024-09-30T19:01:00+03:00", "trade", "B", 100.0, 1, 5),
        _row(12, "2024-09-30T19:01:00+03:00", "best_quote_update", "S", 105.0, 2),
    ]
    state_rows, trades = subject.process_timestamp_block(block, states, {5: ("B", 8)})
    assert trades[0]["prior_bid_price"] == 90.0
    assert trades[0]["prior_offer_price"] == 110.0
    assert trades[0]["trade_inside_prior_spread"]
    assert state_rows[0]["offer_price"] == 105.0


def test_clear_applies_only_to_later_timestamp() -> None:
    old = pd.Timestamp("2024-09-30T19:00:00+03:00")
    states = {"SiTest": parent.QuoteState(90.0, 2, old, 110.0, 3, old)}
    block = [
        _row(10, "2024-09-30T19:01:00+03:00", "best_quote_clear", "S", None, None),
        _row(11, "2024-09-30T19:01:00+03:00", "trade", "B", 110.0, 1, 5),
    ]
    state_rows, trades = subject.process_timestamp_block(block, states, {5: ("B", 8)})
    assert trades[0]["prior_offer_price"] == 110.0
    assert state_rows[0]["offer_price"] is None
