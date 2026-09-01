"""Collect and replay-audit official MOEX calendar-spread EOD history."""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import requests
import yaml

from market_lab.futures import iss
from market_lab.futures.market_data import parse_iss_page_cursor
from market_lab.futures.specs import FuturesAssetSpec
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG: Final[Path] = PROJECT_ROOT / "configs/moex_calendar_spread_source.yaml"
SOURCE_START: Final[date] = date(2021, 1, 1)
SOURCE_END: Final[date] = date(2025, 12, 31)
PROTECTED_FROM: Final[date] = date(2026, 1, 1)
ASSETS: Final[tuple[str, ...]] = ("SI", "RI", "BR", "MIX")
EXPECTED_SPREAD_COUNTS: Final[dict[str, int]] = {
    "SI": 16,
    "RI": 15,
    "BR": 59,
    "MIX": 20,
}
EXPECTED_MISSING_DATE_SPREADS: Final[dict[str, tuple[str, ...]]] = {
    "SI": ("SiZ2SiH3",),
    "RI": (),
    "BR": (),
    "MIX": ("MXU2MXZ2",),
}
EXPECTED_REGULAR_ADJACENT_COUNTS: Final[dict[str, int]] = {
    "SI": 16,
    "RI": 14,
    "BR": 52,
    "MIX": 19,
}
EXPECTED_NEAR_DATE_MATCH_COUNTS: Final[dict[str, int]] = {
    "SI": 16,
    "RI": 13,
    "BR": 56,
    "MIX": 18,
}
MONTH_CODES: Final[str] = "FGHJKMNQUVXZ"
USER_AGENT: Final[str] = "market-lab-research/0.30 (MOEX calendar spreads)"
REQUEST_TIMEOUT_SECONDS: Final[float] = 30.0
MAX_RETRIES: Final[int] = 3
MAX_PAGES: Final[int] = 50
ARCHIVE_PAGE_BASE: Final[str] = (
    "https://www.moex.com/en/derivatives/spreads/archive-spreads.aspx"
)
ARCHIVE_LIST_URL: Final[str] = (
    "https://www.moex.com/webservice/ArchiveSpreads.asmx/GetSpreadList"
)
ARCHIVE_EXPORT_TARGET: Final[str] = (
    "ctl00$PageContent$ctrlSpreads$lbExportToCsvComma"
)
ARCHIVE_BASE_FIELD: Final[str] = (
    "ctl00$PageContent$ctrlSpreads$ddlBaseActives"
)
ARCHIVE_SPREAD_FIELD: Final[str] = "ctl00$PageContent$ctrlSpreads$ddlSpreads"
ARCHIVE_BASE_STATE_FIELD: Final[str] = (
    "ctl00$PageContent$ctrlSpreads$CascadingDropDown1_ClientState"
)
ARCHIVE_SPREAD_STATE_FIELD: Final[str] = (
    "ctl00$PageContent$ctrlSpreads$CascadingDropDown2_ClientState"
)
ARCHIVE_CSV_HEADERS: Final[tuple[str, ...]] = (
    "moment",
    "isin",
    "small_name",
    "best_pk",
    "best_pr",
    "cena",
    "min_cena",
    "max_cena",
    "c_deal",
    "kol_cb",
    "sum_rub",
    "base_small_name",
    "",
)

SERIES_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "secid",
        "name",
        "start_date",
        "expiration_date",
        "asset_code",
        "is_traded",
    }
)
HISTORY_REQUIRED_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "boardid",
        "tradedate",
        "secid",
        "open",
        "low",
        "high",
        "close",
        "openpositionvalue",
        "value",
        "volume",
        "openposition",
        "settleprice",
        "waprice",
        "numtrades",
        "assetcode",
    }
)
DISCOVERY_COLUMNS: Final[tuple[str, ...]] = (
    "spread_id",
    "logical_asset",
    "asset_code",
    "secid",
    "near_secid",
    "far_secid",
    "archive_code",
    "series_start",
    "spread_last_trade",
    "near_expiration",
    "far_expiration",
    "expiry_gap_days",
    "near_expiration_matches_spread_last_trade",
    "regular_adjacent_expiry",
)
CATALOG_COLUMNS: Final[tuple[str, ...]] = DISCOVERY_COLUMNS + (
    "board_id",
    "board_history_from",
    "board_history_till",
    "iss_request_from",
    "iss_request_till",
    "archive_request_from",
    "archive_request_till",
)
ISS_DAILY_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "available_at",
    "spread_id",
    "logical_asset",
    "asset_code",
    "secid",
    "board_id",
    "near_secid",
    "far_secid",
    "spread_last_trade",
    "near_expiration",
    "far_expiration",
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
    "has_settlement",
)
ARCHIVE_DAILY_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "available_at",
    "spread_id",
    "logical_asset",
    "asset_code",
    "secid",
    "archive_code",
    "archive_instrument_id",
    "near_secid",
    "far_secid",
    "spread_last_trade",
    "near_expiration",
    "far_expiration",
    "last",
    "bid",
    "ask",
    "high",
    "low",
    "amount",
    "volume",
    "num_trades",
    "reported_trade_activity",
    "range_complete",
    "last_within_range",
    "last_outside_range",
    "two_sided_quote_fields_complete",
    "closing_quote_crossed",
    "inside_iss_request_interval",
    "inside_series_interval",
)
COVERAGE_COLUMNS: Final[tuple[str, ...]] = (
    "spread_id",
    "logical_asset",
    "secid",
    "archive_code",
    "iss_request_from",
    "iss_request_till",
    "archive_request_from",
    "archive_request_till",
    "iss_rows",
    "iss_reported_trade_rows",
    "iss_settlement_rows",
    "archive_rows",
    "archive_reported_trade_rows",
    "overlap_rows",
    "iss_only_rows",
    "archive_only_rows",
    "archive_outside_iss_interval_rows",
    "archive_outside_series_interval_rows",
    "archive_last_outside_range_rows",
    "archive_crossed_quote_rows",
    "first_iss_date",
    "last_iss_date",
    "first_archive_date",
    "last_archive_date",
)
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
class CalendarSpreadSourceProtocol:
    """Verified source-only declaration for public MOEX spread history."""

    config_path: Path
    config_sha256: str
    payload: dict[str, Any]
    output_directory: Path
    dependency_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class RawRecord:
    """One official response plus closed request metadata and exact body bytes."""

    kind: str
    logical_asset: str
    secid: str | None
    spread_id: str | None
    archive_code: str | None
    request_from: str | None
    request_till: str | None
    url: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SourceAudit:
    """Replay and byte-integrity result for a published bundle."""

    checks: dict[str, bool]
    counts: dict[str, int]


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _sidecar_sha(path: Path) -> str:
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"calendar-spread source sidecar missing: {sidecar}")
    return sidecar.read_text(encoding="utf-8-sig").split()[0].lower()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"calendar-spread source {label} must be a mapping")
    return value


