"""V31: one-shot unseen 2008-2011 temporal validation of frozen V30 economics."""

from __future__ import annotations

import argparse
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
from market_lab import futures_v30_three_sleeve_risk_restoration as v1
from market_lab import futures_v30_three_sleeve_risk_restoration_v2 as v2
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult

PROJECT_ROOT: Final[Path] = v1.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v31_pre2012_temporal_validation.yaml"
)
PROTOCOL_ID: Final[str] = "futures_v31_pre2012_temporal_validation_v1"
PARENT_CONFIG_RELATIVE: Final[str] = (
    "configs/futures_v30_three_sleeve_risk_restoration_v2.yaml"
)
PARENT_CONFIG_SHA256: Final[str] = (
    "8b41f58a17d757b56f4e88a26515416e4e519d98cad915277e1fee18a20cc2ae"
)
PARENT_MODULE_SHA256: Final[str] = (
    "20de599e5bdcace2fae4f8ea37f58cb53e5310609ec5720f2a1b42323ce6ed66"
)
PARENT_METRICS_RELATIVE: Final[str] = (
    "runs/v30_three_sleeve_risk_v2_20260901T141802Z_8b41f58a/metrics.json"
)
PARENT_METRICS_SHA256: Final[str] = (
    "e5aeb7d1af12c861af3c81003d31bcc10cafed17665547b3f302255aed4ad054"
)
PARENT_IDENTITY_RELATIVE: Final[str] = (
    "runs/v30_three_sleeve_risk_v2_20260901T141802Z_8b41f58a/identity.json"
)
PARENT_IDENTITY_SHA256: Final[str] = (
    "acc03e16e71d9209028589f92ceaf9a8954570549fde6e73cddcf51e78923448"
)

SOURCE_START: Final[pd.Timestamp] = pd.Timestamp("2008-10-08")
FIRST_COMPLETE_TREND_OBSERVATION: Final[pd.Timestamp] = pd.Timestamp("2009-10-13")
FIRST_WEEKLY_DECISION: Final[pd.Timestamp] = pd.Timestamp("2009-10-16")
VALIDATION_START: Final[pd.Timestamp] = pd.Timestamp("2009-10-19")
VALIDATION_END: Final[pd.Timestamp] = pd.Timestamp("2011-12-15")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2012-01-01")
EXPECTED_PREDECESSOR: Final[pd.Timestamp] = FIRST_WEEKLY_DECISION
MIX_FIRST_SOURCE_SESSION: Final[pd.Timestamp] = pd.Timestamp("2011-09-30")
EXPECTED_MASTER_SESSIONS: Final[int] = 781
EXPECTED_EXECUTION_SESSIONS: Final[int] = 526
EXPECTED_EVALUATION_SESSIONS: Final[int] = 525
EXPECTED_MIX_UNAVAILABLE_SESSIONS: Final[int] = 727
EVALUATION_YEARS: Final[tuple[int, ...]] = (2009, 2010, 2011)
ROLLING_WINDOW_SESSIONS: Final[int] = 252
BOOTSTRAP_BLOCKS: Final[tuple[int, ...]] = (5, 21, 63)
BOOTSTRAP_REPLICATIONS: Final[int] = 20_000
BOOTSTRAP_ELAPSED_YEARS: Final[float] = 2.162946535520921


@dataclass(frozen=True, slots=True)
class V31TargetBuild:
    """Frozen V30 targets plus an audit count for the causal late-MIX flat adapter."""

    weekly_weights: pd.DataFrame
    risk_audit: pd.DataFrame
    unscaled_targets: pd.DataFrame
    restored_targets: pd.DataFrame
    hard_2x_targets: pd.DataFrame
    decision_audit: pd.DataFrame
    weekly_decisions: int
    roll_decisions: int
    adapted_late_mix_flat_rows: int
    checks: dict[str, bool]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"V31 {label} must be a mapping")
    return value


def _normalized_dates(values: pd.Series, label: str) -> pd.Series:
    dates = pd.to_datetime(values, errors="raise")
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert("UTC").dt.tz_localize(None)
    normalized = dates.dt.normalize()
    if label == "trade_date" and normalized.isna().any():
        raise ValueError("V31 trade_date cannot be missing")
    if label in {"trade_date", "curve_observed_through"} and normalized.dropna().ge(
        PROTECTED_FROM
    ).any():
        raise ValueError(f"V31 {label} touches 2012 or later")
    return normalized


