"""Proverki izderzhek, ispolneniya i sintenticheskogo rezultata."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab.backtest.engine import (
    adverse_fill_price,
    calculate_commission,
    run_backtest,
)
from market_lab.config import PortfolioConfig
from market_lab.strategies import buy_and_hold_targets

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Koren s testovym ryadom.


def _load_synthetic_frame() -> pd.DataFrame:
    """Chitaet prostoi trend s izvestnoi dohodnostyu."""
    frame = pd.read_csv(PROJECT_ROOT / "tests" / "fixtures" / "synthetic_trend.csv")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame.set_index("timestamp")


def _zero_cost_portfolio() -> PortfolioConfig:
    """Vozvrashchaet portfel bez komissii i proskalzyvaniya."""
    return PortfolioConfig(
        initial_capital=1000.0,
        commission_bps=0.0,
        slippage_bps=0.0,
        allow_short=True,
    )


def test_commission_is_based_on_absolute_notional() -> None:
    """Proveryaet komissiyu v pyat bazisnyh punktov."""
    assert calculate_commission(10_000.0, 5.0) == pytest.approx(5.0)


def test_slippage_is_adverse_for_buy_and_sell() -> None:
    """Proveryaet protivopolozhnyi sdvig ceny dlya dvuh storon."""
    assert adverse_fill_price(100.0, 1.0, 10.0) == pytest.approx(100.1)
    assert adverse_fill_price(100.0, -1.0, 10.0) == pytest.approx(99.9)


def test_signal_is_executed_only_on_next_bar() -> None:
    """Proveryaet odin bar zaderzhki mezhdu signalom i poziciei."""
    frame = _load_synthetic_frame()
    targets = pd.Series([0.0, 1.0, 0.0, 0.0], index=frame.index)
    result = run_backtest(frame, targets, _zero_cost_portfolio(), 252)
    assert result.positions.iloc[1]["executed_target"] == 0.0
    assert result.positions.iloc[2]["executed_target"] == 1.0
    assert result.trades.iloc[0]["timestamp"] == frame.index[2]


def test_buy_and_hold_has_known_synthetic_result() -> None:
    """Proveryaet kapital 1210 posle vhoda po 100 i rosta do 121."""
    frame = _load_synthetic_frame()
    result = run_backtest(
        frame,
        buy_and_hold_targets(frame.index),
        _zero_cost_portfolio(),
        252,
    )
    assert result.metrics["final_equity"] == pytest.approx(1210.0)
    assert result.metrics["total_return"] == pytest.approx(0.21)
    assert result.metrics["trade_count"] == 1


def test_constant_target_does_not_rebalance_after_costs() -> None:
    """Proveryaet otsutstvie lishnego oborota pri neizmennom signale."""
    frame = _load_synthetic_frame()
    portfolio = PortfolioConfig(
        initial_capital=1000.0,
        commission_bps=5.0,
        slippage_bps=2.0,
        allow_short=False,
    )
    result = run_backtest(frame, buy_and_hold_targets(frame.index), portfolio, 252)
    assert result.metrics["trade_count"] == 1
    assert result.metrics["turnover"] == pytest.approx(1.0)


def test_reversal_counts_full_turnover_and_commission() -> None:
    """Proveryaet chto perevorot pozicii sozdaet oborot okolo dvuh."""
    frame = _load_synthetic_frame().iloc[:3]
    targets = pd.Series([1.0, -1.0, 0.0], index=frame.index)
    portfolio = PortfolioConfig(
        initial_capital=1000.0,
        commission_bps=5.0,
        slippage_bps=0.0,
        allow_short=True,
    )
    result = run_backtest(frame, targets, portfolio, 252)
    assert result.metrics["trade_count"] == 2
    assert result.metrics["turnover"] > 2.9
    assert result.metrics["commission_cost"] > 1.4