def _project_path(relative_value: str, required_root: str) -> Path:
    relative = Path(relative_value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe calendar-spread path: {relative_value}")
    if relative.parts[0].lower() != required_root.lower():
        raise ValueError(f"calendar-spread path must start with {required_root}")
    return PROJECT_ROOT / relative


def load_protocol(
    config_path: Path = DEFAULT_CONFIG,
) -> CalendarSpreadSourceProtocol:
    """Verify the source-only seal without requesting or reading market history."""
    path = config_path.resolve()
    actual_sha = sha256_file(path)
    if _sidecar_sha(path) != actual_sha:
        raise ValueError("calendar-spread source protocol SHA-256 mismatch")
    payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("calendar-spread source protocol must be a YAML object")
    period = _mapping(payload.get("period"), "period")
    discovery = _mapping(payload.get("discovery"), "discovery")
    preflight = _mapping(payload.get("source_only_preflight"), "preflight")
    history_probe = _mapping(
        preflight.get("bounded_history_schema_probe"), "history probe"
    )
    archive_probe = _mapping(
        preflight.get("bounded_public_archive_probe"), "public archive probe"
    )
    official_sources = _mapping(payload.get("official_sources"), "official sources")
    archive_list_source = _mapping(
        official_sources.get("archive_spread_list"), "archive spread list source"
    )
    archive_source = _mapping(
        official_sources.get("public_archive"), "public archive source"
    )
    output = _mapping(payload.get("output"), "output")
    dependencies = _mapping(
        payload.get("implementation_dependencies"), "dependencies"
    )
    expected_counts = {
        str(key): int(value)
        for key, value in _mapping(
            discovery.get("exact_spread_counts"), "spread counts"
        ).items()
    }
    expected_missing = {
        str(key): tuple(str(item) for item in value)
        for key, value in _mapping(
            discovery.get("exact_missing_date_spreads"), "missing-date spreads"
        ).items()
    }
    expected_regular = {
        str(key): int(value)
        for key, value in _mapping(
            discovery.get("exact_regular_adjacent_counts"), "regular counts"
        ).items()
    }
    expected_date_matches = {
        str(key): int(value)
        for key, value in _mapping(
            discovery.get("exact_near_date_match_counts"), "date-match counts"
        ).items()
    }
    if (
        payload.get("protocol_id") != "moex_calendar_spread_source_v1"
        or payload.get("scope") != "source_only_no_returns_targets_or_pnl"
        or payload.get("sealed_before_bulk_history") is not True
        or payload.get("live_trading_allowed") is not False
        or date.fromisoformat(str(period["start"])) != SOURCE_START
        or date.fromisoformat(str(period["end"])) != SOURCE_END
        or date.fromisoformat(str(period["protected_from"])) != PROTECTED_FROM
        or tuple(discovery.get("logical_assets", ())) != ASSETS
        or expected_counts != EXPECTED_SPREAD_COUNTS
        or expected_missing != EXPECTED_MISSING_DATE_SPREADS
        or expected_regular != EXPECTED_REGULAR_ADJACENT_COUNTS
        or expected_date_matches != EXPECTED_NEAR_DATE_MATCH_COUNTS
        or discovery.get("history_board") != "RFUD"
        or discovery.get("spread_rule")
        != "exchange_listed_same_root_two_outright_codes_concatenated"
        or discovery.get("allow_manual_aliases") is not False
        or discovery.get("archive_code_rule")
        != "official_asset_code_plus_official_near_and_far_leg_names"
        or int(discovery["exact_archive_codes_resolved"])
        != sum(EXPECTED_SPREAD_COUNTS.values())
        or preflight.get("market_values_printed_or_persisted") is not False
        or preflight.get("returns_targets_or_pnl_observed") is not False
        or int(preflight["exact_dated_spreads"]) != sum(EXPECTED_SPREAD_COUNTS.values())
        or int(preflight["exact_missing_date_spreads"])
        != sum(len(value) for value in EXPECTED_MISSING_DATE_SPREADS.values())
        or int(preflight["exact_RFUD_board_segments_resolved"])
        != sum(EXPECTED_SPREAD_COUNTS.values())
        or int(preflight["exact_regular_adjacent_spreads"])
        != sum(EXPECTED_REGULAR_ADJACENT_COUNTS.values())
        or int(preflight["exact_near_date_matches"])
        != sum(EXPECTED_NEAR_DATE_MATCH_COUNTS.values())
        or history_probe.get("secid") != "MXZ4MXH5"
        or int(history_probe["bounded_history_rows_observed"]) != 6
        or {str(column).lower() for column in history_probe["columns_observed"]}
        != HISTORY_REQUIRED_COLUMNS | {"swaprate", "change", "qty", "shortname"}
        or archive_probe.get("archive_code") != "MIX-12.24-3.25"
        or int(archive_probe["raw_csv_rows_observed"]) != 71
        or date.fromisoformat(str(archive_probe["minimum_trade_date_observed"]))
        != date(2024, 9, 12)
        or date.fromisoformat(str(archive_probe["maximum_trade_date_observed"]))
        != date(2024, 12, 19)
        or int(archive_probe["protected_rows_observed"]) != 0
        or tuple(str(item) for item in archive_probe["exact_headers_observed"])
        != ARCHIVE_CSV_HEADERS
        or int(archive_probe["ordinary_ISS_rows_in_matching_bounded_probe"]) != 6
        or int(
            archive_probe[
                "ordinary_ISS_reported_trade_rows_in_matching_bounded_probe"
            ]
        )
        != 0
        or archive_list_source.get("endpoint") != ARCHIVE_LIST_URL
        or archive_source.get("export_event_target") != ARCHIVE_EXPORT_TARGET
        or tuple(str(item) for item in archive_source["exact_headers"])
        != ARCHIVE_CSV_HEADERS
        or date.fromisoformat(
            str(archive_source["full_response_must_not_contain_date_at_or_after"])
        )
        != PROTECTED_FROM
        or output.get("immutable") is not True
        or output.get("overwrite_allowed") is not False
        or tuple(output.get("artifacts", ()))
        != (
            "catalog.parquet",
            "iss_daily.parquet",
            "public_archive_daily.parquet",
            "coverage.parquet",
            "official_moex_responses.jsonl.gz",
            "manifest.json",
            "manifest.sha256",
        )
    ):
        raise ValueError("calendar-spread source protocol invariants drifted")
    if SOURCE_END >= PROTECTED_FROM:
        raise ValueError("calendar-spread source period reaches protected history")
    dependency_hashes: dict[str, str] = {}
    for relative, expected in dependencies.items():
        dependency_path = PROJECT_ROOT / str(relative)
        digest = str(expected).lower()
        if sha256_file(dependency_path) != digest:
            raise ValueError(f"calendar-spread dependency drift: {relative}")
        dependency_hashes[str(relative)] = digest
    output_directory = _project_path(str(output["directory"]), "data")
    return CalendarSpreadSourceProtocol(
        config_path=path,
        config_sha256=actual_sha,
        payload=payload,
        output_directory=output_directory,
        dependency_hashes=dependency_hashes,
    )


def _normalize_date(frame: pd.DataFrame, column: str) -> pd.Series:
    parsed = pd.to_datetime(frame[column], errors="raise")
    if parsed.isna().any():
        raise ValueError(f"missing calendar-spread date: {column}")
    return parsed.dt.normalize()


def _spread_pattern(asset: FuturesAssetSpec) -> re.Pattern[str]:
    prefix = re.escape(str(asset.security_prefix))
    month = f"[{MONTH_CODES}]"
    return re.compile(
        rf"^(?P<near>{prefix}{month}\d)(?P<far>{prefix}{month}\d)$",
        flags=re.IGNORECASE,
    )


def _archive_leg_label(value: object, asset_code: str) -> str:
    label = str(value).strip()
    match = re.fullmatch(rf"{re.escape(asset_code)}-(\d{{1,2}}\.\d{{2}})", label)
    if match is None:
        raise ValueError(f"invalid official archive leg label: {label}")
    month, year = match.group(1).split(".")
    if not 1 <= int(month) <= 12 or not 0 <= int(year) <= 99:
        raise ValueError(f"invalid official archive leg month/year: {label}")
    return match.group(1)


def discover_spreads(
    payload: dict[str, Any],
    asset: FuturesAssetSpec,
    source_start: date = SOURCE_START,
    source_end: date = SOURCE_END,
) -> pd.DataFrame:
    """Discover only adjacent same-root spread SECIDs and prove their two legs."""
    frame = iss._parse_iss_block(payload, "series", SERIES_REQUIRED_COLUMNS)
    output_columns = list(DISCOVERY_COLUMNS)
    if frame.empty:
        return pd.DataFrame(columns=output_columns)
    frame = frame.loc[frame["asset_code"].astype(str).eq(asset.asset_code)].copy()
    frame["secid"] = frame["secid"].astype("string")
    pattern = _spread_pattern(asset)
    spread_mask = frame["secid"].map(
        lambda value: pattern.fullmatch(str(value)) is not None
    )
    parsed_start = pd.to_datetime(frame["start_date"], errors="coerce").dt.normalize()
    parsed_expiration = pd.to_datetime(
        frame["expiration_date"], errors="coerce"
    ).dt.normalize()
    invalid_dates = spread_mask & (parsed_start.isna() | parsed_expiration.isna())
    invalid_secids = tuple(sorted(frame.loc[invalid_dates, "secid"].astype(str)))
    expected_invalid = (
        tuple(sorted(EXPECTED_MISSING_DATE_SPREADS[str(asset.logical_symbol)]))
        if (source_start, source_end) == (SOURCE_START, SOURCE_END)
        else invalid_secids
    )
    if invalid_secids != expected_invalid:
        raise ValueError(
            f"calendar-spread missing-date set drifted: {invalid_secids}"
        )
    frame["series_start"] = parsed_start
    frame["expiration"] = parsed_expiration
    period_mask = frame["expiration"].dt.date.between(source_start, source_end)
    selected = frame.loc[spread_mask & ~invalid_dates & period_mask].copy()
    if selected["secid"].duplicated().any():
        raise ValueError(f"duplicate calendar-spread SECID for {asset.logical_symbol}")
    outright = frame.set_index("secid", drop=False)
    records: list[dict[str, Any]] = []
    for row in selected.sort_values(["expiration", "secid"]).itertuples(index=False):
        match = pattern.fullmatch(str(row.secid))
        if match is None:
            raise AssertionError("selected spread no longer matches its closed regex")
        near_secid = match.group("near")
        far_secid = match.group("far")
        try:
            near = outright.loc[near_secid]
            far = outright.loc[far_secid]
        except KeyError as error:
            raise ValueError(f"spread leg missing from series: {row.secid}") from error
        if isinstance(near, pd.DataFrame) or isinstance(far, pd.DataFrame):
            raise ValueError(f"ambiguous spread leg metadata: {row.secid}")
        near_expiration = pd.Timestamp(near["expiration"])
        far_expiration = pd.Timestamp(far["expiration"])
        spread_last_trade = pd.Timestamp(row.expiration)
        near_archive_label = _archive_leg_label(near["name"], asset.asset_code)
        far_archive_label = _archive_leg_label(far["name"], asset.asset_code)
        archive_code = (
            f"{asset.asset_code}-{near_archive_label}-{far_archive_label}"
        )
        gap = int((far_expiration - near_expiration).days)
        if gap <= 0 or gap > 200:
            raise ValueError(f"invalid leg expiry order for spread: {row.secid}")
        month_gap = (
            (far_expiration.year - near_expiration.year) * 12
            + far_expiration.month
            - near_expiration.month
        )
        regular_adjacent = month_gap == (1 if asset.logical_symbol == "BR" else 3)
        spread_id = (
            f"{asset.logical_symbol}:{row.secid}:"
            f"{near_expiration.date().isoformat()}:"
            f"{far_expiration.date().isoformat()}"
        )
        records.append(
            {
                "spread_id": spread_id,
                "logical_asset": asset.logical_symbol,
                "asset_code": asset.asset_code,
                "secid": str(row.secid),
                "near_secid": near_secid,
                "far_secid": far_secid,
                "archive_code": archive_code,
                "series_start": pd.Timestamp(row.series_start),
                "spread_last_trade": spread_last_trade,
                "near_expiration": near_expiration,
                "far_expiration": far_expiration,
                "expiry_gap_days": gap,
                "near_expiration_matches_spread_last_trade": (
                    near_expiration == spread_last_trade
                ),
                "regular_adjacent_expiry": regular_adjacent,
            }
        )
    result = pd.DataFrame(records, columns=output_columns)
    if result["spread_id"].duplicated().any():
        raise ValueError("duplicate canonical calendar-spread identity")
    return result


def _numeric_preserving_missing(frame: pd.DataFrame, column: str) -> None:
    raw = frame[column]
    converted = pd.to_numeric(raw, errors="coerce")
    invalid = raw.notna() & converted.isna()
    if invalid.any():
        raise ValueError(f"invalid numeric calendar-spread field: {column}")
    frame[column] = converted


def parse_spread_history_page(
    payload: dict[str, Any],
    catalog_row: Mapping[str, Any],
) -> tuple[pd.DataFrame, Any]:
    """Parse signed spread prices while preserving inactive and zero-price rows."""
    frame = iss._parse_iss_block(payload, "history", HISTORY_REQUIRED_COLUMNS)
    cursor = parse_iss_page_cursor(payload, "history")
    if frame.empty:
        return pd.DataFrame(columns=ISS_DAILY_COLUMNS), cursor
    for column in (
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
    ):
        _numeric_preserving_missing(frame, column)
    for column in (
        "volume",
        "value",
        "numtrades",
        "openposition",
        "openpositionvalue",
    ):
        if (frame[column].dropna() < 0.0).any():
            raise ValueError(f"negative calendar-spread count/value: {column}")
    trade_date = _normalize_date(frame, "tradedate")
    if (frame["secid"].astype(str) != str(catalog_row["secid"])).any():
        raise ValueError("calendar-spread history returned another SECID")
    if (frame["boardid"].astype(str) != str(catalog_row["board_id"])).any():
        raise ValueError("calendar-spread history returned another board")
    history_asset = frame["assetcode"].astype("string").fillna(
        str(catalog_row["asset_code"])
    )
    if (history_asset != str(catalog_row["asset_code"])).any():
        raise ValueError("calendar-spread history returned another asset code")
    prices = frame[["open", "high", "low", "close"]]
    finite = np.isfinite(prices.fillna(0.0).to_numpy(dtype=float)).all(axis=1)
    complete = prices.notna().all(axis=1) & finite
    selected = frame.loc[complete]
    invalid_ohlc = (
        (selected["high"] < selected[["open", "close"]].max(axis=1))
        | (selected["low"] > selected[["open", "close"]].min(axis=1))
        | (selected["high"] < selected["low"])
    )
    if invalid_ohlc.any():
        raise ValueError("calendar-spread signed OHLC invariant failed")
    activity = (
        frame["volume"].fillna(0.0).gt(0.0)
        | frame["value"].fillna(0.0).gt(0.0)
        | frame["numtrades"].fillna(0.0).gt(0.0)
    )
    settlement = frame["settleprice"].notna() & np.isfinite(
        frame["settleprice"].fillna(0.0)
    )
    availability = (trade_date + pd.Timedelta(days=1)).dt.tz_localize(
        "Europe/Moscow",
        ambiguous="raise",
        nonexistent="raise",
    )
    output = pd.DataFrame(
        {
            "trade_date": trade_date,
            "available_at": availability,
            "spread_id": str(catalog_row["spread_id"]),
            "logical_asset": str(catalog_row["logical_asset"]),
            "asset_code": str(catalog_row["asset_code"]),
            "secid": frame["secid"].astype(str),
            "board_id": frame["boardid"].astype(str),
            "near_secid": str(catalog_row["near_secid"]),
            "far_secid": str(catalog_row["far_secid"]),
            "spread_last_trade": pd.Timestamp(catalog_row["spread_last_trade"]),
            "near_expiration": pd.Timestamp(catalog_row["near_expiration"]),
            "far_expiration": pd.Timestamp(catalog_row["far_expiration"]),
            "open": frame["open"],
            "high": frame["high"],
            "low": frame["low"],
            "close": frame["close"],
            "settle": frame["settleprice"],
            "waprice": frame["waprice"],
            "volume": frame["volume"],
            "value": frame["value"],
            "num_trades": frame["numtrades"],
            "open_interest": frame["openposition"],
            "open_interest_value": frame["openpositionvalue"],
            "reported_trade_activity": activity,
            "ohlc_complete": complete,
            "ohlc_missing_with_activity": activity & ~complete,
            "has_settlement": settlement,
        }
    )
    return output[list(ISS_DAILY_COLUMNS)], cursor


def _select_board(
    payload: dict[str, Any],
    catalog_row: Mapping[str, Any],
) -> dict[str, Any]:
    boards = iss.parse_futures_boards_payload(payload, preferred_board="RFUD")
    start = pd.Timestamp(catalog_row["series_start"])
    end = pd.Timestamp(catalog_row["spread_last_trade"])
    overlap = (boards["history_from"] <= end) & (boards["history_till"] >= start)
    selected = boards.loc[overlap]
    if len(selected) != 1:
        raise ValueError(
            f"expected one RFUD board for {catalog_row['spread_id']}, got {len(selected)}"
        )
    row = selected.iloc[0]
    return {
        "board_id": str(row["boardid"]),
        "board_history_from": pd.Timestamp(row["history_from"]),
        "board_history_till": pd.Timestamp(row["history_till"]),
    }


class _ArchiveFormParser(HTMLParser):
    """Extract successful controls from the one official ASP.NET archive form."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.form_count = 0
        self.form_action: str | None = None
        self.form_method: str | None = None
        self.fields: dict[str, str] = {}
        self.target_seen = False
        self._inside_form = False
        self._select_name: str | None = None
        self._first_option: str | None = None
        self._selected_option: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == "aspnetForm":
            self.form_count += 1
            self.form_action = attributes.get("action")
            self.form_method = attributes.get("method")
            self._inside_form = True
            return
        if not self._inside_form:
            return
        if tag == "a" and ARCHIVE_EXPORT_TARGET in str(attributes.get("href", "")):
            self.target_seen = True
            return
        if tag == "input":
            name = attributes.get("name")
            input_type = str(attributes.get("type") or "text").lower()
            excluded = {"submit", "button", "image", "file", "reset"}
            checkable = {"radio", "checkbox"}
            if (
                name
                and input_type not in excluded
                and (input_type not in checkable or "checked" in attributes)
            ):
                self.fields[name] = str(attributes.get("value") or "")
            return
        if tag == "select":
            self._select_name = attributes.get("name")
            self._first_option = None
            self._selected_option = None
            return
        if tag == "option" and self._select_name is not None:
            value = str(attributes.get("value") or "")
            if self._first_option is None:
                self._first_option = value
            if "selected" in attributes:
                self._selected_option = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "select" and self._select_name is not None:
            self.fields[self._select_name] = str(
                self._selected_option
                if self._selected_option is not None
                else self._first_option or ""
            )
            self._select_name = None
            self._first_option = None
            self._selected_option = None
            return
        if tag == "form" and self._inside_form:
            self._inside_form = False


def _archive_page_url(archive_code: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9.-]+", archive_code) is None:
        raise ValueError(f"unsafe official archive code: {archive_code}")
    return f"{ARCHIVE_PAGE_BASE}?code={quote(archive_code, safe='.-')}"


def parse_archive_form(
    content: bytes,
    *,
    asset_code: str,
    archive_code: str,
) -> dict[str, str]:
    """Reconstruct the official CSV postback without logging market values."""
    try:
        document = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("official archive page is not UTF-8") from error
    parser = _ArchiveFormParser()
    parser.feed(document)
    expected_action_suffix = f"archive-spreads.aspx?code={archive_code}"
    required = {
        "__VIEWSTATE",
        "__VIEWSTATEGENERATOR",
        ARCHIVE_BASE_FIELD,
        ARCHIVE_SPREAD_FIELD,
        ARCHIVE_BASE_STATE_FIELD,
        ARCHIVE_SPREAD_STATE_FIELD,
    }
    if (
        parser.form_count != 1
        or str(parser.form_method).lower() != "post"
        or not str(parser.form_action).endswith(expected_action_suffix)
        or not parser.target_seen
        or not required.issubset(parser.fields)
        or not parser.fields["__VIEWSTATE"]
        or not parser.fields["__VIEWSTATEGENERATOR"]
        or parser.fields[ARCHIVE_BASE_FIELD] != asset_code
        or parser.fields[ARCHIVE_SPREAD_FIELD] != archive_code
        or parser.fields[ARCHIVE_BASE_STATE_FIELD] != asset_code
        or parser.fields[ARCHIVE_SPREAD_STATE_FIELD] != archive_code
    ):
        raise ValueError(f"official archive form drifted for {archive_code}")
    fields = dict(parser.fields)
    fields["__EVENTTARGET"] = ARCHIVE_EXPORT_TARGET
    fields["__EVENTARGUMENT"] = ""
    return fields


def parse_archive_spread_list(payload: dict[str, Any]) -> tuple[str, ...]:
    """Return the exact unique archive-code list from the official web service."""
    raw_rows = payload.get("d")
    if not isinstance(raw_rows, list):
        raise ValueError("official archive spread list is not an array")
    values: list[str] = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise ValueError("official archive spread-list row is not an object")
        name = str(raw.get("name", "")).strip()
        value = str(raw.get("value", "")).strip()
        if not value or name != value or re.fullmatch(r"[A-Za-z0-9.-]+", value) is None:
            raise ValueError("official archive spread-list identity drifted")
        values.append(value)
    if len(values) != len(set(values)):
        raise ValueError("official archive spread list contains duplicates")
    return tuple(values)


def _numeric_archive_field(frame: pd.DataFrame, column: str) -> None:
    raw = frame[column].astype("string").str.strip().replace("", pd.NA)
    converted = pd.to_numeric(raw, errors="coerce")
    if (raw.notna() & converted.isna()).any():
        raise ValueError(f"invalid public-archive numeric field: {column}")
    finite = converted.dropna().map(np.isfinite)
    if not finite.all():
        raise ValueError(f"non-finite public-archive numeric field: {column}")
    frame[column] = converted


def parse_archive_csv(
    content: bytes,
    catalog_row: Mapping[str, Any],
    request_from: date,
    request_till: date,
) -> pd.DataFrame:
    """Parse exact Windows-1251 CSV labels and clip to the sealed source interval."""
    try:
        document = content.decode("cp1251").lstrip("\ufeff")
    except UnicodeDecodeError as error:
        raise ValueError("official archive CSV is not Windows-1251") from error
    reader = csv.DictReader(StringIO(document, newline=""))
    if tuple(reader.fieldnames or ()) != ARCHIVE_CSV_HEADERS:
        raise ValueError(f"official archive CSV header drifted: {reader.fieldnames}")
    rows = list(reader)
    if any(None in row or str(row.get("", "")).strip() for row in rows):
        raise ValueError("official archive CSV row width drifted")
    if not rows:
        return pd.DataFrame(columns=ARCHIVE_DAILY_COLUMNS)
    frame = pd.DataFrame(rows)
    trade_date = pd.to_datetime(
        frame["moment"],
        format="%m/%d/%Y %I:%M:%S %p",
        errors="raise",
    ).dt.normalize()
    if trade_date.duplicated().any():
        raise ValueError("official archive CSV contains duplicate dates")
    if trade_date.dt.date.ge(PROTECTED_FROM).any():
        raise ValueError("official archive CSV contains protected market values")
    archive_code = str(catalog_row["archive_code"])
    asset_code = str(catalog_row["asset_code"])
    if (
        not frame["small_name"].astype(str).eq(archive_code).all()
        or not frame["base_small_name"].astype(str).eq(asset_code).all()
        or frame["isin"].astype(str).str.strip().eq("").any()
        or frame["isin"].astype(str).nunique() != 1
    ):
        raise ValueError("official archive CSV identity drifted")
    for column in (
        "best_pk",
        "best_pr",
        "cena",
        "min_cena",
        "max_cena",
        "c_deal",
        "kol_cb",
        "sum_rub",
    ):
        _numeric_archive_field(frame, column)
    for column in ("c_deal", "kol_cb", "sum_rub"):
        if frame[column].dropna().lt(0.0).any():
            raise ValueError(f"negative public-archive activity field: {column}")
    range_complete = frame[["cena", "min_cena", "max_cena"]].notna().all(axis=1)
    range_ordered = range_complete & frame["min_cena"].le(frame["max_cena"])
    if (range_complete & ~range_ordered).any():
        raise ValueError("official archive signed daily range order failed")
    last_within_range = (
        range_complete
        & frame["cena"].ge(frame["min_cena"])
        & frame["cena"].le(frame["max_cena"])
    )
    last_outside_range = range_complete & ~last_within_range
    quote_complete = frame[["best_pk", "best_pr"]].notna().all(axis=1)
    quote_crossed = quote_complete & frame["best_pk"].gt(frame["best_pr"])
    activity = (
        frame["c_deal"].gt(0.0).fillna(False)
        | frame["kol_cb"].gt(0.0).fillna(False)
        | frame["sum_rub"].gt(0.0).fillna(False)
    )
    availability = (trade_date + pd.Timedelta(days=1)).dt.tz_localize(
        "Europe/Moscow",
        ambiguous="raise",
        nonexistent="raise",
    )
    inside_iss = trade_date.between(
        pd.Timestamp(catalog_row["iss_request_from"]),
        pd.Timestamp(catalog_row["iss_request_till"]),
    )
    inside_series = trade_date.between(
        pd.Timestamp(catalog_row["series_start"]),
        pd.Timestamp(catalog_row["spread_last_trade"]),
    )
    output = pd.DataFrame(
        {
            "trade_date": trade_date,
            "available_at": availability,
            "spread_id": str(catalog_row["spread_id"]),
            "logical_asset": str(catalog_row["logical_asset"]),
            "asset_code": asset_code,
            "secid": str(catalog_row["secid"]),
            "archive_code": archive_code,
            "archive_instrument_id": frame["isin"].astype(str),
            "near_secid": str(catalog_row["near_secid"]),
            "far_secid": str(catalog_row["far_secid"]),
            "spread_last_trade": pd.Timestamp(catalog_row["spread_last_trade"]),
            "near_expiration": pd.Timestamp(catalog_row["near_expiration"]),
            "far_expiration": pd.Timestamp(catalog_row["far_expiration"]),
            "last": frame["cena"],
            "bid": frame["best_pk"],
            "ask": frame["best_pr"],
            "high": frame["max_cena"],
            "low": frame["min_cena"],
            "amount": frame["kol_cb"],
            "volume": frame["sum_rub"],
            "num_trades": frame["c_deal"],
            "reported_trade_activity": activity,
            "range_complete": range_complete,
            "last_within_range": last_within_range,
            "last_outside_range": last_outside_range,
            "two_sided_quote_fields_complete": quote_complete,
            "closing_quote_crossed": quote_crossed,
            "inside_iss_request_interval": inside_iss,
            "inside_series_interval": inside_series,
        }
    )
    within = trade_date.dt.date.between(request_from, request_till)
    return output.loc[within, list(ARCHIVE_DAILY_COLUMNS)].reset_index(drop=True)


class OfficialMoexClient:
    """Small fail-closed HTTP client with injectable session for tests."""

    def __init__(
        self,
        session: requests.Session | None = None,
        sleeper: Any = time.sleep,
    ) -> None:
        self._owns_session = session is None
        self.session = session or requests.Session()
        self.sleeper = sleeper
        if hasattr(self.session, "headers"):
            self.session.headers.update({"User-Agent": USER_AGENT})

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> OfficialMoexClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    **kwargs,
                )
                response.raise_for_status()
                return response
            except requests.RequestException as error:
                last_error = error
                if attempt >= MAX_RETRIES:
                    break
                self.sleeper(0.25 * (2**attempt))
        raise RuntimeError(f"failed official MOEX request {url}: {last_error}") from last_error

    def get_json(self, url: str) -> dict[str, Any]:
        response = self._request("GET", url)
        try:
            payload = response.json()
        except ValueError as error:
            raise ValueError(f"official MOEX JSON decode failed: {url}") from error
        if not isinstance(payload, dict):
            raise ValueError("MOEX calendar-spread response is not an object")
        return payload

    def post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("POST", url, json=payload)
        try:
            decoded = response.json()
        except ValueError as error:
            raise ValueError(f"official MOEX JSON decode failed: {url}") from error
        if not isinstance(decoded, dict):
            raise ValueError("MOEX calendar-spread response is not an object")
        return decoded

    def get_bytes(self, url: str) -> tuple[bytes, dict[str, str]]:
        response = self._request("GET", url)
        return response.content, {
            "content_type": str(response.headers.get("Content-Type", "")),
            "content_disposition": str(
                response.headers.get("Content-Disposition", "")
            ),
        }

    def post_form_bytes(
        self,
        url: str,
        fields: Mapping[str, str],
    ) -> tuple[bytes, dict[str, str]]:
        response = self._request(
            "POST",
            url,
            data=dict(fields),
            headers={"Referer": url},
        )
        return response.content, {
            "content_type": str(response.headers.get("Content-Type", "")),
            "content_disposition": str(
                response.headers.get("Content-Disposition", "")
            ),
        }


def _raw_record(
    *,
    kind: str,
    asset: FuturesAssetSpec,
    url: str,
    payload: dict[str, Any],
    catalog_row: Mapping[str, Any] | None = None,
    request_from: date | None = None,
    request_till: date | None = None,
) -> RawRecord:
    return RawRecord(
        kind=kind,
        logical_asset=str(asset.logical_symbol),
        secid=None if catalog_row is None else str(catalog_row["secid"]),
        spread_id=None if catalog_row is None else str(catalog_row["spread_id"]),
        archive_code=(
            None if catalog_row is None else str(catalog_row["archive_code"])
        ),
        request_from=None if request_from is None else request_from.isoformat(),
        request_till=None if request_till is None else request_till.isoformat(),
        url=url,
        payload=payload,
    )


def _response_body_payload(
    content: bytes,
    headers: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "body_base64": base64.b64encode(content).decode("ascii"),
        "body_sha256": hashlib.sha256(content).hexdigest(),
        "bytes": len(content),
        "content_type": str(headers.get("content_type", "")),
        "content_disposition": str(headers.get("content_disposition", "")),
    }


def _response_body_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        content = base64.b64decode(str(payload["body_base64"]), validate=True)
    except (KeyError, ValueError) as error:
        raise ValueError("invalid encoded official archive response") from error
    if (
        len(content) != int(payload.get("bytes", -1))
        or hashlib.sha256(content).hexdigest() != str(payload.get("body_sha256", ""))
    ):
        raise ValueError("official archive response body hash drifted")
    return content


def _fetch_public_archive(
    client: OfficialMoexClient,
    asset: FuturesAssetSpec,
    catalog_row: Mapping[str, Any],
    request_from: date,
    request_till: date,
) -> tuple[pd.DataFrame, list[RawRecord]]:
    if request_till >= PROTECTED_FROM:
        raise ValueError("public archive request reaches protected period")
    archive_code = str(catalog_row["archive_code"])
    url = _archive_page_url(archive_code)
    page_content, page_headers = client.get_bytes(url)
    if not str(page_headers.get("content_type", "")).lower().startswith("text/html"):
        raise ValueError("official archive page content type drifted")
    fields = parse_archive_form(
        page_content,
        asset_code=str(asset.asset_code),
        archive_code=archive_code,
    )
    csv_content, csv_headers = client.post_form_bytes(url, fields)
    if not str(csv_headers.get("content_type", "")).lower().startswith(
        "application/csv"
    ) or "attachment" not in str(
        csv_headers.get("content_disposition", "")
    ).lower():
        raise ValueError("official archive CSV response headers drifted")
    frame = parse_archive_csv(
        csv_content,
        catalog_row,
        request_from,
        request_till,
    )
    records = [
        _raw_record(
            kind="archive_page",
            asset=asset,
            url=url,
            payload=_response_body_payload(page_content, page_headers),
            catalog_row=catalog_row,
            request_from=request_from,
            request_till=request_till,
        ),
        _raw_record(
            kind="archive_csv",
            asset=asset,
            url=url,
            payload=_response_body_payload(csv_content, csv_headers),
            catalog_row=catalog_row,
            request_from=request_from,
            request_till=request_till,
        ),
    ]
    return frame, records


def _fetch_history(
    client: OfficialMoexClient,
    asset: FuturesAssetSpec,
    catalog_row: Mapping[str, Any],
    request_from: date,
    request_till: date,
) -> tuple[pd.DataFrame, list[RawRecord]]:
    if request_till >= PROTECTED_FROM:
        raise ValueError("calendar-spread history request reaches protected period")
    frames: list[pd.DataFrame] = []
    records: list[RawRecord] = []
    expected_total: int | None = None
    offset = 0
    for _ in range(MAX_PAGES):
        url = iss.futures_daily_url(
            asset,
            str(catalog_row["secid"]),
            request_from,
            request_till,
            board_id=str(catalog_row["board_id"]),
            cursor_start=offset,
        )
        payload = client.get_json(url)
        raw_rows = iss._parse_iss_block(payload, "history", HISTORY_REQUIRED_COLUMNS)
        frame, cursor = parse_spread_history_page(payload, catalog_row)
        if cursor.index != offset:
            raise ValueError("calendar-spread history cursor index drifted")
        if expected_total is None:
            expected_total = cursor.total
        elif cursor.total != expected_total:
            raise ValueError("calendar-spread history cursor total drifted")
        expected_rows = min(cursor.page_size, max(cursor.total - cursor.index, 0))
        if len(raw_rows) != expected_rows or len(frame) != expected_rows:
            raise ValueError("truncated calendar-spread history page")
        records.append(
            _raw_record(
                kind="history",
                asset=asset,
                url=url,
                payload=payload,
                catalog_row=catalog_row,
                request_from=request_from,
                request_till=request_till,
            )
        )
        if not frame.empty:
            frames.append(frame)
        if cursor.next_index is None:
            break
        if cursor.next_index <= offset:
            raise ValueError("calendar-spread history cursor did not advance")
        offset = cursor.next_index
    else:
        raise ValueError("calendar-spread history exceeded maximum pages")
    combined = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=ISS_DAILY_COLUMNS)
    )
    if len(combined) != int(expected_total or 0):
        raise ValueError("calendar-spread history does not match cursor total")
    if not combined.empty:
        if combined.duplicated(["trade_date", "spread_id", "board_id"]).any():
            raise ValueError("duplicate calendar-spread history identity")
        dates = pd.to_datetime(combined["trade_date"], errors="raise").dt.date
        if dates.lt(request_from).any() or dates.gt(request_till).any():
            raise ValueError("calendar-spread response escaped requested bounds")
    return combined, records


def _raw_archive_bytes(records: list[RawRecord]) -> bytes:
    lines = [
        json.dumps(
            {
                "kind": record.kind,
                "logical_asset": record.logical_asset,
                "secid": record.secid,
                "spread_id": record.spread_id,
                "archive_code": record.archive_code,
                "request_from": record.request_from,
                "request_till": record.request_till,
                "url": record.url,
                "payload": record.payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for record in records
    ]
    return gzip.compress(("\n".join(lines) + "\n").encode("utf-8"), mtime=0)


def _read_raw_archive(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream if line.strip()]
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("calendar-spread raw archive contains a non-object")
    return records


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if rows is not None:
        record["rows"] = int(rows)
    return record


def _forbidden_columns(frame: pd.DataFrame) -> list[str]:
    return [
        column
        for column in frame.columns
        if any(fragment in str(column).lower() for fragment in FORBIDDEN_OUTPUT_FRAGMENTS)
    ]


def collect_calendar_spreads(
    protocol: CalendarSpreadSourceProtocol,
    client: OfficialMoexClient | None = None,
) -> Path:
    """Collect one immutable source bundle without computing any return or target."""
    final = protocol.output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"calendar-spread source output already exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    own_client = client is None
    active_client = client or OfficialMoexClient()
    raw_records: list[RawRecord] = []
    catalog_frames: list[pd.DataFrame] = []
    iss_daily_frames: list[pd.DataFrame] = []
    archive_daily_frames: list[pd.DataFrame] = []
    coverage_rows: list[dict[str, Any]] = []
    try:
        for logical_asset in ASSETS:
            asset = FuturesAssetSpec.from_symbol(logical_asset)
            archive_list_request = {
                "knownCategoryValues": f"Basis:{asset.asset_code};",
                "category": "Spread",
            }
            archive_list_payload = active_client.post_json(
                ARCHIVE_LIST_URL,
                archive_list_request,
            )
            archive_codes = set(parse_archive_spread_list(archive_list_payload))
            raw_records.append(
                _raw_record(
                    kind="archive_spread_list",
                    asset=asset,
                    url=ARCHIVE_LIST_URL,
                    payload=archive_list_payload,
                )
            )
            series_url = iss.futures_series_url(asset)
            series_payload = active_client.get_json(series_url)
            raw_records.append(
                _raw_record(
                    kind="series",
                    asset=asset,
                    url=series_url,
                    payload=series_payload,
                )
            )
            discovered = discover_spreads(series_payload, asset)
            expected_count = EXPECTED_SPREAD_COUNTS[logical_asset]
            if len(discovered) != expected_count:
                raise ValueError(
                    f"calendar-spread count drift for {logical_asset}: "
                    f"{len(discovered)} != {expected_count}"
                )
            regular_count = int(discovered["regular_adjacent_expiry"].sum())
            date_match_count = int(
                discovered["near_expiration_matches_spread_last_trade"].sum()
            )
            if regular_count != EXPECTED_REGULAR_ADJACENT_COUNTS[logical_asset]:
                raise ValueError(
                    f"regular calendar-spread count drift for {logical_asset}"
                )
            if date_match_count != EXPECTED_NEAR_DATE_MATCH_COUNTS[logical_asset]:
                raise ValueError(
                    f"calendar-spread near-date match drift for {logical_asset}"
                )
            missing_archive_codes = set(discovered["archive_code"]) - archive_codes
            if missing_archive_codes:
                raise ValueError(
                    f"official archive mapping missing for {logical_asset}: "
                    f"{sorted(missing_archive_codes)}"
                )
            enriched_rows: list[dict[str, Any]] = []
            for discovered_row in discovered.to_dict("records"):
                board_url = iss.futures_boards_url(str(discovered_row["secid"]))
                board_payload = active_client.get_json(board_url)
                raw_records.append(
                    _raw_record(
                        kind="boards",
                        asset=asset,
                        url=board_url,
                        payload=board_payload,
                        catalog_row=discovered_row,
                    )
                )
                board = _select_board(board_payload, discovered_row)
                row = {**discovered_row, **board}
                iss_request_from = max(
                    SOURCE_START,
                    pd.Timestamp(row["series_start"]).date(),
                    pd.Timestamp(row["board_history_from"]).date(),
                )
                iss_request_till = min(
                    SOURCE_END,
                    pd.Timestamp(row["spread_last_trade"]).date(),
                    pd.Timestamp(row["board_history_till"]).date(),
                )
                if iss_request_till < iss_request_from:
                    raise ValueError(
                        f"empty calendar-spread ISS interval: {row['spread_id']}"
                    )
                archive_request_from = SOURCE_START
                archive_request_till = SOURCE_END
                row["iss_request_from"] = pd.Timestamp(iss_request_from)
                row["iss_request_till"] = pd.Timestamp(iss_request_till)
                row["archive_request_from"] = pd.Timestamp(archive_request_from)
                row["archive_request_till"] = pd.Timestamp(archive_request_till)
                history, history_records = _fetch_history(
                    active_client,
                    asset,
                    row,
                    iss_request_from,
                    iss_request_till,
                )
                raw_records.extend(history_records)
                archive, archive_records = _fetch_public_archive(
                    active_client,
                    asset,
                    row,
                    archive_request_from,
                    archive_request_till,
                )
                raw_records.extend(archive_records)
                if not history.empty:
                    iss_daily_frames.append(history)
                if not archive.empty:
                    archive_daily_frames.append(archive)
                history_dates = set(pd.to_datetime(history["trade_date"]))
                archive_dates = set(pd.to_datetime(archive["trade_date"]))
                coverage_rows.append(
                    {
                        "spread_id": row["spread_id"],
                        "logical_asset": logical_asset,
                        "secid": row["secid"],
                        "archive_code": row["archive_code"],
                        "iss_request_from": pd.Timestamp(iss_request_from),
                        "iss_request_till": pd.Timestamp(iss_request_till),
                        "archive_request_from": pd.Timestamp(archive_request_from),
                        "archive_request_till": pd.Timestamp(archive_request_till),
                        "iss_rows": int(len(history)),
                        "iss_reported_trade_rows": int(
                            history["reported_trade_activity"].sum()
                        ),
                        "iss_settlement_rows": int(history["has_settlement"].sum()),
                        "archive_rows": int(len(archive)),
                        "archive_reported_trade_rows": int(
                            archive["reported_trade_activity"].sum()
                        ),
                        "overlap_rows": int(len(history_dates & archive_dates)),
                        "iss_only_rows": int(len(history_dates - archive_dates)),
                        "archive_only_rows": int(len(archive_dates - history_dates)),
                        "archive_outside_iss_interval_rows": int(
                            (~archive["inside_iss_request_interval"]).sum()
                        ),
                        "archive_outside_series_interval_rows": int(
                            (~archive["inside_series_interval"]).sum()
                        ),
                        "archive_last_outside_range_rows": int(
                            archive["last_outside_range"].sum()
                        ),
                        "archive_crossed_quote_rows": int(
                            archive["closing_quote_crossed"].sum()
                        ),
                        "first_iss_date": (
                            pd.NaT if history.empty else history["trade_date"].min()
                        ),
                        "last_iss_date": (
                            pd.NaT if history.empty else history["trade_date"].max()
                        ),
                        "first_archive_date": (
                            pd.NaT if archive.empty else archive["trade_date"].min()
                        ),
                        "last_archive_date": (
                            pd.NaT if archive.empty else archive["trade_date"].max()
                        ),
                    }
                )
                enriched_rows.append(row)
            catalog_frames.append(pd.DataFrame(enriched_rows, columns=CATALOG_COLUMNS))
        catalog = pd.concat(catalog_frames, ignore_index=True).sort_values(
            ["logical_asset", "near_expiration", "secid"], ignore_index=True
        )
        iss_daily = (
            pd.concat(iss_daily_frames, ignore_index=True).sort_values(
                ["trade_date", "logical_asset", "spread_id"], ignore_index=True
            )
            if iss_daily_frames
            else pd.DataFrame(columns=ISS_DAILY_COLUMNS)
        )
        archive_daily = (
            pd.concat(archive_daily_frames, ignore_index=True).sort_values(
                ["trade_date", "logical_asset", "spread_id"], ignore_index=True
            )
            if archive_daily_frames
            else pd.DataFrame(columns=ARCHIVE_DAILY_COLUMNS)
        )
        coverage = pd.DataFrame(coverage_rows, columns=COVERAGE_COLUMNS).sort_values(
            ["logical_asset", "iss_request_till", "secid"], ignore_index=True
        )
        if len(catalog) != sum(EXPECTED_SPREAD_COUNTS.values()):
            raise ValueError("calendar-spread total catalog count drifted")
        if any(
            _forbidden_columns(frame)
            for frame in (catalog, iss_daily, archive_daily, coverage)
        ):
            raise ValueError("calendar-spread source output contains outcome columns")
        for frame, identity in (
            (iss_daily, ["trade_date", "spread_id", "board_id"]),
            (archive_daily, ["trade_date", "spread_id"]),
        ):
            if frame.empty:
                continue
            maximum_date = pd.to_datetime(
                frame["trade_date"], errors="raise"
            ).max().date()
            if maximum_date >= PROTECTED_FROM:
                raise ValueError("calendar-spread output contains protected prices")
            if frame.duplicated(identity).any():
                raise ValueError("calendar-spread output contains duplicate identities")
        catalog_path = temporary / "catalog.parquet"
        iss_daily_path = temporary / "iss_daily.parquet"
        archive_daily_path = temporary / "public_archive_daily.parquet"
        coverage_path = temporary / "coverage.parquet"
        raw_path = temporary / "official_moex_responses.jsonl.gz"
        _write_parquet(catalog_path, catalog)
        _write_parquet(iss_daily_path, iss_daily)
        _write_parquet(archive_daily_path, archive_daily)
        _write_parquet(coverage_path, coverage)
        atomic_write_bytes(raw_path, _raw_archive_bytes(raw_records))
        artifacts = {
            "catalog": _artifact(catalog_path, len(catalog)),
            "iss_daily": _artifact(iss_daily_path, len(iss_daily)),
            "public_archive_daily": _artifact(
                archive_daily_path, len(archive_daily)
            ),
            "coverage": _artifact(coverage_path, len(coverage)),
            "raw": _artifact(raw_path, len(raw_records)),
        }
        manifest = {
            "bundle_id": "moex-calendar-spreads-current-vintage-2021-2025-v1",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "protocol_sha256": protocol.config_sha256,
            "implementation_sha256": protocol.dependency_hashes,
            "source": "official MOEX ISS and public calendar-spread archive",
            "source_only": True,
            "contains_returns_targets_labels_signals_equity_or_pnl": False,
            "live_trading_allowed": False,
            "redistribution_review_required": True,
            "period": {
                "start": SOURCE_START.isoformat(),
                "end": SOURCE_END.isoformat(),
                "protected_from": PROTECTED_FROM.isoformat(),
            },
            "counts": {
                "spreads": int(len(catalog)),
                "iss_daily_rows": int(len(iss_daily)),
                "public_archive_daily_rows": int(len(archive_daily)),
                "coverage_rows": int(len(coverage)),
                "raw_responses": int(len(raw_records)),
                "spreads_with_iss_history": int(coverage["iss_rows"].gt(0).sum()),
                "spreads_with_public_archive": int(
                    coverage["archive_rows"].gt(0).sum()
                ),
                "spreads_with_reported_trades": int(
                    coverage["archive_reported_trade_rows"].gt(0).sum()
                ),
                "iss_reported_trade_rows": int(
                    coverage["iss_reported_trade_rows"].sum()
                ),
                "public_archive_reported_trade_rows": int(
                    coverage["archive_reported_trade_rows"].sum()
                ),
                "iss_settlement_rows": int(
                    coverage["iss_settlement_rows"].sum()
                ),
                "overlap_rows": int(coverage["overlap_rows"].sum()),
                "iss_only_rows": int(coverage["iss_only_rows"].sum()),
                "public_archive_only_rows": int(
                    coverage["archive_only_rows"].sum()
                ),
                "public_archive_outside_iss_interval_rows": int(
                    coverage["archive_outside_iss_interval_rows"].sum()
                ),
                "public_archive_outside_series_interval_rows": int(
                    coverage["archive_outside_series_interval_rows"].sum()
                ),
                "public_archive_last_outside_range_rows": int(
                    coverage["archive_last_outside_range_rows"].sum()
                ),
                "public_archive_crossed_quote_rows": int(
                    coverage["archive_crossed_quote_rows"].sum()
                ),
                "by_asset": {
                    asset: int(catalog["logical_asset"].eq(asset).sum())
                    for asset in ASSETS
                },
                "regular_adjacent_by_asset": {
                    asset: int(
                        catalog.loc[
                            catalog["logical_asset"].eq(asset),
                            "regular_adjacent_expiry",
                        ].sum()
                    )
                    for asset in ASSETS
                },
                "near_date_match_by_asset": {
                    asset: int(
                        catalog.loc[
                            catalog["logical_asset"].eq(asset),
                            "near_expiration_matches_spread_last_trade",
                        ].sum()
                    )
                    for asset in ASSETS
                },
                "metadata_missing_date_spreads": {
                    asset: list(EXPECTED_MISSING_DATE_SPREADS[asset])
                    for asset in ASSETS
                },
            },
            "availability": {
                "rule": "trade_date_plus_one_calendar_day_00_00_Europe_Moscow",
                "same_day_use_forbidden": True,
            },
            "artifacts": artifacts,
            "limitations": protocol.payload["limitations"],
        }
        manifest_path = temporary / "manifest.json"
        write_json(manifest_path, manifest)
        sidecar_path = temporary / "manifest.sha256"
        sidecar_text = f"{sha256_file(manifest_path)}  manifest.json\n"
        atomic_write_bytes(sidecar_path, sidecar_text.encode("utf-8-sig"))
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    finally:
        if own_client:
            active_client.close()
    return final


def audit_bundle(protocol: CalendarSpreadSourceProtocol) -> SourceAudit:
    """Verify bytes, schemas, temporal bounds and replay both official sources."""
    root = protocol.output_directory.resolve()
    manifest_path = root / "manifest.json"
    sidecar_path = root / "manifest.sha256"
    if not manifest_path.is_file() or not sidecar_path.is_file():
        raise FileNotFoundError("calendar-spread source manifest or sidecar missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    declared_sha = sidecar_path.read_text(encoding="utf-8-sig").split()[0].lower()
    checks: dict[str, bool] = {
        "manifest_sha_exact": declared_sha == sha256_file(manifest_path),
        "protocol_sha_exact": manifest.get("protocol_sha256") == protocol.config_sha256,
        "source_only": manifest.get("source_only") is True,
        "outcome_columns_absent_declared": manifest.get(
            "contains_returns_targets_labels_signals_equity_or_pnl"
        )
        is False,
        "live_forbidden": manifest.get("live_trading_allowed") is False,
    }
    frames: dict[str, pd.DataFrame] = {}
    for name in ("catalog", "iss_daily", "public_archive_daily", "coverage"):
        declaration = manifest["artifacts"][name]
        path = root / declaration["file"]
        checks[f"{name}_bytes_exact"] = path.stat().st_size == int(declaration["bytes"])
        checks[f"{name}_sha_exact"] = sha256_file(path) == declaration["sha256"]
        checks[f"{name}_rows_exact"] = (
            pq.ParquetFile(path).metadata.num_rows == int(declaration["rows"])
        )
        frames[name] = pd.read_parquet(path)
        checks[f"{name}_outcome_columns_absent"] = not _forbidden_columns(frames[name])
    raw_declaration = manifest["artifacts"]["raw"]
    raw_path = root / raw_declaration["file"]
    checks["raw_bytes_exact"] = raw_path.stat().st_size == int(raw_declaration["bytes"])
    checks["raw_sha_exact"] = sha256_file(raw_path) == raw_declaration["sha256"]
    raw_records = _read_raw_archive(raw_path)
    checks["raw_count_exact"] = len(raw_records) == int(raw_declaration["rows"])
    catalog = frames["catalog"]
    iss_daily = frames["iss_daily"]
    archive_daily = frames["public_archive_daily"]
    coverage = frames["coverage"]
    checks["catalog_columns_exact"] = tuple(catalog.columns) == CATALOG_COLUMNS
    checks["iss_daily_columns_exact"] = (
        tuple(iss_daily.columns) == ISS_DAILY_COLUMNS
    )
    checks["public_archive_daily_columns_exact"] = (
        tuple(archive_daily.columns) == ARCHIVE_DAILY_COLUMNS
    )
    checks["coverage_columns_exact"] = tuple(coverage.columns) == COVERAGE_COLUMNS
    checks["catalog_count_exact"] = len(catalog) == sum(EXPECTED_SPREAD_COUNTS.values())
    checks["coverage_count_exact"] = len(coverage) == len(catalog)
    checks["catalog_asset_counts_exact"] = {
        asset: int(catalog["logical_asset"].eq(asset).sum()) for asset in ASSETS
    } == EXPECTED_SPREAD_COUNTS
    checks["catalog_regular_counts_exact"] = {
        asset: int(
            catalog.loc[
                catalog["logical_asset"].eq(asset), "regular_adjacent_expiry"
            ].sum()
        )
        for asset in ASSETS
    } == EXPECTED_REGULAR_ADJACENT_COUNTS
    checks["catalog_near_date_match_counts_exact"] = {
        asset: int(
            catalog.loc[
                catalog["logical_asset"].eq(asset),
                "near_expiration_matches_spread_last_trade",
            ].sum()
        )
        for asset in ASSETS
    } == EXPECTED_NEAR_DATE_MATCH_COUNTS
    checks["iss_daily_identity_unique"] = not iss_daily.duplicated(
        ["trade_date", "spread_id", "board_id"]
    ).any()
    checks["public_archive_daily_identity_unique"] = not archive_daily.duplicated(
        ["trade_date", "spread_id"]
    ).any()
    checks["iss_daily_before_protected"] = bool(
        iss_daily.empty
        or pd.to_datetime(iss_daily["trade_date"], errors="raise").max().date()
        < PROTECTED_FROM
    )
    checks["public_archive_daily_before_protected"] = bool(
        archive_daily.empty
        or pd.to_datetime(
            archive_daily["trade_date"], errors="raise"
        ).max().date()
        < PROTECTED_FROM
    )
    checks["iss_available_at_strictly_after_trade_date"] = bool(
        iss_daily.empty
        or (
            pd.to_datetime(iss_daily["available_at"], utc=True)
            > pd.to_datetime(iss_daily["trade_date"], utc=True)
        ).all()
    )
    checks["archive_available_at_strictly_after_trade_date"] = bool(
        archive_daily.empty
        or (
            pd.to_datetime(archive_daily["available_at"], utc=True)
            > pd.to_datetime(archive_daily["trade_date"], utc=True)
        ).all()
    )
    replay_iss_frames: list[pd.DataFrame] = []
    replay_archive_frames: list[pd.DataFrame] = []
    replay_catalog_frames: list[pd.DataFrame] = []
    replay_board_count = 0
    replay_archive_page_count = 0
    replay_archive_csv_count = 0
    replay_archive_lists: dict[str, set[str]] = {}
    catalog_index = catalog.set_index("spread_id", drop=False)
    for raw in raw_records:
        if raw.get("kind") == "series":
            asset = FuturesAssetSpec.from_symbol(str(raw["logical_asset"]))
            replay_catalog_frames.append(discover_spreads(raw["payload"], asset))
            continue
        if raw.get("kind") == "archive_spread_list":
            logical_asset = str(raw["logical_asset"])
            if logical_asset in replay_archive_lists:
                raise ValueError("duplicate raw public-archive spread list")
            replay_archive_lists[logical_asset] = set(
                parse_archive_spread_list(raw["payload"])
            )
            continue
        if raw.get("kind") == "boards":
            row = catalog_index.loc[str(raw["spread_id"])]
            if isinstance(row, pd.DataFrame):
                raise ValueError("ambiguous spread during board replay")
            board = _select_board(raw["payload"], row)
            replay_board_count += 1
            if any(pd.Timestamp(board[key]) != pd.Timestamp(row[key]) for key in (
                "board_history_from",
                "board_history_till",
            )) or str(board["board_id"]) != str(row["board_id"]):
                raise ValueError("calendar-spread board replay drifted")
            continue
        if raw.get("kind") == "history":
            spread_id = str(raw["spread_id"])
            row = catalog_index.loc[spread_id]
            if isinstance(row, pd.DataFrame):
                raise ValueError("ambiguous spread during raw replay")
            replay, _ = parse_spread_history_page(raw["payload"], row)
            if not replay.empty:
                replay_iss_frames.append(replay)
            continue
        spread_id = str(raw["spread_id"])
        if spread_id == "None" or spread_id not in catalog_index.index:
            raise ValueError("unknown spread in public-archive raw response")
        row = catalog_index.loc[spread_id]
        if isinstance(row, pd.DataFrame):
            raise ValueError("ambiguous spread during raw replay")
        if str(raw.get("archive_code")) != str(row["archive_code"]):
            raise ValueError("public-archive raw identity drifted")
        if raw.get("kind") == "archive_page":
            page = _response_body_bytes(raw["payload"])
            parse_archive_form(
                page,
                asset_code=str(row["asset_code"]),
                archive_code=str(row["archive_code"]),
            )
            replay_archive_page_count += 1
            continue
        if raw.get("kind") == "archive_csv":
            response = _response_body_bytes(raw["payload"])
            replay = parse_archive_csv(
                response,
                row,
                date.fromisoformat(str(raw["request_from"])),
                date.fromisoformat(str(raw["request_till"])),
            )
            if not replay.empty:
                replay_archive_frames.append(replay)
            replay_archive_csv_count += 1
            continue
        raise ValueError(f"unknown calendar-spread raw kind: {raw.get('kind')}")
    replayed_iss = (
        pd.concat(replay_iss_frames, ignore_index=True).sort_values(
            ["trade_date", "logical_asset", "spread_id"], ignore_index=True
        )
        if replay_iss_frames
        else pd.DataFrame(columns=ISS_DAILY_COLUMNS)
    )
    replayed_archive = (
        pd.concat(replay_archive_frames, ignore_index=True).sort_values(
            ["trade_date", "logical_asset", "spread_id"], ignore_index=True
        )
        if replay_archive_frames
        else pd.DataFrame(columns=ARCHIVE_DAILY_COLUMNS)
    )
    try:
        pd.testing.assert_frame_equal(
            replayed_iss.reset_index(drop=True),
            iss_daily.reset_index(drop=True),
            check_dtype=False,
            check_like=False,
        )
        iss_replay_exact = True
    except AssertionError:
        iss_replay_exact = False
    checks["raw_iss_history_replay_exact"] = iss_replay_exact
    try:
        pd.testing.assert_frame_equal(
            replayed_archive.reset_index(drop=True),
            archive_daily.reset_index(drop=True),
            check_dtype=False,
            check_like=False,
        )
        archive_replay_exact = True
    except AssertionError:
        archive_replay_exact = False
    checks["raw_public_archive_replay_exact"] = archive_replay_exact
    replay_catalog = pd.concat(replay_catalog_frames, ignore_index=True).sort_values(
        ["logical_asset", "near_expiration", "secid"], ignore_index=True
    )
    catalog_source_columns = list(DISCOVERY_COLUMNS)
    try:
        pd.testing.assert_frame_equal(
            replay_catalog[catalog_source_columns].reset_index(drop=True),
            catalog[catalog_source_columns].reset_index(drop=True),
            check_dtype=False,
            check_like=False,
        )
        catalog_replay_exact = True
    except AssertionError:
        catalog_replay_exact = False
    checks["raw_series_replay_exact"] = catalog_replay_exact
    checks["raw_boards_replay_exact"] = replay_board_count == len(catalog)
    checks["raw_archive_pages_exact"] = replay_archive_page_count == len(catalog)
    checks["raw_archive_csv_exact"] = replay_archive_csv_count == len(catalog)
    checks["raw_archive_lists_exact"] = set(replay_archive_lists) == set(ASSETS)
    checks["catalog_archive_codes_in_raw_lists"] = all(
        set(catalog.loc[catalog["logical_asset"].eq(asset), "archive_code"])
        <= replay_archive_lists.get(asset, set())
        for asset in ASSETS
    )
    if not all(checks.values()):
        raise ValueError(f"calendar-spread source audit failed: {checks}")
    return SourceAudit(
        checks=checks,
        counts={
            "spreads": int(len(catalog)),
            "iss_daily_rows": int(len(iss_daily)),
            "public_archive_daily_rows": int(len(archive_daily)),
            "raw_responses": int(len(raw_records)),
            "iss_reported_trade_rows": int(
                iss_daily["reported_trade_activity"].sum()
            ),
            "public_archive_reported_trade_rows": int(
                archive_daily["reported_trade_activity"].sum()
            ),
        },
    )


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
    output = collect_calendar_spreads(protocol)
    audit = audit_bundle(protocol)
    print(output)
    print(json.dumps({"checks": audit.checks, "counts": audit.counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
