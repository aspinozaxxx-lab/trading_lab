"""Sealed V12 core-four correlation-aware trend development experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures.execution_dataset import (
    build_portfolio_market,
    map_decision_weights_to_next_open,
)
from market_lab.futures.portfolio_construction import build_causal_portfolio_targets
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    FuturesPortfolioLedgerResult,
    run_futures_portfolio_ledger,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v12_core4_correlation_trend.yaml"
CONFIG_SHA256: Final[str] = (
    "0b1a79d5c09cf40330886ebfba84bb9a7a8a84973301d59627200050e61b3e53"
)
ASSETS: Final[tuple[str, ...]] = ("SI", "RI", "BR", "MIX")
ASSET_ALIASES: Final[dict[str, str]] = {
    "SI": "SI",
    "RI": "RI",
    "RTS": "RI",
    "BR": "BR",
    "MIX": "MIX",
}
MOMENTUM_HORIZONS: Final[tuple[int, ...]] = (21, 63, 126, 252)
VOLATILITY_LOOKBACK: Final[int] = 60
ANNUALIZATION: Final[int] = 252
VOLATILITY_FLOOR: Final[float] = 0.05
OOS_START: Final[pd.Timestamp] = pd.Timestamp("2021-01-01")
OOS_END: Final[pd.Timestamp] = pd.Timestamp("2025-12-31")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
MAXIMUM_PARTICIPATION: Final[float] = 0.01
INITIAL_CASH: Final[float] = 1_000_000.0


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for one immutable input or artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the byte seal and all economics that must not drift after OOS."""
    config_path = config_path.resolve()
    if config_path != CONFIG_PATH.resolve() or sha256_file(config_path) != CONFIG_SHA256:
        raise ValueError("sealed V12 protocol byte drift")
    sidecar = config_path.with_suffix(".sha256")
    stated = sidecar.read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V12 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V12 protocol must be a mapping")
    signal = protocol["signal"]
    portfolio = protocol["portfolio"]
    execution = protocol["execution"]
    if (
        protocol.get("protocol_id") != "futures_v12_core4_correlation_trend_v1"
        or protocol.get("status") != "predeclared_before_v12_oos_outcomes"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or tuple(protocol["universe"]["exact_order"]) != ASSETS
        or tuple(int(value) for value in signal["log_momentum_horizons_sessions"])
        != MOMENTUM_HORIZONS
        or int(signal["volatility_lookback_sessions"]) != VOLATILITY_LOOKBACK
        or int(signal["annualization_sessions"]) != ANNUALIZATION
        or float(signal["volatility_floor_annualized"]) != VOLATILITY_FLOOR
        or int(portfolio["ewma_volatility_span_sessions"]) != 20
        or int(portfolio["covariance_lookback_sessions"]) != 60
        or float(portfolio["annual_target_volatility"]) != 0.20
        or float(portfolio["gross_cap"]) != 1.0
        or int(portfolio["turnover_sleeves"]) != 5
        or float(execution["maximum_participation"]) != MAXIMUM_PARTICIPATION
        or float(execution["initial_cash_rub"]) != INITIAL_CASH
        or execution["execution_atomicity"] != "asset"
    ):
        raise ValueError("sealed V12 protocol invariants were weakened")
    return protocol


def _resolved_input(relative_value: str) -> Path:
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError(f"unsafe V12 input path: {relative_value}")
    if relative.parts[0].lower() != "data":
        raise ValueError(f"V12 input is outside the external data alias: {relative_value}")
    data_root = (PROJECT_ROOT / "data").resolve()
    resolved = (PROJECT_ROOT / relative).resolve()
    if not resolved.is_relative_to(data_root):
        raise ValueError(f"V12 input escapes the external data root: {relative_value}")
    return resolved


@dataclass(frozen=True, slots=True)
class VerifiedInputs:
    paths: dict[str, Path]
    checks: dict[str, bool]
    metadata: dict[str, dict[str, Any]]


