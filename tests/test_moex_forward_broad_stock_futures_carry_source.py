from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from market_lab.futures import moex_forward_broad_stock_futures_carry_source as source
from market_lab.futures import moex_forward_cross_market_bbo_source as cross


class FakeClient:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = payloads

    def get_json(self, url: str) -> dict[str, Any]:
        if "/series.json" in url:
            return self.payloads["series"]
        if "/markets/shares/" in url:
            return self.payloads["spots"]
        if "/markets/forts/" in url:
            return self.payloads["futures"]
        raise AssertionError(f"unexpected URL: {url}")


def _table(columns: tuple[str, ...], rows: list[list[Any]]) -> dict[str, Any]:
    return {"columns": list(columns), "data": rows}


def _market_rows(secids: list[str], board: str) -> list[list[Any]]:
    output = []
    for index, secid in enumerate(secids):
        values = {
            "SECID": secid,
            "BOARDID": board,
            "BID": 100 + index,
            "OFFER": 100.1 + index,
            "BIDDEPTH": 1000 + index,
            "OFFERDEPTH": 900 + index,
            "BIDDEPTHT": 5000 + index,
            "OFFERDEPTHT": 4500 + index,
            "NUMBIDS": 50,
            "NUMOFFERS": 45,
            "VOLTODAY": 10000,
            "VALTODAY": 1000000,
            "OPENPOSITION": 20000 if board == cross.FUTURES_BOARD else None,
            "UPDATETIME": "10:09:01",
            "SEQNUM": index + 1,
            "SYSTIME": "2026-09-02 10:09:01",
        }
        output.append([values[column] for column in source.MARKET_COLUMNS])
    return output


def _payloads(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stocks = list(config["universe"]["exact_stock_order"])
    mapping = config["universe"]["quarterly_futures_asset_code_by_stock"]
    futures_secids = [f"F{index:02d}Z6" for index in range(len(stocks))]
    series_rows = []
    futures_security_rows = []
    for index, (stock, futures_secid) in enumerate(zip(stocks, futures_secids, strict=True)):
        asset_code = str(mapping[stock])
        series_rows.append(
            [
                futures_secid,
                f"{asset_code}-12.26",
                "2026-01-01",
                "2026-12-18",
                asset_code,
                stock,
                1,
            ]
        )
        values = {
            "SECID": futures_secid,
            "BOARDID": cross.FUTURES_BOARD,
            "SECTYPE": f"F{index:02d}",
            "ASSETCODE": asset_code,
            "LOTVOLUME": 100,
            "MINSTEP": 1,
            "LASTTRADEDATE": "2026-12-17",
            "LASTDELDATE": "2026-12-18",
            "INITIALMARGIN": 20000,
            "STEPPRICE": 10,
        }
        futures_security_rows.append(
            [values[column] for column in source.FUTURES_SECURITY_COLUMNS]
        )
    spot_security_rows = []
    for stock in stocks:
        values = {
            "SECID": stock,
            "BOARDID": cross.EQUITY_BOARD,
            "LOTSIZE": 10,
            "MINSTEP": 0.01,
        }
        spot_security_rows.append([values[column] for column in source.SPOT_SECURITY_COLUMNS])
    return {
        "series": {
            "series": _table(
                (
                    "secid",
                    "name",
                    "start_date",
                    "expiration_date",
                    "asset_code",
                    "underlying_asset",
                    "is_traded",
                ),
                series_rows,
            )
        },
        "spots": {
            "securities": _table(source.SPOT_SECURITY_COLUMNS, spot_security_rows),
            "marketdata": _table(
                source.MARKET_COLUMNS, _market_rows(stocks, cross.EQUITY_BOARD)
            ),
        },
        "futures": {
            "securities": _table(
                source.FUTURES_SECURITY_COLUMNS, futures_security_rows
            ),
            "marketdata": _table(
                source.MARKET_COLUMNS,
                _market_rows(futures_secids, cross.FUTURES_BOARD),
            ),
        },
    }


def _raw(payloads: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"kind": kind, "url": kind, "payload": payload}
        for kind, payload in payloads.items()
    ]


def _context(config: dict[str, Any]) -> tuple[pd.Timestamp, pd.Timestamp]:
    retrieval = pd.Timestamp("2026-09-02T07:09:30Z")
    _, _, slot = cross._source_context(config, retrieval)
    return retrieval, slot


def test_protocol_and_contract_selection_cover_all_thirty() -> None:
    config = source.load_config()
    retrieval, _ = _context(config)
    selected = source.select_contracts(
        _payloads(config)["series"],
        retrieval.tz_convert(cross.MOSCOW_TZ).date(),
        config,
    )
    assert len(selected) == 30
    assert all(value is not None for value in selected.values())
    spot_url = source._venue_url(
        config["official_sources"]["spots_bulk"],
        list(config["universe"]["exact_stock_order"]),
        source.SPOT_SECURITY_COLUMNS,
    )
    assert "securities=AFKS%2CAFLT" in spot_url


def test_normalize_valid_units_and_quotes() -> None:
    config = source.load_config()
    retrieval, slot = _context(config)
    frame = source.normalize_snapshot(
        _raw(_payloads(config)),
        config=config,
        source_date=retrieval.tz_convert(cross.MOSCOW_TZ).date(),
        retrieval=retrieval,
        slot=slot,
    )
    assert len(frame) == 30
    assert frame["valid"].all()
    assert frame["spot_lots_per_futures_contract"].eq(10).all()
    assert source._status(frame) == "complete_30_pairs_valid"


def test_fractional_spot_lots_fail_closed() -> None:
    config = source.load_config()
    retrieval, slot = _context(config)
    payloads = _payloads(config)
    columns = payloads["futures"]["securities"]["columns"]
    lot_index = columns.index("LOTVOLUME")
    payloads["futures"]["securities"]["data"][0][lot_index] = 15
    frame = source.normalize_snapshot(
        _raw(payloads),
        config=config,
        source_date=retrieval.tz_convert(cross.MOSCOW_TZ).date(),
        retrieval=retrieval,
        slot=slot,
    )
    first = frame.loc[frame["stock_secid"].eq("AFKS")].iloc[0]
    assert not bool(first["valid"])
    assert "spot_lots_per_contract_not_positive_integer" in str(first["invalid_reason"])
    assert source._status(frame) == "invalid_pairs"


def test_collect_and_raw_replay(tmp_path: Path) -> None:
    config = source.load_config()
    final = source.collect(
        tmp_path,
        client=FakeClient(_payloads(config)),
        retrieved_at="2026-09-02T07:09:30Z",
    )
    checks = source.audit(final)
    assert all(checks.values()), checks
    with pytest.raises(FileExistsError):
        source.collect(
            tmp_path,
            client=FakeClient(_payloads(config)),
            retrieved_at="2026-09-02T07:09:31Z",
        )
