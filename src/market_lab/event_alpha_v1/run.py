"""Artifact-producing runner for the frozen Event Alpha V1 development test."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from market_lab.event_alpha_v1.core import (
    EVENT_ALPHA_VERSION,
    attach_causal_targets,
    build_cbr_events,
    build_cftc_events,
    compute_metrics,
    evaluate_expanding_folds,
    load_frozen_protocol,
    load_verified_inputs,
    sha256_file,
)
from market_lab.io_utils import atomic_write_text, write_json


def run_event_alpha_v1(
    *,
    project_root: Path,
    config_path: Path,
    output_root: Path | None = None,
) -> Path:
    """Runs only the frozen 2018-2025 development experiment and persists evidence."""
    root = Path(project_root).resolve()
    config = Path(config_path).resolve()
    protocol, protocol_sha = load_frozen_protocol(config)
    inputs = load_verified_inputs(root, protocol)
    source_specs = protocol["inputs"]
    cbr_events = build_cbr_events(inputs.cbr, protocol, source_specs["cbr_panel"]["sha256"])
    cftc_events = build_cftc_events(inputs.cftc, protocol, source_specs["cftc_panel"]["sha256"])
    events = pd.concat([cbr_events, cftc_events], ignore_index=True).sort_values(
        ["available_at", "event_id", "asset"], kind="stable"
    )
    active_horizons = [
        int(item["value"])
        for item in protocol["targets"]["horizons"]
        if item["kind"] == "sessions" and item["status"] == "active"
    ]
    dataset = attach_causal_targets(events, inputs.prices, active_horizons)
    predictions = evaluate_expanding_folds(dataset, protocol)
    if predictions.empty:
        raise RuntimeError("Frozen Event Alpha experiment produced no OOS predictions")
    created_at = datetime.now(UTC)
    destination_root = (
        Path(output_root).resolve()
        if output_root is not None
        else (root / str(protocol["outputs"]["root"])).resolve()
    )
    run_name = f"development_{created_at.strftime('%Y%m%dT%H%M%SZ')}_{protocol_sha[:8]}"
    run_path = destination_root / run_name
    if run_path.exists():
        raise FileExistsError(f"Event Alpha run already exists: {run_path}")
    run_path.mkdir(parents=True)
    event_path = run_path / "event_dataset.parquet"
    prediction_path = run_path / "oos_predictions.parquet"
    dataset.to_parquet(event_path, index=False)
    predictions.to_parquet(prediction_path, index=False)
    sleeves = [
        "all_macro",
        "cbr",
        "cftc",
        *[f"family:{name}" for name in sorted(events["event_family"].unique())],
    ]
    all_metrics: list[dict[str, object]] = []
    all_trades: list[pd.DataFrame] = []
    all_daily: list[pd.DataFrame] = []
    for horizon in sorted(predictions["horizon_sessions"].unique()):
        horizon_predictions = predictions[predictions["horizon_sessions"] == horizon]
        for sleeve in sleeves:
            metrics, trades, daily = compute_metrics(horizon_predictions, protocol, sleeve=sleeve)
            if metrics["eligible_event_count"] == 0:
                continue
            metrics["horizon_sessions"] = int(horizon)
            all_metrics.append(metrics)
            if not trades.empty:
                trades = trades.assign(sleeve=sleeve)
                all_trades.append(trades)
            daily = daily.assign(sleeve=sleeve, horizon_sessions=int(horizon))
            all_daily.append(daily)
    trades_frame = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    daily_frame = pd.concat(all_daily, ignore_index=True) if all_daily else pd.DataFrame()
    trades_path = run_path / "trade_ledger.parquet"
    daily_path = run_path / "daily_ledger.parquet"
    trades_frame.to_parquet(trades_path, index=False)
    daily_frame.to_parquet(daily_path, index=False)
    metrics_path = run_path / "metrics.json"
    write_json(metrics_path, {"metrics": all_metrics})
    code_paths = [
        root / "src/market_lab/event_alpha_v1/__init__.py",
        root / "src/market_lab/event_alpha_v1/core.py",
        root / "src/market_lab/event_alpha_v1/run.py",
    ]
    output_evidence = [
        _file_evidence(path, run_path)
        for path in (event_path, prediction_path, trades_path, daily_path, metrics_path)
    ]
    manifest: dict[str, Any] = {
        "version": EVENT_ALPHA_VERSION,
        "created_at": created_at.isoformat(),
        "research_only": True,
        "development_period": ["2018-01-01", "2025-12-31"],
        "evaluation_period": ["2021-01-01", "2025-12-31"],
        "protected_holdout_start": "2026-01-01",
        "protocol": {
            "path": config.relative_to(root).as_posix(),
            "sha256": protocol_sha,
            "sealed_before_return_analysis": True,
        },
        "inputs": list(inputs.input_evidence),
        "code": [
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in code_paths
        ],
        "counts": {
            "raw_event_asset_rows": len(events),
            "cbr_event_asset_rows": len(cbr_events),
            "cftc_event_asset_rows": len(cftc_events),
            "target_rows": len(dataset),
            "oos_prediction_rows": len(predictions),
            "trade_ledger_rows_including_diagnostic_sleeves": len(trades_frame),
        },
        "horizons": {
            "next_executable_30m": {
                "status": "sleeping",
                "reason": (
                    "no physically isolated exact pre-2026 intraday bundle "
                    "admitted to this experiment"
                ),
            },
            "next_1_session": "evaluated",
            "next_5_sessions": "evaluated",
        },
        "corporate_reporting": {
            "status": "sleeping_legal_and_pit_blocker",
            "eligible_real_events": 0,
            "synthetic_fixture_rows_used": 0,
            "qwen_market_or_label_access": False,
            "reason": protocol["corporate_reporting"]["reason"],
        },
        "known_limitations": [
            (
                "CBR and CFTC histories are frozen official current-vintage snapshots, "
                "not full revision-vintage archives."
            ),
            (
                "CFTC standard release timing is schedule-derived; documented exceptional "
                "dates use official overrides."
            ),
            (
                "Results are exploratory challenger metrics and not a production or "
                "expected-return claim."
            ),
        ],
        "outputs": output_evidence,
    }
    manifest_path = run_path / "manifest.json"
    write_json(manifest_path, manifest)
    manifest_sha = sha256_file(manifest_path)
    atomic_write_text(run_path / "manifest.json.sha256", f"{manifest_sha}  manifest.json\n")
    report_path = run_path / "report.md"
    atomic_write_text(report_path, _render_report(manifest, all_metrics))
    return run_path


def _file_evidence(path: Path, relative_root: Path) -> dict[str, object]:
    """Returns immutable evidence for one produced artifact."""
    return {
        "path": path.relative_to(relative_root).as_posix(),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _render_report(manifest: dict[str, Any], metrics: list[dict[str, object]]) -> str:
    """Renders a compact Russian result-first report with sleeping blockers."""
    lines = [
        "# Event Alpha V1 — development results",
        "",
        "Период оценки: 2021–2025. Все результаты exploratory и net of 10 bps round-trip cost.",
        "",
        "| Sleeve | Horizon | Events | Trades | CAGR | Sharpe | MDD | Hit | Worst year |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    ranked = sorted(metrics, key=lambda item: float(item["sharpe"]), reverse=True)
    for item in ranked:
        lines.append(
            "| {sleeve} | {horizon}d | {events} | {trades} | {cagr:.2%} | {sharpe:.3f} | "
            "{mdd:.2%} | {hit:.2%} | {worst:.2%} |".format(
                sleeve=item["sleeve"],
                horizon=item["horizon_sessions"],
                events=item["eligible_event_count"],
                trades=item["trade_count"],
                cagr=item["cagr"],
                sharpe=item["sharpe"],
                mdd=item["maximum_drawdown"],
                hit=item["hit_rate"],
                worst=item["worst_year"],
            )
        )
    lines.extend(
        [
            "",
            "## Coverage and blockers",
            "",
            f"- Raw event-asset rows: {manifest['counts']['raw_event_asset_rows']}.",
            f"- OOS prediction rows: {manifest['counts']['oos_prediction_rows']}.",
            (
                "- 30-minute horizon: sleeping; no separately admitted physical pre-2026 "
                "intraday bundle."
            ),
            (
                "- Corporate reports: sleeping; zero synthetic fixtures used and no "
                "PIT/rights-qualified real corpus."
            ),
            (
                "- Local Qwen is restricted to page-evidenced facts and never sees price, "
                "return, target, label or PnL."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    """CLI entry point with no mutable economics overrides."""
    parser = argparse.ArgumentParser(description="Run frozen Event Alpha V1 development evaluation")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, default=Path("configs/event_alpha_v1.yaml"))
    parser.add_argument("--output-root", type=Path, default=None)
    arguments = parser.parse_args()
    root = arguments.project_root.resolve()
    config = arguments.config if arguments.config.is_absolute() else root / arguments.config
    output = arguments.output_root
    if output is not None and not output.is_absolute():
        output = root / output
    result = run_event_alpha_v1(project_root=root, config_path=config, output_root=output)
    print(json.dumps({"run_path": str(result)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
