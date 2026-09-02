"""Tests for the sealed forward stock-futures cash-carry quote source."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_forward_stock_futures_cash_carry_source as source


def _series(asset: str, *, eligible: bool = True) -> dict:
    expiry = "2026-11-20" if eligible else "2027-03-19"
    secid = f"{source.daily_source.AssetSpec.from_symbol(asset).security_prefix}X6"
    return {
        "series": {
            "columns": [
                "SECID",
                "NAME",
                "START_DATE",
                "EXPIRATION_DATE",
                "ASSET_CODE",
                "IS_TRADED",
                "UNDERLYING_ASSET",
            ],
            "data": [[secid, "test", "2026-01-01", expiry, asset, 1, asset]],
        }
    }


def _description(asset: str) -> dict:
    secid = f"{source.daily_source.AssetSpec.from_symbol(asset).security_prefix}X6"
    return {
        "description": {
            "columns": ["NAME", "VALUE"],
            "data": [
                ["SECID", secid],
                ["ASSETCODE", asset],
                ["LOTSIZE", "100"],
                ["TYPE", "futures"],
                ["LSTTRADE", "2026-11-20"],
            ],
        },
        "boards": {"columns": ["SECID", "BOARDID"], "data": [[secid, "RFUD"]]},
    }


def _quote(secid: str, board: str) -> dict:
    return {
        "securities": {"columns": ["SECID", "BOARDID"], "data": [[secid, board]]},
        "marketdata": {
            "columns": ["SECID", "BOARDID", "BID", "OFFER", "SYSTIME", "SEQNUM"],
            "data": [[secid, board, 100.0, 101.0, "2026-09-02 16:00:00", 7]],
        },
    }


class _Client:
    def __init__(self, *, eligible: bool = True) -> None:
        self.eligible = eligible

    def get_json(self, url: str) -> dict:
        config = source.load_protocol().payload
        for asset in config["universe"]["logical_assets"]:
            spot = config["universe"]["spot_secids"][asset]
            prefix = source.daily_source.AssetSpec.from_symbol(asset).security_prefix
            future = f"{prefix}X6"
            if "statistics/engines/futures" in url and f"asset_code={asset}" in url:
                return _series(asset, eligible=self.eligible)
            if f"/securities/{future}.json" in url and "/engines/" not in url:
                return _description(asset)
            if f"/securities/{spot}.json" in url and "/boards/TQBR/" in url:
                return _quote(spot, "TQBR")
            if f"/securities/{future}.json" in url and "/boards/RFUD/" in url:
                return _quote(future, "RFUD")
        raise AssertionError(f"unexpected URL: {url}")


def test_protocol_is_exact_forward_source_only() -> None:
    protocol = source.load_protocol()

    assert protocol.config_sha256 == source.CONFIG_SHA256
    assert (
        protocol.payload["forward_boundary"][
            "historical_backfill_before_earliest_source_date"
        ]
        == "forbidden"
    )
    assert protocol.payload["live_trading_allowed"] is False


def test_collection_rejects_early_stage_and_duplicate(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="earlier than sealed"):
        source.collect(
            "decision",
            tmp_path,
            client=_Client(),
            retrieved_at="2026-09-02T10:00:00Z",
        )

    snapshot = source.collect(
        "decision",
        tmp_path,
        client=_Client(),
        retrieved_at="2026-09-02T13:00:00Z",
    )
    with pytest.raises(FileExistsError, match="duplicate"):
        source.collect(
            "decision",
            tmp_path,
            client=_Client(),
            retrieved_at="2026-09-02T13:01:00Z",
        )
    assert snapshot.name == "snapshot_20260902_decision"


def test_collect_replays_exact_valid_pairs_without_outcomes(tmp_path: Path) -> None:
    snapshot = source.collect(
        "fill",
        tmp_path,
        client=_Client(),
        retrieved_at="2026-09-02T13:00:00Z",
    )
    frame = pd.read_parquet(snapshot / "quotes.parquet")
    checks = source.audit(snapshot)

    assert all(checks.values())
    assert len(frame) == 10
    assert bool(frame["valid"].all())
    assert set(frame["venue_kind"]) == {"spot", "futures"}
    assert not source._forbidden_columns(frame, source.load_protocol())


def test_no_eligible_contract_is_preserved_as_sleep(tmp_path: Path) -> None:
    snapshot = source.collect(
        "decision",
        tmp_path,
        client=_Client(eligible=False),
        retrieved_at="2026-09-02T13:00:00Z",
    )
    manifest = __import__("json").loads(
        (snapshot / "manifest.json").read_text(encoding="utf-8-sig")
    )
    frame = pd.read_parquet(snapshot / "quotes.parquet")

    assert manifest["status"] == "sleeping_no_eligible_contract"
    assert (
        frame.loc[frame["venue_kind"].eq("futures"), "invalid_reason"]
        == "no_eligible_contract"
    ).all()
    assert all(source.audit(snapshot).values())
