"""Testy fair causal sleeping-specialist router futures-v7."""

from __future__ import annotations

import numpy as np
import pandas as pd

from market_lab.futures.specialist_router import (
    CausalSleepingSpecialistRouter,
    SpecialistRouterConfig,
)
from market_lab.futures.v7_router import (
    V7_ROUTER_VERSION,
    V7SpecialistRouterConfig,
    build_causal_v7_specialist_targets,
)

ASSETS = ("SI", "RI", "BR", "MIX")


def _panel(days: int = 14, *, cftc_wake: int | None = None) -> pd.DataFrame:
    """Stroit rastushchii open panel gde base sistematicheski luchshe macro."""
    dates = pd.bdate_range("2024-01-02", periods=days)
    rows: list[dict[str, object]] = []
    for offset, date in enumerate(dates):
        for asset_index, asset in enumerate(ASSETS):
            rows.append(
                {
                    "trade_date": date,
                    "asset_code": asset,
                    "open": 100.0 + offset * (1.0 + asset_index * 0.1),
                    "target_score": 0.8,
                    "cbr_macro_score": -0.5,
                    "cftc_score": 0.0 if cftc_wake is not None and offset >= cftc_wake else np.nan,
                    "filings_score": np.nan,
                    "news_score": np.nan,
                }
            )
    return pd.DataFrame(rows)


def test_active_only_normalization_learns_instead_of_equal_floor() -> None:
    """Dokazyvaet chto vechno sleeping kanaly ne stachivayut active v ravnye vesa."""
    panel = _panel(days=80, cftc_wake=0)
    old = CausalSleepingSpecialistRouter(
        SpecialistRouterConfig(learning_rate=50.0),
    ).transform(panel)
    result = build_causal_v7_specialist_targets(
        panel,
        V7SpecialistRouterConfig(learning_rate=50.0),
    )
    final = result.loc[result["trade_date"].eq(result["trade_date"].max())]

    assert final["router_weight_base"].gt(final["router_weight_cbr_macro"]).all()
    assert final["router_weight_base"].gt(0.80).all()
    assert final["router_weight_filings"].eq(0.0).all()
    assert final["router_weight_news"].eq(0.0).all()
    old_final = old.loc[old["trade_date"].eq(old["trade_date"].max())]
    np.testing.assert_allclose(old_final["router_weight_base"], 1.0 / 3.0, atol=2e-5)
    assert result["router_version"].eq(V7_ROUTER_VERSION).all()


def test_newly_waking_specialist_gets_fair_current_prior() -> None:
    """Ne daet dolgo sleeping kanalu hindsight-preimushchestvo pri pervom wake."""
    wake = 10
    result = build_causal_v7_specialist_targets(_panel(cftc_wake=wake))
    wake_date = sorted(result["trade_date"].unique())[wake]
    snapshot = result.loc[result["trade_date"].eq(wake_date)]

    assert snapshot["router_available_cftc"].all()
    assert snapshot["router_weight_cftc"].between(0.0, 0.50).all()
    assert snapshot["router_weight_base"].gt(snapshot["router_weight_cftc"]).all()
    sums = snapshot[
        ["router_weight_base", "router_weight_cbr_macro", "router_weight_cftc"]
    ].sum(axis=1)
    np.testing.assert_allclose(sums, 1.0)


def test_future_mutation_does_not_change_router_prefix() -> None:
    """Dokazyvaet append-only i otsutstvie future open/score leakage."""
    panel = _panel(days=16, cftc_wake=8)
    dates = sorted(panel["trade_date"].unique())
    cutoff = dates[9]
    prefix_panel = panel.loc[panel["trade_date"].le(cutoff)].copy()
    expected = build_causal_v7_specialist_targets(prefix_panel)

    mutated = panel.copy()
    future = mutated["trade_date"].gt(cutoff)
    mutated.loc[future, "open"] *= 20.0
    mutated.loc[future, ["target_score", "cbr_macro_score", "cftc_score"]] *= -1.0
    actual = build_causal_v7_specialist_targets(mutated)
    actual = actual.loc[actual["trade_date"].le(cutoff)].reset_index(drop=True)
    pd.testing.assert_frame_equal(expected.reset_index(drop=True), actual)
