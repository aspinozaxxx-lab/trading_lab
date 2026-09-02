"""Run one sealed causal equity-trend risk governor over frozen V49 economics."""

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

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v15_levered_ruonia_collateral as v15
from market_lab import futures_v27_key_rate_extreme_governor as v27
from market_lab import futures_v48_v47_exact_integer_execution as v48
from market_lab import futures_v49_v39_double_risk_exact_execution as v49
from market_lab.futures import moex_stock_futures_cash_carry_source as artifact_io
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v60_v49_equity_trend_governor_v1.yaml"
CONFIG_SHA256: Final[str] = "40145868e1d3cb56ccd5f696e5fd896daabb9aabe409eeb4cedae11ac14affe6"
MODE: Final[str] = "equity_trend_risk"
SHADOW_COLUMN: Final[str] = "double_risk_primary_combined_nav"
LOOKBACK: Final[int] = 126
SCENARIOS: Final[tuple[str, ...]] = v49.SCENARIOS
UNIQUE_FUTURES_SCENARIOS: Final[tuple[str, ...]] = v49.UNIQUE_FUTURES_SCENARIOS
REQUIRED_GATES: Final[tuple[str, ...]] = (
    "execution_complete",
    "zero_critical_failures",
    "zero_unresolved_halts",
    "zero_participation_clips",
    "zero_initial_margin_rejections",
    "maximum_participation",
    "all_nav_positive",
    "all_scenario_cagr",
    "all_scenario_sharpe",
    "all_scenario_mdd",
    "all_scenario_worst_year",
    "primary_positive_years",
    "primary_mdd_better_than_v49",
    "primary_worst_year_better_than_v49",
)


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    v49_protocol: v49.Protocol
    shadow_root: Path


def _sha(path: Path) -> str:
    return artifact_io.sha256_file(path)


def _root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe V60 path: {value}")
    if relative.parts[0].lower() != "runs":
        raise ValueError(f"V60 path must be under runs: {value}")
    return PROJECT_ROOT / relative


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V60 config must be an object")
    selection = payload["selection"]
    parent = payload["parents"]["v49_engine"]
    shadow = payload["parents"]["v49_canonical_shadow"]
    governor = payload["governor"]
    gates = payload["gates"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "futures_v60_v49_equity_trend_governor_v1"
        or payload.get("status") != "sealed_before_any_v60_target_order_position_or_pnl"
        or payload.get("adaptive_same_history") is not True
        or payload.get("live_trading_allowed") is not False
        or _sha(PROJECT_ROOT / parent["config"]) != parent["config_sha256"]
        or _sha(PROJECT_ROOT / parent["implementation"]) != parent["implementation_sha256"]
        or int(selection["candidate_count"]) != 1
        or selection["parameter_search"] is not False
        or int(selection["moving_average_sessions"]) != LOOKBACK
        or float(selection["risk_on_multiplier"]) != 2.0
        or float(selection["risk_off_multiplier"]) != 1.0
        or float(selection["warmup_multiplier"]) != 1.0
        or selection["equality_is_risk_on"] is not True
        or selection["lower_higher_window_or_multiplier_comparison"] != "forbidden"
        or shadow["shadow_column"] != SHADOW_COLUMN
        or shadow["shadow_is_always_on_parent_not_v60_realized_nav"] is not True
        or shadow["use_only_latest_session_strictly_before_target_effective_date"] is not True
        or governor["formula"]
        != "risk_on_2x_if_prior_shadow_nav_gte_trailing_126_session_mean_else_1x"
        or governor["scenario_specific_governor"] is not False
        or governor["current_or_future_shadow_session_forbidden"] is not True
        or float(governor["gross_notional_cap"]) != 4.0
        or float(governor["initial_margin_buffer_multiplier"]) != 2.0
        or float(payload["execution"]["maximum_lagged_volume_participation"]) != 0.01
        or float(gates["all_scenario_cagr_gte"]) != 0.20
        or float(gates["all_scenario_sharpe_gte"]) != 1.0
        or float(gates["all_scenario_mdd_lte"]) != 0.25
        or float(gates["all_scenario_worst_year_gte"]) != -0.10
        or gates["live_promotion_forbidden"] is not True
    ):
        raise ValueError("V60 protocol drifted")
    parent_protocol = v49.load_protocol()
    if parent_protocol.config_sha256 != parent["config_sha256"]:
        raise ValueError("V60 loaded the wrong V49 protocol")
    shadow_root = _root(shadow["root"])
    for declaration in (shadow["manifest"], shadow["ledger"], shadow["metrics"]):
        path = shadow_root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"V60 shadow parent drifted: {path.name}")
    if pq.ParquetFile(shadow_root / shadow["ledger"]["file"]).metadata.num_rows != int(
        shadow["ledger"]["rows"]
    ):
        raise ValueError("V60 shadow ledger row identity drifted")
    return Protocol(payload, actual, parent_protocol, shadow_root)


