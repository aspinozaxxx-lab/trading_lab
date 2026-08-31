"""Sealed V13 core-four trend plus causal futures-curve confirmation experiment."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    FuturesPortfolioLedgerResult,
    run_futures_portfolio_ledger,
)

PROJECT_ROOT: Final[Path] = v12.PROJECT_ROOT
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v13_trend_carry_confirmation.yaml"
CONFIG_SHA256: Final[str] = (
    "94841c0baa1f4c7e0f88302467dfde3bc8104b2e662382b9224bbaf9b75f07ef"
)
V12_PROTOCOL_SHA256: Final[str] = v12.CONFIG_SHA256
V12_METRICS_SHA256: Final[str] = (
    "c989377f7de65c3ef0a8dd52a1f5fcbf11c6ad8048119ea0a7b4402f47b23288"
)
V12_PRIMARY_REFERENCE: Final[dict[str, float]] = {
    "total_return": 0.451113922334873,
    "cagr": 0.07731837008966158,
    "sharpe": 0.7624477569712388,
    "maximum_drawdown": 0.14152584161232418,
    "positive_years": 4.0,
    "worst_year": -0.026317846517727284,
    "total_cost_rub": 13387.28160116245,
}
PANEL_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "asset_code",
    "close",
    "curve_observed_through",
    "curve_available_at",
    "front_settle",
    "next_settle",
    "front_expiration_date",
    "next_expiration_date",
    "roll_yield",
    "curve_valid",
)


@dataclass(frozen=True, slots=True)
class CurveVerification:
    """Holds independently verified same-close carry observations and proof checks."""

    frame: pd.DataFrame
    checks: dict[str, bool]


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the V13 byte seal and the experiment invariants before reading outcomes."""
    config_path = config_path.resolve()
    if config_path != CONFIG_PATH.resolve() or v12.sha256_file(config_path) != CONFIG_SHA256:
        raise ValueError("sealed V13 protocol byte drift")
    sidecar = config_path.with_suffix(".sha256")
    stated = sidecar.read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V13 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V13 protocol must be a mapping")

    parent = protocol["parent_v12"]
    signal = protocol["signal"]
    inherited = signal["inherited_v12_trend"]
    portfolio = protocol["portfolio"]
    execution = protocol["execution"]
    reference = {str(key): float(value) for key, value in parent["primary_reference"].items()}
    if (
        protocol.get("protocol_id") != "futures_v13_trend_carry_confirmation_v1"
        or protocol.get("status") != "predeclared_before_v13_oos_outcomes"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or tuple(protocol["universe"]["exact_order"]) != v12.ASSETS
        or parent["protocol_sha256"] != V12_PROTOCOL_SHA256
        or parent["metrics_sha256"] != V12_METRICS_SHA256
        or reference != V12_PRIMARY_REFERENCE
        or tuple(protocol["inputs"]["panel"]["allowed_columns"]) != PANEL_COLUMNS
        or tuple(int(value) for value in inherited["log_momentum_horizons_sessions"])
        != v12.MOMENTUM_HORIZONS
        or int(inherited["volatility_lookback_sessions"]) != v12.VOLATILITY_LOOKBACK
        or int(inherited["annualization_sessions"]) != v12.ANNUALIZATION
        or float(inherited["volatility_floor_annualized"]) != v12.VOLATILITY_FLOOR
        or signal["carry"]["normalization"] != "sign_only"
        or signal.get("fit_or_training") != "none"
        or signal.get("hyperparameter_search") is not False
        or int(portfolio["ewma_volatility_span_sessions"]) != 20
        or int(portfolio["covariance_lookback_sessions"]) != 60
        or float(portfolio["annual_target_volatility"]) != 0.20
        or float(portfolio["gross_cap"]) != 1.0
        or int(portfolio["turnover_sleeves"]) != 5
        or float(execution["maximum_participation"]) != v12.MAXIMUM_PARTICIPATION
        or float(execution["initial_cash_rub"]) != v12.INITIAL_CASH
        or execution["execution_atomicity"] != "asset"
    ):
        raise ValueError("sealed V13 protocol invariants were weakened")
    if v12._scenario_settings(protocol) != {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }:
        raise ValueError("sealed V13 cost scenarios drifted")
    return protocol


