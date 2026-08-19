"""Testy vremeni RFUD close D i open sleduyushchego trade-date."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from market_lab.futures.session_timing import (
    legacy_forts_decision_calendar,
    require_legacy_timing_period,
)


def test_friday_decision_maps_to_monday_trade_date_but_friday_evening() -> None:
    """Proveryaet staruyu RFUD semantiku bez calendar-business-day podmeny."""
    mapping = legacy_forts_decision_calendar(
        ["2024-05-31", "2024-06-03", "2024-06-04"]
    )
    first = mapping.iloc[0]
    assert first["trade_date"] == pd.Timestamp("2024-05-31")
    assert first["effective_date"] == pd.Timestamp("2024-06-03")
    assert first["decision_at"] == pd.Timestamp("2024-05-31 15:50:00+00:00")
    assert first["conservative_open_at"] == pd.Timestamp("2024-05-31 16:00:00+00:00")
    assert first["decision_at"] < first["conservative_open_at"]


def test_mapping_is_append_only_before_new_last_session() -> None:
    """Proveryaet neizmennost' gotovyh mapping-strok pri append budushchego dnia."""
    base = legacy_forts_decision_calendar(["2024-06-03", "2024-06-04", "2024-06-05"])
    extended = legacy_forts_decision_calendar(
        ["2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06"]
    )
    pd.testing.assert_frame_equal(base, extended.iloc[: len(base)].reset_index(drop=True))


def test_holdout_and_unified_session_require_separate_exact_protocol() -> None:
    """Proveryaet fail-closed granicu do smeny session semantics v 2026."""
    require_legacy_timing_period(date(2018, 1, 1), date(2025, 12, 31))
    with pytest.raises(ValueError, match="holdout"):
        require_legacy_timing_period(date(2025, 1, 1), date(2026, 1, 1))
    with pytest.raises(ValueError, match="holdout"):
        legacy_forts_decision_calendar(["2025-12-30", "2026-01-05"])
