"""Acquire dated Bank of Russia one-week banking-liquidity forecasts."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as wall_time
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CURRENT_ENDPOINT: Final[str] = "https://www.cbr.ru/statistics/pffl/"
ARCHIVE_ENDPOINT: Final[str] = "https://www.cbr.ru/archive/db/pffl/"
DEFINITIONS_URL: Final[str] = "https://www.cbr.ru/eng/statistics/pffl/"
PUBLICATION_SCHEDULE_EVIDENCE_URL: Final[str] = (
    "https://www.cbr.ru/eng/press/pr/?file=120516_104301eng_liq-ind.htm"
)
USER_AGREEMENT_URL: Final[str] = "https://www.cbr.ru/user_agreement/"
SOURCE_START: Final[date] = date(2017, 1, 1)
SOURCE_END: Final[date] = date(2025, 12, 31)
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
USER_AGENT: Final[str] = "market-lab-cbr-liquidity-forecast/1.0 (causal research)"
DEFAULT_MAX_WORKERS: Final[int] = 4
DEFAULT_OUTPUT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/info_radar/cbr-liquidity-forecast-releases-2017-2025-v1"
)
DEFAULT_STAGING: Final[Path] = DEFAULT_OUTPUT.with_name(f".{DEFAULT_OUTPUT.name}.staging")
_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
_CAPTION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'<div[^>]*class="[^"]*\btable-caption\b[^"]*\bgray\b[^"]*"[^>]*>'
    r"(?P<body>.*?)</div>",
    flags=re.IGNORECASE | re.DOTALL,
)
_THREAD_LOCAL = threading.local()


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
class Probe:
    """One requested historical publication page and its immutable response."""

    requested_date: date
    endpoint: str
    url: str
    fetched_at_utc: str
    content: bytes
    headers: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class WeekDiscovery:
    """The first valid regular weekly forecast found in one calendar week."""

    week_start: date
    attempts: tuple[Probe, ...]
    record: dict[str, object] | None
    admitted_probe: Probe | None


class _DataTableParser(HTMLParser):
    """Parse only CBR tables carrying the ``data`` CSS class."""

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


def _worker_session() -> requests.Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        _THREAD_LOCAL.session = session
    return session


def build_forecast_url(endpoint: str, publication_date: date) -> str:
    """Build a deterministic official query for one historical publication date."""
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"cbr.ru", "www.cbr.ru"}:
        raise ValueError("CBR endpoint escaped the official host")
    query = urlencode(
        {
            "UniDbQuery.DT": publication_date.strftime("%d.%m.%Y"),
            "UniDbQuery.Posted": "True",
        }
    )
    return f"{endpoint}?{query}"


def endpoint_for_date(value: date) -> tuple[str, str]:
    """Use the official 2012-2020 archive and the active 2021+ database."""
    if value <= date(2020, 12, 31):
        return ARCHIVE_ENDPOINT, "archive_2012_2020"
    return CURRENT_ENDPOINT, "current_2021_plus"


def conservative_available_at(publication_date: date) -> pd.Timestamp:
    """Admit a forecast only after the entire Moscow publication day has ended."""
    if publication_date < SOURCE_START or publication_date > SOURCE_END:
        raise ValueError("CBR forecast publication escaped the source interval")
    local = datetime.combine(publication_date, wall_time(23, 59, 59), tzinfo=MOSCOW)
    available = pd.Timestamp(local.astimezone(UTC))
    if available >= PROTECTED_FROM:
        raise ValueError("CBR forecast availability crossed the protected boundary")
    return available


def _number(value: str, label: str, *, optional: bool = False) -> float | None:
    normalized = value.replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    if not normalized or not any(character.isdigit() for character in normalized):
        if optional:
            return None
        raise ValueError(f"missing required CBR forecast number: {label}")
    try:
        parsed = float(normalized)
    except ValueError as error:
        raise ValueError(f"invalid CBR forecast number {label}: {value!r}") from error
    if not pd.notna(parsed):
        raise ValueError(f"non-finite CBR forecast number: {label}")
    return parsed


def _date(value: str) -> date:
    return datetime.strptime(value, "%d.%m.%Y").date()


def parse_forecast_html(
    content: bytes,
    *,
    requested_date: date,
    endpoint_schema: str,
    source_url: str,
    retrieved_at_utc: str,
) -> dict[str, object] | None:
    """Normalize a dated forecast, returning ``None`` for CBR's invalid-date fallback."""
    try:
        html = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("CBR forecast HTML is not UTF-8") from error
    parser = _DataTableParser()
    parser.feed(html)
    if len(parser.tables) != 1:
        raise ValueError("CBR forecast page must contain exactly one data table")
    rows = parser.tables[0]
    if len(rows) != 5 or any(len(row) != 2 for row in rows):
        raise ValueError("CBR forecast table must contain five two-cell rows")
    publication_dates = _DATE_PATTERN.findall(rows[-1][0])
    if len(publication_dates) != 1:
        raise ValueError("CBR forecast table does not identify one publication date")
    publication_date = _date(publication_dates[0])
    if publication_date != requested_date:
        return None
    caption_matches = _CAPTION_PATTERN.findall(html)
    if len(caption_matches) != 1:
        raise ValueError("CBR forecast page must contain one forecast-period caption")
    period_dates = _DATE_PATTERN.findall(caption_matches[0])
    if len(period_dates) != 2:
        raise ValueError("CBR forecast caption must contain period start and end")
    period_start, period_end = (_date(value) for value in period_dates)
    if period_start < publication_date or period_end < period_start:
        raise ValueError("CBR forecast period is not forward ordered")

    digest = sha256_bytes(content)
    common: dict[str, object] = {
        "publication_date": pd.Timestamp(publication_date),
        "available_at": conservative_available_at(publication_date),
        "forecast_period_start": pd.Timestamp(period_start),
        "forecast_period_end": pd.Timestamp(period_end),
        "source_url": source_url,
        "source_schema": endpoint_schema,
        "raw_sha256": digest,
        "retrieved_at_utc": retrieved_at_utc,
        "provider": "Bank of Russia",
        "release_keyed_historical_record": True,
    }
    if endpoint_schema == "archive_2012_2020":
        common.update(
            {
                "correspondent_accounts_change_bln_rub": None,
                "cash_change_bln_rub": _number(rows[0][1], "cash"),
                "government_accounts_change_bln_rub": _number(rows[1][1], "government"),
                "required_reserves_change_bln_rub": _number(rows[2][1], "reserves"),
                "cbr_operations_balance_bln_rub": _number(rows[3][1], "cbr_operations"),
                "one_week_auction_limit_bln_rub": _number(
                    rows[4][1], "auction_limit", optional=True
                ),
            }
        )
    elif endpoint_schema == "current_2021_plus":
        common.update(
            {
                "correspondent_accounts_change_bln_rub": _number(
                    rows[0][1], "correspondent_accounts"
                ),
                "cash_change_bln_rub": _number(rows[1][1], "cash"),
                "government_accounts_change_bln_rub": _number(rows[2][1], "government"),
                "required_reserves_change_bln_rub": None,
                "cbr_operations_balance_bln_rub": _number(rows[3][1], "cbr_operations"),
                "one_week_auction_limit_bln_rub": _number(
                    rows[4][1], "auction_limit", optional=True
                ),
            }
        )
    else:
        raise ValueError(f"unknown CBR forecast schema: {endpoint_schema}")
    return common


