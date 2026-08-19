"""Posledovatelnyi backtest s ispolneniem na sleduyushchem open."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from market_lab.backtest.metrics import calculate_metrics
from market_lab.config import PortfolioConfig

POSITION_TOLERANCE = 1e-12  # Dopusk dlya sravneniya drobnyh pozicii.


@dataclass(frozen=True)
class BacktestResult:
    """Obedinyaet metriki, sdelki, kapital, pozicii i dohodnosti."""

    metrics: dict[str, Any]
    trades: pd.DataFrame
    equity_curve: pd.DataFrame
    positions: pd.DataFrame
    returns: pd.Series


def calculate_commission(notional: float, commission_bps: float) -> float:
    """Schitaet komissiyu ot absolyutnogo oborota v bazovoi valyute."""
    if notional < 0 or commission_bps < 0:
        raise ValueError("Oborot i stavka komissii ne mogut byt otricatelnymi")
    return float(notional * commission_bps / 10_000.0)


def adverse_fill_price(open_price: float, quantity_delta: float, slippage_bps: float) -> float:
    """Sdvigaet cenu protiv napravleniya pokupki ili prodazhi."""
    if open_price <= 0 or slippage_bps < 0:
        raise ValueError("Cena dolzhna byt polozhitelnoi, a proskalzyvanie neotricatelnym")
    direction = 1.0 if quantity_delta > 0 else -1.0
    return float(open_price * (1.0 + direction * slippage_bps / 10_000.0))


def _empty_trades() -> pd.DataFrame:
    """Vozvrashchaet pustuyu tablicu sdelok so stabilnoi schemoi."""
    return pd.DataFrame(
        columns=[
            "timestamp",
            "signal_timestamp",
            "side",
            "quantity",
            "fill_price",
            "notional",
            "commission",
            "slippage_cost",
            "turnover",
        ]
    )


def run_backtest(
    frame: pd.DataFrame,
    targets: pd.Series,
    portfolio: PortfolioConfig,
    annualization_factor: int,
) -> BacktestResult:
    """Ispolnyaet signal t na open t+1 i schitaet mark-to-market po close."""
    if frame.empty:
        raise ValueError("Nelzya zapustit backtest na pustom nabore")
    aligned_targets = targets.reindex(frame.index).fillna(0.0).astype(float).clip(-1.0, 1.0)
    if not portfolio.allow_short and (aligned_targets < 0).any():
        raise ValueError("Konfiguraciya zapreshchaet korotkie pozicii")
    cash = float(portfolio.initial_capital)
    quantity = 0.0
    current_target = 0.0
    previous_equity = float(portfolio.initial_capital)
    total_turnover = 0.0
    total_commission = 0.0
    total_slippage = 0.0
    trade_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    return_values: list[float] = []
    for offset, (timestamp, bar) in enumerate(frame.iterrows()):
        open_price = float(bar["open"])
        close_price = float(bar["close"])
        executed_target = 0.0 if offset == 0 else float(aligned_targets.iloc[offset - 1])
        pretrade_equity = cash + quantity * open_price
        if pretrade_equity <= 0:
            raise ValueError("Kapital stal nepolozhitelnym do rebalansirovki")
        target_changed = abs(executed_target - current_target) > POSITION_TOLERANCE
        desired_quantity = (
            executed_target * pretrade_equity / open_price if target_changed else quantity
        )
        quantity_delta = desired_quantity - quantity
        if abs(quantity_delta) > POSITION_TOLERANCE:
            fill_price = adverse_fill_price(
                open_price, quantity_delta, portfolio.slippage_bps
            )
            notional = abs(quantity_delta) * open_price
            commission = calculate_commission(notional, portfolio.commission_bps)
            slippage_cost = abs(quantity_delta) * abs(fill_price - open_price)
            turnover = notional / pretrade_equity
            cash -= quantity_delta * fill_price + commission
            quantity = desired_quantity
            total_turnover += turnover
            total_commission += commission
            total_slippage += slippage_cost
            trade_rows.append(
                {
                    "timestamp": timestamp,
                    "signal_timestamp": frame.index[offset - 1],
                    "side": "buy" if quantity_delta > 0 else "sell",
                    "quantity": abs(quantity_delta),
                    "fill_price": fill_price,
                    "notional": notional,
                    "commission": commission,
                    "slippage_cost": slippage_cost,
                    "turnover": turnover,
                }
            )
        current_target = executed_target
        equity = cash + quantity * close_price
        if equity <= 0:
            raise ValueError("Kapital stal nepolozhitelnym posle pereocenki")
        period_return = equity / previous_equity - 1.0
        previous_equity = equity
        return_values.append(period_return)
        equity_rows.append({"timestamp": timestamp, "equity": equity, "return": period_return})
        position_rows.append(
            {
                "timestamp": timestamp,
                "signal_target": float(aligned_targets.iloc[offset]),
                "executed_target": executed_target,
                "quantity": quantity,
                "cash": cash,
                "exposure": quantity * close_price / equity,
            }
        )
    equity_curve = pd.DataFrame(equity_rows).set_index("timestamp")
    positions = pd.DataFrame(position_rows).set_index("timestamp")
    trades = pd.DataFrame(trade_rows) if trade_rows else _empty_trades()
    returns = pd.Series(return_values, index=frame.index, name="return")
    metrics = calculate_metrics(
        equity=equity_curve["equity"],
        returns=returns,
        initial_capital=portfolio.initial_capital,
        annualization_factor=annualization_factor,
        turnover=total_turnover,
        trade_count=len(trade_rows),
        commission_cost=total_commission,
        slippage_cost=total_slippage,
    )
    return BacktestResult(
        metrics=metrics,
        trades=trades,
        equity_curve=equity_curve,
        positions=positions,
        returns=returns,
    )


def aggregate_backtests(
    results: list[BacktestResult],
    initial_capital: float,
    annualization_factor: int,
) -> BacktestResult:
    """Obedinyaet nepreryvayushchiesya OOS-foldy v odnu validation-krivuyu."""
    if not results:
        raise ValueError("Nuzhen hotya by odin rezultat dlya agregacii")
    returns = pd.concat([result.returns for result in results]).sort_index()
    equity_values = initial_capital * (1.0 + returns).cumprod()
    equity_curve = pd.DataFrame({"equity": equity_values, "return": returns})
    trade_frames = [result.trades for result in results if not result.trades.empty]
    trades = pd.concat(trade_frames, ignore_index=True) if trade_frames else _empty_trades()
    positions = pd.concat([result.positions for result in results]).sort_index()
    turnover = sum(float(result.metrics["turnover"]) for result in results)
    commission = sum(float(result.metrics["commission_cost"]) for result in results)
    slippage = sum(float(result.metrics["slippage_cost"]) for result in results)
    metrics = calculate_metrics(
        equity=equity_curve["equity"],
        returns=returns,
        initial_capital=initial_capital,
        annualization_factor=annualization_factor,
        turnover=turnover,
        trade_count=len(trades),
        commission_cost=commission,
        slippage_cost=slippage,
    )
    return BacktestResult(
        metrics=metrics,
        trades=trades,
        equity_curve=equity_curve,
        positions=positions,
        returns=returns,
    )
