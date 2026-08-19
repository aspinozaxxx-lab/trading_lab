"""Frozen sparse-event direction plus frozen 10-minute timing evaluation.

This module is deliberately evaluation-only.  It verifies every frozen input,
never reconstructs a target, and uses the exact next-bar OHLCV ledger embedded
in the development-only timing tensor.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from market_lab.futures_v9_intraday_timing.data import (
    ASSETS,
    TimingArrays,
    load_timing_arrays,
    sha256_file,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
PROTOCOL_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v9_event_timing_hybrid.yaml"
PROTOCOL_SHA256: Final[str] = "92e98a7252d74bc099ef93a86d8f37eb011b11bebbe2c42b870568236b0f3465"
EVENT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/event_alpha_v1.yaml"
EVENT_CONFIG_SHA256: Final[str] = "91f61abea2e4ca53179c9d5d085cbe98a8b6b863404050af547873c49cca7330"
EVENT_RUN: Final[Path] = PROJECT_ROOT / "runs/event_alpha_v1/development_20260818T155959Z_91f61abe"
EVENT_MANIFEST_SHA256: Final[str] = (
    "dc2be61119332af65f38b369f4dba89619fce29586db2f445bf48b5f0934191c"
)
TENSOR_PATH: Final[Path] = (
    PROJECT_ROOT / "data/processed/futures_v9_intraday_timing/development_2018_2025.npz"
)
TENSOR_SHA256: Final[str] = "7bf3397864e44a13fa2ce841c206ed3c33974439e32bd439625b40df12014b21"
V1_PREDICTIONS: Final[Path] = (
    PROJECT_ROOT / "runs/futures_v9_intraday_timing_full_20260818T163148Z/predictions.parquet"
)
V1_PREDICTIONS_SHA256: Final[str] = (
    "3c7b4e50aff3b49d34b146b9ca89b3b7518e7317da466b80b03795bf58ece32a"
)
V2_PREDICTIONS: Final[Path] = (
    PROJECT_ROOT / "runs/futures_v9_intraday_timing_v2_full_20260818T164623Z/predictions.parquet"
)
V2_PREDICTIONS_SHA256: Final[str] = (
    "3bd145406906376e4ec1067686d83eb67c175dee525b1aa80d9efbbce38be129"
)
TEN_MINUTES_NS: Final[int] = 600_000_000_000
PROTECTED_NS: Final[int] = pd.Timestamp("2026-01-01", tz="UTC").value
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
YEARS: Final[tuple[int, ...]] = (2021, 2022, 2023, 2024, 2025)
INITIAL_CAPITAL: Final[float] = 10_000_000.0
FAMILY_SPECS: Final[dict[str, tuple[str, int]]] = {
    "all_macro": ("all_macro", 5),
    "cbr_usd_rub_tail": ("family:cbr_usd_rub_tail", 5),
    "cbr_key_rate_change": ("family:cbr_key_rate_change", 1),
}
COMBINED_PRIORITY: Final[dict[str, int]] = {
    "cbr_key_rate_change": 0,
    "cbr_usd_rub_tail": 1,
    "all_macro": 2,
}
TIMING_MODES: Final[dict[str, tuple[Literal["v1", "v2"], str]]] = {
    "v1_attention_tail_q90": ("v1", "attention"),
    "v1_independent_tail_q90": ("v1", "independent"),
    "v2_attention_frozen_gate": ("v2", "attention"),
    "v2_independent_frozen_gate": ("v2", "independent"),
}


@dataclass(frozen=True, slots=True)
class PredictionStore:
    v1: pd.DataFrame
    v2: pd.DataFrame
    thresholds: dict[tuple[str, int, int], dict[str, float | int | None]]


@dataclass(frozen=True, slots=True)
class LedgerIndex:
    session_dates: tuple[dict[object, int], ...]


def _verify_hash(path: Path, expected: str, role: str) -> None:
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"{role} byte drift: expected {expected}, got {actual}")


def verify_frozen_inputs() -> dict[str, str]:
    """Verify the complete frozen chain before reading joint outcomes."""
    declared = {
        "protocol": (PROTOCOL_PATH, PROTOCOL_SHA256),
        "event_config": (EVENT_CONFIG, EVENT_CONFIG_SHA256),
        "event_manifest": (EVENT_RUN / "manifest.json", EVENT_MANIFEST_SHA256),
        "timing_tensor": (TENSOR_PATH, TENSOR_SHA256),
        "timing_v1_predictions": (V1_PREDICTIONS, V1_PREDICTIONS_SHA256),
        "timing_v2_predictions": (V2_PREDICTIONS, V2_PREDICTIONS_SHA256),
    }
    hashes: dict[str, str] = {}
    for role, (path, expected) in declared.items():
        _verify_hash(path, expected, role)
        hashes[role] = expected
    manifest = json.loads((EVENT_RUN / "manifest.json").read_text(encoding="utf-8-sig"))
    output_hashes = {
        Path(str(item["path"])).name: str(item["sha256"]) for item in manifest.get("outputs", [])
    }
    ledger_path = EVENT_RUN / "trade_ledger.parquet"
    expected_ledger = output_hashes.get("trade_ledger.parquet")
    if expected_ledger is None:
        raise ValueError("frozen event manifest does not declare trade_ledger.parquet")
    _verify_hash(ledger_path, expected_ledger, "event trade ledger")
    hashes["event_trade_ledger"] = expected_ledger
    return hashes


def load_event_families() -> dict[str, pd.DataFrame]:
    columns = [
        "event_id",
        "event_family",
        "available_at",
        "asset",
        "horizon_sessions",
        "direction_prediction",
        "selected_by_confidence",
        "fold_year",
        "sleeve",
    ]
    ledger = pd.read_parquet(EVENT_RUN / "trade_ledger.parquet", columns=columns)
    ledger["available_at"] = pd.to_datetime(ledger["available_at"], utc=True, errors="raise")
    if ledger["available_at"].max().value >= PROTECTED_NS or int(ledger["fold_year"].max()) >= 2026:
        raise ValueError("frozen event directions touch protected 2026")
    families: dict[str, pd.DataFrame] = {}
    for name, (sleeve, horizon) in FAMILY_SPECS.items():
        selected = ledger[
            ledger["sleeve"].eq(sleeve) & ledger["horizon_sessions"].eq(horizon)
        ].copy()
        if not selected["selected_by_confidence"].fillna(False).all():
            raise ValueError(f"{name} frozen sleeve contains an unselected direction")
        selected["direction_prediction"] = pd.to_numeric(
            selected["direction_prediction"], errors="raise"
        ).astype(int)
        if not selected["direction_prediction"].isin([-1, 1]).all():
            raise ValueError(f"{name} has a non-binary frozen direction")
        if not selected["asset"].isin(ASSETS).all():
            raise ValueError(f"{name} contains an asset outside the timing universe")
        if selected.duplicated(["event_id", "asset"]).any():
            raise ValueError(f"{name} duplicates a frozen event-asset")
        selected["evaluation_family"] = name
        selected["event_key"] = (
            selected["event_id"].astype(str) + "|" + selected["asset"].astype(str)
        )
        families[name] = selected.sort_values(
            ["available_at", "asset", "event_id"], kind="stable"
        ).reset_index(drop=True)
    combined = pd.concat(families.values(), ignore_index=True)
    combined["priority"] = combined["evaluation_family"].map(COMBINED_PRIORITY)
    combined = (
        combined.sort_values(["priority", "available_at", "event_id"], kind="stable")
        .drop_duplicates(["event_id", "asset"], keep="first")
        .sort_values(["available_at", "asset", "event_id"], kind="stable")
        .reset_index(drop=True)
    )
    families["combined"] = combined
    return families


def _side_score(frame: pd.DataFrame, side: str) -> np.ndarray:
    ratios: list[np.ndarray] = []
    for horizon in (3, 6, 18):
        mean = frame[f"{side}_value_{horizon}"].to_numpy(dtype=float)
        sigma = frame[f"{side}_value_{horizon}_uncertainty"].to_numpy(dtype=float)
        ratios.append(
            np.divide(
                mean,
                sigma,
                out=np.full(mean.shape, np.nan, dtype=float),
                where=np.isfinite(mean) & np.isfinite(sigma) & (sigma > 0.0),
            )
        )
    stacked = np.column_stack(ratios)
    finite = np.isfinite(stacked).any(axis=1)
    result = np.full(len(frame), np.nan, dtype=float)
    result[finite] = np.nanmax(stacked[finite], axis=1)
    return result


def calibrate_v1_thresholds(
    v1: pd.DataFrame,
) -> dict[tuple[str, int, int], dict[str, float | int | None]]:
    """Target-free q90 using only scores in the 120 days before each OOS year."""
    thresholds: dict[tuple[str, int, int], dict[str, float | int | None]] = {}
    close_time = v1["timestamp"] + pd.Timedelta(minutes=10)
    for variant in ("attention", "independent"):
        variant_mask = v1["variant"].eq(variant)
        for year in YEARS:
            boundary = pd.Timestamp(f"{year}-01-01", tz=MOSCOW).tz_convert("UTC")
            prior_mask = (
                variant_mask
                & close_time.ge(boundary - pd.Timedelta(days=120))
                & close_time.lt(boundary)
            )
            for direction, side in ((1, "long"), (-1, "short")):
                sample = v1.loc[prior_mask, f"{side}_score"].dropna().to_numpy(float)
                enough = len(sample) >= 1000
                thresholds[(variant, year, direction)] = {
                    "rows": int(len(sample)),
                    "threshold": float(np.quantile(sample, 0.90)) if enough else None,
                }
    return thresholds


def load_prediction_store() -> PredictionStore:
    value_columns = [
        f"{side}_value_{horizon}{suffix}"
        for side in ("long", "short")
        for horizon in (3, 6, 18)
        for suffix in ("", "_uncertainty")
    ]
    v1 = pd.read_parquet(
        V1_PREDICTIONS,
        columns=["timestamp", "asset", "variant", *value_columns],
    )
    v1["timestamp"] = pd.to_datetime(v1["timestamp"], utc=True, errors="raise")
    if v1["timestamp"].max().value >= PROTECTED_NS:
        raise ValueError("V1 predictions touch protected 2026")
    for side in ("long", "short"):
        v1[f"{side}_score"] = _side_score(v1, side)
    thresholds = calibrate_v1_thresholds(v1)
    v1["timestamp_ns"] = v1["timestamp"].astype("int64")
    if v1.duplicated(["variant", "asset", "timestamp_ns"]).any():
        raise ValueError("V1 predictions duplicate variant/asset/timestamp")
    v1 = v1.set_index(["variant", "asset", "timestamp_ns"])[
        ["long_score", "short_score"]
    ].sort_index()

    gate_columns = [
        f"{side}_value_{horizon}_gate" for side in ("long", "short") for horizon in (3, 6, 18)
    ]
    v2 = pd.read_parquet(
        V2_PREDICTIONS,
        columns=["timestamp", "asset", "variant", *gate_columns],
    )
    v2["timestamp"] = pd.to_datetime(v2["timestamp"], utc=True, errors="raise")
    if v2["timestamp"].max().value >= PROTECTED_NS:
        raise ValueError("V2 predictions touch protected 2026")
    for side in ("long", "short"):
        v2[f"{side}_gate"] = (
            v2[[f"{side}_value_{horizon}_gate" for horizon in (3, 6, 18)]]
            .fillna(False)
            .astype(bool)
            .any(axis=1)
        )
    v2["timestamp_ns"] = v2["timestamp"].astype("int64")
    if v2.duplicated(["variant", "asset", "timestamp_ns"]).any():
        raise ValueError("V2 predictions duplicate variant/asset/timestamp")
    v2 = v2.set_index(["variant", "asset", "timestamp_ns"])[
        ["long_gate", "short_gate"]
    ].sort_index()
    return PredictionStore(v1=v1, v2=v2, thresholds=thresholds)


def build_ledger_index(arrays: TimingArrays) -> LedgerIndex:
    local_dates = pd.to_datetime(arrays.timestamps_ns, utc=True).tz_convert(MOSCOW).date
    maps: list[dict[object, int]] = []
    for asset_index in range(len(ASSETS)):
        dates = sorted(set(local_dates[arrays.asset_mask[:, asset_index]]))
        maps.append({value: index for index, value in enumerate(dates)})
    return LedgerIndex(session_dates=tuple(maps))


def eligible_decisions(
    arrays: TimingArrays,
    *,
    asset_index: int,
    available_ns: int,
    maximum: int = 6,
) -> list[int]:
    first = int(np.searchsorted(arrays.timestamps_ns, available_ns - TEN_MINUTES_NS, side="left"))
    result: list[int] = []
    for index in range(max(first, 0), len(arrays.timestamps_ns)):
        if arrays.timestamps_ns[index] + TEN_MINUTES_NS < available_ns:
            continue
        if (
            arrays.asset_mask[index, asset_index]
            and arrays.execution_mask[index, asset_index]
            and arrays.sizing_mask[index, asset_index]
        ):
            result.append(index)
            if len(result) == maximum:
                break
    return result


def _resolve_exit(
    arrays: TimingArrays,
    ledger_index: LedgerIndex,
    *,
    entry_index: int,
    asset_index: int,
) -> tuple[int, int] | None:
    entry_time_ns = int(arrays.timestamps_ns[entry_index] + TEN_MINUTES_NS)
    entry_local = pd.Timestamp(entry_time_ns, tz="UTC").tz_convert(MOSCOW)
    date_map = ledger_index.session_dates[asset_index]
    ordinal = date_map.get(entry_local.date())
    if ordinal is None:
        return None
    inverse = sorted(date_map, key=date_map.get)
    if ordinal + 5 >= len(inverse):
        return None
    target_date = inverse[ordinal + 5]
    target_clock = time(entry_local.hour, entry_local.minute)
    target_local = pd.Timestamp(datetime.combine(target_date, target_clock), tz=MOSCOW)
    exit_execution_ns = int(target_local.tz_convert("UTC").value)
    exit_decision_ns = exit_execution_ns - TEN_MINUTES_NS
    exit_index = int(np.searchsorted(arrays.timestamps_ns, exit_decision_ns))
    if (
        exit_index >= len(arrays.timestamps_ns)
        or int(arrays.timestamps_ns[exit_index]) != exit_decision_ns
        or not arrays.execution_mask[exit_index, asset_index]
        or arrays.contract_ids[entry_index, asset_index] == ""
        or arrays.contract_ids[entry_index, asset_index]
        != arrays.contract_ids[exit_index, asset_index]
        or not np.isfinite(arrays.fee_per_side[exit_index, asset_index])
    ):
        return None
    return exit_index, exit_execution_ns


def _timing_passes(
    store: PredictionStore,
    *,
    mode: str,
    asset: str,
    timestamp_ns: int,
    year: int,
    direction: int,
) -> tuple[bool, float | None, str]:
    version, variant = TIMING_MODES[mode]
    side = "long" if direction == 1 else "short"
    key = (variant, asset, timestamp_ns)
    if version == "v1":
        calibration = store.thresholds[(variant, year, direction)]
        threshold = calibration["threshold"]
        if threshold is None:
            return False, None, "missing_prior_threshold"
        try:
            score = float(store.v1.loc[key, f"{side}_score"])
        except KeyError:
            return False, None, "missing_timing_coverage"
        if not np.isfinite(score):
            return False, None, "missing_timing_coverage"
        # Positive score is exactly the sealed positive calibrated-mean rule,
        # because all admitted uncertainties are strictly positive.
        return score >= float(threshold) and score > 0.0, score, "score_below_gate"
    try:
        gate = bool(store.v2.loc[key, f"{side}_gate"])
    except KeyError:
        return False, None, "missing_timing_coverage"
    return gate, None, "score_below_gate"


def _proposal(
    arrays: TimingArrays,
    ledger_index: LedgerIndex,
    store: PredictionStore,
    event: Any,
    *,
    mode: str | None,
) -> tuple[dict[str, Any] | None, str]:
    asset = str(event.asset)
    asset_index = ASSETS.index(asset)
    available = pd.Timestamp(event.available_at)
    available_ns = int(available.value)
    candidates = eligible_decisions(
        arrays,
        asset_index=asset_index,
        available_ns=available_ns,
        maximum=1 if mode is None else 6,
    )
    if not candidates:
        return None, "no_eligible_entry"
    chosen: int | None = None
    chosen_delay = 0
    chosen_score: float | None = None
    last_reason = "score_below_gate"
    if mode is None:
        chosen = candidates[0]
    else:
        year = int(event.fold_year)
        for delay, index in enumerate(candidates):
            passed, score, reason = _timing_passes(
                store,
                mode=mode,
                asset=asset,
                timestamp_ns=int(arrays.timestamps_ns[index]),
                year=year,
                direction=int(event.direction_prediction),
            )
            last_reason = reason
            if passed:
                chosen = index
                chosen_delay = delay
                chosen_score = score
                break
        if chosen is None:
            return None, last_reason
    resolved = _resolve_exit(
        arrays,
        ledger_index,
        entry_index=chosen,
        asset_index=asset_index,
    )
    if resolved is None:
        return None, "unresolved_same_contract_exit"
    exit_index, exit_time_ns = resolved
    direction = int(event.direction_prediction)
    entry_price = float(arrays.execution_ohlcv[chosen, asset_index, 1 if direction == 1 else 2])
    exit_price = float(arrays.execution_ohlcv[exit_index, asset_index, 2 if direction == 1 else 1])
    values = {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "point_value": float(arrays.point_value[chosen, asset_index]),
        "notional_per_contract": float(arrays.notional[chosen, asset_index]),
        "entry_fee_per_contract": float(arrays.fee_per_side[chosen, asset_index]),
        "exit_fee_per_contract": float(arrays.fee_per_side[exit_index, asset_index]),
        "entry_volume": float(arrays.execution_ohlcv[chosen, asset_index, 4]),
    }
    if not all(np.isfinite(value) and value > 0.0 for value in values.values()):
        return None, "invalid_execution_or_spec"
    return {
        "event_key": str(event.event_key),
        "event_id": str(event.event_id),
        "source_event_family": str(event.event_family),
        "evaluation_family": str(event.evaluation_family),
        "asset": asset,
        "asset_index": asset_index,
        "available_at": available,
        "direction": direction,
        "side": "long" if direction == 1 else "short",
        "direction_horizon_sessions": int(event.horizon_sessions),
        "entry_index": chosen,
        "entry_time_ns": int(arrays.timestamps_ns[chosen] + TEN_MINUTES_NS),
        "exit_index": exit_index,
        "exit_time_ns": exit_time_ns,
        "contract_id": str(arrays.contract_ids[chosen, asset_index]),
        "delay_bars": chosen_delay,
        "timing_score": chosen_score,
        **values,
    }, "admitted"


def simulate_strategy(
    arrays: TimingArrays,
    ledger_index: LedgerIndex,
    store: PredictionStore,
    events: pd.DataFrame,
    *,
    mode: str | None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    equity = INITIAL_CAPITAL
    open_positions: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    audit: Counter[str] = Counter()
    ordered = events.sort_values(["available_at", "asset", "event_id"], kind="stable")
    for event in ordered.itertuples(index=False):
        proposal, reason = _proposal(arrays, ledger_index, store, event, mode=mode)
        if proposal is None:
            audit[reason] += 1
            continue
        entry_time_ns = int(proposal["entry_time_ns"])
        for asset, position in list(open_positions.items()):
            if int(position["exit_time_ns"]) <= entry_time_ns:
                equity += float(position["pnl_1x"])
                del open_positions[asset]
        asset = str(proposal["asset"])
        if asset in open_positions:
            audit["overlap_blocked"] += 1
            continue
        notional = float(proposal["notional_per_contract"])
        requested = math.floor(0.25 * max(equity, 0.0) / notional)
        capacity = math.floor(0.01 * float(proposal["entry_volume"]))
        open_gross = sum(float(position["entry_notional"]) for position in open_positions.values())
        portfolio_capacity = math.floor(max(equity - open_gross, 0.0) / notional)
        quantity = int(min(requested, capacity, portfolio_capacity))
        if quantity < 1:
            audit["sizing_or_participation_blocked"] += 1
            continue
        gross_pnl = (
            quantity
            * float(proposal["point_value"])
            * int(proposal["direction"])
            * (float(proposal["exit_price"]) - float(proposal["entry_price"]))
        )
        fees = quantity * (
            float(proposal["entry_fee_per_contract"]) + float(proposal["exit_fee_per_contract"])
        )
        record = {
            **proposal,
            "strategy": "baseline" if mode is None else mode,
            "entry_time": pd.Timestamp(int(proposal["entry_time_ns"]), tz="UTC"),
            "exit_time": pd.Timestamp(int(proposal["exit_time_ns"]), tz="UTC"),
            "quantity": quantity,
            "entry_notional": quantity * notional,
            "gross_pnl": gross_pnl,
            "fees_1x": fees,
            "pnl_1x": gross_pnl - fees,
            "pnl_2x": gross_pnl - 2.0 * fees,
            "participation": quantity / float(proposal["entry_volume"]),
        }
        trades.append(record)
        open_positions[asset] = record
        audit["admitted"] += 1
    audit["attempted_events"] = len(events)
    return pd.DataFrame(trades), dict(sorted(audit.items()))


def _calculate_metrics(
    arrays: TimingArrays,
    trades: pd.DataFrame,
    *,
    cost_column: Literal["pnl_1x", "pnl_2x"],
) -> dict[str, Any]:
    observed = (
        pd.to_datetime(arrays.timestamps_ns[arrays.asset_mask.any(axis=1)], utc=True)
        .tz_convert(MOSCOW)
        .tz_localize(None)
        .normalize()
    )
    calendar = pd.DatetimeIndex(
        sorted(observed[np.isin(observed.year, np.asarray(YEARS))].unique())
    )
    pnl = pd.Series(0.0, index=calendar)
    if not trades.empty:
        exit_dates = (
            pd.to_datetime(trades["exit_time"], utc=True)
            .dt.tz_convert(MOSCOW)
            .dt.tz_localize(None)
            .dt.normalize()
        )
        grouped = trades.assign(exit_date=exit_dates).groupby("exit_date")[cost_column].sum()
        shared = pnl.index.intersection(grouped.index)
        pnl.loc[shared] = grouped.loc[shared]
    equity = INITIAL_CAPITAL + pnl.cumsum()
    previous = equity.shift(1).fillna(INITIAL_CAPITAL)
    returns = pnl / previous
    elapsed_days = max((calendar[-1] - calendar[0]).days + 1, 1) if len(calendar) else 1
    final = float(equity.iloc[-1]) if len(equity) else INITIAL_CAPITAL
    cagr = (max(final, 1e-12) / INITIAL_CAPITAL) ** (365.25 / elapsed_days) - 1.0
    standard_deviation = float(returns.std(ddof=0)) if len(returns) else 0.0
    sharpe = (
        float(returns.mean() / standard_deviation * math.sqrt(252.0))
        if len(returns) > 1 and standard_deviation > 0.0
        else 0.0
    )
    drawdown = equity / equity.cummax() - 1.0 if len(equity) else pd.Series([0.0])
    per_year: dict[str, dict[str, float | int]] = {}
    local_exit_year = (
        pd.to_datetime(trades["exit_time"], utc=True).dt.tz_convert(MOSCOW).dt.year
        if not trades.empty
        else pd.Series(dtype=int)
    )
    for year in YEARS:
        yearly = pnl[pnl.index.year == year]
        start_equity = float(INITIAL_CAPITAL + pnl[pnl.index.year < year].sum())
        subset = trades[local_exit_year.eq(year)] if not trades.empty else trades
        per_year[str(year)] = {
            "return": float(yearly.sum() / start_equity) if start_equity > 0.0 else -1.0,
            "pnl_rub": float(yearly.sum()),
            "trades": int(len(subset)),
        }
    long_count = int((trades["side"] == "long").sum()) if not trades.empty else 0
    short_count = int((trades["side"] == "short").sum()) if not trades.empty else 0
    years_elapsed = max(elapsed_days / 365.25, 1e-9)
    return {
        "trades": int(len(trades)),
        "cagr": float(cagr),
        "sharpe": sharpe,
        "maximum_drawdown": float(drawdown.min()),
        "worst_year": min((item["return"] for item in per_year.values()), default=0.0),
        "final_equity_rub": final,
        "turnover_annualized": (
            float(2.0 * trades["entry_notional"].sum() / INITIAL_CAPITAL / years_elapsed)
            if not trades.empty
            else 0.0
        ),
        "costs_rub": (
            float(trades["fees_1x"].sum() * (1.0 if cost_column == "pnl_1x" else 2.0))
            if not trades.empty
            else 0.0
        ),
        "long_trades": long_count,
        "short_trades": short_count,
        "long_fraction": long_count / max(long_count + short_count, 1),
        "maximum_participation": float(trades["participation"].max()) if not trades.empty else 0.0,
        "per_year": per_year,
    }


def _enrich_metrics(
    arrays: TimingArrays,
    trades: pd.DataFrame,
    events: pd.DataFrame,
    audit: dict[str, int],
) -> dict[str, Any]:
    output: dict[str, Any] = {"event_asset_decisions": int(len(events)), "audit": audit}
    for multiplier, column in (("cost_1x", "pnl_1x"), ("cost_2x", "pnl_2x")):
        base = _calculate_metrics(arrays, trades, cost_column=column)
        pnl_column = trades[column] if not trades.empty else pd.Series(dtype=float)
        base["hit_rate"] = float((pnl_column > 0.0).mean()) if len(pnl_column) else 0.0
        base["average_delay_bars"] = float(trades["delay_bars"].mean()) if not trades.empty else 0.0
        base["median_delay_bars"] = (
            float(trades["delay_bars"].median()) if not trades.empty else 0.0
        )
        base["basis_points_per_trade"] = (
            float((pnl_column / trades["entry_notional"] * 10_000.0).mean())
            if not trades.empty
            else 0.0
        )
        base["aggregate_basis_points"] = (
            float(pnl_column.sum() / trades["entry_notional"].sum() * 10_000.0)
            if not trades.empty and trades["entry_notional"].sum() > 0
            else 0.0
        )
        for year, yearly in base["per_year"].items():
            if trades.empty:
                yearly["hit_rate"] = 0.0
                yearly["basis_points_per_trade"] = 0.0
                continue
            exit_year = pd.to_datetime(trades["exit_time"], utc=True).dt.tz_convert(MOSCOW).dt.year
            subset = trades[exit_year.eq(int(year))]
            yearly["hit_rate"] = float((subset[column] > 0.0).mean()) if not subset.empty else 0.0
            yearly["basis_points_per_trade"] = (
                float((subset[column] / subset["entry_notional"] * 10_000.0).mean())
                if not subset.empty
                else 0.0
            )
        output[multiplier] = base
    return output


def paired_improvement(baseline: pd.DataFrame, timed: pd.DataFrame) -> dict[str, Any]:
    if baseline.empty:
        return {
            "baseline_events": 0,
            "timed_matched_trades": 0,
            "timed_extra_trades": int(len(timed)),
            "incremental_pnl_1x_rub": 0.0,
            "incremental_pnl_2x_rub": 0.0,
            "incremental_basis_points_1x": 0.0,
            "improved_event_fraction_1x": 0.0,
            "per_year": {},
        }
    base = baseline.set_index("event_key", drop=False)
    timing = timed.set_index("event_key", drop=False) if not timed.empty else pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for key, row in base.iterrows():
        matched = not timed.empty and key in timing.index
        timed_row = timing.loc[key] if matched else None
        rows.append(
            {
                "year": pd.Timestamp(row["exit_time"]).tz_convert(MOSCOW).year,
                "baseline_notional": float(row["entry_notional"]),
                "baseline_pnl_1x": float(row["pnl_1x"]),
                "baseline_pnl_2x": float(row["pnl_2x"]),
                "timed_pnl_1x": float(timed_row["pnl_1x"]) if matched else 0.0,
                "timed_pnl_2x": float(timed_row["pnl_2x"]) if matched else 0.0,
                "matched": bool(matched),
                "delay_bars": int(timed_row["delay_bars"]) if matched else None,
            }
        )
    paired = pd.DataFrame(rows)
    paired["increment_1x"] = paired["timed_pnl_1x"] - paired["baseline_pnl_1x"]
    paired["increment_2x"] = paired["timed_pnl_2x"] - paired["baseline_pnl_2x"]
    denominator = float(paired["baseline_notional"].sum())
    per_year: dict[str, Any] = {}
    for year in YEARS:
        subset = paired[paired["year"].eq(year)]
        per_year[str(year)] = {
            "baseline_events": int(len(subset)),
            "timed_matched_trades": int(subset["matched"].sum()) if len(subset) else 0,
            "incremental_pnl_1x_rub": float(subset["increment_1x"].sum()) if len(subset) else 0.0,
            "incremental_pnl_2x_rub": float(subset["increment_2x"].sum()) if len(subset) else 0.0,
        }
    timed_keys = set(timed["event_key"]) if not timed.empty else set()
    base_keys = set(baseline["event_key"])
    matched_delays = paired.loc[paired["matched"], "delay_bars"]
    return {
        "baseline_events": int(len(paired)),
        "timed_matched_trades": int(paired["matched"].sum()),
        "timed_extra_trades": int(len(timed_keys - base_keys)),
        "timed_match_rate": float(paired["matched"].mean()),
        "average_matched_delay_bars": float(matched_delays.mean()) if len(matched_delays) else 0.0,
        "baseline_pnl_1x_rub": float(paired["baseline_pnl_1x"].sum()),
        "timed_paired_pnl_1x_rub": float(paired["timed_pnl_1x"].sum()),
        "incremental_pnl_1x_rub": float(paired["increment_1x"].sum()),
        "incremental_pnl_2x_rub": float(paired["increment_2x"].sum()),
        "mean_incremental_pnl_1x_rub": float(paired["increment_1x"].mean()),
        "incremental_basis_points_1x": (
            float(paired["increment_1x"].sum() / denominator * 10_000.0)
            if denominator > 0.0
            else 0.0
        ),
        "improved_event_fraction_1x": float((paired["increment_1x"] > 0.0).mean()),
        "per_year": per_year,
    }


def _report(metrics: dict[str, Any], output_dir: Path) -> None:
    lines = [
        "# Frozen event-direction + 10m timing hybrid",
        "",
        f"Protocol SHA-256: `{PROTOCOL_SHA256}`. Development only through 2025; 2026 was not read.",
        "",
        "| family | strategy | trades | delay | bp/trade 1x | CAGR 1x | Sharpe 1x | "
        "MDD 1x | hit 1x | trades 2x | bp/trade 2x | paired increment 1x RUB |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for family, result in metrics["evaluations"].items():
        baseline = result["baseline"]
        one = baseline["cost_1x"]
        two = baseline["cost_2x"]
        lines.append(
            f"| {family} | baseline | {one['trades']} | {one['average_delay_bars']:.2f} | "
            f"{one['basis_points_per_trade']:.2f} | {one['cagr']:.2%} | {one['sharpe']:.2f} | "
            f"{one['maximum_drawdown']:.2%} | {one['hit_rate']:.2%} | {two['trades']} | "
            f"{two['basis_points_per_trade']:.2f} | 0 |"
        )
        for mode, timed in result["timing"].items():
            one = timed["metrics"]["cost_1x"]
            two = timed["metrics"]["cost_2x"]
            paired = timed["paired"]
            lines.append(
                f"| {family} | {mode} | {one['trades']} | {one['average_delay_bars']:.2f} | "
                f"{one['basis_points_per_trade']:.2f} | {one['cagr']:.2%} | {one['sharpe']:.2f} | "
                f"{one['maximum_drawdown']:.2%} | {one['hit_rate']:.2%} | {two['trades']} | "
                f"{two['basis_points_per_trade']:.2f} | {paired['incremental_pnl_1x_rub']:.0f} |"
            )
    lines.extend(
        [
            "",
            "Timed skips are zero in the paired comparison. Thresholds use only the frozen "
            "score distribution in the 120 calendar days before each OOS year; no return or "
            "PnL selected a threshold.",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_hybrid(output_dir: Path) -> dict[str, Any]:
    hashes = verify_frozen_inputs()
    arrays = load_timing_arrays(TENSOR_PATH)
    if int(arrays.timestamps_ns[-1]) >= PROTECTED_NS:
        raise ValueError("timing tensor touches protected 2026")
    store = load_prediction_store()
    families = load_event_families()
    ledger_index = build_ledger_index(arrays)
    output_dir.mkdir(parents=True, exist_ok=False)
    evaluations: dict[str, Any] = {}
    ledgers: list[pd.DataFrame] = []
    for family, events in families.items():
        baseline, baseline_audit = simulate_strategy(arrays, ledger_index, store, events, mode=None)
        if not baseline.empty:
            baseline = baseline.assign(report_family=family)
            ledgers.append(baseline)
        family_result: dict[str, Any] = {
            "source_event_rows": int(len(events)),
            "baseline": _enrich_metrics(arrays, baseline, events, baseline_audit),
            "timing": {},
        }
        for mode in TIMING_MODES:
            timed, timed_audit = simulate_strategy(arrays, ledger_index, store, events, mode=mode)
            if not timed.empty:
                timed = timed.assign(report_family=family)
                ledgers.append(timed)
            family_result["timing"][mode] = {
                "metrics": _enrich_metrics(arrays, timed, events, timed_audit),
                "paired": paired_improvement(baseline, timed),
            }
        evaluations[family] = family_result
    threshold_audit = {
        f"{variant}|{year}|{'long' if direction == 1 else 'short'}": record
        for (variant, year, direction), record in store.thresholds.items()
    }
    metrics: dict[str, Any] = {
        "protocol": "futures_v9_event_timing_hybrid",
        "protocol_sha256": PROTOCOL_SHA256,
        "development_years": list(YEARS),
        "protected_2026_read": False,
        "tensor_max_timestamp": str(pd.Timestamp(int(arrays.timestamps_ns[-1]), tz="UTC")),
        "event_counts": {name: int(len(frame)) for name, frame in families.items()},
        "evaluations": evaluations,
    }
    combined_ledger = pd.concat(ledgers, ignore_index=True) if ledgers else pd.DataFrame()
    combined_ledger.to_parquet(output_dir / "trade_ledger.parquet", index=False)
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    (output_dir / "threshold_audit.json").write_text(
        json.dumps(threshold_audit, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    provenance = {
        "created_at": datetime.now(tz=pd.Timestamp.utcnow().tz).isoformat(),
        "frozen_hashes": hashes,
        "code_sha256": sha256_file(Path(__file__)),
        "outputs": {},
    }
    _report(metrics, output_dir)
    for name in ("metrics.json", "threshold_audit.json", "trade_ledger.parquet", "report.md"):
        provenance["outputs"][name] = sha256_file(output_dir / name)
    (output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return metrics


__all__ = [
    "TIMING_MODES",
    "calibrate_v1_thresholds",
    "eligible_decisions",
    "load_event_families",
    "paired_improvement",
    "run_hybrid",
    "verify_frozen_inputs",
]
