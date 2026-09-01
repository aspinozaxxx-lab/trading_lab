"""Probe the official MOEX historical option-series calendar for numeric IDs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_volatility_curve_source as source_v1
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = source_v1.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_option_series_calendar_probe_v1.yaml"
PROBE_DATE: Final[pd.Timestamp] = pd.Timestamp("2021-09-01")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01")
CORE_ASSET_CODES: Final[tuple[str, ...]] = ("RTS", "MIX", "SI", "BR")
REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(
    {"asset_code", "series_name", "expiration_date"}
)
IDENTIFIER_CANDIDATES: Final[tuple[str, ...]] = (
    "option_series_id",
    "series_id",
    "id",
)
FORBIDDEN_MARKET_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "price",
        "last",
        "bid",
        "offer",
        "open",
        "high",
        "low",
        "close",
        "waprice",
        "yield",
        "value",
        "volume",
        "numtrades",
        "settlement_price",
    }
)


@dataclass(frozen=True, slots=True)
class CalendarProbeProtocol:
    """Byte-sealed metadata-only historical calendar request."""

    config_path: Path
    config_sha256: str
    payload: dict[str, Any]
    request_url: str
    output_directory: Path


@dataclass(frozen=True, slots=True)
class CalendarParse:
    """Documented option-series rows and exact response-schema evidence."""

    frame: pd.DataFrame
    block_columns: tuple[str, ...]
    total_rows: int
    core_rows: int
    identifier_columns: tuple[str, ...]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"MOEX option calendar probe {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"MOEX option calendar sidecar missing: {sidecar}")
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


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> CalendarProbeProtocol:
    """Verify request semantics and implementation before the first response byte."""
    path = config_path.resolve()
    config_sha = source_v1.sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("MOEX option calendar probe protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("MOEX option calendar probe protocol must be a YAML object")
    request = _mapping(payload.get("request"), "request")
    purpose = _mapping(payload.get("schema_question"), "schema question")
    output = _mapping(payload.get("output"), "output")
    if (
        payload.get("protocol_id") != "moex_option_series_calendar_probe_v1"
        or payload.get("status") != "sealed_before_first_response_byte"
        or payload.get("scope") != "historical_static_metadata_schema_only"
        or payload.get("research_only") is not True
        or payload.get("live_trading_allowed") is not False
        or request.get("date") != PROBE_DATE.date().isoformat()
        or request.get("block") != "options"
        or request.get("iss_meta") is not False
        or "marketdata" in str(request["url"]).lower()
        or purpose.get("required_mapping") != "option_series_id_to_expiration_date"
        or purpose.get("price_return_target_or_pnl_used") is not False
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("MOEX option calendar probe invariants drifted")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    for relative, expected in dependencies.items():
        if source_v1.sha256_file(PROJECT_ROOT / str(relative)) != str(expected).lower():
            raise ValueError(f"MOEX option calendar probe dependency drift: {relative}")
    return CalendarProbeProtocol(
        config_path=path,
        config_sha256=config_sha,
        payload=payload,
        request_url=str(request["url"]),
        output_directory=(PROJECT_ROOT / str(output["directory"])).resolve(),
    )


def parse_response(content: bytes) -> CalendarParse:
    """Parse only the documented `options` calendar block and reject market fields."""
    try:
        payload = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("MOEX option calendar response is not UTF-8 JSON") from error
    if not isinstance(payload, dict):
        raise TypeError("MOEX option calendar response must be a JSON object")
    block = _mapping(payload.get("options"), "options block")
    raw_columns = block.get("columns")
    raw_data = block.get("data")
    if not isinstance(raw_columns, list) or not isinstance(raw_data, list):
        raise TypeError("MOEX option calendar options block lacks columns/data")
    columns = tuple(str(value).strip().lower() for value in raw_columns)
    if len(columns) != len(set(columns)):
        raise ValueError("MOEX option calendar contains duplicate columns")
    if missing := REQUIRED_COLUMNS - set(columns):
        raise ValueError(f"MOEX option calendar lacks columns: {sorted(missing)}")
    if forbidden := set(columns) & FORBIDDEN_MARKET_COLUMNS:
        raise ValueError(
            f"MOEX option calendar unexpectedly contains market fields: {sorted(forbidden)}"
        )
    for row in raw_data:
        if not isinstance(row, list) or len(row) != len(columns):
            raise ValueError("MOEX option calendar row width disagrees with schema")
    frame = pd.DataFrame(raw_data, columns=columns)
    frame["asset_code"] = frame["asset_code"].astype("string").str.strip().str.upper()
    frame["series_name"] = frame["series_name"].astype("string").str.strip()
    frame["expiration_date"] = pd.to_datetime(frame["expiration_date"], errors="raise")
    if frame["asset_code"].eq("").any() or frame["series_name"].eq("").any():
        raise ValueError("MOEX option calendar identity is blank")
    core = frame.loc[frame["asset_code"].isin(CORE_ASSET_CODES)].copy()
    identifiers = tuple(column for column in IDENTIFIER_CANDIDATES if column in columns)
    keep = [
        column
        for column in (
            "asset_type_name",
            "asset_code",
            "series_name",
            "series_type",
            "exec_type",
            "margin_style",
            "expiration_date",
            "expiration_type",
            "expiration_time",
            "expiration_clr_sess",
            "weekend_session",
            *identifiers,
        )
        if column in core.columns
    ]
    core = core.loc[:, keep].sort_values(
        ["asset_code", "expiration_date", "series_name"],
        kind="mergesort",
        ignore_index=True,
    )
    return CalendarParse(
        frame=core,
        block_columns=columns,
        total_rows=len(frame),
        core_rows=len(core),
        identifier_columns=identifiers,
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


def build_probe(
    response_path: Path,
    config_path: Path = DEFAULT_CONFIG,
    output_directory: Path | None = None,
    *,
    retrieved_at_utc: str | None = None,
) -> Path:
    """Publish one immutable identifier-schema result from an exact local response."""
    protocol = load_protocol(config_path)
    path = response_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"MOEX option calendar response missing: {path}")
    content = path.read_bytes()
    parsed = parse_response(content)
    final = (output_directory or protocol.output_directory).resolve()
    if final.exists():
        raise FileExistsError(f"MOEX option calendar probe already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        raw_path = temporary / "official_response.json"
        atomic_write_bytes(raw_path, content)
        processed_path = temporary / "core_option_series_calendar.parquet"
        _atomic_parquet(processed_path, parsed.frame)
        retrieved_at = retrieved_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        mapping_available = "option_series_id" in parsed.identifier_columns
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-moex-option-series-calendar-probe-2021-09-01-v1",
            "provider": "MOEX ISS",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": protocol.config_sha256,
            },
            "request_url": protocol.request_url,
            "retrieved_at_utc": retrieved_at,
            "query_date": PROBE_DATE.date().isoformat(),
            "temporal_semantics": {
                "static_contract_metadata": True,
                "retrieved_current_vintage": True,
                "original_publication_vintage_proved": False,
                "market_prices_returns_targets_labels_or_pnl_used": False,
            },
            "schema_result": {
                "options_columns": list(parsed.block_columns),
                "numeric_identifier_columns": list(parsed.identifier_columns),
                "required_option_series_id_to_expiration_mapping_available": mapping_available,
                "combined_curve_archive_unlocks_without_additional_source": mapping_available,
            },
            "counts": {
                "options_rows": parsed.total_rows,
                "core_rows": parsed.core_rows,
                "core_series_names": int(parsed.frame["series_name"].nunique()),
            },
            "artifacts": {
                "raw_response": {
                    "path": raw_path.name,
                    "bytes": raw_path.stat().st_size,
                    "sha256": source_v1.sha256_file(raw_path),
                },
                "processed": {
                    "path": processed_path.name,
                    "bytes": processed_path.stat().st_size,
                    "sha256": source_v1.sha256_file(processed_path),
                    "rows": len(parsed.frame),
                    "columns": parsed.frame.columns.tolist(),
                },
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


def audit_existing_probe(
    output_directory: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Verify raw bytes and replay the processed metadata frame."""
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
    for name, artifact in manifest["artifacts"].items():
        path = root / artifact["path"]
        checks[f"{name}_bytes"] = path.is_file() and path.stat().st_size == artifact["bytes"]
        checks[f"{name}_sha256"] = path.is_file() and source_v1.sha256_file(path) == artifact[
            "sha256"
        ]
    replayed = parse_response((root / manifest["artifacts"]["raw_response"]["path"]).read_bytes())
    stored = pd.read_parquet(root / manifest["artifacts"]["processed"]["path"])
    try:
        pd.testing.assert_frame_equal(stored, replayed.frame, check_like=False)
        checks["processed_replay_exact"] = True
    except AssertionError:
        checks["processed_replay_exact"] = False
    if not all(checks.values()):
        raise ValueError(f"MOEX option calendar probe audit failed: {checks}")
    return {
        "source_id": manifest["source_id"],
        "manifest_sha256": source_v1.sha256_file(manifest_path),
        "checks": checks,
        "schema_result": manifest["schema_result"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--response-path", type=Path)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--audit-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.audit_only:
        result: object = audit_existing_probe(arguments.output_directory, arguments.config)
    else:
        if arguments.response_path is None:
            parser.error("--response-path is required for immutable local-cache acquisition")
        result = build_probe(
            arguments.response_path,
            arguments.config,
            arguments.output_directory,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
