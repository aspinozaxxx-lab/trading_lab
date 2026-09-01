"""Collect and replay-audit sealed MOEX core futures history for 2008-2011."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import requests
import yaml

from market_lab.futures import moex_pre2018_core4_source as parent
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_pre2012_core_source_v1.yaml"
SOURCE_ID: Final[str] = "official-moex-core3-plus-mix-daily-current-vintage-2008-2011-v1"
EXPECTED_COUNTS: Final[dict[str, int]] = {"BR": 38, "MIX": 1, "RI": 16, "SI": 26}
ASSET_CODES: Final[dict[str, str]] = {
    "BR": "BR",
    "MIX": "MIX",
    "RI": "RTS",
    "SI": "Si",
}
EXPECTED_TOTAL_CONTRACTS: Final[int] = 81
FORBIDDEN_OUTPUT_FRAGMENTS: Final[tuple[str, ...]] = (
    "return",
    "target",
    "label",
    "signal",
    "strategy",
    "equity",
    "pnl",
    "profit",
)


@dataclass(frozen=True, slots=True)
class Pre2012SourceProtocol:
    """Sealed wrapper around the reusable pre-2018 MOEX collector."""

    source: parent.SourceProtocol
    payload: dict[str, Any]
    dependency_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class SourceAudit:
    """Exact raw replay and artifact-integrity result."""

    checks: dict[str, bool]
    counts: dict[str, int]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"pre-2012 source {label} must be a mapping")
    return value


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    tokens = sidecar.read_text(encoding="utf-8-sig").split()
    if len(tokens) != 2 or tokens[1] != path.name:
        raise ValueError("invalid pre-2012 source SHA sidecar")
    return tokens[0].lower()


def _project_relative_path(value: str, required_root: str | None = None) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe pre-2012 source path: {value}")
    if required_root is not None and relative.parts[0].lower() != required_root.lower():
        raise ValueError(f"pre-2012 source path must start with {required_root}")
    return PROJECT_ROOT / relative


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> Pre2012SourceProtocol:
    """Verify config and implementation bytes without requesting daily market values."""
    path = config_path.resolve()
    config_sha = sha256_file(path)
    if _sidecar_sha(path) != config_sha:
        raise ValueError("pre-2012 source protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("pre-2012 source protocol must be a YAML object")
    dates = _mapping(payload.get("dates"), "dates")
    network = _mapping(payload.get("network"), "network")
    discovery = _mapping(payload.get("discovery"), "discovery")
    metadata = _mapping(payload.get("metadata_audit_record"), "metadata audit")
    daily = _mapping(payload.get("daily_history"), "daily history")
    output = _mapping(payload.get("output"), "output")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    start = date.fromisoformat(str(dates["source_start"]))
    end = date.fromisoformat(str(dates["source_end"]))
    protected = date.fromisoformat(str(dates["protected_from"]))
    if (
        payload.get("protocol_id") != "moex_pre2012_core_daily_source_v1"
        or payload.get("scope") != "source_only_no_strategy_no_outcomes"
        or payload.get("sealed_before_first_daily_price_response") is not True
        or payload.get("live_trading_allowed") is not False
        or start != date(2008, 1, 1)
        or end != date(2011, 12, 31)
        or protected != date(2026, 1, 1)
        or not start <= end < parent.PRE2018_CEILING < protected
        or int(discovery.get("expected_total_contracts", -1)) != EXPECTED_TOTAL_CONTRACTS
        or int(metadata.get("exact_contracts", -1)) != EXPECTED_TOTAL_CONTRACTS
        or int(metadata.get("FRSTTRADE_present", -1)) != EXPECTED_TOTAL_CONTRACTS
        or int(metadata.get("LSTDELDATE_present", -1)) != EXPECTED_TOTAL_CONTRACTS
        or int(metadata.get("LSTTRADE_present", -1)) != 0
        or int(metadata.get("LSTTRADE_missing", -1)) != EXPECTED_TOTAL_CONTRACTS
        or int(metadata.get("exact_one_overlapping_RFUD_segment", -1)) != EXPECTED_TOTAL_CONTRACTS
        or metadata.get("daily_price_endpoint_reached_before_seal") is not False
        or metadata.get("returns_targets_labels_equity_or_pnl_observed") is not False
        or list(discovery.get("columns", ())) != list(parent.SEARCH_COLUMNS)
        or list(daily.get("columns", ())) != list(parent.DAILY_COLUMNS)
        or daily.get("pagination") != "history_cursor_exact_total"
        or daily.get("primary_board") != "RFUD"
        or output.get("immutable_no_overwrite") is not True
        or output.get("outside_git_via_data_junction") is not True
    ):
        raise ValueError("pre-2012 source protocol invariants drifted")
    rules_payload = discovery.get("assets")
    if not isinstance(rules_payload, list):
        raise ValueError("pre-2012 source discovery rules missing")
    rules = tuple(
        parent._parse_asset_rule(item) for item in rules_payload if isinstance(item, Mapping)
    )
    if (
        len(rules) != 4
        or tuple(rule.logical_symbol for rule in rules) != ("BR", "MIX", "RI", "SI")
        or {rule.logical_symbol: rule.expected_contract_count for rule in rules} != EXPECTED_COUNTS
        or {rule.logical_symbol: rule.asset_code for rule in rules} != ASSET_CODES
    ):
        raise ValueError("pre-2012 source exact asset rules drifted")
    expected_dependencies = {
        "src/market_lab/futures/moex_pre2012_core_source.py",
        "src/market_lab/futures/moex_pre2018_core4_source.py",
    }
    if set(map(str, dependencies)) != expected_dependencies:
        raise ValueError("pre-2012 source dependency set drifted")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = _project_relative_path(str(relative))
        digest = str(expected).lower()
        if sha256_file(dependency_path) != digest:
            raise ValueError(f"pre-2012 source dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    output_path = _project_relative_path(str(output["default_relative_directory"]), "data")
    source = parent.SourceProtocol(
        config_path=path,
        config_sha256=config_sha,
        implementation_sha256=dependency_hashes[
            "src/market_lab/futures/moex_pre2012_core_source.py"
        ],
        source_start=start,
        source_end=end,
        protected_from=protected,
        primary_board=str(daily["primary_board"]),
        search_page_size=int(discovery["page_size"]),
        maximum_search_pages=int(discovery["maximum_pages_per_query"]),
        maximum_history_pages_per_segment=int(daily["maximum_pages_per_segment"]),
        timeout_seconds=float(network["timeout_seconds"]),
        attempts=int(network["attempts"]),
        retry_backoff_seconds=float(network["retry_backoff_seconds"]),
        request_interval_seconds=float(network["minimum_request_interval_seconds"]),
        output_relative=output_path.relative_to(PROJECT_ROOT).as_posix(),
        rules=rules,
    )
    return Pre2012SourceProtocol(
        source=source,
        payload=payload,
        dependency_hashes=dependency_hashes,
    )


def _forbidden_columns(frame: pd.DataFrame) -> list[str]:
    return [
        str(column)
        for column in frame.columns
        if any(fragment in str(column).lower() for fragment in FORBIDDEN_OUTPUT_FRAGMENTS)
    ]


def _source_checks(
    protocol: Pre2012SourceProtocol,
    collection: parent.SourceCollection,
) -> dict[str, bool]:
    contracts = collection.contracts
    daily = collection.daily
    return {
        "exact_contract_count_81": len(contracts) == EXPECTED_TOTAL_CONTRACTS,
        "exact_segment_count_81": len(collection.segments) == EXPECTED_TOTAL_CONTRACTS,
        "exact_asset_contract_counts": contracts.groupby("logical_symbol").size().to_dict()
        == EXPECTED_COUNTS,
        "all_last_trade_dates_preserved_missing": bool(contracts["last_trade_date"].isna().all()),
        "daily_nonempty": not daily.empty,
        "daily_minimum_in_range": bool(
            daily["trade_date"].dt.date.ge(protocol.source.source_start).all()
        ),
        "daily_maximum_in_range": bool(
            daily["trade_date"].dt.date.le(protocol.source.source_end).all()
        ),
        "protected_rows_absent": bool(
            daily["trade_date"].dt.date.lt(protocol.source.protected_from).all()
        ),
        "daily_identity_unique": not daily.duplicated(
            ["trade_date", "canonical_contract_id", "board_id"]
        ).any(),
        "coverage_every_contract": set(collection.coverage["canonical_contract_id"])
        == set(contracts["canonical_contract_id"]),
        "all_source_tables_outcome_free": all(
            not _forbidden_columns(frame)
            for frame in (
                collection.discovery,
                contracts,
                collection.boards,
                collection.segments,
                daily,
                collection.coverage,
            )
        ),
    }


def _artifact(path: Path, frame: pd.DataFrame) -> dict[str, object]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "rows": len(frame),
        "columns": frame.columns.tolist(),
    }


def persist_source(
    protocol: Pre2012SourceProtocol,
    collection: parent.SourceCollection,
    output_directory: Path | None = None,
) -> Path:
    """Atomically publish one immutable outcome-free source bundle outside Git."""
    checks = _source_checks(protocol, collection)
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(f"pre-2012 source checks failed: {failed}")
    final = (output_directory or (PROJECT_ROOT / protocol.source.output_relative)).resolve()
    if final.exists():
        raise FileExistsError(f"pre-2012 source output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        tables = {
            "discovery": collection.discovery,
            "contracts": collection.contracts,
            "boards": collection.boards,
            "segments": collection.segments,
            "daily": collection.daily,
            "coverage": collection.coverage,
        }
        artifacts: dict[str, object] = {}
        for name, frame in tables.items():
            path = temporary / f"{name}.parquet"
            parent._atomic_parquet(path, frame)
            artifacts[name] = _artifact(path, frame)
        raw_content = (
            b"\n".join(parent._canonical_json(record) for record in collection.requests) + b"\n"
        )
        raw_path = temporary / "official_moex_iss_responses.jsonl.gz"
        atomic_write_bytes(raw_path, gzip.compress(raw_content, compresslevel=6, mtime=0))
        artifacts["raw_archive"] = {
            "path": raw_path.name,
            "bytes": raw_path.stat().st_size,
            "sha256": sha256_file(raw_path),
            "requests": len(collection.requests),
        }
        retrieved = [str(item["retrieved_at_utc"]) for item in collection.requests]
        counts_by_asset = {
            logical: {
                "contracts": int(
                    collection.contracts["logical_symbol"].astype(str).eq(logical).sum()
                ),
                "daily_rows": int(
                    collection.daily["asset_code"].astype(str).eq(ASSET_CODES[logical]).sum()
                ),
            }
            for logical in EXPECTED_COUNTS
        }
        manifest_core = {
            "schema_version": 1,
            "source_id": SOURCE_ID,
            "provider": "MOEX ISS",
            "protocol": {
                "path": protocol.source.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "bytes": protocol.source.config_path.stat().st_size,
                "sha256": protocol.source.config_sha256,
                "implementation_sha256": protocol.dependency_hashes,
            },
            "request_count": len(collection.requests),
            "retrieval": {
                "minimum_retrieved_at_utc": min(retrieved),
                "maximum_retrieved_at_utc": max(retrieved),
            },
            "request_bounds": {
                "from": protocol.source.source_start.isoformat(),
                "till": protocol.source.source_end.isoformat(),
                "protected_from": protocol.source.protected_from.isoformat(),
                "all_daily_requests_end_before_2012": True,
            },
            "counts": {
                "contracts": len(collection.contracts),
                "board_segments": len(collection.segments),
                "daily_rows": len(collection.daily),
                "requests": len(collection.requests),
                "by_asset": counts_by_asset,
            },
            "source_checks": checks,
            "temporal_semantics": {
                "contains_prices": True,
                "contains_returns_targets_labels_signals_equity_or_pnl": False,
                "daily_observation_time": "completed official MOEX trading date",
                "signal_use_not_before": "after completed source trade_date",
                "execution_not_before": "next factual open under separate sealed protocol",
                "current_vintage_snapshot": True,
                "no_missing_value_zero_imputation": True,
                "no_gap_or_roll_return_bridge": True,
            },
            "access_observation": {
                "anonymous_http_observed": True,
                "raw_redistribution_allowed": False,
                "research_use_only": True,
            },
            "limitations": protocol.payload["limitations"],
            "artifacts": artifacts,
        }
        manifest_identity = hashlib.sha256(parent._canonical_json(manifest_core)).hexdigest()
        manifest_path = temporary / "manifest.json"
        write_json(
            manifest_path,
            {**manifest_core, "manifest_payload_sha256": manifest_identity},
        )
        atomic_write_text(
            temporary / "manifest.sha256",
            f"{sha256_file(manifest_path)}  manifest.json\n",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


class _ReplayResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _ReplaySession:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records
        self.index = 0
        self.last_retrieved_at = datetime(1970, 1, 1, tzinfo=UTC)

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> _ReplayResponse:
        del headers, timeout
        if self.index >= len(self.records):
            raise AssertionError(f"unexpected replay request: {url}")
        record = self.records[self.index]
        if record["request_url"] != url:
            raise AssertionError(
                f"raw replay URL mismatch at {self.index + 1}: {record['request_url']} != {url}"
            )
        self.index += 1
        self.last_retrieved_at = datetime.fromisoformat(
            str(record["retrieved_at_utc"]).replace("Z", "+00:00")
        )
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("raw replay payload is not an object")
        return _ReplayResponse(payload)

    def clock(self) -> datetime:
        return self.last_retrieved_at


def _read_raw_records(path: Path) -> list[dict[str, Any]]:
    decoded = gzip.decompress(path.read_bytes())
    records = [json.loads(line) for line in decoded.splitlines() if line]
    if not records or any(not isinstance(record, dict) for record in records):
        raise ValueError("pre-2012 raw archive is empty or malformed")
    return records


def _normalized_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in normalized.columns:
        if pd.api.types.is_object_dtype(normalized[column].dtype) or isinstance(
            normalized[column].dtype, pd.StringDtype
        ):
            normalized[column] = normalized[column].astype("string")
    return normalized.convert_dtypes()


def audit_bundle(protocol: Pre2012SourceProtocol) -> SourceAudit:
    """Rebuild every table from exact archived responses and compare artifacts."""
    root = (PROJECT_ROOT / protocol.source.output_relative).resolve()
    manifest_path = root / "manifest.json"
    sidecar_path = root / "manifest.sha256"
    if not manifest_path.is_file() or not sidecar_path.is_file():
        raise FileNotFoundError(f"pre-2012 source bundle is incomplete: {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    raw_meta = manifest.get("artifacts", {}).get("raw_archive", {})
    raw_path = root / str(raw_meta.get("path", ""))
    records = _read_raw_records(raw_path)
    replay_session = _ReplaySession(records)
    replay_protocol = replace(
        protocol.source,
        attempts=1,
        retry_backoff_seconds=0.0,
        request_interval_seconds=0.0,
    )
    replay = parent.collect_source(
        replay_protocol,
        replay_session,
        clock=replay_session.clock,
    )
    checks: dict[str, bool] = {
        "manifest_sha_exact": sidecar_path.read_text(encoding="utf-8-sig").split()[0]
        == sha256_file(manifest_path),
        "source_id_exact": manifest.get("source_id") == SOURCE_ID,
        "protocol_sha_exact": manifest.get("protocol", {}).get("sha256")
        == protocol.source.config_sha256,
        "implementation_sha_exact": manifest.get("protocol", {}).get("implementation_sha256")
        == protocol.dependency_hashes,
        "raw_archive_sha_exact": sha256_file(raw_path) == raw_meta.get("sha256"),
        "raw_request_count_exact": len(records) == int(raw_meta.get("requests", -1)),
        "raw_replay_consumed_all": replay_session.index == len(records),
        "raw_request_records_exact": tuple(records) == replay.requests,
        "source_checks_exact": manifest.get("source_checks") == _source_checks(protocol, replay),
    }
    replay_tables = {
        "discovery": replay.discovery,
        "contracts": replay.contracts,
        "boards": replay.boards,
        "segments": replay.segments,
        "daily": replay.daily,
        "coverage": replay.coverage,
    }
    for name, expected in replay_tables.items():
        metadata = manifest["artifacts"][name]
        path = root / str(metadata["path"])
        checks[f"{name}_bytes"] = path.stat().st_size == int(metadata["bytes"])
        checks[f"{name}_sha256"] = sha256_file(path) == metadata["sha256"]
        stored = pd.read_parquet(path)
        checks[f"{name}_rows"] = len(stored) == int(metadata["rows"])
        checks[f"{name}_columns"] = stored.columns.tolist() == metadata["columns"]
        try:
            pd.testing.assert_frame_equal(
                _normalized_frame(stored),
                _normalized_frame(expected),
                check_dtype=False,
            )
        except AssertionError:
            checks[f"{name}_replay_exact"] = False
        else:
            checks[f"{name}_replay_exact"] = True
    return SourceAudit(
        checks=checks,
        counts={
            "contracts": len(replay.contracts),
            "daily_rows": len(replay.daily),
            "requests": len(records),
        },
    )


def download_source(
    protocol: Pre2012SourceProtocol,
    *,
    session: parent.SessionLike | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Collect after seal, publish atomically, then require an exact raw replay."""
    owned_session = session is None
    active_session: parent.SessionLike = session or requests.Session()
    try:
        collection = parent.collect_source(
            protocol.source,
            active_session,
            clock=clock,
            progress=progress,
        )
        output = persist_source(protocol, collection)
    finally:
        if owned_session and isinstance(active_session, requests.Session):
            active_session.close()
    audit = audit_bundle(protocol)
    if not all(audit.checks.values()):
        failed = sorted(name for name, passed in audit.checks.items() if not passed)
        raise ValueError(f"pre-2012 source audit failed: {failed}")
    return output


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
    output = download_source(protocol, progress=lambda value: print(value, flush=True))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
