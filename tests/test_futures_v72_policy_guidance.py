"""Synthetic text-only extraction, causal timing and paired cost-ledger checks."""

import copy
import json

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v72_policy_guidance as screen


def config():
    return {
        "protocol_id": "synthetic_v72",
        "assets": ["MIX", "SI"],
        "period": {"start": "2018-01-01", "end": "2025-12-31"},
        "signal": {
            "maximum_source_age_at_fill_calendar_days": 14,
            "maximum_decision_to_fill_calendar_days": 7,
        },
        "execution": {
            "weight_per_asset": 0.5,
            "maximum_signal_gross": 1.0,
            "costs": {"base": [1, 1.0], "double": [2, 2.0]},
        },
        "screen_gates": {
            "minimum_ready_asset_date_fraction": 0.9,
            "minimum_round_trips": 80,
            "minimum_cagr_each_cost": 0.05,
            "minimum_sharpe_each_cost": 0.5,
            "maximum_drawdown_each_cost": 0.25,
            "minimum_positive_years_each_cost": 5,
            "expected_years": [str(y) for y in range(2018, 2026)],
            "minimum_worst_year_each_cost": -0.15,
            "minimum_cagr_excess_over_control_each_cost": 0.02,
        },
    }


@pytest.mark.parametrize(
    ("sentence", "direction", "reason"),
    [
        (
            "Банк России допускает возможность дальнейшего повышения ключевой ставки.",
            -1,
            "explicit_hike",
        ),
        (
            "Банк России будет оценивать целесообразность снижения ключевой ставки.",
            1,
            "explicit_cut",
        ),
        ("Банк России не исключает возможности повышения ключевой ставки.", -1, "explicit_hike"),
        (
            "Банк России не планирует рассматривать возможность повышения ключевой ставки.",
            0,
            "no_explicit_direction",
        ),
        (
            "Банк России допускает снижение инфляции при сохранении ключевой ставки.",
            0,
            "no_explicit_direction",
        ),
        (
            "Банк России принял решение повысить ключевую ставку, допускает снижение инфляции.",
            0,
            "no_explicit_direction",
        ),
        (
            "Возможно повышение ключевой ставки. Возможно снижение ключевой ставки.",
            0,
            "ambiguous_both_directions",
        ),
        (
            "Банк России будет поддерживать жесткие денежно-кредитные условия.",
            0,
            "no_explicit_direction",
        ),
        ("Банк России готов снизить ключевую ставку.", 1, "explicit_cut"),
    ],
)
def test_narrow_guidance_direction_negation_and_non_rate_references(sentence, direction, reason):
    row = screen.classify("Банк России сохранил ключевую ставку", [sentence])
    assert row["ready"] and row["primary_direction"] == direction
    assert row["control_direction"] == 0 and row["reason"] == reason


def test_headline_control_has_no_guidance_information_and_unknown_masks_both():
    title = "Банк России повысил ключевую ставку"
    a = screen.classify(title, ["Возможно снижение ключевой ставки."])
    b = screen.classify(title, ["Возможно повышение ключевой ставки."])
    assert a["control_direction"] == b["control_direction"] == -1
    assert a["primary_direction"] == 1 and b["primary_direction"] == -1
    bad = screen.classify("Неизвестная форма заголовка", ["Возможно повышение ключевой ставки."])
    assert (
        not bad["ready"]
        and np.isnan(bad["primary_direction"])
        and np.isnan(bad["control_direction"])
    )


def test_impossibility_is_not_possibility_and_synthetic_gates_match_config():
    row = screen.classify(
        "Банк России сохранил ключевую ставку", ["Невозможно снижение ключевой ставки."]
    )
    assert row["primary_direction"] == 0
    frozen = json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))
    for section in ("screen_gates", "signal", "execution"):
        for key, value in config()[section].items():
            assert frozen[section][key] == value
    assert frozen["assets"] == config()["assets"]
    assert frozen["period"] == config()["period"]


