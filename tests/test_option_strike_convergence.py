"""Synthetic strike ablation, source clocks, exact futures and existing-ledger bridge."""

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from market_lab import futures_v68_reported_option_flow as reporting
from market_lab.futures import option_strike_convergence as model


def config():
    path = Path(__file__).parents[1] / "configs/v90_option_strike_convergence_design_v1.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))


def contract(asset, code="F1", expiry="2021-03-18"):
    prefix = {"SI": "Si", "RI": "RTS"}.get(asset, asset)
    return f"{prefix}:{asset}{code}:{expiry}"


def options(source_dates=("2021-01-08", "2021-01-15", "2021-01-22"), expiry=None):
    rows = []
    for text in source_dates:
        day = pd.Timestamp(text)
        exp = pd.Timestamp(expiry) if expiry else day + pd.Timedelta(days=7)
        for asset in model.ASSETS:
            for strike, oi in [(90.0, 50.0), (110.0, 150.0), (200.0, 100_000.0)]:
                for side in ("call", "put"):
                    rows.append(
                        dict(
                            tradedate=day,
                            logical_asset=asset,
                            secid=f"{asset}{exp:%Y%m%d}-{strike}-{side}",
                            boardid="TEST",
                            available_at_utc=(
                                day.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)
                            ).tz_convert("UTC"),
                            openposition=oi,
                            metadata_ready=True,
                            option_class="margined_future_option",
                            first_trade_date=pd.Timestamp("2020-12-01"),
                            last_trade_date=exp,
                            expiry_date=exp,
                            underlying_contract_id=contract(asset),
                            option_type=side,
                            strike=strike,
                            unit=asset + "-same-quote-unit",
                            lot_size=1.0,
                            exercise_style="American",
                            series_name=f"{asset}-{exp:%Y%m%d}",
                            quote_units_compatible=True,
                        )
                    )
    return pd.DataFrame(rows)


def active():
    dates = pd.bdate_range("2021-01-08", "2021-01-29")
    return pd.concat(
        [
            pd.DataFrame(
                dict(
                    decision_date=dates[:-1],
                    effective_date=dates[1:],
                    observed_through=dates[:-1],
                    asset_code=asset,
                    contract_id=contract(asset),
                    plan_tradable=True,
                    roll=False,
                )
            )
            for asset in model.ASSETS
        ],
        ignore_index=True,
    )


def closes():
    return pd.concat(
        [
            pd.DataFrame(
                dict(
                    trade_date=pd.bdate_range("2021-01-08", "2021-01-29"),
                    logical_asset=asset,
                    canonical_contract_id=contract(asset),
                    close=98.0,
                )
            )
            for asset in model.ASSETS
        ],
        ignore_index=True,
    )


def build(raw=None, plan=None, quotes=None):
    return model.build_targets(
        active() if plan is None else plan,
        options() if raw is None else raw,
        closes() if quotes is None else quotes,
        config(),
    )


def at(frame, day="2021-01-11"):
    return frame.loc[frame.decision_date.eq(day)]


def test_rule_uses_only_immediate_brackets_not_the_largest_far_strike():
    state, targets = build()
    row = at(state)
    assert row.ready.all() and row.primary_direction.eq(1).all()
    assert row.control_direction.eq(-1).all()
    assert row.lower_strike.eq(90).all() and row.upper_strike.eq(110).all()
    assert row.lower_oi.eq(100).all() and row.upper_oi.eq(300).all()
    assert at(targets["primary"]).target_weight.eq(0.225).all()
    assert at(targets["control"]).target_weight.eq(-0.225).all()


def test_oi_magnitude_ablation_leaves_the_control_unchanged():
    raw = options()
    raw.loc[raw.strike.eq(90), "openposition"] = 1000.0
    a, ta = build()
    b, tb = build(raw)
    assert at(a).primary_direction.eq(1).all() and at(b).primary_direction.eq(-1).all()
    pd.testing.assert_series_equal(ta["control"].target_weight, tb["control"].target_weight)


def test_strict_prior_release_fill_and_expiry_flattening():
    state, targets = build()
    assert at(state, "2021-01-08").reason.eq("NO_SOURCE").all()
    used = targets["primary"].loc[targets["primary"].target_weight.ne(0)]
    assert used.source_date.lt(used.decision_date).all()
    assert used.available_at_utc.le(used.decision_at_utc).all()
    assert used.decision_date.lt(used.effective_date).all()
    assert used.effective_date.lt(used.selected_expiry).all()
    assert at(state, "2021-01-14").reason.eq("FILL_REACHES_EXPIRY").all()
    assert at(targets["primary"], "2021-01-14").contract_id.isna().all()
    assert targets["primary"].groupby("asset_code").tail(1).terminal_flat.all()
    assert targets["primary"].groupby("asset_code").tail(1).target_weight.eq(0).all()


