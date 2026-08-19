"""Testy causal'nogo sleeping-experts router bez budushchih intervalov."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.specialist_router import (
    SPECIALIST_NAMES,
    CausalSleepingSpecialistRouter,
    SpecialistRouterConfig,
    build_causal_specialist_targets,
)

TEST_ASSETS = ("SI", "RI", "BR", "MIX")  # Synthetic common-session universe.


def _router_panel(periods: int = 90, news_wakeup: int = 40) -> pd.DataFrame:
    """Stroit determinirovannyi panel s obyazatel'nym CBR i sleeping kanalami."""
    dates = pd.bdate_range("2024-01-03", periods=periods)
    rows: list[dict[str, object]] = []
    for asset_index, asset in enumerate(TEST_ASSETS):
        open_price = 100.0 + 20.0 * asset_index
        for index, trading_date in enumerate(dates):
            open_price *= 1.0 + 0.002 * np.sin((index + 2 * asset_index) / 6.0)
            rows.append(
                {
                    "trade_date": trading_date,
                    "asset_code": asset,
                    "open": open_price,
                    "target_score": float(np.tanh(np.sin((index + asset_index) / 8.0))),
                    "cbr_macro_score": float(
                        np.tanh(np.cos((index + 3 * asset_index) / 11.0))
                    ),
                    "cftc_score": float(
                        np.tanh(np.sin((index + 5 * asset_index) / 13.0))
                    ),
                    "filings_score": np.nan,
                    "news_score": (
                        np.nan
                        if index < news_wakeup
                        else float(np.tanh(np.cos((index + asset_index) / 5.0)))
                    ),
                }
            )
    return pd.DataFrame(rows)


def _sorted(frame: pd.DataFrame) -> pd.DataFrame:
    """Sortiruet router output dlya strogogo sravneniya."""
    return frame.sort_values(["trade_date", "asset_code"]).reset_index(drop=True)


def test_router_emits_bounded_targets_and_full_provenance() -> None:
    """Proveryaet universe, score/gross granicy i sleeping weight provenance."""
    result = build_causal_specialist_targets(_router_panel())
    assert set(result["asset_code"]) == set(TEST_ASSETS)
    assert result.groupby("trade_date")["asset_code"].nunique().eq(4).all()
    assert result["router_target_score"].between(-1.0, 1.0).all()
    gross = result.groupby("trade_date")["target_weight"].apply(lambda value: value.abs().sum())
    assert (gross <= 1.0 + 1e-12).all()
    assert (result["target_session_offset"] == 1).all()
    weight_columns = [f"router_weight_{name}" for name in SPECIALIST_NAMES]
    np.testing.assert_allclose(result[weight_columns].sum(axis=1), 1.0)
    assert result["router_available_base"].all()
    assert result["router_available_cbr_macro"].all()
    assert not result["router_available_filings"].any()
    assert (result["router_weight_filings"] == 0.0).all()
    required = {
        f"router_{kind}_{name}"
        for name in SPECIALIST_NAMES
        for kind in (
            "score",
            "available",
            "weight",
            "loss",
            "loss_observations",
            "cumulative_observations",
        )
    }
    assert required <= set(result.columns)


def test_router_is_ticker_agnostic_and_deterministic() -> None:
    """Proveryaet obshchie weights pri odinakovoi dostupnosti i nezavisimost' ot poryadka."""
    panel = _router_panel()
    router = CausalSleepingSpecialistRouter()
    first = router.predict(panel)
    shuffled = router.predict(panel.sample(frac=1.0, random_state=42))
    pd.testing.assert_frame_equal(_sorted(first), _sorted(shuffled))
    wake_date = pd.Timestamp(sorted(panel["trade_date"].unique())[45])
    snapshot = first.loc[first["trade_date"] == wake_date]
    for specialist in SPECIALIST_NAMES:
        assert snapshot[f"router_weight_{specialist}"].nunique() == 1