def build_governor(
    shadow_ledger: pd.DataFrame,
    effective_dates: pd.Series | pd.DatetimeIndex,
) -> pd.DataFrame:
    required = {"session_date", SHADOW_COLUMN}
    if missing := required - set(shadow_ledger.columns):
        raise ValueError(f"V60 shadow ledger lacks columns: {sorted(missing)}")
    shadow = shadow_ledger.loc[:, ["session_date", SHADOW_COLUMN]].copy()
    shadow["shadow_session_date"] = pd.to_datetime(
        shadow.pop("session_date"), errors="raise"
    ).dt.normalize()
    shadow["shadow_nav"] = pd.to_numeric(shadow.pop(SHADOW_COLUMN), errors="raise").astype(float)
    if (
        shadow["shadow_session_date"].duplicated().any()
        or not shadow["shadow_session_date"].is_monotonic_increasing
        or not np.isfinite(shadow["shadow_nav"]).all()
        or shadow["shadow_nav"].le(0.0).any()
        or shadow["shadow_session_date"].ge("2026-01-01").any()
    ):
        raise ValueError("V60 shadow ledger identity or values invalid")
    shadow["shadow_sma_126"] = shadow["shadow_nav"].rolling(LOOKBACK, min_periods=LOOKBACK).mean()
    dates = pd.DataFrame(
        {
            "effective_date": pd.to_datetime(
                pd.Series(effective_dates), errors="raise"
            ).dt.normalize()
        }
    ).drop_duplicates()
    dates = dates.sort_values("effective_date", kind="stable", ignore_index=True)
    governor = pd.merge_asof(
        dates,
        shadow,
        left_on="effective_date",
        right_on="shadow_session_date",
        direction="backward",
        allow_exact_matches=False,
    )
    governor["warmup_complete"] = governor["shadow_sma_126"].notna()
    governor["risk_on"] = governor["warmup_complete"] & governor["shadow_nav"].ge(
        governor["shadow_sma_126"]
    )
    governor["risk_multiplier"] = np.where(governor["risk_on"], 2.0, 1.0)
    if (
        governor["shadow_session_date"].notna().any()
        and not governor.loc[governor["shadow_session_date"].notna(), "shadow_session_date"]
        .lt(governor.loc[governor["shadow_session_date"].notna(), "effective_date"])
        .all()
    ):
        raise ValueError("V60 governor used current or future shadow session")
    if not set(governor["risk_multiplier"].unique()).issubset({1.0, 2.0}):
        raise ValueError("V60 governor produced an undeclared multiplier")
    return governor


