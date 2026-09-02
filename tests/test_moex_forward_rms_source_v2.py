"""Tests for immutable forward MOEX RMS risk/cashflow snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from market_lab.futures import moex_forward_rms_source_v2 as source


def _payload(table: str, risk_date: str = "2026-09-02") -> bytes:
    config = source.load_config()
    columns = config["source"]["tables"][table]["required_columns"]
    rows = []
    for index, asset in enumerate(("Si", "RTS")):
        row = {column: None for column in columns}
        row.update(
            {
                "tradedate": risk_date if table != "cashflow" else "2026-08-26",
                "assetcode": asset,
                "updatetime": "2026-09-02 03:00:00",
            }
        )
        if table == "cashflow":
            row.update(
                {
                    "t": f"2026-10-0{index + 1}",
                    "cf": 10.0 + index,
                    "cfrisk": 1.0,
                }
            )
        rows.append(list(row.values()))
    return json.dumps(
        {
            table: {"columns": columns, "data": rows},
            f"{table}.cursor": {
                "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                "data": [[0, len(rows), 100]],
            },
        }
    ).encode()


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _Session:
    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> _Response:
        assert headers["User-Agent"] == source.USER_AGENT
        assert timeout == 30.0
        assert parse_qs(urlparse(url).query)["start"] == ["0"]
        table = urlparse(url).path.rsplit("/", 1)[-1].removesuffix(".json")
        return _Response(_payload(table))


def test_config_seals_independent_cashflow_clock() -> None:
    config = source.load_config()

    assert config["correction_scope"]["parameters_changed"] == 0
    assert config["temporal_semantics_v2"]["cashflow_tradedate_may_precede_risk_source_date"]
    assert config["sequential_research"]["discovery_unique_source_dates"] == 60


def test_normalize_accepts_older_current_cashflow_but_not_old_risk() -> None:
    config = source.load_config()
    retrieval = pd.Timestamp("2026-09-02T04:00:00Z")
    cash, _, _ = source.parse_page(_payload("cashflow"), "cashflow", config)
    risk, _, _ = source.parse_page(_payload("limits"), "limits", config)

    normalized_cash = source.normalize_table(cash, "cashflow", retrieval, config)
    normalized_risk = source.normalize_table(risk, "limits", retrieval, config)

    assert normalized_cash["tradedate"].dt.date.astype(str).unique().tolist() == [
        "2026-08-26"
    ]
    assert normalized_risk["tradedate"].dt.date.astype(str).unique().tolist() == [
        "2026-09-02"
    ]
    assert normalized_cash["available_at_utc"].eq(retrieval).all()


def test_collect_and_raw_replay_audit(tmp_path: Path) -> None:
    snapshot = source.collect(
        tmp_path,
        session=_Session(),
        retrieved_at="2026-09-02T04:00:00Z",
    )
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8-sig"))
    checks = source.audit(snapshot)

    assert all(checks.values())
    assert manifest["risk_source_date"] == "2026-09-02"
    assert manifest["cashflow_source_dates"] == ["2026-08-26"]
    assert manifest["contains_price_return_target_prediction_or_pnl"] is False
    assert len(manifest["raw_pages"]) == 3
    assert (snapshot / "audit.json").is_file()
