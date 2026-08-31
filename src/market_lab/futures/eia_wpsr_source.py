"""Acquire release-specific, target-free EIA WPSR Table 1 vintages."""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from datetime import time as wall_time
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
ARCHIVE_INDEX_URL: Final[str] = "https://www.eia.gov/petroleum/supply/weekly/archive/"
COPYRIGHT_URL: Final[str] = "https://www.eia.gov/about/copyrights_reuse.php"
SCHEDULE_URL: Final[str] = "https://www.eia.gov/petroleum/supply/weekly/schedule.php"
SOURCE_START: Final[date] = date(2012, 1, 1)
# The 2025-12-31 issue is deliberately excluded: end-of-release-day in New York is 2026 UTC.
SOURCE_END: Final[date] = date(2025, 12, 30)
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
EASTERN: Final[ZoneInfo] = ZoneInfo("America/New_York")
USER_AGENT: Final[str] = "market-lab-eia-wpsr-source/1.0 (causal research)"
DEFAULT_MAX_WORKERS: Final[int] = 4
DEFAULT_OUTPUT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/info_radar/eia-wpsr-table1-original-vintages-2012-2025-v2"
)
DEFAULT_STAGING: Final[Path] = DEFAULT_OUTPUT.with_name(f".{DEFAULT_OUTPUT.name}.staging")
TABLE_NAME: Final[str] = "WPSR Table 1: U.S. Petroleum Balance Sheet"
MISSING_NUMERIC_TOKENS: Final[frozenset[str]] = frozenset(
    {"", "-", "--", "NA", "N/A", "W", "–", "—", "– –"}
)
_ISSUE_PATH = re.compile(
    r"^/petroleum/supply/weekly/archive/(?P<year>20\d{2})/"
    r"(?P<slug>20\d{2}_\d{2}_\d{2})/wpsr_(?P=slug)\.php$"
)
_LINE_ITEM = re.compile(r"^\((?P<number>\d+)\)\s*(?P<label>.+?)\s*$")
_THREAD_LOCAL = threading.local()


class ResponseLike(Protocol):
    """Minimal requests-compatible binary response."""

    content: bytes
    headers: Mapping[str, str]

    def raise_for_status(self) -> None: ...


class SessionLike(Protocol):
    """Minimal requests-compatible session."""

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> ResponseLike: ...


@dataclass(frozen=True, slots=True)
class Release:
    """One issue linked by the official WPSR archive index."""

    release_date: date
    issue_url: str
    table1_url: str

    @property
    def slug(self) -> str:
        return self.release_date.strftime("%Y_%m_%d")


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.append(href)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
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


def _request_bytes(
    url: str,
    *,
    session: SessionLike | None = None,
    attempts: int = 6,
) -> tuple[bytes, Mapping[str, str]]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "www.eia.gov":
        raise ValueError(f"EIA request escaped the official host: {url}")
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
                raise ValueError("empty EIA response")
            return response.content, response.headers
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(min(8.0, 0.25 * (2**attempt)))
    raise RuntimeError(f"EIA request failed: {url}: {last_error}") from last_error


def discover_releases(index_html: bytes) -> tuple[Release, ...]:
    """Parse only release-specific issue links inside the sealed date range."""
    parser = _AnchorParser()
    parser.feed(index_html.decode("utf-8-sig", errors="strict"))
    by_date: dict[date, Release] = {}
    for href in parser.hrefs:
        issue_url = urljoin(ARCHIVE_INDEX_URL, href)
        parsed = urlparse(issue_url)
        if parsed.scheme != "https" or parsed.netloc.lower() != "www.eia.gov":
            continue
        match = _ISSUE_PATH.fullmatch(parsed.path)
        if match is None:
            continue
        release_date = datetime.strptime(match.group("slug"), "%Y_%m_%d").date()
        if release_date.year != int(match.group("year")):
            raise ValueError("EIA archive issue year and path year disagree")
        if release_date < SOURCE_START or release_date > SOURCE_END:
            continue
        canonical_issue = (
            f"https://www.eia.gov{parsed.path}"
        )
        release = Release(
            release_date=release_date,
            issue_url=canonical_issue,
            table1_url=urljoin(canonical_issue, "csv/table1.csv"),
        )
        previous = by_date.get(release_date)
        if previous is not None and previous != release:
            raise ValueError(f"conflicting EIA issue links for {release_date}")
        by_date[release_date] = release
    if not by_date:
        raise ValueError("official EIA archive index contains no bounded WPSR releases")
    return tuple(by_date[key] for key in sorted(by_date))


