"""Proverki lokalnogo parsera i postranichnoi zagruzki MOEX."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from market_lab.config import AppConfig
from market_lab.data.moex import FixtureSource, MoexIssSource, parse_moex_payload


class FakeResponse:
    """Imitiruet minimalnyi requests.Response dlya unit-testa."""

    def __init__(self, payload: dict[str, Any]) -> None:
        """Sohranyaet JSON-stranicu."""
        self.payload = payload

    def raise_for_status(self) -> None:
        """Imitiruet uspeshnyi HTTP-status."""

    def json(self) -> dict[str, Any]:
        """Vozvrashchaet zafiksirovannyi JSON."""
        return self.payload


class FakeSession:
    """Vozvrashchaet posledovatelnye stranicy bez seti."""

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        """Sohranyaet ochered stranic i parametry vyzovov."""
        self.pages = pages
        self.starts: list[int] = []

    def get(self, _url: str, params: dict[str, Any], timeout: int) -> FakeResponse:
        """Vozvrashchaet stranicu sootvetstvuyushchuyu nomeru vyzova."""
        del timeout
        self.starts.append(int(params["start"]))
        return FakeResponse(self.pages[len(self.starts) - 1])


def _payload(rows: list[list[object]]) -> dict[str, Any]:
    """Formiruet minimalnyi validnyi candles-otvet."""
    return {
        "candles": {
            "columns": ["open", "close", "high", "low", "value", "volume", "begin", "end"],
            "data": rows,
        }
    }


def _row(day: int, price: float) -> list[object]:
    """Formiruet odnu validnuyu dnevnuu svechu."""
    timestamp = f"2024-01-{day:02d} 10:00:00"
    return [price, price, price, price, price * 100, 100, timestamp, timestamp]


def test_fixture_parser_returns_utc_ohlcv(app_config: AppConfig) -> None:
    """Proveryaet lokalnyi MOEX fixture bez setevyh vyzovov."""
    frame = FixtureSource(app_config.data).load().frame
    assert len(frame) == 320
    assert str(frame.index.tz) == "UTC"
    assert list(frame.columns) == ["open", "high", "low", "close", "volume", "value"]
    assert frame.index.is_monotonic_increasing


def test_parser_rejects_missing_columns() -> None:
    """Proveryaet ponyatnuyu oshibku pri narushenii shemy."""
    with pytest.raises(ValueError, match="net kolonok"):
        parse_moex_payload({"candles": {"columns": ["open"], "data": [[1.0]]}})


def test_moex_source_follows_pagination(app_config: AppConfig) -> None:
    """Proveryaet uvelichenie start poka stranica zapolnena."""
    pages = [
        _payload([_row(1, 100.0), _row(2, 101.0)]),
        _payload([_row(3, 102.0)]),
    ]
    session = FakeSession(pages)
    data_config = app_config.data.model_copy(update={"page_size": 2})
    bundle = MoexIssSource(data_config, session=session).load()  # type: ignore[arg-type]
    assert session.starts == [0, 2]
    assert len(bundle.frame) == 3
    assert isinstance(bundle.frame, pd.DataFrame)
