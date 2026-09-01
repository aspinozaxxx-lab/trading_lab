"""Tests for the sealed V31 unseen temporal-validation wrapper."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v31_pre2012_temporal_validation as source


def _synthetic_curve() -> pd.DataFrame:
    dates = pd.bdate_range("2008-10-08", periods=source.EXPECTED_MIX_UNAVAILABLE_SESSIONS)
    rows: list[dict[str, object]] = []
    for date in dates:
        rows.append(
            {
                "trade_date": date,
                "asset_code": "MIX",
                "active_contract_reason": "asset_not_yet_available",
                "active_contract_valid": False,
                "close": np.nan,
                "curve_observed_through": pd.NaT,
                "curve_available_at": pd.NA,
                "front_settle": np.nan,
                "next_settle": np.nan,
                "front_expiration_date": pd.NaT,
                "next_expiration_date": pd.NaT,
                "roll_yield": np.nan,
                "curve_valid": False,
            }
        )
    decision = dates[0]
    front_expiry = pd.Timestamp("2009-03-16")
    next_expiry = pd.Timestamp("2009-06-15")
    distance = (next_expiry - front_expiry).days
    front = 100.0
    next_value = 99.0
    roll_yield = (front / next_value - 1.0) * (365.0 / distance)
    for asset in ("SI", "RI", "BR"):
        rows.append(
            {
                "trade_date": decision,
                "asset_code": asset,
                "active_contract_reason": "front_retained",
                "active_contract_valid": True,
                "close": 100.0,
                "curve_observed_through": decision,
                "curve_available_at": "decision_close",
                "front_settle": front,
                "next_settle": next_value,
                "front_expiration_date": front_expiry,
                "next_expiration_date": next_expiry,
                "roll_yield": roll_yield,
                "curve_valid": True,
            }
        )
    return pd.DataFrame(rows)


def _scenario(
    *, cagr: float = 0.22, sharpe: float = 1.1, mdd: float = 0.25
) -> dict[str, object]:
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": mdd,
        "positive_years": 2,
        "calendar_year_segments": 3,
        "worst_year": -0.10,
        "execution_complete": True,
        "critical_failure_count": 0,
        "unresolved_halt_count": 0,
    }


def _robustness() -> dict[str, object]:
    bootstrap = {
        str(block): {"probability_cagr_ge_0_20_and_mdd_le_0_30": 0.45}
        for block in source.BOOTSTRAP_BLOCKS
    }
    leave = {
        str(year): {"cagr": 0.10, "sharpe": 0.8, "maximum_drawdown": 0.25}
        for year in source.EVALUATION_YEARS
    }
    item: dict[str, object] = {
        "bootstrap": bootstrap,
        "leave_one_year_out": leave,
        "rolling_252": {
            "positive_fraction": 0.80,
            "maximum_window_drawdown": 0.25,
        },
    }
    return {"primary": item, "stress": item}


def test_protocol_pins_v30_parent_and_one_shot_boundary() -> None:
    protocol = source.load_protocol()

    assert protocol.payload["parent_V30_D2"]["config_sha256"] == source.PARENT_CONFIG_SHA256
    assert protocol.payload["outcome_boundary"][
        "pre2012_price_values_returns_targets_equity_or_pnl_observed_before_seal"
    ] is False
    assert protocol.payload["validation"]["hyperparameter_search"] is False
    assert protocol.payload["universe"]["MIX_policy"] == "explicit_flat_mask_never_backfill"


def test_preflight_reads_no_pre2012_market_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = pd.read_parquet
    forbidden = {
        "open",
        "high",
        "low",
        "close",
        "settle",
        "volume",
        "value",
        "front_settle",
        "next_settle",
        "roll_yield",
        "sizing_point_value",
        "realized_accounting_point_value",
    }

    def guarded(*args: object, **kwargs: object) -> pd.DataFrame:
        columns = kwargs.get("columns")
        assert columns is not None
        assert not (set(columns) & forbidden)
        return original(*args, **kwargs)

    monkeypatch.setattr(source.pd, "read_parquet", guarded)
    summary = source.preflight_summary()

    assert summary["checks_true"] == 86
    assert summary["checks_total"] == 86
    assert summary["all_checks_true"] is True
    assert summary["pre2012_price_values_returns_targets_equity_or_pnl_read"] is False


def test_curve_verifier_accepts_only_exact_late_mix_empty_mask() -> None:
    frame = _synthetic_curve()

    verified = source.verify_pre2012_curve_panel(frame)
    tampered = frame.copy()
    first_mix = tampered.index[tampered["asset_code"].eq("MIX")][0]
    tampered.loc[first_mix, "curve_available_at"] = "decision_close"

    assert all(verified.checks.values())
    assert not verified.frame.loc[
        verified.frame["asset"].eq("MIX"), "carry_available"
    ].any()
    try:
        source.verify_pre2012_curve_panel(tampered)
    except ValueError as error:
        assert "availability missing outside exact late-MIX mask" in str(error)
    else:
        raise AssertionError("tampered late-MIX availability must fail closed")


def test_assessment_requires_every_transfer_gate() -> None:
    scenarios: Mapping[str, Mapping[str, object]] = {
        "primary": _scenario(),
        "doubled": _scenario(cagr=0.21),
        "stress": _scenario(cagr=0.205, sharpe=1.02, mdd=0.29),
    }

    passed = source.assess_validation(scenarios, _robustness(), {"proof": True})
    failed_scenarios = dict(scenarios)
    failed_scenarios["stress"] = _scenario(cagr=0.199, sharpe=1.02, mdd=0.29)
    failed = source.assess_validation(
        failed_scenarios, _robustness(), {"proof": True}
    )

    assert passed["verdict"] == "UNSEEN_TEMPORAL_CONFIRMATION_20_RESEARCH_ONLY"
    assert passed["supports_20_percent_on_unseen_temporal_period"] is True
    assert passed["supports_50_percent_on_unseen_temporal_period"] is False
    assert failed["verdict"] == "UNSEEN_TEMPORAL_NO_GO_20"
    assert failed["conditions"]["all_main_CAGR_at_least_20pct"] is False


def test_flat_adapter_only_adds_prior_dates_to_nontradable_mix_masks() -> None:
    protocol = source.load_protocol()
    columns = protocol.payload["inputs"]["active_contract_map"]["read_columns"]
    active = pd.read_parquet(protocol.paths["active_contract_map"], columns=columns)

    adapted, checks, count = source.adapt_late_mix_flat_active_map(active)
    changed = active["decision_date"].isna() & adapted["decision_date"].notna()

    assert count == source.EXPECTED_MIX_UNAVAILABLE_SESSIONS
    assert all(checks.values())
    assert changed.sum() == count
    assert adapted.loc[changed, "asset_code"].eq("MIX").all()
    assert adapted.loc[changed, "contract_id"].isna().all()
    assert not adapted.loc[changed, "plan_tradable"].any()
