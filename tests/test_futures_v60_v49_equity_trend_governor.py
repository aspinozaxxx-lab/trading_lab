"""Tests for the sealed V60 causal shadow-equity trend governor."""

from __future__ import annotations

import numpy as np
import pandas as pd

from market_lab import futures_v60_v49_equity_trend_governor as subject


def test_protocol_pins_one_rule_and_twenty_percent_floor() -> None:
    protocol = subject.load_protocol()

    assert protocol.payload["selection"]["candidate_count"] == 1
    assert protocol.payload["selection"]["parameter_search"] is False
    assert protocol.payload["selection"]["moving_average_sessions"] == 126
    assert protocol.payload["gates"]["all_scenario_cagr_gte"] == 0.20
    assert protocol.payload["live_trading_allowed"] is False


def _shadow(periods: int = 130) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_date": pd.bdate_range("2020-01-01", periods=periods),
            subject.SHADOW_COLUMN: np.linspace(1.0, 2.0, periods),
        }
    )


def test_governor_uses_only_strictly_prior_shadow_session() -> None:
    shadow = _shadow()
    decision = pd.Series([shadow.loc[126, "session_date"]])
    original = subject.build_governor(shadow, decision)
    changed = shadow.copy()
    changed.loc[126, subject.SHADOW_COLUMN] = 0.01
    same = subject.build_governor(changed, decision)

    assert original.loc[0, "shadow_session_date"] == shadow.loc[125, "session_date"]
    assert same.loc[0, "shadow_session_date"] == shadow.loc[125, "session_date"]
    assert original.loc[0, "risk_multiplier"] == same.loc[0, "risk_multiplier"]


def test_governor_has_one_x_warmup_and_two_x_above_trend() -> None:
    shadow = _shadow()
    decisions = pd.Series([shadow.loc[10, "session_date"], shadow.loc[126, "session_date"]])
    governor = subject.build_governor(shadow, decisions)

    assert governor["risk_multiplier"].tolist() == [1.0, 2.0]
    assert governor["warmup_complete"].tolist() == [False, True]


def test_govern_targets_preserves_sign_and_zero() -> None:
    effective = pd.Timestamp("2021-01-04")
    base = pd.DataFrame(
        {
            "effective_date": [effective, effective, effective],
            "target_weight": [-0.5, 0.0, 0.25],
            "provenance": ["a", "b", "c"],
        }
    )
    governor = pd.DataFrame(
        {
            "effective_date": [effective],
            "risk_multiplier": [2.0],
            "risk_on": [True],
            "warmup_complete": [True],
        }
    )

    targets = subject.govern_targets(base, governor)

    assert targets["target_weight"].tolist() == [-1.0, 0.0, 0.5]
    assert targets["target_weight"].mul(targets["v39_target_weight"]).ge(0.0).all()
