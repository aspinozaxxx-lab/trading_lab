"""Collect an immutable pilot of the public MOEX volatility-curve change log."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Final, Protocol
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests
import yaml

from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_volatility_curve_source_v1.yaml"
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
ROOT_TO_ASSET: Final[dict[str, str]] = {
    "RTS": "RI",
    "MIX": "MIX",
    "SI": "SI",
    "BR": "BR",
}
REQUIRED_COLUMNS: Final[tuple[str, ...]] = (
    "#NAME",
    "SMALL_NAME",
    "TIME",
    "FUTURES_PRICE",
    "S",
    "A",
    "B",
    "C",
    "D",
    "E",
    "T",
)
NUMERIC_COLUMNS: Final[tuple[str, ...]] = (
    "futures_price",
    "s",
    "a",
    "b",
    "c",
    "d",
    "e",
    "t",
)
FORBIDDEN_DERIVED_COLUMNS: Final[frozenset[str]] = frozenset(
    {"return", "returns", "target", "label", "signal", "pnl", "equity"}
)
USER_AGENT: Final[str] = "market-lab-moex-volatility-curve-source/1.0 (research)"


class ResponseLike(Protocol):
    """Minimal requests response used by network code and tests."""

    content: bytes

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    """Minimal requests session used by network code and tests."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> ResponseLike: ...


@dataclass(frozen=True, slots=True)
class VolatilityCurveProtocol:
    """Resolved byte-sealed contract for the source-only pilot."""

    config_path: Path
    config_sha256: str
    payload: dict[str, Any]
    source_start: pd.Timestamp
    source_end: pd.Timestamp
    download_url: str
    expected_archive_bytes: int
    archive_member_name: str
    output_directory: Path


