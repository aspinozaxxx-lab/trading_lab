"""Synthetic causality, mechanism, cost and falsification checks for V64."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v64_si_tax_calendar as v64
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    run_futures_portfolio_ledger,
)


def active_map(start="2021-01-15", end="2021-01-29"):
    dates = pd.bdate_range(start, end)
    return pd.DataFrame(
        {
            "decision_date": dates[:-1],
            "effective_date": dates[1:],
            "observed_through": dates[:-1],
            "asset_code": "SI",
            "contract_id": "SYNTH-SI",
            "plan_tradable": True,
            "roll": False,
        }
    )


def synthetic_market():
    dates = pd.bdate_range("2021-01-15", "2021-01-29")
    # Strictly synthetic falling price, not a source observation or calibrated path.
    levels = 100.0 - np.arange(len(dates)) * 0.2
    return pd.DataFrame(
        {
            "session_date": dates,
            "asset_code": "SI",
            "contract_id": "SYNTH-SI",
            "open": levels,
            "high": levels + 1,
            "low": levels - 1,
            "settle": levels - 0.1,
            "volume": 10_000_000.0,
            "sizing_point_value": 100.0,
            "accounting_point_value": 100.0,
            "tick_size": 0.01,
            "fee_per_contract": 1.0,
            "initial_margin": 2500.0,
        }
    )


def test_calendar_old_and_new_rules_without_fit():
    dates = pd.Series(
        pd.to_datetime(
            [
                "2022-11-17",
                "2022-11-18",
                "2022-11-24",
                "2022-11-25",
                "2023-02-20",
                "2023-02-21",
                "2023-02-27",
                "2023-02-28",
            ]
        )
    )
    result = v64.calendar_signal(dates, 0)
    assert result.calendar_weight.tolist() == [0, -1, -1, 0, 0, -1, -1, 0]
    assert result.anchor_day.tolist() == [25] * 4 + [28] * 4


def test_control_is_fixed_two_weeks_earlier():
    dates = pd.Series(pd.to_datetime(["2022-11-04", "2022-11-10", "2022-11-11"]))
    assert v64.calendar_signal(dates, -14).calendar_weight.tolist() == [-1, -1, 0]
    with pytest.raises(ValueError, match="undeclared"):
        v64.calendar_signal(dates, -7)


def test_next_open_only_and_last_target_flat():
    result = v64.build_targets(active_map(), 0)
    assert (result.decision_date < result.effective_date).all()
    entry = result.loc[result.target_weight.ne(0)].iloc[0]
    assert entry.decision_date == pd.Timestamp("2021-01-18")
    assert entry.effective_date == pd.Timestamp("2021-01-19")
    assert result.iloc[-1].target_weight == 0
    assert result.iloc[-1].terminal_flat


def test_poisoned_price_and_outcome_columns_cannot_affect_targets():
    source = active_map()
    expected = v64.build_targets(source, 0)
    source["future_pnl"] = 1e30
    source["close"] = np.arange(len(source)) * 999
    pd.testing.assert_frame_equal(expected, v64.build_targets(source, 0))


def test_missing_contract_is_sleep_not_synthetic_trade():
    source = active_map()
    source.loc[source.decision_date.eq("2021-01-18"), "contract_id"] = None
    result = v64.build_targets(source, 0)
    row = result.loc[result.decision_date.eq("2021-01-18")].iloc[0]
    assert row.source_unavailable
    assert row.requested_weight == -1 and row.target_weight == 0


def test_calendar_expiry_cancels_stale_order_at_reopen():
    source = active_map()
    source.loc[source.decision_date.eq("2021-01-22"), "effective_date"] = pd.Timestamp("2021-02-01")
    result = v64.build_targets(source, 0)
    row = result.loc[result.decision_date.eq("2021-01-22")].iloc[0]
    assert row.calendar_expired_at_fill and row.target_weight == 0


@pytest.mark.parametrize("column", ["decision_date", "effective_date", "observed_through"])
def test_future_or_noncausal_map_rejected(column):
    source = active_map()
    source.loc[0, column] = pd.Timestamp("2026-01-02")
    with pytest.raises(ValueError):
        v64.build_targets(source, 0)


def test_protected_signal_rejected():
    with pytest.raises(ValueError, match="protected"):
        v64.calendar_signal(pd.Series(pd.to_datetime(["2026-01-01"])), 0)


def test_duplicate_map_rejected():
    source = active_map()
    with pytest.raises(ValueError, match="duplicate"):
        v64.build_targets(pd.concat([source, source.iloc[[0]]]), 0)


def test_synthetic_exact_ledger_costs_round_trip_and_accounting():
    summaries = []
    for ticks, fee in ((1, 1.0), (2, 2.0)):
        result = run_futures_portfolio_ledger(
            synthetic_market(),
            v64.build_targets(active_map(), 0),
            FuturesPortfolioLedgerConfig(
                expected_assets=("SI",),
                slippage_ticks=ticks,
                fee_multiplier=fee,
                execution_atomicity="asset",
                unexecutable_target_policy="cancel_and_clip",
            ),
        )
        summary = v64.summarize(result)
        assert summary["execution_complete"] and not summary["terminal_carried"]
        assert summary["round_trips"] == summary["position_entries"] == 1
        assert summary["net_pnl"] > 0
        summaries.append(summary)
    assert summaries[1]["total_cost"] > summaries[0]["total_cost"]
    assert summaries[1]["net_pnl"] < summaries[0]["net_pnl"]


def gate_fixture():
    tax = {
        "execution_complete": True,
        "terminal_carried": False,
        "round_trips": 24,
        "positive_years": 2,
        "year_segments": 2,
        "total_return": 0.1,
        "cagr": 0.05,
    }
    control = {**tax, "total_return": -0.1, "cagr": -0.05}
    return {
        era: {
            arm: {cost: copy.deepcopy(value) for cost in v64.SCENARIOS}
            for arm, value in (("tax", tax), ("control", control))
        }
        for era in ("early", "middle", "recent")
    }


def test_screen_pass_is_not_profit_goal_or_live_permission():
    assessment = v64.assess(gate_fixture())
    assert assessment["verdict"] == "GO_TO_NEW_FORWARD_VALIDATION"
    assert not assessment["goal_20_supported_all_eras"]
    assert not assessment["live_trading_allowed"]


def test_losing_primary_not_replaced_by_control():
    metrics = gate_fixture()
    metrics["recent"]["tax"]["stress"]["total_return"] = -0.01
    assert v64.assess(metrics)["verdict"] == "NO_GO"


def test_incomplete_execution_invalidates_numeric_profit():
    metrics = gate_fixture()
    metrics["early"]["control"]["doubled"]["execution_complete"] = False
    assert v64.assess(metrics)["verdict"] == "INVALID_EXECUTION_NO_PROMOTION"


def test_missing_era_cannot_vacuously_pass():
    with pytest.raises(ValueError, match="missing declared era"):
        v64.assess({})


def test_catalog_only_points_to_three_fixed_source_eras():
    import yaml

    config = yaml.safe_load(v64.CONFIG.read_text(encoding="utf-8-sig"))
    specs = v64.declarations(config)
    assert set(specs) == {"early", "middle", "recent"}
    assert all(set(spec) == {"active_map", "observations", "specs"} for spec in specs.values())
