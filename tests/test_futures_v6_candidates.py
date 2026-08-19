"""Testy izolirovannoi causal futures-v6 candidate assembly."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.session_timing import legacy_forts_decision_calendar
from market_lab.futures.v6_candidates import (
    V6_ASSETS,
    V6_CANDIDATE_IDS,
    build_causal_v6_candidates,
    build_v6_candidate_portfolio_targets,
)

TEST_PERIODS = 105  # Dostatochnaya istoriya dlya 60-session causal risk okon.


def _development_panel(periods: int = TEST_PERIODS) -> pd.DataFrame:
    """Stroit polnyi determinirovannyi panel s factual OHLC/OI i curve."""
    dates = pd.bdate_range("2023-01-03", periods=periods)
    settings = {
        "SI": (70_000.0, 0.0002, 0.0020),
        "RI": (95_000.0, 0.0004, 0.0026),
        "BR": (75.0, 0.0003, 0.0022),
        "MIX": (3_200.0, 0.00035, 0.0024),
    }
    rows: list[dict[str, object]] = []
    for asset_index, (asset, parameters) in enumerate(settings.items()):
        close, drift, amplitude = parameters
        previous_close = close
        for index, trade_date in enumerate(dates):
            daily_return = drift + amplitude * np.sin(
                (index + 2 * asset_index) / 8.0
            )
            close *= 1.0 + daily_return
            open_price = previous_close * (
                1.0 + 0.0005 * np.cos((index + asset_index) / 7.0)
            )
            rows.append(
                {
                    "trade_date": trade_date,
                    "asset_code": asset,
                    "open": open_price,
                    "high": max(open_price, close) * 1.003,
                    "low": min(open_price, close) * 0.997,
                    "close": close,
                    "volume": 20_000.0 + 100.0 * index + 20.0 * asset_index,
                    "open_interest": 100_000.0 + 250.0 * index + 50.0 * asset_index,
                    "roll_yield": 0.02 * np.sin(index / 17.0 + asset_index),
                    "physical_long": 1_000.0 + 4.0 * index + asset_index,
                    "physical_short": 900.0 + 2.0 * index + asset_index,
                    "legal_long": 1_500.0 + 3.0 * index + asset_index,
                    "legal_short": 1_350.0 + 2.5 * index + asset_index,
                }
            )
            previous_close = close
    return pd.DataFrame(rows)


def _decision_calendar(panel: pd.DataFrame) -> pd.DataFrame:
    """Stroit exact legacy calendar iz common factual session dates."""
    dates = pd.DatetimeIndex(panel["trade_date"].drop_duplicates().sort_values())
    return legacy_forts_decision_calendar(dates)


def _cbr_observations(panel: pd.DataFrame) -> pd.DataFrame:
    """Stroit tri CBR series s publication do close sootvetstvuyushchei sessii."""
    dates = pd.DatetimeIndex(panel["trade_date"].drop_duplicates().sort_values())
    rows: list[dict[str, object]] = []
    bases = {"ruonia": 16.0, "key_rate": 17.0, "usd_rub_official": 90.0}
    for series_index, (series_id, base) in enumerate(bases.items()):
        for index, observation_date in enumerate(dates):
            available_at = (
                observation_date.tz_localize("Europe/Moscow")
                + pd.Timedelta(hours=10)
            ).tz_convert("UTC")
            rows.append(
                {
                    "series_id": series_id,
                    "observation_date": observation_date,
                    "available_at": available_at,
                    "value": base
                    + 0.02 * index
                    + 0.15 * np.sin(index / (5.0 + series_index)),
                }
            )
    return pd.DataFrame(rows)


def _cftc_scores(calendar: pd.DataFrame) -> pd.DataFrame:
    """Stroit prebuilt causal CFTC asset scores s explicit availability proof."""
    rows: list[dict[str, object]] = []
    for date_index, decision in calendar.reset_index(drop=True).iterrows():
        for asset_index, asset in enumerate(V6_ASSETS):
            rows.append(
                {
                    "decision_at": decision["decision_at"],
                    "asset_symbol": asset,
                    "score": float(
                        np.tanh(np.sin((date_index + 3 * asset_index) / 13.0))
                    ),
                    "score_status": "available",
                    "usd_available_at": decision["decision_at"]
                    - pd.Timedelta(hours=1),
                }
            )
    return pd.DataFrame(rows)


def _sort_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """Sortiruet universal'nye scores dlya exact causal sravneniya."""
    return frame.sort_values(
        ["candidate_id", "decision_date", "asset"], kind="mergesort"
    ).reset_index(drop=True)