def verify_inputs(protocol: dict[str, Any]) -> v12.VerifiedInputs:
    """Reuse V12 byte/date preflight while making both parent and V13 seals explicit."""
    verified = v12.verify_inputs(protocol)
    checks = dict(verified.checks)
    checks["v12_parent_protocol_seal"] = checks.pop("protocol_seal")
    checks["v13_protocol_seal"] = v12.sha256_file(CONFIG_PATH) == CONFIG_SHA256
    if not all(checks.values()):
        raise ValueError(f"V13 input identity preflight failed: {checks}")
    return v12.VerifiedInputs(
        paths=verified.paths,
        checks=checks,
        metadata=verified.metadata,
    )


def _normalized_dates(values: pd.Series, name: str) -> pd.Series:
    dates = pd.to_datetime(values, errors="raise")
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert("UTC").dt.tz_localize(None)
    normalized = dates.dt.normalize()
    if name in {"trade_date", "curve_observed_through"} and normalized.ge(
        v12.PROTECTED_FROM
    ).any():
        raise ValueError(f"V13 {name} touches protected 2026+")
    return normalized


def verify_curve_panel(frame: pd.DataFrame) -> CurveVerification:
    """Independently prove that roll yield was known at decision close and is exact."""
    required = set(PANEL_COLUMNS)
    if missing := required - set(frame.columns):
        raise ValueError(f"V13 curve panel lacks columns: {sorted(missing)}")
    curve = frame.loc[:, PANEL_COLUMNS].copy()
    curve["trade_date"] = _normalized_dates(curve["trade_date"], "trade_date")
    curve["curve_observed_through"] = _normalized_dates(
        curve["curve_observed_through"], "curve_observed_through"
    )
    curve["front_expiration_date"] = _normalized_dates(
        curve["front_expiration_date"], "front_expiration_date"
    )
    curve["next_expiration_date"] = _normalized_dates(
        curve["next_expiration_date"], "next_expiration_date"
    )
    curve["asset"] = curve["asset_code"].map(v12._asset_code)
    if curve.duplicated(["trade_date", "asset"]).any():
        raise ValueError("V13 curve panel has duplicate date/asset rows")
    if set(curve["asset"]) != set(v12.ASSETS):
        raise ValueError("V13 curve panel universe drift")

    raw_valid = curve["curve_valid"]
    bool_types = (bool, np.bool_)
    valid_types = raw_valid.map(lambda value: isinstance(value, bool_types))
    if raw_valid.isna().any() or not valid_types.all():
        raise ValueError("V13 curve_valid must be non-missing boolean")
    stored_valid = raw_valid.astype(bool)
    for column in ("front_settle", "next_settle", "roll_yield"):
        values = pd.to_numeric(curve[column], errors="coerce").astype(float)
        if np.isinf(values.to_numpy(dtype=float)).any():
            raise ValueError(f"V13 {column} contains infinity")
        curve[column] = values

    distance = (curve["next_expiration_date"] - curve["front_expiration_date"]).dt.days
    independently_valid = (
        curve["front_settle"].notna()
        & curve["next_settle"].notna()
        & curve["front_settle"].gt(0.0)
        & curve["next_settle"].gt(0.0)
        & curve["front_expiration_date"].notna()
        & curve["next_expiration_date"].notna()
        & distance.gt(0)
    )
    if not stored_valid.equals(independently_valid.astype(bool)):
        raise ValueError("V13 curve_valid disagrees with independent front/next proof")
    recomputed = (
        (curve["front_settle"] / curve["next_settle"] - 1.0)
        * (365.0 / distance.astype(float))
    ).where(independently_valid)
    if not np.allclose(
        curve.loc[independently_valid, "roll_yield"].to_numpy(dtype=float),
        recomputed.loc[independently_valid].to_numpy(dtype=float),
        rtol=1e-12,
        atol=1e-12,
        equal_nan=False,
    ):
        raise ValueError("V13 stored roll_yield differs from independent recomputation")
    if curve.loc[~independently_valid, "roll_yield"].notna().any():
        raise ValueError("V13 invalid curve rows must preserve roll_yield as missing")
    if not curve["curve_observed_through"].equals(curve["trade_date"]):
        raise ValueError("V13 curve was not observed through the decision date exactly")
    availability = curve["curve_available_at"].astype("string")
    if availability.isna().any() or not availability.eq("decision_close").all():
        raise ValueError("V13 curve availability is not exactly decision_close")

    checks = {
        "curve_observed_through_equals_decision_date": True,
        "curve_available_at_decision_close": True,
        "curve_valid_recomputed_from_positive_simultaneous_settles": True,
        "next_expiration_strictly_after_front_when_valid": True,
        "stored_roll_yield_matches_independent_recomputation": True,
        "invalid_curve_roll_yield_preserves_missingness": True,
    }
    output = curve.loc[:, ["trade_date", "asset", "roll_yield"]].copy()
    output["carry_available"] = independently_valid.to_numpy(dtype=bool)
    return CurveVerification(
        frame=output.sort_values(
            ["trade_date", "asset"], kind="mergesort", ignore_index=True
        ),
        checks=checks,
    )


