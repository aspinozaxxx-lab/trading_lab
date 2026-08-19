"""Portfel'nyi backtest signalov s ispolneniem na sleduyushchem open."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
import pandas as pd

from market_lab.alpha.config import AlphaPortfolioConfig
from market_lab.backtest.metrics import calculate_metrics

WEIGHT_EPSILON = 1e-12  # Porog izmeneniya vesa dlya podscheta sdelok.
ANNUAL_TRADING_DAYS = 252  # Godovaya annualizaciya dnevnogo decision-panel.


@dataclass(frozen=True)
class StrategySpec:
    """Opisyvaet odno fiksirovannoe pravilo formirovaniya vesov."""

    name: str
    kind: Literal["momentum", "model", "buy_hold"]
    score_column: str | None
    top_k: int
    gross_leverage: float
    regime_filter: bool

    def as_dict(self) -> dict[str, object]:
        """Vozvrashchaet stabil'no serializuemye parametry pravila."""
        return asdict(self)


@dataclass(frozen=True)
class PortfolioBacktest:
    """Hranit metriki, dnevnoi zhurnal i matricu celevyh vesov."""

    metrics: dict[str, float | int]
    ledger: pd.DataFrame
    weights: pd.DataFrame


def _pivot(panel: pd.DataFrame, column: str, tickers: list[str]) -> pd.DataFrame:
    """Preobrazuet dlinnuyu panel' v matricu date na ticker."""
    return panel.pivot(index="decision_date", columns="ticker", values=column).reindex(
        columns=tickers
    )


def build_target_weights(
    panel: pd.DataFrame,
    spec: StrategySpec,
    volatility_floor: float = 0.003,
) -> pd.DataFrame:
    """Stroit vesa iz signalov, dostupnyh na tekushchem close."""
    tickers = sorted(panel["ticker"].unique().tolist())
    target = _pivot(panel, "target_return", tickers)
    volatility = _pivot(panel, "vol_20d", tickers)
    weights = pd.DataFrame(0.0, index=target.index, columns=tickers)
    if spec.kind == "buy_hold":
        available = target.notna()
        divisor = available.sum(axis=1).replace(0, np.nan)
        return available.div(divisor, axis=0).fillna(0.0) * spec.gross_leverage
    if spec.score_column is None:
        raise ValueError("Ranzhiruemaya strategiya dolzhna imet score_column")
    scores = _pivot(panel, spec.score_column, tickers)
    market = panel.groupby("decision_date")["market_ret_20d"].first().reindex(target.index)
    for decision_date in target.index:
        if spec.regime_filter and not market.loc[decision_date] > 0.0:
            continue
        valid = (
            scores.loc[decision_date].notna()
            & volatility.loc[decision_date].notna()
            & target.loc[decision_date].notna()
        )
        available_scores = scores.loc[decision_date, valid]
        if len(available_scores) < spec.top_k:
            continue
        chosen = available_scores.nlargest(spec.top_k).index
        inverse_volatility = 1.0 / volatility.loc[decision_date, chosen].clip(
            lower=volatility_floor
        )
        weights.loc[decision_date, chosen] = (
            spec.gross_leverage * inverse_volatility / inverse_volatility.sum()
        )
    return weights


def run_portfolio_backtest(
    panel: pd.DataFrame,
    spec: StrategySpec,
    portfolio: AlphaPortfolioConfig,
    cost_multiplier: float = 1.0,
) -> PortfolioBacktest:
    """Stroit standartnye vesa i schitaet denezhnyi rezultat."""
    if cost_multiplier < 0:
        raise ValueError("cost_multiplier ne mozhet byt otricatelnym")
    filtered = panel.dropna(subset=["target_return", "vol_20d", "market_ret_20d"]).copy()
    tickers = sorted(filtered["ticker"].unique().tolist())
    returns = _pivot(filtered, "target_return", tickers)
    weights = build_target_weights(
        filtered,
        spec,
        volatility_floor=portfolio.volatility_floor,
    ).reindex_like(returns).fillna(0.0)
    return run_weights_backtest(filtered, weights, portfolio, cost_multiplier)


