"""Bounded future-only market request/parser core. No HTTP, credentials, or admission."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from market_lab.futures.algopack_fo_witnessed_core_v1 import (
    ASSETS,
    _block,
    _date,
    _decode,
    _outright_asset,
)
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW, TEN, utc
from market_lab.futures.algopack_paper_inference_v1 import TRAINED_AT

CANDLE_COLUMNS = ["begin", "end", "open", "high", "low", "close", "volume"]
BOOK_COLUMNS = [
    "BOARDID",
    "SECID",
    "BUYSELL",
    "PRICE",
    "QUANTITY",
    "SEQNUM",
    "UPDATETIME",
    "DECIMALS",
]
SPEC_COLUMNS = [
    "SECID",
    "BOARDID",
    "ASSETCODE",
    "LASTTRADEDATE",
    "LASTDELDATE",
    "LOTVOLUME",
    "MINSTEP",
    "STEPPRICE",
    "INITIALMARGIN",
    "BUYSELLFEE",
]
COLUMNS = {"candles": CANDLE_COLUMNS, "orderbook": BOOK_COLUMNS, "specs": SPEC_COLUMNS}
BLOCKS = {"candles": "candles", "orderbook": "orderbook", "specs": "securities"}
MAX_DAY_BARS = 144


@dataclass(frozen=True)
class RequestWindow:
    future_start: datetime
    requested_at: datetime

    def __post_init__(self) -> None:
        start, requested = utc(self.future_start), utc(self.requested_at)
        local = start.astimezone(MOSCOW)
        # Full-day candle routes cannot safely request the first partial pre-F day.
        if (
            start <= TRAINED_AT
            or requested < start
            or (local.hour, local.minute, local.second, local.microsecond) != (0, 0, 0, 0)
        ):
            raise ValueError("future request requires post-seal Moscow-midnight boundary")

    @property
    def day(self) -> str:
        return utc(self.requested_at).astimezone(MOSCOW).date().isoformat()


def identity(asset: str, secid: str) -> None:
    if asset not in ASSETS or _outright_asset(secid) != asset:
        raise ValueError("market instrument identity outside fixed universe")


def request_url(kind: str, asset: str, secid: str, window: RequestWindow, start: int = 0) -> str:
    """Only exact entitled apim routes. No anonymous fallback or pre-F date range."""
    identity(asset, secid)
    if kind not in COLUMNS or type(start) is not int or not 0 <= start <= MAX_DAY_BARS:
        raise ValueError("invalid market request kind/cursor")
    if kind != "candles" and start:
        raise ValueError("non-candle cursor forbidden")
    suffix = ".json" if kind == "specs" else f"/{kind}.json"
    base = f"https://apim.moex.com/iss/engines/futures/markets/forts/boards/RFUD/securities/{secid}{suffix}"
    block = BLOCKS[kind]
    params = {"iss.meta": "off", "iss.only": block, f"{block}.columns": ",".join(COLUMNS[kind])}
    if kind == "candles":
        params.update(
            {"from": window.day, "till": window.day, "interval": 10, "start": start, "limit": 500}
        )
    return base + "?" + urlencode(params)


def _rows(raw: bytes, kind: str) -> list[dict]:
    payload = _decode(raw)
    block = BLOCKS[kind]
    if set(payload) != {block}:
        raise ValueError("unrequested market response block")
    return _block(payload, block, COLUMNS[kind])


def _number(value: object, *, integer: bool = False) -> int | float | None:
    if value is None:
        return None
    if (
        type(value) not in (int, float)
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
        or integer
        and type(value) is not int
    ):
        raise ValueError("invalid nonnegative market numeric field")
    return value


def _vendor_stamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing vendor timestamp")
    stamp = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    if stamp.strftime("%Y-%m-%d %H:%M:%S") != value:
        raise ValueError("noncanonical vendor timestamp")
    return utc(stamp.replace(tzinfo=MOSCOW))


def receipt_window(window: RequestWindow, received_at: datetime) -> None:
    received = utc(received_at)
    if received < utc(window.requested_at):
        raise ValueError("receipt precedes request")
    if received.astimezone(MOSCOW).date().isoformat() != window.day:
        raise ValueError("request crossed local midnight; unresolved source date")


def parse_candles(
    raw: bytes, *, asset: str, secid: str, window: RequestWindow, received_at: datetime
) -> list[dict]:
    identity(asset, secid)
    receipt_window(window, received_at)
    rows = _rows(raw, "candles")
    if len(rows) > MAX_DAY_BARS:
        raise ValueError("too many ten-minute bars for one local day")
    times = []
    previous = None
    # Validate the entire time projection before interpreting ANY OHLCV value.
    for row in rows:
        begin, end = _vendor_stamp(row["begin"]), _vendor_stamp(row["end"])
        if (
            begin < utc(window.future_start)
            or begin > utc(received_at)
            or begin.astimezone(MOSCOW).date().isoformat() != window.day
            or end.astimezone(MOSCOW).date().isoformat() != window.day
            or begin.minute % 10
            or begin.second
            or begin.microsecond
            or not begin <= end <= begin + TEN
            or end > utc(received_at)
            or previous is not None
            and begin <= previous
        ):
            raise ValueError("pre-F, non-grid, unordered or invalid candle time")
        previous = begin
        times.append((begin, end))
    result = []
    for row, (begin, end) in zip(rows, times, strict=True):
        values = {name: _number(row[name]) for name in CANDLE_COLUMNS[2:]}
        ohlc = [values[name] for name in ("open", "high", "low", "close")]
        status = "READY"
        if any(value is None for value in ohlc):
            status = "MISSING_OHLC"
        elif (
            any(value <= 0 for value in ohlc)
            or not values["low"]
            <= min(values["open"], values["close"])
            <= max(values["open"], values["close"])
            <= values["high"]
        ):
            status = "INVALID_OHLC"
        if begin + TEN > utc(received_at):
            status = "INCOMPLETE_INTERVAL"
        result.append(
            dict(
                asset=asset,
                secid=secid,
                begin=begin.isoformat(),
                end=end.isoformat(),
                **values,
                price_status=status,
                response_completed_at=utc(received_at).isoformat(),
                available_at=None,
            )
        )
    return result


def finish_candle_pages(pages: list[list[dict]]) -> list[dict]:
    """Require an explicit terminal empty page; do not guess a server page-size limit."""
    if not 1 <= len(pages) <= 3 or pages[-1] or any(not page for page in pages[:-1]):
        raise ValueError("incomplete/nonterminal candle pagination")
    rows = [row for page in pages for row in page]
    stamps = [row["begin"] for row in rows]
    if len(rows) > MAX_DAY_BARS or stamps != sorted(set(stamps)):
        raise ValueError("duplicate/unordered/excess candle pages")
    return rows


def parse_orderbook(
    raw: bytes, *, asset: str, secid: str, window: RequestWindow, received_at: datetime
) -> dict:
    identity(asset, secid)
    receipt_window(window, received_at)
    rows = _rows(raw, "orderbook")
    sides = {"B": [], "S": []}
    seen, sequences, clocks = set(), set(), set()
    missing = False
    for row in rows:
        if row["BOARDID"] != "RFUD" or row["SECID"] != secid or row["BUYSELL"] not in sides:
            raise ValueError("orderbook identity mismatch")
        clock = datetime.strptime(row["UPDATETIME"], "%H:%M:%S")
        if clock.strftime("%H:%M:%S") != row["UPDATETIME"]:
            raise ValueError("orderbook update clock not canonical")
        sequence = _number(row["SEQNUM"], integer=True)
        decimals = _number(row["DECIMALS"], integer=True)
        price = _number(row["PRICE"])
        quantity = _number(row["QUANTITY"], integer=True)
        missing |= any(value is None for value in (sequence, decimals, price, quantity))
        if decimals is not None and decimals > 10:
            raise ValueError("invalid orderbook decimals")
        key = row["BUYSELL"], price
        if key in seen:
            raise ValueError("duplicate orderbook level")
        seen.add(key)
        sequences.add(sequence)
        clocks.add(row["UPDATETIME"])
        sides[row["BUYSELL"]].append(row)
    if any(len(rows) > 20 for rows in sides.values()):
        raise ValueError("orderbook exceeds documented depth")
    status = "OBSERVED_NOT_EXECUTION_ADMITTED"
    bid = ask = None
    if not rows:
        status = "EMPTY_BOOK"
    elif missing:
        status = "MISSING_BOOK_FIELD"
    elif not all(sides.values()):
        status = "ONE_SIDED_BOOK"
    elif any(row["PRICE"] <= 0 or row["QUANTITY"] <= 0 for row in rows):
        status = "NONPOSITIVE_BOOK_LEVEL"
    elif len(sequences) != 1 or len(clocks) != 1:
        status = "MIXED_BOOK_VERSION"
    else:
        bid, ask = max(row["PRICE"] for row in sides["B"]), min(row["PRICE"] for row in sides["S"])
        if bid >= ask:
            status = "LOCKED_OR_CROSSED_BOOK"
    return dict(
        asset=asset,
        secid=secid,
        rows=rows,
        best_bid=bid,
        best_ask=ask,
        status=status,
        response_completed_at=utc(received_at).isoformat(),
        available_at=None,
        exchange_date_verified=False,
        execution_admitted=False,
    )


def parse_specs(
    raw: bytes, *, asset: str, secid: str, window: RequestWindow, received_at: datetime
) -> dict:
    identity(asset, secid)
    receipt_window(window, received_at)
    rows = _rows(raw, "specs")
    if len(rows) != 1:
        raise ValueError("one exact security spec required")
    row = rows[0]
    if row["SECID"] != secid or row["BOARDID"] != "RFUD" or row["ASSETCODE"] != ASSETS[asset]:
        raise ValueError("spec instrument identity mismatch")
    last_trade, last_delivery = _date(row["LASTTRADEDATE"]), _date(row["LASTDELDATE"])
    if last_delivery < last_trade:
        raise ValueError("inverted contract expiry metadata")
    for name in SPEC_COLUMNS[5:]:
        _number(row[name], integer=name == "LOTVOLUME")
    status = "OBSERVED_NOT_EXECUTION_ADMITTED"
    if last_trade <= window.day:
        status = "EXPIRY_OR_EXPIRED"
    elif any(row[name] is None for name in SPEC_COLUMNS[5:]):
        status = "MISSING_SPEC_FIELD"
    elif any(row[name] <= 0 for name in ("LOTVOLUME", "MINSTEP", "STEPPRICE", "INITIALMARGIN")):
        status = "NONPOSITIVE_SPEC"
    return dict(
        asset=asset,
        secid=secid,
        values=row,
        status=status,
        response_completed_at=utc(received_at).isoformat(),
        available_at=None,
        execution_admitted=False,
        broker_fee_known=False,
    )