def raw():
    days = pd.to_datetime(["2021-01-08", "2021-01-15"])
    return pd.DataFrame(
        {
            "publication_date": days,
            "available_at_utc": (
                days.tz_localize("Europe/Moscow") + pd.Timedelta(hours=23, minutes=59, seconds=59)
            ).tz_convert("UTC"),
            "headline": "Банк России повысил ключевую ставку",
            "paragraphs": [
                ["Возможно повышение ключевой ставки."],
                ["Возможно снижение ключевой ставки."],
            ],
            "source_url": ["synthetic://first", "synthetic://second"],
            "raw_sha256": "synthetic",
        }
    )


def mapping():
    days = pd.bdate_range("2021-01-04", "2021-02-12")
    return pd.concat(
        [
            pd.DataFrame(
                {
                    "decision_date": days[:-1],
                    "effective_date": days[1:],
                    "observed_through": days[:-1],
                    "asset_code": asset,
                    "contract_id": "SYNTH-" + asset,
                    "plan_tradable": True,
                    "roll": False,
                }
            )
            for asset in config()["assets"]
        ],
        ignore_index=True,
    )


def test_friday_eod_release_enters_monday_not_friday_or_tuesday_and_expires():
    out = screen.targets(mapping(), screen.states(raw(), config()), "primary", config())
    first = out.loc[out.target_weight.ne(0)].iloc[0]
    assert first.source_date == first.decision_date == pd.Timestamp("2021-01-08")
    assert first.effective_date == pd.Timestamp("2021-01-11")
    assert first.target_weight == -0.5
    used = out.loc[out.target_weight.ne(0)]
    assert used.available_at_utc.le(used.decision_at_utc).all()
    assert used.source_date.le(used.decision_date).all()
    assert used.decision_date.lt(used.effective_date).all()
    assert out.groupby("effective_date").target_weight.apply(lambda w: w.abs().sum()).max() == 1
    stale = out.loc[out.effective_date.ge("2021-02-01")]
    assert stale.stale_at_fill.all() and stale.target_weight.eq(0).all()
    assert out.groupby("asset_code").tail(1).terminal_flat.all()


def test_future_text_mutation_cannot_change_earlier_decisions():
    a = raw()
    b = raw()
    b.at[1, "paragraphs"] = ["Возможно повышение ключевой ставки."]
    for arm in screen.ARMS:
        first = screen.targets(mapping(), screen.states(a, config()), arm, config())
        second = screen.targets(mapping(), screen.states(b, config()), arm, config())
        pd.testing.assert_frame_equal(
            first.loc[first.decision_date.lt("2021-01-15")],
            second.loc[second.decision_date.lt("2021-01-15")],
        )


def test_neutral_or_unknown_latest_release_does_not_inherit_older_direction():
    for headline, paragraph in [
        ("Банк России сохранил ключевую ставку", "Без направления."),
        ("Неизвестно", "Возможно повышение ключевой ставки."),
    ]:
        d = raw()
        d.at[1, "headline"], d.at[1, "paragraphs"] = headline, [paragraph]
        out = screen.targets(mapping(), screen.states(d, config()), "primary", config())
        after = out.loc[out.decision_date.eq("2021-01-15")]
        assert after.source_date.eq(pd.Timestamp("2021-01-15")).all()
        assert after.target_weight.eq(0).all()


def test_late_receipt_is_not_backdated():
    d = raw()
    d.loc[1, "available_at_utc"] += pd.Timedelta(days=4)
    out = screen.targets(mapping(), screen.states(d, config()), "primary", config())
    assert (
        out.loc[out.decision_date.eq("2021-01-18"), "source_date"]
        .eq(pd.Timestamp("2021-01-08"))
        .all()
    )
    assert out.loc[out.decision_date.eq("2021-01-19"), "target_weight"].eq(0.5).all()


@pytest.mark.parametrize("fault", ["duplicate", "protected", "premature", "same_day"])
def test_bad_source_identity_or_clock_fails(fault):
    d = raw()
    if fault == "duplicate":
        d = pd.concat([d, d.iloc[:1]])
    elif fault == "protected":
        d.loc[0, "publication_date"] = pd.Timestamp("2026-01-01")
    elif fault == "premature":
        d["available_at_utc"] -= pd.Timedelta(seconds=1)
    else:
        d.loc[1, "publication_date"] = d.loc[0, "publication_date"]
    with pytest.raises(ValueError):
        screen.states(d, config())


