"""V62 event ledger: causal requests, bounded fills, marked open positions."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from market_lab.futures.opening_regime_v2 import Market, local_time

SCENARIOS = {"primary": (1, 1.0), "doubled": (2, 2.0), "stress": (4, 2.0)}


def metrics(equity: pd.DataFrame, initial: float = 1_000_000.0) -> dict:
    values = equity["equity"].to_numpy(float)
    returns = values / np.r_[initial, values[:-1]] - 1.0
    peaks = np.maximum.accumulate(np.r_[initial, values])[1:]
    # Fixed reporting horizon includes sleeping dates, with the initial capital as the first peak.
    years = (
        equity["local_date"].iloc[-1] + pd.Timedelta(days=1) - equity["local_date"].iloc[0]
    ).days / 365.2425
    yearly = {}
    for year, group in equity.groupby(equity["local_date"].dt.year):
        yearly[str(year)] = float(group["equity"].iloc[-1] / group["equity_before"].iloc[0] - 1)
    std = float(np.std(returns, ddof=0))
    return dict(
        cagr=float((values[-1] / initial) ** (1 / years) - 1) if values[-1] > 0 else -1.0,
        total_return=float(values[-1] / initial - 1),
        sharpe=float(np.mean(returns) / std * np.sqrt(252)) if std > 0 else 0.0,
        maximum_drawdown=float(np.max(1 - values / peaks)),
        yearly_returns=yearly,
        positive_years=sum(v > 0 for v in yearly.values()),
        worst_year=min(yearly.values()),
        final_equity=float(values[-1]),
    )


def simulate(
    predictions: pd.DataFrame, market: Market, specs: pd.DataFrame, scenario: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    ticks, fee_multiplier = SCENARIOS[scenario]
    spec_lookup = specs.set_index(["local_date", "contract_id"])
    signals = predictions.loc[predictions["direction"].ne(0)].copy()
    by_time = {time: part.sort_values("asset") for time, part in signals.groupby("entry_at")}
    sessions = market.sessions[(market.sessions.year >= 2021) & (market.sessions.year <= 2025)]
    cash = 1_000_000.0
    orders, trades, equity_rows, marks, failures = [], [], [], [], []
    maximum_gross, maximum_participation, maximum_margin = 0.0, 0.0, 0.0
    halted = False
    for day in sessions:
        if halted:
            break
        before = cash
        positions = {}
        entered = set()
        for minute in range(610, 741, 10):
            timestamp = local_time(day, minute)
            # Close requests retain remaining integer quantity; every retry uses its own volume.
            for asset, pos in list(positions.items()):
                if timestamp < pos["exit_at"]:
                    continue
                row = market.bar(pos["contract_id"], timestamp)
                quantity = (
                    min(pos["remaining"], math.floor(float(row["volume"]) * 0.01))
                    if row is not None
                    else 0
                )
                orders.append(
                    dict(
                        candidate_id=pos["candidate_id"],
                        asset=asset,
                        timestamp=timestamp,
                        kind="exit",
                        requested=pos["remaining"],
                        filled=quantity,
                        reason="filled" if quantity else "no_capacity_or_bar",
                    )
                )
                if quantity:
                    fill = float(row["open"]) - pos["direction"] * ticks * pos["tick"]
                    gross = pos["direction"] * quantity * (fill - pos["entry_fill"]) * pos["point"]
                    fee = quantity * pos["fee"] * fee_multiplier
                    cash += gross - fee
                    pos["remaining"] -= quantity
                    pos["exit_pnl"] += gross - fee
                    pos["fees"] += fee
                    pos["slippage"] += quantity * ticks * pos["tick"] * pos["point"]
                    pos["exit_notional"] += quantity * float(row["open"]) * pos["point"]
                    maximum_participation = max(maximum_participation, quantity / row["volume"])
                    if not pos["remaining"]:
                        trades.append(
                            dict(
                                candidate_id=pos["candidate_id"],
                                local_date=day,
                                asset=asset,
                                contract_id=pos["contract_id"],
                                decision_minute=pos["decision_minute"],
                                entry_at=pos["entry_at"],
                                exit_at=timestamp,
                                direction=pos["direction"],
                                quantity=pos["quantity"],
                                pnl=pos["exit_pnl"] - pos["entry_fee"],
                                fees=pos["fees"],
                                slippage=pos["slippage"],
                                turnover=pos["entry_notional"] + pos["exit_notional"],
                                exit_retried=timestamp > pos["exit_at"],
                            )
                        )
                        del positions[asset]
            # Decision equity and exposure use only completed bars, never an exit horizon.
            decision_equity, gross_current, pricing_valid = cash, 0.0, True
            for pos in positions.values():
                completed = market.bar(pos["contract_id"], timestamp - pd.Timedelta(minutes=10))
                if completed is None:
                    pricing_valid = False
                    break
                price = float(completed["close"])
                decision_equity += (
                    pos["direction"] * pos["remaining"] * (price - pos["entry_fill"]) * pos["point"]
                )
                gross_current += pos["remaining"] * price * pos["point"]
            current = by_time.get(timestamp, pd.DataFrame())
            for signal in current.itertuples(index=False):
                if signal.asset in entered:
                    continue
                record = dict(
                    candidate_id=signal.candidate_id,
                    asset=signal.asset,
                    timestamp=timestamp,
                    kind="entry",
                    requested=0,
                    filled=0,
                    reason="unusable_spec_or_decision_mark",
                )
                key = (day, signal.contract_id)
                if not pricing_valid or decision_equity <= 0 or key not in spec_lookup.index:
                    orders.append(record)
                    continue
                spec = spec_lookup.loc[key]
                fields = [
                    "sizing_point_value",
                    "sizing_tick_cash_value",
                    "conservative_fee_per_side",
                ]
                values = spec[fields].to_numpy(float)
                if (
                    not bool(spec["sizing_usable"])
                    or not np.isfinite(values).all()
                    or (values <= 0).any()
                    or pd.isna(spec["sizing_observed_session_date"])
                    or spec["sizing_observed_session_date"] >= day
                ):
                    orders.append(record)
                    continue
                point, tick_cash, fee = values
                notional = signal.decision_close * point
                # Two-times 25% model margin equals a 2x gross ceiling; mark breaches are reported.
                budget = max(
                    0.0, min(0.60 * decision_equity, 2.0 * decision_equity - gross_current)
                )
                requested = min(
                    math.floor(budget / notional), math.floor(0.0025 * signal.decision_volume)
                )
                record.update(requested=requested, reason="zero_requested")
                if requested < 1:
                    orders.append(record)
                    continue
                # Actual bar volume affects the fill only, after the request has been recorded.
                row = market.bar(signal.contract_id, timestamp)
                quantity = (
                    min(requested, math.floor(0.01 * float(row["volume"])))
                    if row is not None
                    else 0
                )
                record.update(
                    filled=quantity, reason="filled" if quantity else "no_entry_capacity_or_bar"
                )
                orders.append(record)
                if not quantity:
                    continue
                price = float(row["open"])
                # A price jump can reject/reduce the fill under the same hard admission limits.
                actual_budget = max(
                    0.0, min(0.75 * decision_equity, 2.0 * decision_equity - gross_current)
                )
                quantity = min(quantity, math.floor(actual_budget / (price * point)))
                record.update(
                    filled=quantity, reason="filled" if quantity else "execution_gross_cap"
                )
                if not quantity:
                    continue
                fill = price + signal.direction * ticks * tick_cash / point
                entry_fee = quantity * fee * fee_multiplier
                cash -= entry_fee
                decision_equity -= entry_fee + quantity * ticks * tick_cash
                gross_current += quantity * price * point
                pos = dict(
                    candidate_id=signal.candidate_id,
                    contract_id=signal.contract_id,
                    entry_at=timestamp,
                    exit_at=signal.exit_at,
                    direction=signal.direction,
                    decision_minute=signal.decision_minute,
                    quantity=quantity,
                    remaining=quantity,
                    point=point,
                    tick=tick_cash / point,
                    fee=fee,
                    entry_fill=fill,
                    entry_fee=entry_fee,
                    fees=entry_fee,
                    exit_pnl=0.0,
                    slippage=quantity * ticks * tick_cash,
                    entry_notional=quantity * price * point,
                    exit_notional=0.0,
                )
                positions[signal.asset] = pos
                entered.add(signal.asset)
                maximum_participation = max(maximum_participation, quantity / row["volume"])
            # Open marks use only factual opens; missing marks invalidate the economic gate.
            mark, gross = cash, 0.0
            for asset, pos in positions.items():
                row = market.bar(pos["contract_id"], timestamp)
                if row is None:
                    failures.append(
                        dict(
                            local_date=day,
                            timestamp=timestamp,
                            asset=asset,
                            reason="missing_open_position_mark",
                        )
                    )
                    mark = np.nan
                    continue
                price = float(row["open"])
                mark += (
                    pos["direction"] * pos["remaining"] * (price - pos["entry_fill"]) * pos["point"]
                )
                gross += pos["remaining"] * price * pos["point"]
            marks.append(dict(timestamp=timestamp, equity=mark, gross_notional=gross))
            if np.isfinite(mark) and mark > 0:
                maximum_gross = max(maximum_gross, gross / mark)
                maximum_margin = max(maximum_margin, 0.5 * gross / mark)
            if np.isfinite(mark) and mark <= 0:
                failures.append(
                    dict(local_date=day, timestamp=timestamp, reason="nonpositive_equity")
                )
                halted = True
                break
        if positions:
            failures.extend(
                dict(local_date=day, reason="unresolved_terminal_position", asset=a)
                for a in positions
            )
            halted = True
            break
        equity_rows.append(
            dict(local_date=day, equity_before=before, equity=cash, pnl=cash - before)
        )
    equity = pd.DataFrame(equity_rows)
    result = metrics(equity) if len(equity) else {}
    trades = pd.DataFrame(
        trades,
        columns=[
            "candidate_id",
            "local_date",
            "asset",
            "contract_id",
            "decision_minute",
            "entry_at",
            "exit_at",
            "direction",
            "quantity",
            "pnl",
            "fees",
            "slippage",
            "turnover",
            "exit_retried",
        ],
    )
    mark_frame = pd.DataFrame(marks)
    if not mark_frame.empty:
        vals = mark_frame["equity"].to_numpy(float)
        finite = vals[np.isfinite(vals)]
        intraday_mdd = (
            float(np.max(1 - finite / np.maximum.accumulate(np.r_[1_000_000.0, finite])[1:]))
            if len(finite)
            else None
        )
    else:
        intraday_mdd = 0.0
    result.update(
        dict(
            scenario=scenario,
            prediction_count=len(predictions),
            signal_count=len(signals),
            trade_count=len(trades),
            no_fill_count=sum(o["kind"] == "entry" and not o["filled"] for o in orders),
            unresolved_count=len(failures),
            failures=failures,
            execution_complete=not halted,
            economic_metrics_valid=not halted and not failures,
            maximum_participation=maximum_participation,
            maximum_mark_gross=maximum_gross,
            maximum_modeled_margin_buffer_ratio=maximum_margin,
            intraday_mark_maximum_drawdown=intraday_mdd,
            costs=float((trades["fees"] + trades["slippage"]).sum()),
            turnover=float(trades["turnover"].sum()),
            long_count=int(trades["direction"].eq(1).sum()),
            short_count=int(trades["direction"].eq(-1).sum()),
        )
    )
    result["breakdowns"] = {}
    for field in ("asset", "direction", "decision_minute"):
        result["breakdowns"][field] = {
            str(key): dict(trades=len(group), pnl=float(group["pnl"].sum()))
            for key, group in trades.groupby(field)
        }
    return trades, equity, pd.DataFrame(orders), dict(metrics=result, marks=mark_frame)
