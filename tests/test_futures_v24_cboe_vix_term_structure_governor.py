"""Tests for the sealed V24 Cboe VIX/VIX3M daily risk governor."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v24_cboe_vix_term_structure_governor as v24
from market_lab.futures import cboe_vix_term_structure_source as source


def test_real_protocol_and_raw_source_bundle_are_strictly_replayable() -> None:
    protocol = v24.load_protocol()
    verified = v24.verify_inputs(protocol)
    replayed = v24.verify_vix_bundle(protocol, verified)

    assert all(verified.checks.values())
    assert all(replayed.checks.values())
    assert replayed.raw_records == 2
    assert len(replayed.frame) == 2087
    assert int(replayed.frame["complete_pair"].sum()) == 2011
    assert replayed.frame["observation_date"].max() == pd.Timestamp("2025-12-31")

    active = pd.read_parquet(
        verified.paths["active_contract_map"],
        columns=protocol["inputs"]["active_contract_map"]["allowed_columns"],
    )
    first_decision = pd.to_datetime(active["decision_date"]).dropna().min()
    zero_weights = pd.DataFrame(
        [
            {
                "decision_date": first_decision,
                "asset": asset,
                "target_weight": 0.0,
                "provenance": "source_calendar_preflight_only",
            }
            for asset in v12.ASSETS
        ]
    )
    governed = v24.build_daily_governed_weights(zero_weights, active, replayed)
    assert v24._state_counts(governed.governor) == v24.EXPECTED_ALL_STATES
    assert (
        v24._state_counts(
            governed.governor.loc[
                governed.governor["decision_date"].between(v12.OOS_START, v12.OOS_END)
            ]
        )
        == v24.EXPECTED_OOS_STATES
    )


def _active_map(decision_dates: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for decision_text in decision_dates:
        decision = pd.Timestamp(decision_text)
        for asset in v12.ASSETS:
            rows.append(
                {
                    "decision_date": decision,
                    "effective_date": decision + pd.Timedelta(days=1),
                    "observed_through": decision,
                    "asset_code": asset,
                    "contract_id": f"{asset}-TEST",
                    "plan_tradable": True,
                    "roll": False,
                }
            )
    return pd.DataFrame(rows)


def _weekly_weights() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "decision_date": pd.Timestamp("2021-01-03"),
                "asset": asset,
                "target_weight": value,
                "provenance": "synthetic_frozen_v12",
            }
            for asset, value in zip(v12.ASSETS, (0.2, -0.2, 0.1, -0.1), strict=True)
        ]
    )


def _vix_frame() -> pd.DataFrame:
    observations = [
        ("2021-01-02", 10.0, 12.0, "contango"),
        ("2021-01-03", 15.0, 12.0, "backwardation"),
        ("2021-01-04", None, 12.0, "missing"),
        ("2021-01-09", 12.0, 12.0, "flat"),
    ]
    rows: list[dict[str, object]] = []
    for day, vix_close, vix3m_close, state in observations:
        complete = vix_close is not None and vix3m_close is not None
        rows.append(
            {
                "observation_date": pd.Timestamp(day),
                "vix_close": vix_close,
                "vix3m_close": vix3m_close,
                "available_at": source.conservative_available_at(pd.Timestamp(day).date()),
                "complete_pair": complete,
                "vix_vix3m_ratio": (
                    float(vix_close) / float(vix3m_close) if complete else float("nan")
                ),
                "term_structure": state,
                "retrieved_at_utc": pd.Timestamp("2026-09-01T04:00:00Z"),
                "source_current_vintage": True,
            }
        )
    return pd.DataFrame(rows)


def test_daily_governor_is_causal_binary_and_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = ["2021-01-03", "2021-01-04", "2021-01-05", "2021-01-10", "2021-01-16"]
    expected = {
        "decision_dates": 5,
        "pass_contango": 1,
        "cash_backwardation": 1,
        "cash_flat": 1,
        "cash_missing_or_stale": 2,
    }
    monkeypatch.setattr(v24, "EXPECTED_ALL_STATES", expected)
    monkeypatch.setattr(v24, "EXPECTED_OOS_STATES", expected)
    verification = v24.VixVerification(
        frame=_vix_frame(),
        coverage=pd.DataFrame(),
        checks={"synthetic": True},
        raw_records=2,
    )

    built = v24.build_daily_governed_weights(_weekly_weights(), _active_map(dates), verification)

    states = built.governor.set_index("decision_date")["governor_state"]
    assert states.to_dict() == {
        pd.Timestamp("2021-01-03"): "pass_contango",
        pd.Timestamp("2021-01-04"): "cash_backwardation",
        pd.Timestamp("2021-01-05"): "cash_missing_or_stale",
        pd.Timestamp("2021-01-10"): "cash_flat",
        pd.Timestamp("2021-01-16"): "cash_missing_or_stale",
    }
    selected = built.governor.set_index("decision_date")["observation_date"]
    assert selected[pd.Timestamp("2021-01-03")] == pd.Timestamp("2021-01-02")
    assert selected[pd.Timestamp("2021-01-04")] == pd.Timestamp("2021-01-03")
    by_day = built.weights.groupby("decision_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    assert by_day[pd.Timestamp("2021-01-03")] == pytest.approx(0.6)
    assert by_day.drop(pd.Timestamp("2021-01-03")).eq(0.0).all()
    assert all(built.checks.values())


def test_protocol_has_no_fitted_vix_threshold_or_risk_increase() -> None:
    protocol = v24.load_protocol()
    governor = protocol["risk_governor"]

    assert governor["structural_boundary"] == 1.0
    assert governor["threshold_fit"] == "none"
    assert governor["admitted_scale"] == 1.0
    assert governor["cash_scale"] == 0.0
    assert governor["scale_can_increase_v12_risk"] is False
    assert protocol["validation"]["number_of_oos_variants"] == 1
    assert protocol["validation"]["protected_2026_market_read"] == "forbidden"


def test_protocol_path_is_external_data_only() -> None:
    protocol = v24.load_protocol()
    for declaration in protocol["inputs"].values():
        path = Path(str(declaration["path"]))
        assert not path.is_absolute()
        assert path.parts[0] == "data"
        assert ".." not in path.parts
