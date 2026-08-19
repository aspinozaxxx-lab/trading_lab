"""Event-driven backtest neperesekayushchihsya intraday-targetov."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import pandas as pd

from market_lab.backtest.metrics import calculate_metrics
from market_lab.sequence.config import SequencePortfolioConfig

WEIGHT_EPSILON = 1e-12  # Porog real'nogo order-notional.
CALENDAR_DAYS_PER_YEAR = 365.25  # Baza dlya fakticheskogo finansirovaniya.
TRADING_DAYS_PER_YEAR = 252  # Annualizaciya po dnevnym equity-tochkam.


@dataclass(frozen=True)
class IntradayStrategySpec:
    """Fiksiruet confidence-gate, gisterezis i portfolio-razmer."""

    name: str
    top_k: int
    minimum_score: float
    keep_rank: int
    regime_filter: bool
    leverage: float
    score_column: str = "prediction"
    position_mode: Literal["long_only", "long_short"] = "long_only"

    def as_dict(self) -> dict[str, object]:
        """Vozvrashchaet serializuemye parametry strategii."""
        return asdict(self)


@dataclass(frozen=True)
class IntradayBacktest:
    """Hranit metriki, event-ledger i matricu signal'nyh vesov."""

    metrics: dict[str, float | int]
    ledger: pd.DataFrame
    weights: pd.DataFrame


def _single_scheduled_time(group: pd.DataFrame, column: str) -> pd.Timestamp:
    """Trebuet odno obshchee vremya entry ili exit dlya decision-group."""
    values = pd.to_datetime(group[column], utc=True).dropna().unique()
    if len(values) != 1:
        raise ValueError(f"Decision-group dolzhen imet odin {column}, polucheno {len(values)}")
    return pd.Timestamp(values[0])


def build_intraday_weights(
    predictions: pd.DataFrame,
    spec: IntradayStrategySpec,
) -> pd.DataFrame:
    """Zamorazhivaet order-intent bez proverki budushchego target ili open."""
    required = {
        "entry_time",
        "exit_time",
        "ticker",
        "market_regime",
        "entry_available",
        spec.score_column,
    }
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"Net kolonok dlya vesov: {sorted(missing)}")
    tickers = sorted(predictions["ticker"].unique().tolist())
    entry_times = sorted(pd.to_datetime(predictions["entry_time"], utc=True).unique())
    weights = pd.DataFrame(0.0, index=entry_times, columns=tickers)
    previous = pd.Series(0.0, index=tickers)
    previous_exit: pd.Timestamp | None = None
    for entry_time, group in predictions.groupby("entry_time", sort=True):
        entry = pd.Timestamp(entry_time)
        exit_time = _single_scheduled_time(group, "exit_time")
        if previous_exit is not None and entry != previous_exit:
            previous[:] = 0.0
        scores = group.set_index("ticker")[spec.score_column].dropna().sort_values(
            ascending=False
        )
        updated = pd.Series(0.0, index=tickers)
        regime_ok = (
            spec.position_mode == "long_short"
            or not spec.regime_filter
            or float(group["market_regime"].median()) > 0.0
        )
        if spec.position_mode == "long_short":
            enough_assets = len(scores) >= 2 * spec.top_k
            spread = (
                float(scores.iloc[: spec.top_k].mean() - scores.iloc[-spec.top_k :].mean())
                if enough_assets
                else float("-inf")
            )
            if regime_ok and spread >= spec.minimum_score:
                long_ranks = scores.rank(ascending=False, method="first")
                short_ranks = scores.rank(ascending=True, method="first")
                held_longs = [
                    ticker
                    for ticker in previous.loc[previous > 0.0].index
                    if ticker in long_ranks.index
                    and long_ranks.loc[ticker] <= spec.keep_rank
                ]
                selected_longs = held_longs[: spec.top_k]
                for ticker in scores.index:
                    if len(selected_longs) >= spec.top_k:
                        break
                    if ticker not in selected_longs:
                        selected_longs.append(ticker)
                held_shorts = [
                    ticker
                    for ticker in previous.loc[previous < 0.0].index
                    if ticker in short_ranks.index
                    and short_ranks.loc[ticker] <= spec.keep_rank
                    and ticker not in selected_longs
                ]
                selected_shorts = held_shorts[: spec.top_k]
                for ticker in reversed(scores.index.tolist()):
                    if len(selected_shorts) >= spec.top_k:
                        break
                    if ticker not in selected_longs and ticker not in selected_shorts:
                        selected_shorts.append(ticker)
                if (
                    len(selected_longs) == spec.top_k
                    and len(selected_shorts) == spec.top_k
                ):
                    side_weight = spec.leverage / (2.0 * spec.top_k)
                    updated.loc[selected_longs] = side_weight
                    updated.loc[selected_shorts] = -side_weight
        elif regime_ok and not scores.empty and float(scores.iloc[0]) >= spec.minimum_score:
            ranks = scores.rank(ascending=False, method="first")
            held = [
                ticker
                for ticker in previous.loc[previous > 0.0].index
                if ticker in ranks.index
                and ranks.loc[ticker] <= spec.keep_rank
                and scores.loc[ticker] > 0.0
            ]
            selected = held[: spec.top_k]
            for ticker in scores.index:
                if len(selected) >= spec.top_k:
                    break
                if ticker not in selected:
                    selected.append(ticker)
            if selected:
                updated.loc[selected] = spec.leverage / len(selected)
        weights.loc[entry] = updated
        availability = (
            group.set_index("ticker")["entry_available"].reindex(tickers).eq(True)
        )
        previous = updated.where(availability, 0.0)
        previous_exit = exit_time
    weights.index.name = "entry_time"
    return weights