def govern_targets(base_targets: pd.DataFrame, governor: pd.DataFrame) -> pd.DataFrame:
    required = {"effective_date", "target_weight", "provenance"}
    if missing := required - set(base_targets.columns):
        raise ValueError(f"V60 base targets lack columns: {sorted(missing)}")
    targets = base_targets.copy()
    targets["effective_date"] = pd.to_datetime(
        targets["effective_date"], errors="raise"
    ).dt.normalize()
    targets["v39_target_weight"] = pd.to_numeric(targets["target_weight"], errors="raise").astype(
        float
    )
    targets = targets.merge(
        governor.loc[:, ["effective_date", "risk_multiplier", "risk_on", "warmup_complete"]],
        on="effective_date",
        how="left",
        validate="many_to_one",
    )
    if targets["risk_multiplier"].isna().any():
        raise ValueError("V60 target date lacks a governor state")
    targets["target_weight"] = targets["v39_target_weight"] * targets["risk_multiplier"]
    targets["v60_mode"] = MODE
    targets["provenance"] = (
        targets["provenance"].astype("string")
        + "|v60_prior_shadow_equity_trend_"
        + targets["risk_multiplier"].map({1.0: "1x", 2.0: "2x"}).astype("string")
    )
    if not targets.loc[targets["v39_target_weight"].eq(0.0), "target_weight"].eq(0.0).all():
        raise ValueError("V60 changed a V39 zero target")
    if targets["target_weight"].mul(targets["v39_target_weight"]).lt(0.0).any():
        raise ValueError("V60 changed a V39 target direction")
    return targets


def _combined_metrics(nav: pd.Series) -> dict[str, Any]:
    metrics = v48._metrics(nav)
    metrics["minimum_nav"] = float(nav.min())
    return metrics


def evaluate_gates(
    scenarios: dict[str, Any], benchmark: dict[str, Any], config: dict[str, Any]
) -> dict[str, bool]:
    gates = config["gates"]
    futures = [item["futures"] for item in scenarios.values()]
    combined = [item["combined"] for item in scenarios.values()]
    primary = scenarios["primary"]["combined"]
    parent_primary = benchmark["scenarios"]["primary"]["combined"]
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
        "primary_positive_years": int(primary["positive_years"])
        >= int(gates["primary_positive_years_gte"]),
        "primary_mdd_better_than_v49": float(primary["maximum_drawdown"])
        < float(parent_primary["maximum_drawdown"]),
        "primary_worst_year_better_than_v49": float(primary["worst_year"])
        > float(parent_primary["worst_year"]),
        "stretch_primary_cagr_40": float(primary["cagr"])
        >= float(gates["stretch_primary_cagr_gte"]),
        "aspirational_primary_cagr_50": float(primary["cagr"])
        >= float(gates["aspirational_primary_cagr_gte"]),
    }