def _request_bytes(
    url: str,
    *,
    session: SessionLike | None = None,
    attempts: int = 5,
) -> tuple[bytes, Mapping[str, str]]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"cbr.ru", "www.cbr.ru"}:
        raise ValueError("CBR request escaped the official host")
    network_session: SessionLike = session or _worker_session()
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
                raise ValueError("empty CBR forecast response")
            return bytes(response.content), response.headers
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(min(8.0, 0.25 * (2**attempt)))
    raise RuntimeError(f"CBR forecast request failed: {url}: {last_error}") from last_error


def _cached_probe(
    requested_date: date,
    staging: Path,
    *,
    session: SessionLike | None,
    fetched_at_utc: str | None,
) -> Probe:
    endpoint, endpoint_schema = endpoint_for_date(requested_date)
    url = build_forecast_url(endpoint, requested_date)
    stem = requested_date.isoformat()
    data_path = staging / "downloads" / f"{stem}.html"
    metadata_path = staging / "metadata" / f"{stem}.json"
    if data_path.exists() != metadata_path.exists():
        raise ValueError(f"partial CBR forecast staging artifact: {stem}")
    if data_path.exists():
        content = data_path.read_bytes()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        if (
            metadata.get("url") != url
            or metadata.get("sha256") != sha256_bytes(content)
            or int(metadata.get("bytes", -1)) != len(content)
        ):
            raise ValueError(f"invalid CBR forecast staging artifact: {stem}")
        return Probe(
            requested_date=requested_date,
            endpoint=endpoint_schema,
            url=url,
            fetched_at_utc=str(metadata["fetched_at_utc"]),
            content=content,
            headers=metadata.get("headers", {}),
        )
    content, headers = _request_bytes(url, session=session)
    fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    selected_headers = {
        name: headers.get(name)
        for name in ("Last-Modified", "Content-Type", "ETag")
        if headers.get(name) is not None
    }
    metadata = {
        "requested_date": requested_date.isoformat(),
        "endpoint_schema": endpoint_schema,
        "url": url,
        "fetched_at_utc": fetched_at,
        "bytes": len(content),
        "sha256": sha256_bytes(content),
        "headers": selected_headers,
    }
    atomic_write_bytes(data_path, content)
    write_json(metadata_path, metadata)
    return Probe(
        requested_date=requested_date,
        endpoint=endpoint_schema,
        url=url,
        fetched_at_utc=fetched_at,
        content=content,
        headers=selected_headers,
    )


