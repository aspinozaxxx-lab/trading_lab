"""Sealed V28 validation of frozen V27 economics on unseen 2013-2017 MOEX data."""

from __future__ import annotations

import argparse
import base64
import gzip
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
from market_lab import futures_v15_levered_ruonia_collateral as v15
from market_lab import futures_v25_stlfsi_stress_governor as v25
from market_lab import futures_v26_stlfsi_levered_ruonia_capacity as v26
from market_lab import futures_v27_key_rate_extreme_governor as v27
from market_lab.futures import portfolio_ledger as ledger_engine
from market_lab.futures import pre2018_macro_source as macro_v1
from market_lab.futures import pre2018_macro_source_v3 as macro_v3
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult

PROJECT_ROOT: Final[Path] = v12.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/futures_v28_pre2018_unseen.yaml"
VALIDATION_START: Final[pd.Timestamp] = pd.Timestamp("2013-01-01")
VALIDATION_END: Final[pd.Timestamp] = pd.Timestamp("2017-12-01")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2018-01-01")
EXPECTED_PREDECESSOR: Final[pd.Timestamp] = pd.Timestamp("2012-12-28")
MOSCOW: Final[str] = "Europe/Moscow"
STLFSI_MAXIMUM_AGE_DAYS: Final[int] = 14
KEY_RATE_MAXIMUM_AGE_DAYS: Final[int] = 7
KEY_RATE_BOUNDARY_PERCENT: Final[float] = 20.0
LEVERAGE_MULTIPLIER: Final[float] = 2.0
RUONIA_APPLIED_FRACTION: Final[float] = 0.50
OPERATIONAL_BUFFER_FRACTION: Final[float] = 0.10
DAY_COUNT_DENOMINATOR: Final[float] = 365.0
EXPECTED_ALL_STATES: Final[dict[str, int]] = {
    "weekly_decisions": 306,
    "pass_both": 147,
    "cash_stlfsi_above_average": 70,
    "cash_stlfsi_missing_or_stale": 0,
    "cash_key_rate_at_least_20": 0,
    "cash_key_rate_missing_or_stale": 89,
    "raw_stlfsi_pass": 209,
    "raw_stlfsi_above": 96,
    "raw_stlfsi_missing_or_stale": 1,
}
EXPECTED_VALIDATION_STATES: Final[dict[str, int]] = {
    "weekly_decisions": 254,
    "pass_both": 147,
    "cash_stlfsi_above_average": 70,
    "cash_stlfsi_missing_or_stale": 0,
    "cash_key_rate_at_least_20": 0,
    "cash_key_rate_missing_or_stale": 37,
    "raw_stlfsi_pass": 183,
    "raw_stlfsi_above": 71,
    "raw_stlfsi_missing_or_stale": 0,
}
EXPECTED_COLLATERAL_CALENDAR: Final[dict[str, int]] = {
    "execution_sessions": 1225,
    "accrual_intervals": 1224,
    "accrual_calendar_days": 1795,
    "known_rate_intervals": 56,
    "unknown_no_credit_intervals": 1168,
    "known_rate_calendar_days": 79,
}
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
class V28Protocol:
    """Verified V28 configuration and its resolved immutable inputs."""

    config_path: Path
    config_sha256: str
    payload: dict[str, Any]
    paths: dict[str, Path]
    dependency_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class VerifiedInputs:
    """Pre-price identity, schema, manifest and temporal checks."""

    paths: dict[str, Path]
    checks: dict[str, bool]
    metadata: dict[str, dict[str, Any]]


@dataclass(frozen=True, slots=True)
class MacroBundle:
    """Raw-replayed macro tables used by the two governors and collateral model."""

    stlfsi: pd.DataFrame
    key_rate: pd.DataFrame
    ruonia: pd.DataFrame
    coverage: pd.DataFrame
    checks: dict[str, bool]
    raw_records: int


@dataclass(frozen=True, slots=True)
class GovernorBuild:
    """Frozen V12 weights after V25 and V27 binary cash governors."""

    weights: pd.DataFrame
    governor: pd.DataFrame
    checks: dict[str, bool]
    all_counts: dict[str, int]
    validation_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class CollateralEvaluation:
    """Conservative recognized collateral income and its interval audit."""

    audit: pd.DataFrame
    combined_ledger: pd.DataFrame
    metrics: dict[str, Any]
    checks: dict[str, bool]


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"V28 protocol sidecar is missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def _resolved_input(relative_value: str) -> Path:
    return v12._resolved_input(relative_value)


