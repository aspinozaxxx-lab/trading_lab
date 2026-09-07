"""Closed calendar request/raw replay primitives; no HTTP or source admission."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from market_lab.futures.algopack_fo_witnessed_core_v1 import _block, _date, _decode
from market_lab.futures.algopack_paper_alignment_v1 import utc
from market_lab.futures.algopack_paper_market_core_v1 import _vendor_stamp

PROTOCOL = "algopack_paper_calendar_core_v1"
COLUMNS = ["tradedate", "is_traded", "trade_session_date", "reason", "updatetime"]
MAX_BYTES = 2 * 1024 * 1024
MAX_PAGES = 367  # At most 366 single-row pages plus an explicit empty terminal page.


@dataclass(frozen=True)
class CalendarWindow:
    first: date
    last: date

    def __post_init__(self):
        if (
            type(self.first) is not date
            or type(self.last) is not date
            or self.first > self.last
            or self.first.year != self.last.year
        ):
            raise ValueError("calendar interval must stay within one year")

    @property
    def days(self) -> tuple[date, ...]:
        return tuple(
            self.first + timedelta(days=i) for i in range((self.last - self.first).days + 1)
        )


@dataclass(frozen=True)
class Page:
    start: int
    requested_at: datetime
    received_at: datetime
    raw: bytes


def request_url(window: CalendarWindow, start: int = 0) -> str:
    if not isinstance(window, CalendarWindow):
        raise ValueError("calendar window required")
    if type(start) is not int or not 0 <= start <= len(window.days):
        raise ValueError("calendar cursor outside interval")
    return "https://apim.moex.com/iss/calendars/futures.json?" + urlencode(
        {
            "iss.meta": "off",
            "iss.only": "off_days",
            "show_all_days": 1,
            "off_days.columns": ",".join(COLUMNS),
            "from": window.first.isoformat(),
            "till": window.last.isoformat(),
            "start": start,
        }
    )


def parse_page(page: Page, window: CalendarWindow) -> list[dict]:
    request_url(window, page.start)
    requested, received = utc(page.requested_at), utc(page.received_at)
    if requested > received:
        raise ValueError("calendar receipt predates request")
    if type(page.raw) is not bytes or not 0 < len(page.raw) <= MAX_BYTES:
        raise ValueError("calendar raw byte limit")
    data = _decode(page.raw)
    if set(data) != {"off_days"}:
        raise ValueError("unrequested calendar blocks")
    rows = _block(data, "off_days", COLUMNS)
    if len(rows) > len(window.days):
        raise ValueError("calendar row limit")
    result, previous = [], None
    for row in rows:
        day = date.fromisoformat(_date(row["tradedate"]))
        if not window.first <= day <= window.last or (previous is not None and day <= previous):
            raise ValueError("calendar date scope/order")
        previous = day
        flag, reason = row["is_traded"], row["reason"]
        if flag is not None and (type(flag) is not int or flag not in (0, 1)):
            raise ValueError("invalid calendar trading flag")
        if reason is not None and reason not in ("H", "W", "N", "T"):
            raise ValueError("unknown calendar reason")
        session = (
            None
            if row["trade_session_date"] is None
            else date.fromisoformat(_date(row["trade_session_date"]))
        )
        update = _vendor_stamp(row["updatetime"])
        if update > received:
            raise ValueError("calendar update after receipt")
        # Preserve vendor contradictions as unresolved, not an invented closed day.
        known_open = flag == 1 and reason in ("N", "T", "W")
        known_closed = flag == 0 and reason == "H"
        if reason == "W" and (session is None or session <= day):
            known_open = False
        if reason != "W" and session is not None and session != day:
            known_open = known_closed = False
        status = "OPEN" if known_open else "CLOSED" if known_closed else "UNRESOLVED"
        result.append(
            dict(
                day=day.isoformat(),
                is_traded=flag,
                reason=reason,
                trade_session_date=None if session is None else session.isoformat(),
                updated_at=update.isoformat(),
                status=status,
                strategy_scope="WEEKDAY" if day.weekday() < 5 else "OUT_OF_SCOPE_WEEKEND",
            )
        )
    return result


def replay(pages: tuple[Page, ...], window: CalendarWindow, *, observed_at: datetime) -> dict:
    """Validate raw pagination/coverage. Caller clocks are NOT durable provenance."""
    if type(pages) is not tuple or not 2 <= len(pages) <= MAX_PAGES:
        raise ValueError("calendar needs bounded data and empty terminal pages")
    observed = utc(observed_at)
    rows, evidence, cursor, prior_received = [], [], 0, None
    for index, page in enumerate(pages):
        if not isinstance(page, Page) or page.start != cursor:
            raise ValueError("calendar cursor discontinuity")
        requested, received = utc(page.requested_at), utc(page.received_at)
        if received > observed or (prior_received is not None and requested < prior_received):
            raise ValueError("calendar page chronology")
        parsed = parse_page(page, window)
        if (index == len(pages) - 1) != (len(parsed) == 0):
            raise ValueError("calendar terminal pagination missing or premature")
        rows.extend(parsed)
        cursor += len(parsed)
        if cursor > len(window.days):
            raise ValueError("calendar excessive rows")
        prior_received = received
        evidence.append(
            dict(
                url=request_url(window, page.start),
                raw_sha256=hashlib.sha256(page.raw).hexdigest(),
                requested_at=requested.isoformat(),
                received_at=received.isoformat(),
                rows=len(parsed),
            )
        )
    if [row["day"] for row in rows] != [day.isoformat() for day in window.days]:
        raise ValueError("calendar incomplete/duplicate/out-of-order dates")
    payload = dict(
        protocol_id=PROTOCOL,
        first=window.first.isoformat(),
        last=window.last.isoformat(),
        rows=rows,
        pages=evidence,
    )
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return dict(
        **payload,
        replay_sha256=digest,
        observed_at=observed.isoformat(),
        status="RAW_CALENDAR_REPLAYED_NOT_ADMITTED",
        unresolved_days=[row["day"] for row in rows if row["status"] == "UNRESOLVED"],
        calendar_source_verified=False,
        execution_admitted=False,
    )
