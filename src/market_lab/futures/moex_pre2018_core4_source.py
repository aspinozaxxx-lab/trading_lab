"""Collect sealed official MOEX daily futures history for the unseen 2012-2017 period."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import quote, urlencode

import pandas as pd
import requests
import yaml

from market_lab.futures.iss import (
    parse_futures_boards_payload,
    resolve_canonical_board_segments,
)
from market_lab.futures.market_data import parse_futures_daily_payload
from market_lab.futures.specs import FuturesAssetSpec, canonical_contract_id
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_pre2018_core4_source_v2.yaml"
SEARCH_ENDPOINT: Final[str] = "https://iss.moex.com/iss/securities.json"
DETAIL_ENDPOINT: Final[str] = "https://iss.moex.com/iss/securities/{secid}.json"
HISTORY_ENDPOINT: Final[str] = (
    "https://iss.moex.com/iss/history/engines/futures/markets/forts/"
    "boards/{board_id}/securities/{secid}.json"
)
SEARCH_COLUMNS: Final[tuple[str, ...]] = ("SECID", "SHORTNAME", "GROUP", "TYPE")
DESCRIPTION_COLUMNS: Final[tuple[str, ...]] = ("name", "value")
BOARD_COLUMNS: Final[tuple[str, ...]] = (
    "secid",
    "boardid",
    "history_from",
    "history_till",
    "listed_from",
    "listed_till",
    "is_primary",
    "is_traded",
    "engine",
    "market",
)
DAILY_COLUMNS: Final[tuple[str, ...]] = (
    "BOARDID",
    "TRADEDATE",
    "SECID",
    "OPEN",
    "LOW",
    "HIGH",
    "CLOSE",
    "VALUE",
    "VOLUME",
    "OPENPOSITION",
    "OPENPOSITIONVALUE",
    "SETTLEPRICE",
    "WAPRICE",
    "NUMTRADES",
    "ASSETCODE",
)
REQUIRED_DESCRIPTION_FIELDS: Final[frozenset[str]] = frozenset(
    {"SECID", "SHORTNAME", "FRSTTRADE", "LSTTRADE", "LSTDELDATE"}
)
CONTRACT_COLUMNS: Final[tuple[str, ...]] = (
    "canonical_contract_id",
    "secid",
    "name",
    "start_date",
    "last_trade_date",
    "expiration_date",
    "asset_code",
    "logical_symbol",
    "underlying_asset",
    "is_traded",
)
USER_AGENT: Final[str] = "market-lab-pre2018-core4-source/1.0 (MOEX ISS research)"
PRE2018_CEILING: Final[date] = date(2018, 1, 1)


class ResponseLike(Protocol):
    """Minimal requests-compatible response used in production and synthetic tests."""

    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class SessionLike(Protocol):
    """Minimal requests-compatible HTTP session."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> ResponseLike: ...


@dataclass(frozen=True, slots=True)
class AssetDiscoveryRule:
    """One sealed exact-name discovery rule for an underlying futures family."""

    logical_symbol: str
    asset_code: str
    search_query: str
    shortname_prefix: str
    expected_months_by_year: tuple[tuple[int, tuple[int, ...]], ...]
    expected_contract_count: int

    @property
    def expected_shortnames(self) -> frozenset[str]:
        names = {
            f"{self.shortname_prefix}-{month}.{year % 100:02d}"
            for year, months in self.expected_months_by_year
            for month in months
        }
        if len(names) != self.expected_contract_count:
            raise ValueError(f"sealed expected count mismatch for {self.logical_symbol}")
        return frozenset(names)


@dataclass(frozen=True, slots=True)
class SourceProtocol:
    """Validated source-only protocol; it contains no strategy or outcome parameters."""

    config_path: Path
    config_sha256: str
    implementation_sha256: str
    source_start: date
    source_end: date
    protected_from: date
    primary_board: str
    search_page_size: int
    maximum_search_pages: int
    maximum_history_pages_per_segment: int
    timeout_seconds: float
    attempts: int
    retry_backoff_seconds: float
    request_interval_seconds: float
    output_relative: str
    rules: tuple[AssetDiscoveryRule, ...]