def _as_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"V28 {label} must be a mapping")
    return value


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> V28Protocol:
    """Verify the V28 seal and every frozen economic and validation invariant."""
    path = config_path.resolve()
    actual_sha = v12.sha256_file(path)
    if _sidecar_sha(path) != actual_sha:
        raise ValueError("V28 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("sealed V28 protocol must be a mapping")
    parents = _as_mapping(payload.get("frozen_parent_identity"), "parent identity")
    signal = _as_mapping(payload.get("signal"), "signal")
    governors = _as_mapping(payload.get("governors"), "governors")
    capital = _as_mapping(payload.get("capital_efficiency"), "capital efficiency")
    collateral = _as_mapping(payload.get("collateral_income"), "collateral income")
    execution = _as_mapping(payload.get("execution"), "execution")
    validation = _as_mapping(payload.get("validation"), "validation")
    state_counts = _as_mapping(payload.get("sealed_source_only_state_counts"), "state counts")
    collateral_calendar = _as_mapping(
        payload.get("sealed_source_only_collateral_calendar"), "collateral calendar"
    )
    if (
        payload.get("protocol_id") != "futures_v28_pre2018_unseen_validation_v1"
        or payload.get("status") != "predeclared_before_first_pre2018_strategy_outcome"
        or payload.get("sealed_before_outcomes") is not True
        or payload.get("live_trading_allowed") is not False
        or str(payload["dates"]["validation_start"]) != VALIDATION_START.date().isoformat()
        or str(payload["dates"]["validation_end"]) != VALIDATION_END.date().isoformat()
        or str(payload["dates"]["protected_from"]) != PROTECTED_FROM.date().isoformat()
        or tuple(payload["universe"]["exact_order"]) != v12.ASSETS
        or parents.get("V12_protocol_sha256") != v12.CONFIG_SHA256
        or parents.get("V25_protocol_sha256") != v25.CONFIG_SHA256
        or parents.get("V26_protocol_sha256") != v26.CONFIG_SHA256
        or parents.get("V27_protocol_sha256") != v27.CONFIG_SHA256
        or tuple(int(value) for value in signal["log_momentum_horizons_sessions"])
        != v12.MOMENTUM_HORIZONS
        or int(signal["volatility_lookback_sessions"]) != v12.VOLATILITY_LOOKBACK
        or int(signal["annualization_sessions"]) != v12.ANNUALIZATION
        or float(signal["volatility_floor_annualized"]) != v12.VOLATILITY_FLOOR
        or signal.get("implementation") != "imported_frozen_V12"
        or float(governors["STLFSI4"]["boundary"]) != 0.0
        or int(governors["STLFSI4"]["maximum_age_calendar_days"])
        != STLFSI_MAXIMUM_AGE_DAYS
        or float(governors["key_rate"]["boundary_percent_per_annum"])
        != KEY_RATE_BOUNDARY_PERCENT
        or int(governors["key_rate"]["maximum_age_calendar_days"])
        != KEY_RATE_MAXIMUM_AGE_DAYS
        or float(capital["target_weight_multiplier_after_governors"])
        != LEVERAGE_MULTIPLIER
        or float(capital["maximum_gross_notional_multiple"]) != v15.MAXIMUM_GROSS
        or float(collateral["applied_rate_fraction"]) != RUONIA_APPLIED_FRACTION
        or float(collateral["operational_buffer_fraction_of_conservative_equity"])
        != OPERATIONAL_BUFFER_FRACTION
        or collateral.get("unknown_availability_policy")
        != "no_credit_preserve_rate_and_timing_missing"
        or collateral.get("reinvested_into_contract_sizing") is not False
        or collateral.get("compounded_into_future_eligible_balance") is not False
        or execution.get("unexecutable_target_policy") != "cancel_and_clip"
        or float(execution["maximum_participation"]) != v12.MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"]) != v15.MAXIMUM_GROSS
        or float(execution["initial_margin_buffer_multiple"])
        != v15.MARGIN_BUFFER_MULTIPLIER
        or validation.get("period_role")
        != "unseen_market_period_external_validation_not_full_PIT_confirmation"
        or validation.get("parameter_selection_on_validation") != "forbidden"
    ):
        raise ValueError("sealed V28 economic or validation invariants drifted")
    declared_all = {str(key): int(value) for key, value in state_counts["all"].items()}
    declared_validation = {
        str(key): int(value) for key, value in state_counts["validation"].items()
    }
    declared_collateral = {str(key): int(value) for key, value in collateral_calendar.items()}
    if (
        declared_all != EXPECTED_ALL_STATES
        or declared_validation != EXPECTED_VALIDATION_STATES
        or declared_collateral != EXPECTED_COLLATERAL_CALENDAR
    ):
        raise ValueError("V28 source-only predeclared counts drifted")
    if v12._scenario_settings(payload) != {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }:
        raise ValueError("V28 cost scenarios drifted")
    inputs = _as_mapping(payload.get("inputs"), "inputs")
    paths = {
        str(name): _resolved_input(str(_as_mapping(item, str(name))["path"]))
        for name, item in inputs.items()
    }
    dependencies = _as_mapping(payload.get("implementation_dependencies"), "dependencies")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = PROJECT_ROOT / str(relative)
        digest = str(expected).lower()
        if v12.sha256_file(dependency_path) != digest:
            raise ValueError(f"V28 implementation dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    return V28Protocol(path, actual_sha, payload, paths, dependency_hashes)


def _manifest_payload_sha(manifest: Mapping[str, Any]) -> str:
    core = {key: value for key, value in manifest.items() if key != "manifest_payload_sha256"}
    return macro_v1.sha256_bytes(macro_v1._canonical_json(core))


def verify_inputs(protocol: V28Protocol) -> VerifiedInputs:
    """Verify bytes and dates before loading any market price field."""
    checks: dict[str, bool] = {"protocol_seal": True}
    metadata: dict[str, dict[str, Any]] = {}
    declarations = protocol.payload["inputs"]
    for name, declaration_value in declarations.items():
        declaration = _as_mapping(declaration_value, str(name))
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
            item["rows"] = parquet.metadata.num_rows
            item["columns"] = parquet.schema_arrow.names
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
            read_columns = tuple(declaration["read_columns"])
            checks[f"{name}_read_schema"] = set(read_columns) <= set(parquet.schema_arrow.names)
            normalized = {str(column).lower() for column in parquet.schema_arrow.names}
            checks[f"{name}_outcome_free_source_schema"] = not bool(
                normalized & FORBIDDEN_OUTCOME_COLUMNS
            )
        metadata[str(name)] = item
    if not all(checks.values()):
        raise ValueError(f"V28 byte/schema preflight failed: {checks}")

    market_manifest = json.loads(
        protocol.paths["market_manifest"].read_text(encoding="utf-8-sig")
    )
    macro_manifest = json.loads(
        protocol.paths["macro_manifest"].read_text(encoding="utf-8-sig")
    )
    checks.update(
        {
            "market_manifest_payload": _manifest_payload_sha(market_manifest)
            == market_manifest["manifest_payload_sha256"],
            "macro_manifest_payload": _manifest_payload_sha(macro_manifest)
            == macro_manifest["manifest_payload_sha256"],
            "market_manifest_sidecar": protocol.paths["market_manifest_sidecar"]
            .read_text(encoding="utf-8-sig")
            .split()[0]
            == declarations["market_manifest"]["sha256"],
            "macro_manifest_sidecar": protocol.paths["macro_manifest_sidecar"]
            .read_text(encoding="utf-8-sig")
            .split()[0]
            == declarations["macro_manifest"]["sha256"],
            "market_source_identity": market_manifest.get("source_id")
            == "moex-pre2018-core4-causal-derived-2012-2017-v3",
            "market_source_has_no_prior_outcomes": market_manifest["temporal_semantics"].get(
                "contains_returns_targets_labels_or_pnl"
            )
            is False,
            "market_source_no_roll_bridge": market_manifest["temporal_semantics"].get(
                "missing_return_bridge_created"
            )
            is False,
            "market_source_unresolved_zero": int(
                market_manifest["quality_gates"]["unresolved_roll_count"]
            )
            == 0
            and int(market_manifest["quality_gates"]["unresolved_exit_count"]) == 0,
            "market_source_roll_counts": market_manifest["quality_gates"]["successful_rolls"]
            == {"BR": 70, "MIX": 23, "RI": 23, "SI": 22},
            "macro_source_identity": macro_manifest.get("source_id")
            == "official-pre2018-stlfsi4-cbr-monetary-current-vintage-v3",
            "macro_source_has_no_prior_outcomes": macro_manifest["limitations"].get(
                "strategy_outcomes_observed"
            )
            is False,
            "macro_unknown_timing_no_credit": macro_manifest["temporal_semantics"].get(
                "RUONIA_unknown_publication"
            )
            == "available_at_missing_no_inference_no_credit",
        }
    )
    market_artifact_names = {
        "panel": "market_panel",
        "active_contract_map": "active_contract_map",
        "contract_observations": "contract_observations",
        "spec_proxy": "spec_proxy",
        "audit": "market_audit",
    }
    for artifact_name, input_name in market_artifact_names.items():
        artifact = market_manifest["artifacts"][artifact_name]
        declaration = declarations[input_name]
        checks[f"market_manifest_{artifact_name}_identity"] = (
            artifact["sha256"] == declaration["sha256"]
            and int(artifact["bytes"]) == int(declaration["bytes"])
        )
    macro_artifact_names = {
        "stlfsi4": "stlfsi",
        "cbr_monetary": "cbr_monetary",
        "coverage": "macro_coverage",
        "raw_archive": "macro_raw_archive",
    }
    for artifact_name, input_name in macro_artifact_names.items():
        artifact = macro_manifest["artifacts"][artifact_name]
        declaration = declarations[input_name]
        checks[f"macro_manifest_{artifact_name}_identity"] = (
            artifact["sha256"] == declaration["sha256"]
            and int(artifact["bytes"]) == int(declaration["bytes"])
        )

    date_specs = {
        "market_panel": ("trade_date", "2012-01-03", "2017-12-01"),
        "active_contract_map": ("effective_date", "2012-01-03", "2017-12-01"),
        "contract_observations": ("trade_date", "2012-01-03", "2017-12-01"),
        "spec_proxy": ("session_date", "2012-01-03", "2017-12-01"),
        "stlfsi": ("observation_date", "2012-01-06", "2017-12-22"),
    }
    for name, (column, minimum, maximum) in date_specs.items():
        values = pd.to_datetime(
            pd.read_parquet(protocol.paths[name], columns=[column])[column], errors="raise"
        ).dt.normalize()
        checks[f"{name}_date_min"] = values.min() == pd.Timestamp(minimum)
        checks[f"{name}_date_max"] = values.max() == pd.Timestamp(maximum)
        checks[f"{name}_protected"] = bool(values.lt(PROTECTED_FROM).all())
        metadata[name]["minimum_timestamp"] = values.min().date().isoformat()
        metadata[name]["maximum_timestamp"] = values.max().date().isoformat()
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
        raise ValueError(f"V28 manifest/temporal preflight failed: {checks}")
    return VerifiedInputs(protocol.paths, checks, metadata)


def verify_macro_bundle(protocol: V28Protocol, verified: VerifiedInputs) -> MacroBundle:
    """Replay all three official responses and match the sealed normalized Parquet."""
    stlfsi = pd.read_parquet(
        verified.paths["stlfsi"],
        columns=protocol.payload["inputs"]["stlfsi"]["read_columns"],
    )
    monetary = pd.read_parquet(
        verified.paths["cbr_monetary"],
        columns=protocol.payload["inputs"]["cbr_monetary"]["read_columns"],
    )
    coverage = pd.read_parquet(
        verified.paths["macro_coverage"],
        columns=protocol.payload["inputs"]["macro_coverage"]["read_columns"],
    )
    with gzip.open(verified.paths["macro_raw_archive"], "rt", encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream]
    kinds = [record["kind"] for record in records]
    if kinds != ["fred_stlfsi4_csv", "cbr_ruonia_html", "cbr_key_rate_soap_xml"]:
        raise ValueError("V28 macro raw archive response order drifted")
    contents: list[bytes] = []
    raw_checks: dict[str, bool] = {}
    for index, record in enumerate(records):
        content = base64.b64decode(record["content"])
        contents.append(content)
        raw_checks[f"macro_raw_{index}_bytes"] = len(content) == int(
            record["response_bytes"]
        )
        raw_checks[f"macro_raw_{index}_sha256"] = (
            macro_v1.sha256_bytes(content) == record["response_sha256"]
        )
    source_protocol = macro_v3.load_protocol()
    parsed_stlfsi = macro_v1.parse_stlfsi(contents[0], source_protocol)
    retrieved = pd.Timestamp(records[0]["retrieved_at_utc"]).tz_convert("UTC")
    parsed_stlfsi["retrieved_at_utc"] = pd.Series(
        [retrieved] * len(parsed_stlfsi), dtype="datetime64[ms, UTC]"
    )
    parsed_stlfsi = parsed_stlfsi.loc[:, list(stlfsi.columns)]
    pd.testing.assert_frame_equal(parsed_stlfsi, stlfsi, check_dtype=True, check_exact=True)
    parsed_monetary = macro_v3.parse_monetary(contents[1], contents[2], source_protocol)
    pd.testing.assert_frame_equal(parsed_monetary, monetary, check_dtype=True, check_exact=True)
    macro_v1._assert_source_only_schema(
        {"stlfsi": stlfsi, "cbr_monetary": monetary, "coverage": coverage}
    )
    key_rate = monetary.loc[monetary["series_id"].eq("key_rate")].copy()
    key_rate["key_rate_percent"] = pd.to_numeric(
        key_rate["value"], errors="raise"
    ).astype(float)
    ruonia = monetary.loc[monetary["series_id"].eq("ruonia")].copy()
    ruonia["ruonia_percent"] = pd.to_numeric(ruonia["value"], errors="raise").astype(float)
    checks = {
        **raw_checks,
        "macro_raw_replay_stlfsi_exact": True,
        "macro_raw_replay_monetary_exact": True,
        "macro_source_schema_outcome_free": True,
        "stlfsi_rows_exact": len(stlfsi) == 312 and int(stlfsi["complete"].sum()) == 312,
        "key_rate_rows_exact": len(key_rate) == 1065,
        "ruonia_rows_exact": len(ruonia) == 1478,
        "ruonia_explicit_timing_exact": int(ruonia["available_at"].notna().sum()) == 78,
        "ruonia_unknown_timing_exact": int(ruonia["available_at"].isna().sum()) == 1400,
        "all_nonmissing_macro_availability_pre2018": bool(
            pd.concat([stlfsi["available_at"], monetary["available_at"]], ignore_index=True)
            .dropna()
            .lt(pd.Timestamp(PROTECTED_FROM, tz=MOSCOW).tz_convert("UTC"))
            .all()
        ),
        "ruonia_unknown_never_inferred": bool(
            ruonia.loc[ruonia["publication_date"].isna(), "available_at"].isna().all()
            and ruonia.loc[
                ruonia["publication_date"].isna(), "availability_rule"
            ].eq("publication_date_unavailable_no_inference").all()
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"V28 macro replay/coverage failed: {checks}")
    return MacroBundle(
        stlfsi=stlfsi.sort_values("available_at", kind="mergesort", ignore_index=True),
        key_rate=key_rate.sort_values("available_at", kind="mergesort", ignore_index=True),
        ruonia=ruonia.sort_values("observation_date", kind="mergesort", ignore_index=True),
        coverage=coverage,
        checks=checks,
        raw_records=len(records),
    )


def _state_counts(frame: pd.DataFrame) -> dict[str, int]:
    combined = frame["combined_state"].value_counts()
    stress = frame["stlfsi_state"].value_counts()
    return {
        "weekly_decisions": int(len(frame)),
        "pass_both": int(combined.get("pass_both", 0)),
        "cash_stlfsi_above_average": int(
            combined.get("cash_stlfsi_above_average", 0)
        ),
        "cash_stlfsi_missing_or_stale": int(
            combined.get("cash_stlfsi_missing_or_stale", 0)
        ),
        "cash_key_rate_at_least_20": int(
            combined.get("cash_key_rate_at_least_20", 0)
        ),
        "cash_key_rate_missing_or_stale": int(
            combined.get("cash_key_rate_missing_or_stale", 0)
        ),
        "raw_stlfsi_pass": int(stress.get("pass_stlfsi", 0)),
        "raw_stlfsi_above": int(stress.get("cash_stlfsi_above_average", 0)),
        "raw_stlfsi_missing_or_stale": int(
            stress.get("cash_stlfsi_missing_or_stale", 0)
        ),
    }


def apply_frozen_governors(
    weekly_weights: pd.DataFrame,
    macro: MacroBundle,
    *,
    expected_all: Mapping[str, int] = EXPECTED_ALL_STATES,
    expected_validation: Mapping[str, int] = EXPECTED_VALIDATION_STATES,
) -> GovernorBuild:
    """Apply byte-equivalent V25/V27 binary state semantics to pre-2018 decisions."""
    required = {"decision_date", "asset", "target_weight", "provenance"}
    if missing := required - set(weekly_weights.columns):
        raise ValueError(f"V28 weekly weights lack columns: {sorted(missing)}")
    weights = weekly_weights.copy()
    weights["decision_date"] = pd.to_datetime(
        weights["decision_date"], errors="raise"
    ).dt.normalize()
    if (
        weights.duplicated(["decision_date", "asset"]).any()
        or weights.groupby("decision_date")["asset"].nunique().ne(len(v12.ASSETS)).any()
    ):
        raise ValueError("V28 weekly snapshots are incomplete")
    decisions = weights.loc[:, ["decision_date"]].drop_duplicates().sort_values(
        "decision_date", kind="mergesort", ignore_index=True
    )
    decisions["decision_at"] = (
        decisions["decision_date"].dt.tz_localize(MOSCOW)
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).dt.tz_convert("UTC")
    stress_source = macro.stlfsi.loc[
        :, ["observation_date", "available_at", "complete", "stress_state"]
    ].rename(
        columns={
            "observation_date": "stlfsi_observation_date",
            "available_at": "stlfsi_available_at",
        }
    )
    governor = pd.merge_asof(
        decisions.sort_values("decision_at", kind="mergesort"),
        stress_source.sort_values("stlfsi_available_at", kind="mergesort"),
        left_on="decision_at",
        right_on="stlfsi_available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    governor["stlfsi_age_calendar_days"] = (
        governor["decision_date"] - governor["stlfsi_observation_date"]
    ).dt.days
    stress_fresh = (
        governor["stlfsi_available_at"].notna()
        & governor["stlfsi_available_at"].le(governor["decision_at"])
        & governor["stlfsi_age_calendar_days"].between(
            0, STLFSI_MAXIMUM_AGE_DAYS, inclusive="both"
        )
        & governor["complete"].eq(True)
    )
    governor["stlfsi_state"] = "cash_stlfsi_missing_or_stale"
    governor.loc[
        stress_fresh & governor["stress_state"].eq("above_average"), "stlfsi_state"
    ] = "cash_stlfsi_above_average"
    governor.loc[
        stress_fresh & governor["stress_state"].eq("normal_or_below"), "stlfsi_state"
    ] = "pass_stlfsi"
    key_source = macro.key_rate.loc[
        :, ["observation_date", "available_at", "key_rate_percent"]
    ].rename(
        columns={
            "observation_date": "key_rate_observation_date",
            "available_at": "key_rate_available_at",
        }
    )
    governor = pd.merge_asof(
        governor.sort_values("decision_at", kind="mergesort"),
        key_source.sort_values("key_rate_available_at", kind="mergesort"),
        left_on="decision_at",
        right_on="key_rate_available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    governor["key_rate_age_calendar_days"] = (
        governor["decision_date"] - governor["key_rate_observation_date"]
    ).dt.days
    key_fresh = (
        governor["key_rate_available_at"].notna()
        & governor["key_rate_available_at"].le(governor["decision_at"])
        & governor["key_rate_age_calendar_days"].between(
            0, KEY_RATE_MAXIMUM_AGE_DAYS, inclusive="both"
        )
    )
    governor["combined_state"] = "cash_key_rate_missing_or_stale"
    governor.loc[
        key_fresh & governor["stlfsi_state"].eq("cash_stlfsi_above_average"),
        "combined_state",
    ] = "cash_stlfsi_above_average"
    governor.loc[
        key_fresh & governor["stlfsi_state"].eq("cash_stlfsi_missing_or_stale"),
        "combined_state",
    ] = "cash_stlfsi_missing_or_stale"
    governor.loc[
        key_fresh
        & governor["stlfsi_state"].eq("pass_stlfsi")
        & governor["key_rate_percent"].ge(KEY_RATE_BOUNDARY_PERCENT),
        "combined_state",
    ] = "cash_key_rate_at_least_20"
    governor.loc[
        key_fresh
        & governor["stlfsi_state"].eq("pass_stlfsi")
        & governor["key_rate_percent"].lt(KEY_RATE_BOUNDARY_PERCENT),
        "combined_state",
    ] = "pass_both"
    governor["risk_scale"] = governor["combined_state"].eq("pass_both").astype(float)
    governed = weights.merge(
        governor.loc[
            :,
            [
                "decision_date",
                "decision_at",
                "stlfsi_observation_date",
                "stlfsi_available_at",
                "stlfsi_age_calendar_days",
                "stress_state",
                "stlfsi_state",
                "key_rate_observation_date",
                "key_rate_available_at",
                "key_rate_age_calendar_days",
                "key_rate_percent",
                "combined_state",
                "risk_scale",
            ],
        ],
        on="decision_date",
        how="left",
        validate="many_to_one",
    )
    governed["pre_governor_target_weight"] = pd.to_numeric(
        governed["target_weight"], errors="raise"
    ).astype(float)
    governed["target_weight"] = governed["pre_governor_target_weight"] * governed["risk_scale"]
    governed["provenance"] = (
        governed["provenance"].astype("string")
        + "|pre2018_frozen_v25_v27_state="
        + governed["combined_state"].astype("string")
    )
    all_counts = _state_counts(governor)
    validation = governor.loc[
        governor["decision_date"].between(VALIDATION_START, VALIDATION_END)
    ]
    validation_counts = _state_counts(validation)
    checks = {
        "governor_complete_four_asset_snapshots": bool(
            governed.groupby("decision_date")["asset"].nunique().eq(len(v12.ASSETS)).all()
        ),
        "governor_available_at_not_after_decision": bool(
            governor.loc[
                governor["stlfsi_available_at"].notna(), "stlfsi_available_at"
            ].le(governor.loc[governor["stlfsi_available_at"].notna(), "decision_at"]).all()
            and governor.loc[
                governor["key_rate_available_at"].notna(), "key_rate_available_at"
            ].le(governor.loc[governor["key_rate_available_at"].notna(), "decision_at"]).all()
        ),
        "governor_never_increases_v12_risk": bool(
            governed["target_weight"]
            .abs()
            .le(governed["pre_governor_target_weight"].abs() + 1e-12)
            .all()
        ),
        "governor_all_source_only_counts_exact": all_counts
        == {str(key): int(value) for key, value in expected_all.items()},
        "governor_validation_source_only_counts_exact": validation_counts
        == {str(key): int(value) for key, value in expected_validation.items()},
        "key_rate_extreme_state_matches_predeclared_count": int(
            validation_counts["cash_key_rate_at_least_20"]
        )
        == int(expected_validation["cash_key_rate_at_least_20"]),
    }
    if not all(checks.values()):
        raise ValueError(
            f"V28 frozen governor failure: {checks}, {all_counts}, {validation_counts}"
        )
    return GovernorBuild(
        weights=governed.sort_values(
            ["decision_date", "asset"], kind="mergesort", ignore_index=True
        ),
        governor=governor.sort_values("decision_date", kind="mergesort", ignore_index=True),
        checks=checks,
        all_counts=all_counts,
        validation_counts=validation_counts,
    )


def build_levered_execution_targets(
    governed_weights: pd.DataFrame, active_map: pd.DataFrame
) -> v12.TargetBuild:
    """Map unlevered governed weights causally, then apply the frozen exact 2x multiplier."""
    base = v12.build_execution_targets(
        governed_weights,
        active_map,
        oos_start=VALIDATION_START,
        oos_end=VALIDATION_END,
    )
    targets = base.targets.copy()
    targets["pre_leverage_target_weight"] = pd.to_numeric(
        targets["target_weight"], errors="raise"
    ).astype(float)
    targets["target_weight"] = targets["pre_leverage_target_weight"] * LEVERAGE_MULTIPLIER
    gross = targets.groupby("effective_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    if gross.gt(v15.MAXIMUM_GROSS + 1e-12).any():
        raise ValueError("V28 mapped target exceeds frozen 2x gross cap")
    return v12.TargetBuild(
        targets=targets.sort_values(
            ["effective_date", "asset_code"], kind="mergesort", ignore_index=True
        ),
        decision_audit=base.decision_audit,
        weekly_decisions=base.weekly_decisions,
        roll_decisions=base.roll_decisions,
    )


def build_levered_weekly_weights(governed_weights: pd.DataFrame) -> pd.DataFrame:
    """Create an audit-only exact 2x weekly view without changing mapped timing."""
    output = governed_weights.copy()
    output["pre_leverage_target_weight"] = pd.to_numeric(
        output["target_weight"], errors="raise"
    ).astype(float)
    output["target_weight"] = output["pre_leverage_target_weight"] * LEVERAGE_MULTIPLIER
    output["provenance"] = output["provenance"].astype("string") + "|sealed_exact_two_times"
    gross = output.groupby("decision_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    if gross.gt(v15.MAXIMUM_GROSS + 1e-12).any():
        raise ValueError("V28 weekly weights exceed frozen 2x gross cap")
    return output.sort_values(["decision_date", "asset"], kind="mergesort", ignore_index=True)


def _annual_daily_returns(ledger: pd.DataFrame) -> dict[str, float]:
    daily = pd.to_numeric(ledger["ending_cash"], errors="raise").astype(float) / pd.to_numeric(
        ledger["starting_cash"], errors="raise"
    ).astype(float) - 1.0
    dates = pd.to_datetime(ledger["session_date"], errors="raise").dt.normalize()
    return {
        str(year): float((1.0 + daily.loc[dates.dt.year.eq(year)]).prod() - 1.0)
        for year in range(2013, 2018)
        if dates.dt.year.eq(year).any()
    }


def _annual_level_returns(dates: pd.Series, levels: pd.Series) -> dict[str, float]:
    ordered = pd.DataFrame(
        {
            "date": pd.to_datetime(dates, errors="raise").dt.normalize(),
            "level": pd.to_numeric(levels, errors="raise").astype(float),
        }
    ).sort_values("date", kind="mergesort")
    output: dict[str, float] = {}
    for year in range(2013, 2018):
        start = pd.Timestamp(f"{year}-01-01")
        end = pd.Timestamp(f"{year}-12-31")
        before = ordered.loc[ordered["date"].lt(start), "level"]
        within = ordered.loc[ordered["date"].between(start, end), "level"]
        if within.empty:
            continue
        starting = float(before.iloc[-1]) if not before.empty else v12.INITIAL_CASH
        output[str(year)] = float(within.iloc[-1] / starting - 1.0)
    return output


def evaluate_conservative_collateral(
    result: FuturesPortfolioLedgerResult,
    ruonia: pd.DataFrame,
    *,
    expected_calendar: Mapping[str, int] = EXPECTED_COLLATERAL_CALENDAR,
) -> CollateralEvaluation:
    """Credit only explicitly timed RUONIA; unknown timing remains missing and earns nothing."""
    required = {
        "session_date",
        "ending_cash",
        "intraday_adverse_equity",
        "modeled_initial_margin",
    }
    if missing := required - set(result.ledger.columns):
        raise ValueError(f"V28 ledger lacks collateral fields: {sorted(missing)}")
    ledger = result.ledger.sort_values("session_date", kind="mergesort", ignore_index=True)
    if ledger.empty:
        raise ValueError("V28 collateral requires a nonempty ledger")
    dates = pd.to_datetime(ledger["session_date"], errors="raise").dt.normalize()
    if dates.duplicated().any() or dates.ge(PROTECTED_FROM).any():
        raise ValueError("V28 collateral ledger date boundary failed")
    source = ruonia.loc[
        ruonia["available_at"].notna(),
        ["observation_date", "available_at", "ruonia_percent"],
    ].sort_values("available_at", kind="mergesort")
    sessions = pd.DataFrame(
        {
            "session_number": np.arange(len(ledger)),
            "session_start_utc": dates.dt.tz_localize(MOSCOW).dt.tz_convert("UTC"),
        }
    )
    lookup = pd.merge_asof(
        sessions.sort_values("session_start_utc", kind="mergesort"),
        source,
        left_on="session_start_utc",
        right_on="available_at",
        direction="backward",
        allow_exact_matches=True,
    ).sort_values("session_number", kind="mergesort")
    if lookup["available_at"].gt(lookup["session_start_utc"]).fillna(False).any():
        raise ValueError("V28 collateral lookup used future RUONIA")
    cumulative = np.zeros(len(ledger), dtype=float)
    credited = np.zeros(len(ledger), dtype=float)
    audit_rows: list[dict[str, Any]] = []
    for index in range(len(ledger) - 1):
        raw_start = pd.Timestamp(dates.iloc[index])
        accrual_start = max(raw_start, VALIDATION_START)
        accrual_end = pd.Timestamp(dates.iloc[index + 1])
        days = max((accrual_end - accrual_start).days, 0)
        rate = lookup.iloc[index]["ruonia_percent"]
        available_at = lookup.iloc[index]["available_at"]
        observation_date = lookup.iloc[index]["observation_date"]
        recognized = days > 0 and pd.notna(rate) and pd.notna(available_at)
        ending_cash = float(ledger.iloc[index]["ending_cash"])
        adverse_equity = float(ledger.iloc[index]["intraday_adverse_equity"])
        margin = float(ledger.iloc[index]["modeled_initial_margin"])
        conservative_equity = max(min(ending_cash, adverse_equity), 0.0)
        operational_buffer = conservative_equity * OPERATIONAL_BUFFER_FRACTION
        eligible = max(
            conservative_equity
            - v15.MARGIN_BUFFER_MULTIPLIER * max(margin, 0.0)
            - operational_buffer,
            0.0,
        )
        applied_percent = float(rate) * RUONIA_APPLIED_FRACTION if recognized else np.nan
        interest = (
            eligible * applied_percent / 100.0 * float(days) / DAY_COUNT_DENOMINATOR
            if recognized
            else 0.0
        )
        cumulative[index + 1] = cumulative[index] + interest
        credited[index + 1] = interest
        audit_rows.append(
            {
                "accrual_start_session": raw_start,
                "accrual_start_clipped": accrual_start,
                "accrual_end_session": accrual_end,
                "calendar_days": days,
                "ruonia_observation_date": observation_date,
                "ruonia_available_at": available_at,
                "ruonia_percent": None if pd.isna(rate) else float(rate),
                "credit_status": (
                    "credited_explicit_availability"
                    if recognized
                    else "no_credit_unknown_availability"
                ),
                "applied_percent": applied_percent,
                "conservative_equity": conservative_equity,
                "modeled_initial_margin": margin,
                "margin_reserve": v15.MARGIN_BUFFER_MULTIPLIER * max(margin, 0.0),
                "operational_buffer": operational_buffer,
                "eligible_balance": eligible,
                "interest_rub": interest,
                "cumulative_interest_rub": cumulative[index + 1],
            }
        )
    audit = pd.DataFrame(audit_rows)
    positive = audit["calendar_days"].gt(0)
    recognized = positive & audit["credit_status"].eq("credited_explicit_availability")
    unknown = positive & audit["credit_status"].eq("no_credit_unknown_availability")
    observed_calendar = {
        "execution_sessions": int(len(ledger)),
        "accrual_intervals": int(len(audit)),
        "accrual_calendar_days": int(audit.loc[positive, "calendar_days"].sum()),
        "known_rate_intervals": int(recognized.sum()),
        "unknown_no_credit_intervals": int(unknown.sum()),
        "known_rate_calendar_days": int(audit.loc[recognized, "calendar_days"].sum()),
    }
    expected = {str(key): int(value) for key, value in expected_calendar.items()}
    checks = {
        "collateral_calendar_counts_exact": observed_calendar == expected,
        "unknown_ruonia_never_zero_imputed": bool(
            audit.loc[unknown, "ruonia_percent"].isna().all()
            and audit.loc[unknown, "applied_percent"].isna().all()
        ),
        "unknown_ruonia_receives_no_credit": bool(
            audit.loc[unknown, "interest_rub"].eq(0.0).all()
        ),
        "recognized_ruonia_is_causal": bool(
            audit.loc[recognized, "ruonia_available_at"]
            .le(
                audit.loc[recognized, "accrual_start_session"]
                .dt.tz_localize(MOSCOW)
                .dt.tz_convert("UTC")
            )
            .all()
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"V28 collateral invariant failure: {checks}, {observed_calendar}")
    combined = ledger.copy()
    combined["collateral_interest_credited"] = credited
    combined["cumulative_collateral_interest"] = cumulative
    combined["combined_ending_equity"] = combined["ending_cash"].astype(float) + cumulative
    performance = ledger_engine._performance_metrics(
        combined["combined_ending_equity"], combined["session_date"], v12.INITIAL_CASH
    )
    annual = _annual_level_returns(
        combined["session_date"], combined["combined_ending_equity"]
    )
    metrics: dict[str, Any] = {
        **performance,
        "annual_returns": annual,
        "positive_years": int(sum(value > 0.0 for value in annual.values())),
        "worst_year": min(annual.values()) if annual else None,
        "collateral_income_rub": float(cumulative[-1]),
        "collateral_return_contribution": float(cumulative[-1] / v12.INITIAL_CASH),
        **observed_calendar,
        "applied_rate_fraction": RUONIA_APPLIED_FRACTION,
        "operational_buffer_fraction": OPERATIONAL_BUFFER_FRACTION,
        "interest_reinvested_into_sizing": False,
        "interest_compounded_into_eligible_balance": False,
        "unknown_availability_rate_imputed": False,
        "metrics_valid": bool(result.execution_complete),
    }
    return CollateralEvaluation(audit, combined, metrics, checks)


def _scenario_payload(
    result: FuturesPortfolioLedgerResult,
    market: pd.DataFrame,
    settings: dict[str, float],
    ruonia: pd.DataFrame,
) -> tuple[dict[str, Any], CollateralEvaluation]:
    futures = v12.scenario_metrics(result, market, settings)
    annual = _annual_daily_returns(result.ledger)
    futures["annual_returns"] = annual
    futures["positive_years"] = int(sum(value > 0.0 for value in annual.values()))
    futures["worst_year"] = min(annual.values()) if annual else None
    collateral = evaluate_conservative_collateral(result, ruonia)
    combined = dict(collateral.metrics)
    reserve = futures["terminal_exit_cost_reserve"]
    combined["post_terminal_reserve_total_return"] = (
        None
        if reserve is None
        else (
            float(result.metrics["ending_cash"])
            + float(combined["collateral_income_rub"])
            - float(reserve)
        )
        / v12.INITIAL_CASH
        - 1.0
    )
    combined["maximum_post_mark_gross_leverage"] = float(
        result.ledger["gross_leverage"].max()
    )
    combined["maximum_2x_margin_to_starting_cash"] = float(
        (
            v15.MARGIN_BUFFER_MULTIPLIER
            * result.ledger["modeled_initial_margin"]
            / result.ledger["starting_cash"]
        ).max()
    )
    collateral_summary = {
        key: value
        for key, value in combined.items()
        if key
        in {
            "collateral_income_rub",
            "collateral_return_contribution",
            "accrual_intervals",
            "accrual_calendar_days",
            "known_rate_intervals",
            "unknown_no_credit_intervals",
            "known_rate_calendar_days",
            "applied_rate_fraction",
            "unknown_availability_rate_imputed",
        }
    }
    return (
        {
            "settings": settings,
            "futures_only": futures,
            "collateral": collateral_summary,
            "combined": combined,
        },
        collateral,
    )


def _assessment(
    results: Mapping[str, Mapping[str, Any]], checks: Mapping[str, bool]
) -> dict[str, Any]:
    primary = results["primary"]["combined"]
    common = {
        "every_input_source_governor_collateral_and_temporal_check_true": all(checks.values()),
        "all_scenarios_execution_complete": all(
            bool(item["futures_only"]["execution_complete"]) for item in results.values()
        ),
        "zero_critical_failures_and_unresolved_halts": all(
            int(item["futures_only"]["critical_failure_count"]) == 0
            and int(item["futures_only"]["unresolved_halt_count"]) == 0
            for item in results.values()
        ),
        "all_scenarios_MDD_at_most_0_30": all(
            float(item["combined"]["maximum_drawdown"]) <= 0.30
            for item in results.values()
        ),
        "primary_sharpe_at_least_0_80": float(primary["sharpe"]) >= 0.80,
        "primary_worst_year_at_least_minus_0_15": float(primary["worst_year"]) >= -0.15,
        "primary_positive_years_at_least_4_of_5": int(primary["positive_years"]) >= 4
        and len(primary["annual_returns"]) == 5,
        "no_order_time_gross_participation_or_margin_breach": all(
            float(item["futures_only"]["maximum_participation"])
            <= v12.MAXIMUM_PARTICIPATION + 1e-12
            and int(item["futures_only"]["gross_limit_rejection_count"]) == 0
            and int(item["futures_only"]["initial_margin_rejection_count"]) == 0
            and float(item["futures_only"]["ending_cash"]) > 0.0
            for item in results.values()
        ),
    }
    support_20_conditions = {
        **common,
        "all_scenarios_CAGR_at_least_0_20": all(
            float(item["combined"]["cagr"]) >= 0.20 for item in results.values()
        ),
    }
    support_50_conditions = {
        **common,
        "all_scenarios_CAGR_at_least_0_50": all(
            float(item["combined"]["cagr"]) >= 0.50 for item in results.values()
        ),
    }
    support_20 = all(support_20_conditions.values())
    support_50 = all(support_50_conditions.values())
    return {
        "support_20_percent": {
            "conditions": support_20_conditions,
            "passed": support_20,
        },
        "support_50_percent": {
            "conditions": support_50_conditions,
            "passed": support_50,
        },
        "verdict": (
            "PASS_UNSEEN_20_RESEARCH_ONLY" if support_20 else "FAIL_UNSEEN_20"
        ),
        "live_trading_allowed": False,
        "full_point_in_time_confirmation": False,
    }


def _report_text(payload: Mapping[str, Any]) -> str:
    lines = [
        "# V28 frozen V27 economics on unseen pre-2018 MOEX history",
        "",
        f"Verdict: **{payload['assessment']['verdict']}** (research-only; live forbidden).",
        "",
        "| Scenario | Combined return | CAGR | Sharpe | MDD | Worst year | Costs RUB |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("primary", "doubled", "stress"):
        item = payload["scenarios"][name]
        combined = item["combined"]
        futures = item["futures_only"]
        lines.append(
            f"| {name} | {combined['total_return']:.4%} | {combined['cagr']:.4%} | "
            f"{combined['sharpe']:.3f} | {combined['maximum_drawdown']:.4%} | "
            f"{combined['worst_year']:.4%} | {futures['total_cost']:.2f} |"
        )
    lines.extend(["", "## Primary annual returns", ""])
    for year, value in payload["scenarios"]["primary"]["combined"][
        "annual_returns"
    ].items():
        lines.append(f"- {year}: {value:.4%}")
    counts = payload["counts"]
    primary = payload["scenarios"]["primary"]
    lines.extend(
        [
            "",
            "## Causal coverage",
            "",
            f"- Weekly validation decisions: {counts['validation_weekly_decisions']}",
            f"- Both governors pass: {counts['validation_pass_both']}",
            f"- STLFSI4 cash: {counts['validation_cash_stlfsi4']}",
            f"- Missing/stale key-rate cash: {counts['validation_cash_key_rate_missing']}",
            f"- Key-rate >=20% cash: {counts['validation_cash_key_rate_extreme']}",
            f"- Nonzero mapped targets: {counts['nonzero_targets']}",
            f"- Complete next-open dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            f"- RUONIA recognized intervals: "
            f"{primary['collateral']['known_rate_intervals']}/"
            f"{primary['collateral']['accrual_intervals']}",
            f"- RUONIA intervals deliberately receiving no credit: "
            f"{primary['collateral']['unknown_no_credit_intervals']}",
            "",
            "The strategy, leverage, governors, costs and target gates were frozen before "
            "the first 2013-2017 return. STLFSI4 is current-vintage, the 20% key-rate state "
            "does not occur in this period, most RUONIA publication timing is unknown, and "
            "historical exchange specs/fees remain conservative proxies.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(
    output_root: Path,
    config_path: Path = DEFAULT_CONFIG,
) -> Path:
    """Execute exactly one immutable V28 pre-2018 validation run."""
    protocol = load_protocol(config_path)
    verified = verify_inputs(protocol)
    macro = verify_macro_bundle(protocol, verified)
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
    checks = {**verified.checks, **macro.checks}
    scores = v12.build_trend_scores(panel)
    weekly_v12 = v12.build_weekly_weights(panel, scores)
    governed = apply_frozen_governors(weekly_v12, macro)
    checks.update(governed.checks)
    levered_weekly = build_levered_weekly_weights(governed.weights)
    target_build = build_levered_execution_targets(governed.weights, active)
    mapped_gross = target_build.targets.groupby("effective_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    checks["mapped_target_gross_at_most_two"] = bool(
        mapped_gross.le(v15.MAXIMUM_GROSS + 1e-12).all()
    )
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
    execution_dates = pd.DatetimeIndex(
        execution_market["session_date"].drop_duplicates().sort_values()
    )
    checks["execution_predecessor_exact"] = predecessor == EXPECTED_PREDECESSOR
    checks["execution_session_count_exact"] = (
        len(execution_dates) == EXPECTED_COLLATERAL_CALENDAR["execution_sessions"]
    )
    coverage = v12.execution_coverage(market, target_build.targets)
    nonzero_targets = int(target_build.targets["target_weight"].abs().gt(1e-12).sum())
    covered_nonzero_targets = int(coverage["execution_dependencies_complete"].sum())
    checks["execution_coverage_report_complete"] = len(coverage) == nonzero_targets
    if not all(checks.values()):
        raise ValueError(f"V28 pre-execution invariant failure: {checks}")

    scenario_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    collateral_outputs: dict[str, CollateralEvaluation] = {}
    scenario_results: dict[str, dict[str, Any]] = {}
    for name, settings in v12._scenario_settings(protocol.payload).items():
        result = v15.run_levered_portfolio_ledger(
            execution_market,
            target_build.targets,
            v26.CapacityAwareLeveredLedgerConfig(
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name], collateral_outputs[name] = _scenario_payload(
            result, execution_market, settings, macro.ruonia
        )
        checks.update(
            {
                f"{name}_{key}": value
                for key, value in collateral_outputs[name].checks.items()
            }
        )
    counts = {
        "source_panel_rows": int(len(panel)),
        "source_active_map_rows": int(len(active)),
        "source_contract_observation_rows": int(len(observations)),
        "source_spec_rows": int(len(specs)),
        "stlfsi_source_rows": int(len(macro.stlfsi)),
        "key_rate_source_rows": int(len(macro.key_rate)),
        "ruonia_source_rows": int(len(macro.ruonia)),
        "macro_raw_records": macro.raw_records,
        "all_weekly_decisions": governed.all_counts["weekly_decisions"],
        "validation_weekly_decisions": governed.validation_counts["weekly_decisions"],
        "validation_pass_both": governed.validation_counts["pass_both"],
        "validation_cash_stlfsi4": governed.validation_counts[
            "cash_stlfsi_above_average"
        ]
        + governed.validation_counts["cash_stlfsi_missing_or_stale"],
        "validation_cash_key_rate_missing": governed.validation_counts[
            "cash_key_rate_missing_or_stale"
        ],
        "validation_cash_key_rate_extreme": governed.validation_counts[
            "cash_key_rate_at_least_20"
        ],
        "mapped_weekly_decisions": target_build.weekly_decisions,
        "roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": int(len(target_build.targets)),
        "nonzero_targets": nonzero_targets,
        "covered_nonzero_targets": covered_nonzero_targets,
    }
    assessment = _assessment(scenario_results, checks)
    identity = {
        "protocol_sha256": protocol.config_sha256,
        "frozen_parent_identity": protocol.payload["frozen_parent_identity"],
        "input_sha256": {
            name: declaration["sha256"] for name, declaration in inputs.items()
        },
        "implementation_sha256": protocol.dependency_hashes,
        "protected_from": PROTECTED_FROM.date().isoformat(),
        "contains_2018_or_later_market_prices_returns_targets_or_pnl": False,
        "contains_2026_prices_returns_targets_or_pnl": False,
    }
    payload: dict[str, Any] = {
        "protocol_id": protocol.payload["protocol_id"],
        "protocol_sha256": protocol.config_sha256,
        "research_only": True,
        "unseen_market_period_external_validation": True,
        "full_point_in_time_confirmation": False,
        "live_trading_allowed": False,
        "checks": checks,
        "input_metadata": verified.metadata,
        "identity": identity,
        "counts": counts,
        "scenarios": scenario_results,
        "assessment": assessment,
        "limitations": protocol.payload["limitations"],
    }
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v28_pre2018_unseen_{timestamp}_{protocol.config_sha256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V28 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(protocol.config_path, temporary / "resolved_protocol.yaml")
        v12._write_parquet(temporary / "scores.parquet", scores)
        v12._write_parquet(temporary / "weekly_v12_weights.parquet", weekly_v12)
        v12._write_parquet(
            temporary / "weekly_v28_governed_weights.parquet", governed.weights
        )
        v12._write_parquet(
            temporary / "weekly_v28_levered_weights.parquet", levered_weekly
        )
        governed.governor.to_csv(
            temporary / "combined_governor.csv", index=False, encoding="utf-8-sig"
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
        (temporary / "report.md").write_text(_report_text(payload), encoding="utf-8-sig")
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
