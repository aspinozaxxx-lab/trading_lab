"""Run the sealed dividend-revision calendar-spread convergence experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures import moex_dividend_calendar_spread_source as source
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/dividend_calendar_spread_v1.yaml"
CONFIG_SHA256: Final[str] = (
    "52a8ce0609efff665b1a185c09a7caeebbd98186120b277f771d8f79f4b8793d"
)
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
ASSETS: Final[tuple[str, ...]] = source.ASSETS
SCENARIO_COSTS: Final[dict[str, float]] = {
    "primary": 2.0,
    "doubled": 4.0,
    "stress": 8.0,
}
EVENT_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "asset",
    "spread_id",
    "signal_date",
    "near_expiration",
    "far_expiration",
    "previous_midpoint",
    "current_midpoint",
    "previous_cashflow_points",
    "current_cashflow_points",
    "cashflow_change",
    "fair_target",
    "residual",
    "direction",
    "cashflow_state_date",
    "previous_cashflow_state_date",
)
TRADE_COLUMNS: Final[tuple[str, ...]] = (
    "trade_id",
    "event_id",
    "asset",
    "spread_id",
    "direction",
    "signal_date",
    "entry_date",
    "exit_date",
    "fair_target",
    "entry_fill",
    "exit_fill",
    "initial_target_edge",
    "holding_observations",
    "exit_reason",
    "gross_points",
    "primary_net_points",
    "doubled_net_points",
    "stress_net_points",
)


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    paths: dict[str, Path]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"dividend spread V1 {label} must be a mapping")
    return value


def _project_path(root: str, file: str | None = None) -> Path:
    relative = Path(root)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe dividend spread V1 path: {root}")
    path = PROJECT_ROOT / relative
    return path if file is None else path / file


def load_protocol() -> Protocol:
    actual = sha256_file(CONFIG_PATH)
    sidecar = CONFIG_PATH.with_suffix(".sha256")
    declared = sidecar.read_text(encoding="utf-8-sig").split()[0].lower()
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("dividend spread V1 config must be an object")
    inputs = _mapping(payload.get("inputs"), "inputs")
    scenarios = _mapping(payload.get("cost_scenarios_quote_points_round_trip"), "costs")
    validation = _mapping(payload.get("validation"), "validation")
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "dividend_calendar_spread_economic_v1"
        or payload.get("sealed_before_outcomes") is not True
        or payload.get("live_trading_allowed") is not False
        or payload["hypothesis"]["strategy_count"] != 1
        or payload["hypothesis"]["parameter_search"] is not False
        or {key: float(scenarios[key]) for key in SCENARIO_COSTS} != SCENARIO_COSTS
        or int(payload["execution_proxy"]["maximum_holding_observations"]) != 10
        or int(payload["execution_proxy"]["forced_exit_days_to_near_expiration"])
        != 4
        or int(validation["minimum_completed_primary_trades"]) != 20
    ):
        raise ValueError("dividend spread V1 protocol invariant drifted")
    spread_root = _project_path(str(inputs["spread_root"]))
    cashflow_root = _project_path(str(inputs["cashflow_root"]))
    paths = {
        "spread_manifest": spread_root / str(inputs["spread_manifest"]["file"]),
        "catalog": spread_root / str(inputs["catalog"]["file"]),
        "archive_daily": spread_root / str(inputs["archive_daily"]["file"]),
        "raw_responses": spread_root / str(inputs["raw_responses"]["file"]),
        "cashflow": cashflow_root / str(inputs["cashflow"]["file"]),
        "cashflow_manifest": cashflow_root / str(inputs["cashflow_manifest"]["file"]),
        "cashflow_audit": cashflow_root / str(inputs["cashflow_audit"]["file"]),
    }
    for name, path in paths.items():
        declaration = inputs[name]
        if sha256_file(path) != str(declaration["sha256"]):
            raise ValueError(f"dividend spread V1 input drifted: {name}")
        if (
            "rows" in declaration
            and path.suffix == ".parquet"
            and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
        ):
            raise ValueError(f"dividend spread V1 row count drifted: {name}")
    source_protocol = source.load_protocol()
    source_audit = source.audit_bundle(source_protocol)
    if not all(source_audit.checks.values()):
        raise ValueError("dividend spread source audit is not exact")
    return Protocol(payload=payload, config_sha256=actual, paths=paths)


def _eligible_archive(protocol: Protocol) -> pd.DataFrame:
    frame = pd.read_parquet(protocol.paths["archive_daily"])
    for column in ("trade_date", "near_expiration", "far_expiration"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="raise", utc=True)
    if frame["trade_date"].ge(PROTECTED_FROM).any():
        raise ValueError("dividend spread archive crossed protected boundary")
    if frame.duplicated(["trade_date", "spread_id"]).any():
        raise ValueError("dividend spread archive identity duplicated")
    numeric = ("bid", "ask", "amount", "volume", "num_trades")
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    eligible = (
        frame["two_sided_quote_fields_complete"].astype(bool)
        & ~frame["closing_quote_crossed"].astype(bool)
        & frame["reported_trade_activity"].astype(bool)
        & frame["inside_iss_request_interval"].astype(bool)
        & frame["inside_series_interval"].astype(bool)
        & frame["bid"].notna()
        & frame["ask"].notna()
        & np.isfinite(frame["bid"])
        & np.isfinite(frame["ask"])
        & frame["ask"].gt(frame["bid"])
    )
    result = frame.loc[eligible].copy()
    result["midpoint"] = (result["bid"] + result["ask"]) / 2.0
    return result.sort_values(
        ["logical_asset", "trade_date", "near_expiration", "spread_id"],
        kind="stable",
        ignore_index=True,
    )


def _cashflow_snapshots(protocol: Protocol) -> dict[str, list[dict[str, Any]]]:
    frame = pd.read_parquet(protocol.paths["cashflow"])
    frame = frame.loc[frame["assetcode"].astype(str).isin(ASSETS)].copy()
    frame["tradedate"] = pd.to_datetime(frame["tradedate"], errors="raise").dt.normalize()
    frame["t"] = pd.to_datetime(frame["t"], errors="raise").dt.normalize()
    frame["available_at_utc"] = pd.to_datetime(
        frame["available_at_utc"], errors="raise", utc=True
    )
    for column in ("cf", "cfrisk"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if (~np.isfinite(frame[column]) | frame[column].lt(0.0)).any():
            raise ValueError(f"invalid anticipated cashflow field: {column}")
    if frame["tradedate"].ge(PROTECTED_FROM).any() or frame["t"].isna().any():
        raise ValueError("invalid or protected cashflow state")
    snapshots: dict[str, list[dict[str, Any]]] = {asset: [] for asset in ASSETS}
    group_columns = ["assetcode", "tradedate", "updatetime", "available_at_utc"]
    for key, part in frame.groupby(group_columns, sort=True, dropna=False):
        asset, tradedate, updatetime, available = key
        snapshots[str(asset)].append(
            {
                "tradedate": pd.Timestamp(tradedate),
                "updatetime": str(updatetime),
                "available_at": pd.Timestamp(available),
                "rows": part[["t", "cf", "cfrisk"]].copy(),
            }
        )
    for asset in ASSETS:
        snapshots[asset].sort(
            key=lambda item: (item["tradedate"], item["available_at"], item["updatetime"])
        )
    return snapshots


def _latest_prior_snapshot(
    snapshots: list[dict[str, Any]], trade_date: pd.Timestamp
) -> dict[str, Any] | None:
    eligible = [item for item in snapshots if item["tradedate"] < trade_date]
    return eligible[-1] if eligible else None


def _between_cashflow(
    snapshot: dict[str, Any], near: pd.Timestamp, far: pd.Timestamp
) -> float:
    rows = snapshot["rows"]
    selected = rows.loc[rows["t"].gt(near) & rows["t"].le(far)]
    return float((selected["cf"] * selected["cfrisk"]).sum())


def build_events(protocol: Protocol) -> tuple[pd.DataFrame, pd.DataFrame]:
    quotes = _eligible_archive(protocol)
    snapshots = _cashflow_snapshots(protocol)
    records: list[dict[str, Any]] = []
    for spread_id, part in quotes.groupby("spread_id", sort=True):
        part = part.sort_values("trade_date", kind="stable")
        previous: dict[str, Any] | None = None
        for row in part.to_dict("records"):
            asset = str(row["logical_asset"])
            snapshot = _latest_prior_snapshot(snapshots[asset], pd.Timestamp(row["trade_date"]))
            if snapshot is None:
                previous = None
                continue
            cashflow_points = _between_cashflow(
                snapshot,
                pd.Timestamp(row["near_expiration"]),
                pd.Timestamp(row["far_expiration"]),
            )
            current = {**row, "snapshot": snapshot, "cashflow_points": cashflow_points}
            if previous is not None:
                change = cashflow_points - float(previous["cashflow_points"])
                if not math.isclose(change, 0.0, abs_tol=1e-12):
                    target = float(previous["midpoint"]) - change
                    residual = float(row["midpoint"]) - target
                    if not math.isclose(residual, 0.0, abs_tol=1e-12):
                        event_id = f"{asset}:{spread_id}:{pd.Timestamp(row['trade_date']).date()}"
                        records.append(
                            {
                                "event_id": event_id,
                                "asset": asset,
                                "spread_id": spread_id,
                                "signal_date": row["trade_date"],
                                "near_expiration": row["near_expiration"],
                                "far_expiration": row["far_expiration"],
                                "previous_midpoint": previous["midpoint"],
                                "current_midpoint": row["midpoint"],
                                "previous_cashflow_points": previous["cashflow_points"],
                                "current_cashflow_points": cashflow_points,
                                "cashflow_change": change,
                                "fair_target": target,
                                "residual": residual,
                                "direction": -1 if residual > 0.0 else 1,
                                "cashflow_state_date": snapshot["tradedate"],
                                "previous_cashflow_state_date": previous["snapshot"][
                                    "tradedate"
                                ],
                            }
                        )
            previous = current
    events = pd.DataFrame(records, columns=EVENT_COLUMNS)
    if not events.empty:
        events = events.sort_values(
            ["signal_date", "asset", "near_expiration", "spread_id"],
            kind="stable",
            ignore_index=True,
        )
    return events, quotes


def execute_events(events: pd.DataFrame, quotes: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    quote_groups = {
        str(key): part.sort_values("trade_date", kind="stable", ignore_index=True)
        for key, part in quotes.groupby("spread_id", sort=False)
    }
    last_exit: dict[str, pd.Timestamp] = {}
    blocked_assets: set[str] = set()
    trades: list[dict[str, Any]] = []
    unresolved = 0
    for event in events.to_dict("records"):
        asset = str(event["asset"])
        if asset in blocked_assets:
            continue
        future = quote_groups[str(event["spread_id"])]
        future = future.loc[future["trade_date"].gt(pd.Timestamp(event["signal_date"]))]
        if future.empty:
            continue
        entry = future.iloc[0]
        if asset in last_exit and pd.Timestamp(entry["trade_date"]) <= last_exit[asset]:
            continue
        direction = int(event["direction"])
        target = float(event["fair_target"])
        entry_fill = float(entry["ask"] if direction > 0 else entry["bid"])
        edge = direction * (target - entry_fill)
        if edge <= 0.0:
            continue
        later = future.loc[future["trade_date"].gt(pd.Timestamp(entry["trade_date"]))]
        exit_row: pd.Series | None = None
        exit_reason: str | None = None
        holding = 0
        for _, row in later.iterrows():
            holding += 1
            executable = float(row["bid"] if direction > 0 else row["ask"])
            gross = direction * (executable - entry_fill)
            target_reached = executable >= target if direction > 0 else executable <= target
            if target_reached:
                exit_row, exit_reason = row, "fair_target"
                break
            if gross <= -2.0 * edge:
                exit_row, exit_reason = row, "two_edge_adverse_stop"
                break
            days_to_near = (pd.Timestamp(event["near_expiration"]) - row["trade_date"]).days
            if days_to_near <= 4:
                exit_row, exit_reason = row, "expiry_buffer"
                break
            if holding >= 10:
                exit_row, exit_reason = row, "maximum_holding"
                break
        if exit_row is None or exit_reason is None:
            unresolved += 1
            blocked_assets.add(asset)
            continue
        exit_fill = float(exit_row["bid"] if direction > 0 else exit_row["ask"])
        gross_points = direction * (exit_fill - entry_fill)
        trade_id = f"{asset}:{len(trades):05d}"
        record = {
            "trade_id": trade_id,
            "event_id": event["event_id"],
            "asset": asset,
            "spread_id": event["spread_id"],
            "direction": direction,
            "signal_date": event["signal_date"],
            "entry_date": entry["trade_date"],
            "exit_date": exit_row["trade_date"],
            "fair_target": target,
            "entry_fill": entry_fill,
            "exit_fill": exit_fill,
            "initial_target_edge": edge,
            "holding_observations": holding,
            "exit_reason": exit_reason,
            "gross_points": gross_points,
        }
        for scenario, cost in SCENARIO_COSTS.items():
            record[f"{scenario}_net_points"] = gross_points - cost
        trades.append(record)
        last_exit[asset] = pd.Timestamp(exit_row["trade_date"])
    return pd.DataFrame(trades, columns=TRADE_COLUMNS), unresolved


def _scenario_metrics(trades: pd.DataFrame, scenario: str) -> dict[str, Any]:
    column = f"{scenario}_net_points"
    values = trades[column].astype(float) if not trades.empty else pd.Series(dtype=float)
    return {
        "trades": int(len(trades)),
        "gross_points": float(trades["gross_points"].sum()) if not trades.empty else 0.0,
        "net_points": float(values.sum()),
        "mean_net_points": float(values.mean()) if len(values) else None,
        "median_net_points": float(values.median()) if len(values) else None,
        "win_rate": float(values.gt(0.0).mean()) if len(values) else None,
        "by_asset": {
            asset: float(trades.loc[trades["asset"].eq(asset), column].sum())
            for asset in ASSETS
        },
        "by_exit_year": {
            str(year): float(group[column].sum())
            for year, group in trades.groupby(trades["exit_date"].dt.year, sort=True)
        }
        if not trades.empty
        else {},
    }


def build_metrics(
    events: pd.DataFrame, trades: pd.DataFrame, unresolved: int
) -> dict[str, Any]:
    if not trades.empty:
        for column in ("signal_date", "entry_date", "exit_date"):
            trades[column] = pd.to_datetime(trades[column], errors="raise").dt.normalize()
    evaluation = trades.loc[
        trades["exit_date"].between("2025-01-01", "2025-12-31")
    ] if not trades.empty else trades.copy()
    full = {name: _scenario_metrics(trades, name) for name in SCENARIO_COSTS}
    eval_metrics = {name: _scenario_metrics(evaluation, name) for name in SCENARIO_COSTS}
    primary_eval = eval_metrics["primary"]
    primary_full = full["primary"]
    gates = {
        "minimum_20_evaluation_trades": len(evaluation) >= 20,
        "primary_evaluation_positive": primary_eval["net_points"] > 0.0,
        "doubled_evaluation_positive": eval_metrics["doubled"]["net_points"] > 0.0,
        "stress_evaluation_positive": eval_metrics["stress"]["net_points"] > 0.0,
        "four_positive_evaluation_assets": sum(
            value > 0.0 for value in primary_eval["by_asset"].values()
        )
        >= 4,
        "two_positive_full_history_exit_years": sum(
            value > 0.0 for value in primary_full["by_exit_year"].values()
        )
        >= 2,
        "positive_evaluation_median_trade": (
            primary_eval["median_net_points"] is not None
            and primary_eval["median_net_points"] > 0.0
        ),
        "zero_unresolved": unresolved == 0,
    }
    return {
        "protocol_sha256": CONFIG_SHA256,
        "counts": {
            "cashflow_change_events": int(len(events)),
            "completed_trades": int(len(trades)),
            "evaluation_trades": int(len(evaluation)),
            "unresolved_positions": int(unresolved),
        },
        "full_history": full,
        "temporal_evaluation_2025": eval_metrics,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "verdict": (
            "CANDIDATE_FOR_EXACT_EXECUTION_AND_FORWARD_VALIDATION"
            if all(gates.values())
            else "NO_GO"
        ),
        "cagr_or_ruble_return_reported": False,
        "live_trading_allowed": False,
    }


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    try:
        frame.to_parquet(temporary_name, index=False, compression="zstd")
        Path(temporary_name).replace(path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if rows is not None:
        value["rows"] = int(rows)
    return value


def _accounting_replay_exact(trades: pd.DataFrame) -> bool:
    if trades.empty:
        return True
    return all(
        np.allclose(
            trades[f"{scenario}_net_points"].to_numpy(dtype=float),
            trades["gross_points"].to_numpy(dtype=float) - cost,
        )
        for scenario, cost in SCENARIO_COSTS.items()
    )


def _report(metrics: Mapping[str, Any]) -> str:
    evaluation = metrics["temporal_evaluation_2025"]
    lines = [
        "# Dividend calendar spread V1",
        "",
        f"Verdict: `{metrics['verdict']}`.",
        "",
        "The result is quote-point evidence only; CAGR and live profitability are not reported.",
        "",
        "| Scenario | 2025 trades | 2025 net points | Median/trade |",
        "|---|---:|---:|---:|",
    ]
    for scenario in SCENARIO_COSTS:
        item = evaluation[scenario]
        median = item["median_net_points"]
        lines.append(
            f"| {scenario} | {item['trades']} | {item['net_points']:.6f} | "
            f"{median if median is not None else 'n/a'} |"
        )
    lines.extend(["", "Gates:"])
    lines.extend(
        f"- {name}: {str(value).lower()}" for name, value in metrics["gates"].items()
    )
    return "\n".join(lines) + "\n"


def run(output_root: Path) -> Path:
    protocol = load_protocol()
    events, quotes = build_events(protocol)
    trades, unresolved = execute_events(events, quotes)
    metrics = build_metrics(events, trades, unresolved)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    final = output_root.resolve() / f"dividend_calendar_spread_v1_{timestamp}_{CONFIG_SHA256[:8]}"
    if final.exists():
        raise FileExistsError(f"dividend spread V1 output exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        events_path = temporary / "events.parquet"
        trades_path = temporary / "trades.parquet"
        metrics_path = temporary / "metrics.json"
        report_path = temporary / "report.md"
        _write_parquet(events_path, events)
        _write_parquet(trades_path, trades)
        write_json(metrics_path, metrics)
        atomic_write_bytes(report_path, _report(metrics).encode("utf-8-sig"))
        artifacts = {
            "events": _artifact(events_path, len(events)),
            "trades": _artifact(trades_path, len(trades)),
            "metrics": _artifact(metrics_path),
            "report": _artifact(report_path),
        }
        audit = {
            "all_artifacts_present": True,
            "metrics_protocol_exact": metrics["protocol_sha256"] == CONFIG_SHA256,
            "trade_accounting_replay_exact": _accounting_replay_exact(trades),
            "protected_rows_zero": bool(
                trades.empty or pd.to_datetime(trades["exit_date"]).lt(PROTECTED_FROM).all()
            ),
            "capital_return_absent": metrics["cagr_or_ruble_return_reported"] is False,
        }
        audit_path = temporary / "audit.json"
        write_json(audit_path, audit)
        artifacts["audit"] = _artifact(audit_path)
        manifest = {
            "run_id": final.name,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": sha256_file(Path(__file__)),
            "source_manifest_sha256": protocol.payload["inputs"]["spread_manifest"][
                "sha256"
            ],
            "cashflow_sha256": protocol.payload["inputs"]["cashflow"]["sha256"],
            "artifacts": artifacts,
            "verdict": metrics["verdict"],
            "live_trading_allowed": False,
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        sidecar = f"{sha256_file(manifest_path)}  manifest.json\n"
        atomic_write_bytes(temporary / "manifest.sha256", sidecar.encode("utf-8-sig"))
        temporary.replace(final)
    except Exception:
        import shutil

        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def audit_run(run_directory: Path) -> dict[str, bool]:
    protocol = load_protocol()
    root = run_directory.resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    declared = (root / "manifest.sha256").read_text(encoding="utf-8-sig").split()[0]
    checks = {
        "manifest_sha_exact": declared == sha256_file(manifest_path),
        "protocol_sha_exact": manifest["protocol_sha256"] == protocol.config_sha256,
        "implementation_sha_exact": manifest["implementation_sha256"]
        == sha256_file(Path(__file__)),
        "live_forbidden": manifest["live_trading_allowed"] is False,
    }
    for name, declaration in manifest["artifacts"].items():
        path = root / declaration["file"]
        checks[f"{name}_sha_exact"] = sha256_file(path) == declaration["sha256"]
        checks[f"{name}_bytes_exact"] = path.stat().st_size == declaration["bytes"]
        if "rows" in declaration:
            checks[f"{name}_rows_exact"] = (
                pq.ParquetFile(path).metadata.num_rows == declaration["rows"]
            )
    trades = pd.read_parquet(root / "trades.parquet")
    metrics = json.loads((root / "metrics.json").read_text(encoding="utf-8-sig"))
    checks["completed_trade_count_exact"] = len(trades) == metrics["counts"][
        "completed_trades"
    ]
    checks["net_accounting_replay_exact"] = _accounting_replay_exact(trades)
    checks["capital_return_absent"] = metrics["cagr_or_ruble_return_reported"] is False
    checks["protected_rows_zero"] = bool(
        trades.empty or pd.to_datetime(trades["exit_date"]).lt(PROTECTED_FROM).all()
    )
    if not all(checks.values()):
        raise ValueError(f"dividend spread V1 run audit failed: {checks}")
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    parser.add_argument("--audit-directory", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.audit_directory is not None:
        print(json.dumps(audit_run(arguments.audit_directory), indent=2))
        return 0
    output = run(arguments.output_root)
    print(output)
    print(json.dumps(audit_run(output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
