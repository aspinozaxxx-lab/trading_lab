"""Tests for target-free forward MOEX equity microstructure snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.stocks import moex_forward_equity_microstructure_source as source


def _row(dataset: str, ticker: str) -> list[object]:
    values: dict[str, object] = {
        "tradedate": "2026-09-02",
        "tradetime": "10:10:00",
        "secid": ticker,
        "vol": 1000,
        "val": 100_000.0,
        "trades": 50,
        "trades_b": 30,
        "trades_s": 20,
        "val_b": 60_000.0,
        "val_s": 40_000.0,
        "vol_b": 600,
        "vol_s": 400,
        "disb": 0.2,
        "put_orders_b": 100,
        "put_orders_s": 90,
        "put_val_b": 2_000_000.0,
        "put_val_s": 1_800_000.0,
        "put_vol_b": 2000,
        "put_vol_s": 1800,
        "put_vol": 3800,
        "put_val": 3_800_000.0,
        "put_orders": 190,
        "cancel_orders_b": 80,
        "cancel_orders_s": 70,
        "cancel_val_b": 1_600_000.0,
        "cancel_val_s": 1_400_000.0,
        "cancel_vol_b": 1600,
        "cancel_vol_s": 1400,
        "cancel_vol": 3000,
        "cancel_val": 3_000_000.0,
        "cancel_orders": 150,
        "spread_bbo": 0.1,
        "spread_lv10": 0.5,
        "spread_1mio": 0.3,
        "levels_b": 20,
        "levels_s": 22,
        "imbalance_vol_bbo": 0.1,
        "imbalance_val_bbo": 0.1,
        "imbalance_vol": -0.2,
        "imbalance_val": -0.25,
        "SYSTIME": "2026-09-02 10:10:15",
    }
    return [values[column] for column in source.DATASET_COLUMNS[dataset]]


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.content = json.dumps(payload, separators=(",", ":")).encode()

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> FakeResponse:
        assert timeout == 60.0
        self.calls.append((url, headers))
        dataset = Path(urlparse(url).path).stem
        columns = source.DATASET_COLUMNS[dataset]
        return FakeResponse(
            {
                "data": {
                    "columns": list(columns),
                    "data": [_row(dataset, "SBER"), _row(dataset, "NOT_IN_UNIVERSE")],
                }
            }
        )


def test_urls_are_authenticated_target_free_and_latest_only() -> None:
    date = pd.Timestamp("2026-09-02")
    for dataset, columns in source.DATASET_COLUMNS.items():
        url = source.dataset_url(dataset, date)
        query = parse_qs(urlparse(url).query)
        assert url.startswith(source.AUTHENTICATED_ISS_ROOT)
        assert query["latest"] == ["1"]
        assert query["data.columns"] == [",".join(columns)]
        assert not set(columns) & source.FORBIDDEN_PRICE_OUTCOME_COLUMNS


def test_normalization_filters_universe_and_never_backdates_availability() -> None:
    dataset = "tradestats"
    frame = pd.DataFrame(
        [_row(dataset, "SBER"), _row(dataset, "OTHER")],
        columns=source.DATASET_COLUMNS[dataset],
    )
    retrieved = pd.Timestamp("2026-09-02T08:00:00Z")

    normalized = source.normalize_dataset(frame, dataset, retrieved)

    assert normalized["secid"].tolist() == ["SBER"]
    assert normalized["available_at"].ge(retrieved).all()
    assert normalized["contains_absolute_price_return_target_or_pnl"].eq(False).all()
    assert not set(normalized.columns) & source.FORBIDDEN_PRICE_OUTCOME_COLUMNS


def test_snapshot_is_immutable_hashed_and_never_persists_token(tmp_path: Path) -> None:
    session = FakeSession()
    output = source.collect_snapshot(
        tmp_path,
        "2026-09-02",
        token="synthetic-secret",
        session=session,
        retrieved_at_utc="2026-09-02T08:00:00Z",
    )

    manifest_text = (output / "manifest.json").read_text(encoding="utf-8-sig")
    requests_text = (output / "requests.json").read_text(encoding="utf-8-sig")
    manifest = json.loads(manifest_text)
    assert manifest["request_count"] == 3
    assert manifest["normalized_rows"] == 3
    assert manifest["token_persisted"] is False
    assert "synthetic-secret" not in manifest_text + requests_text
    assert all(source.audit_snapshot(output).values())
    assert all(
        headers["Authorization"] == "Bearer synthetic-secret"
        for _, headers in session.calls
    )
    with pytest.raises(FileExistsError):
        source.collect_snapshot(
            tmp_path,
            "2026-09-02",
            token="synthetic-secret",
            session=FakeSession(),
            retrieved_at_utc="2026-09-02T08:00:00Z",
        )


def test_collection_requires_token_and_forward_date(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="bearer token"):
        source.collect_snapshot(
            tmp_path,
            "2026-09-02",
            token="",
            session=FakeSession(),
            retrieved_at_utc="2026-09-02T08:00:00Z",
        )
    with pytest.raises(ValueError, match="2026 or later"):
        source.collect_snapshot(
            tmp_path,
            "2025-12-31",
            token="synthetic-secret",
            session=FakeSession(),
            retrieved_at_utc="2026-09-02T08:00:00Z",
        )


def test_closed_response_schema_fails_on_forbidden_or_extra_field() -> None:
    payload = {
        "data": {
            "columns": [*source.TRADESTATS_COLUMNS, "pr_close"],
            "data": [],
        }
    }
    with pytest.raises(ValueError, match="closed schema"):
        source._table(payload, source.TRADESTATS_COLUMNS)
