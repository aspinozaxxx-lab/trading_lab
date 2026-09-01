"""Tests for the sealed V25 weekly STLFSI4 stress governor."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v25_stlfsi_stress_governor as v25
from market_lab.futures import stlfsi_source


def _zero_weekly_weights(decision_dates: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "decision_date": decision,
                "asset": asset,
                "target_weight": 0.0,
                "provenance": "source_calendar_preflight_only",
            }
            for decision in decision_dates
            for asset in v12.ASSETS
        ]
    )


def test_real_protocol_raw_replay_and_source_calendar_are_exact() -> None:
    protocol = v25.load_protocol()
    verified = v25.verify_inputs(protocol)
    replayed = v25.verify_stlfsi_bundle(protocol, verified)

    assert all(verified.checks.values())
    assert all(replayed.checks.values())
    assert replayed.raw_records == 1
    assert len(replayed.frame) == 417
    panel_dates = pd.read_parquet(verified.paths["panel"], columns=["trade_date"])["trade_date"]
    weekly_dates = (
        pd.DataFrame(
            {
                "decision_date": pd.Series(
                    pd.to_datetime(panel_dates).dropna().dt.normalize().unique()
                ).sort_values()
            }
        )
        .assign(week=lambda frame: frame["decision_date"].dt.to_period("W-SUN"))
        .groupby("week", as_index=False)["decision_date"]
        .max()["decision_date"]
    )
    governed = v25.apply_weekly_governor(_zero_weekly_weights(weekly_dates), replayed)
    assert v25._state_counts(governed.governor) == v25.EXPECTED_ALL_STATES
    assert (
        v25._state_counts(
            governed.governor.loc[
                governed.governor["decision_date"].between(v12.OOS_START, v12.OOS_END)
            ]
        )
        == v25.EXPECTED_OOS_STATES
    )


def _synthetic_verification() -> v25.StlfsiVerification:
    rows: list[dict[str, object]] = []
    for day, value in (
        ("2021-01-01", -0.1),
        ("2021-01-08", 0.2),
        ("2021-01-15", None),
    ):
        complete = value is not None
        rows.append(
            {
                "observation_date": pd.Timestamp(day),
                "stress_index": value,
                "available_at": stlfsi_source.conservative_available_at(pd.Timestamp(day).date()),
                "complete": complete,
                "stress_state": (
                    "missing"
                    if not complete
                    else "above_average"
                    if float(value) > 0.0
                    else "normal_or_below"
                ),
                "retrieved_at_utc": pd.Timestamp("2026-09-01T05:00:00Z"),
                "source_current_vintage": True,
                "methodology_version": "STLFSI4",
            }
        )
    return v25.StlfsiVerification(
        frame=pd.DataFrame(rows),
        coverage=pd.DataFrame(),
        checks={"synthetic": True},
        raw_records=1,
    )


def _synthetic_weights(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "decision_date": pd.Timestamp(day),
                "asset": asset,
                "target_weight": value,
                "provenance": "synthetic_frozen_v12",
            }
            for day in dates
            for asset, value in zip(v12.ASSETS, (0.2, -0.2, 0.1, -0.1), strict=True)
        ]
    )


def test_weekly_governor_is_causal_binary_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = ["2021-01-07", "2021-01-08", "2021-01-14", "2021-01-15", "2021-01-22"]
    expected = {
        "weekly_decisions": 5,
        "pass_normal_or_below": 2,
        "cash_above_average_stress": 1,
        "cash_missing_or_stale": 2,
    }
    monkeypatch.setattr(v25, "EXPECTED_ALL_STATES", expected)
    monkeypatch.setattr(v25, "EXPECTED_OOS_STATES", expected)

    built = v25.apply_weekly_governor(_synthetic_weights(dates), _synthetic_verification())

    states = built.governor.set_index("decision_date")["governor_state"]
    assert states.to_dict() == {
        pd.Timestamp("2021-01-07"): "cash_missing_or_stale",
        pd.Timestamp("2021-01-08"): "pass_normal_or_below",
        pd.Timestamp("2021-01-14"): "pass_normal_or_below",
        pd.Timestamp("2021-01-15"): "cash_above_average_stress",
        pd.Timestamp("2021-01-22"): "cash_missing_or_stale",
    }
    selected = built.governor.set_index("decision_date")["observation_date"]
    assert pd.isna(selected[pd.Timestamp("2021-01-07")])
    assert selected[pd.Timestamp("2021-01-08")] == pd.Timestamp("2021-01-01")
    assert selected[pd.Timestamp("2021-01-15")] == pd.Timestamp("2021-01-08")
    gross = built.weights.groupby("decision_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    assert gross.loc[pd.Timestamp("2021-01-08")] == pytest.approx(0.6)
    assert gross.loc[pd.Timestamp("2021-01-14")] == pytest.approx(0.6)
    assert gross.drop([pd.Timestamp("2021-01-08"), pd.Timestamp("2021-01-14")]).eq(0.0).all()
    assert all(built.checks.values())


def test_protocol_has_only_official_zero_and_binary_downscale() -> None:
    protocol = v25.load_protocol()
    governor = protocol["risk_governor"]

    assert governor["official_structural_boundary"] == 0.0
    assert governor["maximum_source_age_calendar_days"] == 14
    assert governor["threshold_fit"] == "none"
    assert governor["admitted_scale"] == 1.0
    assert governor["cash_scale"] == 0.0
    assert governor["scale_can_increase_v12_risk"] is False
    assert protocol["validation"]["number_of_oos_variants"] == 1
    assert protocol["validation"]["protected_2026_market_read"] == "forbidden"


def test_protocol_inputs_stay_under_external_data_alias() -> None:
    protocol = v25.load_protocol()
    for declaration in protocol["inputs"].values():
        path = Path(str(declaration["path"]))
        assert not path.is_absolute()
        assert path.parts[0] == "data"
        assert ".." not in path.parts
