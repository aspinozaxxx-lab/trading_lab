"""Kausal'noe sopostavlenie publikacii s pervym dostupnym open MOEX."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import pandas as pd

from market_lab.filings.schema import MOEX_TIMEZONE, PROTECTED_HOLDOUT_START


def first_eligible_session_open(
    published_at: datetime,
    session_opens: Iterable[datetime | pd.Timestamp],
) -> pd.Timestamp:
    """Nahodit pervyi open strogo pozhe mgnoveniya publikacii."""
    if published_at.tzinfo is None or published_at.utcoffset() is None:
        raise ValueError("published_at dolzhen soderzhat' timezone")
    opens = pd.DatetimeIndex(session_opens)
    if opens.empty:
        raise LookupError("Kalendar' MOEX pust")
    if opens.tz is None:
        raise ValueError("Session opens dolzhny soderzhat' timezone")
    opens = opens.tz_convert("UTC")
    if opens.has_duplicates or not opens.is_monotonic_increasing:
        raise ValueError("Session opens dolzhny byt' unikal'nymi i vozrastayushchimi")
    if any(
        timestamp.tz_convert(MOEX_TIMEZONE).date() >= PROTECTED_HOLDOUT_START
        for timestamp in opens
    ):
        raise ValueError("Kalendar' soderzhit zashchishchennyi holdout")
    publication = pd.Timestamp(published_at).tz_convert("UTC")
    position = int(opens.searchsorted(publication, side="right"))
    if position >= len(opens):
        raise LookupError("Posle publikacii net dopushchennoi sessii MOEX")
    return opens[position]


def utc_datetime(value: str) -> datetime:
    """Stroit aware UTC timestamp dlya testov i vneshnih adapterov."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamp dolzhen soderzhat' timezone")
    return parsed.astimezone(UTC)
