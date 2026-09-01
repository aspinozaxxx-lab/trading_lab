"""Synthetic tests for the sealed V28 unseen pre-2018 validation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from market_lab import futures_v28_pre2018_unseen_validation as v28
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult


def test_default_protocol_is_sealed_without_loading_market_outcomes() -> None:
    protocol = v28.load_protocol()

    assert protocol.config_sha256 == (
        "4f9e66634803a7ac1c100ecdc998e1ca6e29558b704416003bff9331eac511b2"
    )
    assert protocol.payload["sealed_source_only_state_counts"]["validation"] == (
        v28.EXPECTED_VALIDATION_STATES
    )
    assert protocol.payload["sealed_source_only_collateral_calendar"] == (
        v28.EXPECTED_COLLATERAL_CALENDAR
    )


def _synthetic_macro() -> v28.MacroBundle:
    stress = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(
                ["2013-01-04", "2013-01-11", "2013-01-18", "2013-02-01"]
            ),
            "available_at": pd.to_datetime(
                [
                    "2013-01-04T00:00:00Z",
                    "2013-01-11T00:00:00Z",
                    "2013-01-18T00:00:00Z",
                    "2013-02-01T00:00:00Z",
                ],
                utc=True,
            ),
            "complete": [True, True, True, True],
            "stress_state": [
                "normal_or_below",
                "above_average",
                "normal_or_below",
                "normal_or_below",
            ],
        }
    )
    key_rate = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(
                ["2013-01-04", "2013-01-11", "2013-01-18"]
            ),
            "available_at": pd.to_datetime(
                [
                    "2013-01-04T00:00:00Z",
                    "2013-01-11T00:00:00Z",
                    "2013-01-18T00:00:00Z",
                ],
                utc=True,
            ),
            "key_rate_percent": [7.0, 7.0, 20.0],
        }
    )
    return v28.MacroBundle(
        stlfsi=stress,
        key_rate=key_rate,
        ruonia=pd.DataFrame(),
        coverage=pd.DataFrame(),
        checks={"synthetic": True},
        raw_records=0,
    )


def _weekly_weights() -> pd.DataFrame:
    dates = pd.to_datetime(["2013-01-04", "2013-01-11", "2013-01-18", "2013-02-01"])
    frame = pd.MultiIndex.from_product(
        [dates, v28.v12.ASSETS], names=["decision_date", "asset"]
    ).to_frame(index=False)
    frame["target_weight"] = 0.10
    frame["provenance"] = "synthetic_frozen_v12"
    return frame


def test_frozen_governors_distinguish_all_four_cash_and_pass_reasons() -> None:
    expected = {
        "weekly_decisions": 4,
        "pass_both": 1,
        "cash_stlfsi_above_average": 1,
        "cash_stlfsi_missing_or_stale": 0,
        "cash_key_rate_at_least_20": 1,
        "cash_key_rate_missing_or_stale": 1,
        "raw_stlfsi_pass": 3,
        "raw_stlfsi_above": 1,
        "raw_stlfsi_missing_or_stale": 0,
    }

    result = v28.apply_frozen_governors(
        _weekly_weights(),
        _synthetic_macro(),
        expected_all=expected,
        expected_validation=expected,
    )

    assert result.all_counts == expected
    assert result.validation_counts == expected
    nonzero = result.weights.groupby("decision_date")["target_weight"].apply(
        lambda values: int(values.ne(0.0).sum())
    )
    assert nonzero.tolist() == [4, 0, 0, 0]


def test_exact_two_times_weekly_multiplier_preserves_cash() -> None:
    governed = _weekly_weights()
    governed.loc[governed["decision_date"].eq(pd.Timestamp("2013-01-11")), "target_weight"] = 0.0

    result = v28.build_levered_weekly_weights(governed)

    assert result.loc[
        result["decision_date"].eq(pd.Timestamp("2013-01-04")), "target_weight"
    ].eq(0.20).all()
    assert result.loc[
        result["decision_date"].eq(pd.Timestamp("2013-01-11")), "target_weight"
    ].eq(0.0).all()


def test_execution_mapping_applies_leverage_only_after_next_open_mapping() -> None:
    weights = pd.DataFrame(
        {
            "decision_date": [pd.Timestamp("2012-12-28")] * 4,
            "asset": list(v28.v12.ASSETS),
            "target_weight": [0.10] * 4,
            "provenance": ["synthetic"] * 4,
        }
    )
    rows: list[dict[str, object]] = []
    for decision, effective in (
        (pd.Timestamp("2012-12-28"), pd.Timestamp("2013-01-03")),
        (pd.Timestamp("2013-01-03"), pd.Timestamp("2013-01-04")),
    ):
        for asset in v28.v12.ASSETS:
            rows.append(
                {
                    "decision_date": decision,
                    "effective_date": effective,
                    "observed_through": decision,
                    "asset_code": asset,
                    "contract_id": f"{asset}-TEST",
                    "plan_tradable": True,
                    "roll": False,
                }
            )
    active = pd.DataFrame(rows)

    result = v28.build_levered_execution_targets(weights, active)

    assert result.targets["effective_date"].eq(pd.Timestamp("2013-01-03")).all()
    assert result.targets["pre_leverage_target_weight"].eq(0.10).all()
    assert result.targets["target_weight"].eq(0.20).all()


def _collateral_result() -> FuturesPortfolioLedgerResult:
    ledger = pd.DataFrame(
        {
            "session_date": pd.to_datetime(["2012-12-28", "2013-01-03", "2013-01-04"]),
            "ending_cash": [1_000_000.0, 1_000_000.0, 1_000_000.0],
            "intraday_adverse_equity": [1_000_000.0, 1_000_000.0, 1_000_000.0],
            "modeled_initial_margin": [0.0, 0.0, 0.0],
        }
    )
    return FuturesPortfolioLedgerResult(
        ledger=ledger,
        positions=pd.DataFrame(),
        orders=pd.DataFrame(),
        metrics={},
        execution_complete=True,
    )


def test_unknown_ruonia_timing_receives_no_credit_without_zero_imputation() -> None:
    ruonia = pd.DataFrame(
        {
            "observation_date": pd.to_datetime(["2013-01-01"]),
            "available_at": pd.to_datetime(["2013-01-02T00:00:00Z"], utc=True),
            "ruonia_percent": [10.0],
        }
    )
    expected = {
        "execution_sessions": 3,
        "accrual_intervals": 2,
        "accrual_calendar_days": 3,
        "known_rate_intervals": 1,
        "unknown_no_credit_intervals": 1,
        "known_rate_calendar_days": 1,
    }

    result = v28.evaluate_conservative_collateral(
        _collateral_result(), ruonia, expected_calendar=expected
    )

    unknown = result.audit.loc[
        result.audit["credit_status"].eq("no_credit_unknown_availability")
    ].iloc[0]
    assert pd.isna(unknown["ruonia_percent"])
    assert pd.isna(unknown["applied_percent"])
    assert unknown["interest_rub"] == 0.0
    assert result.metrics["known_rate_intervals"] == 1


def _scenario(cagr: float) -> dict[str, object]:
    return {
        "futures_only": {
            "execution_complete": True,
            "critical_failure_count": 0,
            "unresolved_halt_count": 0,
            "maximum_participation": 0.005,
            "gross_limit_rejection_count": 0,
            "initial_margin_rejection_count": 0,
            "ending_cash": 2_000_000.0,
        },
        "combined": {
            "cagr": cagr,
            "maximum_drawdown": 0.20,
            "sharpe": 1.0,
            "worst_year": -0.05,
            "positive_years": 4,
            "annual_returns": {str(year): 0.1 for year in range(2013, 2018)},
        },
    }


def test_assessment_separates_twenty_and_fifty_percent_support() -> None:
    scenarios = {name: _scenario(0.25) for name in ("primary", "doubled", "stress")}

    result = v28._assessment(scenarios, {"sealed": True})

    assert result["support_20_percent"]["passed"] is True
    assert result["support_50_percent"]["passed"] is False
    assert result["live_trading_allowed"] is False


def test_default_run_path_remains_external_junction_alias() -> None:
    assert (v28.PROJECT_ROOT / "runs").resolve().is_relative_to(
        Path("D:/Projects/trading_lab_data").resolve()
    )
