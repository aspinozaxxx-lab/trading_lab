"""Sealed V26: 2x V25 stress-governed trend plus RUONIA and capacity admission."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v15_levered_ruonia_collateral as v15
from market_lab import futures_v25_stlfsi_stress_governor as v25
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult

PROJECT_ROOT: Final[Path] = v12.PROJECT_ROOT
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v26_stlfsi_levered_ruonia_capacity.yaml"
CONFIG_SHA256: Final[str] = "2b08589013f3b3387002830cad7878ef0fffc5dc808b8165fc004e724abf4c1b"
V25_PROTOCOL_SHA256: Final[str] = v25.CONFIG_SHA256
V25_METRICS_SHA256: Final[str] = "c2518d17b4e945ef921fa8dbaa8bd330645131acddd73fc01a45c44c0aacfa86"
V15_PROTOCOL_SHA256: Final[str] = v15.CONFIG_SHA256
V15_METRICS_SHA256: Final[str] = "3f882e0b74e1b58fced362c3f4713f6c7641e7577964b51625d1b18d471298c4"
V25_PRIMARY_REFERENCE: Final[dict[str, float]] = {
    "total_return": 0.490720124866874,
    "cagr": 0.08313666849961998,
    "sharpe": 0.8177496477975039,
    "maximum_drawdown": 0.14226187896737108,
    "positive_years": 4.0,
    "worst_year": -0.022575414621381795,
    "total_cost_rub": 13835.173808167034,
}
V15_COMBINED_REFERENCE: Final[dict[str, float]] = {
    "total_return": 1.6287025663069512,
    "cagr": 0.21327167662258972,
    "sharpe": 0.8826497601427579,
    "maximum_drawdown": 0.34482347022508963,
    "positive_years": 4.0,
    "worst_year": -0.15253455335968313,
    "total_cost_rub": 51931.216387763736,
    "critical_failure_count": 8.0,
}


@dataclass(frozen=True, slots=True)
class CapacityAwareLeveredLedgerConfig:
    """Permit exactly 2x gross while cancelling or clipping causally known bad orders."""

    initial_cash: float = v12.INITIAL_CASH
    expected_assets: tuple[str, ...] = v12.ASSETS
    maximum_gross_notional_multiple: float = v15.MAXIMUM_GROSS
    initial_margin_buffer_multiplier: float = v15.MARGIN_BUFFER_MULTIPLIER
    maximum_participation: float = v12.MAXIMUM_PARTICIPATION
    slippage_ticks: Literal[1, 2, 4] = 1
    fee_multiplier: Literal[1.0, 2.0] = 1.0
    execution_atomicity: Literal["asset"] = "asset"
    terminal_policy: Literal["carry"] = "carry"
    unexecutable_target_policy: Literal["cancel_and_clip"] = "cancel_and_clip"

    def __post_init__(self) -> None:
        fixed = (
            self.initial_cash == v12.INITIAL_CASH
            and self.expected_assets == v12.ASSETS
            and self.maximum_gross_notional_multiple == v15.MAXIMUM_GROSS
            and self.initial_margin_buffer_multiplier == v15.MARGIN_BUFFER_MULTIPLIER
            and self.maximum_participation == v12.MAXIMUM_PARTICIPATION
            and self.execution_atomicity == "asset"
            and self.terminal_policy == "carry"
            and self.unexecutable_target_policy == "cancel_and_clip"
        )
        if not fixed:
            raise ValueError("V26 capacity-aware ledger settings drift")
        if self.slippage_ticks not in {1, 2, 4}:
            raise ValueError("V26 slippage must be 1, 2 or 4 ticks")
        if self.fee_multiplier not in {1.0, 2.0}:
            raise ValueError("V26 fee multiplier must be 1 or 2")


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the byte seal and every fixed V26 economic or execution choice."""
    config_path = config_path.resolve()
    if config_path != CONFIG_PATH.resolve() or v12.sha256_file(config_path) != CONFIG_SHA256:
        raise ValueError("sealed V26 protocol byte drift")
    sidecar = config_path.with_suffix(".sha256")
    stated = sidecar.read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V26 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V26 protocol must be a mapping")

    parent = protocol["parent_v25"]
    infrastructure = protocol["infrastructure_parent_v15"]
    signal = protocol["signal"]
    governor = protocol["risk_governor"]
    capital = protocol["capital_efficiency"]
    collateral = protocol["collateral_income"]
    execution = protocol["execution"]
    parent_reference = {
        str(key): float(value) for key, value in parent["primary_reference"].items()
    }
    infrastructure_reference = {
        str(key): float(value)
        for key, value in infrastructure["primary_combined_reference"].items()
    }
    declared_all = {
        str(key): int(value)
        for key, value in governor["sealed_state_counts"]["all_2018_2025"].items()
    }
    declared_oos = {
        str(key): int(value)
        for key, value in governor["sealed_state_counts"]["oos_2021_2025"].items()
    }
    if (
        protocol.get("protocol_id") != "futures_v26_stlfsi_levered_ruonia_capacity_v1"
        or protocol.get("status") != "predeclared_before_v26_oos_outcomes"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or tuple(protocol["universe"]["exact_order"]) != v12.ASSETS
        or parent["protocol_sha256"] != V25_PROTOCOL_SHA256
        or parent["metrics_sha256"] != V25_METRICS_SHA256
        or parent_reference != V25_PRIMARY_REFERENCE
        or infrastructure["protocol_sha256"] != V15_PROTOCOL_SHA256
        or infrastructure["metrics_sha256"] != V15_METRICS_SHA256
        or infrastructure_reference != V15_COMBINED_REFERENCE
        or tuple(protocol["inputs"]["stlfsi"]["allowed_columns"]) != v25.STLFSI_COLUMNS
        or tuple(protocol["inputs"]["stlfsi_coverage"]["allowed_columns"]) != v25.COVERAGE_COLUMNS
        or tuple(protocol["inputs"]["cbr_panel"]["allowed_columns"]) != v15.RUONIA_COLUMNS
        or tuple(int(value) for value in signal["log_momentum_horizons_sessions"])
        != v12.MOMENTUM_HORIZONS
        or int(signal["volatility_lookback_sessions"]) != v12.VOLATILITY_LOOKBACK
        or int(signal["annualization_sessions"]) != v12.ANNUALIZATION
        or float(signal["volatility_floor_annualized"]) != v12.VOLATILITY_FLOOR
        or signal["score_implementation"] != "imported_frozen_v12"
        or signal["hyperparameter_search"] is not False
        or float(governor["official_structural_boundary"]) != 0.0
        or float(governor["admitted_scale"]) != 1.0
        or float(governor["cash_scale"]) != 0.0
        or int(governor["maximum_source_age_calendar_days"]) != v25.MAXIMUM_SOURCE_AGE_DAYS
        or governor["threshold_fit"] != "none"
        or governor["scale_can_increase_v12_risk"] is not False
        or declared_all != v25.EXPECTED_ALL_STATES
        or declared_oos != v25.EXPECTED_OOS_STATES
        or float(capital["target_weight_multiplier_after_governor"]) != v15.LEVERAGE_MULTIPLIER
        or float(capital["maximum_gross_notional_multiple"]) != v15.MAXIMUM_GROSS
        or float(capital["initial_margin_buffer_multiple"]) != v15.MARGIN_BUFFER_MULTIPLIER
        or float(collateral["applied_rate_fraction"]) != v15.RUONIA_APPLIED_FRACTION
        or collateral["day_count"] != "ACT_365_calendar_days"
        or float(collateral["operational_buffer_fraction_of_conservative_equity"])
        != v15.OPERATIONAL_BUFFER_FRACTION
        or collateral["reinvested_into_contract_sizing"] is not False
        or collateral["compounded_into_future_eligible_balance"] is not False
        or collateral["principal_double_counted"] is not False
        or float(execution["initial_cash_rub"]) != v12.INITIAL_CASH
        or execution["execution_atomicity"] != "asset"
        or execution["unexecutable_target_policy"] != "cancel_and_clip"
        or float(execution["maximum_participation"]) != v12.MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"]) != v15.MAXIMUM_GROSS
        or float(execution["initial_margin_buffer_multiple"]) != v15.MARGIN_BUFFER_MULTIPLIER
    ):
        raise ValueError("sealed V26 protocol invariants were weakened")
    if v12._scenario_settings(protocol) != {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }:
        raise ValueError("sealed V26 cost scenarios drifted")
    return protocol


