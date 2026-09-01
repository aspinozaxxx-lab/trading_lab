"""Build the MOEX archive catalog with conservative legacy-schema corrections."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import tempfile
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_volatility_curve_archive_catalog as v1
from market_lab.futures import moex_volatility_curve_source as source_v1
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = v1.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = (
    PROJECT_ROOT / "configs/moex_volatility_curve_archive_catalog_v2.yaml"
)
PARENT_CONFIG_SHA256: Final[str] = (
    "198e4206bd02f3bf045758c778088e514a2d8ebc1eb47993d03a663ace064c51"
)
PARENT_MODULE_SHA256: Final[str] = (
    "636d8c011272f10eeea7ba95c44eeb5c99f301231e8527f1c56262e5dc743020"
)
LEGACY_REQUIRED: Final[tuple[str, ...]] = v1.REQUIRED_COLUMNS
COEFFICIENT_COLUMNS: Final[tuple[str, ...]] = ("s", "a", "b", "c", "d", "e")
COMBINED_REQUIRED: Final[tuple[str, ...]] = (
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
    "SETTLEMENT_PRICE_OPEN",
    "BEGIN",
)


@dataclass(frozen=True, slots=True)
class CatalogV2Protocol:
    """Verified V2 correction linked to the failed immutable V1 contract."""

    config_path: Path
    config_sha256: str
    payload: dict[str, Any]
    parent: v1.CatalogProtocol
    output_directory: Path


@dataclass(frozen=True, slots=True)
class ParsedLegacy:
    """Legacy snapshot rows after deterministic duplicate handling."""

    resolved_frame: pd.DataFrame
    total_rows: int
    ignored_rows: int
    original_core_rows: int
    duplicate_observations: int
    identical_duplicate_observations: int
    conflicting_duplicate_observations: int
    conflicting_keys: int
    conflicting_rows_removed: int
    conflicting_T_keys: int
    member_name: str
    member_bytes: int
    member_crc32: int


@dataclass(frozen=True, slots=True)
class ParsedCombined:
    """New combined schema metadata whose maturity coverage is unresolved."""

    frame: pd.DataFrame
    total_rows: int
    ignored_rows: int
    member_name: str
    member_bytes: int
    member_crc32: int


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"MOEX curve archive catalog V2 {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"MOEX curve archive catalog V2 sidecar missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> CatalogV2Protocol:
    """Verify V2 and the byte-identical V1 parent before canonical publication."""
    path = config_path.resolve()
    config_sha = source_v1.sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("MOEX curve archive catalog V2 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("MOEX curve archive catalog V2 protocol must be a YAML object")
    parent_contract = _mapping(payload.get("parent_v1"), "parent")
    correction = _mapping(payload.get("only_changed_behavior"), "correction")
    output = _mapping(payload.get("output"), "output")
    parent = v1.load_protocol(PROJECT_ROOT / str(parent_contract["config_path"]))
    if (
        payload.get("protocol_id") != "moex_volatility_curve_archive_catalog_v2"
        or payload.get("status") != "sealed_schema_correction_before_canonical_catalog"
        or payload.get("scope") != "source_schema_and_causal_coverage_only"
        or payload.get("research_only") is not True
        or payload.get("live_trading_allowed") is not False
        or parent_contract.get("config_sha256") != PARENT_CONFIG_SHA256
        or parent_contract.get("module_sha256") != PARENT_MODULE_SHA256
        or parent_contract.get("canonical_output_created") is not False
        or correction.get("exact_duplicate_policy") != "collapse_to_one_for_coverage"
        or correction.get("conflicting_duplicate_policy")
        != "exclude_every_row_of_the_ambiguous_key_from_coverage"
        or correction.get("combined_schema_policy")
        != "preserve_and_report_but_no_maturity_coverage_without_T_or_expiry_join"
        or correction.get("coverage_grid_threshold_or_archive_list_changed") is not False
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("MOEX curve archive catalog V2 invariants drifted")
    if (
        parent.config_sha256 != PARENT_CONFIG_SHA256
        or source_v1.sha256_file(PROJECT_ROOT / str(parent_contract["module_path"]))
        != PARENT_MODULE_SHA256
    ):
        raise ValueError("MOEX curve archive catalog V1 parent identity drifted")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    for relative, expected in dependencies.items():
        if source_v1.sha256_file(PROJECT_ROOT / str(relative)) != str(expected).lower():
            raise ValueError(f"MOEX curve archive catalog V2 dependency drift: {relative}")
    return CatalogV2Protocol(
        config_path=path,
        config_sha256=config_sha,
        payload=payload,
        parent=parent,
        output_directory=(PROJECT_ROOT / str(output["directory"])).resolve(),
    )


def _header(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
) -> tuple[str, int, str, list[str]]:
    encoding = v1._stream_encoding(archive, member)
    with archive.open(member) as binary:
        text = io.TextIOWrapper(binary, encoding=encoding, newline="")
        lines: list[str] = []
        for _ in range(30):
            line = text.readline()
            if line == "":
                break
            lines.append(line)
    for index, line in enumerate(lines):
        for delimiter in (";", ","):
            cells = next(csv.reader([line], delimiter=delimiter))
            while cells and not cells[-1].strip():
                cells.pop()
            columns = [cell.strip().lstrip("\ufeff").upper() for cell in cells]
            columns = [{"[#NAME]": "#NAME", "[TIME]": "TIME"}.get(cell, cell) for cell in columns]
            if set(LEGACY_REQUIRED) <= set(columns) or set(COMBINED_REQUIRED) <= set(columns):
                if len(columns) != len(set(columns)):
                    raise ValueError("duplicate MOEX curve archive V2 header columns")
                return encoding, index, delimiter, columns
    raise ValueError("MOEX curve archive V2 supported header was not found")


def _rows(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    encoding: str,
    header_index: int,
    delimiter: str,
    columns: list[str],
) -> Any:
    with archive.open(member) as binary:
        text = io.TextIOWrapper(binary, encoding=encoding, newline="")
        for _ in range(header_index + 1):
            next(text)
        reader = csv.reader(text, delimiter=delimiter)
        for row in reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            while len(row) > len(columns) and not row[-1].strip():
                row.pop()
            if len(row) != len(columns):
                raise ValueError(
                    f"malformed MOEX curve archive V2 row: {len(row)} != {len(columns)}"
                )
            yield row


def _parse_legacy(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    encoding: str,
    header_index: int,
    delimiter: str,
    columns: list[str],
) -> ParsedLegacy:
    indices = {column: columns.index(column) for column in LEGACY_REQUIRED}
    selected: list[list[str | int]] = []
    total_rows = 0
    ignored_rows = 0
    for source_row, row in enumerate(
        _rows(archive, member, encoding, header_index, delimiter, columns), start=1
    ):
        total_rows += 1
        identity = source_v1._asset_from_full_name(row[indices["#NAME"]])
        if identity is None:
            ignored_rows += 1
            continue
        root, asset = identity
        selected.append(
            [source_row, root, asset, *[row[indices[column]] for column in LEGACY_REQUIRED]]
        )
    if total_rows == 0 or not selected:
        raise ValueError("MOEX curve archive V2 legacy member is empty")
    frame = pd.DataFrame(
        selected,
        columns=[
            "source_row",
            "source_root",
            "asset",
            *[column.lower() for column in LEGACY_REQUIRED],
        ],
    ).rename(columns={"#name": "full_name", "time": "source_time", "t": "years_to_expiry"})
    frame["full_name"] = frame["full_name"].astype(str).str.strip()
    frame["small_name"] = frame["small_name"].astype(str).str.strip()
    frame["event_at"] = source_v1._event_time(frame.pop("source_time"))
    for column in (*COEFFICIENT_COLUMNS, "years_to_expiry"):
        frame[column] = source_v1._numeric(frame[column], column)
    frame["curve_feature_eligible"] = frame["years_to_expiry"].gt(0.0)
    frame["available_at"] = frame["event_at"] + pd.Timedelta(
        minutes=v1.AVAILABILITY_DELAY_MINUTES
    )
    key = ["event_at", "full_name", "small_name"]
    duplicated = frame.duplicated(key, keep=False)
    duplicate_observations = int(frame.duplicated(key, keep="first").sum())
    grouped = frame.loc[duplicated].groupby(key, sort=False, dropna=False)
    conflict_by_key = grouped[list(COEFFICIENT_COLUMNS)].nunique(dropna=False).gt(1).any(axis=1)
    T_conflict_by_key = grouped["years_to_expiry"].nunique(dropna=False).gt(1)
    conflicting_index = set(conflict_by_key.index[conflict_by_key])
    conflict_mask = pd.Series(False, index=frame.index)
    if conflicting_index:
        keys = pd.MultiIndex.from_frame(frame.loc[:, key])
        conflict_mask = pd.Series(keys.isin(conflicting_index), index=frame.index)
    conflicting_keys = int(conflict_by_key.sum())
    conflicting_rows_removed = int(conflict_mask.sum())
    conflicting_duplicate_observations = sum(
        len(group) - 1
        for name, group in grouped
        if name in conflicting_index
    )
    identical_duplicate_observations = (
        duplicate_observations - conflicting_duplicate_observations
    )
    resolved = frame.loc[~conflict_mask].drop_duplicates(key, keep="first").copy()
    resolved = resolved.sort_values(
        ["event_at", "asset", "full_name", "source_row"],
        kind="mergesort",
        ignore_index=True,
    )
    return ParsedLegacy(
        resolved_frame=resolved,
        total_rows=total_rows,
        ignored_rows=ignored_rows,
        original_core_rows=len(frame),
        duplicate_observations=duplicate_observations,
        identical_duplicate_observations=int(identical_duplicate_observations),
        conflicting_duplicate_observations=int(conflicting_duplicate_observations),
        conflicting_keys=conflicting_keys,
        conflicting_rows_removed=conflicting_rows_removed,
        conflicting_T_keys=int(T_conflict_by_key.sum()),
        member_name=member.filename,
        member_bytes=member.file_size,
        member_crc32=member.CRC,
    )


def _parse_combined(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    encoding: str,
    header_index: int,
    delimiter: str,
    columns: list[str],
) -> ParsedCombined:
    indices = {column: columns.index(column) for column in COMBINED_REQUIRED}
    selected: list[list[str]] = []
    total_rows = 0
    ignored_rows = 0
    for row in _rows(archive, member, encoding, header_index, delimiter, columns):
        total_rows += 1
        identity = source_v1._asset_from_full_name(row[indices["ISIN"]])
        if identity is None:
            ignored_rows += 1
            continue
        root, asset = identity
        selected.append([row[indices["ISIN"]], row[indices["BEGIN"]], root, asset])
    if total_rows == 0 or not selected:
        raise ValueError("MOEX curve archive V2 combined member is empty")
    frame = pd.DataFrame(selected, columns=["full_name", "source_time", "source_root", "asset"])
    parsed = pd.to_datetime(frame.pop("source_time"), format="%d.%m.%Y %H:%M", errors="raise")
    frame["event_at"] = parsed.dt.tz_localize(
        "Europe/Moscow", ambiguous="raise", nonexistent="raise"
    )
    return ParsedCombined(
        frame=frame,
        total_rows=total_rows,
        ignored_rows=ignored_rows,
        member_name=member.filename,
        member_bytes=member.file_size,
        member_crc32=member.CRC,
    )


def parse_archive(
    content: bytes,
    spec: v1.ArchiveSpec,
) -> ParsedLegacy | ParsedCombined:
    """Apply only the sealed duplicate and combined-schema corrections."""
    if len(content) != spec.expected_bytes:
        raise ValueError(f"MOEX curve archive V2 {spec.archive_id} byte mismatch")
    digest = hashlib.sha256(content).hexdigest()
    if spec.known_sha256 is not None and digest != spec.known_sha256:
        raise ValueError(f"MOEX curve archive V2 {spec.archive_id} SHA-256 mismatch")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        member = v1._safe_single_csv(archive)
        encoding, header_index, delimiter, columns = _header(archive, member)
        if set(LEGACY_REQUIRED) <= set(columns):
            result: ParsedLegacy | ParsedCombined = _parse_legacy(
                archive, member, encoding, header_index, delimiter, columns
            )
        else:
            result = _parse_combined(
                archive, member, encoding, header_index, delimiter, columns
            )
    frame = result.resolved_frame if isinstance(result, ParsedLegacy) else result.frame
    dates = frame["event_at"].dt.tz_localize(None).dt.normalize()
    if dates.lt(spec.source_start).any() or dates.gt(spec.source_end).any():
        raise ValueError(f"MOEX curve archive V2 {spec.archive_id} escaped its interval")
    if dates.ge(v1.PROTECTED_FROM).any():
        raise ValueError(f"MOEX curve archive V2 {spec.archive_id} contains protected data")
    return result


def _legacy_summary(parsed: ParsedLegacy, archive_sha256: str) -> dict[str, Any]:
    compatible = v1.ParsedArchive(
        frame=parsed.resolved_frame,
        total_rows=parsed.total_rows,
        ignored_rows=parsed.ignored_rows,
        member_name=parsed.member_name,
        member_bytes=parsed.member_bytes,
        member_crc32=parsed.member_crc32,
    )
    summary = v1.archive_summary(compatible, archive_sha256)
    return {
        **summary,
        "schema_family": "legacy_with_T",
        "original_core_rows": parsed.original_core_rows,
        "resolved_core_rows": len(parsed.resolved_frame),
        "duplicate_observations": parsed.duplicate_observations,
        "identical_duplicate_observations": parsed.identical_duplicate_observations,
        "conflicting_duplicate_observations": parsed.conflicting_duplicate_observations,
        "conflicting_keys": parsed.conflicting_keys,
        "conflicting_rows_removed": parsed.conflicting_rows_removed,
        "conflicting_T_keys": parsed.conflicting_T_keys,
        "market_price_fields_used_for_catalog": False,
    }


def _combined_summary(parsed: ParsedCombined, archive_sha256: str) -> dict[str, Any]:
    frame = parsed.frame
    source_dates = frame["event_at"].dt.date
    date_has_day = frame["event_at"].dt.hour.lt(19).groupby(source_dates).any()
    date_has_evening = frame["event_at"].dt.hour.ge(19).groupby(source_dates).any()
    return {
        "archive_sha256": archive_sha256,
        "archive_rows": parsed.total_rows,
        "ignored_non_core_rows": parsed.ignored_rows,
        "core_rows": len(frame),
        "curve_feature_eligible_rows": None,
        "nonpositive_T_rows": None,
        "member_name": parsed.member_name,
        "member_bytes": parsed.member_bytes,
        "member_crc32": f"{parsed.member_crc32:08x}",
        "minimum_event_at": frame["event_at"].min().isoformat(),
        "maximum_event_at": frame["event_at"].max().isoformat(),
        "event_dates": int(source_dates.nunique()),
        "day_session_dates": int(date_has_day.sum()),
        "evening_session_dates": int(date_has_evening.sum()),
        "day_and_evening_dates": int((date_has_day & date_has_evening).sum()),
        "full_names": int(frame["full_name"].nunique()),
        "coverage_rows": 0,
        "coverage_by_asset": {
            asset: {
                "available_30d_fraction": None,
                "available_90d_fraction": None,
                "complete_30d_90d_fraction": None,
            }
            for asset in v1.ASSETS
        },
        "complete_coverage_by_hour": {},
        "passes_predeclared_coverage_gate": False,
        "schema_family": "combined_without_T",
        "coverage_unavailable_reason": "missing_T_and_official_series_expiry_join",
        "market_price_fields_used_for_catalog": False,
    }


def _validate_sealed_duplicate_counts(
    protocol: CatalogV2Protocol,
    archive_id: str,
    parsed: ParsedLegacy,
) -> None:
    expected_all = _mapping(protocol.payload.get("sealed_duplicate_audit"), "duplicate audit")
    expected = _mapping(expected_all.get(archive_id), f"duplicate audit {archive_id}")
    actual = {
        "duplicate_observations": parsed.duplicate_observations,
        "identical_duplicate_observations": parsed.identical_duplicate_observations,
        "conflicting_duplicate_observations": parsed.conflicting_duplicate_observations,
        "conflicting_keys": parsed.conflicting_keys,
        "conflicting_rows_removed": parsed.conflicting_rows_removed,
        "conflicting_T_keys": parsed.conflicting_T_keys,
    }
    if actual != {key: int(value) for key, value in expected.items()}:
        raise ValueError(f"MOEX curve archive V2 duplicate audit drift: {archive_id} {actual}")


def _validate_sealed_combined_counts(
    protocol: CatalogV2Protocol,
    parsed: ParsedCombined,
) -> None:
    expected = _mapping(protocol.payload.get("sealed_combined_audit"), "combined audit")
    actual: dict[str, object] = {
        "archive_rows": parsed.total_rows,
        "core_rows": len(parsed.frame),
        "minimum_event_at": parsed.frame["event_at"].min().isoformat(),
        "maximum_event_at": parsed.frame["event_at"].max().isoformat(),
    }
    if actual != dict(expected):
        raise ValueError(f"MOEX curve archive V2 combined audit drift: {actual}")


def _catalog_from_raw(
    protocol: CatalogV2Protocol,
    raw_paths: Mapping[str, Path],
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for spec in protocol.parent.archives:
        content = raw_paths[spec.archive_id].read_bytes()
        parsed = parse_archive(content, spec)
        digest = hashlib.sha256(content).hexdigest()
        if isinstance(parsed, ParsedLegacy):
            _validate_sealed_duplicate_counts(protocol, spec.archive_id, parsed)
            summary = _legacy_summary(parsed, digest)
        else:
            _validate_sealed_combined_counts(protocol, parsed)
            summary = _combined_summary(parsed, digest)
        summaries.append(
            {
                "archive_id": spec.archive_id,
                "official_url": spec.url,
                "archive_bytes": len(content),
                **summary,
            }
        )
    eligible = [
        item["archive_id"] for item in summaries if item["passes_predeclared_coverage_gate"]
    ]
    return {
        "schema_version": 2,
        "protocol_sha256": protocol.config_sha256,
        "parent_v1_protocol_sha256": protocol.parent.config_sha256,
        "coverage_contract": {
            "timezone": "Europe/Moscow",
            "grid": f"{v1.GRID_START}-{v1.GRID_END}/{v1.GRID_FREQUENCY_MINUTES}m",
            "availability_delay_minutes": v1.AVAILABILITY_DELAY_MINUTES,
            "maximum_freshness_minutes": v1.MAXIMUM_FRESHNESS_MINUTES,
            "target_calendar_days": list(v1.TARGET_DAYS),
            "interpolation_extrapolation": "forbidden",
        },
        "schema_correction": {
            "exact_duplicates": "collapsed_once_for_coverage",
            "conflicting_duplicate_keys": "all_rows_excluded_from_coverage",
            "combined_without_T": "preserved_but_not_coverage_eligible",
        },
        "archives": summaries,
        "selection": {
            "minimum_each_asset_fraction": v1.MINIMUM_CANDIDATE_COVERAGE,
            "eligible_archive_ids": eligible,
            "selection_uses_market_outcomes": False,
        },
    }


def build_catalog(
    config_path: Path = DEFAULT_CONFIG,
    cache_directory: Path = v1.DEFAULT_CACHE_DIRECTORY,
    output_directory: Path | None = None,
    *,
    built_at_utc: str | None = None,
) -> Path:
    """Create immutable V2 raw preservation and the corrected coverage catalog."""
    protocol = load_protocol(config_path)
    cache = cache_directory.resolve()
    raw_paths = {
        spec.archive_id: cache / spec.cache_file for spec in protocol.parent.archives
    }
    for spec in protocol.parent.archives:
        path = raw_paths[spec.archive_id]
        if not path.is_file() or path.stat().st_size != spec.expected_bytes:
            raise FileNotFoundError(f"MOEX curve archive V2 cache missing: {spec.archive_id}")
    catalog = _catalog_from_raw(protocol, raw_paths)
    final = (output_directory or protocol.output_directory).resolve()
    if final.exists():
        raise FileExistsError(f"MOEX curve archive catalog V2 already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        raw_directory = temporary / "raw"
        raw_directory.mkdir()
        raw_artifacts: dict[str, dict[str, object]] = {}
        for spec in protocol.parent.archives:
            destination = raw_directory / spec.cache_file
            atomic_write_bytes(destination, raw_paths[spec.archive_id].read_bytes())
            raw_artifacts[spec.archive_id] = {
                "path": destination.relative_to(temporary).as_posix(),
                "bytes": destination.stat().st_size,
                "sha256": source_v1.sha256_file(destination),
                "official_url": spec.url,
            }
        catalog_path = temporary / "archive_coverage.json"
        write_json(catalog_path, catalog)
        built_at = built_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest_core = {
            "schema_version": 2,
            "source_id": "official-moex-volatility-curve-archive-catalog-v2",
            "provider": "MOEX",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": protocol.config_sha256,
            },
            "parent_v1": {
                "config_sha256": PARENT_CONFIG_SHA256,
                "module_sha256": PARENT_MODULE_SHA256,
                "canonical_output_created": False,
                "failure": "duplicate legacy key before output",
            },
            "built_at_utc": built_at,
            "information_contract": {
                "source_schema_and_causal_coverage_only": True,
                "market_price_fields_used": False,
                "returns_targets_labels_or_pnl_used": False,
                "all_source_events_before_2026": True,
                "archive_selection_uses_future_returns": False,
            },
            "counts": {
                "archives": len(protocol.parent.archives),
                "eligible_archives": len(catalog["selection"]["eligible_archive_ids"]),
            },
            "artifacts": {
                "catalog": {
                    "path": catalog_path.name,
                    "bytes": catalog_path.stat().st_size,
                    "sha256": source_v1.sha256_file(catalog_path),
                },
                "raw_archives": raw_artifacts,
            },
        }
        manifest = {
            **manifest_core,
            "manifest_payload_sha256": hashlib.sha256(
                v1._canonical_json(manifest_core)
            ).hexdigest(),
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


def audit_existing_catalog(
    output_directory: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Replay V2 from preserved raw ZIPs and verify exact catalog bytes."""
    protocol = load_protocol(config_path)
    root = (output_directory or protocol.output_directory).resolve()
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    checks: dict[str, bool] = {
        "manifest_payload_sha256": v1._manifest_payload_sha(manifest)
        == manifest["manifest_payload_sha256"],
        "manifest_sidecar_sha256": (root / "manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        == source_v1.sha256_file(manifest_path),
        "protocol_identity": manifest["protocol"]["sha256"] == protocol.config_sha256,
    }
    raw_paths: dict[str, Path] = {}
    for archive_id, artifact in manifest["artifacts"]["raw_archives"].items():
        path = root / artifact["path"]
        raw_paths[archive_id] = path
        checks[f"raw_{archive_id}_exists"] = path.is_file()
        checks[f"raw_{archive_id}_bytes"] = path.is_file() and path.stat().st_size == artifact[
            "bytes"
        ]
        checks[f"raw_{archive_id}_sha256"] = (
            path.is_file() and source_v1.sha256_file(path) == artifact["sha256"]
        )
    catalog_artifact = manifest["artifacts"]["catalog"]
    catalog_path = root / catalog_artifact["path"]
    checks["catalog_bytes"] = catalog_path.stat().st_size == catalog_artifact["bytes"]
    checks["catalog_sha256"] = source_v1.sha256_file(catalog_path) == catalog_artifact["sha256"]
    stored = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    checks["catalog_replay_exact"] = stored == _catalog_from_raw(protocol, raw_paths)
    if not all(checks.values()):
        raise ValueError(f"MOEX curve archive catalog V2 audit failed: {checks}")
    return {
        "source_id": manifest["source_id"],
        "manifest_sha256": source_v1.sha256_file(manifest_path),
        "checks": checks,
        "selection": stored["selection"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cache-directory", type=Path, default=v1.DEFAULT_CACHE_DIRECTORY)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.audit_only:
        result: object = audit_existing_catalog(arguments.output_directory, arguments.config)
    else:
        result = build_catalog(
            arguments.config,
            arguments.cache_directory,
            arguments.output_directory,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
