"""Fail-closed next-open execution proxy for frozen V9 structural strategies."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import yaml

PointMode = Literal["selected", "adverse", "favorable"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _positive(value: object) -> bool:
    return bool(pd.notna(value) and np.isfinite(float(value)) and float(value) > 0.0)


def _nonnegative(value: object) -> bool:
    return bool(pd.notna(value) and np.isfinite(float(value)) and float(value) >= 0.0)


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    Path(temporary_name).unlink(missing_ok=True)
    try:
        frame.to_parquet(temporary_name, index=False, compression="zstd")
        Path(temporary_name).replace(path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def load_official_execution_market(
    archive_path: Path, *, forbidden_from: pd.Timestamp
) -> pd.DataFrame:
    """Parse the content-addressed 2017-2025 ISS archive without any network access."""
    records: list[dict[str, Any]] = []
    with gzip.open(archive_path, "rt", encoding="utf-8") as stream:
        first_line = stream.readline()
        if not first_line:
            raise ValueError("official source archive is empty")
        catalog = json.loads(first_line)
        catalog_columns = [str(column) for column in catalog.get("columns", [])]
        required_catalog = {"asset_code", "secid", "contract_id"}
        if not required_catalog.issubset(catalog_columns):
            raise ValueError("official catalog lacks canonical contract mapping")
        catalog_index = {column: catalog_columns.index(column) for column in required_catalog}
        alias_map: dict[str, tuple[str, str]] = {}
        for row in catalog.get("data", []):
            secid = str(row[catalog_index["secid"]])
            mapped = (
                str(row[catalog_index["contract_id"]]),
                str(row[catalog_index["asset_code"]]),
            )
            if secid in alias_map and alias_map[secid] != mapped:
                raise ValueError("catalog SECID maps to conflicting contracts")
            alias_map[secid] = mapped
        for line in stream:
            record = json.loads(line)
            payload = record.get("payload")
            if not isinstance(payload, dict) or "history" not in payload:
                raise ValueError("source archive history record is malformed")
            block = payload["history"]
            columns = [str(column).lower() for column in block.get("columns", [])]
            required = {
                "tradedate",
                "secid",
                "open",
                "low",
                "high",
                "close",
                "settleprice",
                "value",
                "volume",
                "waprice",
                "openposition",
                "openpositionvalue",
            }
            if not required.issubset(columns):
                raise ValueError("official history page lacks execution fields")
            index = {column: columns.index(column) for column in required}
            for raw in block.get("data", []):
                trade_date = pd.Timestamp(raw[index["tradedate"]]).normalize()
                if trade_date >= forbidden_from:
                    raise ValueError("protected 2026+ row in official execution archive")
                secid = str(raw[index["secid"]])
                if secid not in alias_map:
                    raise ValueError(f"history SECID absent from canonical catalog: {secid}")
                contract_id, asset_code = alias_map[secid]
                records.append(
                    {
                        "asset_code": asset_code,
                        "contract_id": contract_id,
                        "secid": secid,
                        "trade_date": trade_date,
                        "open": raw[index["open"]],
                        "low": raw[index["low"]],
                        "high": raw[index["high"]],
                        "close": raw[index["close"]],
                        "settle": raw[index["settleprice"]],
                        "value": raw[index["value"]],
                        "volume": raw[index["volume"]],
                        "waprice": raw[index["waprice"]],
                        "open_interest": raw[index["openposition"]],
                        "open_interest_value": raw[index["openpositionvalue"]],
                    }
                )
    market = pd.DataFrame(records)
    if market.empty:
        raise ValueError("official execution archive has no rows")
    numeric = [
        "open",
        "low",
        "high",
        "close",
        "settle",
        "value",
        "volume",
        "waprice",
        "open_interest",
        "open_interest_value",
    ]
    for column in numeric:
        market[column] = pd.to_numeric(market[column], errors="coerce")
    market = market.sort_values(
        ["asset_code", "contract_id", "trade_date", "value", "volume", "secid"],
        ascending=[True, True, True, False, False, True],
        na_position="last",
        kind="mergesort",
    ).drop_duplicates(["asset_code", "contract_id", "trade_date"], keep="first")
    primary = market["value"] / (market["volume"] * market["waprice"])
    primary = primary.where(
        market["value"].gt(0.0) & market["volume"].gt(0.0) & market["waprice"].gt(0.0)
    )
    fallback = market["open_interest_value"] / (market["open_interest"] * market["settle"])
    fallback = fallback.where(
        market["open_interest_value"].gt(0.0)
        & market["open_interest"].gt(0.0)
        & market["settle"].gt(0.0)
    )
    market["primary_point_value"] = primary.where(np.isfinite(primary) & primary.gt(0.0))
    market["fallback_point_value"] = fallback.where(np.isfinite(fallback) & fallback.gt(0.0))
    market["realized_point_value"] = market["primary_point_value"].fillna(
        market["fallback_point_value"]
    )
    market["point_value_source"] = np.select(
        [market["primary_point_value"].notna(), market["fallback_point_value"].notna()],
        ["primary_trade_value", "fallback_open_interest_value"],
        default="unavailable",
    )
    market["point_value_lower"] = market[["primary_point_value", "fallback_point_value"]].min(
        axis=1, skipna=True
    )
    market["point_value_upper"] = market[["primary_point_value", "fallback_point_value"]].max(
        axis=1, skipna=True
    )
    no_proxy = market["realized_point_value"].isna()
    market.loc[no_proxy, ["point_value_lower", "point_value_upper"]] = np.nan
    calendar = pd.DatetimeIndex(sorted(market["trade_date"].unique()))
    ordinal = pd.Series(np.arange(len(calendar), dtype=int), index=calendar)
    market["session_ordinal"] = market["trade_date"].map(ordinal)
    groups = market.groupby("contract_id", sort=False, observed=True)
    market["lag_session_date"] = groups["trade_date"].shift(1)
    market["lag_session_ordinal"] = groups["session_ordinal"].shift(1)
    market["lag_point_value"] = groups["realized_point_value"].shift(1)
    market["lag_point_value_lower"] = groups["point_value_lower"].shift(1)
    market["lag_point_value_upper"] = groups["point_value_upper"].shift(1)
    market["lag_volume"] = groups["volume"].shift(1)
    market["lag_gap"] = market["session_ordinal"] - market["lag_session_ordinal"]
    market["sizing_proxy_usable"] = (
        market["lag_gap"].eq(1.0)
        & market["lag_point_value"].gt(0.0)
        & market["lag_volume"].ge(0.0)
        & market["open"].gt(0.0)
        & market["settle"].gt(0.0)
    )
    return market.sort_values(
        ["trade_date", "asset_code", "contract_id"], kind="mergesort"
    ).reset_index(drop=True)


@dataclass(frozen=True, slots=True)
class FrozenWeightPlan:
    strategy: str
    dates: pd.DatetimeIndex
    assets: tuple[str, ...]
    weights: pd.DataFrame
    weight_decision_dates: pd.Series
    active_contracts: pd.DataFrame
    canonical_missing_return_dates: frozenset[pd.Timestamp]


def build_frozen_weight_plan(
    panel: pd.DataFrame, config: dict[str, Any], strategy: str
) -> FrozenWeightPlan:
    horizons = [int(value) for value in config["signals"]["momentum_horizons_sessions"]]
    columns = {
        "tsmom_6m": f"signal_tsmom_{horizons[2]}",
        "tsmom_multi": "signal_tsmom_multi",
        "risk_adjusted_momentum": "signal_risk_adjusted_momentum",
    }
    if strategy not in columns:
        raise ValueError(f"strategy is not frozen for exact execution: {strategy}")
    minimum_assets = int(config["eligibility"]["minimum_daily_assets"])
    observed_counts = panel.groupby("trade_date")["asset_code"].nunique()
    dates = pd.DatetimeIndex(sorted(observed_counts.loc[observed_counts.ge(minimum_assets)].index))
    assets = tuple(sorted(panel["asset_code"].astype(str).unique()))

    def wide(column: str) -> pd.DataFrame:
        return panel.pivot(index="trade_date", columns="asset_code", values=column).reindex(
            index=dates, columns=assets
        )

    volatility = wide("volatility")
    eligible = wide("eligible").eq(True)
    signal = wide(columns[strategy])
    valid = eligible & signal.notna() & volatility.gt(0.0)
    raw = (signal / volatility).where(valid)
    raw_gross = raw.abs().sum(axis=1)
    target = raw.div(raw_gross.replace(0.0, np.nan), axis=0).clip(
        -float(config["portfolio"]["single_asset_cap"]),
        float(config["portfolio"]["single_asset_cap"]),
    )
    target = target.fillna(0.0)
    estimated_volatility = np.sqrt(np.square(target * volatility.fillna(0.0)).sum(axis=1))
    volatility_scale = (
        (
            float(config["portfolio"]["volatility_target_annualized"])
            / estimated_volatility.replace(0.0, np.nan)
        )
        .clip(upper=1.0)
        .fillna(1.0)
    )
    target = target.mul(volatility_scale, axis=0)
    target_gross = target.abs().sum(axis=1)
    gross_scale = (
        (float(config["portfolio"]["gross_cap"]) / target_gross.replace(0.0, np.nan))
        .clip(upper=1.0)
        .fillna(1.0)
    )
    target = target.mul(gross_scale, axis=0)
    target.loc[valid.sum(axis=1).lt(minimum_assets), :] = 0.0
    weeks = target.index.to_period("W-SUN")
    rebalance_dates = pd.Series(target.index, index=target.index).groupby(weeks).max()
    is_rebalance = target.index.isin(rebalance_dates.to_numpy())
    desired = target.copy()
    desired.loc[~is_rebalance, :] = np.nan
    desired = desired.ffill().fillna(0.0)
    decision_dates = pd.Series(pd.NaT, index=dates, dtype="datetime64[ns]")
    decision_dates.loc[is_rebalance] = dates[is_rebalance]
    decision_dates = decision_dates.ffill()
    active_contracts = wide("active_contract")
    returns = wide("asset_return")
    held = desired.shift(1).fillna(0.0)
    silent_missing = (held.abs() * returns.isna()).sum(axis=1).gt(0.0)
    development = pd.Series(dates, index=dates).between(
        pd.Timestamp(config["dates"]["development_start"]),
        pd.Timestamp(config["dates"]["development_end"]),
    )
    missing_dates = frozenset(pd.Timestamp(value) for value in dates[silent_missing & development])
    return FrozenWeightPlan(
        strategy=strategy,
        dates=dates,
        assets=assets,
        weights=desired,
        weight_decision_dates=decision_dates,
        active_contracts=active_contracts,
        canonical_missing_return_dates=missing_dates,
    )


@dataclass(slots=True)
class _Position:
    contract_id: str
    quantity: int
    previous_settle: float


@dataclass(slots=True)
class _PendingTarget:
    key: tuple[object, ...]
    contract_id: str | None
    quantity: int | None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    ledger: pd.DataFrame
    orders: pd.DataFrame
    metrics: dict[str, Any]


def _market_row(
    indexed: pd.DataFrame, trade_date: pd.Timestamp, contract_id: str | None
) -> pd.Series | None:
    if contract_id is None:
        return None
    try:
        row = indexed.loc[(trade_date, contract_id)]
    except KeyError:
        return None
    if isinstance(row, pd.DataFrame):
        raise RuntimeError("duplicate execution market row")
    return row


def _accounting_point_value(row: pd.Series, signed_move: float, mode: PointMode) -> float:
    if mode == "selected":
        value = row["realized_point_value"]
    elif mode == "adverse":
        value = row["point_value_lower"] if signed_move >= 0.0 else row["point_value_upper"]
    else:
        value = row["point_value_upper"] if signed_move >= 0.0 else row["point_value_lower"]
    return float(value) if _positive(value) else math.nan


def _execution_ready(row: pd.Series | None) -> tuple[bool, str]:
    if row is None:
        return False, "missing_contract_row"
    reasons = []
    if not _positive(row["open"]):
        reasons.append("missing_factual_open")
    if not _positive(row["settle"]):
        reasons.append("missing_factual_settle")
    if not bool(row["sizing_proxy_usable"]):
        if row["lag_gap"] != 1.0:
            reasons.append("nonconsecutive_lagged_contract_session")
        if not _positive(row["lag_point_value"]):
            reasons.append("unknown_lagged_point_value")
        if not _nonnegative(row["lag_volume"]):
            reasons.append("unknown_lagged_volume")
    return not reasons, ",".join(dict.fromkeys(reasons))


def _position_notional(
    position: _Position, row: pd.Series | None, *, prefer_open: bool = True
) -> float:
    if row is None:
        return math.nan
    price = row["open"] if prefer_open and _positive(row["open"]) else row["settle"]
    point_value = (
        row["lag_point_value"] if _positive(row["lag_point_value"]) else row["realized_point_value"]
    )
    if not _positive(price) or not _positive(point_value):
        return math.nan
    return abs(position.quantity) * float(price) * float(point_value)


def _portfolio_notional(
    positions: dict[str, _Position], indexed: pd.DataFrame, trade_date: pd.Timestamp
) -> float:
    values = [
        _position_notional(position, _market_row(indexed, trade_date, position.contract_id))
        for position in positions.values()
        if position.quantity != 0
    ]
    if any(not np.isfinite(value) for value in values):
        return math.nan
    return float(sum(values))


def _performance_metrics(ledger: pd.DataFrame, initial_cash: float) -> dict[str, Any]:
    def calculate(frame: pd.DataFrame) -> dict[str, Any]:
        returns = frame["net_return"].astype(float)
        equity = frame["ending_cash"].astype(float) / initial_cash
        elapsed_years = max(
            (frame["trade_date"].iloc[-1] - frame["trade_date"].iloc[0]).days / 365.25,
            1.0 / 365.25,
        )
        standard_deviation = float(returns.std(ddof=1))
        drawdown = equity / equity.cummax() - 1.0
        return {
            "observations": int(len(frame)),
            "through_date": frame["trade_date"].iloc[-1].date().isoformat(),
            "ending_cash": float(frame["ending_cash"].iloc[-1]),
            "total_return": float(frame["ending_cash"].iloc[-1] / initial_cash - 1.0),
            "cagr": float(
                (frame["ending_cash"].iloc[-1] / initial_cash) ** (1.0 / elapsed_years) - 1.0
            ),
            "sharpe": float(returns.mean() / standard_deviation * np.sqrt(252.0))
            if standard_deviation > 0.0
            else math.nan,
            "annualized_volatility": standard_deviation * np.sqrt(252.0),
            "max_drawdown": float(drawdown.min()),
            "positive_years": int(
                sum(
                    (1.0 + group).prod() - 1.0 > 0.0
                    for _, group in returns.groupby(frame["trade_date"].dt.year)
                )
            ),
        }

    resolved = ledger.loc[ledger["pnl_resolved"] & ledger["ending_cash"].notna()].copy()
    if ledger.empty or not bool(ledger["pnl_resolved"].all()) or ledger["ending_cash"].isna().any():
        result = {
            "metrics_valid": False,
            "observations": int(len(ledger)),
            "unresolved_pnl_sessions": int((~ledger["pnl_resolved"]).sum())
            if not ledger.empty
            else 0,
            "resolved_prefix_only_not_full_period": calculate(resolved)
            if not resolved.empty
            else None,
        }
        if not ledger.empty and (~ledger["pnl_resolved"]).any():
            first = ledger.loc[~ledger["pnl_resolved"]].iloc[0]
            result["first_unresolved_date"] = first["trade_date"].date().isoformat()
            result["first_unresolved_reason"] = str(first["unresolved_reason"])
        return result
    return {"metrics_valid": True, **calculate(ledger)}


def run_execution_proxy(
    market: pd.DataFrame,
    plan: FrozenWeightPlan,
    *,
    initial_cash: float,
    one_way_bps: float,
    execution_lag: int,
    maximum_participation: float,
    point_mode: PointMode = "selected",
    development_start: pd.Timestamp,
    development_end: pd.Timestamp,
) -> ExecutionResult:
    if execution_lag not in {1, 2}:
        raise ValueError("sealed execution lag must be one or two sessions")
    indexed = market.set_index(["trade_date", "contract_id"]).sort_index()
    date_positions = {pd.Timestamp(value): index for index, value in enumerate(plan.dates)}
    simulation_dates = [
        pd.Timestamp(value)
        for value in plan.dates
        if development_start <= pd.Timestamp(value) <= development_end
    ]
    positions: dict[str, _Position] = {}
    pending: dict[str, _PendingTarget] = {}
    cash = float(initial_cash)
    ledger_rows: list[dict[str, Any]] = []
    order_rows: list[dict[str, Any]] = []
    stopped = False

    for trade_date in simulation_dates:
        start_cash = cash
        date_index = date_positions[trade_date]
        if date_index < execution_lag:
            continue
        decision_date = pd.Timestamp(plan.dates[date_index - execution_lag])
        session_gap_pnl = 0.0
        session_intraday_pnl = 0.0
        session_bridge_pnl = 0.0
        session_cost = 0.0
        pnl_resolved = True
        unresolved_reasons: list[str] = []
        bridge_assets: set[str] = set()
        session_rejections = 0
        session_fills = 0
        partial_fills = 0

        for asset, position in sorted(positions.items()):
            row = _market_row(indexed, trade_date, position.contract_id)
            if row is None or not _positive(row["settle"]):
                pnl_resolved = False
                unresolved_reasons.append(
                    f"{asset}:{position.contract_id}:missing_settle_or_contract"
                )
                continue
            if not _positive(row["realized_point_value"]):
                pnl_resolved = False
                unresolved_reasons.append(f"{asset}:missing_realized_point_value")
                continue
            if _positive(row["open"]):
                signed_move = position.quantity * (float(row["open"]) - position.previous_settle)
                point_value = _accounting_point_value(row, signed_move, point_mode)
                if not np.isfinite(point_value):
                    pnl_resolved = False
                    unresolved_reasons.append(f"{asset}:missing_point_value_bound")
                    continue
                session_gap_pnl += signed_move * point_value
            else:
                signed_move = position.quantity * (float(row["settle"]) - position.previous_settle)
                point_value = _accounting_point_value(row, signed_move, point_mode)
                if not np.isfinite(point_value):
                    pnl_resolved = False
                    unresolved_reasons.append(f"{asset}:missing_bridge_point_value")
                    continue
                session_bridge_pnl += signed_move * point_value
                bridge_assets.add(asset)

        if not pnl_resolved:
            ledger_rows.append(
                {
                    "trade_date": trade_date,
                    "decision_date": decision_date,
                    "starting_cash": start_cash,
                    "gap_pnl": math.nan,
                    "intraday_pnl": math.nan,
                    "settle_bridge_pnl": math.nan,
                    "variation_margin": math.nan,
                    "transaction_cost": math.nan,
                    "ending_cash": math.nan,
                    "net_return": math.nan,
                    "gross_notional": math.nan,
                    "gross_multiple": math.nan,
                    "modeled_initial_margin": math.nan,
                    "required_margin_buffer": math.nan,
                    "positions": len(positions),
                    "filled_events": 0,
                    "rejected_events": 0,
                    "partial_fill_events": 0,
                    "settle_bridge_assets": len(bridge_assets),
                    "pnl_resolved": False,
                    "unresolved_reason": ",".join(unresolved_reasons),
                    "canonical_missing_return_flag": trade_date
                    in plan.canonical_missing_return_dates,
                    "canonical_missing_resolution": "unresolved",
                    "post_trade_gross_cap_ok": False,
                }
            )
            stopped = True
            break

        cash += session_gap_pnl + session_bridge_pnl
        proposals: list[dict[str, Any]] = []
        for asset in plan.assets:
            weight = float(plan.weights.loc[decision_date, asset])
            contract_value = plan.active_contracts.loc[decision_date, asset]
            target_contract = (
                None if weight == 0.0 or pd.isna(contract_value) else str(contract_value)
            )
            weight_decision = plan.weight_decision_dates.loc[decision_date]
            key = (
                pd.Timestamp(weight_decision) if pd.notna(weight_decision) else pd.NaT,
                target_contract,
                float(weight),
            )
            previous_pending = pending.get(asset)
            if previous_pending is None or previous_pending.key != key:
                pending[asset] = _PendingTarget(key=key, contract_id=target_contract, quantity=None)
            target = pending[asset]
            current = positions.get(asset)
            if target.quantity is None:
                if target_contract is None or weight == 0.0:
                    target.quantity = 0
                else:
                    target_row = _market_row(indexed, trade_date, target_contract)
                    ready, reason = _execution_ready(target_row)
                    if not ready:
                        session_rejections += 1
                        order_rows.append(
                            {
                                "trade_date": trade_date,
                                "decision_date": decision_date,
                                "asset_code": asset,
                                "leg": "target_initialization",
                                "contract_id": target_contract,
                                "quantity_delta": 0,
                                "factual_open": target_row["open"]
                                if target_row is not None
                                else math.nan,
                                "lag_point_value": target_row["lag_point_value"]
                                if target_row is not None
                                else math.nan,
                                "lag_volume": target_row["lag_volume"]
                                if target_row is not None
                                else math.nan,
                                "participation": math.nan,
                                "traded_notional": 0.0,
                                "cost": 0.0,
                                "filled": False,
                                "reason": reason,
                            }
                        )
                        continue
                    assert target_row is not None
                    one_contract = float(target_row["open"]) * float(target_row["lag_point_value"])
                    target.quantity = math.trunc(weight * initial_cash / one_contract)
            desired_quantity = int(target.quantity)
            current_quantity = current.quantity if current is not None else 0
            current_contract = current.contract_id if current is not None else None
            if current_quantity == desired_quantity and current_contract == target_contract:
                continue
            if asset in bridge_assets and current_quantity != 0:
                session_rejections += 1
                order_rows.append(
                    {
                        "trade_date": trade_date,
                        "decision_date": decision_date,
                        "asset_code": asset,
                        "leg": "carry_rejected",
                        "contract_id": current_contract,
                        "quantity_delta": 0,
                        "factual_open": math.nan,
                        "lag_point_value": math.nan,
                        "lag_volume": math.nan,
                        "participation": math.nan,
                        "traded_notional": 0.0,
                        "cost": 0.0,
                        "filled": False,
                        "reason": "missing_old_factual_open_settle_bridge_used",
                    }
                )
                continue

            before = current
            after: _Position | None
            legs: list[dict[str, Any]] = []
            reason = ""
            if current is None or current_quantity == 0:
                if desired_quantity == 0 or target_contract is None:
                    continue
                row = _market_row(indexed, trade_date, target_contract)
                ready, reason = _execution_ready(row)
                if ready:
                    assert row is not None
                    capacity = int(math.floor(float(row["lag_volume"]) * maximum_participation))
                    filled_quantity = int(np.sign(desired_quantity)) * min(
                        abs(desired_quantity), capacity
                    )
                    if filled_quantity == 0:
                        reason = "zero_capacity_or_integer_target"
                    else:
                        after = _Position(target_contract, filled_quantity, float(row["settle"]))
                        legs.append(
                            {
                                "leg": "entry",
                                "contract_id": target_contract,
                                "quantity_delta": filled_quantity,
                                "row": row,
                            }
                        )
                        partial = abs(filled_quantity) < abs(desired_quantity)
                        proposals.append(
                            {
                                "asset": asset,
                                "before": before,
                                "after": after,
                                "legs": legs,
                                "partial": partial,
                            }
                        )
                        continue
                session_rejections += 1
            elif target_contract is None or desired_quantity == 0:
                row = _market_row(indexed, trade_date, current.contract_id)
                ready, reason = _execution_ready(row)
                if ready:
                    assert row is not None
                    capacity = int(math.floor(float(row["lag_volume"]) * maximum_participation))
                    close_size = min(abs(current.quantity), capacity)
                    if close_size > 0:
                        delta = -int(np.sign(current.quantity)) * close_size
                        remaining = current.quantity + delta
                        after = (
                            None
                            if remaining == 0
                            else _Position(current.contract_id, remaining, current.previous_settle)
                        )
                        legs.append(
                            {
                                "leg": "exit",
                                "contract_id": current.contract_id,
                                "quantity_delta": delta,
                                "row": row,
                            }
                        )
                        proposals.append(
                            {
                                "asset": asset,
                                "before": before,
                                "after": after,
                                "legs": legs,
                                "partial": remaining != 0,
                            }
                        )
                        continue
                    reason = "zero_capacity"
                session_rejections += 1
            elif current.contract_id == target_contract:
                row = _market_row(indexed, trade_date, current.contract_id)
                ready, reason = _execution_ready(row)
                if ready:
                    assert row is not None
                    capacity = int(math.floor(float(row["lag_volume"]) * maximum_participation))
                    requested = desired_quantity - current.quantity
                    delta = int(np.sign(requested)) * min(abs(requested), capacity)
                    if delta != 0:
                        after_quantity = current.quantity + delta
                        after = _Position(
                            current.contract_id, after_quantity, current.previous_settle
                        )
                        legs.append(
                            {
                                "leg": "rebalance",
                                "contract_id": current.contract_id,
                                "quantity_delta": delta,
                                "row": row,
                            }
                        )
                        proposals.append(
                            {
                                "asset": asset,
                                "before": before,
                                "after": after,
                                "legs": legs,
                                "partial": abs(delta) < abs(requested),
                            }
                        )
                        continue
                    reason = "zero_capacity"
                session_rejections += 1
            else:
                old_row = _market_row(indexed, trade_date, current.contract_id)
                new_row = _market_row(indexed, trade_date, target_contract)
                old_ready, old_reason = _execution_ready(old_row)
                new_ready, new_reason = _execution_ready(new_row)
                reason = ",".join(value for value in (old_reason, new_reason) if value)
                if old_ready and new_ready:
                    assert old_row is not None and new_row is not None
                    old_capacity = int(
                        math.floor(float(old_row["lag_volume"]) * maximum_participation)
                    )
                    new_capacity = int(
                        math.floor(float(new_row["lag_volume"]) * maximum_participation)
                    )
                    new_quantity = int(np.sign(desired_quantity)) * min(
                        abs(desired_quantity), new_capacity
                    )
                    if old_capacity >= abs(current.quantity) and new_quantity != 0:
                        after = _Position(target_contract, new_quantity, float(new_row["settle"]))
                        legs.extend(
                            [
                                {
                                    "leg": "roll_exit",
                                    "contract_id": current.contract_id,
                                    "quantity_delta": -current.quantity,
                                    "row": old_row,
                                },
                                {
                                    "leg": "roll_entry",
                                    "contract_id": target_contract,
                                    "quantity_delta": new_quantity,
                                    "row": new_row,
                                },
                            ]
                        )
                        proposals.append(
                            {
                                "asset": asset,
                                "before": before,
                                "after": after,
                                "legs": legs,
                                "partial": abs(new_quantity) < abs(desired_quantity),
                            }
                        )
                        continue
                    reason = "atomic_roll_capacity"
                session_rejections += 1

            order_rows.append(
                {
                    "trade_date": trade_date,
                    "decision_date": decision_date,
                    "asset_code": asset,
                    "leg": "rejected",
                    "contract_id": target_contract or current_contract,
                    "quantity_delta": 0,
                    "factual_open": math.nan,
                    "lag_point_value": math.nan,
                    "lag_volume": math.nan,
                    "participation": math.nan,
                    "traded_notional": 0.0,
                    "cost": 0.0,
                    "filled": False,
                    "reason": reason or "unresolved_order",
                }
            )

        for proposal in proposals:
            before = proposal["before"]
            after = proposal["after"]
            before_notional = (
                0.0
                if before is None
                else _position_notional(
                    before, _market_row(indexed, trade_date, before.contract_id)
                )
            )
            after_notional = (
                0.0
                if after is None
                else _position_notional(after, _market_row(indexed, trade_date, after.contract_id))
            )
            proposal["risk_increasing"] = not (
                np.isfinite(before_notional)
                and np.isfinite(after_notional)
                and after_notional <= before_notional + 1e-9
            )
        proposals.sort(key=lambda item: (bool(item["risk_increasing"]), str(item["asset"])))
        for proposal in proposals:
            asset = str(proposal["asset"])
            tentative = positions.copy()
            if proposal["after"] is None:
                tentative.pop(asset, None)
            else:
                tentative[asset] = proposal["after"]
            projected_gross = _portfolio_notional(tentative, indexed, trade_date)
            if bool(proposal["risk_increasing"]) and (
                not np.isfinite(projected_gross) or projected_gross > initial_cash + 1e-6
            ):
                session_rejections += 1
                for leg in proposal["legs"]:
                    row = leg["row"]
                    order_rows.append(
                        {
                            "trade_date": trade_date,
                            "decision_date": decision_date,
                            "asset_code": asset,
                            "leg": leg["leg"],
                            "contract_id": leg["contract_id"],
                            "quantity_delta": leg["quantity_delta"],
                            "factual_open": row["open"],
                            "lag_point_value": row["lag_point_value"],
                            "lag_volume": row["lag_volume"],
                            "participation": abs(leg["quantity_delta"]) / float(row["lag_volume"]),
                            "traded_notional": 0.0,
                            "cost": 0.0,
                            "filled": False,
                            "reason": "portfolio_gross_cap",
                        }
                    )
                continue
            positions = tentative
            session_fills += 1
            partial_fills += int(bool(proposal["partial"]))
            for leg in proposal["legs"]:
                row = leg["row"]
                traded_notional = (
                    abs(int(leg["quantity_delta"]))
                    * float(row["open"])
                    * float(row["lag_point_value"])
                )
                cost = traded_notional * one_way_bps / 10_000.0
                session_cost += cost
                order_rows.append(
                    {
                        "trade_date": trade_date,
                        "decision_date": decision_date,
                        "asset_code": asset,
                        "leg": leg["leg"],
                        "contract_id": leg["contract_id"],
                        "quantity_delta": int(leg["quantity_delta"]),
                        "factual_open": float(row["open"]),
                        "lag_point_value": float(row["lag_point_value"]),
                        "lag_volume": float(row["lag_volume"]),
                        "participation": abs(int(leg["quantity_delta"])) / float(row["lag_volume"]),
                        "traded_notional": traded_notional,
                        "cost": cost,
                        "filled": True,
                        "reason": "partial_capacity" if proposal["partial"] else "filled",
                    }
                )

        for asset, position in sorted(positions.items()):
            if asset in bridge_assets:
                row = _market_row(indexed, trade_date, position.contract_id)
                if row is not None and _positive(row["settle"]):
                    position.previous_settle = float(row["settle"])
                continue
            row = _market_row(indexed, trade_date, position.contract_id)
            if row is None or not _positive(row["open"]) or not _positive(row["settle"]):
                pnl_resolved = False
                unresolved_reasons.append(f"{asset}:post_trade_mark_missing")
                continue
            signed_move = position.quantity * (float(row["settle"]) - float(row["open"]))
            point_value = _accounting_point_value(row, signed_move, point_mode)
            if not np.isfinite(point_value):
                pnl_resolved = False
                unresolved_reasons.append(f"{asset}:post_trade_point_value_missing")
                continue
            session_intraday_pnl += signed_move * point_value
            position.previous_settle = float(row["settle"])
        if not pnl_resolved:
            cash = math.nan
        else:
            cash += session_intraday_pnl - session_cost
        gross_notional = _portfolio_notional(positions, indexed, trade_date)
        gross_multiple = (
            gross_notional / cash if np.isfinite(gross_notional) and cash > 0 else math.nan
        )
        canonical_missing = trade_date in plan.canonical_missing_return_dates
        if canonical_missing:
            if bridge_assets:
                missing_resolution = "factual_settlement_bridge"
            elif positions:
                missing_resolution = "factual_contract_open_and_settlement"
            else:
                missing_resolution = "no_integer_position"
        else:
            missing_resolution = "not_applicable"
        ledger_rows.append(
            {
                "trade_date": trade_date,
                "decision_date": decision_date,
                "starting_cash": start_cash,
                "gap_pnl": session_gap_pnl,
                "intraday_pnl": session_intraday_pnl,
                "settle_bridge_pnl": session_bridge_pnl,
                "variation_margin": session_gap_pnl + session_intraday_pnl + session_bridge_pnl,
                "transaction_cost": session_cost,
                "ending_cash": cash,
                "net_return": cash / start_cash - 1.0 if np.isfinite(cash) else math.nan,
                "gross_notional": gross_notional,
                "gross_multiple": gross_multiple,
                "modeled_initial_margin": gross_notional * 0.25
                if np.isfinite(gross_notional)
                else math.nan,
                "required_margin_buffer": gross_notional * 0.5
                if np.isfinite(gross_notional)
                else math.nan,
                "positions": len(positions),
                "filled_events": session_fills,
                "rejected_events": session_rejections,
                "partial_fill_events": partial_fills,
                "settle_bridge_assets": len(bridge_assets),
                "pnl_resolved": pnl_resolved,
                "unresolved_reason": ",".join(unresolved_reasons),
                "canonical_missing_return_flag": canonical_missing,
                "canonical_missing_resolution": missing_resolution,
                "post_trade_gross_cap_ok": bool(
                    np.isfinite(gross_notional) and gross_notional <= initial_cash + 1e-6
                ),
            }
        )
        if not pnl_resolved:
            stopped = True
            break

    ledger = pd.DataFrame(ledger_rows)
    orders = pd.DataFrame(order_rows)
    metrics = _performance_metrics(ledger, initial_cash)
    metrics.update(
        {
            "stopped_on_unresolved_pnl": stopped,
            "simulated_sessions": int(len(ledger)),
            "required_sessions": int(len(simulation_dates)),
            "filled_events": int(ledger["filled_events"].sum()) if not ledger.empty else 0,
            "rejected_events": int(ledger["rejected_events"].sum()) if not ledger.empty else 0,
            "partial_fill_events": int(ledger["partial_fill_events"].sum())
            if not ledger.empty
            else 0,
            "settle_bridge_asset_sessions": int(ledger["settle_bridge_assets"].sum())
            if not ledger.empty
            else 0,
            "settle_bridge_sessions": int(ledger["settle_bridge_assets"].gt(0).sum())
            if not ledger.empty
            else 0,
            "canonical_missing_return_sessions": int(ledger["canonical_missing_return_flag"].sum())
            if not ledger.empty
            else 0,
            "canonical_missing_unresolved_sessions": int(
                (
                    ledger["canonical_missing_return_flag"]
                    & ledger["canonical_missing_resolution"].eq("unresolved")
                ).sum()
            )
            if not ledger.empty
            else 0,
            "total_transaction_cost": float(ledger["transaction_cost"].sum())
            if not ledger.empty
            else 0.0,
            "maximum_gross_multiple": float(ledger["gross_multiple"].max())
            if not ledger.empty
            else math.nan,
            "post_trade_gross_cap_breach_sessions": int(
                (ledger["pnl_resolved"] & ~ledger["post_trade_gross_cap_ok"]).sum()
            )
            if not ledger.empty
            else 0,
            "research_only": True,
            "broker_exact": False,
            "historical_exchange_exact": False,
        }
    )
    return ExecutionResult(ledger=ledger, orders=orders, metrics=metrics)


def run_execution_study(config_path: Path, output_root: Path) -> Path:
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    project_root = Path.cwd().resolve()
    run_dir = (project_root / protocol["canonical"]["run"]).resolve()
    canonical_results = json.loads((run_dir / "results.json").read_text(encoding="utf-8-sig"))
    canonical_identity = canonical_results["identity"]
    checks = {
        "protocol_seal": sha256_file(config_path)
        == (project_root / "configs/futures_v9_structural_execution.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0],
        "canonical_config": canonical_identity["config_sha256"]
        == protocol["canonical"]["config_sha256"],
        "canonical_source": canonical_identity["source_manifest_sha256"]
        == protocol["canonical"]["source_manifest_sha256"],
        "canonical_history": canonical_identity["history_sha256"]
        == protocol["canonical"]["history_sha256"],
        "canonical_panel": sha256_file(run_dir / canonical_results["panel"]["path"])
        == protocol["canonical"]["panel_sha256"],
    }
    archive_path = (project_root / protocol["canonical"]["raw_source_archive"]["path"]).resolve()
    checks["raw_source_archive"] = (
        sha256_file(archive_path) == protocol["canonical"]["raw_source_archive"]["sha256"]
    )
    if not all(checks.values()):
        raise ValueError(f"execution input identity mismatch: {checks}")
    panel = pd.read_parquet(run_dir / canonical_results["panel"]["path"])
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="raise")
    forbidden = pd.Timestamp(protocol["dates"]["forbidden_from"])
    if panel["trade_date"].ge(forbidden).any():
        raise ValueError("canonical panel contains protected 2026+")
    structural_config = yaml.safe_load(
        (project_root / "configs/futures_v9_structural.yaml").read_text(encoding="utf-8-sig")
    )
    market = load_official_execution_market(archive_path, forbidden_from=forbidden)
    if market["trade_date"].ge(forbidden).any():
        raise ValueError("execution market contains protected 2026+")
    identity = {
        "protocol_sha256": sha256_file(config_path),
        "canonical_results_sha256": sha256_file(run_dir / "results.json"),
        "panel_sha256": sha256_file(run_dir / canonical_results["panel"]["path"]),
        "raw_source_archive_sha256": sha256_file(archive_path),
        "implementation_sha256": sha256_file(Path(__file__)),
    }
    run_id = hashlib.sha256(_canonical_json(identity)).hexdigest()[:16]
    output = output_root / f"execution_{run_id}"
    output.mkdir(parents=True, exist_ok=True)
    market_path = output / "execution_market_proxy.parquet"
    _atomic_parquet(market_path, market)
    artifacts: dict[str, Any] = {
        market_path.name: {
            "sha256": sha256_file(market_path),
            "rows": len(market),
        }
    }
    scenarios = {
        "ordinary": {"bps": 5.0, "lag": 1, "point_mode": "selected"},
        "doubled": {"bps": 10.0, "lag": 1, "point_mode": "selected"},
        "stress_20bps": {"bps": 20.0, "lag": 1, "point_mode": "selected"},
        "delayed_ordinary": {"bps": 5.0, "lag": 2, "point_mode": "selected"},
        "proxy_adverse_stress": {"bps": 20.0, "lag": 1, "point_mode": "adverse"},
        "proxy_favorable_ordinary": {"bps": 5.0, "lag": 1, "point_mode": "favorable"},
    }
    results: dict[str, Any] = {}
    coverage_records: list[dict[str, Any]] = []
    canonical_missing_audit_records: list[dict[str, Any]] = []
    initial_cash = float(protocol["capital_and_sizing"]["initial_cash_rub"])
    development_start = pd.Timestamp(protocol["dates"]["development_start"])
    development_end = pd.Timestamp(protocol["dates"]["development_end"])
    for strategy in protocol["canonical"]["selected_strategies"]:
        plan = build_frozen_weight_plan(panel, structural_config, str(strategy))
        if len(plan.canonical_missing_return_dates) != int(
            protocol["accounting"]["expected_canonical_missing_return_sessions"]
        ):
            raise ValueError("canonical missing-return audit count changed")
        stored = pd.read_parquet(
            run_dir / canonical_results["ledgers"][strategy]["path"]
        ).set_index("trade_date")
        stored.index = pd.to_datetime(stored.index)
        replay_gross = plan.weights.shift(1).abs().sum(axis=1).reindex(stored.index)
        gross_replay_error = float((replay_gross - stored["gross_exposure"]).abs().max())
        if gross_replay_error > 1e-12:
            raise ValueError(f"frozen target replay mismatch for {strategy}")
        strategy_results: dict[str, Any] = {
            "fractional_weight_gross_replay_max_error": gross_replay_error,
            "canonical_missing_return_dates": [
                value.date().isoformat() for value in sorted(plan.canonical_missing_return_dates)
            ],
            "scenarios": {},
        }
        for scenario, settings in scenarios.items():
            execution = run_execution_proxy(
                market,
                plan,
                initial_cash=initial_cash,
                one_way_bps=float(settings["bps"]),
                execution_lag=int(settings["lag"]),
                maximum_participation=float(protocol["liquidity"]["maximum_participation"]),
                point_mode=str(settings["point_mode"]),
                development_start=development_start,
                development_end=development_end,
            )
            ledger_path = output / f"ledger_{strategy}_{scenario}.parquet"
            orders_path = output / f"orders_{strategy}_{scenario}.parquet"
            _atomic_parquet(ledger_path, execution.ledger)
            _atomic_parquet(orders_path, execution.orders)
            artifacts[ledger_path.name] = {
                "sha256": sha256_file(ledger_path),
                "rows": len(execution.ledger),
            }
            artifacts[orders_path.name] = {
                "sha256": sha256_file(orders_path),
                "rows": len(execution.orders),
            }
            strategy_results["scenarios"][scenario] = {
                "settings": settings,
                "metrics": {
                    **execution.metrics,
                    "order_reason_counts": {
                        str(reason): int(count)
                        for reason, count in execution.orders["reason"].value_counts().items()
                    }
                    if not execution.orders.empty
                    else {},
                },
                "ledger": ledger_path.name,
                "orders": orders_path.name,
            }
            for missing_date in sorted(plan.canonical_missing_return_dates):
                observed = execution.ledger.loc[execution.ledger["trade_date"].eq(missing_date)]
                if observed.empty:
                    resolution = "not_reached_due_earlier_unresolved_execution_path"
                    pnl_resolved = False
                else:
                    row = observed.iloc[0]
                    resolution = str(row["canonical_missing_resolution"])
                    pnl_resolved = bool(row["pnl_resolved"])
                canonical_missing_audit_records.append(
                    {
                        "strategy": strategy,
                        "scenario": scenario,
                        "trade_date": missing_date,
                        "pnl_resolved": pnl_resolved,
                        "resolution": resolution,
                        "zero_imputed": False,
                    }
                )
            coverage_records.append(
                {
                    "strategy": strategy,
                    "scenario": scenario,
                    **{
                        key: value
                        for key, value in execution.metrics.items()
                        if not isinstance(value, dict)
                    },
                }
            )
        required = ["ordinary", "doubled", "stress_20bps", "delayed_ordinary"]
        strategy_results["promotion_positive_all_required"] = all(
            strategy_results["scenarios"][scenario]["metrics"].get("metrics_valid", False)
            and strategy_results["scenarios"][scenario]["metrics"].get("cagr", -math.inf) > 0.0
            for scenario in required
        )
        strategy_results["full_period_positive_result_proven"] = bool(
            strategy_results["promotion_positive_all_required"]
        )
        results[str(strategy)] = strategy_results
    coverage = pd.DataFrame(coverage_records)
    coverage_path = output / "coverage_and_metrics.csv"
    coverage.to_csv(coverage_path, index=False, encoding="utf-8-sig", float_format="%.12g")
    artifacts[coverage_path.name] = {
        "sha256": sha256_file(coverage_path),
        "rows": len(coverage),
    }
    canonical_missing_audit = pd.DataFrame(canonical_missing_audit_records)
    canonical_missing_audit_path = output / "canonical_missing_return_audit.csv"
    canonical_missing_audit.to_csv(
        canonical_missing_audit_path,
        index=False,
        encoding="utf-8-sig",
    )
    artifacts[canonical_missing_audit_path.name] = {
        "sha256": sha256_file(canonical_missing_audit_path),
        "rows": len(canonical_missing_audit),
    }
    market_development = market.loc[
        market["trade_date"].between(development_start, development_end)
    ]
    result = {
        "research_only": True,
        "broker_exact": False,
        "historical_exchange_exact": False,
        "verdict_scope": "exact-execution proxy falsification, never live promotion",
        "identity": identity,
        "checks": checks,
        "input": {
            "minimum_date": str(market["trade_date"].min()),
            "maximum_date": str(market["trade_date"].max()),
            "rows": len(market),
            "assets": int(market["asset_code"].nunique()),
            "contracts": int(market["contract_id"].nunique()),
            "development_open_coverage": float(market_development["open"].gt(0.0).mean()),
            "development_realized_point_value_coverage": float(
                market_development["realized_point_value"].gt(0.0).mean()
            ),
            "development_sizing_proxy_coverage": float(
                market_development["sizing_proxy_usable"].mean()
            ),
            "contains_2026_or_later": False,
        },
        "fundamental_blockers": [
            (
                "Historical exchange/broker contract specifications, fee schedules and initial "
                "margin are not present for the 21 effective roots."
            ),
            (
                "The lagged VALUE/WAPRICE or OI formula is a factual research point-value proxy, "
                "not a historical contract specification."
            ),
            (
                "Only BR/MIX/RTS/Si have the pre-existing frozen tick/fee registry; applying it "
                "cross-sectionally would fabricate the remaining roots."
            ),
            (
                "The 5/10/20 bps costs and 25% IM with 2x buffer are scenario assumptions, not "
                "broker-exact observations."
            ),
            (
                "Official daily OPEN is a session aggregate and cannot prove queue priority, "
                "bid-ask spread, partial fill timing, or intraday tradability."
            ),
        ],
        "results": results,
        "promotion_go": all(value["promotion_positive_all_required"] for value in results.values()),
        "execution_verdict": "GO"
        if all(value["promotion_positive_all_required"] for value in results.values())
        else "NO_GO",
        "full_period_positive_result_proven_for": [
            strategy
            for strategy, value in results.items()
            if value["full_period_positive_result_proven"]
        ],
        "canonical_missing_return_zero_imputations": int(
            canonical_missing_audit["zero_imputed"].sum()
        ),
        "artifacts": artifacts,
    }
    result_path = output / "results.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    identity_path = output / "run_identity.json"
    identity_path.write_text(
        json.dumps(
            {**identity, "results_sha256": sha256_file(result_path)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output