def _desired_notionals(
    equity: float,
    current: pd.Series,
    weights: pd.Series,
    cost_rate: float,
) -> tuple[pd.Series, float]:
    """Reshaet target-notional s uchetom ego sobstvennyh transaction costs."""
    after_cost_equity = equity
    desired = weights * after_cost_equity
    for _ in range(8):
        traded = float((desired - current).abs().sum())
        after_cost_equity = equity - traded * cost_rate
        desired = weights * after_cost_equity
    return desired, max(after_cost_equity, 0.0)


def _daily_metric_inputs(
    ledger: pd.DataFrame,
    initial_capital: float,
) -> tuple[pd.Series, pd.Series]:
    """Stroit dnevnoe equity s obyazatel'noi nachal'noi tochkoi."""
    local_dates = pd.to_datetime(ledger["exit_time"], utc=True).dt.tz_convert(
        "Europe/Moscow"
    ).dt.normalize()
    daily = ledger.assign(local_date=local_dates).groupby("local_date")["equity"].last()
    initial_index = daily.index.min() - pd.Timedelta(days=1)
    equity = pd.concat([pd.Series([initial_capital], index=[initial_index]), daily])
    returns = equity.pct_change().dropna()
    return equity, returns


def run_intraday_backtest(
    predictions: pd.DataFrame,
    weights: pd.DataFrame,
    portfolio: SequencePortfolioConfig,
    cost_multiplier: float = 1.0,
) -> IntradayBacktest:
    """Vypolnyaet order-intent cherez driftuyushchie notionals, cash i actual turnover."""
    if cost_multiplier < 0:
        raise ValueError("cost_multiplier ne mozhet byt otricatelnym")
    required = {
        "entry_time",
        "exit_time",
        "ticker",
        "entry_available",
        "target_return",
    }
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"Net kolonok dlya backtesta: {sorted(missing)}")
    if predictions.duplicated(["entry_time", "ticker"]).any():
        raise ValueError("Prediction-panel soderzhit dublikat entry_time/ticker")
    tickers = list(weights.columns)
    grouped = {pd.Timestamp(key): part for key, part in predictions.groupby("entry_time")}
    commission_rate = portfolio.commission_bps * cost_multiplier / 10_000.0
    slippage_rate = portfolio.slippage_bps * cost_multiplier / 10_000.0
    cost_rate = commission_rate + slippage_rate
    cash = float(portfolio.initial_capital)
    current = pd.Series(0.0, index=tickers)
    previous_exit: pd.Timestamp | None = None
    rows: list[dict[str, object]] = []
    commission_total = 0.0
    slippage_total = 0.0
    financing_total = 0.0
    short_borrow_total = 0.0
    turnover_total = 0.0
    trade_count = 0
    missing_exit_count = 0

    def charge_trade(traded_notional: float, equity: float) -> tuple[float, float, float]:
        """Vozvrashchaet commission, slippage i dolyu turnover dlya order-event."""
        commission = traded_notional * commission_rate
        slippage = traded_notional * slippage_rate
        turnover = traded_notional / max(equity, WEIGHT_EPSILON)
        return commission, slippage, turnover

    for entry_time in weights.index:
        entry = pd.Timestamp(entry_time)
        if entry not in grouped:
            raise ValueError(f"Net execution-group dlya {entry}")
        group = grouped[entry]
        exit_time = _single_scheduled_time(group, "exit_time")
        if previous_exit is not None and entry < previous_exit:
            raise ValueError("Torgovye intervaly perekryvayutsya")
        if previous_exit is not None and entry > previous_exit and current.abs().any():
            equity_before_exit = cash + float(current.sum())
            traded = float(current.abs().sum())
            commission, slippage, turnover = charge_trade(traded, equity_before_exit)
            close_count = int((current.abs() > WEIGHT_EPSILON).sum())
            cash += float(current.sum()) - commission - slippage
            current[:] = 0.0
            commission_total += commission
            slippage_total += slippage
            turnover_total += turnover
            trade_count += close_count
            if rows:
                rows[-1]["commission_cost"] += commission
                rows[-1]["slippage_cost"] += slippage
                rows[-1]["turnover"] += turnover
                rows[-1]["equity"] = cash
                rows[-1]["net_return"] = cash / rows[-1]["starting_equity"] - 1.0
        equity_before = cash + float(current.sum())
        desired_weights = weights.loc[entry].copy()
        availability = (
            group.set_index("ticker")["entry_available"].reindex(tickers).eq(True)
        )
        desired_weights.loc[~availability] = 0.0
        desired, after_cost_equity = _desired_notionals(
            equity_before,
            current,
            desired_weights,
            cost_rate,
        )
        delta = desired - current
        traded = float(delta.abs().sum())
        commission, slippage, turnover = charge_trade(traded, equity_before)
        cash -= float(delta.sum()) + commission + slippage
        trade_count += int((delta.abs() > WEIGHT_EPSILON).sum())
        commission_total += commission
        slippage_total += slippage
        turnover_total += turnover
        targets = group.set_index("ticker")["target_return"].reindex(tickers)
        selected_without_exit = (desired.abs() > WEIGHT_EPSILON) & targets.isna()
        missing_exit_count += int(selected_without_exit.sum())
        realized_targets = targets.copy()
        missing_long = realized_targets.isna() & (desired >= 0.0)
        missing_short = realized_targets.isna() & (desired < 0.0)
        realized_targets.loc[missing_long] = portfolio.missing_exit_return
        realized_targets.loc[missing_short] = -portfolio.missing_exit_return
        gross_pnl = float((desired * realized_targets).sum())
        duration_years = (exit_time - entry).total_seconds() / (
            CALENDAR_DAYS_PER_YEAR * 24.0 * 60.0 * 60.0
        )
        financing = max(-cash, 0.0) * portfolio.financing_rate_annual * duration_years
        short_notional = float(desired.clip(upper=0.0).abs().sum())
        short_borrow = (
            short_notional * portfolio.short_borrow_rate_annual * duration_years
        )
        cash -= financing + short_borrow
        financing_total += financing
        short_borrow_total += short_borrow
        current = desired * (1.0 + realized_targets)
        ending_equity = cash + float(current.sum())
        if ending_equity <= 0 or after_cost_equity <= 0:
            raise ValueError("Kapital stal nepolozhitel'nym: strategiya bankrot")
        rows.append(
            {
                "entry_time": entry,
                "exit_time": exit_time,
                "starting_equity": equity_before,
                "gross_pnl": gross_pnl,
                "net_return": ending_equity / equity_before - 1.0,
                "turnover": turnover,
                "gross_exposure": float(desired.abs().sum()) / after_cost_equity,
                "commission_cost": commission,
                "slippage_cost": slippage,
                "financing_cost": financing,
                "short_borrow_cost": short_borrow,
                "equity": ending_equity,
            }
        )
        previous_exit = exit_time
    if current.abs().any() and rows:
        equity_before_exit = cash + float(current.sum())
        traded = float(current.abs().sum())
        commission, slippage, turnover = charge_trade(traded, equity_before_exit)
        cash += float(current.sum()) - commission - slippage
        commission_total += commission
        slippage_total += slippage
        turnover_total += turnover
        trade_count += int((current.abs() > WEIGHT_EPSILON).sum())
        rows[-1]["commission_cost"] += commission
        rows[-1]["slippage_cost"] += slippage
        rows[-1]["turnover"] += turnover
        rows[-1]["equity"] = cash
        rows[-1]["net_return"] = cash / rows[-1]["starting_equity"] - 1.0
    ledger = pd.DataFrame(rows)
    if ledger.empty:
        raise ValueError("Backtest ne sozdal ni odnogo intervala")
    metric_equity, metric_returns = _daily_metric_inputs(ledger, portfolio.initial_capital)
    metrics = calculate_metrics(
        equity=metric_equity,
        returns=metric_returns,
        initial_capital=portfolio.initial_capital,
        annualization_factor=TRADING_DAYS_PER_YEAR,
        turnover=turnover_total,
        trade_count=trade_count,
        commission_cost=commission_total,
        slippage_cost=slippage_total,
    )
    metrics["financing_cost"] = float(financing_total)
    metrics["short_borrow_cost"] = float(short_borrow_total)
    metrics["total_cost"] = float(
        metrics["total_cost"] + financing_total + short_borrow_total
    )
    metrics["daily_observations"] = len(metric_returns)
    metrics["missing_exit_count"] = missing_exit_count
    metrics["execution_complete"] = missing_exit_count == 0
    metrics["active_interval_fraction"] = float(
        (ledger["gross_exposure"].abs() > WEIGHT_EPSILON).mean()
    )
    return IntradayBacktest(metrics=metrics, ledger=ledger, weights=weights)


def evaluate_strategy(
    predictions: pd.DataFrame,
    spec: IntradayStrategySpec,
    portfolio: SequencePortfolioConfig,
    cost_multiplier: float = 1.0,
) -> IntradayBacktest:
    """Zamorazhivaet vesa i zapuskaet standartnyi event-driven backtest."""
    weights = build_intraday_weights(predictions, spec)
    return run_intraday_backtest(predictions, weights, portfolio, cost_multiplier)


def validation_objective(result: IntradayBacktest) -> float:
    """Kombiniruet Sharpe, CAGR i shtraf za prosadku tol'ko na validation."""
    metrics = result.metrics
    return float(
        metrics["sharpe"]
        + 0.5 * metrics["annualized_return"]
        - 2.0 * metrics["max_drawdown"]
    )
