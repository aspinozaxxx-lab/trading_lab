"""Tests for sealed V27 official key-rate risk governor."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab import futures_v27_key_rate_extreme_governor as v27


def _zero_weights(decision_dates: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "decision_date": decision,
                "asset": asset,
                "target_weight": 0.0,
                "provenance": "source_only",
            }
            for decision in decision_dates
            for asset in v27.v12.ASSETS
        ]
    )


def test_real_protocol_raw_replay_and_combined_state_counts_are_exact() -> None:
    protocol = v27.load_protocol()
    parent = v27.v26.load_protocol()
    verified = v27.verify_inputs(protocol)
    key_rate = v27.verify_key_rate_bundle(protocol, verified)
    stlfsi = v27.v25.verify_stlfsi_bundle(parent, verified)
    panel_dates = pd.read_parquet(verified.paths["panel"], columns=["trade_date"])["trade_date"]
    dates = pd.Series(pd.to_datetime(panel_dates).dropna().dt.normalize().unique()).sort_values()
    weekly_dates = dates.groupby(dates.dt.to_period("W-SUN")).max().reset_index(drop=True)
    v25_weights = v27.v25.apply_weekly_governor(_zero_weights(weekly_dates), stlfsi).weights
    built = v27.apply_monetary_governor(v25_weights, key_rate)

    assert all(verified.checks.values())
    assert all(key_rate.checks.values())
    assert len(key_rate.frame) == v27.KEY_RATE_ROWS
    assert key_rate.raw_sha256 == (
        "06da1497c27f985151bbb4455cc7f6109660edf190a8fbf5280c0d04016d4639"
    )
    assert v27._state_counts(built.governor) == v27.EXPECTED_ALL_STATES
    assert (
        v27._state_counts(
            built.governor.loc[
                built.governor["decision_date"].between(v27.v12.OOS_START, v27.v12.OOS_END)
            ]
        )
        == v27.EXPECTED_OOS_STATES
    )


def _synthetic_key_rate() -> v27.KeyRateVerification:
    frame = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(["2021-01-06", "2021-01-13", "2021-01-20"]),
            "available_at": pd.to_datetime(
                [
                    "2021-01-06T21:00:00Z",
                    "2021-01-13T21:00:00Z",
                    "2021-01-20T21:00:00Z",
                ],
                utc=True,
            ),
            "key_rate_percent": [19.0, 20.0, 19.0],
        }
    )
    return v27.KeyRateVerification(
        frame=frame,
        checks={"synthetic": True},
        raw_bytes=1,
        raw_sha256="synthetic",
    )


def _synthetic_v25_weights() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day, state, scale in (
        ("2021-01-01", "pass_normal_or_below", 1.0),
        ("2021-01-08", "pass_normal_or_below", 1.0),
        ("2021-01-15", "pass_normal_or_below", 1.0),
        ("2021-01-22", "cash_above_average_stress", 0.0),
    ):
        for asset, value in zip(v27.v12.ASSETS, (0.2, -0.2, 0.1, -0.1), strict=True):
            rows.append(
                {
                    "decision_date": pd.Timestamp(day),
                    "asset": asset,
                    "target_weight": value * scale,
                    "governor_state": state,
                    "risk_scale": scale,
                    "provenance": "synthetic_v25",
                }
            )
    return pd.DataFrame(rows)


def test_monetary_governor_is_causal_binary_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "weekly_decisions": 4,
        "pass_both": 1,
        "cash_stlfsi4": 1,
        "cash_key_rate_at_least_20": 1,
        "cash_key_rate_missing_or_stale": 1,
    }
    monkeypatch.setattr(v27, "EXPECTED_ALL_STATES", expected)
    monkeypatch.setattr(v27, "EXPECTED_OOS_STATES", expected)

    built = v27.apply_monetary_governor(_synthetic_v25_weights(), _synthetic_key_rate())
    states = built.governor.set_index("decision_date")["combined_state"].to_dict()

    assert states == {
        pd.Timestamp("2021-01-01"): "cash_key_rate_missing_or_stale",
        pd.Timestamp("2021-01-08"): "pass_both",
        pd.Timestamp("2021-01-15"): "cash_key_rate_at_least_20",
        pd.Timestamp("2021-01-22"): "cash_stlfsi4",
    }
    cash_dates = [
        pd.Timestamp("2021-01-01"),
        pd.Timestamp("2021-01-15"),
        pd.Timestamp("2021-01-22"),
    ]
    assert (
        built.weights.loc[built.weights["decision_date"].isin(cash_dates), "target_weight"]
        .eq(0.0)
        .all()
    )
    assert all(built.checks.values())


def _scenario(*, cagr: float = 0.21, mdd: float = 0.29) -> dict[str, object]:
    return {
        "futures_only": {
            "execution_complete": True,
            "critical_failure_count": 0,
            "unresolved_halt_count": 0,
            "maximum_participation": 0.01,
            "gross_limit_rejection_count": 0,
            "initial_margin_rejection_count": 0,
            "ending_cash": 2_000_000.0,
        },
        "combined": {
            "metrics_valid": True,
            "cagr": cagr,
            "maximum_drawdown": mdd,
            "sharpe": 1.0,
            "worst_year": -0.10,
            "positive_years": 4,
            "annual_returns": {str(year): 0.01 for year in range(2021, 2026)},
        },
    }


def test_promotion_keeps_twenty_percent_and_thirty_percent_drawdown_gates() -> None:
    checks = {
        "monetary_governor_all_state_counts_exact": True,
        "monetary_governor_oos_state_counts_exact": True,
        "another_check": True,
    }
    passing = {name: _scenario() for name in ("primary", "doubled", "stress")}
    low_return = {**passing, "stress": _scenario(cagr=0.1999)}
    high_drawdown = {**passing, "doubled": _scenario(mdd=0.3001)}

    assert v27._promotion(passing, checks)["passed"] is True
    assert v27._promotion(low_return, checks)["passed"] is False
    assert v27._promotion(high_drawdown, checks)["passed"] is False


def test_protocol_has_one_round_threshold_and_no_new_market_input() -> None:
    protocol = v27.load_protocol()

    assert protocol["monetary_governor"]["boundary_percent_per_annum"] == 20.0
    assert protocol["monetary_governor"]["comparison"] == "greater_than_or_equal"
    assert protocol["monetary_governor"]["threshold_fit"] == "none_round_economic_boundary"
    assert protocol["input_inheritance"]["new_market_outcome_input"] == "none"
    assert protocol["validation"]["number_of_oos_variants"] == 1
    raw = Path(protocol["input_inheritance"]["cbr_key_rate_transitive_raw"]["path"])
    assert not raw.is_absolute()
    assert raw.parts[0] == "raw"
    assert ".." not in raw.parts


def test_sidecar_names_the_sealed_protocol() -> None:
    digest, name = v27.CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()

    assert digest == v27.CONFIG_SHA256
    assert name == v27.CONFIG_PATH.name
