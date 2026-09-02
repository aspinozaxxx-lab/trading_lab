"""Tests for MOEX Type B V3 quote-clear semantics."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab.futures import moex_type_b_derivatives_sample_source_v3 as subject


def _row(*, deal_id: str = "", price: str = "310", volume: str = "1") -> pd.DataFrame:
    return pd.DataFrame(
        [["Si90000BX4", "P", "B", "20240930185801437", deal_id, price, volume]],
        columns=subject.parent.TICK_HEADER,
    )


def test_v3_protocol_seal_is_exact() -> None:
    assert subject.load_config()["protocol_id"].endswith("_v3")


def test_null_pair_is_quote_clear() -> None:
    result = subject.normalize_tick_chunk(
        _row(price="null", volume="null"), 7, subject._compat_config()
    )
    assert result.loc[0, "event_kind"] == "best_quote_clear"
    assert result.loc[0, "original_row_number"] == 7
    assert pd.isna(result.loc[0, "price"])
    assert pd.isna(result.loc[0, "volume"])


def test_one_null_is_rejected() -> None:
    with pytest.raises(ValueError, match="null pair"):
        subject.normalize_tick_chunk(_row(price="null", volume="1"), 1, subject._compat_config())


def test_trade_with_null_is_rejected() -> None:
    with pytest.raises(ValueError, match="trade cannot clear"):
        subject.normalize_tick_chunk(
            _row(deal_id="1892949931690295433", price="null", volume="null"),
            1,
            subject._compat_config(),
        )
