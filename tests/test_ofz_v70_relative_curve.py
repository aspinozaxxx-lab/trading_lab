"""Synthetic contemporaneous curve, source clocks and unchanged bond cash accounting."""

import json

import numpy as np
import pandas as pd
import pytest

from market_lab import ofz_v70_relative_curve as screen


def config():
    return json.loads(screen.CONFIG.read_text(encoding="utf-8-sig"))


def history():
    rows = []
    bumps = [-0.1, 0.8, -0.05, 0.7, -0.1, -0.2, 0.6, -0.1, 0.01, -0.1]
    start = pd.Timestamp("2021-01-04")
    for day in pd.bdate_range(start, "2021-04-05"):
        for i, years in enumerate(np.linspace(2.5, 6.8, 10)):
            yield_value = 7 + years * 0.4 + years * years * 0.03 + bumps[i]
            clean = 100 + (day - start).days * 0.01
            rows.append(
                {
                    "trade_date": day,
                    "security_id": f"SU262TEST{i}",
                    "value_rub": 20_000_000.0,
                    "open_clean_pct": clean,
                    "close_clean_pct": clean + 0.005,
                    "wap_clean_pct": clean,
                    "legal_close_clean_pct": clean,
                    "accrued_interest_rub": 5.0,
                    "yield_at_wap_pct": yield_value,
                    "maturity_date": start + pd.Timedelta(days=round(years * 365.25)),
                    "face_value": 1000.0,
                    "currency_id": "SUR",
                    "face_unit": "RUB",
                    "available_at_utc": (
                        day.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)
                    ).tz_convert("UTC"),
                }
            )
    return pd.DataFrame(rows)


def prepared():
    return screen.engine.prepare_history(history(), config())


def empty_schedule():
    return pd.DataFrame(columns=screen.engine.SCHEDULE_COLUMNS)


def test_leave_one_out_fitted_value_excludes_own_yield():
    x = np.linspace(2, 7, 10)
    y = 8 + 0.3 * x + 0.01 * x * x
    y[3] += 1
    fitted, residual = screen.loo_residuals(x, y)
    assert residual[3] == pytest.approx(1)
    y[3] += 20
    changed, other = screen.loo_residuals(x, y)
    assert fitted[3] == pytest.approx(changed[3])
    assert other[3] == pytest.approx(21)


def test_perfect_quadratic_has_exact_numerical_zero_residuals():
    x = np.linspace(2, 7, 10)
    _, residual = screen.loo_residuals(x, 9 + 0.1 * x + 0.2 * x * x)
    assert (residual == 0).all()


@pytest.mark.parametrize("fault", ["rank", "nan", "infinite", "small"])
def test_bad_curve_is_not_fitted(fault):
    x, y = np.linspace(2, 7, 10), np.arange(10.0)
    if fault == "rank":
        x[:] = 4
    elif fault == "nan":
        y[0] = np.nan
    elif fault == "infinite":
        x[0] = np.inf
    else:
        x, y = x[:3], y[:3]
    with pytest.raises(ValueError):
        screen.loo_residuals(x, y)


def test_strict_prior_month_snapshot_and_same_curve_paired_control():
    chosen, scores = screen.decisions(prepared(), config())
    selected = chosen.loc[chosen.status.eq("selected")]
    assert selected.decision_date.nunique() == 3
    assert selected.groupby(["arm", "decision_date"]).size().eq(3).all()
    assert selected.groupby(["arm", "decision_date"]).target_weight.sum().eq(1).all()
    assert selected.available_at_utc.le(selected.decision_at_utc).all()
    assert selected.snapshot_date.lt(selected.decision_date).all()
    assert selected.loc[selected.arm.eq("primary"), "residual_yield_pct"].gt(0).all()
    for day, values in scores.groupby("decision_date"):
        expected = (
            values.assign(a=values.residual_yield_pct.abs())
            .sort_values(["a", "security_id"])
            .head(3)
        )
        actual = selected.loc[
            selected.arm.eq("control") & selected.decision_date.eq(day)
        ].sort_values("rank")
        assert actual.security_id.tolist() == expected.security_id.tolist()


def test_future_price_and_yield_mutation_cannot_change_earlier_decisions():
    raw = history()
    original, _ = screen.decisions(screen.engine.prepare_history(raw, config()), config())
    for col in (
        "yield_at_wap_pct",
        "open_clean_pct",
        "close_clean_pct",
        "wap_clean_pct",
        "legal_close_clean_pct",
    ):
        raw.loc[raw.trade_date.ge("2021-03-01"), col] *= 3
    changed, _ = screen.decisions(screen.engine.prepare_history(raw, config()), config())
    pd.testing.assert_frame_equal(
        original.loc[original.decision_date.le("2021-03-01")],
        changed.loc[changed.decision_date.le("2021-03-01")],
    )


def test_late_source_is_excluded_without_older_issue_fallback():
    frame = prepared()
    frame.loc[frame.trade_date.eq("2021-01-29"), "available_at_utc"] = pd.Timestamp(
        "2021-02-03", tz="UTC"
    )
    chosen, _ = screen.decisions(frame, config())
    feb = chosen.loc[chosen.decision_date.eq("2021-02-01")]
    assert feb.status.eq("insufficient_curve_issues").all()
    assert feb.security_id.isna().all()


