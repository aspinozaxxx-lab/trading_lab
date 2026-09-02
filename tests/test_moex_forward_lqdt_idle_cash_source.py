"""Tests for the sealed forward LQDT idle-cash source."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_forward_lqdt_idle_cash_source as source


def _payload(*, bid: float = 2.0, offer: float = 2.0001) -> dict:
    return {
        "securities": {
            "columns": [
                "SECID",
                "BOARDID",
                "ISIN",
                "LOTSIZE",
                "MINSTEP",
                "SETTLEDATE",
            ],
            "data": [["LQDT", "TQBR", "RU000A1014L8", 1, 0.0001, "2026-09-03"]],
        },
        "marketdata": {
            "columns": ["SECID", "BOARDID", "BID", "OFFER", "SYSTIME", "SEQNUM"],
            "data": [["LQDT", "TQBR", bid, offer, "2026-09-02 16:00:00", 12]],
        },
    }


class _Client:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or _payload()

    def get_json(self, url: str) -> dict:
        assert "/boards/TQBR/securities/LQDT.json" in url
        assert "iss.only=securities%2Cmarketdata" in url
        return self.payload


def test_config_is_exact_and_forbids_double_use_as_active_collateral() -> None:
    config = source.load_config()

    assert source._sha(source.CONFIG_PATH) == source.CONFIG_SHA256
    assert config["instrument"]["intended_role"].startswith("idle_sleeve_only")
    assert config["economic_separation"][
        "LQDT_units_must_be_zero_while_corresponding_cash_carry_sleeve_is_active"
    ] is True
    assert config["economic_separation"][
        "official_iNAV_values_not_collected_due_to_unresolved_commercial_use_terms"
    ] is True


def test_normalize_preserves_quote_settlement_and_no_outcomes() -> None:
    config = source.load_config()
    frame = source.normalize_response(
        _payload(),
        config=config,
        stage="decision",
        source_date=pd.Timestamp("2026-09-02").date(),
        retrieval=pd.Timestamp("2026-09-02T13:00:00Z"),
    )

    assert tuple(frame.columns) == source.OUTPUT_COLUMNS
    assert bool(frame.iloc[0]["valid"])
    assert frame.iloc[0]["settlement_date"] == "2026-09-03"
    assert frame.iloc[0]["bid"] == 2.0
    assert frame.iloc[0]["offer"] == 2.0001
    forbidden = set(source.load_config()["forbidden_outputs"])
    assert not forbidden & set(frame.columns)


def test_locked_quote_is_invalid_not_zero() -> None:
    frame = source.normalize_response(
        _payload(bid=2.0, offer=2.0),
        config=source.load_config(),
        stage="decision",
        source_date=pd.Timestamp("2026-09-02").date(),
        retrieval=pd.Timestamp("2026-09-02T13:00:00Z"),
    )

    assert not bool(frame.iloc[0]["valid"])
    assert frame.iloc[0]["invalid_reason"] == "crossed_or_locked_quote"


def test_collect_replays_and_rejects_early_or_duplicate(tmp_path: Path) -> None:
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

    assert all(source.audit(snapshot).values())
    assert (snapshot / "audit.json").is_file()