def test_v6_assembly_emits_exact_candidates_complete_bounded_snapshots() -> None:
    """Proveryaet chetyre kandidata, granicy i isklyuchenie poslednego bara."""
    panel = _development_panel()
    calendar = _decision_calendar(panel)
    bundle = build_causal_v6_candidates(
        panel,
        _cbr_observations(panel),
        calendar,
        cftc_asset_scores=_cftc_scores(calendar),
    )
    scores = bundle.candidate_scores
    assert tuple(scores["candidate_id"].drop_duplicates()) == V6_CANDIDATE_IDS
    assert scores["candidate_score"].between(-1.0, 1.0).all()
    assert scores.groupby(["candidate_id", "decision_date"])["asset"].nunique().eq(4).all()
    dates = pd.DatetimeIndex(panel["trade_date"].drop_duplicates().sort_values())
    assert scores["decision_date"].max() == dates[-2]
    assert dates[-1] not in set(scores["decision_date"])
    assert (scores["decision_at"] < scores["effective_date"].map(
        lambda value: pd.Timestamp(value).tz_localize("Europe/Moscow").tz_convert("UTC")
        + pd.Timedelta(hours=19)
    )).all()
    assert bundle.base_targets.groupby("trade_date")["asset_code"].nunique().eq(4).all()


def test_missing_cftc_is_a_sleeping_specialist_not_a_missing_candidate() -> None:
    """Proveryaet NaN CFTC, nulevoi router weight i polnye final scores."""
    panel = _development_panel()
    bundle = build_causal_v6_candidates(
        panel,
        _cbr_observations(panel),
        _decision_calendar(panel),
    )
    assert bundle.cftc_asset_scores["score"].isna().all()
    assert not bundle.router_targets["router_available_cftc"].any()
    assert bundle.router_targets["router_weight_cftc"].eq(0.0).all()
    assert bundle.candidate_scores["candidate_score"].notna().all()
    provenance = json.loads(
        bundle.candidate_scores.loc[
            bundle.candidate_scores["candidate_id"].eq("specialist_router"),
            "provenance",
        ].iloc[-1]
    )
    assert provenance["cftc_status"] == "sleeping_missing_source"
    assert provenance["router_available_cftc"] is False


def test_future_mutation_cannot_rewrite_any_past_candidate() -> None:
    """Proveryaet panel, CBR i CFTC mutacii posle cutoff bez perepisyvaniya proshlogo."""
    panel = _development_panel()
    calendar = _decision_calendar(panel)
    cbr = _cbr_observations(panel)
    cftc = _cftc_scores(calendar)
    cutoff = pd.Timestamp(calendar["trade_date"].iloc[72])
    baseline = build_causal_v6_candidates(
        panel,
        cbr,
        calendar,
        cftc_asset_scores=cftc,
    ).candidate_scores
    changed_panel = panel.copy()
    future_panel = changed_panel["trade_date"] > cutoff
    changed_panel.loc[future_panel, ["open", "high", "low", "close"]] *= 1.2
    changed_panel.loc[future_panel, ["volume", "open_interest"]] *= 2.0
    changed_panel.loc[future_panel, "roll_yield"] *= -3.0
    changed_cbr = cbr.copy()
    future_cbr = changed_cbr["observation_date"] > cutoff
    changed_cbr.loc[future_cbr, "value"] *= -5.0
    changed_cftc = cftc.copy()
    cutoff_at = calendar.loc[calendar["trade_date"].eq(cutoff), "decision_at"].iloc[0]
    changed_cftc.loc[changed_cftc["decision_at"] > cutoff_at, "score"] *= -1.0
    revised = build_causal_v6_candidates(
        changed_panel,
        changed_cbr,
        calendar,
        cftc_asset_scores=changed_cftc,
    ).candidate_scores
    pd.testing.assert_frame_equal(
        _sort_scores(baseline.loc[baseline["decision_date"] <= cutoff]),
        _sort_scores(revised.loc[revised["decision_date"] <= cutoff]),
    )


