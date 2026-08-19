"""Integer-contract, capacity-limited corridor portfolio evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from math import floor, isfinite, sqrt
from typing import Final
from zoneinfo import ZoneInfo

import pandas as pd

from market_lab.futures_v9_corridor.data import CorridorSourceBundle

MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
INITIAL_CAPITAL: Final[float] = 1_000_000.0
TARGET_GROSS_PER_TRADE: Final[float] = 0.18
MAXIMUM_GROSS: Final[float] = 1.0
CAPACITY_FRACTION: Final[float] = 0.01


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """One corridor/cost ledger and its report."""

    corridor_id: str
    cost_multiplier: float
    attempts: pd.DataFrame
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    metrics: dict[str, object]


def _local_window(day: object, hour: int, minute: int) -> datetime:
    return datetime.combine(pd.Timestamp(day).date(), time(hour, minute), MOSCOW).astimezone(UTC)


def _spec_lookup(spec: pd.DataFrame) -> dict[tuple[object, str], pd.Series]:
    usable = spec.copy()
    if usable.duplicated(["session_date", "contract_id"]).any():
        duplicates = usable[usable.duplicated(["session_date", "contract_id"], keep=False)]
        if duplicates.groupby(["session_date", "contract_id"]).size().max() > 1:
            usable = usable.sort_values(["session_date", "contract_id"]).drop_duplicates(
                ["session_date", "contract_id"], keep="last"
            )
    return {
        (row.session_date, str(row.contract_id)): pd.Series(row._asdict())
        for row in usable.itertuples(index=False)
    }


def _mark_price(
    bundle: CorridorSourceBundle,
    contract_id: str,
    decision_at: pd.Timestamp,
) -> float | None:
    opened = _local_window(decision_at.tz_convert(MOSCOW).date(), 18, 40)
    row = bundle.bar_store.exact_bar(contract_id, opened)
    if row is None:
        return None
    value = float(row["close"])
    return value if isfinite(value) and value > 0.0 else None


def _equity_at(
    bundle: CorridorSourceBundle,
    trades: list[dict[str, object]],
    decision_at: pd.Timestamp,
) -> tuple[float | None, float | None]:
    equity = INITIAL_CAPITAL
    gross = 0.0
    for trade in trades:
        entry_at = pd.Timestamp(trade["entry_at"])
        event_at = pd.Timestamp(trade["event_at"])
        if entry_at >= decision_at:
            continue
        if event_at <= decision_at:
            equity += float(trade["net_pnl"])
            continue
        mark = _mark_price(bundle, str(trade["contract_id"]), decision_at)
        if mark is None:
            return None, None
        sign = 1.0 if trade["direction"] == "long" else -1.0
        quantity = int(trade["quantity"])
        point_value = float(trade["point_value"])
        equity += (
            sign * (mark - float(trade["entry_price"])) * point_value * quantity
            - float(trade["entry_fee"])
        )
        gross += abs(mark * point_value * quantity)
    return equity, gross


def _performance_metrics(equity: pd.DataFrame) -> dict[str, object]:
    if equity.empty or equity["equity"].isna().any():
        return {
            "cagr": None,
            "sharpe": None,
            "maximum_drawdown": None,
            "year_returns": {},
            "metric_status": "NO_GO_missing_mark",
        }
    values = equity["equity"].astype(float)
    if (values <= 0.0).any():
        return {
            "cagr": None,
            "sharpe": None,
            "maximum_drawdown": None,
            "year_returns": {},
            "metric_status": "NO_GO_nonpositive_equity",
        }
    daily = values.pct_change().fillna(0.0)
    elapsed_years = max(
        (pd.Timestamp(equity["decision_at"].iloc[-1]) - pd.Timestamp(equity["decision_at"].iloc[0]))
        .total_seconds()
        / (365.25 * 24.0 * 3600.0),
        1.0 / 365.25,
    )
    cagr = float((values.iloc[-1] / values.iloc[0]) ** (1.0 / elapsed_years) - 1.0)
    scale = float(daily.std(ddof=0))
    sharpe = float(sqrt(252.0) * daily.mean() / scale) if scale > 0.0 else 0.0
    drawdown = values / values.cummax() - 1.0
    years = pd.to_datetime(equity["decision_at"], utc=True).dt.year
    year_returns = {
        str(int(year)): float((1.0 + daily[years == year]).prod() - 1.0)
        for year in sorted(years.unique())
    }
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": float(drawdown.min()),
        "year_returns": year_returns,
        "metric_status": "OK",
    }


def run_corridor_backtest(
    bundle: CorridorSourceBundle,
    predictions: pd.DataFrame,
    *,
    corridor_id: str,
    cost_multiplier: float,
) -> BacktestResult:
    """Evaluate train-only selected signals in chronological order."""
    if cost_multiplier not in {1.0, 2.0}:
        raise ValueError("only sealed 1x and 2x cost scenarios are allowed")
    signals = predictions[
        (predictions["corridor_id"] == corridor_id)
        & predictions["daily_model_choice"].astype(bool)
    ].sort_values("decision_at", kind="stable")
    specs = _spec_lookup(bundle.spec_proxy)
    trades: list[dict[str, object]] = []
    attempts: list[dict[str, object]] = []
    for signal in signals.itertuples(index=False):
        decision_at = pd.Timestamp(signal.decision_at)
        entry_at = pd.Timestamp(_local_window(signal.decision_date, 19, 20))
        attempt: dict[str, object] = {
            "corridor_id": corridor_id,
            "cost_multiplier": cost_multiplier,
            "decision_at": decision_at,
            "entry_at": entry_at,
            "asset": str(signal.asset),
            "direction": str(signal.direction),
            "contract_id": str(signal.contract_id),
            "probability": float(signal.calibrated_tp_probability),
            "threshold": float(signal.fold_threshold),
            "status": "pending",
            "reason": None,
            "requested_quantity": 0,
            "capacity_contracts": 0,
            "filled_quantity": 0,
        }
        equity, current_gross = _equity_at(bundle, trades, decision_at)
        if equity is None or current_gross is None or equity <= 0.0:
            attempt.update(status="unresolved", reason="missing_locked_contract_mark")
            attempts.append(attempt)
            continue
        active = [
            trade
            for trade in trades
            if pd.Timestamp(trade["entry_at"]) < entry_at < pd.Timestamp(trade["event_at"])
        ]
        if any(trade["asset"] == signal.asset for trade in active):
            attempt.update(status="rejected", reason="asset_position_already_open")
            attempts.append(attempt)
            continue
        spec = specs.get((signal.decision_date, str(signal.contract_id)))
        if spec is None or not bool(spec.get("sizing_usable", False)):
            attempt.update(status="unresolved", reason="missing_or_unusable_spec")
            attempts.append(attempt)
            continue
        numeric = {
            name: float(spec[name])
            for name in (
                "sizing_point_value",
                "sizing_notional",
                "conservative_fee_per_side",
                "modeled_initial_margin",
            )
        }
        if not all(isfinite(value) and value > 0.0 for value in numeric.values()):
            attempt.update(status="unresolved", reason="nonfinite_spec")
            attempts.append(attempt)
            continue
        requested = floor(TARGET_GROSS_PER_TRADE * equity / numeric["sizing_notional"])
        capacity = floor(float(signal.entry_volume) * CAPACITY_FRACTION)
        attempt["requested_quantity"] = requested
        attempt["capacity_contracts"] = capacity
        if requested <= 0:
            attempt.update(status="rejected", reason="integer_quantity_zero")
            attempts.append(attempt)
            continue
        if capacity < requested:
            attempt.update(status="unresolved", reason="partial_fill_capacity")
            attempts.append(attempt)
            continue
        entry_notional = abs(
            float(signal.entry_price) * numeric["sizing_point_value"] * requested
        )
        if (current_gross + entry_notional) / equity > MAXIMUM_GROSS + 1e-12:
            attempt.update(status="rejected", reason="maximum_gross")
            attempts.append(attempt)
            continue
        fee_per_side = numeric["conservative_fee_per_side"] * cost_multiplier
        entry_fee = fee_per_side * requested
        exit_fee = fee_per_side * requested
        gross_pnl = float(signal.gross_price_pnl) * numeric["sizing_point_value"] * requested
        net_pnl = gross_pnl - entry_fee - exit_fee
        trade = {
            **attempt,
            "status": "filled",
            "reason": None,
            "quantity": requested,
            "filled_quantity": requested,
            "entry_price": float(signal.entry_price),
            "exit_price": float(signal.exit_price),
            "event_type": str(signal.event_type),
            "event_at": pd.Timestamp(signal.event_at),
            "point_value": numeric["sizing_point_value"],
            "entry_notional": entry_notional,
            "modeled_initial_margin": numeric["modeled_initial_margin"] * requested,
            "entry_fee": entry_fee,
            "exit_fee": exit_fee,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "participation": requested / float(signal.entry_volume),
            "same_bar_collision": bool(signal.same_bar_collision),
        }
        trades.append(trade)
        attempt.update(status="filled", filled_quantity=requested)
        attempts.append(attempt)
    attempts_frame = pd.DataFrame(attempts)
    trades_frame = pd.DataFrame(trades)
    curve_rows: list[dict[str, object]] = []
    oos_decisions = [item for item in bundle.decisions if 2021 <= item.year <= 2025]
    for raw_decision in oos_decisions:
        decision_at = pd.Timestamp(raw_decision)
        equity, gross = _equity_at(bundle, trades, decision_at)
        curve_rows.append(
            {
                "decision_at": decision_at,
                "session_date": raw_decision.astimezone(MOSCOW).date(),
                "equity": equity,
                "gross_notional": gross,
                "gross_leverage": (
                    None if equity is None or gross is None or equity <= 0.0 else gross / equity
                ),
            }
        )
    equity_frame = pd.DataFrame(curve_rows)
    performance = _performance_metrics(equity_frame)
    if trades_frame.empty:
        win_rate = payoff = tp_rate = max_participation = 0.0
        event_counts: dict[str, int] = {}
        asset_counts: dict[str, int] = {}
        direction_counts: dict[str, int] = {}
    else:
        wins = trades_frame[trades_frame["net_pnl"] > 0.0]["net_pnl"]
        losses = trades_frame[trades_frame["net_pnl"] < 0.0]["net_pnl"]
        win_rate = float((trades_frame["net_pnl"] > 0.0).mean())
        payoff = (
            float(wins.mean() / abs(losses.mean()))
            if len(wins) and len(losses) and losses.mean() != 0.0
            else 0.0
        )
        tp_rate = float((trades_frame["event_type"] == "take_profit").mean())
        max_participation = float(trades_frame["participation"].max())
        event_counts = {
            str(key): int(value)
            for key, value in trades_frame["event_type"].value_counts().items()
        }
        asset_counts = {
            str(key): int(value) for key, value in trades_frame["asset"].value_counts().items()
        }
        direction_counts = {
            str(key): int(value)
            for key, value in trades_frame["direction"].value_counts().items()
        }
    attempt_counts = (
        {}
        if attempts_frame.empty
        else {
            str(key): int(value)
            for key, value in attempts_frame["reason"].fillna("filled").value_counts().items()
        }
    )
    nominal_required = 2.8 / 3.6 if corridor_id == "primary" else 1.6 / 2.8
    metrics: dict[str, object] = {
        "corridor_id": corridor_id,
        "cost_multiplier": cost_multiplier,
        "model_choice_count": len(signals),
        "trade_count": len(trades_frame),
        "win_rate": win_rate,
        "tp_event_rate": tp_rate,
        "nominal_break_even_win_rate": nominal_required,
        "win_rate_minus_nominal_required": win_rate - nominal_required,
        "payoff_ratio": payoff,
        "event_counts": event_counts,
        "asset_counts": asset_counts,
        "direction_counts": direction_counts,
        "attempt_reason_counts": attempt_counts,
        "maximum_participation": max_participation,
        "maximum_gross_leverage": (
            None
            if equity_frame["gross_leverage"].dropna().empty
            else float(equity_frame["gross_leverage"].max())
        ),
        "same_bar_collision_trades": (
            0 if trades_frame.empty else int(trades_frame["same_bar_collision"].sum())
        ),
        **performance,
    }
    return BacktestResult(
        corridor_id=corridor_id,
        cost_multiplier=cost_multiplier,
        attempts=attempts_frame,
        trades=trades_frame,
        equity_curve=equity_frame,
        metrics=metrics,
    )


__all__ = ["BacktestResult", "run_corridor_backtest"]
