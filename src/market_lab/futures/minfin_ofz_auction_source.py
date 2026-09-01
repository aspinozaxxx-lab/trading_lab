"""Acquire official current-vintage Minfin OFZ auction-result records."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as wall_time
from html.parser import HTMLParser
from pathlib import Path
from typing import Final, Protocol
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
ARCHIVE_URL: Final[str] = (
    "https://minfin.gov.ru/ru/perfomance/public_debt/internal/operations/ofz/auction/"
)
LICENSE_URL: Final[str] = "https://creativecommons.org/licenses/by/4.0/deed.ru"
SOURCE_START: Final[date] = date(2021, 1, 1)
SOURCE_END: Final[date] = date(2025, 12, 31)
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
USER_AGENT: Final[str] = "market-lab-minfin-ofz-auctions/1.0 (causal research)"
DEFAULT_MAX_WORKERS: Final[int] = 6
DEFAULT_OUTPUT: Final[Path] = (
    PROJECT_ROOT
    / "data/processed/info_radar/minfin-ofz-auction-results-current-vintage-2021-2025-v2"
)
_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset({"minfin.gov.ru", "www.minfin.gov.ru"})
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
_RUSSIAN_DATE = re.compile(
    r"(?P<day>\d{1,2})\s+(?P<month>"
    + "|".join(_RUSSIAN_MONTHS)
    + r")\s+(?P<year>\d{4})",
    flags=re.IGNORECASE,
)
_ISSUE = re.compile(r"\b(?P<issue>\d{5}RMFS)\b", flags=re.IGNORECASE)
_VOLUME_NUMBER = r"(?P<number>\d[\d\s\u00a0]*(?:[,.]\d+)?)"
_VOLUME_UNIT = r"(?P<unit>млрд|млн)\.?\s*(?:руб(?:лей|ля|\.)?)?"


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
class AuctionCard:
    """One result-card identity recovered from the official archive listing."""

    document_id: int
    title: str
    publication_date: date
    modified_date: date
    detail_url: str
    attachment_url: str | None
    listing_page: int


@dataclass(frozen=True, slots=True)
class RequestRecord:
    """Raw response plus selected reproducibility metadata."""

    kind: str
    identity: str
    url: str
    content: bytes
    headers: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ListingPage:
    """Parsed result cards and archive pagination metadata."""

    cards: tuple[AuctionCard, ...]
    page_count: int | None


class _ResultListingParser(HTMLParser):
    def __init__(self, page: int) -> None:
        super().__init__(convert_charrefs=True)
        self.page = page
        self.page_count: int | None = None
        self.cards: list[AuctionCard] = []
        self._card: dict[str, object] | None = None
        self._card_depth = 0
        self._date_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and attributes.get("id") == "ajax-pagination-10090-39":
            page_count = attributes.get("data-page-count")
            if page_count is not None:
                self.page_count = int(page_count)
        if tag == "div":
            classes = set((attributes.get("class") or "").split())
            href = attributes.get("data-href") or ""
            if self._card is None and "document_card" in classes and "id_39=" in href:
                self._card = {"detail_href": href, "dates": []}
                self._card_depth = 1
                return
            if self._card is not None:
                self._card_depth += 1
        if self._card is None:
            return
        classes = set((attributes.get("class") or "").split())
        if tag == "span" and "date" in classes:
            self._date_text = []
        elif tag == "a" and "document_title" in classes:
            self._card["title"] = attributes.get("title") or ""
        elif tag == "a" and "file_item" in classes:
            self._card["attachment_href"] = attributes.get("href")

    def handle_data(self, data: str) -> None:
        if self._date_text is not None:
            self._date_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if tag == "span" and self._date_text is not None:
            text = " ".join("".join(self._date_text).split())
            dates = self._card["dates"]
            assert isinstance(dates, list)
            dates.append(text)
            self._date_text = None
        if tag != "div":
            return
        self._card_depth -= 1
        if self._card_depth != 0:
            return
        self.cards.append(_finalize_card(self._card, self.page))
        self._card = None


class _TextWrapperParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set((dict(attrs).get("class") or "").split())
        if tag == "div" and self._depth == 0 and "text_wrapper" in classes:
            self._depth = 1
            return
        if self._depth == 0:
            return
        if tag == "div":
            self._depth += 1
        elif tag in {"br", "p", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._depth:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._depth == 0:
            return
        if tag == "div":
            self._depth -= 1
        elif tag in {"p", "li", "tr"}:
            self.parts.append("\n")

    def text(self) -> str:
        lines = [
            " ".join(part.replace("\xa0", " ").split())
            for part in "".join(self.parts).splitlines()
        ]
        return "\n".join(line for line in lines if line)


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
        raise ValueError("Minfin URL escaped the official HTTPS host")
    return absolute


def _date_from_listing(value: str, prefix: str) -> date | None:
    normalized = " ".join(value.split())
    marker = f"{prefix}:"
    if not normalized.startswith(marker):
        return None
    try:
        return datetime.strptime(normalized[len(marker) :].strip(), "%d.%m.%Y").date()
    except ValueError as error:
        raise ValueError(f"invalid Minfin {prefix.lower()} date: {value!r}") from error


def _finalize_card(raw: Mapping[str, object], page: int) -> AuctionCard:
    href = str(raw.get("detail_href") or "")
    query = parse_qs(urlparse(href).query)
    identity = query.get("id_39", [""])[0].split("-", maxsplit=1)[0]
    if not identity.isdigit():
        raise ValueError("Minfin result card has no numeric id_39")
    title = " ".join(str(raw.get("title") or "").replace("\xa0", " ").split())
    if not title:
        raise ValueError("Minfin result card has no title")
    raw_dates = raw.get("dates")
    if not isinstance(raw_dates, list):
        raise ValueError("Minfin result card has no date list")
    published = next(
        (
            _date_from_listing(str(value), "Опубликовано")
            for value in raw_dates
            if str(value).startswith("Опубликовано")
        ),
        None,
    )
    modified = next(
        (
            _date_from_listing(str(value), "Изменено")
            for value in raw_dates
            if str(value).startswith("Изменено")
        ),
        None,
    )
    if published is None or modified is None:
        raise ValueError("Minfin result card lacks publication or modification date")
    if modified < published:
        raise ValueError("Minfin result card was modified before publication")
    attachment = raw.get("attachment_href")
    return AuctionCard(
        document_id=int(identity),
        title=title,
        publication_date=published,
        modified_date=modified,
        detail_url=_official_url(href),
        attachment_url=_official_url(str(attachment)) if attachment else None,
        listing_page=page,
    )


def parse_listing_page(content: bytes, *, page: int) -> ListingPage:
    """Parse only the ``id_39`` result-card group from one archive page."""
    try:
        html = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("Minfin listing HTML is not UTF-8") from error
    parser = _ResultListingParser(page)
    parser.feed(html)
    if not parser.cards:
        raise ValueError("Minfin listing page contains no result cards")
    dates = [card.publication_date for card in parser.cards]
    if dates != sorted(dates, reverse=True):
        raise ValueError("Minfin result cards are not reverse-chronological within page")
    return ListingPage(tuple(parser.cards), parser.page_count)


def conservative_available_at(publication_date: date) -> pd.Timestamp:
    """Treat a date-only official record as unavailable until day end in Moscow."""
    local = datetime.combine(publication_date, wall_time(23, 59, 59), tzinfo=MOSCOW)
    available = pd.Timestamp(local.astimezone(UTC))
    if available >= PROTECTED_FROM:
        raise ValueError("Minfin auction availability crossed the protected boundary")
    return available


def classify_title(title: str) -> str:
    normalized = " ".join(title.lower().replace("ё", "е").split())
    if "дополнительн" in normalized and ("результат" in normalized or "итог" in normalized):
        return "supplemental_result"
    if "уточнен" in normalized:
        return "correction"
    if any(marker in normalized for marker in ("несостоявш", "непроведен", "отмен")):
        return "failed_or_cancelled"
    if normalized.startswith("о проведении") and "аукцион" in normalized:
        return "auction_announcement"
    if "результат" in normalized and "размещен" in normalized and "аукцион" in normalized:
        return "primary_result"
    return "other"


def _classify_record(title: str, text: str) -> str:
    normalized_body = " ".join(text.lower().replace("ё", "е").split())
    if "аукцион" in normalized_body and "признан несостоявшимся" in normalized_body:
        return "failed_or_cancelled"
    return classify_title(title)


def _parse_russian_date(value: str) -> date | None:
    match = _RUSSIAN_DATE.search(value)
    if match is None:
        return None
    return date(
        int(match.group("year")),
        _RUSSIAN_MONTHS[match.group("month").lower()],
        int(match.group("day")),
    )


def _number(value: str, label: str) -> float:
    normalized = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        parsed = float(normalized)
    except ValueError as error:
        raise ValueError(f"invalid Minfin numeric field {label}: {value!r}") from error
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite Minfin numeric field: {label}")
    return parsed


def _volume(text: str, label_pattern: str, label: str) -> float | None:
    pattern = re.compile(
        rf"{label_pattern}\s*[–—:-]\s*{_VOLUME_NUMBER}\s*{_VOLUME_UNIT}",
        flags=re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        return None
    value = _number(match.group("number"), label)
    return value if match.group("unit").lower() == "млрд" else value / 1000.0


def _percent(text: str, label_pattern: str, label: str) -> float | None:
    match = re.search(
        rf"{label_pattern}\s*[–—:-]\s*(\d[\d\s\u00a0]*(?:[,.]\d+)?)\s*%",
        text,
        flags=re.IGNORECASE,
    )
    return _number(match.group(1), label) if match is not None else None


def _auction_date(title: str, text: str) -> date | None:
    title_match = re.search(r"на аукционе\s+(.+)$", title, flags=re.IGNORECASE)
    if title_match is not None:
        parsed = _parse_russian_date(title_match.group(1))
        if parsed is not None:
            return parsed
    body_match = re.search(
        r"результатах проведения\s+(.{0,80}?)\s+аукциона",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _parse_russian_date(body_match.group(1)) if body_match is not None else None


def parse_result_detail(
    content: bytes,
    *,
    card: AuctionCard,
    retrieved_at_utc: str,
) -> dict[str, object]:
    """Parse one official result page; fail closed on incomplete primary results."""
    try:
        html = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("Minfin result HTML is not UTF-8") from error
    parser = _TextWrapperParser()
    parser.feed(html)
    text = parser.text()
    if not text:
        raise ValueError("Minfin result page contains no text_wrapper body")
    event_kind = _classify_record(card.title, text)
    issue_match = _ISSUE.search(f"{card.title}\n{text}")
    issue_code = issue_match.group("issue").upper() if issue_match is not None else None
    type_match = re.search(
        r"ОФЗ[\s\-‑–]*(ПД|ПК|ИН|АД)",
        f"{card.title}\n{text}",
        flags=re.IGNORECASE,
    )
    ofz_type = type_match.group(1).upper() if type_match is not None else None
    maturity_match = re.search(r"датой погашения\s+(.{0,60})", text, flags=re.IGNORECASE)
    maturity = _parse_russian_date(maturity_match.group(1)) if maturity_match else None
    auction = _auction_date(card.title, text)
    offered = _volume(text, r"объ[её]м предложения", "offered_volume")
    offered_is_remaining = bool(
        re.search(
            r"объ[её]м предложения\s*[–—:-]\s*остаток",
            text,
            flags=re.IGNORECASE,
        )
    )
    demand = _volume(text, r"объ[её]м спроса", "demand_volume")
    placed = _volume(
        text,
        r"(?:размещенн(?:ый|ого) объ[её]м выпуска|объ[её]м размещения)",
        "placed_volume",
    )
    proceeds = _volume(text, r"выручка от размещения", "placement_proceeds")
    cutoff_price = _percent(text, r"цена отсечения", "cutoff_price")
    weighted_price = _percent(text, r"средневзвешенная цена", "weighted_price")
    cutoff_yield = _percent(
        text,
        r"(?:реальная\s+)?доходность по цене отсечения",
        "cutoff_yield",
    )
    weighted_yield = _percent(
        text,
        (
            r"(?:средневзвешенная(?:\s+реальная)? доходность|"
            r"доходность по средневзвешенной цене)"
        ),
        "weighted_yield",
    )
    if event_kind == "primary_result":
        required = {
            "issue_code": issue_code,
            "ofz_type": ofz_type,
            "auction_date": auction,
            "maturity_date": maturity,
            "demand_volume": demand,
            "placed_volume": placed,
            "placement_proceeds": proceeds,
            "cutoff_price": cutoff_price,
            "weighted_price": weighted_price,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(f"Minfin primary result misses required fields: {missing}")
        if not offered_is_remaining and offered is None:
            raise ValueError("Minfin primary result has neither numeric nor remaining offer")
        if ofz_type != "ПК" and (cutoff_yield is None or weighted_yield is None):
            raise ValueError("Minfin non-floater primary result misses yields")
        assert auction is not None
        if auction > card.publication_date or (card.publication_date - auction).days > 7:
            raise ValueError("Minfin auction/publication lag escaped 0..7 days")
        assert placed is not None and demand is not None
        if placed <= 0.0 or demand <= 0.0:
            raise ValueError("Minfin primary result has non-positive demand or placement")
    bid_to_cover = demand / placed if demand is not None and placed and placed > 0.0 else None
    return {
        "document_id": card.document_id,
        "event_kind": event_kind,
        "title": card.title,
        "publication_date": pd.Timestamp(card.publication_date),
        "modified_date": pd.Timestamp(card.modified_date),
        "available_at": conservative_available_at(card.publication_date),
        "auction_date": pd.Timestamp(auction) if auction is not None else pd.NaT,
        "issue_code": issue_code,
        "ofz_type": ofz_type,
        "maturity_date": pd.Timestamp(maturity) if maturity is not None else pd.NaT,
        "offered_volume_bln_rub": offered,
        "offered_volume_is_remaining": offered_is_remaining,
        "demand_volume_bln_rub": demand,
        "placed_volume_bln_rub": placed,
        "placement_proceeds_bln_rub": proceeds,
        "bid_to_cover": bid_to_cover,
        "cutoff_price_pct": cutoff_price,
        "weighted_price_pct": weighted_price,
        "cutoff_yield_pct": cutoff_yield,
        "weighted_yield_pct": weighted_yield,
        "source_url": card.detail_url,
        "attachment_url": card.attachment_url,
        "raw_sha256": sha256_bytes(content),
        "retrieved_at_utc": retrieved_at_utc,
        "provider": "Ministry of Finance of the Russian Federation",
        "current_vintage_historical_record": True,
        "original_publication_bytes_available": False,
        "historical_content_immutability_cryptographically_proved": False,
    }


def _request_bytes(
    url: str,
    *,
    session: SessionLike | None = None,
    attempts: int = 5,
) -> tuple[bytes, Mapping[str, str]]:
    _official_url(url)
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
                raise ValueError("empty Minfin response")
            return bytes(response.content), response.headers
        except (requests.RequestException, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(min(8.0, 0.25 * (2**attempt)))
    raise RuntimeError(f"Minfin request failed: {url}: {last_error}") from last_error


def _listing_url(page: int) -> str:
    if page < 1:
        raise ValueError("Minfin archive page must be positive")
    return ARCHIVE_URL if page == 1 else f"{ARCHIVE_URL}?page_39={page}"


def _fetch_many(
    requests_to_make: Sequence[tuple[str, str, str]],
    *,
    session: SessionLike | None,
    max_workers: int,
) -> list[RequestRecord]:
    def fetch(item: tuple[str, str, str]) -> RequestRecord:
        kind, identity, url = item
        content, headers = _request_bytes(url, session=session)
        return RequestRecord(kind, identity, url, content, headers)

    if session is not None or max_workers == 1:
        return [fetch(item) for item in requests_to_make]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(fetch, requests_to_make))


def discover_cards(
    *,
    session: SessionLike | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> tuple[list[AuctionCard], list[RequestRecord], int, bytes]:
    """Discover the bounded interval while proving reverse chronology and page stability."""
    first_content, first_headers = _request_bytes(ARCHIVE_URL, session=session)
    first = parse_listing_page(first_content, page=1)
    if first.page_count is None or first.page_count < 1:
        raise ValueError("Minfin archive has no result page count")
    raw_pages = [RequestRecord("listing", "1", ARCHIVE_URL, first_content, first_headers)]
    cards = list(first.cards)
    previous_date = cards[-1].publication_date
    saw_interval = any(SOURCE_START <= card.publication_date <= SOURCE_END for card in cards)
    page = 2
    stop = False
    while page <= first.page_count and not stop:
        pages = list(range(page, min(page + max_workers, first.page_count + 1)))
        records = _fetch_many(
            [("listing", str(value), _listing_url(value)) for value in pages],
            session=session,
            max_workers=max_workers,
        )
        for record, page_number in zip(records, pages, strict=True):
            parsed = parse_listing_page(record.content, page=page_number)
            raw_pages.append(record)
            if parsed.cards[0].publication_date > previous_date:
                raise ValueError("Minfin archive is not reverse-chronological across pages")
            previous_date = parsed.cards[-1].publication_date
            cards.extend(parsed.cards)
            saw_interval |= any(
                SOURCE_START <= card.publication_date <= SOURCE_END for card in parsed.cards
            )
            if saw_interval and max(card.publication_date for card in parsed.cards) < SOURCE_START:
                stop = True
                break
        page += len(pages)
    if not saw_interval or not stop:
        raise ValueError("Minfin archive did not bracket the requested interval")
    identities = [card.document_id for card in cards]
    if len(identities) != len(set(identities)):
        raise ValueError("Minfin archive contains duplicate result-card ids")
    second_content, _ = _request_bytes(ARCHIVE_URL, session=session)
    second = parse_listing_page(second_content, page=1)
    if second.cards != first.cards or second.page_count != first.page_count:
        raise ValueError("Minfin first-page result index changed during discovery")
    selected = [card for card in cards if SOURCE_START <= card.publication_date <= SOURCE_END]
    return selected, raw_pages, first.page_count, second_content


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


def download_minfin_ofz_auction_results(
    output_directory: Path = DEFAULT_OUTPUT,
    *,
    session: SessionLike | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    fetched_at_utc: str | None = None,
    minimum_primary_rows: int = 100,
) -> Path:
    """Write one immutable source-only bundle; never overwrite an existing bundle."""
    final = output_directory.resolve()
    if final.exists():
        raise FileExistsError(f"Minfin OFZ auction output already exists: {final}")
    if max_workers < 1:
        raise ValueError("max_workers must be positive")
    fetched_at = fetched_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    cards, listing_records, site_page_count, _ = discover_cards(
        session=session,
        max_workers=max_workers,
    )
    detail_records = _fetch_many(
        [("detail", str(card.document_id), card.detail_url) for card in cards],
        session=session,
        max_workers=max_workers,
    )
    parsed_rows: list[dict[str, object]] = []
    for card, record in zip(cards, detail_records, strict=True):
        try:
            parsed_rows.append(
                parse_result_detail(record.content, card=card, retrieved_at_utc=fetched_at)
            )
        except ValueError as error:
            raise ValueError(
                f"Minfin result {card.document_id} could not be parsed: {card.title}: {error}"
            ) from error
    frame = pd.DataFrame(parsed_rows).sort_values(
        ["publication_date", "document_id"], kind="mergesort", ignore_index=True
    )
    if frame["document_id"].duplicated().any():
        raise ValueError("Minfin processed events contain duplicate document ids")
    if frame["available_at"].ge(PROTECTED_FROM).any():
        raise ValueError("Minfin processed events crossed the protected boundary")
    primary = frame["event_kind"].eq("primary_result")
    if int(primary.sum()) < minimum_primary_rows:
        raise ValueError("Minfin primary-result coverage is unexpectedly small")
    primary_years = set(frame.loc[primary, "auction_date"].dt.year.astype(int).tolist())
    if primary_years != set(range(SOURCE_START.year, SOURCE_END.year + 1)):
        raise ValueError("Minfin primary results do not cover every requested year")
    float_columns = [
        "offered_volume_bln_rub",
        "demand_volume_bln_rub",
        "placed_volume_bln_rub",
        "placement_proceeds_bln_rub",
        "bid_to_cover",
        "cutoff_price_pct",
        "weighted_price_pct",
        "cutoff_yield_pct",
        "weighted_yield_pct",
    ]
    for column in float_columns:
        frame[column] = pd.array(frame[column], dtype="Float64")
    coverage = pd.DataFrame(
        [
            {
                "document_id": card.document_id,
                "listing_page": card.listing_page,
                "publication_date": pd.Timestamp(card.publication_date),
                "modified_date": pd.Timestamp(card.modified_date),
                "event_kind": str(
                    frame.loc[frame["document_id"].eq(card.document_id), "event_kind"].iloc[0]
                ),
                "title": card.title,
                "detail_url": card.detail_url,
                "attachment_url": card.attachment_url,
            }
            for card in cards
        ]
    ).sort_values(["publication_date", "document_id"], ignore_index=True)
    event_counts = Counter(frame["event_kind"].astype(str))
    primary_frame = frame.loc[primary]
    year_counts = Counter(primary_frame["auction_date"].dt.year.astype(int))
    publication_lag = (
        primary_frame["publication_date"] - primary_frame["auction_date"]
    ).dt.days
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        data_path = temporary / "minfin_ofz_auction_events.parquet"
        coverage_path = temporary / "coverage.parquet"
        raw_path = temporary / "official_minfin_ofz_auction_pages.jsonl.gz"
        _atomic_parquet(data_path, frame)
        _atomic_parquet(coverage_path, coverage)
        raw_lines = [_raw_record(record) for record in [*listing_records, *detail_records]]
        atomic_write_bytes(
            raw_path,
            gzip.compress(b"\n".join(raw_lines) + b"\n", compresslevel=6, mtime=0),
        )
        manifest_core = {
            "schema_version": 1,
            "source_id": "official-minfin-ofz-auction-results-current-vintage-2021-2025-v2",
            "provider": "Ministry of Finance of the Russian Federation",
            "source_name": "OFZ auction result records",
            "source_url": ARCHIVE_URL,
            "license_url": LICENSE_URL,
            "fetched_at_utc": fetched_at,
            "request_count": len(listing_records) + len(detail_records) + 1,
            "request_bounds": {
                "publication_from": SOURCE_START.isoformat(),
                "publication_through": SOURCE_END.isoformat(),
                "protected_from_utc": PROTECTED_FROM.isoformat(),
            },
            "coverage": {
                "site_result_page_count_at_retrieval": site_page_count,
                "listing_pages_fetched": len(listing_records),
                "source_interval_cards": len(cards),
                "event_kind_counts": dict(sorted(event_counts.items())),
                "primary_result_rows": int(primary.sum()),
                "primary_result_rows_by_auction_year": {
                    str(year): year_counts[year] for year in sorted(year_counts)
                },
                "minimum_publication_date": frame["publication_date"].min().date().isoformat(),
                "maximum_publication_date": frame["publication_date"].max().date().isoformat(),
                "minimum_auction_date": primary_frame["auction_date"].min().date().isoformat(),
                "maximum_auction_date": primary_frame["auction_date"].max().date().isoformat(),
                "maximum_publication_lag_days": int(publication_lag.max()),
                "modified_after_publication_date_count": int(
                    frame["modified_date"].gt(frame["publication_date"]).sum()
                ),
            },
            "temporal_semantics": {
                "publication_date": "date printed by Minfin on the result card",
                "available_at": "23:59:59 Europe/Moscow on the printed publication date",
                "admissible_join": "available_at less than or equal to decision_at",
                "date_only_source_uses_conservative_day_end": True,
                "current_vintage_historical_record": True,
                "original_historical_response_bytes_available": False,
                "historical_content_immutability_cryptographically_proved": False,
                "development_backtest_admissible": True,
                "independent_confirmation_without_forward_vintage_collection": False,
                "contains_prices_returns_targets_labels_or_pnl": False,
                "last_modified_used_for_availability": False,
            },
            "source_quality": {
                "archive_reverse_chronology_verified": True,
                "first_page_result_index_unchanged_during_discovery": True,
                "every_interval_card_classified": "other" not in event_counts,
                "every_primary_result_required_field_complete": True,
                "bid_to_cover_is_demand_divided_by_placed_volume": True,
                "auction_yields_nullable_for_floating_rate_ofz_pk": True,
            },
            "rights": {
                "site_footer_states_cc_by_4_0": True,
                "attribution_required": True,
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
                "raw_pages": {
                    "path": raw_path.name,
                    "bytes": raw_path.stat().st_size,
                    "sha256": sha256_file(raw_path),
                    "records": len(raw_lines),
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
    arguments = parser.parse_args()
    print(
        download_minfin_ofz_auction_results(
            arguments.output_directory,
            max_workers=arguments.max_workers,
        )
    )


if __name__ == "__main__":
    main()