def build_trend_carry_scores(
    panel: pd.DataFrame,
    curve_verification: CurveVerification | None = None,
) -> pd.DataFrame:
    """Keep V12 trend only where finite same-close roll yield has the same strict sign."""
    proof = curve_verification or verify_curve_panel(panel)
    trend = v12.build_trend_scores(panel).rename(columns={"candidate_score": "trend_score"})
    carry = proof.frame.rename(columns={"trade_date": "decision_date"})
    scores = trend.merge(
        carry,
        on=["decision_date", "asset"],
        how="left",
        validate="one_to_one",
    )
    trend_finite = scores["trend_score"].notna() & np.isfinite(scores["trend_score"])
    carry_finite = (
        scores["carry_available"].fillna(False).astype(bool)
        & scores["roll_yield"].notna()
        & np.isfinite(scores["roll_yield"])
    )
    inputs_available = trend_finite & carry_finite
    agrees = inputs_available & scores["trend_score"].mul(scores["roll_yield"]).gt(0.0)
    observed_neutral = inputs_available & ~agrees
    scores["candidate_score"] = np.nan
    scores.loc[observed_neutral, "candidate_score"] = 0.0
    scores.loc[agrees, "candidate_score"] = scores.loc[agrees, "trend_score"]
    scores["confirmation_state"] = "missing_input"
    scores.loc[observed_neutral, "confirmation_state"] = "observed_not_confirmed"
    scores.loc[agrees, "confirmation_state"] = "confirmed"
    scores["confirmation_agrees"] = agrees
    return scores.sort_values(
        ["decision_date", "asset"], kind="mergesort", ignore_index=True
    )


def _comparison(primary: dict[str, Any]) -> dict[str, Any]:
    """Report signed deltas against the already-frozen V12 primary result."""
    return {
        "reference_protocol_sha256": V12_PROTOCOL_SHA256,
        "reference_metrics_sha256": V12_METRICS_SHA256,
        "reference": V12_PRIMARY_REFERENCE,
        "delta": {
            "total_return": float(primary["total_return"])
            - V12_PRIMARY_REFERENCE["total_return"],
            "cagr": float(primary["cagr"]) - V12_PRIMARY_REFERENCE["cagr"],
            "sharpe": float(primary["sharpe"]) - V12_PRIMARY_REFERENCE["sharpe"],
            "maximum_drawdown_reduction": V12_PRIMARY_REFERENCE["maximum_drawdown"]
            - float(primary["maximum_drawdown"]),
            "worst_year_improvement": float(primary["worst_year"])
            - V12_PRIMARY_REFERENCE["worst_year"],
            "cost_reduction_rub": V12_PRIMARY_REFERENCE["total_cost_rub"]
            - float(primary["total_cost"]),
        },
    }


