"""Tests for the sealed broad cash-carry unit correction replay."""

from __future__ import annotations

import pandas as pd
import pytest

from market_lab.futures import stock_futures_cash_carry_broad_r1 as correction


def test_protocol_parent_and_correction_source_are_exact() -> None:
    protocol = correction.load_protocol()

    assert protocol.config_sha256 == correction.CONFIG_SHA256
    assert len(protocol.events) == 4
    assert len(protocol.affected) == 27


def test_unit_correction_changes_only_affected_contract() -> None:
    frame = pd.DataFrame(
        {
            "contract_id": ["old", "normal"],
            "lot_size_shares": [10, 100],
        }
    )
    affected = pd.DataFrame(
        {"contract_id": ["old"], "back_adjusted_spot_units": [100]}
    )

    result = correction._apply_unit_correction(frame, affected)

    assert result["lot_size_shares"].tolist() == [100, 100]
    assert result["historical_contract_lot_shares"].tolist() == [10, 100]
    assert result["unit_corrected"].tolist() == [True, False]


def test_cashflow_basis_adjusts_only_pre_effective_event_dates() -> None:
    frame = pd.DataFrame(
        {
            "assetcode": ["PLZL", "PLZL", "SBRF"],
            "t": pd.to_datetime(["2025-03-01", "2025-04-01", "2025-03-01"]),
            "cf": [1_000.0, 100.0, 20.0],
        }
    )
    event = {
        "stock_secid": "PLZL",
        "action": "split",
        "factor_new_shares_per_old_share": 10,
        "equity_effective_date": "2025-03-27",
    }

    result, counts = correction._adjust_cashflows(frame, [event])

    assert result["cf"].tolist() == pytest.approx([100.0, 100.0, 20.0])
    assert counts == {"PLZL": 1}
