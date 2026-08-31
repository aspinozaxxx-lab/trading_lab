"""Pure causal signal, execution, accounting, and metric logic for V10."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import time
from typing import Any

import numpy as np
import pandas as pd

TEN_MINUTES = pd.Timedelta(minutes=10)
PROTECTED_FROM = pd.Timestamp("2026-01-01", tz="UTC")
MOSCOW_TIMEZONE = "Europe/Moscow"


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    """A fixed log-price residual and its gross allocation."""

    name: str
    assets: tuple[str, ...]
    coefficients: tuple[int, ...]
    gross_fraction_per_leg: float
    authoritative: bool

    def __post_init__(self) -> None:
        if len(self.assets) != len(self.coefficients) or not self.assets:
            raise ValueError("assets and coefficients must be non-empty and aligned")
        if set(self.coefficients) - {-1, 1}:
            raise ValueError("V10 residual coefficients must be exactly -1 or +1")
        if not 0.0 < self.gross_fraction_per_leg <= 1.0:
            raise ValueError("gross fraction per leg must be in (0, 1]")


PRIMARY_STRATEGY = StrategyDefinition(
    name="triangular_ri_mix_si",
    assets=("RI", "MIX", "SI"),
    coefficients=(1, -1, 1),
    gross_fraction_per_leg=0.30,
    authoritative=True,
)
FX_ABLATION = StrategyDefinition(
    name="fx_ablation_ri_mix",
    assets=("RI", "MIX"),
    coefficients=(1, -1),
    gross_fraction_per_leg=0.45,
    authoritative=False,
)


@dataclass(frozen=True, slots=True)
class SignalSettings:
    baseline_observations: int = 72
    entry_absolute_z: float = 2.0
    take_profit_absolute_z: float = 0.5
    distant_stop_absolute_z: float = 4.0
    maximum_holding_completed_bars: int = 18
    entry_window_start: time = time(10, 20)
    entry_window_end: time = time(14, 30)
    initial_capital_rub: float = 1_000_000.0
    participation_limit: float = 0.01
    maximum_gross_fraction: float = 1.0
    oos_years: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)

    def __post_init__(self) -> None:
        if self.baseline_observations < 2:
            raise ValueError("baseline requires at least two observations")
        if not (
            0.0 <= self.take_profit_absolute_z
            < self.entry_absolute_z
            < self.distant_stop_absolute_z
        ):
            raise ValueError("z thresholds must satisfy take-profit < entry < stop")
        if self.maximum_holding_completed_bars < 1:
            raise ValueError("maximum holding period must be positive")
        if self.entry_window_start > self.entry_window_end:
            raise ValueError("entry window is inverted")
        if self.initial_capital_rub <= 0.0:
            raise ValueError("initial capital must be positive")
        if not 0.0 < self.participation_limit <= 0.01:
            raise ValueError("participation cannot exceed the sealed one-percent cap")
        if not 0.0 < self.maximum_gross_fraction <= 1.0:
            raise ValueError("maximum gross must be in (0, 1]")
        if not self.oos_years or max(self.oos_years) >= 2026:
            raise ValueError("OOS years touch the protected holdout")


def settings_from_protocol(protocol: Mapping[str, Any]) -> SignalSettings:
    """Build settings only from fields frozen in the sealed YAML protocol."""

    signal = protocol["signal"]
    portfolio = protocol["portfolio"]
    boundaries = protocol["boundaries"]
    start_text, end_text = signal["entry_decision_bar_end_local_inclusive"]
    return SignalSettings(
        baseline_observations=int(signal["baseline_observations"]),
        entry_absolute_z=float(signal["entry_absolute_z"]),
        take_profit_absolute_z=float(signal["take_profit_absolute_z"]),
        distant_stop_absolute_z=float(signal["distant_adverse_stop_absolute_z"]),
        maximum_holding_completed_bars=int(signal["maximum_holding_completed_bars"]),
        entry_window_start=time.fromisoformat(str(start_text)),
        entry_window_end=time.fromisoformat(str(end_text)),
        initial_capital_rub=float(portfolio["initial_capital_rub"]),
        participation_limit=float(portfolio["entry_and_exit_realized_participation_limit"]),
        maximum_gross_fraction=float(portfolio["maximum_total_gross_fraction"]),
        oos_years=tuple(int(value) for value in boundaries["oos_years"]),
    )


def _required_panel_columns(strategy: StrategyDefinition) -> set[str]:
    required = {"timestamp", "end_timestamp"}
    for asset in strategy.assets:
        required.update(
            {
                f"{asset}_contract_id",
                f"{asset}_open",
                f"{asset}_high",
                f"{asset}_low",
                f"{asset}_close",
                f"{asset}_volume",
                f"{asset}_sizing_point_value",
                f"{asset}_sizing_notional",
                f"{asset}_sizing_tick_cash_value",
                f"{asset}_conservative_fee_per_side",
                f"{asset}_sizing_usable",
            }
        )
    return required


def validate_panel(panel: pd.DataFrame, strategy: StrategyDefinition) -> pd.DataFrame:
    """Fail closed on malformed, duplicated, non-ten-minute, or protected rows."""

    missing = _required_panel_columns(strategy) - set(panel.columns)
    if missing:
        raise ValueError(f"V10 panel is missing columns: {sorted(missing)}")
    frame = panel.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise", utc=True)
    frame["end_timestamp"] = pd.to_datetime(
        frame["end_timestamp"], errors="raise", utc=True
    )
    frame = frame.sort_values("timestamp", kind="stable").reset_index(drop=True)
    if frame["timestamp"].duplicated().any():
        raise ValueError("V10 common panel has duplicated timestamps")
    if (frame["end_timestamp"] - frame["timestamp"]).ne(TEN_MINUTES).any():
        raise ValueError("V10 accepts exact ten-minute bars only")
    if (
        frame["timestamp"].ge(PROTECTED_FROM).any()
        or frame["end_timestamp"].gt(PROTECTED_FROM).any()
    ):
        raise ValueError("V10 panel touches protected 2026 data")
    for asset in strategy.assets:
        values = frame[
            [
                f"{asset}_open",
                f"{asset}_high",
                f"{asset}_low",
                f"{asset}_close",
                f"{asset}_volume",
            ]
        ].apply(pd.to_numeric, errors="coerce")
        valid = (
            values.notna().all(axis=1)
            & values[f"{asset}_open"].gt(0.0)
            & values[f"{asset}_close"].gt(0.0)
            & values[f"{asset}_high"].ge(
                values[[f"{asset}_open", f"{asset}_close"]].max(axis=1)
            )
            & values[f"{asset}_low"].le(
                values[[f"{asset}_open", f"{asset}_close"]].min(axis=1)
            )
            & values[f"{asset}_low"].gt(0.0)
            & values[f"{asset}_volume"].ge(0.0)
        )
        if not valid.all():
            raise ValueError(f"V10 panel contains invalid {asset} OHLCV")
    return frame


def build_signal_frame(
    panel: pd.DataFrame,
    strategy: StrategyDefinition,
    settings: SignalSettings,
) -> pd.DataFrame:
    """Calculate a prior-window z-score within each contiguous contract tuple."""

    frame = validate_panel(panel, strategy)
    residual = np.zeros(len(frame), dtype=np.float64)
    for asset, coefficient in zip(strategy.assets, strategy.coefficients, strict=True):
        residual += coefficient * np.log(frame[f"{asset}_close"].to_numpy(dtype=float))
    frame["residual"] = residual
    contract_columns = [f"{asset}_contract_id" for asset in strategy.assets]
    contracts = frame[contract_columns].fillna("").astype(str)
    valid_contracts = contracts.ne("").all(axis=1)
    same_previous = contracts.eq(contracts.shift(1)).all(axis=1)
    contiguous_run_start = ~(
        same_previous & valid_contracts & valid_contracts.shift(1, fill_value=False)
    )
    frame["contract_run_id"] = contiguous_run_start.cumsum().astype(np.int64)
    lagged = frame.groupby("contract_run_id", sort=False)["residual"].shift(1)
    grouped_lagged = lagged.groupby(frame["contract_run_id"], sort=False)
    window = settings.baseline_observations
    frame["baseline_mean"] = grouped_lagged.transform(
        lambda values: values.rolling(window, min_periods=window).mean()
    )
    frame["baseline_std"] = grouped_lagged.transform(
        lambda values: values.rolling(window, min_periods=window).std(ddof=1)
    )
    usable_std = frame["baseline_std"].where(frame["baseline_std"] > 1e-12)
    frame["zscore"] = (frame["residual"] - frame["baseline_mean"]) / usable_std

    same_next_contract = contracts.eq(contracts.shift(-1)).all(axis=1)
    frame["exact_next"] = (
        frame["timestamp"].shift(-1).eq(frame["end_timestamp"])
        & same_next_contract
        & valid_contracts
        & valid_contracts.shift(-1, fill_value=False)
    )
    local_end = frame["end_timestamp"].dt.tz_convert(MOSCOW_TIMEZONE)
    seconds = local_end.dt.hour * 3600 + local_end.dt.minute * 60 + local_end.dt.second
    start_seconds = (
        settings.entry_window_start.hour * 3600
        + settings.entry_window_start.minute * 60
        + settings.entry_window_start.second
    )
    end_seconds = (
        settings.entry_window_end.hour * 3600
        + settings.entry_window_end.minute * 60
        + settings.entry_window_end.second
    )
    frame["local_date"] = local_end.dt.tz_localize(None).dt.normalize()
    frame["oos"] = local_end.dt.year.isin(settings.oos_years)
    frame["entry_window"] = seconds.between(start_seconds, end_seconds, inclusive="both")
    frame["signal_ready"] = np.isfinite(frame["zscore"])
    frame["eligible_signal_bar"] = (
        frame["oos"] & frame["entry_window"] & frame["signal_ready"]
    )
    frame["raw_entry_signal"] = (
        frame["eligible_signal_bar"]
        & frame["zscore"].abs().ge(settings.entry_absolute_z)
    )
    frame["residual_position_side"] = np.where(
        frame["raw_entry_signal"], -np.sign(frame["zscore"]), 0.0
    ).astype(np.int8)
    return frame


@dataclass(slots=True)
class _OpenBasket:
    entry_decision_index: int
    entry_fill_index: int
    entry_residual_side: int
    entry_zscore: float
    contracts: dict[str, str]
    leg_sides: dict[str, int]
    quantities: dict[str, int]
    entry_prices: dict[str, float]
    point_values: dict[str, float]
    notionals: dict[str, float]
    entry_cost_per_side: dict[str, float]
    entry_participation: dict[str, float]


@dataclass(frozen=True, slots=True)
class SimulationResult:
    strategy: str
    trades: pd.DataFrame
    legs: pd.DataFrame
    unresolved_events: pd.DataFrame
    counts: dict[str, Any]
    halted: bool


def _finite_positive(value: object) -> bool:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric) and numeric > 0.0


def _usable_specs(row: pd.Series, assets: Sequence[str]) -> bool:
    for asset in assets:
        if not bool(row[f"{asset}_sizing_usable"]):
            return False
        for field in (
            "sizing_point_value",
            "sizing_notional",
            "sizing_tick_cash_value",
            "conservative_fee_per_side",
        ):
            value = row[f"{asset}_{field}"]
            if field == "conservative_fee_per_side":
                if not math.isfinite(float(value)) or float(value) < 0.0:
                    return False
            elif not _finite_positive(value):
                return False
    return True


def _contracts_match(row: pd.Series, position: _OpenBasket) -> bool:
    return all(
        str(row[f"{asset}_contract_id"]) == contract
        for asset, contract in position.contracts.items()
    )


def _is_exact_successor(previous: pd.Series, current: pd.Series) -> bool:
    return pd.Timestamp(current["timestamp"]) == pd.Timestamp(previous["end_timestamp"])


def simulate_strategy(
    signals: pd.DataFrame,
    strategy: StrategyDefinition,
    settings: SignalSettings,
) -> SimulationResult:
    """Execute one non-overlapping basket with causal sizing and adverse fills."""

    frame = signals.reset_index(drop=True)
    required = {
        "zscore",
        "oos",
        "entry_window",
        "signal_ready",
        "eligible_signal_bar",
        "raw_entry_signal",
        "exact_next",
    }
    if required - set(frame.columns):
        raise ValueError("signals must come from build_signal_frame")
    if len(frame) and pd.Timestamp(frame["end_timestamp"].max()) > PROTECTED_FROM:
        raise ValueError("simulation touches protected 2026 data")

    oos_mask = frame["oos"].astype(bool)
    counts: dict[str, Any] = {
        "common_bars": int(oos_mask.sum()),
        "eligible_signal_bars": int(frame["eligible_signal_bar"].sum()),
        "raw_entries": int(frame["raw_entry_signal"].sum()),
        "orders_submitted": 0,
        "skipped_zero_quantity": 0,
        "skipped_missing_spec": 0,
        "rejected_capacity": 0,
        "unresolved": 0,
        "completed_trades": 0,
        "exits_by_reason": {"distant_stop": 0, "take_profit": 0, "time_exit": 0},
    }
    basket_rows: list[dict[str, Any]] = []
    leg_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    position: _OpenBasket | None = None
    equity_ordinary = settings.initial_capital_rub
    halted = False

    def fail(index: int, reason: str, phase: str) -> None:
        nonlocal halted
        counts["unresolved"] += 1
        unresolved_rows.append(
            {
                "strategy": strategy.name,
                "index": index,
                "decision_at": frame.iloc[index]["end_timestamp"] if len(frame) else pd.NaT,
                "phase": phase,
                "reason": reason,
            }
        )
        halted = True

    for index in range(len(frame)):
        row = frame.iloc[index]
        if not bool(row["oos"]):
            continue
        just_requested_exit = False
        if position is not None:
            if index > position.entry_fill_index:
                previous = frame.iloc[index - 1]
                if not _is_exact_successor(previous, row):
                    fail(index, "clock_gap_while_open", "monitor")
                    break
            if not _contracts_match(row, position):
                fail(index, "contract_changed_while_open", "monitor")
                break
            holding_bars = index - position.entry_fill_index + 1
            zscore = float(row["zscore"])
            exit_reason = ""
            adverse_extension = (
                position.entry_residual_side * zscore
                <= -settings.distant_stop_absolute_z
            )
            if math.isfinite(zscore) and adverse_extension:
                # A residual position is opposite the entry z sign.  A loss therefore has
                # position_side * current_z <= -stop.
                exit_reason = "distant_stop"
            elif math.isfinite(zscore) and abs(zscore) <= settings.take_profit_absolute_z:
                exit_reason = "take_profit"
            elif holding_bars >= settings.maximum_holding_completed_bars:
                exit_reason = "time_exit"

            if exit_reason:
                just_requested_exit = True
                exit_index = index + 1
                if exit_index >= len(frame):
                    fail(index, "missing_exit_successor", "exit")
                    break
                exit_row = frame.iloc[exit_index]
                if not _is_exact_successor(row, exit_row):
                    fail(index, "non_exact_exit_successor", "exit")
                    break
                if not _contracts_match(exit_row, position):
                    fail(index, "contract_changed_before_exit_fill", "exit")
                    break
                if not _usable_specs(row, strategy.assets):
                    fail(index, "missing_exit_spec", "exit")
                    break
                insufficient_exit_capacity = any(
                    position.quantities[asset]
                    > math.floor(
                        settings.participation_limit * float(exit_row[f"{asset}_volume"])
                    )
                    for asset in strategy.assets
                )
                if insufficient_exit_capacity:
                    counts["rejected_capacity"] += 1
                    fail(index, "insufficient_exit_window_capacity", "exit")
                    break

                trade_legs: list[dict[str, Any]] = []
                for asset in strategy.assets:
                    side = position.leg_sides[asset]
                    exit_price = float(
                        exit_row[f"{asset}_low"] if side == 1 else exit_row[f"{asset}_high"]
                    )
                    quantity = position.quantities[asset]
                    gross_pnl = (
                        quantity
                        * position.point_values[asset]
                        * side
                        * (exit_price - position.entry_prices[asset])
                    )
                    exit_cost_per_side = float(
                        row[f"{asset}_conservative_fee_per_side"]
                        + row[f"{asset}_sizing_tick_cash_value"]
                    )
                    costs_1x = quantity * (
                        position.entry_cost_per_side[asset] + exit_cost_per_side
                    )
                    exit_participation = quantity / max(
                        float(exit_row[f"{asset}_volume"]), 1.0
                    )
                    leg = {
                        "strategy": strategy.name,
                        "trade_id": len(basket_rows),
                        "asset": asset,
                        "contract_id": position.contracts[asset],
                        "side": "long" if side == 1 else "short",
                        "quantity": quantity,
                        "entry_price": position.entry_prices[asset],
                        "exit_price": exit_price,
                        "point_value": position.point_values[asset],
                        "entry_notional": quantity * position.notionals[asset],
                        "gross_pnl": gross_pnl,
                        "costs_1x": costs_1x,
                        "pnl_1x": gross_pnl - costs_1x,
                        "pnl_2x": gross_pnl - 2.0 * costs_1x,
                        "entry_participation": position.entry_participation[asset],
                        "exit_participation": exit_participation,
                    }
                    trade_legs.append(leg)
                    leg_rows.append(leg)
                gross_pnl = float(sum(leg["gross_pnl"] for leg in trade_legs))
                costs_1x = float(sum(leg["costs_1x"] for leg in trade_legs))
                pnl_1x = gross_pnl - costs_1x
                pnl_2x = gross_pnl - 2.0 * costs_1x
                entry_row = frame.iloc[position.entry_decision_index]
                basket_rows.append(
                    {
                        "strategy": strategy.name,
                        "trade_id": len(basket_rows),
                        "entry_decision_at": entry_row["end_timestamp"],
                        "entry_fill_at": frame.iloc[position.entry_fill_index]["end_timestamp"],
                        "exit_decision_at": row["end_timestamp"],
                        "exit_fill_at": exit_row["end_timestamp"],
                        "entry_side": (
                            "long_residual"
                            if position.entry_residual_side == 1
                            else "short_residual"
                        ),
                        "entry_zscore": position.entry_zscore,
                        "exit_zscore": zscore,
                        "holding_completed_bars": holding_bars,
                        "exit_reason": exit_reason,
                        "gross_entry_notional": float(
                            sum(
                                position.quantities[asset] * position.notionals[asset]
                                for asset in strategy.assets
                            )
                        ),
                        "gross_pnl": gross_pnl,
                        "costs_1x": costs_1x,
                        "pnl_1x": pnl_1x,
                        "pnl_2x": pnl_2x,
                        "maximum_entry_participation": max(
                            position.entry_participation.values()
                        ),
                        "maximum_exit_participation": max(
                            float(leg["exit_participation"]) for leg in trade_legs
                        ),
                    }
                )
                equity_ordinary += pnl_1x
                counts["completed_trades"] += 1
                counts["exits_by_reason"][exit_reason] += 1
                position = None

        if halted or position is not None or just_requested_exit:
            continue
        if not bool(row["raw_entry_signal"]):
            continue
        if not bool(row["exact_next"]):
            fail(index, "missing_exact_entry_successor", "entry")
            break
        if not _usable_specs(row, strategy.assets):
            counts["skipped_missing_spec"] += 1
            continue
        entry_index = index + 1
        entry_row = frame.iloc[entry_index]
        residual_side = int(row["residual_position_side"])
        quantities: dict[str, int] = {}
        contracts: dict[str, str] = {}
        leg_sides: dict[str, int] = {}
        entry_prices: dict[str, float] = {}
        point_values: dict[str, float] = {}
        notionals: dict[str, float] = {}
        entry_cost_per_side: dict[str, float] = {}
        entry_participation: dict[str, float] = {}
        for asset, coefficient in zip(strategy.assets, strategy.coefficients, strict=True):
            notional = float(row[f"{asset}_sizing_notional"])
            capital_quantity = math.floor(
                strategy.gross_fraction_per_leg * max(equity_ordinary, 0.0) / notional
            )
            causal_capacity = math.floor(
                settings.participation_limit * float(row[f"{asset}_volume"])
            )
            quantities[asset] = min(capital_quantity, causal_capacity)
            contracts[asset] = str(row[f"{asset}_contract_id"])
            leg_sides[asset] = residual_side * coefficient
            point_values[asset] = float(row[f"{asset}_sizing_point_value"])
            notionals[asset] = notional
            entry_cost_per_side[asset] = float(
                row[f"{asset}_conservative_fee_per_side"]
                + row[f"{asset}_sizing_tick_cash_value"]
            )
        if any(quantity < 1 for quantity in quantities.values()):
            counts["skipped_zero_quantity"] += 1
            continue
        gross = sum(quantities[asset] * notionals[asset] for asset in strategy.assets)
        if gross > settings.maximum_gross_fraction * max(equity_ordinary, 0.0) + 1e-9:
            raise AssertionError("sealed V10 gross cap was exceeded")
        counts["orders_submitted"] += 1
        insufficient_entry_capacity = any(
            quantities[asset]
            > math.floor(
                settings.participation_limit * float(entry_row[f"{asset}_volume"])
            )
            for asset in strategy.assets
        )
        if insufficient_entry_capacity:
            counts["rejected_capacity"] += 1
            fail(index, "insufficient_entry_window_capacity", "entry")
            break
        for asset in strategy.assets:
            side = leg_sides[asset]
            entry_prices[asset] = float(
                entry_row[f"{asset}_high"] if side == 1 else entry_row[f"{asset}_low"]
            )
            entry_participation[asset] = quantities[asset] / max(
                float(entry_row[f"{asset}_volume"]), 1.0
            )
        position = _OpenBasket(
            entry_decision_index=index,
            entry_fill_index=entry_index,
            entry_residual_side=residual_side,
            entry_zscore=float(row["zscore"]),
            contracts=contracts,
            leg_sides=leg_sides,
            quantities=quantities,
            entry_prices=entry_prices,
            point_values=point_values,
            notionals=notionals,
            entry_cost_per_side=entry_cost_per_side,
            entry_participation=entry_participation,
        )

    if position is not None and not halted:
        fail(len(frame) - 1, "open_position_at_data_end", "terminal")
    return SimulationResult(
        strategy=strategy.name,
        trades=pd.DataFrame(basket_rows),
        legs=pd.DataFrame(leg_rows),
        unresolved_events=pd.DataFrame(unresolved_rows),
        counts=counts,
        halted=halted,
    )


def calculate_metrics(
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    settings: SignalSettings,
    *,
    cost_column: str,
    valid: bool,
) -> dict[str, Any]:
    """Calculate daily realized metrics on the fixed 2021-2025 OOS calendar."""

    if cost_column not in {"pnl_1x", "pnl_2x"}:
        raise ValueError("unknown cost scenario")
    oos = signals.loc[signals["oos"].astype(bool)]
    calendar = pd.DatetimeIndex(sorted(pd.to_datetime(oos["local_date"]).unique()))
    daily_pnl = pd.Series(0.0, index=calendar, dtype=float)
    if not trades.empty:
        exits = pd.to_datetime(trades["exit_fill_at"], errors="raise", utc=True)
        exit_dates = exits.dt.tz_convert(MOSCOW_TIMEZONE).dt.tz_localize(None).dt.normalize()
        grouped = trades.assign(_exit_date=exit_dates).groupby("_exit_date")[cost_column].sum()
        common = daily_pnl.index.intersection(grouped.index)
        daily_pnl.loc[common] = grouped.loc[common]
    equity = settings.initial_capital_rub + daily_pnl.cumsum()
    previous = equity.shift(1).fillna(settings.initial_capital_rub)
    returns = daily_pnl / previous.where(previous > 0.0)
    final_equity = float(equity.iloc[-1]) if len(equity) else settings.initial_capital_rub
    elapsed_days = max((calendar[-1] - calendar[0]).days + 1, 1) if len(calendar) else 1
    cagr = (
        (max(final_equity, 1e-12) / settings.initial_capital_rub)
        ** (365.25 / elapsed_days)
        - 1.0
    )
    return_std = float(returns.std(ddof=0)) if len(returns) else 0.0
    sharpe = (
        float(returns.mean() / return_std * math.sqrt(252.0))
        if return_std > 0.0
        else 0.0
    )
    if len(equity):
        values = np.concatenate(([settings.initial_capital_rub], equity.to_numpy(dtype=float)))
        peaks = np.maximum.accumulate(values)
        maximum_drawdown = float(np.min(values / peaks - 1.0))
    else:
        maximum_drawdown = 0.0
    selected_pnl = trades[cost_column].astype(float) if not trades.empty else pd.Series(dtype=float)
    gains = float(selected_pnl[selected_pnl > 0.0].sum())
    losses = float(-selected_pnl[selected_pnl < 0.0].sum())
    profit_factor: float | None = gains / losses if losses > 0.0 else (None if gains > 0 else 0.0)
    per_year: dict[str, dict[str, float | int]] = {}
    running_start = settings.initial_capital_rub
    for year in settings.oos_years:
        yearly = daily_pnl[daily_pnl.index.year == year]
        yearly_pnl = float(yearly.sum())
        if trades.empty:
            yearly_trades = 0
        else:
            exit_year = (
                pd.to_datetime(trades["exit_fill_at"], utc=True)
                .dt.tz_convert(MOSCOW_TIMEZONE)
                .dt.year
            )
            yearly_trades = int(exit_year.eq(year).sum())
        yearly_return = yearly_pnl / running_start if running_start > 0.0 else -1.0
        per_year[str(year)] = {
            "return": float(yearly_return),
            "pnl_rub": yearly_pnl,
            "trades": yearly_trades,
        }
        running_start += yearly_pnl
    max_participation = 0.0
    if not trades.empty:
        max_participation = float(
            trades[["maximum_entry_participation", "maximum_exit_participation"]]
            .max(axis=1)
            .max()
        )
    return {
        "valid": bool(valid),
        "trades": int(len(trades)),
        "total_return": float(final_equity / settings.initial_capital_rub - 1.0),
        "cagr": float(cagr),
        "annualized_sharpe": sharpe,
        "maximum_drawdown": maximum_drawdown,
        "final_equity_rub": final_equity,
        "win_rate": float((selected_pnl > 0.0).mean()) if len(selected_pnl) else 0.0,
        "profit_factor": profit_factor,
        "average_trade_pnl": float(selected_pnl.mean()) if len(selected_pnl) else 0.0,
        "costs_rub": (
            float(trades["costs_1x"].sum()) * (1.0 if cost_column == "pnl_1x" else 2.0)
            if not trades.empty
            else 0.0
        ),
        "maximum_realized_participation": max_participation,
        "positive_years": int(
            sum(float(values["return"]) > 0.0 for values in per_year.values())
        ),
        "per_year": per_year,
    }


def evaluate_promotion(
    primary_ordinary: Mapping[str, Any],
    primary_doubled: Mapping[str, Any],
    ablation_ordinary: Mapping[str, Any],
    counts: Mapping[str, Any],
    rules: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate every sealed promotion condition without changing thresholds."""

    per_year = primary_ordinary["per_year"]
    checks = {
        "metrics_valid": bool(primary_ordinary["valid"] and primary_doubled["valid"]),
        "completed_trades_minimum": int(primary_ordinary["trades"])
        >= int(rules["completed_trades_minimum"]),
        "minimum_trades_each_year": all(
            int(values["trades"]) >= int(rules["completed_trades_minimum_each_oos_year"])
            for values in per_year.values()
        ),
        "positive_years": int(primary_ordinary["positive_years"])
        >= int(rules["positive_oos_years_minimum"]),
        "ordinary_cagr": float(primary_ordinary["cagr"])
        >= float(rules["ordinary_cagr_minimum"]),
        "ordinary_sharpe": float(primary_ordinary["annualized_sharpe"])
        >= float(rules["ordinary_annualized_sharpe_minimum"]),
        "ordinary_drawdown": float(primary_ordinary["maximum_drawdown"])
        >= float(rules["ordinary_maximum_drawdown_floor"]),
        "doubled_cost_cagr": float(primary_doubled["cagr"]) > 0.0,
        "doubled_cost_sharpe": float(primary_doubled["annualized_sharpe"])
        >= float(rules["doubled_cost_annualized_sharpe_minimum"]),
        "fx_ablation_advantage": (
            float(primary_ordinary["annualized_sharpe"])
            - float(ablation_ordinary["annualized_sharpe"])
        )
        >= float(rules["primary_sharpe_advantage_over_fx_ablation_minimum"]),
        "unresolved_zero": int(counts["unresolved"]) == 0,
        "participation_cap": float(primary_ordinary["maximum_realized_participation"])
        <= float(rules["maximum_realized_participation_must_not_exceed"]) + 1e-12,
        "protected_holdout_untouched": True,
    }
    return {"passed": all(checks.values()), "checks": checks}
