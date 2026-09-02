from __future__ import annotations

import pandas as pd

from market_lab.futures import (
    moex_forward_broad_stock_futures_carry_source_v2 as broad,
)
from market_lab.futures import moex_forward_cross_market_bbo_source_v2 as cross


def test_cross_v2_only_removes_unavailable_depth_reason() -> None:
    config = cross.load_config()
    frame = pd.DataFrame(
        {
            "invalid_reason": [
                "positive_best_depth_missing",
                "crossed_or_locked_quote|positive_best_depth_missing",
                pd.NA,
            ],
            "valid": [False, False, True],
        }
    )

    corrected = cross._remove_unavailable_depth_reasons(frame)

    assert corrected["valid"].tolist() == [True, False, True]
    assert pd.isna(corrected.loc[0, "invalid_reason"])
    assert corrected.loc[1, "invalid_reason"] == "crossed_or_locked_quote"
    assert config["output"]["root"].endswith("v2-delayed")
    assert "15_minutes_delayed" in config["official_sources"]["access_mode"]


def test_broad_v2_keeps_units_quotes_and_clocks_required() -> None:
    config = broad.load_config()
    frame = pd.DataFrame(
        {
            "invalid_reason": [
                "spot_positive_best_depth_missing|futures_positive_best_depth_missing",
                "futures_positive_two_sided_quote_missing|futures_positive_best_depth_missing",
            ],
            "valid": [False, False],
        }
    )

    corrected = broad._remove_unavailable_depth_reasons(frame)

    assert corrected["valid"].tolist() == [True, False]
    assert pd.isna(corrected.loc[0, "invalid_reason"])
    assert corrected.loc[1, "invalid_reason"] == "futures_positive_two_sided_quote_missing"
    assert config["output"]["root"].endswith("v2-delayed")
    assert len(config["universe"]["exact_stock_order"]) == 30
