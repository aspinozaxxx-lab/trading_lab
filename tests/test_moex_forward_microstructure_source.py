"""Tests for target-free MOEX forward microstructure snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from market_lab.futures import moex_forward_microstructure_source as source


def _futoi_rows(ticker: str) -> list[list[object]]:
    return [
        [
            7,
            101,
            "2026-08-18",
            "10:05:00",
            ticker,
            "FIZ",
            10,
            40,
            -30,
            8,
            4,
            "2026-08-18 10:05:09",
        ],
        [
            7,
            101,
            "2026-08-18",
            "10:05:00",
            ticker,
            "YUR",
            -10,
            30,
            -40,
            4,
            8,
            "2026-08-18 10:05:09",
        ],
    ]


def _tradestats_rows(contract_id: str) -> list[list[object]]:
    values: dict[str, object] = {
        "tradedate": "2026-08-18",
        "tradetime": "10:05:00",
        "secid": contract_id,
        "asset_code": "RTS",
        "vol": 1_000,
        "trades": 100,
        "trades_b": 55,
        "trades_s": 45,
        "val_b": 5_500_000,
        "val_s": 4_500_000,
        "vol_b": 550,
        "vol_s": 450,
        "disb": 0.10,
        "im": 25_000,
        "oi_open": 20_000,
        "oi_high": 20_100,
        "oi_low": 19_900,
        "oi_close": 20_050,
        "SYSTIME": "2026-08-18 10:05:08",
    }
    return [[values[column] for column in source.TRADESTATS_FLOW_COLUMNS]]


def _obstats_rows(contract_id: str) -> list[list[object]]:
    values: dict[str, object] = {
        "tradedate": "2026-08-18",
        "tradetime": "10:05:00",
        "secid": contract_id,
        "asset_code": "RTS",
        "spread_l1": 1.0,
        "spread_l2": 2.0,
        "spread_l3": 3.0,
        "spread_l5": 5.0,
        "spread_l10": 10.0,
        "spread_l20": 20.0,
        "levels_b": 20,
        "levels_s": 21,
        "vol_b_l1": 100,
        "vol_b_l2": 200,
        "vol_b_l3": 300,
        "vol_b_l5": 500,
        "vol_b_l10": 1_000,
        "vol_b_l20": 2_000,
        "vol_s_l1": 90,
        "vol_s_l2": 190,
        "vol_s_l3": 290,
        "vol_s_l5": 490,
        "vol_s_l10": 990,
        "vol_s_l20": 1_990,
        "SYSTIME": "2026-08-18 10:05:09",
    }
    return [[values[column] for column in source.OBSTATS_FLOW_COLUMNS]]


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.content = json.dumps(payload, separators=(",", ":")).encode("utf-8")

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
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if "/futoi/" in parsed.path:
            token = Path(parsed.path).stem
            ticker = {"si": "Si", "ri": "RI", "br": "BR", "mx": "MX"}[token]
            return FakeResponse(
                {
                    "futoi": {
                        "columns": list(source.FUTOI_COLUMNS),
                        "data": _futoi_rows(ticker),
                    }
                }
            )
        contract_id = Path(parsed.path).stem
        if "/tradestats/" in parsed.path:
            assert query["data.columns"] == [",".join(source.TRADESTATS_FLOW_COLUMNS)]
            return FakeResponse(
                {
                    "data": {
                        "columns": list(source.TRADESTATS_FLOW_COLUMNS),
                        "data": _tradestats_rows(contract_id),
                    }
                }
            )
        assert "/obstats/" in parsed.path
        assert query["data.columns"] == [",".join(source.OBSTATS_FLOW_COLUMNS)]
        return FakeResponse(
            {
                "data": {
                    "columns": list(source.OBSTATS_FLOW_COLUMNS),
                    "data": _obstats_rows(contract_id),
                }
            }
        )


def test_urls_request_only_closed_target_free_columns() -> None:
    date = pd.Timestamp("2026-08-18")
    public = source._futoi_url("Si", date, authenticated=False)
    subscribed = source._algopack_url("tradestats", "RIU6", date)
    public_query = parse_qs(urlparse(public).query)
    subscribed_query = parse_qs(urlparse(subscribed).query)

    assert public.startswith(source.PUBLIC_ISS_ROOT)
    assert public_query["futoi.columns"] == [",".join(source.FUTOI_COLUMNS)]
    assert subscribed.startswith(source.AUTHENTICATED_ISS_ROOT)
    assert subscribed_query["data.columns"] == [",".join(source.TRADESTATS_FLOW_COLUMNS)]
    assert not set(source.TRADESTATS_FLOW_COLUMNS) & source.FORBIDDEN_OUTCOME_COLUMNS
    assert not set(source.OBSTATS_FLOW_COLUMNS) & source.FORBIDDEN_OUTCOME_COLUMNS


def test_futoi_availability_is_never_backdated_before_retrieval() -> None:
    frame = pd.DataFrame(_futoi_rows("Si"), columns=source.FUTOI_COLUMNS)
    retrieved = pd.Timestamp("2026-09-02T08:00:00Z")

    normalized = source.normalize_futoi_snapshot(frame, "Si", retrieved, False)

    assert len(normalized) == 2
    assert normalized["available_at"].eq(retrieved).all()
    assert normalized["access_mode"].eq("public_15_day_delayed").all()
    assert normalized["contains_prices_returns_targets_or_pnl"].eq(False).all()


def test_algopack_normalization_contains_flow_and_depth_but_no_prices() -> None:
    frame = pd.DataFrame(
        _tradestats_rows("RIU6"),
        columns=source.TRADESTATS_FLOW_COLUMNS,
    )
    retrieved = pd.Timestamp("2026-08-18T07:07:00Z")

    normalized = source.normalize_algopack_snapshot(
        frame,
        "tradestats",
        "RIU6",
        retrieved,
    )

    assert normalized.iloc[0]["available_at"] == retrieved
    assert normalized.iloc[0]["disb"] == pytest.approx(0.10)
    assert not set(normalized.columns) & source.FORBIDDEN_OUTCOME_COLUMNS


def test_snapshot_is_immutable_hashed_and_never_persists_token(tmp_path: Path) -> None:
    session = FakeSession()
    output = source.collect_forward_snapshot(
        tmp_path,
        "2026-08-18",
        contracts={"RI": "RIU6"},
        token="synthetic-secret",
        session=session,
        retrieved_at_utc="2026-08-18T07:07:00Z",
    )

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    normalized = pd.read_parquet(output / "microstructure.parquet")
    requests = (output / "requests.json").read_text(encoding="utf-8-sig")
    assert manifest["request_count"] == 6
    assert manifest["normalized_rows"] == 10
    assert manifest["token_persisted"] is False
    assert "synthetic-secret" not in requests
    assert normalized["contains_prices_returns_targets_or_pnl"].eq(False).all()
    assert all(source.audit_forward_snapshot(output).values())
    assert all(
        headers.get("Authorization") == "Bearer synthetic-secret"
        for _, headers in session.calls
    )
    with pytest.raises(FileExistsError):
        source.collect_forward_snapshot(
            tmp_path,
            "2026-08-18",
            contracts={"RI": "RIU6"},
            token="synthetic-secret",
            session=FakeSession(),
            retrieved_at_utc="2026-08-18T07:07:00Z",
        )


def test_subscribed_contract_data_requires_token_and_forward_date(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="bearer token"):
        source.collect_forward_snapshot(
            tmp_path,
            "2026-08-18",
            contracts={"RI": "RIU6"},
            session=FakeSession(),
            retrieved_at_utc="2026-08-18T07:07:00Z",
        )
    with pytest.raises(ValueError, match="2026 or later"):
        source.collect_forward_snapshot(
            tmp_path,
            "2025-12-31",
            session=FakeSession(),
            retrieved_at_utc="2026-08-18T07:07:00Z",
        )
