"""Tests for the sealed MOEX USD/RUB TOM historical source collector."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import moex_fx_spot_source as source


def _payload(start: int, *, total: int = 2, page_size: int = 1) -> bytes:
    config = source.load_config()
    columns = config["required_history_columns"]
    date = pd.Timestamp("2020-01-01") + pd.Timedelta(days=start)
    values = {
        "BOARDID": "CETS",
        "TRADEDATE": date.date().isoformat(),
        "SHORTNAME": "US Dollar TOM",
        "SECID": "USD000UTSTOM",
        "OPEN": 60.0 + start,
        "LOW": 59.0 + start,
        "HIGH": 61.0 + start,
        "CLOSE": 60.5 + start,
        "NUMTRADES": 100 + start,
        "WAPRICE": 60.25 + start,
    }
    rows = [[values[column] for column in columns]] if start < total else []
    return json.dumps(
        {
            "history": {"columns": columns, "data": rows},
            "history.cursor": {
                "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                "data": [[start, total, page_size]],
            },
        }
    ).encode()


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _Session:
    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _Response:
        assert headers["User-Agent"] == source.USER_AGENT
        assert timeout == 30.0
        start = int(parse_qs(urlparse(url).query)["start"][0])
        return _Response(_payload(start))


def _small_config() -> dict:
    config = copy.deepcopy(source.load_config())
    config["source"]["page_size_observed_in_transport_probe"] = 1
    config["source"]["total_rows_observed_in_transport_probe"] = 2
    return config


def test_config_is_source_only_and_protected() -> None:
    config = source.load_config()

    assert (
        config["hypothesis_for_later_protocol"]
        ["this_protocol_computes_returns_targets_or_pnl"]
        is False
    )
    assert config["temporal_semantics"]["protected_ceiling_exclusive"] == "2026-01-01"
    assert (
        config["future_economic_protocol_requirements"]["forbid_unproven_USD_interest_income"]
        is True
    )
    assert "basis" in config["forbidden_columns"]


def test_normalize_page_applies_next_day_availability(monkeypatch) -> None:
    config = _small_config()
    monkeypatch.setattr(source, "load_config", lambda: config)
    frame, total, page_size = source.normalize_page(
        _payload(0), 0, pd.Timestamp("2026-09-02T00:00:00Z"), config
    )

    assert total == 2
    assert page_size == 1
    assert frame.iloc[0]["security_id"] == "USD000UTSTOM"
    assert frame.iloc[0]["available_at_utc"] == pd.Timestamp("2020-01-01T21:00:00Z")
    assert not set(config["forbidden_columns"]) & set(frame.columns)


def test_normalize_rejects_cursor_drift(monkeypatch) -> None:
    config = _small_config()
    monkeypatch.setattr(source, "load_config", lambda: config)
    with pytest.raises(ValueError, match="cursor value drift"):
        source.normalize_page(
            _payload(0), 1, pd.Timestamp("2026-09-02T00:00:00Z"), config
        )


def test_collect_and_raw_replay_audit(tmp_path: Path, monkeypatch) -> None:
    config = _small_config()
    monkeypatch.setattr(source, "load_config", lambda: config)
    output = tmp_path / "fx-source"
    collected = source.collect(
        output,
        session=_Session(),
        retrieved_at="2026-09-02T00:00:00Z",
    )

    checks = source.audit(collected)
    stored = pd.read_parquet(collected / "spot_history.parquet")
    assert all(checks.values())
    assert len(stored) == 2
    assert stored["trade_date"].max() < pd.Timestamp("2026-01-01")
    assert (collected / "audit.json").is_file()