def test_missing_yields_and_rank_deficiency_sleep_without_imputation():
    frame = prepared()
    frame.loc[
        frame.security_id.isin(["SU262TEST0", "SU262TEST1", "SU262TEST2"]), "yield_at_wap_pct"
    ] = np.nan
    chosen, _ = screen.decisions(frame, config())
    assert not chosen.status.eq("selected").any()
    frame = prepared()
    frame["maturity_date"] = pd.Timestamp("2025-01-01")
    chosen, _ = screen.decisions(frame, config())
    assert (
        chosen.loc[chosen.decision_date.gt("2021-01-04"), "status"].eq("rank_deficient_curve").all()
    )


def test_protected_history_and_duplicate_identities_rejected():
    raw = history()
    raw.loc[0, "trade_date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="protected"):
        screen.engine.prepare_history(raw, config())
    raw = history()
    with pytest.raises(ValueError, match="identity"):
        screen.engine.prepare_history(pd.concat([raw, raw.iloc[:1]]), config())


def test_existing_ledger_next_open_coupon_credit_and_terminal_cost_reserve():
    cfg, frame = config(), prepared()
    chosen, _ = screen.decisions(frame, cfg)
    primary = chosen.loc[chosen.arm.eq("primary")]
    security = primary.loc[primary.status.eq("selected"), "security_id"].iloc[0]
    schedule = pd.DataFrame(
        [
            {
                "event_kind": "coupon",
                "security_id": security,
                "event_date": pd.Timestamp("2021-02-10"),
                "record_date": pd.Timestamp("2021-02-08"),
                "value_rub": 10.0,
                "current_vintage": True,
            }
        ]
    )
    values = []
    for cost in cfg["cost_scenarios"]:
        result = screen.engine.simulate(frame, schedule, primary, cfg, cost)
        value, ledger = screen.summarize(result, cfg, cost)
        assert value["complete"] and value["completed_rebalances"] == 3
        assert result.trades.execution_date.gt(result.trades.decision_date).all()
        assert value["coupon_and_amortization_credit_rub"] > 0
        assert value["terminal_cost_reserve_rub"] > 0
        assert value["position_counts"]["terminal_open_episodes"] == 3
        assert ledger.reported_nav.iloc[-1] == pytest.approx(
            ledger.nav.iloc[-1] - value["terminal_cost_reserve_rub"]
        )
        assert (ledger.reported_nav.iloc[:-1] == ledger.nav.iloc[:-1]).all()
        values.append(value)
    assert values[0]["net_pnl_after_reserve_rub"] > values[1]["net_pnl_after_reserve_rub"]


def test_missing_held_mark_makes_full_period_metrics_null():
    cfg, frame = config(), prepared()
    chosen, _ = screen.decisions(frame, cfg)
    primary = chosen.loc[chosen.arm.eq("primary")]
    security = primary.loc[primary.status.eq("selected"), "security_id"].iloc[0]
    frame.loc[frame.trade_date.eq("2021-02-05") & frame.security_id.eq(security), "dirty_mark"] = (
        np.nan
    )
    result = screen.engine.simulate(frame, empty_schedule(), primary, cfg, "primary_10bps")
    value, ledger = screen.summarize(result, cfg, "primary_10bps")
    assert not value["complete"] and value["marked_sessions"] < value["total_sessions"]
    assert value["performance"] is None and value["position_counts"] is None
    assert ledger.reported_nav.isna().all()


def test_selection_is_independent_of_accounting_schedule():
    frame = prepared()
    before, scores_before = screen.decisions(frame, config())
    # Schedule is not an input to the predictor; accounting must not mutate history.
    screen.engine.simulate(
        frame, empty_schedule(), before.loc[before.arm.eq("primary")], config(), "primary_10bps"
    )
    after, scores_after = screen.decisions(frame, config())
    pd.testing.assert_frame_equal(before, after)
    pd.testing.assert_frame_equal(scores_before, scores_after)


def test_gate_requires_excess_over_control_both_costs_and_full_accounting():
    cfg = config()

    def value(cagr):
        return {
            "complete": True,
            "completed_rebalances": 55,
            "performance": {
                "cagr": cagr,
                "sharpe": 1.0,
                "maximum_drawdown": 0.1,
                "positive_years": 5,
                "worst_year": 0.01,
                "annual_returns": dict.fromkeys(cfg["screen_gates"]["expected_years"], 0.1),
            },
        }

    metrics = {
        arm: {cost: value(0.1 if arm == "primary" else 0.05) for cost in cfg["cost_scenarios"]}
        for arm in screen.ARMS
    }
    counts = {"months": 60, "selected_months": 55}
    assert screen.assess(metrics, counts, cfg)["verdict"] == "STAGE2_CANDIDATE"
    metrics["primary"]["doubled_20bps"]["performance"]["cagr"] = 0.06
    assert screen.assess(metrics, counts, cfg)["verdict"] == "REJECT_STAGE1"
    metrics["control"]["primary_10bps"] = {"complete": False, "performance": None}
    assert screen.assess(metrics, counts, cfg)["verdict"] == "INVALID_INCOMPLETE_ACCOUNTING"
