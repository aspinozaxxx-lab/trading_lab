"""Tests for sealed V44 all-stock breadth governor mechanics."""

from __future__ import annotations

import pandas as pd
import pytest

import market_lab.futures_v44_v41_stock_breadth_governor as v44


def test_protocol_parents_and_fixed_parameters_are_exact() -> None:
    protocol = v44.load_protocol()

    assert protocol.config_sha256 == v44.CONFIG_SHA256
    assert protocol.v41_root.exists()
    assert protocol.stock_root.exists()
    assert len(protocol.v35_config["universe"]["tickers"]) == 30
    assert protocol.payload["breadth"]["return_lookback_sessions"] == 63


def test_state_transition_rebalances_only_when_state_changes() -> None:
    v39 = pd.Series([1.0, 1.10, 1.21, 1.331])
    cash = pd.Series([1.0, 1.01, 1.0201, 1.030301])
    risk_off = pd.Series([False, True, True, False])

    ledger, counts = v44.simulate(v39, cash, risk_off, 5.0)

    assert counts["state_transitions"] == 2
    assert ledger["state_transition"].tolist() == [False, True, False, True]
    assert counts["total_transition_cost_nav_units"] > 0.0
    assert ledger["governed_nav"].gt(0.0).all()
    assert ledger["actual_v39_weight"].between(0.0, 1.0).all()


def test_alignment_uses_strictly_prior_breadth_state() -> None:
    calendar = pd.Series(pd.to_datetime(["2021-01-04", "2021-01-05"]))
    states = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2021-01-04"]),
            "breadth_fraction": [0.2],
            "state_valid": [True],
            "risk_off": [True],
        }
    )

    aligned = v44.align_states(calendar, states)

    assert not bool(aligned.iloc[0]["risk_off"])
    assert bool(aligned.iloc[1]["risk_off"])
    assert pd.isna(aligned.iloc[0]["signal_date"])
    assert aligned.iloc[1]["signal_date"] == pd.Timestamp("2021-01-04")


def test_simulation_rejects_no_inputs_only_by_normal_pandas_errors() -> None:
    with pytest.raises((IndexError, ValueError)):
        v44.simulate(pd.Series(dtype=float), pd.Series(dtype=float), pd.Series([False]), 5.0)
