"""Tests for the official public-page MOEX futures calendar transport."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pandas as pd
import pytest
import requests

from market_lab.futures import moex_forward_futures_calendar_source_v1 as source


def _calendar_year(year: int) -> dict[str, dict[str, object]]:
    return {
        value.strftime("%Y-%m-%d"): {
            "tradedate": value.strftime("%Y-%m-%d"),
            "is_traded": None if value.day == 1 and value.month == 1 else int(value.weekday() < 5),
            "reason": None if value.day == 1 and value.month == 1 else (
                "N" if value.weekday() < 5 else "H"
            ),
        }
        for value in pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    }


def _html(*, drop_date: str | None = None) -> bytes:
    year_2027 = _calendar_year(2027)
    if drop_date is not None:
        year_2027.pop(drop_date)
    payload = {
        "props": {
            "pageProps": {
                "recursiveComponentContentProps": {
                    "layout-slot": {
                        "children": [
                            {
                                "initData": {
                                    "offDays": {
                                        "stock": {},
                                        "futures": {
                                            "2026": _calendar_year(2026),
                                            "2027": year_2027,
                                        },
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        }
    }
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    return (
        b'<html><script id="__NEXT_DATA__" type="application/json">'
        + encoded
        + b"</script></html>"
    )


class _Response:
    status_code = 200
    content = _html()
    headers = {"Content-Type": "text/html; charset=utf-8"}


class _Session:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str],
        headers: Mapping[str, str],
        timeout: float,
    ) -> _Response:
        assert url == "https://www.moex.com/ru/tradingcalendar"
        assert params == {"market": "derivatives-market", "type": "trading"}
        assert headers["Accept"] == "text/html"
        assert headers["Accept-Encoding"] == "identity"
        assert timeout == 30.0
        if self.fail:
            raise requests.ReadTimeout("synthetic timeout")
        return _Response()


def test_config_preserves_frozen_roll_and_blocks_inference() -> None:
    config = source.load_config()
    assert config["parent_paper_protocol"]["hard_fallback_sessions_unchanged"] == 5
    assert config["causality"]["generic_weekday_substitution"] == "forbidden"
    assert config["causality"]["null_is_traded_policy"] == "unavailable_never_infer"
    assert (
        config["consumer_contract"][
            "signal_direction_scale_cap_margin_cost_or_gate_changed"
        ]
        is False
    )
    assert config["live_trading_allowed"] is False


def test_parse_keeps_only_post_retrieval_current_and_next_year() -> None:
    frame = source.parse_response(_html(), pd.Timestamp("2026-09-02T22:50:00Z"))
    assert tuple(frame.columns) == source.OUTPUT_COLUMNS
    assert frame["tradedate"].min() == pd.Timestamp("2026-09-03")
    assert frame["tradedate"].max() == pd.Timestamp("2027-12-31")
    assert frame["tradedate"].is_unique
    assert frame["available_at_utc"].eq(pd.Timestamp("2026-09-02T22:50:00Z")).all()
    assert frame.loc[frame["tradedate"].eq(pd.Timestamp("2027-01-01")), "is_traded"].isna().all()


def test_missing_calendar_day_fails_closed() -> None:
    raw = _html(drop_date="2027-12-31")
    with pytest.raises(ValueError, match="does not cover every date"):
        source.parse_response(raw, pd.Timestamp("2026-09-02T22:50:00Z"))


def test_collect_and_raw_replay_audit(tmp_path: Path) -> None:
    snapshot = source.collect(
        tmp_path,
        session=_Session(),
        retrieved_at="2026-09-02T22:50:00Z",
    )
    checks = source.audit(snapshot)
    assert all(checks.values())
    assert (snapshot / "raw_moex_trading_calendar.html.gz").is_file()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["contains_return_label_signal_target_prediction_equity_or_pnl"] is False


def test_transport_failure_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(source.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="calendar transport failed"):
        source.collect(
            tmp_path,
            session=_Session(fail=True),
            retrieved_at="2026-09-02T22:50:00Z",
        )
    assert not list(tmp_path.glob("snapshot_*"))
