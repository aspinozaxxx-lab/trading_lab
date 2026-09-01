"""Acquire current-vintage Bank of Russia daily banking-liquidity factors."""

from __future__ import annotations

import argparse
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
from datetime import time as wall_time
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CURRENT_ENDPOINT: Final[str] = "https://www.cbr.ru/statistics/flikvid/"
DEFINITIONS_URL: Final[str] = "https://www.cbr.ru/statistics/flikvid/definitions/"
PUBLICATION_SCHEDULE_EVIDENCE_URL: Final[str] = (
    "https://www.cbr.ru/eng/press/pr/?file=120516_104301eng_liq-ind.htm"
)
USER_AGREEMENT_URL: Final[str] = "https://www.cbr.ru/user_agreement/"
SOURCE_START: Final[date] = date(2021, 1, 1)
SOURCE_END: Final[date] = date(2025, 12, 31)
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
USER_AGENT: Final[str] = "market-lab-cbr-liquidity-factors/1.0 (causal research)"
EXPECTED_RAW_ROWS: Final[int] = 1239
DEFAULT_OUTPUT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/info_radar/cbr-liquidity-factors-current-vintage-2021-2025-v1"
)
_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\d{2}\.\d{2}\.\d{4}")
_VALUE_COLUMNS: Final[tuple[str, ...]] = (
    "cash_change_bln_rub",
    "government_accounts_change_bln_rub",
    "government_domestic_debt_change_bln_rub",
    "treasury_deposits_change_bln_rub",
    "treasury_repo_change_bln_rub",
    "minfin_fx_operations_bln_rub",
    "cbr_fx_operations_bln_rub",
    "cbr_liquidity_operations_bln_rub",
)


class ResponseLike(Protocol):
    """Minimal requests-compatible response used by production and tests."""

    content: bytes
    headers: Mapping[str, str]

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    """Minimal requests-compatible session used by production and tests."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> ResponseLike: ...


@dataclass(frozen=True, slots=True)
class LiquidityFactorParse:
    """Normalized admitted rows plus transparent current-vintage coverage facts."""

    frame: pd.DataFrame
    raw_row_count: int
    excluded_without_pre_boundary_publication: int
    maximum_observation_gap_days: int


class _DataTableParser(HTMLParser):
    """Parse only top-level CBR tables carrying the ``data`` CSS class."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            if self._table is not None:
                self._depth += 1
            elif "data" in set((attributes.get("class") or "").split()):
                self._table = []
                self._depth = 1
            return
        if self._table is None or self._depth != 1:
            return
        if tag == "tr":
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._table is None:
            return
        if tag in {"th", "td"} and self._cell is not None:
            value = " ".join("".join(self._cell).split())
            if self._row is not None:
                self._row.append(value)
            self._cell = None
        elif tag == "tr" and self._row is not None and self._depth == 1:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table":
            self._depth -= 1
            if self._depth == 0:
                self.tables.append(self._table)
                self._table = None


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def build_liquidity_factors_url(
    start_date: date = SOURCE_START,
    end_date: date = SOURCE_END,
) -> str:
    """Build one deterministic official historical-table request."""
    parsed = urlparse(CURRENT_ENDPOINT)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"cbr.ru", "www.cbr.ru"}:
        raise ValueError("CBR liquidity endpoint escaped the official host")
    if start_date < SOURCE_START or end_date > SOURCE_END or end_date < start_date:
        raise ValueError("CBR liquidity request escaped the source interval")
    query = urlencode(
        {
            "UniDbQuery.From": start_date.strftime("%d.%m.%Y"),
            "UniDbQuery.Posted": "True",
            "UniDbQuery.To": end_date.strftime("%d.%m.%Y"),
        }
    )
    return f"{CURRENT_ENDPOINT}?{query}"


def conservative_available_at(publication_date: date) -> pd.Timestamp:
    """Use 10:31 Moscow after the official 'before 10:30' publication deadline."""
    local = datetime.combine(publication_date, wall_time(10, 31), tzinfo=MOSCOW)
    available = pd.Timestamp(local.astimezone(UTC))
    if available >= PROTECTED_FROM:
        raise ValueError("CBR liquidity availability crossed the protected boundary")
    return available


def _number(value: str, label: str) -> float:
    normalized = value.replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    try:
        parsed = float(normalized)
    except ValueError as error:
        raise ValueError(f"invalid CBR liquidity number {label}: {value!r}") from error
    if not np.isfinite(parsed):
        raise ValueError(f"non-finite CBR liquidity number: {label}")
    return parsed


