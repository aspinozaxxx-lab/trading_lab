"""Build an outcome-free active calendar-spread panel from sealed MOEX sources."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures import moex_calendar_spread_source as source_v1
from market_lab.futures import moex_calendar_spread_source_v3 as source_v3
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = source_v1.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = (
    PROJECT_ROOT / "configs/moex_calendar_spread_derived_v1.yaml"
)
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
ASSETS: Final[tuple[str, ...]] = source_v1.ASSETS
EXPECTED_CLEAN_SPREADS: Final[dict[str, int]] = {
    "SI": 16,
    "RI": 13,
    "BR": 51,
    "MIX": 18,
}
EXPECTED_CANDIDATE_ROWS: Final[dict[str, int]] = {
    "SI": 1986,
    "RI": 1994,
    "BR": 3096,
    "MIX": 1205,
}
EXPECTED_ACTIVE_ROWS: Final[dict[str, int]] = {
    "SI": 1129,
    "RI": 918,
    "BR": 1200,
    "MIX": 1119,
}
EXPECTED_TOTAL_CANDIDATE_ROWS: Final[int] = 8281
EXPECTED_TOTAL_ACTIVE_ROWS: Final[int] = 4366
EXPECTED_ZERO_LOCKED_ACTIVE_ROWS: Final[int] = 2
EXPECTED_STRICT_POSITIVE_WIDTH_ACTIVE_ROWS: Final[int] = 4364
EXPECTED_POINT_VALUES_EQUAL_ACTIVE_ROWS: Final[int] = 1218
FORBIDDEN_COLUMN_TOKENS: Final[tuple[str, ...]] = (
    "return",
    "target",
    "label",
    "signal",
    "strategy",
    "equity",
    "pnl",
    "profit",
)
SPEC_FIELDS: Final[tuple[str, ...]] = (
    "sizing_observed_session_date",
    "sizing_point_value",
    "sizing_notional",
    "sizing_tick_cash_value",
    "modeled_initial_margin",
    "expected_buffered_initial_margin",
    "sizing_status",
    "sizing_usable",
    "tick_size",
    "conservative_fee_per_side",
    "approximate",
    "historical_exchange_exact",
    "broker_exact",
)
CANDIDATE_COLUMNS: Final[tuple[str, ...]] = (
    *source_v1.ARCHIVE_DAILY_COLUMNS,
    "series_start",
    "expiry_gap_days",
    "regular_adjacent_expiry",
    "near_expiration_matches_spread_last_trade",
    "days_to_near_expiration",
    "calendar_tenor_days",
    "candidate_count",
    "quote_width",
    "quote_midpoint",
    "strict_positive_quote_width",
    "zero_locked_quote",
)
ACTIVE_COLUMNS: Final[tuple[str, ...]] = (
    *CANDIDATE_COLUMNS,
    "near_contract_id",
    "far_contract_id",
    *(f"near_{field}" for field in SPEC_FIELDS),
    *(f"far_{field}" for field in SPEC_FIELDS),
    "both_sizing_usable",
    "spec_observations_strictly_prior",
    "gross_sizing_notional",
    "conservative_two_leg_fee_per_side",
    "conservative_two_leg_buffered_margin",
    "point_values_equal",
)
COVERAGE_COLUMNS: Final[tuple[str, ...]] = (
    "logical_asset",
    "clean_spreads",
    "candidate_rows",
    "active_rows",
    "active_unique_spreads",
    "first_active_date",
    "last_active_date",
    "maximum_calendar_gap_days",
    "minimum_days_to_near_expiration",
    "maximum_days_to_near_expiration",
    "zero_locked_active_rows",
    "strict_positive_width_active_rows",
    "both_sizing_usable_rows",
    "strictly_prior_spec_rows",
)


@dataclass(frozen=True, slots=True)
class DerivedProtocol:
    """Sealed source identities and structural derivation rules."""

    config_path: Path
    config_sha256: str
    payload: dict[str, Any]
    output_directory: Path
    source_directory: Path
    source_manifest_sha256: str
    spec_directory: Path
    spec_manifest_sha256: str
    spec_parquet_sha256: str
    dependency_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class DerivedTables:
    """Outcome-free candidate, active and coverage artifacts."""

    candidates: pd.DataFrame
    active: pd.DataFrame
    coverage: pd.DataFrame
    audit: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DerivedAudit:
    """Immutable artifact and exact logical rebuild checks."""

    checks: dict[str, bool]
    counts: dict[str, int]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"calendar-spread derived {label} must be a mapping")
    return value


def _safe_project_path(relative_value: str) -> Path:
    return source_v1._project_path(relative_value, "data")


def _counts(value: object, label: str) -> dict[str, int]:
    return {
        str(key): int(count)
        for key, count in _mapping(value, label).items()
    }


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> DerivedProtocol:
    """Verify the derived seal without reading source market values."""
    path = config_path.resolve()
    config_sha = source_v1.sha256_file(path)
    if source_v1._sidecar_sha(path) != config_sha:
        raise ValueError("calendar-spread derived protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("calendar-spread derived protocol must be a YAML object")
    source = _mapping(payload.get("calendar_spread_source"), "source")
    spec = _mapping(payload.get("causal_spec_proxy"), "spec proxy")
    rules = _mapping(payload.get("structural_rules"), "rules")
    preflight = _mapping(payload.get("source_only_preflight"), "preflight")
    output = _mapping(payload.get("output"), "output")
    dependencies = _mapping(
        payload.get("implementation_dependencies"), "dependencies"
    )
    if (
        payload.get("protocol_id") != "moex_calendar_spread_derived_source_v1"
        or payload.get("scope") != "source_derived_no_returns_targets_or_pnl"
        or payload.get("sealed_before_first_return_or_pnl") is not True
        or payload.get("live_trading_allowed") is not False
        or source.get("protocol_sha256")
        != "3d89c51fe674f3b55282aba808ad6f0336cae502956681203f02b0218022f19c"
        or source.get("manifest_sha256")
        != "94d5fab4b799ac9a73b359c7350df7ccd30572e6dba8b9ae8cf5d41f5080ee0b"
        or int(source.get("catalog_rows", -1)) != 110
        or int(source.get("archive_rows", -1)) != 10157
        or spec.get("manifest_sha256")
        != "b1cada60c44296641062bb6ca7c45d12fa4c5b261810e4bb100edae458eb20d3"
        or spec.get("parquet_sha256")
        != "8494235f8782a258ed86d448c1c57adf2d313062da06845211991bda2f76d682"
        or int(spec.get("rows", -1)) != 66052
        or rules.get("catalog_filter")
        != "regular_adjacent_and_near_expiration_matches_spread_last_trade"
        or rules.get("row_filter")
        != "reported_activity_and_inside_series_and_complete_uncrossed_quote"
        or rules.get("active_selection")
        != "minimum_nonnegative_days_to_near_expiration_per_asset_date"
        or rules.get("tie_policy") != "reject"
        or rules.get("locked_or_zero_quote_policy") != "preserve_and_flag"
        or rules.get("last_outside_range_policy") != "preserve_not_a_filter"
        or rules.get("spec_join")
        != "same_session_contract_id_with_strictly_prior_sizing_observation"
        or _counts(preflight.get("clean_spreads_by_asset"), "clean spreads")
        != EXPECTED_CLEAN_SPREADS
        or _counts(preflight.get("candidate_rows_by_asset"), "candidate rows")
        != EXPECTED_CANDIDATE_ROWS
        or _counts(preflight.get("active_rows_by_asset"), "active rows")
        != EXPECTED_ACTIVE_ROWS
        or int(preflight.get("candidate_rows", -1))
        != EXPECTED_TOTAL_CANDIDATE_ROWS
        or int(preflight.get("active_rows", -1)) != EXPECTED_TOTAL_ACTIVE_ROWS
        or int(preflight.get("active_tie_rows", -1)) != 0
        or int(preflight.get("zero_locked_active_rows", -1))
        != EXPECTED_ZERO_LOCKED_ACTIVE_ROWS
        or int(preflight.get("strict_positive_width_active_rows", -1))
        != EXPECTED_STRICT_POSITIVE_WIDTH_ACTIVE_ROWS
        or int(preflight.get("near_spec_missing_active_rows", -1)) != 0
        or int(preflight.get("far_spec_missing_active_rows", -1)) != 0
        or int(preflight.get("both_sizing_usable_active_rows", -1))
        != EXPECTED_TOTAL_ACTIVE_ROWS
        or int(preflight.get("strictly_prior_spec_active_rows", -1))
        != EXPECTED_TOTAL_ACTIVE_ROWS
        or int(preflight.get("point_values_equal_active_rows", -1))
        != EXPECTED_POINT_VALUES_EQUAL_ACTIVE_ROWS
        or int(preflight.get("approximate_specs_both_legs_rows", -1))
        != EXPECTED_TOTAL_ACTIVE_ROWS
        or int(preflight.get("historical_exchange_exact_both_legs_rows", -1)) != 0
        or int(preflight.get("broker_exact_both_legs_rows", -1)) != 0
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("calendar-spread derived protocol invariants drifted")
    source_directory = _safe_project_path(str(source["directory"]))
    spec_directory = _safe_project_path(str(spec["directory"]))
    output_directory = _safe_project_path(str(output["directory"]))
    if output_directory in {source_directory, spec_directory}:
        raise ValueError("calendar-spread derived output aliases an input")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency = PROJECT_ROOT / str(relative)
        digest = str(expected).lower()
        if source_v1.sha256_file(dependency) != digest:
            raise ValueError(f"calendar-spread derived dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    return DerivedProtocol(
        config_path=path,
        config_sha256=config_sha,
        payload=payload,
        output_directory=output_directory,
        source_directory=source_directory,
        source_manifest_sha256=str(source["manifest_sha256"]),
        spec_directory=spec_directory,
        spec_manifest_sha256=str(spec["manifest_sha256"]),
        spec_parquet_sha256=str(spec["parquet_sha256"]),
        dependency_hashes=dependency_hashes,
    )


def _verify_file(path: Path, declaration: Mapping[str, Any]) -> None:
    if (
        not path.is_file()
        or path.stat().st_size != int(declaration["bytes"])
        or source_v1.sha256_file(path) != str(declaration["sha256"])
    ):
        raise ValueError(f"calendar-spread derived input bytes drifted: {path}")
    if "rows" in declaration and pq.ParquetFile(path).metadata.num_rows != int(
        declaration["rows"]
    ):
        raise ValueError(f"calendar-spread derived input rows drifted: {path}")


def verify_and_load_inputs(
    protocol: DerivedProtocol,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Audit parent source bytes and load only the two declared market-value tables."""
    parent_protocol = source_v3.load_protocol()
    if (
        parent_protocol.config_sha256
        != protocol.payload["calendar_spread_source"]["protocol_sha256"]
        or parent_protocol.output_directory.resolve()
        != protocol.source_directory.resolve()
    ):
        raise ValueError("calendar-spread derived parent protocol identity drifted")
    parent_audit = source_v3.audit_bundle(parent_protocol)
    if not all(parent_audit.checks.values()):
        raise ValueError("calendar-spread derived parent source audit failed")
    source_manifest_path = protocol.source_directory / "manifest.json"
    if source_v1.sha256_file(source_manifest_path) != protocol.source_manifest_sha256:
        raise ValueError("calendar-spread derived source manifest drifted")
    source_manifest = json.loads(
        source_manifest_path.read_text(encoding="utf-8-sig")
    )
    for name in ("catalog", "public_archive_daily"):
        declaration = _mapping(source_manifest["artifacts"][name], name)
        _verify_file(protocol.source_directory / str(declaration["file"]), declaration)
    catalog = pd.read_parquet(protocol.source_directory / "catalog.parquet")
    archive = pd.read_parquet(
        protocol.source_directory / "public_archive_daily.parquet"
    )
    spec_manifest_path = protocol.spec_directory / "manifest.json"
    spec_path = protocol.spec_directory / "spec_proxy.parquet"
    if source_v1.sha256_file(spec_manifest_path) != protocol.spec_manifest_sha256:
        raise ValueError("calendar-spread derived spec manifest drifted")
    spec_manifest = json.loads(spec_manifest_path.read_text(encoding="utf-8-sig"))
    output_declaration = _mapping(
        _mapping(spec_manifest.get("output"), "spec output").get("parquet"),
        "spec parquet",
    )
    if (
        output_declaration.get("sha256") != protocol.spec_parquet_sha256
        or int(output_declaration.get("rows", -1)) != 66052
        or source_v1.sha256_file(spec_path) != protocol.spec_parquet_sha256
        or pq.ParquetFile(spec_path).metadata.num_rows != 66052
        or spec_manifest.get("requested_end") != "2025-12-31"
        or spec_manifest.get("protected_from") != "2026-01-01"
        or spec_manifest.get("quality", {}).get("contains_returns") is not False
        or spec_manifest.get("quality", {}).get("contains_pnl") is not False
    ):
        raise ValueError("calendar-spread derived spec proxy declaration drifted")
    spec = pd.read_parquet(
        spec_path,
        columns=("session_date", "contract_id", *SPEC_FIELDS),
    )
    for frame, column in ((archive, "trade_date"), (spec, "session_date")):
        if pd.to_datetime(frame[column], errors="raise").max() >= PROTECTED_FROM:
            raise ValueError("calendar-spread derived input reaches protected values")
    provenance = {
        "source_manifest_sha256": protocol.source_manifest_sha256,
        "source_parent_checks": len(parent_audit.checks),
        "spec_manifest_sha256": protocol.spec_manifest_sha256,
        "spec_parquet_sha256": protocol.spec_parquet_sha256,
    }
    return catalog, archive, spec, provenance


