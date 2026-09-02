from __future__ import annotations

import copy
from pathlib import Path

import pandas as pd
import pytest
import yaml

from market_lab import futures_v52_ofz_carry_roll_down as v52


def _config() -> dict:
    payload = yaml.safe_load(
        (Path(__file__).parents[1] / "configs/v52_ofz_carry_roll_down_v1.yaml").read_text(
            encoding="utf-8-sig"
        )
    )
    return copy.deepcopy(payload)


def test_dirty_price_and_fixed_point_preserve_accounting_identity() -> None:
    assert v52.dirty_price(97.5, 1_000.0, 13.25) == pytest.approx(988.25)
    assert pd.isna(v52.dirty_price(0.0, 1_000.0, 0.0))

    post_nav, desired, cost = v52.solve_post_cost_nav(
        1_000.0, {}, ("A", "B"), 0.001
    )
    assert post_nav == pytest.approx(1_000.0 - cost)
    assert sum(desired.values()) == pytest.approx(post_nav)
    assert desired["A"] == pytest.approx(desired["B"])


def test_month_end_selection_uses_sealed_liquidity_maturity_and_yield_order() -> None:
    config = _config()
    dates = pd.bdate_range("2021-01-01", periods=22)
    yields = {"SU262A": 9.0, "SU262B": 12.0, "SU262C": 11.0, "SU262D": 10.0}
    rows: list[dict] = []
    for security, yield_value in yields.items():
        for date in dates:
            rows.append(
                {
                    "trade_date": date,
                    "security_id": security,
                    "value_rub": 20_000_000.0,
                    "open_clean_pct": 100.0,
                    "close_clean_pct": 100.0,
                    "wap_clean_pct": 100.0,
                    "legal_close_clean_pct": 100.0,
                    "accrued_interest_rub": 5.0,
                    "yield_at_wap_pct": yield_value,
                    "maturity_date": date + pd.Timedelta(days=4 * 365),
                    "face_value": 1_000.0,
                    "currency_id": "RUB",
                    "face_unit": "RUB",
                    "available_at_utc": pd.Timestamp(date, tz="UTC") + pd.Timedelta(days=1),
                }
            )
    prepared = v52.prepare_history(pd.DataFrame(rows), config)
    decisions = v52.build_decisions(prepared, config)
    last_decision = decisions["decision_date"].max()
    selected = decisions.loc[
        decisions["status"].eq("selected") & decisions["decision_date"].eq(last_decision)
    ].sort_values("rank")
    assert selected["security_id"].tolist() == ["SU262B", "SU262C", "SU262D"]
    assert selected["target_weight"].tolist() == pytest.approx([1 / 3, 1 / 3, 1 / 3])
    assert selected["trailing_median_value_rub"].eq(20_000_000.0).all()


def test_simulation_enters_next_open_and_credits_explicit_coupon_entitlement() -> None:
    config = _config()
    config["selection"]["selected_security_count"] = 1
    dates = pd.to_datetime(["2021-01-29", "2021-02-01", "2021-02-02", "2021-02-03"])
    history = pd.DataFrame(
        {
            "trade_date": dates,
            "security_id": ["SU262X"] * len(dates),
            "dirty_open": [1_000.0] * len(dates),
            "dirty_mark": [1_000.0] * len(dates),
        }
    )
    decisions = pd.DataFrame(
        {
            "decision_date": [dates[0]],
            "security_id": ["SU262X"],
            "rank": [1],
            "status": ["selected"],
            "available_at_utc": [pd.Timestamp("2021-01-30", tz="UTC")],
        }
    )
    schedule = pd.DataFrame(
        {
            "event_kind": ["coupon"],
            "security_id": ["SU262X"],
            "event_date": [dates[3]],
            "record_date": [dates[2]],
            "value_rub": [10.0],
            "current_vintage": [True],
        }
    )
    result = v52.simulate(history, schedule, decisions, config, "primary_10bps")
    assert result.completed_rebalances == 1
    assert result.unresolved_rebalances == 0
    assert result.unresolved_cashflows == 0
    assert result.trades.iloc[0]["execution_date"] == dates[1]
    assert result.ledger.loc[result.ledger["date"].eq(dates[3]), "cashflow_credit_rub"].iloc[
        0
    ] > 0
    assert result.ledger["nav"].iloc[-1] > result.ledger["nav"].iloc[-2]