@dataclass(frozen=True, slots=True)
class SourceCollection:
    """Normalized source tables and the exact raw request log."""

    discovery: pd.DataFrame
    contracts: pd.DataFrame
    boards: pd.DataFrame
    segments: pd.DataFrame
    daily: pd.DataFrame
    coverage: pd.DataFrame
    requests: tuple[dict[str, Any], ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _bounded_project_path(relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise ValueError("protocol path must be non-empty and project-relative")
    root = PROJECT_ROOT.resolve()
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"protocol path escapes project root: {relative_path}") from error
    return candidate


def _parse_sidecar(sidecar: Path, expected_name: str) -> str:
    parts = sidecar.read_text(encoding="utf-8-sig").strip().split()
    if len(parts) != 2 or parts[1] != expected_name:
        raise ValueError(f"invalid SHA sidecar: {sidecar}")
    digest = parts[0].lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"invalid SHA-256 in sidecar: {sidecar}")
    return digest


def _parse_asset_rule(payload: Mapping[str, Any]) -> AssetDiscoveryRule:
    months_payload = payload.get("expected_months_by_year")
    if not isinstance(months_payload, Mapping) or not months_payload:
        raise ValueError("asset rule lacks expected_months_by_year")
    months_by_year: list[tuple[int, tuple[int, ...]]] = []
    for raw_year, raw_months in months_payload.items():
        year = int(raw_year)
        if not isinstance(raw_months, list) or not raw_months:
            raise ValueError("expected months must be a non-empty list")
        months = tuple(int(value) for value in raw_months)
        if len(months) != len(set(months)) or any(value < 1 or value > 12 for value in months):
            raise ValueError("expected months must be unique values from 1 through 12")
        months_by_year.append((year, tuple(sorted(months))))
    rule = AssetDiscoveryRule(
        logical_symbol=str(payload["logical_symbol"]),
        asset_code=str(payload["asset_code"]),
        search_query=str(payload["search_query"]),
        shortname_prefix=str(payload["shortname_prefix"]),
        expected_months_by_year=tuple(sorted(months_by_year)),
        expected_contract_count=int(payload["expected_contract_count"]),
    )
    expected_spec = FuturesAssetSpec.from_symbol(rule.logical_symbol)
    if expected_spec.asset_code != rule.asset_code:
        raise ValueError(f"asset code mismatch for {rule.logical_symbol}")
    _ = rule.expected_shortnames
    return rule


