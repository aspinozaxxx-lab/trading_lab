"""Tests for the official MOEX Type B option sample parser."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab.futures import moex_type_b_derivatives_sample_source_v2 as subject


def test_protocol_seal_and_parent_are_exact() -> None:
    config = subject.load_config()
    assert config["protocol_id"] == "moex_type_b_derivatives_sample_source_v2"
    assert config["live_trading_allowed"] is False


def test_tick_normalization_accepts_previous_evening_and_trade_day() -> None:
    config = subject.load_config()
    raw = pd.DataFrame(
        [
            ["Si90000BX4", "P", "B", "20240930185801437", "", "310.0", "1"],
            [
                "RI100000BV4A",
                "P",
                "S",
                "20241001123456789123",
                "1925038079035310152",
                "950.0",
                "5",
            ],
        ],
        columns=subject.TICK_HEADER,
    )
    result = subject.normalize_tick_chunk(raw, 1, config)
    assert result["original_row_number"].tolist() == [1, 2]
    assert result["event_kind"].tolist() == ["best_quote_update", "trade"]
    assert result["event_at_moscow"].dt.tz is not None
    assert result["trade_id"].isna().tolist() == [True, False]


def test_deal_normalization_is_strict() -> None:
    config = subject.load_config()
    raw = pd.DataFrame(
        [
            [
                "Si93000BJ4",
                "C",
                "20240930190549040",
                "1892949931690295433",
                "987.0",
                "3",
                "0",
                "S",
            ]
        ],
        columns=subject.DEAL_HEADER,
    )
    result = subject.normalize_deal_chunk(raw, 1, config)
    assert result.loc[0, "open_interest"] == 0
    assert result.loc[0, "direction"] == "S"


def test_event_outside_corrected_session_window_fails() -> None:
    config = subject.load_config()
    raw = pd.DataFrame(
        [["Si90000BX4", "P", "B", "20240930120000000", "", "310", "1"]],
        columns=subject.TICK_HEADER,
    )
    with pytest.raises(ValueError, match="source-session window"):
        subject.normalize_tick_chunk(raw, 1, config)