def parse_liquidity_factors_html(
    content: bytes,
    *,
    source_url: str,
    retrieved_at_utc: str,
    source_start: date = SOURCE_START,
    source_end: date = SOURCE_END,
) -> LiquidityFactorParse:
    """Normalize the table and infer each row's next-working-day publication time."""
    try:
        html = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("CBR liquidity HTML is not UTF-8") from error
    parser = _DataTableParser()
    parser.feed(html)
    if len(parser.tables) != 1:
        raise ValueError("CBR liquidity page must contain exactly one data table")
    dated_rows: list[list[str]] = []
    for row in parser.tables[0]:
        if row and _DATE_PATTERN.fullmatch(row[0]):
            if len(row) != 9:
                raise ValueError("CBR liquidity data row must contain nine cells")
            dated_rows.append(row)
    if len(dated_rows) < 2:
        raise ValueError("CBR liquidity page contains fewer than two dated rows")

    records: list[dict[str, object]] = []
    for row in dated_rows:
        observation = datetime.strptime(row[0], "%d.%m.%Y").date()
        if observation < source_start or observation > source_end:
            raise ValueError("CBR liquidity row escaped the requested interval")
        record: dict[str, object] = {"observation_date": pd.Timestamp(observation)}
        for column, value in zip(_VALUE_COLUMNS, row[1:], strict=True):
            record[column] = _number(value, column)
        records.append(record)
    raw = pd.DataFrame(records).sort_values(
        "observation_date", kind="mergesort", ignore_index=True
    )
    if raw["observation_date"].duplicated().any():
        raise ValueError("CBR liquidity table contains duplicate observation dates")
    if raw["observation_date"].min().date() < source_start or raw[
        "observation_date"
    ].max().date() != source_end:
        raise ValueError("CBR liquidity table boundary drifted")
    gaps = raw["observation_date"].diff().dt.days.dropna()
    maximum_gap = int(gaps.max()) if not gaps.empty else 0
    if maximum_gap > 14:
        raise ValueError("CBR liquidity history has an unexplained gap over 14 days")

    raw["publication_date"] = raw["observation_date"].shift(-1)
    eligible = raw["publication_date"].notna()
    eligible &= raw["publication_date"].dt.tz_localize(MOSCOW).dt.tz_convert("UTC").lt(
        PROTECTED_FROM
    )
    admitted = raw.loc[eligible].copy()
    admitted["available_at"] = admitted["publication_date"].map(
        lambda value: conservative_available_at(pd.Timestamp(value).date())
    )
    digest = sha256_bytes(content)
    admitted["source_url"] = source_url
    admitted["raw_sha256"] = digest
    admitted["retrieved_at_utc"] = retrieved_at_utc
    admitted["provider"] = "Bank of Russia"
    admitted["current_vintage_historical_record"] = True
    admitted["original_publication_bytes_available"] = False
    admitted["historical_values_may_be_revised"] = True
    ordered = [
        "observation_date",
        "publication_date",
        "available_at",
        *_VALUE_COLUMNS,
        "source_url",
        "raw_sha256",
        "retrieved_at_utc",
        "provider",
        "current_vintage_historical_record",
        "original_publication_bytes_available",
        "historical_values_may_be_revised",
    ]
    admitted = admitted.loc[:, ordered].reset_index(drop=True)
    return LiquidityFactorParse(
        frame=admitted,
        raw_row_count=len(raw),
        excluded_without_pre_boundary_publication=int((~eligible).sum()),
        maximum_observation_gap_days=maximum_gap,
    )


