"""Tests for causal core-four Type B BBO reconstruction."""

from __future__ import annotations

import pandas as pd

from market_lab.futures import moex_type_b_core4_bbo_derived_v1 as subject


def _events() -> pd.DataFrame:
    rows = [
        ["best_quote_update", "B", pd.NA, 100.0, 3],
        ["best_quote_update", "S", pd.NA, 110.0, 4],
        ["trade", "B", 10, 110.0, 1],
        ["best_quote_clear", "S", pd.NA, pd.NA, pd.NA],
        ["trade", "S", 11, 100.0, 2],
    ]
    frame = pd.DataFrame(rows, columns=["event_kind", "side", "trade_id", "price", "volume"])
    frame["source_date"] = pd.Timestamp("2024-10-01")
    frame["event_at_moscow"] = pd.date_range(
        "2024-09-30T19:00:00+03:00", periods=len(frame), freq="1s"
    )
    frame["original_row_number"] = range(1, len(frame) + 1)
    frame["secid"] = "SiTest"
    frame["logical_asset"] = "SI"
    frame["strike"] = 100.0
    frame["option_type"] = "Call"
    frame["option_system"] = "C"
    return frame.loc[:, subject.EVENT_COLUMNS]


def test_protocol_seal_is_exact() -> None:
    config = subject.load_config()
    assert config["identity_parent"]["identity_date"] == "2024-09-27"


def test_state_machine_uses_strictly_prior_trade_context_and_clear() -> None:
    deals = {
        10: ("SiTest", "B", "SI", 5),
        11: ("SiTest", "S", "SI", 4),
    }
    state, trades = subject.apply_state_machine(_events(), {}, deals)
    assert state.loc[1, "two_sided"]
    assert trades.loc[0, "prior_bid_price"] == 100.0
    assert trades.loc[0, "prior_offer_price"] == 110.0
    assert trades.loc[0, "trade_at_or_above_prior_offer"]
    assert pd.isna(state.loc[3, "offer_price"])
    assert not state.loc[3, "two_sided"]
    assert pd.isna(trades.loc[1, "prior_offer_price"])
    assert pd.isna(trades.loc[1, "trade_inside_prior_spread"])


def test_trade_does_not_mutate_quote_state() -> None:
    deals = {
        10: ("SiTest", "B", "SI", 5),
        11: ("SiTest", "S", "SI", 4),
    }
    state, _ = subject.apply_state_machine(_events(), {}, deals)
    assert state.loc[2, "bid_price"] == state.loc[1, "bid_price"]
    assert state.loc[2, "offer_price"] == state.loc[1, "offer_price"]