def test_future_mutation_cannot_rewrite_router_history() -> None:
    """Proveryaet, chto budushchie open i specialist scores ne menyayut proshloe."""
    panel = _router_panel()
    dates = pd.DatetimeIndex(panel["trade_date"].drop_duplicates().sort_values())
    cutoff = pd.Timestamp(dates[60])
    baseline = build_causal_specialist_targets(panel)
    changed = panel.copy()
    future = changed["trade_date"] > cutoff
    changed.loc[future, "open"] *= 1.25
    changed.loc[future, ["target_score", "cbr_macro_score", "cftc_score"]] *= -1.0
    changed.loc[future, "news_score"] = 0.95
    revised = build_causal_specialist_targets(changed)
    pd.testing.assert_frame_equal(
        baseline.loc[baseline["trade_date"] <= cutoff].reset_index(drop=True),
        revised.loc[revised["trade_date"] <= cutoff].reset_index(drop=True),
    )


def test_appending_sessions_is_byte_stable_for_existing_router_output() -> None:
    """Proveryaet append-only invariant expanding router."""
    panel = _router_panel()
    dates = pd.DatetimeIndex(panel["trade_date"].drop_duplicates().sort_values())
    cutoff = pd.Timestamp(dates[64])
    prefix = panel.loc[panel["trade_date"] <= cutoff].copy()
    prefix_result = build_causal_specialist_targets(prefix)
    full_result = build_causal_specialist_targets(panel)
    pd.testing.assert_frame_equal(
        prefix_result,
        full_result.loc[full_result["trade_date"] <= cutoff].reset_index(drop=True),
    )


def test_sleeping_specialist_wakes_without_hindsight_loss() -> None:
    """Proveryaet nulevoi weight vo sne i polozhitel'nyi weight do pervogo feedback."""
    wakeup = 40
    panel = _router_panel(news_wakeup=wakeup)
    dates = pd.DatetimeIndex(panel["trade_date"].drop_duplicates().sort_values())
    result = build_causal_specialist_targets(panel)
    before = result.loc[result["trade_date"] < dates[wakeup]]
    assert not before["router_available_news"].any()
    assert (before["router_weight_news"] == 0.0).all()
    wake = result.loc[result["trade_date"] == dates[wakeup]]
    assert wake["router_available_news"].all()
    assert (wake["router_weight_news"] > 0.0).all()
    assert wake["router_loss_news"].isna().all()
    assert (wake["router_loss_observations_news"] == 0).all()
    first_feedback = result.loc[result["trade_date"] == dates[wakeup + 2]]
    assert first_feedback["router_loss_news"].notna().all()
    assert (first_feedback["router_loss_observations_news"] == 4).all()


def test_feedback_timing_is_exact_two_step_open_interval() -> None:
    """Proveryaet signal D-2, entry D-1, exit D i update vesov uzhe na D."""
    panel = _router_panel()
    dates = pd.DatetimeIndex(panel["trade_date"].drop_duplicates().sort_values())
    current_index = 55
    current_date = pd.Timestamp(dates[current_index])
    baseline = build_causal_specialist_targets(panel)
    day = baseline.loc[baseline["trade_date"] == current_date]
    assert day["router_feedback_signal_date"].eq(dates[current_index - 2]).all()
    assert day["router_feedback_entry_date"].eq(dates[current_index - 1]).all()
    assert day["router_feedback_exit_date"].eq(current_date).all()
    changed = panel.copy()
    current_si = changed["trade_date"].eq(current_date) & changed["asset_code"].eq("SI")
    entry_open = float(
        changed.loc[
            changed["trade_date"].eq(dates[current_index - 1])
            & changed["asset_code"].eq("SI"),
            "open",
        ].iloc[0]
    )
    changed.loc[current_si, "open"] = entry_open * 0.9
    revised = build_causal_specialist_targets(changed)
    pd.testing.assert_frame_equal(
        baseline.loc[baseline["trade_date"] < current_date].reset_index(drop=True),
        revised.loc[revised["trade_date"] < current_date].reset_index(drop=True),
    )
    revised_day = revised.loc[revised["trade_date"] == current_date]
    assert not np.allclose(
        day["router_loss_base"],
        revised_day["router_loss_base"],
        equal_nan=True,
    )
    assert (
        day["router_weight_base"].to_numpy()
        != revised_day["router_weight_base"].to_numpy()
    ).any()


