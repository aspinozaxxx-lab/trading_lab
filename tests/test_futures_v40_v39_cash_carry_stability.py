"""Tests for the sealed V40 fixed stability blend."""

from __future__ import annotations

import pandas as pd

import market_lab.futures_v40_v39_cash_carry_stability as v40


def test_protocol_parents_and_weights_are_exact() -> None:
    protocol = v40.load_protocol()

    assert protocol.config_sha256 == v40.CONFIG_SHA256
    assert protocol.v39_root.exists()
    assert protocol.cash_root.exists()


def test_metrics_and_annual_returns_use_prior_year_end() -> None:
    dates = pd.to_datetime(["2020-12-30", "2021-01-04", "2021-12-30", "2022-12-30"])
    nav = pd.Series([1.0, 1.1, 1.2, 1.32], index=dates)
    metrics = v40._metrics(nav)

    assert abs(metrics["annual_returns"]["2021"] - 0.2) < 1e-12
    assert abs(metrics["annual_returns"]["2022"] - 0.1) < 1e-12
    assert metrics["maximum_drawdown"] == 0.0
