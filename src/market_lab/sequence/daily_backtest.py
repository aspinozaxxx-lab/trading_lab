"""Prichinnyi event-driven backtest pyati staggered daily-sleeves."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from market_lab.backtest.metrics import calculate_metrics

SLEEVE_COUNT = 5  # Chislo nezavisimyh pyatidnevnyh subportfelei.
TRADING_DAYS_PER_YEAR = 252  # Baza annualizacii dnevnyh dohodnostei.
CALENDAR_DAYS_PER_YEAR = 365.25  # Baza fakticheskih borrow i financing izderzhek.
ORDER_EPSILON = 1e-10  # Porog nenulevogo kolichestva ili vesa.
CAP_TOLERANCE = 1e-8  # Dopusk proverki gross-leverage posle order-event.
FIXED_POINT_STEPS = 12  # Chislo iteracii target-equity s uchetom izderzhek.


@dataclass(frozen=True)
class DailyStrategySpec:
    """Zadaet causal-pravilo top/bottom selection i actual-fill hysteresis."""

    position_mode: Literal["long_only", "long_short"] = "long_only"
    top_k: int = 1
    minimum_score: float = 0.0
    keep_rank: int = 1
    score_column: str = "prediction"

    def __post_init__(self) -> None:
        """Proveryaet granicy selection bez obrashcheniya k rynochnym cenam."""
        if self.position_mode not in {"long_only", "long_short"}:
            raise ValueError(f"Neizvestnyi position_mode: {self.position_mode}")
        if self.top_k < 1 or self.keep_rank < 1:
            raise ValueError("top_k i keep_rank dolzhny byt polozhitel'nymi")
        if not np.isfinite(self.minimum_score) or self.minimum_score < 0:
            raise ValueError("minimum_score ne mozhet byt otricatelnym")
        if not self.score_column:
            raise ValueError("score_column ne mozhet byt pustym")


@dataclass(frozen=True)
class DailyBacktestConfig:
    """Zadaet kapital, izderzhki i zhestkii gross-limit portfelya."""

    initial_capital: float = 1_000_000.0
    commission_bps: float = 5.0
    slippage_bps: float = 2.0
    financing_rate_annual: float = 0.0
    short_borrow_rate_annual: float = 0.0
    target_gross_leverage: float = 1.0
    maximum_gross_leverage: float = 1.0

    def __post_init__(self) -> None:
        """Zapreshchaet nevalidnye izderzhki, kapital i leverage."""
        if not np.isfinite(self.initial_capital) or self.initial_capital <= 0:
            raise ValueError("initial_capital dolzhen byt polozhitel'nym")
        rates = (
            self.commission_bps,
            self.slippage_bps,
            self.financing_rate_annual,
            self.short_borrow_rate_annual,
        )
        if any(not np.isfinite(rate) or rate < 0 for rate in rates):
            raise ValueError("Izderzhki i stavki ne mogut byt otricatelnymi")
        leverages = (self.target_gross_leverage, self.maximum_gross_leverage)
        if any(not np.isfinite(value) or value <= 0 for value in leverages):
            raise ValueError("Gross-leverage dolzhen byt polozhitel'nym")
        if self.target_gross_leverage > self.maximum_gross_leverage:
            raise ValueError("target_gross_leverage prevyshaet maximum_gross_leverage")


@dataclass(frozen=True)
class DailyBacktestResult:
    """Hranit metriki, daily-ledger, actual weights i agregirovannye ordera."""

    metrics: dict[str, float | int | bool]
    ledger: pd.DataFrame
    weights: pd.DataFrame
    orders: pd.DataFrame
    execution_complete: bool


def _normalize_session_dates(values: pd.Series) -> pd.Series:
    """Privodit session-date k timezone-naive polunochi bez smeny daty."""
    timestamps = pd.to_datetime(values, errors="raise")
    if timestamps.dt.tz is not None:
        timestamps = timestamps.dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
    return timestamps.dt.normalize()


def _normalize_predictions(predictions: pd.DataFrame, spec: DailyStrategySpec) -> pd.DataFrame:
    """Proveryaet tol'ko signal'nye kolonki i ne chitaet future open ili target."""
    required = {"session_date", "ticker", spec.score_column}
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"Net kolonok daily-predictions: {sorted(missing)}")
    result = predictions.loc[:, ["session_date", "ticker", spec.score_column]].copy()
    result["session_date"] = _normalize_session_dates(result["session_date"])
    result["ticker"] = result["ticker"].astype(str).str.upper()
    result[spec.score_column] = pd.to_numeric(result[spec.score_column], errors="coerce")
    result.loc[~np.isfinite(result[spec.score_column]), spec.score_column] = np.nan
    if result["session_date"].isna().any() or result["ticker"].eq("").any():
        raise ValueError("Daily predictions soderzhat pustuyu datu ili ticker")
    if result.duplicated(["session_date", "ticker"]).any():
        raise ValueError("Daily predictions soderzhat dublikat session_date/ticker")
    return result.sort_values(["session_date", "ticker"], kind="mergesort").reset_index(
        drop=True
    )


def _normalize_daily_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet factual open i denezhnyi oborot kazhdoi session/ticker."""
    required = {"session_date", "ticker", "raw_open", "raw_value"}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"Net kolonok daily execution-panel: {sorted(missing)}")
    result = panel.loc[:, ["session_date", "ticker", "raw_open", "raw_value"]].copy()
    result["session_date"] = _normalize_session_dates(result["session_date"])
    result["ticker"] = result["ticker"].astype(str).str.upper()
    result["raw_open"] = pd.to_numeric(result["raw_open"], errors="coerce")
    result["raw_value"] = pd.to_numeric(result["raw_value"], errors="coerce")
    if result["session_date"].isna().any() or result["ticker"].eq("").any():
        raise ValueError("Daily execution-panel soderzhit pustuyu datu ili ticker")
    if result.duplicated(["session_date", "ticker"]).any():
        raise ValueError("Daily execution-panel soderzhit dublikat session_date/ticker")
    if (~np.isfinite(result["raw_open"].dropna())).any() or (
        result["raw_open"].dropna() <= 0
    ).any():
        raise ValueError("Dostupnyi daily raw_open dolzhen byt polozhitel'nym")
    if (~np.isfinite(result["raw_value"].dropna())).any() or (
        result["raw_value"].dropna() < 0
    ).any():
        raise ValueError("Daily raw_value ne mozhet byt otricatelnym")
    return result.sort_values(["session_date", "ticker"], kind="mergesort").reset_index(
        drop=True
    )


