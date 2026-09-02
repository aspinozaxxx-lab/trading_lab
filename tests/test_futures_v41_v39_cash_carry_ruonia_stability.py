"""Tests for sealed V41 V39 plus cash-carry RUONIA blend."""

from __future__ import annotations

import pandas as pd

import market_lab.futures_v41_v39_cash_carry_ruonia_stability as v41


def test_protocol_parents_and_inherited_weights_are_exact() -> None:
    protocol = v41.load_protocol()

    assert protocol.config_sha256 == v41.CONFIG_SHA256
    assert protocol.v39_root.exists()
    assert protocol.cash_root.exists()
    assert protocol.payload["inheritance"]["weight_search_after_v40r1"] is False


def test_cash_parent_covers_exact_v39_boundary() -> None:
    protocol = v41.load_protocol()
    cash = pd.read_parquet(protocol.cash_root / "daily_ledger.parquet", columns=["date"])

    dates = pd.to_datetime(cash["date"])
    assert dates.min() == pd.Timestamp("2020-12-30")
    assert dates.max() == pd.Timestamp("2025-12-30")
