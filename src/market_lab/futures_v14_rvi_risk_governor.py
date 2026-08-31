"""Sealed V14 frozen-V12 trend with a strictly lagged MOEX RVI risk governor."""

from __future__ import annotations

import argparse
import json
import math
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
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v14_rvi_risk_governor.yaml"
CONFIG_SHA256: Final[str] = (
    "9f680ebfcfcd6aae98a1e39eb44b9c51b59aa73067edc32e7a558399a8a29a53"
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
RVI_COLUMNS: Final[tuple[str, ...]] = (
    "source_date",
    "close",
    "conservative_available_from_date",
    "availability_rule",
    "provider",
    "current_vintage_snapshot",
)
RVI_CALIBRATION_START: Final[pd.Timestamp] = pd.Timestamp("2018-01-03")
RVI_CALIBRATION_END: Final[pd.Timestamp] = pd.Timestamp("2020-12-31")
RVI_CALIBRATION_ROWS: Final[int] = 756
RVI_FROZEN_MEDIAN: Final[float] = 24.134999999999998


@dataclass(frozen=True, slots=True)
class RviVerification:
    """Verified current-vintage RVI observations and fail-closed proof checks."""

    frame: pd.DataFrame
    checks: dict[str, bool]
    calibration_rows: int
    calibration_median: float


@dataclass(frozen=True, slots=True)
class GovernedWeights:
    """Post-V12 weights and one-row-per-week RVI decision audit."""

    weights: pd.DataFrame
    governor: pd.DataFrame


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the V14 byte seal and all fixed economics before reading OOS outcomes."""
    config_path = config_path.resolve()
    if config_path != CONFIG_PATH.resolve() or v12.sha256_file(config_path) != CONFIG_SHA256:
        raise ValueError("sealed V14 protocol byte drift")
    sidecar = config_path.with_suffix(".sha256")
    stated = sidecar.read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V14 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V14 protocol must be a mapping")
    parent = protocol["parent_v12"]
    signal = protocol["signal"]
    governor = protocol["risk_governor"]
    portfolio = protocol["portfolio"]
    execution = protocol["execution"]
    reference = {str(key): float(value) for key, value in parent["primary_reference"].items()}
    if (
        protocol.get("protocol_id") != "futures_v14_rvi_risk_governor_v1"
        or protocol.get("status") != "predeclared_before_v14_oos_outcomes"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or tuple(protocol["universe"]["exact_order"]) != v12.ASSETS
        or parent["protocol_sha256"] != V12_PROTOCOL_SHA256
        or parent["metrics_sha256"] != V12_METRICS_SHA256
        or reference != V12_PRIMARY_REFERENCE
        or tuple(protocol["inputs"]["rvi"]["allowed_columns"]) != RVI_COLUMNS
        or tuple(int(value) for value in signal["log_momentum_horizons_sessions"])
        != v12.MOMENTUM_HORIZONS
        or int(signal["volatility_lookback_sessions"]) != v12.VOLATILITY_LOOKBACK
        or int(signal["annualization_sessions"]) != v12.ANNUALIZATION
        or float(signal["volatility_floor_annualized"]) != v12.VOLATILITY_FLOOR
        or signal.get("score_implementation") != "imported_frozen_v12"
        or signal.get("hyperparameter_search") is not False
        or int(governor["calibration_rows"]) != RVI_CALIBRATION_ROWS
        or float(governor["frozen_rvi_median"]) != RVI_FROZEN_MEDIAN
        or governor["source_value"]
        != "exact_previous_factual_core4_panel_session_rvi_close"
        or governor["formula"]
        != "min(1.0, frozen_rvi_median / previous_session_rvi_close)"
        or governor["lower_floor"] != "none"
        or float(governor["upper_cap"]) != 1.0
        or governor["scale_can_increase_v12_risk"] is not False
        or int(portfolio["ewma_volatility_span_sessions"]) != 20
        or int(portfolio["covariance_lookback_sessions"]) != 60
        or float(portfolio["annual_target_volatility_before_governor"]) != 0.20
        or float(portfolio["gross_cap"]) != 1.0
        or int(portfolio["turnover_sleeves"]) != 5
        or float(execution["maximum_participation"]) != v12.MAXIMUM_PARTICIPATION
        or float(execution["initial_cash_rub"]) != v12.INITIAL_CASH
        or execution["execution_atomicity"] != "asset"
    ):
        raise ValueError("sealed V14 protocol invariants were weakened")
    if v12._scenario_settings(protocol) != {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }:
        raise ValueError("sealed V14 cost scenarios drifted")
    return protocol


def verify_inputs(protocol: dict[str, Any]) -> v12.VerifiedInputs:
    """Reuse the frozen V12 byte/date preflight and add the V14 protocol seal."""
    verified = v12.verify_inputs(protocol)
    checks = dict(verified.checks)
    checks["v12_parent_protocol_seal"] = checks.pop("protocol_seal")
    checks["v14_protocol_seal"] = v12.sha256_file(CONFIG_PATH) == CONFIG_SHA256
    if not all(checks.values()):
        raise ValueError(f"V14 input identity preflight failed: {checks}")
    return v12.VerifiedInputs(
        paths=verified.paths,
        checks=checks,
        metadata=verified.metadata,
    )


def _normalize_date(values: pd.Series, name: str) -> pd.Series:
    dates = pd.to_datetime(values, errors="raise")
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert("UTC").dt.tz_localize(None)
    normalized = dates.dt.normalize()
    if normalized.ge(v12.PROTECTED_FROM).any():
        raise ValueError(f"V14 {name} touches protected 2026+")
    return normalized


def verify_rvi_source(frame: pd.DataFrame) -> RviVerification:
    """Verify schema, conservative availability and the frozen 2018-2020 statistic."""
    required = set(RVI_COLUMNS)
    if missing := required - set(frame.columns):
        raise ValueError(f"V14 RVI source lacks columns: {sorted(missing)}")
    rvi = frame.loc[:, RVI_COLUMNS].copy()
    rvi["source_date"] = _normalize_date(rvi["source_date"], "RVI source_date")
    rvi["conservative_available_from_date"] = _normalize_date(
        rvi["conservative_available_from_date"], "RVI availability"
    )
    if rvi.duplicated("source_date").any():
        raise ValueError("V14 RVI source has duplicate dates")
    close = pd.to_numeric(rvi["close"], errors="coerce").astype(float)
    if close.isna().any() or not np.isfinite(close).all() or close.le(0.0).any():
        raise ValueError("V14 RVI close must be finite and positive")
    rvi["close"] = close
    expected_available = rvi["source_date"] + pd.Timedelta(days=1)
    if not rvi["conservative_available_from_date"].equals(expected_available):
        raise ValueError("V14 RVI conservative availability drift")
    if not rvi["availability_rule"].astype("string").eq(
        "use_only_when_source_date_strictly_before_decision_date"
    ).all():
        raise ValueError("V14 RVI availability rule drift")
    if not rvi["provider"].astype("string").eq("MOEX ISS").all():
        raise ValueError("V14 RVI provider drift")
    current = rvi["current_vintage_snapshot"]
    if current.isna().any() or not current.map(
        lambda value: isinstance(value, (bool, np.bool_))
    ).all():
        raise ValueError("V14 current_vintage_snapshot must be boolean")
    if not current.astype(bool).all():
        raise ValueError("V14 RVI input is not the declared current-vintage snapshot")
    if len(rvi) != 2014:
        raise ValueError("V14 RVI row identity drift")
    if rvi["source_date"].min() != pd.Timestamp("2018-01-03") or rvi[
        "source_date"
    ].max() != pd.Timestamp("2025-12-30"):
        raise ValueError("V14 RVI temporal identity drift")
    calibration = rvi.loc[
        rvi["source_date"].between(RVI_CALIBRATION_START, RVI_CALIBRATION_END)
    ]
    median = float(calibration["close"].median())
    if len(calibration) != RVI_CALIBRATION_ROWS or not math.isclose(
        median, RVI_FROZEN_MEDIAN, rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError("V14 frozen RVI calibration identity drift")
    checks = {
        "rvi_rows_dates_and_schema_exact": True,
        "rvi_has_no_2026_rows": True,
        "rvi_close_finite_positive": True,
        "rvi_conservative_availability_exact": True,
        "rvi_current_vintage_disclosed": True,
        "rvi_calibration_ends_before_oos": RVI_CALIBRATION_END < v12.OOS_START,
        "rvi_frozen_warmup_median_exact": True,
    }
    return RviVerification(
        frame=rvi.sort_values("source_date", kind="mergesort", ignore_index=True),
        checks=checks,
        calibration_rows=len(calibration),
        calibration_median=median,
    )


def apply_rvi_governor(
    panel: pd.DataFrame,
    weekly_weights: pd.DataFrame,
    rvi: RviVerification,
) -> GovernedWeights:
    """Scale all V12 weights down using only the exact previous core-four session's RVI."""
    required = {"decision_date", "asset", "target_weight", "provenance"}
    if missing := required - set(weekly_weights.columns):
        raise ValueError(f"V14 weekly weights lack columns: {sorted(missing)}")
    weights = weekly_weights.copy()
    weights["decision_date"] = pd.to_datetime(
        weights["decision_date"], errors="raise"
    ).dt.normalize()
    if weights.duplicated(["decision_date", "asset"]).any():
        raise ValueError("V14 weekly weights have duplicate keys")
    if weights.groupby("decision_date")["asset"].nunique().ne(len(v12.ASSETS)).any():
        raise ValueError("V14 weekly weights do not contain complete snapshots")

    signal_panel = v12.normalize_signal_panel(panel)
    calendar = pd.DatetimeIndex(signal_panel["trade_date"].drop_duplicates().sort_values())
    previous_by_date = pd.Series(calendar[:-1], index=calendar[1:])
    decisions = pd.DatetimeIndex(weights["decision_date"].drop_duplicates().sort_values())
    governor = pd.DataFrame({"decision_date": decisions})
    governor["rvi_source_date"] = governor["decision_date"].map(previous_by_date)
    source = rvi.frame.rename(
        columns={
            "source_date": "rvi_source_date",
            "close": "rvi_close",
            "conservative_available_from_date": "rvi_available_from_date",
        }
    )
    governor = governor.merge(
        source.loc[:, ["rvi_source_date", "rvi_close", "rvi_available_from_date"]],
        on="rvi_source_date",
        how="left",
        validate="many_to_one",
    )
    available = (
        governor["rvi_source_date"].notna()
        & governor["rvi_close"].notna()
        & np.isfinite(governor["rvi_close"])
        & governor["rvi_source_date"].lt(governor["decision_date"])
        & governor["rvi_available_from_date"].le(governor["decision_date"])
    )
    governor["risk_scale_available"] = available
    governor["risk_scale"] = np.nan
    governor.loc[available, "risk_scale"] = np.minimum(
        1.0,
        RVI_FROZEN_MEDIAN / governor.loc[available, "rvi_close"].astype(float),
    )
    finite_scale = governor.loc[available, "risk_scale"]
    if finite_scale.le(0.0).any() or finite_scale.gt(1.0).any():
        raise ValueError("V14 RVI governor produced an invalid or empty risk scale")
    governor["downscaled"] = available & governor["risk_scale"].lt(1.0 - 1e-12)

    governed = weights.merge(
        governor,
        on="decision_date",
        how="left",
        validate="many_to_one",
    )
    governed["v12_target_weight"] = pd.to_numeric(
        governed["target_weight"], errors="raise"
    ).astype(float)
    governed["target_weight"] = 0.0
    admitted = governed["risk_scale_available"].fillna(False).astype(bool)
    governed.loc[admitted, "target_weight"] = (
        governed.loc[admitted, "v12_target_weight"]
        * governed.loc[admitted, "risk_scale"].astype(float)
    )
    if governed["target_weight"].abs().gt(
        governed["v12_target_weight"].abs() + 1e-12
    ).any():
        raise ValueError("V14 RVI governor increased a frozen V12 target")
    gross = governed.groupby("decision_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    if gross.gt(1.0 + 1e-12).any():
        raise ValueError("V14 governed weekly weights exceed gross one")
    governed["provenance"] = governed["provenance"].astype("string") + np.where(
        admitted,
        "|prior_session_rvi_proportional_downscale",
        "|missing_previous_session_rvi_cash",
    )
    return GovernedWeights(
        weights=governed.sort_values(
            ["decision_date", "asset"], kind="mergesort", ignore_index=True
        ),
        governor=governor.sort_values("decision_date", kind="mergesort", ignore_index=True),
    )


def _scenario_metrics_with_risk(
    result: FuturesPortfolioLedgerResult,
    market: pd.DataFrame,
    settings: dict[str, float],
) -> dict[str, Any]:
    metrics = v12.scenario_metrics(result, market, settings)
    ledger = result.ledger
    metrics["maximum_post_mark_gross_leverage"] = (
        float(ledger["gross_leverage"].max()) if not ledger.empty else 0.0
    )
    metrics["maximum_2x_margin_to_starting_cash"] = (
        float((2.0 * ledger["modeled_initial_margin"] / ledger["starting_cash"]).max())
        if not ledger.empty
        else 0.0
    )
    return metrics


def _comparison(primary: dict[str, Any]) -> dict[str, Any]:
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
        "every_input_rvi_and_temporal_check_true": all(checks.values()),
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
        "no_order_time_gross_participation_or_margin_breach": all(
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
        "# V14 frozen V12 plus prior-session RVI risk governor",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        "This is one adaptive 2021-2025 stability hypothesis, not independent confirmation.",
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
            "## RVI, coverage and execution",
            "",
            f"- Frozen 2018-2020 RVI median: {counts['rvi_calibration_median']:.6f}",
            f"- OOS RVI-available weekly decisions: {counts['rvi_available_weekly_decisions']}",
            f"- OOS downscaled weekly decisions: {counts['rvi_downscaled_weekly_decisions']}",
            f"- OOS missing-RVI weekly decisions: {counts['rvi_missing_weekly_decisions']}",
            f"- Minimum/mean admitted scale: {counts['minimum_risk_scale']:.4f}/"
            f"{counts['mean_risk_scale']:.4f}",
            f"- Weekly decisions: {counts['weekly_decisions']}",
            f"- Extra roll decisions: {counts['roll_decisions']}",
            f"- Non-zero targets: {counts['nonzero_targets']}",
            f"- Complete next-open dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "RVI is a current-vintage source and is used only from the exact previous core-four "
            "session. Terminal positions are carried; broker/order-book economics remain proxy.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute exactly one immutable V14 adaptive-development run."""
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
    rvi_frame = pd.read_parquet(
        verified.paths["rvi"], columns=protocol["inputs"]["rvi"]["allowed_columns"]
    )
    rvi = verify_rvi_source(rvi_frame)
    checks = {**verified.checks, **rvi.checks}
    scores = v12.build_trend_scores(panel)
    v12_weekly_weights = v12.build_weekly_weights(panel, scores)
    governed = apply_rvi_governor(panel, v12_weekly_weights, rvi)
    target_build = v12.build_execution_targets(governed.weights, active)
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
        scenario_results[name] = _scenario_metrics_with_risk(
            result, execution_market, settings
        )

    oos_governor = governed.governor.loc[
        governed.governor["decision_date"].between(v12.OOS_START, v12.OOS_END)
    ]
    admitted_scales = oos_governor.loc[
        oos_governor["risk_scale_available"], "risk_scale"
    ].astype(float)
    counts = {
        "source_panel_rows": int(len(panel)),
        "source_active_map_rows": int(len(active)),
        "source_contract_observation_rows": int(len(observations)),
        "source_spec_rows": int(len(specs)),
        "source_rvi_rows": int(len(rvi.frame)),
        "rvi_calibration_rows": rvi.calibration_rows,
        "rvi_calibration_median": rvi.calibration_median,
        "score_rows": int(len(scores)),
        "finite_score_rows": int(scores["candidate_score"].notna().sum()),
        "rvi_available_weekly_decisions": int(
            oos_governor["risk_scale_available"].sum()
        ),
        "rvi_downscaled_weekly_decisions": int(oos_governor["downscaled"].sum()),
        "rvi_missing_weekly_decisions": int(
            (~oos_governor["risk_scale_available"]).sum()
        ),
        "minimum_risk_scale": float(admitted_scales.min()),
        "mean_risk_scale": float(admitted_scales.mean()),
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
        "v14_implementation": Path(__file__).resolve(),
        "v12_frozen_parent": Path(v12.__file__).resolve(),
        "rvi_source_builder": PROJECT_ROOT / "src/market_lab/futures/rvi_source.py",
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
    run_name = f"v14_rvi_governor_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V14 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        v12._write_parquet(temporary / "scores.parquet", scores)
        v12._write_parquet(temporary / "weekly_weights.parquet", governed.weights)
        governed.governor.to_csv(
            temporary / "rvi_governor.csv", index=False, encoding="utf-8-sig"
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
        help="External immutable runs root; a unique V14 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
