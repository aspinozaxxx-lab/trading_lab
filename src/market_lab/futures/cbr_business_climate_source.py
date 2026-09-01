"""Acquire release-specific Bank of Russia business-climate records."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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
ARCHIVE_URL: Final[str] = "https://www.cbr.ru/analytics/dkp/monitoring/"
SOURCE_START: Final[date] = date(2022, 5, 1)
SOURCE_END: Final[date] = date(2025, 12, 1)
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
DEFAULT_OUTPUT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/info_radar/cbr-business-climate-release-pages-2022-2025-v1"
)
USER_AGENT: Final[str] = "market-lab-cbr-business-climate/1.0 (causal research)"
DEFAULT_MAX_WORKERS: Final[int] = 8
MAX_HTML_BYTES: Final[int] = 2 * 1024 * 1024
MAX_PDF_BYTES: Final[int] = 24 * 1024 * 1024
_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset({"cbr.ru", "www.cbr.ru"})
_RELEASE_PATH: Final[re.Pattern[str]] = re.compile(
    r"^/analytics/dkp/monitoring/(?P<month>\d{2})_?(?P<year>\d{2})/$",
    re.IGNORECASE,
)
_SAFE_SNAPSHOT_ID: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
)
_RUSSIAN_MONTHS: Final[dict[str, int]] = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_COMPONENT_IDS: Final[dict[str, str]] = {
    "s0": "bci",
    "s1": "current_assessments",
    "s2": "expectations",
}
EXPECTED_RELEASE_MONTHS: Final[tuple[date, ...]] = tuple(
    date(year, month, 1)
    for year in range(SOURCE_START.year, SOURCE_END.year + 1)
    for month in range(1, 13)
    if SOURCE_START <= date(year, month, 1) <= SOURCE_END
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
class ReleaseLink:
    """One release-specific page discovered from the official archive."""

    release_month: date
    release_key: str
    page_url: str


@dataclass(frozen=True, slots=True)
class RequestRecord:
    """One raw official response retained in the external source archive."""

    kind: str
    identity: str
    url: str
    content: bytes
    headers: Mapping[str, str]


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


def _official_url(value: str) -> str:
    absolute = urljoin(ARCHIVE_URL, value)
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise ValueError("CBR URL escaped the official HTTPS host")
    if parsed.username is not None or parsed.password is not None or parsed.port is not None:
        raise ValueError("CBR URL contains forbidden authority fields")
    return absolute


def _month_from_url(value: str) -> tuple[date, str] | None:
    candidate = urlparse(value)
    match = _RELEASE_PATH.fullmatch(candidate.path)
    if match is None:
        return None
    parsed = urlparse(_official_url(value))
    month = int(match.group("month"))
    year = 2000 + int(match.group("year"))
    try:
        release_month = date(year, month, 1)
    except ValueError as error:
        raise ValueError(f"invalid CBR release path: {parsed.path}") from error
    return release_month, parsed.path.rstrip("/").rsplit("/", maxsplit=1)[-1]


class _ArchiveParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href is not None and _month_from_url(href) is not None:
            self.links.append(_official_url(href))


def discover_release_links(content: bytes) -> list[ReleaseLink]:
    """Discover the exact admitted monthly pages from the official archive."""
    if len(content) > MAX_HTML_BYTES:
        raise ValueError("CBR archive page exceeds the HTML size limit")
    parser = _ArchiveParser()
    parser.feed(content.decode("utf-8-sig"))
    by_month: dict[date, ReleaseLink] = {}
    for url in sorted(set(parser.links)):
        parsed = _month_from_url(url)
        if parsed is None:
            continue
        release_month, release_key = parsed
        if not SOURCE_START <= release_month <= SOURCE_END:
            continue
        link = ReleaseLink(release_month, release_key, url)
        previous = by_month.setdefault(release_month, link)
        if previous != link:
            raise ValueError(f"multiple CBR release URLs for {release_month}")
    expected = set(EXPECTED_RELEASE_MONTHS)
    if set(by_month) != expected:
        missing = sorted(expected - set(by_month))
        extra = sorted(set(by_month) - expected)
        raise ValueError(f"CBR release coverage drifted; missing={missing}, extra={extra}")
    return [by_month[month] for month in sorted(by_month)]


class _ReleasePageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pdf_links: list[str] = []
        self.visible_text: list[str] = []
        self.news_date_text: list[str] = []
        self._news_date_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self._news_date_depth:
            self._news_date_depth += 1
        classes = set((attributes.get("class") or "").split())
        if "news-info-line_date" in classes:
            if self._news_date_depth:
                raise ValueError("nested CBR publication-date containers")
            self._news_date_depth = 1
        if tag == "a":
            href = attributes.get("href")
            if href and urlparse(href).path.lower().endswith(".pdf"):
                absolute = _official_url(href)
                if "/collection/collection/file/" in urlparse(absolute).path.lower():
                    self.pdf_links.append(absolute)

    def handle_endtag(self, tag: str) -> None:
        del tag
        if self._news_date_depth:
            self._news_date_depth -= 1

    def handle_data(self, data: str) -> None:
        normalized = " ".join(data.split())
        if normalized:
            self.visible_text.append(normalized)
            if self._news_date_depth:
                self.news_date_text.append(normalized)


def _russian_page_date(value: str) -> date:
    normalized = " ".join(value.casefold().split())
    match = re.fullmatch(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})\s+года", normalized)
    if match is None or match.group(2) not in _RUSSIAN_MONTHS:
        raise ValueError(f"invalid CBR page date: {value!r}")
    return date(
        int(match.group(3)),
        _RUSSIAN_MONTHS[match.group(2)],
        int(match.group(1)),
    )


def conservative_available_at(publication_date: date, last_updated_date: date) -> pd.Timestamp:
    """Use Moscow day-end of the later printed page date."""
    if last_updated_date < publication_date:
        raise ValueError("CBR last-updated date precedes publication date")
    local = datetime.combine(
        max(publication_date, last_updated_date),
        wall_time(23, 59, 59),
        tzinfo=MOSCOW,
    )
    return pd.Timestamp(local.astimezone(UTC))


def _balanced_array(text: str, start: int) -> str:
    if start >= len(text) or text[start] != "[":
        raise ValueError("CBR chart array does not start with an opening bracket")
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("CBR chart contains an unbalanced JSON array")


def _array_after(text: str, key: str, start: int) -> tuple[object, int]:
    key_position = text.find(key, start)
    if key_position < 0:
        raise ValueError(f"CBR chart misses {key}")
    array_start = text.find("[", key_position + len(key))
    if array_start < 0:
        raise ValueError(f"CBR chart misses the array for {key}")
    encoded = _balanced_array(text, array_start)
    try:
        return json.loads(encoded), array_start + len(encoded)
    except json.JSONDecodeError as error:
        raise ValueError(f"CBR chart {key} is not valid JSON") from error


def _label_number(value: object) -> float:
    if not isinstance(value, str):
        raise ValueError("CBR chart point has no printed numeric label")
    normalized = value.replace("\u00a0", "").replace(",", ".").strip()
    try:
        result = float(normalized)
    except ValueError as error:
        raise ValueError(f"invalid CBR chart label: {value!r}") from error
    if not math.isfinite(result):
        raise ValueError("CBR chart label is not finite")
    return result


def _chart_components(page: str, release_month: date) -> dict[str, object]:
    marker = 'id="GrafChart_ChartModel_chart"'
    marker_position = page.find(marker)
    if marker_position < 0:
        raise ValueError("CBR release page misses the BCI chart")
    categories_raw, categories_end = _array_after(page, '"categories":', marker_position)
    if not isinstance(categories_raw, list):
        raise ValueError("CBR BCI chart categories are not a list")
    categories: list[date] = []
    for group in categories_raw:
        if not isinstance(group, dict) or not isinstance(group.get("categories"), list):
            raise ValueError("CBR BCI chart category group is invalid")
        for raw_date in group["categories"]:
            try:
                category = date.fromisoformat(raw_date)
            except (TypeError, ValueError) as error:
                raise ValueError("CBR BCI chart category is not an ISO date") from error
            categories.append(category)
    if len(categories) != len(set(categories)) or categories != sorted(categories):
        raise ValueError("CBR BCI chart categories are not unique and chronological")
    try:
        release_index = categories.index(release_month)
    except ValueError as error:
        raise ValueError("CBR BCI chart lacks its release month") from error
    series_raw, _ = _array_after(page, '"series":', categories_end)
    if not isinstance(series_raw, list):
        raise ValueError("CBR BCI chart series are not a list")
    by_id = {
        item.get("id"): item
        for item in series_raw
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if set(by_id) != set(_COMPONENT_IDS):
        raise ValueError(f"unexpected CBR BCI component ids: {sorted(by_id)}")
    component_indices: dict[str, int] = {}
    for series_id, component in _COMPONENT_IDS.items():
        data = by_id[series_id].get("data")
        if not isinstance(data, list) or len(data) != len(categories):
            raise ValueError(f"CBR BCI {component} data length does not match categories")
        non_missing = [index for index, point in enumerate(data) if point is not None]
        if not non_missing:
            raise ValueError(f"CBR BCI {component} has no observed chart point")
        component_indices[component] = non_missing[-1]
    if len(set(component_indices.values())) != 1:
        raise ValueError("CBR BCI components end on different observation months")
    observation_index = next(iter(component_indices.values()))
    if observation_index > release_index or release_index - observation_index > 1:
        raise ValueError("CBR BCI endpoint is not the release month or its prior month")
    observation_month = categories[observation_index]
    result: dict[str, float | pd.Timestamp] = {
        "observation_month": pd.Timestamp(observation_month)
    }
    for series_id, component in _COMPONENT_IDS.items():
        data = by_id[series_id].get("data")
        point = data[observation_index]
        if not isinstance(point, dict) or "y" not in point or "name" not in point:
            raise ValueError(f"CBR BCI {component} release point is not printed and labeled")
        if any(later is not None for later in data[observation_index + 1 :]):
            raise ValueError(f"CBR BCI {component} contains future non-null chart points")
        try:
            exact = float(point["y"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"CBR BCI {component} exact point is not numeric") from error
        published = _label_number(point["name"])
        if not math.isfinite(exact) or abs(exact - published) > 0.051:
            raise ValueError(f"CBR BCI {component} exact point disagrees with its label")
        result[f"{component}_value"] = published
        result[f"{component}_chart_exact"] = exact
    return result


def parse_release_page(
    content: bytes,
    *,
    release: ReleaseLink,
    retrieved_at_utc: str,
) -> dict[str, object]:
    """Parse only the release-month labeled points from one versioned CBR page."""
    if len(content) > MAX_HTML_BYTES:
        raise ValueError("CBR release page exceeds the HTML size limit")
    try:
        retrieved = pd.Timestamp(retrieved_at_utc)
    except ValueError as error:
        raise ValueError("invalid CBR retrieval timestamp") from error
    if retrieved.tzinfo is None:
        raise ValueError("CBR retrieval timestamp must be timezone-aware")
    page = content.decode("utf-8-sig")
    parser = _ReleasePageParser()
    parser.feed(page)
    publication_date = _russian_page_date(" ".join(parser.news_date_text))
    visible = " ".join(parser.visible_text)
    update_match = re.search(
        r"Последнее\s+обновление\s+страницы\s*:\s*(\d{2}\.\d{2}\.\d{4})",
        visible,
        re.IGNORECASE,
    )
    if update_match is None:
        raise ValueError("CBR release page misses its last-updated date")
    last_updated_date = datetime.strptime(update_match.group(1), "%d.%m.%Y").date()
    if date(publication_date.year, publication_date.month, 1) != release.release_month:
        raise ValueError("CBR page publication month disagrees with the archive link")
    pdf_links = sorted(set(parser.pdf_links))
    if len(pdf_links) != 1:
        raise ValueError(f"unexpected CBR release PDF links: {pdf_links}")
    return {
        "release_month": pd.Timestamp(release.release_month),
        "release_key": release.release_key,
        "publication_date": pd.Timestamp(publication_date),
        "last_updated_date": pd.Timestamp(last_updated_date),
        "availability_date": pd.Timestamp(max(publication_date, last_updated_date)),
        "available_at": conservative_available_at(publication_date, last_updated_date),
        **_chart_components(page, release.release_month),
        "page_url": release.page_url,
        "pdf_url": pdf_links[0],
        "retrieved_at_utc": retrieved,
        "release_specific_current_vintage": True,
        "modified_after_publication": last_updated_date > publication_date,
    }


def _request_record(
    kind: str,
    identity: str,
    url: str,
    *,
    session: SessionLike,
) -> RequestRecord:
    official = _official_url(url)
    response = session.get(
        official,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        timeout=60.0,
    )
    response.raise_for_status()
    content = response.content
    limit = MAX_PDF_BYTES if kind == "pdf" else MAX_HTML_BYTES
    if not content or len(content) > limit:
        raise ValueError(f"CBR {kind} response has an invalid size")
    if kind == "pdf" and not content.startswith(b"%PDF-"):
        raise ValueError("CBR report attachment is not a PDF")
    return RequestRecord(kind, identity, official, content, dict(response.headers))


def _fetch_many(
    requests_to_make: Sequence[tuple[str, str, str]],
    *,
    session: SessionLike,
    max_workers: int,
) -> list[RequestRecord]:
    def fetch(item: tuple[str, str, str]) -> RequestRecord:
        kind, identity, url = item
        try:
            return _request_record(kind, identity, url, session=session)
        except Exception as error:
            raise RuntimeError(f"CBR request failed for {kind}:{identity}:{url}") from error

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(fetch, requests_to_make))


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _raw_record(record: RequestRecord) -> bytes:
    selected_headers = {
        name: record.headers.get(name)
        for name in ("Last-Modified", "Content-Type", "ETag")
        if record.headers.get(name) is not None
    }
    return json.dumps(
        {
            "kind": record.kind,
            "identity": record.identity,
            "url": record.url,
            "headers": selected_headers,
            "bytes": len(record.content),
            "sha256": sha256_bytes(record.content),
            "content_encoding": "base64",
            "content": base64.b64encode(record.content).decode("ascii"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def download_cbr_business_climate(
    output_directory: Path = DEFAULT_OUTPUT,
    *,
    session: SessionLike | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    fetched_at_utc: str | None = None,
    minimum_releases: int = 40,
) -> Path:
    """Write one immutable target-free source bundle; never overwrite an existing path."""
    final = output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"CBR business-climate output already exists: {final}")
    if not _SAFE_SNAPSHOT_ID.fullmatch(final.name):
        raise ValueError("unsafe CBR business-climate snapshot directory name")
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = session or requests.Session()
    archive_initial = _request_record(
        "archive", "initial", ARCHIVE_URL, session=client
    )
    releases = discover_release_links(archive_initial.content)
    page_records = _fetch_many(
        [("page", item.release_key, item.page_url) for item in releases],
        session=client,
        max_workers=max_workers,
    )
    rows: list[dict[str, object]] = []
    for release, record in zip(releases, page_records, strict=True):
        try:
            rows.append(
                parse_release_page(
                    record.content,
                    release=release,
                    retrieved_at_utc=fetched_at,
                )
            )
        except ValueError as error:
            raise ValueError(
                f"CBR business-climate release {release.release_key} could not be parsed"
            ) from error
    if len(rows) < minimum_releases:
        raise ValueError("CBR business-climate release coverage is unexpectedly small")
    pdf_records = _fetch_many(
        [
            ("pdf", release.release_key, str(row["pdf_url"]))
            for release, row in zip(releases, rows, strict=True)
        ],
        session=client,
        max_workers=max_workers,
    )
    archive_final = _request_record("archive", "final", ARCHIVE_URL, session=client)
    if discover_release_links(archive_final.content) != releases:
        raise ValueError("CBR release index changed during collection")
    frame = pd.DataFrame(rows).sort_values("release_month", ignore_index=True)
    if frame["release_month"].duplicated().any():
        raise ValueError("CBR business-climate releases contain duplicate months")
    if frame["available_at"].ge(PROTECTED_FROM).any():
        raise ValueError("CBR business-climate releases crossed the protected boundary")
    if set(frame["release_month"].dt.date) != set(EXPECTED_RELEASE_MONTHS):
        raise ValueError("CBR processed release coverage differs from the archive")
    if frame[["bci_value", "current_assessments_value", "expectations_value"]].isna().any().any():
        raise ValueError("CBR business-climate components contain missing values")
    page_by_key = {record.identity: record for record in page_records}
    pdf_by_key = {record.identity: record for record in pdf_records}
    if set(page_by_key) != {release.release_key for release in releases}:
        raise ValueError("CBR page response identities are incomplete")
    if set(pdf_by_key) != set(page_by_key):
        raise ValueError("CBR PDF response identities are incomplete")
    coverage = pd.DataFrame(
        [
            {
                "release_month": row["release_month"],
                "observation_month": row["observation_month"],
                "publication_date": row["publication_date"],
                "last_updated_date": row["last_updated_date"],
                "available_at": row["available_at"],
                "release_key": release.release_key,
                "page_url": release.page_url,
                "page_bytes": len(page_by_key[release.release_key].content),
                "page_sha256": sha256_bytes(page_by_key[release.release_key].content),
                "pdf_url": row["pdf_url"],
                "pdf_bytes": len(pdf_by_key[release.release_key].content),
                "pdf_sha256": sha256_bytes(pdf_by_key[release.release_key].content),
                "modified_after_publication": row["modified_after_publication"],
            }
            for release, row in zip(releases, rows, strict=True)
        ]
    ).sort_values("release_month", ignore_index=True)
    year_counts = Counter(frame["release_month"].dt.year.astype(int))
    deltas = frame["bci_value"].diff().dropna()
    availability_collisions = int(frame["available_at"].duplicated(keep=False).sum())
    availability_gaps = frame["available_at"].sort_values().diff().dt.total_seconds() / 86_400
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        data_path = temporary / "cbr_business_climate_releases.parquet"
        coverage_path = temporary / "coverage.parquet"
        raw_path = temporary / "official_cbr_business_climate_responses.jsonl.gz"
        _atomic_parquet(data_path, frame)
        _atomic_parquet(coverage_path, coverage)
        raw_records = [archive_initial, *page_records, *pdf_records, archive_final]
        raw_lines = [_raw_record(record) for record in raw_records]
        atomic_write_bytes(
            raw_path,
            gzip.compress(b"\n".join(raw_lines) + b"\n", compresslevel=6, mtime=0),
        )
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-cbr-business-climate-release-pages-2022-2025-v1",
            "provider": "Bank of Russia",
            "source_name": "Business Climate Index monthly release pages",
            "source_url": ARCHIVE_URL,
            "fetched_at_utc": fetched_at,
            "request_count": len(raw_records),
            "request_bounds": {
                "release_month_from": SOURCE_START.isoformat(),
                "release_month_through": SOURCE_END.isoformat(),
                "protected_from_utc": PROTECTED_FROM.isoformat(),
            },
            "coverage": {
                "release_pages": len(frame),
                "release_pages_by_year": {
                    str(year): year_counts[year] for year in sorted(year_counts)
                },
                "minimum_release_month": frame["release_month"].min().date().isoformat(),
                "maximum_release_month": frame["release_month"].max().date().isoformat(),
                "minimum_available_at": frame["available_at"].min().isoformat(),
                "maximum_available_at": frame["available_at"].max().isoformat(),
                "modified_after_publication_count": int(
                    frame["modified_after_publication"].sum()
                ),
                "prior_month_observation_count": int(
                    frame["observation_month"].lt(frame["release_month"]).sum()
                ),
                "rows_in_availability_collisions": availability_collisions,
                "maximum_availability_gap_days": float(availability_gaps.max()),
                "sequential_bci_delta_counts": {
                    "positive": int(deltas.gt(0).sum()),
                    "negative": int(deltas.lt(0).sum()),
                    "zero": int(deltas.eq(0).sum()),
                },
            },
            "temporal_semantics": {
                "release_month": "month encoded in the versioned official page URL",
                "observation_month": "month of the labeled chart endpoint in that release",
                "publication_date": "date printed in the release page header",
                "last_updated_date": "date printed in the page revision footer",
                "available_at": (
                    "23:59:59 Europe/Moscow on the later of publication_date and "
                    "last_updated_date"
                ),
                "same_available_at_collision_rule": (
                    "downstream protocols must keep only the latest release_month"
                ),
                "admissible_join": "available_at less than or equal to decision_at",
                "date_only_source_uses_conservative_day_end": True,
                "release_specific_pages_retrieved_currently": True,
                "original_historical_response_bytes_available": False,
                "historical_content_immutability_cryptographically_proved": False,
                "development_backtest_admissible": True,
                "independent_confirmation_without_forward_vintage_collection": False,
                "contains_prices_returns_targets_labels_or_pnl": False,
                "missing_values_are_not_zero": True,
            },
            "value_semantics": {
                "strategy_admissible_value": (
                    "one-decimal label printed on each release-specific chart endpoint"
                ),
                "chart_exact_value_retained_for_source_audit_only": True,
                "components": sorted(_COMPONENT_IDS.values()),
                "latest_current_vintage_history_not_used": True,
            },
            "source_quality": {
                "archive_contains_every_expected_month": True,
                "archive_index_unchanged_during_collection": True,
                "every_page_has_one_unique_release_pdf": True,
                "every_release_point_is_labeled": True,
                "every_chart_has_no_non_null_future_point": True,
                "duplicate_release_months": 0,
            },
            "rights": {
                "redistribution_license_verified": False,
                "raw_stored_outside_git": True,
            },
            "artifacts": {
                "processed": {
                    "path": data_path.name,
                    "bytes": data_path.stat().st_size,
                    "sha256": sha256_file(data_path),
                    "rows": len(frame),
                    "columns": frame.columns.tolist(),
                },
                "coverage": {
                    "path": coverage_path.name,
                    "bytes": coverage_path.stat().st_size,
                    "sha256": sha256_file(coverage_path),
                    "rows": len(coverage),
                },
                "raw_responses": {
                    "path": raw_path.name,
                    "bytes": raw_path.stat().st_size,
                    "sha256": sha256_file(raw_path),
                    "records": len(raw_records),
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
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--minimum-releases", type=int, default=40)
    arguments = parser.parse_args()
    print(
        download_cbr_business_climate(
            arguments.output_directory,
            max_workers=arguments.max_workers,
            minimum_releases=arguments.minimum_releases,
        )
    )


if __name__ == "__main__":
    main()
