"""Tests for the sealed V13 trend plus causal futures-curve challenger."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v13_trend_carry_confirmation as v13


def _curve_panel() -> pd.DataFrame:
    decision = pd.Timestamp("2025-06-20")
    front_expiry = pd.Timestamp("2025-06-30")
    next_expiry = pd.Timestamp("2025-09-30")
    distance = float((next_expiry - front_expiry).days)
    rows = []
    for index, asset in enumerate(v13.v12.ASSETS):
        front = 100.0 + index
        following = 99.0 + index
        rows.append(
            {
                "trade_date": decision,
                "asset_code": asset,
                "close": 100.0,
                "curve_observed_through": decision,
                "curve_available_at": "decision_close",
                "front_settle": front,
                "next_settle": following,
                "front_expiration_date": front_expiry,
                "next_expiration_date": next_expiry,
                "roll_yield": (front / following - 1.0) * 365.0 / distance,
                "curve_valid": True,
            }
        )
    return pd.DataFrame(rows)


def test_protocol_is_byte_sealed_and_research_only() -> None:
    protocol = v13.load_protocol()

    assert protocol["protocol_id"] == "futures_v13_trend_carry_confirmation_v1"
    assert protocol["research_only"] is True
    assert protocol["live_trading_allowed"] is False
    assert protocol["dates"]["forbidden_from"] == "2026-01-01"
    assert v13.v12.sha256_file(v13.CONFIG_PATH) == v13.CONFIG_SHA256


def test_curve_is_independently_recomputed_at_same_close() -> None:
    panel = _curve_panel()
    proof = v13.verify_curve_panel(panel)

    assert proof.frame["carry_available"].all()
    assert proof.frame["roll_yield"].notna().all()
    assert set(proof.frame["asset"]) == set(v13.v12.ASSETS)
    assert all(proof.checks.values())


@pytest.mark.parametrize("failure", ["wrong_yield", "future_observation", "wrong_availability"])
def test_curve_proof_fails_closed(failure: str) -> None:
    panel = _curve_panel()
    if failure == "wrong_yield":
        panel.loc[0, "roll_yield"] += 0.01
    elif failure == "future_observation":
        panel.loc[0, "curve_observed_through"] = pd.Timestamp("2026-01-02")
    else:
        panel.loc[0, "curve_available_at"] = "next_session"

    with pytest.raises(ValueError):
        v13.verify_curve_panel(panel)


def test_confirmation_keeps_only_strict_same_sign(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = pd.Timestamp("2025-06-20")
    trend = pd.DataFrame(
        {
            "decision_date": [decision] * 4,
            "asset": list(v13.v12.ASSETS),
            "candidate_score": [0.6, -0.4, -0.2, 0.5],
        }
    )
    monkeypatch.setattr(v13.v12, "build_trend_scores", lambda _panel: trend.copy())
    curve = v13.CurveVerification(
        frame=pd.DataFrame(
            {
                "trade_date": [decision] * 4,
                "asset": list(v13.v12.ASSETS),
                "roll_yield": [0.1, 0.1, -0.1, np.nan],
                "carry_available": [True, True, True, False],
            }
        ),
        checks={"synthetic": True},
    )

    scores = v13.build_trend_carry_scores(pd.DataFrame(), curve).set_index("asset")

    assert scores.loc["SI", "candidate_score"] == pytest.approx(0.6)
    assert scores.loc["RI", "candidate_score"] == pytest.approx(0.0)
    assert scores.loc["BR", "candidate_score"] == pytest.approx(-0.2)
    assert pd.isna(scores.loc["MIX", "candidate_score"])
    assert scores.loc["SI", "confirmation_state"] == "confirmed"
    assert scores.loc["RI", "confirmation_state"] == "observed_not_confirmed"
    assert scores.loc["MIX", "confirmation_state"] == "missing_input"


def test_sidecar_names_the_sealed_protocol() -> None:
    sidecar = Path(v13.CONFIG_PATH).with_suffix(".sha256")
    digest, name = sidecar.read_text(encoding="utf-8-sig").split()

    assert digest == v13.CONFIG_SHA256
    assert name == v13.CONFIG_PATH.name