@pytest.mark.parametrize("variant", ["oi", "distance", "exact"])
def test_ties_have_fixed_arm_specific_flat_policy(variant):
    raw, quote = options(), closes()
    if variant == "oi":
        raw.loc[raw.strike.eq(90), "openposition"] = 150.0
    else:
        quote["close"] = 100.0 if variant == "distance" else 110.0
    state, _ = build(raw, quotes=quote)
    row = at(state)
    assert row.ready.all()
    expected = {"oi": (0, -1), "distance": (1, 0), "exact": (0, 0)}[variant]
    assert row.primary_direction.eq(expected[0]).all()
    assert row.control_direction.eq(expected[1]).all()


@pytest.mark.parametrize("bad_oi", [np.nan, np.inf, -1.0])
def test_invalid_oi_is_masked_not_zero_and_no_fake_bracket(bad_oi):
    raw = options()
    raw.loc[raw.strike.eq(90), "openposition"] = bad_oi
    state, targets = build(raw)
    assert at(state).reason.eq("UNBRACKETED_PRICE").all()
    assert at(targets["primary"]).target_weight.eq(0).all()


def test_reported_zero_is_known_but_two_zero_brackets_do_not_generate_an_oi_signal():
    raw = options()
    raw.loc[raw.strike.isin([90, 110]), "openposition"] = 0.0
    state, _ = build(raw)
    assert at(state).reason.eq("ZERO_BRACKET_OI").all()


def test_new_missing_release_supersedes_old_good_without_fallback():
    raw = options(("2021-01-11", "2021-01-13"), expiry="2021-01-19")
    raw.loc[raw.tradedate.eq("2021-01-13"), "openposition"] = np.nan
    state, targets = build(raw)
    assert at(state, "2021-01-12").ready.all()
    after = at(state, "2021-01-14")
    assert after.source_date.eq(pd.Timestamp("2021-01-13")).all()
    assert after.reason.eq("NO_POSITIVE_REPORTED_OI").all()
    assert at(targets["primary"], "2021-01-14").target_weight.eq(0).all()


def test_delayed_source_does_not_backdate_or_displace_a_newer_available_source():
    raw = options(("2021-01-08", "2021-01-11"), expiry="2021-01-19")
    raw.loc[raw.tradedate.eq("2021-01-08"), "available_at_utc"] += pd.Timedelta(days=6)
    state, _ = build(raw)
    assert at(state, "2021-01-11").reason.eq("NO_SOURCE").all()
    assert at(state, "2021-01-12").source_date.eq(pd.Timestamp("2021-01-11")).all()
    assert at(state, "2021-01-15").source_date.eq(pd.Timestamp("2021-01-11")).all()


def test_cannot_skip_empty_or_fill_blocked_near_expiry_for_later_oi():
    near = options(("2021-01-08",), expiry="2021-01-12")
    later = options(("2021-01-08",), expiry="2021-01-15")
    raw = pd.concat([near, later], ignore_index=True)
    state, _ = build(raw)
    assert at(state).selected_expiry.eq(pd.Timestamp("2021-01-12")).all()
    assert at(state).reason.eq("FILL_REACHES_EXPIRY").all()
    near = options(("2021-01-08",), expiry="2021-01-13").assign(openposition=np.nan)
    state, _ = build(pd.concat([near, later], ignore_index=True))
    assert at(state).selected_expiry.eq(pd.Timestamp("2021-01-13")).all()
    assert at(state).reason.eq("NO_POSITIVE_REPORTED_OI").all()


@pytest.mark.parametrize(
    "field,value",
    [
        ("metadata_ready", False),
        ("quote_units_compatible", False),
        ("underlying_contract_id", None),
        ("first_trade_date", pd.Timestamp("2021-02-01")),
        ("strike", np.nan),
    ],
)
def test_unresolved_reported_mapping_masks_release_not_only_inconvenient_contract(field, value):
    raw = options()
    raw.loc[raw.strike.eq(200), field] = value
    state, targets = build(raw)
    assert at(state).reason.eq("UNRESOLVED_REPORTED_METADATA").all()
    assert at(state).unresolved_reported_rows.eq(2).all()
    assert at(targets["primary"]).target_weight.eq(0).all()


