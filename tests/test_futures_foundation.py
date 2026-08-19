"""Synthetic-testy causal'nogo futures-fundamenta bez setevyh zagruzok."""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import pytest

from market_lab.futures import (
    FuturesAssetSpec,
    RollPlannerConfig,
    build_causal_forward_adjusted_series,
    futures_boards_url,
    futures_candles_url,
    futures_daily_url,
    futures_open_interest_url,
    futures_series_url,
    parse_futures_boards_payload,
    parse_futures_series_catalog,
    parse_futures_series_payload,
    plan_causal_rolls,
    resolve_canonical_board_segments,
    resolve_canonical_contract_segment,
    resolve_contract_segment,
)


def _series_payload() -> dict[str, object]:
    """Stroit payload s povtornym odnocifrovym SECID cherez desyat' let."""
    return {
        "series": {
            "columns": [
                "secid",
                "name",
                "start_date",
                "expiration_date",
                "asset_code",
                "underlying_asset",
                "is_traded",
            ],
            "data": [
                ["SiU4", "Si-9.14", "2013-01-01", "2014-09-15", "Si", "USD", 0],
                ["SiU4", "Si-9.24", "2022-09-09", "2024-09-19", "Si", "USD", 0],
            ],
        }
    }


def _boards_payload() -> dict[str, object]:
    """Stroit dva arhivnyh segmenta odnogo i togo zhe SECID."""
    return {
        "boards": {
            "columns": [
                "secid",
                "boardid",
                "history_from",
                "history_till",
                "listed_from",
                "listed_till",
                "is_primary",
                "is_traded",
            ],
            "data": [
                ["SiU4", "RFUD", "2013-01-01", "2014-09-15", None, None, 1, 0],
                ["SiU4", "RFUD", "2022-09-09", "2024-09-19", None, None, 1, 0],
                ["SiU4", "FIQS", None, None, "2024-09-19", "2024-09-19", 0, 0],
            ],
        }
    }


def _split_alias_payloads() -> tuple[dict[str, object], dict[str, object]]:
    """Stroit real'nyi tip razryva SiH8 na dva SECID odnogo kontrakta."""
    series = {
        "series": {
            "columns": [
                "secid",
                "name",
                "start_date",
                "expiration_date",
                "asset_code",
                "underlying_asset",
                "is_traded",
            ],
            "data": [
                ["SiH8", "SiH8", "2016-11-22", "2018-03-15", "Si", "USD", 0],
                [
                    "SiH8_2018",
                    "Si-3.18",
                    "2016-06-20",
                    "2018-03-15",
                    "Si",
                    "USD",
                    0,
                ],
                [
                    "SiZ0SiH1",
                    "SiZ0SiH1",
                    "2020-01-01",
                    "2020-12-17",
                    "Si",
                    "USD",
                    0,
                ],
                ["USD_CLT", "USD_CLT", None, None, "Si", "USD", 0],
            ],
        }
    }
    boards = {
        "boards": {
            "columns": ["secid", "boardid", "history_from", "history_till"],
            "data": [
                ["SiH8", "RFUD", "2016-06-20", "2017-12-29"],
                ["SiH8_2018", "RFUD", "2018-01-03", "2018-03-16"],
            ],
        }
    }
    return series, boards


def _roll_panel(missing_overlap: bool = False) -> pd.DataFrame:
    """Stroit dva kontrakta s dvuhdnevnoi dominaciei dal'nego kontrakta."""
    dates = pd.date_range("2024-03-11", periods=6, freq="B")
    rows: list[dict[str, object]] = []
    for index, trading_date in enumerate(dates):
        rows.extend(
            [
                {
                    "trade_date": trading_date,
                    "asset_code": "Si",
                    "secid": "SiH4",
                    "expiration_date": "2024-03-21",
                    "volume": [100, 100, 80, 60, 40, 20][index],
                    "open_interest": [1000, 1000, 800, 600, 400, 200][index],
                    "settle": 100.0 + index,
                    "open": 100.0 + index,
                    "high": 101.0 + index,
                    "low": 99.0 + index,
                    "close": 100.5 + index,
                },
                {
                    "trade_date": trading_date,
                    "asset_code": "Si",
                    "secid": "SiM4",
                    "expiration_date": "2024-06-20",
                    "volume": [10, 20, 90, 100, 120, 130][index],
                    "open_interest": [100, 200, 900, 1000, 1200, 1300][index],
                    "settle": np.nan if missing_overlap and index == 3 else 110.0 + index,
                    "open": 110.0 + index,
                    "high": 111.0 + index,
                    "low": 109.0 + index,
                    "close": 110.5 + index,
                },
            ]
        )
    return pd.DataFrame(rows)


