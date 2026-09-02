"""Tests for the sealed historical point-in-time MOEX RMS source."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd

from market_lab.futures import moex_rms_historical_pit_source as source


def _payload(table: str, query_date: str) -> bytes:
    config = source.load_config()
    columns = config["source"]["tables"][table]["required_columns"]
    rows = []
    for index, asset in enumerate(("Si", "RTS")):
        row = {column: None for column in columns}
        row.update(
            {
                "tradedate": query_date,
                "assetcode": asset,
                "updatetime": f"{query_date} 12:00:00",
            }
        )
        if table == "cashflow":
            row.update({"t": f"2026-02-0{index + 1}", "cf": 10.0, "cfrisk": 1.0})
        rows.append(list(row.values()))
    return json.dumps(
        {
            table: {"columns": columns, "data": rows},
            f"{table}.cursor": {
                "columns": ["INDEX", "TOTAL", "PAGESIZE"],
                "data": [[0, len(rows), 1000]],
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
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        assert query["start"] == ["0"]
        table = parsed.path.rsplit("/", 1)[-1].removesuffix(".json")
        return _Response(_payload(table, query["date"][0]))


class _AsOfCashflowSession(_Session):
    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float
    ) -> _Response:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        table = parsed.path.rsplit("/", 1)[-1].removesuffix(".json")
        returned_date = (
            "2025-12-30" if table == "cashflow" else query["date"][0]
        )
        return _Response(_payload(table, returned_date))


def test_config_seals_structural_zero_change_rule_and_pre2026_boundary() -> None:
    config = source.load_config()

    assert config["temporal_boundary"]["protected_from"] == "2026-01-01"
    assert (
        config["future_hypothesis_constraints"]["structural_margin_rule_threshold"]
        == "zero_change_only_not_percentile_fit"
    )
    assert config["objective"]["returns_targets_predictions_or_pnl_allowed"] is False
    assert config["source"]["tables"]["cashflow"]["date_semantics"] == (
        "latest_snapshot_as_of_query_date"
    )
    assert config["source"]["tables"]["cashflow"][
        "maximum_snapshot_age_calendar_days"
    ] == 62


def test_small_archive_collects_and_raw_replays(tmp_path: Path) -> None:
    output = tmp_path / "rms"
    ranges = {table: ("2025-12-30", "2025-12-30") for table in source.TABLES}

    source.collect(
        output,
        date_ranges=ranges,
        session=_Session(),
        retrieved_at="2026-09-02T01:30:00Z",
    )
    checks = source.audit(output)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))

    assert all(checks.values())
    assert manifest["canonical_full_range"] is False
    assert manifest["request_date_count"] == 3
    assert manifest["raw_page_count"] == 3
    assert manifest["contains_returns_targets_predictions_or_pnl"] is False
    assert manifest["processed"]["limits"]["rows"] == 2


def test_cashflow_asof_repeats_keep_earliest_query_date(tmp_path: Path) -> None:
    output = tmp_path / "rms-asof"
    ranges = {
        table: (
            ("2025-12-30", "2025-12-31")
            if table == "cashflow"
            else ("2025-12-30", "2025-12-30")
        )
        for table in source.TABLES
    }

    source.collect(
        output,
        date_ranges=ranges,
        session=_AsOfCashflowSession(),
        retrieved_at="2026-09-02T01:30:00Z",
    )
    cashflow = pd.read_parquet(output / "cashflow.parquet")

    assert len(cashflow) == 2
    assert cashflow["tradedate"].dt.date.astype(str).eq("2025-12-30").all()
    assert cashflow["archive_query_date"].dt.date.astype(str).eq("2025-12-30").all()
    assert all(source.audit(output).values())
