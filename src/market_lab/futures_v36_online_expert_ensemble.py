"""Byte-sealed V36 multi-era online expert ensemble and exact futures ledger."""

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
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v26_stlfsi_levered_ruonia_capacity as v26
from market_lab import futures_v29_risk_first_roll as v29
from market_lab.futures import online_expert_ensemble as core

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v36_online_expert_ensemble.yaml"
CONFIG_SHA256: Final[str] = "cb391e44f9da66b1edc1931b43e0124bafd6253a836de1f44dfdf33fefdfdf39"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
CORE_PATH: Final[Path] = Path(core.__file__).resolve()


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


def load_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if actual != CONFIG_SHA256 or declared != CONFIG_SHA256:
        raise ValueError("V36 config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        config.get("protocol_id") != "futures_v36_online_expert_ensemble_v1"
        or config.get("live_trading_allowed") is not False
        or str(config["dates"]["forbidden_from"]) != "2026-01-01"
        or tuple(config["experts"]["ordered"]) != core.EXPERTS
        or float(config["portfolio"]["maximum_risk_multiplier"]) != 2.0
    ):
        raise ValueError("V36 economic invariant drift")
    return config


def _declarations(config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    output = [(f"panel_{index}", value) for index, value in enumerate(config["inputs"]["panels"])]
    for index, era in enumerate(config["inputs"]["execution_eras"]):
        for kind in ("active_map", "observations", "specs"):
            output.append((f"era_{index}_{kind}", era[kind]))
    return output


def preflight(config: dict[str, Any]) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    metadata: dict[str, Any] = {}
    for name, declaration in _declarations(config):
        path = (PROJECT_ROOT / declaration["path"]).resolve()
        exists = path.is_file()
        checks[f"{name}_exists"] = exists
        checks[f"{name}_bytes"] = exists and path.stat().st_size == int(declaration["bytes"])
        checks[f"{name}_sha"] = exists and _sha(path) == declaration["sha256"]
        if exists:
            parquet = pq.ParquetFile(path)
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
            metadata[name] = {
                "path": declaration["path"],
                "rows": parquet.metadata.num_rows,
                "columns": parquet.schema_arrow.names,
                "sha256": _sha(path),
            }
    panel_dates = []
    for declaration in config["inputs"]["panels"]:
        path = PROJECT_ROOT / declaration["path"]
        dates = pd.to_datetime(pd.read_parquet(path, columns=["trade_date"])["trade_date"])
        panel_dates.extend([dates.min(), dates.max()])
    checks["source_start_exact"] = min(panel_dates) == pd.Timestamp(config["dates"]["source_start"])
    checks["source_end_exact"] = max(panel_dates) == pd.Timestamp(config["dates"]["evaluation_end"])
    checks["protected_boundary_exact"] = max(panel_dates) < pd.Timestamp("2026-01-01")
    return {"checks": checks, "metadata": metadata}


def _read_inputs(config: dict[str, Any]) -> tuple[pd.DataFrame, ...]:
    panels = [pd.read_parquet(PROJECT_ROOT / item["path"]) for item in config["inputs"]["panels"]]
    panel = pd.concat(panels, ignore_index=True).sort_values(
        ["trade_date", "asset_code"], kind="stable", ignore_index=True
    )
    active_parts = []
    observation_parts = []
    spec_parts = []
    for era in config["inputs"]["execution_eras"]:
        active_parts.append(pd.read_parquet(PROJECT_ROOT / era["active_map"]["path"]))
        observation_parts.append(pd.read_parquet(PROJECT_ROOT / era["observations"]["path"]))
        spec_parts.append(pd.read_parquet(PROJECT_ROOT / era["specs"]["path"]))
    active = pd.concat(active_parts, ignore_index=True)
    observations = pd.concat(observation_parts, ignore_index=True)
    specs = pd.concat(spec_parts, ignore_index=True)
    return panel, active, observations, specs


def _annual_returns(ledger: pd.DataFrame, years: tuple[int, ...]) -> dict[str, float]:
    if ledger.empty:
        return {str(year): 0.0 for year in years}
    dates = pd.to_datetime(ledger["session_date"], errors="raise")
    daily = ledger["ending_cash"].astype(float) / ledger["starting_cash"].astype(float) - 1.0
    return {
        str(year): float(np.prod(1.0 + daily.loc[dates.dt.year.eq(year)]) - 1.0)
        for year in years
    }


def _scenario_summary(result: Any, years: tuple[int, ...]) -> dict[str, Any]:
    metrics = {str(key): value for key, value in result.metrics.items()}
    annual = _annual_returns(result.ledger, years)
    metrics.update(
        {
            "annual_returns": annual,
            "positive_years": sum(value > 0.0 for value in annual.values()),
            "worst_year": min(annual.values()),
            "metrics_valid": bool(result.execution_complete),
        }
    )
    return metrics


def _assessment(
    metrics: dict[str, dict[str, dict[str, Any]]], config: dict[str, Any]
) -> dict[str, Any]:
    online = metrics["online_expert"]
    primary = online["primary"]
    stress = online["stress"]
    gates = config["reporting"]["gates"]
    comparisons = (
        metrics["static_equal_active_experts"]["primary"]["cagr"],
        metrics["frozen_three_sleeve"]["primary"]["cagr"],
    )
    conditions = {
        "all_scenario_cagr_at_least_20": all(
            float(item["cagr"]) >= float(gates["all_scenario_cagr_minimum"])
            for item in online.values()
        ),
        "primary_and_stress_sharpe_at_least_1": float(primary["sharpe"])
        >= float(gates["primary_and_stress_sharpe_minimum"])
        and float(stress["sharpe"]) >= float(gates["primary_and_stress_sharpe_minimum"]),
        "all_scenario_mdd_at_most_30": all(
            float(item["maximum_drawdown"]) <= float(gates["all_scenario_mdd_maximum"])
            for item in online.values()
        ),
        "primary_positive_years_at_least_10": int(primary["positive_years"])
        >= int(gates["primary_positive_years_minimum"]),
        "primary_worst_year_at_least_minus_20": float(primary["worst_year"])
        >= float(gates["primary_worst_year_minimum"]),
        "online_beats_both_static_primary_cagr": float(primary["cagr"]) > max(comparisons),
        "zero_critical_or_unresolved": all(
            int(item["critical_failure_count"]) == 0
            and int(item["unresolved_halt_count"]) == 0
            for item in online.values()
        ),
    }
    passed = all(conditions.values())
    supports_50 = passed and all(
        float(item["cagr"]) >= float(gates["aspirational_all_scenario_cagr"])
        for item in online.values()
    )
    return {
        "verdict": "GO_TO_NEW_FORWARD_CONFIRMATION" if passed else "NO_GO",
        "conditions": conditions,
        "supports_20_percent": passed,
        "supports_50_percent": supports_50,
        "independent_confirmation": False,
        "live_trading_allowed": False,
    }


def run(config: dict[str, Any], output_root: Path) -> Path:
    verified = preflight(config)
    if not all(verified["checks"].values()):
        raise ValueError("V36 preflight failed")
    panel, active, observations, specs = _read_inputs(config)
    if panel.duplicated(["trade_date", "asset_code"]).any():
        raise ValueError("V36 combined panel has duplicate date/asset")
    experts = core.build_expert_scores(panel, config)
    if not all(experts.checks.values()):
        raise ValueError("V36 expert build failed")
    execution_market = v12.build_execution_market(observations, specs)
    evaluation_start = pd.Timestamp(config["dates"]["evaluation_start"])
    evaluation_end = pd.Timestamp(config["dates"]["evaluation_end"])
    market_dates = pd.to_datetime(execution_market["session_date"])
    predecessor = market_dates[market_dates < evaluation_start].max()
    execution_market = execution_market.loc[
        market_dates.between(predecessor, evaluation_end)
    ].copy()
    scenario_settings = config["execution"]["scenarios"]
    years = tuple(int(year) for year in config["reporting"]["required_years"])
    metrics: dict[str, dict[str, dict[str, Any]]] = {}
    artifacts: dict[str, pd.DataFrame] = {}
    target_counts: dict[str, Any] = {}
    for variant, scores in experts.scores.items():
        weekly = v12.build_weekly_weights(panel, scores)
        restored, risk = core.restore_weekly_weights(weekly, scores, config)
        target_build = v12.build_execution_targets(
            restored,
            active,
            oos_start=evaluation_start,
            oos_end=evaluation_end,
        )
        coverage = v12.execution_coverage(execution_market, target_build.targets)
        artifacts[f"scores_{variant}"] = scores
        artifacts[f"weekly_{variant}"] = restored
        artifacts[f"risk_{variant}"] = risk
        artifacts[f"targets_{variant}"] = target_build.targets
        artifacts[f"coverage_{variant}"] = coverage
        metrics[variant] = {}
        target_counts[variant] = {
            "weekly_decisions": target_build.weekly_decisions,
            "roll_decisions": target_build.roll_decisions,
            "target_rows": len(target_build.targets),
            "nonzero_targets": int(target_build.targets["target_weight"].abs().gt(1e-12).sum()),
            "covered_nonzero_targets": int(coverage["execution_dependencies_complete"].sum()),
        }
        for scenario, settings in scenario_settings.items():
            result = v29.run_risk_first_portfolio_ledger(
                execution_market,
                target_build.targets,
                v26.CapacityAwareLeveredLedgerConfig(
                    slippage_ticks=int(settings["slippage_ticks"]),
                    fee_multiplier=float(settings["fee_multiplier"]),
                ),
            )
            metrics[variant][scenario] = _scenario_summary(result, years)
            artifacts[f"ledger_{variant}_{scenario}"] = result.ledger
            artifacts[f"orders_{variant}_{scenario}"] = result.orders
            artifacts[f"positions_{variant}_{scenario}"] = result.positions
    payload = {
        "protocol_id": config["protocol_id"],
        "config_sha256": CONFIG_SHA256,
        "source_checks": verified["checks"],
        "expert_checks": experts.checks,
        "counts": {
            "panel_rows": len(panel),
            "panel_sessions": panel["trade_date"].nunique(),
            "expert_weight_rows": len(experts.expert_weights),
            "expert_component_rows": len(experts.expert_components),
            "targets": target_counts,
        },
        "metrics": metrics,
    }
    payload["assessment"] = _assessment(metrics, config)
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    name = f"v36_online_expert_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{CONFIG_SHA256[:8]}"
    final = output_root / name
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=output_root))
    try:
        (temporary / "resolved_config.yaml").write_bytes(CONFIG_PATH.read_bytes())
        experts.expert_weights.to_parquet(temporary / "expert_weights.parquet", index=False)
        experts.expert_components.to_parquet(temporary / "expert_components.parquet", index=False)
        for artifact_name, frame in artifacts.items():
            frame.to_parquet(temporary / f"{artifact_name}.parquet", index=False)
        _write_json(temporary / "metrics.json", payload)
        artifact_paths = sorted(path for path in temporary.iterdir() if path.is_file())
        identity = {
            "config_sha256": CONFIG_SHA256,
            "runner_sha256": _sha(MODULE_PATH),
            "core_sha256": _sha(CORE_PATH),
            "artifacts": [
                {"path": path.name, "bytes": path.stat().st_size, "sha256": _sha(path)}
                for path in artifact_paths
            ],
        }
        _write_json(temporary / "identity.json", identity)
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit(final)
    _write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("V36 audit failed")
    return final


