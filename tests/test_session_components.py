"""Small counterfactual tests: source-only selection and explicit non-ledger reporting."""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
import pytest

from market_lab.futures.opening_regime_v2 import Market, local_time
from market_lab.futures.session_components import (
    CONFIG,
    evaluate,
    read_json,
    report,
    requests,
    spec_index,
    summarize,
)


def fixture():
    cfg = read_json(CONFIG)
    days = pd.bdate_range("2021-01-04", periods=4)
    bars, specs = [], []
    for day in days:
        for minute in (600, 620, 1100, 1120):
            stamp = local_time(day, minute)
            bars.append(
                dict(
                    contract_id="MIX:ONE",
                    timestamp=stamp,
                    end_timestamp=stamp + pd.Timedelta(minutes=10),
                    open=10_000.0,
                    high=10_001.0,
                    low=9_999.0,
                    close=10_000.0,
                    volume=5_000.0,
                )
            )
        specs.append(
            dict(
                session_date=day,
                contract_id="MIX:ONE",
                sizing_usable=True,
                sizing_observed_session_date=day - pd.Timedelta(days=1),
                sizing_point_value=1.0,
                sizing_tick_cash_value=1.0,
                conservative_fee_per_side=1.0,
            )
        )
    plan = pd.DataFrame(dict(local_date=days, asset="MIX", contract_id="MIX:ONE"))
    return Market(pd.DataFrame(bars), plan, days), pd.DataFrame(specs), cfg


def changed(market, bars=None, plan=None):
    return Market(
        market.bars.copy() if bars is None else bars,
        market.plan.copy() if plan is None else plan,
        market.sessions,
    )


def test_flat_prices_only_costs_and_no_portfolio_metrics():
    market, specs, cfg = fixture()
    req = requests(market, specs, cfg)
    assert len(req) == 8
    assert req.requested_quantity.sum() == 7
    for scenario, expected in (("primary", -4.0), ("doubled", -8.0)):
        frame = evaluate(req, market, specs, cfg, scenario)
        good = frame.loc[frame.state.eq("OBSERVED_PAIR")]
        assert len(good) == 7
        assert good.net_basis_points.eq(expected).all()
        assert good.gross_cash.eq(0).all()
        result = summarize(frame)
        for field in ("cagr", "sharpe", "maximum_drawdown", "portfolio_pnl"):
            assert result[field] is None
        assert result["unresolved"] == 0


def test_entry_decision_latency_and_future_mutation():
    market, specs, cfg = fixture()
    req = requests(market, specs, cfg)
    assert (req.entry_at - req.decision_at).eq(pd.Timedelta(minutes=10)).all()
    bars = market.bars.copy()
    selected = bars.timestamp.eq(local_time(market.sessions[1], 620))
    bars.loc[selected, "volume"] = 0
    bars.loc[selected, ["open", "close"]] = 1_000
    bars.loc[selected, "low"] = 999
    mutated = changed(market, bars)
    pd.testing.assert_frame_equal(req, requests(mutated, specs, cfg))
    results = evaluate(req, mutated, specs, cfg, "primary")
    first = results.loc[results.arm.eq("off_session")].iloc[0]
    assert first.entered_quantity == 1 and first.closed_quantity == 0
    assert first.state == "UNRESOLVED_EXIT_BAR_OR_CAPACITY"
    assert np.isnan(first.net_basis_points)


def test_roll_never_substitutes_new_active_contract():
    market, specs, cfg = fixture()
    plan = market.plan.copy()
    plan.loc[plan.local_date.ge(market.sessions[1]), "contract_id"] = "MIX:TWO"
    bars = market.bars.copy()
    bars.loc[bars.timestamp.ge(local_time(market.sessions[1], 0)), "contract_id"] = "MIX:TWO"
    specs.loc[specs.session_date.ge(market.sessions[1]), "contract_id"] = "MIX:TWO"
    mutated = changed(market, bars, plan)
    result = evaluate(requests(mutated, specs, cfg), mutated, specs, cfg, "primary")
    first = result.loc[result.arm.eq("off_session")].iloc[0]
    assert first.contract_id == "MIX:ONE"
    assert first.state.startswith("UNRESOLVED")
    assert first.entered_quantity == 1 and first.closed_quantity == 0


