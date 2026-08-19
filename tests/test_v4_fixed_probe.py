"""Bystrye proverki fiksirovannyh pravil i causalnosti v4-probe."""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.testing import assert_series_equal

from scripts.v4_fixed_probe import (
    RULE_COUNT,
    RULE_DEFINITIONS,
    build_fixed_predictions,
    outer_fold_masks,
)

EXPECTED_RULES = (  # Etalonnyi poryadok pyatnadcati pravil bez post-hoc rasshireniya.
    "mom20",
    "mom60",
    "mom120",
    "mom_blend",
    "mom60_skip5",
    "quality_momentum",
    "relative_momentum",
    "reversal1",
    "reversal5",
    "low_vol20",
    "volume_momentum",
    "breakout60",
    "blend_imoex_gate",
    "blend_rvi_gate",
    "blend_imoex_rvi_gate",
)


def _synthetic_panel(session_count: int = 140) -> pd.DataFrame:
    """Stroit malyi polnyi panel s razlichimymi aktivami i budushchimi vybrosami."""
    dates = pd.bdate_range("2020-01-01", periods=session_count)
    parts: list[pd.DataFrame] = []
    for ticker_number, ticker in enumerate(("AAA", "BBB", "CCC", "DDD"), start=1):
        step = np.arange(session_count, dtype=float)
        base = 100.0 + ticker_number * 4.0 + step * (0.05 + ticker_number * 0.01)
        close = base * (1.0 + 0.01 * np.sin(step / (3.0 + ticker_number)))
        close_series = pd.Series(close)
        returns = {
            horizon: close_series.pct_change(horizon).to_numpy()
            for horizon in (1, 5, 20, 60, 120)
        }
        parts.append(
            pd.DataFrame(
                {
                    "session_date": dates,
                    "ticker": ticker,
                    "return_1": returns[1],
                    "return_5": returns[5],
                    "return_20": returns[20],
                    "return_60": returns[60],
                    "return_120": returns[120],
                    "volatility_20": 0.01 + ticker_number * 0.001 + step * 1e-6,
                    "volatility_60": 0.015 + ticker_number * 0.001 + step * 1e-6,
                    "volume_z_20": np.sin(step / 7.0) + ticker_number * 0.05,
                    "raw_high": close * (1.01 + ticker_number * 0.0001),
                    "raw_close": close,
                    "context_ctx_imoex_ret_20": np.sin(step / 15.0) * 0.03,
                    "context_ctx_rvi_ret_20": np.cos(step / 13.0) * 0.05,
                }
            )
        )
    return pd.concat(parts, ignore_index=True)


def test_rule_definitions_are_exactly_frozen() -> None:
    """Fiksiruet chislo, imena, poryadok i klyuchevye formuly probe."""
    assert RULE_COUNT == 15
    assert tuple(RULE_DEFINITIONS) == EXPECTED_RULES
    assert RULE_DEFINITIONS["mom_blend"] == (
        "0.50*return_20 + 0.30*return_60 + 0.20*return_120"
    )
    assert RULE_DEFINITIONS["breakout60"] == "raw_close/previous_60_session_high-1"


def test_predictions_do_not_change_when_future_sessions_are_appended() -> None:
    """Dokazyvaet invariantnost proshlyh score k dobavleniyu ekstremal'nogo budushchego."""
    panel = _synthetic_panel()
    boundary = pd.Timestamp("2020-05-29")
    past = panel.loc[pd.to_datetime(panel["session_date"]).le(boundary)].copy()
    future_mask = pd.to_datetime(panel["session_date"]).gt(boundary)
    altered = panel.copy()
    altered.loc[future_mask, "raw_high"] *= 100.0
    altered.loc[future_mask, "raw_close"] *= 50.0
    altered.loc[future_mask, "return_20"] += 10.0
    altered.loc[future_mask, "return_60"] -= 10.0
    altered.loc[future_mask, "context_ctx_imoex_ret_20"] *= -100.0
    prefix_predictions = build_fixed_predictions(past)
    full_predictions = build_fixed_predictions(altered)
    for rule in EXPECTED_RULES:
        expected = prefix_predictions[rule].sort_values(
            ["ticker", "session_date"], kind="mergesort"
        )
        actual = full_predictions[rule].loc[
            pd.to_datetime(full_predictions[rule]["session_date"]).le(boundary)
        ].sort_values(["ticker", "session_date"], kind="mergesort")
        assert_series_equal(
            expected["prediction"].reset_index(drop=True),
            actual["prediction"].reset_index(drop=True),
            check_names=False,
        )


def test_outer_fold_mask_purges_signals_whose_exit_is_outside_fold() -> None:
    """Proveryaet chto poslednie signaly ne ostavlyayut pozicii pri sbrose fold."""
    sessions = pd.bdate_range("2022-12-19", "2022-12-30")
    panel = pd.DataFrame(
        {
            "session_date": sessions,
            "exit_time": pd.to_datetime(sessions + pd.offsets.BDay(6))
            .tz_localize("Europe/Moscow")
            .tz_convert("UTC"),
        }
    )
    fold = type(
        "Fold",
        (),
        {
            "outer_start": pd.Timestamp("2022-01-01").date(),
            "outer_end": pd.Timestamp("2022-12-31").date(),
        },
    )()
    execution_mask, signal_mask = outer_fold_masks(panel, fold)
    assert execution_mask.all()
    assert signal_mask.sum() < execution_mask.sum()
    assert pd.to_datetime(panel.loc[signal_mask, "exit_time"], utc=True).lt(
        pd.Timestamp("2023-01-01 09:50", tz="Europe/Moscow").tz_convert("UTC")
    ).all()