@dataclass(frozen=True, slots=True)
class CurveArchiveParse:
    """Filtered core-four curve events and source-only diagnostics."""

    frame: pd.DataFrame
    total_archive_rows: int
    ignored_non_core_rows: int
    root_counts: dict[str, int]
    member_name: str
    member_bytes: int


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"MOEX volatility curve {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"MOEX volatility curve sidecar is missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> VolatilityCurveProtocol:
    """Verify all source-only invariants before requesting numerical history."""
    path = config_path.resolve()
    config_sha = sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("MOEX volatility curve protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("MOEX volatility curve protocol must be a YAML object")
    dates = _mapping(payload.get("dates"), "dates")
    source = _mapping(payload.get("source"), "source")
    selection = _mapping(payload.get("selection"), "selection")
    temporal = _mapping(payload.get("temporal_semantics"), "temporal semantics")
    output = _mapping(payload.get("output"), "output")
    start = pd.Timestamp(str(dates["pilot_start"])).normalize()
    end = pd.Timestamp(str(dates["pilot_end"])).normalize()
    protected = pd.Timestamp(str(dates["protected_from"])).normalize()
    roots = tuple(str(root).upper() for root in selection["full_code_roots"])
    if (
        payload.get("protocol_id") != "moex_volatility_curve_source_v1"
        or payload.get("status") != "sealed_before_first_volatility_curve_value_byte"
        or payload.get("scope") != "source_only_no_strategy_no_returns_no_pnl"
        or payload.get("research_only") is not True
        or payload.get("live_trading_allowed") is not False
        or start != pd.Timestamp("2021-01-01")
        or end != pd.Timestamp("2021-01-31")
        or protected != PROTECTED_FROM
        or end >= protected
        or roots != tuple(ROOT_TO_ASSET)
        or tuple(source["required_columns"]) != REQUIRED_COLUMNS
        or source.get("archive_kind") != "public_moex_volatility_curve_monthly_zip"
        or int(source["expected_archive_bytes"]) <= 0
        or temporal.get("admissible_join") != "available_at_not_after_decision_at"
        or temporal.get("delivery_buffer") != "one_minute"
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("MOEX volatility curve protocol invariants drifted")
    download_url = str(source["download_url"])
    parsed_url = urlparse(download_url)
    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc != "ftp.moex.com"
        or parsed_url.path != "/pub/FORTS/volat_coeff/202101.zip"
    ):
        raise ValueError("MOEX volatility curve URL escaped the sealed pilot")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    for relative, expected in dependencies.items():
        dependency = PROJECT_ROOT / str(relative)
        if sha256_file(dependency) != str(expected).lower():
            raise ValueError(f"MOEX volatility curve dependency drift: {relative}")
    return VolatilityCurveProtocol(
        config_path=path,
        config_sha256=config_sha,
        payload=payload,
        source_start=start,
        source_end=end,
        download_url=download_url,
        expected_archive_bytes=int(source["expected_archive_bytes"]),
        archive_member_name=str(source["archive_member_name"]),
        output_directory=(PROJECT_ROOT / str(output["directory"])).resolve(),
    )


def fetch_archive_bytes(
    session: SessionLike,
    protocol: VolatilityCurveProtocol,
    *,
    attempts: int = 5,
) -> bytes:
    """Download the sealed public ZIP and reject transport or byte drift."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(
                protocol.download_url,
                headers={"User-Agent": USER_AGENT},
                timeout=180.0,
            )
            response.raise_for_status()
            content = bytes(response.content)
            if len(content) != protocol.expected_archive_bytes:
                raise ValueError(
                    "MOEX volatility curve archive byte drift: "
                    f"{len(content)} != {protocol.expected_archive_bytes}"
                )
            if not content.startswith(b"PK") or not zipfile.is_zipfile(io.BytesIO(content)):
                raise ValueError("MOEX volatility curve response is not a ZIP archive")
            return content
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.25 * (2**attempt))
    raise RuntimeError(f"MOEX volatility curve request failed: {last_error}") from last_error


def _safe_member(archive: zipfile.ZipFile, expected_name: str) -> zipfile.ZipInfo:
    files = [member for member in archive.infolist() if not member.is_dir()]
    if len(files) != 1:
        raise ValueError("MOEX volatility curve ZIP must contain exactly one file")
    member = files[0]
    pure = PurePosixPath(member.filename.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or pure.name.lower() != expected_name.lower():
        raise ValueError(f"unsafe or unexpected curve ZIP member: {member.filename}")
    if member.file_size <= 0 or member.file_size > 1024 * 1024 * 1024:
        raise ValueError("MOEX volatility curve CSV size is outside the pilot bound")
    return member


def _decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("MOEX volatility curve CSV encoding is unsupported")


def _locate_header(lines: list[str]) -> tuple[int, str, list[str]]:
    for index, line in enumerate(lines[:30]):
        for delimiter in (";", ","):
            cells = next(csv.reader([line], delimiter=delimiter))
            normalized = [cell.strip().lstrip("\ufeff").upper() for cell in cells]
            if {"#NAME", "SMALL_NAME", "TIME"} <= set(normalized):
                if len(normalized) != len(set(normalized)):
                    raise ValueError("duplicate MOEX volatility curve columns")
                return index, delimiter, normalized
    raise ValueError("MOEX volatility curve CSV header was not found")


def _asset_from_full_name(value: object) -> tuple[str, str] | None:
    full_name = str(value).strip().upper()
    for root, asset in ROOT_TO_ASSET.items():
        if full_name == root or full_name.startswith(f"{root}-"):
            return root, asset
    return None


def _numeric(series: pd.Series, column: str) -> pd.Series:
    text = series.astype("string").str.strip()
    missing = text.isna() | text.str.lower().isin({"", "null", "none", "nan", "-"})
    normalized = text.str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False)
    normalized = normalized.str.replace(",", ".", regex=False)
    values = pd.to_numeric(normalized.where(~missing), errors="coerce").astype(float)
    invalid = missing | values.isna() | ~np.isfinite(values)
    if invalid.any():
        sample = text.loc[invalid].head(3).tolist()
        raise ValueError(f"invalid MOEX volatility curve {column}: {sample}")
    return values


def _event_time(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    if (~text.str.fullmatch(r"\d{17}", na=False)).any():
        sample = text.loc[~text.str.fullmatch(r"\d{17}", na=False)].head(3).tolist()
        raise ValueError(f"invalid MOEX volatility curve TIME: {sample}")
    parsed = pd.to_datetime(text, format="%Y%m%d%H%M%S%f", errors="raise")
    return parsed.dt.tz_localize("Europe/Moscow", ambiguous="raise", nonexistent="raise")


def parse_archive_bytes(
    content: bytes,
    protocol: VolatilityCurveProtocol,
) -> CurveArchiveParse:
    """Replay the documented change log and retain exact core-four futures roots."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        member = _safe_member(archive, protocol.archive_member_name)
        raw_csv = archive.read(member)
    lines = _decode_csv(raw_csv).splitlines()
    header_index, delimiter, columns = _locate_header(lines)
    if missing := set(REQUIRED_COLUMNS) - set(columns):
        raise ValueError(f"MOEX volatility curve CSV lacks columns: {sorted(missing)}")
    indices = {column: columns.index(column) for column in REQUIRED_COLUMNS}
    selected_rows: list[list[str]] = []
    roots: list[str] = []
    assets: list[str] = []
    total_rows = 0
    ignored_rows = 0
    reader = csv.reader(lines[header_index + 1 :], delimiter=delimiter)
    for row in reader:
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) != len(columns):
            raise ValueError(
                f"malformed MOEX volatility curve row {total_rows + 1}: "
                f"{len(row)} != {len(columns)}"
            )
        total_rows += 1
        identity = _asset_from_full_name(row[indices["#NAME"]])
        if identity is None:
            ignored_rows += 1
            continue
        root, asset = identity
        selected_rows.append([row[columns.index(column)] for column in REQUIRED_COLUMNS])
        roots.append(root)
        assets.append(asset)
    if total_rows == 0:
        raise ValueError("MOEX volatility curve archive is empty")
    if not selected_rows:
        raise ValueError("MOEX volatility curve archive has no core-four rows")
    frame = pd.DataFrame(selected_rows, columns=[column.lower() for column in REQUIRED_COLUMNS])
    frame = frame.rename(
        columns={"#name": "full_name", "time": "source_time", "t": "years_to_expiry"}
    )
    frame["full_name"] = frame["full_name"].astype(str).str.strip()
    frame["small_name"] = frame["small_name"].astype(str).str.strip()
    if frame["full_name"].eq("").any() or frame["small_name"].eq("").any():
        raise ValueError("MOEX volatility curve instrument identity is blank")
    frame["event_at"] = _event_time(frame.pop("source_time"))
    source_dates = frame["event_at"].dt.tz_localize(None).dt.normalize()
    if source_dates.lt(protocol.source_start).any() or source_dates.gt(protocol.source_end).any():
        raise ValueError("MOEX volatility curve event escaped the sealed pilot interval")
    if source_dates.ge(PROTECTED_FROM).any():
        raise ValueError("MOEX volatility curve archive contains a protected event")
    for column in NUMERIC_COLUMNS:
        target_column = "years_to_expiry" if column == "t" else column
        if target_column == "years_to_expiry":
            frame[target_column] = _numeric(frame[target_column], target_column)
        else:
            frame[target_column] = _numeric(frame[target_column], target_column)
    if frame["years_to_expiry"].le(0.0).any():
        raise ValueError("MOEX volatility curve years_to_expiry must be positive")
    frame["source_root"] = roots
    frame["asset"] = assets
    frame["available_at"] = frame["event_at"] + pd.Timedelta(minutes=1)
    frame["availability_rule"] = "event_at_plus_one_minute_not_after_decision_at"
    frame["historical_event_log"] = True
    frame["archive_publication_was_later"] = True
    frame["provider"] = "MOEX"
    if frame.duplicated(["event_at", "full_name", "small_name"]).any():
        raise ValueError("duplicate MOEX volatility curve event/instrument row")
    frame = frame.sort_values(
        ["event_at", "asset", "full_name", "small_name"],
        kind="mergesort",
        ignore_index=True,
    )
    if set(frame.columns.str.lower()) & FORBIDDEN_DERIVED_COLUMNS:
        raise ValueError("MOEX volatility curve source contains a derived outcome column")
    counts = {root: int(frame["source_root"].eq(root).sum()) for root in ROOT_TO_ASSET}
    return CurveArchiveParse(
        frame=frame,
        total_archive_rows=total_rows,
        ignored_non_core_rows=ignored_rows,
        root_counts=counts,
        member_name=member.filename,
        member_bytes=member.file_size,
    )


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _checks(
    parsed: CurveArchiveParse,
    protocol: VolatilityCurveProtocol,
    content: bytes,
) -> dict[str, bool]:
    frame = parsed.frame
    event_dates = frame["event_at"].dt.tz_localize(None).dt.normalize()
    return {
        "protocol_seal_verified": True,
        "archive_exact_expected_bytes": len(content) == protocol.expected_archive_bytes,
        "archive_is_zip": content.startswith(b"PK"),
        "archive_exact_member": PurePosixPath(parsed.member_name).name.lower()
        == protocol.archive_member_name.lower(),
        "archive_rows_positive": parsed.total_archive_rows > 0,
        "core_rows_positive": len(frame) > 0,
        "source_dates_in_pilot": bool(
            event_dates.between(protocol.source_start, protocol.source_end).all()
        ),
        "protected_events_zero": bool(event_dates.lt(PROTECTED_FROM).all()),
        "unique_event_instrument": not frame.duplicated(
            ["event_at", "full_name", "small_name"]
        ).any(),
        "exact_declared_assets": set(frame["asset"]) <= set(ROOT_TO_ASSET.values()),
        "available_at_strictly_after_event": bool(
            frame["available_at"].gt(frame["event_at"]).all()
        ),
        "derived_outcome_columns_absent": not bool(
            set(frame.columns.str.lower()) & FORBIDDEN_DERIVED_COLUMNS
        ),
    }


