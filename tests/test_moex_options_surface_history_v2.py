"""Tests for the sealed public exact-date MOEX option history pilot V2."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from market_lab.futures import moex_options_surface_history_v2 as source


def _payload(query_date: str) -> bytes:
    columns = source.load_config()["source"]["required_columns"]
    rows = []
    for security_id, strike in (("SI75000BA1", 10.0), ("SI80000BM1", 11.0)):
        row = {column: None for column in columns}
        row.update(
            {
                "TRADEDATE": query_date,
                "BOARDID": "ROPD",
                "SECID": security_id,
                "OPEN": strike,
                "LOW": strike - 1.0,
                "HIGH": strike + 1.0,
                "CLOSE": strike,
                "SETTLEPRICE": strike,
                "VOLUME": 1,
                "OPENPOSITION": 2,
                "NUMTRADES": 1,
            }
        )
        rows.append([row[column] for column in columns])
    return json.dumps(
        {
            "history": {"columns": columns, "data": rows},
            "history.cursor": {
                "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                "data": [[0, 2, 100]],
            },
        }
    ).encode()


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _Session:
    def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> _Response:
        assert headers["User-Agent"] == source.USER_AGENT
        assert timeout == 30.0
        query = parse_qs(urlparse(url).query)
        assert query["assetcode"] == ["Si"]
        assert query["start"] == ["0"]
        return _Response(_payload(query["date"][0]))


def test_config_is_source_only_and_protects_2026() -> None:
    config = source.load_config()

    assert config["objective"]["signal_returns_targets_predictions_or_pnl_allowed"] is False
    assert config["dates"]["protected_from"] == "2026-01-01"
    assert config["limitations"]["historical_bid_ask_or_order_book_available"] is False


def test_small_source_collects_and_replays(tmp_path: Path) -> None:
    output = source.collect(
        tmp_path / "options",
        jobs=[(date(2021, 1, 4), "Si")],
        session=_Session(),
        retrieved_at="2026-09-02T02:30:00Z",
    )
    frame = pd.read_parquet(output / "options_daily_core4.parquet")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))

    assert len(frame) == 2
    assert set(frame["logical_asset"]) == {"SI"}
    assert frame["available_at_utc"].eq(pd.Timestamp("2021-01-04T21:00:00Z")).all()
    assert manifest["contains_returns_targets_predictions_or_pnl"] is False
    assert all(source.audit(output).values())