def conservative_available_at(release_date: date) -> pd.Timestamp:
    """Use end-of-release-day ET, later than all stated Table 1 publication times."""
    if release_date < SOURCE_START or release_date > SOURCE_END:
        raise ValueError("EIA release date escaped the sealed source interval")
    local = datetime.combine(release_date, wall_time(23, 59, 59), tzinfo=EASTERN)
    available = pd.Timestamp(local.astimezone(UTC))
    if available >= PROTECTED_FROM:
        raise ValueError("conservative EIA availability crosses the protected boundary")
    return available


def _parse_eia_date(value: str) -> pd.Timestamp:
    parsed = pd.to_datetime(value.strip(), format="mixed", errors="raise")
    if parsed.tzinfo is not None:
        raise ValueError("EIA table date unexpectedly includes a timezone")
    return parsed.normalize()


def _numeric(value: str) -> float | None:
    normalized = value.replace("\xa0", " ").strip()
    if normalized.upper() in MISSING_NUMERIC_TOKENS:
        return None
    try:
        return float(normalized.replace(",", ""))
    except ValueError as error:
        raise ValueError(f"unknown EIA numeric token: {value!r}") from error


def _normalized_row(
    *,
    release: Release,
    data_week_ending: pd.Timestamp,
    previous_week_ending: pd.Timestamp,
    year_ago_week_ending: pd.Timestamp,
    row_ordinal: int,
    section: str,
    item_number: int | None,
    item: str,
    unit: str,
    current_raw: str,
    previous_raw: str,
    change_raw: str,
    year_ago_raw: str,
    raw_sha256: str,
    retrieved_at_utc: str,
) -> dict[str, object]:
    return {
        "release_date": pd.Timestamp(release.release_date),
        "available_at": conservative_available_at(release.release_date),
        "data_week_ending": data_week_ending,
        "previous_week_ending": previous_week_ending,
        "year_ago_week_ending": year_ago_week_ending,
        "row_ordinal": row_ordinal,
        "section": section,
        "item_number": item_number,
        "item": item,
        "unit": unit,
        "current_value": _numeric(current_raw),
        "previous_value": _numeric(previous_raw),
        "reported_weekly_change": _numeric(change_raw),
        "year_ago_value": _numeric(year_ago_raw),
        "current_raw": current_raw,
        "previous_raw": previous_raw,
        "reported_weekly_change_raw": change_raw,
        "year_ago_raw": year_ago_raw,
        "issue_url": release.issue_url,
        "source_url": release.table1_url,
        "raw_sha256": raw_sha256,
        "retrieved_at_utc": retrieved_at_utc,
        "provider": "U.S. Energy Information Administration",
        "source_table": TABLE_NAME,
        "release_specific_archive": True,
    }


