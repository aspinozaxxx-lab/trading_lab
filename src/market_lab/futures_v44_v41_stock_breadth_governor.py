"""Evaluate the sealed all-stock breadth governor on frozen V41 components."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures import moex_stock_futures_cash_carry_source as io_utils
from market_lab.futures_v40_v39_cash_carry_stability import _metrics
from market_lab.io_utils import atomic_write_bytes, write_json
from market_lab.stocks import cross_sectional_intraday as stocks

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v44_v41_stock_breadth_governor_v1.yaml"
CONFIG_SHA256: Final[str] = (
    "0343758a5376c53c0ffa7e0c2a0852b75e47fdc5ce7cd35c020089d504e86c15"
)
SCENARIOS: Final[tuple[str, ...]] = ("primary", "doubled", "stress")
METRIC_KEYS: Final[tuple[str, ...]] = (
    "total_return",
    "cagr",
    "sharpe",
    "maximum_drawdown",
    "annual_returns",
    "positive_years",
    "worst_year",
)


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    v41_root: Path
    stock_root: Path
    v35_config: dict[str, Any]


def _sha(path: Path) -> str:
    return io_utils.sha256_file(path)


def _relative_root(value: str, required_prefix: tuple[str, ...]) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe V44 path: {value}")
    if tuple(part.lower() for part in relative.parts[: len(required_prefix)]) != tuple(
        part.lower() for part in required_prefix
    ):
        raise ValueError(f"V44 path must start with {'/'.join(required_prefix)}")
    return PROJECT_ROOT / relative


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V44 config must be an object")
    breadth = payload["breadth"]
    allocation = payload["allocation"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "futures_v44_v41_stock_breadth_governor_v1"
        or payload.get("live_trading_allowed") is not False
        or int(breadth["return_lookback_sessions"]) != 63
        or float(breadth["risk_off_if_strictly_below"]) != 1.0 / 3.0
        or allocation["normal"] != {"v39": 0.80, "cash_carry_ruonia": 0.20}
        or allocation["risk_off"] != {"v39": 0.40, "cash_carry_ruonia": 0.60}
        or allocation["rebalance_only_on_state_transition"] is not True
        or allocation["leverage_added"] is not False
    ):
        raise ValueError("V44 protocol drifted")
    parents = payload["parents"]
    v41 = parents["v41"]
    stock = parents["stocks"]
    v41_root = _relative_root(v41["root"], ("runs",))
    stock_root = _relative_root(stock["root"], ("data", "processed"))
    for key, declaration in v41.items():
        if key in {"root", "protocol_sha256"}:
            continue
        path = v41_root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"V44 V41 parent drifted: {key}")
        if "rows" in declaration and pq.ParquetFile(path).metadata.num_rows != int(
            declaration["rows"]
        ):
            raise ValueError(f"V44 V41 parent rows drifted: {key}")
    stock_manifest = stock_root / stock["manifest"]["file"]
    if (
        _sha(stock_manifest) != stock["manifest"]["sha256"]
        or stock_manifest.stat().st_size != int(stock["manifest"]["bytes"])
    ):
        raise ValueError("V44 stock source manifest drifted")
    loader_path = PROJECT_ROOT / stock["loader"]["file"]
    v35_path = PROJECT_ROOT / stock["universe_source_config"]["file"]
    if (
        _sha(loader_path) != stock["loader"]["sha256"]
        or _sha(v35_path) != stock["universe_source_config"]["sha256"]
    ):
        raise ValueError("V44 stock loader/config drifted")
    v35_config = yaml.safe_load(v35_path.read_text(encoding="utf-8-sig"))
    if len(v35_config["universe"]["tickers"]) != 30:
        raise ValueError("V44 stock universe count drifted")
    v41_manifest = json.loads(
        (v41_root / v41["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    if v41_manifest["protocol_sha256"] != v41["protocol_sha256"]:
        raise ValueError("V44 V41 protocol identity drifted")
    return Protocol(payload, actual, v41_root, stock_root, v35_config)


def build_breadth_states(protocol: Protocol) -> pd.DataFrame:
    manifest = stocks.validate_source_manifest(protocol.v35_config, PROJECT_ROOT)
    artifacts = {item["ticker"]: item for item in manifest["artifacts"]}
    tickers = tuple(protocol.v35_config["universe"]["tickers"])
    frames: dict[str, pd.Series] = {}
    common: pd.DatetimeIndex | None = None
    for ticker in tickers:
        item = artifacts[ticker]
        path = protocol.stock_root / item["path"]
        if _sha(path) != item["sha256"]:
            raise ValueError(f"V44 stock artifact drifted: {ticker}")
        frame = pd.read_parquet(path, columns=["timestamp", "close"])
        if "timestamp" in frame.columns:
            timestamp_values = frame.pop("timestamp")
        elif frame.index.name == "timestamp":
            timestamp_values = frame.index
        else:
            raise ValueError(f"V44 timestamp missing after decode: {ticker}")
        timestamp = pd.DatetimeIndex(pd.to_datetime(timestamp_values, utc=True))
        if len(timestamp) and timestamp.max() >= pd.Timestamp("2026-01-01", tz="UTC"):
            raise ValueError("V44 decoded protected stock timestamp")
        series = pd.Series(
            pd.to_numeric(frame["close"], errors="coerce").to_numpy(),
            index=timestamp,
            name=ticker,
        )
        frames[ticker] = series
        common = timestamp if common is None else common.intersection(timestamp, sort=True)
    if common is None or common.empty:
        raise ValueError("V44 exact common stock panel is empty")
    local_dates = common.tz_convert("Europe/Moscow").normalize().tz_localize(None)
    final_positions = (
        pd.Series(np.arange(len(common)), index=local_dates).groupby(level=0).last()
    )
    final_timestamps = common[final_positions.to_numpy(dtype=int)]
    closes = pd.DataFrame(
        {
            ticker: frames[ticker].reindex(final_timestamps).to_numpy()
            for ticker in tickers
        },
        index=pd.DatetimeIndex(final_positions.index, name="signal_date"),
    )
    lookback = int(protocol.payload["breadth"]["return_lookback_sessions"])
    momentum = closes / closes.shift(lookback) - 1.0
    available = momentum.notna().sum(axis=1)
    breadth = momentum.gt(0.0).sum(axis=1) / len(tickers)
    valid = available.eq(len(tickers))
    threshold = float(protocol.payload["breadth"]["risk_off_if_strictly_below"])
    output = pd.DataFrame(
        {
            "signal_date": closes.index,
            "final_bar_open_at_utc": final_timestamps,
            "available_assets": available.to_numpy(dtype=int),
            "positive_assets": momentum.gt(0.0).sum(axis=1).to_numpy(dtype=int),
            "breadth_fraction": breadth.to_numpy(dtype=float),
            "state_valid": valid.to_numpy(dtype=bool),
            "risk_off": (valid & breadth.lt(threshold)).to_numpy(dtype=bool),
        }
    )
    if output["signal_date"].duplicated().any():
        raise ValueError("V44 duplicate stock signal date")
    return output


def align_states(calendar: pd.Series, states: pd.DataFrame) -> pd.DataFrame:
    sessions = pd.DataFrame(
        {"session_date": pd.to_datetime(calendar, errors="raise")}
    ).sort_values("session_date")
    source = states.loc[
        states["state_valid"], ["signal_date", "breadth_fraction", "risk_off"]
    ].sort_values("signal_date")
    aligned = pd.merge_asof(
        sessions,
        source,
        left_on="session_date",
        right_on="signal_date",
        direction="backward",
        allow_exact_matches=False,
    )
    aligned["risk_off"] = aligned["risk_off"].eq(True)
    if aligned["signal_date"].notna().any() and not bool(
        aligned.loc[aligned["signal_date"].notna(), "signal_date"].lt(
            aligned.loc[aligned["signal_date"].notna(), "session_date"]
        ).all()
    ):
        raise ValueError("V44 breadth state is not strictly prior")
    return aligned


def simulate(
    v39_nav: pd.Series,
    cash_nav: pd.Series,
    risk_off: pd.Series,
    one_way_cost_bps: float,
) -> tuple[pd.DataFrame, dict[str, float | int]]:
    v39_returns = v39_nav.astype(float).pct_change().fillna(0.0).to_numpy()
    cash_returns = cash_nav.astype(float).pct_change().fillna(0.0).to_numpy()
    states = risk_off.astype(bool).to_numpy()
    v39_value, cash_value = 0.80, 0.20
    current_state = False
    cost_rate = float(one_way_cost_bps) / 10_000.0
    rows = []
    total_cost = 0.0
    transitions = 0
    for index, desired_state in enumerate(states):
        nav_before = v39_value + cash_value
        transition = bool(desired_state != current_state)
        transition_turnover = 0.0
        transition_cost = 0.0
        if transition:
            target = 0.40 if desired_state else 0.80
            shift = abs(target * nav_before - v39_value)
            transition_turnover = 2.0 * shift
            transition_cost = transition_turnover * cost_rate
            nav_after_cost = nav_before - transition_cost
            v39_value = target * nav_after_cost
            cash_value = (1.0 - target) * nav_after_cost
            total_cost += transition_cost
            transitions += 1
            current_state = bool(desired_state)
        v39_value *= 1.0 + v39_returns[index]
        cash_value *= 1.0 + cash_returns[index]
        ending = v39_value + cash_value
        rows.append(
            {
                "risk_off": bool(desired_state),
                "state_transition": transition,
                "transition_turnover_nav_units": transition_turnover,
                "transition_cost_nav_units": transition_cost,
                "v39_value": v39_value,
                "cash_value": cash_value,
                "governed_nav": ending,
                "actual_v39_weight": v39_value / ending,
            }
        )
    return pd.DataFrame(rows), {
        "state_transitions": transitions,
        "total_transition_cost_nav_units": total_cost,
        "risk_off_sessions": int(states.sum()),
    }


def _reported_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload[key] for key in METRIC_KEYS}


def build(protocol: Protocol) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    parent = pd.read_parquet(protocol.v41_root / "combined_ledger.parquet")
    parent["session_date"] = pd.to_datetime(parent["session_date"], errors="raise")
    benchmark = json.loads(
        (protocol.v41_root / "metrics.json").read_text(encoding="utf-8-sig")
    )
    breadth = build_breadth_states(protocol)
    aligned = align_states(parent["session_date"], breadth)
    output = aligned.copy()
    scenarios: dict[str, Any] = {}
    for name in SCENARIOS:
        scenario = protocol.payload["scenarios"][name]
        v39_column, cash_column = scenario["v41_component_columns"]
        simulated, counts = simulate(
            parent[v39_column],
            parent[cash_column],
            aligned["risk_off"],
            float(scenario["one_way_cost_per_component_bps"]),
        )
        output[f"benchmark_{name}_nav"] = parent[f"combined_{name}_nav"].to_numpy()
        for column in simulated:
            output[f"{name}_{column}"] = simulated[column].to_numpy()
        combined = pd.Series(
            simulated["governed_nav"].to_numpy(), index=parent["session_date"]
        )
        combined_metrics = _metrics(combined)
        benchmark_metrics = _reported_metrics(
            benchmark["scenarios"][scenario["benchmark"]]["combined"]
        )
        scenarios[name] = {
            "benchmark_v41": benchmark_metrics,
            "governed": combined_metrics,
            "counts": counts,
            "delta": {
                key: combined_metrics[key] - benchmark_metrics[key]
                for key in ("cagr", "sharpe", "maximum_drawdown", "worst_year")
            },
        }
    gates = {
        "all_scenario_cagr_gte_20pct": all(
            item["governed"]["cagr"] >= 0.20 for item in scenarios.values()
        ),
        "all_scenario_sharpe_not_worse_than_v41": all(
            item["governed"]["sharpe"] >= item["benchmark_v41"]["sharpe"]
            for item in scenarios.values()
        ),
        "all_scenario_mdd_strictly_better_than_v41": all(
            item["governed"]["maximum_drawdown"]
            < item["benchmark_v41"]["maximum_drawdown"]
            for item in scenarios.values()
        ),
        "all_scenario_worst_year_not_worse_than_v41": all(
            item["governed"]["worst_year"] >= item["benchmark_v41"]["worst_year"]
            for item in scenarios.values()
        ),
        "primary_positive_years_gte_5": scenarios["primary"]["governed"]
        ["positive_years"]
        >= 5,
    }
    metrics = {
        "verdict": "IMPROVES_V41_GO_TO_FORWARD" if all(gates.values()) else "NO_GO",
        "breadth": {
            "lookback_sessions": 63,
            "risk_off_threshold": 1.0 / 3.0,
            "valid_source_states": int(breadth["state_valid"].sum()),
            "aligned_risk_off_sessions": int(aligned["risk_off"].sum()),
        },
        "scenarios": scenarios,
        "gates": gates,
        "adaptive_same_history": True,
        "live_trading_allowed": False,
    }
    return output, breadth, metrics


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# V44 all-stock breadth governor on V41",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        "Risk-off shifts V39/cash from 80/20 to 40/60 only on state transitions.",
        "",
        "| Scenario | CAGR | Sharpe | MDD | Worst year | dCAGR | dSharpe | dMDD | Transitions |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in metrics["scenarios"].items():
        governed, delta = item["governed"], item["delta"]
        lines.append(
            f"| {name} | {governed['cagr']:.4%} | {governed['sharpe']:.3f} | "
            f"{governed['maximum_drawdown']:.4%} | {governed['worst_year']:.4%} | "
            f"{delta['cagr']:+.4%} | {delta['sharpe']:+.3f} | "
            f"{delta['maximum_drawdown']:+.4%} | {item['counts']['state_transitions']} |"
        )
    lines.extend(
        [
            "",
            "This is same-history adaptive evidence with a survivorship-biased stock universe.",
            "No parameter may be changed from this outcome; live trading remains forbidden.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(protocol: Protocol) -> Path:
    ledger, breadth, metrics = build(protocol)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = _relative_root(protocol.payload["outputs"]["root"], ("runs",))
    output = base.parent / f"{base.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"V44 output exists: {output}")
    output.mkdir(parents=True)
    ledger_path = output / "daily_ledger.parquet"
    breadth_path = output / "breadth_states.parquet"
    metrics_path = output / "metrics.json"
    report_path = output / "report.md"
    io_utils._write_parquet(ledger_path, ledger)
    io_utils._write_parquet(breadth_path, breadth)
    write_json(metrics_path, metrics)
    atomic_write_bytes(report_path, _report(metrics).encode("utf-8-sig"))
    known = ledger["signal_date"].notna()
    audit = {
        "checks": {
            "protocol_sha_exact": _sha(CONFIG_PATH) == protocol.config_sha256,
            "dates_before_2026": bool(
                pd.to_datetime(ledger["session_date"]).dt.year.le(2025).all()
            ),
            "breadth_strictly_prior": bool(
                ledger.loc[known, "signal_date"].lt(
                    ledger.loc[known, "session_date"]
                ).all()
            ),
            "exact_30_asset_states": bool(
                breadth.loc[breadth["state_valid"], "available_assets"].eq(30).all()
            ),
            "no_leverage": all(
                ledger[f"{name}_actual_v39_weight"].between(0.0, 1.0).all()
                for name in SCENARIOS
            ),
            "all_nav_positive": bool(
                ledger.filter(regex="_nav$").gt(0.0).all(axis=None)
            ),
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"V44 audit failed: {audit}")
    audit_path = output / "audit.json"
    write_json(audit_path, audit)
    artifacts = {
        "ledger": io_utils._artifact(ledger_path, len(ledger)),
        "breadth": io_utils._artifact(breadth_path, len(breadth)),
        "metrics": io_utils._artifact(metrics_path),
        "report": io_utils._artifact(report_path),
        "audit": io_utils._artifact(audit_path),
    }
    manifest = {
        "run_id": output.name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": protocol.config_sha256,
        "implementation_sha256": _sha(Path(__file__)),
        "verdict": metrics["verdict"],
        "live_trading_allowed": False,
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
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    output = run(load_protocol())
    print(output)
    print((output / "report.md").read_text(encoding="utf-8-sig"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