def verify_inputs(protocol: dict[str, Any]) -> VerifiedInputs:
    """Verify hashes, sizes, schemas and date-only boundaries before price columns load."""
    paths: dict[str, Path] = {}
    checks: dict[str, bool] = {"protocol_seal": sha256_file(CONFIG_PATH) == CONFIG_SHA256}
    metadata: dict[str, dict[str, Any]] = {}
    for name, declaration in protocol["inputs"].items():
        path = _resolved_input(str(declaration["path"]))
        paths[str(name)] = path
        exists = path.is_file()
        checks[f"{name}_exists"] = exists
        checks[f"{name}_bytes"] = exists and path.stat().st_size == int(declaration["bytes"])
        checks[f"{name}_sha256"] = exists and sha256_file(path) == declaration["sha256"]
        item: dict[str, Any] = {
            "path": declaration["path"],
            "bytes": path.stat().st_size if exists else None,
            "sha256": sha256_file(path) if exists else None,
        }
        if path.suffix.lower() == ".parquet" and exists:
            parquet = pq.ParquetFile(path)
            item["rows"] = parquet.metadata.num_rows
            item["columns"] = parquet.schema_arrow.names
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
            allowed = set(declaration["allowed_columns"])
            checks[f"{name}_schema"] = allowed <= set(parquet.schema_arrow.names)
        metadata[str(name)] = item
    if not all(checks.values()):
        raise ValueError(f"V12 input identity preflight failed: {checks}")

    date_specs = {
        "panel": ("trade_date", "minimum_timestamp", "maximum_timestamp"),
        "contract_observations": (
            "trade_date",
            "minimum_timestamp",
            "maximum_timestamp",
        ),
        "spec_proxy": ("session_date", "minimum_timestamp", "maximum_timestamp"),
    }
    for name, (column, minimum_key, maximum_key) in date_specs.items():
        dates = pd.to_datetime(
            pd.read_parquet(paths[name], columns=[column])[column], errors="raise"
        )
        declaration = protocol["inputs"][name]
        checks[f"{name}_date_min"] = dates.min() == pd.Timestamp(declaration[minimum_key])
        checks[f"{name}_date_max"] = dates.max() == pd.Timestamp(declaration[maximum_key])
        checks[f"{name}_protected"] = bool(dates.lt(PROTECTED_FROM).all())
        metadata[name]["minimum_timestamp"] = dates.min().date().isoformat()
        metadata[name]["maximum_timestamp"] = dates.max().date().isoformat()
    active = pd.read_parquet(
        paths["active_contract_map"], columns=["decision_date", "effective_date"]
    )
    decision = pd.to_datetime(active["decision_date"], errors="raise")
    effective = pd.to_datetime(active["effective_date"], errors="raise")
    declaration = protocol["inputs"]["active_contract_map"]
    checks["active_decision_max"] = decision.max() == pd.Timestamp(
        declaration["decision_maximum_timestamp"]
    )
    checks["active_effective_max"] = effective.max() == pd.Timestamp(
        declaration["effective_maximum_timestamp"]
    )
    initial_sentinel = decision.isna()
    checks["active_initial_decision_sentinel"] = bool(
        int(initial_sentinel.sum()) == len(ASSETS)
        and effective.loc[initial_sentinel].eq(effective.min()).all()
    )
    checks["active_protected"] = bool(
        decision.dropna().lt(PROTECTED_FROM).all() and effective.lt(PROTECTED_FROM).all()
    )
    metadata["active_contract_map"].update(
        {
            "decision_minimum_timestamp": decision.min().date().isoformat(),
            "decision_maximum_timestamp": decision.max().date().isoformat(),
            "effective_maximum_timestamp": effective.max().date().isoformat(),
            "initial_null_decision_rows": int(initial_sentinel.sum()),
        }
    )
    if not all(checks.values()):
        raise ValueError(f"V12 temporal preflight failed: {checks}")
    return VerifiedInputs(paths=paths, checks=checks, metadata=metadata)


def _asset_code(value: object) -> str:
    normalized = str(value).strip().upper()
    if normalized not in ASSET_ALIASES:
        raise ValueError(f"unexpected V12 asset: {value!r}")
    return ASSET_ALIASES[normalized]


