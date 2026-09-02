from __future__ import annotations

import pandas as pd

from market_lab.futures import (
    moex_broad_stock_futures_cash_carry_intraday_source as source,
)


def _table(columns: tuple[str, ...], rows: list[list[object]]) -> dict[str, object]:
    return {"columns": list(columns), "data": rows}


def _series_raw(protocol: source.Protocol) -> list[dict[str, object]]:
    columns = (
        "secid",
        "name",
        "start_date",
        "expiration_date",
        "asset_code",
        "underlying_asset",
        "is_traded",
    )
    counts = protocol.payload["universe"]["exact_outright_contract_count_by_stock"]
    output: list[dict[str, object]] = []
    month_codes = ("H", "M", "U", "Z")
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for index, stock in enumerate(protocol.payload["universe"]["exact_stock_order"]):
        prefix = alphabet[index // len(alphabet)] + alphabet[index % len(alphabet)]
        rows: list[list[object]] = []
        for contract_index in range(int(counts[stock])):
            year = 3 + contract_index // 4
            month_code = month_codes[contract_index % 4]
            month = (3, 6, 9, 12)[contract_index % 4]
            secid = f"{prefix}{month_code}{year}"
            asset_code = f"A{index:02d}"
            rows.append(
                [
                    secid,
                    f"{asset_code}-{month}.{2020 + year}",
                    f"202{year - 1}-01-01",
                    f"202{year}-{month:02d}-20",
                    asset_code,
                    stock,
                    0,
                ]
            )
        rows.extend(
            [
                [
                    f"{prefix}H3{prefix}M3",
                    "calendar spread",
                    "2022-01-01",
                    "2023-03-20",
                    f"A{index:02d}",
                    stock,
                    0,
                ],
                [
                    f"{prefix}F",
                    "perpetual",
                    "2022-01-01",
                    "2100-01-01",
                    f"A{index:02d}F",
                    stock,
                    1,
                ],
            ]
        )
        output.append(
            {
                "kind": "series",
                "stock_secid": stock,
                "url": stock,
                "payload": {"series": _table(columns, rows)},
            }
        )
    return output


def test_protocol_and_metadata_selection_are_exact() -> None:
    protocol = source.load_protocol()
    catalog = source.select_catalog(_series_raw(protocol), protocol)
    assert len(catalog) == 339
    assert catalog["contract_id"].is_unique
    assert catalog.groupby("stock_secid").size().to_dict() == {
        stock: int(count)
        for stock, count in protocol.payload["universe"][
            "exact_outright_contract_count_by_stock"
        ].items()
        if int(count) > 0
    }
    assert "ENPG" not in set(catalog["stock_secid"])


def test_description_units_and_candle_temporal_semantics() -> None:
    row = {
        "contract_id": "GAZP:GAZR:GZH3:2023-03-17",
        "stock_secid": "GAZP",
        "secid": "GZH3",
        "asset_code": "GAZR",
        "series_start": pd.Timestamp("2022-01-01"),
        "expiration": pd.Timestamp("2023-03-17"),
    }
    description_rows = [
        ["SECID", "GZH3"],
        ["ASSETCODE", "GAZR"],
        ["TYPE", "futures"],
        ["LOTSIZE", "100"],
        ["FRSTTRADE", "2022-01-10"],
        ["LSTTRADE", "2023-03-16"],
        ["LSTDELDATE", "2023-03-17"],
    ]
    description = {
        "description": _table(("name", "value"), description_rows),
        "boards": _table(("secid", "boardid"), [["GZH3", "RFUD"]]),
    }
    spec = source.parse_description(description, row)
    assert spec["lot_size_shares"] == 100
    assert spec["request_till"] == pd.Timestamp("2023-03-16")
    candles = {
        "candles": _table(
            ("open", "close", "high", "low", "value", "volume", "begin", "end"),
            [
                [
                    100.0,
                    100.5,
                    101.0,
                    99.5,
                    100000.0,
                    10.0,
                    "2023-03-01 10:00:00",
                    "2023-03-01 10:09:59",
                ]
            ],
        )
    }
    frame = source.parse_candles(candles, spec)
    assert len(frame) == 1
    assert frame.iloc[0]["available_at"] > frame.iloc[0]["timestamp"]
    assert not source._forbidden(frame)