def test_archive_secid_is_split_by_full_expiration_and_board_dates() -> None:
    """Proveryaet, chto odin SECID iz raznyh desyatiletii ne skhlepyvaetsya."""
    contracts = parse_futures_series_payload(_series_payload(), FuturesAssetSpec("Si"))
    boards = parse_futures_boards_payload(_boards_payload())
    assert boards.attrs["excluded_undated_count"] == 1
    segments = resolve_canonical_board_segments(contracts, boards)
    assert contracts["canonical_contract_id"].nunique() == 2
    assert segments["canonical_segment_id"].nunique() == 2
    old = resolve_contract_segment(segments, "SiU4", date(2014, 9, 1))
    new = resolve_contract_segment(segments, "SiU4", date(2024, 9, 1))
    assert old.canonical_contract_id != new.canonical_contract_id


def test_split_archive_aliases_are_stitched_into_one_delivery() -> None:
    """Proveryaet skleyku SiH8 i SiH8_2018 bez smesheniya fakticheskih SECID."""
    series_payload, boards_payload = _split_alias_payloads()
    catalog = parse_futures_series_catalog(series_payload, FuturesAssetSpec("Si"))
    contracts = catalog.contracts
    segments = resolve_canonical_board_segments(
        contracts,
        parse_futures_boards_payload(boards_payload),
    )
    assert len(contracts) == 2
    assert len(catalog.excluded) == 2
    assert set(catalog.excluded["exclusion_reason"]) == {
        "calendar_spread_or_service",
        "missing_contract_dates",
    }
    assert contracts["canonical_contract_id"].nunique() == 1
    contract_id = str(contracts["canonical_contract_id"].iloc[0])
    old = resolve_canonical_contract_segment(segments, contract_id, date(2017, 12, 1))
    new = resolve_canonical_contract_segment(segments, contract_id, date(2018, 2, 1))
    assert old.secid == "SiH8"
    assert new.secid == "SiH8_2018"
    assert old.segment_start == date(2016, 6, 20)
    assert new.segment_end == date(2018, 3, 16)


def test_known_asset_registry_maps_logical_ri_to_official_rts() -> None:
    """Proveryaet yavnoe sootvetstvie RI -> RTS i zapret tikhogo pustogo zaprosa."""
    ri = FuturesAssetSpec.from_symbol("RI")
    assert ri.asset_code == "RTS"
    assert ri.security_prefix == "RI"
    with pytest.raises(ValueError, match="Neizvestnyi asset_code"):
        FuturesAssetSpec("RI")


def test_roll_decision_never_uses_future_volume_or_open_interest() -> None:
    """Proveryaet invarianti plana pri izmenenii eshche ne nablyudavshegosya dnya."""
    panel = _roll_panel()
    cutoff = pd.Timestamp("2024-03-14")
    baseline = plan_causal_rolls(panel)
    changed = panel.copy()
    future = changed["trade_date"] > cutoff
    changed.loc[future & (changed["secid"] == "SiM4"), ["volume", "open_interest"]] = 1e9
    revised = plan_causal_rolls(changed)
    columns = ["effective_date", "canonical_contract_id", "action", "reason"]
    next_effective = baseline.loc[
        baseline["decision_date"] == cutoff,
        "effective_date",
    ].max()
    pd.testing.assert_frame_equal(
        baseline.loc[
            baseline["effective_date"] <= next_effective,
            columns,
        ].reset_index(drop=True),
        revised.loc[
            revised["effective_date"] <= next_effective,
            columns,
        ].reset_index(drop=True),
    )
    decisions = baseline.dropna(subset=["decision_date"])
    assert (decisions["observed_through"] < decisions["effective_date"]).all()


def test_two_day_dominance_rolls_only_after_second_confirmed_close() -> None:
    """Proveryaet dve polnye sessii dominacii pered sleduyushchim open."""
    plan = plan_causal_rolls(_roll_panel())
    rolls = plan.loc[plan["action"] == "roll"]
    assert len(rolls) == 1
    assert rolls.iloc[0]["decision_date"] == pd.Timestamp("2024-03-14")
    assert rolls.iloc[0]["effective_date"] == pd.Timestamp("2024-03-15")
    assert rolls.iloc[0]["reason"] == "two_day_volume_oi_dominance"


def test_hard_fallback_is_explicit_parameter_and_can_force_flat() -> None:
    """Proveryaet flat pri blizkoi expiracii bez dostupnogo sleduyushchego kontrakta."""
    panel = _roll_panel().loc[lambda value: value["secid"] == "SiH4"].copy()
    plan = plan_causal_rolls(
        panel,
        RollPlannerConfig(hard_fallback_days=8, overlap_price_column="settle"),
    )
    forced = plan.loc[plan["reason"] == "hard_fallback_without_next_contract"]
    assert not forced.empty
    assert (~forced["tradable"]).all()