def build(
    protocol: Protocol,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    market, ruonia = v48._prepare_inputs()
    base_targets = pd.read_parquet(
        protocol.v49_protocol.v48_protocol.v39_root / "mapped_targets.parquet"
    )
    shadow_declaration = protocol.payload["parents"]["v49_canonical_shadow"]["ledger"]
    shadow = pd.read_parquet(protocol.shadow_root / shadow_declaration["file"])
    governor = build_governor(shadow, base_targets["effective_date"])
    targets = govern_targets(base_targets, governor)
    gross = targets.groupby("effective_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    maximum_gross = float(protocol.payload["governor"]["gross_notional_cap"])
    if float(gross.max()) > maximum_gross + 1e-12:
        raise ValueError("V60 governed target exceeds sealed gross")
    settings = v12._scenario_settings(v27.load_protocol())
    futures_results: dict[str, FuturesPortfolioLedgerResult] = {}
    collateral_results: dict[str, v15.CollateralEvaluation] = {}
    orders: list[pd.DataFrame] = []
    positions: list[pd.DataFrame] = []
    for scenario in UNIQUE_FUTURES_SCENARIOS:
        setting = settings[scenario]
        ledger_config = v49.DoubleRiskLedgerConfig(
            initial_cash=v12.INITIAL_CASH,
            expected_assets=v12.ASSETS,
            maximum_gross_notional_multiple=maximum_gross,
            initial_margin_buffer_multiplier=float(
                protocol.payload["governor"]["initial_margin_buffer_multiplier"]
            ),
            maximum_participation=v12.MAXIMUM_PARTICIPATION,
            slippage_ticks=int(setting["slippage_ticks"]),
            fee_multiplier=float(setting["fee_multiplier"]),
        )
        result = v48.run_scaled_ledger(market, targets, ledger_config)  # type: ignore[arg-type]
        futures_results[scenario] = result
        collateral_results[scenario] = v15.evaluate_collateral_income(result, ruonia)
        order_frame = result.orders.copy()
        order_frame.insert(0, "v60_mode", MODE)
        order_frame.insert(1, "scenario", scenario)
        orders.append(order_frame)
        position_frame = result.positions.copy()
        position_frame.insert(0, "v60_mode", MODE)
        position_frame.insert(1, "scenario", scenario)
        positions.append(position_frame)
    benchmark = json.loads(
        (
            protocol.shadow_root
            / protocol.payload["parents"]["v49_canonical_shadow"]["metrics"]["file"]
        ).read_text(encoding="utf-8-sig")
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
        parent_metrics = benchmark["scenarios"][scenario]["combined"]
        scenarios[scenario] = {
            "futures": futures_metrics,
            "combined": combined,
            "delta_vs_v49": {
                key: float(combined[key]) - float(parent_metrics[key])
                for key in ("cagr", "sharpe", "maximum_drawdown", "worst_year")
            },
            "margin_buffer_multiplier": 2.0,
            "carry_cash_fraction": 0.0,
        }
        if ledger_output is None:
            ledger_output = pd.DataFrame({"session_date": combined_nav.index})
        ledger_output[f"{MODE}_{scenario}_combined_nav"] = combined_nav.to_numpy()
        ledger_output[f"{MODE}_{scenario}_exact_futures_nav"] = (
            exact_nav / float(exact_nav.iloc[0])
        ).to_numpy()
    gates = evaluate_gates(scenarios, benchmark, protocol.payload)
    required_pass = all(gates[name] for name in REQUIRED_GATES)
    counts = {
        "target_effective_dates": int(governor["effective_date"].nunique()),
        "warmup_dates": int((~governor["warmup_complete"]).sum()),
        "risk_on_2x_dates": int(governor["risk_on"].sum()),
        "risk_off_1x_dates": int((~governor["risk_on"]).sum()),
        "nonzero_target_rows": int(targets["target_weight"].ne(0.0).sum()),
    }
    metrics = {
        "verdict": "GO_TO_NEW_FORWARD_CONFIRMATION" if required_pass else "NO_GO",
        "mode": MODE,
        "governor": "strictly_prior_parent_shadow_nav_vs_126_session_mean",
        "counts": counts,
        "maximum_governed_target_gross": float(gross.max()),
        "scenarios": scenarios,
        "gates": gates,
        "required_gates": list(REQUIRED_GATES),
        "candidate_count": 1,
        "parameter_search_performed": False,
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
        governor,
        metrics,
    )


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# V60 V49 causal shadow-equity trend governor",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        "| Scenario | CAGR | Sharpe | MDD | Worst year | CAGR vs V49 | MDD vs V49 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario, item in metrics["scenarios"].items():
        combined = item["combined"]
        delta = item["delta_vs_v49"]
        lines.append(
            f"| {scenario} | {combined['cagr']:.4%} | {combined['sharpe']:.3f} | "
            f"{combined['maximum_drawdown']:.4%} | {combined['worst_year']:.4%} | "
            f"{delta['cagr']:+.4%} | {delta['maximum_drawdown']:+.4%} |"
        )
    counts = metrics["counts"]
    lines.extend(
        [
            "",
            f"Risk-on 2x / risk-off 1x / warmup dates: "
            f"{counts['risk_on_2x_dates']}/{counts['risk_off_1x_dates']}/"
            f"{counts['warmup_dates']}.",
            "",
            "One presealed causal rule was tested without a parameter search. This is "
            "adaptive same-history development, not predictable return or live evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def _artifact_rows(path: Path) -> int | None:
    return pq.ParquetFile(path).metadata.num_rows if path.suffix == ".parquet" else None


def run(protocol: Protocol) -> Path:
    ledger, orders, positions, targets, governor, metrics = build(protocol)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = _root(protocol.payload["outputs"]["root"])
    output = base.parent / f"{base.name}_{stamp}_{protocol.config_sha256[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    paths = {
        "ledger": output / "combined_ledger.parquet",
        "orders": output / "orders.parquet",
        "positions": output / "positions.parquet",
        "targets": output / "governed_targets.parquet",
        "governor": output / "governor.parquet",
        "metrics": output / "metrics.json",
        "report": output / "report.md",
    }
    for key, frame in (
        ("ledger", ledger),
        ("orders", orders),
        ("positions", positions),
        ("targets", targets),
        ("governor", governor),
    ):
        artifact_io._write_parquet(paths[key], frame)
    write_json(paths["metrics"], metrics)
    atomic_write_bytes(paths["report"], _report(metrics).encode("utf-8-sig"))
    runtime_audit = {
        "checks": {
            "protocol_sha_exact": _sha(CONFIG_PATH) == protocol.config_sha256,
            "dates_before_2026": bool(
                pd.to_datetime(ledger["session_date"]).lt("2026-01-01").all()
            ),
            "strict_prior_shadow": bool(
                governor.loc[governor["shadow_session_date"].notna(), "shadow_session_date"]
                .lt(governor.loc[governor["shadow_session_date"].notna(), "effective_date"])
                .all()
            ),
            "single_presealed_rule": metrics["candidate_count"] == 1,
            "no_parameter_search": metrics["parameter_search_performed"] is False,
            "multipliers_exact": set(targets["risk_multiplier"].unique()) <= {1.0, 2.0},
            "targets_sign_and_zero_preserved": bool(
                targets["target_weight"].mul(targets["v39_target_weight"]).ge(0.0).all()
            ),
            "all_nav_positive": bool(ledger.filter(regex="_nav$").gt(0.0).all(axis=None)),
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(runtime_audit["checks"].values()):
        raise ValueError(f"V60 runtime audit failed: {runtime_audit}")
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
        "parent_v49_protocol_sha256": protocol.v49_protocol.config_sha256,
        "verdict": metrics["verdict"],
        "live_trading_allowed": False,
        "artifacts": artifacts,
    }
    manifest_path = output / "manifest.json"
    write_json(manifest_path, manifest)
    atomic_write_bytes(
        output / "manifest.sha256", f"{_sha(manifest_path)}  manifest.json\n".encode("utf-8-sig")
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
    targets = pd.read_parquet(output / "governed_targets.parquet")
    governor = pd.read_parquet(output / "governor.parquet")
    benchmark = json.loads(
        (
            protocol.shadow_root
            / protocol.payload["parents"]["v49_canonical_shadow"]["metrics"]["file"]
        ).read_text(encoding="utf-8-sig")
    )
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
    gate_replay = evaluate_gates(metrics["scenarios"], benchmark, protocol.payload)
    checks = {
        "manifest_sha_exact": declared_manifest == _sha(output / "manifest.json"),
        "protocol_sha_exact": manifest["protocol_sha256"] == protocol.config_sha256,
        "implementation_sha_exact": manifest["implementation_sha256"] == _sha(Path(__file__)),
        "parent_v49_exact": manifest["parent_v49_protocol_sha256"]
        == protocol.v49_protocol.config_sha256,
        "dates_before_2026": bool(pd.to_datetime(ledger["session_date"]).lt("2026-01-01").all()),
        "strict_prior_shadow": bool(
            governor.loc[governor["shadow_session_date"].notna(), "shadow_session_date"]
            .lt(governor.loc[governor["shadow_session_date"].notna(), "effective_date"])
            .all()
        ),
        "multipliers_exact": set(targets["risk_multiplier"].unique()) <= {1.0, 2.0},
        "targets_sign_and_zero_preserved": bool(
            targets["target_weight"].mul(targets["v39_target_weight"]).ge(0.0).all()
        ),
        "gates_replay_exact": gate_replay == metrics["gates"],
        "verdict_replay_exact": (
            all(gate_replay[name] for name in REQUIRED_GATES)
            == (metrics["verdict"] == "GO_TO_NEW_FORWARD_CONFIRMATION")
        ),
        "no_parameter_search": metrics["candidate_count"] == 1
        and metrics["parameter_search_performed"] is False,
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
