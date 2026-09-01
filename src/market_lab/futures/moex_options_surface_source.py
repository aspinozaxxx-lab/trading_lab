"""Collect an immutable, target-free pilot of historical MOEX option results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
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
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_options_surface_source_v1.yaml"
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
ROOT_TO_ASSET: Final[dict[str, str]] = {
    "RI": "RI",
    "MX": "MIX",
    "SI": "SI",
    "BR": "BR",
}
REQUIRED_ARCHIVE_COLUMNS: Final[tuple[str, ...]] = (
    "BOARDID",
    "TRADEDATE",
    "SECID",
    "OPEN",
    "LOW",
    "HIGH",
    "CLOSE",
    "OPENPOSITIONVALUE",
    "VALUE",
    "VOLUME",
    "OPENPOSITION",
    "SETTLEPRICE",
    "WAPRICE",
    "CHANGE",
    "QTY",
    "NUMTRADES",
    "THEOR_PRICE",
)
FLOAT_COLUMNS: Final[tuple[str, ...]] = (
    "open",
    "low",
    "high",
    "close",
    "openpositionvalue",
    "value",
    "settleprice",
    "waprice",
    "change",
    "theor_price",
)
INTEGER_COLUMNS: Final[tuple[str, ...]] = (
    "volume",
    "openposition",
    "qty",
    "numtrades",
)
CALL_MONTH_CODES: Final[str] = "ABCDEFGHIJKL"
PUT_MONTH_CODES: Final[str] = "MNOPQRSTUVWX"
OPTION_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?P<root>RI|MX|SI|BR)(?P<strike>-?\d+(?:\.\d+)?)"
    r"(?P<settlement>[ABC])(?P<month>[A-X])(?P<year>\d)(?P<week>[A-E]?)$"
)
FORBIDDEN_DERIVED_COLUMNS: Final[frozenset[str]] = frozenset(
    {"return", "returns", "target", "label", "signal", "pnl", "equity"}
)
USER_AGENT: Final[str] = "market-lab-moex-options-source/1.0 (research)"


class ResponseLike(Protocol):
    """Minimal requests response used by network code and synthetic tests."""

    content: bytes

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    """Minimal requests session used by network code and synthetic tests."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> ResponseLike: ...