def normalize_table1(
    content: bytes,
    release: Release,
    *,
    retrieved_at_utc: str,
) -> pd.DataFrame:
    """Normalize weekly stock and balance-sheet rows without prices or outcomes."""
    rows = list(csv.reader(io.StringIO(content.decode("cp1252", errors="strict"))))
    while rows and (not rows[-1] or rows[-1][0].strip("\x1a ") == ""):
        rows.pop()
    if len(rows) < 3 or len(rows[0]) < 8 or rows[0][0].strip() != "STUB_1":
        raise ValueError(f"malformed EIA Table 1 for {release.release_date}")
    data_week_ending = _parse_eia_date(rows[0][1])
    previous_week_ending = _parse_eia_date(rows[0][2])
    year_ago_week_ending = _parse_eia_date(rows[0][5])
    if data_week_ending.date() >= release.release_date:
        raise ValueError("EIA data week must end before its issue release date")
    if previous_week_ending >= data_week_ending or year_ago_week_ending >= data_week_ending:
        raise ValueError("EIA comparison weeks must predate the current data week")
    balance_header_indices = [
        index
        for index, row in enumerate(rows)
        if len(row) >= 2 and row[0].strip() == "STUB_1" and row[1].strip() == "STUB_2"
    ]
    if len(balance_header_indices) != 1:
        raise ValueError("EIA Table 1 must contain exactly one balance-sheet header")
    balance_header = balance_header_indices[0]
    if balance_header <= 1:
        raise ValueError("EIA Table 1 stock section is empty")
    balance_dates = tuple(_parse_eia_date(rows[balance_header][index]) for index in (2, 3, 5))
    if balance_dates != (data_week_ending, previous_week_ending, year_ago_week_ending):
        raise ValueError("EIA stock and balance-sheet headers disagree on comparison weeks")
    digest = sha256_bytes(content)
    output_rows: list[dict[str, object]] = []
    for row_ordinal, row in enumerate(rows[1:balance_header], start=1):
        if len(row) < 8 or not row[0].strip():
            raise ValueError("malformed EIA Table 1 stock row")
        output_rows.append(
            _normalized_row(
                release=release,
                data_week_ending=data_week_ending,
                previous_week_ending=previous_week_ending,
                year_ago_week_ending=year_ago_week_ending,
                row_ordinal=row_ordinal,
                section="Stocks",
                item_number=None,
                item=row[0].strip(),
                unit="million_barrels",
                current_raw=row[1],
                previous_raw=row[2],
                change_raw=row[3],
                year_ago_raw=row[5],
                raw_sha256=digest,
                retrieved_at_utc=retrieved_at_utc,
            )
        )
    for row_ordinal, row in enumerate(rows[balance_header + 1 :], start=balance_header + 1):
        if not row or row[0].strip("\x1a ") == "":
            continue
        if len(row) < 7:
            raise ValueError("malformed EIA Table 1 balance-sheet row")
        line = _LINE_ITEM.fullmatch(row[1].strip())
        if line is None:
            raise ValueError(f"unknown EIA Table 1 line item: {row[1]!r}")
        output_rows.append(
            _normalized_row(
                release=release,
                data_week_ending=data_week_ending,
                previous_week_ending=previous_week_ending,
                year_ago_week_ending=year_ago_week_ending,
                row_ordinal=row_ordinal,
                section=row[0].strip(),
                item_number=int(line.group("number")),
                item=line.group("label"),
                unit="thousand_barrels_per_day",
                current_raw=row[2],
                previous_raw=row[3],
                change_raw=row[4],
                year_ago_raw=row[5],
                raw_sha256=digest,
                retrieved_at_utc=retrieved_at_utc,
            )
        )
    output = pd.DataFrame(output_rows)
    if output.empty or output.duplicated(["release_date", "row_ordinal"]).any():
        raise ValueError("EIA Table 1 normalized rows are empty or duplicated")
    for column in (
        "current_value",
        "previous_value",
        "reported_weekly_change",
        "year_ago_value",
    ):
        output[column] = pd.array(output[column], dtype="Float64")
    output["item_number"] = pd.array(output["item_number"], dtype="Int64")
    return output


def classify_release_admissibility(coverage: pd.DataFrame) -> pd.DataFrame:
    """Exclude stale/non-increasing archive issues while preserving their raw evidence."""
    required = {"release_date", "data_week_ending", "sha256"}
    if missing := required - set(coverage.columns):
        raise ValueError(f"EIA coverage lacks admission fields: {sorted(missing)}")
    output = coverage.sort_values("release_date", kind="mergesort", ignore_index=True).copy()
    output["admissible"] = True
    output["exclusion_reason"] = pd.Series(pd.NA, index=output.index, dtype="string")
    last_admissible_week: pd.Timestamp | None = None
    last_admissible_hash: str | None = None
    for index, row in output.iterrows():
        data_week = pd.Timestamp(row["data_week_ending"])
        raw_hash = str(row["sha256"])
        if last_admissible_week is not None and data_week <= last_admissible_week:
            output.at[index, "admissible"] = False
            if data_week == last_admissible_week and raw_hash == last_admissible_hash:
                reason = "duplicate_stale_archive_file"
            else:
                reason = "non_increasing_data_week"
            output.at[index, "exclusion_reason"] = reason
            continue
        last_admissible_week = data_week
        last_admissible_hash = raw_hash
    return output


