"""Causality and seal tests for the V17 EIA physical-balance strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pandas.testing as pdt

from market_lab import futures_v17_eia_supply_demand as v17
from market_lab.futures_v12_core4_correlation_trend import ASSETS


def _eia_frame(periods: int = 300) -> pd.DataFrame:
    releases = pd.date_range("2015-01-07", periods=periods, freq="W-WED")
    rows: list[dict[str, object]] = []
    for release_index, release_date in enumerate(releases):
        available_at = (
            release_date.tz_localize("America/New_York")
            + pd.Timedelta(hours=23, minutes=59, seconds=59)
        ).tz_convert("UTC")
        for component_index, component in enumerate(v17.COMPONENTS):
            value = np.sin(release_index / 5.0) + component_index * 0.07
            rows.append(
                {
                    "release_date": release_date,
                    "available_at": available_at,
                    "data_week_ending": release_date - pd.Timedelta(days=5),
                    "section": component.section,
                    "item": component.item,
                    "reported_weekly_change": value,
                    "raw_sha256": f"{release_index:064x}",
                    "release_specific_archive": True,
                }
            )
    return pd.DataFrame(rows)


def _panel(periods: int = 180) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-02", periods=periods)
    rows: list[dict[str, object]] = []
    aliases = {"SI": "Si", "RI": "RTS", "BR": "BR", "MIX": "MIX"}
    for asset_index, asset in enumerate(ASSETS):
        steps = np.arange(periods, dtype=float)
        close = 100.0 * np.exp(
            0.0002 * steps + 0.006 * np.sin(steps / (5.0 + asset_index))
        )
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
    for decision_date, effective_date in zip(dates[:-1], dates[1:], strict=True):
        for asset in ASSETS:
            rows.append(
                {
                    "decision_date": decision_date,
                    "effective_date": effective_date,
                    "observed_through": decision_date,
                    "asset_code": asset,
                    "contract_id": f"{asset}:Z3",
                    "plan_tradable": True,
                    "roll": False,
                }
            )
    return pd.DataFrame(rows)


def test_protocol_hash_and_signal_economics_are_frozen() -> None:
    assert v17.sha256_file(v17.CONFIG_PATH) == v17.CONFIG_SHA256
    protocol = v17.load_protocol()

    assert len(protocol["signal"]["components"]) == 7
    assert protocol["signal"]["trade_threshold"] == "none"
    assert protocol["portfolio"]["annual_target_volatility"] == 0.20
    assert protocol["information_set"]["no_zero_imputation"] is True


def test_source_score_is_prior_only_and_future_mutation_is_inert() -> None:
    source = _eia_frame()
    baseline = v17.build_source_scores(source)
    cutoff = baseline.loc[baseline.index[220], "release_date"]
    mutated = source.copy()
    future = pd.to_datetime(mutated["release_date"]).gt(cutoff)
    mutated.loc[future, "reported_weekly_change"] *= 1000.0
    revised = v17.build_source_scores(mutated)

    columns = [
        "release_date",
        *[f"z_{component.name}" for component in v17.COMPONENTS],
        "composite",
        "direction",
    ]
    pdt.assert_frame_equal(
        baseline.loc[baseline["release_date"].le(cutoff), columns].reset_index(drop=True),
        revised.loc[revised["release_date"].le(cutoff), columns].reset_index(drop=True),
    )


def test_missing_component_makes_whole_release_sleep_without_zero_imputation() -> None:
    source = _eia_frame()
    missing_release = pd.Timestamp(source["release_date"].drop_duplicates().iloc[200])
    mask = source["release_date"].eq(missing_release) & source["item"].eq(
        v17.COMPONENTS[0].item
    )

    scores = v17.build_source_scores(source.loc[~mask])
    row = scores.loc[scores["release_date"].eq(missing_release)].iloc[0]

    assert row["component_rows"] == 6
    assert not row["eligible"]
    assert pd.isna(row["composite"])
    assert pd.isna(row["direction"])


def test_equal_positive_shocks_respect_predeclared_bearish_supply_majority() -> None:
    source = _eia_frame()
    last_release = source["release_date"].max()
    source.loc[source["release_date"].eq(last_release), "reported_weekly_change"] = 10.0

    scores = v17.build_source_scores(source)
    last = scores.iloc[-1]

    assert last["eligible"]
    assert last["composite"] < 0.0
    assert last["direction"] == -1.0


def test_release_waits_for_completed_session_and_builds_only_BR_risk() -> None:
    panel = _panel()
    dates = pd.DatetimeIndex(panel["trade_date"].drop_duplicates().sort_values())
    release_date = dates[120]
    available_at = (
        release_date.tz_localize("America/New_York")
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).tz_convert("UTC")
    scores = pd.DataFrame(
        [
            {
                "release_date": release_date,
                "available_at": available_at,
                "data_week_ending": release_date - pd.Timedelta(days=5),
                "component_rows": len(v17.COMPONENTS),
                "eligible": True,
                "composite": 0.75,
                "direction": 1.0,
                "normalization_history_count": 200,
            }
        ]
    )

    built = v17.build_release_decisions(scores, panel, _active_map(dates))

    assert built.mapped_release_count == 1
    decision = built.decisions.iloc[0]
    assert decision["decision_at"] >= decision["available_at"]
    assert decision["decision_date"] >= available_at.tz_convert("Europe/Moscow").tz_localize(
        None
    ).normalize()
    weights = built.weights.set_index("asset")["target_weight"]
    assert 0.0 < weights["BR"] <= 1.0
    assert weights.drop("BR").eq(0.0).all()
