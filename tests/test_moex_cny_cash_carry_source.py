"""Tests for the sealed MOEX CNY cash-and-carry source."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from market_lab.futures import moex_cny_cash_carry_source as source


def _history(kind: str, secid: str, start: int = 0) -> bytes:
    config = source.load_config()
    required = (
        config["required_spot_columns"]
        if kind == "spot"
        else config["required_futures_columns"]
    )
    values = {column: None for column in required}
    values.update(
        {
            "BOARDID": "CETS" if kind == "spot" else "RFUD",
            "TRADEDATE": "2025-01-02",
            "SHORTNAME": "CNY TOM",
            "SECID": secid,
            "OPEN": 13.0,
            "LOW": 12.9,
            "HIGH": 13.1,
            "CLOSE": 13.05,
            "NUMTRADES": 100,
            "WAPRICE": 13.02,
            "VOLUME": 200,
            "OPENPOSITION": 300,
            "SETTLEPRICE": 13_050.0,
            "ASSETCODE": "CNY",
        }
    )
    return json.dumps(
        {
            "history": {"columns": required, "data": [[values[column] for column in required]]},
            "history.cursor": {
                "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                "data": [[start, 1, 1]],
            },
        }
    ).encode()


def _small_config() -> dict:
    config = copy.deepcopy(source.load_config())
    config["source"]["spot"]["page_size_observed"] = 1
    config["source"]["spot"]["total_rows_observed"] = 1
    config["source"]["futures"]["page_size_observed"] = 1
    config["source"]["futures"]["exact_contracts"] = {"CRH5": "2025-03-20"}
    return config


def _description() -> bytes:
    values = {
        "SECID": "CRH5",
        "ASSETCODE": "CNY",
        "LSTTRADE": "2025-03-20",
        "LOTSIZE": 1000,
        "TYPE": "futures",
    }
    return json.dumps(
        {
            "description": {
                "columns": ["name", "value"],
                "data": [[name, value] for name, value in values.items()],
            },
            "boards": {"columns": ["boardid"], "data": [["RFUD"]]},
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
        if "/iss/securities/CRH5.json" in url:
            return _Response(_description())
        start = int(parse_qs(urlparse(url).query)["start"][0])
        if "CNYRUB_TOM" in url:
            return _Response(_history("spot", "CNYRUB_TOM", start))
        return _Response(_history("futures", "CRH5", start))


def test_config_declares_exact_twelve_contracts_and_no_outcomes() -> None:
    config = source.load_config()

    assert len(config["source"]["futures"]["exact_contracts"]) == 12
    assert config["source"]["futures"]["lot_size_cny"] == 1000
    assert (
        config["hypothesis_for_later_protocol"]
        ["this_protocol_computes_basis_returns_targets_or_pnl"]
        is False
    )
    assert "basis" in config["forbidden_columns"]


def test_normalize_spot_and_futures_are_target_free(monkeypatch) -> None:
    config = _small_config()
    monkeypatch.setattr(source, "load_config", lambda: config)
    retrieval = pd.Timestamp("2026-09-02T00:00:00Z")

    spot, _, _ = source.normalize_page(
        _history("spot", "CNYRUB_TOM"),
        kind="spot",
        secid="CNYRUB_TOM",
        expected_start=0,
        retrieved_at=retrieval,
        config=config,
    )
    futures, _, _ = source.normalize_page(
        _history("futures", "CRH5"),
        kind="futures",
        secid="CRH5",
        expected_start=0,
        retrieved_at=retrieval,
        config=config,
    )

    assert spot.iloc[0]["lot_size_cny"] == 1000
    assert futures.iloc[0]["expiration_date"] == pd.Timestamp("2025-03-20")
    assert not set(config["forbidden_columns"]) & set(spot.columns)
    assert not set(config["forbidden_columns"]) & set(futures.columns)


def test_collect_and_replay_audit(tmp_path: Path, monkeypatch) -> None:
    config = _small_config()
    monkeypatch.setattr(source, "load_config", lambda: config)
    output = source.collect(
        tmp_path / "cny-source",
        session=_Session(),
        retrieved_at="2026-09-02T00:00:00Z",
    )

    checks = source.audit(output)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    assert all(checks.values())
    assert manifest["counts"]["spot_rows"] == 1
    assert manifest["counts"]["futures_rows"] == 1
    assert (output / "audit.json").is_file()