def _promotion(
    results: dict[str, dict[str, Any]], checks: dict[str, bool]
) -> dict[str, Any]:
    primary = results["primary"]
    conditions = {
        "every_input_curve_and_temporal_check_true": all(checks.values()),
        "all_scenarios_execution_complete": all(
            bool(value["execution_complete"]) for value in results.values()
        ),
        "zero_critical_failures_and_unresolved_halts": all(
            int(value["critical_failure_count"]) == 0
            and int(value["unresolved_halt_count"]) == 0
            for value in results.values()
        ),
        "primary_cagr_at_least_0_05": float(primary["cagr"]) >= 0.05,
        "primary_sharpe_at_least_frozen_v12": float(primary["sharpe"])
        >= V12_PRIMARY_REFERENCE["sharpe"],
        "primary_maximum_drawdown_at_most_frozen_v12": float(
            primary["maximum_drawdown"]
        )
        <= V12_PRIMARY_REFERENCE["maximum_drawdown"],
        "primary_positive_years_at_least_4_of_5": int(primary["positive_years"]) >= 4
        and len(primary["annual_returns"]) == 5,
        "doubled_total_return_positive": float(results["doubled"]["total_return"]) > 0.0,
        "stress_total_return_positive": float(results["stress"]["total_return"]) > 0.0,
        "no_gross_participation_or_margin_breach": all(
            float(value["maximum_participation"]) <= v12.MAXIMUM_PARTICIPATION + 1e-12
            and int(value["gross_limit_rejection_count"]) == 0
            and int(value["initial_margin_rejection_count"]) == 0
            and float(value["ending_cash"]) > 0.0
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
        "# V13 trend plus futures-curve confirmation",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        (
            "This is an adaptive challenger on the already-observed 2021-2025 period, "
            "not independent confirmation."
        ),
        "",
        "| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name in ("primary", "doubled", "stress"):
        item = payload["scenarios"][name]
        lines.append(
            f"| {name} | {item['total_return']:.4%} | {item['cagr']:.4%} | "
            f"{item['sharpe']:.3f} | {item['maximum_drawdown']:.4%} | "
            f"{item['positive_years']}/5 | {item['total_cost']:.2f} | "
            f"{item['execution_complete']} |"
        )
    delta = payload["comparison_to_v12"]["delta"]
    lines.extend(
        [
            "",
            "## Delta versus frozen V12 primary",
            "",
            f"- CAGR: {delta['cagr']:+.4%}",
            f"- Sharpe: {delta['sharpe']:+.4f}",
            f"- Drawdown reduction: {delta['maximum_drawdown_reduction']:+.4%}",
            f"- Worst-year improvement: {delta['worst_year_improvement']:+.4%}",
            f"- Cost reduction: {delta['cost_reduction_rub']:+.2f} RUB",
            "",
            "## Primary annual returns",
            "",
        ]
    )
    for year, value in payload["scenarios"]["primary"]["annual_returns"].items():
        lines.append(f"- {year}: {value:.4%}")
    counts = payload["counts"]
    lines.extend(
        [
            "",
            "## Signal, coverage and execution",
            "",
            f"- Curve-valid rows: {counts['curve_valid_rows']}",
            f"- Confirmed rows: {counts['trend_carry_agreement_rows']}",
            f"- Observed but not confirmed rows: {counts['trend_carry_disagreement_rows']}",
            f"- Weekly decisions: {counts['weekly_decisions']}",
            f"- Extra roll decisions: {counts['roll_decisions']}",
            f"- Non-zero targets: {counts['nonzero_targets']}",
            f"- Complete next-open dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "Terminal positions are carried with a one-way exit reserve. Historical exchange "
            "specs, broker fees, order-book spread and queue remain approximate.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute exactly one immutable V13 adaptive-development run."""
    protocol = load_protocol()
    verified = verify_inputs(protocol)
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
    curve = verify_curve_panel(panel)
    checks = {**verified.checks, **curve.checks}
    scores = build_trend_carry_scores(panel, curve)
    weekly_weights = v12.build_weekly_weights(panel, scores)
    target_build = v12.build_execution_targets(weekly_weights, active)
    market = v12.build_execution_market(observations, specs)
    coverage = v12.execution_coverage(market, target_build.targets)

    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < v12.OOS_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(
            predecessor, v12.OOS_END
        )
    ].copy()
    scenario_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    scenario_results: dict[str, dict[str, Any]] = {}
    for name, settings in v12._scenario_settings(protocol).items():
        result = run_futures_portfolio_ledger(
            execution_market,
            target_build.targets,
            FuturesPortfolioLedgerConfig(
                initial_cash=v12.INITIAL_CASH,
                expected_assets=v12.ASSETS,
                maximum_gross_notional_multiple=1.0,
                initial_margin_buffer_multiplier=2.0,
                maximum_participation=v12.MAXIMUM_PARTICIPATION,
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
                execution_atomicity="asset",
                terminal_policy="carry",
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name] = v12.scenario_metrics(result, execution_market, settings)

    oos_scores = scores.loc[scores["decision_date"].between(v12.OOS_START, v12.OOS_END)]
    counts = {
        "source_panel_rows": int(len(panel)),
        "source_active_map_rows": int(len(active)),
        "source_contract_observation_rows": int(len(observations)),
        "source_spec_rows": int(len(specs)),
        "score_rows": int(len(scores)),
        "finite_score_rows": int(scores["candidate_score"].notna().sum()),
        "curve_valid_rows": int(curve.frame["carry_available"].sum()),
        "oos_curve_valid_rows": int(oos_scores["carry_available"].sum()),
        "trend_carry_agreement_rows": int(
            oos_scores["confirmation_state"].eq("confirmed").sum()
        ),
        "trend_carry_disagreement_rows": int(
            oos_scores["confirmation_state"].eq("observed_not_confirmed").sum()
        ),
        "missing_signal_input_rows": int(
            oos_scores["confirmation_state"].eq("missing_input").sum()
        ),
        "weekly_decisions": target_build.weekly_decisions,
        "roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": int(len(target_build.targets)),
        "nonzero_targets": int(
            target_build.targets["target_weight"].abs().gt(1e-12).sum()
        ),
        "covered_nonzero_targets": int(coverage["execution_dependencies_complete"].sum()),
    }
    comparison = _comparison(scenario_results["primary"])
    promotion = _promotion(scenario_results, checks)
    code_paths = {
        "v13_implementation": Path(__file__).resolve(),
        "v12_frozen_parent": Path(v12.__file__).resolve(),
        "portfolio_construction": PROJECT_ROOT
        / "src/market_lab/futures/portfolio_construction.py",
        "execution_dataset": PROJECT_ROOT / "src/market_lab/futures/execution_dataset.py",
        "portfolio_ledger": PROJECT_ROOT / "src/market_lab/futures/portfolio_ledger.py",
        "spec_proxy": PROJECT_ROOT / "src/market_lab/futures/spec_proxy.py",
    }
    identity = {
        "protocol_sha256": CONFIG_SHA256,
        "parent_v12_protocol_sha256": V12_PROTOCOL_SHA256,
        "parent_v12_metrics_sha256": V12_METRICS_SHA256,
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
        "comparison_to_v12": comparison,
        "promotion": promotion,
        "limitations": protocol["execution"]["limitations"],
    }

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v13_trend_carry_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V13 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        v12._write_parquet(temporary / "scores.parquet", scores)
        v12._write_parquet(temporary / "weekly_weights.parquet", weekly_weights)
        v12._write_parquet(temporary / "mapped_targets.parquet", target_build.targets)
        target_build.decision_audit.to_csv(
            temporary / "decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        for name, result in scenario_outputs.items():
            v12._write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            v12._write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            v12._write_parquet(temporary / f"positions_{name}.parquet", result.positions)
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
                v12._json_safe(
                    {**identity, "metrics_sha256": v12.sha256_file(metrics_path)}
                ),
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
        help="External immutable runs root; a unique V13 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
