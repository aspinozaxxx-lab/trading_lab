"""Proverki alpha-paneli, timing, splitov i denezhnogo backtesta."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab.alpha.config import load_alpha_config
from market_lab.alpha.models import validation_periods
from market_lab.alpha.panel import BASE_FEATURE_COLUMNS, build_asset_decisions
from market_lab.alpha.portfolio import StrategySpec, run_portfolio_backtest
from market_lab.alpha.ranker_config import load_ranker_config
from market_lab.alpha.ranker_experiment import build_ranker_weights

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Koren testovogo proekta.


def _hourly_frame(days: int = 140) -> pd.DataFrame:
    """Stroit prostye validnye chasovye svechi po tri bara v den'."""
    business_days = pd.bdate_range("2022-01-03", periods=days, tz="Europe/Moscow")
    timestamps: list[pd.Timestamp] = []
    for day in business_days:
        timestamps.extend(day + pd.Timedelta(hours=hour) for hour in (10, 11, 12))
    index = pd.DatetimeIndex(timestamps).tz_convert("UTC")
    base = 100.0 + np.arange(len(index), dtype=float) * 0.01
    return pd.DataFrame(
        {
            "open": base,
            "high": base + 1.0,
            "low": base - 1.0,
            "close": base + 0.2,
            "volume": np.full(len(index), 1000.0),
            "value": base * 1000.0,
        },
        index=pd.DatetimeIndex(index, name="timestamp"),
    )


def test_alpha_target_uses_two_future_opens() -> None:
    """Proveryaet signal na close, vhod na next open i vyhod na sleduyushchem open."""
    hourly = _hourly_frame()
    decisions = build_asset_decisions(hourly, "TEST")
    row = decisions.iloc[20]
    expected_entry = hourly.iloc[21 * 3]["open"]
    expected_exit = hourly.iloc[22 * 3]["open"]
    assert row["entry_open"] == pytest.approx(expected_entry)
    assert row["exit_open"] == pytest.approx(expected_exit)
    assert row["target_return"] == pytest.approx(expected_exit / expected_entry - 1.0)
    assert row["entry_time"] > row["decision_time"]


def test_alpha_features_do_not_change_from_future_prices() -> None:
    """Proveryaet invariantnost' istoricheskih priznakov k budushchim cenam."""
    original = _hourly_frame()
    changed = original.copy()
    boundary = original.index[130 * 3]
    changed.loc[boundary:, ["open", "high", "low", "close"]] *= 7.0
    first = build_asset_decisions(original, "TEST").set_index("decision_date")
    second = build_asset_decisions(changed, "TEST").set_index("decision_date")
    comparison_date = first.index[125]
    pd.testing.assert_series_equal(
        first.loc[comparison_date, list(BASE_FEATURE_COLUMNS)],
        second.loc[comparison_date, list(BASE_FEATURE_COLUMNS)],
    )


def test_alpha_validation_periods_and_embargo_protocol() -> None:
    """Proveryaet chetyre neperekryvayushchihsya polugodovyh folda."""
    config = load_alpha_config(PROJECT_ROOT / "configs" / "alpha50.yaml")
    periods = validation_periods(config)
    assert periods == [
        (pd.Timestamp("2023-01-01"), pd.Timestamp("2023-06-30")),
        (pd.Timestamp("2023-07-01"), pd.Timestamp("2023-12-31")),
        (pd.Timestamp("2024-01-01"), pd.Timestamp("2024-06-30")),
        (pd.Timestamp("2024-07-01"), pd.Timestamp("2024-12-31")),
    ]
    assert config.protocol.embargo_days == 2
    assert set(config.universe.development).isdisjoint(config.universe.holdout)


def test_alpha_backtest_accounts_for_turnover_cost_and_financing() -> None:
    """Proveryaet 2x-oborot, izderzhki i platu za zaemnyi kapital."""
    config = load_alpha_config(PROJECT_ROOT / "configs" / "alpha50.yaml")
    dates = pd.to_datetime(["2023-01-02", "2023-01-03"])
    rows: list[dict[str, object]] = []
    for date in dates:
        for ticker, score, target in (("A", 3.0, 0.01), ("B", 2.0, 0.01), ("C", 1.0, -0.01)):
            rows.append(
                {
                    "decision_date": date,
                    "ticker": ticker,
                    "target_return": target,
                    "vol_20d": 0.01,
                    "market_ret_20d": 0.02,
                    "score": score,
                }
            )
    panel = pd.DataFrame(rows)
    spec = StrategySpec("test", "momentum", "score", 2, 2.0, True)
    result = run_portfolio_backtest(panel, spec, config.portfolio)
    first = result.ledger.iloc[0]
    expected_cost_fraction = 2.0 * 0.0007 + 0.20 / 252
    assert first["turnover"] == pytest.approx(2.0)
    assert first["gross_return"] == pytest.approx(0.02)
    assert first["net_return"] == pytest.approx(0.02 - expected_cost_fraction)
    assert result.ledger.iloc[1]["turnover"] == pytest.approx(0.0)


def test_alpha_run_is_deterministic_for_fixed_panel() -> None:
    """Proveryaet polnuyu deterministichnost' vesov i equity pravila."""
    config = load_alpha_config(PROJECT_ROOT / "configs" / "alpha50.yaml")
    dates = pd.bdate_range("2023-01-02", periods=20)
    rows = [
        {
            "decision_date": date,
            "ticker": ticker,
            "target_return": 0.001 * (rank - 1),
            "vol_20d": 0.01 + rank * 0.001,
            "market_ret_20d": 0.01,
            "score": float(rank),
        }
        for date in dates
        for rank, ticker in enumerate(("A", "B", "C"), start=1)
    ]
    panel = pd.DataFrame(rows)
    spec = StrategySpec("test", "momentum", "score", 2, 1.0, True)
    first = run_portfolio_backtest(panel, spec, config.portfolio)
    second = run_portfolio_backtest(panel, spec, config.portfolio)
    pd.testing.assert_frame_equal(first.ledger, second.ledger)
    pd.testing.assert_frame_equal(first.weights, second.weights)


def test_ranker_weights_rebalance_and_exit_on_bad_regime() -> None:
    """Proveryaet redkii rebalance i nemedlennyi vyhod v risk-off."""
    config = load_ranker_config(PROJECT_ROOT / "configs" / "alpha50_ranker.yaml")
    dates = pd.bdate_range("2025-01-06", periods=7)
    rows: list[dict[str, object]] = []
    for offset, date in enumerate(dates):
        bad_regime = offset == 2
        for ticker, base_score in (("A", 3.0), ("B", 2.0), ("C", 1.0)):
            score = base_score if offset == 0 else 4.0 - base_score
            rows.append(
                {
                    "decision_date": date,
                    "ticker": ticker,
                    "target_return": 0.001,
                    "ranker_score": score,
                    "vol_20d": 0.01,
                    "ret_20d": -0.01 if bad_regime else 0.01,
                    "ret_60d": 0.05,
                }
            )
    weights = build_ranker_weights(pd.DataFrame(rows), config, leverage=1.0)
    assert weights.loc[dates[0], "A"] == pytest.approx(1.0)
    assert weights.loc[dates[1], "A"] == pytest.approx(1.0)
    assert weights.loc[dates[2]].abs().sum() == pytest.approx(0.0)
    assert weights.loc[dates[3], "C"] == pytest.approx(1.0)
    assert (weights.abs().sum(axis=1) <= 1.0).all()
