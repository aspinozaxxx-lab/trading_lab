"""Tests for delayed cross-market V3 CNY-perpetual source repair."""

from __future__ import annotations

from typing import Any

import pandas as pd

from market_lab.futures import moex_forward_cross_market_bbo_source as v1
from market_lab.futures import moex_forward_cross_market_bbo_source_v3 as v3


def _table(columns: tuple[str, ...], rows: list[list[Any]]) -> dict[str, Any]:
    return {"columns": list(columns), "data": rows}


def _cny_payload() -> dict[str, Any]:
    security = {column: None for column in v1.SECURITY_COLUMNS}
    security.update(
        {"SECID": "CNYRUBF", "BOARDID": "RFUD", "LOTVOLUME": 1000, "MINSTEP": 0.001}
    )
    market = {column: None for column in v1.MARKET_COLUMNS}
    market.update(
        {
            "SECID": "CNYRUBF",
            "BOARDID": "RFUD",
            "BID": 12.8,
            "OFFER": 12.801,
            "LAST": 12.8,
            "NUMTRADES": 100,
            "SYSTIME": "2026-09-02 12:00:00",
            "UPDATETIME": "11:45:00",
        }
    )
    return {
        "securities": _table(v1.SECURITY_COLUMNS, [[security[c] for c in v1.SECURITY_COLUMNS]]),
        "marketdata": _table(v1.MARKET_COLUMNS, [[market[c] for c in v1.MARKET_COLUMNS]]),
    }


def test_protocol_and_exact_cny_url_are_fixed() -> None:
    config = v3.load_config()
    url = v3.cny_perpetual_url(config)

    assert config["protocol_id"] == "moex_forward_cross_market_bbo_source_v3"
    assert "securities=CNYRUBF" in url
    assert config["v3_correction"]["expected_core_rows"] == 35


def test_normalize_replaces_only_core_currency_identity(monkeypatch) -> None:
    rows = []
    for index in range(39):
        row = {column: pd.NA for column in v1.OUTPUT_COLUMNS}
        row.update(
            {
                "venue_kind": "fx" if index == 34 else "equity",
                "logical_asset": "CNYRUB_TOM" if index == 34 else f"X{index:02d}",
                "core_required": index < 35,
                "valid": index != 34,
            }
        )
        rows.append(row)
    parent = pd.DataFrame(rows, columns=v1.OUTPUT_COLUMNS)
    monkeypatch.setattr(v3.v2, "normalize_snapshot", lambda *args, **kwargs: parent.copy())
    raw = [
        {"kind": kind, "url": kind, "payload": _cny_payload() if kind == "cny_perpetual" else {}}
        for kind in ("series", "equities", "futures", "fx", "cny_perpetual")
    ]
    retrieval = pd.Timestamp("2026-09-02T09:00:30Z")
    frame = v3.normalize_snapshot(
        raw,
        config=v3.load_config(),
        source_date=retrieval.tz_convert(v1.MOSCOW_TZ).date(),
        retrieval=retrieval,
        slot=pd.Timestamp("2026-09-02T12:00:00+03:00"),
    )

    assert len(frame) == 40
    assert int(frame["core_required"].sum()) == 35
    perpetual = frame.loc[frame["logical_asset"].eq("CNYRUB_PERPETUAL")].iloc[0]
    spot = frame.loc[frame["logical_asset"].eq("CNYRUB_TOM")].iloc[0]
    assert bool(perpetual["valid"])
    assert bool(perpetual["core_required"])
    assert not bool(spot["core_required"])
