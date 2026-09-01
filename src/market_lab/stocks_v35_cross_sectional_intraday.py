"""Byte-sealed orchestration for V35 thirty-stock continuous neural timing."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from market_lab.stocks import cross_sectional_intraday as core

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MODULE_PATH: Final[Path] = Path(__file__).resolve()
CORE_PATH: Final[Path] = Path(core.__file__).resolve()
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/stocks_v35_cross_sectional_intraday.yaml"
CONFIG_SHA256: Final[str] = "257422c0ce2824e3a12252f1759e01fdee29c321f11190bd3b09d9a2b4984388"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved != CONFIG_PATH.resolve():
        raise ValueError("V35 accepts only its canonical sealed config")
    actual = _sha(resolved)
    if actual != CONFIG_SHA256:
        raise ValueError(f"V35 config SHA mismatch: {actual}")
    declared = resolved.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if declared != actual:
        raise ValueError("V35 config sidecar SHA mismatch")
    config = yaml.safe_load(resolved.read_text(encoding="utf-8-sig"))
    if config["protocol_name"] != "stocks-v35-cross-sectional-intraday":
        raise ValueError("V35 protocol identity mismatch")
    if config["source"]["protected_2026_read_allowed"] is not False:
        raise ValueError("V35 protected-data invariant escaped")
    if config["reporting"]["live_promotion_allowed"] is not False:
        raise ValueError("V35 must remain development-only")
    return config


def _artifact_record(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha(path),
    }
    if path.suffix == ".parquet":
        record["rows"] = len(pd.read_parquet(path, columns=[]))
    return record


def _signal_ids(predictions: pd.DataFrame, variant: str) -> set[int]:
    selected = predictions.loc[
        predictions["variant"].eq(variant) & predictions["active_signal"].eq(True),
        "candidate_id",
    ]
    return {int(value) for value in selected}


def _verdict(metrics: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    lookup = {(item["variant"], item["scenario"]): item for item in metrics}
    primary = lookup[("full_all_stock_neural", "primary")]
    doubled = lookup[("full_all_stock_neural", "doubled")]
    aggregate = lookup[("aggregate_only_neural", "primary")]
    gates = config["reporting"]["gates"]
    checks = {
        "primary_cagr_at_least_20": primary["cagr"] >= float(gates["primary_cagr_minimum"]),
        "doubled_cagr_at_least_20": doubled["cagr"] >= float(gates["doubled_cagr_minimum"]),
        "primary_sharpe_at_least_1": primary["sharpe"]
        >= float(gates["primary_sharpe_minimum"]),
        "primary_drawdown_at_most_30": primary["maximum_drawdown"]
        <= float(gates["primary_maximum_drawdown_ceiling"]),
        "minimum_positive_years": primary["positive_years"]
        >= int(gates["minimum_positive_oos_years"]),
        "full_beats_aggregate_primary_cagr": primary["cagr"] > aggregate["cagr"],
        "zero_unresolved_full_primary": primary["unresolved_count"] == 0,
        "aspirational_50_cagr": primary["cagr"] >= float(gates["aspirational_cagr"]),
    }
    economic = all(value for key, value in checks.items() if key != "aspirational_50_cagr")
    status = "GO_TO_INDEPENDENT_FORWARD_VALIDATION" if economic else "NO_GO"
    return {
        "status": status,
        "supports_20_percent_claim": economic,
        "supports_50_percent_claim": economic and checks["aspirational_50_cagr"],
        "live_trading_allowed": False,
        "checks": checks,
        "live_blockers": [
            "fixed current universe is not point-in-time constituents",
            "historical short-locate and lot-size records are absent",
            "no independent forward confirmation",
        ],
    }


def _report(metrics_payload: dict[str, Any]) -> str:
    verdict = metrics_payload["verdict"]
    lines = [
        "# V35: внутридневная cross-sectional reversion по 30 акциям",
        "",
        f"Verdict: **{verdict['status']}**. Live trading: **запрещён**.",
        "",
        "Решение принимается после завершённого 10-минутного бара, вход — на следующем ",
        "exact common open, выход — через 60 минут. Корзина dollar-neutral: три long ",
        "наиболее отрицательных residual z и три short наиболее положительных.",
        "",
        f"Candidates: {metrics_payload['candidate_count']}; neural predictions: "
        f"{metrics_payload['prediction_count']}; positive doubled-cost labels: "
        f"{metrics_payload['positive_label_count']}.",
        "",
        "| Variant | Costs | Trades | CAGR | Sharpe | MDD | Unresolved | Costs RUB |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in metrics_payload["strategies"]:
        lines.append(
            f"| {item['variant']} | {item['scenario']} | {item['completed_trades']} | "
            f"{item['cagr']:.4%} | {item['sharpe']:.4f} | "
            f"{item['maximum_drawdown']:.4%} | {item['unresolved_count']} | "
            f"{item['costs_rub']:.2f} |"
        )
    lines.extend(
        [
            "",
            "Годовые результаты и все threshold/fold records находятся в metrics.json и ",
            "fold_records.parquet. Параметры этой версии после просмотра результата менять нельзя.",
            "",
        ]
    )
    return "\n".join(lines)


def run_experiment(config: dict[str, Any], output_root: Path) -> Path:
    preflight = core.preflight_source(config, PROJECT_ROOT)
    if not all(preflight["checks"].values()):
        raise ValueError("V35 source preflight failed")
    panel = core.load_panel(config, PROJECT_ROOT)
    candidates = core.build_candidates(panel, config)
    if candidates.frame.empty:
        raise ValueError("V35 produced no candidates")
    candidate_frame = candidates.frame.copy()
    labels = core.doubled_cost_label(candidate_frame, config)
    candidate_frame["doubled_cost_positive_label"] = labels
    predictions, fold_records = core.build_oos_predictions(candidates, config)
    oos_years = set(int(year) for year in config["folds"]["expanding_oos_years"])
    evaluation_candidates = candidate_frame.loc[candidate_frame["year"].isin(oos_years)].copy()
    scenarios = core.scenario_parameters(config)
    local_panel = panel.timestamps.tz_convert(config["timing"]["timezone"])
    evaluation_sessions = tuple(
        sorted(
            {
                str(value)
                for value, year in zip(local_panel.date, local_panel.year, strict=True)
                if int(year) in oos_years
            }
        )
    )
    variants = (
        "full_all_stock_neural",
        "aggregate_only_neural",
        "fixed_cross_sectional_rule",
    )
    all_trades: list[pd.DataFrame] = []
    all_curves: list[pd.DataFrame] = []
    strategy_metrics: list[dict[str, Any]] = []
    for variant in variants:
        signal_ids = (
            set(int(value) for value in evaluation_candidates["candidate_id"])
            if variant == "fixed_cross_sectional_rule"
            else _signal_ids(predictions, variant)
        )
        for scenario, parameters in scenarios.items():
            trades, curve, metrics = core.simulate_ledger(
                evaluation_candidates,
                signal_ids,
                config,
                variant=variant,
                scenario=scenario,
                parameters=parameters,
                evaluation_sessions=evaluation_sessions,
            )
            all_trades.append(trades)
            all_curves.append(curve)
            strategy_metrics.append(metrics)
    metrics_payload: dict[str, Any] = {
        "protocol": config["protocol_name"],
        "config_sha256": CONFIG_SHA256,
        "source_manifest_sha256": config["source"]["manifest_sha256"],
        "candidate_count": len(candidate_frame),
        "evaluation_candidate_count": len(evaluation_candidates),
        "positive_label_count": int(labels.sum()),
        "prediction_count": len(predictions),
        "fold_record_count": len(fold_records),
        "panel_common_timestamps": len(panel.timestamps),
        "panel_minimum_timestamp": panel.timestamps.min().isoformat(),
        "panel_maximum_timestamp": panel.timestamps.max().isoformat(),
        "strategies": strategy_metrics,
    }
    metrics_payload["verdict"] = _verdict(strategy_metrics, config)

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_name = (
        f"v35_cross_sectional_intraday_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{CONFIG_SHA256[:8]}"
    )
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"immutable V35 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}-", dir=output_root))
    try:
        candidate_frame.to_parquet(temporary / "candidates.parquet", index=False)
        predictions.to_parquet(temporary / "predictions.parquet", index=False)
        fold_records.to_parquet(temporary / "fold_records.parquet", index=False)
        pd.concat(all_trades, ignore_index=True).to_parquet(
            temporary / "trades.parquet", index=False
        )
        pd.concat(all_curves, ignore_index=True).to_parquet(
            temporary / "equity.parquet", index=False
        )
        np.savez_compressed(
            temporary / "features.npz",
            full=candidates.full_features,
            aggregate=candidates.aggregate_features,
            full_names=np.asarray(candidates.full_feature_names),
            aggregate_names=np.asarray(candidates.aggregate_feature_names),
        )
        _write_json(temporary / "metrics.json", metrics_payload)
        (temporary / "resolved_config.yaml").write_bytes(CONFIG_PATH.read_bytes())
        (temporary / "report.md").write_text(_report(metrics_payload), encoding="utf-8-sig")
        artifact_names = (
            "candidates.parquet",
            "predictions.parquet",
            "fold_records.parquet",
            "trades.parquet",
            "equity.parquet",
            "features.npz",
            "metrics.json",
            "resolved_config.yaml",
            "report.md",
        )
        identity = {
            "protocol": config["protocol_name"],
            "created_at_utc": datetime.now(UTC).isoformat(),
            "config_sha256": CONFIG_SHA256,
            "runner_sha256": _sha(MODULE_PATH),
            "core_sha256": _sha(CORE_PATH),
            "source_manifest_sha256": config["source"]["manifest_sha256"],
            "artifacts": [_artifact_record(temporary / name) for name in artifact_names],
        }
        _write_json(temporary / "identity.json", identity)
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit_run(final)
    _write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("V35 post-run audit failed")
    return final


def audit_run(run_directory: Path) -> dict[str, bool]:
    run_directory = run_directory.resolve()
    identity_path = run_directory / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8-sig"))
    metrics = json.loads((run_directory / "metrics.json").read_text(encoding="utf-8-sig"))
    artifacts_exact = True
    rows_exact = True
    for item in identity.get("artifacts", []):
        path = run_directory / item["path"]
        artifacts_exact &= path.is_file()
        if not path.is_file():
            continue
        artifacts_exact &= path.stat().st_size == int(item["bytes"])
        artifacts_exact &= _sha(path) == item["sha256"]
        if "rows" in item:
            rows_exact &= len(pd.read_parquet(path, columns=[])) == int(item["rows"])
    candidates = pd.read_parquet(
        run_directory / "candidates.parquet", columns=["candidate_id", "year"]
    )
    predictions = pd.read_parquet(
        run_directory / "predictions.parquet", columns=["candidate_id", "variant"]
    )
    trades = pd.read_parquet(
        run_directory / "trades.parquet", columns=["variant", "scenario", "candidate_id"]
    )
    metric_trade_counts = {
        (item["variant"], item["scenario"]): int(item["completed_trades"])
        for item in metrics["strategies"]
    }
    actual_trade_counts = trades.groupby(["variant", "scenario"]).size().to_dict()
    counts_exact = all(
        actual_trade_counts.get(key, 0) == value
        for key, value in metric_trade_counts.items()
    )
    checks = {
        "identity_protocol_exact": identity.get("protocol")
        == "stocks-v35-cross-sectional-intraday",
        "config_identity_exact": identity.get("config_sha256") == CONFIG_SHA256,
        "resolved_config_exact": _sha(run_directory / "resolved_config.yaml") == CONFIG_SHA256,
        "runner_identity_exact": identity.get("runner_sha256") == _sha(MODULE_PATH),
        "core_identity_exact": identity.get("core_sha256") == _sha(CORE_PATH),
        "source_identity_exact": identity.get("source_manifest_sha256")
        == metrics.get("source_manifest_sha256"),
        "artifact_identities_exact": bool(artifacts_exact),
        "artifact_rows_exact": bool(rows_exact),
        "candidate_count_exact": len(candidates) == int(metrics["candidate_count"]),
        "candidate_ids_unique": not candidates["candidate_id"].duplicated().any(),
        "candidate_year_boundary_exact": int(candidates["year"].max()) <= 2025,
        "prediction_count_exact": len(predictions) == int(metrics["prediction_count"]),
        "prediction_variants_exact": set(predictions["variant"])
        == {"full_all_stock_neural", "aggregate_only_neural"},
        "trade_counts_exact": bool(counts_exact),
        "live_trading_forbidden": metrics["verdict"]["live_trading_allowed"] is False,
        "supports_claims_are_boolean": isinstance(
            metrics["verdict"]["supports_20_percent_claim"], bool
        )
        and isinstance(metrics["verdict"]["supports_50_percent_claim"], bool),
    }
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--audit-run", type=Path)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    args = parser.parse_args()
    config = load_config()
    if args.audit_run is not None:
        checks = audit_run(args.audit_run)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
        if not all(checks.values()):
            raise SystemExit(2)
        return
    if args.preflight_only:
        result = core.preflight_source(config, PROJECT_ROOT)
        print(json.dumps(result, indent=2))
        if not all(result["checks"].values()):
            raise SystemExit(2)
        return
    output = run_experiment(config, args.output_root)
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    print(json.dumps({"output": str(output), "metrics": metrics}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