def _actual_quantity_series(
    actual_quantities: pd.Series | Mapping[str, float] | None,
) -> pd.Series:
    """Normalizuet izvestnye k signal-time fakticheskie pozicii sleeve."""
    if actual_quantities is None:
        return pd.Series(dtype=float)
    values = pd.Series(actual_quantities, dtype=float)
    values.index = values.index.astype(str).str.upper()
    return values.groupby(level=0).sum()


def select_daily_weights(
    signal_predictions: pd.DataFrame,
    spec: DailyStrategySpec,
    actual_quantities: pd.Series | Mapping[str, float] | None = None,
) -> pd.Series:
    """Vyberaet target weights tol'ko iz score i uzhe ispolnennyh pozicii."""
    required = {"ticker", spec.score_column}
    missing = required - set(signal_predictions.columns)
    if missing:
        raise ValueError(f"Net kolonok dlya daily selection: {sorted(missing)}")
    signals = signal_predictions.loc[:, ["ticker", spec.score_column]].copy()
    signals["ticker"] = signals["ticker"].astype(str).str.upper()
    if signals["ticker"].duplicated().any():
        raise ValueError("Signal-group soderzhit povtornyi ticker")
    scores = pd.to_numeric(signals[spec.score_column], errors="coerce")
    scores.index = signals["ticker"]
    scores = scores.dropna()
    tickers = sorted(signals["ticker"].unique().tolist())
    weights = pd.Series(0.0, index=tickers, dtype=float)
    if scores.empty:
        return weights
    actual = _actual_quantity_series(actual_quantities).reindex(tickers).fillna(0.0)
    descending = scores.sort_values(ascending=False, kind="mergesort")
    ascending = scores.sort_values(ascending=True, kind="mergesort")

    def choose_side(
        ranked: pd.Series,
        held_mask: pd.Series,
        eligible_mask: pd.Series,
        lowest_first: bool,
    ) -> list[str]:
        """Sohranyaet actual fills v keep-rank i dopolnyaet ih luchshimi score."""
        eligible = ranked.loc[eligible_mask.reindex(ranked.index).fillna(False)]
        ranks = eligible.rank(ascending=lowest_first, method="first")
        retained = [
            ticker
            for ticker in eligible.index
            if bool(held_mask.get(ticker, False)) and float(ranks.loc[ticker]) <= spec.keep_rank
        ]
        chosen = retained[: spec.top_k]
        for ticker in eligible.index:
            if len(chosen) >= spec.top_k:
                break
            if ticker not in chosen:
                chosen.append(ticker)
        return chosen

    if spec.position_mode == "long_only":
        positive = (scores > 0.0) & (scores >= spec.minimum_score)
        longs = choose_side(descending, actual.gt(ORDER_EPSILON), positive, False)
        if longs:
            weights.loc[longs] = 1.0 / spec.top_k
        return weights
    enough_assets = len(scores) >= 2 * spec.top_k
    spread = (
        float(
            descending.iloc[: spec.top_k].mean()
            - descending.iloc[-spec.top_k :].mean()
        )
        if enough_assets
        else float("-inf")
    )
    if spread < spec.minimum_score:
        return weights
    eligible = pd.Series(True, index=scores.index)
    longs = choose_side(descending, actual.gt(ORDER_EPSILON), eligible, False)
    short_eligible = eligible & ~eligible.index.isin(longs)
    shorts = choose_side(ascending, actual.lt(-ORDER_EPSILON), short_eligible, True)
    if longs:
        weights.loc[longs] = 0.5 / spec.top_k
    if shorts:
        weights.loc[shorts] = -0.5 / spec.top_k
    return weights