def run_weights_backtest(
    panel: pd.DataFrame,
    weights: pd.DataFrame,
    portfolio: AlphaPortfolioConfig,
    cost_multiplier: float = 1.0,
) -> PortfolioBacktest:
    """Schitaet equity dlya vneshnei matricy target-vesov bez look-ahead."""
    if cost_multiplier < 0:
        raise ValueError("cost_multiplier ne mozhet byt otricatelnym")
    filtered = panel.dropna(subset=["target_return"]).copy()
    tickers = sorted(filtered["ticker"].unique().tolist())
    returns = _pivot(filtered, "target_return", tickers)
    weights = weights.reindex(index=returns.index, columns=tickers).fillna(0.0)
    if (weights.abs().sum(axis=1) > portfolio.maximum_gross_leverage + WEIGHT_EPSILON).any():
        raise ValueError("Vesa prevyshayut maximum_gross_leverage")
    previous = weights.shift(1).fillna(0.0)
    changes = weights - previous
    turnover = changes.abs().sum(axis=1)
    gross_return = (weights * returns.fillna(0.0)).sum(axis=1)
    commission_rate = portfolio.commission_bps * cost_multiplier / 10_000.0
    slippage_rate = portfolio.slippage_bps * cost_multiplier / 10_000.0
    financing_rate = portfolio.financing_rate_annual / ANNUAL_TRADING_DAYS
    financing_fraction = (weights.abs().sum(axis=1) - 1.0).clip(lower=0.0) * financing_rate
    capital = float(portfolio.initial_capital)
    rows: list[dict[str, object]] = []
    commission_total = 0.0
    slippage_total = 0.0
    financing_total = 0.0
    for decision_date in returns.index:
        starting_capital = capital
        commission_cost = starting_capital * turnover.loc[decision_date] * commission_rate
        slippage_cost = starting_capital * turnover.loc[decision_date] * slippage_rate
        financing_cost = starting_capital * financing_fraction.loc[decision_date]
        gross_pnl = starting_capital * gross_return.loc[decision_date]
        capital = starting_capital + gross_pnl - commission_cost - slippage_cost - financing_cost
        if capital <= 0:
            raise ValueError("Kapital stal nepolozhitel'nym: strategiya bankrot")
        net_return = capital / starting_capital - 1.0
        rows.append(
            {
                "decision_date": decision_date,
                "gross_return": gross_return.loc[decision_date],
                "net_return": net_return,
                "turnover": turnover.loc[decision_date],
                "gross_exposure": weights.loc[decision_date].abs().sum(),
                "commission_cost": commission_cost,
                "slippage_cost": slippage_cost,
                "financing_cost": financing_cost,
                "equity": capital,
            }
        )
        commission_total += commission_cost
        slippage_total += slippage_cost
        financing_total += financing_cost
    ledger = pd.DataFrame(rows).set_index("decision_date")
    trade_count = int((changes.abs() > WEIGHT_EPSILON).sum().sum())
    metrics = calculate_metrics(
        equity=ledger["equity"],
        returns=ledger["net_return"],
        initial_capital=portfolio.initial_capital,
        annualization_factor=ANNUAL_TRADING_DAYS,
        turnover=float(turnover.sum()),
        trade_count=trade_count,
        commission_cost=commission_total,
        slippage_cost=slippage_total,
    )
    metrics["financing_cost"] = float(financing_total)
    metrics["total_cost"] = float(metrics["total_cost"] + financing_total)
    metrics["average_daily_turnover"] = float(turnover.mean())
    metrics["active_day_fraction"] = float((weights.abs().sum(axis=1) > 0).mean())
    return PortfolioBacktest(metrics=metrics, ledger=ledger, weights=weights)