@pytest.mark.parametrize("where", ["decision", "entry", "exit"])
def test_capacity_unknown_is_not_zero_return(where):
    market, specs, cfg = fixture()
    bars = market.bars.copy()
    day = market.sessions[1] if where == "exit" else market.sessions[0]
    minute = {"decision": 1100, "entry": 1120, "exit": 620}[where]
    bars.loc[bars.timestamp.eq(local_time(day, minute)), "volume"] = 0
    mutated = changed(market, bars)
    frame = evaluate(requests(mutated, specs, cfg), mutated, specs, cfg, "primary")
    first = frame.loc[frame.arm.eq("off_session")].iloc[0]
    assert np.isnan(first.net_cash)
    assert first.entered_quantity == int(where == "exit")
    assert first.closed_quantity == 0


def test_same_day_spec_is_not_available_at_decision():
    market, specs, cfg = fixture()
    specs["sizing_observed_session_date"] = specs.session_date
    req = requests(market, specs, cfg)
    assert req.requested_quantity.sum() == 0
    assert len(req) == 8


def test_changed_point_value_exit_remains_unresolved():
    market, specs, cfg = fixture()
    specs.loc[1, "sizing_point_value"] = 2
    result = evaluate(requests(market, specs, cfg), market, specs, cfg, "primary")
    first = result.loc[result.arm.eq("off_session")].iloc[0]
    assert first.state == "UNRESOLVED_POINT_VALUE_CHANGE"
    assert first.entered_quantity == 1 and first.closed_quantity == 0


def test_protected_or_duplicate_specs_rejected():
    _, specs, _ = fixture()
    with pytest.raises(ValueError, match="duplicate"):
        spec_index(pd.concat([specs, specs]))
    specs.loc[0, "session_date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="protected"):
        spec_index(specs)


def test_missing_source_cannot_be_promoted_even_with_positive_observed_pairs():
    market, specs, cfg = fixture()
    req = requests(market, specs, cfg)
    frames = []
    for cost in cfg["costs"]:
        frame = evaluate(req, market, specs, cfg, cost)
        index = frame.loc[frame.arm.eq("off_session")].index[0]
        frame.loc[index, ["state", "closed_quantity", "net_basis_points"]] = [
            "UNRESOLVED_EXIT_BAR_OR_CAPACITY",
            0,
            np.nan,
        ]
        frames.append(frame)
    result = report(pd.concat(frames, ignore_index=True), cfg)
    assert result["verdict"] == "INCOMPLETE_SOURCE_NO_PROMOTION"
    assert not result["stage2_candidate"] and not result["goal_verified"]


def test_no_entries_has_explicit_empty_statistics_and_no_promotion():
    market, specs, cfg = fixture()
    cfg = copy.deepcopy(cfg)
    cfg["minimum_signal_volume"] = 100_000
    req = requests(market, specs, cfg)
    pairs = pd.concat([evaluate(req, market, specs, cfg, c) for c in cfg["costs"]])
    result = report(pairs, cfg)
    assert result["verdict"] == "NO_GO_COMPONENT"
    assert all(r["completed"] == 0 for r in result["results"].values())


def test_overnight_endpoints_use_next_calendar_day_and_same_contract():
    market, specs, cfg = fixture()
    bars = market.bars.copy()
    select = bars.timestamp.eq(local_time(market.sessions[1], 620))
    bars.loc[select, ["open", "close", "high"]] = 10_100.0
    mutated = changed(market, bars)
    req = requests(mutated, specs, cfg)
    frame = evaluate(req, mutated, specs, cfg, "primary")
    first = frame.loc[frame.arm.eq("off_session")].iloc[0]
    assert first.gross_cash == 100
    assert first.net_basis_points == 96
    assert first.exit_local_date == market.sessions[1]