def _marked_values(quantities: pd.DataFrame, prices: pd.Series) -> pd.DataFrame:
    """Pereocenivaet sleeve quantities po poslednemu fakticheskomu open."""
    held = quantities.abs().sum(axis=0).gt(ORDER_EPSILON)
    if prices.loc[held].isna().any():
        missing = prices.loc[held & prices.isna()].index.tolist()
        raise ValueError(f"Net poslednei ceny dlya otkrytoi pozicii: {missing}")
    return quantities.mul(prices.fillna(0.0), axis=1)


def _scale_to_gross_cap(
    desired: pd.DataFrame,
    prices: pd.Series,
    available: pd.Series,
    equity: float,
    maximum_gross_leverage: float,
) -> tuple[pd.DataFrame, bool]:
    """Masshtabiruet ispolnimye pozicii i ne sintetiziruet ceny locked-holdings."""
    values = _marked_values(desired, prices)
    cap = max(equity, 0.0) * maximum_gross_leverage
    locked_gross = float(values.loc[:, ~available].abs().to_numpy().sum())
    adjustable_gross = float(values.loc[:, available].abs().to_numpy().sum())
    if locked_gross + adjustable_gross <= cap + CAP_TOLERANCE:
        return desired, False
    allowed = max(cap - locked_gross, 0.0)
    scale = min(1.0, allowed / max(adjustable_gross, ORDER_EPSILON))
    scaled = desired.copy()
    scaled.loc[:, available] *= scale
    return scaled, locked_gross > cap + CAP_TOLERANCE


def _empty_orders() -> pd.DataFrame:
    """Sozdaet stabil'nuyu skhemu pustogo order-ledger."""
    return pd.DataFrame(
        columns=[
            "session_date",
            "ticker",
            "side",
            "quantity",
            "price",
            "signed_notional",
            "absolute_notional",
            "commission_cost",
            "slippage_cost",
            "participation",
            "contributing_sleeves",
        ]
    )


def _build_desired_quantities(
    quantities: pd.DataFrame,
    pending_exits: Mapping[tuple[int, str], int],
    target_weights: pd.Series,
    current_open: pd.Series,
    last_prices: pd.Series,
    available: pd.Series,
    sleeve_id: int,
    equity_basis: float,
    maximum_gross_leverage: float,
) -> tuple[pd.DataFrame, bool]:
    """Stroit odnu fixed-point iteraciyu sleeve-targetov i gross-capa."""
    desired = quantities.copy()
    for pending_sleeve, pending_ticker in pending_exits:
        if bool(available.loc[pending_ticker]):
            desired.loc[pending_sleeve, pending_ticker] = 0.0
    for ticker in quantities.columns:
        if bool(available.loc[ticker]):
            desired.loc[sleeve_id, ticker] = (
                target_weights.loc[ticker] * equity_basis / current_open.loc[ticker]
            )
    return _scale_to_gross_cap(
        desired,
        last_prices,
        available,
        equity_basis,
        maximum_gross_leverage,
    )


