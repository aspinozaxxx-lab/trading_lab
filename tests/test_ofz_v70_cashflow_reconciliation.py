"""Synthetic fail-closed zero-entitlement correction, no real bond values."""

import json

import numpy as np
import pandas as pd
import pytest

from market_lab import ofz_v70_cashflow_reconciliation as repair


def frames(ever_held=False):
    days = pd.to_datetime(["2021-01-04", "2022-06-14", "2022-06-15"])
    positions = pd.DataFrame(columns=["date", "security_id", "quantity"])
    trades = pd.DataFrame(columns=["execution_date", "security_id"])
    if ever_held:
        positions = pd.DataFrame([{"date": days[0], "security_id": "SU262TEST", "quantity": 2.0}])
        trades = pd.DataFrame([{"execution_date": days[0], "security_id": "SU262TEST"}])
    positions["quantity"] = positions.quantity.astype(float)
    ledger = pd.DataFrame(
        {
            "date": days,
            "mark_complete": True,
            "held_security_count": [int(ever_held), 0, 0],
            "cashflow_credit_rub": [0.0, 0.0, 0.0],
        }
    )
    schedule = pd.DataFrame(
        [
            {
                "security_id": "SU262TEST",
                "event_kind": "amortization",
                "event_date": days[-1],
                "record_date": pd.NaT,
                "value_rub": 1000.0,
            }
        ]
    )
    return schedule, *repair.prepare_metadata(positions, trades, ledger)


def evidence():
    return [
        {
            "security_id": "SU262TEST",
            "event_date": "2022-06-15",
            "record_date": "2022-06-14",
            "reference": "synthetic",
        }
    ]


def test_never_held_is_proved_zero_without_inventing_a_record_date():
    s, p, t, ledger = frames()
    proof = repair.resolve(s, p, t, ledger, [], 1)
    assert proof[0]["resolution"] == "NEVER_HELD_OR_TRADED"
    assert proof[0]["record_date_evidence"] is None
    assert proof[0]["cash_change_rub"] == 0
    assert s.record_date.isna().all()


def test_ever_held_requires_exact_external_evidence_and_old_exit():
    s, p, t, ledger = frames(True)
    with pytest.raises(ValueError, match="missing exact"):
        repair.resolve(s, p, t, ledger, [], 1)
    proof = repair.resolve(s, p, t, ledger, evidence(), 1)
    assert proof[0]["record_date_evidence"] == "2022-06-14"
    assert proof[0]["entitlement_quantity"] == 0
    assert s.record_date.isna().all()


@pytest.mark.parametrize(
    "field,value",
    [
        ("value_rub", np.nan),
        ("value_rub", 0.0),
        ("event_kind", "coupon"),
    ],
)
def test_missing_amount_or_coupon_cannot_be_released(field, value):
    s, p, t, ledger = frames()
    s.loc[0, field] = value
    with pytest.raises(ValueError, match="unresolved coupon or amount"):
        repair.resolve(s, p, t, ledger, [], 1)


def test_positive_record_date_entitlement_stays_unresolved():
    s, p, t, ledger = frames(True)
    p.loc[0, "date"] = pd.Timestamp("2022-06-14")
    with pytest.raises(ValueError, match="positive entitlement"):
        repair.resolve(s, p, t, ledger, evidence(), 1)


def test_recent_trade_prevents_zero_credit_shortcut():
    s, p, t, ledger = frames(True)
    t.loc[0, "execution_date"] = pd.Timestamp("2022-06-14")
    with pytest.raises(ValueError, match="recent or subsequent"):
        repair.resolve(s, p, t, ledger, evidence(), 1)


def test_unlisted_record_date_is_not_interpolated():
    s, p, t, ledger = frames(True)
    e = evidence()
    e[0]["record_date"] = "2022-06-13"
    with pytest.raises(ValueError, match="invalid record date"):
        repair.resolve(s, p, t, ledger, e, 1)


def test_incomplete_position_book_does_not_mean_zero():
    _, p, t, ledger = frames(True)
    with pytest.raises(ValueError, match="missing holdings"):
        repair.prepare_metadata(p.iloc[:0], t, ledger)


def test_protected_and_missing_calendar_rejected():
    _, p, t, ledger = frames()
    ledger.loc[2, "date"] = pd.Timestamp("2026-01-01")
    with pytest.raises(ValueError, match="protected"):
        repair.prepare_metadata(p, t, ledger)
    ledger.loc[2, "date"] = pd.Timestamp("2022-06-15")
    ledger.loc[2, "mark_complete"] = False
    with pytest.raises(ValueError, match="incomplete marks"):
        repair.prepare_metadata(p, t, ledger)


def test_counts_and_duplicate_evidence_are_fail_closed():
    s, p, t, ledger = frames(True)
    with pytest.raises(ValueError, match="unexpected unresolved"):
        repair.resolve(s, p, t, ledger, evidence(), 2)
    with pytest.raises(ValueError, match="duplicate evidence"):
        repair.resolve(s, p, t, ledger, evidence() * 2, 1)


def test_existing_coupon_credit_independently_replayed():
    s, p, _, ledger = frames(True)
    s.loc[0, "event_kind"] = "coupon"
    s.loc[0, "record_date"] = pd.Timestamp("2021-01-04")
    s.loc[0, "value_rub"] = 25.0
    ledger.loc[2, "cashflow_credit_rub"] = 50.0
    repair.verify_existing_credits(s, p, ledger)
    ledger.loc[2, "cashflow_credit_rub"] = 0.0
    with pytest.raises(ValueError, match="credit drift"):
        repair.verify_existing_credits(s, p, ledger)


def test_configuration_cannot_retune_parent_economics():
    cfg = json.loads(repair.CONFIG.read_text(encoding="utf-8-sig"))
    assert not ({"selection", "execution", "cost_scenarios", "screen_gates"} & set(cfg))
    assert cfg["goal_verified"] is False
    assert len(cfg["record_date_evidence"]) == 6
    assert len(cfg["documents"]) == 6
