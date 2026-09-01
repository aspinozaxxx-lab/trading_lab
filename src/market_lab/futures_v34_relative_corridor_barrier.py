"""Sealed V34 RI/MIX relative-corridor barrier experiment."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as parquet
import sklearn
import yaml

from market_lab import futures_v32_curve_regime_intraday as v32
from market_lab.futures.relative_corridor_barrier import (
    MODEL_CURVE_META,
    MODEL_FIXED_RULE,
    MODEL_IDS,
    MODEL_MARKET_META,
    CorridorSettings,
    MetaModelSettings,
    PairExecutionSettings,
    PairRiskSettings,
    build_corridor_candidates,
    run_barrier_walk_forward,
    simulate_atomic_pair_portfolio,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v34_relative_corridor_barrier.yaml"
SIDECAR_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v34_relative_corridor_barrier.sha256"
CORE_MODULE_PATH: Final[Path] = (
    PROJECT_ROOT / "src/market_lab/futures/relative_corridor_barrier.py"
)
RUNNER_MODULE_PATH: Final[Path] = Path(__file__).resolve()
PROTOCOL_ID: Final[str] = "futures_v34_relative_corridor_barrier_v1"


def sha256_file(path: Path) -> str:
    digest = sha256()
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
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if pd.isna(value) and not isinstance(value, (str, bytes)):
        return None
    return value


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON root must be an object: {path}")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def _sidecar_hash() -> str:
    text = SIDECAR_PATH.read_text(encoding="utf-8-sig").strip()
    token = text.split()[0].lower() if text else ""
    if len(token) != 64 or any(character not in "0123456789abcdef" for character in token):
        raise ValueError("V34 config sidecar is malformed")
    return token


def _repo_path(relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"V34 path must be repo-relative: {relative}")
    return PROJECT_ROOT / candidate


def _verify_file(record: dict[str, Any], label: str) -> Path:
    path = _repo_path(str(record["path"]))
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"{label} byte count drift")
    if sha256_file(path) != str(record["sha256"]):
        raise ValueError(f"{label} SHA-256 drift")
    return path


def load_protocol() -> dict[str, Any]:
    expected = _sidecar_hash()
    if sha256_file(CONFIG_PATH) != expected:
        raise ValueError("sealed V34 protocol byte drift")
    protocol = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V34 protocol must be a mapping")
    if (
        protocol.get("protocol_id") != PROTOCOL_ID
        or protocol.get("status") != "sealed_before_first_v34_economic_read"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
    ):
        raise ValueError("V34 protocol invariants were weakened")
    implementation = protocol["implementation"]
    if sha256_file(CORE_MODULE_PATH) != str(implementation["core_sha256"]):
        raise ValueError("V34 core implementation byte drift")
    if sha256_file(RUNNER_MODULE_PATH) != str(implementation["runner_sha256"]):
        raise ValueError("V34 runner implementation byte drift")
    parent = protocol["parent_v32"]
    _verify_file(parent["config"], "V32 config")
    _verify_file(parent["config_sidecar"], "V32 config sidecar")
    _verify_file(parent["core"], "V32 core")
    _verify_file(parent["runner"], "V32 runner")
    parent_protocol = v32.load_protocol()
    if parent_protocol["protocol_id"] != "futures_v32_curve_regime_intraday_cross_asset_v1":
        raise ValueError("V34 parent protocol identity drift")
    return protocol


def metadata_preflight(protocol: dict[str, Any]) -> dict[str, Any]:
    parent = v32.metadata_preflight(v32.load_protocol())
    expected = protocol["pre_outcome_metadata_seal"]
    counts = {
        "active_bar_rows": int(parent["counts"]["active_bar_rows"]),
        "common_four_bars": int(parent["counts"]["common_four_bars"]),
        "curve_events": int(parent["counts"]["curve_events"]),
        "events_with_structural_decisions": int(
            parent["counts"]["events_with_structural_decisions"]
        ),
        "structural_decisions": int(parent["counts"]["structural_decisions"]),
    }
    checks = {
        "parent_metadata_preflight_all_true": all(parent["checks"].values()),
        "expected_active_bar_rows": counts["active_bar_rows"]
        == int(expected["active_bar_rows"]),
        "expected_common_four_bars": counts["common_four_bars"]
        == int(expected["common_four_bars"]),
        "expected_curve_events": counts["curve_events"] == int(expected["curve_events"]),
        "expected_structural_event_days": counts["events_with_structural_decisions"]
        == int(expected["events_with_structural_decisions"]),
        "expected_structural_decisions": counts["structural_decisions"]
        == int(expected["structural_decisions"]),
        "metadata_scope_excludes_price_return_target_and_pnl": bool(
            expected["metadata_only_no_market_values"]
        ),
        "protected_boundary_is_2026": protocol["boundaries"]["protected_from"]
        == "2026-01-01",
    }
    if not all(checks.values()):
        raise ValueError(f"V34 metadata preflight failed: {checks}")
    return {
        "scope": "parent identities and structural metadata only",
        "counts": counts,
        "checks": checks,
    }


def _settings(
    protocol: dict[str, Any],
) -> tuple[CorridorSettings, MetaModelSettings, PairRiskSettings]:
    model_payload = dict(protocol["validation_and_model"])
    for key in ("probability_thresholds", "hidden_layers", "seeds"):
        model_payload[key] = tuple(model_payload[key])
    return (
        CorridorSettings(**protocol["corridor"]),
        MetaModelSettings(**model_payload),
        PairRiskSettings(**protocol["pair_risk"]),
    )


def _scenario_settings(protocol: dict[str, Any], scenario: str) -> PairExecutionSettings:
    execution = protocol["execution"]
    scenario_record = execution["scenarios"][scenario]
    return PairExecutionSettings(
        initial_cash=float(execution["initial_cash_rub"]),
        slippage_ticks=int(scenario_record["slippage_ticks"]),
        fee_multiplier=float(scenario_record["fee_multiplier"]),
        signal_participation=float(execution["signal_participation"]),
        factual_participation_cap=float(execution["factual_participation_cap"]),
        margin_buffer_multiple=float(execution["margin_buffer_multiple"]),
        maximum_exit_retry_bars=int(execution["maximum_exit_retry_bars"]),
        maximum_trades_per_day=int(execution["maximum_trades_per_day"]),
    )


def _promotion(
    protocol: dict[str, Any],
    results: dict[str, dict[str, Any]],
    counts: dict[str, int],
    checks: dict[str, bool],
) -> dict[str, Any]:
    primary = results[f"{MODEL_CURVE_META}:primary"]
    doubled = results[f"{MODEL_CURVE_META}:doubled"]
    stress = results[f"{MODEL_CURVE_META}:stress"]
    market = results[f"{MODEL_MARKET_META}:primary"]
    fixed = results[f"{MODEL_FIXED_RULE}:primary"]
    best_baseline_cagr = max(float(market["cagr"]), float(fixed["cagr"]))
    best_baseline_sharpe = max(
        float(market["annualized_sharpe"]), float(fixed["annualized_sharpe"])
    )
    gates = protocol["promotion_rule"]
    conditions = {
        "all_integrity_and_temporal_checks_true": all(checks.values()),
        "all_curve_cost_ledgers_complete": all(
            bool(results[f"{MODEL_CURVE_META}:{name}"]["execution_complete"])
            for name in ("primary", "doubled", "stress")
        ),
        "both_primary_baselines_complete": bool(market["execution_complete"])
        and bool(fixed["execution_complete"]),
        "minimum_filled_order_legs": int(primary["filled_order_legs"])
        >= int(gates["minimum_filled_order_legs"]),
        "all_cost_cagr_at_least_20_percent": min(
            float(primary["cagr"]), float(doubled["cagr"]), float(stress["cagr"])
        )
        >= float(gates["minimum_cagr"]),
        "primary_sharpe_at_least_one": float(primary["annualized_sharpe"])
        >= float(gates["minimum_sharpe"]),
        "primary_maximum_drawdown_at_most_25_percent": float(primary["maximum_drawdown"])
        <= float(gates["maximum_drawdown"]),
        "all_three_calendar_segments_positive": int(primary["positive_years"])
        >= int(gates["minimum_positive_calendar_segments"]),
        "incremental_cagr_over_best_baseline": float(primary["cagr"])
        >= best_baseline_cagr + float(gates["minimum_cagr_advantage_over_baseline"]),
        "incremental_sharpe_over_best_baseline": float(primary["annualized_sharpe"])
        >= best_baseline_sharpe + float(gates["minimum_sharpe_advantage_over_baseline"]),
        "zero_unresolved": int(primary["unresolved_count"]) == 0,
        "candidate_and_active_coverage_nonempty": counts["evaluation_candidates"] > 0
        and counts["active_curve_signals"] > 0,
    }
    support_20 = bool(all(conditions.values()))
    support_50 = bool(
        support_20
        and min(float(primary["cagr"]), float(doubled["cagr"]), float(stress["cagr"]))
        >= float(gates["aspirational_cagr"])
    )
    return {
        "conditions": conditions,
        "best_baseline_cagr": best_baseline_cagr,
        "best_baseline_sharpe": best_baseline_sharpe,
        "supports_20_percent_cagr": support_20,
        "supports_50_percent_cagr": support_50,
        "verdict": (
            "ADAPTIVE_LEAD_REQUIRES_NEW_FORWARD_VALIDATION" if support_20 else "NO_GO"
        ),
        "live_trading_allowed": False,
    }


def _report_text(payload: dict[str, Any]) -> str:
    results = payload["results"]
    promotion = payload["promotion"]

    def result_row(label: str, key: str) -> str:
        result = results[key]
        return (
            f"| {label} | {result['cagr']:.4%} | {result['annualized_sharpe']:.3f} | "
            f"{result['maximum_drawdown']:.4%} | {result['total_return']:.4%} | "
            f"{result['completed_pair_trades']} | {result['execution_complete']} |"
        )

    primary = results[f"{MODEL_CURVE_META}:primary"]
    return "\n".join(
        (
            "# V34 RI–MIX relative-corridor barrier",
            "",
            f"Verdict: **{promotion['verdict']}**. Live trading: **forbidden**.",
            "",
            "V34 predicts whether a relative RI–MIX deviation will reach a fixed",
            "take-profit corridor before a three-times-distant stop. It does not predict",
            "the absolute next-hour return. Every pair is entered and exited atomically.",
            "",
            "| Variant | CAGR | Sharpe | MDD | Total return | Pair trades | Complete |",
            "|---|---:|---:|---:|---:|---:|---|",
            result_row("curve meta MLP primary", f"{MODEL_CURVE_META}:primary"),
            result_row("curve meta MLP doubled", f"{MODEL_CURVE_META}:doubled"),
            result_row("curve meta MLP stress", f"{MODEL_CURVE_META}:stress"),
            result_row("market-only meta MLP", f"{MODEL_MARKET_META}:primary"),
            result_row("fixed corridor", f"{MODEL_FIXED_RULE}:primary"),
            "",
            f"Primary calendar returns: `{primary['annual_returns']}`.",
            (
                f"Candidates: {payload['counts']['candidate_rows']}; evaluation candidates: "
                f"{payload['counts']['evaluation_candidates']}; active curve signals: "
                f"{payload['counts']['active_curve_signals']}."
            ),
            (
                f"Filled legs: {primary['filled_order_legs']}; total costs: "
                f"{primary['total_cost']:.2f} RUB; unresolved: {primary['unresolved_count']}."
            ),
            "",
            "This remains adaptive historical research. A passing result would require a",
            "new sealed forward collection and shadow/paper validation; it is not evidence",
            "of guaranteed future profit.",
            "",
        )
    )


def _artifact_record(path: Path) -> dict[str, object]:
    record: dict[str, object] = {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if path.suffix == ".parquet":
        record["rows"] = parquet.ParquetFile(path).metadata.num_rows
    return record


def run_experiment(output_root: Path) -> Path:
    protocol = load_protocol()
    preflight = metadata_preflight(protocol)
    common, context, provenance = v32.load_economic_inputs(v32.load_protocol())
    corridor_settings, model_settings, risk_settings = _settings(protocol)
    candidates = build_corridor_candidates(common, context, corridor_settings)
    walk = run_barrier_walk_forward(candidates, model_settings)
    if walk.predictions.empty:
        raise ValueError("V34 walk-forward produced no prediction records")
    evaluation_start = pd.Timestamp(
        protocol["boundaries"]["evaluation_start"], tz="Europe/Moscow"
    ).tz_convert("UTC")
    evaluation_end = (
        pd.Timestamp(protocol["boundaries"]["evaluation_end"], tz="Europe/Moscow")
        + pd.Timedelta(days=1)
    ).tz_convert("UTC")
    execution_panel = common.loc[
        common["timestamp"].ge(evaluation_start) & common["timestamp"].lt(evaluation_end)
    ].copy()
    simulations: dict[str, Any] = {}
    results: dict[str, dict[str, Any]] = {}
    for model_id in MODEL_IDS:
        scenario_names = (
            ("primary", "doubled", "stress")
            if model_id == MODEL_CURVE_META
            else ("primary",)
        )
        for scenario in scenario_names:
            key = f"{model_id}:{scenario}"
            simulation = simulate_atomic_pair_portfolio(
                execution_panel,
                walk.predictions,
                model_id,
                risk_settings,
                _scenario_settings(protocol, scenario),
            )
            simulations[key] = simulation
            results[key] = dict(simulation.metrics)
    fold_causality = True
    if not walk.folds.empty:
        checkable = walk.folds.loc[
            walk.folds["status"].isin(["predicted", "sleep_calibration_gate"])
        ]
        for row in checkable.to_dict("records"):
            fold_causality &= bool(
                pd.Timestamp(row["core_max_target_end_at"])
                < pd.Timestamp(row["calibration_min_decision_at"])
                and pd.Timestamp(row["calibration_max_target_end_at"])
                < pd.Timestamp(row["test_min_decision_at"])
            )
    evaluation_mask = candidates["decision_at"].ge(evaluation_start) & candidates[
        "decision_at"
    ].lt(evaluation_end)
    checks = {
        "metadata_preflight_all_true": all(preflight["checks"].values()),
        "candidate_decisions_after_source_availability": bool(
            candidates["decision_at"].ge(candidates["source_available_at"]).all()
        ),
        "candidate_targets_before_2026": bool(
            candidates["target_end_at"].lt(pd.Timestamp("2026-01-01", tz="UTC")).all()
        ),
        "candidate_exits_are_next_open_within_frozen_horizon": bool(
            candidates["barrier_exit_at"].gt(candidates["entry_at"]).all()
            and candidates["barrier_exit_at"]
            .sub(candidates["entry_at"])
            .le(pd.Timedelta(minutes=120))
            .all()
        ),
        "monthly_core_calibration_test_are_purged": fold_causality,
        "prediction_model_ids_are_predeclared": set(walk.predictions["model_id"]).issubset(
            set(MODEL_IDS)
        ),
        "execution_panel_stops_before_2026": bool(
            execution_panel["timestamp"].lt(pd.Timestamp("2026-01-01", tz="UTC")).all()
        ),
        "no_live_trading_claim": protocol["live_trading_allowed"] is False,
        "no_post_outcome_parameter_tuning": protocol["outcome_boundary"][
            "post_outcome_parameter_tuning_inside_V34"
        ]
        == "forbidden",
    }
    counts = {
        **{key: int(value) for key, value in provenance.items()},
        "candidate_rows": int(len(candidates)),
        "candidate_source_events": int(candidates["source_event_date"].nunique()),
        "positive_barrier_targets": int(candidates["barrier_target"].sum()),
        "evaluation_candidates": int(evaluation_mask.sum()),
        "prediction_rows": int(len(walk.predictions)),
        "active_curve_signals": int(
            walk.predictions.loc[
                walk.predictions["model_id"].eq(MODEL_CURVE_META), "active_signal"
            ].sum()
        ),
        "active_market_signals": int(
            walk.predictions.loc[
                walk.predictions["model_id"].eq(MODEL_MARKET_META), "active_signal"
            ].sum()
        ),
        "active_fixed_signals": int(
            walk.predictions.loc[
                walk.predictions["model_id"].eq(MODEL_FIXED_RULE), "active_signal"
            ].sum()
        ),
        "fold_records": int(len(walk.folds)),
    }
    promotion = _promotion(protocol, results, counts, checks)
    payload: dict[str, Any] = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": _sidecar_hash(),
        "created_at_utc": datetime.now(UTC),
        "research_only": True,
        "live_trading_allowed": False,
        "source_limitations": protocol["source_limitations"],
        "runtime": {
            "python": os.sys.version,
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "settings": {
            "corridor": asdict(corridor_settings),
            "model": asdict(model_settings),
            "risk": asdict(risk_settings),
        },
        "preflight": preflight,
        "counts": counts,
        "checks": checks,
        "results": results,
        "promotion": promotion,
    }
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v34_relative_corridor_{timestamp}_{_sidecar_hash()[:8]}"
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(final)
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        (temporary / "resolved_protocol.yaml").write_bytes(CONFIG_PATH.read_bytes())
        _write_json(temporary / "preflight.json", preflight)
        candidate_columns = [
            "decision_at",
            "entry_at",
            "target_end_at",
            "source_event_at",
            "source_available_at",
            "source_event_date",
            "corridor_z",
            "corridor_beta",
            "corridor_take_profit_barrier",
            "corridor_stop_barrier",
            "barrier_exit_at",
            "barrier_exit_reason",
            "barrier_net_stress_return",
            "barrier_target",
        ]
        candidates.loc[:, candidate_columns].to_parquet(
            temporary / "candidate_audit.parquet", index=False
        )
        walk.predictions.to_parquet(temporary / "predictions.parquet", index=False)
        folds_to_write = walk.folds.copy()
        if "threshold_candidates" in folds_to_write:
            folds_to_write["threshold_candidates"] = folds_to_write[
                "threshold_candidates"
            ].map(
                lambda value: (
                    json.dumps(_json_safe(value), sort_keys=True)
                    if isinstance(value, list)
                    else None
                )
            )
        folds_to_write.to_parquet(temporary / "folds.parquet", index=False)
        for key, simulation in simulations.items():
            safe = key.replace(":", "_")
            simulation.ledger.to_parquet(temporary / f"ledger_{safe}.parquet", index=False)
            simulation.orders.to_parquet(temporary / f"orders_{safe}.parquet", index=False)
            simulation.trades.to_parquet(temporary / f"trades_{safe}.parquet", index=False)
            simulation.skipped_entries.to_parquet(
                temporary / f"skipped_{safe}.parquet", index=False
            )
            simulation.unresolved.to_parquet(
                temporary / f"unresolved_{safe}.parquet", index=False
            )
        artifact_paths = sorted(
            path
            for path in temporary.iterdir()
            if path.name not in {"metrics.json", "identity.json", "report.md"}
        )
        payload["artifacts"] = {path.name: _artifact_record(path) for path in artifact_paths}
        (temporary / "report.md").write_text(_report_text(payload), encoding="utf-8-sig")
        payload["artifacts"]["report.md"] = _artifact_record(temporary / "report.md")
        _write_json(temporary / "metrics.json", payload)
        identity = {
            "protocol_id": protocol["protocol_id"],
            "protocol_sha256": _sidecar_hash(),
            "core_sha256": sha256_file(CORE_MODULE_PATH),
            "runner_sha256": sha256_file(RUNNER_MODULE_PATH),
            "metrics_sha256": sha256_file(temporary / "metrics.json"),
            "artifact_names": sorted(path.name for path in temporary.iterdir()),
        }
        _write_json(temporary / "identity.json", identity)
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def audit_run(run_path: Path) -> dict[str, Any]:
    identity = _read_json(run_path / "identity.json")
    metrics_path = run_path / "metrics.json"
    if sha256_file(metrics_path) != str(identity["metrics_sha256"]):
        raise ValueError("V34 metrics SHA drift")
    metrics = _read_json(metrics_path)
    checks: dict[str, bool] = {}
    for name, record in metrics["artifacts"].items():
        path = run_path / name
        checks[f"artifact:{name}"] = bool(
            path.is_file()
            and path.stat().st_size == int(record["bytes"])
            and sha256_file(path) == str(record["sha256"])
        )
        if checks[f"artifact:{name}"] and path.suffix == ".parquet":
            checks[f"rows:{name}"] = parquet.ParquetFile(path).metadata.num_rows == int(
                record["rows"]
            )
    checks["recorded_checks_all_true"] = all(metrics["checks"].values())
    checks["identity_matches_sealed_implementation"] = bool(
        identity["protocol_sha256"] == _sidecar_hash()
        and identity["core_sha256"] == sha256_file(CORE_MODULE_PATH)
        and identity["runner_sha256"] == sha256_file(RUNNER_MODULE_PATH)
    )
    checks["exact_recorded_directory_members"] = set(
        path.name for path in run_path.iterdir()
    ) == {*identity["artifact_names"], "identity.json"}
    if not all(checks.values()):
        raise ValueError(f"V34 run audit failed: {checks}")
    return {
        "run": str(run_path),
        "checks": checks,
        "metrics_sha256": identity["metrics_sha256"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--audit-run", type=Path)
    arguments = parser.parse_args()
    protocol = load_protocol()
    if arguments.preflight_only:
        print(json.dumps(_json_safe(metadata_preflight(protocol)), ensure_ascii=False, indent=2))
        return
    if arguments.audit_run is not None:
        print(json.dumps(_json_safe(audit_run(arguments.audit_run)), ensure_ascii=False, indent=2))
        return
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()


__all__ = [
    "CONFIG_PATH",
    "PROJECT_ROOT",
    "SIDECAR_PATH",
    "audit_run",
    "load_protocol",
    "main",
    "metadata_preflight",
    "run_experiment",
    "sha256_file",
]