def load_source_protocol(config_path: Path = DEFAULT_CONFIG) -> SourceProtocol:
    """Verify config/implementation bytes before a source request can be constructed."""
    path = config_path.resolve()
    content = path.read_bytes()
    actual_sha = hashlib.sha256(content).hexdigest()
    stated_sha = _parse_sidecar(path.with_suffix(".sha256"), path.name)
    if actual_sha != stated_sha:
        raise ValueError("source protocol SHA-256 mismatch")
    declared_payload = yaml.safe_load(content.decode("utf-8-sig"))
    if not isinstance(declared_payload, Mapping):
        raise ValueError("source protocol must be a YAML object")
    if declared_payload.get("protocol_id") != "moex_pre2018_core4_daily_source_v2":
        raise ValueError("unexpected source protocol id")
    parent = declared_payload.get("parent_protocol")
    if not isinstance(parent, Mapping):
        raise ValueError("source protocol v2 lacks its sealed parent identity")
    parent_path = _bounded_project_path(str(parent["path"]))
    parent_bytes = parent_path.read_bytes()
    parent_sha = hashlib.sha256(parent_bytes).hexdigest()
    if parent_sha != str(parent["sha256"]).lower():
        raise ValueError("parent source protocol SHA-256 mismatch")
    if _parse_sidecar(parent_path.with_suffix(".sha256"), parent_path.name) != parent_sha:
        raise ValueError("parent source protocol sidecar mismatch")
    parent_payload = yaml.safe_load(parent_bytes.decode("utf-8-sig"))
    if not isinstance(parent_payload, Mapping):
        raise ValueError("parent source protocol must be a YAML object")
    payload = dict(parent_payload)
    payload.update(
        {key: value for key, value in declared_payload.items() if key != "parent_protocol"}
    )
    if payload.get("scope") != "source_only_no_strategy_no_outcomes":
        raise ValueError("source protocol scope is not source-only")

    implementation = payload.get("implementation")
    if not isinstance(implementation, Mapping):
        raise ValueError("source protocol lacks implementation identity")
    implementation_path = _bounded_project_path(str(implementation["path"]))
    implementation_sha = str(implementation["sha256"]).lower()
    if sha256_file(implementation_path) != implementation_sha:
        raise ValueError("source implementation SHA-256 mismatch")

    dates = payload.get("dates")
    network = payload.get("network")
    discovery = payload.get("discovery")
    daily = payload.get("daily_history")
    output = payload.get("output")
    if not all(isinstance(item, Mapping) for item in (dates, network, discovery, daily, output)):
        raise ValueError("source protocol has an invalid section")
    assert isinstance(dates, Mapping)
    assert isinstance(network, Mapping)
    assert isinstance(discovery, Mapping)
    assert isinstance(daily, Mapping)
    assert isinstance(output, Mapping)
    source_start = date.fromisoformat(str(dates["source_start"]))
    source_end = date.fromisoformat(str(dates["source_end"]))
    protected_from = date.fromisoformat(str(dates["protected_from"]))
    if source_start > source_end or source_end >= PRE2018_CEILING:
        raise ValueError("source range must end before 2018-01-01")
    if source_end >= protected_from:
        raise ValueError("source range crosses protected boundary")
    if list(discovery.get("columns", [])) != list(SEARCH_COLUMNS):
        raise ValueError("discovery columns differ from the sealed closed schema")
    if list(daily.get("columns", [])) != list(DAILY_COLUMNS):
        raise ValueError("daily columns differ from the sealed closed schema")
    if daily.get("pagination") != "history_cursor_exact_total":
        raise ValueError("daily pagination contract changed")
    rules_payload = discovery.get("assets")
    if not isinstance(rules_payload, list):
        raise ValueError("source protocol lacks asset discovery rules")
    rules = tuple(_parse_asset_rule(item) for item in rules_payload if isinstance(item, Mapping))
    if len(rules) != len(rules_payload) or {rule.logical_symbol for rule in rules} != {
        "BR",
        "MIX",
        "RI",
        "SI",
    }:
        raise ValueError("source protocol must contain exactly the four core assets")
    expected_total = int(discovery["expected_total_contracts"])
    if sum(rule.expected_contract_count for rule in rules) != expected_total:
        raise ValueError("total sealed contract count does not match asset rules")
    return SourceProtocol(
        config_path=path,
        config_sha256=actual_sha,
        implementation_sha256=implementation_sha,
        source_start=source_start,
        source_end=source_end,
        protected_from=protected_from,
        primary_board=str(daily["primary_board"]),
        search_page_size=int(discovery["page_size"]),
        maximum_search_pages=int(discovery["maximum_pages_per_query"]),
        maximum_history_pages_per_segment=int(daily["maximum_pages_per_segment"]),
        timeout_seconds=float(network["timeout_seconds"]),
        attempts=int(network["attempts"]),
        retry_backoff_seconds=float(network["retry_backoff_seconds"]),
        request_interval_seconds=float(network["minimum_request_interval_seconds"]),
        output_relative=str(output["default_relative_directory"]),
        rules=rules,
    )


def _table(payload: Mapping[str, Any], name: str) -> pd.DataFrame:
    block = payload.get(name)
    if not isinstance(block, Mapping):
        raise ValueError(f"MOEX payload lacks {name}")
    columns = block.get("columns")
    rows = block.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list):
        raise ValueError(f"invalid MOEX table {name}")
    normalized = [str(column).lower() for column in columns]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"duplicate columns in MOEX table {name}")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError(f"malformed row in MOEX table {name}")
    return pd.DataFrame(rows, columns=normalized)