def verify_inputs(protocol: dict[str, Any]) -> v12.VerifiedInputs:
    """Verify every byte before price or execution outcomes are loaded."""
    verified = v12.verify_inputs(protocol)
    checks = dict(verified.checks)
    checks["frozen_v12_parent_protocol_seal"] = checks.pop("protocol_seal")
    checks["parent_v25_protocol_seal"] = v12.sha256_file(v25.CONFIG_PATH) == V25_PROTOCOL_SHA256
    checks["infrastructure_v15_protocol_seal"] = (
        v12.sha256_file(v15.CONFIG_PATH) == V15_PROTOCOL_SHA256
    )
    checks["v26_protocol_seal"] = v12.sha256_file(CONFIG_PATH) == CONFIG_SHA256
    if not all(checks.values()):
        raise ValueError(f"V26 input identity preflight failed: {checks}")
    return v12.VerifiedInputs(paths=verified.paths, checks=checks, metadata=verified.metadata)


def build_levered_governed_weights(governed_weights: pd.DataFrame) -> pd.DataFrame:
    """Double the already-governed V25 snapshot without changing its state or composition."""
    required = {"decision_date", "asset", "target_weight", "provenance"}
    if missing := required - set(governed_weights.columns):
        raise ValueError(f"V26 governed weights lack columns: {sorted(missing)}")
    output = governed_weights.copy()
    output["v25_target_weight"] = pd.to_numeric(output["target_weight"], errors="raise").astype(
        float
    )
    output["target_weight"] = output["v25_target_weight"] * v15.LEVERAGE_MULTIPLIER
    output["provenance"] = (
        output["provenance"].astype("string") + "|sealed_two_times_after_v25_governor"
    )
    gross = output.groupby("decision_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    if gross.gt(v15.MAXIMUM_GROSS + 1e-12).any():
        raise ValueError("V26 levered governed target exceeds sealed gross two")
    if not output.loc[output["v25_target_weight"].eq(0.0), "target_weight"].eq(0.0).all():
        raise ValueError("V26 leverage changed a V25 cash state")
    return output.sort_values(["decision_date", "asset"], kind="mergesort", ignore_index=True)


def _comparison(primary: dict[str, Any]) -> dict[str, Any]:
    combined = primary["combined"]
    futures = primary["futures_only"]
    return {
        "v25": {
            "protocol_sha256": V25_PROTOCOL_SHA256,
            "metrics_sha256": V25_METRICS_SHA256,
            "reference": V25_PRIMARY_REFERENCE,
            "delta": {
                "total_return": float(combined["total_return"])
                - V25_PRIMARY_REFERENCE["total_return"],
                "cagr": float(combined["cagr"]) - V25_PRIMARY_REFERENCE["cagr"],
                "sharpe": float(combined["sharpe"]) - V25_PRIMARY_REFERENCE["sharpe"],
                "maximum_drawdown_reduction": V25_PRIMARY_REFERENCE["maximum_drawdown"]
                - float(combined["maximum_drawdown"]),
                "worst_year_improvement": float(combined["worst_year"])
                - V25_PRIMARY_REFERENCE["worst_year"],
                "cost_change_rub": float(futures["total_cost"])
                - V25_PRIMARY_REFERENCE["total_cost_rub"],
            },
        },
        "v15": {
            "protocol_sha256": V15_PROTOCOL_SHA256,
            "metrics_sha256": V15_METRICS_SHA256,
            "reference": V15_COMBINED_REFERENCE,
            "delta": {
                "total_return": float(combined["total_return"])
                - V15_COMBINED_REFERENCE["total_return"],
                "cagr": float(combined["cagr"]) - V15_COMBINED_REFERENCE["cagr"],
                "sharpe": float(combined["sharpe"]) - V15_COMBINED_REFERENCE["sharpe"],
                "maximum_drawdown_reduction": V15_COMBINED_REFERENCE["maximum_drawdown"]
                - float(combined["maximum_drawdown"]),
                "worst_year_improvement": float(combined["worst_year"])
                - V15_COMBINED_REFERENCE["worst_year"],
                "cost_change_rub": float(futures["total_cost"])
                - V15_COMBINED_REFERENCE["total_cost_rub"],
                "critical_failure_reduction": int(V15_COMBINED_REFERENCE["critical_failure_count"])
                - int(futures["critical_failure_count"]),
            },
        },
    }


def _promotion(results: dict[str, dict[str, Any]], checks: dict[str, bool]) -> dict[str, Any]:
    primary = results["primary"]["combined"]
    conditions = {
        "every_input_raw_replay_source_temporal_and_accrual_check_true": all(checks.values()),
        "exact_sealed_weekly_stlfsi4_state_counts": checks["weekly_governor_all_state_counts_exact"]
        and checks["weekly_governor_oos_state_counts_exact"],
        "all_scenarios_execution_and_combined_metrics_complete": all(
            bool(value["futures_only"]["execution_complete"])
            and bool(value["combined"]["metrics_valid"])
            for value in results.values()
        ),
        "zero_critical_failures_and_zero_unresolved_halts": all(
            int(value["futures_only"]["critical_failure_count"]) == 0
            and int(value["futures_only"]["unresolved_halt_count"]) == 0
            for value in results.values()
        ),
        "all_scenarios_combined_cagr_at_least_0_20": all(
            float(value["combined"]["cagr"]) >= 0.20 for value in results.values()
        ),
        "all_scenarios_combined_maximum_drawdown_at_most_0_30": all(
            float(value["combined"]["maximum_drawdown"]) <= 0.30 for value in results.values()
        ),
        "primary_combined_sharpe_at_least_sealed_v25": float(primary["sharpe"])
        >= V25_PRIMARY_REFERENCE["sharpe"],
        "primary_combined_worst_year_at_least_minus_0_15": float(primary["worst_year"]) >= -0.15,
        "primary_combined_positive_years_at_least_4_of_5": int(primary["positive_years"]) >= 4
        and len(primary["annual_returns"]) == 5,
        "no_order_time_gross_participation_or_margin_breach": all(
            float(value["futures_only"]["maximum_participation"])
            <= v12.MAXIMUM_PARTICIPATION + 1e-12
            and int(value["futures_only"]["gross_limit_rejection_count"]) == 0
            and int(value["futures_only"]["initial_margin_rejection_count"]) == 0
            and float(value["futures_only"]["ending_cash"]) > 0.0
            for value in results.values()
        ),
    }
    passed = all(conditions.values())
    return {
        "conditions": conditions,
        "passed": passed,
        "verdict": "GO_TO_NEW_UNSEEN_VALIDATION" if passed else "NO_GO",
        "live_trading_allowed": False,
        "independent_confirmation_required": True,
    }


def _report_text(payload: dict[str, Any]) -> str:
    lines = [
        "# V26 2x V25 STLFSI4 governor plus causal RUONIA and capacity admission",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        "This is one adaptive 2021-2025 capital-efficiency test, not independent confirmation.",
        "",
        (
            "| Scenario | Futures CAGR | Combined CAGR | Sharpe | MDD | Worst year | "
            "Costs RUB | Clips | Cancels |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("primary", "doubled", "stress"):
        item = payload["scenarios"][name]
        futures = item["futures_only"]
        combined = item["combined"]
        cancels = sum(
            int(futures[key])
            for key in (
                "target_cancel_no_open_count",
                "target_cancel_no_liquidity_count",
                "target_cancel_roll_capacity_count",
            )
        )
        lines.append(
            f"| {name} | {futures['cagr']:.4%} | {combined['cagr']:.4%} | "
            f"{combined['sharpe']:.3f} | {combined['maximum_drawdown']:.4%} | "
            f"{combined['worst_year']:.4%} | {futures['total_cost']:.2f} | "
            f"{futures['participation_clip_count']} | {cancels} |"
        )
    primary = payload["scenarios"]["primary"]
    counts = payload["counts"]
    v15_delta = payload["comparisons"]["v15"]["delta"]
    lines.extend(
        [
            "",
            "## Primary combined annual returns",
            "",
        ]
    )
    for year, value in primary["combined"]["annual_returns"].items():
        lines.append(f"- {year}: {value:.4%}")
    lines.extend(
        [
            "",
            "## Stability and execution",
            "",
            f"- Combined total return: {primary['combined']['total_return']:.4%}",
            f"- Collateral income: {primary['collateral']['collateral_income_rub']:.2f} RUB",
            f"- Critical failures removed versus V15: {v15_delta['critical_failure_reduction']}",
            f"- OOS normal/below pass weeks: {counts['oos_pass_normal_or_below']}",
            f"- OOS above-average-stress cash weeks: {counts['oos_cash_above_average_stress']}",
            f"- Non-zero mapped targets: {counts['nonzero_targets']}",
            f"- Complete next-open dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "The exact leverage, 50% RUONIA haircut, 10% operational buffer and "
            "cancel-and-clip policy were fixed before this run. Interest is neither "
            "reinvested into sizing nor compounded into future eligible balance.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute exactly one immutable V26 adaptive-development run."""
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    stlfsi = v25.verify_stlfsi_bundle(protocol, verified)

    panel = pd.read_parquet(
        verified.paths["panel"], columns=protocol["inputs"]["panel"]["allowed_columns"]
    )
    active = pd.read_parquet(
        verified.paths["active_contract_map"],
        columns=protocol["inputs"]["active_contract_map"]["allowed_columns"],
    )
    observations = pd.read_parquet(
        verified.paths["contract_observations"],
        columns=protocol["inputs"]["contract_observations"]["allowed_columns"],
    )
    specs = pd.read_parquet(
        verified.paths["spec_proxy"],
        columns=protocol["inputs"]["spec_proxy"]["allowed_columns"],
    )
    ruonia_frame = pd.read_parquet(
        verified.paths["cbr_panel"],
        columns=protocol["inputs"]["cbr_panel"]["allowed_columns"],
        filters=[("series_id", "==", "ruonia")],
    )
    ruonia = v15.verify_ruonia(ruonia_frame)
    checks = {**verified.checks, **stlfsi.checks, **ruonia.checks}

    scores = v12.build_trend_scores(panel)
    weekly_v12 = v12.build_weekly_weights(panel, scores)
    governed = v25.apply_weekly_governor(weekly_v12, stlfsi)
    checks.update(governed.checks)
    levered = build_levered_governed_weights(governed.weights)
    target_build = v12.build_execution_targets(levered, active)
    mapped_gross = target_build.targets.groupby("effective_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    checks["mapped_target_gross_at_most_two"] = bool(
        mapped_gross.le(v15.MAXIMUM_GROSS + 1e-12).all()
    )

    market = v12.build_execution_market(observations, specs)
    coverage = v12.execution_coverage(market, target_build.targets)
    nonzero_targets = int(target_build.targets["target_weight"].abs().gt(1e-12).sum())
    covered_nonzero_targets = int(coverage["execution_dependencies_complete"].sum())
    checks["all_nonzero_next_open_dependencies_complete"] = (
        covered_nonzero_targets == nonzero_targets
    )
    if not all(checks.values()):
        raise ValueError(f"V26 pre-execution invariant failure: {checks}")

    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < v12.OOS_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(predecessor, v12.OOS_END)
    ].copy()
    scenario_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    collateral_outputs: dict[str, v15.CollateralEvaluation] = {}
    scenario_results: dict[str, dict[str, Any]] = {}
    for name, settings in v12._scenario_settings(protocol).items():
        result = v15.run_levered_portfolio_ledger(
            execution_market,
            target_build.targets,
            CapacityAwareLeveredLedgerConfig(
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name], collateral_outputs[name] = v15._scenario_payload(
            result, execution_market, settings, ruonia
        )

    oos_governor = governed.governor.loc[
        governed.governor["decision_date"].between(v12.OOS_START, v12.OOS_END)
    ]
    oos_counts = v25._state_counts(oos_governor)
    counts = {
        "source_panel_rows": int(len(panel)),
        "source_active_map_rows": int(len(active)),
        "source_contract_observation_rows": int(len(observations)),
        "source_spec_rows": int(len(specs)),
        "source_ruonia_rows": int(len(ruonia.frame)),
        "stlfsi_source_rows": int(len(stlfsi.frame)),
        "stlfsi_raw_records": stlfsi.raw_records,
        "score_rows": int(len(scores)),
        "finite_score_rows": int(scores["candidate_score"].notna().sum()),
        "all_weekly_decisions": int(len(governed.governor)),
        "oos_weekly_decisions": oos_counts["weekly_decisions"],
        "oos_pass_normal_or_below": oos_counts["pass_normal_or_below"],
        "oos_cash_above_average_stress": oos_counts["cash_above_average_stress"],
        "oos_cash_missing_or_stale": oos_counts["cash_missing_or_stale"],
        "mapped_weekly_decisions": target_build.weekly_decisions,
        "roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": int(len(target_build.targets)),
        "nonzero_targets": nonzero_targets,
        "covered_nonzero_targets": covered_nonzero_targets,
    }
    comparisons = _comparison(scenario_results["primary"])
    promotion = _promotion(scenario_results, checks)
    code_paths = {
        "v26_implementation": Path(__file__).resolve(),
        "v25_governor_parent": Path(v25.__file__).resolve(),
        "v15_collateral_parent": Path(v15.__file__).resolve(),
        "v12_frozen_parent": Path(v12.__file__).resolve(),
        "stlfsi_source_builder": Path(v25.stlfsi_source.__file__).resolve(),
        "portfolio_construction": PROJECT_ROOT / "src/market_lab/futures/portfolio_construction.py",
        "execution_dataset": PROJECT_ROOT / "src/market_lab/futures/execution_dataset.py",
        "portfolio_ledger": PROJECT_ROOT / "src/market_lab/futures/portfolio_ledger.py",
        "spec_proxy": PROJECT_ROOT / "src/market_lab/futures/spec_proxy.py",
    }
    identity = {
        "protocol_sha256": CONFIG_SHA256,
        "parent_v25_protocol_sha256": V25_PROTOCOL_SHA256,
        "parent_v25_metrics_sha256": V25_METRICS_SHA256,
        "infrastructure_v15_protocol_sha256": V15_PROTOCOL_SHA256,
        "infrastructure_v15_metrics_sha256": V15_METRICS_SHA256,
        "input_sha256": {
            name: declaration["sha256"] for name, declaration in protocol["inputs"].items()
        },
        "code_sha256": {name: v12.sha256_file(path) for name, path in code_paths.items()},
        "protected_from": v12.PROTECTED_FROM.date().isoformat(),
        "contains_2026_prices_returns_targets_or_pnl": False,
    }
    payload: dict[str, Any] = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "research_only": True,
        "adaptive_same_period": True,
        "independent_holdout_confirmation": False,
        "live_trading_allowed": False,
        "checks": checks,
        "input_metadata": verified.metadata,
        "identity": identity,
        "counts": counts,
        "scenarios": scenario_results,
        "comparisons": comparisons,
        "promotion": promotion,
        "limitations": protocol["execution"]["limitations"],
    }

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v26_stlfsi_levered_ruonia_capacity_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V26 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        v12._write_parquet(temporary / "scores.parquet", scores)
        v12._write_parquet(temporary / "weekly_v12_weights.parquet", weekly_v12)
        v12._write_parquet(temporary / "weekly_v25_governed_weights.parquet", governed.weights)
        v12._write_parquet(temporary / "weekly_v26_levered_weights.parquet", levered)
        governed.governor.to_csv(
            temporary / "stlfsi_governor.csv", index=False, encoding="utf-8-sig"
        )
        v12._write_parquet(temporary / "mapped_targets.parquet", target_build.targets)
        target_build.decision_audit.to_csv(
            temporary / "decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        for name, result in scenario_outputs.items():
            v12._write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            v12._write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            v12._write_parquet(temporary / f"positions_{name}.parquet", result.positions)
            v12._write_parquet(
                temporary / f"collateral_{name}.parquet", collateral_outputs[name].audit
            )
            v12._write_parquet(
                temporary / f"combined_ledger_{name}.parquet",
                collateral_outputs[name].combined_ledger,
            )
        report_path = temporary / "report.md"
        report_path.write_text(_report_text(payload), encoding="utf-8-sig")
        artifacts: dict[str, Any] = {}
        for path in sorted(temporary.iterdir()):
            if path.name in {"metrics.json", "identity.json"}:
                continue
            entry: dict[str, Any] = {
                "bytes": path.stat().st_size,
                "sha256": v12.sha256_file(path),
            }
            if path.suffix == ".parquet":
                entry["rows"] = pq.ParquetFile(path).metadata.num_rows
            artifacts[path.name] = entry
        payload["artifacts"] = artifacts
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(v12._json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8-sig",
        )
        identity_path = temporary / "identity.json"
        identity_path.write_text(
            json.dumps(
                v12._json_safe({**identity, "metrics_sha256": v12.sha256_file(metrics_path)}),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8-sig",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "runs",
        help="External immutable runs root; a unique V26 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
