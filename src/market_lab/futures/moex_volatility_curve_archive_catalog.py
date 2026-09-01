"""Audit stratified public MOEX volatility-curve archives without market outcomes."""

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
from pathlib import Path, PurePosixPath
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from market_lab.futures import moex_volatility_curve_source as source_v1
from market_lab.futures import moex_volatility_curve_source_v2 as source_v2
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = source_v1.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = (
    PROJECT_ROOT / "configs/moex_volatility_curve_archive_catalog_v1.yaml"
)
DEFAULT_CACHE_DIRECTORY: Final[Path] = (
    (PROJECT_ROOT / "data").resolve().parent / "downloads/moex_volatility_curve"
)
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
ASSETS: Final[tuple[str, ...]] = ("RI", "MIX", "SI", "BR")
ARCHIVE_IDS: Final[tuple[str, ...]] = (
    "201801",
    "201901",
    "202006",
    "202101",
    "202108",
    "202108_202405",
)
GRID_START: Final[str] = "10:10:00"
GRID_END: Final[str] = "23:50:00"
GRID_FREQUENCY_MINUTES: Final[int] = 10
EXPECTED_GRID_POINTS: Final[int] = 83
AVAILABILITY_DELAY_MINUTES: Final[int] = 1
MAXIMUM_FRESHNESS_MINUTES: Final[int] = 20
TARGET_DAYS: Final[tuple[int, ...]] = (30, 90)
SECONDS_PER_YEAR: Final[float] = 365.0 * 24.0 * 60.0 * 60.0
MINIMUM_CANDIDATE_COVERAGE: Final[float] = 0.85
REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "#NAME",
    "SMALL_NAME",
    "TIME",
    "S",
    "A",
    "B",
    "C",
    "D",
    "E",
    "T",
)


@dataclass(frozen=True, slots=True)
class ArchiveSpec:
    """One byte-size-pinned official archive candidate."""

    archive_id: str
    url: str
    expected_bytes: int
    cache_file: str
    source_start: pd.Timestamp
    source_end: pd.Timestamp
    known_sha256: str | None


@dataclass(frozen=True, slots=True)
class CatalogProtocol:
    """Verified source-only archive-selection protocol."""

    config_path: Path
    config_sha256: str
    payload: dict[str, Any]
    archives: tuple[ArchiveSpec, ...]
    output_directory: Path