def test_forward_adjustment_leaves_past_prices_byte_for_byte_equal() -> None:
    """Proveryaet forward-chain: gap nanosit'sya tol'ko na novyi i budushchii segment."""
    panel = _roll_panel()
    plan = plan_causal_rolls(panel)
    continuous = build_causal_forward_adjusted_series(panel, plan)
    roll_date = plan.loc[plan["action"] == "roll", "effective_date"].iloc[0]
    before = continuous.loc[
        (continuous["trade_date"] < roll_date) & continuous["tradable"], "close"
    ].to_numpy()
    expected = panel.loc[
        panel["secid"].eq("SiH4")
        & panel["trade_date"].isin(
            continuous.loc[
                (continuous["trade_date"] < roll_date) & continuous["tradable"], "trade_date"
            ]
        ),
        "close",
    ].to_numpy()
    np.testing.assert_array_equal(before, expected)
    rolled = continuous.loc[continuous["trade_date"] == roll_date].iloc[0]
    assert rolled["adjustment"] == -10.0


def test_forward_adjustment_keeps_prices_attached_to_rows_after_sort() -> None:
    """Proveryaet, chto nesortirovannyi vhod ne peremeshivaet OHLC mezhdu datami."""
    panel = _roll_panel().sample(frac=1.0, random_state=42).reset_index(drop=True)
    plan = plan_causal_rolls(panel)
    continuous = build_causal_forward_adjusted_series(panel, plan)
    first = continuous.loc[
        (continuous["action"] == "enter") & continuous["tradable"]
    ].iloc[0]
    raw = panel.loc[
        (panel["trade_date"] == first["trade_date"])
        & (panel["secid"] == first["secid"])
    ].iloc[0]
    assert first["open"] == raw["open"]
    assert first["close"] == raw["close"]


def test_forward_adjustment_uses_the_planners_frozen_overlap_anchor() -> None:
    """Proveryaet edinyi close-anchor mezhdu roll-planom i continuous-chain."""
    panel = _roll_panel()
    decision_date = pd.Timestamp("2024-03-14")
    panel.loc[
        (panel["trade_date"] == decision_date) & (panel["secid"] == "SiM4"),
        "close",
    ] = 130.0
    plan = plan_causal_rolls(
        panel,
        RollPlannerConfig(overlap_price_column="close"),
    )
    roll = plan.loc[plan["action"] == "roll"].iloc[0]
    continuous = build_causal_forward_adjusted_series(panel, plan)
    adjusted = continuous.loc[
        continuous["trade_date"] == roll["effective_date"]
    ].iloc[0]
    expected = float(roll["overlap_old_price"] - roll["overlap_new_price"])
    assert expected == 103.5 - 130.0
    assert adjusted["adjustment"] == expected


def test_missing_roll_overlap_becomes_flat_skip_without_synthetic_gap() -> None:
    """Proveryaet zapret skleyki, kogda net odnovremennoi ceny dvuh kontraktov."""
    panel = _roll_panel(missing_overlap=True)
    plan = plan_causal_rolls(panel)
    skipped = plan.loc[plan["reason"] == "missing_roll_overlap"]
    assert len(skipped) == 1
    assert skipped.iloc[0]["action"] == "flat_skip"
    assert not bool(skipped.iloc[0]["tradable"])
    continuous = build_causal_forward_adjusted_series(panel, plan)
    boundary = continuous.loc[
        continuous["trade_date"] == skipped.iloc[0]["effective_date"]
    ].iloc[0]
    assert not bool(boundary["tradable"])
    assert np.isnan(boundary["close"])


def test_absent_overlap_column_cannot_create_tradable_roll() -> None:
    """Proveryaet fail-closed, kogda voobsche net settle ili close dlya skleyki."""
    panel = _roll_panel().drop(columns=["settle", "close"])
    plan = plan_causal_rolls(panel)
    assert not (plan["action"] == "roll").any()
    skipped = plan.loc[plan["reason"] == "missing_roll_overlap"]
    assert len(skipped) == 1
    assert not bool(skipped.iloc[0]["tradable"])


def test_official_iss_url_builders_use_contract_board_and_asset_routes() -> None:
    """Proveryaet marshruty series, 10m, daily history i agregirovannogo OI."""
    asset = FuturesAssetSpec("Si")
    series = futures_series_url(asset)
    boards = futures_boards_url("SiU4")
    candles = futures_candles_url(
        asset,
        "SiU4",
        date(2024, 9, 1),
        date(2024, 9, 19),
        board_id="RFUD",
        cursor_start=500,
    )
    daily = futures_daily_url(asset, "SiU4", board_id="RFUD", cursor_start=100)
    open_interest = futures_open_interest_url(asset)
    assert "/statistics/engines/futures/markets/forts/series.json" in series
    series_query = parse_qs(urlparse(series).query)
    assert series_query["asset_code"] == ["Si"]
    assert series_query["show_expired"] == ["1"]
    assert "/securities/SiU4.json" in boards
    assert "/boards/RFUD/securities/SiU4/candles.json" in candles
    assert parse_qs(urlparse(candles).query)["interval"] == ["10"]
    assert parse_qs(urlparse(candles).query)["start"] == ["500"]
    assert "/history/engines/futures/markets/forts/boards/RFUD/" in daily
    assert parse_qs(urlparse(daily).query)["start"] == ["100"]
    assert "iss.only" not in parse_qs(urlparse(daily).query)
    assert "start" not in parse_qs(urlparse(open_interest).query)
