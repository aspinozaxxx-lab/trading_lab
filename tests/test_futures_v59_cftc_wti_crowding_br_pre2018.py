"""Synthetic tests for the sealed V59 crowding sign."""

from __future__ import annotations

import pandas as pd

from market_lab import futures_v59_cftc_wti_crowding_br_pre2018 as v59


def test_protocol_keeps_only_contrarian_change() -> None:
    protocol = v59.load_protocol()

    assert protocol["signal"]["direction"] == ("positive_short_BR_negative_long_BR_exact_zero_cash")
    assert protocol["risk_execution"]["annual_volatility_target"] == 0.30
    assert protocol["risk_execution"]["maximum_absolute_target"] == 2.0
    assert protocol["dates"]["protected_from"] == "2018-01-01"


def test_contrarian_wrapper_inverts_only_candidate(monkeypatch) -> None:
    base = pd.DataFrame(
        {
            "decision_date": [pd.Timestamp("2017-01-06")],
            "candidate_sign": [1.0],
            "candidate_target_weight": [1.5],
            "baseline_sign": [-1.0],
            "baseline_target_weight": [-1.25],
        }
    )
    monkeypatch.setattr(v59.v58, "build_weekly_signals", lambda panel, cftc: base.copy())

    actual = v59.build_contrarian_signals(pd.DataFrame(), pd.DataFrame())

    assert actual["candidate_sign"].iloc[0] == -1.0
    assert actual["candidate_target_weight"].iloc[0] == -1.5
    assert actual["baseline_target_weight"].iloc[0] == -1.25