def _canonical_contract_id(
    asset_code: pd.Series,
    secid: pd.Series,
    expiration: pd.Series,
) -> pd.Series:
    dates = pd.to_datetime(expiration, errors="raise").dt.strftime("%Y-%m-%d")
    return asset_code.astype(str) + ":" + secid.astype(str) + ":" + dates


def _prefix_spec(spec: pd.DataFrame, prefix: str) -> pd.DataFrame:
    selected = spec[["session_date", "contract_id", *SPEC_FIELDS]].copy()
    return selected.rename(
        columns={
            "session_date": f"{prefix}_session_date",
            "contract_id": f"{prefix}_contract_id",
            **{field: f"{prefix}_{field}" for field in SPEC_FIELDS},
        }
    )


def _assert_outcome_free(frames: Mapping[str, pd.DataFrame]) -> None:
    offenders = {
        name: [
            str(column)
            for column in frame.columns
            if any(token in str(column).lower() for token in FORBIDDEN_COLUMN_TOKENS)
        ]
        for name, frame in frames.items()
    }
    offenders = {name: columns for name, columns in offenders.items() if columns}
    if offenders:
        raise ValueError(f"calendar-spread derived outcome columns found: {offenders}")


def derive_tables(
    catalog: pd.DataFrame,
    archive: pd.DataFrame,
    spec: pd.DataFrame,
    provenance: Mapping[str, Any] | None = None,
    *,
    enforce_sealed_counts: bool = True,
) -> DerivedTables:
    """Apply only structural eligibility and nearest-expiry selection."""
    if tuple(catalog.columns) != source_v1.CATALOG_COLUMNS:
        raise ValueError("calendar-spread derived catalog schema drifted")
    if tuple(archive.columns) != source_v1.ARCHIVE_DAILY_COLUMNS:
        raise ValueError("calendar-spread derived archive schema drifted")
    if catalog["spread_id"].duplicated().any():
        raise ValueError("calendar-spread derived duplicate catalog identities")
    enriched = archive.merge(
        catalog[
            [
                "spread_id",
                "series_start",
                "expiry_gap_days",
                "regular_adjacent_expiry",
                "near_expiration_matches_spread_last_trade",
            ]
        ],
        on="spread_id",
        how="left",
        validate="many_to_one",
    )
    if enriched["regular_adjacent_expiry"].isna().any():
        raise ValueError("calendar-spread derived archive identity is absent from catalog")
    days_to_near = (
        pd.to_datetime(enriched["near_expiration"], errors="raise")
        - pd.to_datetime(enriched["trade_date"], errors="raise")
    ).dt.days
    structural_mask = (
        enriched["regular_adjacent_expiry"].astype(bool)
        & enriched["near_expiration_matches_spread_last_trade"].astype(bool)
        & enriched["reported_trade_activity"].astype(bool)
        & enriched["inside_series_interval"].astype(bool)
        & enriched["two_sided_quote_fields_complete"].astype(bool)
        & ~enriched["closing_quote_crossed"].astype(bool)
        & days_to_near.ge(0)
    )
    candidates = enriched.loc[structural_mask].copy()
    candidates["days_to_near_expiration"] = days_to_near.loc[structural_mask].astype(
        "int64"
    )
    candidates["calendar_tenor_days"] = (
        pd.to_datetime(candidates["far_expiration"], errors="raise")
        - pd.to_datetime(candidates["near_expiration"], errors="raise")
    ).dt.days.astype("int64")
    groups = candidates.groupby(["trade_date", "logical_asset"], sort=False)
    candidates["candidate_count"] = groups["spread_id"].transform("size").astype(
        "int64"
    )
    candidates["quote_width"] = candidates["ask"] - candidates["bid"]
    candidates["quote_midpoint"] = (candidates["ask"] + candidates["bid"]) / 2.0
    candidates["strict_positive_quote_width"] = candidates["quote_width"].gt(0.0)
    candidates["zero_locked_quote"] = (
        candidates["bid"].eq(0.0) & candidates["ask"].eq(0.0)
    )
    candidates = candidates.sort_values(
        ["trade_date", "logical_asset", "days_to_near_expiration", "spread_id"],
        ignore_index=True,
    )
    minimum_days = candidates.groupby(
        ["trade_date", "logical_asset"], sort=False
    )["days_to_near_expiration"].transform("min")
    selected = candidates.loc[
        candidates["days_to_near_expiration"].eq(minimum_days)
    ].copy()
    if selected.duplicated(["trade_date", "logical_asset"], keep=False).any():
        raise ValueError("calendar-spread derived active selection contains a tie")
    active = selected.sort_values(
        ["trade_date", "logical_asset"], ignore_index=True
    )
    active["near_contract_id"] = _canonical_contract_id(
        active["asset_code"], active["near_secid"], active["near_expiration"]
    )
    active["far_contract_id"] = _canonical_contract_id(
        active["asset_code"], active["far_secid"], active["far_expiration"]
    )
    active["trade_date"] = pd.to_datetime(active["trade_date"], errors="raise").dt.normalize()
    normalized_spec = spec.copy()
    normalized_spec["session_date"] = pd.to_datetime(
        normalized_spec["session_date"], errors="raise"
    ).dt.normalize()
    if normalized_spec.duplicated(["session_date", "contract_id"]).any():
        raise ValueError("calendar-spread derived spec identities are duplicated")
    active = active.merge(
        _prefix_spec(normalized_spec, "near"),
        left_on=["trade_date", "near_contract_id"],
        right_on=["near_session_date", "near_contract_id"],
        how="left",
        validate="many_to_one",
    ).merge(
        _prefix_spec(normalized_spec, "far"),
        left_on=["trade_date", "far_contract_id"],
        right_on=["far_session_date", "far_contract_id"],
        how="left",
        validate="many_to_one",
    )
    if active[["near_session_date", "far_session_date"]].isna().any().any():
        raise ValueError("calendar-spread derived active spec join is incomplete")
    for prefix in ("near", "far"):
        active[f"{prefix}_sizing_observed_session_date"] = pd.to_datetime(
            active[f"{prefix}_sizing_observed_session_date"], errors="raise"
        ).dt.normalize()
        usable = active[f"{prefix}_sizing_usable"]
        if usable.isna().any() or not usable.map(
            lambda value: isinstance(value, (bool, np.bool_))
        ).all():
            raise ValueError("calendar-spread derived sizing flag is not strict boolean")
        for field in (
            "sizing_point_value",
            "sizing_notional",
            "sizing_tick_cash_value",
            "modeled_initial_margin",
            "expected_buffered_initial_margin",
            "tick_size",
            "conservative_fee_per_side",
        ):
            values = pd.to_numeric(active[f"{prefix}_{field}"], errors="coerce")
            if values.isna().any() or not np.isfinite(values).all():
                raise ValueError(f"calendar-spread derived invalid {prefix}_{field}")
            active[f"{prefix}_{field}"] = values
    active["both_sizing_usable"] = (
        active["near_sizing_usable"].astype(bool)
        & active["far_sizing_usable"].astype(bool)
    )
    active["spec_observations_strictly_prior"] = (
        active["near_sizing_observed_session_date"].lt(active["trade_date"])
        & active["far_sizing_observed_session_date"].lt(active["trade_date"])
    )
    active["gross_sizing_notional"] = (
        active["near_sizing_notional"] + active["far_sizing_notional"]
    )
    active["conservative_two_leg_fee_per_side"] = (
        active["near_conservative_fee_per_side"]
        + active["far_conservative_fee_per_side"]
    )
    active["conservative_two_leg_buffered_margin"] = (
        active["near_expected_buffered_initial_margin"]
        + active["far_expected_buffered_initial_margin"]
    )
    finite_point_values = np.isfinite(active["near_sizing_point_value"]) & np.isfinite(
        active["far_sizing_point_value"]
    )
    active["point_values_equal"] = finite_point_values & np.isclose(
        active["near_sizing_point_value"], active["far_sizing_point_value"]
    )
    active = active.drop(columns=["near_session_date", "far_session_date"])
    clean_catalog = catalog.loc[
        catalog["regular_adjacent_expiry"].astype(bool)
        & catalog["near_expiration_matches_spread_last_trade"].astype(bool)
    ]
    coverage_rows: list[dict[str, Any]] = []
    for asset in ASSETS:
        asset_active = active.loc[active["logical_asset"].eq(asset)].copy()
        dates = pd.to_datetime(asset_active["trade_date"], errors="raise").sort_values()
        coverage_rows.append(
            {
                "logical_asset": asset,
                "clean_spreads": int(clean_catalog["logical_asset"].eq(asset).sum()),
                "candidate_rows": int(candidates["logical_asset"].eq(asset).sum()),
                "active_rows": int(len(asset_active)),
                "active_unique_spreads": int(asset_active["spread_id"].nunique()),
                "first_active_date": dates.min(),
                "last_active_date": dates.max(),
                "maximum_calendar_gap_days": (
                    0 if len(dates) < 2 else int(dates.diff().dt.days.max())
                ),
                "minimum_days_to_near_expiration": int(
                    asset_active["days_to_near_expiration"].min()
                ),
                "maximum_days_to_near_expiration": int(
                    asset_active["days_to_near_expiration"].max()
                ),
                "zero_locked_active_rows": int(
                    asset_active["zero_locked_quote"].sum()
                ),
                "strict_positive_width_active_rows": int(
                    asset_active["strict_positive_quote_width"].sum()
                ),
                "both_sizing_usable_rows": int(
                    asset_active["both_sizing_usable"].sum()
                ),
                "strictly_prior_spec_rows": int(
                    asset_active["spec_observations_strictly_prior"].sum()
                ),
            }
        )
    coverage = pd.DataFrame(coverage_rows, columns=COVERAGE_COLUMNS)
    candidates = candidates[list(CANDIDATE_COLUMNS)].reset_index(drop=True)
    active = active[list(ACTIVE_COLUMNS)].reset_index(drop=True)
    if enforce_sealed_counts:
        candidate_counts = {
            asset: int(candidates["logical_asset"].eq(asset).sum()) for asset in ASSETS
        }
        active_counts = {
            asset: int(active["logical_asset"].eq(asset).sum()) for asset in ASSETS
        }
        clean_counts = {
            asset: int(clean_catalog["logical_asset"].eq(asset).sum()) for asset in ASSETS
        }
        if (
            clean_counts != EXPECTED_CLEAN_SPREADS
            or candidate_counts != EXPECTED_CANDIDATE_ROWS
            or active_counts != EXPECTED_ACTIVE_ROWS
            or len(candidates) != EXPECTED_TOTAL_CANDIDATE_ROWS
            or len(active) != EXPECTED_TOTAL_ACTIVE_ROWS
            or int(active["zero_locked_quote"].sum())
            != EXPECTED_ZERO_LOCKED_ACTIVE_ROWS
            or int(active["strict_positive_quote_width"].sum())
            != EXPECTED_STRICT_POSITIVE_WIDTH_ACTIVE_ROWS
            or not active["both_sizing_usable"].all()
            or not active["spec_observations_strictly_prior"].all()
            or int(active["point_values_equal"].sum())
            != EXPECTED_POINT_VALUES_EQUAL_ACTIVE_ROWS
            or not (
                active["near_approximate"].astype(bool)
                & active["far_approximate"].astype(bool)
            ).all()
            or (
                active["near_historical_exchange_exact"].astype(bool)
                | active["far_historical_exchange_exact"].astype(bool)
                | active["near_broker_exact"].astype(bool)
                | active["far_broker_exact"].astype(bool)
            ).any()
        ):
            raise ValueError("calendar-spread derived sealed counts drifted")
    for frame in (candidates, active):
        if pd.to_datetime(frame["trade_date"], errors="raise").max() >= PROTECTED_FROM:
            raise ValueError("calendar-spread derived output reaches protected values")
        if not (
            pd.to_datetime(frame["available_at"], utc=True)
            > pd.to_datetime(frame["trade_date"], utc=True)
        ).all():
            raise ValueError("calendar-spread derived availability is not causal")
    _assert_outcome_free(
        {"candidates": candidates, "active": active, "coverage": coverage}
    )
    audit = {
        **dict(provenance or {}),
        "clean_spreads_by_asset": {
            asset: int(coverage.loc[coverage["logical_asset"].eq(asset), "clean_spreads"].iloc[0])
            for asset in ASSETS
        },
        "candidate_rows": int(len(candidates)),
        "candidate_rows_by_asset": {
            asset: int(candidates["logical_asset"].eq(asset).sum()) for asset in ASSETS
        },
        "active_rows": int(len(active)),
        "active_rows_by_asset": {
            asset: int(active["logical_asset"].eq(asset).sum()) for asset in ASSETS
        },
        "active_tie_rows": 0,
        "zero_locked_active_rows": int(active["zero_locked_quote"].sum()),
        "strict_positive_width_active_rows": int(
            active["strict_positive_quote_width"].sum()
        ),
        "both_sizing_usable_active_rows": int(active["both_sizing_usable"].sum()),
        "strictly_prior_spec_active_rows": int(
            active["spec_observations_strictly_prior"].sum()
        ),
        "point_values_equal_active_rows": int(active["point_values_equal"].sum()),
        "minimum_active_date": str(active["trade_date"].min().date()),
        "maximum_active_date": str(active["trade_date"].max().date()),
        "contains_prices": True,
        "contains_returns_targets_labels_signals_equity_or_pnl": False,
        "historical_exchange_exact": False,
        "broker_exact": False,
    }
    return DerivedTables(candidates, active, coverage, audit)