def test_missing_open_does_not_bridge_feedback_interval() -> None:
    """Proveryaet propusk entry/exit odnogo asset bez poiska bolee starogo open."""
    panel = _router_panel()
    dates = pd.DatetimeIndex(panel["trade_date"].drop_duplicates().sort_values())
    current_index = 55
    missing_entry = panel["trade_date"].eq(dates[current_index - 1]) & panel[
        "asset_code"
    ].eq("SI")
    damaged = panel.copy()
    damaged.loc[missing_entry, "open"] = np.nan
    result = build_causal_specialist_targets(damaged)
    current = result.loc[result["trade_date"] == dates[current_index]]
    following = result.loc[result["trade_date"] == dates[current_index + 1]]
    for specialist in ("base", "cbr_macro", "cftc", "news"):
        assert (current[f"router_loss_observations_{specialist}"] == 3).all()
        assert (following[f"router_loss_observations_{specialist}"] == 4).all()
    assert (current["router_loss_observations_filings"] == 0).all()
    missing_exit = panel["trade_date"].eq(dates[current_index]) & panel[
        "asset_code"
    ].eq("SI")
    exit_damaged = panel.copy()
    exit_damaged.loc[missing_exit, "open"] = np.nan
    exit_result = build_causal_specialist_targets(exit_damaged)
    exit_day = exit_result.loc[exit_result["trade_date"] == dates[current_index]]
    entry_day = exit_result.loc[exit_result["trade_date"] == dates[current_index + 1]]
    recovered = exit_result.loc[exit_result["trade_date"] == dates[current_index + 2]]
    for specialist in ("base", "cbr_macro", "cftc", "news"):
        assert (exit_day[f"router_loss_observations_{specialist}"] == 3).all()
        assert (entry_day[f"router_loss_observations_{specialist}"] == 3).all()
        assert (recovered[f"router_loss_observations_{specialist}"] == 4).all()


def test_router_schema_and_ranges_fail_closed() -> None:
    """Proveryaet obyazatel'nyi CBR, polnyi universe i dopustimye score granicy."""
    panel = _router_panel()
    absent_optional = panel.drop(columns=["cftc_score", "filings_score", "news_score"])
    optional_result = build_causal_specialist_targets(absent_optional)
    for specialist in ("cftc", "filings", "news"):
        assert not optional_result[f"router_available_{specialist}"].any()
        assert (optional_result[f"router_weight_{specialist}"] == 0.0).all()
    with pytest.raises(ValueError, match="cbr_macro_score"):
        build_causal_specialist_targets(panel.drop(columns="cbr_macro_score"))
    sleeping_cbr = panel.copy()
    sleeping_cbr.loc[sleeping_cbr.index[0], "cbr_macro_score"] = np.nan
    with pytest.raises(ValueError, match="cbr_macro"):
        build_causal_specialist_targets(sleeping_cbr)
    missing_asset = panel.loc[
        ~(
            panel["trade_date"].eq(panel["trade_date"].min())
            & panel["asset_code"].eq("BR")
        )
    ]
    with pytest.raises(ValueError, match="Nepolnyi router asset snapshot"):
        build_causal_specialist_targets(missing_asset)
    outside = panel.copy()
    outside.loc[outside.index[0], "target_score"] = 1.1
    with pytest.raises(ValueError, match=r"\[-1, 1\]"):
        build_causal_specialist_targets(outside)


def test_router_config_rejects_noncausal_or_unbounded_values() -> None:
    """Proveryaet fixed config granicy bez skrytoi leverage-optimizacii."""
    with pytest.raises(ValueError, match="learning_rate"):
        SpecialistRouterConfig(learning_rate=0.0)
    with pytest.raises(ValueError, match="exploration"):
        SpecialistRouterConfig(exploration=1.0)
    with pytest.raises(ValueError, match="maximum_gross"):
        SpecialistRouterConfig(maximum_gross=1.1)
