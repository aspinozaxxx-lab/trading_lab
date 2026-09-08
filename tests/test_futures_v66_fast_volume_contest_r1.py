"""Reproduce nullable contract-count failure and verify reporting-only repair."""

import pandas as pd
import pytest

from market_lab import futures_v66_fast_volume_contest as original
from market_lab import futures_v66_fast_volume_contest_r1 as repair


def positions():
    return pd.DataFrame(
        {
            "session_date": pd.bdate_range("2021-01-04", periods=6),
            "asset_code": "BR",
            "contract_id": [pd.NA, "A", "A", "A", "B", pd.NA],
            "contracts": [0, 1, 2, -1, -1, 0],
        }
    )


def test_parent_nullable_failure_is_reproduced():
    with pytest.raises(TypeError, match="boolean value of NA is ambiguous"):
        original.position_counts(positions())


def test_repair_counts_flat_sign_and_roll_without_mutating_input():
    rows = positions()
    before = rows.copy(deep=True)
    assert repair.position_counts(rows) == {
        "position_entries": 3,
        "round_trips": 3,
        "exposed_asset_sessions": 4,
    }
    pd.testing.assert_frame_equal(rows, before)
    assert original.position_counts is repair.ORIGINAL_COUNTER


def test_repair_preserves_parent_count_for_nonnullable_data():
    rows = positions().fillna({"contract_id": "FLAT"})
    assert repair.position_counts(rows) == original.position_counts(rows)
