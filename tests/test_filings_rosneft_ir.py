"""Testy Rosneft IR metadata-adaptera bez real'nogo crawl, PDF, cen i targetov."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
import requests

from market_lab.filings.rosneft_ir import (
    ROSNEFT_IR_ROBOTS_HTTP_STATUS,
    RosneftIrArchiveAdapter,
    RosneftIrSettings,
    parse_rosneft_ir_archive_page,
    persist_rosneft_ir_crawl,
    rosneft_ir_access_policy,
    rosneft_ir_archive_page_url,
)

AUDIT_RETRIEVED_AT = datetime(2026, 8, 18, tzinfo=UTC)  # Fiksirovannoe test retrieval time.


class FakeResponse:
    """Imitiruet HTML response ili bounded HTTP-oshibku."""

    def __init__(
        self,
        content: bytes = b"",
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Sokhranyaet exact bytes, status i headers synthetic otveta."""
        self.content = content
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}

    def raise_for_status(self) -> None:
        """Podnimaet requests.HTTPError dlya status >= 400."""
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"synthetic HTTP {self.status_code}",
                response=self,
            )


class FakeSession:
    """Marshrutiziruet GET k synthetic responses i zapominaet vse URL."""

    def __init__(self, outcomes: dict[str, list[FakeResponse]]) -> None:
        """Prinimaet pocherednye responses dlya kazhdogo canonical page URL."""
        self.outcomes = outcomes
        self.calls: list[tuple[str, float]] = []
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: float) -> FakeResponse:
        """Vozvrashchaet sleduyushchii response bez seti."""
        self.calls.append((url, timeout))
        return self.outcomes[url].pop(0)

    def close(self) -> None:
        """Ne delaet nichego dlya vnedrennoi fake-session."""


def _html(
    entries: list[tuple[str, str, str]],
    next_page: int | None = None,
) -> bytes:
    """Stroit UTF-8 archive fixture s dd.date, canonical item i optional Next."""
    navigation = (
        f'<a href="/press/releases/{next_page}/">Next</a>'
        if next_page is not None
        else ""
    )
    releases = "".join(
        (
            '<dl class="simple_list">'
            f'<dd class="date">{published}</dd>'
            f'<dt><a href="/press/releases/item/{item_id}/">{title}</a></dt>'
            '<dd class="short"><p>Synthetic short text</p></dd>'
            "</dl>"
        )
        for published, title, item_id in entries
    )
    return f"<!doctype html><html><body>{navigation}{releases}</body></html>".encode()


def _authorized_settings(**changes: Any) -> RosneftIrSettings:
    """Stroit test-only permission gate bez pretenzii na real'noe pravo."""
    defaults: dict[str, Any] = {
        "written_permission_confirmed": True,
        "written_permission_reference": "synthetic-test-only",
        "minimum_request_interval_seconds": 0.0,
        "max_retries": 0,
    }
    defaults.update(changes)
    return RosneftIrSettings(**defaults)


def test_parser_uses_exact_moscow_dd_date_and_filters_results() -> None:
    """Izvlekaet IFRS event, no ne anons i ne obshchii press-reliz."""
    content = _html(
        [
            (
                "05 February 2019 12:34",
                "Financial results for 12M 2018 and 4Q 2018",
                "193743",
            ),
            ("04 February 2019 10:00", "Rosneft Opens a New Laboratory", "193700"),
            (
                "03 February 2019 09:00",
                "Rosneft will report its financial results on Tuesday",
                "193699",
            ),
        ],
        next_page=2,
    )

    parsed = parse_rosneft_ir_archive_page(
        content,
        rosneft_ir_archive_page_url(1),
        AUDIT_RETRIEVED_AT,
    )

    assert len(parsed.entries) == 1
    event = parsed.entries[0]
    assert event.item_id == "193743"
    assert event.canonical_url.endswith("/press/releases/item/193743/")
    assert event.canonical_title == "Financial results for 12M 2018 and 4Q 2018"
    assert event.published_at.isoformat() == "2019-02-05T12:34:00+03:00"
    assert event.published_at.astimezone(UTC).hour == 9
    assert not event.revision_log_available
    assert not event.model_eligible
    assert parsed.next_page_url == rosneft_ir_archive_page_url(2)


