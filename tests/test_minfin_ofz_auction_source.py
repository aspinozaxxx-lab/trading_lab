"""Synthetic tests for the official Minfin OFZ auction-result source."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import minfin_ofz_auction_source as source


def _card(document_id: int, title: str, published: str, modified: str | None = None) -> str:
    changed = modified or published
    slug = f"{document_id}-synthetic"
    return f"""
    <div data-href="/ru/perfomance/public_debt/internal/operations/ofz/auction?id_39={slug}"
         class="document_card inner_link">
      <div class="document_info"><div class="date_list">
        <span class="date">Опубликовано: {published}</span>
        <span class="date">Изменено: {changed}</span>
      </div></div>
      <a class="document_title"
         href="/ru/perfomance/public_debt/internal/operations/ofz/auction?id_39={slug}"
         title="{title}">{title}</a>
      <div class="document_footer"><div class="files_info">
        <a class="file_item" href="/common/upload/{document_id}.doc">Документ</a>
      </div></div>
    </div>
    """


def _listing(cards: list[str], *, pages: int | None = None) -> bytes:
    pagination = (
        f'<a id="ajax-pagination-10090-39" data-page-count="{pages}"></a>'
        if pages is not None
        else ""
    )
    return f"<html>{pagination}{''.join(cards)}</html>".encode()


def _detail(
    issue: str,
    auction_date: str,
    maturity_date: str,
    *,
    ofz_type: str = "ПД",
    include_demand: bool = True,
) -> bytes:
    demand = "- объем спроса – 189,981 млрд. рублей;<br>" if include_demand else ""
    yields = (
        ""
        if ofz_type == "ПК"
        else (
            "- доходность по цене отсечения – 14,90% годовых;<br>"
            "- средневзвешенная доходность – 14,88% годовых.<br>"
        )
    )
    return f"""
    <html><div class="text_wrapper">
      <p>Минфин России информирует о результатах проведения {auction_date} г.
      аукциона по размещению ОФЗ-{ofz_type} выпуска № {issue}
      с датой погашения {maturity_date} г.</p>
      <p>Итоги размещения выпуска № {issue}:<br>
      - объем предложения – остаток, доступный для размещения;<br>
      {demand}
      - размещенный объем выпуска – 138,616 млрд. рублей;<br>
      - выручка от размещения – 119,443 млрд. рублей;<br>
      - цена отсечения – 83,5823% от номинала;<br>
      {yields}
      - средневзвешенная цена – 83,5915% от номинала.</p>
    </div></html>
    """.encode()


def _auction_card(
    document_id: int = 314741,
    *,
    title: str = "О результатах размещения ОФЗ выпуска № 26251RMFS на аукционе 3 декабря 2025 г.",
    publication_date: date = date(2025, 12, 3),
) -> source.AuctionCard:
    return source.AuctionCard(
        document_id=document_id,
        title=title,
        publication_date=publication_date,
        modified_date=publication_date,
        detail_url=(
            "https://minfin.gov.ru/ru/perfomance/public_debt/internal/operations/ofz/"
            f"auction?id_39={document_id}-synthetic"
        ),
        attachment_url=f"https://minfin.gov.ru/common/upload/{document_id}.doc",
        listing_page=1,
    )


def test_listing_parser_isolates_result_cards_and_dates() -> None:
    page = _listing(
        [
            _card(
                314741,
                "О результатах размещения ОФЗ выпуска № 26251RMFS на аукционе 3 декабря 2025 г.",
                "03.12.2025",
            ),
            _card(
                314735,
                "О результатах размещения ОФЗ выпуска № 26253RMFS на аукционе 3 декабря 2025 г.",
                "03.12.2025",
            ),
        ],
        pages=242,
    )

    parsed = source.parse_listing_page(page, page=13)

    assert parsed.page_count == 242
    assert [card.document_id for card in parsed.cards] == [314741, 314735]
    assert parsed.cards[0].publication_date == date(2025, 12, 3)
    assert parsed.cards[0].listing_page == 13
    assert parsed.cards[0].attachment_url == "https://minfin.gov.ru/common/upload/314741.doc"


def test_primary_detail_parses_metrics_and_conservative_availability() -> None:
    record = source.parse_result_detail(
        _detail("26251RMFS", "3 декабря 2025", "28 августа 2030"),
        card=_auction_card(),
        retrieved_at_utc="2026-09-01T00:00:00Z",
    )

    assert record["event_kind"] == "primary_result"
    assert record["available_at"] == pd.Timestamp("2025-12-03T20:59:59Z")
    assert record["auction_date"] == pd.Timestamp("2025-12-03")
    assert record["maturity_date"] == pd.Timestamp("2030-08-28")
    assert record["ofz_type"] == "ПД"
    assert record["demand_volume_bln_rub"] == 189.981
    assert record["placed_volume_bln_rub"] == 138.616
    assert record["bid_to_cover"] == pytest.approx(189.981 / 138.616)
    assert record["cutoff_yield_pct"] == 14.9
    assert record["weighted_yield_pct"] == 14.88


def test_ofz_pk_accepts_absent_yields() -> None:
    card = _auction_card(
        title="О результатах размещения ОФЗ выпуска № 29026RMFS на аукционе 4 декабря 2024 г.",
        publication_date=date(2024, 12, 4),
    )

    record = source.parse_result_detail(
        _detail("29026RMFS", "4 декабря 2024", "4 сентября 2038", ofz_type="ПК"),
        card=card,
        retrieved_at_utc="2026-09-01T00:00:00Z",
    )

    assert record["ofz_type"] == "ПК"
    assert record["cutoff_yield_pct"] is None
    assert record["weighted_yield_pct"] is None


def test_ofz_in_parses_real_yields() -> None:
    body = _detail("52005RMFS", "28 февраля 2024", "11 мая 2033", ofz_type="ИН")
    body = body.replace(
        "доходность по цене отсечения".encode(),
        "реальная доходность по цене отсечения".encode(),
    ).replace(
        "средневзвешенная доходность".encode(),
        "средневзвешенная реальная доходность".encode(),
    )
    card = _auction_card(
        title="О результатах размещения ОФЗ выпуска № 52005RMFS на аукционе 28 февраля 2024 г.",
        publication_date=date(2024, 2, 28),
    )

    record = source.parse_result_detail(
        body,
        card=card,
        retrieved_at_utc="2026-09-01T00:00:00Z",
    )

    assert record["ofz_type"] == "ИН"
    assert record["cutoff_yield_pct"] == 14.9
    assert record["weighted_yield_pct"] == 14.88


def test_primary_detail_fails_closed_on_missing_demand() -> None:
    with pytest.raises(ValueError, match="required fields"):
        source.parse_result_detail(
            _detail(
                "26251RMFS",
                "3 декабря 2025",
                "28 августа 2030",
                include_demand=False,
            ),
            card=_auction_card(),
            retrieved_at_utc="2026-09-01T00:00:00Z",
        )


def test_misleading_success_title_is_failed_when_body_says_auction_failed() -> None:
    body = """
    <html><div class="text_wrapper"><p>
    Министерство финансов сообщает, что аукцион по размещению ОФЗ-ПД выпуска
    № 26233RMFS 7 мая 2025 года признан несостоявшимся в связи с отсутствием заявок.
    </p></div></html>
    """.encode()
    card = _auction_card(
        title="О результатах размещения ОФЗ-ПД выпуска № 26233RMFS на аукционе 7 мая 2025 года",
        publication_date=date(2025, 5, 7),
    )

    record = source.parse_result_detail(
        body,
        card=card,
        retrieved_at_utc="2026-09-01T00:00:00Z",
    )

    assert record["event_kind"] == "failed_or_cancelled"
    assert record["issue_code"] == "26233RMFS"


def test_title_classification_keeps_non_primary_events_separate() -> None:
    assert source.classify_title("О результатах дополнительного размещения ОФЗ после аукциона") == (
        "supplemental_result"
    )
    assert (
        source.classify_title("Об уточнении результатов размещения ОФЗ на аукционе")
        == "correction"
    )
    assert source.classify_title("О признании аукциона ОФЗ несостоявшимся") == (
        "failed_or_cancelled"
    )
    assert source.classify_title("О проведении 7 декабря 2022 года аукционов ОФЗ") == (
        "auction_announcement"
    )


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str, *, headers: object, timeout: float) -> FakeResponse:
        del headers
        assert timeout == 60.0
        self.requested.append(url)
        return FakeResponse(self.pages[url])


def test_download_writes_hashed_target_free_bundle(tmp_path: Path) -> None:
    years = [2025, 2024, 2023, 2022, 2021]
    ids = [5005, 5004, 5003, 5002, 5001]
    russian_dates = {
        2025: "3 декабря 2025",
        2024: "4 декабря 2024",
        2023: "6 декабря 2023",
        2022: "7 декабря 2022",
        2021: "8 декабря 2021",
    }
    publication_days = {2025: 3, 2024: 4, 2023: 6, 2022: 7, 2021: 8}
    cards = [
        _card(
            document_id,
            (
                "О результатах размещения ОФЗ выпуска № 26251RMFS на аукционе "
                f"{russian_dates[year]} г."
            ),
            f"{publication_days[year]:02d}.12.{year}",
        )
        for document_id, year in zip(ids, years, strict=True)
    ]
    root = source.ARCHIVE_URL
    pages = {
        root: _listing(cards, pages=2),
        f"{root}?page_39=2": _listing(
            [_card(4000, "Справка по итогам размещения гособлигаций", "16.12.2020")]
        ),
    }
    for document_id, year in zip(ids, years, strict=True):
        detail_url = (
            "https://minfin.gov.ru/ru/perfomance/public_debt/internal/operations/ofz/"
            f"auction?id_39={document_id}-synthetic"
        )
        pages[detail_url] = _detail(
            "26251RMFS",
            russian_dates[year],
            "28 августа 2030",
        )
    session = FakeSession(pages)
    output = tmp_path / "bundle"

    result = source.download_minfin_ofz_auction_results(
        output,
        session=session,
        max_workers=1,
        fetched_at_utc="2026-09-01T00:00:00Z",
        minimum_primary_rows=5,
    )

    assert result == output.resolve()
    data = pd.read_parquet(output / "minfin_ofz_auction_events.parquet")
    coverage = pd.read_parquet(output / "coverage.parquet")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert len(data) == 5
    assert len(coverage) == 5
    assert set(data["auction_date"].dt.year) == set(years)
    assert manifest["coverage"]["primary_result_rows"] == 5
    assert manifest["temporal_semantics"]["contains_prices_returns_targets_labels_or_pnl"] is False
    assert manifest["source_quality"]["first_page_result_index_unchanged_during_discovery"] is True
    assert manifest["artifacts"]["raw_pages"]["records"] == 7
    assert (output / "manifest.json").read_bytes().startswith(b"\xef\xbb\xbf")
    with pytest.raises(FileExistsError):
        source.download_minfin_ofz_auction_results(output, session=session)


def test_protected_boundary_rejected() -> None:
    with pytest.raises(ValueError, match="protected"):
        source.conservative_available_at(date(2026, 1, 1))
