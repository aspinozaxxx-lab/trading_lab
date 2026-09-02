"""Synthetic tests for the sealed MOEX OFZ source collector."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from market_lab.futures import moex_ofz_total_return_source as subject


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.content = json.dumps(payload).encode()

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, payloads: dict[str, dict[str, object]]) -> None:
        self.payloads = payloads

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> _Response:
        assert headers["User-Agent"] == subject.USER_AGENT
        assert timeout == 30.0
        blocks = parse_qs(urlparse(url).query)["iss.only"][0]
        key = blocks.split(",", maxsplit=1)[0]
        return _Response(self.payloads[key])


def _table(columns: list[str], rows: list[list[object]]) -> dict[str, object]:
    return {"columns": columns, "data": rows}


def _cursor(total: int, page_size: int = 100) -> dict[str, object]:
    return _table(["INDEX", "TOTAL", "PAGESIZE"], [[0, total, page_size]])


def _history_payload(config: dict[str, object]) -> dict[str, object]:
    columns = config["required_history_columns"]
    values = {
        "BOARDID": "TQOB",
        "TRADEDATE": "2025-12-30",
        "SHORTNAME": "OFZ synthetic",
        "SECID": "SU00000TEST1",
        "NUMTRADES": 10,
        "VALUE": 1_000_000,
        "VOLUME": 1_000,
        "OPEN": 98.0,
        "CLOSE": 98.5,
        "WAPRICE": 98.4,
        "LEGALCLOSEPRICE": 98.45,
        "ACCINT": 12.5,
        "YIELDCLOSE": 14.2,
        "YIELDATWAP": 14.3,
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
    corporate = row.copy()
    corporate[columns.index("SECID")] = "RU00000CORP1"
    return {"history": _table(columns, [row, corporate]), "history.cursor": _cursor(2)}


def _schedule_payloads(config: dict[str, object]) -> dict[str, dict[str, object]]:
    required = config["required_schedule_columns"]
    coupon_values = {
        "isin": "RU00000TEST1",
        "name": "OFZ synthetic",
        "issuevalue": 1_000_000_000,
        "coupondate": "2025-06-30",
        "recorddate": "2025-06-29",
        "startdate": "2024-12-30",
        "initialfacevalue": 1_000,
        "facevalue": 1_000,
        "faceunit": "RUB",
        "value": 40.0,
        "valueprc": 8.0,
        "value_rub": 40.0,
        "secid": "SU00000TEST1",
        "primary_boardid": "TQOB",
    }
    amort_values = {
        "isin": "RU00000TEST1",
        "name": "OFZ synthetic",
        "issuevalue": 1_000_000_000,
        "amortdate": "2025-12-30",
        "facevalue": 1_000,
        "initialfacevalue": 1_000,
        "faceunit": "RUB",
        "valueprc": 100.0,
        "value": 1_000,
        "value_rub": 1_000,
        "data_source": "maturity",
        "secid": "SU00000TEST1",
        "primary_boardid": "TQOB",
    }
    return {
        "coupons": {
            "coupons": _table(
                required["coupons"],
                [[coupon_values[column] for column in required["coupons"]]],
            ),
            "coupons.cursor": _cursor(1, 20),
        },
        "amortizations": {
            "amortizations": _table(
                required["amortizations"],
                [[amort_values[column] for column in required["amortizations"]]],
            ),
            "amortizations.cursor": _cursor(1, 20),
        },
        "offers": {"offers": _table(required["offers"], [])},
    }


def test_real_config_is_source_only_and_sealed() -> None:
    config = subject.load_config()

    assert config["scope"]["computes_return_target_prediction_or_pnl"] is False
    assert config["source"]["history"]["till"] == "2025-12-31"
    assert config["source"]["bondization"]["current_vintage_not_original_publication_vintage"]
    assert config["live_trading_allowed"] is False


def test_history_normalization_filters_non_ofz() -> None:
    config = subject.load_config()
    frame, total, page_size = subject.normalize_history_page(
        json.dumps(_history_payload(config)).encode(),
        expected_start=0,
        retrieved_at=pd.Timestamp("2026-09-02T16:30:00Z"),
        config=config,
    )

    assert total == 2
    assert page_size == 100
    assert list(frame["security_id"]) == ["SU00000TEST1"]
    assert frame["available_at_utc"].iloc[0] == pd.Timestamp("2025-12-30T21:00:00Z")
    assert not ({"return", "target", "prediction", "pnl"} & set(frame.columns))


def test_empty_offer_schedule_is_valid() -> None:
    config = subject.load_config()
    payload = _schedule_payloads(config)["offers"]
    frame, total, page_size = subject.normalize_schedule_page(
        json.dumps(payload).encode(),
        secid="SU00000TEST1",
        kind="offers",
        expected_start=0,
        retrieved_at=pd.Timestamp("2026-09-02T16:30:00Z"),
        config=config,
    )

    assert frame.empty
    assert total == 0
    assert page_size == 20


def test_collect_and_raw_replay_audit(tmp_path: Path) -> None:
    config = subject.load_config()
    payloads = {"history": _history_payload(config), **_schedule_payloads(config)}
    output = tmp_path / "ofz-source"

    subject.collect(
        output,
        session=_Session(payloads),
        retrieved_at="2026-09-02T16:30:00Z",
    )
    result = subject.audit(output)

    assert result["all_true"] is True
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["counts"]["history_rows"] == 1
    assert manifest["counts"]["coupon_events"] == 1
    assert manifest["contains_return_label_target_prediction_or_pnl"] is False
