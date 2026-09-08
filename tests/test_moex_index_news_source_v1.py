"""Synthetic source-only checks for the MOEX index-news catalogue."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from urllib.parse import parse_qs, urlparse

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
        source.parse_article(_encode(_article()), news_id=41, expected_stamp="2025-02-28 08:35:00")


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


def _sample_config():
    return {
        "sample_news_ids": [41],
        "max_sample_requests": 2,
        "max_requests": 2,
        "max_response_bytes": 4096,
        "request_interval_seconds": 0,
        "timeout_seconds": 30,
        "catalogue_collection_allowed": False,
    }


def _clock_article(value="2025-03-05 17:54:00"):
    return _encode({"content": {"columns": ["id", "published_at"], "data": [[41, value]]}})


def _sample_evidence():
    raws = [_clock_article(), _encode(_article())]
    records = []
    for index, kind in enumerate(("article_clock", "article")):
        records.append(
            {
                "kind": kind,
                "key": 41,
                "url": source.request_url(kind, 41),
                "final_url": source.request_url(kind, 41),
                "status": 200,
                "content_type": "application/json",
                "requested_at_utc": f"2026-09-08T09:00:0{2 * index}+00:00",
                "retrieved_at_utc": f"2026-09-08T09:00:0{2 * index + 1}+00:00",
                "path": str(index),
                "bytes": len(raws[index]),
                "sha256": source.sha(raws[index]),
                **({"expected_stamp": "2025-03-05 17:54:00"} if index else {}),
            }
        )
    return records, lambda row: raws[int(row["path"])]


def test_individual_article_clock_is_date_only_and_rejects_protected_year():
    assert source.article_clock(_clock_article(), 41) == "2025-03-05 17:54:00"
    with pytest.raises(ValueError):
        source.article_clock(_clock_article("2026-01-01 00:00:00"), 41)
    with pytest.raises(ValueError):
        source.article_clock(_clock_article(), 42)
    query = parse_qs(urlparse(source.request_url("article_clock", 41)).query)
    assert query["content.columns"] == ["id,published_at"]
    assert query["iss.only"] == ["content"]


def test_sample_full_raw_replay_does_not_grant_economic_or_event_admission():
    records, get_raw = _sample_evidence()
    result = source.assemble_sample(records, get_raw, _sample_config())
    assert result["summary"]["articles"] == 1
    assert result["summary"]["requests"] == 2
    for name in (
        "event_corpus_complete",
        "historical_model_eligible",
        "economic_evaluation_allowed",
    ):
        assert result["summary"][name] is False
    assert result["articles"][0]["available_at"] is None
    assert result["articles"][0]["raw_clock_request"] == 0


@pytest.mark.parametrize("damage", ["hash", "url", "time", "id", "stamp", "coverage", "redirect"])
def test_sample_replay_rejects_corrupted_evidence(damage):
    records, get_raw = _sample_evidence()
    records = deepcopy(records)
    if damage == "hash":
        records[1]["sha256"] = "0" * 64
    elif damage == "url":
        records[1]["url"] = source.request_url("article", 42)
    elif damage == "redirect":
        records[1]["final_url"] = "https://example.invalid/"
    elif damage == "time":
        records[1]["requested_at_utc"] = records[0]["requested_at_utc"]
    elif damage == "id":
        records[1]["key"] = 42
    elif damage == "stamp":
        records[1]["expected_stamp"] = "2025-02-28 08:35:00"
    else:
        records.pop()
    with pytest.raises(ValueError):
        source.assemble_sample(records, get_raw, _sample_config())


class _Response:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, url, content):
        self.url, self.content = url, content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def iter_content(self, chunk_size):
        yield self.content


class _Session:
    def __init__(self, clock=None):
        self.urls, self.closed = [], False
        self.clock = _clock_article() if clock is None else clock

    def get(self, url, **kwargs):
        assert kwargs["allow_redirects"] is False
        assert kwargs["stream"] is True
        self.urls.append(url)
        columns = parse_qs(urlparse(url).query)["content.columns"][0]
        return _Response(url, self.clock if columns == "id,published_at" else _encode(_article()))

    def close(self):
        self.closed = True


def _configure_sample(monkeypatch, tmp_path, session):
    config = _sample_config()
    monkeypatch.setattr(source, "load_protocol", lambda _sha: (config, {}))
    monkeypatch.setattr(source, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(source.requests, "Session", lambda: session)
    path = tmp_path / source.CONFIG_PATH
    path.parent.mkdir()
    path.write_bytes(_encode(config))
    return "1" * 64


def test_sample_collect_replay_and_existing_output_refusal(monkeypatch, tmp_path):
    session = _Session()
    seal = _configure_sample(monkeypatch, tmp_path, session)
    result = source.collect_sample(tmp_path, seal)
    assert session.trust_env is False and session.closed
    assert len(session.urls) == 2
    output = (
        tmp_path
        / "data/processed/index_announcements"
        / ("moex_index_news_fixed_sample_v1_" + seal[:12])
    )
    report = source.audit(output, seal, result["manifest_sha256"])
    assert report["passed"] == 6
    assert all(report["checks"].values())
    with pytest.raises(FileExistsError):
        source.collect_sample(tmp_path, seal)
    assert len(session.urls) == 2


def test_protected_date_stops_before_body_and_retains_failed_attempt(monkeypatch, tmp_path):
    session = _Session(_clock_article("2026-01-01 00:00:00"))
    seal = _configure_sample(monkeypatch, tmp_path, session)
    with pytest.raises(ValueError):
        source.collect_sample(tmp_path, seal)
    assert session.closed and len(session.urls) == 1
    failed = list((tmp_path / "data").rglob("failure.json"))
    assert len(failed) == 1
    assert len(json.loads(failed[0].read_text(encoding="utf-8-sig"))["requests"]) == 1


def test_full_catalogue_refused_before_output_or_http(monkeypatch, tmp_path):
    session = _Session()
    seal = _configure_sample(monkeypatch, tmp_path, session)
    with pytest.raises(ValueError, match="full catalogue disabled"):
        source.collect(tmp_path, seal)
    assert not session.urls and not (tmp_path / "data").exists()


def test_body_request_rejects_protected_or_missing_stamp_before_network(tmp_path, monkeypatch):
    session = _Session()
    monkeypatch.setattr(source.requests, "Session", lambda: session)
    acquisition = source.Acquisition(tmp_path, _sample_config())
    for metadata in ({}, {"expected_stamp": "2026-01-01 00:00:00"}):
        with pytest.raises(ValueError):
            acquisition.fetch("article", 41, **metadata)
    assert not session.urls


def test_response_size_is_bounded_before_raw_persistence(tmp_path, monkeypatch):
    session = _Session(b"x" * 4097)
    monkeypatch.setattr(source.requests, "Session", lambda: session)
    acquisition = source.Acquisition(tmp_path, _sample_config())
    with pytest.raises(ValueError, match="byte budget"):
        acquisition.fetch("article_clock", 41)
    assert not (tmp_path / "raw").exists()
