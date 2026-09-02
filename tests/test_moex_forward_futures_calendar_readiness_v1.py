"""Tests for causal MOEX futures-calendar readiness."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_lab.futures import moex_forward_futures_calendar_readiness_v1 as readiness
from market_lab.futures import moex_forward_futures_calendar_source_v1 as source
from tests.test_moex_forward_futures_calendar_source_v1 import _Session


def _snapshot(root: Path) -> Path:
    return source.collect(
        root,
        session=_Session(),
        retrieved_at="2026-09-02T22:50:00Z",
    )


def test_readiness_selects_only_snapshot_available_before_assessment(tmp_path: Path) -> None:
    _snapshot(tmp_path)
    before = readiness.assess(tmp_path, as_of_utc="2026-09-02T22:49:59Z")
    after = readiness.assess(tmp_path, as_of_utc="2026-09-02T23:00:00Z")
    assert before["calendar_source_ready_for_five_session_fallback"] is False
    assert before["blockers"] == ["no_causal_official_calendar_snapshot"]
    assert after["calendar_source_ready_for_five_session_fallback"] is True
    assert after["next_six_trading_sessions_known"] is True
    assert after["contains_return_label_signal_target_prediction_equity_or_pnl"] is False


def test_calendar_for_roll_returns_at_most_six_known_sessions(tmp_path: Path) -> None:
    _snapshot(tmp_path)
    calendar = readiness.calendar_for_roll(
        "2026-09-03T02:00:00+03:00",
        "2026-09-30",
        tmp_path,
    )
    assert len(calendar) == 6
    assert calendar.min() > pd.Timestamp("2026-09-03")


def test_calendar_for_roll_blocks_snapshot_retrieved_after_decision(tmp_path: Path) -> None:
    _snapshot(tmp_path)
    with pytest.raises(ValueError, match="available before decision"):
        readiness.calendar_for_roll(
            "2026-09-02T22:49:59Z",
            "2026-09-30",
            tmp_path,
        )