def _request_bytes(
    url: str,
    *,
    session: SessionLike | None = None,
    attempts: int = 5,
) -> tuple[bytes, Mapping[str, str]]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"cbr.ru", "www.cbr.ru"}:
        raise ValueError("CBR liquidity request escaped the official host")
    network_session: SessionLike = session or requests.Session()
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = network_session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=60.0,
            )
            response.raise_for_status()
            if not response.content:
                raise ValueError("empty CBR liquidity response")
            return bytes(response.content), response.headers
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(min(8.0, 0.25 * (2**attempt)))
    raise RuntimeError(f"CBR liquidity request failed: {url}: {last_error}") from last_error


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def download_cbr_liquidity_factors(
    output_directory: Path = DEFAULT_OUTPUT,
    *,
    session: SessionLike | None = None,
    fetched_at_utc: str | None = None,
    expected_raw_rows: int = EXPECTED_RAW_ROWS,
) -> Path:
    """Write one immutable source-only bundle; never overwrite an existing bundle."""
    final = output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"CBR liquidity factors output already exists: {final}")
    url = build_liquidity_factors_url()
    content, headers = _request_bytes(url, session=session)
    fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    parsed = parse_liquidity_factors_html(
        content,
        source_url=url,
        retrieved_at_utc=fetched_at,
    )
    if parsed.raw_row_count != expected_raw_rows:
        raise ValueError(
            f"CBR liquidity raw row count drifted: {parsed.raw_row_count} != {expected_raw_rows}"
        )
    frame = parsed.frame
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        data_path = temporary / "cbr_liquidity_factors.parquet"
        raw_path = temporary / "official_cbr_liquidity_factors_current_vintage.html.gz"
        _atomic_parquet(data_path, frame)
        atomic_write_bytes(raw_path, gzip.compress(content, compresslevel=6, mtime=0))
        selected_headers = {
            name: headers.get(name)
            for name in ("Last-Modified", "Content-Type", "ETag")
            if headers.get(name) is not None
        }
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-cbr-liquidity-factors-current-vintage-2021-2025-v1",
            "provider": "Bank of Russia",
            "source_name": "Factors affecting banking-sector liquidity",
            "source_url": url,
            "definitions_url": DEFINITIONS_URL,
            "publication_schedule_evidence_url": PUBLICATION_SCHEDULE_EVIDENCE_URL,
            "user_agreement_url": USER_AGREEMENT_URL,
            "fetched_at_utc": fetched_at,
            "response_headers": selected_headers,
            "request_bounds": {
                "observation_from": SOURCE_START.isoformat(),
                "observation_through": SOURCE_END.isoformat(),
                "protected_from_utc": PROTECTED_FROM.isoformat(),
            },
            "coverage": {
                "raw_dated_rows": parsed.raw_row_count,
                "admitted_rows": len(frame),
                "excluded_without_pre_boundary_publication": (
                    parsed.excluded_without_pre_boundary_publication
                ),
                "minimum_observation_date": frame["observation_date"].min().date().isoformat(),
                "maximum_observation_date": frame["observation_date"].max().date().isoformat(),
                "maximum_publication_date": frame["publication_date"].max().date().isoformat(),
                "maximum_available_at": frame["available_at"].max().isoformat(),
                "maximum_observation_gap_days": parsed.maximum_observation_gap_days,
            },
            "temporal_semantics": {
                "observation_date": "working day whose liquidity factors are reported",
                "publication_date": "next dated CBR working-day row inferred from the table",
                "available_at": "10:31 Europe/Moscow on inferred publication date",
                "publication_evidence": (
                    "previous working-day information published daily before 10:30"
                ),
                "admissible_join": "available_at less than or equal to decision_at",
                "current_vintage_historical_record": True,
                "original_historical_response_bytes_available": False,
                "historical_content_immutability_cryptographically_proved": False,
                "historical_values_may_be_revised": True,
                "development_backtest_admissible": True,
                "independent_confirmation_without_forward_vintage_collection": False,
                "contains_prices_returns_targets_labels_or_pnl": False,
                "last_modified_used_for_availability": False,
            },
            "sign_semantics": {
                "minfin_fx_positive": "purchase of foreign currency on the domestic FX market",
                "minfin_fx_negative": "sale of foreign currency on the domestic FX market",
            },
            "rights": {
                "official_user_agreement_requires_link_when_quoting": True,
                "raw_redistribution_allowed": False,
                "raw_redistribution_requires_separate_legal_review": True,
            },
            "artifacts": {
                "processed": {
                    "path": data_path.name,
                    "bytes": data_path.stat().st_size,
                    "sha256": sha256_file(data_path),
                    "rows": len(frame),
                    "columns": frame.columns.tolist(),
                },
                "raw_current_vintage": {
                    "path": raw_path.name,
                    "bytes": raw_path.stat().st_size,
                    "sha256": sha256_file(raw_path),
                    "uncompressed_bytes": len(content),
                    "uncompressed_sha256": sha256_bytes(content),
                },
            },
        }
        manifest_path = temporary / "manifest.json"
        write_json(
            manifest_path,
            {
                **manifest_core,
                "manifest_payload_sha256": sha256_bytes(_canonical_json(manifest_core)),
            },
        )
        manifest_sha = sha256_file(manifest_path)
        atomic_write_bytes(
            temporary / "manifest.sha256",
            f"{manifest_sha}  manifest.json\n".encode("utf-8-sig"),
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    print(download_cbr_liquidity_factors(arguments.output_directory))


if __name__ == "__main__":
    main()