def _retrieved_at(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None:
        raise ValueError("request clock must return a timezone-aware datetime")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _request_json(
    session: SessionLike,
    url: str,
    protocol: SourceProtocol,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(protocol.attempts):
        try:
            response = session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=protocol.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("MOEX response is not an object")
            if protocol.request_interval_seconds > 0.0:
                time.sleep(protocol.request_interval_seconds)
            return payload
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt + 1 < protocol.attempts:
                time.sleep(protocol.retry_backoff_seconds * (2**attempt))
    raise RuntimeError(f"MOEX request failed: {url}: {last_error}") from last_error


def search_url(rule: AssetDiscoveryRule, offset: int, page_size: int) -> str:
    if offset < 0 or page_size <= 0:
        raise ValueError("invalid search pagination")
    query = urlencode(
        {
            "q": rule.search_query,
            "group_by": "type",
            "group_by_filter": "futures",
            "iss.meta": "off",
            "iss.only": "securities",
            "securities.columns": ",".join(column.lower() for column in SEARCH_COLUMNS),
            "start": offset,
            "limit": page_size,
        }
    )
    return f"{SEARCH_ENDPOINT}?{query}"


def detail_url(secid: str) -> str:
    if not secid:
        raise ValueError("SECID is required")
    query = urlencode(
        {
            "iss.meta": "off",
            "iss.only": "description,boards",
            "description.columns": ",".join(DESCRIPTION_COLUMNS),
            "boards.columns": ",".join(BOARD_COLUMNS),
        }
    )
    return f"{DETAIL_ENDPOINT.format(secid=quote(secid, safe=''))}?{query}"


def history_url(
    protocol: SourceProtocol,
    secid: str,
    board_id: str,
    start: date,
    end: date,
    offset: int,
) -> str:
    if not secid or not board_id or offset < 0 or start > end:
        raise ValueError("invalid history request")
    if start < protocol.source_start or end > protocol.source_end:
        raise ValueError("history request escapes sealed source range")
    if end >= PRE2018_CEILING or end >= protocol.protected_from:
        raise ValueError("history request crosses a protected boundary")
    query = urlencode(
        {
            "from": start.isoformat(),
            "till": end.isoformat(),
            "start": offset,
            "limit": 100,
            "iss.meta": "off",
            "iss.only": "history,history.cursor",
            "history.columns": ",".join(DAILY_COLUMNS),
        }
    )
    endpoint = HISTORY_ENDPOINT.format(
        board_id=quote(board_id, safe=""),
        secid=quote(secid, safe=""),
    )
    return f"{endpoint}?{query}"


def _archive_request(
    requests_log: list[dict[str, Any]],
    *,
    kind: str,
    url: str,
    payload: dict[str, Any],
    clock: Callable[[], datetime],
    asset_code: str | None = None,
    secid: str | None = None,
) -> None:
    requests_log.append(
        {
            "request_index": len(requests_log) + 1,
            "request_kind": kind,
            "asset_code": asset_code,
            "secid": secid,
            "request_url": url,
            "retrieved_at_utc": _retrieved_at(clock),
            "payload": payload,
        }
    )


def discover_contracts(
    protocol: SourceProtocol,
    session: SessionLike,
    requests_log: list[dict[str, Any]],
    clock: Callable[[], datetime],
) -> pd.DataFrame:
    """Exhaust each fuzzy finder query, then admit only the sealed exact shortnames."""
    admitted: list[pd.DataFrame] = []
    for rule in protocol.rules:
        pages: list[pd.DataFrame] = []
        seen_rows: set[tuple[str, str, str, str]] = set()
        offset = 0
        for _ in range(protocol.maximum_search_pages):
            url = search_url(rule, offset, protocol.search_page_size)
            payload = _request_json(session, url, protocol)
            _archive_request(
                requests_log,
                kind="security_search",
                url=url,
                payload=payload,
                clock=clock,
                asset_code=rule.asset_code,
            )
            page = _table(payload, "securities")
            if list(page.columns) != [column.lower() for column in SEARCH_COLUMNS]:
                raise ValueError("MOEX finder returned a non-sealed column schema")
            if len(page) > protocol.search_page_size:
                raise ValueError("MOEX finder page exceeds the sealed page size")
            tuples = [tuple(str(value) for value in row) for row in page.itertuples(index=False)]
            if len(tuples) != len(set(tuples)) or any(value in seen_rows for value in tuples):
                raise ValueError("duplicate security finder row within or across pages")
            seen_rows.update(tuples)
            if not page.empty:
                pages.append(page)
            offset += len(page)
            if len(page) < protocol.search_page_size:
                break
        else:
            raise ValueError(f"security finder pagination exceeded limit for {rule.asset_code}")
        combined = pd.concat(pages, ignore_index=True) if pages else pd.DataFrame()
        expected = rule.expected_shortnames
        selected = combined.loc[combined["shortname"].astype(str).isin(expected)].copy()
        if not selected["type"].astype(str).eq("futures").all():
            raise ValueError("finder admitted a non-futures row")
        if not selected["group"].astype(str).eq("futures_forts").all():
            raise ValueError("finder admitted a non-FORTS row")
        if selected["shortname"].duplicated().any() or selected["secid"].duplicated().any():
            raise ValueError("finder returned duplicate exact contract identities")
        found = frozenset(selected["shortname"].astype(str))
        if found != expected or len(selected) != rule.expected_contract_count:
            missing = sorted(expected - found)
            extra = sorted(found - expected)
            raise ValueError(
                f"exact discovery mismatch for {rule.logical_symbol}: "
                f"missing={missing}, extra={extra}, rows={len(selected)}"
            )
        selected.insert(0, "logical_symbol", rule.logical_symbol)
        selected.insert(1, "asset_code", rule.asset_code)
        admitted.append(selected)
    result = pd.concat(admitted, ignore_index=True)
    if result["secid"].duplicated().any() or result["shortname"].duplicated().any():
        raise ValueError("core-four discovery identities overlap across assets")
    return result.sort_values(["asset_code", "shortname"], kind="mergesort", ignore_index=True)


def _description_values(payload: Mapping[str, Any]) -> dict[str, Any]:
    description = _table(payload, "description")
    if list(description.columns) != list(DESCRIPTION_COLUMNS):
        raise ValueError("MOEX description returned a non-sealed schema")
    names = description["name"].astype(str)
    if names.duplicated().any():
        raise ValueError("MOEX description contains duplicate field names")
    values = dict(zip(names, description["value"], strict=True))
    if missing := REQUIRED_DESCRIPTION_FIELDS - set(values):
        raise ValueError(f"MOEX description lacks fields: {sorted(missing)}")
    return values


def fetch_contract_metadata(
    protocol: SourceProtocol,
    discovery: pd.DataFrame,
    session: SessionLike,
    requests_log: list[dict[str, Any]],
    clock: Callable[[], datetime],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Resolve exact listing dates and dated RFUD board history for every discovered alias."""
    contract_rows: list[dict[str, Any]] = []
    board_frames: list[pd.DataFrame] = []
    for row in discovery.to_dict("records"):
        secid = str(row["secid"])
        url = detail_url(secid)
        payload = _request_json(session, url, protocol)
        _archive_request(
            requests_log,
            kind="security_description_and_boards",
            url=url,
            payload=payload,
            clock=clock,
            asset_code=str(row["asset_code"]),
            secid=secid,
        )
        values = _description_values(payload)
        if str(values["SECID"]) != secid or str(values["SHORTNAME"]) != str(row["shortname"]):
            raise ValueError(f"description identity mismatch for {secid}")
        start_date = pd.Timestamp(values["FRSTTRADE"]).normalize()
        last_trade_date = pd.Timestamp(values["LSTTRADE"]).normalize()
        expiration_date = pd.Timestamp(values["LSTDELDATE"]).normalize()
        if pd.isna(start_date) or pd.isna(last_trade_date) or pd.isna(expiration_date):
            raise ValueError(f"missing contract dates for {secid}")
        if not start_date <= last_trade_date <= expiration_date:
            raise ValueError(f"invalid contract date ordering for {secid}")
        if not protocol.source_start.year <= expiration_date.year <= protocol.source_end.year:
            raise ValueError(f"contract expiry escaped sealed years for {secid}")
        contract_rows.append(
            {
                "canonical_contract_id": canonical_contract_id(
                    str(row["asset_code"]), secid, expiration_date.date()
                ),
                "secid": secid,
                "name": str(row["shortname"]),
                "start_date": start_date,
                "last_trade_date": last_trade_date,
                "expiration_date": expiration_date,
                "asset_code": str(row["asset_code"]),
                "logical_symbol": str(row["logical_symbol"]),
                "underlying_asset": str(row["asset_code"]),
                "is_traded": False,
            }
        )
        boards = parse_futures_boards_payload(payload, preferred_board=protocol.primary_board)
        if boards.empty or not boards["secid"].astype(str).eq(secid).all():
            raise ValueError(f"no exact {protocol.primary_board} board history for {secid}")
        board_frames.append(boards)
    contracts = pd.DataFrame(contract_rows, columns=CONTRACT_COLUMNS).sort_values(
        ["asset_code", "expiration_date", "secid"], kind="mergesort", ignore_index=True
    )
    duplicate_contract = contracts["canonical_contract_id"].duplicated().any()
    duplicate_secid = contracts["secid"].duplicated().any()
    if duplicate_contract or duplicate_secid:
        raise ValueError("duplicate normalized contract identity")
    boards = pd.concat(board_frames, ignore_index=True).sort_values(
        ["secid", "history_from"], kind="mergesort", ignore_index=True
    )
    segments = resolve_canonical_board_segments(
        contracts,
        boards,
        preferred_board=protocol.primary_board,
        require_all=True,
    )
    if set(segments["canonical_contract_id"]) != set(contracts["canonical_contract_id"]):
        raise ValueError("not every discovered contract has a resolved board segment")
    return contracts, boards, segments


def fetch_daily_segment(
    protocol: SourceProtocol,
    asset: FuturesAssetSpec,
    segment: Mapping[str, Any],
    start: date,
    end: date,
    session: SessionLike,
    requests_log: list[dict[str, Any]],
    clock: Callable[[], datetime],
) -> pd.DataFrame:
    """Follow the exact history cursor and return one non-empty normalized segment."""
    frames: list[pd.DataFrame] = []
    expected_total: int | None = None
    offset = 0
    for _ in range(protocol.maximum_history_pages_per_segment):
        url = history_url(
            protocol,
            str(segment["secid"]),
            str(segment["boardid"]),
            start,
            end,
            offset,
        )
        payload = _request_json(session, url, protocol)
        _archive_request(
            requests_log,
            kind="daily_history",
            url=url,
            payload=payload,
            clock=clock,
            asset_code=asset.asset_code,
            secid=str(segment["secid"]),
        )
        frame, cursor = parse_futures_daily_payload(
            payload,
            asset,
            expected_secid=str(segment["secid"]),
        )
        if cursor.index != offset:
            raise ValueError("daily history cursor index differs from request offset")
        if expected_total is None:
            expected_total = cursor.total
        elif cursor.total != expected_total:
            raise ValueError("daily history cursor total changed during pagination")
        expected_rows = min(cursor.page_size, max(cursor.total - cursor.index, 0))
        if len(frame) != expected_rows:
            raise ValueError("daily history page is truncated")
        if not frame.empty:
            if frame["trade_date"].dt.date.lt(start).any() or frame["trade_date"].dt.date.gt(
                end
            ).any():
                raise ValueError("daily history row escaped its request bounds")
            if not frame["board_id"].astype(str).eq(str(segment["boardid"])).all():
                raise ValueError("daily history returned another board")
            frames.append(frame)
        next_offset = cursor.next_index
        if next_offset is None:
            break
        if next_offset <= offset:
            raise ValueError("daily history cursor did not progress")
        offset = next_offset
    else:
        raise ValueError("daily history pagination exceeded the sealed limit")
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if combined.empty or len(combined) != (expected_total or 0):
        raise ValueError(f"empty or incomplete daily history for {segment['secid']}")
    if combined.duplicated(["trade_date", "secid", "board_id"]).any():
        raise ValueError("duplicate daily row across cursor pages")
    if not combined["trade_date"].is_monotonic_increasing:
        raise ValueError("daily cursor pages are not chronological")
    combined.insert(0, "canonical_segment_id", str(segment["canonical_segment_id"]))
    combined.insert(0, "canonical_contract_id", str(segment["canonical_contract_id"]))
    return combined


def collect_source(
    protocol: SourceProtocol,
    session: SessionLike,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    progress: Callable[[str], None] | None = None,
) -> SourceCollection:
    """Collect metadata and daily prices without calculating any return, target, or PnL."""
    requests_log: list[dict[str, Any]] = []
    discovery = discover_contracts(protocol, session, requests_log, clock)
    if progress is not None:
        progress(f"discovered {len(discovery)} sealed contracts")
    contracts, boards, segments = fetch_contract_metadata(
        protocol,
        discovery,
        session,
        requests_log,
        clock,
    )
    if len(contracts) != sum(rule.expected_contract_count for rule in protocol.rules):
        raise ValueError("metadata contract count differs from the sealed discovery count")

    contract_lookup = contracts.set_index("canonical_contract_id")
    daily_frames: list[pd.DataFrame] = []
    coverage_rows: list[dict[str, Any]] = []
    for asset_index, rule in enumerate(protocol.rules, start=1):
        asset = FuturesAssetSpec.from_symbol(rule.logical_symbol)
        asset_segments = segments.loc[
            segments["canonical_contract_id"].isin(
                contracts.loc[contracts["asset_code"] == rule.asset_code, "canonical_contract_id"]
            )
        ]
        for segment in asset_segments.to_dict("records"):
            contract = contract_lookup.loc[str(segment["canonical_contract_id"])]
            start = max(
                protocol.source_start,
                pd.Timestamp(segment["segment_start"]).date(),
                pd.Timestamp(contract["start_date"]).date(),
            )
            end = min(
                protocol.source_end,
                pd.Timestamp(segment["segment_end"]).date(),
                pd.Timestamp(contract["expiration_date"]).date(),
            )
            if start > end:
                raise ValueError(f"resolved segment does not intersect source range: {segment}")
            frame = fetch_daily_segment(
                protocol,
                asset,
                segment,
                start,
                end,
                session,
                requests_log,
                clock,
            )
            daily_frames.append(frame)
            dates = frame["trade_date"].sort_values()
            gaps = dates.diff().dropna().dt.days
            coverage_rows.append(
                {
                    "asset_code": asset.asset_code,
                    "logical_symbol": asset.logical_symbol,
                    "canonical_contract_id": segment["canonical_contract_id"],
                    "canonical_segment_id": segment["canonical_segment_id"],
                    "secid": segment["secid"],
                    "board_id": segment["boardid"],
                    "requested_start": pd.Timestamp(start),
                    "requested_end": pd.Timestamp(end),
                    "rows": len(frame),
                    "minimum_trade_date": dates.min(),
                    "maximum_trade_date": dates.max(),
                    "trade_rows": int(frame["has_trade"].sum()),
                    "settlement_rows": int(frame["has_settlement"].sum()),
                    "ohlc_missing_with_activity_rows": int(
                        frame["ohlc_missing_with_activity"].sum()
                    ),
                    "maximum_calendar_gap_days": int(gaps.max()) if not gaps.empty else 0,
                }
            )
        if progress is not None:
            progress(
                f"daily history complete for {rule.logical_symbol} "
                f"({asset_index}/{len(protocol.rules)})"
            )
    daily = pd.concat(daily_frames, ignore_index=True).sort_values(
        ["trade_date", "asset_code", "canonical_contract_id"],
        kind="mergesort",
        ignore_index=True,
    )
    if daily.duplicated(["trade_date", "canonical_contract_id", "board_id"]).any():
        raise ValueError("duplicate normalized daily observation")
    if daily["trade_date"].dt.date.lt(protocol.source_start).any() or daily[
        "trade_date"
    ].dt.date.gt(protocol.source_end).any():
        raise ValueError("normalized daily source escaped the sealed interval")
    if daily["trade_date"].dt.date.ge(protocol.protected_from).any():
        raise ValueError("normalized daily source contains a protected row")
    coverage = pd.DataFrame(coverage_rows).sort_values(
        ["asset_code", "minimum_trade_date", "canonical_contract_id"],
        kind="mergesort",
        ignore_index=True,
    )
    return SourceCollection(
        discovery=discovery,
        contracts=contracts,
        boards=boards,
        segments=segments,
        daily=daily,
        coverage=coverage,
        requests=tuple(requests_log),
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


def _artifact(path: Path, frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "rows": len(frame),
        "columns": frame.columns.tolist(),
    }


def persist_source(
    protocol: SourceProtocol,
    collection: SourceCollection,
    output_directory: Path,
) -> Path:
    """Atomically persist one immutable source bundle outside Git."""
    final = output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"source output already exists: {final}")
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
        artifacts: dict[str, Any] = {}
        for name, frame in tables.items():
            path = temporary / f"{name}.parquet"
            _atomic_parquet(path, frame)
            artifacts[name] = _artifact(path, frame)

        raw_content = b"\n".join(_canonical_json(record) for record in collection.requests) + b"\n"
        raw_path = temporary / "official_moex_iss_responses.jsonl.gz"
        atomic_write_bytes(raw_path, gzip.compress(raw_content, compresslevel=6, mtime=0))
        artifacts["raw_archive"] = {
            "path": raw_path.name,
            "bytes": raw_path.stat().st_size,
            "sha256": sha256_file(raw_path),
            "requests": len(collection.requests),
        }
        retrieved = [str(record["retrieved_at_utc"]) for record in collection.requests]
        counts_by_asset = {
            asset_code: {
                "contracts": int(
                    collection.contracts["asset_code"].astype(str).eq(asset_code).sum()
                ),
                "daily_rows": int(collection.daily["asset_code"].astype(str).eq(asset_code).sum()),
            }
            for asset_code in sorted(collection.contracts["asset_code"].astype(str).unique())
        }
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-moex-core4-daily-current-vintage-2012-2017-v1",
            "provider": "MOEX ISS",
            "protocol": {
                "path": protocol.config_path.relative_to(PROJECT_ROOT).as_posix(),
                "bytes": protocol.config_path.stat().st_size,
                "sha256": protocol.config_sha256,
                "implementation_sha256": protocol.implementation_sha256,
            },
            "request_count": len(collection.requests),
            "retrieval": {
                "minimum_retrieved_at_utc": min(retrieved),
                "maximum_retrieved_at_utc": max(retrieved),
            },
            "request_bounds": {
                "from": protocol.source_start.isoformat(),
                "till": protocol.source_end.isoformat(),
                "pre2018_ceiling": PRE2018_CEILING.isoformat(),
                "protected_from": protocol.protected_from.isoformat(),
                "all_daily_request_till_values_before_2018": True,
            },
            "counts": {
                "contracts": len(collection.contracts),
                "board_segments": len(collection.segments),
                "daily_rows": len(collection.daily),
                "requests": len(collection.requests),
                "by_asset": counts_by_asset,
            },
            "temporal_semantics": {
                "contains_prices": True,
                "contains_returns_targets_labels_or_pnl": False,
                "daily_observation_time": "completed official MOEX trading date",
                "signal_use_not_before": "after completed source trade_date",
                "execution_not_before": "next factual open under a separately sealed protocol",
                "current_vintage_snapshot": True,
                "no_missing_value_zero_imputation": True,
                "no_gap_or_roll_return_bridge": True,
            },
            "access_observation": {
                "anonymous_http_observed": True,
                "raw_redistribution_allowed": False,
                "terms_and_market_data_policy_review_required": True,
                "research_use_only": True,
            },
            "limitations": {
                "historical_exchange_specs_exact": False,
                "historical_broker_fees_and_margin_exact": False,
                "order_book_or_spread_evidence": False,
                "main_v27_key_rate_20_percent_governor_activated": False,
                "live_admission_possible": False,
            },
            "artifacts": artifacts,
        }
        manifest_identity = hashlib.sha256(_canonical_json(manifest_core)).hexdigest()
        manifest_path = temporary / "manifest.json"
        write_json(
            manifest_path,
            {**manifest_core, "manifest_payload_sha256": manifest_identity},
        )
        manifest_sha = sha256_file(manifest_path)
        atomic_write_text(temporary / "manifest.sha256", f"{manifest_sha}  manifest.json\n")
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def download_source(
    config_path: Path = DEFAULT_CONFIG,
    *,
    output_directory: Path | None = None,
    session: SessionLike | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Verify the seal, collect the source, and atomically publish a single bundle."""
    protocol = load_source_protocol(config_path)
    output = output_directory or (PROJECT_ROOT / protocol.output_relative)
    owned_session = session is None
    network_session: SessionLike = session or requests.Session()
    try:
        collection = collect_source(
            protocol,
            network_session,
            clock=clock,
            progress=progress,
        )
        return persist_source(protocol, collection, output)
    finally:
        if owned_session and isinstance(network_session, requests.Session):
            network_session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-directory", type=Path)
    arguments = parser.parse_args(argv)
    result = download_source(
        arguments.config,
        output_directory=arguments.output_directory,
        progress=lambda message: print(message, flush=True),
    )
    print(result, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
