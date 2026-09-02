"""Run the sealed V49 exact 2x development challenger without a scale search."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v15_levered_ruonia_collateral as v15
from market_lab import futures_v27_key_rate_extreme_governor as v27
from market_lab import futures_v48_v47_exact_integer_execution as v48
from market_lab.futures import moex_stock_futures_cash_carry_source as artifact_io
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v49_v39_double_risk_exact_execution_v1.yaml"
CONFIG_SHA256: Final[str] = "37b4fcb0e346b1a03f414899891bcecb3cc71f3103a2d54d54184a52bf981f3d"
MODE: Final[str] = "double_risk"
SCENARIOS: Final[tuple[str, ...]] = v48.SCENARIOS
UNIQUE_FUTURES_SCENARIOS: Final[tuple[str, ...]] = v48.UNIQUE_FUTURES_SCENARIOS
REQUIRED_GATES: Final[tuple[str, ...]] = (
    "execution_complete",
    "zero_critical_failures",
    "zero_unresolved_halts",
    "zero_participation_clips",
    "zero_initial_margin_rejections",
    "maximum_participation",
    "all_nav_positive",
    "primary_cagr",
    "all_scenario_cagr",
    "all_scenario_sharpe",
    "all_scenario_mdd",
    "all_scenario_worst_year",
    "primary_positive_years",
)


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    v48_protocol: v48.Protocol
    benchmark_root: Path


@dataclass(frozen=True, slots=True)
class DoubleRiskLedgerConfig:
    initial_cash: float
    expected_assets: tuple[str, ...]
    maximum_gross_notional_multiple: float
    initial_margin_buffer_multiplier: float
    maximum_participation: float
    slippage_ticks: Literal[1, 2, 4]
    fee_multiplier: Literal[1.0, 2.0]
    execution_atomicity: Literal["asset"] = "asset"
    terminal_policy: Literal["carry"] = "carry"
    unexecutable_target_policy: Literal["cancel_and_clip"] = "cancel_and_clip"

    def __post_init__(self) -> None:
        if (
            self.initial_cash != v12.INITIAL_CASH
            or self.expected_assets != v12.ASSETS
            or self.maximum_gross_notional_multiple != 4.0
            or self.initial_margin_buffer_multiplier != 2.0
            or self.maximum_participation != v12.MAXIMUM_PARTICIPATION
            or self.slippage_ticks not in {1, 2, 4}
            or self.fee_multiplier not in {1.0, 2.0}
        ):
            raise ValueError("V49 exact double-risk ledger settings drifted")


def _sha(path: Path) -> str:
    return artifact_io.sha256_file(path)


def _root(value: str) -> Path:
    relative = Path(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
        or relative.parts[0].lower() != "runs"
    ):
        raise ValueError(f"unsafe V49 run path: {value}")
    return PROJECT_ROOT / relative


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V49 config must be an object")
    parent = payload["parents"]["v48_engine"]
    benchmark = payload["parents"]["v48_canonical_benchmark"]
    risk = payload["risk_mode"]
    selection = payload["selection"]
    gates = payload["gates"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "futures_v49_v39_double_risk_exact_execution_v1"
        or payload.get("status") != "sealed_before_any_v49_order_position_or_pnl"
        or payload.get("adaptive_same_history") is not True
        or payload.get("selected_after_observing_v48") is not True
        or payload.get("live_trading_allowed") is not False
        or _sha(PROJECT_ROOT / parent["config"]) != parent["config_sha256"]
        or _sha(PROJECT_ROOT / parent["implementation"]) != parent["implementation_sha256"]
        or int(selection["candidate_count"]) != 1
        or float(selection["mapped_target_multiplier"]) != 2.0
        or selection["lower_or_higher_scale_comparison"] != "forbidden"
        or risk["name"] != MODE
        or float(risk["mapped_target_multiplier"]) != 2.0
        or float(risk["maximum_gross_notional_multiple"]) != 4.0
        or float(risk["initial_margin_buffer_multiplier"]) != 2.0
        or float(risk["broad_carry_cash_fraction"]) != 0.0
        or risk["volatility_drawdown_or_result_dependent_scaling"] != "forbidden"
        or float(payload["execution"]["maximum_lagged_volume_participation"]) != 0.01
        or float(gates["primary_cagr_gte"]) != 0.45
        or float(gates["all_scenario_cagr_gte"]) != 0.40
        or float(gates["stretch_primary_cagr_gte"]) != 0.50
        or gates["stretch_gate_is_reported_but_not_required_for_pass"] is not True
        or gates["live_promotion_forbidden"] is not True
    ):
        raise ValueError("V49 protocol drifted")
    parent_protocol = v48.load_protocol()
    if parent_protocol.config_sha256 != parent["config_sha256"]:
        raise ValueError("V49 loaded the wrong V48 protocol")
    benchmark_root = _root(benchmark["root"])
    for declaration in (benchmark["manifest"], benchmark["metrics"]):
        path = benchmark_root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"V49 benchmark drifted: {path.name}")
    benchmark_manifest = json.loads(
        (benchmark_root / benchmark["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    if benchmark_manifest["protocol_sha256"] != parent_protocol.config_sha256:
        raise ValueError("V49 benchmark protocol identity drifted")
    return Protocol(payload, actual, parent_protocol, benchmark_root)


def scale_targets(targets: pd.DataFrame, multiplier: float = 2.0) -> pd.DataFrame:
    if multiplier != 2.0:
        raise ValueError("V49 permits only the sealed 2.00x multiplier")
    output = targets.copy()
    output["v39_target_weight"] = pd.to_numeric(output["target_weight"], errors="raise").astype(
        float
    )
    output["target_weight"] = output["v39_target_weight"] * multiplier
    output["v49_mode"] = MODE
    output["provenance"] = (
        output["provenance"].astype("string") + "|v49_exact_target_multiplier_2.00"
    )
    zero = output["v39_target_weight"].eq(0.0)
    if not output.loc[zero, "target_weight"].eq(0.0).all():
        raise ValueError("V49 scaling changed a V39 zero target")
    nonzero = ~zero
    if (
        output.loc[nonzero, "target_weight"]
        .mul(output.loc[nonzero, "v39_target_weight"])
        .le(0.0)
        .any()
    ):
        raise ValueError("V49 scaling changed target direction")
    return output


def _combined_metrics(nav: pd.Series) -> dict[str, Any]:
    metrics = v48._metrics(nav)
    metrics["minimum_nav"] = float(nav.min())
    return metrics


def evaluate_gates(scenarios: dict[str, Any], config: dict[str, Any]) -> dict[str, bool]:
    gates = config["gates"]
    futures = [item["futures"] for item in scenarios.values()]
    combined = [item["combined"] for item in scenarios.values()]
    return {
        "execution_complete": all(item["execution_complete"] is True for item in futures),
        "zero_critical_failures": all(int(item["critical_failure_count"]) == 0 for item in futures),
        "zero_unresolved_halts": all(int(item["unresolved_halt_count"]) == 0 for item in futures),
        "zero_participation_clips": all(
            int(item["participation_clip_count"]) == 0 for item in futures
        ),
        "zero_initial_margin_rejections": all(
            int(item["initial_margin_rejection_count"]) == 0 for item in futures
        ),
        "maximum_participation": all(
            float(item["maximum_participation"])
            <= float(gates["maximum_participation_lte"]) + 1e-12
            for item in futures
        ),
        "all_nav_positive": all(float(item["minimum_nav"]) > 0.0 for item in combined),
        "primary_cagr": float(scenarios["primary"]["combined"]["cagr"])
        >= float(gates["primary_cagr_gte"]),
        "all_scenario_cagr": all(
            float(item["cagr"]) >= float(gates["all_scenario_cagr_gte"]) for item in combined
        ),
        "all_scenario_sharpe": all(
            float(item["sharpe"]) >= float(gates["all_scenario_sharpe_gte"]) for item in combined
        ),
        "all_scenario_mdd": all(
            float(item["maximum_drawdown"]) <= float(gates["all_scenario_mdd_lte"])
            for item in combined
        ),
        "all_scenario_worst_year": all(
            float(item["worst_year"]) >= float(gates["all_scenario_worst_year_gte"])
            for item in combined
        ),
        "primary_positive_years": int(scenarios["primary"]["combined"]["positive_years"])
        >= int(gates["primary_positive_years_gte"]),
        "stretch_primary_cagr_50": float(scenarios["primary"]["combined"]["cagr"])
        >= float(gates["stretch_primary_cagr_gte"]),
    }


def build(
    protocol: Protocol,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    market, ruonia = v48._prepare_inputs()
    base_targets = pd.read_parquet(protocol.v48_protocol.v39_root / "mapped_targets.parquet")
    targets = scale_targets(base_targets)
    gross = targets.groupby("effective_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    maximum_gross = float(protocol.payload["risk_mode"]["maximum_gross_notional_multiple"])
    if float(gross.max()) > maximum_gross + 1e-12:
        raise ValueError("V49 scaled target exceeds sealed gross")
    settings = v12._scenario_settings(v27.load_protocol())
    futures_results: dict[str, FuturesPortfolioLedgerResult] = {}
    collateral_results: dict[str, v15.CollateralEvaluation] = {}
    orders: list[pd.DataFrame] = []
    positions: list[pd.DataFrame] = []
    for scenario in UNIQUE_FUTURES_SCENARIOS:
        setting = settings[scenario]
        ledger_config = DoubleRiskLedgerConfig(
            initial_cash=v12.INITIAL_CASH,
            expected_assets=v12.ASSETS,
            maximum_gross_notional_multiple=maximum_gross,
            initial_margin_buffer_multiplier=float(
                protocol.payload["risk_mode"]["initial_margin_buffer_multiplier"]
            ),
            maximum_participation=v12.MAXIMUM_PARTICIPATION,
            slippage_ticks=int(setting["slippage_ticks"]),
            fee_multiplier=float(setting["fee_multiplier"]),
        )
        result = v48.run_scaled_ledger(market, targets, ledger_config)  # type: ignore[arg-type]
        futures_results[scenario] = result
        collateral_results[scenario] = v15.evaluate_collateral_income(result, ruonia)
        order_frame = result.orders.copy()
        order_frame.insert(0, "v49_mode", MODE)
        order_frame.insert(1, "scenario", scenario)
        orders.append(order_frame)
        position_frame = result.positions.copy()
        position_frame.insert(0, "v49_mode", MODE)
        position_frame.insert(1, "scenario", scenario)
        positions.append(position_frame)

    benchmark = json.loads(
        (protocol.benchmark_root / "metrics.json").read_text(encoding="utf-8-sig")
    )
    ledger_output: pd.DataFrame | None = None
    scenarios: dict[str, Any] = {}
    for scenario in SCENARIOS:
        futures_name = "stress" if scenario == "execution_stress" else scenario
        result = futures_results[futures_name]
        collateral = collateral_results[futures_name]
        exact_nav = collateral.combined_ledger.set_index("session_date")[
            "combined_ending_equity"
        ].astype(float)
        combined_nav = exact_nav / float(exact_nav.iloc[0])
        combined = _combined_metrics(combined_nav)
        futures_metrics = v12.scenario_metrics(result, market, settings[futures_name])
        benchmark_metrics = benchmark["modes"]["frontier"]["scenarios"][scenario]["combined"]
        scenarios[scenario] = {
            "futures": futures_metrics,
            "combined": combined,
            "delta_vs_v48_frontier": {
                key: float(combined[key]) - float(benchmark_metrics[key])
                for key in ("cagr", "sharpe", "maximum_drawdown", "worst_year")
            },
            "margin_buffer_multiplier": float(
                protocol.payload["risk_mode"]["initial_margin_buffer_multiplier"]
            ),
            "carry_cash_fraction": 0.0,
        }
        if ledger_output is None:
            ledger_output = pd.DataFrame({"session_date": combined_nav.index})
        ledger_output[f"{MODE}_{scenario}_combined_nav"] = combined_nav.to_numpy()
        ledger_output[f"{MODE}_{scenario}_exact_futures_nav"] = (
            exact_nav / float(exact_nav.iloc[0])
        ).to_numpy()

    gates = evaluate_gates(scenarios, protocol.payload)
    required_pass = all(gates[name] for name in REQUIRED_GATES)
    metrics = {
        "verdict": "PASS_DEVELOPMENT_GATES" if required_pass else "NO_GO",
        "mode": MODE,
        "target_multiplier": 2.0,
        "maximum_scaled_target_gross": float(gross.max()),
        "scenarios": scenarios,
        "gates": gates,
        "required_gates": list(REQUIRED_GATES),
        "stretch_50_cagr_pass": gates["stretch_primary_cagr_50"],
        "candidate_count": 1,
        "scale_search_performed": False,
        "adaptive_same_history": True,
        "independent_validation": False,
        "live_trading_allowed": False,
    }
    assert ledger_output is not None
    return (
        ledger_output,
        pd.concat(orders, ignore_index=True),
        pd.concat(positions, ignore_index=True),
        targets,
        metrics,
    )


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# V49 exact double-risk development challenger",
        "",
        f"Verdict: **{metrics['verdict']}**",
        f"50% CAGR stretch gate: **{metrics['stretch_50_cagr_pass']}**",
        "",
        "| Scenario | CAGR | Sharpe | MDD | Worst year | Clips | Margin rejects |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario, item in metrics["scenarios"].items():
        combined = item["combined"]
        futures = item["futures"]
        lines.append(
            f"| {scenario} | {combined['cagr']:.4%} | {combined['sharpe']:.3f} | "
            f"{combined['maximum_drawdown']:.4%} | {combined['worst_year']:.4%} | "
            f"{futures['participation_clip_count']} | "
            f"{futures['initial_margin_rejection_count']} |"
        )
    lines.extend(
        [
            "",
            "The scale is the single presealed 2.00x candidate; no scale search was run.",
            "This is adaptive same-history research, not predictable return or live evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def _artifact_rows(path: Path) -> int | None:
    return pq.ParquetFile(path).metadata.num_rows if path.suffix == ".parquet" else None


def run(protocol: Protocol) -> Path:
    ledger, orders, positions, targets, metrics = build(protocol)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = _root(protocol.payload["outputs"]["root"])
    output = base.parent / f"{base.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"V49 output exists: {output}")
    output.mkdir(parents=True)
    paths = {
        "ledger": output / "combined_ledger.parquet",
        "orders": output / "orders.parquet",
        "positions": output / "positions.parquet",
        "targets": output / "scaled_targets.parquet",
        "metrics": output / "metrics.json",
        "report": output / "report.md",
    }
    artifact_io._write_parquet(paths["ledger"], ledger)
    artifact_io._write_parquet(paths["orders"], orders)
    artifact_io._write_parquet(paths["positions"], positions)
    artifact_io._write_parquet(paths["targets"], targets)
    write_json(paths["metrics"], metrics)
    atomic_write_bytes(paths["report"], _report(metrics).encode("utf-8-sig"))
    runtime_audit = {
        "checks": {
            "protocol_sha_exact": _sha(CONFIG_PATH) == protocol.config_sha256,
            "dates_before_2026": bool(
                pd.to_datetime(ledger["session_date"]).lt("2026-01-01").all()
            ),
            "single_presealed_mode": metrics["mode"] == MODE and metrics["candidate_count"] == 1,
            "no_scale_search": metrics["scale_search_performed"] is False,
            "targets_preserve_sign": bool(
                targets.loc[targets["v39_target_weight"].ne(0.0), "target_weight"]
                .mul(targets.loc[targets["v39_target_weight"].ne(0.0), "v39_target_weight"])
                .gt(0.0)
                .all()
            ),
            "targets_exact_double": bool(
                targets["target_weight"].eq(targets["v39_target_weight"] * 2.0).all()
            ),
            "all_nav_positive": bool(ledger.filter(regex="_nav$").gt(0.0).all(axis=None)),
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(runtime_audit["checks"].values()):
        raise ValueError(f"V49 runtime audit failed: {runtime_audit}")
    audit_path = output / "audit.json"
    write_json(audit_path, runtime_audit)
    paths["audit"] = audit_path
    artifacts = {
        key: artifact_io._artifact(path, _artifact_rows(path)) for key, path in paths.items()
    }
    manifest = {
        "run_id": output.name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": protocol.config_sha256,
        "implementation_sha256": _sha(Path(__file__)),
        "parent_v48_protocol_sha256": protocol.v48_protocol.config_sha256,
        "verdict": metrics["verdict"],
        "stretch_50_cagr_pass": metrics["stretch_50_cagr_pass"],
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


def _close(left: Any, right: Any) -> bool:
    return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)


def audit(run_directory: Path) -> dict[str, Any]:
    protocol = load_protocol()
    output = run_directory.resolve()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    declared_manifest = (output / "manifest.sha256").read_text(encoding="utf-8-sig").split()[0]
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    ledger = pd.read_parquet(output / "combined_ledger.parquet")
    targets = pd.read_parquet(output / "scaled_targets.parquet")
    orders = pd.read_parquet(output / "orders.parquet")
    positions = pd.read_parquet(output / "positions.parquet")
    artifact_checks: dict[str, bool] = {}
    for name, declaration in manifest["artifacts"].items():
        path = output / declaration["file"]
        artifact_checks[f"artifact_{name}_sha"] = _sha(path) == declaration["sha256"]
        artifact_checks[f"artifact_{name}_bytes"] = path.stat().st_size == int(declaration["bytes"])
        if "rows" in declaration:
            artifact_checks[f"artifact_{name}_rows"] = pq.ParquetFile(
                path
            ).metadata.num_rows == int(declaration["rows"])
    replay_checks: dict[str, bool] = {}
    for scenario in SCENARIOS:
        nav = ledger.set_index("session_date")[f"{MODE}_{scenario}_combined_nav"].astype(float)
        replay = _combined_metrics(nav)
        stored = metrics["scenarios"][scenario]["combined"]
        for key in (
            "total_return",
            "cagr",
            "sharpe",
            "maximum_drawdown",
            "worst_year",
            "minimum_nav",
        ):
            replay_checks[f"{scenario}_{key}_replay"] = _close(replay[key], stored[key])
        replay_checks[f"{scenario}_positive_years_replay"] = int(replay["positive_years"]) == int(
            stored["positive_years"]
        )
    gate_replay = evaluate_gates(metrics["scenarios"], protocol.payload)
    checks = {
        "manifest_sha_exact": declared_manifest == _sha(output / "manifest.json"),
        "protocol_sha_exact": manifest["protocol_sha256"] == protocol.config_sha256,
        "implementation_sha_exact": manifest["implementation_sha256"] == _sha(Path(__file__)),
        "parent_v48_exact": manifest["parent_v48_protocol_sha256"]
        == protocol.v48_protocol.config_sha256,
        "required_artifacts_exact": {
            declaration["file"] for declaration in manifest["artifacts"].values()
        }
        == set(protocol.payload["outputs"]["required"]) - {"manifest.json", "manifest.sha256"},
        "dates_before_2026": bool(pd.to_datetime(ledger["session_date"]).lt("2026-01-01").all()),
        "targets_exact_double": bool(
            targets["target_weight"].eq(targets["v39_target_weight"] * 2.0).all()
        ),
        "targets_sign_and_zero_preserved": bool(
            targets["target_weight"].mul(targets["v39_target_weight"]).ge(0.0).all()
        ),
        "single_mode_targets": set(targets["v49_mode"].astype(str)) == {MODE},
        "single_mode_orders": set(orders["v49_mode"].astype(str)) == {MODE},
        "single_mode_positions": set(positions["v49_mode"].astype(str)) == {MODE},
        "scenario_identity": set(orders["scenario"].astype(str)) == set(UNIQUE_FUTURES_SCENARIOS)
        and set(positions["scenario"].astype(str)) == set(UNIQUE_FUTURES_SCENARIOS),
        "gates_replay_exact": gate_replay == metrics["gates"],
        "verdict_replay_exact": (
            all(gate_replay[name] for name in REQUIRED_GATES)
            == (metrics["verdict"] == "PASS_DEVELOPMENT_GATES")
        ),
        "stretch_replay_exact": gate_replay["stretch_primary_cagr_50"]
        is metrics["stretch_50_cagr_pass"],
        "no_scale_search": metrics["candidate_count"] == 1
        and metrics["scale_search_performed"] is False,
        "same_history_disclosed": metrics["adaptive_same_history"] is True
        and metrics["independent_validation"] is False,
        "live_forbidden": manifest["live_trading_allowed"] is False
        and metrics["live_trading_allowed"] is False,
        **artifact_checks,
        **replay_checks,
    }
    return {"checks": checks, "all_true": all(checks.values())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args(argv)
    if args.audit_directory is not None:
        payload = audit(args.audit_directory)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["all_true"] else 1
    output = run(load_protocol())
    print(output)
    print((output / "report.md").read_text(encoding="utf-8-sig"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
