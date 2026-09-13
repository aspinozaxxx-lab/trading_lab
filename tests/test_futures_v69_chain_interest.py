"""Synthetic all-chain aggregation, causal month sampling and shared cash accounting."""

import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v69_chain_interest as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))


def toy_config():
    cfg = config()
    cfg["signal"]["lookback_sessions"] = 3
    return cfg


def source():
    return pd.DataFrame(
        [
            {
                "trade_date": day,
                "logical_asset": asset,
                "canonical_contract_id": asset + leg,
                "open_interest": 100.0 + i + offset,
            }
            for i, day in enumerate(pd.bdate_range("2018-01-03", "2018-05-31"))
            for asset in config()["assets"]
            for leg, offset in (("near", 0), ("far", 100))
        ]
    )


def mapping():
    dates = pd.bdate_range("2018-01-03", "2018-05-31")
    return pd.DataFrame(
        [
            {
                "decision_date": day,
                "effective_date": dates[i + 1],
                "observed_through": day,
                "asset_code": asset,
                "contract_id": "SYNTH-" + asset,
                "plan_tradable": True,
                "roll": False,
            }
            for i, day in enumerate(dates[:-1])
            for asset in config()["assets"]
        ]
    )


def test_all_contracts_aggregated_without_active_map_and_exact_63_lag():
    states = screen.states(source(), config())
    for _, asset in states.groupby("asset_code"):
        asset = asset.reset_index(drop=True)
        assert asset.source_rows.eq(2).all()
        assert asset.loc[0, "chain_oi"] == 300
        assert not asset.loc[:62, "ready"].any()
        assert asset.loc[63:, "ready"].all()
        assert asset.loc[63, "prior_chain_oi"] == 300
        assert asset.loc[63, "growth"] == pytest.approx(np.log(426 / 300))


def test_null_contract_masks_total_and_all_null_is_not_zero():
    raw = source()
    day = pd.Timestamp("2018-02-01")
    raw.loc[
        raw.trade_date.eq(day) & raw.canonical_contract_id.str.endswith("far"), "open_interest"
    ] = np.nan
    raw.loc[raw.trade_date.eq("2018-02-02"), "open_interest"] = np.nan
    states = screen.states(raw, toy_config())
    missing = states.loc[states.source_date.eq(day)]
    assert missing.missing_rows.eq(1).all() and missing.chain_oi.isna().all()
    assert not missing.ready.any()
    all_missing = states.loc[states.source_date.eq("2018-02-02")]
    assert all_missing.reported_sum.isna().all() and all_missing.chain_oi.isna().all()
    raw["open_interest"] = 0.0
    assert not screen.states(raw, toy_config()).ready.any()


def test_transfer_between_contracts_does_not_create_chain_growth():
    raw = source()
    index = raw.trade_date.map({day: i for i, day in enumerate(sorted(raw.trade_date.unique()))})
    raw["open_interest"] = np.where(
        raw.canonical_contract_id.str.endswith("near"), 200 - index, 100 + index
    )
    states = screen.states(raw, toy_config())
    assert states.chain_oi.eq(300).all()
    assert states.loc[states.ready, "primary_direction"].eq(0).all()
    assert states.loc[states.ready, "control_direction"].eq(1).all()


def test_declining_chain_interest_is_short_while_control_remains_long():
    raw = source()
    raw["open_interest"] = 1000 - raw.open_interest
    states = screen.states(raw, toy_config())
    assert states.loc[states.ready, "primary_direction"].eq(-1).all()
    assert states.loc[states.ready, "control_direction"].eq(1).all()


@pytest.mark.parametrize(
    "fault", ["duplicate", "protected", "negative", "infinite", "identity", "asset"]
)
def test_invalid_source_rejected(fault):
    raw = source()
    if fault == "duplicate":
        raw = pd.concat([raw, raw.iloc[:1]])
    elif fault == "protected":
        raw.loc[0, "trade_date"] = pd.Timestamp("2026-01-01")
    elif fault == "negative":
        raw.loc[0, "open_interest"] = -1
    elif fault == "infinite":
        raw.loc[0, "open_interest"] = np.inf
    elif fault == "identity":
        raw.loc[0, "canonical_contract_id"] = None
    else:
        raw.loc[0, "logical_asset"] = "UNKNOWN"
    with pytest.raises(ValueError):
        screen.states(raw, toy_config())


def test_gap_resets_growth_until_full_causal_window():
    raw = source()
    raw = raw.loc[~raw.trade_date.between("2018-02-01", "2018-02-16")]
    states = screen.states(raw, toy_config())
    post = states.loc[states.source_date.ge("2018-02-19")].groupby("asset_code").head(3)
    assert not post.ready.any()
    assert states.loc[states.source_date.eq("2018-02-22"), "ready"].all()


def test_first_month_decision_strict_prior_and_direction_frozen():
    raw = source()
    raw.loc[raw.trade_date.ge("2018-02-15"), "open_interest"] *= 0.1
    out = screen.targets(mapping(), screen.states(raw, toy_config()), "primary", toy_config())
    feb = out.loc[out.decision_date.dt.month.eq(2)]
    assert feb.source_date.eq(pd.Timestamp("2018-01-31")).all()
    assert feb.target_weight.eq(0.25).all()
    assert feb.groupby("asset_code").monthly_update.sum().eq(1).all()
    used = out.loc[out.target_weight.ne(0)]
    assert used.available_at_utc.le(used.signal_decision_at_utc).all()
    assert used.signal_decision_at_utc.le(used.decision_at_utc).all()
    assert used.source_date.lt(used.decision_date).all()
    assert used.decision_date.lt(used.effective_date).all()
    assert out.groupby("asset_code").tail(1).target_weight.eq(0).all()


