"""Bounded metadata-adapter IR Rosnefti s fail-closed pravami i PIT-vremenem."""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import requests

from market_lab.io_utils import atomic_write_bytes, write_json

ROSNEFT_IR_ARCHIVE_BASE_URL = (  # Oficial'nyi English archive press-relizov emitenta.
    "https://limited.rosneft.com/press/releases/"
)
ROSNEFT_IR_LEGAL_URL = (  # Oficial'nye obshchie usloviya svyazannyh saitov Rosnefti.
    "https://www.rosneft.ru/legal/"
)
ROSNEFT_IR_ROBOTS_URL = (  # Proverennyi robots endpoint limited-hosta.
    "https://limited.rosneft.com/robots.txt"
)
ROSNEFT_IR_TERMS_AUDITED_AT = date(2026, 8, 18)  # Data ruchnogo audita uslovii.
ROSNEFT_IR_ROBOTS_HTTP_STATUS = 404  # Faktivnyi status: robots.txt ne opublikovan.
ROSNEFT_IR_BULK_RESEARCH_APPROVED = False  # Site terms ne dayut bulk-prava po umolchaniyu.
ROSNEFT_IR_DEVELOPMENT_START = date(2018, 1, 1)  # Nachalo dopustimogo metadata-perioda.
ROSNEFT_IR_DEVELOPMENT_END = date(2025, 12, 31)  # Konec dopustimogo metadata-perioda.
ROSNEFT_IR_PROTECTED_FROM = date(2026, 1, 1)  # Nachalo zashchishchennogo holdout.
ROSNEFT_IR_TIMEZONE = ZoneInfo("Europe/Moscow")  # Zona tochnoi metki iz archive HTML.
ROSNEFT_IR_SCHEMA_VERSION = 1  # Versiya raw-page/event manifesta adaptera.
ROSNEFT_IR_USER_AGENT = (  # Identifikator bounded klienta bez maskirovki pod browser.
    "market-lab-research/0.7-rosneft-ir (+written-permission-required)"
)
ROSNEFT_IR_ITEM_PATH = re.compile(  # Edinstvennyi dopustimyi canonical release URL.
    r"^/press/releases/item/(?P<item_id>[1-9]\d*)/?$"
)
ROSNEFT_IR_PAGE_PATH = re.compile(  # Dopuskaet tol'ko numerovannye archive pages.
    r"^/press/releases/(?P<page>[1-9]\d*)/$"
)
ROSNEFT_IR_SHA256 = re.compile(r"^[0-9a-f]{64}$")  # Format provenance digest.
ROSNEFT_IR_DATE = re.compile(  # God obyazatelen: bez nego PIT-metka ne dokazuyema.
    r"^(?P<day>0[1-9]|[12]\d|3[01]) "
    r"(?P<month>[A-Za-z]+) "
    r"(?P<year>20\d{2}) "
    r"(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d)$"
)
ROSNEFT_IR_MONTHS = {  # Ne zavisit ot process locale pri razbore English HTML.
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
ROSNEFT_IR_RESULT_MARKERS = (  # Pozitivnye priznaki imenno reliza rezultatov.
    "financial results",
    "ifrs results",
    "results under ifrs",
)
ROSNEFT_IR_NON_RESULT_MARKERS = (  # Anonsy budushchego reliza ne schitayutsya otchetom.
    "will report",
    "to report",
    "conference call",
    "results presentation",
    "date of publication",
)


@dataclass(frozen=True, slots=True)
class RosneftIrAccessPolicy:
    """Fiksiruet audit robots/terms i otsutstvie avtomaticheskogo bulk-prava."""

    legal_url: str = ROSNEFT_IR_LEGAL_URL
    robots_url: str = ROSNEFT_IR_ROBOTS_URL
    audited_at: date = ROSNEFT_IR_TERMS_AUDITED_AT
    robots_http_status: int = ROSNEFT_IR_ROBOTS_HTTP_STATUS
    bulk_research_approved: bool = ROSNEFT_IR_BULK_RESEARCH_APPROVED
    limitation: str = (
        "Site terms razreshayut tol'ko odnu kopiyu dlya lichnogo nekommercheskogo "
        "ispol'zovaniya; bulk trebuet otdel'nogo pis'mennogo razresheniya Rosnefti."
    )


@dataclass(frozen=True, slots=True)
class RosneftIrSettings:
    """Zadaet bounded setevye limity i yavnoe dokazatel'stvo razresheniya."""

    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_backoff_seconds: float = 0.5
    maximum_retry_after_seconds: float = 30.0
    minimum_request_interval_seconds: float = 1.0
    maximum_pages: int = 128
    maximum_page_bytes: int = 2_000_000
    first_page: int = 1
    written_permission_confirmed: bool = False
    written_permission_reference: str | None = None

    def __post_init__(self) -> None:
        """Zapreshchaet beskonechnye limity i deklaraciyu prava bez ssylki."""
        if self.timeout_seconds <= 0.0:
            raise ValueError("timeout_seconds dolzhen byt' > 0")
        if self.max_retries < 0:
            raise ValueError("max_retries dolzhen byt' >= 0")
        if self.retry_backoff_seconds < 0.0:
            raise ValueError("retry_backoff_seconds dolzhen byt' >= 0")
        if self.maximum_retry_after_seconds <= 0.0:
            raise ValueError("maximum_retry_after_seconds dolzhen byt' > 0")
        if self.minimum_request_interval_seconds < 0.0:
            raise ValueError("minimum_request_interval_seconds dolzhen byt' >= 0")
        if self.maximum_pages <= 0:
            raise ValueError("maximum_pages dolzhen byt' > 0")
        if self.maximum_page_bytes <= 0:
            raise ValueError("maximum_page_bytes dolzhen byt' > 0")
        if self.first_page <= 0:
            raise ValueError("first_page dolzhen byt' > 0")
        if self.written_permission_confirmed and not (
            self.written_permission_reference
            and self.written_permission_reference.strip()
        ):
            raise ValueError("Podtverzhdennomu razresheniyu nuzhna audit-reference")
        if not self.written_permission_confirmed and self.written_permission_reference is not None:
            raise ValueError("Reference bez podtverzhdeniya prava nedopustima")


@dataclass(frozen=True, slots=True)
class RosneftIrRawPage:
    """Hranit original'nye archive-page bytes i polnuyu retrieval provenance."""

    page_number: int
    source_url: str
    retrieved_at: datetime
    content: bytes
    content_sha256: str
    media_type: str = "text/html"

    def __post_init__(self) -> None:
        """Proveryaet canonical page URL, aware retrieval time, bytes i SHA-256."""
        if self.page_number <= 0:
            raise ValueError("page_number dolzhen byt' > 0")
        expected = rosneft_ir_archive_page_url(self.page_number)
        if self.source_url != expected:
            raise ValueError("Raw page URL ne canonical dlya page_number")
        _require_aware(self.retrieved_at, "retrieved_at")
        if not self.content:
            raise ValueError("Raw archive-page bytes pusty")
        digest = hashlib.sha256(self.content).hexdigest()
        if self.content_sha256 != digest:
            raise ValueError("Raw archive-page SHA-256 ne sovpal")
        if self.media_type.lower() != "text/html":
            raise ValueError("Rosneft archive page dolzhna byt' text/html")


@dataclass(frozen=True, slots=True)
class RosneftIrEventMetadata:
    """Opisyvaet odin release-event bez PDF, teksta dokumenta, cen ili targetov."""

    source_event_id: str
    item_id: str
    canonical_url: str
    canonical_title: str
    published_at: datetime
    archive_page_url: str
    archive_page_sha256: str
    retrieved_at: datetime
    issuer_symbol: str = "ROSN"
    source_kind: str = "issuer_ir"
    filing_kind: str = "ifrs"
    revision_log_available: bool = False
    model_eligible: bool = False

    def __post_init__(self) -> None:
        """Zapreshchaet necanonical URL, holdout, bezvremennoe i model-ready sobytie."""
        expected_url, expected_id = _canonical_item_url(self.canonical_url)
        if expected_url != self.canonical_url or expected_id != self.item_id:
            raise ValueError("Event item_id/canonical_url ne soglasovany")
        if self.source_event_id != f"rosneft-ir-{self.item_id}":
            raise ValueError("source_event_id ne sootvetstvuet item_id")
        if self.canonical_title != _canonical_title(self.canonical_title):
            raise ValueError("canonical_title soderzhit nestabil'nye probely ili Unicode")
        if not _is_financial_results_title(self.canonical_title):
            raise ValueError("Event ne yavlyaetsya IFRS/financial-results release")
        _validate_development_timestamp(self.published_at)
        _require_aware(self.retrieved_at, "retrieved_at")
        if self.retrieved_at < self.published_at.astimezone(UTC):
            raise ValueError("retrieved_at ne mozhet byt' ran'she published_at")
        if ROSNEFT_IR_SHA256.fullmatch(self.archive_page_sha256) is None:
            raise ValueError("archive_page_sha256 imeet nekorrektnyi format")
        _validate_page_url(self.archive_page_url)
        if self.issuer_symbol != "ROSN" or self.source_kind != "issuer_ir":
            raise ValueError("Adapter podderzhivaet tol'ko ROSN issuer_ir")
        if self.filing_kind != "ifrs":
            raise ValueError("Rosneft financial-results event dolzhen byt' IFRS")
        if self.revision_log_available or self.model_eligible:
            raise ValueError("IR archive ne dokazyvaet revision-log i model eligibility")


@dataclass(frozen=True, slots=True)
class ParsedRosneftIrPage:
    """Vozvrashchaet vse validnye entries stranicy i ee bounded Next URL."""

    entries: tuple[RosneftIrEventMetadata, ...]
    all_publication_times: tuple[datetime, ...]
    next_page_url: str | None


@dataclass(frozen=True, slots=True)
class RosneftIrCrawlResult:
    """Hranit proverennye raw pages i tol'ko otobrannye financial events."""

    requested_start: date
    requested_end: date
    raw_pages: tuple[RosneftIrRawPage, ...]
    events: tuple[RosneftIrEventMetadata, ...]
    permission_reference: str

    def __post_init__(self) -> None:
        """Dokazyvaet period, polnotu page provenance i otsutstvie dublikatov."""
        _validate_period(self.requested_start, self.requested_end)
        if not self.raw_pages:
            raise ValueError("Crawl result ne mozhet byt' bez raw pages")
        if not self.permission_reference.strip():
            raise ValueError("Crawl result trebuet permission_reference")
        page_urls = {page.source_url for page in self.raw_pages}
        for event in self.events:
            if event.archive_page_url not in page_urls:
                raise ValueError("Event ssylayetsya na otsutstvuyushchuyu raw page")
            event_date = event.published_at.astimezone(ROSNEFT_IR_TIMEZONE).date()
            if not self.requested_start <= event_date <= self.requested_end:
                raise ValueError("Event vyshel iz requested period")
        _assert_unique_events(self.events)


@dataclass(slots=True)
class _RawHtmlEntry:
    """Vremenno hranit literal'nye date/href/title iz odnogo simple_list."""

    date_text: str
    href: str
    title: str


class _RosneftArchiveHtmlParser(HTMLParser):
    """Izvlekaet tol'ko dl.simple_list i archive Next iz stdlib HTML parsera."""

    def __init__(self) -> None:
        """Inicializiruet strogie odinochnye capture-polya."""
        super().__init__(convert_charrefs=True)
        self.entries: list[_RawHtmlEntry] = []
        self.next_href: str | None = None
        self._in_release = False
        self._date_capture = False
        self._title_capture = False
        self._nav_capture = False
        self._date_parts: list[str] = []
        self._title_parts: list[str] = []
        self._nav_parts: list[str] = []
        self._href: str | None = None
        self._nav_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Nachinaet capture release/date/title ili vneshnei navigation ssylki."""
        attributes = {key.lower(): value for key, value in attrs}
        classes = set((attributes.get("class") or "").split())
        lowered = tag.lower()
        if lowered == "dl" and "simple_list" in classes:
            if self._in_release:
                raise ValueError("Vlozhennyi dl.simple_list nedopustim")
            self._in_release = True
            self._date_parts = []
            self._title_parts = []
            self._href = None
            return
        if self._in_release and lowered == "dd" and "date" in classes:
            if self._date_capture or self._date_parts:
                raise ValueError("Povtor dd.date v odnom release")
            self._date_capture = True
            return
        if self._in_release and lowered == "a" and attributes.get("href"):
            if self._title_capture or self._href is not None:
                raise ValueError("Povtor release href v odnom simple_list")
            self._title_capture = True
            self._href = str(attributes["href"])
            return
        if not self._in_release and lowered == "a" and attributes.get("href"):
            self._nav_capture = True
            self._nav_href = str(attributes["href"])
            self._nav_parts = []

    def handle_data(self, data: str) -> None:
        """Nakaplivaet text tol'ko aktivnogo date/title/navigation capture."""
        if self._date_capture:
            self._date_parts.append(data)
        if self._title_capture:
            self._title_parts.append(data)
        if self._nav_capture:
            self._nav_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        """Zavershaet capture i fail-closed fiksiruet release pri zakrytii dl."""
        lowered = tag.lower()
        if lowered == "dd" and self._date_capture:
            self._date_capture = False
            return
        if lowered == "a" and self._title_capture:
            self._title_capture = False
            return
        if lowered == "a" and self._nav_capture:
            label = _canonical_title("".join(self._nav_parts))
            if label.casefold() == "next":
                if self.next_href is not None and self.next_href != self._nav_href:
                    raise ValueError("Archive HTML soderzhit dva raznyh Next href")
                self.next_href = self._nav_href
            self._nav_capture = False
            self._nav_href = None
            self._nav_parts = []
            return
        if lowered == "dl" and self._in_release:
            date_text = _canonical_title("".join(self._date_parts))
            title = _canonical_title("".join(self._title_parts))
            if not date_text or not title or self._href is None:
                raise ValueError("dl.simple_list ne soderzhit odin date/title/href")
            self.entries.append(_RawHtmlEntry(date_text, self._href, title))
            self._in_release = False
            self._date_parts = []
            self._title_parts = []
            self._href = None

    def finish(self) -> None:
        """Proveryaet, chto HTML ne oborvalsya posredi release/capture."""
        if self._in_release or self._date_capture or self._title_capture:
            raise ValueError("Archive HTML oborvan posredi release")
        if not self.entries:
            raise ValueError("Archive HTML ne soderzhit dl.simple_list")


def rosneft_ir_access_policy() -> RosneftIrAccessPolicy:
    """Vozvrashchaet konservativnyi audit: bulk po umolchaniyu ne razreshen."""
    return RosneftIrAccessPolicy()


def require_rosneft_ir_written_permission(settings: RosneftIrSettings) -> None:
    """Fail-closed trebuet vneshnee pis'mennoe razreshenie pered HTTP."""
    if not settings.written_permission_confirmed or not settings.written_permission_reference:
        raise PermissionError(
            "Bulk Rosneft IR zapreshchen site terms bez otdel'nogo pis'mennogo razresheniya"
        )


def rosneft_ir_archive_page_url(page_number: int) -> str:
    """Stroit canonical HTTPS URL odnoi numerovannoi archive-page."""
    if page_number <= 0:
        raise ValueError("page_number dolzhen byt' > 0")
    return f"{ROSNEFT_IR_ARCHIVE_BASE_URL}{page_number}/"


def parse_rosneft_ir_archive_page(
    content: bytes,
    page_url: str,
    retrieved_at: datetime,
) -> ParsedRosneftIrPage:
    """Strogo parse-it date/title/item URL, ne zagruzhaya item ili PDF."""
    _require_aware(retrieved_at, "retrieved_at")
    page_number = _validate_page_url(page_url)
    try:
        html = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("Archive page ne yavlyaetsya validnym UTF-8") from error
    parser = _RosneftArchiveHtmlParser()
    parser.feed(html)
    parser.close()
    parser.finish()
    page_hash = hashlib.sha256(content).hexdigest()
    events: list[RosneftIrEventMetadata] = []
    all_times: list[datetime] = []
    seen_urls: set[str] = set()
    for raw in parser.entries:
        published_at = _parse_moscow_timestamp(raw.date_text)
        _validate_not_protected_timestamp(published_at)
        canonical_url, item_id = _canonical_item_url(urljoin(page_url, raw.href))
        if canonical_url in seen_urls:
            raise ValueError("Povtor canonical release URL na odnoi archive-page")
        seen_urls.add(canonical_url)
        all_times.append(published_at)
        local_date = published_at.astimezone(ROSNEFT_IR_TIMEZONE).date()
        if (
            _is_financial_results_title(raw.title)
            and local_date >= ROSNEFT_IR_DEVELOPMENT_START
        ):
            events.append(
                RosneftIrEventMetadata(
                    source_event_id=f"rosneft-ir-{item_id}",
                    item_id=item_id,
                    canonical_url=canonical_url,
                    canonical_title=raw.title,
                    published_at=published_at,
                    archive_page_url=page_url,
                    archive_page_sha256=page_hash,
                    retrieved_at=retrieved_at.astimezone(UTC),
                )
            )
    if any(
        later > earlier
        for earlier, later in zip(all_times, all_times[1:], strict=False)
    ):
        raise ValueError("Archive releases ne otsortirovany po ubivaniyu vremeni")
    next_url: str | None = None
    if parser.next_href is not None:
        candidate = urljoin(page_url, parser.next_href)
        next_page = _validate_page_url(candidate)
        if next_page != page_number + 1:
            raise ValueError("Archive Next ne vedet na sleduyushchuyu stranicu")
        next_url = rosneft_ir_archive_page_url(next_page)
    return ParsedRosneftIrPage(tuple(events), tuple(all_times), next_url)


class RosneftIrArchiveAdapter:
    """Bounded-poluchaet tol'ko archive HTML posle yavnogo pravovogo gate."""

    def __init__(
        self,
        settings: RosneftIrSettings | None = None,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] | None = None,
    ) -> None:
        """Sokhranyaet lazy session i vnedryaemye clock/sleeper dlya testov."""
        self.settings = settings or RosneftIrSettings()
        self._session = session
        self._owns_session = False
        self.sleeper = sleeper
        self.monotonic = monotonic
        self.utc_now = utc_now or (lambda: datetime.now(UTC))
        self._last_request_at: float | None = None

    def close(self) -> None:
        """Zakryvaet tol'ko lazy-session, sozdannuyu samim adapterom."""
        if self._owns_session and self._session is not None:
            self._session.close()
        self._session = None
        self._owns_session = False

    def __enter__(self) -> RosneftIrArchiveAdapter:
        """Vozvrashchaet adapter dlya upravlyaemogo konteksta."""
        return self

    def __exit__(self, *_: object) -> None:
        """Garantirovanno zakryvaet sobstvennuyu setevuyu sessiyu."""
        self.close()

    def crawl(self, start_date: date, end_date: date) -> RosneftIrCrawlResult:
        """Listaet archive do cutoff, no ne chitaet item/PDF i ne zapisivaet ceny."""
        _validate_period(start_date, end_date)
        require_rosneft_ir_written_permission(self.settings)
        page_number = self.settings.first_page
        raw_pages: list[RosneftIrRawPage] = []
        events: list[RosneftIrEventMetadata] = []
        previous_oldest: datetime | None = None
        reached_cutoff = False
        for _ in range(self.settings.maximum_pages):
            page_url = rosneft_ir_archive_page_url(page_number)
            content = self._request_page(page_url)
            retrieved_at = self.utc_now().astimezone(UTC)
            parsed = parse_rosneft_ir_archive_page(content, page_url, retrieved_at)
            newest = parsed.all_publication_times[0]
            oldest = parsed.all_publication_times[-1]
            if previous_oldest is not None and newest > previous_oldest:
                raise ValueError("Archive pages narushayut global'nyi hronologicheskii poryadok")
            previous_oldest = oldest
            page = RosneftIrRawPage(
                page_number=page_number,
                source_url=page_url,
                retrieved_at=retrieved_at,
                content=content,
                content_sha256=hashlib.sha256(content).hexdigest(),
            )
            raw_pages.append(page)
            events.extend(
                event
                for event in parsed.entries
                if start_date
                <= event.published_at.astimezone(ROSNEFT_IR_TIMEZONE).date()
                <= end_date
            )
            if oldest.astimezone(ROSNEFT_IR_TIMEZONE).date() < start_date:
                reached_cutoff = True
                break
            if parsed.next_page_url is None:
                reached_cutoff = True
                break
            page_number = _validate_page_url(parsed.next_page_url)
        if not reached_cutoff:
            raise ValueError("Rosneft IR crawl dostig maximum_pages do vremennogo cutoff")
        ordered = tuple(
            sorted(events, key=lambda item: (item.published_at, item.canonical_url))
        )
        _assert_unique_events(ordered)
        return RosneftIrCrawlResult(
            requested_start=start_date,
            requested_end=end_date,
            raw_pages=tuple(raw_pages),
            events=ordered,
            permission_reference=str(self.settings.written_permission_reference),
        )

    def _network_session(self) -> requests.Session:
        """Sozdaet requests.Session lenivo tol'ko posle period/permission guards."""
        if self._session is None:
            self._session = requests.Session()
            self._owns_session = True
            self._session.headers.update({"User-Agent": ROSNEFT_IR_USER_AGENT})
        return self._session

    def _pace(self) -> None:
        """Vyderzhivaet minimal'nyi interval mezhdu posledovatel'nymi GET."""
        now = self.monotonic()
        if self._last_request_at is not None:
            remaining = (
                self.settings.minimum_request_interval_seconds - (now - self._last_request_at)
            )
            if remaining > 0.0:
                self.sleeper(remaining)
        self._last_request_at = self.monotonic()

    def _request_page(self, url: str) -> bytes:
        """Vypolnyaet bounded retry tol'ko dlya timeout, 429 i 5xx otvetov."""
        _validate_page_url(url)
        session = self._network_session()
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retries + 1):
            try:
                self._pace()
                response = session.get(url, timeout=self.settings.timeout_seconds)
                response.raise_for_status()
                media_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0]
                if media_type.lower() != "text/html":
                    raise ValueError("Rosneft archive response ne yavlyaetsya text/html")
                content = bytes(response.content)
                if not content or len(content) > self.settings.maximum_page_bytes:
                    raise ValueError("Rosneft archive response pust ili prevysil byte-limit")
                return content
            except (requests.RequestException, ValueError) as error:
                last_error = error
                if attempt >= self.settings.max_retries:
                    break
                response = getattr(error, "response", None)
                status = getattr(response, "status_code", None)
                if status is not None and status != 429 and int(status) < 500:
                    break
                retry_after = 0.0
                if response is not None:
                    raw_retry_after = response.headers.get("Retry-After")
                    try:
                        retry_after = float(raw_retry_after) if raw_retry_after else 0.0
                    except ValueError:
                        retry_after = 0.0
                exponential = self.settings.retry_backoff_seconds * (2**attempt)
                delay = min(
                    max(retry_after, exponential),
                    self.settings.maximum_retry_after_seconds,
                )
                if delay > 0.0:
                    self.sleeper(delay)
        raise RuntimeError(
            f"Ne udalos' poluchit' Rosneft IR page {url}: {last_error}"
        ) from last_error


