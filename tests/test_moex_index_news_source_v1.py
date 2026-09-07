"""Synthetic source-only checks for the MOEX index-news catalogue."""

from __future__ import annotations

import hashlib
import json

import pytest

from market_lab.stocks import moex_index_news_source_v1 as source


def _encode(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _listing(
    *,
    clock_only: bool = False,
    rows: list[list[object]] | None = None,
    index: int = 100,
    page_size: int = 2,
) -> dict[str, object]:
    columns = ["id", "published_at"]
    if not clock_only:
        columns.append("title")
    if rows is None:
        rows = [[41, "2025-03-05 17:54:00"], [40, "2025-02-28 08:35:00"]]
        if not clock_only:
            rows[0].append("Новые базы расчета индексов")
            rows[1].append("Об изменении состава индекса")
    return {
        "sitenews": {"columns": columns, "data": rows},
        "sitenews.cursor": {
            "columns": ["INDEX", "TOTAL", "PAGESIZE"],
            "data": [[index, 200, page_size]],
        },
    }


def _article(
    *,
    news_id: int = 41,
    stamp: str = "2025-03-05 17:54:00",
    body: str = "<p>Сообщение о составе индекса.</p>",
) -> dict[str, object]:
    return {
        "content": {
            "columns": ["id", "title", "published_at", "body"],
            "data": [[news_id, "Новые базы расчета индексов", stamp, body]],
        }
    }


def test_clock_listing_accepts_only_metadata_including_protected_year() -> None:
    payload = _listing(clock_only=True, rows=[[51, "2026-09-07 09:00:00"]])
    rows, cursor = source.parse_listing(_encode(payload), expected_start=100, clock_only=True)
    assert rows == [{"id": 51, "published_at": "2026-09-07 09:00:00"}]
    assert cursor == {"INDEX": 100, "TOTAL": 200, "PAGESIZE": 2}


def test_catalog_listing_preserves_ids_stamps_and_titles() -> None:
    rows, cursor = source.parse_listing(_encode(_listing()), expected_start=100, clock_only=False)
    assert rows == [
        {
            "id": 41,
            "published_at": "2025-03-05 17:54:00",
            "title": "Новые базы расчета индексов",
        },
        {
            "id": 40,
            "published_at": "2025-02-28 08:35:00",
            "title": "Об изменении состава индекса",
        },
    ]
    assert cursor["INDEX"] == 100


def test_duplicate_listing_id_fails_closed() -> None:
    payload = _listing(rows=[[41, "2025-03-05 17:54:00", "А"], [41, "2025-02-28 08:35:00", "Б"]])
    with pytest.raises(ValueError):
        source.parse_listing(_encode(payload), expected_start=100, clock_only=False)


def test_wrong_cursor_index_or_columns_fails_closed() -> None:
    with pytest.raises(ValueError):
        source.parse_listing(_encode(_listing(index=101)), expected_start=100, clock_only=False)
    payload = _listing()
    payload["sitenews.cursor"] = {
        "columns": ["INDEX", "TOTAL", "PAGESIZE", "UNKNOWN"],
        "data": [[100, 200, 2, 1]],
    }
    with pytest.raises(ValueError):
        source.parse_listing(_encode(payload), expected_start=100, clock_only=False)


def test_unexpected_listing_columns_fail_in_both_modes() -> None:
    with pytest.raises(ValueError):
        source.parse_listing(_encode(_listing()), expected_start=100, clock_only=True)
    payload = _listing()
    payload["sitenews"] = {
        "columns": ["id", "published_at", "title", "synthetic_market_value"],
        "data": [[41, "2025-03-05 17:54:00", "А", 1]],
    }
    with pytest.raises(ValueError):
        source.parse_listing(_encode(payload), expected_start=100, clock_only=False)


def test_invalid_listing_timestamp_fails_closed() -> None:
    payload = _listing(rows=[[41, "2025-02-30 17:54:00", "А"]])
    with pytest.raises(ValueError):
        source.parse_listing(_encode(payload), expected_start=100, clock_only=False)


def test_ascending_listing_chronology_fails_closed() -> None:
    payload = _listing(rows=[[40, "2025-02-28 08:35:00", "А"], [41, "2025-03-05 17:54:00", "Б"]])
    with pytest.raises(ValueError):
        source.parse_listing(_encode(payload), expected_start=100, clock_only=False)


def test_more_listing_rows_than_page_size_fails_closed() -> None:
    with pytest.raises(ValueError):
        source.parse_listing(_encode(_listing(page_size=1)), expected_start=100, clock_only=False)


def test_catalog_protected_timestamp_fails_closed() -> None:
    payload = _listing(rows=[[51, "2026-01-01 00:00:00", "Изменение состава индекса"]])
    with pytest.raises(ValueError):
        source.parse_listing(_encode(payload), expected_start=100, clock_only=False)


def test_title_classification_is_discovery_not_event_extraction() -> None:
    for title in (
        "НОВЫЕ БАЗЫ РАСЧЕТА ИНДЕКСОВ",
        "Об изменении состава индекса",
        "Список акций индекса",
        "Включение в индекс",
        "Исключение из индекса",
        "Пересмотр индексов",
        "Перечни бумаг для индекса",
        "Изменения индексных коэффициентов",
    ):
        assert source.classify_title(title) == "candidate_index_change"
    assert source.classify_title("Методология индекса") == "other_index_news"
    assert source.classify_title("Изменение состава совета директоров") == "non_index_news"


def test_article_keeps_mixed_index_dates_waitlists_and_free_float_as_text() -> None:
    paragraphs = [
        "С 21 марта 2025 года изменяется состав первого индекса.",
        "С 1 апреля 2025 года изменяется состав другого индекса.",
        "В лист ожидания включены акции условного эмитента.",
        "Коэффициент free-float указан в отдельной таблице.",
    ]
    body = "".join(f"<p>{paragraph}</p>" for paragraph in paragraphs)
    result = source.parse_article(
        _encode(_article(body=body)), news_id=41, expected_stamp="2025-03-05 17:54:00"
    )
    assert result["id"] == 41
    assert result["title"] == "Новые базы расчета индексов"
    assert result["published_at_raw"] == "2025-03-05 17:54:00"
    assert result["paragraphs"] == paragraphs
    assert result["body_sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert result["original_version_verified"] is False
    assert result["historical_model_eligible"] is False
    assert result["available_at"] is None
    assert "effective_date" not in result
    assert "security_operations" not in result


def test_article_excludes_script_and_style_content_and_unescapes_text() -> None:
    body = (
        "<script>СИНТЕТИЧЕСКИЙ ТЕКУЩИЙ ВИДЖЕТ 2026: 123</script>"
        "<style>.виджет { content: 'СКРЫТЫЙ ТЕКСТ'; }</style>"
        "<p>Индекс &amp; состав: <strong>обыкновенные акции</strong>.</p>"
    )
    result = source.parse_article(
        _encode(_article(body=body)), news_id=41, expected_stamp="2025-03-05 17:54:00"
    )
    assert result["paragraphs"] == ["Индекс & состав: обыкновенные акции."]
    assert "ВИДЖЕТ" not in " ".join(result["paragraphs"])
    assert "СКРЫТЫЙ" not in " ".join(result["paragraphs"])


def test_article_rejects_protected_publication_date() -> None:
    stamp = "2026-01-01 00:00:00"
    with pytest.raises(ValueError):
        source.parse_article(_encode(_article(stamp=stamp)), news_id=41, expected_stamp=stamp)


def test_article_rejects_pre2011_publication_date() -> None:
    stamp = "2010-12-31 23:59:59"
    with pytest.raises(ValueError):
        source.parse_article(_encode(_article(stamp=stamp)), news_id=41, expected_stamp=stamp)


def test_article_rejects_mismatched_news_id() -> None:
    with pytest.raises(ValueError):
        source.parse_article(
            _encode(_article(news_id=42)), news_id=41, expected_stamp="2025-03-05 17:54:00"
        )


def test_article_rejects_mismatched_publication_stamp() -> None:
    with pytest.raises(ValueError):
        source.parse_article(
            _encode(_article()), news_id=41, expected_stamp="2025-02-28 08:35:00"
        )


def test_article_rejects_unexpected_columns() -> None:
    payload = _article()
    payload["content"] = {
        "columns": ["id", "title", "published_at", "body", "effective_date"],
        "data": [[41, "Состав индекса", "2025-03-05 17:54:00", "<p>Текст.</p>", "2025-03-21"]],
    }
    with pytest.raises(ValueError):
        source.parse_article(_encode(payload), news_id=41, expected_stamp="2025-03-05 17:54:00")


def test_non_json_error_pages_fail_closed() -> None:
    content = "<html><body>Ошибка источника</body></html>".encode()
    with pytest.raises(ValueError):
        source.parse_listing(content, expected_start=100, clock_only=False)
    with pytest.raises(ValueError):
        source.parse_article(content, news_id=41, expected_stamp="2025-03-05 17:54:00")
