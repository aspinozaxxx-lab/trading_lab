"""Causality and protocol tests for V12 core-four correlation trend."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas.testing as pdt

from market_lab.futures_v12_core4_correlation_trend import (
    ASSETS,
    CONFIG_PATH,
    CONFIG_SHA256,
    build_execution_targets,
    build_trend_scores,
    load_protocol,
    sha256_file,
    weekly_score_snapshots,
)


def _panel(periods: int = 430) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-02", periods=periods)
    rows: list[dict[str, object]] = []
    slopes = {"SI": 0.0005, "RI": -0.0003, "BR": 0.0008, "MIX": 0.0002}
    aliases = {"SI": "Si", "RI": "RTS", "BR": "BR", "MIX": "MIX"}
    for asset in ASSETS:
        steps = np.arange(periods, dtype=float)
        close = 100.0 * np.exp(slopes[asset] * steps + 0.002 * np.sin(steps / 11.0))
        for trade_date, value in zip(dates, close, strict=True):
            rows.append(
                {
                    "trade_date": trade_date,
                    "asset_code": aliases[asset],
                    "close": value,
                }
            )
    return pd.DataFrame(rows)


def _active_map(dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, decision_date in enumerate(dates):
        effective_date = decision_date + pd.offsets.BDay(1)
        for asset in ASSETS:
            contract = f"{asset}:H4" if index < 2 else f"{asset}:M4"
            rows.append(
                {
                    "decision_date": decision_date,
                    "effective_date": effective_date,
                    "observed_through": decision_date,
                    "asset_code": asset,
                    "contract_id": contract,
                    "plan_tradable": True,
                    "roll": index == 2,
                }
            )
    return pd.DataFrame(rows)


def test_protocol_hash_and_frozen_economics() -> None:
    assert sha256_file(CONFIG_PATH) == CONFIG_SHA256
    protocol = load_protocol()
    assert protocol["signal"]["log_momentum_horizons_sessions"] == [21, 63, 126, 252]
    assert protocol["portfolio"]["annual_target_volatility"] == 0.20
    assert protocol["execution"]["maximum_participation"] == 0.01
    assert protocol["dates"]["forbidden_from"] == "2026-01-01"


def test_trend_score_is_causal_and_future_mutation_is_inert() -> None:
    panel = _panel()
    baseline = build_trend_scores(panel)
    cutoff = pd.Timestamp("2024-08-30")
    mutated = panel.copy()
    future = pd.to_datetime(mutated["trade_date"]).gt(cutoff)
    mutated.loc[future, "close"] *= np.linspace(1.0, 50.0, int(future.sum()))
    revised = build_trend_scores(mutated)
    columns = ["decision_date", "asset", "candidate_score"]
    pdt.assert_frame_equal(
        baseline.loc[baseline["decision_date"].le(cutoff), columns].reset_index(drop=True),
        revised.loc[revised["decision_date"].le(cutoff), columns].reset_index(drop=True),
    )


def test_missing_observation_invalidates_scores_instead_of_zero_imputation() -> None:
    panel = _panel()
    missing_date = pd.Timestamp(panel["trade_date"].drop_duplicates().iloc[300])
    mask = panel["trade_date"].eq(missing_date) & panel["asset_code"].eq("BR")
    panel.loc[mask, "close"] = np.nan
    scores = build_trend_scores(panel)
    affected = scores.loc[
        scores["asset"].eq("BR")
        & scores["decision_date"].between(missing_date, missing_date + pd.offsets.BDay(21))
    ]
    assert affected["candidate_score"].isna().all()


def test_weekly_snapshot_uses_last_factual_session() -> None:
    scores = build_trend_scores(_panel())
    weekly = weekly_score_snapshots(scores)
    selected = pd.DatetimeIndex(weekly["decision_date"].drop_duplicates())
    all_dates = pd.DatetimeIndex(scores["decision_date"].drop_duplicates())
    expected = pd.Series(all_dates, index=all_dates).groupby(
        all_dates.to_period("W-SUN")
    ).max()
    assert selected.equals(pd.DatetimeIndex(expected.to_numpy()))
    assert weekly.groupby("decision_date")["asset"].nunique().eq(4).all()


def test_roll_adds_event_without_changing_carried_weights() -> None:
    decision_dates = pd.bdate_range("2024-01-08", periods=4)
    weekly_rows = []
    weights = {"SI": 0.30, "RI": -0.20, "BR": 0.25, "MIX": -0.15}
    for asset, weight in weights.items():
        weekly_rows.append(
            {
                "decision_date": decision_dates[0],
                "asset": asset,
                "target_weight": weight,
                "provenance": "synthetic_weekly",
            }
        )
    built = build_execution_targets(
        pd.DataFrame(weekly_rows),
        _active_map(decision_dates),
        oos_start=pd.Timestamp("2024-01-01"),
        oos_end=pd.Timestamp("2024-12-31"),
    )
    assert built.weekly_decisions == 1
    assert built.roll_decisions == 1
    assert built.decision_audit["decision_date"].tolist() == [
        decision_dates[0],
        decision_dates[2],
    ]
    roll = built.targets.loc[built.targets["decision_date"].eq(decision_dates[2])]
    assert roll.set_index("asset_code")["target_weight"].to_dict() == weights
    assert roll["effective_date"].eq(decision_dates[2] + pd.offsets.BDay(1)).all()
