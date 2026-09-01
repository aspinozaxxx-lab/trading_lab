"""Preserve official inert daily placeholders in the sealed 2008-2011 source."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import requests
import yaml

from market_lab.futures import moex_pre2012_core_source as v1
from market_lab.futures import moex_pre2018_core4_source as parent
from market_lab.futures.market_data import (
    DAILY_NONNEGATIVE_COLUMNS,
    IssPageCursor,
    parse_iss_page_cursor,
)
from market_lab.futures.market_data import (
    parse_futures_daily_payload as base_parse_daily,
)
from market_lab.futures.specs import FuturesAssetSpec
from market_lab.io_utils import atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_pre2012_core_source_v2.yaml"
SOURCE_ID: Final[str] = (
    "official-moex-core3-plus-mix-daily-current-vintage-2008-2011-v2"
)
V1_CONFIG_RELATIVE: Final[str] = "configs/moex_pre2012_core_source_v1.yaml"
V1_CONFIG_SHA256: Final[str] = (
    "92c7f3249e4bd0363a65af78fccd3871929ea04e2ec7d187c8b6522a8fc71997"
)
V1_MODULE_SHA256: Final[str] = (
    "55965d9cb068a23c4d9310c91e03e95e7f65dedeec4ec06d247d3958613dfb4e"
)
PARENT_MODULE_SHA256: Final[str] = (
    "7dd25e01d28303988190123fc57c70fd3d93d938c207d219a03e837484833fc7"
)
KNOWN_INERT_SECID: Final[str] = "RIM9_2009"
KNOWN_INERT_DATE: Final[pd.Timestamp] = pd.Timestamp("2008-09-12")
PRICE_FIELDS: Final[tuple[str, ...]] = (
    "open",
    "low",
    "high",
    "close",
    "settleprice",
    "waprice",
)
ACTIVITY_FIELDS: Final[tuple[str, ...]] = ("value", "volume", "numtrades")
NUMERIC_FIELDS: Final[tuple[str, ...]] = (
    "open",
    "high",
    "low",
    "close",
    "settleprice",
    "waprice",
    "volume",
    "value",
    "numtrades",
    "openposition",
    "openpositionvalue",
)
NORMALIZED_DAILY_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "board_id",
    "secid",
    "asset_code",
    "open",
    "high",
    "low",
    "close",
    "settle",
    "waprice",
    "volume",
    "value",
    "num_trades",
    "open_interest",
    "open_interest_value",
    "reported_trade_activity",
    "ohlc_complete",
    "ohlc_missing_with_activity",
    "has_trade",
    "has_settlement",
)


@dataclass(frozen=True, slots=True)
class V2SourceProtocol:
    """Validated parser-only successor of the byte-sealed V1 source protocol."""

    source: parent.SourceProtocol
    payload: dict[str, Any]
    dependency_hashes: dict[str, str]


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"pre-2012 V2 {label} must be a mapping")
    return value


def load_protocol(config_path: Path = DEFAULT_CONFIG) -> V2SourceProtocol:
    """Verify the V2 correction and every transitive dependency before collection."""
    path = config_path.resolve()
    config_sha = v1.sha256_file(path)
    if v1._sidecar_sha(path) != config_sha:
        raise ValueError("pre-2012 V2 protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("pre-2012 V2 protocol must be a YAML object")
    parent_identity = _mapping(payload.get("parent_protocol"), "parent protocol")
    correction = _mapping(payload.get("parser_correction"), "parser correction")
    observed = _mapping(payload.get("observed_v1_failure"), "V1 failure")
    output = _mapping(payload.get("output"), "output")
    dependencies = _mapping(payload.get("implementation_dependencies"), "dependencies")
    if (
        payload.get("protocol_id") != "moex_pre2012_core_daily_source_v2"
        or payload.get("scope") != "source_only_no_strategy_no_outcomes"
        or payload.get("post_daily_access_parser_only_correction") is not True
        or payload.get("live_trading_allowed") is not False
        or str(parent_identity.get("path")) != V1_CONFIG_RELATIVE
        or str(parent_identity.get("sha256")).lower() != V1_CONFIG_SHA256
        or correction.get("universe_dates_endpoints_unchanged") is not True
        or correction.get("raw_payload_preserved_exactly") is not True
        or correction.get("inert_row_policy")
        != "preserve_identity_and_missing_values_with_all_market_flags_false"
        or correction.get("inert_row_is_zero_return") is not False
        or correction.get("inert_row_is_executable") is not False
        or observed.get("secid") != KNOWN_INERT_SECID
        or date.fromisoformat(str(observed.get("trade_date")))
        != KNOWN_INERT_DATE.date()
        or observed.get("market_values_printed") is not False
        or output.get("immutable_no_overwrite") is not True
        or output.get("outside_git_via_data_junction") is not True
    ):
        raise ValueError("pre-2012 V2 protocol invariants drifted")
    v1_path = v1._project_relative_path(str(parent_identity["path"]), "configs")
    if v1.sha256_file(v1_path) != V1_CONFIG_SHA256:
        raise ValueError("pre-2012 V1 parent bytes drifted")
    v1_protocol = v1.load_protocol(v1_path)
    expected_dependencies = {
        "src/market_lab/futures/moex_pre2012_core_source_v2.py",
        "src/market_lab/futures/moex_pre2012_core_source.py",
        "src/market_lab/futures/moex_pre2018_core4_source.py",
    }
    if set(map(str, dependencies)) != expected_dependencies:
        raise ValueError("pre-2012 V2 dependency set drifted")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = v1._project_relative_path(str(relative))
        digest = str(expected).lower()
        if v1.sha256_file(dependency_path) != digest:
            raise ValueError(f"pre-2012 V2 dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    if (
        dependency_hashes["src/market_lab/futures/moex_pre2012_core_source.py"]
        != V1_MODULE_SHA256
        or dependency_hashes["src/market_lab/futures/moex_pre2018_core4_source.py"]
        != PARENT_MODULE_SHA256
    ):
        raise ValueError("pre-2012 V2 pinned parent identity drifted")
    output_path = v1._project_relative_path(
        str(output["default_relative_directory"]), "data"
    )
    source = replace(
        v1_protocol.source,
        config_path=path,
        config_sha256=config_sha,
        implementation_sha256=dependency_hashes[
            "src/market_lab/futures/moex_pre2012_core_source_v2.py"
        ],
        output_relative=output_path.relative_to(PROJECT_ROOT).as_posix(),
    )
    return V2SourceProtocol(
        source=source,
        payload=payload,
        dependency_hashes=dependency_hashes,
    )


def _zero_or_null(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    return series.isna() | (numeric.notna() & numeric.eq(0.0))


def _inert_mask(raw: pd.DataFrame) -> pd.Series:
    """Select only exact null-price and null/zero-activity source placeholders."""
    price_null = raw[list(PRICE_FIELDS)].isna().all(axis=1)
    activity_empty = pd.concat(
        [_zero_or_null(raw[column]).rename(column) for column in ACTIVITY_FIELDS],
        axis=1,
    ).all(axis=1)
    return price_null & activity_empty


def _normalize_inert_rows(
    raw: pd.DataFrame,
    asset: FuturesAssetSpec,
    expected_secid: str | None,
) -> pd.DataFrame:
    frame = raw.copy()
    frame["trade_date"] = pd.to_datetime(frame["tradedate"], errors="raise").dt.normalize()
    if frame["trade_date"].isna().any():
        raise ValueError("inert daily row has missing trade date")
    frame["board_id"] = frame["boardid"].astype("string")
    frame["secid"] = frame["secid"].astype("string")
    frame["asset_code"] = frame["assetcode"].astype("string").fillna(asset.asset_code)
    if not frame["asset_code"].eq(asset.asset_code).all():
        raise ValueError("inert daily row contains another asset code")
    if expected_secid is not None and not frame["secid"].eq(expected_secid).all():
        raise ValueError("inert daily row contains another SECID")
    for column in NUMERIC_FIELDS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in DAILY_NONNEGATIVE_COLUMNS:
        if (frame[column].dropna() < 0.0).any():
            raise ValueError(f"negative inert daily field: {column}")
    known_open_interest = frame[["openposition", "openpositionvalue"]].dropna(how="all")
    if not known_open_interest.empty and not np.isfinite(
        known_open_interest.fillna(0.0).to_numpy(dtype=float)
    ).all():
        raise ValueError("inert daily open interest is not finite")
    frame["reported_trade_activity"] = False
    frame["ohlc_complete"] = False
    frame["ohlc_missing_with_activity"] = False
    frame["has_trade"] = False
    frame["has_settlement"] = False
    frame = frame.rename(
        columns={
            "settleprice": "settle",
            "numtrades": "num_trades",
            "openposition": "open_interest",
            "openpositionvalue": "open_interest_value",
        }
    )
    return frame[list(NORMALIZED_DAILY_COLUMNS)]


def _filtered_payload(payload: Mapping[str, Any], keep: pd.Series) -> dict[str, Any]:
    history = _mapping(payload.get("history"), "history payload")
    columns = history.get("columns")
    rows = history.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list) or len(rows) != len(keep):
        raise ValueError("pre-2012 V2 history page is malformed")
    admitted_rows = [row for row, admitted in zip(rows, keep, strict=True) if admitted]
    return {
        "history": {"columns": list(columns), "data": admitted_rows},
        "history.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[0, len(admitted_rows), max(len(admitted_rows), 1)]],
        },
    }


def parse_futures_daily_payload_v2(
    payload: dict[str, Any],
    asset: FuturesAssetSpec,
    expected_secid: str | None = None,
) -> tuple[pd.DataFrame, IssPageCursor]:
    """Preserve identity-only official rows without converting them to market bars."""
    cursor = parse_iss_page_cursor(payload, "history")
    raw = parent._table(payload, "history")
    if raw.columns.tolist() != [column.lower() for column in parent.DAILY_COLUMNS]:
        raise ValueError("pre-2012 V2 daily columns differ from sealed schema")
    inert = _inert_mask(raw)
    admitted, _ = base_parse_daily(
        _filtered_payload(payload, ~inert),
        asset,
        expected_secid=expected_secid,
    )
    inert_rows = _normalize_inert_rows(raw.loc[inert], asset, expected_secid)
    combined = pd.concat([admitted, inert_rows], ignore_index=True)
    if len(combined) != len(raw):
        raise ValueError("pre-2012 V2 parser lost a source row")
    if combined.duplicated(["trade_date", "secid", "board_id"]).any():
        raise ValueError("pre-2012 V2 parser produced duplicate daily identity")
    return combined.sort_values("trade_date", ignore_index=True), cursor


@contextmanager
def _parser_context() -> Iterator[None]:
    original = parent.parse_futures_daily_payload
    if original is not base_parse_daily:
        raise RuntimeError("pre-2012 V2 parent parser is already patched")
    parent.parse_futures_daily_payload = parse_futures_daily_payload_v2
    try:
        yield
    finally:
        parent.parse_futures_daily_payload = original


def collect_source(
    protocol: V2SourceProtocol,
    session: parent.SessionLike,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    progress: Callable[[str], None] | None = None,
) -> parent.SourceCollection:
    """Run the unchanged exact collector with the scoped placeholder parser."""
    with _parser_context():
        return parent.collect_source(
            protocol.source,
            session,
            clock=clock,
            progress=progress,
        )


def _inert_rows(daily: pd.DataFrame) -> pd.Series:
    return (
        ~daily["reported_trade_activity"]
        & ~daily["has_settlement"]
        & ~daily["ohlc_complete"]
    )


def _source_checks(
    protocol: V2SourceProtocol,
    collection: parent.SourceCollection,
) -> dict[str, bool]:
    checks = v1._source_checks(protocol, collection)
    daily = collection.daily
    inert = _inert_rows(daily)
    known = daily.loc[
        daily["secid"].astype(str).eq(KNOWN_INERT_SECID)
        & daily["trade_date"].eq(KNOWN_INERT_DATE)
    ]
    inert_values = daily.loc[
        inert,
        ["open", "low", "high", "close", "settle", "waprice"],
    ]
    inert_activity = daily.loc[inert, ["value", "volume", "num_trades"]]
    checks.update(
        {
            "inert_rows_explicitly_present": bool(inert.any()),
            "known_v1_failure_row_preserved_once": len(known) == 1,
            "known_v1_failure_row_is_inert": len(known) == 1
            and bool(_inert_rows(known).iloc[0]),
            "inert_prices_and_settlement_missing": bool(
                inert_values.isna().all(axis=None)
            ),
            "inert_activity_missing_or_zero": bool(
                (inert_activity.isna() | inert_activity.eq(0.0)).all(axis=None)
            ),
            "inert_rows_not_executable": bool(
                (~daily.loc[inert, ["has_trade", "has_settlement"]]).all(axis=None)
            ),
            "every_daily_row_classified": bool(
                (
                    inert
                    | daily["reported_trade_activity"]
                    | daily["has_settlement"]
                    | daily["ohlc_complete"]
                ).all()
            ),
        }
    )
    return checks


def _rewrite_v2_manifest(
    protocol: V2SourceProtocol,
    collection: parent.SourceCollection,
    staging: Path,
) -> None:
    manifest_path = staging / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    inert = _inert_rows(collection.daily)
    manifest.pop("manifest_payload_sha256", None)
    manifest["schema_version"] = 2
    manifest["source_id"] = SOURCE_ID
    manifest["source_checks"] = _source_checks(protocol, collection)
    manifest["counts"]["inert_daily_rows"] = int(inert.sum())
    for logical, asset_code in v1.ASSET_CODES.items():
        asset_inert = inert & collection.daily["asset_code"].astype(str).eq(asset_code)
        manifest["counts"]["by_asset"][logical]["inert_daily_rows"] = int(
            asset_inert.sum()
        )
    manifest["parser_correction"] = {
        "parent_source_protocol_sha256": V1_CONFIG_SHA256,
        "universe_dates_endpoints_unchanged": True,
        "raw_payload_preserved_exactly": True,
        "inert_row_policy": (
            "preserve_identity_and_missing_values_with_all_market_flags_false"
        ),
        "inert_row_is_zero_return": False,
        "inert_row_is_executable": False,
        "known_failure_identity": {
            "secid": KNOWN_INERT_SECID,
            "trade_date": KNOWN_INERT_DATE.date().isoformat(),
        },
    }
    manifest["temporal_semantics"]["inert_daily_rows_are_market_bars"] = False
    manifest["temporal_semantics"]["inert_daily_rows_are_zero_returns"] = False
    manifest["limitations"] = protocol.payload["limitations"]
    identity = hashlib.sha256(parent._canonical_json(manifest)).hexdigest()
    write_json(
        manifest_path,
        {**manifest, "manifest_payload_sha256": identity},
    )
    atomic_write_text(
        staging / "manifest.sha256",
        f"{v1.sha256_file(manifest_path)}  manifest.json\n",
    )


def persist_source(
    protocol: V2SourceProtocol,
    collection: parent.SourceCollection,
    output_directory: Path | None = None,
) -> Path:
    """Publish an atomic V2 bundle while reusing V1 artifact serialization."""
    checks = _source_checks(protocol, collection)
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(f"pre-2012 V2 source checks failed: {failed}")
    final = (
        output_directory or (PROJECT_ROOT / protocol.source.output_relative)
    ).resolve()
    if final.exists():
        raise FileExistsError(f"pre-2012 V2 source output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=f".{final.name}.v2.", dir=final.parent))
    staging = workspace / "bundle"
    try:
        v1.persist_source(protocol, collection, staging)
        _rewrite_v2_manifest(protocol, collection, staging)
        staging.replace(final)
    except Exception:
        shutil.rmtree(workspace, ignore_errors=True)
        raise
    shutil.rmtree(workspace, ignore_errors=True)
    return final


def audit_bundle(protocol: V2SourceProtocol) -> v1.SourceAudit:
    """Replay exact V2 raw responses and compare every normalized artifact."""
    root = (PROJECT_ROOT / protocol.source.output_relative).resolve()
    manifest_path = root / "manifest.json"
    sidecar_path = root / "manifest.sha256"
    if not manifest_path.is_file() or not sidecar_path.is_file():
        raise FileNotFoundError(f"pre-2012 V2 source bundle is incomplete: {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    raw_meta = manifest.get("artifacts", {}).get("raw_archive", {})
    raw_path = root / str(raw_meta.get("path", ""))
    records = v1._read_raw_records(raw_path)
    replay_session = v1._ReplaySession(records)
    replay_protocol = V2SourceProtocol(
        source=replace(
            protocol.source,
            attempts=1,
            retry_backoff_seconds=0.0,
            request_interval_seconds=0.0,
        ),
        payload=protocol.payload,
        dependency_hashes=protocol.dependency_hashes,
    )
    replay = collect_source(
        replay_protocol,
        replay_session,
        clock=replay_session.clock,
    )
    identity_payload = dict(manifest)
    recorded_identity = identity_payload.pop("manifest_payload_sha256", None)
    checks: dict[str, bool] = {
        "manifest_sha_exact": sidecar_path.read_text(encoding="utf-8-sig").split()[0]
        == v1.sha256_file(manifest_path),
        "manifest_payload_sha_exact": hashlib.sha256(
            parent._canonical_json(identity_payload)
        ).hexdigest()
        == recorded_identity,
        "source_id_exact": manifest.get("source_id") == SOURCE_ID,
        "protocol_sha_exact": manifest.get("protocol", {}).get("sha256")
        == protocol.source.config_sha256,
        "implementation_sha_exact": manifest.get("protocol", {}).get(
            "implementation_sha256"
        )
        == protocol.dependency_hashes,
        "raw_archive_sha_exact": v1.sha256_file(raw_path) == raw_meta.get("sha256"),
        "raw_request_count_exact": len(records) == int(raw_meta.get("requests", -1)),
        "raw_replay_consumed_all": replay_session.index == len(records),
        "raw_request_records_exact": tuple(records) == replay.requests,
        "source_checks_exact": manifest.get("source_checks")
        == _source_checks(protocol, replay),
        "inert_count_exact": int(manifest.get("counts", {}).get("inert_daily_rows", -1))
        == int(_inert_rows(replay.daily).sum()),
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
        checks[f"{name}_sha256"] = v1.sha256_file(path) == metadata["sha256"]
        stored = pd.read_parquet(path)
        checks[f"{name}_rows"] = len(stored) == int(metadata["rows"])
        checks[f"{name}_columns"] = stored.columns.tolist() == metadata["columns"]
        try:
            pd.testing.assert_frame_equal(
                v1._normalized_frame(stored),
                v1._normalized_frame(expected),
                check_dtype=False,
            )
        except AssertionError:
            checks[f"{name}_replay_exact"] = False
        else:
            checks[f"{name}_replay_exact"] = True
    return v1.SourceAudit(
        checks=checks,
        counts={
            "contracts": len(replay.contracts),
            "daily_rows": len(replay.daily),
            "inert_daily_rows": int(_inert_rows(replay.daily).sum()),
            "requests": len(records),
        },
    )


def download_source(
    protocol: V2SourceProtocol,
    *,
    session: parent.SessionLike | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Collect V2 once, publish atomically, and require exact offline replay."""
    owned_session = session is None
    active_session: parent.SessionLike = session or requests.Session()
    try:
        collection = collect_source(
            protocol,
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
        raise ValueError(f"pre-2012 V2 source audit failed: {failed}")
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