def test_explicit_currency_options_and_all_null_unknowns_are_counted_without_mixing():
    raw = options()
    currency = raw.copy().assign(
        secid=raw.secid + "-currency",
        option_class="premium_currency_option",
        underlying_contract_id=None,
        quote_units_compatible=False,
        unit="other",
        lot_size=100,
        openposition=1e12,
    )
    unknown = raw.copy().assign(
        secid=raw.secid + "-unknown",
        metadata_ready=False,
        quote_units_compatible=False,
        option_class=None,
        underlying_contract_id=None,
        openposition=np.nan,
    )
    baseline, targets_a = build(raw)
    state, targets_b = build(pd.concat([raw, currency, unknown], ignore_index=True))
    assert at(state).source_rows.eq(18).all()
    assert at(state).explicit_nonfuture_rows.eq(6).all()
    assert at(state).usable_oi_rows.eq(12).all()
    assert at(state).unusable_oi_rows.eq(6).all()
    assert at(state).unresolved_reported_rows.eq(0).all()
    for arm in model.ARMS:
        pd.testing.assert_series_equal(targets_a[arm].target_weight, targets_b[arm].target_weight)
    pd.testing.assert_series_equal(baseline.ready, state.ready)


@pytest.mark.parametrize(
    "field,value",
    [
        ("series_name", "another-series"),
        ("unit", "another-unit"),
        ("lot_size", 100.0),
        ("exercise_style", "European"),
    ],
)
def test_incompatible_same_expiry_pools_cannot_be_summed(field, value):
    raw = options()
    raw.loc[raw.strike.eq(200), field] = value
    state, _ = build(raw)
    assert at(state).reason.eq("INCOMPATIBLE_SERIES").all()


def test_exact_contract_close_required_at_roll_no_old_or_next_day_price_substitute():
    plan = active()
    mask = plan.decision_date.eq("2021-01-11")
    for asset in model.ASSETS:
        plan.loc[mask & plan.asset_code.eq(asset), "contract_id"] = contract(asset, "NEW")
    plan.loc[mask, "roll"] = True
    state, _ = build(plan=plan)
    assert at(state).reason.eq("MISSING_DECISION_CLOSE").all()
    q = closes()
    new = q.loc[q.trade_date.eq("2021-01-11")].copy()
    new["canonical_contract_id"] = new.logical_asset.map(lambda asset: contract(asset, "NEW"))
    state, _ = build(plan=plan, quotes=pd.concat([q, new], ignore_index=True))
    assert at(state).reason.eq("NO_MAPPED_EXPIRY").all()


def test_future_values_cannot_change_past_states_or_targets():
    raw, quote = options(), closes()
    cutoff = pd.Timestamp("2021-01-15")
    raw.loc[raw.tradedate.ge(cutoff), "openposition"] = 9999999.0
    quote.loc[quote.trade_date.gt(cutoff), "close"] = 777.0
    a, ta = build()
    b, tb = build(raw, quotes=quote)
    pd.testing.assert_frame_equal(
        a.loc[a.decision_date.le(cutoff)], b.loc[b.decision_date.le(cutoff)]
    )
    for arm in model.ARMS:
        pd.testing.assert_frame_equal(
            ta[arm].loc[ta[arm].decision_date.le(cutoff)],
            tb[arm].loc[tb[arm].decision_date.le(cutoff)],
        )


def test_stale_source_and_long_fill_delay_sleep_without_trimming_calendar():
    state, _ = build(options(("2021-01-08",), expiry="2021-01-29"))
    late = state.loc[state.effective_date.ge("2021-01-19")]
    assert late.reason.eq("STALE_SOURCE_OR_FILL").all()
    plan = active()
    plan["effective_date"] += pd.Timedelta(days=10)
    state, _ = build(plan=plan)
    assert state.loc[state.source_date.notna()].stale_at_fill.all()
    assert len(state) == len(plan)


@pytest.mark.parametrize(
    "mutation",
    [
        "protected_options",
        "protected_close",
        "early_clock",
        "duplicate_option",
        "duplicate_close",
        "future_map",
        "missing_asset",
        "labels",
        "string_flag",
    ],
)
def test_input_contract_rejects_leakage_and_ambiguous_identities(mutation):
    raw, plan, quote = options(), active(), closes()
    if mutation == "protected_options":
        raw.loc[0, "tradedate"] = pd.Timestamp("2026-01-01")
    elif mutation == "protected_close":
        quote.loc[0, "trade_date"] = pd.Timestamp("2026-01-01")
    elif mutation == "early_clock":
        raw["available_at_utc"] -= pd.Timedelta(days=1)
    elif mutation == "duplicate_option":
        raw = pd.concat([raw, raw.iloc[:1]], ignore_index=True)
    elif mutation == "duplicate_close":
        quote = pd.concat([quote, quote.iloc[:1]], ignore_index=True)
    elif mutation == "future_map":
        plan.loc[0, "observed_through"] = plan.loc[0, "effective_date"]
    elif mutation == "missing_asset":
        plan = plan.iloc[1:]
    elif mutation == "labels":
        quote["future_return"] = 1.0
    else:
        raw["metadata_ready"] = "False"
    with pytest.raises(ValueError):
        build(raw, plan, quote)