def test_appending_future_sessions_preserves_existing_candidate_bytes() -> None:
    """Proveryaet determinirovannyi append-only rezultat dlya starogo prefiksa."""
    full_panel = _development_panel()
    full_calendar = _decision_calendar(full_panel)
    cbr = _cbr_observations(full_panel)
    cftc = _cftc_scores(full_calendar)
    dates = pd.DatetimeIndex(full_panel["trade_date"].drop_duplicates().sort_values())
    prefix_last = dates[82]
    prefix_panel = full_panel.loc[full_panel["trade_date"] <= prefix_last].copy()
    prefix_calendar = _decision_calendar(prefix_panel)
    prefix = build_causal_v6_candidates(
        prefix_panel,
        cbr,
        prefix_calendar,
        cftc_asset_scores=cftc,
    ).candidate_scores
    full = build_causal_v6_candidates(
        full_panel,
        cbr,
        full_calendar,
        cftc_asset_scores=cftc,
    ).candidate_scores
    comparable = full.loc[full["decision_date"] <= dates[81]]
    pd.testing.assert_frame_equal(_sort_scores(prefix), _sort_scores(comparable))


def test_incomplete_snapshot_inexact_calendar_and_future_cftc_fail_closed() -> None:
    """Proveryaet tri vremennyh/shemnyh narusheniya do candidate rascheta."""
    panel = _development_panel()
    calendar = _decision_calendar(panel)
    cbr = _cbr_observations(panel)
    missing_asset = panel.drop(index=panel.index[0])
    with pytest.raises(ValueError, match="Nepolnyi development snapshot"):
        build_causal_v6_candidates(missing_asset, cbr, calendar)
    shifted = calendar.copy()
    shifted.loc[0, "decision_at"] += pd.Timedelta(seconds=1)
    with pytest.raises(ValueError, match="exact legacy mapping"):
        build_causal_v6_candidates(panel, cbr, shifted)
    cftc = _cftc_scores(calendar)
    cftc.loc[0, "usd_available_at"] = cftc.loc[0, "decision_at"] + pd.Timedelta(
        seconds=1
    )
    with pytest.raises(ValueError, match="budushchii timestamp"):
        build_causal_v6_candidates(panel, cbr, calendar, cftc_asset_scores=cftc)


def test_portfolio_helper_uses_same_constructor_for_all_candidates() -> None:
    """Proveryaet exact candidate set i bounded gross posle obshchego risk constructor."""
    panel = _development_panel()
    calendar = _decision_calendar(panel)
    bundle = build_causal_v6_candidates(
        panel,
        _cbr_observations(panel),
        calendar,
        cftc_asset_scores=_cftc_scores(calendar),
    )
    market = panel.rename(
        columns={
            "trade_date": "session_date",
            "asset_code": "asset",
            "close": "adjusted_close",
        }
    )[["session_date", "asset", "adjusted_close"]]
    targets = build_v6_candidate_portfolio_targets(market, bundle)
    assert tuple(targets["candidate_id"].drop_duplicates()) == V6_CANDIDATE_IDS
    assert targets.groupby(["candidate_id", "decision_date"])["asset"].nunique().eq(4).all()
    gross = targets.groupby(["candidate_id", "decision_date"])["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    assert (gross <= 1.0 + 1e-12).all()
    assert targets.groupby("candidate_id").size().nunique() == 1
