from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from market_lab.futures import forward_cross_market_bbo_readiness as readiness_module
from market_lab.futures import moex_forward_cross_market_bbo_source as source


class FakeClient:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = payloads

    def get_json(self, url: str) -> dict[str, Any]:
        for kind, payload in self.payloads.items():
            if kind == "series" and "/series.json" in url:
                return payload
            if kind == "equities" and "/markets/shares/" in url:
                return payload
            if kind == "futures" and "/markets/forts/" in url:
                return payload
            if kind == "fx" and "/markets/selt/" in url:
                return payload
        raise AssertionError(f"unexpected URL: {url}")


def _table(columns: tuple[str, ...], rows: list[list[Any]]) -> dict[str, Any]:
    return {"columns": list(columns), "data": rows}


def _venue_payload(secids: list[str], board: str) -> dict[str, Any]:
    security_rows = []
    for secid in secids:
        values = {
            "SECID": secid,
            "BOARDID": board,
            "LOTSIZE": 1 if board != source.FUTURES_BOARD else None,
            "LOTVOLUME": 1 if board == source.FUTURES_BOARD else None,
            "MINSTEP": 0.01,
        }
        security_rows.append([values[column] for column in source.SECURITY_COLUMNS])
    market_rows: list[list[Any]] = []
    for index, secid in enumerate(secids):
        values: dict[str, Any] = {
            "SECID": secid,
            "BOARDID": board,
            "BID": 100.0 + index,
            "OFFER": 100.1 + index,
            "BIDDEPTH": 1000 + index,
            "OFFERDEPTH": 900 + index,
            "BIDDEPTHT": 5000 + index,
            "OFFERDEPTHT": 4500 + index,
            "NUMBIDS": 40 + index,
            "NUMOFFERS": 35 + index,
            "TRADINGSTATUS": "T",
            "OPEN": 99.0 + index,
            "HIGH": 101.0 + index,
            "LOW": 98.0 + index,
            "LAST": 100.05 + index,
            "WAPRICE": 100.0 + index,
            "VOLUME": 10000 + index,
            "VALTODAY": 1000000 + index,
            "VALUE": 10000 + index,
            "NUMTRADES": 100 + index,
            "OPENPOSITION": 20000 + index,
            "SYSTIME": "2026-09-02 10:09:01",
            "UPDATETIME": "10:09:01",
            "SEQNUM": index + 1,
        }
        market_rows.append([values[column] for column in source.MARKET_COLUMNS])
    return {
        "securities": _table(source.SECURITY_COLUMNS, security_rows),
        "marketdata": _table(source.MARKET_COLUMNS, market_rows),
    }


