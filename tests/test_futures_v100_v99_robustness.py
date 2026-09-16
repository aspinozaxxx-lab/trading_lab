"""Synthetic stress, temporal/dependence and stored-cash replay checks."""

import copy
import json

import numpy as np
import pandas as pd
import pytest
from test_futures_v98_fomc_event_premium import active
from test_futures_v99_reserve_liquidity import config as parent_config
from test_futures_v99_reserve_liquidity import release

from market_lab import futures_v100_v99_robustness as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8"))


@pytest.mark.parametrize("days", [0, 1, 7])
def test_latency_moves_clock_only_and_preserves_parent_values(days):
    rows = [release("2019-10-03", 100), release("2020-01-02", 110)]
    before = copy.deepcopy(rows)
    state = screen.delayed_states(rows, days, parent_config())
    assert rows == before
    assert state[-1]["growth"] == pytest.approx(.1)
    assert state[-1]["release_date"] == "2020-01-02"
    assert state[-1]["available"] == pd.Timestamp("2020-01-03T06:00:00Z") + pd.Timedelta(days=days)
    assert state[-1]["lag_available"] < state[-1]["available"]
    assert state[-1]["original_available_at_utc"] == rows[-1]["available_at_utc"]


def test_latency_changes_eligible_next_open_without_future_exit_selection():
    rows = [release("2019-10-03", 100), release("2020-01-02", 110)]
    plan = active(pd.bdate_range("2019-12-30", "2020-01-20"))
    firsts = []
    for days in [0, 1, 7]:
        frame = screen.candidate.targets(plan, screen.delayed_states(rows, days, parent_config()),
                                          parent_config())["primary"]
        firsts.append(frame.loc[frame.target_weight.ne(0), "effective_date"].iloc[0])
    assert firsts == list(pd.to_datetime(["2020-01-06", "2020-01-07", "2020-01-13"]))
    assert frame.iloc[-1].target_weight == 0
    with pytest.raises(ValueError, match="unplanned"):
        screen.delayed_states(rows, 2, parent_config())


def test_temporal_every_block_and_every_omitted_year_keep_zero_year():
    annual = {str(y): .1 for y in range(2018, 2026)}
    out = screen.temporal(annual)
    assert len(out["four_calendar_year_geometric_annual"]) == 5
    assert len(out["leave_one_year_out_annual"]) == 8
    assert all(v == pytest.approx(.1) for v in out["four_calendar_year_geometric_annual"].values())
    annual["2018"] = 0
    assert screen.temporal(annual)["positive_years"] == 7
    assert screen.temporal(annual)["four_calendar_year_geometric_annual"]["2018-2021"] < .1
    with pytest.raises(ValueError, match="coverage"):
        screen.temporal({k: v for k, v in annual.items() if k != "2018"})


def frames():
    dates = pd.date_range("2020-12-31", "2025-12-31", freq="ME")
    changes = np.tile([-.02, .03, .01], 20)
    nav = np.r_[1, np.cumprod(1 + changes)]
    return (pd.DataFrame({"session_date": dates, "ending_cash": 1000000 * nav}),
            pd.DataFrame({"session_date": dates, "reference": nav}))


def test_monthly_dependence_exact_alignment_and_ex_post_negative_months():
    left, right = frames()
    result, rows = screen.monthly_dependence(left, right, "reference")
    assert len(rows) == result["months"] == 60
    assert result["monthly_correlation"] == pytest.approx(1)
    assert result["v49_negative_months"] == 20
    assert result["v99_mean_in_v49_negative_months"] == pytest.approx(-.02)
    assert result["v99_positive_in_v49_negative_months"] == 0
    right["reference"] = 1.
    flat, _ = screen.monthly_dependence(left, right, "reference")
    assert flat["monthly_correlation"] is None and flat["v99_mean_in_v49_negative_months"] is None


def test_monthly_missing_anchor_protected_and_bad_nav_fail_closed():
    left, right = frames()
    with pytest.raises(ValueError, match="missing monthly"):
        screen.monthly_dependence(left.drop(index=12), right, "reference")
    left.loc[len(left) - 1, "session_date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="protected"):
        screen.monthly_dependence(left, right, "reference")
    left, right = frames()
    right.loc[5, "reference"] = np.nan
    with pytest.raises(ValueError, match="NAV values"):
        screen.monthly_dependence(left, right, "reference")


def fake_case(annual=.1, verdict="STAGE2_CANDIDATE", complete=True, costs=("base", "double")):
    return {"metrics": {arm: {cost: {
        "annual_returns": {str(y): annual for y in range(2018, 2026)},
        "execution_complete": complete, "critical_failure_count": 0,
        "unresolved_halt_count": 0, "terminal_carried": False,
    } for cost in costs} for arm in ["primary", "control"]},
        "assessment": {"verdict": verdict}}


def test_no_promotion_on_known_temporal_weakness_any_stress_or_bad_execution():
    def cases(**kwargs):
        return {s["id"]: fake_case(costs=s["costs"], **kwargs) for s in config()["scenarios"]}

    baseline, good = fake_case(), cases()
    assert screen.assessment(baseline, good, config())["verdict"] == "STAGE3_SOURCE_CHECK_CANDIDATE"
    for metric in baseline["metrics"]["primary"].values():
        metric["annual_returns"].update({str(y): .01 for y in range(2022, 2026)})
    assert screen.assessment(baseline, good, config())["verdict"] == "REJECT_STAGE2_ROBUSTNESS"
    assert screen.assessment(fake_case(), cases(verdict="REJECT_STAGE1"),
                              config())["verdict"] == "REJECT_STAGE2_ROBUSTNESS"
    assert screen.assessment(fake_case(), cases(complete=False),
                              config())["verdict"] == "INVALID_STAGE2_EXECUTION"
    with pytest.raises(ValueError, match="missing stress scenarios"):
        screen.assessment(fake_case(), {}, config())
    del good["delay7"]["metrics"]["control"]["stress"]
    with pytest.raises(ValueError, match="missing stress cost"):
        screen.assessment(fake_case(), good, config())


def test_full_flat_ledger_stress_and_cash_replay_rejects_tampering(tmp_path):
    parent = parent_config()
    parent["execution"]["costs"] = {"stress": [4, 2.]}
    rows = [release("2019-10-03", 100), release("2020-01-02", 110)]
    signals = screen.candidate.targets(active(pd.bdate_range("2019-12-30", "2020-01-20")),
                                        screen.delayed_states(rows, 7, parent), parent)
    market = pd.DataFrame([{
        "session_date": day, "asset_code": "MIX", "contract_id": "MIXTEST", "volume": 1e7,
        "open": 100., "high": 100., "low": 100., "settle": 100., "tick_size": .01,
        "sizing_point_value": 100., "accounting_point_value": 100.,
        "fee_per_contract": 1., "initial_margin": 1000.,
    } for day in signals["primary"].effective_date])
    folder = tmp_path / "case"
    case = screen.engine.simulate_case(folder, signals, market,
                                       {"ready_asset_date_fraction": 1.}, parent, "synthetic")
    assert screen.audit_case(folder, case, signals)["cash_cost_metric_annual_count_replays"] == 2
    for arm in case["metrics"].values():
        assert arm["stress"]["net_pnl"] == pytest.approx(-arm["stress"]["total_cost"])
    path = folder / "ledger_primary_stress.parquet"
    ledger = pd.read_parquet(path)
    ledger.loc[3, "starting_cash"] += 100
    ledger.to_parquet(path, index=False)
    with pytest.raises(ValueError, match="cash continuity"):
        screen.audit_case(folder, case, signals)