def test_missing_plan_future_map_and_long_decision_gap():
    state = screen.states(raw(), config())
    plan = mapping()
    plan.loc[plan.decision_date.eq("2021-01-15"), "contract_id"] = None
    out = screen.targets(plan, state, "primary", config())
    assert out.loc[out.decision_date.eq("2021-01-15"), "target_weight"].eq(0).all()
    bad = mapping()
    bad.loc[0, "observed_through"] = bad.loc[0, "effective_date"]
    with pytest.raises(ValueError, match="future map"):
        screen.targets(bad, state, "primary", config())
    late = mapping()
    late["effective_date"] += pd.Timedelta(days=10)
    assert screen.targets(late, state, "primary", config()).target_weight.eq(0).all()


def test_stage_gate_needs_all_years_meaningful_excess_and_complete_controls():
    good = {
        "execution_complete": True,
        "critical_failure_count": 0,
        "unresolved_halt_count": 0,
        "terminal_carried": False,
        "round_trips": 100,
        "cagr": 0.1,
        "sharpe": 0.8,
        "maximum_drawdown": 0.1,
        "positive_years": 8,
        "worst_year": 0.01,
        "annual_returns": {str(y): 0.01 for y in range(2018, 2026)},
    }
    metrics = {
        arm: {
            cost: {**good, "cagr": 0.1 if arm == "primary" else 0.04} for cost in ["base", "double"]
        }
        for arm in screen.ARMS
    }
    q = {"ready_asset_date_fraction": 1.0}
    assert screen.assess(metrics, q, config())["verdict"] == "STAGE2_CANDIDATE"
    assert not screen.assess(metrics, q, config())["goal_verified"]
    bad = copy.deepcopy(metrics)
    bad["control"]["double"]["cagr"] = 0.09
    assert screen.assess(bad, q, config())["verdict"] == "REJECT_STAGE1"
    bad["control"]["base"]["execution_complete"] = False
    assert screen.assess(bad, q, config())["verdict"] == "INVALID_EXECUTION_NO_PROMOTION"


def test_two_asset_synthetic_ledger_retains_costs_and_terminal_flat():
    days = pd.bdate_range("2021-01-04", "2021-02-12")
    market = pd.concat(
        [
            pd.DataFrame(
                {
                    "session_date": days,
                    "asset_code": asset,
                    "contract_id": "SYNTH-" + asset,
                    "open": 100 + np.arange(len(days)) * 0.1,
                    "high": 102 + np.arange(len(days)) * 0.1,
                    "low": 98 + np.arange(len(days)) * 0.1,
                    "settle": 100.1 + np.arange(len(days)) * 0.1,
                    "volume": 1e7,
                    "sizing_point_value": 100.0,
                    "accounting_point_value": 100.0,
                    "tick_size": 0.01,
                    "fee_per_contract": 1.0,
                    "initial_margin": 1000.0,
                }
            )
            for asset in config()["assets"]
        ],
        ignore_index=True,
    )
    signal = screen.targets(mapping(), screen.states(raw(), config()), "primary", config())
    results = []
    for ticks, fee in [(1, 1.0), (2, 2.0)]:
        result = screen.base.run_futures_portfolio_ledger(
            market,
            signal,
            screen.base.FuturesPortfolioLedgerConfig(
                initial_cash=screen.base.CAPITAL,
                expected_assets=tuple(config()["assets"]),
                maximum_gross_notional_multiple=1.0,
                initial_margin_buffer_multiplier=2.0,
                maximum_participation=0.01,
                slippage_ticks=ticks,
                fee_multiplier=fee,
                execution_atomicity="asset",
                unexecutable_target_policy="cancel_and_clip",
            ),
        )
        value = screen.shared.summarize(result)
        assert value["execution_complete"] and not value["terminal_carried"]
        assert value["round_trips"] == 4 and value["total_cost"] > 0
        results.append(value)
    assert results[1]["total_cost"] > results[0]["total_cost"]
    assert results[1]["net_pnl"] < results[0]["net_pnl"]