def _payloads(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    equity_secids = list(config["universe"]["equities"]["secids"]) + list(
        config["universe"]["idle_cash_context"]["secids"]
    )
    future_secids = ["SiZ6", "RIZ6", "BRZ6", "MXZ6"]
    series_rows = [
        ["SiZ6", "Si-12.26", "2026-01-01", "2026-12-17", "Si", 1],
        ["RIZ6", "RTS-12.26", "2026-01-01", "2026-12-17", "RTS", 1],
        ["BRZ6", "BR-12.26", "2026-01-01", "2026-12-17", "BR", 1],
        ["MXZ6", "MIX-12.26", "2026-01-01", "2026-12-17", "MIX", 1],
    ]
    return {
        "series": {
            "series": _table(
                (
                    "secid",
                    "name",
                    "start_date",
                    "expiration_date",
                    "asset_code",
                    "is_traded",
                ),
                series_rows,
            )
        },
        "equities": _venue_payload(equity_secids, source.EQUITY_BOARD),
        "futures": _venue_payload(future_secids, source.FUTURES_BOARD),
        "fx": _venue_payload(["CNYRUB_TOM"], source.FX_BOARD),
    }


def _context() -> tuple[dict[str, Any], pd.Timestamp, pd.Timestamp]:
    config = source.load_config()
    retrieval = pd.Timestamp("2026-09-02T07:09:30Z")
    _, _, slot = source._source_context(config, retrieval)
    return config, retrieval, slot


def test_protocol_and_urls_are_fixed() -> None:
    config = source.load_config()
    urls = source.request_urls(config, ["SiZ6", "RIZ6", "BRZ6", "MXZ6"])
    assert set(urls) == {"series", "equities", "futures", "fx"}
    assert "marketdata.columns=" in urls["equities"]
    assert "securities=AFKS%2CAFLT" in urls["equities"]
    assert "securities=SiZ6%2CRIZ6%2CBRZ6%2CMXZ6" in urls["futures"]
    assert len(config["universe"]["equities"]["secids"]) == 30


def test_normalize_complete_cross_market_snapshot() -> None:
    config, retrieval, slot = _context()
    payloads = _payloads(config)
    raw = [
        {"kind": kind, "url": kind, "payload": payload}
        for kind, payload in payloads.items()
    ]
    frame = source.normalize_snapshot(
        raw,
        config=config,
        source_date=retrieval.tz_convert(source.MOSCOW_TZ).date(),
        retrieval=retrieval,
        slot=slot,
    )
    assert len(frame) == 39
    assert int(frame["core_required"].sum()) == 35
    assert frame["valid"].all()
    assert source._status(frame) == "complete_core_valid"
    futures = frame.loc[frame["venue_kind"].eq("futures")]
    assert set(futures["logical_asset"]) == {"SI", "RI", "BR", "MIX"}
    assert futures["contract_expiration"].eq("2026-12-17").all()


def test_invalid_optional_fund_does_not_invalidate_core() -> None:
    config, retrieval, slot = _context()
    payloads = _payloads(config)
    market = payloads["equities"]["marketdata"]
    secid_index = market["columns"].index("SECID")
    market["data"] = [row for row in market["data"] if row[secid_index] != "TMON"]
    raw = [
        {"kind": kind, "url": kind, "payload": payload}
        for kind, payload in payloads.items()
    ]
    frame = source.normalize_snapshot(
        raw,
        config=config,
        source_date=retrieval.tz_convert(source.MOSCOW_TZ).date(),
        retrieval=retrieval,
        slot=slot,
    )
    tmon = frame.loc[frame["logical_asset"].eq("TMON")].iloc[0]
    assert not bool(tmon["valid"])
    assert source._status(frame) == "complete_core_valid"


def test_collect_and_audit_round_trip(tmp_path: Path) -> None:
    config = source.load_config()
    final = source.collect(
        tmp_path,
        client=FakeClient(_payloads(config)),
        retrieved_at="2026-09-02T07:09:30Z",
    )
    assert final.name == "snapshot_20260902T1009_moscow"
    checks = source.audit(final)
    assert all(checks.values()), checks
    readiness = readiness_module.readiness(tmp_path)
    assert readiness["counts"]["complete_core_snapshots"] == 1
    assert readiness["counts"]["complete_sessions"] == 0
    assert readiness["gates"]["annualization_allowed"] is False
    with pytest.raises(FileExistsError):
        source.collect(
            tmp_path,
            client=FakeClient(_payloads(config)),
            retrieved_at="2026-09-02T07:09:31Z",
        )


def test_source_context_rejects_off_slot_and_weekend() -> None:
    config = source.load_config()
    with pytest.raises(ValueError, match="missed"):
        source._source_context(config, "2026-09-02T07:12:00Z")
    with pytest.raises(ValueError, match="weekdays"):
        source._source_context(config, "2026-09-05T07:09:00Z")


def test_empty_readiness_stays_source_only(tmp_path: Path) -> None:
    payload = readiness_module.readiness(tmp_path)
    assert payload["counts"]["snapshot_directories"] == 0
    assert payload["next_action"] == "continue_immutable_ten_minute_source_collection"
    assert payload["market_outcomes_or_pnl_computed"] is False