def build_tables(protocol: DerivedProtocol) -> DerivedTables:
    catalog, archive, spec, provenance = verify_and_load_inputs(protocol)
    return derive_tables(catalog, archive, spec, provenance)


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": source_v1.sha256_file(path),
    }
    if rows is not None:
        record["rows"] = int(rows)
    return record


def persist(protocol: DerivedProtocol, tables: DerivedTables) -> Path:
    """Atomically publish one immutable derived-source bundle outside Git."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"calendar-spread derived output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        frames = {
            "candidates": tables.candidates,
            "active": tables.active,
            "coverage": tables.coverage,
        }
        _assert_outcome_free(frames)
        artifacts: dict[str, Any] = {}
        for name, frame in frames.items():
            path = temporary / f"{name}.parquet"
            source_v1._write_parquet(path, frame)
            artifacts[name] = _artifact(path, len(frame))
            artifacts[name]["columns"] = frame.columns.tolist()
        audit_path = temporary / "audit.json"
        write_json(audit_path, tables.audit)
        artifacts["audit"] = _artifact(audit_path)
        manifest = {
            "schema_version": 1,
            "bundle_id": "moex-calendar-spread-derived-2021-2025-v1",
            "protocol_sha256": protocol.config_sha256,
            "implementation_sha256": protocol.dependency_hashes,
            "source_only": True,
            "contains_returns_targets_labels_signals_equity_or_pnl": False,
            "live_trading_allowed": False,
            "parent_source": {
                "directory": protocol.source_directory.relative_to(PROJECT_ROOT).as_posix(),
                "manifest_sha256": protocol.source_manifest_sha256,
            },
            "spec_proxy": {
                "directory": protocol.spec_directory.relative_to(PROJECT_ROOT).as_posix(),
                "manifest_sha256": protocol.spec_manifest_sha256,
                "parquet_sha256": protocol.spec_parquet_sha256,
            },
            "temporal_semantics": {
                "minimum_trade_date": tables.audit["minimum_active_date"],
                "maximum_trade_date": tables.audit["maximum_active_date"],
                "protected_from": PROTECTED_FROM.date().isoformat(),
                "available_at_inherited": True,
                "spec_observations_strictly_prior": True,
                "missing_values_preserved": True,
            },
            "counts": {
                key: value
                for key, value in tables.audit.items()
                if key
                in {
                    "clean_spreads_by_asset",
                    "candidate_rows",
                    "candidate_rows_by_asset",
                    "active_rows",
                    "active_rows_by_asset",
                    "active_tie_rows",
                    "zero_locked_active_rows",
                    "strict_positive_width_active_rows",
                    "both_sizing_usable_active_rows",
                    "strictly_prior_spec_active_rows",
                    "point_values_equal_active_rows",
                }
            },
            "artifacts": artifacts,
            "limitations": protocol.payload["limitations"],
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        manifest_sha = source_v1.sha256_file(manifest_path)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{manifest_sha}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def build_and_persist(protocol: DerivedProtocol) -> Path:
    return persist(protocol, build_tables(protocol))


def _frames_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(
            left.reset_index(drop=True),
            right.reset_index(drop=True),
            check_dtype=False,
            check_like=False,
        )
        return True
    except AssertionError:
        return False


def audit_bundle(protocol: DerivedProtocol) -> DerivedAudit:
    """Verify artifact bytes and logically rebuild every derived row from parents."""
    root = protocol.output_directory.resolve()
    manifest_path = root / "manifest.json"
    sidecar_path = root / "manifest.sha256"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    declared_manifest_sha = sidecar_path.read_text(encoding="utf-8-sig").split()[0]
    checks: dict[str, bool] = {
        "manifest_sha_exact": declared_manifest_sha
        == source_v1.sha256_file(manifest_path),
        "protocol_sha_exact": manifest.get("protocol_sha256") == protocol.config_sha256,
        "source_only": manifest.get("source_only") is True,
        "outcomes_absent_declared": manifest.get(
            "contains_returns_targets_labels_signals_equity_or_pnl"
        )
        is False,
        "live_forbidden": manifest.get("live_trading_allowed") is False,
    }
    frames: dict[str, pd.DataFrame] = {}
    expected_columns = {
        "candidates": CANDIDATE_COLUMNS,
        "active": ACTIVE_COLUMNS,
        "coverage": COVERAGE_COLUMNS,
    }
    for name in ("candidates", "active", "coverage"):
        declaration = _mapping(manifest["artifacts"][name], name)
        path = root / str(declaration["file"])
        checks[f"{name}_bytes_exact"] = path.stat().st_size == int(
            declaration["bytes"]
        )
        checks[f"{name}_sha_exact"] = source_v1.sha256_file(path) == str(
            declaration["sha256"]
        )
        checks[f"{name}_rows_exact"] = pq.ParquetFile(path).metadata.num_rows == int(
            declaration["rows"]
        )
        frames[name] = pd.read_parquet(path)
        checks[f"{name}_columns_exact"] = tuple(frames[name].columns) == expected_columns[
            name
        ]
        checks[f"{name}_outcome_columns_absent"] = not any(
            any(token in str(column).lower() for token in FORBIDDEN_COLUMN_TOKENS)
            for column in frames[name].columns
        )
    audit_declaration = _mapping(manifest["artifacts"]["audit"], "audit")
    audit_path = root / str(audit_declaration["file"])
    checks["audit_bytes_exact"] = audit_path.stat().st_size == int(
        audit_declaration["bytes"]
    )
    checks["audit_sha_exact"] = source_v1.sha256_file(audit_path) == str(
        audit_declaration["sha256"]
    )
    rebuilt = build_tables(protocol)
    checks["candidate_rebuild_exact"] = _frames_equal(
        rebuilt.candidates, frames["candidates"]
    )
    checks["active_rebuild_exact"] = _frames_equal(rebuilt.active, frames["active"])
    checks["coverage_rebuild_exact"] = _frames_equal(
        rebuilt.coverage, frames["coverage"]
    )
    checks["active_identity_unique"] = not frames["active"].duplicated(
        ["trade_date", "logical_asset"]
    ).any()
    checks["active_before_protected"] = bool(
        pd.to_datetime(frames["active"]["trade_date"], errors="raise").max()
        < PROTECTED_FROM
    )
    checks["spec_strictly_prior"] = bool(
        frames["active"]["spec_observations_strictly_prior"].all()
    )
    checks["sizing_complete"] = bool(frames["active"]["both_sizing_usable"].all())
    if not all(checks.values()):
        raise ValueError(f"calendar-spread derived audit failed: {checks}")
    return DerivedAudit(
        checks=checks,
        counts={
            "candidates": int(len(frames["candidates"])),
            "active": int(len(frames["active"])),
            "zero_locked_active": int(frames["active"]["zero_locked_quote"].sum()),
            "point_values_equal": int(frames["active"]["point_values_equal"].sum()),
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args(argv)
    protocol = load_protocol(arguments.config)
    if arguments.audit_only:
        audit = audit_bundle(protocol)
        print(json.dumps({"checks": audit.checks, "counts": audit.counts}, indent=2))
        return 0
    output = build_and_persist(protocol)
    audit = audit_bundle(protocol)
    print(output)
    print(json.dumps({"checks": audit.checks, "counts": audit.counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