def test_parser_rejects_missing_year_noncanonical_url_and_holdout() -> None:
    """Ne pridumyvaet god, ne prinimaet vneshnii item URL i ne chitaet 2026."""
    missing_year = _html(
        [("05 February 12:34", "Financial results for 12M 2018", "193743")]
    )
    with pytest.raises(ValueError, match="exact day Month year"):
        parse_rosneft_ir_archive_page(
            missing_year,
            rosneft_ir_archive_page_url(1),
            AUDIT_RETRIEVED_AT,
        )
    external = missing_year.replace(
        b'/press/releases/item/193743/',
        b'https://example.com/press/releases/item/193743/',
    ).replace(b"05 February 12:34", b"05 February 2019 12:34")
    with pytest.raises(ValueError, match="limited.rosneft.com"):
        parse_rosneft_ir_archive_page(
            external,
            rosneft_ir_archive_page_url(1),
            AUDIT_RETRIEVED_AT,
        )
    holdout = _html(
        [("05 February 2026 12:34", "ROSNEFT FIRST QUARTER IFRS RESULTS", "224171")]
    )
    with pytest.raises(ValueError, match="holdout"):
        parse_rosneft_ir_archive_page(
            holdout,
            rosneft_ir_archive_page_url(1),
            AUDIT_RETRIEVED_AT,
        )


def test_permission_and_2026_guards_run_before_http() -> None:
    """Blokiruet bulk i holdout do pervogo Session.get."""
    page_url = rosneft_ir_archive_page_url(1)
    session = FakeSession({page_url: [FakeResponse(_html([]))]})
    blocked = RosneftIrArchiveAdapter(
        settings=RosneftIrSettings(minimum_request_interval_seconds=0.0),
        session=session,
    )
    with pytest.raises(PermissionError, match="pis'mennogo"):
        blocked.crawl(date(2018, 1, 1), date(2025, 12, 31))
    authorized = RosneftIrArchiveAdapter(
        settings=_authorized_settings(),
        session=session,
    )
    with pytest.raises(ValueError, match="holdout"):
        authorized.crawl(date(2025, 1, 1), date(2026, 1, 1))
    assert not session.calls


def test_bounded_crawl_keeps_raw_pages_and_never_fetches_item_or_pdf() -> None:
    """Listaet dve fake pages do 2017 cutoff i vybiraet tol'ko 2018-2025."""
    first_url = rosneft_ir_archive_page_url(1)
    second_url = rosneft_ir_archive_page_url(2)
    first = _html(
        [
            ("30 August 2025 10:35", "ROSNEFT FIRST HALF 2025 IFRS RESULTS", "222714"),
            ("21 July 2025 12:00", "Rosneft Holds Board Meeting", "222600"),
        ],
        next_page=2,
    )
    second = _html(
        [
            ("05 February 2018 12:00", "Financial results for FY 2017", "190001"),
            ("31 December 2017 09:00", "Rosneft Year-End Operations", "189999"),
        ]
    )
    session = FakeSession(
        {
            first_url: [FakeResponse(first)],
            second_url: [FakeResponse(second)],
        }
    )
    adapter = RosneftIrArchiveAdapter(
        settings=_authorized_settings(),
        session=session,
        utc_now=lambda: AUDIT_RETRIEVED_AT,
    )

    result = adapter.crawl(date(2018, 1, 1), date(2025, 12, 31))

    assert len(result.raw_pages) == 2
    assert [event.item_id for event in result.events] == ["190001", "222714"]
    assert result.raw_pages[0].content == first
    assert result.raw_pages[0].content_sha256 == hashlib.sha256(first).hexdigest()
    assert [url for url, _ in session.calls] == [first_url, second_url]
    assert all("/item/" not in url and not url.endswith(".pdf") for url, _ in session.calls)


def test_retry_is_bounded_and_honors_retry_after() -> None:
    """Povtoryaet odin 429, no ne vykhodit za max_retries."""
    page_url = rosneft_ir_archive_page_url(1)
    terminal = _html(
        [("31 December 2017 09:00", "Rosneft Year-End Operations", "189999")]
    )
    session = FakeSession(
        {
            page_url: [
                FakeResponse(status_code=429, headers={"Retry-After": "2"}),
                FakeResponse(terminal),
            ]
        }
    )
    delays: list[float] = []
    adapter = RosneftIrArchiveAdapter(
        settings=_authorized_settings(max_retries=1),
        session=session,
        sleeper=delays.append,
        utc_now=lambda: AUDIT_RETRIEVED_AT,
    )

    result = adapter.crawl(date(2018, 1, 1), date(2025, 12, 31))

    assert not result.events
    assert len(session.calls) == 2
    assert delays == [2.0]


