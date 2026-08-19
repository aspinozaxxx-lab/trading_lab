"""Exact five-sleeve open-to-open portfolio for market-graph-v1."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SLEEVES = 5
EPSILON = 1e-10


@dataclass(frozen=True, slots=True)
class PortfolioResult:
    """Metrics and auditable daily ledgers for one predeclared variant."""

    metrics: dict[str, float | int | bool]
    yearly_returns: dict[str, float]
    ledger: pd.DataFrame
    orders: pd.DataFrame


def construct_prediction_weights(
    factor_location: np.ndarray,
    factor_scale: np.ndarray,
    residual_location: np.ndarray,
    current_mask: np.ndarray,
    observable_target_mask: np.ndarray,
    *,
    factor_budget: float = 0.25,
    factor_minimum_snr: float = 1.25,
    residual_budget: float = 0.75,
    top_bottom: int = 5,
    maximum_stock_weight: float = 0.10,
) -> np.ndarray:
    """Build fixed factor plus exact-dollar-neutral top-five/bottom-five weights."""
    days, assets = residual_location.shape
    weights = np.zeros((days, assets), dtype=np.float64)
    for day in range(days):
        eligible = current_mask[day] & np.isfinite(residual_location[day])
        eligible_indices = np.flatnonzero(eligible)
        if len(eligible_indices) >= 2 * top_bottom:
            ranked = eligible_indices[
                np.argsort(residual_location[day, eligible_indices], kind="mergesort")
            ]
            short = ranked[:top_bottom]
            long = ranked[-top_bottom:]
            weights[day, long] += residual_budget / (2.0 * top_bottom)
            weights[day, short] -= residual_budget / (2.0 * top_bottom)
        scale = max(float(factor_scale[day]), 1e-12)
        snr = abs(float(factor_location[day])) / scale
        if eligible_indices.size and snr >= factor_minimum_snr:
            direction = np.sign(float(factor_location[day]))
            weights[day, eligible_indices] += direction * factor_budget / len(eligible_indices)
        weights[day, ~observable_target_mask[day]] = 0.0
        maximum = float(np.max(np.abs(weights[day])))
        if maximum > maximum_stock_weight:
            weights[day] *= maximum_stock_weight / maximum
        gross = float(np.abs(weights[day]).sum())
        if gross > 1.0:
            weights[day] /= gross
    return weights


def _portfolio_metrics(
    ledger: pd.DataFrame,
    *,
    initial_capital: float,
    total_turnover: float,
    total_trading_cost: float,
    total_borrow_cost: float,
    order_count: int,
    maximum_signal_weight: float,
    unresolved_positions: int,
) -> tuple[dict[str, float | int | bool], dict[str, float]]:
    equity = ledger.set_index("session_date")["equity"].astype(float)
    returns = ledger.set_index("session_date")["net_return"].astype(float)
    final = float(equity.iloc[-1])
    elapsed_days = max((equity.index[-1] - equity.index[0]).days, 1)
    cagr = (final / initial_capital) ** (365.25 / elapsed_days) - 1.0
    volatility = float(returns.std(ddof=1))
    sharpe = float(np.sqrt(252.0) * returns.mean() / volatility) if volatility > 1e-12 else 0.0
    drawdown = equity / equity.cummax() - 1.0
    yearly = {
        str(int(year)): float(np.prod(1.0 + part.to_numpy()) - 1.0)
        for year, part in returns.groupby(returns.index.year)
    }
    years = elapsed_days / 365.25
    mean_long = float(ledger["long_gross"].mean())
    mean_short = float(ledger["short_gross"].mean())
    metrics: dict[str, float | int | bool] = {
        "initial_capital": float(initial_capital),
        "final_equity": final,
        "total_return": final / initial_capital - 1.0,
        "net_cagr": float(cagr),
        "net_sharpe": sharpe,
        "maximum_drawdown": float(-drawdown.min()),
        "worst_year": float(min(yearly.values())) if yearly else 0.0,
        "turnover_total": float(total_turnover),
        "turnover_annualized": float(total_turnover / max(years, 1e-12)),
        "trading_cost_rub": float(total_trading_cost),
        "short_borrow_cost_rub": float(total_borrow_cost),
        "total_cost_rub": float(total_trading_cost + total_borrow_cost),
        "order_count": int(order_count),
        "mean_long_gross": mean_long,
        "mean_short_gross": mean_short,
        "long_short_gross_ratio": mean_long / max(mean_short, 1e-12),
        "maximum_realized_gross": float(ledger["gross"].max()),
        "maximum_realized_stock_weight": float(ledger["maximum_stock_weight"].max()),
        "maximum_signal_stock_weight": float(maximum_signal_weight),
        "gross_limit_breach": bool((ledger["gross"] > 1.00000001).any()),
        "signal_weight_limit_breach": bool(maximum_signal_weight > 0.10000001),
        "unresolved_position_count": int(unresolved_positions),
        "annualization_note": "CAGR uses elapsed calendar days; Sharpe uses sqrt(252)",
    }
    return metrics, yearly


def run_five_sleeve_backtest(
    dates: np.ndarray,
    tickers: tuple[str, ...],
    raw_open: np.ndarray,
    weights: np.ndarray,
    *,
    start_index: int,
    initial_capital: float = 1_000_000.0,
    one_way_cost_bps: float = 7.0,
    short_borrow_rate_annual: float = 0.20,
    cost_multiplier: float = 1.0,
    maximum_stock_weight: float = 0.10,
) -> PortfolioResult:
    """Execute D-close signals at D+1 factual opens through five rotating sleeves."""
    if raw_open.shape != weights.shape or raw_open.shape != (len(dates), len(tickers)):
        raise ValueError("portfolio axes do not match")
    if not 0 <= start_index < len(dates) - 1:
        raise ValueError("invalid portfolio start index")
    assets = len(tickers)
    quantities = np.zeros((SLEEVES, assets), dtype=np.float64)
    pending_exit = np.zeros((SLEEVES, assets), dtype=bool)
    last_prices = np.full(assets, np.nan, dtype=np.float64)
    cash = float(initial_capital)
    previous_equity = float(initial_capital)
    cost_rate = float(one_way_cost_bps) * float(cost_multiplier) / 10_000.0
    total_turnover = 0.0
    total_trading_cost = 0.0
    total_borrow_cost = 0.0
    order_count = 0
    rows: list[dict[str, object]] = []
    order_rows: list[dict[str, object]] = []
    maximum_signal_weight = float(np.max(np.abs(weights)))

    for index in range(start_index + 1, len(dates)):
        session = pd.Timestamp(dates[index])
        previous_session = pd.Timestamp(dates[index - 1])
        current_open = raw_open[index].astype(np.float64)
        available = np.isfinite(current_open) & (current_open > 0.0)
        last_prices[available] = current_open[available]
        held = np.abs(quantities).sum(axis=0) > EPSILON
        if np.any(held & ~np.isfinite(last_prices)):
            raise ValueError("open position has no factual or prior mark")
        marks = np.where(np.isfinite(last_prices), last_prices, 0.0)
        marked_values = quantities * marks[None, :]
        elapsed_years = max((session - previous_session).days, 0) / 365.25
        short_notional = float(np.abs(np.minimum(marked_values, 0.0)).sum())
        borrow = short_notional * short_borrow_rate_annual * elapsed_years
        cash -= borrow
        total_borrow_cost += borrow
        equity_before_trade = cash + float(marked_values.sum())

        desired = quantities.copy()
        closable_pending = pending_exit & available[None, :]
        desired[closable_pending] = 0.0
        pending_exit[closable_pending] = False

        signal_index = index - 1
        sleeve = (signal_index - start_index) % SLEEVES
        target_weights = weights[signal_index] / SLEEVES
        for asset in range(assets):
            current = float(quantities[sleeve, asset])
            target = float(target_weights[asset])
            if available[asset]:
                if pending_exit[sleeve, asset]:
                    desired[sleeve, asset] = 0.0
                    pending_exit[sleeve, asset] = False
                else:
                    desired[sleeve, asset] = target * equity_before_trade / current_open[asset]
            elif (
                abs(current) > EPSILON
                and abs(target - current * marks[asset] / max(equity_before_trade, EPSILON))
                > EPSILON
            ):
                pending_exit[sleeve, asset] = True

        # Iterate against after-cost equity so gross and per-stock caps are literal,
        # not merely signal-time intentions that can breach after fees or price drift.
        for _ in range(8):
            aggregate_delta = (desired - quantities).sum(axis=0)
            aggregate_delta[~available] = 0.0
            absolute_notional = np.abs(aggregate_delta[available] * current_open[available])
            after_cost_equity = equity_before_trade - float(absolute_notional.sum() * cost_rate)
            if after_cost_equity <= 0.0:
                raise ValueError("costs exhausted market_graph portfolio equity")
            for asset in np.flatnonzero(available):
                aggregate_value = float(desired[:, asset].sum() * current_open[asset])
                cap = maximum_stock_weight * after_cost_equity
                if abs(aggregate_value) > cap + 1e-8:
                    desired[:, asset] *= cap / abs(aggregate_value)
            desired_values = desired * marks[None, :]
            locked_gross = float(np.abs(desired_values[:, ~available]).sum())
            adjustable_gross = float(np.abs(desired_values[:, available]).sum())
            allowed = max(after_cost_equity - locked_gross, 0.0)
            if adjustable_gross > allowed + 1e-8 and adjustable_gross > 0.0:
                desired[:, available] *= allowed / adjustable_gross

        sleeve_delta = desired - quantities
        aggregate_delta = sleeve_delta.sum(axis=0)
        aggregate_delta[~available] = 0.0
        absolute_notional = np.abs(aggregate_delta[available] * current_open[available])
        trading_cost = float(absolute_notional.sum() * cost_rate)
        turnover = float(absolute_notional.sum() / max(equity_before_trade, EPSILON))
        cash -= float((aggregate_delta[available] * current_open[available]).sum()) + trading_cost
        for asset in np.flatnonzero(np.abs(aggregate_delta) > EPSILON):
            notional = float(aggregate_delta[asset] * current_open[asset])
            order_rows.append(
                {
                    "session_date": session,
                    "ticker": tickers[asset],
                    "signed_notional": notional,
                    "absolute_notional": abs(notional),
                    "cost": abs(notional) * cost_rate,
                }
            )
        quantities = desired
        ending_values = quantities * marks[None, :]
        equity = cash + float(ending_values.sum())
        if equity <= 0.0:
            raise ValueError("market_graph portfolio equity became non-positive")
        aggregate_values = ending_values.sum(axis=0)
        gross = float(np.abs(aggregate_values).sum() / equity)
        long_gross = float(np.maximum(aggregate_values, 0.0).sum() / equity)
        short_gross = float(np.abs(np.minimum(aggregate_values, 0.0)).sum() / equity)
        maximum_stock = float(np.max(np.abs(aggregate_values)) / equity)
        rows.append(
            {
                "session_date": session,
                "signal_session": previous_session,
                "equity": equity,
                "net_return": equity / previous_equity - 1.0,
                "gross": gross,
                "long_gross": long_gross,
                "short_gross": short_gross,
                "maximum_stock_weight": maximum_stock,
                "turnover": turnover,
                "trading_cost": trading_cost,
                "borrow_cost": borrow,
                "pending_exits": int(pending_exit.sum()),
            }
        )
        previous_equity = equity
        total_turnover += turnover
        total_trading_cost += trading_cost
        order_count += int(np.count_nonzero(np.abs(aggregate_delta) > EPSILON))

    ledger = pd.DataFrame(rows)
    orders = pd.DataFrame(order_rows)
    unresolved = int((np.abs(quantities) > EPSILON).sum())
    metrics, yearly = _portfolio_metrics(
        ledger,
        initial_capital=initial_capital,
        total_turnover=total_turnover,
        total_trading_cost=total_trading_cost,
        total_borrow_cost=total_borrow_cost,
        order_count=order_count,
        maximum_signal_weight=maximum_signal_weight,
        unresolved_positions=unresolved,
    )
    return PortfolioResult(metrics=metrics, yearly_returns=yearly, ledger=ledger, orders=orders)