def persist_rosneft_ir_crawl(project_root: Path, result: RosneftIrCrawlResult) -> Path:
    """Atomarno pishet exact raw pages i final manifest tol'ko posle vseh proverok."""
    root = project_root.resolve()
    raw_root = root / "data" / "raw" / "filings" / "rosneft_ir" / "archive_pages"
    processed_root = root / "data" / "processed" / "filings" / "rosneft_ir"
    manifest_path = processed_root / (
        f"manifest_{result.requested_start.isoformat()}_{result.requested_end.isoformat()}.json"
    )
    _assert_inside(root, raw_root)
    _assert_inside(root, manifest_path)
    if manifest_path.exists():
        raise FileExistsError(
            "Rosneft IR manifest uzhe sushchestvuet; revision overwrite zapreshchen"
        )
    page_records: list[dict[str, Any]] = []
    planned_paths: list[Path] = []
    for page in result.raw_pages:
        filename = f"page_{page.page_number:04d}_{page.content_sha256[:12]}.html"
        path = raw_root / filename
        _assert_inside(root, path)
        if path.exists():
            raise FileExistsError("Rosneft IR raw page uzhe sushchestvuet")
        planned_paths.append(path)
        page_records.append(
            {
                "page_number": page.page_number,
                "source_url": page.source_url,
                "retrieved_at": page.retrieved_at,
                "content_sha256": page.content_sha256,
                "byte_size": len(page.content),
                "media_type": page.media_type,
                "path": path.relative_to(root).as_posix(),
            }
        )
    for page, path in zip(result.raw_pages, planned_paths, strict=True):
        atomic_write_bytes(path, page.content)
    policy = rosneft_ir_access_policy()
    manifest = {
        "schema_version": ROSNEFT_IR_SCHEMA_VERSION,
        "source": "official Rosneft issuer IR archive metadata",
        "issuer_symbol": "ROSN",
        "requested_start": result.requested_start,
        "requested_end": result.requested_end,
        "protected_from": ROSNEFT_IR_PROTECTED_FROM,
        "access_policy": asdict(policy),
        "written_permission_reference": result.permission_reference,
        "counts": {
            "raw_pages": len(result.raw_pages),
            "financial_events": len(result.events),
            "pdf_downloads": 0,
            "detail_page_downloads": 0,
        },
        "limitations": {
            "revision_log_available": False,
            "model_eligible": False,
            "reason": "Issuer archive ne predostavlyaet dokazannyi revision event-log.",
        },
        "raw_pages": page_records,
        "events": [_event_to_mapping(event) for event in result.events],
    }
    write_json(manifest_path, manifest)
    return manifest_path