def test_both_arms_and_costs_use_existing_integer_ledger_with_terminal_flat():
    state, targets = build()
    rows = []
    for asset in model.ASSETS:
        for day in pd.bdate_range("2021-01-08", "2021-01-29"):
            rows.append(
                dict(
                    session_date=day,
                    asset_code=asset,
                    contract_id=contract(asset),
                    open=98.0,
                    high=98.0,
                    low=98.0,
                    settle=98.0,
                    volume=1_000_000.0,
                    sizing_point_value=100.0,
                    accounting_point_value=100.0,
                    tick_size=0.01,
                    fee_per_contract=1.0,
                    initial_margin=500.0,
                )
            )
    market = pd.DataFrame(rows)
    before = copy.deepcopy(targets)
    costs = {}
    for arm in model.ARMS:
        costs[arm] = {}
        for name, (ticks, fee) in config()["execution"]["costs"].items():
            result = model.base.run_futures_portfolio_ledger(
                market,
                targets[arm],
                model.base.FuturesPortfolioLedgerConfig(
                    expected_assets=model.ASSETS,
                    slippage_ticks=ticks,
                    fee_multiplier=fee,
                    execution_atomicity="asset",
                    unexecutable_target_policy="cancel_and_clip",
                ),
            )
            metrics = reporting.summarize(result)
            assert metrics["execution_complete"] and metrics["critical_failure_count"] == 0
            assert metrics["unresolved_halt_count"] == 0 and not metrics["terminal_carried"]
            assert metrics["round_trips"] > 0 and metrics["cagr"] < 0  # Flat market, costs only.
            costs[arm][name] = metrics["ending_cash"]
        assert costs[arm]["double"] < costs[arm]["base"]
        pd.testing.assert_frame_equal(before[arm], targets[arm])
    assert len(state) == len(active())


def test_empty_source_has_stable_schema_and_zero_targets_on_entire_calendar():
    state, targets = build(options().iloc[:0])
    assert len(state) == len(active()) and state.reason.eq("NO_SOURCE").all()
    assert state.selected_expiry.isna().all() and state.pool_rows.eq(0).all()
    for target in targets.values():
        assert target.target_weight.eq(0).all() and target.contract_id.isna().all()


def test_pre_evaluation_warmup_missing_decision_is_not_an_evaluation_input():
    plan = active()
    warmup = (
        plan.iloc[:1]
        .copy()
        .assign(
            effective_date=pd.Timestamp("2018-01-03"), decision_date=pd.NaT, observed_through=pd.NaT
        )
    )
    a, _ = build(plan=plan)
    b, _ = build(plan=pd.concat([warmup, plan], ignore_index=True))
    pd.testing.assert_frame_equal(a, b)


def test_missing_current_close_is_not_replaced_by_adjacent_date():
    q = closes()
    q.loc[q.trade_date.eq("2021-01-11"), "close"] = np.nan
    state, targets = build(quotes=q)
    assert at(state).reason.eq("MISSING_DECISION_CLOSE").all()
    assert at(targets["primary"]).target_weight.eq(0).all()


def test_distinct_board_duplicates_are_not_double_counted_as_new_open_interest():
    raw = options()
    duplicate = (
        raw.loc[raw.strike.eq(90)]
        .copy()
        .assign(boardid="SECOND", secid=raw.loc[raw.strike.eq(90), "secid"] + "-duplicate")
    )
    state, _ = build(pd.concat([raw, duplicate], ignore_index=True))
    assert at(state).reason.eq("DUPLICATE_STRIKE_SIDE").all()


def test_options_cannot_outlive_their_claimed_underlying_future():
    raw = options()
    raw["underlying_contract_id"] = raw.logical_asset.map(
        lambda asset: contract(asset, expiry="2021-01-10")
    )
    state, _ = build(raw)
    assert at(state).reason.eq("UNRESOLVED_REPORTED_METADATA").all()


def test_expired_future_plan_is_not_tradable_despite_a_true_flag():
    plan = active()
    plan["contract_id"] = plan.asset_code.map(lambda asset: contract(asset, expiry="2021-01-01"))
    state, targets = build(plan=plan)
    assert state.reason.eq("INVALID_PLAN").all()
    assert targets["primary"].target_weight.eq(0).all()
