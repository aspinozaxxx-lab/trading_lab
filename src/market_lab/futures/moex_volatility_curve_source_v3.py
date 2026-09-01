"""Final pilot correction preserving finite post-expiry MOEX curve events."""

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab.futures import moex_volatility_curve_source as v1
from market_lab.futures import moex_volatility_curve_source_v2 as v2
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = v1.PROJECT_ROOT
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_volatility_curve_source_v3.yaml"
PARENT_V2_CONFIG_SHA256: Final[str] = (
    "90204aab3d06bc7fbf444157a7b5a8cac011fb14af48a665bf5639569dda6005"
)
PARENT_V2_MODULE_SHA256: Final[str] = (
    "8eeb28525c5a951a7791df2ab6f61e0294c5019ec9fdcd91183c86e93da042fc"
)
EXPECTED_ARCHIVE_ROWS: Final[int] = 304_132
EXPECTED_CORE_ROWS: Final[int] = 76_999
EXPECTED_ROOT_ROWS: Final[dict[str, int]] = {
    "RTS": 22_851,
    "MIX": 15_998,
    "SI": 22_840,
    "BR": 15_310,
}
EXPECTED_NONPOSITIVE_T: Final[int] = 1_520
EXPECTED_NEGATIVE_T: Final[int] = 1_520


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"MOEX volatility curve V3 {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"MOEX volatility curve V3 sidecar is missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> v1.VolatilityCurveProtocol:
    """Verify the final source-only correction and both immutable parents."""
    path = config_path.resolve()
    config_sha = v1.sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("MOEX volatility curve V3 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise TypeError("MOEX volatility curve V3 protocol must be a YAML object")
    parent = _mapping(payload.get("parent_v2"), "parent")
    source = _mapping(payload.get("source"), "source")
    correction = _mapping(payload.get("only_changed_behavior"), "correction")
    expected = _mapping(payload.get("sealed_source_only_counts"), "counts")
    output = _mapping(payload.get("output"), "output")
    expected_root_rows = {str(key): int(value) for key, value in expected["root_rows"].items()}
    if (
        payload.get("protocol_id") != "moex_volatility_curve_source_v3"
        or payload.get("status") != "sealed_T_sign_semantics_before_canonical_build"
        or payload.get("scope") != "source_only_no_strategy_no_returns_no_pnl"
        or payload.get("research_only") is not True
        or payload.get("live_trading_allowed") is not False
        or parent.get("config_sha256") != PARENT_V2_CONFIG_SHA256
        or parent.get("module_sha256") != PARENT_V2_MODULE_SHA256
        or source.get("archive_sha256")
        != "40b79e536033bdc32a5f768300084c18be7e3f546e2aa1020660589f7359561f"
        or int(source["expected_archive_bytes"]) != 9_920_473
        or correction.get("old_invalid_rule") != "years_to_expiry_strictly_positive"
        or correction.get("new_source_rule") != "preserve_every_finite_years_to_expiry"
        or correction.get("nonpositive_consumer_policy")
        != "mask_from_curve_reconstruction_or_strategy_features"
        or correction.get("selection_timestamp_or_numeric_value_change") is not False
        or int(expected["archive_rows"]) != EXPECTED_ARCHIVE_ROWS
        or int(expected["core_rows"]) != EXPECTED_CORE_ROWS
        or expected_root_rows != EXPECTED_ROOT_ROWS
        or int(expected["nonpositive_T_rows"]) != EXPECTED_NONPOSITIVE_T
        or int(expected["negative_T_rows"]) != EXPECTED_NEGATIVE_T
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
    ):
        raise ValueError("MOEX volatility curve V3 invariants drifted")
    parent_config = PROJECT_ROOT / str(parent["config_path"])
    parent_module = PROJECT_ROOT / str(parent["module_path"])
    if (
        v1.sha256_file(parent_config) != PARENT_V2_CONFIG_SHA256
        or v1.sha256_file(parent_module) != PARENT_V2_MODULE_SHA256
    ):
        raise ValueError("MOEX volatility curve V2 parent identity drifted")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    for relative, digest in dependencies.items():
        if v1.sha256_file(PROJECT_ROOT / str(relative)) != str(digest).lower():
            raise ValueError(f"MOEX volatility curve V3 dependency drift: {relative}")
    return v1.VolatilityCurveProtocol(
        config_path=path,
        config_sha256=config_sha,
        payload=payload,
        source_start=pd.Timestamp("2021-01-01"),
        source_end=pd.Timestamp("2021-01-31"),
        download_url=str(source["download_url"]),
        expected_archive_bytes=int(source["expected_archive_bytes"]),
        archive_member_name=str(source["archive_member_name"]),
        output_directory=(PROJECT_ROOT / str(output["directory"])).resolve(),
    )


def parse_archive_bytes(
    content: bytes,
    protocol: v1.VolatilityCurveProtocol,
) -> v1.CurveArchiveParse:
    """Replay V2 exactly while preserving finite T<=0 rows with an explicit mask."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        member = v1._safe_member(archive, protocol.archive_member_name)
        raw_csv = archive.read(member)
    lines = v1._decode_csv(raw_csv).splitlines()
    header_index, delimiter, columns = v2._locate_header(lines)
    if missing := set(v1.REQUIRED_COLUMNS) - set(columns):
        raise ValueError(f"MOEX volatility curve V3 lacks columns: {sorted(missing)}")
    indices = {column: columns.index(column) for column in v1.REQUIRED_COLUMNS}
    selected_rows: list[list[str]] = []
    roots: list[str] = []
    assets: list[str] = []
    total_rows = 0
    ignored_rows = 0
    reader = csv.reader(lines[header_index + 1 :], delimiter=delimiter)
    for row in reader:
        if not row or not any(cell.strip() for cell in row):
            continue
        while len(row) > len(columns) and not row[-1].strip():
            row.pop()
        if len(row) != len(columns):
            raise ValueError(
                f"malformed MOEX volatility curve V3 row {total_rows + 1}: "
                f"{len(row)} != {len(columns)}"
            )
        total_rows += 1
        identity = v1._asset_from_full_name(row[indices["#NAME"]])
        if identity is None:
            ignored_rows += 1
            continue
        root, asset = identity
        selected_rows.append([row[columns.index(column)] for column in v1.REQUIRED_COLUMNS])
        roots.append(root)
        assets.append(asset)
    if total_rows == 0 or not selected_rows:
        raise ValueError("MOEX volatility curve V3 archive/core rows are empty")
    frame = pd.DataFrame(
        selected_rows,
        columns=[column.lower() for column in v1.REQUIRED_COLUMNS],
    )
    frame = frame.rename(
        columns={"#name": "full_name", "time": "source_time", "t": "years_to_expiry"}
    )
    frame["full_name"] = frame["full_name"].astype(str).str.strip()
    frame["small_name"] = frame["small_name"].astype(str).str.strip()
    if frame["full_name"].eq("").any() or frame["small_name"].eq("").any():
        raise ValueError("MOEX volatility curve V3 instrument identity is blank")
    frame["event_at"] = v1._event_time(frame.pop("source_time"))
    event_dates = frame["event_at"].dt.tz_localize(None).dt.normalize()
    if event_dates.lt(protocol.source_start).any() or event_dates.gt(protocol.source_end).any():
        raise ValueError("MOEX volatility curve V3 event escaped the pilot interval")
    if event_dates.ge(v1.PROTECTED_FROM).any():
        raise ValueError("MOEX volatility curve V3 contains a protected event")
    for column in v1.NUMERIC_COLUMNS:
        target = "years_to_expiry" if column == "t" else column
        frame[target] = v1._numeric(frame[target], target)
    frame["expired_or_at_expiry"] = frame["years_to_expiry"].le(0.0)
    frame["curve_feature_eligible"] = ~frame["expired_or_at_expiry"]
    frame["source_root"] = roots
    frame["asset"] = assets
    frame["available_at"] = frame["event_at"] + pd.Timedelta(minutes=1)
    frame["availability_rule"] = "event_at_plus_one_minute_not_after_decision_at"
    frame["historical_event_log"] = True
    frame["archive_publication_was_later"] = True
    frame["provider"] = "MOEX"
    if frame.duplicated(["event_at", "full_name", "small_name"]).any():
        raise ValueError("duplicate MOEX volatility curve V3 event/instrument row")
    frame = frame.sort_values(
        ["event_at", "asset", "full_name", "small_name"],
        kind="mergesort",
        ignore_index=True,
    )
    if set(frame.columns.str.lower()) & v1.FORBIDDEN_DERIVED_COLUMNS:
        raise ValueError("MOEX volatility curve V3 contains a derived outcome column")
    counts = {root: int(frame["source_root"].eq(root).sum()) for root in v1.ROOT_TO_ASSET}
    return v1.CurveArchiveParse(
        frame=frame,
        total_archive_rows=total_rows,
        ignored_non_core_rows=ignored_rows,
        root_counts=counts,
        member_name=member.filename,
        member_bytes=member.file_size,
    )


def _checks(
    parsed: v1.CurveArchiveParse,
    protocol: v1.VolatilityCurveProtocol,
    content: bytes,
) -> dict[str, bool]:
    checks = v1._checks(parsed, protocol, content)
    frame = parsed.frame
    checks.update(
        {
            "exact_archive_rows": parsed.total_archive_rows == EXPECTED_ARCHIVE_ROWS,
            "exact_core_rows": len(frame) == EXPECTED_CORE_ROWS,
            "exact_root_rows": parsed.root_counts == EXPECTED_ROOT_ROWS,
            "exact_nonpositive_T_rows": int(frame["years_to_expiry"].le(0.0).sum())
            == EXPECTED_NONPOSITIVE_T,
            "exact_negative_T_rows": int(frame["years_to_expiry"].lt(0.0).sum())
            == EXPECTED_NEGATIVE_T,
            "expiry_masks_exact_complements": bool(
                frame["expired_or_at_expiry"].eq(~frame["curve_feature_eligible"]).all()
            ),
            "nonpositive_T_never_feature_eligible": not bool(
                frame.loc[frame["years_to_expiry"].le(0.0), "curve_feature_eligible"].any()
            ),
            "data_value_transform_absent": True,
        }
    )
    return checks


def write_source_from_bytes(
    content: bytes,
    protocol: v1.VolatilityCurveProtocol,
    output_directory: Path | None = None,
    *,
    fetched_at_utc: str | None = None,
    acquisition_transport: str = "windows_system_tls_local_cache",
) -> Path:
    """Create immutable V3 output while preserving the exact official archive."""
    final = (output_directory or protocol.output_directory).resolve()
    if final.exists():
        raise FileExistsError(f"MOEX volatility curve V3 output already exists: {final}")
    if len(content) != protocol.expected_archive_bytes:
        raise ValueError("MOEX volatility curve V3 bytes do not match the protocol")
    if hashlib.sha256(content).hexdigest() != protocol.payload["source"]["archive_sha256"]:
        raise ValueError("MOEX volatility curve V3 archive SHA-256 mismatch")
    if acquisition_transport not in {"windows_system_tls_local_cache", "synthetic_test"}:
        raise ValueError("unsupported MOEX volatility curve V3 acquisition transport")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        parsed = parse_archive_bytes(content, protocol)
        checks = _checks(parsed, protocol, content)
        if not all(checks.values()):
            raise ValueError(f"MOEX volatility curve V3 source audit failed: {checks}")
        raw_path = temporary / "official_moex_volatility_curve_202101.zip"
        atomic_write_bytes(raw_path, content)
        processed_path = temporary / "volatility_curve_core4.parquet"
        v1._atomic_parquet(processed_path, parsed.frame)
        counts = {
            "archive_rows": parsed.total_archive_rows,
            "ignored_non_core_rows": parsed.ignored_non_core_rows,
            "core_rows": len(parsed.frame),
            "root_rows": parsed.root_counts,
            "event_dates": int(parsed.frame["event_at"].dt.date.nunique()),
            "full_names": int(parsed.frame["full_name"].nunique()),
            "events": int(parsed.frame["event_at"].nunique()),
            "negative_T_rows": int(parsed.frame["years_to_expiry"].lt(0.0).sum()),
            "nonpositive_T_rows": int(parsed.frame["years_to_expiry"].le(0.0).sum()),
            "curve_feature_eligible_rows": int(parsed.frame["curve_feature_eligible"].sum()),
        }
        audit_path = temporary / "source_audit.json"
        write_json(audit_path, {"schema_version": 3, "checks": checks, "counts": counts})
        fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest_core = {
            "schema_version": 3,
            "source_id": "official-moex-volatility-curve-core4-pilot-2021-01-v3",
            "provider": "MOEX",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": protocol.config_sha256,
            },
            "parent_v2": {
                "config_sha256": PARENT_V2_CONFIG_SHA256,
                "module_sha256": PARENT_V2_MODULE_SHA256,
                "output_published": False,
            },
            "fetched_at_utc": fetched_at,
            "official_endpoint": protocol.download_url,
            "acquisition": {
                "transport": acquisition_transport,
                "raw_archive_sha256": hashlib.sha256(content).hexdigest(),
                "raw_archive_bytes": len(content),
            },
            "request_bounds": {
                "pilot_start": protocol.source_start.date().isoformat(),
                "pilot_end": protocol.source_end.date().isoformat(),
                "protected_from": v1.PROTECTED_FROM.date().isoformat(),
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
            "source_semantics_correction": {
                "finite_T_preserved_for_audit": True,
                "nonpositive_T_curve_feature_eligible": False,
                "source_rows_filtered_by_T": False,
                "data_value_transform": "none",
            },
            "selection": {
                "roots": list(v1.ROOT_TO_ASSET),
                "assets": list(v1.ROOT_TO_ASSET.values()),
                "price_or_outcome_filter_used": False,
                "series_or_maturity_filter_used": False,
            },
            "counts": counts,
            "artifacts": {
                "raw_archive": {
                    "path": raw_path.name,
                    "bytes": raw_path.stat().st_size,
                    "sha256": v1.sha256_file(raw_path),
                },
                "processed": {
                    "path": processed_path.name,
                    "bytes": processed_path.stat().st_size,
                    "sha256": v1.sha256_file(processed_path),
                    "rows": len(parsed.frame),
                    "columns": parsed.frame.columns.tolist(),
                    "minimum_event_at": parsed.frame["event_at"].min().isoformat(),
                    "maximum_event_at": parsed.frame["event_at"].max().isoformat(),
                },
                "audit": {
                    "path": audit_path.name,
                    "bytes": audit_path.stat().st_size,
                    "sha256": v1.sha256_file(audit_path),
                },
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
        manifest_sha = v1.sha256_file(manifest_path)
        atomic_write_text(temporary / "manifest.sha256", f"{manifest_sha}  manifest.json\n")
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def collect_source(
    archive_path: Path,
    config_path: Path = DEFAULT_CONFIG,
    output_directory: Path | None = None,
    *,
    fetched_at_utc: str | None = None,
) -> Path:
    """Build the final pilot from the exact system-TLS cache."""
    protocol = load_protocol(config_path)
    path = archive_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"MOEX volatility curve V3 archive is missing: {path}")
    return write_source_from_bytes(
        path.read_bytes(),
        protocol,
        output_directory,
        fetched_at_utc=fetched_at_utc,
    )


def audit_existing_source(
    output_directory: Path | None = None,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, object]:
    """Replay exact raw bytes and verify every V3 artifact without mutation."""
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
        == v1.sha256_file(manifest_path),
        "protocol_identity": manifest["protocol"]["sha256"] == protocol.config_sha256,
    }
    for name, artifact in manifest["artifacts"].items():
        path = root / artifact["path"]
        checks[f"{name}_exists"] = path.is_file()
        checks[f"{name}_bytes"] = path.is_file() and path.stat().st_size == artifact["bytes"]
        checks[f"{name}_sha256"] = path.is_file() and v1.sha256_file(path) == artifact["sha256"]
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
    checks["protected_events_zero"] = bool(event_dates.lt(v1.PROTECTED_FROM).all())
    if not all(checks.values()):
        raise ValueError(f"MOEX volatility curve V3 audit failed: {checks}")
    return {
        "source_id": manifest["source_id"],
        "checks": checks,
        "counts": manifest["counts"],
        "manifest_sha256": v1.sha256_file(manifest_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--archive-path", type=Path)
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
        if arguments.archive_path is None:
            parser.error("--archive-path is required for the system-TLS V3 build")
        print(
            collect_source(
                arguments.archive_path,
                arguments.config,
                arguments.output_directory,
            )
        )


if __name__ == "__main__":
    main()
