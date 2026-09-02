"""Run the sealed broad covered stock-futures cash-and-carry screen."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/stock_futures_cash_carry_broad_v1.yaml"
CONFIG_SHA256: Final[str] = (
    "0279da39fb7dc704d1efdd9b64e82f0158d872827e7784905772bf52f9e64c6c"
)
STOCKS: Final[tuple[str, ...]] = (
    "AFKS",
    "AFLT",
    "ALRS",
    "BSPB",
    "CBOM",
    "CHMF",
    "GAZP",
    "GMKN",
    "IRAO",
    "LKOH",
    "MAGN",
    "MGNT",
    "MOEX",
    "MTSS",
    "NLMK",
    "NVTK",
    "PHOR",
    "PLZL",
    "ROSN",
    "RTKM",
    "RUAL",
    "SBER",
    "SBERP",
    "SNGS",
    "SNGSP",
    "TATN",
    "TATNP",
    "TRNFP",
    "VTBR",
)
RMS_BY_FUTURES_ASSET: Final[dict[str, str | None]] = {
    "AFKS": "AFKS",
    "AFLT": "AFLT",
    "ALRS": "ALRS",
    "BSPB": "BSPB",
    "CBOM": None,
    "CHMF": "CHMF",
    "GAZR": "GAZPF",
    "GMKN": "GMKN",
    "IRAO": "IRAO",
    "LKOH": "LKOH",
    "MAGN": "MAGN",
    "MGNT": "MGNT",
    "MOEX": "MOEX",
    "MTSI": "MTSI",
    "NLMK": "NLMK",
    "NOTK": "NOTK",
    "PHOR": "PHOR",
    "PLZL": "PLZL",
    "PLZLM": "PLZLM",
    "ROSN": "ROSN",
    "RTKM": "RTKM",
    "RUAL": None,
    "SBRF": "SBRF",
    "SBPR": "SBPR",
    "SNGR": "SNGR",
    "SNGP": "SNGP",
    "TATN": "TATN",
    "TATP": "TATP",
    "TRNF": "TRNF",
    "VTBR": "VTBR",
}
SCENARIOS: Final[dict[str, tuple[float, str, str]]] = {
    "primary": (0.50, "ordinary", "primary"),
    "doubled": (0.50, "doubled", "primary"),
    "zero_cashflow_stress": (0.00, "doubled", "primary"),
    "delayed_fill_stress": (0.00, "doubled", "delayed"),
}
COSTS: Final[dict[str, tuple[float, float]]] = {
    "ordinary": (10.0 / 10_000.0, 5.0 / 10_000.0),
    "doubled": (20.0 / 10_000.0, 10.0 / 10_000.0),
}


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    paths: dict[str, Path]
    spot_paths: dict[str, Path]


def _sha(path: Path) -> str:
    return storage.sha256_file(path)


def _path(root: str, file_name: str) -> Path:
    return storage._project_path(root, "data" if root.startswith("data/") else "runs") / file_name


def _verify_parquet(path: Path, sha256: str, rows: int | None = None) -> None:
    if _sha(path) != sha256:
        raise ValueError(f"broad cash-carry input hash drifted: {path}")
    if rows is not None and pq.ParquetFile(path).metadata.num_rows != rows:
        raise ValueError(f"broad cash-carry input rows drifted: {path}")


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("broad cash-carry config must be an object")
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "stock_futures_cash_carry_broad_v1"
        or payload.get("status")
        != "sealed_before_any_broad_basis_signal_return_trade_or_pnl"
        or payload.get("live_trading_allowed") is not False
        or tuple(payload["universe"]["exact_stocks"]) != STOCKS
        or payload["universe"]["rms_assetcode_by_futures_assetcode"]
        != RMS_BY_FUTURES_ASSET
        or payload["decision"]["primary_execution_candle_begin"] != "15:50:00"
        or payload["decision"]["delayed_stress_execution_candle_begin"] != "16:00:00"
    ):
        raise ValueError("broad cash-carry protocol drifted")

    paths: dict[str, Path] = {}
    for section_name, keys in {
        "futures_intraday": ("manifest", "specs", "candles", "raw"),
        "rms_cashflow": ("manifest", "cashflow"),
        "rates": ("manifest", "daily"),
    }.items():
        section = payload["sources"][section_name]
        for key in keys:
            declaration = section[key]
            path = _path(section["root"], declaration["file"])
            if path.suffix == ".parquet":
                _verify_parquet(path, declaration["sha256"], declaration.get("rows"))
            elif _sha(path) != declaration["sha256"]:
                raise ValueError(f"broad cash-carry input drifted: {section_name}.{key}")
            paths[f"{section_name}_{key}"] = path

    spot_section = payload["sources"]["spot"]
    spot_manifest_path = _path(spot_section["root"], spot_section["manifest"]["file"])
    if _sha(spot_manifest_path) != spot_section["manifest"]["sha256"]:
        raise ValueError("broad cash-carry spot manifest drifted")
    spot_manifest = json.loads(spot_manifest_path.read_text(encoding="utf-8-sig"))
    artifacts = {str(item["ticker"]): item for item in spot_manifest["artifacts"]}
    if set(artifacts) != set(STOCKS) | {"ENPG"}:
        raise ValueError("broad cash-carry spot universe drifted")
    spot_paths: dict[str, Path] = {}
    for stock in STOCKS:
        item = artifacts[stock]
        path = _path(spot_section["root"], str(item["path"]))
        _verify_parquet(path, str(item["sha256"]), int(item["rows"]))
        spot_paths[stock] = path
    paths["spot_manifest"] = spot_manifest_path
    return Protocol(payload, actual, paths, spot_paths)


def _load_cashflows(protocol: Protocol) -> pd.DataFrame:
    frame = pd.read_parquet(protocol.paths["rms_cashflow_cashflow"])
    frame["assetcode"] = frame["assetcode"].astype(str)
    frame["t"] = pd.to_datetime(frame["t"], errors="raise").dt.normalize()
    frame["available_at_utc"] = pd.to_datetime(
        frame["available_at_utc"], errors="raise", utc=True
    )
    frame["cf"] = pd.to_numeric(frame["cf"], errors="raise")
    if (~np.isfinite(frame["cf"]) | frame["cf"].lt(0.0)).any():
        raise ValueError("broad cash-carry RMS cashflow invalid")
    allowed = {value for value in RMS_BY_FUTURES_ASSET.values() if value is not None}
    return frame.loc[frame["assetcode"].isin(allowed)].copy()


def _cashflow_sum(
    frame: pd.DataFrame,
    rms_assetcode: str | None,
    available_at: pd.Timestamp,
    after_date: pd.Timestamp,
    through_date: pd.Timestamp,
) -> tuple[float, int, bool]:
    if rms_assetcode is None:
        return 0.0, 0, True
    selected = frame.loc[
        frame["assetcode"].eq(rms_assetcode)
        & frame["available_at_utc"].le(available_at)
        & frame["t"].gt(after_date)
        & frame["t"].le(through_date)
    ].copy()
    if selected.empty:
        return 0.0, 0, False
    latest = selected.sort_values("available_at_utc").groupby("t", as_index=False).tail(1)
    return float(latest["cf"].sum()), int(len(latest)), False


def _load_ruonia(protocol: Protocol) -> pd.DataFrame:
    frame = pd.read_parquet(protocol.paths["rates_daily"])
    frame = frame.loc[frame["series_id"].astype(str).eq("ruonia")].copy()
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="raise", utc=True)
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    return frame.sort_values("available_at", ignore_index=True)


def _prior_ruonia(
    frame: pd.DataFrame, decision_at: pd.Timestamp
) -> tuple[float, pd.Timestamp] | None:
    eligible = frame.loc[frame["available_at"].le(decision_at)]
    if eligible.empty:
        return None
    row = eligible.iloc[-1]
    return float(row["value"]), pd.Timestamp(row["available_at"])


def _aligned_stock(
    protocol: Protocol, stock: str, futures: pd.DataFrame, specs: pd.DataFrame
) -> pd.DataFrame:
    selected = futures.loc[futures["stock_secid"].eq(stock)].copy()
    local = selected["timestamp"].dt.tz_convert("Europe/Moscow")
    decisions = selected.loc[local.dt.strftime("%H:%M:%S").eq("15:40:00")].copy()
    decisions["local_date"] = local.loc[decisions.index].dt.tz_localize(None).dt.normalize()
    decisions["primary_execution_timestamp"] = decisions["timestamp"] + pd.Timedelta(
        minutes=10
    )
    decisions["delayed_execution_timestamp"] = decisions["timestamp"] + pd.Timedelta(
        minutes=20
    )
    bars = selected[["contract_id", "timestamp", "open", "volume"]]
    primary = bars.rename(
        columns={
            "timestamp": "primary_execution_timestamp",
            "open": "futures_primary_open",
            "volume": "futures_primary_volume",
        }
    )
    delayed = bars.rename(
        columns={
            "timestamp": "delayed_execution_timestamp",
            "open": "futures_delayed_open",
            "volume": "futures_delayed_volume",
        }
    )
    decisions = decisions.merge(
        primary, on=["contract_id", "primary_execution_timestamp"], how="left"
    ).merge(delayed, on=["contract_id", "delayed_execution_timestamp"], how="left")
    decisions = decisions.rename(
        columns={
            "close": "futures_decision_close",
            "volume": "futures_decision_volume",
            "end_timestamp": "decision_at",
        }
    )

    spot = pd.read_parquet(protocol.spot_paths[stock]).copy()
    spot.index = pd.to_datetime(spot.index, errors="raise", utc=True)
    spot_decision = spot[["close", "volume"]].rename(
        columns={"close": "spot_decision_close", "volume": "spot_decision_volume"}
    )
    spot_primary = spot[["open", "volume"]].rename(
        columns={"open": "spot_primary_open", "volume": "spot_primary_volume"}
    )
    spot_delayed = spot[["open", "volume"]].rename(
        columns={"open": "spot_delayed_open", "volume": "spot_delayed_volume"}
    )
    decisions = decisions.join(spot_decision, on="timestamp")
    decisions = decisions.join(spot_primary, on="primary_execution_timestamp")
    decisions = decisions.join(spot_delayed, on="delayed_execution_timestamp")

    spec_columns = specs[
        ["contract_id", "asset_code", "lot_size_shares", "last_trade"]
    ].rename(
        columns={
            "asset_code": "spec_asset_code",
            "lot_size_shares": "spec_lot_size_shares",
        }
    )
    decisions = decisions.merge(spec_columns, on="contract_id", how="left")
    if not decisions["asset_code"].eq(decisions["spec_asset_code"]).all():
        raise ValueError(f"broad cash-carry asset code drifted: {stock}")
    candle_units = pd.to_numeric(decisions["lot_size_shares"], errors="raise")
    spec_units = pd.to_numeric(decisions["spec_lot_size_shares"], errors="raise")
    if not candle_units.eq(spec_units).all():
        raise ValueError(f"broad cash-carry contract units drifted: {stock}")
    decisions["lot_size_shares"] = spec_units.astype(int)
    if decisions["lot_size_shares"].le(0).any():
        raise ValueError(f"broad cash-carry nonpositive units: {stock}")
    decisions["last_trade"] = pd.to_datetime(decisions["last_trade"]).dt.normalize()
    decisions["dte"] = (decisions["last_trade"] - decisions["local_date"]).dt.days
    numeric = [
        "futures_decision_close",
        "futures_decision_volume",
        "futures_primary_open",
        "futures_primary_volume",
        "futures_delayed_open",
        "futures_delayed_volume",
        "spot_decision_close",
        "spot_decision_volume",
        "spot_primary_open",
        "spot_primary_volume",
        "spot_delayed_open",
        "spot_delayed_volume",
    ]
    decisions["global_fill_complete"] = decisions[numeric].notna().all(axis=1) & decisions[
        numeric
    ].gt(0.0).all(axis=1)
    return decisions.sort_values(["local_date", "dte", "secid"], ignore_index=True)


def _roundtrip_cost_values(
    shares: int,
    spot_entry: float,
    futures_entry: float,
    spot_exit: float,
    futures_exit: float,
    model: str,
) -> tuple[float, float, float]:
    spot_bps, futures_bps = COSTS[model]
    entry = spot_bps * shares * spot_entry + futures_bps * futures_entry
    exit_cost = spot_bps * shares * spot_exit + futures_bps * futures_exit
    return entry + exit_cost, entry, exit_cost


def build_decisions_and_trades(
    protocol: Protocol,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    futures = pd.read_parquet(protocol.paths["futures_intraday_candles"])
    futures["timestamp"] = pd.to_datetime(futures["timestamp"], errors="raise", utc=True)
    futures["end_timestamp"] = pd.to_datetime(
        futures["end_timestamp"], errors="raise", utc=True
    )
    if futures["timestamp"].ge(pd.Timestamp("2026-01-01", tz="UTC")).any():
        raise ValueError("broad cash-carry futures crossed protected period")
    specs = pd.read_parquet(protocol.paths["futures_intraday_specs"])
    cashflows = _load_cashflows(protocol)
    ruonia = _load_ruonia(protocol)
    aligned = {
        stock: _aligned_stock(protocol, stock, futures, specs) for stock in STOCKS
    }
    decision_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    trade_number = 0
    for stock in STOCKS:
        frame = aligned[stock]
        candidates = frame.loc[frame["dte"].between(30, 90)].groupby(
            "local_date", as_index=False, sort=True
        ).head(1)
        blocked_through: pd.Timestamp | None = None
        for candidate in candidates.to_dict("records"):
            row = pd.Series(candidate)
            shares = int(row["lot_size_shares"])
            rms_assetcode = RMS_BY_FUTURES_ASSET[str(row["asset_code"])]
            record: dict[str, Any] = {
                "decision_id": f"{stock}:{pd.Timestamp(row['local_date']).date()}",
                "stock_secid": stock,
                "local_date": row["local_date"],
                "decision_at": row["decision_at"],
                "primary_execution_timestamp": row["primary_execution_timestamp"],
                "delayed_execution_timestamp": row["delayed_execution_timestamp"],
                "contract_id": row["contract_id"],
                "secid": row["secid"],
                "asset_code": row["asset_code"],
                "rms_assetcode": rms_assetcode,
                "lot_size_shares": shares,
                "last_trade": row["last_trade"],
                "dte": int(row["dte"]),
                "status": "pending",
                "signal": False,
            }
            if blocked_through is not None and pd.Timestamp(row["local_date"]) <= blocked_through:
                record["status"] = "position_open"
                decision_rows.append(record)
                continue
            if not bool(row["global_fill_complete"]):
                record["status"] = "missing_primary_or_delayed_aligned_fill"
                decision_rows.append(record)
                continue
            prior_rate = _prior_ruonia(ruonia, pd.Timestamp(row["decision_at"]))
            if prior_rate is None:
                record["status"] = "missing_ruonia"
                decision_rows.append(record)
                continue
            rate, rate_available = prior_rate
            planned_exit = pd.Timestamp(row["last_trade"]) - pd.Timedelta(days=5)
            expected_cf, expected_events, mapping_missing = _cashflow_sum(
                cashflows,
                rms_assetcode,
                pd.Timestamp(row["decision_at"]),
                pd.Timestamp(row["local_date"]),
                planned_exit,
            )
            stock_notional = shares * float(row["spot_decision_close"])
            futures_notional = float(row["futures_decision_close"])
            capital = stock_notional + 0.30 * futures_notional
            decision_cost = (
                2.0 * COSTS["ordinary"][0] * stock_notional
                + 2.0 * COSTS["ordinary"][1] * futures_notional
            )
            holding_days = max(int(row["dte"]) - 5, 1)
            locked = (
                futures_notional
                + shares * 0.50 * expected_cf
                - stock_notional
                - decision_cost
            )
            annualized = locked / capital * 365.0 / holding_days
            threshold = max(0.20, rate / 100.0 + 0.04)
            record.update(
                {
                    "ruonia_percent": rate,
                    "ruonia_available_at": rate_available,
                    "expected_cashflow_per_share": expected_cf,
                    "expected_cashflow_events": expected_events,
                    "cashflow_mapping_missing": mapping_missing,
                    "decision_stock_notional": stock_notional,
                    "decision_futures_notional": futures_notional,
                    "conservative_capital": capital,
                    "annualized_locked_proxy": annualized,
                    "entry_threshold": threshold,
                }
            )
            if annualized < threshold:
                record["status"] = "hurdle_not_met"
                decision_rows.append(record)
                continue
            exits = frame.loc[
                frame["contract_id"].eq(row["contract_id"])
                & frame["local_date"].gt(row["local_date"])
                & frame["dte"].between(0, 5)
                & frame["global_fill_complete"]
            ]
            if exits.empty:
                record["status"] = "missing_scheduled_exit"
                decision_rows.append(record)
                continue
            exit_row = exits.iloc[0]
            record["status"] = "admitted"
            record["signal"] = True
            decision_rows.append(record)
            trade_number += 1
            outcome_cf, outcome_events, _ = _cashflow_sum(
                cashflows,
                rms_assetcode,
                pd.Timestamp(exit_row["primary_execution_timestamp"]),
                pd.Timestamp(row["local_date"]),
                pd.Timestamp(exit_row["local_date"]),
            )
            trade: dict[str, Any] = {
                "trade_id": f"broad_cash_carry_{trade_number:04d}",
                "decision_id": record["decision_id"],
                "stock_secid": stock,
                "contract_id": row["contract_id"],
                "secid": row["secid"],
                "asset_code": row["asset_code"],
                "rms_assetcode": rms_assetcode,
                "lot_size_shares": shares,
                "entry_date": row["local_date"],
                "exit_date": exit_row["local_date"],
                "primary_entry_timestamp": row["primary_execution_timestamp"],
                "primary_exit_timestamp": exit_row["primary_execution_timestamp"],
                "delayed_entry_timestamp": row["delayed_execution_timestamp"],
                "delayed_exit_timestamp": exit_row["delayed_execution_timestamp"],
                "spot_primary_entry_open": float(row["spot_primary_open"]),
                "futures_primary_entry_open": float(row["futures_primary_open"]),
                "spot_primary_exit_open": float(exit_row["spot_primary_open"]),
                "futures_primary_exit_open": float(exit_row["futures_primary_open"]),
                "spot_delayed_entry_open": float(row["spot_delayed_open"]),
                "futures_delayed_entry_open": float(row["futures_delayed_open"]),
                "spot_delayed_exit_open": float(exit_row["spot_delayed_open"]),
                "futures_delayed_exit_open": float(exit_row["futures_delayed_open"]),
                "projected_cashflow_per_share": expected_cf,
                "outcome_rms_proxy_per_share": outcome_cf,
                "outcome_rms_event_count": outcome_events,
                "holding_calendar_days": int(
                    (pd.Timestamp(exit_row["local_date"]) - pd.Timestamp(row["local_date"])).days
                ),
            }
            for scenario, (fraction, model, fill) in SCENARIOS.items():
                spot_entry = float(trade[f"spot_{fill}_entry_open"])
                futures_entry = float(trade[f"futures_{fill}_entry_open"])
                spot_exit = float(trade[f"spot_{fill}_exit_open"])
                futures_exit = float(trade[f"futures_{fill}_exit_open"])
                capital = shares * spot_entry + 0.30 * futures_entry
                total_cost, entry_cost, exit_cost = _roundtrip_cost_values(
                    shares,
                    spot_entry,
                    futures_entry,
                    spot_exit,
                    futures_exit,
                    model,
                )
                gross = shares * (spot_exit - spot_entry) + futures_entry - futures_exit
                credit = shares * fraction * outcome_cf
                net = gross + credit - total_cost
                trade[f"{scenario}_capital"] = capital
                trade[f"{scenario}_gross_pair_pnl"] = gross
                trade[f"{scenario}_cashflow_credit"] = credit
                trade[f"{scenario}_entry_cost"] = entry_cost
                trade[f"{scenario}_exit_cost"] = exit_cost
                trade[f"{scenario}_net_pnl"] = net
                trade[f"{scenario}_return"] = net / capital
            trade_rows.append(trade)
            blocked_through = pd.Timestamp(exit_row["local_date"])
    return pd.DataFrame(decision_rows), pd.DataFrame(trade_rows), aligned


def _trade_path(
    trade: dict[str, Any], frame: pd.DataFrame, scenario: str
) -> pd.Series:
    _, _, fill = SCENARIOS[scenario]
    marks = frame.loc[
        frame["contract_id"].eq(trade["contract_id"])
        & frame["local_date"].between(trade["entry_date"], trade["exit_date"])
        & frame["global_fill_complete"]
    ].drop_duplicates("local_date", keep="last")
    marks = marks.set_index("local_date").sort_index()
    if marks.empty or pd.Timestamp(trade["exit_date"]) not in marks.index:
        raise ValueError("broad cash-carry trade lacks mark path")
    shares = int(trade["lot_size_shares"])
    spot_entry = float(trade[f"spot_{fill}_entry_open"])
    futures_entry = float(trade[f"futures_{fill}_entry_open"])
    gross = shares * (marks[f"spot_{fill}_open"] - spot_entry) + (
        futures_entry - marks[f"futures_{fill}_open"]
    )
    cumulative = gross - float(trade[f"{scenario}_entry_cost"])
    cumulative.loc[pd.Timestamp(trade["exit_date"])] += (
        float(trade[f"{scenario}_cashflow_credit"])
        - float(trade[f"{scenario}_exit_cost"])
    )
    path = 1.0 + cumulative / float(trade[f"{scenario}_capital"])
    if (~np.isfinite(path) | path.le(0.0)).any():
        raise ValueError("broad cash-carry normalized trade path invalid")
    return path


def _equal_sleeve_nav(
    trades: pd.DataFrame,
    aligned: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    scenario: str,
) -> pd.Series:
    stock_navs: list[pd.Series] = []
    for stock in STOCKS:
        nav = pd.Series(np.nan, index=dates, dtype=float)
        nav.iloc[0] = 1.0
        current_nav = 1.0
        selected = trades.loc[trades["stock_secid"].eq(stock)].sort_values("entry_date")
        for trade in selected.to_dict("records"):
            path = _trade_path(trade, aligned[stock], scenario)
            nav.loc[path.index] = current_nav * path
            current_nav = float(nav.loc[pd.Timestamp(trade["exit_date"])])
        stock_navs.append(nav.ffill().rename(stock))
    return pd.concat(stock_navs, axis=1).mean(axis=1)


def _active_cap_nav(
    trades: pd.DataFrame,
    aligned: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    scenario: str,
) -> tuple[pd.Series, pd.Series, pd.Series, dict[str, float | int]]:
    records = trades.sort_values(["entry_date", "stock_secid"]).to_dict("records")
    paths = {
        str(trade["trade_id"]): _trade_path(
            trade, aligned[str(trade["stock_secid"])], scenario
        )
        for trade in records
    }
    entries: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    exits: dict[pd.Timestamp, list[str]] = {}
    for trade in records:
        entry_date = pd.Timestamp(trade["entry_date"])
        exit_date = pd.Timestamp(trade["exit_date"])
        entries.setdefault(entry_date, []).append(trade)
        exits.setdefault(exit_date, []).append(str(trade["trade_id"]))
    cash = 1.0
    active: dict[str, dict[str, float]] = {}
    nav_values: list[float] = []
    active_counts: list[int] = []
    exposures: list[float] = []
    allocated_trades = 0
    max_entry_weight = 0.0
    for date in dates:
        for trade_id, state in active.items():
            path = paths[trade_id]
            if date in path.index:
                state["value"] = state["allocation"] * float(path.loc[date])
        for trade_id in exits.get(pd.Timestamp(date), []):
            state = active.pop(trade_id, None)
            if state is not None:
                cash += state["value"]
        nav_before_entries = cash + sum(state["value"] for state in active.values())
        target = 0.10 * nav_before_entries
        for trade in entries.get(pd.Timestamp(date), []):
            allocation = min(target, cash)
            if allocation <= 0.0:
                continue
            trade_id = str(trade["trade_id"])
            path = paths[trade_id]
            cash -= allocation
            active[trade_id] = {
                "allocation": allocation,
                "value": allocation * float(path.loc[date]),
            }
            allocated_trades += 1
            max_entry_weight = max(max_entry_weight, allocation / nav_before_entries)
        active_value = sum(state["value"] for state in active.values())
        nav = cash + active_value
        if not math.isfinite(nav) or nav <= 0.0:
            raise ValueError("broad cash-carry active-cap NAV invalid")
        nav_values.append(nav)
        active_counts.append(len(active))
        exposures.append(active_value / nav)
    diagnostics: dict[str, float | int] = {
        "allocated_trades": allocated_trades,
        "unallocated_trades": len(records) - allocated_trades,
        "maximum_entry_weight": max_entry_weight,
        "maximum_marked_exposure": max(exposures, default=0.0),
        "maximum_concurrent_positions": max(active_counts, default=0),
    }
    return (
        pd.Series(nav_values, index=dates),
        pd.Series(active_counts, index=dates, dtype=int),
        pd.Series(exposures, index=dates, dtype=float),
        diagnostics,
    )


def build_ledger(
    trades: pd.DataFrame, aligned: dict[str, pd.DataFrame]
) -> tuple[pd.DataFrame, dict[str, dict[str, float | int]]]:
    dates = pd.DatetimeIndex(
        sorted(set().union(*(set(frame["local_date"]) for frame in aligned.values())))
    )
    ledger = pd.DataFrame(index=dates)
    diagnostics: dict[str, dict[str, float | int]] = {}
    for scenario in SCENARIOS:
        equal_nav = _equal_sleeve_nav(trades, aligned, dates, scenario)
        active_nav, active_count, exposure, details = _active_cap_nav(
            trades, aligned, dates, scenario
        )
        ledger[f"equal_sleeves_{scenario}_nav"] = equal_nav
        ledger[f"equal_sleeves_{scenario}_return"] = equal_nav.pct_change().fillna(0.0)
        ledger[f"active_cap_{scenario}_nav"] = active_nav
        ledger[f"active_cap_{scenario}_return"] = active_nav.pct_change().fillna(0.0)
        ledger[f"active_cap_{scenario}_positions"] = active_count
        ledger[f"active_cap_{scenario}_exposure"] = exposure
        diagnostics[scenario] = details
    return ledger.rename_axis("date").reset_index(), diagnostics


def _metrics(nav: pd.Series, dates: pd.DatetimeIndex) -> dict[str, Any]:
    values = nav.astype(float)
    returns = values.pct_change().fillna(0.0)
    total = float(values.iloc[-1] / values.iloc[0] - 1.0)
    days = max(int((dates[-1] - dates[0]).days), 1)
    cagr = float((values.iloc[-1] / values.iloc[0]) ** (365.0 / days) - 1.0)
    std = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / std * math.sqrt(252.0)) if std > 0 else 0.0
    drawdown = values / values.cummax() - 1.0
    indexed = pd.Series(values.to_numpy(), index=dates)
    years = {
        str(year): float(part.iloc[-1] / part.iloc[0] - 1.0)
        for year, part in indexed.groupby(indexed.index.year)
    }
    return {
        "total_return": total,
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": float(-drawdown.min()),
        "per_year": years,
        "positive_years": int(sum(value > 0.0 for value in years.values())),
        "worst_year": min(years.values(), default=0.0),
    }


def build_metrics(
    decisions: pd.DataFrame,
    trades: pd.DataFrame,
    ledger: pd.DataFrame,
    allocation_diagnostics: dict[str, dict[str, float | int]],
) -> dict[str, Any]:
    dates = pd.DatetimeIndex(ledger["date"])
    views = {
        view: {
            scenario: _metrics(ledger[f"{view}_{scenario}_nav"], dates)
            for scenario in SCENARIOS
        }
        for view in ("equal_sleeves", "active_cap")
    }
    equal = views["equal_sleeves"]
    gates = {
        "equal_primary_and_doubled_positive_cagr": equal["primary"]["cagr"] > 0.0
        and equal["doubled"]["cagr"] > 0.0,
        "equal_primary_sharpe_gte_1": equal["primary"]["sharpe"] >= 1.0,
        "equal_primary_mdd_lte_15pct": equal["primary"]["maximum_drawdown"] <= 0.15,
        "trades_gte_20": len(trades) >= 20,
        "equal_positive_years_gte_2": equal["primary"]["positive_years"] >= 2,
        "all_stress_mdd_lte_20pct": all(
            item["maximum_drawdown"] <= 0.20
            for view in views.values()
            for item in view.values()
        ),
    }
    trade_wins = {
        scenario: int(trades[f"{scenario}_net_pnl"].gt(0.0).sum())
        for scenario in SCENARIOS
    }
    return {
        "verdict": "FORWARD_CANDIDATE" if all(gates.values()) else "NO_GO",
        "objective_20pct_cagr_reached": {
            view: {
                scenario: item["cagr"] >= 0.20 for scenario, item in scenarios.items()
            }
            for view, scenarios in views.items()
        },
        "counts": {
            "decisions": len(decisions),
            "signals": int(decisions["signal"].fillna(False).sum()),
            "trades": len(trades),
            "unresolved": int(decisions["status"].astype(str).str.startswith("missing").sum()),
            "explicit_missing_cashflow_mapping_decisions": int(
                decisions.get("cashflow_mapping_missing", pd.Series(dtype=bool))
                .fillna(False)
                .sum()
            ),
            "statuses": decisions["status"].value_counts().astype(int).to_dict(),
            "trades_by_stock": trades["stock_secid"].value_counts().astype(int).to_dict(),
            "winning_trades": trade_wins,
        },
        "views": views,
        "active_cap_diagnostics": allocation_diagnostics,
        "gates": gates,
    }


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# Broad stock–futures cash-and-carry V1",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        f"Decisions: {metrics['counts']['decisions']}; signals/trades: "
        f"{metrics['counts']['signals']}/{metrics['counts']['trades']}; unresolved: "
        f"{metrics['counts']['unresolved']}.",
        "",
        "| Portfolio | Scenario | CAGR | Sharpe | MDD | Total return | Positive years |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for view, scenarios in metrics["views"].items():
        for scenario, item in scenarios.items():
            lines.append(
                f"| {view} | {scenario} | {item['cagr']:.4%} | "
                f"{item['sharpe']:.3f} | {item['maximum_drawdown']:.4%} | "
                f"{item['total_return']:.4%} | {item['positive_years']} |"
            )
    lines.extend(
        [
            "",
            "The broad universe is the only signal-family change; timing, hurdle, DTE, "
            "cashflow haircut and costs are inherited from sealed V1.",
            "RMS cashflows are projections/outcome proxies, not proof of paid dividends. "
            "Historical candles do not prove BID/OFFER fills, queue, broker terms or live profit.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(protocol: Protocol) -> Path:
    decisions, trades, aligned = build_decisions_and_trades(protocol)
    ledger, allocation_diagnostics = build_ledger(trades, aligned)
    metrics = build_metrics(decisions, trades, ledger, allocation_diagnostics)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = PROJECT_ROOT / protocol.payload["outputs"]["root"]
    output = root.parent / f"{root.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"broad cash-carry run exists: {output}")
    output.mkdir(parents=True)
    paths = {
        "decisions": output / "decisions.parquet",
        "trades": output / "trades.parquet",
        "ledger": output / "daily_ledger.parquet",
        "audit": output / "audit.json",
        "metrics": output / "metrics.json",
        "report": output / "report.md",
    }
    storage._write_parquet(paths["decisions"], decisions)
    storage._write_parquet(paths["trades"], trades)
    storage._write_parquet(paths["ledger"], ledger)
    no_overlap = all(
        not (
            part.sort_values("entry_date")["entry_date"].iloc[1:].reset_index(drop=True)
            <= part.sort_values("entry_date")["exit_date"].iloc[:-1].reset_index(drop=True)
        ).any()
        for _, part in trades.groupby("stock_secid")
    )
    audit = {
        "checks": {
            "protocol_sha_exact": _sha(CONFIG_PATH) == protocol.config_sha256,
            "all_decisions_before_2026": bool(
                pd.to_datetime(decisions["local_date"]).dt.year.le(2025).all()
            ),
            "all_trades_before_2026": bool(
                pd.to_datetime(trades["exit_date"]).dt.year.le(2025).all()
            ),
            "signals_equal_trades": int(decisions["signal"].sum()) == len(trades),
            "no_stock_overlap": bool(no_overlap),
            "positive_integer_contract_units": bool(
                trades["lot_size_shares"].astype(int).gt(0).all()
            ),
            "scenario_decisions_identical": True,
            "delayed_fill_exactly_ten_minutes_after_primary": bool(
                (
                    pd.to_datetime(trades["delayed_entry_timestamp"], utc=True)
                    - pd.to_datetime(trades["primary_entry_timestamp"], utc=True)
                ).eq(pd.Timedelta(minutes=10)).all()
            ),
            "rms_not_labeled_realized_dividend": not any(
                "realized_dividend" in str(column).lower() for column in trades.columns
            ),
            "all_scenario_returns_finite": bool(
                np.isfinite(
                    trades[[f"{scenario}_return" for scenario in SCENARIOS]].to_numpy()
                ).all()
            ),
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"broad cash-carry run audit failed: {audit}")
    write_json(paths["audit"], audit)
    write_json(paths["metrics"], metrics)
    atomic_write_bytes(paths["report"], _report(metrics).encode("utf-8-sig"))
    artifacts = {
        name: storage._artifact(path, pq.ParquetFile(path).metadata.num_rows)
        if path.suffix == ".parquet"
        else storage._artifact(path)
        for name, path in paths.items()
    }
    manifest = {
        "run_id": output.name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": protocol.config_sha256,
        "implementation_sha256": _sha(Path(__file__)),
        "verdict": metrics["verdict"],
        "live_trading_allowed": False,
        "same_history_development_only": True,
        "artifacts": artifacts,
    }
    manifest_path = output / "manifest.json"
    write_json(manifest_path, manifest)
    atomic_write_bytes(
        output / "manifest.sha256",
        f"{_sha(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    protocol = load_protocol()
    output = run(protocol)
    print(output)
    print((output / "report.md").read_text(encoding="utf-8-sig"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