@dataclass(frozen=True, slots=True)
class OptionsSourceProtocol:
    """Resolved, byte-sealed source-only pilot contract."""

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
class ArchiveParse:
    """Filtered core-four option observations and source-only parse diagnostics."""

    frame: pd.DataFrame
    total_archive_rows: int
    ignored_non_core_rows: int
    core_prefixed_unparsed: tuple[str, ...]
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
        raise TypeError(f"MOEX options {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"MOEX options protocol sidecar is missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> OptionsSourceProtocol:
    """Verify the source-only contract before any archive byte is requested."""
    path = config_path.resolve()
    config_sha = sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("MOEX options protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("MOEX options protocol must be a YAML object")
    dates = _mapping(payload.get("dates"), "dates")
    source = _mapping(payload.get("source"), "source")
    selection = _mapping(payload.get("selection"), "selection")
    temporal = _mapping(payload.get("temporal_semantics"), "temporal semantics")
    output = _mapping(payload.get("output"), "output")
    start = pd.Timestamp(str(dates["pilot_start"])).normalize()
    end = pd.Timestamp(str(dates["pilot_end"])).normalize()
    protected = pd.Timestamp(str(dates["protected_from"])).normalize()
    roots = tuple(str(value).upper() for value in selection["short_code_roots"])
    if (
        payload.get("protocol_id") != "moex_options_surface_source_v1"
        or payload.get("status") != "sealed_before_first_historical_option_price_byte"
        or payload.get("scope") != "source_only_no_strategy_no_returns_no_pnl"
        or payload.get("research_only") is not True
        or payload.get("live_trading_allowed") is not False
        or start != pd.Timestamp("2021-01-01")
        or end != pd.Timestamp("2021-01-31")
        or protected != PROTECTED_FROM
        or end >= protected
        or roots != tuple(ROOT_TO_ASSET)
        or tuple(source["required_columns"]) != REQUIRED_ARCHIVE_COLUMNS
        or source.get("archive_kind") != "official_iss_monthly_securities_csv_zip"
        or int(source["expected_archive_bytes"]) <= 0
        or temporal.get("admissible_join") != "source_date_strictly_before_decision_date"
        or temporal.get("same_day_signal_allowed") is not False
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("MOEX options source protocol invariants drifted")
    download_url = str(source["download_url"])
    parsed_url = urlparse(download_url)
    expected_suffix = "/years/2021/months/01/securities.csv.zip"
    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc != "iss.moex.com"
        or not parsed_url.path.endswith(expected_suffix)
    ):
        raise ValueError("MOEX options download URL escaped the sealed pilot")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    for relative, expected in dependencies.items():
        dependency = PROJECT_ROOT / str(relative)
        if sha256_file(dependency) != str(expected).lower():
            raise ValueError(f"MOEX options implementation dependency drift: {relative}")
    output_directory = (PROJECT_ROOT / str(output["directory"])).resolve()
    return OptionsSourceProtocol(
        config_path=path,
        config_sha256=config_sha,
        payload=payload,
        source_start=start,
        source_end=end,
        download_url=download_url,
        expected_archive_bytes=int(source["expected_archive_bytes"]),
        archive_member_name=str(source["archive_member_name"]),
        output_directory=output_directory,
    )


def fetch_archive_bytes(
    session: SessionLike,
    protocol: OptionsSourceProtocol,
    *,
    attempts: int = 5,
) -> bytes:
    """Download the one sealed ZIP and reject byte-count drift."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(
                protocol.download_url,
                headers={"User-Agent": USER_AGENT},
                timeout=120.0,
            )
            response.raise_for_status()
            content = bytes(response.content)
            if len(content) != protocol.expected_archive_bytes:
                raise ValueError(
                    "MOEX options archive byte count drift: "
                    f"{len(content)} != {protocol.expected_archive_bytes}"
                )
            if not content.startswith(b"PK") or not zipfile.is_zipfile(io.BytesIO(content)):
                raise ValueError("MOEX options response is not a ZIP archive")
            return content
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(0.25 * (2**attempt))
    raise RuntimeError(f"MOEX options archive request failed: {last_error}") from last_error


def _safe_member(archive: zipfile.ZipFile, expected_name: str) -> zipfile.ZipInfo:
    files = [member for member in archive.infolist() if not member.is_dir()]
    if len(files) != 1:
        raise ValueError("MOEX options ZIP must contain exactly one file")
    member = files[0]
    pure = PurePosixPath(member.filename.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or pure.name != expected_name:
        raise ValueError(f"unsafe or unexpected MOEX options ZIP member: {member.filename}")
    if member.file_size <= 0 or member.file_size > 512 * 1024 * 1024:
        raise ValueError("MOEX options CSV uncompressed size is outside the pilot bound")
    return member


def _decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("MOEX options CSV is neither UTF-8 nor Windows-1251")


def _locate_header(lines: list[str]) -> tuple[int, str, list[str]]:
    required = {"TRADEDATE", "SECID"}
    for index, line in enumerate(lines[:50]):
        for delimiter in (";", ","):
            cells = next(csv.reader([line], delimiter=delimiter))
            normalized = [cell.strip().lstrip("\ufeff").upper() for cell in cells]
            if required <= set(normalized):
                if len(normalized) != len(set(normalized)):
                    raise ValueError("duplicate columns in MOEX options CSV")
                return index, delimiter, normalized
    raise ValueError("MOEX options CSV header was not found")


def parse_option_short_code(value: object) -> dict[str, object] | None:
    """Parse the official short-code fields without guessing an exact expiry day."""
    security_id = str(value).strip().upper()
    match = OPTION_CODE_PATTERN.fullmatch(security_id)
    if match is None:
        return None
    month_code = match.group("month")
    if month_code in CALL_MONTH_CODES:
        option_type = "call"
        expiry_month = CALL_MONTH_CODES.index(month_code) + 1
    elif month_code in PUT_MONTH_CODES:
        option_type = "put"
        expiry_month = PUT_MONTH_CODES.index(month_code) + 1
    else:  # Defensive: the regex currently makes this unreachable.
        return None
    root = match.group("root")
    return {
        "source_root": root,
        "asset": ROOT_TO_ASSET[root],
        "strike": float(match.group("strike")),
        "settlement_code": match.group("settlement"),
        "option_type": option_type,
        "encoded_expiry_month": expiry_month,
        "encoded_expiry_year_digit": int(match.group("year")),
        "encoded_week_code": match.group("week") or None,
    }


def _numeric(series: pd.Series, column: str) -> pd.Series:
    text = series.astype("string").str.strip()
    missing = text.isna() | text.str.lower().isin({"", "null", "none", "nan", "-"})
    normalized = text.str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False)
    normalized = normalized.str.replace(",", ".", regex=False)
    values = pd.to_numeric(normalized.where(~missing), errors="coerce").astype(float)
    invalid = ~missing & values.isna()
    if invalid.any():
        sample = text.loc[invalid].head(3).tolist()
        raise ValueError(f"non-numeric MOEX options {column}: {sample}")
    if np.isinf(values.to_numpy(dtype=float, na_value=np.nan)).any():
        raise ValueError(f"infinite MOEX options {column}")
    return values


def parse_archive_bytes(content: bytes, protocol: OptionsSourceProtocol) -> ArchiveParse:
    """Replay the official CSV and retain only exact parsed RI/MIX/SI/BR options."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        member = _safe_member(archive, protocol.archive_member_name)
        raw_csv = archive.read(member)
    text = _decode_csv(raw_csv)
    lines = text.splitlines()
    header_index, delimiter, columns = _locate_header(lines)
    missing_columns = set(REQUIRED_ARCHIVE_COLUMNS) - set(columns)
    if missing_columns:
        raise ValueError(f"MOEX options CSV lacks columns: {sorted(missing_columns)}")
    indices = {column: columns.index(column) for column in REQUIRED_ARCHIVE_COLUMNS}
    selected_rows: list[list[str]] = []
    parsed_fields: list[dict[str, object]] = []
    unparsed: set[str] = set()
    total_rows = 0
    ignored_rows = 0
    reader = csv.reader(lines[header_index + 1 :], delimiter=delimiter)
    for row in reader:
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) != len(columns):
            raise ValueError(
                f"malformed MOEX options CSV row {total_rows + 1}: "
                f"{len(row)} != {len(columns)}"
            )
        total_rows += 1
        security_id = row[indices["SECID"]].strip().upper()
        parsed = parse_option_short_code(security_id)
        if parsed is None:
            if security_id[:2] in ROOT_TO_ASSET:
                unparsed.add(security_id)
            else:
                ignored_rows += 1
            continue
        selected_rows.append([row[columns.index(column)] for column in columns])
        parsed_fields.append(parsed)
    if total_rows == 0:
        raise ValueError("MOEX options archive contains no rows")
    if unparsed:
        raise ValueError(
            "unparsed core-prefixed MOEX option codes: " + ", ".join(sorted(unparsed)[:20])
        )
    if not selected_rows:
        raise ValueError("MOEX options archive contains no parsed core-four rows")
    frame = pd.DataFrame(selected_rows, columns=[column.lower() for column in columns])
    frame = frame.loc[:, [column.lower() for column in REQUIRED_ARCHIVE_COLUMNS]].copy()
    frame = frame.rename(columns={"tradedate": "source_date", "secid": "security_id"})
    frame["source_date"] = pd.to_datetime(frame["source_date"], errors="raise").dt.normalize()
    if frame["source_date"].lt(protocol.source_start).any() or frame["source_date"].gt(
        protocol.source_end
    ).any():
        raise ValueError("MOEX options row escaped the sealed pilot interval")
    if frame["source_date"].ge(PROTECTED_FROM).any():
        raise ValueError("MOEX options archive contains a protected row")
    frame["security_id"] = frame["security_id"].astype(str).str.strip().str.upper()
    frame["board_id"] = frame.pop("boardid").astype(str).str.strip().str.upper()
    for column in FLOAT_COLUMNS:
        frame[column] = _numeric(frame[column], column)
    for column in INTEGER_COLUMNS:
        values = _numeric(frame[column], column)
        non_integer = values.notna() & ~np.isclose(values, np.round(values), atol=1e-9)
        if non_integer.any():
            raise ValueError(f"non-integer MOEX options {column}")
        frame[column] = values.round().astype("Int64")
    parsed_frame = pd.DataFrame(parsed_fields)
    for column in parsed_frame.columns:
        frame[column] = parsed_frame[column].to_numpy()
    if frame.duplicated(["source_date", "board_id", "security_id"]).any():
        raise ValueError("duplicate MOEX options date/board/security row")
    frame["available_at"] = (
        frame["source_date"].dt.tz_localize("Europe/Moscow") + pd.Timedelta(days=1)
    )
    frame["availability_rule"] = "source_date_strictly_before_decision_date"
    frame["historical_final_archive"] = True
    frame["revision_vintage_proved"] = False
    frame["provider"] = "MOEX ISS"
    frame = frame.sort_values(
        ["source_date", "asset", "security_id", "board_id"],
        kind="mergesort",
        ignore_index=True,
    )
    if set(frame.columns.str.lower()) & FORBIDDEN_DERIVED_COLUMNS:
        raise ValueError("MOEX options source unexpectedly contains a derived outcome column")
    counts = {
        root: int(frame["source_root"].eq(root).sum()) for root in ROOT_TO_ASSET
    }
    return ArchiveParse(
        frame=frame,
        total_archive_rows=total_rows,
        ignored_non_core_rows=ignored_rows,
        core_prefixed_unparsed=tuple(),
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


def _audit_checks(
    parsed: ArchiveParse,
    protocol: OptionsSourceProtocol,
    archive_bytes: bytes,
) -> dict[str, bool]:
    frame = parsed.frame
    return {
        "protocol_seal_verified": True,
        "archive_exact_expected_bytes": len(archive_bytes) == protocol.expected_archive_bytes,
        "archive_is_zip": archive_bytes.startswith(b"PK"),
        "archive_exact_member": PurePosixPath(parsed.member_name).name
        == protocol.archive_member_name,
        "archive_rows_positive": parsed.total_archive_rows > 0,
        "core_rows_positive": len(frame) > 0,
        "core_codes_all_parsed": not parsed.core_prefixed_unparsed,
        "source_dates_in_pilot": bool(
            frame["source_date"].between(protocol.source_start, protocol.source_end).all()
        ),
        "protected_rows_zero": bool(frame["source_date"].lt(PROTECTED_FROM).all()),
        "unique_date_board_security": not frame.duplicated(
            ["source_date", "board_id", "security_id"]
        ).any(),
        "exact_declared_assets": set(frame["asset"]) <= set(ROOT_TO_ASSET.values()),
        "same_day_signal_disabled": protocol.payload["temporal_semantics"]
        ["same_day_signal_allowed"]
        is False,
        "derived_outcome_columns_absent": not bool(
            set(frame.columns.str.lower()) & FORBIDDEN_DERIVED_COLUMNS
        ),
    }


def write_source_from_bytes(
    archive_bytes: bytes,
    protocol: OptionsSourceProtocol,
    output_directory: Path | None = None,
    *,
    fetched_at_utc: str | None = None,
) -> Path:
    """Create one immutable source directory from the exact sealed archive."""
    final = (output_directory or protocol.output_directory).resolve()
    if final.exists():
        raise FileExistsError(f"MOEX options output already exists: {final}")
    if len(archive_bytes) != protocol.expected_archive_bytes:
        raise ValueError("MOEX options archive bytes do not match the sealed protocol")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        parsed = parse_archive_bytes(archive_bytes, protocol)
        checks = _audit_checks(parsed, protocol, archive_bytes)
        if not all(checks.values()):
            raise ValueError(f"MOEX options source audit failed: {checks}")
        raw_path = temporary / "official_moex_options_2021_01.csv.zip"
        atomic_write_bytes(raw_path, archive_bytes)
        processed_path = temporary / "options_daily_core4.parquet"
        _atomic_parquet(processed_path, parsed.frame)
        audit_path = temporary / "source_audit.json"
        audit_payload = {
            "schema_version": 1,
            "checks": checks,
            "counts": {
                "archive_rows": parsed.total_archive_rows,
                "ignored_non_core_rows": parsed.ignored_non_core_rows,
                "core_rows": len(parsed.frame),
                "root_rows": parsed.root_counts,
                "source_dates": int(parsed.frame["source_date"].nunique()),
                "securities": int(parsed.frame["security_id"].nunique()),
            },
        }
        write_json(audit_path, audit_payload)
        fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-moex-options-core4-pilot-2021-01-v1",
            "provider": "MOEX ISS",
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
                "all_market_rows_before_protected_from": True,
            },
            "temporal_semantics": {
                "source_date": "MOEX final trading-results date",
                "available_at": "00:00 Europe/Moscow on the next calendar date",
                "admissible_join": "source_date strictly before decision_date",
                "same_day_signal_allowed": False,
                "historical_final_archive": True,
                "revision_vintage_proved": False,
                "contains_returns_targets_labels_or_pnl": False,
            },
            "selection": {
                "roots": list(ROOT_TO_ASSET),
                "assets": list(ROOT_TO_ASSET.values()),
                "price_or_outcome_filter_used": False,
                "short_code_parse_only": True,
                "exact_expiry_day_inferred": False,
            },
            "counts": audit_payload["counts"],
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
                    "minimum_source_date": parsed.frame["source_date"].min().date().isoformat(),
                    "maximum_source_date": parsed.frame["source_date"].max().date().isoformat(),
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


def collect_options_source(
    config_path: Path = DEFAULT_CONFIG,
    output_directory: Path | None = None,
    *,
    session: SessionLike | None = None,
    fetched_at_utc: str | None = None,
) -> Path:
    """Download and build the sealed target-free pilot exactly once."""
    protocol = load_protocol(config_path)
    network_session: SessionLike = session or requests.Session()
    archive_bytes = fetch_archive_bytes(network_session, protocol)
    return write_source_from_bytes(
        archive_bytes,
        protocol,
        output_directory,
        fetched_at_utc=fetched_at_utc,
    )


def audit_existing_source(
    output_directory: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, object]:
    """Replay raw bytes and verify every immutable source artifact without mutation."""
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
    checks["protected_rows_zero"] = bool(stored["source_date"].lt(PROTECTED_FROM).all())
    if not all(checks.values()):
        raise ValueError(f"MOEX options existing-source audit failed: {checks}")
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
        print(
            collect_options_source(
                arguments.config,
                arguments.output_directory,
            )
        )


if __name__ == "__main__":
    main()