def revision_chain_audit(frame: pd.DataFrame) -> dict[str, int | float]:
    """Count release-to-release revisions without rewriting either publication vintage."""
    ordered = frame.sort_values(
        ["section", "item", "data_week_ending", "release_date"], kind="mergesort"
    ).copy()
    grouped = ordered.groupby(["section", "item"], sort=False, dropna=False)
    prior_week = grouped["data_week_ending"].shift()
    prior_current = grouped["current_value"].shift()
    comparable = (
        ordered["data_week_ending"].sub(prior_week).eq(pd.Timedelta(days=7))
        & ordered["previous_value"].notna()
        & prior_current.notna()
    )
    differences = ordered.loc[comparable, "previous_value"].astype(float).sub(
        prior_current.loc[comparable].astype(float)
    ).abs()
    return {
        "comparable_previous_vintage_values": int(comparable.sum()),
        "exact_matches": int(differences.eq(0.0).sum()),
        "revised_or_reclassified_values": int(differences.gt(0.0).sum()),
        "maximum_absolute_revision": float(differences.max()) if not differences.empty else 0.0,
    }


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _stage_release(
    release: Release,
    downloads: Path,
    metadata_directory: Path,
    *,
    session: SessionLike | None,
    fetched_at_utc: str | None,
) -> dict[str, object]:
    data_path = downloads / f"{release.slug}.csv"
    metadata_path = metadata_directory / f"{release.slug}.json"
    if data_path.exists() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        if (
            metadata.get("source_url") != release.table1_url
            or metadata.get("sha256") != sha256_file(data_path)
            or metadata.get("bytes") != data_path.stat().st_size
        ):
            raise ValueError(f"invalid resumable EIA staging artifact: {release.slug}")
        return metadata
    if data_path.exists() != metadata_path.exists():
        raise ValueError(f"partial resumable EIA staging artifact: {release.slug}")
    content, headers = _request_bytes(release.table1_url, session=session)
    retrieved_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata = {
        "release_date": release.release_date.isoformat(),
        "issue_url": release.issue_url,
        "source_url": release.table1_url,
        "retrieved_at_utc": retrieved_at,
        "last_modified": headers.get("Last-Modified"),
        "content_type": headers.get("Content-Type"),
        "bytes": len(content),
        "sha256": sha256_bytes(content),
    }
    atomic_write_bytes(data_path, content)
    write_json(metadata_path, metadata)
    return metadata


def _load_staged_release(
    release: Release,
    downloads: Path,
    metadata_directory: Path,
) -> tuple[bytes, dict[str, object]]:
    data_path = downloads / f"{release.slug}.csv"
    metadata_path = metadata_directory / f"{release.slug}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    content = data_path.read_bytes()
    if metadata["sha256"] != sha256_bytes(content) or metadata["bytes"] != len(content):
        raise ValueError(f"EIA staging hash mismatch: {release.slug}")
    return content, metadata