def _candidate_dates(week_start: date) -> tuple[date, ...]:
    """Try regular Tuesday first, then documented holiday-shift weekdays."""
    if week_start.weekday() != 0:
        raise ValueError("week_start must be Monday")
    return tuple(week_start + timedelta(days=offset) for offset in (1, 2, 0, 3, 4))


def _discover_week(
    week_start: date,
    staging: Path,
    *,
    session: SessionLike | None,
    fetched_at_utc: str | None,
) -> WeekDiscovery:
    attempts: list[Probe] = []
    for candidate in _candidate_dates(week_start):
        if candidate < SOURCE_START or candidate > SOURCE_END:
            continue
        probe = _cached_probe(
            candidate,
            staging,
            session=session,
            fetched_at_utc=fetched_at_utc,
        )
        attempts.append(probe)
        record = parse_forecast_html(
            probe.content,
            requested_date=candidate,
            endpoint_schema=probe.endpoint,
            source_url=probe.url,
            retrieved_at_utc=probe.fetched_at_utc,
        )
        if record is not None:
            return WeekDiscovery(week_start, tuple(attempts), record, probe)
    return WeekDiscovery(week_start, tuple(attempts), None, None)


def _week_starts(start_date: date, end_date: date) -> tuple[date, ...]:
    first = start_date + timedelta(days=(-start_date.weekday()) % 7)
    last = end_date - timedelta(days=end_date.weekday())
    count = ((last - first).days // 7) + 1
    return tuple(first + timedelta(days=7 * index) for index in range(count))


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def download_cbr_liquidity_forecasts(
    output_directory: Path = DEFAULT_OUTPUT,
    *,
    staging_directory: Path = DEFAULT_STAGING,
    session: SessionLike | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    fetched_at_utc: str | None = None,
    week_starts: Sequence[date] | None = None,
) -> Path:
    """Write an immutable source-only bundle of official dated weekly forecasts."""
    final = output_directory.resolve()
    staging = staging_directory.resolve()
    if final.exists():
        raise FileExistsError(f"CBR liquidity forecast output already exists: {final}")
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    weeks = (
        tuple(week_starts)
        if week_starts is not None
        else _week_starts(SOURCE_START, SOURCE_END)
    )
    if not weeks or any(value.weekday() != 0 for value in weeks):
        raise ValueError("CBR forecast discovery requires Monday week starts")
    final.parent.mkdir(parents=True, exist_ok=True)
    (staging / "downloads").mkdir(parents=True, exist_ok=True)
    (staging / "metadata").mkdir(parents=True, exist_ok=True)
    plan = {
        "schema_version": 1,
        "source_start": SOURCE_START.isoformat(),
        "source_end": SOURCE_END.isoformat(),
        "week_starts": [value.isoformat() for value in weeks],
        "candidate_order": [1, 2, 0, 3, 4],
        "current_endpoint": CURRENT_ENDPOINT,
        "archive_endpoint": ARCHIVE_ENDPOINT,
    }
    plan_path = staging / "plan.json"
    if plan_path.exists():
        if json.loads(plan_path.read_text(encoding="utf-8-sig")) != plan:
            raise ValueError("CBR forecast resumable discovery plan changed")
    else:
        write_json(plan_path, plan)

    def discover(value: date) -> WeekDiscovery:
        return _discover_week(
            value,
            staging,
            session=session,
            fetched_at_utc=fetched_at_utc,
        )

    if session is not None or max_workers == 1:
        discoveries = [discover(value) for value in weeks]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            discoveries = list(executor.map(discover, weeks))
    records = [item.record for item in discoveries if item.record is not None]
    if not records:
        raise ValueError("CBR forecast discovery found no dated releases")
    frame = pd.DataFrame(records).sort_values("publication_date", ignore_index=True)
    if frame["publication_date"].duplicated().any():
        raise ValueError("CBR forecast bundle contains duplicate publication dates")
    if frame["available_at"].ge(PROTECTED_FROM).any():
        raise ValueError("CBR forecast bundle crossed the protected boundary")
    gaps = frame["publication_date"].diff().dt.days.dropna()
    if not gaps.empty and int(gaps.max()) > 28:
        raise ValueError("CBR forecast release history contains an unexplained gap over 28 days")
    nullable = (
        "correspondent_accounts_change_bln_rub",
        "cash_change_bln_rub",
        "government_accounts_change_bln_rub",
        "required_reserves_change_bln_rub",
        "cbr_operations_balance_bln_rub",
        "one_week_auction_limit_bln_rub",
    )
    for column in nullable:
        frame[column] = pd.array(frame[column], dtype="Float64")

    coverage_rows: list[dict[str, object]] = []
    raw_records: list[bytes] = []
    for item in discoveries:
        probe = item.admitted_probe
        coverage_rows.append(
            {
                "week_start": pd.Timestamp(item.week_start),
                "publication_date": item.record["publication_date"] if item.record else pd.NaT,
                "forecast_period_start": (
                    item.record["forecast_period_start"] if item.record else pd.NaT
                ),
                "forecast_period_end": (
                    item.record["forecast_period_end"] if item.record else pd.NaT
                ),
                "found": item.record is not None,
                "attempt_count": len(item.attempts),
                "requested_dates": json.dumps(
                    [attempt.requested_date.isoformat() for attempt in item.attempts]
                ),
                "admitted_raw_sha256": sha256_bytes(probe.content) if probe else None,
            }
        )
        if probe is not None and item.record is not None:
            raw_records.append(
                json.dumps(
                    {
                        "publication_date": pd.Timestamp(
                            item.record["publication_date"]
                        ).date().isoformat(),
                        "source_url": probe.url,
                        "endpoint_schema": probe.endpoint,
                        "retrieved_at_utc": probe.fetched_at_utc,
                        "headers": dict(probe.headers),
                        "bytes": len(probe.content),
                        "sha256": sha256_bytes(probe.content),
                        "content_encoding": "base64",
                        "content": base64.b64encode(probe.content).decode("ascii"),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
    coverage = pd.DataFrame(coverage_rows).sort_values("week_start", ignore_index=True)
    request_count = sum(len(item.attempts) for item in discoveries)
    fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        data_path = temporary / "cbr_liquidity_forecasts.parquet"
        coverage_path = temporary / "coverage.parquet"
        raw_path = temporary / "official_cbr_pffl_releases.jsonl.gz"
        _atomic_parquet(data_path, frame)
        _atomic_parquet(coverage_path, coverage)
        atomic_write_bytes(
            raw_path,
            gzip.compress(b"\n".join(raw_records) + b"\n", compresslevel=6, mtime=0),
        )
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-cbr-liquidity-forecast-releases-2017-2025-v1",
            "provider": "Bank of Russia",
            "source_name": "Forecast of banking-sector liquidity factors for one-week auctions",
            "current_endpoint": CURRENT_ENDPOINT,
            "archive_endpoint": ARCHIVE_ENDPOINT,
            "definitions_url": DEFINITIONS_URL,
            "publication_schedule_evidence_url": PUBLICATION_SCHEDULE_EVIDENCE_URL,
            "user_agreement_url": USER_AGREEMENT_URL,
            "fetched_at_utc": fetched_at,
            "request_count": request_count,
            "calendar_week_count": len(discoveries),
            "release_count": len(frame),
            "missing_calendar_week_count": int((~coverage["found"]).sum()),
            "request_bounds": {
                "publication_from": SOURCE_START.isoformat(),
                "publication_through": SOURCE_END.isoformat(),
                "protected_from_utc": PROTECTED_FROM.isoformat(),
            },
            "temporal_semantics": {
                "publication_date": "dated CBR forecast/auction record selected by the query",
                "forecast_period": "future period printed on that dated record",
                "available_at": "23:59:59 Europe/Moscow on the publication date",
                "admissible_join": "available_at less than or equal to decision_at",
                "release_keyed_historical_record": True,
                "original_historical_response_bytes_available": False,
                "historical_content_immutability_cryptographically_proved": False,
                "development_backtest_admissible": True,
                "independent_confirmation_without_forward_vintage_collection": False,
                "contains_prices_returns_targets_labels_or_pnl": False,
                "last_modified_used_for_availability": False,
            },
            "source_quality": {
                "regular_weekly_query_with_holiday_fallback": True,
                "maximum_release_gap_days": int(gaps.max()) if not gaps.empty else 0,
                "forecast_government_component_includes_minfin_fx_operations": True,
                "forecast_values_are_not_realized_liquidity_outcomes": True,
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
                    "minimum_publication_date": frame["publication_date"].min().date().isoformat(),
                    "maximum_publication_date": frame["publication_date"].max().date().isoformat(),
                    "maximum_available_at": frame["available_at"].max().isoformat(),
                },
                "coverage": {
                    "path": coverage_path.name,
                    "bytes": coverage_path.stat().st_size,
                    "sha256": sha256_file(coverage_path),
                    "rows": len(coverage),
                },
                "raw_releases": {
                    "path": raw_path.name,
                    "bytes": raw_path.stat().st_size,
                    "sha256": sha256_file(raw_path),
                    "records": len(raw_records),
                },
            },
        }
        manifest_identity = sha256_bytes(_canonical_json(manifest_core))
        manifest_path = temporary / "manifest.json"
        write_json(
            manifest_path,
            {**manifest_core, "manifest_payload_sha256": manifest_identity},
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
    parser.add_argument("--staging-directory", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    arguments = parser.parse_args()
    print(
        download_cbr_liquidity_forecasts(
            arguments.output_directory,
            staging_directory=arguments.staging_directory,
            max_workers=arguments.max_workers,
        )
    )


if __name__ == "__main__":
    main()
