"""Synthetic tests for the OFZ explicit-date transport correction."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pandas as pd

from market_lab.futures import moex_ofz_total_return_source_r1 as subject


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.content = json.dumps(payload).encode()

    def raise_for_status(self) -> None:
        return None


class _DailySession:
    def __init__(self, config: dict[str, object]) -> None:
        self.config = config

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _Response:
        query = parse_qs(urlparse(url).query)
        date = query["date"][0]
        columns = self.config["required_history_columns"]
        values = {
            "BOARDID": "TQOB",
            "TRADEDATE": date,
            "SHORTNAME": "OFZ synthetic",
            "SECID": "SU00000TEST1",
            "NUMTRADES": 1,
            "VALUE": 100_000,
            "VOLUME": 100,
            "OPEN": 99.0,
            "CLOSE": 99.1,
            "WAPRICE": 99.05,
            "LEGALCLOSEPRICE": 99.08,
            "ACCINT": 10.0,
            "YIELDCLOSE": 12.0,
            "YIELDATWAP": 12.1,
            "MATDATE": "2028-12-30",
            "DURATION": 700,
            "COUPONPERCENT": 8.0,
            "COUPONVALUE": 40.0,
            "FACEVALUE": 1_000,
            "CURRENCYID": "SUR",
            "FACEUNIT": "RUB",
            "BONDTYPE": "government_bond",
            "BONDSUBTYPE": "ofz_pd",
        }
        row = [values[column] for column in columns]
        return _Response(
            {
                "history": {"columns": columns, "data": [row]},
                "history.cursor": {
                    "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                    "data": [[0, 1, 100]],
                },
            }
        )


def test_real_r1_is_transport_only_and_sealed() -> None:
    config = subject.load_config()

    correction = config["transport_correction"]
    assert correction["V1_output_created"] is False
    assert correction["V1_bondization_requested"] is False
    assert correction["market_fields_or_economics_changed"] is False
    assert config["scope"]["computes_return_target_prediction_or_pnl"] is False
    assert config["live_trading_allowed"] is False


def test_daily_url_uses_explicit_date_not_ignored_range() -> None:
    config = subject.load_config()
    url = subject.daily_history_url(config, pd.Timestamp("2021-01-04"), 100)
    query = parse_qs(urlparse(url).query)

    assert query["date"] == ["2021-01-04"]
    assert query["start"] == ["100"]
    assert "from" not in query
    assert "till" not in query


def test_daily_container_replays_every_sealed_date() -> None:
    config = subject.load_config()
    config["source"]["history"]["from"] = "2025-12-29"
    config["source"]["history"]["till"] = "2025-12-30"
    retrieval = pd.Timestamp("2026-09-02T16:40:00Z")

    frame, pages = subject._fetch_history(_DailySession(config), config, retrieval)
    replay, total, _ = subject.normalize_history_page(
        pages[0]["raw"],
        expected_start=0,
        retrieved_at=retrieval,
        config=config,
    )

    assert len(frame) == 2
    assert total == 2
    assert list(replay["trade_date"].dt.date.astype(str)) == ["2025-12-29", "2025-12-30"]
    container = json.loads(pages[0]["raw"])
    assert container["format"] == subject.CONTAINER_FORMAT
    assert len(container["pages"]) == 2