def test_invalid_new_month_supersedes_valid_old_month_without_fallback():
    raw = source()
    raw.loc[raw.trade_date.eq("2018-02-28"), "open_interest"] = np.nan
    for arm in screen.ARMS:
        out = screen.targets(mapping(), screen.states(raw, toy_config()), arm, toy_config())
        march = out.loc[out.decision_date.dt.month.eq(3)]
        assert march.feature_unavailable.all() and march.target_weight.eq(0).all()
        assert march.source_date.eq(pd.Timestamp("2018-02-28")).all()
        assert out.loc[out.decision_date.dt.month.eq(2), "target_weight"].eq(0.25).all()


def test_future_values_do_not_change_past_targets():
    raw, changed = source(), source()
    changed.loc[changed.trade_date.ge("2018-03-01"), "open_interest"] *= 0.01
    for arm in screen.ARMS:
        a = screen.targets(mapping(), screen.states(raw, toy_config()), arm, toy_config())
        b = screen.targets(mapping(), screen.states(changed, toy_config()), arm, toy_config())
        pd.testing.assert_frame_equal(
            a.loc[a.decision_date.lt("2018-03-01")], b.loc[b.decision_date.lt("2018-03-01")]
        )


def test_delayed_availability_cannot_enter_earlier_month_snapshot():
    states = screen.states(source(), toy_config())
    delayed = states.source_date.eq("2018-01-31")
    states.loc[delayed, "available_at_utc"] += pd.Timedelta(days=2)
    states.loc[delayed, "primary_direction"] = -1
    out = screen.targets(mapping(), states, "primary", toy_config())
    feb = out.loc[out.decision_date.dt.month.eq(2)]
    assert feb.source_date.eq(pd.Timestamp("2018-01-30")).all()
    assert feb.target_weight.eq(0.25).all()


def test_missing_map_and_future_clock_fail_closed():
    active = mapping()
    active.loc[active.decision_date.eq("2018-02-05"), "contract_id"] = None
    out = screen.targets(active, screen.states(source(), toy_config()), "primary", toy_config())
    assert out.loc[out.decision_date.eq("2018-02-05"), "target_weight"].eq(0).all()
    active.loc[0, "observed_through"] = pd.Timestamp("2018-01-10")
    with pytest.raises(ValueError, match="future map"):
        screen.targets(active, screen.states(source(), toy_config()), "primary", toy_config())


def test_actual_synthetic_shared_ledger_cost_stress_and_terminal_exit():
    cfg = toy_config()
    signal = screen.targets(mapping(), screen.states(source(), cfg), "primary", cfg)
    dates = sorted(signal.effective_date.unique())
    market = pd.DataFrame(
        [
            {
                "session_date": day,
                "asset_code": asset,
                "contract_id": "SYNTH-" + asset,
                "open": 1000.0 + 2 * i,
                "high": 1003.0 + 2 * i,
                "low": 998.0 + 2 * i,
                "settle": 1001.0 + 2 * i,
                "sizing_point_value": 1.0,
                "accounting_point_value": 1.0,
                "tick_size": 1.0,
                "fee_per_contract": 1.0,
                "initial_margin": 100.0,
                "volume": 1_000_000.0,
            }
            for i, day in enumerate(dates)
            for asset in cfg["assets"]
        ]
    )
    values = []
    for ticks, fee in cfg["execution"]["costs"].values():
        result = screen.base.run_futures_portfolio_ledger(
            market,
            signal,
            screen.base.FuturesPortfolioLedgerConfig(
                expected_assets=tuple(cfg["assets"]),
                slippage_ticks=ticks,
                fee_multiplier=fee,
                execution_atomicity="asset",
                unexecutable_target_policy="cancel_and_clip",
            ),
        )
        value = screen.shared.summarize(result)
        assert value["execution_complete"] and not value["terminal_carried"]
        assert value["round_trips"] == 4 and value["position_entries"] == 4
        assert value["critical_failure_count"] == 0 and value["unresolved_halt_count"] == 0
        values.append(value)
    assert values[0]["ending_cash"] > values[1]["ending_cash"]
    assert values[0]["total_cost"] < values[1]["total_cost"]


def test_gate_requires_all_eight_years_both_costs_and_no_promotion_of_control():
    cfg = config()

    def metric(cagr):
        return {
            "execution_complete": True,
            "critical_failure_count": 0,
            "unresolved_halt_count": 0,
            "terminal_carried": False,
            "round_trips": 101,
            "cagr": cagr,
            "sharpe": 1.0,
            "maximum_drawdown": 0.1,
            "positive_years": 8,
            "annual_returns": dict.fromkeys(cfg["screen_gates"]["expected_years"], 0.1),
            "worst_year": 0.1,
        }

    metrics = {
        arm: {cost: metric(0.1 if arm == "primary" else 0.05) for cost in cfg["execution"]["costs"]}
        for arm in screen.ARMS
    }
    quality = {"ready_asset_date_fraction": 0.7}
    assert screen.shared.assess(metrics, quality, cfg)["verdict"] == "STAGE2_CANDIDATE"
    metrics["primary"]["double"]["cagr"] = 0.01
    assert screen.shared.assess(metrics, quality, cfg)["verdict"] == "REJECT_STAGE1"
    metrics["primary"]["double"] = metric(0.1)
    del metrics["primary"]["double"]["annual_returns"]["2022"]
    assert screen.shared.assess(metrics, quality, cfg)["verdict"] == "REJECT_STAGE1"
