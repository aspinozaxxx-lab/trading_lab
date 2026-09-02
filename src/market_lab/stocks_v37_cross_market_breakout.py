"""Run the sealed V37 cross-market intraday breakout exactly once."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from market_lab.stocks import cross_market_breakout as core

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/stocks_v37_cross_market_breakout.yaml"
CONFIG_SHA256: Final[str] = "15c6d67c83798e89dead6d8dc975a9c4b0d0e4844b981d3adb576387c00e49e6"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_RUN_ROOT: Final[Path] = PROJECT_ROOT / "runs"


def _sha_file(path: Path) -> str:
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
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8-sig",
    )


def load_protocol() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    if actual != CONFIG_SHA256 or declared != CONFIG_SHA256:
        raise ValueError("V37 config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        config.get("protocol_name") != "stocks-v37-cross-market-breakout"
        or int(config.get("protocol_version", -1)) != 37
        or config.get("sealed_before_outcomes") is not True
        or config.get("live_trading_allowed") is not False
        or config["source"]["protected_2026_read_allowed"] is not False
        or config["candidate"]["selected_direction"] != "strongest_confirmed_side"
        or float(config["model"]["fixed_trade_probability_threshold"]) != 0.60
        or config["model"]["probability_threshold_search"] != "forbidden"
        or float(config["exit"]["hard_stop_adverse_fraction_from_entry"]) != 0.018
        or float(config["exit"]["trailing_activation_favorable_fraction"]) != 0.006
        or float(config["exit"]["trailing_retrace_fraction_from_best_completed_close"])
        != 0.004
    ):
        raise ValueError("V37 sealed invariants drifted")
    return config


def _evaluation_sessions(panel: core.BreakoutPanel, config: dict[str, Any]) -> tuple[str, ...]:
    local = panel.timestamps.tz_convert(config["timing"]["timezone"])
    years = set(int(value) for value in config["folds"]["expanding_oos_years"])
    return tuple(sorted({str(value.date()) for value in local if value.year in years}))


def _promotion(
    metrics: dict[str, dict[str, dict[str, Any]]], config: dict[str, Any]
) -> tuple[dict[str, bool], str]:
    gates = config["reporting"]["gates"]
    primary = metrics["full_cross_stock_mlp"]["primary"]
    doubled = metrics["full_cross_stock_mlp"]["doubled"]
    stress = metrics["full_cross_stock_mlp"]["stress"]
    comparison = max(
        metrics["aggregate_only_mlp"]["primary"]["cagr"],
        metrics["ungated_breakout"]["primary"]["cagr"],
    )
    checks = {
        "primary_cagr": primary["cagr"] >= float(gates["primary_cagr_minimum"]),
        "doubled_cagr": doubled["cagr"] >= float(gates["doubled_cagr_minimum"]),
        "stress_positive": stress["total_return"] >= float(
            gates["stress_total_return_minimum"]
        ),
        "sharpe": primary["sharpe"] >= float(gates["primary_sharpe_minimum"]),
        "drawdown": primary["maximum_drawdown"]
        <= float(gates["primary_maximum_drawdown_ceiling"]),
        "positive_years": primary["positive_years"]
        >= int(gates["minimum_positive_oos_years"]),
        "worst_year": primary["worst_year"] >= float(gates["worst_oos_year_minimum"]),
        "trades": primary["completed_trades"] >= int(gates["minimum_completed_trades"]),
        "unresolved": max(
            metrics["full_cross_stock_mlp"][scenario]["unresolved_count"]
            for scenario in ("primary", "doubled", "stress")
        )
        <= int(gates["unresolved_count_maximum"]),
        "participation": max(
            metrics["full_cross_stock_mlp"][scenario]["maximum_participation"]
            for scenario in ("primary", "doubled", "stress")
        )
        <= float(gates["maximum_participation"]),
        "full_beats_predeclared_baselines": primary["cagr"] > comparison,
    }
    verdict = "GO_TO_NEW_FORWARD_VALIDATION" if all(checks.values()) else "NO_GO"
    return checks, verdict


def _report(payload: dict[str, Any]) -> str:
    primary = payload["metrics"]["full_cross_stock_mlp"]["primary"]
    doubled = payload["metrics"]["full_cross_stock_mlp"]["doubled"]
    stress = payload["metrics"]["full_cross_stock_mlp"]["stress"]
    lines = [
        "# V37 cross-market intraday breakout",
        "",
        f"Verdict: **{payload['verdict']}**",
        "",
        f"- Candidates: {payload['counts']['candidates']}",
        f"- OOS predictions: {payload['counts']['predictions']}",
        f"- Primary completed trades: {primary['completed_trades']}",
        f"- Primary CAGR / Sharpe / MDD: {primary['cagr']:.4%} / "
        f"{primary['sharpe']:.4f} / {primary['maximum_drawdown']:.4%}",
        f"- Doubled/stress CAGR: {doubled['cagr']:.4%} / {stress['cagr']:.4%}",
        f"- Primary yearly returns: {primary['yearly_returns']}",
        f"- Promotion checks: {payload['promotion_checks']}",
        "",
        "Research proxy only: lot sizes, short locate, corporate actions and forward "
        "fill evidence remain missing.",
    ]
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path = DEFAULT_RUN_ROOT) -> Path:
    config = load_protocol()
    source_checks = core.preflight_source(config, PROJECT_ROOT)
    if not all(source_checks.values()):
        raise ValueError(f"V37 source preflight failed: {source_checks}")
    panel = core.load_panel(config, PROJECT_ROOT)
    candidates = core.build_candidates(panel, config)
    if candidates.frame.empty:
        raise ValueError("V37 produced no candidates")
    predictions, folds = core.build_oos_predictions(candidates, config)
    oos_years = set(int(value) for value in config["folds"]["expanding_oos_years"])
    oos = candidates.frame["year"].isin(oos_years)
    variants: dict[str, set[int]] = {}
    for variant in ("full_cross_stock_mlp", "aggregate_only_mlp"):
        selected = predictions.loc[
            predictions["variant"].eq(variant) & predictions["active_signal"].eq(True),
            "candidate_id",
        ]
        variants[variant] = set(pd.to_numeric(selected, errors="raise").astype(int))
    variants["ungated_breakout"] = set(
        candidates.frame.loc[oos, "candidate_id"].astype(int)
    )
    variants["long_only_ungated"] = set(
        candidates.frame.loc[oos & candidates.frame["direction"].eq(1), "candidate_id"].astype(int)
    )
    sessions = _evaluation_sessions(panel, config)
    all_metrics: dict[str, dict[str, dict[str, Any]]] = {}
    trade_artifacts: dict[tuple[str, str], pd.DataFrame] = {}
    curve_artifacts: dict[tuple[str, str], pd.DataFrame] = {}
    for variant, signal_ids in variants.items():
        all_metrics[variant] = {}
        for scenario, parameters in core.scenario_parameters(config).items():
            trades, curve, metrics = core.simulate_ledger(
                candidates.frame,
                signal_ids,
                config,
                variant=variant,
                scenario=scenario,
                parameters=parameters,
                evaluation_sessions=sessions,
            )
            all_metrics[variant][scenario] = metrics
            trade_artifacts[(variant, scenario)] = trades
            curve_artifacts[(variant, scenario)] = curve
    promotion_checks, verdict = _promotion(all_metrics, config)
    counts = {
        "panel_rows": len(panel.timestamps),
        "candidates": len(candidates.frame),
        "execution_observed_candidates": int(candidates.frame["execution_observed"].sum()),
        "predictions": len(predictions),
        "fold_records": len(folds),
        "evaluation_sessions": len(sessions),
    }
    audit_checks = {
        **{f"source_{key}": value for key, value in source_checks.items()},
        "candidate_ids_unique": not candidates.frame["candidate_id"].duplicated().any(),
        "candidate_decision_before_entry": bool(
            pd.to_datetime(candidates.frame["decision_at"], utc=True)
            .le(pd.to_datetime(candidates.frame["entry_at"], utc=True))
            .all()
        ),
        "candidate_exit_after_entry_when_observed": bool(
            pd.to_datetime(
                candidates.frame.loc[candidates.frame["execution_observed"], "exit_at"],
                utc=True,
            )
            .gt(
                pd.to_datetime(
                    candidates.frame.loc[
                        candidates.frame["execution_observed"], "entry_at"
                    ],
                    utc=True,
                )
            )
            .all()
        ),
        "protected_boundary": bool(
            pd.to_datetime(candidates.frame["decision_at"], utc=True)
            .lt(core.PROTECTED_BOUNDARY)
            .all()
        ),
        "fixed_threshold_only": bool(predictions["threshold"].dropna().eq(0.60).all()),
        "no_calibration_records": len(folds) == 8,
        "three_cost_scenarios": all(
            set(scenarios) == {"primary", "doubled", "stress"}
            for scenarios in all_metrics.values()
        ),
    }
    if not all(audit_checks.values()):
        raise ValueError(f"V37 runtime audit failed: {audit_checks}")
    payload = {
        "protocol_name": config["protocol_name"],
        "config_sha256": CONFIG_SHA256,
        "verdict": verdict,
        "counts": counts,
        "metrics": all_metrics,
        "promotion_checks": promotion_checks,
        "audit_checks": audit_checks,
    }
    identity = {
        "config": {"path": str(CONFIG_PATH), "sha256": CONFIG_SHA256},
        "runner": {"path": str(MODULE_PATH), "sha256": _sha_file(MODULE_PATH)},
        "core": {
            "path": str(Path(core.__file__).resolve()),
            "sha256": _sha_file(Path(core.__file__).resolve()),
        },
        "source_manifest": {
            "path": config["source"]["manifest_path"],
            "sha256": config["source"]["manifest_sha256"],
        },
        "created_at_utc": datetime.now(UTC).isoformat(),
    }
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    name = (
        f"v37_cross_market_breakout_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{CONFIG_SHA256[:8]}"
    )
    final = output_root / name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=output_root))
    try:
        candidates.frame.to_parquet(temporary / "candidates.parquet", index=False)
        np.savez_compressed(
            temporary / "features.npz",
            full=candidates.full_features,
            aggregate=candidates.aggregate_features,
            full_names=np.asarray(candidates.full_feature_names),
            aggregate_names=np.asarray(candidates.aggregate_feature_names),
        )
        predictions.to_parquet(temporary / "predictions.parquet", index=False)
        folds.to_csv(temporary / "fold_records.csv", index=False, encoding="utf-8-sig")
        for (variant, scenario), frame in trade_artifacts.items():
            frame.to_parquet(temporary / f"trades_{variant}_{scenario}.parquet", index=False)
        for (variant, scenario), frame in curve_artifacts.items():
            frame.to_parquet(temporary / f"daily_equity_{variant}_{scenario}.parquet", index=False)
        _write_json(temporary / "metrics.json", payload)
        _write_json(temporary / "identity.json", identity)
        (temporary / "report.md").write_text(_report(payload), encoding="utf-8-sig")
        artifact_manifest = {}
        for path in sorted(temporary.iterdir()):
            artifact_manifest[path.name] = {
                "bytes": path.stat().st_size,
                "sha256": _sha_file(path),
            }
        _write_json(
            temporary / "manifest.json",
            {
                "protocol_name": config["protocol_name"],
                "config_sha256": CONFIG_SHA256,
                "verdict": verdict,
                "artifacts": artifact_manifest,
            },
        )
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit_run(final)
    _write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("V37 artifact audit failed")
    return final


def audit_run(run_directory: Path) -> dict[str, bool]:
    manifest = json.loads(
        (run_directory / "manifest.json").read_text(encoding="utf-8-sig")
    )
    checks = {
        "protocol_exact": manifest["protocol_name"]
        == "stocks-v37-cross-market-breakout",
        "config_exact": manifest["config_sha256"] == CONFIG_SHA256,
    }
    for name, item in manifest["artifacts"].items():
        path = run_directory / name
        checks[f"artifact_{name}"] = (
            path.is_file()
            and path.stat().st_size == int(item["bytes"])
            and _sha_file(path) == item["sha256"]
        )
    metrics = json.loads((run_directory / "metrics.json").read_text(encoding="utf-8-sig"))
    checks["runtime_audit_all_true"] = all(metrics["audit_checks"].values())
    checks["verdict_exact"] = metrics["verdict"] == manifest["verdict"]
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit_run(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(run_experiment(args.output_root))


if __name__ == "__main__":
    main()