def test_duplicate_or_revision_conflict_fails_closed() -> None:
    """Otklonyaet odin item ID s izmenennym title na sosednei stranice."""
    first_url = rosneft_ir_archive_page_url(1)
    second_url = rosneft_ir_archive_page_url(2)
    first = _html(
        [("30 August 2025 10:35", "ROSNEFT FIRST HALF 2025 IFRS RESULTS", "222714")],
        next_page=2,
    )
    second = _html(
        [
            (
                "29 August 2025 10:35",
                "ROSNEFT REVISED FIRST HALF 2025 IFRS RESULTS",
                "222714",
            ),
            ("31 December 2017 09:00", "Rosneft Year-End Operations", "189999"),
        ]
    )
    session = FakeSession(
        {
            first_url: [FakeResponse(first)],
            second_url: [FakeResponse(second)],
        }
    )
    adapter = RosneftIrArchiveAdapter(
        settings=_authorized_settings(),
        session=session,
        utc_now=lambda: AUDIT_RETRIEVED_AT,
    )

    with pytest.raises(ValueError, match="Konflikt/revision"):
        adapter.crawl(date(2018, 1, 1), date(2025, 12, 31))


def test_maximum_pages_fails_instead_of_silent_truncation() -> None:
    """Ne vydaet truncated crawl za polnyi, esli Next ostalsya posle limita."""
    page_url = rosneft_ir_archive_page_url(1)
    content = _html(
        [("30 August 2025 10:35", "ROSNEFT FIRST HALF 2025 IFRS RESULTS", "222714")],
        next_page=2,
    )
    session = FakeSession({page_url: [FakeResponse(content)]})
    adapter = RosneftIrArchiveAdapter(
        settings=_authorized_settings(maximum_pages=1),
        session=session,
        utc_now=lambda: AUDIT_RETRIEVED_AT,
    )

    with pytest.raises(ValueError, match="maximum_pages"):
        adapter.crawl(date(2018, 1, 1), date(2025, 12, 31))


def test_atomic_persistence_preserves_exact_html_and_provenance(tmp_path: Path) -> None:
    """Pishet raw bytes bez izmeneniya i BOM-manifest bez PDF/detail downloads."""
    page_url = rosneft_ir_archive_page_url(1)
    content = _html(
        [
            ("05 February 2018 12:00", "Financial results for FY 2017", "190001"),
            ("31 December 2017 09:00", "Rosneft Year-End Operations", "189999"),
        ]
    )
    session = FakeSession({page_url: [FakeResponse(content)]})
    result = RosneftIrArchiveAdapter(
        settings=_authorized_settings(),
        session=session,
        utc_now=lambda: AUDIT_RETRIEVED_AT,
    ).crawl(date(2018, 1, 1), date(2025, 12, 31))

    manifest_path = persist_rosneft_ir_crawl(tmp_path, result)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    raw_path = tmp_path / Path(manifest["raw_pages"][0]["path"])
    assert raw_path.read_bytes() == content
    assert manifest_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert manifest["raw_pages"][0]["content_sha256"] == hashlib.sha256(content).hexdigest()
    assert manifest["counts"] == {
        "raw_pages": 1,
        "financial_events": 1,
        "pdf_downloads": 0,
        "detail_page_downloads": 0,
    }
    assert manifest["limitations"]["revision_log_available"] is False
    assert manifest["limitations"]["model_eligible"] is False
    with pytest.raises(FileExistsError, match="revision overwrite"):
        persist_rosneft_ir_crawl(tmp_path, result)


def test_access_policy_records_robots_and_bulk_blocker() -> None:
    """Fiksiruet 404 robots, no ne traktuyet ego kak bulk-razreshenie."""
    policy = rosneft_ir_access_policy()
    assert policy.robots_http_status == ROSNEFT_IR_ROBOTS_HTTP_STATUS == 404
    assert not policy.bulk_research_approved
    assert policy.legal_url == "https://www.rosneft.ru/legal/"