@dataclass(frozen=True, slots=True)
class ParsedArchive:
    """Core-four source metadata needed for causal coverage only."""

    frame: pd.DataFrame
    total_rows: int
    ignored_rows: int
    member_name: str
    member_bytes: int
    member_crc32: int


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"MOEX curve archive catalog {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"MOEX curve archive catalog sidecar is missing: {sidecar}")
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


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> CatalogProtocol:
    """Verify the archive probe contract and implementation before new archive bytes."""
    path = config_path.resolve()
    config_sha = source_v1.sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("MOEX curve archive catalog protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("MOEX curve archive catalog protocol must be a YAML object")
    grid = _mapping(payload.get("coverage_contract"), "coverage contract")
    selection = _mapping(payload.get("selection_gate"), "selection gate")
    output = _mapping(payload.get("output"), "output")
    raw_archives = payload.get("archives")
    if not isinstance(raw_archives, list):
        raise TypeError("MOEX curve archive catalog archives must be a list")
    archives: list[ArchiveSpec] = []
    for raw in raw_archives:
        item = _mapping(raw, "archive")
        known = item.get("known_sha256")
        archives.append(
            ArchiveSpec(
                archive_id=str(item["archive_id"]),
                url=str(item["url"]),
                expected_bytes=int(item["expected_bytes"]),
                cache_file=str(item["cache_file"]),
                source_start=pd.Timestamp(str(item["source_start"])),
                source_end=pd.Timestamp(str(item["source_end"])),
                known_sha256=str(known).lower() if known is not None else None,
            )
        )
    if (
        payload.get("protocol_id") != "moex_volatility_curve_archive_catalog_v1"
        or payload.get("status") != "sealed_before_new_archive_bytes"
        or payload.get("scope") != "source_schema_and_causal_coverage_only"
        or payload.get("research_only") is not True
        or payload.get("live_trading_allowed") is not False
        or tuple(item.archive_id for item in archives) != ARCHIVE_IDS
        or any(item.expected_bytes <= 0 for item in archives)
        or any(item.source_start > item.source_end for item in archives)
        or any(item.source_end >= PROTECTED_FROM for item in archives)
        or grid.get("member_rule") != "exactly_one_safe_csv"
        or grid.get("availability") != "event_at_plus_one_minute"
        or int(grid["maximum_freshness_minutes"]) != MAXIMUM_FRESHNESS_MINUTES
        or int(grid["frequency_minutes"]) != GRID_FREQUENCY_MINUTES
        or grid.get("start") != GRID_START
        or grid.get("end") != GRID_END
        or tuple(int(value) for value in grid["target_calendar_days"]) != TARGET_DAYS
        or selection.get("metric") != "complete_30d_90d_fraction_each_asset"
        or float(selection["minimum_fraction"]) != MINIMUM_CANDIDATE_COVERAGE
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("MOEX curve archive catalog invariants drifted")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    for relative, expected in dependencies.items():
        if source_v1.sha256_file(PROJECT_ROOT / str(relative)) != str(expected).lower():
            raise ValueError(f"MOEX curve archive catalog dependency drift: {relative}")
    return CatalogProtocol(
        config_path=path,
        config_sha256=config_sha,
        payload=payload,
        archives=tuple(archives),
        output_directory=(PROJECT_ROOT / str(output["directory"])).resolve(),
    )


def _safe_single_csv(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    members = [item for item in archive.infolist() if not item.is_dir()]
    if len(members) != 1:
        raise ValueError(f"MOEX curve archive must contain one file, got {len(members)}")
    member = members[0]
    normalized = member.filename.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.suffix.lower() != ".csv"
        or member.flag_bits & 0x1
        or member.file_size <= 0
        or member.file_size > 2_000_000_000
    ):
        raise ValueError(f"unsafe MOEX curve archive member: {member.filename}")
    return member


def _stream_encoding(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> str:
    with archive.open(member) as stream:
        prefix = stream.read(65_536)
    try:
        prefix.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError:
        prefix.decode("cp1251")
        return "cp1251"


def _parse_member(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    encoding: str,
) -> tuple[pd.DataFrame, int, int]:
    with archive.open(member) as binary:
        text = io.TextIOWrapper(binary, encoding=encoding, newline="")
        preamble: list[str] = []
        for _ in range(30):
            line = text.readline()
            if line == "":
                break
            preamble.append(line)
    header_index, delimiter, columns = source_v2._locate_header(preamble)
    if missing := set(REQUIRED_COLUMNS) - set(columns):
        raise ValueError(f"MOEX curve archive lacks columns: {sorted(missing)}")
    indices = {column: columns.index(column) for column in REQUIRED_COLUMNS}
    selected: list[list[str]] = []
    roots: list[str] = []
    assets: list[str] = []
    total_rows = 0
    ignored_rows = 0
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
                    f"malformed MOEX curve archive row {total_rows + 1}: "
                    f"{len(row)} != {len(columns)}"
                )
            total_rows += 1
            identity = source_v1._asset_from_full_name(row[indices["#NAME"]])
            if identity is None:
                ignored_rows += 1
                continue
            root, asset = identity
            selected.append([row[indices[column]] for column in REQUIRED_COLUMNS])
            roots.append(root)
            assets.append(asset)
    if total_rows == 0 or not selected:
        raise ValueError("MOEX curve archive is empty or has no core-four rows")
    frame = pd.DataFrame(selected, columns=[column.lower() for column in REQUIRED_COLUMNS])
    frame = frame.rename(
        columns={"#name": "full_name", "time": "source_time", "t": "years_to_expiry"}
    )
    frame["full_name"] = frame["full_name"].astype(str).str.strip()
    frame["small_name"] = frame["small_name"].astype(str).str.strip()
    frame["event_at"] = source_v1._event_time(frame.pop("source_time"))
    for column in ("s", "a", "b", "c", "d", "e", "years_to_expiry"):
        frame[column] = source_v1._numeric(frame[column], column)
    frame["source_root"] = roots
    frame["asset"] = assets
    frame["curve_feature_eligible"] = frame["years_to_expiry"].gt(0.0)
    frame["available_at"] = frame["event_at"] + pd.Timedelta(
        minutes=AVAILABILITY_DELAY_MINUTES
    )
    if frame.duplicated(["event_at", "full_name", "small_name"]).any():
        raise ValueError("duplicate MOEX curve archive event/series row")
    return frame, total_rows, ignored_rows


def parse_archive(content: bytes, spec: ArchiveSpec) -> ParsedArchive:
    """Parse only source coefficients and timestamps required for coverage selection."""
    if len(content) != spec.expected_bytes:
        raise ValueError(
            f"MOEX curve archive {spec.archive_id} bytes: "
            f"{len(content)} != {spec.expected_bytes}"
        )
    digest = hashlib.sha256(content).hexdigest()
    if spec.known_sha256 is not None and digest != spec.known_sha256:
        raise ValueError(f"MOEX curve archive {spec.archive_id} SHA-256 mismatch")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        member = _safe_single_csv(archive)
        encoding = _stream_encoding(archive, member)
        frame, total_rows, ignored_rows = _parse_member(archive, member, encoding)
    dates = frame["event_at"].dt.tz_localize(None).dt.normalize()
    if dates.lt(spec.source_start).any() or dates.gt(spec.source_end).any():
        raise ValueError(f"MOEX curve archive {spec.archive_id} escaped its date interval")
    if dates.ge(PROTECTED_FROM).any():
        raise ValueError(f"MOEX curve archive {spec.archive_id} contains protected data")
    return ParsedArchive(
        frame=frame.sort_values(
            ["event_at", "asset", "full_name"], kind="mergesort", ignore_index=True
        ),
        total_rows=total_rows,
        ignored_rows=ignored_rows,
        member_name=member.filename,
        member_bytes=member.file_size,
        member_crc32=member.CRC,
    )


def _date_grid(value: object) -> pd.DataFrame:
    start = pd.Timestamp(f"{value} {GRID_START}").tz_localize("Europe/Moscow")
    end = pd.Timestamp(f"{value} {GRID_END}").tz_localize("Europe/Moscow")
    decisions = pd.date_range(start, end, freq=f"{GRID_FREQUENCY_MINUTES}min")
    if len(decisions) != EXPECTED_GRID_POINTS:
        raise ValueError(f"unexpected MOEX curve catalog grid length: {len(decisions)}")
    return pd.DataFrame({"decision_at": decisions})


def coverage_panel(frame: pd.DataFrame) -> pd.DataFrame:
    """Measure causal 30/90-day bracket coverage on every factual source date."""
    rows: list[pd.DataFrame] = []
    local_dates = frame["event_at"].dt.tz_convert("Europe/Moscow").dt.date
    for value, day_events in frame.groupby(local_dates, sort=True):
        grid = _date_grid(value)
        for asset in ASSETS:
            states: list[pd.DataFrame] = []
            asset_events = day_events.loc[day_events["asset"].eq(asset)]
            for _, series in asset_events.groupby("full_name", sort=True):
                ordered = series.loc[
                    :, ["event_at", "available_at", "years_to_expiry", "curve_feature_eligible"]
                ].sort_values("available_at", kind="mergesort")
                joined = pd.merge_asof(
                    grid,
                    ordered,
                    left_on="decision_at",
                    right_on="available_at",
                    direction="backward",
                    allow_exact_matches=True,
                )
                age = (joined["decision_at"] - joined["available_at"]).dt.total_seconds() / 60.0
                elapsed = (
                    (joined["decision_at"] - joined["event_at"]).dt.total_seconds()
                    / SECONDS_PER_YEAR
                )
                joined["effective_T"] = joined["years_to_expiry"] - elapsed
                joined["fresh"] = (
                    joined["available_at"].notna()
                    & age.between(0.0, MAXIMUM_FRESHNESS_MINUTES)
                    & joined["curve_feature_eligible"].eq(True)
                    & joined["effective_T"].gt(0.0)
                )
                states.append(joined.loc[:, ["decision_at", "effective_T", "fresh"]])
            result = grid.copy()
            result["asset"] = asset
            if states:
                combined = pd.concat(states, ignore_index=True)
                valid = combined.loc[combined["fresh"]]
                bracket = valid.groupby("decision_at")["effective_T"].agg(["min", "max"])
                minimum = result["decision_at"].map(bracket["min"])
                maximum = result["decision_at"].map(bracket["max"])
            else:
                minimum = pd.Series(np.nan, index=result.index)
                maximum = pd.Series(np.nan, index=result.index)
            for days in TARGET_DAYS:
                target = days / 365.0
                result[f"available_{days}d"] = minimum.le(target) & maximum.ge(target)
            result["complete_30d_90d"] = result[
                [f"available_{days}d" for days in TARGET_DAYS]
            ].all(axis=1)
            rows.append(result)
    panel = pd.concat(rows, ignore_index=True)
    panel["_asset_order"] = panel["asset"].map(
        {asset: order for order, asset in enumerate(ASSETS)}
    )
    return (
        panel.sort_values(
            ["decision_at", "_asset_order"], kind="mergesort", ignore_index=True
        )
        .drop(columns="_asset_order")
    )


def archive_summary(parsed: ParsedArchive, archive_sha256: str) -> dict[str, Any]:
    """Produce value-free schema and causal-coverage evidence for one archive."""
    frame = parsed.frame
    panel = coverage_panel(frame)
    by_asset = panel.groupby("asset", sort=False)[
        ["available_30d", "available_90d", "complete_30d_90d"]
    ].mean()
    source_dates = frame["event_at"].dt.date
    date_has_day = frame["event_at"].dt.hour.lt(19).groupby(source_dates).any()
    date_has_evening = frame["event_at"].dt.hour.ge(19).groupby(source_dates).any()
    fractions = {
        asset: {
            "available_30d_fraction": float(by_asset.loc[asset, "available_30d"]),
            "available_90d_fraction": float(by_asset.loc[asset, "available_90d"]),
            "complete_30d_90d_fraction": float(
                by_asset.loc[asset, "complete_30d_90d"]
            ),
        }
        for asset in ASSETS
    }
    selected = all(
        values["complete_30d_90d_fraction"] >= MINIMUM_CANDIDATE_COVERAGE
        for values in fractions.values()
    )
    by_hour = panel.groupby(panel["decision_at"].dt.hour)["complete_30d_90d"].mean()
    return {
        "archive_sha256": archive_sha256,
        "archive_rows": parsed.total_rows,
        "ignored_non_core_rows": parsed.ignored_rows,
        "core_rows": len(frame),
        "curve_feature_eligible_rows": int(frame["curve_feature_eligible"].sum()),
        "nonpositive_T_rows": int((~frame["curve_feature_eligible"]).sum()),
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
        "coverage_rows": len(panel),
        "coverage_by_asset": fractions,
        "complete_coverage_by_hour": {
            str(int(hour)): float(value) for hour, value in by_hour.items()
        },
        "passes_predeclared_coverage_gate": selected,
        "contains_market_prices_returns_targets_labels_or_pnl": False,
    }


def _catalog_from_raw(
    protocol: CatalogProtocol,
    raw_paths: Mapping[str, Path],
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for spec in protocol.archives:
        path = raw_paths[spec.archive_id]
        content = path.read_bytes()
        parsed = parse_archive(content, spec)
        summaries.append(
            {
                "archive_id": spec.archive_id,
                "official_url": spec.url,
                "archive_bytes": len(content),
                **archive_summary(parsed, hashlib.sha256(content).hexdigest()),
            }
        )
    eligible = [
        item["archive_id"] for item in summaries if item["passes_predeclared_coverage_gate"]
    ]
    return {
        "schema_version": 1,
        "protocol_sha256": protocol.config_sha256,
        "coverage_contract": {
            "timezone": "Europe/Moscow",
            "grid": f"{GRID_START}-{GRID_END}/{GRID_FREQUENCY_MINUTES}m",
            "availability_delay_minutes": AVAILABILITY_DELAY_MINUTES,
            "maximum_freshness_minutes": MAXIMUM_FRESHNESS_MINUTES,
            "target_calendar_days": list(TARGET_DAYS),
            "interpolation_extrapolation": "forbidden",
        },
        "archives": summaries,
        "selection": {
            "minimum_each_asset_fraction": MINIMUM_CANDIDATE_COVERAGE,
            "eligible_archive_ids": eligible,
            "selection_uses_market_outcomes": False,
        },
    }


def build_catalog(
    config_path: Path = DEFAULT_CONFIG,
    cache_directory: Path = DEFAULT_CACHE_DIRECTORY,
    output_directory: Path | None = None,
    *,
    built_at_utc: str | None = None,
) -> Path:
    """Build an immutable audit catalog and preserve every exact official ZIP."""
    protocol = load_protocol(config_path)
    cache = cache_directory.resolve()
    raw_paths = {spec.archive_id: cache / spec.cache_file for spec in protocol.archives}
    for spec in protocol.archives:
        path = raw_paths[spec.archive_id]
        if not path.is_file() or path.stat().st_size != spec.expected_bytes:
            raise FileNotFoundError(
                f"MOEX curve archive cache missing or wrong size: {spec.archive_id} {path}"
            )
    catalog = _catalog_from_raw(protocol, raw_paths)
    final = (output_directory or protocol.output_directory).resolve()
    if final.exists():
        raise FileExistsError(f"MOEX curve archive catalog already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        raw_directory = temporary / "raw"
        raw_directory.mkdir()
        raw_artifacts: dict[str, dict[str, object]] = {}
        for spec in protocol.archives:
            source_path = raw_paths[spec.archive_id]
            destination = raw_directory / spec.cache_file
            atomic_write_bytes(destination, source_path.read_bytes())
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
            "schema_version": 1,
            "source_id": "official-moex-volatility-curve-archive-catalog-v1",
            "provider": "MOEX",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": protocol.config_sha256,
            },
            "built_at_utc": built_at,
            "information_contract": {
                "source_schema_and_causal_coverage_only": True,
                "contains_market_prices_returns_targets_labels_or_pnl": False,
                "all_source_events_before_2026": True,
                "archive_selection_uses_future_returns": False,
            },
            "counts": {
                "archives": len(protocol.archives),
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


def audit_existing_catalog(
    output_directory: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Verify stored raw bytes and replay every source-only coverage summary."""
    protocol = load_protocol(config_path)
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
    replayed = _catalog_from_raw(protocol, raw_paths)
    checks["catalog_replay_exact"] = stored == replayed
    if not all(checks.values()):
        raise ValueError(f"MOEX curve archive catalog audit failed: {checks}")
    return {
        "source_id": manifest["source_id"],
        "manifest_sha256": source_v1.sha256_file(manifest_path),
        "checks": checks,
        "selection": stored["selection"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cache-directory", type=Path, default=DEFAULT_CACHE_DIRECTORY)
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
