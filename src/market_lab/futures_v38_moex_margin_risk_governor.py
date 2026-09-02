"""Sealed V38: frozen V27 plus an asset-specific official MOEX MR1 governor."""

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
from market_lab import futures_v15_levered_ruonia_collateral as v15
from market_lab import futures_v25_stlfsi_stress_governor as v25
from market_lab import futures_v26_stlfsi_levered_ruonia_capacity as v26
from market_lab import futures_v27_key_rate_extreme_governor as v27
from market_lab.futures import moex_rms_historical_pit_source as rms_source
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult

PROJECT_ROOT: Final[Path] = v12.PROJECT_ROOT
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v38_moex_margin_risk_governor.yaml"
CONFIG_SHA256: Final[str] = "3f9288e38948464d73a4f76ef68f53ebcefe879a6a952482bff13e451926c4ac"
SOURCE_ROOT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/info_radar/moex-rms-historical-pit-2018-2025-v4"
)
SOURCE_CONFIG_SHA256: Final[str] = rms_source.CONFIG_SHA256
SOURCE_MANIFEST_SHA256: Final[str] = (
    "e88360d3f1a3476e3e34a67b947fb7aa1a656a2c290aa46e27add84dd397b2e3"
)
SOURCE_AUDIT_SHA256: Final[str] = (
    "013c6e234521fc5d6eebf143bddb3c35392251c414dc014e749f672b8726824c"
)
SOURCE_LIMITS_SHA256: Final[str] = (
    "b0def4c6fdfb385ee715144cd32dd9c167503c6021c2177f3ce021ff915aed19"
)
SOURCE_LIMITS_ROWS: Final[int] = 189_682
MAXIMUM_SOURCE_AGE_DAYS: Final[int] = 7
ASSET_MAPPING: Final[dict[str, str]] = {
    "SI": "Si",
    "RI": "RTS",
    "BR": "BR",
    "MIX": "MIX",
}


@dataclass(frozen=True, slots=True)
class MarginRiskVerification:
    """Verified target-free official MOEX level-1 risk-rate history."""

    frame: pd.DataFrame
    checks: dict[str, bool]
    manifest_sha256: str
    audit_sha256: str