def download_eia_wpsr_source(
    output_directory: Path = DEFAULT_OUTPUT,
    *,
    staging_directory: Path = DEFAULT_STAGING,
    session: SessionLike | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    fetched_at_utc: str | None = None,
) -> Path:
    """Write an immutable, resumable bundle of official release-specific Table 1 files."""
    final = output_directory.resolve()
    staging = staging_directory.resolve()
    if final.exists():
        raise FileExistsError(f"EIA WPSR output already exists: {final}")
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    final.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)
    downloads = staging / "downloads"
    metadata_directory = staging / "metadata"
    downloads.mkdir(exist_ok=True)
    metadata_directory.mkdir(exist_ok=True)

    index_content, index_headers = _request_bytes(ARCHIVE_INDEX_URL, session=session)
    releases = discover_releases(index_content)
    plan = {
        "schema_version": 1,
        "archive_index_url": ARCHIVE_INDEX_URL,
        "archive_index_sha256": sha256_bytes(index_content),
        "source_start": SOURCE_START.isoformat(),
        "source_end": SOURCE_END.isoformat(),
        "releases": [
            {**asdict(release), "release_date": release.release_date.isoformat()}
            for release in releases
        ],
    }
    plan_path = staging / "plan.json"
    if plan_path.exists():
        existing = json.loads(plan_path.read_text(encoding="utf-8-sig"))
        if existing != plan:
            raise ValueError("official EIA archive index changed during resumable acquisition")
    else:
        write_json(plan_path, plan)
        atomic_write_bytes(staging / "archive_index.html", index_content)

    def stage(release: Release) -> dict[str, object]:
        return _stage_release(
            release,
            downloads,
            metadata_directory,
            session=session,
            fetched_at_utc=fetched_at_utc,
        )

    if session is not None or max_workers == 1:
        metadata_records = [stage(release) for release in releases]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            metadata_records = list(executor.map(stage, releases))
    if len(metadata_records) != len(releases):
        raise ValueError("incomplete EIA WPSR acquisition")

    normalized_parts: list[pd.DataFrame] = []
    coverage_rows: list[dict[str, object]] = []
    raw_records: list[bytes] = []
    for release in releases:
        content, metadata = _load_staged_release(release, downloads, metadata_directory)
        normalized = normalize_table1(
            content,
            release,
            retrieved_at_utc=str(metadata["retrieved_at_utc"]),
        )
        normalized_parts.append(normalized)
        raw_records.append(
            json.dumps(
                {
                    **metadata,
                    "content_encoding": "base64",
                    "content": base64.b64encode(content).decode("ascii"),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        coverage_rows.append(
            {
                **metadata,
                "available_at": conservative_available_at(release.release_date),
                "data_week_ending": normalized["data_week_ending"].iat[0],
                "normalized_rows": len(normalized),
                "missing_current_values": int(normalized["current_value"].isna().sum()),
                "missing_reported_weekly_changes": int(
                    normalized["reported_weekly_change"].isna().sum()
                ),
            }
        )
    combined = pd.concat(normalized_parts, ignore_index=True)
    coverage = classify_release_admissibility(pd.DataFrame(coverage_rows))
    admitted_dates = set(coverage.loc[coverage["admissible"], "release_date"].astype(str))
    combined = combined.loc[combined["release_date"].astype(str).isin(admitted_dates)].reset_index(
        drop=True
    )
    if combined["release_date"].max() > pd.Timestamp(SOURCE_END):
        raise ValueError("normalized EIA data escaped the source boundary")
    if combined["available_at"].max() >= PROTECTED_FROM:
        raise ValueError("normalized EIA availability crossed the protected boundary")
    if combined.duplicated(["release_date", "row_ordinal"]).any():
        raise ValueError("normalized EIA bundle contains duplicate release rows")

    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        data_path = temporary / "eia_wpsr_table1.parquet"
        coverage_path = temporary / "coverage.parquet"
        raw_path = temporary / "official_eia_wpsr_table1_releases.jsonl.gz"
        index_path = temporary / "official_eia_wpsr_archive_index.html.gz"
        _atomic_parquet(data_path, combined)
        _atomic_parquet(coverage_path, coverage)
        atomic_write_bytes(
            raw_path,
            gzip.compress(b"\n".join(raw_records) + b"\n", compresslevel=6, mtime=0),
        )
        atomic_write_bytes(index_path, gzip.compress(index_content, compresslevel=6, mtime=0))
        fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-eia-wpsr-table1-original-vintages-2012-2025-v2",
            "provider": "U.S. Energy Information Administration",
            "table": TABLE_NAME,
            "archive_index_url": ARCHIVE_INDEX_URL,
            "schedule_url": SCHEDULE_URL,
            "copyright_and_reuse_url": COPYRIGHT_URL,
            "fetched_at_utc": fetched_at,
            "request_count": len(releases) + 1,
            "release_count": len(releases),
            "processed_release_count": int(coverage["admissible"].sum()),
            "excluded_release_count": int((~coverage["admissible"]).sum()),
            "request_bounds": {
                "release_from": SOURCE_START.isoformat(),
                "release_through": SOURCE_END.isoformat(),
                "protected_from_utc": PROTECTED_FROM.isoformat(),
                "excluded_release_2025_12_31": True,
            },
            "temporal_semantics": {
                "release_date": "date linked by the official issue archive",
                "data_week_ending": "week ending printed inside that release-specific file",
                "available_at": "23:59:59 America/New_York on official release date",
                "official_table_release_rule": "after 10:30 America/New_York, holiday exceptions",
                "admissible_join": "available_at less than or equal to decision_at",
                "release_specific_archive": True,
                "historical_content_immutability_cryptographically_proved": False,
                "historical_development_backtest_admissible": True,
                "contains_prices_returns_targets_labels_or_pnl": False,
            },
            "source_quality": {
                "excluded_releases": coverage.loc[
                    ~coverage["admissible"],
                    ["release_date", "data_week_ending", "sha256", "exclusion_reason"],
                ].to_dict(orient="records"),
                "revision_chain": revision_chain_audit(combined),
                "last_modified_used_for_availability": False,
            },
            "rights": {
                "official_statement": "U.S. government EIA publications are public domain",
                "acknowledgment_required_by_project": True,
                "raw_redistribution_allowed": True,
            },
            "archive_index": {
                "bytes": len(index_content),
                "sha256": sha256_bytes(index_content),
                "last_modified": index_headers.get("Last-Modified"),
            },
            "artifacts": {
                "processed": {
                    "path": data_path.name,
                    "bytes": data_path.stat().st_size,
                    "sha256": sha256_file(data_path),
                    "rows": len(combined),
                    "columns": combined.columns.tolist(),
                    "minimum_release_date": combined["release_date"].min().date().isoformat(),
                    "maximum_release_date": combined["release_date"].max().date().isoformat(),
                    "maximum_available_at": combined["available_at"].max().isoformat(),
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
                "raw_archive_index": {
                    "path": index_path.name,
                    "bytes": index_path.stat().st_size,
                    "sha256": sha256_file(index_path),
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
        download_eia_wpsr_source(
            arguments.output_directory,
            staging_directory=arguments.staging_directory,
            max_workers=arguments.max_workers,
        )
    )


if __name__ == "__main__":
    main()
