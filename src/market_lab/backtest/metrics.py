"""Chistye funkcii rascheta finansovyh metrik."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

CALMAR_EPSILON = 1e-12  # Zashchita objective ot deleniya na nol.


def calculate_max_drawdown(equity: pd.Series) -> float:
    """Vozvrashchaet maksimalnuyu prosadku kak neotricatelnuyu dolyu."""
    clean = equity.astype(float).dropna()
    if clean.empty:
        return 0.0
    running_peak = clean.cummax()
    drawdowns = clean / running_peak - 1.0
    return float(max(0.0, -drawdowns.min()))


def calculate_metrics(
    equity: pd.Series,
    returns: pd.Series,
    initial_capital: float,
    annualization_factor: int,
    turnover: float,
    trade_count: int,
    commission_cost: float,
    slippage_cost: float,
) -> dict[str, Any]:
    """Schitaet dohodnost, risk i izderzhki po krivoi kapitala."""
    clean_equity = equity.astype(float).dropna()
    clean_returns = returns.astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    final_equity = float(clean_equity.iloc[-1]) if not clean_equity.empty else initial_capital
    total_return = final_equity / initial_capital - 1.0
    periods = max(len(clean_returns), 1)
    if final_equity > 0:
        annualized_return = (final_equity / initial_capital) ** (
            annualization_factor / periods
        ) - 1.0
    else:
        annualized_return = -1.0
    standard_deviation = float(clean_returns.std(ddof=1)) if len(clean_returns) >= 2 else 0.0
    if standard_deviation > CALMAR_EPSILON:
        sharpe = (
            math.sqrt(annualization_factor) * float(clean_returns.mean()) / standard_deviation
        )
    else:
        sharpe = 0.0
    max_drawdown = calculate_max_drawdown(clean_equity)
    calmar = annualized_return / max(max_drawdown, CALMAR_EPSILON)
    return {
        "initial_capital": float(initial_capital),
        "final_equity": final_equity,
        "total_return": float(total_return),
        "annualized_return": float(annualized_return),
        "sharpe": float(sharpe),
        "calmar": float(calmar),
        "max_drawdown": float(max_drawdown),
        "turnover": float(turnover),
        "trade_count": int(trade_count),
        "commission_cost": float(commission_cost),
        "slippage_cost": float(slippage_cost),
        "total_cost": float(commission_cost + slippage_cost),
    }