def write_source_from_bytes(
    content: bytes,
    protocol: VolatilityCurveProtocol,
    output_directory: Path | None = None,
    *,
    fetched_at_utc: str | None = None,
) -> Path:
    """Create the immutable pilot from exact public archive bytes."""
    final = (output_directory or protocol.output_directory).resolve()
    if final.exists():
        raise FileExistsError(f"MOEX volatility curve output already exists: {final}")
    if len(content) != protocol.expected_archive_bytes:
        raise ValueError("MOEX volatility curve bytes do not match the sealed protocol")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        parsed = parse_archive_bytes(content, protocol)
        checks = _checks(parsed, protocol, content)
        if not all(checks.values()):
            raise ValueError(f"MOEX volatility curve source audit failed: {checks}")
        raw_path = temporary / "official_moex_volatility_curve_202101.zip"
        atomic_write_bytes(raw_path, content)
        processed_path = temporary / "volatility_curve_core4.parquet"
        _atomic_parquet(processed_path, parsed.frame)
        counts = {
            "archive_rows": parsed.total_archive_rows,
            "ignored_non_core_rows": parsed.ignored_non_core_rows,
            "core_rows": len(parsed.frame),
            "root_rows": parsed.root_counts,
            "event_dates": int(parsed.frame["event_at"].dt.date.nunique()),
            "full_names": int(parsed.frame["full_name"].nunique()),
            "events": int(parsed.frame["event_at"].nunique()),
        }
        audit_path = temporary / "source_audit.json"
        write_json(audit_path, {"schema_version": 1, "checks": checks, "counts": counts})
        fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-moex-volatility-curve-core4-pilot-2021-01-v1",
            "provider": "MOEX",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": protocol.config_sha256,
            },
            "fetched_at_utc": fetched_at,
            "official_endpoint": protocol.download_url,
            "request_bounds": {
                "pilot_start": protocol.source_start.date().isoformat(),
                "pilot_end": protocol.source_end.date().isoformat(),
                "protected_from": PROTECTED_FROM.date().isoformat(),
                "all_events_before_protected_from": True,
            },
            "temporal_semantics": {
                "event_at": "documented current time of volatility-parameter change",
                "timezone": "Europe/Moscow",
                "available_at": "event_at plus one minute delivery buffer",
                "admissible_join": "available_at not after decision_at",
                "historical_event_log": True,
                "archive_publication_was_later": True,
                "live_feed_delivery_not_proved_by_archive": True,
                "contains_returns_targets_labels_or_pnl": False,
            },
            "selection": {
                "roots": list(ROOT_TO_ASSET),
                "assets": list(ROOT_TO_ASSET.values()),
                "price_or_outcome_filter_used": False,
                "series_or_maturity_filter_used": False,
            },
            "counts": counts,
            "artifacts": {
                "raw_archive": {
                    "path": raw_path.name,
                    "bytes": raw_path.stat().st_size,
                    "sha256": sha256_file(raw_path),
                },
                "processed": {
                    "path": processed_path.name,
                    "bytes": processed_path.stat().st_size,
                    "sha256": sha256_file(processed_path),
                    "rows": len(parsed.frame),
                    "columns": parsed.frame.columns.tolist(),
                    "minimum_event_at": parsed.frame["event_at"].min().isoformat(),
                    "maximum_event_at": parsed.frame["event_at"].max().isoformat(),
                },
                "audit": {
                    "path": audit_path.name,
                    "bytes": audit_path.stat().st_size,
                    "sha256": sha256_file(audit_path),
                },
            },
        }
        manifest = {
            **manifest_core,
            "manifest_payload_sha256": hashlib.sha256(_canonical_json(manifest_core)).hexdigest(),
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        manifest_sha = sha256_file(manifest_path)
        atomic_write_text(temporary / "manifest.sha256", f"{manifest_sha}  manifest.json\n")
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def collect_source(
    config_path: Path = DEFAULT_CONFIG,
    output_directory: Path | None = None,
    *,
    session: SessionLike | None = None,
    fetched_at_utc: str | None = None,
) -> Path:
    """Download and build the sealed target-free pilot exactly once."""
    protocol = load_protocol(config_path)
    network_session: SessionLike = session or requests.Session()
    content = fetch_archive_bytes(network_session, protocol)
    return write_source_from_bytes(
        content,
        protocol,
        output_directory,
        fetched_at_utc=fetched_at_utc,
    )


def audit_existing_source(
    output_directory: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, object]:
    """Replay raw bytes and verify immutable source artifacts without mutation."""
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
        == sha256_file(manifest_path),
        "protocol_identity": manifest["protocol"]["sha256"] == protocol.config_sha256,
    }
    for name, artifact in manifest["artifacts"].items():
        path = root / artifact["path"]
        checks[f"{name}_exists"] = path.is_file()
        checks[f"{name}_bytes"] = path.is_file() and path.stat().st_size == artifact["bytes"]
        checks[f"{name}_sha256"] = path.is_file() and sha256_file(path) == artifact["sha256"]
    raw_path = root / manifest["artifacts"]["raw_archive"]["path"]
    replay = parse_archive_bytes(raw_path.read_bytes(), protocol)
    stored = pd.read_parquet(root / manifest["artifacts"]["processed"]["path"])
    try:
        pd.testing.assert_frame_equal(stored, replay.frame, check_like=False)
        checks["raw_replay_exact"] = True
    except AssertionError:
        checks["raw_replay_exact"] = False
    checks["processed_rows"] = len(stored) == manifest["artifacts"]["processed"]["rows"]
    event_dates = stored["event_at"].dt.tz_localize(None).dt.normalize()
    checks["protected_events_zero"] = bool(event_dates.lt(PROTECTED_FROM).all())
    if not all(checks.values()):
        raise ValueError(f"MOEX volatility curve existing-source audit failed: {checks}")
    return {
        "source_id": manifest["source_id"],
        "checks": checks,
        "counts": manifest["counts"],
        "manifest_sha256": sha256_file(manifest_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.audit_only:
        print(
            json.dumps(
                audit_existing_source(arguments.output_directory, arguments.config),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(collect_source(arguments.config, arguments.output_directory))


if __name__ == "__main__":
    main()
