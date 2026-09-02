"""Tests for sealed V43 V39 plus broad cash-carry RUONIA blends."""

from __future__ import annotations

import pandas as pd

import market_lab.futures_v43_v39_broad_carry_ruonia_stability as v43


def test_protocol_parents_views_scenarios_and_weights_are_exact() -> None:
    protocol = v43.load_protocol()

    assert protocol.config_sha256 == v43.CONFIG_SHA256
    assert protocol.v39_root.exists()
    assert protocol.cash_root.exists()
    assert protocol.benchmark_root.exists()
    assert tuple(protocol.payload["views"]) == v43.VIEWS
    assert tuple(protocol.payload["scenario_mapping"]) == tuple(v43.SCENARIOS)
    assert protocol.payload["inheritance"]["view_selection_after_outcome"] == "forbidden"


def test_broad_cash_parent_covers_exact_v39_boundary() -> None:
    protocol = v43.load_protocol()
    cash = pd.read_parquet(protocol.cash_root / "daily_ledger.parquet", columns=["date"])

    dates = pd.to_datetime(cash["date"])
    assert dates.min() == pd.Timestamp("2020-12-30")
    assert dates.max() == pd.Timestamp("2025-12-30")
