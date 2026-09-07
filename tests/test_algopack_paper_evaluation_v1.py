"""Pure artificial future equity; no historical/actual AlgoPack economic evaluation."""

import copy
from datetime import date, datetime, time, timedelta

import pytest
from test_algopack_paper_journal_v1 import START

from market_lab.futures import algopack_paper_evaluation_v1 as core
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW, utc


def snapshot(day, value=1_000_000.0):
    clock = utc(datetime.combine(day, time(18, 20), MOSCOW)).isoformat()
    counts = {name: 0 for name in core.COUNTS}
    counts["sleep"] = core.DECISIONS_PER_DAY
    if value != 1_000_000.0:
        counts.update(ready=1, sleep=core.DECISIONS_PER_DAY - 1, entries=1, closed=1)
    return dict(
        day=day.isoformat(),
        valuation_at=clock,
        observed_at=clock,
        ledger_sha256="a" * 64,
        arms={
            arm: dict(status="VALUED", equity_rub={"1x": value, "2x": value}, counts=dict(counts))
            for arm in core.MODEL_SHA
        },
    )


def evaluate(days, rows):
    end = utc(datetime.combine(days[-1], time(19), MOSCOW)) if days else START
    return core.evaluate(
        expected_days=tuple(days),
        observations=rows,
        future_start=START,
        evaluated_at=end,
        calendar_sha256="b" * 64,
    )


def test_short_sample_no_annualization_and_initial_drawdown_included():
    days = [date(2026, 9, 8), date(2026, 9, 9)]
    result = evaluate(days, [snapshot(days[0], 900000), snapshot(days[1], 950000)])
    metrics = result["arms"]["price_flow"]["metrics"]["1x"]
    assert metrics["total_return"] == pytest.approx(-0.05)
    assert metrics["mdd_daily"] == pytest.approx(-0.1)
    assert metrics["cagr"] is metrics["sharpe_zero_rf"] is None
    assert result["target_income_verified"] is False


def test_missing_day_invalidates_curve_without_trimming_or_forward_fill():
    days = [date(2026, 9, 8), date(2026, 9, 9)]
    result = evaluate(days, [snapshot(days[1])])
    assert result["missing_days"] == [days[0].isoformat()]
    assert all(arm["metrics"] is None for arm in result["arms"].values())
    assert result["arms"]["price_flow"]["decision_coverage"] == 0.5


@pytest.mark.parametrize("case", ["unknown", "open", "pending", "unresolved"])
def test_bad_full_arm_does_not_hide_baseline_or_count_unknown_as_zero(case):
    day = date(2026, 9, 8)
    row = snapshot(day)
    arm = row["arms"]["price_flow"]
    if case == "unknown":
        arm.update(status="UNRESOLVED_MARK", equity_rub=None)
    else:
        arm["counts"][case + "_positions"] = 1
    result = evaluate([day], [row])
    assert result["arms"]["price_flow"]["metrics"] is None
    assert result["arms"]["price_only"]["metrics"] is not None


@pytest.mark.parametrize(
    "case", ["duplicate", "counts", "boolean", "late", "future", "costs", "nan"]
)
def test_invalid_snapshot_fails(case):
    day = date(2026, 9, 8)
    row = snapshot(day)
    arm = row["arms"]["price_only"]
    if case == "counts":
        arm["counts"]["ready"] = 1
    elif case == "boolean":
        arm["counts"]["closed"] = True
    elif case == "late":
        row["observed_at"] = utc(datetime.combine(day, time(18, 21), MOSCOW)).isoformat()
    elif case == "future":
        row["valuation_at"] = utc(datetime.combine(day, time(18, 20, 1), MOSCOW)).isoformat()
    elif case == "costs":
        arm["equity_rub"]["2x"] += 1
    elif case == "nan":
        arm["equity_rub"]["1x"] = float("nan")
    with pytest.raises(ValueError):
        evaluate([day], [row, copy.deepcopy(row)] if case == "duplicate" else [row])


def test_zero_trades_and_flat_curve_remain_zero_result_not_success():
    day = date(2026, 9, 8)
    result = evaluate([day], [snapshot(day)])
    arm = result["arms"]["price_flow"]
    assert arm["counts"]["entries"] == arm["counts"]["closed"] == 0
    assert arm["metrics"]["1x"]["total_return"] == 0
    assert result["target_income_verified"] is False


def test_full_year_annualization_is_descriptive_not_target_verification():
    days = [date(2026, 9, 8) + timedelta(days=i) for i in range(370)]
    days = [day for day in days if day.weekday() < 5]
    rows = [
        snapshot(day, 1_000_000 * (1.0 + i / len(days) * 0.25)) for i, day in enumerate(days, 1)
    ]
    result = evaluate(days, rows)
    metrics = result["arms"]["price_flow"]["metrics"]["1x"]
    assert 0.20 < metrics["cagr"] < 0.30
    assert metrics["sharpe_zero_rf"] is not None
    assert set(metrics["by_year"]) == {"2026", "2027"}
    assert result["target_income_verified"] is result["execution_verified"] is False


def test_capital_exhaustion_not_positive_cagr():
    day = date(2026, 9, 8)
    metrics = evaluate([day], [snapshot(day, -100.0)])["arms"]["price_flow"]["metrics"]["1x"]
    assert metrics["status"] == "CAPITAL_EXHAUSTED" and metrics["cagr"] is None


def test_empty_evaluation_is_not_complete():
    result = evaluate([], [])
    assert result["status"] == "NO_DATA"
    assert all(arm["metrics"] is None for arm in result["arms"].values())