def normalize_signal_panel(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep only the sealed price information set and preserve missing observations."""
    required = {"trade_date", "asset_code", "close"}
    if missing := required - set(frame.columns):
        raise ValueError(f"V12 signal panel lacks columns: {sorted(missing)}")
    panel = frame.loc[:, ["trade_date", "asset_code", "close"]].copy()
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="raise").dt.normalize()
    if panel["trade_date"].ge(PROTECTED_FROM).any():
        raise ValueError("V12 signal panel touches protected 2026+")
    panel["asset"] = panel["asset_code"].map(_asset_code)
    panel["close"] = pd.to_numeric(panel["close"], errors="coerce")
    valid = panel["close"].notna() & np.isfinite(panel["close"]) & panel["close"].gt(0.0)
    panel.loc[~valid, "close"] = np.nan
    if panel.duplicated(["trade_date", "asset"]).any():
        raise ValueError("V12 signal panel has duplicate date/asset rows")
    observed_assets = set(panel["asset"])
    if observed_assets != set(ASSETS):
        raise ValueError(f"V12 signal universe drift: {sorted(observed_assets)}")
    return panel.loc[:, ["trade_date", "asset", "close"]].sort_values(
        ["trade_date", "asset"], kind="mergesort", ignore_index=True
    )


def build_trend_scores(panel: pd.DataFrame) -> pd.DataFrame:
    """Build the predeclared four-horizon score from completed data through date D."""
    normalized = normalize_signal_panel(panel)
    closes = normalized.pivot(index="trade_date", columns="asset", values="close").reindex(
        columns=ASSETS
    )
    log_close = np.log(closes)
    log_return = log_close.diff()
    annualized_volatility = (
        log_return.rolling(VOLATILITY_LOOKBACK, min_periods=VOLATILITY_LOOKBACK).std(ddof=1)
        * np.sqrt(float(ANNUALIZATION))
    )
    daily_volatility = annualized_volatility.clip(lower=VOLATILITY_FLOOR) / np.sqrt(
        float(ANNUALIZATION)
    )
    horizon_scores: dict[int, pd.DataFrame] = {}
    for horizon in MOMENTUM_HORIZONS:
        momentum = log_return.rolling(horizon, min_periods=horizon).sum()
        scaled = momentum / (daily_volatility * np.sqrt(float(horizon)))
        horizon_scores[horizon] = scaled.clip(-2.0, 2.0) / 2.0
    stacked = np.stack(
        [horizon_scores[horizon].to_numpy(dtype=float) for horizon in MOMENTUM_HORIZONS],
        axis=0,
    )
    complete = np.isfinite(stacked).all(axis=0)
    score_values = np.where(complete, stacked.mean(axis=0), np.nan)
    score = pd.DataFrame(score_values, index=closes.index, columns=closes.columns)
    rows: list[pd.DataFrame] = []
    for horizon in MOMENTUM_HORIZONS:
        rows.append(
            horizon_scores[horizon]
            .stack(future_stack=True)
            .rename(f"score_{horizon}")
            .to_frame()
        )
    output = pd.concat(rows, axis=1)
    output["candidate_score"] = score.stack(future_stack=True)
    output = output.reset_index().rename(columns={"trade_date": "decision_date"})
    return output.sort_values(
        ["decision_date", "asset"], kind="mergesort", ignore_index=True
    )


def weekly_score_snapshots(scores: pd.DataFrame) -> pd.DataFrame:
    """Select the last factual score date in each W-SUN week without outcome access."""
    required = {"decision_date", "asset", "candidate_score"}
    if missing := required - set(scores.columns):
        raise ValueError(f"V12 score frame lacks columns: {sorted(missing)}")
    frame = scores.copy()
    frame["decision_date"] = pd.to_datetime(frame["decision_date"], errors="raise").dt.normalize()
    dates = pd.DatetimeIndex(frame["decision_date"].drop_duplicates().sort_values())
    weekly_dates = (
        pd.Series(dates, index=dates).groupby(dates.to_period("W-SUN")).max().to_numpy()
    )
    selected = frame.loc[frame["decision_date"].isin(weekly_dates)].copy()
    if selected.groupby("decision_date")["asset"].nunique().ne(len(ASSETS)).any():
        raise ValueError("V12 weekly score snapshot is incomplete")
    return selected.sort_values(
        ["decision_date", "asset"], kind="mergesort", ignore_index=True
    )


def build_weekly_weights(panel: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    """Apply the frozen covariance-aware 20% risk constructor to weekly trend scores."""
    normalized = normalize_signal_panel(panel)
    market = normalized.rename(
        columns={"trade_date": "session_date", "close": "adjusted_close"}
    )
    weekly = weekly_score_snapshots(scores)
    weights = build_causal_portfolio_targets(
        market,
        weekly.loc[:, ["decision_date", "asset", "candidate_score"]],
    )
    if weights.empty:
        raise ValueError("V12 portfolio constructor returned no weekly weights")
    if weights.groupby("decision_date")["asset"].nunique().ne(len(ASSETS)).any():
        raise ValueError("V12 portfolio constructor returned incomplete snapshots")
    if weights.groupby("decision_date")["target_weight"].apply(lambda x: x.abs().sum()).gt(
        1.0 + 1e-12
    ).any():
        raise ValueError("V12 weekly weights exceed the sealed gross cap")
    return weights.sort_values(
        ["decision_date", "asset"], kind="mergesort", ignore_index=True
    )


def normalize_active_map(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "decision_date",
        "effective_date",
        "observed_through",
        "asset_code",
        "contract_id",
        "plan_tradable",
        "roll",
    }
    if missing := required - set(frame.columns):
        raise ValueError(f"V12 active map lacks columns: {sorted(missing)}")
    active = frame.loc[:, sorted(required)].copy()
    for column in ("decision_date", "effective_date", "observed_through"):
        active[column] = pd.to_datetime(active[column], errors="raise").dt.normalize()
    active["asset"] = active["asset_code"].map(_asset_code)
    active["contract_id"] = active["contract_id"].astype("string")
    active["tradable"] = active["plan_tradable"].fillna(False).astype(bool)
    active["roll"] = active["roll"].fillna(False).astype(bool)
    active = active.loc[active["decision_date"].lt(active["effective_date"])].copy()
    if active["effective_date"].ge(PROTECTED_FROM).any():
        raise ValueError("V12 active map touches protected 2026+")
    if active["observed_through"].gt(active["decision_date"]).any():
        raise ValueError("V12 active map is not point-in-time")
    if active.duplicated(["decision_date", "asset"]).any():
        raise ValueError("V12 active map has duplicate decision/asset rows")
    counts = active.groupby("decision_date")["asset"].nunique()
    if counts.ne(len(ASSETS)).any():
        raise ValueError("V12 active map does not contain complete four-asset snapshots")
    return active.sort_values(
        ["decision_date", "asset"], kind="mergesort", ignore_index=True
    )


@dataclass(frozen=True, slots=True)
class TargetBuild:
    targets: pd.DataFrame
    decision_audit: pd.DataFrame
    weekly_decisions: int
    roll_decisions: int


def build_execution_targets(
    weekly_weights: pd.DataFrame,
    active_map: pd.DataFrame,
    *,
    oos_start: pd.Timestamp = OOS_START,
    oos_end: pd.Timestamp = OOS_END,
) -> TargetBuild:
    """Map weekly weights plus causal roll events to exact next factual opens."""
    active = normalize_active_map(active_map)
    weights = weekly_weights.copy()
    weights["decision_date"] = pd.to_datetime(
        weights["decision_date"], errors="raise"
    ).dt.normalize()
    weights["asset"] = weights["asset"].map(_asset_code)
    if weights.duplicated(["decision_date", "asset"]).any():
        raise ValueError("V12 weekly weights have duplicate keys")
    weight_matrix = weights.pivot(
        index="decision_date", columns="asset", values="target_weight"
    ).reindex(columns=ASSETS)
    active_dates = pd.DatetimeIndex(active["decision_date"].drop_duplicates().sort_values())
    union = weight_matrix.index.union(active_dates).sort_values()
    carried = weight_matrix.reindex(union).ffill().reindex(active_dates).fillna(0.0)

    contracts = active.pivot(index="decision_date", columns="asset", values="contract_id").reindex(
        index=active_dates, columns=ASSETS
    )
    declared_roll = active.pivot(index="decision_date", columns="asset", values="roll").reindex(
        index=active_dates, columns=ASSETS, fill_value=False
    )
    changed = contracts.ne(contracts.shift(1)) & contracts.notna() & contracts.shift(1).notna()
    roll_assets = declared_roll.astype(bool) | changed
    roll_needed = (roll_assets & carried.abs().gt(1e-12)).any(axis=1)
    weekly_event = pd.Series(active_dates.isin(weight_matrix.index), index=active_dates)
    selected_dates = active_dates[weekly_event | roll_needed]

    event_weights = (
        carried.reindex(selected_dates)
        .stack(future_stack=True)
        .rename("target_weight")
        .reset_index()
    )
    weight_provenance = weights.loc[:, ["decision_date", "asset", "provenance"]]
    event_weights = event_weights.merge(
        weight_provenance,
        on=["decision_date", "asset"],
        how="left",
        validate="many_to_one",
    )
    event_weights["provenance"] = event_weights["provenance"].fillna(
        "carried_last_weekly_weight_for_causal_contract_roll"
    )
    selected_active = active.loc[active["decision_date"].isin(selected_dates)].copy()
    selected_active = selected_active.merge(
        event_weights.loc[:, ["decision_date", "asset", "target_weight"]],
        on=["decision_date", "asset"],
        how="left",
        validate="one_to_one",
    )
    unavailable = ~selected_active["tradable"] | selected_active["contract_id"].isna()
    selected_active.loc[unavailable, "target_weight"] = 0.0
    adjusted = event_weights.drop(columns="target_weight").merge(
        selected_active.loc[:, ["decision_date", "asset", "target_weight"]],
        on=["decision_date", "asset"],
        how="inner",
        validate="one_to_one",
    )
    timing = selected_active.loc[:, ["decision_date", "effective_date"]].drop_duplicates()
    mapping_active = selected_active.loc[
        :,
        [
            "decision_date",
            "effective_date",
            "observed_through",
            "asset",
            "contract_id",
            "tradable",
        ],
    ].rename(columns={"asset": "asset_code"})
    mapped = map_decision_weights_to_next_open(adjusted, timing, mapping_active)
    in_oos = mapped["effective_date"].between(oos_start, oos_end)
    mapped = mapped.loc[in_oos].reset_index(drop=True)
    event_oos_dates = set(mapped["decision_date"])
    weekly_oos = int(sum(date in set(weight_matrix.index) for date in event_oos_dates))
    roll_oos = int(
        sum(
            bool(roll_needed.get(date, False)) and date not in weight_matrix.index
            for date in event_oos_dates
        )
    )
    decision_audit = pd.DataFrame(
        {
            "decision_date": selected_dates,
            "weekly_rebalance": weekly_event.reindex(selected_dates).to_numpy(dtype=bool),
            "roll_required": roll_needed.reindex(selected_dates).to_numpy(dtype=bool),
        }
    )
    effective_lookup = timing.set_index("decision_date")["effective_date"]
    decision_audit["effective_date"] = decision_audit["decision_date"].map(effective_lookup)
    decision_audit = decision_audit.loc[
        decision_audit["effective_date"].between(oos_start, oos_end)
    ].reset_index(drop=True)
    if mapped.groupby("effective_date")["asset_code"].nunique().ne(len(ASSETS)).any():
        raise ValueError("V12 mapped targets are not complete four-asset snapshots")
    return TargetBuild(
        targets=mapped,
        decision_audit=decision_audit,
        weekly_decisions=weekly_oos,
        roll_decisions=roll_oos,
    )


def build_execution_market(observations: pd.DataFrame, spec_proxy: pd.DataFrame) -> pd.DataFrame:
    """Join raw factual contract observations to the frozen causal spec proxy."""
    normalized = observations.rename(
        columns={
            "trade_date": "session_date",
            "logical_asset": "asset_code",
            "canonical_contract_id": "contract_id",
        }
    ).copy()
    normalized["asset_code"] = normalized["asset_code"].map(_asset_code)
    market = build_portfolio_market(normalized, spec_proxy)
    dates = pd.to_datetime(market["session_date"], errors="raise")
    if dates.ge(PROTECTED_FROM).any():
        raise ValueError("V12 execution market touches protected 2026+")
    return market


def execution_coverage(market: pd.DataFrame, targets: pd.DataFrame) -> pd.DataFrame:
    """Report, but never use for signal selection, every factual next-open dependency."""
    ordered = market.sort_values(
        ["asset_code", "contract_id", "session_date"], kind="mergesort"
    ).copy()
    ordered["lagged_volume"] = ordered.groupby(
        ["asset_code", "contract_id"], sort=False
    )["volume"].shift(1)
    nonzero = targets.loc[targets["target_weight"].abs().gt(1e-12)].copy()
    joined = nonzero.merge(
        ordered,
        left_on=["effective_date", "asset_code", "contract_id"],
        right_on=["session_date", "asset_code", "contract_id"],
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    output = joined.loc[
        :,
        ["decision_date", "effective_date", "asset_code", "contract_id", "target_weight"],
    ].copy()
    output["market_row"] = joined["_merge"].eq("both")
    positive = (
        "open",
        "settle",
        "sizing_point_value",
        "accounting_point_value",
        "tick_size",
        "initial_margin",
    )
    for column in positive:
        values = pd.to_numeric(joined[column], errors="coerce")
        output[f"{column}_available"] = values.notna() & np.isfinite(values) & values.gt(0.0)
    fee = pd.to_numeric(joined["fee_per_contract"], errors="coerce")
    output["fee_available"] = fee.notna() & np.isfinite(fee) & fee.ge(0.0)
    volume = pd.to_numeric(joined["lagged_volume"], errors="coerce")
    output["lagged_volume_available"] = volume.notna() & np.isfinite(volume) & volume.ge(0.0)
    availability = [column for column in output if column.endswith("_available")]
    output["execution_dependencies_complete"] = output["market_row"] & output[
        availability
    ].all(axis=1)
    return output.sort_values(
        ["effective_date", "asset_code"], kind="mergesort", ignore_index=True
    )


def _annual_returns(ledger: pd.DataFrame) -> dict[str, float]:
    if ledger.empty:
        return {}
    daily = ledger["ending_cash"].astype(float) / ledger["starting_cash"].astype(float) - 1.0
    dates = pd.to_datetime(ledger["session_date"], errors="raise")
    result: dict[str, float] = {}
    for year in range(2021, 2026):
        values = daily.loc[dates.dt.year.eq(year)]
        if not values.empty:
            result[str(year)] = float((1.0 + values).prod() - 1.0)
    return result


def _terminal_exit_reserve(
    result: FuturesPortfolioLedgerResult,
    market: pd.DataFrame,
    settings: dict[str, float],
) -> float | None:
    if result.positions.empty or result.ledger.empty:
        return 0.0
    terminal_date = pd.Timestamp(result.ledger["session_date"].max())
    terminal = result.positions.loc[result.positions["session_date"].eq(terminal_date)]
    terminal = terminal.loc[terminal["contracts"].ne(0)]
    if terminal.empty:
        return 0.0
    indexed = market.set_index(["session_date", "asset_code", "contract_id"])
    reserve = 0.0
    for row in terminal.itertuples(index=False):
        try:
            quote = indexed.loc[(terminal_date, row.asset_code, row.contract_id)]
        except KeyError:
            return None
        if isinstance(quote, pd.DataFrame):
            return None
        needed = ("fee_per_contract", "tick_size", "accounting_point_value")
        if any(
            not math.isfinite(float(quote[item])) or float(quote[item]) < 0.0
            for item in needed
        ):
            return None
        quantity = abs(int(row.contracts))
        reserve += quantity * (
            float(quote["fee_per_contract"]) * float(settings["fee_multiplier"])
            + float(quote["tick_size"])
            * float(quote["accounting_point_value"])
            * float(settings["slippage_ticks"])
        )
    return float(reserve)


def scenario_metrics(
    result: FuturesPortfolioLedgerResult,
    market: pd.DataFrame,
    settings: dict[str, float],
) -> dict[str, Any]:
    annual = _annual_returns(result.ledger)
    reserve = _terminal_exit_reserve(result, market, settings)
    ending_cash = float(result.metrics["ending_cash"])
    reserve_return = None if reserve is None else (ending_cash - reserve) / INITIAL_CASH - 1.0
    orders = result.orders
    filled = orders.loc[orders["filled"].eq(True)] if not orders.empty else orders
    rejection_counts = (
        {
            str(key): int(value)
            for key, value in orders.loc[~orders["filled"]]["reason"].value_counts().items()
        }
        if not orders.empty
        else {}
    )
    return {
        **_json_safe(result.metrics),
        "metrics_valid": bool(result.execution_complete),
        "annual_returns": annual,
        "positive_years": int(sum(value > 0.0 for value in annual.values())),
        "worst_year": min(annual.values()) if annual else None,
        "terminal_exit_cost_reserve": reserve,
        "post_terminal_reserve_total_return": reserve_return,
        "filled_order_notional": float(filled["gross_notional"].sum()) if not filled.empty else 0.0,
        "turnover_multiple": float(filled["gross_notional"].sum() / INITIAL_CASH)
        if not filled.empty
        else 0.0,
        "rejected_leg_count": int((~orders["filled"]).sum()) if not orders.empty else 0,
        "rejection_reason_counts": rejection_counts,
        "settings": settings,
    }


def _promotion(results: dict[str, dict[str, Any]], checks: dict[str, bool]) -> dict[str, Any]:
    primary = results["primary"]
    conditions = {
        "every_input_and_temporal_check_true": all(checks.values()),
        "all_scenarios_execution_complete": all(
            bool(value["execution_complete"]) for value in results.values()
        ),
        "zero_critical_failures_and_unresolved_halts": all(
            int(value["critical_failure_count"]) == 0
            and int(value["unresolved_halt_count"]) == 0
            for value in results.values()
        ),
        "primary_cagr_at_least_0_05": float(primary["cagr"]) >= 0.05,
        "primary_sharpe_at_least_0_60": float(primary["sharpe"]) >= 0.60,
        "primary_maximum_drawdown_at_most_0_25": float(primary["maximum_drawdown"])
        <= 0.25,
        "primary_positive_years_at_least_4_of_5": int(primary["positive_years"]) >= 4
        and len(primary["annual_returns"]) == 5,
        "doubled_total_return_positive": float(results["doubled"]["total_return"]) > 0.0,
        "stress_total_return_positive": float(results["stress"]["total_return"]) > 0.0,
        "no_gross_participation_or_margin_breach": all(
            float(value["maximum_participation"]) <= MAXIMUM_PARTICIPATION + 1e-12
            and float(value["ending_cash"]) > 0.0
            for value in results.values()
        ),
    }
    passed = all(conditions.values())
    return {
        "conditions": conditions,
        "passed": passed,
        "verdict": "GO_TO_NEW_UNSEEN_VALIDATION" if passed else "NO_GO",
        "live_trading_allowed": False,
        "independent_confirmation_required": True,
    }


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    frame.to_parquet(path, index=False, compression="zstd")


def _report_text(payload: dict[str, Any]) -> str:
    lines = [
        "# V12 core-four correlation trend",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        (
            "This is adaptive same-period hypothesis generation on 2021-2025, not an "
            "independent holdout confirmation."
        ),
        "",
        "| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name in ("primary", "doubled", "stress"):
        item = payload["scenarios"][name]
        lines.append(
            f"| {name} | {item['total_return']:.4%} | {item['cagr']:.4%} | "
            f"{item['sharpe']:.3f} | {item['maximum_drawdown']:.4%} | "
            f"{item['positive_years']}/5 | {item['total_cost']:.2f} | "
            f"{item['execution_complete']} |"
        )
    lines.extend(["", "## Primary annual returns", ""])
    for year, value in payload["scenarios"]["primary"]["annual_returns"].items():
        lines.append(f"- {year}: {value:.4%}")
    counts = payload["counts"]
    lines.extend(
        [
            "",
            "## Coverage and execution",
            "",
            f"- Weekly decisions: {counts['weekly_decisions']}",
            f"- Extra roll decisions: {counts['roll_decisions']}",
            f"- Mapped target rows: {counts['mapped_target_rows']}",
            f"- Non-zero targets: {counts['nonzero_targets']}",
            f"- Complete next-open dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "Terminal positions are carried and a one-way exit reserve is reported; historical "
            "exchange specs, broker fees, order-book spread and queue are not exact.",
        ]
    )
    return "\n".join(lines) + "\n"


def _scenario_settings(protocol: dict[str, Any]) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = {}
    for name, values in protocol["execution"]["scenarios"].items():
        output[str(name)] = {
            "slippage_ticks": int(values["slippage_ticks_per_leg"]),
            "fee_multiplier": float(values["conservative_fee_multiplier"]),
        }
    if output != {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }:
        raise ValueError("V12 cost scenarios drifted from the seal")
    return output


def run_experiment(output_root: Path) -> Path:
    """Execute one immutable V12 development run and return its external directory."""
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    panel = pd.read_parquet(
        verified.paths["panel"], columns=protocol["inputs"]["panel"]["allowed_columns"]
    )
    active = pd.read_parquet(
        verified.paths["active_contract_map"],
        columns=protocol["inputs"]["active_contract_map"]["allowed_columns"],
    )
    observations = pd.read_parquet(
        verified.paths["contract_observations"],
        columns=protocol["inputs"]["contract_observations"]["allowed_columns"],
    )
    specs = pd.read_parquet(
        verified.paths["spec_proxy"],
        columns=protocol["inputs"]["spec_proxy"]["allowed_columns"],
    )
    scores = build_trend_scores(panel)
    weekly_weights = build_weekly_weights(panel, scores)
    target_build = build_execution_targets(weekly_weights, active)
    market = build_execution_market(observations, specs)
    coverage = execution_coverage(market, target_build.targets)

    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < OOS_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(predecessor, OOS_END)
    ].copy()
    scenario_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    scenario_results: dict[str, dict[str, Any]] = {}
    for name, settings in _scenario_settings(protocol).items():
        result = run_futures_portfolio_ledger(
            execution_market,
            target_build.targets,
            FuturesPortfolioLedgerConfig(
                initial_cash=INITIAL_CASH,
                expected_assets=ASSETS,
                maximum_gross_notional_multiple=1.0,
                initial_margin_buffer_multiplier=2.0,
                maximum_participation=MAXIMUM_PARTICIPATION,
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
                execution_atomicity="asset",
                terminal_policy="carry",
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name] = scenario_metrics(result, execution_market, settings)

    counts = {
        "source_panel_rows": int(len(panel)),
        "source_active_map_rows": int(len(active)),
        "source_contract_observation_rows": int(len(observations)),
        "source_spec_rows": int(len(specs)),
        "score_rows": int(len(scores)),
        "finite_score_rows": int(scores["candidate_score"].notna().sum()),
        "weekly_decisions": target_build.weekly_decisions,
        "roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": int(len(target_build.targets)),
        "nonzero_targets": int(target_build.targets["target_weight"].abs().gt(1e-12).sum()),
        "covered_nonzero_targets": int(coverage["execution_dependencies_complete"].sum()),
    }
    promotion = _promotion(scenario_results, verified.checks)
    code_paths = {
        "v12_implementation": Path(__file__).resolve(),
        "portfolio_construction": PROJECT_ROOT / "src/market_lab/futures/portfolio_construction.py",
        "execution_dataset": PROJECT_ROOT / "src/market_lab/futures/execution_dataset.py",
        "portfolio_ledger": PROJECT_ROOT / "src/market_lab/futures/portfolio_ledger.py",
        "spec_proxy": PROJECT_ROOT / "src/market_lab/futures/spec_proxy.py",
    }
    identity = {
        "protocol_sha256": CONFIG_SHA256,
        "input_sha256": {
            name: declaration["sha256"] for name, declaration in protocol["inputs"].items()
        },
        "code_sha256": {name: sha256_file(path) for name, path in code_paths.items()},
        "protected_from": PROTECTED_FROM.date().isoformat(),
        "contains_2026_prices_returns_targets_or_pnl": False,
    }
    payload: dict[str, Any] = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "research_only": True,
        "adaptive_same_period": True,
        "independent_holdout_confirmation": False,
        "live_trading_allowed": False,
        "checks": verified.checks,
        "input_metadata": verified.metadata,
        "identity": identity,
        "counts": counts,
        "scenarios": scenario_results,
        "promotion": promotion,
        "limitations": protocol["execution"]["limitations"],
    }

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v12_core4_trend_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V12 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        _write_parquet(temporary / "scores.parquet", scores)
        _write_parquet(temporary / "weekly_weights.parquet", weekly_weights)
        _write_parquet(temporary / "mapped_targets.parquet", target_build.targets)
        target_build.decision_audit.to_csv(
            temporary / "decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        for name, result in scenario_outputs.items():
            _write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            _write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            _write_parquet(temporary / f"positions_{name}.parquet", result.positions)
        report_path = temporary / "report.md"
        report_path.write_text(_report_text(payload), encoding="utf-8-sig")
        artifacts: dict[str, Any] = {}
        for path in sorted(temporary.iterdir()):
            if path.name in {"metrics.json", "identity.json"}:
                continue
            entry: dict[str, Any] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            if path.suffix == ".parquet":
                entry["rows"] = pq.ParquetFile(path).metadata.num_rows
            artifacts[path.name] = entry
        payload["artifacts"] = artifacts
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8-sig",
        )
        identity_path = temporary / "identity.json"
        identity_path.write_text(
            json.dumps(
                _json_safe({**identity, "metrics_sha256": sha256_file(metrics_path)}),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8-sig",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "runs",
        help="External immutable runs root; a unique V12 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