def _parent_paths() -> tuple[Path, Path, Path]:
    return (
        PROJECT_ROOT / PARENT_CONFIG_RELATIVE,
        (PROJECT_ROOT / PARENT_METRICS_RELATIVE).resolve(),
        (PROJECT_ROOT / PARENT_IDENTITY_RELATIVE).resolve(),
    )


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> v1.V30Protocol:
    """Verify the V31 seal, frozen V30 parent and exact unseen-source declarations."""
    path = config_path.resolve()
    actual_sha = v12.sha256_file(path)
    if v1._sidecar_sha(path) != actual_sha:
        raise ValueError("V31 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("V31 protocol must be a YAML object")

    boundary = _mapping(payload.get("outcome_boundary"), "outcome boundary")
    parent = _mapping(payload.get("parent_V30_D2"), "parent V30-D2")
    dates = _mapping(payload.get("dates"), "dates")
    validation = _mapping(payload.get("validation"), "validation")
    execution = _mapping(payload.get("execution"), "execution")
    if (
        payload.get("protocol_id") != PROTOCOL_ID
        or payload.get("status")
        != "sealed_unseen_pre2012_temporal_validation_before_price_read"
        or payload.get("research_only") is not True
        or payload.get("live_trading_allowed") is not False
        or boundary.get("metadata_dates_schemas_and_masks_observed_before_seal") is not True
        or boundary.get(
            "pre2012_price_values_returns_targets_equity_or_pnl_observed_before_seal"
        )
        is not False
        or boundary.get("parameter_selection_on_2008_2011") != "forbidden"
        or str(parent.get("config_path")) != PARENT_CONFIG_RELATIVE
        or str(parent.get("config_sha256")) != PARENT_CONFIG_SHA256
        or str(parent.get("module_sha256")) != PARENT_MODULE_SHA256
        or str(parent.get("metrics_path")) != PARENT_METRICS_RELATIVE
        or str(parent.get("metrics_sha256")) != PARENT_METRICS_SHA256
        or str(parent.get("identity_path")) != PARENT_IDENTITY_RELATIVE
        or str(parent.get("identity_sha256")) != PARENT_IDENTITY_SHA256
        or parent.get("formula_signal_risk_execution_and_costs_changed") is not False
        or str(dates.get("source_start")) != SOURCE_START.date().isoformat()
        or str(dates.get("first_complete_trend_observation"))
        != FIRST_COMPLETE_TREND_OBSERVATION.date().isoformat()
        or str(dates.get("first_weekly_decision"))
        != FIRST_WEEKLY_DECISION.date().isoformat()
        or str(dates.get("validation_start")) != VALIDATION_START.date().isoformat()
        or str(dates.get("validation_end")) != VALIDATION_END.date().isoformat()
        or str(dates.get("protected_from")) != PROTECTED_FROM.date().isoformat()
        or validation.get("period_role") != "one_shot_unseen_temporal_validation"
        or validation.get("hyperparameter_search") is not False
        or tuple(int(value) for value in validation["leave_one_year_out_years"])
        != EVALUATION_YEARS
        or int(validation["rolling_window_sessions"]) != ROLLING_WINDOW_SESSIONS
        or int(validation["bootstrap_replications_per_block_scenario"])
        != BOOTSTRAP_REPLICATIONS
        or tuple(int(value) for value in validation["bootstrap_block_sessions"])
        != BOOTSTRAP_BLOCKS
        or float(validation["bootstrap_elapsed_years"]) != BOOTSTRAP_ELAPSED_YEARS
        or execution.get("implementation")
        != "frozen_V29_risk_first_roll_with_V26_integer_capacity_ledger"
        or float(execution["maximum_participation"]) != v12.MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"])
        != v1.MAXIMUM_RISK_MULTIPLIER
    ):
        raise ValueError("V31 protocol invariants drifted")

    expected_scenarios = {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }
    scenarios = _mapping(execution.get("cost_scenarios"), "cost scenarios")
    observed_scenarios = {
        str(name): {
            "slippage_ticks": int(_mapping(value, str(name))["slippage_ticks"]),
            "fee_multiplier": float(_mapping(value, str(name))["fee_multiplier"]),
        }
        for name, value in scenarios.items()
    }
    if observed_scenarios != expected_scenarios:
        raise ValueError("V31 cost scenarios drifted")

    parent_config, parent_metrics_path, parent_identity_path = _parent_paths()
    if v12.sha256_file(parent_config) != PARENT_CONFIG_SHA256:
        raise ValueError("V31 parent V30-D2 config bytes drifted")
    if (
        v12.sha256_file(
            PROJECT_ROOT
            / "src/market_lab/futures_v30_three_sleeve_risk_restoration_v2.py"
        )
        != PARENT_MODULE_SHA256
    ):
        raise ValueError("V31 parent V30-D2 module bytes drifted")
    loaded_parent = v2.load_protocol(parent_config)
    if loaded_parent.config_sha256 != PARENT_CONFIG_SHA256:
        raise ValueError("V31 parent V30-D2 protocol replay drifted")
    if (
        v12.sha256_file(parent_metrics_path) != PARENT_METRICS_SHA256
        or parent_metrics_path.stat().st_size != int(parent["metrics_bytes"])
        or v12.sha256_file(parent_identity_path) != PARENT_IDENTITY_SHA256
        or parent_identity_path.stat().st_size != int(parent["identity_bytes"])
    ):
        raise ValueError("V31 parent V30-D2 canonical output drifted")
    parent_metrics = json.loads(parent_metrics_path.read_text(encoding="utf-8-sig"))
    parent_identity = json.loads(parent_identity_path.read_text(encoding="utf-8-sig"))
    if (
        parent_metrics.get("protocol_sha256") != PARENT_CONFIG_SHA256
        or parent_metrics.get("development_selection") is not True
        or parent_metrics.get("independent_confirmation") is not False
        or parent_metrics.get("assessment", {}).get("verdict")
        != "DEVELOPMENT_CANDIDATE_READY_FOR_SEPARATE_PRE2012_SEAL"
        or parent_metrics.get("assessment", {}).get(
            "supports_20_percent_on_open_development"
        )
        is not True
        or parent_metrics.get("assessment", {}).get(
            "supports_50_percent_on_open_development"
        )
        is not False
        or parent_identity.get("metrics_sha256") != PARENT_METRICS_SHA256
        or parent_identity.get("pre2012_returns_or_pnl_observed") is not False
    ):
        raise ValueError("V31 parent V30-D2 semantic identity drifted")

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
            raise ValueError(f"V31 implementation dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    return v1.V30Protocol(path, actual_sha, payload, paths, dependency_hashes)


def verify_inputs(protocol: v1.V30Protocol) -> v1.VerifiedInputs:
    """Read only identities, schemas, dates and masks; never pre-2012 prices."""
    checks: dict[str, bool] = {
        "protocol_seal": True,
        "parent_V30_D2_config_sealed": v12.sha256_file(_parent_paths()[0])
        == PARENT_CONFIG_SHA256,
        "parent_V30_D2_metrics_sealed": v12.sha256_file(_parent_paths()[1])
        == PARENT_METRICS_SHA256,
        "parent_V30_D2_identity_sealed": v12.sha256_file(_parent_paths()[2])
        == PARENT_IDENTITY_SHA256,
    }
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
            checks[f"{name}_source_schema_has_no_outcomes"] = not bool(
                {str(column).lower() for column in columns} & v1.FORBIDDEN_OUTCOME_COLUMNS
            )
        metadata[str(name)] = item
    if not all(checks.values()):
        raise ValueError(f"V31 byte/schema preflight failed: {checks}")

    manifest = json.loads(
        protocol.paths["market_manifest"].read_text(encoding="utf-8-sig")
    )
    temporal = manifest["temporal_semantics"]
    quality = manifest["quality_gates"]
    variable = manifest["variable_availability"]
    checks.update(
        {
            "market_manifest_payload": v1._manifest_payload_sha(manifest)
            == manifest["manifest_payload_sha256"],
            "market_manifest_sidecar": protocol.paths["market_manifest_sidecar"]
            .read_text(encoding="utf-8-sig")
            .split()[0]
            == declarations["market_manifest"]["sha256"],
            "market_source_identity": manifest.get("source_id")
            == "moex-pre2012-core3-plus-late-mix-causal-derived-2008-2011-v3",
            "market_source_contains_prices_but_no_outcomes": temporal.get("contains_prices")
            is True
            and temporal.get("contains_returns_targets_labels_signals_equity_or_pnl")
            is False,
            "market_source_causal_forward_adjustment": temporal.get(
                "causal_forward_adjustment"
            )
            is True,
            "market_source_no_gap_or_listing_return_bridge": temporal.get(
                "missing_or_listing_gap_return_bridge_created"
            )
            is False,
            "market_source_bounds": temporal.get("minimum_session")
            == SOURCE_START.date().isoformat()
            and temporal.get("maximum_session") == VALIDATION_END.date().isoformat(),
            "market_source_protected_before_2012": temporal.get(
                "derived_market_rows_must_be_before"
            )
            == PROTECTED_FROM.date().isoformat(),
            "market_source_unresolved_zero": int(quality["unresolved_roll_count"]) == 0
            and int(quality["unresolved_exit_count"]) == 0,
            "market_source_roll_counts": quality["successful_rolls"]
            == {"SI": 11, "RI": 11, "BR": 36, "MIX": 0},
            "market_source_late_MIX_exact": variable.get("MIX_first_source_session")
            == MIX_FIRST_SOURCE_SESSION.date().isoformat()
            and int(variable.get("MIX_unavailable_session_count", -1))
            == EXPECTED_MIX_UNAVAILABLE_SESSIONS
            and variable.get("MIX_unavailable_policy")
            == "explicit_flat_mask_never_backfill",
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
        checks[f"{name}_date_min"] = dates.min() == SOURCE_START
        checks[f"{name}_date_max"] = dates.max() == VALIDATION_END
        checks[f"{name}_protected"] = bool(dates.lt(PROTECTED_FROM).all())
        metadata[name]["minimum_timestamp"] = dates.min().date().isoformat()
        metadata[name]["maximum_timestamp"] = dates.max().date().isoformat()

    panel_keys = pd.read_parquet(
        protocol.paths["market_panel"], columns=["trade_date", "asset_code"]
    )
    panel_keys["trade_date"] = pd.to_datetime(
        panel_keys["trade_date"], errors="raise"
    ).dt.normalize()
    master = pd.DatetimeIndex(panel_keys["trade_date"].drop_duplicates().sort_values())
    weekly_dates = pd.Series(master, index=master).groupby(master.to_period("W-SUN")).max()
    first_weekly = weekly_dates.loc[weekly_dates.ge(FIRST_COMPLETE_TREND_OBSERVATION)].iloc[0]
    checks.update(
        {
            "master_session_count_exact": len(master) == EXPECTED_MASTER_SESSIONS,
            "master_calendar_strictly_increasing": master.is_monotonic_increasing
            and master.is_unique,
            "panel_complete_four_row_masks": bool(
                panel_keys.groupby("trade_date")["asset_code"].nunique().eq(4).all()
            ),
            "panel_exact_asset_universe": set(panel_keys["asset_code"])
            == set(v12.ASSETS),
            "calendar_253rd_observation_exact": master[252]
            == FIRST_COMPLETE_TREND_OBSERVATION,
            "first_mechanical_weekly_decision_exact": first_weekly
            == FIRST_WEEKLY_DECISION,
            "validation_start_is_next_factual_session": master[
                master.get_loc(FIRST_WEEKLY_DECISION) + 1
            ]
            == VALIDATION_START,
            "evaluation_session_count_exact": int(
                master.to_series().between(VALIDATION_START, VALIDATION_END).sum()
            )
            == EXPECTED_EVALUATION_SESSIONS,
        }
    )

    active_metadata = pd.read_parquet(
        protocol.paths["active_contract_map"],
        columns=[
            "decision_date",
            "effective_date",
            "observed_through",
            "asset_code",
            "contract_id",
            "plan_tradable",
            "roll",
            "reason",
        ],
    )
    for column in ("decision_date", "effective_date", "observed_through"):
        active_metadata[column] = pd.to_datetime(
            active_metadata[column], errors="raise"
        ).dt.normalize()
    decided = active_metadata["decision_date"].notna()
    mix_prelisting = active_metadata["asset_code"].eq("MIX") & active_metadata[
        "effective_date"
    ].lt(MIX_FIRST_SOURCE_SESSION)
    mix_first_source_warmup = (
        active_metadata["asset_code"].eq("MIX")
        & active_metadata["effective_date"].eq(MIX_FIRST_SOURCE_SESSION)
        & active_metadata["decision_date"].isna()
    )
    null_decision = active_metadata["decision_date"].isna()
    permitted_null_decision = (
        (
            active_metadata["effective_date"].eq(SOURCE_START)
            & active_metadata["reason"].astype("string").isin(
                ["initial_warmup", "asset_not_yet_available"]
            )
        )
        | (
            active_metadata["asset_code"].eq("MIX")
            & active_metadata["effective_date"].gt(SOURCE_START)
            & active_metadata["effective_date"].lt(MIX_FIRST_SOURCE_SESSION)
            & active_metadata["reason"]
            .astype("string")
            .eq("asset_not_yet_available")
        )
        | (
            active_metadata["asset_code"].eq("MIX")
            & active_metadata["effective_date"].eq(MIX_FIRST_SOURCE_SESSION)
            & active_metadata["reason"].astype("string").eq("initial_warmup")
        )
    )
    checks.update(
        {
            "active_decision_strictly_before_effective": bool(
                active_metadata.loc[decided, "decision_date"].lt(
                    active_metadata.loc[decided, "effective_date"]
                ).all()
            ),
            "active_observed_not_after_decision": bool(
                active_metadata.loc[decided, "observed_through"].le(
                    active_metadata.loc[decided, "decision_date"]
                ).all()
            ),
            "active_complete_four_row_masks": bool(
                active_metadata.groupby("effective_date")["asset_code"].nunique().eq(4).all()
            ),
            "active_MIX_prelisting_is_flat": bool(
                (~active_metadata.loc[mix_prelisting, "plan_tradable"].astype(bool)).all()
                and active_metadata.loc[mix_prelisting, "contract_id"].isna().all()
                and active_metadata.loc[mix_prelisting, "reason"]
                .astype("string")
                .eq("asset_not_yet_available")
                .all()
            ),
            "active_MIX_first_source_warmup_is_flat": bool(
                int(mix_first_source_warmup.sum()) == 1
                and not bool(
                    active_metadata.loc[mix_first_source_warmup, "plan_tradable"].iloc[0]
                )
                and pd.isna(
                    active_metadata.loc[mix_first_source_warmup, "contract_id"].iloc[0]
                )
                and active_metadata.loc[mix_first_source_warmup, "reason"]
                .astype("string")
                .eq("initial_warmup")
                .all()
            ),
            "active_null_decisions_are_exact_initial_or_late_MIX_masks": bool(
                int(null_decision.sum()) == 731
                and np.array_equal(
                    null_decision.to_numpy(dtype=bool),
                    permitted_null_decision.to_numpy(dtype=bool),
                )
            ),
        }
    )

    panel_masks = pd.read_parquet(
        protocol.paths["market_panel"],
        columns=[
            "trade_date",
            "asset_code",
            "active_contract_reason",
            "active_contract_valid",
            "curve_observed_through",
            "curve_available_at",
            "curve_valid",
        ],
    )
    panel_masks["trade_date"] = pd.to_datetime(
        panel_masks["trade_date"], errors="raise"
    ).dt.normalize()
    panel_masks["curve_observed_through"] = pd.to_datetime(
        panel_masks["curve_observed_through"], errors="raise"
    ).dt.normalize()
    availability = panel_masks["curve_available_at"].astype("string")
    missing_availability = availability.isna()
    exact_prelisting = (
        panel_masks["asset_code"].eq("MIX")
        & panel_masks["trade_date"].lt(MIX_FIRST_SOURCE_SESSION)
        & panel_masks["active_contract_reason"]
        .astype("string")
        .eq("asset_not_yet_available")
        & ~panel_masks["active_contract_valid"].astype(bool)
    )
    bool_types = (bool, np.bool_)
    checks.update(
        {
            "curve_missing_availability_count_exact": int(missing_availability.sum())
            == EXPECTED_MIX_UNAVAILABLE_SESSIONS,
            "curve_missing_availability_only_exact_MIX_prelisting": bool(
                np.array_equal(
                    missing_availability.to_numpy(dtype=bool),
                    exact_prelisting.to_numpy(dtype=bool),
                )
            ),
            "curve_available_rows_are_decision_close": bool(
                availability.loc[~missing_availability].eq("decision_close").all()
            ),
            "curve_prelisting_observed_through_is_missing": bool(
                panel_masks.loc[exact_prelisting, "curve_observed_through"].isna().all()
            ),
            "curve_available_observed_through_equals_trade_date": bool(
                panel_masks.loc[~exact_prelisting, "curve_observed_through"].equals(
                    panel_masks.loc[~exact_prelisting, "trade_date"]
                )
            ),
            "curve_valid_is_nonmissing_boolean": bool(
                panel_masks["curve_valid"].notna().all()
                and panel_masks["curve_valid"]
                .map(lambda value: isinstance(value, bool_types))
                .all()
            ),
            "prelisting_curve_valid_is_false": bool(
                (~panel_masks.loc[exact_prelisting, "curve_valid"].astype(bool)).all()
            ),
        }
    )
    expected_count = int(protocol.payload["preflight"]["expected_check_count"])
    if len(checks) != expected_count:
        raise ValueError(
            f"V31 preflight check-count drift: {len(checks)} != {expected_count}"
        )
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(f"V31 manifest/temporal/mask preflight failed: {failed}")
    return v1.VerifiedInputs(protocol.paths, checks, metadata)


def verify_pre2012_curve_panel(frame: pd.DataFrame) -> v13.CurveVerification:
    """Apply the V13 proof while allowing only the sealed late-MIX empty mask."""
    columns = list(v13.PANEL_COLUMNS) + ["active_contract_reason", "active_contract_valid"]
    if missing := set(columns) - set(frame.columns):
        raise ValueError(f"V31 curve panel lacks columns: {sorted(missing)}")
    curve = frame.loc[:, columns].copy()
    curve["trade_date"] = _normalized_dates(curve["trade_date"], "trade_date")
    for column in (
        "curve_observed_through",
        "front_expiration_date",
        "next_expiration_date",
    ):
        curve[column] = _normalized_dates(curve[column], column)
    curve["asset"] = curve["asset_code"].map(v12._asset_code)
    if curve.duplicated(["trade_date", "asset"]).any():
        raise ValueError("V31 curve panel has duplicate date/asset rows")
    if set(curve["asset"]) != set(v12.ASSETS):
        raise ValueError("V31 curve panel universe drift")

    raw_valid = curve["curve_valid"]
    bool_types = (bool, np.bool_)
    if raw_valid.isna().any() or not raw_valid.map(
        lambda value: isinstance(value, bool_types)
    ).all():
        raise ValueError("V31 curve_valid must be non-missing boolean")
    stored_valid = raw_valid.astype(bool)
    for column in ("front_settle", "next_settle", "roll_yield"):
        values = pd.to_numeric(curve[column], errors="coerce").astype(float)
        if np.isinf(values.to_numpy(dtype=float)).any():
            raise ValueError(f"V31 {column} contains infinity")
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
        raise ValueError("V31 curve_valid disagrees with independent front/next proof")
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
        raise ValueError("V31 stored roll_yield differs from independent recomputation")
    if curve.loc[~independently_valid, "roll_yield"].notna().any():
        raise ValueError("V31 invalid curve rows must preserve roll_yield as missing")

    availability = curve["curve_available_at"].astype("string")
    missing_availability = availability.isna()
    exact_prelisting = (
        curve["asset"].eq("MIX")
        & curve["trade_date"].lt(MIX_FIRST_SOURCE_SESSION)
        & curve["active_contract_reason"]
        .astype("string")
        .eq("asset_not_yet_available")
        & ~curve["active_contract_valid"].astype(bool)
    )
    if not np.array_equal(
        missing_availability.to_numpy(dtype=bool),
        exact_prelisting.to_numpy(dtype=bool),
    ):
        raise ValueError("V31 curve availability missing outside exact late-MIX mask")
    if not availability.loc[~exact_prelisting].eq("decision_close").all():
        raise ValueError("V31 available curve row is not decision_close")
    if not curve.loc[exact_prelisting, "curve_observed_through"].isna().all():
        raise ValueError("V31 late-MIX empty mask has an observed-through timestamp")
    if not curve.loc[~exact_prelisting, "curve_observed_through"].equals(
        curve.loc[~exact_prelisting, "trade_date"]
    ):
        raise ValueError("V31 available curve was not observed through decision date")
    if not (
        curve.loc[exact_prelisting, ["front_settle", "next_settle", "roll_yield"]]
        .isna()
        .all()
        .all()
        and (~stored_valid.loc[exact_prelisting]).all()
    ):
        raise ValueError("V31 late-MIX empty mask contains fabricated curve values")

    checks = {
        "curve_observed_through_equals_decision_or_exact_prelisting_missing": True,
        "curve_available_at_decision_close_or_exact_prelisting_missing": True,
        "curve_valid_recomputed_from_positive_simultaneous_settles": True,
        "next_expiration_strictly_after_front_when_valid": True,
        "stored_roll_yield_matches_independent_recomputation": True,
        "invalid_curve_roll_yield_preserves_missingness": True,
        "late_MIX_mask_count_exact": int(exact_prelisting.sum())
        == EXPECTED_MIX_UNAVAILABLE_SESSIONS,
        "late_MIX_mask_has_no_fabricated_curve_values": True,
    }
    output = curve.loc[:, ["trade_date", "asset", "roll_yield"]].copy()
    output["carry_available"] = independently_valid.to_numpy(dtype=bool)
    return v13.CurveVerification(
        frame=output.sort_values(
            ["trade_date", "asset"], kind="mergesort", ignore_index=True
        ),
        checks=checks,
    )


def build_three_sleeve_scores(panel: pd.DataFrame) -> v1.SignalBuild:
    """Build byte-inherited V30 economics with only the sealed late-listing verifier."""
    curve = verify_pre2012_curve_panel(panel)
    trend = v12.build_trend_scores(panel)
    built = v1.compose_signal_components(trend, curve.frame)
    components = built.components
    checks = {
        **curve.checks,
        **built.checks,
        "component_dates_strictly_pre2012": bool(
            components["decision_date"].lt(PROTECTED_FROM).all()
        ),
        "late_MIX_never_backfilled_into_252_session_signal": bool(
            components.loc[components["asset"].eq("MIX"), "composite_score"].isna().all()
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"V31 signal checks failed: {checks}")
    counts = {
        **built.counts,
        "MIX_component_rows": int(components["asset"].eq("MIX").sum()),
        "MIX_finite_composite_rows": int(
            components.loc[components["asset"].eq("MIX"), "composite_score"]
            .notna()
            .sum()
        ),
    }
    return v1.SignalBuild(built.scores, components, checks, counts)


def adapt_late_mix_flat_active_map(
    active_map: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, bool], int]:
    """Attach prior factual decisions only to provably unavailable zero-weight MIX rows."""
    required = {
        "decision_date",
        "effective_date",
        "observed_through",
        "asset_code",
        "contract_id",
        "plan_tradable",
        "roll",
        "reason",
    }
    if missing := required - set(active_map.columns):
        raise ValueError(f"V31 active map lacks flat-adapter columns: {sorted(missing)}")
    adapted = active_map.copy()
    for column in ("decision_date", "effective_date", "observed_through"):
        adapted[column] = pd.to_datetime(adapted[column], errors="raise").dt.normalize()
    master = pd.DatetimeIndex(adapted["effective_date"].drop_duplicates().sort_values())
    prior = pd.Series(master[:-1], index=master[1:])
    eligible = (
        adapted["asset_code"].eq("MIX")
        & adapted["decision_date"].isna()
        & adapted["effective_date"].gt(SOURCE_START)
        & adapted["effective_date"].le(MIX_FIRST_SOURCE_SESSION)
        & ~adapted["plan_tradable"].fillna(False).astype(bool)
        & adapted["contract_id"].isna()
        & ~adapted["roll"].fillna(False).astype(bool)
        & (
            (
                adapted["effective_date"].lt(MIX_FIRST_SOURCE_SESSION)
                & adapted["reason"]
                .astype("string")
                .eq("asset_not_yet_available")
            )
            | (
                adapted["effective_date"].eq(MIX_FIRST_SOURCE_SESSION)
                & adapted["reason"].astype("string").eq("initial_warmup")
            )
        )
    )
    adapted_rows = int(eligible.sum())
    if adapted_rows != EXPECTED_MIX_UNAVAILABLE_SESSIONS:
        raise ValueError(
            f"V31 late-MIX flat-adapter count drift: {adapted_rows} "
            f"!= {EXPECTED_MIX_UNAVAILABLE_SESSIONS}"
        )
    assigned = adapted.loc[eligible, "effective_date"].map(prior)
    if assigned.isna().any():
        raise ValueError("V31 late-MIX flat adapter lacks a prior factual session")
    adapted.loc[eligible, "decision_date"] = assigned.to_numpy()
    adapted.loc[eligible, "observed_through"] = assigned.to_numpy()
    retained = adapted.loc[
        adapted["decision_date"].notna()
        & adapted["decision_date"].lt(adapted["effective_date"])
    ]
    counts = retained.groupby("decision_date")["asset_code"].nunique()
    checks = {
        "late_MIX_flat_adapter_count_exact": adapted_rows
        == EXPECTED_MIX_UNAVAILABLE_SESSIONS,
        "late_MIX_flat_adapter_uses_prior_factual_session": bool(
            adapted.loc[eligible, "decision_date"].equals(
                adapted.loc[eligible, "observed_through"]
            )
            and adapted.loc[eligible, "decision_date"]
            .lt(adapted.loc[eligible, "effective_date"])
            .all()
        ),
        "late_MIX_flat_adapter_preserves_missing_contract": bool(
            adapted.loc[eligible, "contract_id"].isna().all()
        ),
        "late_MIX_flat_adapter_preserves_nontradable_zero_context": bool(
            (~adapted.loc[eligible, "plan_tradable"].astype(bool)).all()
            and (~adapted.loc[eligible, "roll"].astype(bool)).all()
        ),
        "adapted_active_map_has_complete_four_asset_decisions": bool(
            counts.eq(len(v12.ASSETS)).all()
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"V31 late-MIX flat adapter failed: {checks}")
    return adapted, checks, adapted_rows


def build_targets(
    panel: pd.DataFrame,
    scores: pd.DataFrame,
    active_map: pd.DataFrame,
) -> V31TargetBuild:
    """Map the frozen V30 target formula onto the fixed unseen evaluation dates."""
    weekly = v12.build_weekly_weights(panel, scores)
    adapted_active, adapter_checks, adapted_rows = adapt_late_mix_flat_active_map(
        active_map
    )
    base = v12.build_execution_targets(
        weekly,
        adapted_active,
        oos_start=VALIDATION_START,
        oos_end=VALIDATION_END,
    )
    risk = weekly.loc[
        :, ["decision_date", "gross", "expected_annual_volatility"]
    ].drop_duplicates()
    risk = risk.sort_values("decision_date", kind="mergesort", ignore_index=True)
    risk["risk_multiplier"] = v1.risk_restoration_multiplier(
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
        raise ValueError("V31 mapped target lacks a prior weekly risk multiplier")
    restored["pre_restoration_target_weight"] = restored["target_weight"].astype(float)
    restored["target_weight"] = (
        restored["pre_restoration_target_weight"] * restored["risk_multiplier"]
    )
    restored["provenance"] = (
        restored["provenance"].astype("string")
        + "|V30_frozen_final_vol_20pct_cap_2x_multiplier="
        + restored["risk_multiplier"].map(lambda value: f"{float(value):.12g}")
        + "|V31_unseen_period_only"
    )
    hard = base.targets.copy()
    hard["pre_restoration_target_weight"] = hard["target_weight"].astype(float)
    hard["risk_multiplier"] = v1.MAXIMUM_RISK_MULTIPLIER
    hard["target_weight"] = (
        hard["target_weight"].astype(float) * v1.MAXIMUM_RISK_MULTIPLIER
    )
    hard["provenance"] = (
        hard["provenance"].astype("string")
        + "|V30_frozen_hard_2x_sensitivity|V31_unseen_period_only"
    )
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
        **adapter_checks,
        "risk_multiplier_finite_nonnegative": bool(
            np.isfinite(risk["risk_multiplier"]).all()
            and risk["risk_multiplier"].ge(0.0).all()
        ),
        "risk_multiplier_at_most_2x": bool(
            risk["risk_multiplier"].le(v1.MAXIMUM_RISK_MULTIPLIER + 1e-12).all()
        ),
        "restored_expected_volatility_at_most_20pct": bool(
            risk["restored_expected_annual_volatility"]
            .le(v1.FINAL_TARGET_VOLATILITY + 1e-12)
            .all()
        ),
        "restored_mapped_gross_at_most_2x": bool(
            restored_gross.le(v1.MAXIMUM_RISK_MULTIPLIER + 1e-12).all()
        ),
        "hard_sensitivity_gross_at_most_2x": bool(
            hard_gross.le(v1.MAXIMUM_RISK_MULTIPLIER + 1e-12).all()
        ),
        "mapped_target_dates_in_frozen_validation": bool(
            pd.to_datetime(restored["effective_date"], errors="raise")
            .between(VALIDATION_START, VALIDATION_END)
            .all()
        ),
        "mapped_target_dates_strictly_pre2012": bool(
            pd.to_datetime(restored["effective_date"], errors="raise")
            .lt(PROTECTED_FROM)
            .all()
        ),
        "late_MIX_target_is_always_flat": bool(
            restored.loc[restored["asset_code"].eq("MIX"), "target_weight"]
            .abs()
            .le(1e-12)
            .all()
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"V31 target construction failed: {checks}")
    return V31TargetBuild(
        weekly,
        risk,
        unscaled,
        restored,
        hard,
        base.decision_audit,
        base.weekly_decisions,
        base.roll_decisions,
        adapted_rows,
        checks,
    )


def _annual_returns(ledger: pd.DataFrame) -> dict[str, float]:
    daily = pd.to_numeric(ledger["ending_cash"], errors="raise").astype(float) / pd.to_numeric(
        ledger["starting_cash"], errors="raise"
    ).astype(float) - 1.0
    dates = pd.to_datetime(ledger["session_date"], errors="raise").dt.normalize()
    return {
        str(year): float((1.0 + daily.loc[dates.dt.year.eq(year)]).prod() - 1.0)
        for year in EVALUATION_YEARS
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
            "calendar_year_segments": len(annual),
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
    protocol: v1.V30Protocol,
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
        leave = robustness.leave_one_year_out(returns, years=EVALUATION_YEARS)
        leave.insert(0, "scenario", scenario)
        scenario_bootstrap: dict[str, Any] = {}
        for block in BOOTSTRAP_BLOCKS:
            samples = robustness.circular_block_bootstrap(
                returns.to_numpy(dtype=float),
                replications=BOOTSTRAP_REPLICATIONS,
                block_sessions=block,
                seed=int(seed_map[scenario][str(block)]),
                elapsed_years=BOOTSTRAP_ELAPSED_YEARS,
            )
            samples.insert(0, "scenario", scenario)
            samples.insert(1, "block_sessions", block)
            bootstrap_frames.append(samples)
            scenario_bootstrap[str(block)] = robustness.summarize_bootstrap(
                samples, quantiles=(0.05, 0.50, 0.95)
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


def assess_validation(
    scenarios: Mapping[str, Mapping[str, Any]],
    robustness_summary: Mapping[str, Any],
    checks: Mapping[str, bool],
) -> dict[str, Any]:
    """Apply predeclared transfer gates without changing the frozen V30 economics."""
    main = [scenarios[name] for name in ("primary", "doubled", "stress")]
    structural = {
        "all_source_signal_target_and_temporal_checks_true": all(checks.values()),
        "all_main_scenarios_execution_complete": all(
            bool(value["execution_complete"]) for value in main
        ),
        "zero_main_critical_failures_and_unresolved_halts": all(
            int(value["critical_failure_count"]) == 0
            and int(value["unresolved_halt_count"]) == 0
            for value in main
        ),
    }
    stress_bootstrap = robustness_summary["stress"]["bootstrap"]
    minimum_joint = min(
        float(stress_bootstrap[str(block)]["probability_cagr_ge_0_20_and_mdd_le_0_30"])
        for block in BOOTSTRAP_BLOCKS
    )
    stress_leave = robustness_summary["stress"]["leave_one_year_out"]
    minimum_leave_cagr = min(float(value["cagr"]) for value in stress_leave.values())
    stress_rolling = robustness_summary["stress"]["rolling_252"]
    economic = {
        "all_main_CAGR_at_least_20pct": all(float(value["cagr"]) >= 0.20 for value in main),
        "all_main_MDD_at_most_30pct": all(
            float(value["maximum_drawdown"]) <= 0.30 for value in main
        ),
        "primary_and_stress_sharpe_at_least_1": float(scenarios["primary"]["sharpe"])
        >= 1.0
        and float(scenarios["stress"]["sharpe"]) >= 1.0,
        "primary_positive_years_at_least_2_of_3": int(
            scenarios["primary"]["positive_years"]
        )
        >= 2
        and int(scenarios["primary"]["calendar_year_segments"]) == 3,
        "primary_worst_year_at_least_minus_15pct": float(
            scenarios["primary"]["worst_year"]
        )
        >= -0.15,
        "stress_worst_year_at_least_minus_20pct": float(
            scenarios["stress"]["worst_year"]
        )
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
    structural_pass = all(structural.values())
    passed = structural_pass and all(economic.values())
    supports_50 = passed and all(float(value["cagr"]) >= 0.50 for value in main)
    if not structural_pass:
        verdict = "UNSEEN_TEMPORAL_INVALID_EXECUTION_OR_INTEGRITY"
    elif passed:
        verdict = "UNSEEN_TEMPORAL_CONFIRMATION_20_RESEARCH_ONLY"
    else:
        verdict = "UNSEEN_TEMPORAL_NO_GO_20"
    return {
        "conditions": {**structural, **economic},
        "passed": passed,
        "verdict": verdict,
        "minimum_stress_bootstrap_joint_20_30_frequency": minimum_joint,
        "minimum_stress_leave_one_year_out_CAGR": minimum_leave_cagr,
        "supports_20_percent_on_unseen_temporal_period": passed,
        "supports_50_percent_on_unseen_temporal_period": supports_50,
        "independent_temporal_validation": True,
        "live_trading_allowed": False,
    }


def _report_text(payload: Mapping[str, Any]) -> str:
    lines = [
        "# V31 one-shot unseen pre-2012 temporal validation",
        "",
        f"Verdict: **{payload['assessment']['verdict']}** (research-only; live forbidden).",
        "",
        "V30 economics were frozen on 2012-2017 before any 2008-2011 price/return/PnL read.",
        "Only the calendar and exact late-listing MIX mask were adapted before this run.",
        "",
        "| Scenario | CAGR | Sharpe | MDD | Positive year segments | Worst segment | "
        "Costs RUB | Complete |",
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
            f"{item['maximum_drawdown']:.4%} | {item['positive_years']}/3 | "
            f"{item['worst_year']:.4%} | {item['total_cost']:.2f} | "
            f"{item['execution_complete']} |"
        )
    lines.extend(["", "## Primary annual/partial-year returns", ""])
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
            f"- MIX finite composite rows: {counts['MIX_finite_composite_rows']} "
            "(late listing is never backfilled).",
            f"- Mean risk multiplier: {counts['mean_risk_multiplier']:.4f}; maximum: "
            f"{counts['maximum_risk_multiplier']:.4f}.",
            f"- Minimum stress bootstrap joint 20% CAGR / 30% MDD frequency: "
            f"{payload['assessment']['minimum_stress_bootstrap_joint_20_30_frequency']:.2%}.",
            f"- Minimum stress leave-one-year-out CAGR: "
            f"{payload['assessment']['minimum_stress_leave_one_year_out_CAGR']:.2%}.",
            "",
            "This is an unseen temporal test, not live admission. Historical exchange specs, "
            "broker fees, margin, spread, queue and intraday fill remain research proxies.",
        ]
    )
    return "\n".join(lines) + "\n"


def preflight_summary(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    """Return the outcome-free seal/source proof without loading any market value."""
    protocol = load_protocol(config_path)
    verified = verify_inputs(protocol)
    return {
        "protocol_id": protocol.payload["protocol_id"],
        "protocol_sha256": protocol.config_sha256,
        "checks_true": int(sum(verified.checks.values())),
        "checks_total": len(verified.checks),
        "all_checks_true": all(verified.checks.values()),
        "pre2012_price_values_returns_targets_equity_or_pnl_read": False,
    }


def run_experiment(
    output_root: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> Path:
    """Execute the single immutable V31 economic read after commit and push."""
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
        pd.to_datetime(market["session_date"], errors="raise")
        .drop_duplicates()
        .sort_values()
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
        "execution_sessions_exact": execution_market["session_date"].nunique()
        == EXPECTED_EXECUTION_SESSIONS,
        "coverage_rows_match_nonzero_targets": len(coverage)
        == int(targets.restored_targets["target_weight"].abs().gt(1e-12).sum()),
        "frozen_V30_parent_bytes_verified": protocol.payload["parent_V30_D2"][
            "formula_signal_risk_execution_and_costs_changed"
        ]
        is False,
        "pre2012_outcomes_not_observed_before_V31_seal": True,
    }
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(f"V31 pre-execution checks failed: {failed}")

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
        "source_master_sessions": EXPECTED_MASTER_SESSIONS,
        "execution_sessions_including_predecessor": EXPECTED_EXECUTION_SESSIONS,
        "evaluation_sessions": EXPECTED_EVALUATION_SESSIONS,
        "weekly_decisions": targets.weekly_decisions,
        "roll_decisions": targets.roll_decisions,
        "adapted_late_MIX_flat_rows": targets.adapted_late_mix_flat_rows,
        "mapped_target_rows": len(targets.restored_targets),
        "nonzero_targets": nonzero,
        "covered_nonzero_targets": int(
            coverage["execution_dependencies_complete"].sum()
        ),
        "mean_risk_multiplier": float(targets.risk_audit["risk_multiplier"].mean()),
        "maximum_risk_multiplier": float(targets.risk_audit["risk_multiplier"].max()),
        "minimum_risk_multiplier": float(targets.risk_audit["risk_multiplier"].min()),
    }
    assessment = assess_validation(metrics, robustness_summary, checks)
    parent = protocol.payload["parent_V30_D2"]
    identity = {
        "protocol_sha256": protocol.config_sha256,
        "parent_V30_D2_config_sha256": PARENT_CONFIG_SHA256,
        "parent_V30_D2_module_sha256": PARENT_MODULE_SHA256,
        "parent_V30_D2_metrics_sha256": PARENT_METRICS_SHA256,
        "parent_V30_D2_identity_sha256": PARENT_IDENTITY_SHA256,
        "market_manifest_sha256": inputs["market_manifest"]["sha256"],
        "input_sha256": {name: value["sha256"] for name, value in inputs.items()},
        "implementation_sha256": protocol.dependency_hashes,
        "formula_signal_risk_execution_and_costs_changed_from_V30_D2": parent[
            "formula_signal_risk_execution_and_costs_changed"
        ],
        "pre2012_price_values_returns_targets_equity_or_pnl_observed_before_V31_seal": False,
        "pre2012_outcomes_observed_by_this_single_run": True,
        "contains_2012_or_later_prices_returns_targets_equity_or_pnl": False,
    }
    payload: dict[str, Any] = {
        "protocol_id": protocol.payload["protocol_id"],
        "protocol_sha256": protocol.config_sha256,
        "research_only": True,
        "development_selection": False,
        "independent_temporal_validation": True,
        "live_trading_allowed": False,
        "checks": checks,
        "input_metadata": verified.metadata,
        "identity": identity,
        "counts": counts,
        "scenarios": metrics,
        "robustness": robustness_summary,
        "assessment": assessment,
        "parent_development_reference": protocol.payload["parent_development_reference"],
        "limitations": protocol.payload["limitations"],
    }

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v31_pre2012_temporal_{timestamp}_{protocol.config_sha256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V31 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    parent_config, parent_metrics_path, parent_identity_path = _parent_paths()
    try:
        shutil.copyfile(protocol.config_path, temporary / "resolved_protocol.yaml")
        shutil.copyfile(parent_config, temporary / "parent_v30_d2_protocol.yaml")
        shutil.copyfile(parent_metrics_path, temporary / "parent_v30_d2_metrics.json")
        shutil.copyfile(parent_identity_path, temporary / "parent_v30_d2_identity.json")
        v1._write_parquet(temporary / "scores.parquet", signal.scores)
        v1._write_parquet(temporary / "signal_components.parquet", signal.components)
        v1._write_parquet(temporary / "weekly_weights.parquet", targets.weekly_weights)
        v1._write_parquet(temporary / "risk_restoration.parquet", targets.risk_audit)
        v1._write_parquet(temporary / "mapped_targets_1x.parquet", targets.unscaled_targets)
        v1._write_parquet(
            temporary / "mapped_targets_risk_restored.parquet",
            targets.restored_targets,
        )
        v1._write_parquet(
            temporary / "mapped_targets_hard_2x.parquet", targets.hard_2x_targets
        )
        targets.decision_audit.to_csv(
            temporary / "decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        v1._write_parquet(temporary / "bootstrap.parquet", bootstrap)
        v1._write_parquet(temporary / "rolling_252.parquet", rolling)
        leave.to_csv(
            temporary / "leave_one_year_out.csv", index=False, encoding="utf-8-sig"
        )
        for name, result in outputs.items():
            v1._write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            v1._write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            v1._write_parquet(temporary / f"positions_{name}.parquet", result.positions)
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
    parser.add_argument("--preflight-only", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.preflight_only:
        print(
            json.dumps(
                preflight_summary(arguments.config), ensure_ascii=False, indent=2
            )
        )
    else:
        print(run_experiment(arguments.output_root, arguments.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
