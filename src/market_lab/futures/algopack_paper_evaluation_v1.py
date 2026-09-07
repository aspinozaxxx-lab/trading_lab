"""Fixed prospective daily paper evaluation; no source IO, historical runs or promotion."""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime, time, timedelta

from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW, utc
from market_lab.futures.algopack_paper_execution_v1 import INITIAL_CAPITAL_RUB
from market_lab.futures.algopack_paper_inference_v1 import MODEL_SHA, sha
from market_lab.futures.algopack_paper_market_core_v1 import RequestWindow

PROTOCOL = "algopack_paper_evaluation_v1"
DECISIONS_PER_DAY = 42 * 4
MIN_ANNUAL_SESSIONS = 252
MIN_ANNUAL_DAYS = 365
COSTS = ("1x", "2x")
COUNTS = (
    "ready",
    "sleep",
    "failed",
    "missing",
    "entries",
    "closed",
    "open_positions",
    "pending_positions",
    "unresolved_positions",
)


def _clock(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if utc(result).isoformat() != value:
        raise ValueError("canonical UTC evaluation clock required")
    return result


def _metrics(days: list[date], equity: list[float], start: datetime, end: datetime) -> dict:
    curve = [INITIAL_CAPITAL_RUB, *equity]
    peak, drawdown = curve[0], 0.0
    for value in curve:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    if min(curve) <= 0:
        return dict(
            status="CAPITAL_EXHAUSTED",
            total_return=curve[-1] / curve[0] - 1,
            cagr=None,
            sharpe_zero_rf=None,
            mdd_daily=drawdown,
            by_year={},
        )
    returns = [right / left - 1 for left, right in zip(curve, curve[1:], strict=False)]
    elapsed_days = (utc(end) - utc(start)).total_seconds() / 86400
    annual = len(days) >= MIN_ANNUAL_SESSIONS and elapsed_days >= MIN_ANNUAL_DAYS
    std = statistics.stdev(returns) if len(returns) > 1 else 0.0
    yearly, previous = {}, curve[0]
    for day, value in zip(days, equity, strict=True):
        key = str(day.year)
        if key not in yearly:
            yearly[key] = dict(start_equity=previous, end_equity=value, sessions=0)
        yearly[key]["end_equity"] = value
        yearly[key]["sessions"] += 1
        previous = value
    for row in yearly.values():
        row["return_not_annualized"] = row["end_equity"] / row["start_equity"] - 1
    total = curve[-1] / curve[0] - 1
    return dict(
        status="DESCRIPTIVE_ONLY",
        total_return=total,
        cagr=math.expm1(math.log1p(total) * 365.2425 / elapsed_days) if annual else None,
        sharpe_zero_rf=(statistics.mean(returns) / std * math.sqrt(252))
        if annual and std > 0
        else None,
        mdd_daily=drawdown,
        by_year=yearly,
        annualization_eligible=annual,
        intraday_mdd_verified=False,
        risk_free_rate_assumption=0.0,
    )


def evaluate(
    *,
    expected_days: tuple[date, ...],
    observations: list[dict],
    future_start: datetime,
    evaluated_at: datetime,
    calendar_sha256: str,
) -> dict:
    """Caller owes sealed calendar/snapshot/ledger evidence; no source mask may select days."""
    RequestWindow(future_start, evaluated_at)
    sha(calendar_sha256)
    if (
        not isinstance(expected_days, tuple)
        or any(type(day) is not date for day in expected_days)
        or list(expected_days) != sorted(set(expected_days))
    ):
        raise ValueError("expected calendar must be an ordered unique date tuple")
    boundary_day = utc(future_start).astimezone(MOSCOW).date()
    for day in expected_days:
        if (
            day < boundary_day
            or day.weekday() >= 5
            or datetime.combine(day, time(18, 20, 30), MOSCOW) > utc(evaluated_at)
        ):
            raise ValueError("calendar outside matured fixed prospective evaluation period")
    records = {}
    for row in observations:
        day = date.fromisoformat(row["day"])
        if row["day"] != day.isoformat() or day not in expected_days or day in records:
            raise ValueError("unexpected/duplicate daily snapshot")
        valuation, observed = _clock(row["valuation_at"]), _clock(row["observed_at"])
        scheduled = datetime.combine(day, time(18, 20), MOSCOW)
        if not scheduled <= valuation <= observed <= scheduled + timedelta(seconds=30):
            raise ValueError("daily snapshot is outside fixed actual observation window")
        if observed > utc(evaluated_at):
            raise ValueError("snapshot received after evaluation")
        sha(row["ledger_sha256"])
        if set(row["arms"]) != set(MODEL_SHA):
            raise ValueError("both paired paper arms required")
        for arm in row["arms"].values():
            counts = arm["counts"]
            if (
                set(counts) != set(COUNTS)
                or any(type(value) is not int or value < 0 for value in counts.values())
                or sum(counts[name] for name in COUNTS[:4]) != DECISIONS_PER_DAY
            ):
                raise ValueError("daily decision denominator/count mismatch")
            if arm["status"] not in {"VALUED", "UNRESOLVED_MARK", "UNRESOLVED_POSITION"}:
                raise ValueError("invalid daily valuation state")
            values = arm["equity_rub"]
            if values is not None:
                if set(values) != set(COSTS) or any(
                    type(value) not in (int, float) or not math.isfinite(value)
                    for value in values.values()
                ):
                    raise ValueError("invalid cost-scenario equity")
                if values["2x"] > values["1x"] + 1e-6:
                    raise ValueError("same-trade doubled costs cannot improve equity")
            elif arm["status"] == "VALUED":
                raise ValueError("valued snapshot lacks equity")
        records[day] = row
    missing_days = [day.isoformat() for day in expected_days if day not in records]
    output = dict(
        protocol_id=PROTOCOL,
        future_start=utc(future_start).isoformat(),
        evaluated_at=utc(evaluated_at).isoformat(),
        calendar_sha256=calendar_sha256,
        expected_sessions=len(expected_days),
        observed_sessions=len(records),
        missing_days=missing_days,
        arms={},
        status="NO_DATA" if not expected_days else "DESCRIPTIVE_PAPER_ONLY",
        live_trading_allowed=False,
        target_income_verified=False,
        broker_fee_verified=False,
        execution_verified=False,
    )
    for name in MODEL_SHA:
        counts = {key: 0 for key in COUNTS[:6]}
        invalid, equity, days, closes_by_year = [], {cost: [] for cost in COSTS}, [], {}
        for day in expected_days:
            if day not in records:
                continue
            arm = records[day]["arms"][name]
            for key in counts:
                counts[key] += arm["counts"][key]
            year = str(day.year)
            closes_by_year[year] = closes_by_year.get(year, 0) + arm["counts"]["closed"]
            if (
                arm["status"] != "VALUED"
                or arm["equity_rub"] is None
                or any(arm["counts"][key] for key in COUNTS[6:])
            ):
                invalid.append(day.isoformat())
                continue
            days.append(day)
            for cost in COSTS:
                equity[cost].append(arm["equity_rub"][cost])
        complete = bool(expected_days) and not missing_days and not invalid
        metrics = (
            {
                cost: _metrics(
                    days, equity[cost], future_start, _clock(records[days[-1]]["valuation_at"])
                )
                for cost in COSTS
            }
            if complete
            else None
        )
        output["arms"][name] = dict(
            counts=counts,
            closed_trades_by_year=closes_by_year,
            unresolved_days=invalid,
            complete_equity_curve=complete,
            metrics=metrics,
            decision_coverage=(counts["ready"] + counts["sleep"])
            / (len(expected_days) * DECISIONS_PER_DAY)
            if expected_days
            else None,
        )
    return output