@dataclass(frozen=True, slots=True)
class MarginRiskGovernorBuild:
    """Frozen V27 weights after the asset-specific MR1 reduction."""

    weights: pd.DataFrame
    governor: pd.DataFrame
    checks: dict[str, bool]


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the V38 byte seal and its single structural-zero rule."""
    path = config_path.resolve()
    if path != CONFIG_PATH.resolve() or v12.sha256_file(path) != CONFIG_SHA256:
        raise ValueError("sealed V38 protocol byte drift")
    if path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0] != CONFIG_SHA256:
        raise ValueError("V38 sidecar does not match the code-pinned seal")
    protocol = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    parent = protocol["parent_v27"]
    source = protocol["source"]
    governor = protocol["margin_risk_governor"]
    capital = protocol["capital_execution_and_costs"]
    if (
        protocol.get("protocol_id") != "futures_v38_moex_margin_risk_governor_v1"
        or protocol.get("status")
        != "predeclared_before_historical_margin_values_or_v38_outcomes"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or parent["protocol_sha256"] != v27.CONFIG_SHA256
        or parent["implementation_sha256"] != v12.sha256_file(Path(v27.__file__))
        or parent["metrics_sha256"]
        != "5fc1f271acf8f9df711006bca24e6bc40425bf097c21e989eb0296baeb0e7654"
        or source["archive_protocol_sha256"] != SOURCE_CONFIG_SHA256
        or source["archive_implementation_sha256"]
        != v12.sha256_file(Path(rms_source.__file__))
        or source["manifest_sha256"] != SOURCE_MANIFEST_SHA256
        or source["audit_sha256"] != SOURCE_AUDIT_SHA256
        or source["limits"]["sha256"] != SOURCE_LIMITS_SHA256
        or int(source["limits"]["rows"]) != SOURCE_LIMITS_ROWS
        or dict(protocol["universe"]["source_assetcode_mapping"]) != ASSET_MAPPING
        or int(protocol["information_set"]["maximum_current_row_age_calendar_days"])
        != MAXIMUM_SOURCE_AGE_DAYS
        or governor["source_field"] != "mr1"
        or governor["threshold"] != "exact_positive_change_above_zero"
        or governor["threshold_fit"] != "none_structural_zero_change"
        or float(governor["admitted_scale"]) != 1.0
        or float(governor["cash_scale"]) != 0.0
        or governor["scale_can_increase_parent_risk"] is not False
        or governor["global_cross_asset_cash_switch"] is not False
        or capital["inherited_byte_identical_from_V27"] is not True
        or float(capital["target_weight_multiplier_after_all_governors"])
        != v15.LEVERAGE_MULTIPLIER
        or float(capital["maximum_gross_notional_multiple"]) != v15.MAXIMUM_GROSS
        or float(capital["initial_margin_buffer_multiple"])
        != v15.MARGIN_BUFFER_MULTIPLIER
    ):
        raise ValueError("sealed V38 protocol invariants were weakened")
    parent_scenarios = v12._scenario_settings(v27.load_protocol())
    declared_scenarios = {
        name: {
            "slippage_ticks": int(values["slippage_ticks_per_leg"]),
            "fee_multiplier": float(values["conservative_fee_multiplier"]),
        }
        for name, values in capital["scenarios"].items()
    }
    if declared_scenarios != parent_scenarios:
        raise ValueError("V38 cost scenarios drifted from frozen V27")
    return protocol


def verify_margin_risk_source(protocol: dict[str, Any]) -> MarginRiskVerification:
    """Replay the source audit and admit only the sealed target-free MR1 columns."""
    root = SOURCE_ROOT.resolve()
    data_root = (PROJECT_ROOT / "data").resolve()
    if not root.is_relative_to(data_root) or not root.is_dir():
        raise ValueError("V38 MOEX RMS source path escapes or is missing")
    manifest_path = root / "manifest.json"
    audit_path = root / "audit.json"
    limits_path = root / str(protocol["source"]["limits"]["path"])
    replay_checks = rms_source.audit(root)
    stored_audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    allowed = list(protocol["source"]["limits"]["allowed_columns"])
    frame = pd.read_parquet(limits_path, columns=allowed)
    frame["tradedate"] = pd.to_datetime(frame["tradedate"], errors="raise").dt.normalize()
    frame["archive_query_date"] = pd.to_datetime(
        frame["archive_query_date"], errors="raise"
    ).dt.normalize()
    frame["available_at_utc"] = pd.to_datetime(
        frame["available_at_utc"], errors="raise", utc=True
    )
    frame["retrieved_at_utc"] = pd.to_datetime(
        frame["retrieved_at_utc"], errors="raise", utc=True
    )
    frame["mr1"] = pd.to_numeric(frame["mr1"], errors="raise").astype(float)
    selected = frame.loc[frame["assetcode"].isin(ASSET_MAPPING.values())].copy()
    checks = {
        "source_config_exact": manifest["config_sha256"] == SOURCE_CONFIG_SHA256,
        "source_implementation_exact": manifest["implementation_sha256"]
        == v12.sha256_file(Path(rms_source.__file__)),
        "source_manifest_exact": v12.sha256_file(manifest_path) == SOURCE_MANIFEST_SHA256,
        "source_audit_exact": v12.sha256_file(audit_path) == SOURCE_AUDIT_SHA256,
        "source_limits_exact": len(frame) == SOURCE_LIMITS_ROWS
        and v12.sha256_file(limits_path) == SOURCE_LIMITS_SHA256,
        "source_replay_all_true": all(replay_checks.values())
        and stored_audit.get("all_true") is True
        and all(stored_audit.get("checks", {}).values()),
        "source_target_free": manifest["contains_returns_targets_predictions_or_pnl"]
        is False,
        "source_selected_assets_complete": set(selected["assetcode"].unique())
        == set(ASSET_MAPPING.values()),
        "source_mr1_finite_nonnegative": bool(
            len(selected)
            and np.isfinite(selected["mr1"]).all()
            and selected["mr1"].ge(0.0).all()
        ),
        "source_pre2026_only": bool(
            selected["tradedate"].lt(v12.PROTECTED_FROM).all()
            and selected["archive_query_date"].lt(v12.PROTECTED_FROM).all()
            and selected["available_at_utc"].lt(pd.Timestamp("2026-01-01T00:00:00Z")).all()
        ),
        "source_original_intraday_key_unique": not selected.duplicated(
            ["tradedate", "assetcode", "updatetime"]
        ).any(),
    }
    if not all(checks.values()):
        raise ValueError(f"V38 MOEX RMS source verification failed: {checks}")
    return MarginRiskVerification(
        frame=selected.sort_values(
            ["assetcode", "available_at_utc", "tradedate", "updatetime"],
            kind="mergesort",
            ignore_index=True,
        ),
        checks=checks,
        manifest_sha256=v12.sha256_file(manifest_path),
        audit_sha256=v12.sha256_file(audit_path),
    )


def apply_margin_risk_governor(
    parent_weights: pd.DataFrame, source: MarginRiskVerification
) -> MarginRiskGovernorBuild:
    """Set an asset to cash after an exact positive week-over-week MR1 change."""
    required = {"decision_date", "asset", "target_weight", "provenance"}
    if missing := required - set(parent_weights.columns):
        raise ValueError(f"V38 parent weights lack columns: {sorted(missing)}")
    weights = parent_weights.copy()
    weights["decision_date"] = pd.to_datetime(
        weights["decision_date"], errors="raise"
    ).dt.normalize()
    if (
        weights.duplicated(["decision_date", "asset"]).any()
        or set(weights["asset"].unique()) != set(v12.ASSETS)
        or weights.groupby("decision_date")["asset"].nunique().ne(len(v12.ASSETS)).any()
    ):
        raise ValueError("V38 parent weekly snapshots are incomplete")
    decisions = weights.loc[:, ["decision_date", "asset"]].copy()
    decisions["source_assetcode"] = decisions["asset"].map(ASSET_MAPPING)
    decisions["decision_at"] = (
        decisions["decision_date"].dt.tz_localize(v15.MOSCOW_TIMEZONE)
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).dt.tz_convert("UTC")

    selected_rows: list[dict[str, Any]] = []
    for row in decisions.itertuples(index=False):
        eligible = source.frame.loc[
            source.frame["assetcode"].eq(row.source_assetcode)
            & source.frame["available_at_utc"].le(row.decision_at)
            & source.frame["tradedate"].le(row.decision_date)
        ]
        selected_rows.append(
            {
                "decision_date": row.decision_date,
                "asset": row.asset,
                "source_assetcode": row.source_assetcode,
                "decision_at": row.decision_at,
                "source_tradedate": eligible.iloc[-1]["tradedate"] if len(eligible) else pd.NaT,
                "source_available_at": (
                    eligible.iloc[-1]["available_at_utc"] if len(eligible) else pd.NaT
                ),
                "source_updatetime": eligible.iloc[-1]["updatetime"] if len(eligible) else None,
                "mr1": float(eligible.iloc[-1]["mr1"]) if len(eligible) else np.nan,
            }
        )
    governor = pd.DataFrame(selected_rows).sort_values(
        ["asset", "decision_date"], kind="mergesort", ignore_index=True
    )
    governor["source_age_calendar_days"] = (
        governor["decision_date"] - governor["source_tradedate"]
    ).dt.days
    governor["current_fresh"] = (
        governor["source_available_at"].notna()
        & governor["source_available_at"].le(governor["decision_at"])
        & governor["source_tradedate"].le(governor["decision_date"])
        & governor["source_age_calendar_days"].between(
            0, MAXIMUM_SOURCE_AGE_DAYS, inclusive="both"
        )
    )
    grouped = governor.groupby("asset", sort=False)
    governor["previous_decision_date"] = grouped["decision_date"].shift(1)
    governor["previous_mr1"] = grouped["mr1"].shift(1)
    governor["previous_source_tradedate"] = grouped["source_tradedate"].shift(1)
    governor["previous_source_available_at"] = grouped["source_available_at"].shift(1)
    governor["previous_fresh"] = grouped["current_fresh"].shift(
        1, fill_value=False
    ).astype(bool)
    complete = governor["current_fresh"] & governor["previous_fresh"]
    governor["mr1_change"] = governor["mr1"] - governor["previous_mr1"]
    governor["margin_risk_state"] = "cash_missing_or_stale"
    governor.loc[complete & governor["mr1_change"].le(0.0), "margin_risk_state"] = (
        "pass_nonincrease"
    )
    governor.loc[complete & governor["mr1_change"].gt(0.0), "margin_risk_state"] = (
        "cash_mr1_increase"
    )
    governor["margin_risk_scale"] = governor["margin_risk_state"].eq(
        "pass_nonincrease"
    ).astype(float)

    governed = weights.merge(
        governor,
        on=["decision_date", "asset"],
        how="left",
        validate="one_to_one",
    )
    governed["pre_margin_risk_target_weight"] = pd.to_numeric(
        governed["target_weight"], errors="raise"
    ).astype(float)
    governed["target_weight"] = (
        governed["pre_margin_risk_target_weight"] * governed["margin_risk_scale"]
    )
    governed["provenance"] = governed["provenance"].astype("string") + np.select(
        [
            governed["margin_risk_state"].eq("pass_nonincrease"),
            governed["margin_risk_state"].eq("cash_mr1_increase"),
        ],
        ["|moex_mr1_nonincrease_pass", "|moex_mr1_increase_cash"],
        default="|moex_mr1_missing_or_stale_cash",
    )
    oos = governed["decision_date"].between(v12.OOS_START, v12.OOS_END)
    checks = {
        "governor_complete_four_asset_snapshots": governed.groupby("decision_date")[
            "asset"
        ]
        .nunique()
        .eq(len(v12.ASSETS))
        .all(),
        "governor_source_not_after_decision": bool(
            governor.loc[governor["source_available_at"].notna(), "source_available_at"]
            .le(governor.loc[governor["source_available_at"].notna(), "decision_at"])
            .all()
        ),
        "governor_source_tradedate_not_after_decision": bool(
            governor.loc[governor["source_tradedate"].notna(), "source_tradedate"]
            .le(governor.loc[governor["source_tradedate"].notna(), "decision_date"])
            .all()
        ),
        "governor_previous_decision_strictly_earlier": bool(
            governor.loc[governor["previous_decision_date"].notna(), "previous_decision_date"]
            .lt(governor.loc[governor["previous_decision_date"].notna(), "decision_date"])
            .all()
        ),
        "governor_scale_set_exact": set(governed["margin_risk_scale"].unique())
        <= {0.0, 1.0},
        "governor_never_increases_parent_risk": bool(
            governed["target_weight"]
            .abs()
            .le(governed["pre_margin_risk_target_weight"].abs() + 1e-12)
            .all()
        ),
        "oos_has_positive_mr1_change": bool(
            (oos & governed["margin_risk_state"].eq("cash_mr1_increase")).any()
        ),
        "oos_nonzero_parent_target_reduced_by_mr1_increase": bool(
            (
                oos
                & governed["margin_risk_state"].eq("cash_mr1_increase")
                & governed["pre_margin_risk_target_weight"].abs().gt(1e-12)
            ).any()
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"V38 margin-risk governor invariant failure: {checks}")
    return MarginRiskGovernorBuild(
        weights=governed.sort_values(
            ["decision_date", "asset"], kind="mergesort", ignore_index=True
        ),
        governor=governor.sort_values(
            ["decision_date", "asset"], kind="mergesort", ignore_index=True
        ),
        checks=checks,
    )


def _parent_metrics(protocol: dict[str, Any]) -> dict[str, Any]:
    run = (PROJECT_ROOT / protocol["parent_v27"]["canonical_run"]).resolve()
    path = run / "metrics.json"
    identity_path = run / "identity.json"
    if (
        v12.sha256_file(path) != protocol["parent_v27"]["metrics_sha256"]
        or v12.sha256_file(identity_path) != protocol["parent_v27"]["identity_sha256"]
    ):
        raise ValueError("V38 frozen V27 canonical parent identity drift")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _promotion(
    results: dict[str, dict[str, Any]], checks: dict[str, bool], parent: dict[str, Any]
) -> dict[str, Any]:
    primary = results["primary"]["combined"]
    parent_scenarios = parent["scenarios"]
    conditions = {
        "all_identity_source_temporal_and_governor_checks_true": all(checks.values()),
        "at_least_one_oos_positive_mr1_change_state": checks[
            "oos_has_positive_mr1_change"
        ],
        "at_least_one_nonzero_parent_target_reduced": checks[
            "oos_nonzero_parent_target_reduced_by_mr1_increase"
        ],
        "zero_critical_failures_and_zero_unresolved_halts": all(
            int(value["futures_only"]["critical_failure_count"]) == 0
            and int(value["futures_only"]["unresolved_halt_count"]) == 0
            for value in results.values()
        ),
        "all_scenarios_combined_cagr_at_least_0_20": all(
            float(value["combined"]["cagr"]) >= 0.20 for value in results.values()
        ),
        "all_scenarios_mdd_not_worse_than_frozen_v27": all(
            float(results[name]["combined"]["maximum_drawdown"])
            <= float(parent_scenarios[name]["combined"]["maximum_drawdown"]) + 1e-12
            for name in results
        ),
        "primary_sharpe_at_least_frozen_v27": float(primary["sharpe"])
        >= float(parent_scenarios["primary"]["combined"]["sharpe"]),
        "primary_worst_year_not_worse_than_frozen_v27": float(primary["worst_year"])
        >= float(parent_scenarios["primary"]["combined"]["worst_year"]),
        "primary_positive_years_at_least_4_of_5": int(primary["positive_years"]) >= 4
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
        "verdict": "GO_TO_NEW_FORWARD_CONFIRMATION" if passed else "NO_GO",
        "live_trading_allowed": False,
        "independent_confirmation_required": True,
    }


def run_experiment(output_root: Path) -> Path:
    """Execute the single immutable V38 adaptive-development run."""
    protocol = load_protocol()
    v27_protocol = v27.load_protocol()
    v26_protocol = v26.load_protocol()
    parent_metrics = _parent_metrics(protocol)
    verified = v27.verify_inputs(v27_protocol)
    stlfsi = v25.verify_stlfsi_bundle(v26_protocol, verified)
    key_rate = v27.verify_key_rate_bundle(v27_protocol, verified)
    margin_source = verify_margin_risk_source(protocol)
    panel = pd.read_parquet(
        verified.paths["panel"], columns=v26_protocol["inputs"]["panel"]["allowed_columns"]
    )
    active = pd.read_parquet(
        verified.paths["active_contract_map"],
        columns=v26_protocol["inputs"]["active_contract_map"]["allowed_columns"],
    )
    observations = pd.read_parquet(
        verified.paths["contract_observations"],
        columns=v26_protocol["inputs"]["contract_observations"]["allowed_columns"],
    )
    specs = pd.read_parquet(
        verified.paths["spec_proxy"],
        columns=v26_protocol["inputs"]["spec_proxy"]["allowed_columns"],
    )
    ruonia_frame = pd.read_parquet(
        verified.paths["cbr_panel"],
        columns=v26_protocol["inputs"]["cbr_panel"]["allowed_columns"],
        filters=[("series_id", "==", "ruonia")],
    )
    ruonia = v15.verify_ruonia(ruonia_frame)
    checks = {
        **verified.checks,
        **stlfsi.checks,
        **key_rate.checks,
        **margin_source.checks,
        **ruonia.checks,
        "v38_protocol_seal": v12.sha256_file(CONFIG_PATH) == CONFIG_SHA256,
    }
    scores = v12.build_trend_scores(panel)
    weekly_v12 = v12.build_weekly_weights(panel, scores)
    governed_v25 = v25.apply_weekly_governor(weekly_v12, stlfsi)
    checks.update(governed_v25.checks)
    monetary_v27 = v27.apply_monetary_governor(governed_v25.weights, key_rate)
    checks.update(monetary_v27.checks)
    margin_v38 = apply_margin_risk_governor(monetary_v27.weights, margin_source)
    checks.update(margin_v38.checks)
    levered = v26.build_levered_governed_weights(margin_v38.weights)
    target_build = v26.build_execution_targets(margin_v38.weights, active)
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
        raise ValueError(f"V38 pre-execution invariant failure: {checks}")

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
    collateral_outputs: dict[str, v15.CollateralEvaluation] = {}
    scenario_results: dict[str, dict[str, Any]] = {}
    for name, settings in v12._scenario_settings(v27_protocol).items():
        result = v15.run_levered_portfolio_ledger(
            execution_market,
            target_build.targets,
            v26.CapacityAwareLeveredLedgerConfig(
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name], collateral_outputs[name] = v15._scenario_payload(
            result, execution_market, settings, ruonia
        )

    oos_governor = margin_v38.governor.loc[
        margin_v38.governor["decision_date"].between(v12.OOS_START, v12.OOS_END)
    ]
    oos_weights = margin_v38.weights.loc[
        margin_v38.weights["decision_date"].between(v12.OOS_START, v12.OOS_END)
    ]
    state_counts = oos_governor["margin_risk_state"].value_counts()
    counts = {
        "source_limits_rows": len(margin_source.frame),
        "source_selected_assets": int(margin_source.frame["assetcode"].nunique()),
        "all_weekly_asset_states": len(margin_v38.governor),
        "oos_weekly_asset_states": len(oos_governor),
        "oos_pass_nonincrease": int(state_counts.get("pass_nonincrease", 0)),
        "oos_cash_mr1_increase": int(state_counts.get("cash_mr1_increase", 0)),
        "oos_cash_missing_or_stale": int(state_counts.get("cash_missing_or_stale", 0)),
        "oos_nonzero_parent_targets_reduced_on_increase": int(
            (
                oos_weights["margin_risk_state"].eq("cash_mr1_increase")
                & oos_weights["pre_margin_risk_target_weight"].abs().gt(1e-12)
            ).sum()
        ),
        "mapped_target_rows": len(target_build.targets),
        "nonzero_targets": nonzero_targets,
        "covered_nonzero_targets": covered_nonzero_targets,
    }
    promotion = _promotion(scenario_results, checks, parent_metrics)
    comparison = {
        name: {
            metric: float(scenario_results[name]["combined"][metric])
            - float(parent_metrics["scenarios"][name]["combined"][metric])
            for metric in ("total_return", "cagr", "sharpe", "maximum_drawdown", "worst_year")
        }
        for name in scenario_results
    }
    identity = {
        "protocol_sha256": CONFIG_SHA256,
        "parent_v27_protocol_sha256": v27.CONFIG_SHA256,
        "parent_v27_metrics_sha256": protocol["parent_v27"]["metrics_sha256"],
        "source_config_sha256": SOURCE_CONFIG_SHA256,
        "source_manifest_sha256": margin_source.manifest_sha256,
        "source_audit_sha256": margin_source.audit_sha256,
        "source_limits_sha256": SOURCE_LIMITS_SHA256,
        "code_sha256": {
            "v38_implementation": v12.sha256_file(Path(__file__)),
            "v27_parent": v12.sha256_file(Path(v27.__file__)),
            "rms_source": v12.sha256_file(Path(rms_source.__file__)),
        },
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
        "identity": identity,
        "counts": counts,
        "scenarios": scenario_results,
        "comparison_to_v27": comparison,
        "promotion": promotion,
        "limitations": {
            "same_period_adaptive_development": True,
            "broker_exact": False,
            "forward_confirmation_required": True,
        },
    }

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v38_moex_margin_risk_governor_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V38 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        v12._write_parquet(temporary / "scores.parquet", scores)
        v12._write_parquet(temporary / "weekly_v12_weights.parquet", weekly_v12)
        v12._write_parquet(
            temporary / "weekly_v25_governed_weights.parquet", governed_v25.weights
        )
        v12._write_parquet(
            temporary / "weekly_v27_monetary_weights.parquet", monetary_v27.weights
        )
        v12._write_parquet(
            temporary / "weekly_v38_margin_governed_weights.parquet", margin_v38.weights
        )
        v12._write_parquet(temporary / "weekly_v38_levered_weights.parquet", levered)
        v12._write_parquet(temporary / "margin_risk_governor.parquet", margin_v38.governor)
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
        artifacts: dict[str, Any] = {}
        for path in sorted(temporary.iterdir()):
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
        (temporary / "identity.json").write_text(
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
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
