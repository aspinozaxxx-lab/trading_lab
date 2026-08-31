"""Immutable real-data runner for the sealed V10 triangular experiment."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .core import (
    FX_ABLATION,
    PRIMARY_STRATEGY,
    build_signal_frame,
    calculate_metrics,
    evaluate_promotion,
    settings_from_protocol,
    simulate_strategy,
)
from .data import (
    CONFIG_SHA256,
    PROJECT_ROOT,
    load_protocol,
    load_verified_panel,
    sha256_file,
)


def _json_default(value: object) -> object:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _signal_audit(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[
        [
            "timestamp",
            "end_timestamp",
            "local_date",
            "residual",
            "baseline_mean",
            "baseline_std",
            "zscore",
            "contract_run_id",
            "exact_next",
            "oos",
            "entry_window",
            "signal_ready",
            "eligible_signal_bar",
            "raw_entry_signal",
            "residual_position_side",
        ]
    ].copy()


def _combine_frames(frames: list[pd.DataFrame], fallback_columns: list[str]) -> pd.DataFrame:
    populated = [frame for frame in frames if not frame.empty]
    if populated:
        return pd.concat(populated, ignore_index=True)
    return pd.DataFrame(columns=fallback_columns)


def _write_report(path: Path, result: dict[str, Any]) -> None:
    primary = result["strategies"][PRIMARY_STRATEGY.name]
    ordinary = primary["ordinary_cost"]
    doubled = primary["doubled_cost"]
    counts = primary["counts"]
    lines = [
        "# V10 triangular relative-value result",
        "",
        f"- Verdict: **{result['verdict']}**",
        f"- Protocol SHA-256: `{result['protocol_sha256']}`",
        f"- Completed trades: {counts['completed_trades']}",
        f"- Unresolved events: {counts['unresolved']}",
        f"- Ordinary CAGR (partial if invalid): {ordinary['cagr']:.6%}",
        f"- Ordinary Sharpe (partial if invalid): {ordinary['annualized_sharpe']:.6f}",
        f"- Ordinary maximum drawdown: {ordinary['maximum_drawdown']:.6%}",
        f"- Doubled-cost CAGR (partial if invalid): {doubled['cagr']:.6%}",
        "",
        "Metrics are not full-period claims when `valid=false`. This is a research proxy,",
        "not broker-exact execution, and it never authorizes live trading.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_experiment(output_dir: Path) -> dict[str, Any]:
    """Run both predeclared residuals once and persist a fully hashed audit trail."""

    protocol = load_protocol()
    settings = settings_from_protocol(protocol)
    loaded = load_verified_panel()
    output_dir.mkdir(parents=True, exist_ok=False)

    primary_signals = build_signal_frame(loaded.panel, PRIMARY_STRATEGY, settings)
    ablation_signals = build_signal_frame(loaded.panel, FX_ABLATION, settings)
    primary = simulate_strategy(primary_signals, PRIMARY_STRATEGY, settings)
    ablation = simulate_strategy(ablation_signals, FX_ABLATION, settings)
    primary_valid = not primary.halted and int(primary.counts["unresolved"]) == 0
    ablation_valid = not ablation.halted and int(ablation.counts["unresolved"]) == 0

    primary_ordinary = calculate_metrics(
        primary_signals,
        primary.trades,
        settings,
        cost_column="pnl_1x",
        valid=primary_valid,
    )
    primary_doubled = calculate_metrics(
        primary_signals,
        primary.trades,
        settings,
        cost_column="pnl_2x",
        valid=primary_valid,
    )
    ablation_ordinary = calculate_metrics(
        ablation_signals,
        ablation.trades,
        settings,
        cost_column="pnl_1x",
        valid=ablation_valid,
    )
    ablation_doubled = calculate_metrics(
        ablation_signals,
        ablation.trades,
        settings,
        cost_column="pnl_2x",
        valid=ablation_valid,
    )
    no_trade = calculate_metrics(
        primary_signals,
        pd.DataFrame(),
        settings,
        cost_column="pnl_1x",
        valid=True,
    )
    promotion = evaluate_promotion(
        primary_ordinary,
        primary_doubled,
        ablation_ordinary,
        primary.counts,
        protocol["promotion_to_next_research_stage"],
    )
    if primary.halted:
        verdict = "NO_GO_UNRESOLVED_EXECUTION"
    elif promotion["passed"]:
        verdict = "PROMOTE_TO_NEXT_RESEARCH_STAGE"
    else:
        verdict = "NO_GO_SEALED_CRITERIA_NOT_MET"

    _signal_audit(primary_signals).to_parquet(
        output_dir / "primary_signal_audit.parquet", index=False
    )
    _signal_audit(ablation_signals).to_parquet(
        output_dir / "fx_ablation_signal_audit.parquet", index=False
    )
    trades = _combine_frames(
        [primary.trades, ablation.trades],
        ["strategy", "trade_id", "entry_fill_at", "exit_fill_at", "pnl_1x", "pnl_2x"],
    )
    legs = _combine_frames(
        [primary.legs, ablation.legs],
        ["strategy", "trade_id", "asset", "pnl_1x", "pnl_2x"],
    )
    unresolved = _combine_frames(
        [primary.unresolved_events, ablation.unresolved_events],
        ["strategy", "index", "decision_at", "phase", "reason"],
    )
    trades.to_parquet(output_dir / "trades.parquet", index=False)
    legs.to_parquet(output_dir / "legs.parquet", index=False)
    unresolved.to_parquet(output_dir / "unresolved.parquet", index=False)

    data_root = (PROJECT_ROOT / "data").resolve()
    raw_artifacts = [
        {
            "path": str(Path(item.path).resolve().relative_to(data_root)).replace("\\", "/"),
            "sha256": item.sha256,
            "asset": item.asset,
            "rows": item.rows,
        }
        for item in loaded.raw_artifacts
    ]
    _write_json(output_dir / "raw_artifacts.json", raw_artifacts)

    result: dict[str, Any] = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "research_only": True,
        "live_trading_allowed": False,
        "protected_holdout_from": "2026-01-01",
        "protected_holdout_touches": 0,
        "verdict": verdict,
        "promotion": promotion,
        "source_hashes": loaded.source_hashes,
        "code_hashes": {
            "core.py": sha256_file(Path(__file__).with_name("core.py")),
            "data.py": sha256_file(Path(__file__).with_name("data.py")),
            "run.py": sha256_file(Path(__file__)),
        },
        "data_counts": loaded.counts,
        "strategies": {
            PRIMARY_STRATEGY.name: {
                "authoritative": True,
                "halted": primary.halted,
                "counts": primary.counts,
                "ordinary_cost": primary_ordinary,
                "doubled_cost": primary_doubled,
            },
            FX_ABLATION.name: {
                "authoritative": False,
                "halted": ablation.halted,
                "counts": ablation.counts,
                "ordinary_cost": ablation_ordinary,
                "doubled_cost": ablation_doubled,
            },
            "no_trade": {
                "authoritative": False,
                "ordinary_cost": no_trade,
            },
        },
        "limitations": protocol["accounting"]["limitations"],
        "artifacts": {},
    }
    _write_report(output_dir / "report.md", result)
    artifact_names = [
        "primary_signal_audit.parquet",
        "fx_ablation_signal_audit.parquet",
        "trades.parquet",
        "legs.parquet",
        "unresolved.parquet",
        "raw_artifacts.json",
        "report.md",
    ]
    for name in artifact_names:
        path = output_dir / name
        result["artifacts"][name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    _write_json(output_dir / "metrics.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_experiment(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