def run_staggered_daily_backtest(
    predictions: pd.DataFrame,
    daily_panel: pd.DataFrame,
    spec: DailyStrategySpec,
    config: DailyBacktestConfig,
) -> DailyBacktestResult:
    """Ispolnyaet close-D score na sleduyushchem open cherez pyat sleeves."""
    signals = _normalize_predictions(predictions, spec)
    market = _normalize_daily_panel(daily_panel)
    market_tickers = set(market["ticker"])
    unknown = set(signals["ticker"]) - market_tickers
    if unknown:
        raise ValueError(f"Predictions soderzhat tickery bez daily-panel: {sorted(unknown)}")
    calendar = pd.DatetimeIndex(sorted(market["session_date"].unique()), name="session_date")
    if len(calendar) < 2:
        raise ValueError("Daily backtest trebuet minimum dve session")
    tickers = sorted(market_tickers)
    opens = market.pivot(index="session_date", columns="ticker", values="raw_open").reindex(
        index=calendar, columns=tickers
    )
    values = market.pivot(index="session_date", columns="ticker", values="raw_value").reindex(
        index=calendar, columns=tickers
    )
    lagged_values = values.shift(1)
    signal_groups = {
        pd.Timestamp(key): part.loc[:, ["ticker", spec.score_column]]
        for key, part in signals.groupby("session_date", sort=False)
    }
    quantities = pd.DataFrame(0.0, index=range(SLEEVE_COUNT), columns=tickers)
    pending_exits: dict[tuple[int, str], int] = {}
    last_prices = opens.loc[calendar[0]].where(opens.loc[calendar[0]].notna())
    cash = float(config.initial_capital)
    previous_equity = cash
    ledger_rows: list[dict[str, object]] = []
    weight_rows: list[dict[str, object]] = []
    order_parts: list[pd.DataFrame] = []
    commission_total = 0.0
    slippage_total = 0.0
    financing_total = 0.0
    borrow_total = 0.0
    turnover_total = 0.0
    trade_count = 0
    missing_entry_count = 0
    missing_rebalance_count = 0
    missing_exit_count = 0
    holding_extension_sessions = 0
    maximum_holding_extension = 0
    gross_cap_breach_count = 0
    invalid_participation_count = 0
    had_missing_entry = False
    had_missing_rebalance = False
    had_missing_exit = False
    commission_rate = config.commission_bps / 10_000.0
    slippage_rate = config.slippage_bps / 10_000.0
    cost_rate = commission_rate + slippage_rate

    for session_offset in range(1, len(calendar)):
        session = pd.Timestamp(calendar[session_offset])
        signal_session = pd.Timestamp(calendar[session_offset - 1])
        sleeve_id = (session_offset - 1) % SLEEVE_COUNT
        current_open = opens.loc[session]
        available = current_open.notna()
        last_prices = last_prices.where(~available, current_open)
        current_values = _marked_values(quantities, last_prices)
        equity_marked = cash + float(current_values.to_numpy().sum())
        elapsed_years = (session - calendar[session_offset - 1]).days / CALENDAR_DAYS_PER_YEAR
        short_market_value = float(
            current_values.where(quantities.lt(-ORDER_EPSILON), 0.0).abs().to_numpy().sum()
        )
        financing = max(-cash, 0.0) * config.financing_rate_annual * elapsed_years
        short_borrow = short_market_value * config.short_borrow_rate_annual * elapsed_years
        cash -= financing + short_borrow
        equity_before_trade = cash + float(current_values.to_numpy().sum())
        actual_for_hysteresis = quantities.loc[sleeve_id].copy()
        for pending_sleeve, pending_ticker in pending_exits:
            if pending_sleeve == sleeve_id:
                actual_for_hysteresis.loc[pending_ticker] = 0.0
        signal_group = signal_groups.get(
            signal_session,
            pd.DataFrame(columns=["ticker", spec.score_column]),
        )
        base_intent = select_daily_weights(signal_group, spec, actual_for_hysteresis).reindex(
            tickers
        ).fillna(0.0)
        target_weights = base_intent * (config.target_gross_leverage / SLEEVE_COUNT)

        for ticker in tickers:
            key = (sleeve_id, ticker)
            current_quantity = float(quantities.loc[sleeve_id, ticker])
            target_weight = float(target_weights.loc[ticker])
            same_direction = current_quantity * target_weight > 0.0
            if key in pending_exits and same_direction:
                del pending_exits[key]
            if bool(available.loc[ticker]):
                if key in pending_exits:
                    del pending_exits[key]
                continue
            if abs(current_quantity) <= ORDER_EPSILON and abs(target_weight) > ORDER_EPSILON:
                missing_entry_count += 1
                had_missing_entry = True
            elif abs(current_quantity) > ORDER_EPSILON and same_direction:
                missing_rebalance_count += 1
                had_missing_rebalance = True
            elif (
                abs(current_quantity) > ORDER_EPSILON
                and not same_direction
                and key not in pending_exits
            ):
                pending_exits[key] = 0
                missing_exit_count += 1
                had_missing_exit = True

        for key in list(pending_exits):
            sleeve, ticker = key
            if not bool(available.loc[ticker]):
                pending_exits[key] += 1
                holding_extension_sessions += 1
                maximum_holding_extension = max(maximum_holding_extension, pending_exits[key])

        after_cost_equity = equity_before_trade
        cap_locked = False
        desired = quantities.copy()
        for _ in range(FIXED_POINT_STEPS):
            desired, cap_locked = _build_desired_quantities(
                quantities,
                pending_exits,
                target_weights,
                current_open,
                last_prices,
                available,
                sleeve_id,
                after_cost_equity,
                config.maximum_gross_leverage,
            )
            aggregate_delta = desired.sum(axis=0) - quantities.sum(axis=0)
            absolute_notional = float(
                (aggregate_delta.loc[available].abs() * current_open.loc[available]).sum()
            )
            after_cost_equity = equity_before_trade - absolute_notional * cost_rate
        sleeve_deltas = desired - quantities
        aggregate_delta = sleeve_deltas.sum(axis=0)
        order_rows: list[dict[str, object]] = []
        session_commission = 0.0
        session_slippage = 0.0
        session_absolute_notional = 0.0
        session_turnover = 0.0
        for ticker in tickers:
            quantity_delta = float(aggregate_delta.loc[ticker])
            if abs(quantity_delta) <= ORDER_EPSILON:
                continue
            if not bool(available.loc[ticker]):
                raise RuntimeError("Vnutrennyaya oshibka: order bez factual open")
            price = float(current_open.loc[ticker])
            signed_notional = quantity_delta * price
            absolute = abs(signed_notional)
            commission = absolute * commission_rate
            slippage = absolute * slippage_rate
            raw_value = float(lagged_values.loc[session, ticker])
            participation = (
                absolute / raw_value
                if np.isfinite(raw_value) and raw_value > 0
                else np.inf
            )
            if not np.isfinite(participation):
                invalid_participation_count += 1
            contributors = [
                str(sleeve)
                for sleeve in range(SLEEVE_COUNT)
                if abs(float(sleeve_deltas.loc[sleeve, ticker])) > ORDER_EPSILON
            ]
            order_rows.append(
                {
                    "session_date": session,
                    "ticker": ticker,
                    "side": "BUY" if quantity_delta > 0 else "SELL",
                    "quantity": quantity_delta,
                    "price": price,
                    "signed_notional": signed_notional,
                    "absolute_notional": absolute,
                    "commission_cost": commission,
                    "slippage_cost": slippage,
                    "participation": participation,
                    "contributing_sleeves": ",".join(contributors),
                }
            )
            session_commission += commission
            session_slippage += slippage
            session_absolute_notional += absolute
            session_turnover += absolute / max(equity_before_trade, ORDER_EPSILON)
        if order_rows:
            order_parts.append(pd.DataFrame(order_rows))
        cash -= float(
            (aggregate_delta.loc[available] * current_open.loc[available]).sum()
        ) + session_commission + session_slippage
        quantities = desired
        for key in list(pending_exits):
            pending_sleeve, pending_ticker = key
            if bool(available.loc[pending_ticker]) and abs(
                float(quantities.loc[pending_sleeve, pending_ticker])
            ) <= ORDER_EPSILON:
                del pending_exits[key]
        ending_values = _marked_values(quantities, last_prices)
        ending_equity = cash + float(ending_values.to_numpy().sum())
        gross_market_value = float(ending_values.abs().to_numpy().sum())
        net_market_value = float(ending_values.to_numpy().sum())
        gross_leverage = gross_market_value / max(ending_equity, ORDER_EPSILON)
        if cap_locked or gross_leverage > config.maximum_gross_leverage + CAP_TOLERANCE:
            gross_cap_breach_count += 1
        if ending_equity <= 0:
            raise ValueError("Daily portfolio stal nepolozhitel'nym")
        session_trades = len(order_rows)
        ledger_rows.append(
            {
                "session_date": session,
                "signal_session": signal_session,
                "rebalanced_sleeve": sleeve_id,
                "starting_equity": previous_equity,
                "marked_equity_before_costs": equity_marked,
                "market_pnl": equity_marked - previous_equity,
                "financing_cost": financing,
                "short_borrow_cost": short_borrow,
                "commission_cost": session_commission,
                "slippage_cost": session_slippage,
                "order_notional": session_absolute_notional,
                "turnover": session_turnover,
                "trade_count": session_trades,
                "cash": cash,
                "gross_market_value": gross_market_value,
                "net_market_value": net_market_value,
                "gross_leverage": gross_leverage,
                "equity": ending_equity,
                "net_return": ending_equity / previous_equity - 1.0,
                "pending_exit_count": len(pending_exits),
            }
        )
        for sleeve in range(SLEEVE_COUNT):
            for ticker in tickers:
                quantity = float(quantities.loc[sleeve, ticker])
                market_value = float(ending_values.loc[sleeve, ticker])
                if abs(quantity) <= ORDER_EPSILON and (sleeve, ticker) not in pending_exits:
                    continue
                weight_rows.append(
                    {
                        "session_date": session,
                        "sleeve_id": sleeve,
                        "ticker": ticker,
                        "quantity": quantity,
                        "market_value": market_value,
                        "weight": market_value / ending_equity,
                        "pending_exit": (sleeve, ticker) in pending_exits,
                    }
                )
        commission_total += session_commission
        slippage_total += session_slippage
        financing_total += financing
        borrow_total += short_borrow
        turnover_total += session_turnover
        trade_count += session_trades
        previous_equity = ending_equity

    ledger = pd.DataFrame(ledger_rows)
    orders = pd.concat(order_parts, ignore_index=True) if order_parts else _empty_orders()
    weights_frame = pd.DataFrame(
        weight_rows,
        columns=[
            "session_date",
            "sleeve_id",
            "ticker",
            "quantity",
            "market_value",
            "weight",
            "pending_exit",
        ],
    )
    initial_index = pd.Timestamp(calendar[0])
    equity = pd.concat(
        [
            pd.Series([config.initial_capital], index=[initial_index], dtype=float),
            ledger.set_index("session_date")["equity"],
        ]
    )
    returns = equity.pct_change().dropna()
    metrics = calculate_metrics(
        equity=equity,
        returns=returns,
        initial_capital=config.initial_capital,
        annualization_factor=TRADING_DAYS_PER_YEAR,
        turnover=turnover_total,
        trade_count=trade_count,
        commission_cost=commission_total,
        slippage_cost=slippage_total,
    )
    finite_participation = pd.to_numeric(orders["participation"], errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    measured_maximum_participation = (
        float(finite_participation.max()) if not finite_participation.empty else 0.0
    )
    maximum_participation = (
        max(1.0, measured_maximum_participation)
        if invalid_participation_count
        else measured_maximum_participation
    )
    execution_complete = (
        not had_missing_entry
        and not had_missing_exit
        and not had_missing_rebalance
        and not pending_exits
        and gross_cap_breach_count == 0
        and invalid_participation_count == 0
    )
    metrics.update(
        {
            "financing_cost": float(financing_total),
            "short_borrow_cost": float(borrow_total),
            "total_cost": float(
                metrics["total_cost"] + financing_total + borrow_total
            ),
            "missing_entry_count": missing_entry_count,
            "missing_rebalance_count": missing_rebalance_count,
            "missing_exit_count": missing_exit_count,
            "unresolved_exit_count": len(pending_exits),
            "holding_extension_sessions": holding_extension_sessions,
            "maximum_holding_extension_sessions": maximum_holding_extension,
            "gross_cap_breach_count": gross_cap_breach_count,
            "invalid_participation_count": invalid_participation_count,
            "maximum_participation": maximum_participation,
            "mean_participation": (
                float(finite_participation.mean()) if not finite_participation.empty else 0.0
            ),
            "open_position_count": int((quantities.abs() > ORDER_EPSILON).to_numpy().sum()),
            "execution_complete": execution_complete,
        }
    )
    return DailyBacktestResult(
        metrics=metrics,
        ledger=ledger,
        weights=weights_frame,
        orders=orders,
        execution_complete=execution_complete,
    )


def run_daily_backtest(
    predictions: pd.DataFrame,
    daily_panel: pd.DataFrame,
    spec: DailyStrategySpec,
    config: DailyBacktestConfig,
) -> DailyBacktestResult:
    """Predostavlyaet korotkii publichnyi alias staggered daily-dvizhka."""
    return run_staggered_daily_backtest(predictions, daily_panel, spec, config)
