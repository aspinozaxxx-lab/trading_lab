"""Tests for the sealed forward money-market fund pool source."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import pytest

from market_lab.futures import moex_forward_money_market_fund_pool_source as source

DECLARATIONS = {
    "LQDT": ("RU000A1014L8", "3915"),
    "SBMM": ("RU000A103RF1", "4607"),
    "AKMM": ("RU000A104X08", "5012"),
    "TMON": ("RU000A106DL2", "5229"),
}


def _payload(secid: str, *, depth: float = 5000.0) -> dict:
    isin, registration = DECLARATIONS[secid]
    return {
        "securities": {
            "columns": [
                "SECID",
                "BOARDID",
                "ISIN",
                "REGNUMBER",
                "LOTSIZE",
                "MINSTEP",
                "SETTLEDATE",
            ],
            "data": [[secid, "TQBR", isin, registration, 1, 0.0001, "2026-09-03"]],
        },
        "marketdata": {
            "columns": [
                "SECID",
                "BOARDID",
                "BID",
                "OFFER",
                "BIDDEPTH",
                "OFFERDEPTH",
                "BIDDEPTHT",
                "OFFERDEPTHT",
                "NUMBIDS",
                "NUMOFFERS",
                "SYSTIME",
                "SEQNUM",
            ],
            "data": [
                [secid, "TQBR", 2.0, 2.0001, depth, depth, 0, 0, 0, 0,
                 "2026-09-02 16:00:00", 12]
            ],
        },
    }


class _Client:
    def get_json(self, url: str) -> dict:
        secid = Path(urlparse(url).path).stem
        assert secid in DECLARATIONS
        assert "iss.only=securities%2Cmarketdata" in url
        return _payload(secid)


def test_config_is_exact_fixed_and_source_only() -> None:
    config = source.load_config()

    assert source._sha(source.CONFIG_PATH) == source.CONFIG_SHA256
    assert tuple(config["fixed_universe"]["funds"]) == tuple(DECLARATIONS)
    assert (
        config["role_constraints"]["simultaneous_fund_and_cash_collateral_credit"]
        == "forbidden"
    )
    assert (
        config["economic_separation"][
            "no_fund_ranking_before_60_complete_discovery_pairs"
        ]
        is True
    )


def test_normalize_preserves_depth_zero_context_and_no_outcomes() -> None:
    frame = source.normalize_response(
        _payload("LQDT"),
        "LQDT",
        config=source.load_config(),
        stage="decision",
        source_date=pd.Timestamp("2026-09-02").date(),
        retrieval=pd.Timestamp("2026-09-02T13:00:00Z"),
    )

    assert tuple(frame.columns) == source.OUTPUT_COLUMNS
    assert bool(frame.iloc[0]["valid"])
    assert frame.iloc[0]["total_bid_depth_units"] == 0
    assert frame.iloc[0]["number_of_offers"] == 0
    assert not source._forbidden(frame, source.load_config())


def test_missing_required_best_depth_is_invalid() -> None:
    frame = source.normalize_response(
        _payload("LQDT", depth=0),
        "LQDT",
        config=source.load_config(),
        stage="decision",
        source_date=pd.Timestamp("2026-09-02").date(),
        retrieval=pd.Timestamp("2026-09-02T13:00:00Z"),
    )

    assert not bool(frame.iloc[0]["valid"])
    assert "positive_two_sided_depth_missing" in frame.iloc[0]["invalid_reason"]


def test_collect_replays_four_funds_and_rejects_duplicate(tmp_path: Path) -> None:
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
    frame = pd.read_parquet(snapshot / "fund_quotes.parquet")
    assert set(frame["secid"]) == set(DECLARATIONS)
    assert frame["valid"].all()
