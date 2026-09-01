"""Build a causal robust regime panel from MOEX raw curve coefficients."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from market_lab.futures import moex_volatility_curve_archive_catalog_v2 as catalog_v2
from market_lab.futures import moex_volatility_curve_source as source_v1
from market_lab.io_utils import atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = source_v1.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_curve_coefficient_regime_source_v1.yaml"
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
ASSETS: Final[tuple[str, ...]] = ("RI", "MIX", "SI", "BR")
COEFFICIENTS: Final[tuple[str, ...]] = ("s", "a", "b", "c", "d", "e")
RAW_COLUMNS: Final[tuple[str, ...]] = (
    "SESS_ID",
    "A",
    "B",
    "C",
    "D",
    "E",
    "S",
    "OPTION_SERIES_ID",
    "FUT_ISIN_ID",
    "ISIN",
    "BEGIN",
)
EXPECTED_ARCHIVE_ROWS: Final[int] = 191_197
EXPECTED_CORE_ROWS: Final[int] = 25_172
EXPECTED_EVENTS: Final[int] = 686
EXPECTED_LONG_ROWS: Final[int] = EXPECTED_EVENTS * len(ASSETS)
EXPECTED_WIDE_ROWS: Final[int] = EXPECTED_EVENTS
AVAILABILITY_DELAY_MINUTES: Final[int] = 1
EXPECTED_LATE_EVENT: Final[pd.Timestamp] = pd.Timestamp(
    "2023-09-13 13:30:00", tz="Europe/Moscow"
)
FORBIDDEN_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "settlement_price_open",
        "price",
        "return",
        "returns",
        "target",
        "label",
        "signal",
        "pnl",
        "equity",
        "atm_volatility",
        "years_to_expiry",
        "t",
    }
)


@dataclass(frozen=True, slots=True)
class RegimeProtocol:
    """Byte-pinned parent and outcome-free coefficient transform contract."""

    config_path: Path
    config_sha256: str
    payload: dict[str, Any]
    parent_root: Path
    parent_manifest_path: Path
    parent_catalog_path: Path
    raw_archive_path: Path
    output_directory: Path


@dataclass(frozen=True, slots=True)
class RegimeBuild:
    """Processed coefficient rows, long aggregates, wide context and evidence."""

    core: pd.DataFrame
    long: pd.DataFrame
    wide: pd.DataFrame
    checks: dict[str, bool]
    counts: dict[str, Any]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"MOEX coefficient regime {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"MOEX coefficient regime sidecar missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _manifest_payload_sha(manifest: Mapping[str, Any]) -> str:
    core = {key: value for key, value in manifest.items() if key != "manifest_payload_sha256"}
    return hashlib.sha256(_canonical_json(core)).hexdigest()


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> RegimeProtocol:
    """Verify parent bytes and fixed transform before reading coefficient values."""
    path = config_path.resolve()
    config_sha = source_v1.sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("MOEX coefficient regime protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("MOEX coefficient regime protocol must be a YAML object")
    parent = _mapping(payload.get("parent_catalog"), "parent")
    transform = _mapping(payload.get("transform"), "transform")
    quality = _mapping(payload.get("quality_gates"), "quality gates")
    output = _mapping(payload.get("output"), "output")
    if (
        payload.get("protocol_id") != "moex_curve_coefficient_regime_source_v1"
        or payload.get("status") != "sealed_before_first_coefficient_aggregate_value"
        or payload.get("scope") != "source_derived_no_prices_no_T_no_returns_no_pnl"
        or payload.get("research_only") is not True
        or payload.get("live_trading_allowed") is not False
        or parent.get("source_id") != "official-moex-volatility-curve-archive-catalog-v2"
        or parent.get("manifest_sha256")
        != "5d6e97b575dd0e97ebcf59c3101d2ede65efc0076ec20b985decdf6a8ae05630"
        or parent.get("catalog_sha256")
        != "add6c5d519ab06e0123af941ce4806de0eb5bf5c3a3baa9ce6cecbdccabb1cd3"
        or parent.get("raw_archive_sha256")
        != "67a33666902a14e1c8ee6ceac01f1980021890087fb0a3271c5d2060fab51794"
        or tuple(transform["coefficients"]) != COEFFICIENTS
        or tuple(transform["robust_statistics"]) != ("median", "q25", "q75", "iqr", "mad")
        or transform.get("delta") != "current_median_minus_previous_source_event_median"
        or transform.get("maturity_interpretation") != "forbidden"
        or transform.get("price_field_used") is not False
        or tuple(transform["asset_order"]) != ASSETS
        or int(quality["exact_archive_rows"]) != EXPECTED_ARCHIVE_ROWS
        or int(quality["exact_core_rows"]) != EXPECTED_CORE_ROWS
        or int(quality["exact_events"]) != EXPECTED_EVENTS
        or int(quality["exact_long_rows"]) != EXPECTED_LONG_ROWS
        or int(quality["exact_wide_rows"]) != EXPECTED_WIDE_ROWS
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("MOEX coefficient regime protocol invariants drifted")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    for relative, expected in dependencies.items():
        if source_v1.sha256_file(PROJECT_ROOT / str(relative)) != str(expected).lower():
            raise ValueError(f"MOEX coefficient regime dependency drift: {relative}")
    parent_root = (PROJECT_ROOT / str(parent["directory"])).resolve()
    return RegimeProtocol(
        config_path=path,
        config_sha256=config_sha,
        payload=payload,
        parent_root=parent_root,
        parent_manifest_path=parent_root / str(parent["manifest_path"]),
        parent_catalog_path=parent_root / str(parent["catalog_path"]),
        raw_archive_path=parent_root / str(parent["raw_archive_path"]),
        output_directory=(PROJECT_ROOT / str(output["directory"])).resolve(),
    )


def verify_parent(protocol: RegimeProtocol) -> tuple[dict[str, Any], dict[str, bool]]:
    """Verify catalog and raw ZIP identities before opening the member."""
    parent = protocol.payload["parent_catalog"]
    paths = {
        "manifest": protocol.parent_manifest_path,
        "catalog": protocol.parent_catalog_path,
        "raw_archive": protocol.raw_archive_path,
    }
    checks = {f"{name}_exists": path.is_file() for name, path in paths.items()}
    if not all(checks.values()):
        raise FileNotFoundError(f"MOEX coefficient regime parent missing: {checks}")
    checks.update(
        {
            "manifest_bytes": paths["manifest"].stat().st_size
            == int(parent["manifest_bytes"]),
            "manifest_sha256": source_v1.sha256_file(paths["manifest"])
            == parent["manifest_sha256"],
            "catalog_bytes": paths["catalog"].stat().st_size == int(parent["catalog_bytes"]),
            "catalog_sha256": source_v1.sha256_file(paths["catalog"])
            == parent["catalog_sha256"],
            "raw_archive_bytes": paths["raw_archive"].stat().st_size
            == int(parent["raw_archive_bytes"]),
            "raw_archive_sha256": source_v1.sha256_file(paths["raw_archive"])
            == parent["raw_archive_sha256"],
        }
    )
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8-sig"))
    checks.update(
        {
            "parent_manifest_payload": catalog_v2.v1._manifest_payload_sha(manifest)
            == manifest["manifest_payload_sha256"],
            "parent_source_id": manifest["source_id"] == parent["source_id"],
            "parent_catalog_artifact": manifest["artifacts"]["catalog"]["sha256"]
            == parent["catalog_sha256"],
            "parent_raw_artifact": manifest["artifacts"]["raw_archives"]["202108_202405"]
            ["sha256"]
            == parent["raw_archive_sha256"],
            "parent_outcome_free_selection": manifest["information_contract"]
            ["archive_selection_uses_future_returns"]
            is False,
        }
    )
    if not all(checks.values()):
        raise ValueError(f"MOEX coefficient regime parent verification failed: {checks}")
    return manifest, checks


def _safe_member(content: bytes, expected_name: str, expected_bytes: int) -> bytes:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) != 1:
            raise ValueError("MOEX coefficient regime ZIP must have exactly one member")
        member = members[0]
        path = PurePosixPath(member.filename.replace("\\", "/"))
        if (
            path.is_absolute()
            or ".." in path.parts
            or member.filename != expected_name
            or member.file_size != expected_bytes
            or member.flag_bits & 0x1
        ):
            raise ValueError("MOEX coefficient regime ZIP member identity is unsafe")
        return archive.read(member)


def parse_combined_archive(content: bytes, protocol_payload: Mapping[str, Any]) -> pd.DataFrame:
    """Read coefficients and identifiers while never loading SETTLEMENT_PRICE_OPEN."""
    parent = _mapping(protocol_payload.get("parent_catalog"), "parent")
    if len(content) != int(parent["raw_archive_bytes"]):
        raise ValueError("MOEX coefficient regime raw archive byte mismatch")
    if hashlib.sha256(content).hexdigest() != parent["raw_archive_sha256"]:
        raise ValueError("MOEX coefficient regime raw archive SHA-256 mismatch")
    raw_csv = _safe_member(
        content,
        str(parent["raw_member_name"]),
        int(parent["raw_member_bytes"]),
    )
    frame = pd.read_csv(
        io.BytesIO(raw_csv),
        sep=";",
        usecols=list(RAW_COLUMNS),
        dtype={"ISIN": "string", "BEGIN": "string"},
    )
    if len(frame) != EXPECTED_ARCHIVE_ROWS:
        raise ValueError(f"MOEX coefficient regime archive rows drifted: {len(frame)}")
    isin = frame["ISIN"].str.strip().str.upper()
    conditions = [isin.str.startswith(f"{root}-", na=False) for root in ("RTS", "MIX", "SI", "BR")]
    assets = np.select(conditions, ASSETS, default="")
    core = frame.loc[assets != ""].copy()
    core["asset"] = assets[assets != ""]
    core["underlying_isin"] = core.pop("ISIN").str.strip()
    core["event_at"] = pd.to_datetime(
        core.pop("BEGIN"), format="%d.%m.%Y %H:%M", errors="raise"
    ).dt.tz_localize("Europe/Moscow", ambiguous="raise", nonexistent="raise")
    core["available_at"] = core["event_at"] + pd.Timedelta(
        minutes=AVAILABILITY_DELAY_MINUTES
    )
    core = core.rename(
        columns={
            "SESS_ID": "session_id",
            "OPTION_SERIES_ID": "option_series_id",
            "FUT_ISIN_ID": "futures_isin_id",
            **{column.upper(): column for column in COEFFICIENTS},
        }
    )
    for column in ("session_id", "option_series_id", "futures_isin_id"):
        values = pd.to_numeric(core[column], errors="raise")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"MOEX coefficient regime invalid identifier: {column}")
        core[column] = values.astype("int64")
    for column in COEFFICIENTS:
        values = pd.to_numeric(core[column], errors="raise").astype(float)
        if values.isna().any() or not np.isfinite(values.to_numpy()).all():
            raise ValueError(f"MOEX coefficient regime invalid coefficient: {column}")
        core[column] = values
    if len(core) != EXPECTED_CORE_ROWS:
        raise ValueError(f"MOEX coefficient regime core rows drifted: {len(core)}")
    if core.duplicated(["event_at", "option_series_id"]).any():
        raise ValueError("MOEX coefficient regime duplicate event/series ID")
    if core.groupby("option_series_id")["underlying_isin"].nunique().gt(1).any():
        raise ValueError("MOEX coefficient regime series ID changed underlying")
    if core["event_at"].dt.tz_localize(None).ge(PROTECTED_FROM).any():
        raise ValueError("MOEX coefficient regime contains protected source event")
    columns = [
        "event_at",
        "available_at",
        "asset",
        "session_id",
        "option_series_id",
        "futures_isin_id",
        "underlying_isin",
        *COEFFICIENTS,
    ]
    return core.loc[:, columns].sort_values(
        ["event_at", "asset", "option_series_id"], kind="mergesort", ignore_index=True
    )


def _mad(series: pd.Series) -> float:
    values = series.to_numpy(dtype=float)
    median = float(np.median(values))
    return float(np.median(np.abs(values - median)))


def build_long_panel(core: pd.DataFrame) -> pd.DataFrame:
    """Aggregate every event/asset with fixed robust cross-series statistics."""
    rows: list[dict[str, object]] = []
    for (event_at, asset), group in core.groupby(["event_at", "asset"], sort=True):
        row: dict[str, object] = {
            "event_at": event_at,
            "available_at": group["available_at"].max(),
            "asset": asset,
            "series_count": len(group),
            "underlying_isin_count": int(group["underlying_isin"].nunique()),
        }
        for coefficient in COEFFICIENTS:
            values = group[coefficient]
            q25 = float(values.quantile(0.25, interpolation="linear"))
            q75 = float(values.quantile(0.75, interpolation="linear"))
            row[f"{coefficient}_median"] = float(values.median())
            row[f"{coefficient}_q25"] = q25
            row[f"{coefficient}_q75"] = q75
            row[f"{coefficient}_iqr"] = q75 - q25
            row[f"{coefficient}_mad"] = _mad(values)
        rows.append(row)
    panel = pd.DataFrame(rows)
    panel["_asset_order"] = panel["asset"].map(
        {asset: order for order, asset in enumerate(ASSETS)}
    )
    panel = (
        panel.sort_values(
            ["event_at", "_asset_order"], kind="mergesort", ignore_index=True
        )
        .drop(columns="_asset_order")
    )
    panel["previous_event_at"] = panel.groupby("asset", sort=False)["event_at"].shift(1)
    panel["days_since_previous_source"] = (
        panel["event_at"] - panel["previous_event_at"]
    ).dt.total_seconds() / 86_400.0
    panel["series_count_delta"] = panel.groupby("asset", sort=False)["series_count"].diff()
    for coefficient in COEFFICIENTS:
        column = f"{coefficient}_median"
        panel[f"{coefficient}_median_delta"] = panel.groupby("asset", sort=False)[column].diff()
    return panel


def build_wide_context(long: pd.DataFrame) -> pd.DataFrame:
    """Expose all four markets and cross-market aggregates at every source event."""
    feature_columns = ["series_count", "underlying_isin_count", "series_count_delta"]
    for coefficient in COEFFICIENTS:
        feature_columns.extend(
            [
                f"{coefficient}_median",
                f"{coefficient}_q25",
                f"{coefficient}_q75",
                f"{coefficient}_iqr",
                f"{coefficient}_mad",
                f"{coefficient}_median_delta",
            ]
        )
    events = long.loc[:, ["event_at", "available_at"]].drop_duplicates("event_at")
    wide = events.sort_values("event_at", kind="mergesort", ignore_index=True)
    context_data: dict[str, pd.Series] = {}
    for asset in ASSETS:
        subset = long.loc[long["asset"].eq(asset)].set_index("event_at")
        for feature in feature_columns:
            context_data[f"context_{asset.lower()}_{feature}"] = wide["event_at"].map(
                subset[feature]
            )
    wide = pd.concat([wide, pd.DataFrame(context_data, index=wide.index)], axis=1)
    cross_data: dict[str, pd.Series] = {}
    for coefficient in COEFFICIENTS:
        columns = [f"context_{asset.lower()}_{coefficient}_median" for asset in ASSETS]
        values = wide.loc[:, columns]
        cross_data[f"cross_asset_{coefficient}_median"] = values.median(axis=1)
        cross_data[f"cross_asset_{coefficient}_dispersion"] = values.std(axis=1, ddof=1)
    wide = pd.concat([wide, pd.DataFrame(cross_data, index=wide.index)], axis=1)
    wide = wide.assign(
        source_observed_through=wide["event_at"],
        source_available_through=wide["available_at"],
    )
    return wide


def build_regime(core: pd.DataFrame) -> RegimeBuild:
    """Build and fail closed on exact source, causality and completeness gates."""
    long = build_long_panel(core)
    wide = build_wide_context(long)
    per_asset_dates = long.groupby("asset")["event_at"].nunique().to_dict()
    late_events = core.loc[core["event_at"].dt.strftime("%H:%M").ne("10:00"), "event_at"].unique()
    causal_delta_columns = [
        "days_since_previous_source",
        "series_count_delta",
        *[f"{coefficient}_median_delta" for coefficient in COEFFICIENTS],
    ]
    numeric_long = long.select_dtypes(include=[np.number]).drop(
        columns=causal_delta_columns,
        errors="ignore",
    )
    checks = {
        "exact_core_rows": len(core) == EXPECTED_CORE_ROWS,
        "exact_events": core["event_at"].nunique() == EXPECTED_EVENTS,
        "exact_long_rows": len(long) == EXPECTED_LONG_ROWS,
        "exact_wide_rows": len(wide) == EXPECTED_WIDE_ROWS,
        "unique_core_event_series": not core.duplicated(["event_at", "option_series_id"]).any(),
        "unique_long_event_asset": not long.duplicated(["event_at", "asset"]).any(),
        "unique_wide_event": not wide.duplicated("event_at").any(),
        "all_assets_every_event": all(
            int(per_asset_dates.get(asset, 0)) == EXPECTED_EVENTS for asset in ASSETS
        ),
        "exact_asset_order": tuple(long["asset"].drop_duplicates()) == ASSETS,
        "availability_not_before_event": core["available_at"].ge(core["event_at"]).all(),
        "wide_causal": wide["source_available_through"].eq(wide["available_at"]).all(),
        "all_robust_levels_finite": np.isfinite(numeric_long.to_numpy(dtype=float)).all(),
        "single_late_event_preserved": len(late_events) == 1
        and pd.Timestamp(late_events[0]) == EXPECTED_LATE_EVENT,
        "forbidden_columns_absent": not bool(
            (
                set(core.columns.str.lower())
                | set(long.columns.str.lower())
                | set(wide.columns.str.lower())
            )
            & FORBIDDEN_COLUMNS
        ),
        "before_protected_boundary": wide["event_at"].dt.tz_localize(None).lt(PROTECTED_FROM).all(),
    }
    if not all(checks.values()):
        raise ValueError(f"MOEX coefficient regime gates failed: {checks}")
    counts: dict[str, Any] = {
        "core_rows": len(core),
        "events": int(core["event_at"].nunique()),
        "long_rows": len(long),
        "wide_rows": len(wide),
        "rows_by_asset": {key: int(value) for key, value in core.groupby("asset").size().items()},
        "series_ids_by_asset": {
            key: int(value)
            for key, value in core.groupby("asset")["option_series_id"].nunique().items()
        },
        "late_event": EXPECTED_LATE_EVENT.isoformat(),
    }
    return RegimeBuild(core, long, wide, checks, counts)


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def build_source(
    config_path: Path = DEFAULT_CONFIG,
    output_directory: Path | None = None,
    *,
    built_at_utc: str | None = None,
) -> Path:
    """Publish immutable raw-coefficient and robust-context source artifacts."""
    protocol = load_protocol(config_path)
    parent_manifest, parent_checks = verify_parent(protocol)
    core = parse_combined_archive(protocol.raw_archive_path.read_bytes(), protocol.payload)
    result = build_regime(core)
    final = (output_directory or protocol.output_directory).resolve()
    if final.exists():
        raise FileExistsError(f"MOEX coefficient regime output exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        artifact_frames = {
            "core_coefficients": ("core_curve_coefficients.parquet", result.core),
            "long_panel": ("coefficient_regime_long.parquet", result.long),
            "wide_context": ("coefficient_regime_wide.parquet", result.wide),
        }
        artifacts: dict[str, dict[str, object]] = {}
        for name, (filename, frame) in artifact_frames.items():
            path = temporary / filename
            _atomic_parquet(path, frame)
            artifacts[name] = {
                "path": filename,
                "bytes": path.stat().st_size,
                "sha256": source_v1.sha256_file(path),
                "rows": len(frame),
                "columns": frame.columns.tolist(),
            }
        audit_path = temporary / "source_audit.json"
        write_json(
            audit_path,
            {
                "schema_version": 1,
                "parent_checks": parent_checks,
                "source_checks": result.checks,
                "counts": result.counts,
            },
        )
        artifacts["audit"] = {
            "path": audit_path.name,
            "bytes": audit_path.stat().st_size,
            "sha256": source_v1.sha256_file(audit_path),
        }
        built_at = built_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-moex-curve-coefficient-regime-2021-2024-v1",
            "provider": "MOEX",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": protocol.config_sha256,
            },
            "built_at_utc": built_at,
            "parent": {
                "source_id": parent_manifest["source_id"],
                "manifest_sha256": source_v1.sha256_file(protocol.parent_manifest_path),
                "raw_archive_sha256": source_v1.sha256_file(protocol.raw_archive_path),
            },
            "information_contract": {
                "event_at": "factual BEGIN from official combined curve file",
                "available_at": "event_at plus one minute delivery buffer",
                "maturity_or_ATM_interpretation": "forbidden_without_T",
                "settlement_price_open_loaded_or_used": False,
                "contains_returns_targets_labels_or_pnl": False,
                "historical_archive_delivery_is_original_vintage": False,
                "research_only": True,
            },
            "transform": {
                "coefficients": list(COEFFICIENTS),
                "statistics": ["median", "q25", "q75", "iqr", "mad"],
                "deltas": "previous source event per asset",
                "cross_market_context": list(ASSETS),
            },
            "counts": result.counts,
            "artifacts": artifacts,
        }
        manifest = {
            **manifest_core,
            "manifest_payload_sha256": hashlib.sha256(_canonical_json(manifest_core)).hexdigest(),
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        manifest_sha = source_v1.sha256_file(manifest_path)
        atomic_write_text(temporary / "manifest.sha256", f"{manifest_sha}  manifest.json\n")
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def audit_existing_source(
    output_directory: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Rebuild from the pinned raw ZIP and verify all three Parquet frames exactly."""
    protocol = load_protocol(config_path)
    verify_parent(protocol)
    root = (output_directory or protocol.output_directory).resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    checks: dict[str, bool] = {
        "manifest_payload_sha256": _manifest_payload_sha(manifest)
        == manifest["manifest_payload_sha256"],
        "manifest_sidecar_sha256": (root / "manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        == source_v1.sha256_file(manifest_path),
        "protocol_identity": manifest["protocol"]["sha256"] == protocol.config_sha256,
    }
    rebuilt = build_regime(
        parse_combined_archive(protocol.raw_archive_path.read_bytes(), protocol.payload)
    )
    frames = {
        "core_coefficients": rebuilt.core,
        "long_panel": rebuilt.long,
        "wide_context": rebuilt.wide,
    }
    for name, artifact in manifest["artifacts"].items():
        path = root / artifact["path"]
        checks[f"{name}_exists"] = path.is_file()
        checks[f"{name}_bytes"] = path.is_file() and path.stat().st_size == artifact["bytes"]
        checks[f"{name}_sha256"] = path.is_file() and source_v1.sha256_file(path) == artifact[
            "sha256"
        ]
        if name in frames and path.is_file():
            try:
                pd.testing.assert_frame_equal(
                    pd.read_parquet(path), frames[name], check_like=False
                )
                checks[f"{name}_replay_exact"] = True
            except AssertionError:
                checks[f"{name}_replay_exact"] = False
    if not all(checks.values()):
        raise ValueError(f"MOEX coefficient regime existing audit failed: {checks}")
    return {
        "source_id": manifest["source_id"],
        "manifest_sha256": source_v1.sha256_file(manifest_path),
        "checks": checks,
        "counts": manifest["counts"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.audit_only:
        result: object = audit_existing_source(arguments.output_directory, arguments.config)
    else:
        result = build_source(arguments.config, arguments.output_directory)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
