"""Fakticheskoe vremya resheniya i next-open dlya legacy RFUD daily."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Final
from zoneinfo import ZoneInfo

import pandas as pd

FORTS_TIMEZONE: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")  # Chasovoi poyas RFUD.
LEGACY_DECISION_TIME: Final[time] = time(18, 50)  # Close D posle osnovnoi sessii.
LEGACY_NEXT_OPEN_TIME: Final[time] = time(19, 0)  # Bucket start vechernego open D+1.
UNIFIED_SESSION_START: Final[date] = date(2026, 3, 23)  # Smena semantiki vechernei sessii.
PROTECTED_HOLDOUT_START: Final[date] = date(2026, 1, 1)  # Zapret I/O H1-2026.


def _normalize_legacy_calendar(session_dates: Sequence[object]) -> pd.DatetimeIndex:
    """Proveryaet factual rastushchii trade-date calendar tolko do holdout."""
    calendar = pd.DatetimeIndex(pd.to_datetime(list(session_dates), errors="raise"))
    if calendar.tz is not None:
        calendar = calendar.tz_convert(FORTS_TIMEZONE).tz_localize(None)
    calendar = calendar.normalize()
    if calendar.empty or calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise ValueError("RFUD calendar dolzhen byt' nepustym, unikal'nym i rastushchim")
    if any(timestamp.date() >= PROTECTED_HOLDOUT_START for timestamp in calendar):
        raise ValueError("Legacy timing ne mozhet chitat' protected futures holdout")
    return calendar


def legacy_forts_decision_calendar(
    session_dates: Sequence[object],
) -> pd.DataFrame:
    """Stroit D close 18:50 -> next factual trade-date open posle 19:00 D."""
    calendar = _normalize_legacy_calendar(session_dates)
    if len(calendar) < 2:
        raise ValueError("Dlya next-open mapping nuzhny minimum dve factual sessii")
    rows: list[dict[str, object]] = []
    for index in range(len(calendar) - 1):
        decision_date = pd.Timestamp(calendar[index])
        effective_date = pd.Timestamp(calendar[index + 1])
        decision_at = pd.Timestamp(datetime.combine(
            decision_date.date(),
            LEGACY_DECISION_TIME,
            tzinfo=FORTS_TIMEZONE,
        ))
        conservative_open_at = pd.Timestamp(datetime.combine(
            decision_date.date(),
            LEGACY_NEXT_OPEN_TIME,
            tzinfo=FORTS_TIMEZONE,
        ))
        if not decision_at < conservative_open_at:
            raise RuntimeError("Legacy RFUD decision dolzhen predshestvovat' next open")
        rows.append(
            {
                "trade_date": decision_date,
                "decision_at": decision_at.tz_convert("UTC"),
                "effective_date": effective_date,
                "conservative_open_at": conservative_open_at.tz_convert("UTC"),
                "timing_regime": "legacy_evening_belongs_to_next_trade_date",
            }
        )
    return pd.DataFrame(rows)


def require_legacy_timing_period(start_date: date, end_date: date) -> None:
    """Fail-closed zapreshchaet ETS-2026 i protected holdout v legacy evaluator."""
    if end_date < start_date:
        raise ValueError("end_date ran'she start_date")
    if end_date >= PROTECTED_HOLDOUT_START:
        raise ValueError("Protected futures holdout trebuet otdelnyi exact 10m protocol")
    if end_date >= UNIFIED_SESSION_START:
        raise ValueError("Unified session nel'zya ocenivat legacy daily-open mapping")


__all__ = [
    "LEGACY_DECISION_TIME",
    "LEGACY_NEXT_OPEN_TIME",
    "PROTECTED_HOLDOUT_START",
    "UNIFIED_SESSION_START",
    "legacy_forts_decision_calendar",
    "require_legacy_timing_period",
]