def _event_to_mapping(event: RosneftIrEventMetadata) -> dict[str, Any]:
    """Prevrashchaet metadata event v stabil'no JSON-ready predstavlenie."""
    payload = asdict(event)
    payload["published_at"] = event.published_at.isoformat()
    payload["retrieved_at"] = event.retrieved_at.isoformat()
    return payload


def _validate_period(start_date: date, end_date: date) -> None:
    """Razreshaet tol'ko 2018-2025 i blokiruet 2026 do seti."""
    if end_date < start_date:
        raise ValueError("end_date ran'she start_date")
    if start_date < ROSNEFT_IR_DEVELOPMENT_START:
        raise ValueError("Rosneft IR start_date ran'she 2018-01-01")
    if end_date > ROSNEFT_IR_DEVELOPMENT_END or end_date >= ROSNEFT_IR_PROTECTED_FROM:
        raise ValueError("Zapreshchen dostup k Rosneft IR holdout s 2026-01-01")


def _require_aware(value: datetime, field_name: str) -> None:
    """Zapreshchaet timestamp bez timezone-offset."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} dolzhen soderzhat' timezone")


def _validate_development_timestamp(value: datetime) -> None:
    """Proveryaet aware Moscow timestamp v strogoi development-granice."""
    _require_aware(value, "published_at")
    local_date = value.astimezone(ROSNEFT_IR_TIMEZONE).date()
    if not ROSNEFT_IR_DEVELOPMENT_START <= local_date <= ROSNEFT_IR_DEVELOPMENT_END:
        raise ValueError("published_at vyshel iz 2018-2025 ili popal v holdout")


def _validate_not_protected_timestamp(value: datetime) -> None:
    """Dopuskaet staryi cutoff, no blokiruet lyubuyu metadata s 2026 goda."""
    _require_aware(value, "published_at")
    if value.astimezone(ROSNEFT_IR_TIMEZONE).date() >= ROSNEFT_IR_PROTECTED_FROM:
        raise ValueError("published_at popal v zashchishchennyi holdout")


def _parse_moscow_timestamp(value: str) -> datetime:
    """Chitaet exact dd Month YYYY HH:MM i lokalizuet kak Europe/Moscow."""
    canonical = _canonical_title(value)
    match = ROSNEFT_IR_DATE.fullmatch(canonical)
    if match is None:
        raise ValueError("dd.date dolzhen soderzhat' exact day Month year HH:MM")
    month = ROSNEFT_IR_MONTHS.get(match.group("month").casefold())
    if month is None:
        raise ValueError("Neizvestnyi English month v dd.date")
    try:
        return datetime(
            int(match.group("year")),
            month,
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            tzinfo=ROSNEFT_IR_TIMEZONE,
        )
    except ValueError as error:
        raise ValueError("Nesushchestvuyushchaya data v dd.date") from error


def _canonical_title(value: str) -> str:
    """Normalizuet Unicode NFC i HTML-probely bez semanticheskogo perevoda."""
    normalized = unicodedata.normalize("NFC", value).replace("\xa0", " ")
    return " ".join(normalized.split())


def _is_financial_results_title(title: str) -> bool:
    """Otlichaet vypushchennye IFRS/financial results ot anonsov i prezentacii."""
    normalized = _canonical_title(title).casefold()
    if any(marker in normalized for marker in ROSNEFT_IR_NON_RESULT_MARKERS):
        return False
    if "ifrs" in normalized and "result" in normalized:
        return True
    return any(marker in normalized for marker in ROSNEFT_IR_RESULT_MARKERS)


def _canonical_item_url(value: str) -> tuple[str, str]:
    """Proveryaet official host/path i ubiraet query/fragment iz item URL."""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "limited.rosneft.com":
        raise ValueError("Release URL dolzhen byt' na limited.rosneft.com po HTTPS")
    if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise ValueError("Release URL ne dolzhen imet' auth/port/query/fragment")
    match = ROSNEFT_IR_ITEM_PATH.fullmatch(parsed.path)
    if match is None:
        raise ValueError("Release URL ne sootvetstvuet /press/releases/item/<id>/")
    item_id = match.group("item_id")
    canonical = urlunsplit(
        ("https", "limited.rosneft.com", f"/press/releases/item/{item_id}/", "", "")
    )
    return canonical, item_id


def _validate_page_url(value: str) -> int:
    """Proveryaet numerovannyi archive URL bez redirekta na item/PDF/2026 route."""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname != "limited.rosneft.com":
        raise ValueError("Archive page dolzhna byt' na limited.rosneft.com po HTTPS")
    if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise ValueError("Archive page URL ne dolzhen imet' auth/port/query/fragment")
    match = ROSNEFT_IR_PAGE_PATH.fullmatch(parsed.path)
    if match is None:
        raise ValueError("Archive page URL dolzhen byt' numerovannym /press/releases/N/")
    page = int(match.group("page"))
    if value != rosneft_ir_archive_page_url(page):
        raise ValueError("Archive page URL ne canonical")
    return page


def _assert_unique_events(events: Sequence[RosneftIrEventMetadata]) -> None:
    """Fail-closed otklonyaet lyuboi duplicate ili konflikt revision metadata."""
    by_id: dict[str, RosneftIrEventMetadata] = {}
    by_url: dict[str, RosneftIrEventMetadata] = {}
    by_title_time: dict[tuple[str, datetime], RosneftIrEventMetadata] = {}
    for event in events:
        keys = (
            (by_id, event.source_event_id, "source_event_id"),
            (by_url, event.canonical_url, "canonical_url"),
            (
                by_title_time,
                (event.canonical_title, event.published_at),
                "title/published_at",
            ),
        )
        for registry, key, label in keys:
            previous = registry.get(key)  # type: ignore[arg-type]
            if previous is not None:
                if previous == event:
                    raise ValueError(f"Duplicate Rosneft IR event po {label}")
                raise ValueError(f"Konflikt/revision Rosneft IR event po {label}")
            registry[key] = event  # type: ignore[index]


def _assert_inside(root: Path, path: Path) -> None:
    """Zapreshchaet vyhod raw/manifest puti iz project root."""
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError("Rosneft IR put' vyshel iz project root")