def audit(run_directory: Path) -> dict[str, bool]:
    identity = json.loads((run_directory / "identity.json").read_text(encoding="utf-8-sig"))
    metrics = json.loads((run_directory / "metrics.json").read_text(encoding="utf-8-sig"))
    exact = True
    for item in identity["artifacts"]:
        path = run_directory / item["path"]
        exact &= (
            path.is_file()
            and path.stat().st_size == item["bytes"]
            and _sha(path) == item["sha256"]
        )
    return {
        "config_exact": identity["config_sha256"] == CONFIG_SHA256,
        "runner_exact": identity["runner_sha256"] == _sha(MODULE_PATH),
        "core_exact": identity["core_sha256"] == _sha(CORE_PATH),
        "artifacts_exact": bool(exact),
        "source_checks_true": all(metrics["source_checks"].values()),
        "expert_checks_true": all(metrics["expert_checks"].values()),
        "live_forbidden": metrics["assessment"]["live_trading_allowed"] is False,
        "claims_boolean": isinstance(metrics["assessment"]["supports_20_percent"], bool)
        and isinstance(metrics["assessment"]["supports_50_percent"], bool),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--audit-run", type=Path)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    args = parser.parse_args()
    config = load_config()
    if args.audit_run:
        checks = audit(args.audit_run)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
        return
    if args.preflight_only:
        result = preflight(config)
        print(json.dumps(result, indent=2))
        return
    output = run(config, args.output_root)
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    print(json.dumps({"output": str(output), "metrics": metrics}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
