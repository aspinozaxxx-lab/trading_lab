"""V30 development: equal trend/carry/relative sleeves with causal risk restoration."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v13_trend_carry_confirmation as v13
from market_lab import futures_v26_stlfsi_levered_ruonia_capacity as v26
from market_lab import futures_v27_robustness as robustness
from market_lab import futures_v29_risk_first_roll as v29
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult

PROJECT_ROOT: Final[Path] = v12.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v30_three_sleeve_risk_restoration.yaml"
)
ASSETS: Final[tuple[str, ...]] = v12.ASSETS
VALIDATION_START: Final[pd.Timestamp] = pd.Timestamp("2013-01-01")
VALIDATION_END: Final[pd.Timestamp] = pd.Timestamp("2017-12-01")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2018-01-01")
EXPECTED_PREDECESSOR: Final[pd.Timestamp] = pd.Timestamp("2012-12-28")
FINAL_TARGET_VOLATILITY: Final[float] = 0.20
MAXIMUM_RISK_MULTIPLIER: Final[float] = 2.0
COMPONENT_WEIGHT: Final[float] = 1.0 / 3.0
BOOTSTRAP_BLOCKS: Final[tuple[int, ...]] = (5, 21, 63)
BOOTSTRAP_REPLICATIONS: Final[int] = 20_000
ROLLING_WINDOW_SESSIONS: Final[int] = 252
FORBIDDEN_OUTCOME_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "return",
        "returns",
        "target",
        "label",
        "signal",
        "pnl",
        "equity",
        "ending_cash",
        "combined_ending_equity",
    }
)


@dataclass(frozen=True, slots=True)
class V30Protocol:
    """Verified development protocol and resolved byte-pinned inputs."""

    config_path: Path
    config_sha256: str
    payload: dict[str, Any]
    paths: dict[str, Path]
    dependency_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class VerifiedInputs:
    """Outcome-free source identity, schema and temporal proof."""

    paths: dict[str, Path]
    checks: dict[str, bool]
    metadata: dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class SignalBuild:
    """Three bounded causal components and their equal-weight composite."""

    scores: pd.DataFrame
    components: pd.DataFrame
    checks: dict[str, bool]
    counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class TargetBuild:
    """Unscaled, risk-restored and hard-2x mapped next-open targets."""

    weekly_weights: pd.DataFrame
    risk_audit: pd.DataFrame
    unscaled_targets: pd.DataFrame
    restored_targets: pd.DataFrame
    hard_2x_targets: pd.DataFrame
    decision_audit: pd.DataFrame
    weekly_decisions: int
    roll_decisions: int
    checks: dict[str, bool]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"V30 {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"V30 protocol sidecar is missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _manifest_payload_sha(manifest: Mapping[str, Any]) -> str:
    core = {key: value for key, value in manifest.items() if key != "manifest_payload_sha256"}
    return hashlib.sha256(_canonical_json(core)).hexdigest()


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> V30Protocol:
    """Verify the selected development formula and every immutable dependency."""
    path = config_path.resolve()
    actual_sha = v12.sha256_file(path)
    if _sidecar_sha(path) != actual_sha:
        raise ValueError("V30 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("V30 protocol must be a YAML object")
    development = _mapping(payload.get("development_selection"), "development selection")
    signal = _mapping(payload.get("signal"), "signal")
    restoration = _mapping(payload.get("risk_restoration"), "risk restoration")
    execution = _mapping(payload.get("execution"), "execution")
    validation = _mapping(payload.get("validation"), "validation")
    if (
        payload.get("protocol_id")
        != "futures_v30_three_sleeve_risk_restoration_v1"
        or payload.get("status")
        != "selected_on_open_2012_2017_before_pre2012_strategy_outcomes"
        or payload.get("research_only") is not True
        or payload.get("live_trading_allowed") is not False
        or development.get("2012_2017_outcomes_observed_before_formula_freeze") is not True
        or development.get("2008_2011_returns_or_pnl_observed") is not False
        or tuple(payload["universe"]["exact_order"]) != ASSETS
        or str(payload["dates"]["validation_start"])
        != VALIDATION_START.date().isoformat()
        or str(payload["dates"]["validation_end"]) != VALIDATION_END.date().isoformat()
        or str(payload["dates"]["protected_from"]) != PROTECTED_FROM.date().isoformat()
        or tuple(signal["component_order"])
        != ("time_series_trend", "curve_carry", "relative_trend")
        or tuple(float(value) for value in signal["component_weights"])
        != (COMPONENT_WEIGHT, COMPONENT_WEIGHT, COMPONENT_WEIGHT)
        or signal.get("relative_trend_transform")
        != "time_series_score_minus_finite_cross_asset_mean_clipped_minus1_plus1"
        or signal.get("missing_carry_policy") != "carry_sleeve_zero_only"
        or signal.get("fit_or_training") != "none"
        or signal.get("hyperparameter_search") is not False
        or float(restoration["final_expected_annual_volatility"])
        != FINAL_TARGET_VOLATILITY
        or float(restoration["maximum_multiplier"]) != MAXIMUM_RISK_MULTIPLIER
        or restoration.get("zero_or_missing_expected_volatility") != "cash"
        or restoration.get("formula")
        != "min_2x_final_target_volatility_divided_by_causal_expected_volatility"
        or execution.get("unexecutable_target_policy")
        != "risk_first_roll_then_cancel_and_clip"
        or float(execution["maximum_participation"]) != v12.MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"])
        != MAXIMUM_RISK_MULTIPLIER
        or float(execution["initial_margin_buffer_multiple"])
        != v26.v15.MARGIN_BUFFER_MULTIPLIER
        or validation.get("period_role") != "open_development_selection_not_holdout"
        or validation.get("next_unseen_period") != "2008_2011_separate_future_seal"
        or int(validation["bootstrap_replications_per_block_scenario"])
        != BOOTSTRAP_REPLICATIONS
        or tuple(int(value) for value in validation["bootstrap_block_sessions"])
        != BOOTSTRAP_BLOCKS
        or int(validation["rolling_window_sessions"]) != ROLLING_WINDOW_SESSIONS
    ):
        raise ValueError("V30 protocol invariants drifted")
    scenarios = _mapping(execution.get("cost_scenarios"), "cost scenarios")
    expected_scenarios = {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }
    observed_scenarios = {
        str(name): {
            "slippage_ticks": int(_mapping(value, str(name))["slippage_ticks"]),
            "fee_multiplier": float(_mapping(value, str(name))["fee_multiplier"]),
        }
        for name, value in scenarios.items()
    }
    if observed_scenarios != expected_scenarios:
        raise ValueError("V30 cost scenarios drifted")
    inputs = _mapping(payload.get("inputs"), "inputs")
    paths = {
        str(name): v12._resolved_input(str(_mapping(value, str(name))["path"]))
        for name, value in inputs.items()
    }
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = PROJECT_ROOT / str(relative)
        digest = str(expected).lower()
        if v12.sha256_file(dependency_path) != digest:
            raise ValueError(f"V30 implementation dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    return V30Protocol(path, actual_sha, payload, paths, dependency_hashes)


def verify_inputs(protocol: V30Protocol) -> VerifiedInputs:
    """Verify source bytes, schemas and dates before loading price values."""
    checks: dict[str, bool] = {"protocol_seal": True}
    metadata: dict[str, dict[str, Any]] = {}
    declarations = protocol.payload["inputs"]
    for name, declaration_value in declarations.items():
        declaration = _mapping(declaration_value, str(name))
        path = protocol.paths[str(name)]
        exists = path.is_file()
        checks[f"{name}_exists"] = exists
        checks[f"{name}_bytes"] = exists and path.stat().st_size == int(declaration["bytes"])
        checks[f"{name}_sha256"] = exists and v12.sha256_file(path) == declaration["sha256"]
        item: dict[str, Any] = {
            "path": declaration["path"],
            "bytes": path.stat().st_size if exists else None,
            "sha256": v12.sha256_file(path) if exists else None,
        }
        if exists and path.suffix.lower() == ".parquet":
            parquet = pq.ParquetFile(path)
            columns = parquet.schema_arrow.names
            item.update({"rows": parquet.metadata.num_rows, "columns": columns})
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
            checks[f"{name}_read_schema"] = set(declaration["read_columns"]) <= set(columns)
            checks[f"{name}_source_schema_outcome_free"] = not bool(
                {str(column).lower() for column in columns} & FORBIDDEN_OUTCOME_COLUMNS
            )
        metadata[str(name)] = item
    if not all(checks.values()):
        raise ValueError(f"V30 byte/schema preflight failed: {checks}")
    manifest = json.loads(
        protocol.paths["market_manifest"].read_text(encoding="utf-8-sig")
    )
    checks.update(
        {
            "market_manifest_payload": _manifest_payload_sha(manifest)
            == manifest["manifest_payload_sha256"],
            "market_manifest_sidecar": protocol.paths["market_manifest_sidecar"]
            .read_text(encoding="utf-8-sig")
            .split()[0]
            == declarations["market_manifest"]["sha256"],
            "market_source_identity": manifest.get("source_id")
            == "moex-pre2018-core4-causal-derived-2012-2017-v3",
            "market_source_outcome_free": manifest["temporal_semantics"].get(
                "contains_returns_targets_labels_or_pnl"
            )
            is False,
            "market_source_causal_forward_adjustment": manifest[
                "temporal_semantics"
            ].get("causal_forward_adjustment")
            is True,
            "market_source_no_return_bridge": manifest["temporal_semantics"].get(
                "missing_return_bridge_created"
            )
            is False,
            "market_source_bounds": manifest["temporal_semantics"].get(
                "minimum_session"
            )
            == "2012-01-03"
            and manifest["temporal_semantics"].get("maximum_session") == "2017-12-01",
            "market_source_unresolved_zero": int(
                manifest["quality_gates"]["unresolved_roll_count"]
            )
            == 0
            and int(manifest["quality_gates"]["unresolved_exit_count"]) == 0,
            "market_source_roll_counts": manifest["quality_gates"]["successful_rolls"]
            == {"BR": 70, "MIX": 23, "RI": 23, "SI": 22},
        }
    )
    artifact_inputs = {
        "panel": "market_panel",
        "active_contract_map": "active_contract_map",
        "contract_observations": "contract_observations",
        "spec_proxy": "spec_proxy",
        "audit": "market_audit",
    }
    for artifact_name, input_name in artifact_inputs.items():
        artifact = manifest["artifacts"][artifact_name]
        declaration = declarations[input_name]
        checks[f"manifest_{artifact_name}_identity"] = (
            artifact["sha256"] == declaration["sha256"]
            and int(artifact["bytes"]) == int(declaration["bytes"])
        )
    date_specs = {
        "market_panel": "trade_date",
        "active_contract_map": "effective_date",
        "contract_observations": "trade_date",
        "spec_proxy": "session_date",
    }
    for name, column in date_specs.items():
        dates = pd.to_datetime(
            pd.read_parquet(protocol.paths[name], columns=[column])[column],
            errors="raise",
        ).dt.normalize()
        checks[f"{name}_date_min"] = dates.min() == pd.Timestamp("2012-01-03")
        checks[f"{name}_date_max"] = dates.max() == VALIDATION_END
        checks[f"{name}_protected"] = bool(dates.lt(PROTECTED_FROM).all())
        metadata[name]["minimum_timestamp"] = dates.min().date().isoformat()
        metadata[name]["maximum_timestamp"] = dates.max().date().isoformat()
    active_dates = pd.read_parquet(
        protocol.paths["active_contract_map"],
        columns=["decision_date", "effective_date", "observed_through"],
    )
    decision = pd.to_datetime(active_dates["decision_date"], errors="coerce")
    effective = pd.to_datetime(active_dates["effective_date"], errors="raise")
    observed = pd.to_datetime(active_dates["observed_through"], errors="coerce")
    checks["active_decision_strictly_before_effective"] = bool(
        decision.dropna().lt(effective.loc[decision.notna()]).all()
    )
    checks["active_observed_not_after_decision"] = bool(
        observed.loc[decision.notna()].le(decision.loc[decision.notna()]).all()
    )
    if not all(checks.values()):
        raise ValueError(f"V30 manifest/temporal preflight failed: {checks}")
    return VerifiedInputs(protocol.paths, checks, metadata)


def compose_signal_components(
    trend_scores: pd.DataFrame,
    curve_frame: pd.DataFrame,
) -> SignalBuild:
    """Combine equal bounded trend, carry and relative-trend components."""
    required_trend = {"decision_date", "asset", "candidate_score"}
    required_curve = {"trade_date", "asset", "roll_yield", "carry_available"}
    if missing := required_trend - set(trend_scores.columns):
        raise ValueError(f"V30 trend frame lacks columns: {sorted(missing)}")
    if missing := required_curve - set(curve_frame.columns):
        raise ValueError(f"V30 curve frame lacks columns: {sorted(missing)}")
    trend = trend_scores.copy()
    trend["decision_date"] = pd.to_datetime(
        trend["decision_date"], errors="raise"
    ).dt.normalize()
    trend["asset"] = trend["asset"].map(v12._asset_code)
    trend["time_series_trend"] = pd.to_numeric(
        trend["candidate_score"], errors="coerce"
    ).astype(float)
    finite_trend = trend["time_series_trend"].notna() & np.isfinite(
        trend["time_series_trend"]
    )
    finite_count = trend["time_series_trend"].where(finite_trend).groupby(
        trend["decision_date"]
    ).transform("count")
    cross_mean = trend["time_series_trend"].where(finite_trend).groupby(
        trend["decision_date"]
    ).transform("mean")
    relative = (trend["time_series_trend"] - cross_mean).clip(-1.0, 1.0)
    relative = relative.where(finite_trend & finite_count.ge(2), 0.0)
    relative = relative.where(finite_trend)
    trend["relative_trend"] = relative
    curve = curve_frame.loc[:, list(required_curve)].copy()
    curve["trade_date"] = pd.to_datetime(curve["trade_date"], errors="raise").dt.normalize()
    curve["asset"] = curve["asset"].map(v12._asset_code)
    curve["roll_yield"] = pd.to_numeric(curve["roll_yield"], errors="coerce")
    available = curve["carry_available"].fillna(False).astype(bool)
    curve["curve_carry"] = np.sign(curve["roll_yield"]).where(available, 0.0)
    curve = curve.rename(columns={"trade_date": "decision_date"})
    merged = trend.merge(
        curve.loc[
            :, ["decision_date", "asset", "roll_yield", "carry_available", "curve_carry"]
        ],
        on=["decision_date", "asset"],
        how="left",
        validate="one_to_one",
    )
    merged["carry_available"] = merged["carry_available"].fillna(False).astype(bool)
    merged["curve_carry"] = merged["curve_carry"].fillna(0.0).astype(float)
    merged["composite_score"] = (
        merged["time_series_trend"]
        + merged["curve_carry"]
        + merged["relative_trend"]
    ) * COMPONENT_WEIGHT
    merged.loc[~finite_trend.to_numpy(dtype=bool), "composite_score"] = np.nan
    component_columns = [
        "decision_date",
        "asset",
        "time_series_trend",
        "curve_carry",
        "relative_trend",
        "composite_score",
        "roll_yield",
        "carry_available",
    ]
    components = merged.loc[:, component_columns].sort_values(
        ["decision_date", "asset"], kind="mergesort", ignore_index=True
    )
    finite_components = components.loc[components["composite_score"].notna()]
    checks = {
        "complete_unique_date_asset_keys": not components.duplicated(
            ["decision_date", "asset"]
        ).any(),
        "exact_asset_universe": set(components["asset"].unique()) == set(ASSETS),
        "trend_component_bounded": bool(
            finite_components["time_series_trend"].abs().le(1.0 + 1e-12).all()
        ),
        "carry_component_is_sign_or_zero": set(
            finite_components["curve_carry"].unique()
        )
        <= {-1.0, 0.0, 1.0},
        "relative_component_bounded": bool(
            finite_components["relative_trend"].abs().le(1.0 + 1e-12).all()
        ),
        "composite_component_bounded": bool(
            finite_components["composite_score"].abs().le(1.0 + 1e-12).all()
        ),
        "missing_carry_affects_only_carry_sleeve": bool(
            components.loc[~components["carry_available"], "curve_carry"].eq(0.0).all()
        ),
        "no_protected_dates": bool(components["decision_date"].lt(PROTECTED_FROM).all()),
    }
    if not all(checks.values()):
        raise ValueError(f"V30 component construction failed: {checks}")
    scores = trend_scores.drop(columns=["candidate_score"]).merge(
        components.loc[:, ["decision_date", "asset", "composite_score"]],
        on=["decision_date", "asset"],
        how="left",
        validate="one_to_one",
    )
    scores = scores.rename(columns={"composite_score": "candidate_score"})
    counts = {
        "component_rows": len(components),
        "finite_composite_rows": int(components["composite_score"].notna().sum()),
        "carry_available_rows": int(components["carry_available"].sum()),
        "carry_sleep_rows": int((~components["carry_available"]).sum()),
        "nonzero_composite_rows": int(components["composite_score"].abs().gt(1e-12).sum()),
    }
    return SignalBuild(scores, components, checks, counts)


def build_three_sleeve_scores(panel: pd.DataFrame) -> SignalBuild:
    """Verify the same-close curve and build the V30 composite without outcomes."""
    curve = v13.verify_curve_panel(panel)
    trend = v12.build_trend_scores(panel)
    built = compose_signal_components(trend, curve.frame)
    return SignalBuild(
        built.scores,
        built.components,
        {**curve.checks, **built.checks},
        built.counts,
    )


def risk_restoration_multiplier(expected_volatility: pd.Series) -> pd.Series:
    """Restore final expected volatility toward 20%, never above 2x."""
    values = pd.to_numeric(expected_volatility, errors="coerce").astype(float)
    valid = values.notna() & np.isfinite(values) & values.gt(0.0)
    output = pd.Series(0.0, index=values.index, dtype=float)
    output.loc[valid] = np.minimum(
        MAXIMUM_RISK_MULTIPLIER,
        FINAL_TARGET_VOLATILITY / values.loc[valid],
    )
    return output


def build_targets(
    panel: pd.DataFrame,
    scores: pd.DataFrame,
    active_map: pd.DataFrame,
) -> TargetBuild:
    """Map 1x weights first, then apply the last known causal risk multiplier."""
    weekly = v12.build_weekly_weights(panel, scores)
    base = v12.build_execution_targets(
        weekly,
        active_map,
        oos_start=VALIDATION_START,
        oos_end=VALIDATION_END,
    )
    risk = weekly.loc[
        :, ["decision_date", "gross", "expected_annual_volatility"]
    ].drop_duplicates()
    risk = risk.sort_values("decision_date", kind="mergesort", ignore_index=True)
    risk["risk_multiplier"] = risk_restoration_multiplier(
        risk["expected_annual_volatility"]
    )
    risk["restored_expected_annual_volatility"] = (
        risk["expected_annual_volatility"] * risk["risk_multiplier"]
    )
    mapped = base.targets.sort_values("decision_date", kind="mergesort").copy()
    restored = pd.merge_asof(
        mapped,
        risk.loc[:, ["decision_date", "risk_multiplier"]],
        on="decision_date",
        direction="backward",
        allow_exact_matches=True,
    )
    if restored["risk_multiplier"].isna().any():
        raise ValueError("V30 mapped target lacks a prior weekly risk multiplier")
    restored["pre_restoration_target_weight"] = restored["target_weight"].astype(float)
    restored["target_weight"] = (
        restored["pre_restoration_target_weight"] * restored["risk_multiplier"]
    )
    restored["provenance"] = (
        restored["provenance"].astype("string")
        + "|V30_final_vol_20pct_cap_2x_multiplier="
        + restored["risk_multiplier"].map(lambda value: f"{float(value):.12g}")
    )
    hard = base.targets.copy()
    hard["pre_restoration_target_weight"] = hard["target_weight"].astype(float)
    hard["risk_multiplier"] = MAXIMUM_RISK_MULTIPLIER
    hard["target_weight"] = hard["target_weight"].astype(float) * MAXIMUM_RISK_MULTIPLIER
    hard["provenance"] = hard["provenance"].astype("string") + "|V30_hard_2x_sensitivity"
    restored = restored.sort_values(
        ["effective_date", "asset_code"], kind="mergesort", ignore_index=True
    )
    hard = hard.sort_values(
        ["effective_date", "asset_code"], kind="mergesort", ignore_index=True
    )
    unscaled = base.targets.sort_values(
        ["effective_date", "asset_code"], kind="mergesort", ignore_index=True
    )
    restored_gross = restored.groupby("effective_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    hard_gross = hard.groupby("effective_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    checks = {
        "risk_multiplier_finite_nonnegative": bool(
            np.isfinite(risk["risk_multiplier"]).all()
            and risk["risk_multiplier"].ge(0.0).all()
        ),
        "risk_multiplier_at_most_2x": bool(
            risk["risk_multiplier"].le(MAXIMUM_RISK_MULTIPLIER + 1e-12).all()
        ),
        "restored_expected_volatility_at_most_20pct": bool(
            risk["restored_expected_annual_volatility"].le(
                FINAL_TARGET_VOLATILITY + 1e-12
            ).all()
        ),
        "restored_mapped_gross_at_most_2x": bool(
            restored_gross.le(MAXIMUM_RISK_MULTIPLIER + 1e-12).all()
        ),
        "hard_sensitivity_gross_at_most_2x": bool(
            hard_gross.le(MAXIMUM_RISK_MULTIPLIER + 1e-12).all()
        ),
        "mapped_target_dates_pre2018": bool(
            pd.to_datetime(restored["effective_date"]).lt(PROTECTED_FROM).all()
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"V30 target construction failed: {checks}")
    return TargetBuild(
        weekly,
        risk,
        unscaled,
        restored,
        hard,
        base.decision_audit,
        base.weekly_decisions,
        base.roll_decisions,
        checks,
    )


def _annual_returns(ledger: pd.DataFrame) -> dict[str, float]:
    daily = pd.to_numeric(ledger["ending_cash"], errors="raise").astype(float) / pd.to_numeric(
        ledger["starting_cash"], errors="raise"
    ).astype(float) - 1.0
    dates = pd.to_datetime(ledger["session_date"], errors="raise").dt.normalize()
    return {
        str(year): float((1.0 + daily.loc[dates.dt.year.eq(year)]).prod() - 1.0)
        for year in range(2013, 2018)
        if dates.dt.year.eq(year).any()
    }


def _scenario_metrics(
    result: FuturesPortfolioLedgerResult,
    market: pd.DataFrame,
    settings: Mapping[str, float],
) -> dict[str, Any]:
    output = v12.scenario_metrics(result, market, dict(settings))
    annual = _annual_returns(result.ledger)
    output.update(
        {
            "annual_returns": annual,
            "positive_years": int(sum(value > 0.0 for value in annual.values())),
            "worst_year": min(annual.values()) if annual else None,
        }
    )
    return output


def _daily_returns(result: FuturesPortfolioLedgerResult) -> pd.Series:
    ledger = result.ledger
    dates = pd.DatetimeIndex(
        pd.to_datetime(ledger["session_date"], errors="raise").dt.normalize()
    )
    values = (
        pd.to_numeric(ledger["ending_cash"], errors="raise").to_numpy(dtype=float)
        / pd.to_numeric(ledger["starting_cash"], errors="raise").to_numpy(dtype=float)
        - 1.0
    )
    return pd.Series(values, index=dates, name="daily_return")


def _robustness_outputs(
    main_results: Mapping[str, FuturesPortfolioLedgerResult],
    protocol: V30Protocol,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    validation = protocol.payload["validation"]
    seed_map = validation["bootstrap_seeds"]
    summaries: dict[str, Any] = {}
    bootstrap_frames: list[pd.DataFrame] = []
    rolling_frames: list[pd.DataFrame] = []
    leave_frames: list[pd.DataFrame] = []
    for scenario in ("primary", "stress"):
        returns = _daily_returns(main_results[scenario])
        rolling = robustness.rolling_windows(
            returns, window_sessions=ROLLING_WINDOW_SESSIONS
        )
        rolling.insert(0, "scenario", scenario)
        leave = robustness.leave_one_year_out(
            returns, years=(2013, 2014, 2015, 2016, 2017)
        )
        leave.insert(0, "scenario", scenario)
        scenario_bootstrap: dict[str, Any] = {}
        for block in BOOTSTRAP_BLOCKS:
            samples = robustness.circular_block_bootstrap(
                returns.to_numpy(dtype=float),
                replications=BOOTSTRAP_REPLICATIONS,
                block_sessions=block,
                seed=int(seed_map[scenario][str(block)]),
                elapsed_years=5.0,
            )
            samples.insert(0, "scenario", scenario)
            samples.insert(1, "block_sessions", block)
            bootstrap_frames.append(samples)
            scenario_bootstrap[str(block)] = robustness.summarize_bootstrap(
                samples,
                quantiles=(0.05, 0.50, 0.95),
            )
        summaries[scenario] = {
            "rolling_252": robustness.summarize_rolling(rolling),
            "leave_one_year_out": {
                str(int(row.excluded_year)): {
                    "cagr": float(row.cagr),
                    "sharpe": float(row.sharpe),
                    "maximum_drawdown": float(row.maximum_drawdown),
                }
                for row in leave.itertuples()
            },
            "bootstrap": scenario_bootstrap,
        }
        rolling_frames.append(rolling)
        leave_frames.append(leave)
    return (
        summaries,
        pd.concat(bootstrap_frames, ignore_index=True),
        pd.concat(rolling_frames, ignore_index=True),
        pd.concat(leave_frames, ignore_index=True),
    )


def assess_candidate(
    scenarios: Mapping[str, Mapping[str, Any]],
    robustness_summary: Mapping[str, Any],
    checks: Mapping[str, bool],
) -> dict[str, Any]:
    """Apply predeclared development gates without claiming independent validation."""
    main = [scenarios[name] for name in ("primary", "doubled", "stress")]
    stress_bootstrap = robustness_summary["stress"]["bootstrap"]
    minimum_joint = min(
        float(stress_bootstrap[str(block)]["probability_cagr_ge_0_20_and_mdd_le_0_30"])
        for block in BOOTSTRAP_BLOCKS
    )
    stress_leave = robustness_summary["stress"]["leave_one_year_out"]
    minimum_leave_cagr = min(float(value["cagr"]) for value in stress_leave.values())
    stress_rolling = robustness_summary["stress"]["rolling_252"]
    conditions = {
        "all_source_signal_target_and_temporal_checks_true": all(checks.values()),
        "all_main_scenarios_execution_complete": all(
            bool(value["execution_complete"]) for value in main
        ),
        "zero_main_critical_failures_and_unresolved_halts": all(
            int(value["critical_failure_count"]) == 0
            and int(value["unresolved_halt_count"]) == 0
            for value in main
        ),
        "all_main_CAGR_at_least_20pct": all(float(value["cagr"]) >= 0.20 for value in main),
        "all_main_MDD_at_most_30pct": all(
            float(value["maximum_drawdown"]) <= 0.30 for value in main
        ),
        "primary_and_stress_sharpe_at_least_1": float(scenarios["primary"]["sharpe"])
        >= 1.0
        and float(scenarios["stress"]["sharpe"]) >= 1.0,
        "primary_positive_years_at_least_4_of_5": int(
            scenarios["primary"]["positive_years"]
        )
        >= 4,
        "primary_worst_year_at_least_minus_15pct": float(
            scenarios["primary"]["worst_year"]
        )
        >= -0.15,
        "stress_worst_year_at_least_minus_20pct": float(scenarios["stress"]["worst_year"])
        >= -0.20,
        "stress_bootstrap_joint_20_30_frequency_at_least_40pct": minimum_joint >= 0.40,
        "stress_leave_one_year_out_minimum_CAGR_at_least_8pct": minimum_leave_cagr
        >= 0.08,
        "stress_rolling_positive_fraction_at_least_75pct": float(
            stress_rolling["positive_fraction"]
        )
        >= 0.75,
        "stress_rolling_maximum_window_MDD_at_most_30pct": float(
            stress_rolling["maximum_window_drawdown"]
        )
        <= 0.30,
    }
    passed = all(conditions.values())
    supports_50 = passed and all(float(value["cagr"]) >= 0.50 for value in main)
    return {
        "conditions": conditions,
        "passed": passed,
        "verdict": (
            "DEVELOPMENT_CANDIDATE_READY_FOR_SEPARATE_PRE2012_SEAL"
            if passed
            else "DEVELOPMENT_NO_GO"
        ),
        "minimum_stress_bootstrap_joint_20_30_frequency": minimum_joint,
        "minimum_stress_leave_one_year_out_CAGR": minimum_leave_cagr,
        "supports_20_percent_on_open_development": passed,
        "supports_50_percent_on_open_development": supports_50,
        "independent_confirmation": False,
        "live_trading_allowed": False,
    }


def _report_text(payload: Mapping[str, Any]) -> str:
    lines = [
        "# V30 equal trend/carry/relative sleeves with causal risk restoration",
        "",
        f"Verdict: **{payload['assessment']['verdict']}** (development only; live forbidden).",
        "",
        "The formula was selected after open 2012-2017 diagnostics. It is not an unseen result.",
        "",
        "| Scenario | CAGR | Sharpe | MDD | Positive years | Worst year | Costs RUB | Complete |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name in (
        "baseline_1x_primary",
        "primary",
        "doubled",
        "stress",
        "hard_2x_primary",
        "hard_2x_stress",
    ):
        item = payload["scenarios"][name]
        lines.append(
            f"| {name} | {item['cagr']:.4%} | {item['sharpe']:.3f} | "
            f"{item['maximum_drawdown']:.4%} | {item['positive_years']}/5 | "
            f"{item['worst_year']:.4%} | {item['total_cost']:.2f} | "
            f"{item['execution_complete']} |"
        )
    lines.extend(["", "## Primary annual returns", ""])
    for year, value in payload["scenarios"]["primary"]["annual_returns"].items():
        lines.append(f"- {year}: {value:.4%}")
    counts = payload["counts"]
    lines.extend(
        [
            "",
            "## Construction and robustness",
            "",
            f"- Weekly decisions: {counts['weekly_decisions']}; roll decisions: "
            f"{counts['roll_decisions']}.",
            f"- Nonzero mapped targets: {counts['nonzero_targets']}; covered: "
            f"{counts['covered_nonzero_targets']}.",
            f"- Mean risk multiplier: {counts['mean_risk_multiplier']:.4f}; maximum: "
            f"{counts['maximum_risk_multiplier']:.4f}.",
            f"- Minimum stress bootstrap joint 20% CAGR / 30% MDD frequency: "
            f"{payload['assessment']['minimum_stress_bootstrap_joint_20_30_frequency']:.2%}.",
            f"- Minimum stress leave-one-year-out CAGR: "
            f"{payload['assessment']['minimum_stress_leave_one_year_out_CAGR']:.2%}.",
            "",
            "The next permitted economic read is one separately sealed 2008-2011 run. "
            "Historical fees, specs, margin, spread and queue remain research proxies.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    v12._write_parquet(path, frame)


def run_experiment(
    output_root: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> Path:
    """Run one immutable canonical V30 development evaluation."""
    protocol = load_protocol(config_path)
    verified = verify_inputs(protocol)
    inputs = protocol.payload["inputs"]
    panel = pd.read_parquet(
        verified.paths["market_panel"], columns=inputs["market_panel"]["read_columns"]
    )
    active = pd.read_parquet(
        verified.paths["active_contract_map"],
        columns=inputs["active_contract_map"]["read_columns"],
    )
    observations = pd.read_parquet(
        verified.paths["contract_observations"],
        columns=inputs["contract_observations"]["read_columns"],
    )
    specs = pd.read_parquet(
        verified.paths["spec_proxy"], columns=inputs["spec_proxy"]["read_columns"]
    )
    signal = build_three_sleeve_scores(panel)
    targets = build_targets(panel, signal.scores, active)
    market = v12.build_execution_market(observations, specs)
    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < VALIDATION_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(
            predecessor, VALIDATION_END
        )
    ].copy()
    coverage = v12.execution_coverage(market, targets.restored_targets)
    checks = {
        **verified.checks,
        **signal.checks,
        **targets.checks,
        "execution_predecessor_exact": predecessor == EXPECTED_PREDECESSOR,
        "execution_sessions_exact": execution_market["session_date"].nunique() == 1225,
        "coverage_rows_match_nonzero_targets": len(coverage)
        == int(targets.restored_targets["target_weight"].abs().gt(1e-12).sum()),
        "pre2012_outcomes_read_by_V30": False,
    }
    if not all(checks.values()):
        raise ValueError(f"V30 pre-execution checks failed: {checks}")
    scenario_declarations = protocol.payload["execution"]["cost_scenarios"]
    run_specs = {
        "baseline_1x_primary": (
            targets.unscaled_targets,
            scenario_declarations["primary"],
        ),
        "primary": (targets.restored_targets, scenario_declarations["primary"]),
        "doubled": (targets.restored_targets, scenario_declarations["doubled"]),
        "stress": (targets.restored_targets, scenario_declarations["stress"]),
        "hard_2x_primary": (targets.hard_2x_targets, scenario_declarations["primary"]),
        "hard_2x_stress": (targets.hard_2x_targets, scenario_declarations["stress"]),
    }
    outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    metrics: dict[str, dict[str, Any]] = {}
    for name, (scenario_targets, settings) in run_specs.items():
        result = v29.run_risk_first_portfolio_ledger(
            execution_market,
            scenario_targets,
            v26.CapacityAwareLeveredLedgerConfig(
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
            ),
        )
        outputs[name] = result
        metrics[name] = _scenario_metrics(result, execution_market, settings)
    robustness_summary, bootstrap, rolling, leave = _robustness_outputs(
        {name: outputs[name] for name in ("primary", "stress")}, protocol
    )
    nonzero = int(targets.restored_targets["target_weight"].abs().gt(1e-12).sum())
    counts = {
        **signal.counts,
        "source_panel_rows": len(panel),
        "weekly_decisions": targets.weekly_decisions,
        "roll_decisions": targets.roll_decisions,
        "mapped_target_rows": len(targets.restored_targets),
        "nonzero_targets": nonzero,
        "covered_nonzero_targets": int(
            coverage["execution_dependencies_complete"].sum()
        ),
        "mean_risk_multiplier": float(targets.risk_audit["risk_multiplier"].mean()),
        "maximum_risk_multiplier": float(targets.risk_audit["risk_multiplier"].max()),
        "minimum_risk_multiplier": float(targets.risk_audit["risk_multiplier"].min()),
    }
    assessment = assess_candidate(metrics, robustness_summary, checks)
    identity = {
        "protocol_sha256": protocol.config_sha256,
        "market_manifest_sha256": inputs["market_manifest"]["sha256"],
        "input_sha256": {name: value["sha256"] for name, value in inputs.items()},
        "implementation_sha256": protocol.dependency_hashes,
        "development_period_outcomes_observed_before_formula_freeze": True,
        "pre2012_returns_or_pnl_observed": False,
        "contains_2018_or_later_prices_returns_targets_or_pnl": False,
    }
    payload: dict[str, Any] = {
        "protocol_id": protocol.payload["protocol_id"],
        "protocol_sha256": protocol.config_sha256,
        "research_only": True,
        "development_selection": True,
        "independent_confirmation": False,
        "live_trading_allowed": False,
        "checks": checks,
        "input_metadata": verified.metadata,
        "identity": identity,
        "counts": counts,
        "scenarios": metrics,
        "robustness": robustness_summary,
        "assessment": assessment,
        "limitations": protocol.payload["limitations"],
    }
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v30_three_sleeve_risk_{timestamp}_{protocol.config_sha256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V30 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(protocol.config_path, temporary / "resolved_protocol.yaml")
        _write_parquet(temporary / "scores.parquet", signal.scores)
        _write_parquet(temporary / "signal_components.parquet", signal.components)
        _write_parquet(temporary / "weekly_weights.parquet", targets.weekly_weights)
        _write_parquet(temporary / "risk_restoration.parquet", targets.risk_audit)
        _write_parquet(temporary / "mapped_targets_1x.parquet", targets.unscaled_targets)
        _write_parquet(
            temporary / "mapped_targets_risk_restored.parquet",
            targets.restored_targets,
        )
        _write_parquet(temporary / "mapped_targets_hard_2x.parquet", targets.hard_2x_targets)
        targets.decision_audit.to_csv(
            temporary / "decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        _write_parquet(temporary / "bootstrap.parquet", bootstrap)
        _write_parquet(temporary / "rolling_252.parquet", rolling)
        leave.to_csv(
            temporary / "leave_one_year_out.csv", index=False, encoding="utf-8-sig"
        )
        for name, result in outputs.items():
            _write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            _write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            _write_parquet(temporary / f"positions_{name}.parquet", result.positions)
        (temporary / "report.md").write_text(
            _report_text(payload), encoding="utf-8-sig"
        )
        artifacts: dict[str, Any] = {}
        for artifact_path in sorted(temporary.iterdir()):
            if artifact_path.name in {"metrics.json", "identity.json"}:
                continue
            record: dict[str, Any] = {
                "bytes": artifact_path.stat().st_size,
                "sha256": v12.sha256_file(artifact_path),
            }
            if artifact_path.suffix == ".parquet":
                record["rows"] = pq.ParquetFile(artifact_path).metadata.num_rows
            artifacts[artifact_path.name] = record
        payload["artifacts"] = artifacts
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(
                v12._json_safe(payload),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8-sig",
        )
        (temporary / "identity.json").write_text(
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    arguments = parser.parse_args(argv)
    print(run_experiment(arguments.output_root, arguments.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
