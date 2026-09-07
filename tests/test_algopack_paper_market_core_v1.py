"""Synthetic market schema/time tests; never call an exchange endpoint."""

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from market_lab.futures import algopack_paper_market_core_v1 as core

START = datetime(2026, 9, 7, 21, tzinfo=UTC)  # Synthetic next Moscow midnight, not actual F.
REQUESTED = datetime(2026, 9, 8, 8, 4, tzinfo=UTC)
RECEIVED = REQUESTED + timedelta(seconds=1)
WINDOW = core.RequestWindow(START, REQUESTED)
ARGS = dict(asset="SI", secid="SiU6", window=WINDOW, received_at=RECEIVED)


def raw(kind, rows):
    return json.dumps(
        {core.BLOCKS[kind]: dict(columns=core.COLUMNS[kind], data=rows)}, allow_nan=False
    ).encode()


def candle(**changes):
    row = dict(
        begin="2026-09-08 10:50:00",
        end="2026-09-08 10:59:59",
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        volume=5.0,
    )
    row.update(changes)
    return [row[name] for name in core.CANDLE_COLUMNS]


def book(**changes):
    row = dict(
        BOARDID="RFUD",
        SECID="SiU6",
        BUYSELL="B",
        PRICE=100.0,
        QUANTITY=3,
        SEQNUM=17,
        UPDATETIME="11:04:00",
        DECIMALS=0,
    )
    row.update(changes)
    return [row[name] for name in core.BOOK_COLUMNS]


def specs(**changes):
    row = dict(
        SECID="SiU6",
        BOARDID="RFUD",
        ASSETCODE="Si",
        LASTTRADEDATE="2026-09-17",
        LASTDELDATE="2026-09-17",
        LOTVOLUME=1,
        MINSTEP=1.0,
        STEPPRICE=1.0,
        INITIALMARGIN=10000.0,
        BUYSELLFEE=2.0,
    )
    row.update(changes)
    return [row[name] for name in core.SPEC_COLUMNS]


@pytest.mark.parametrize("kind", list(core.COLUMNS))
def test_only_canonical_paid_current_day_route(kind):
    url = core.request_url(kind, "SI", "SiU6", WINDOW)
    parsed = urlsplit(url)
    assert parsed.scheme == "https" and parsed.netloc == "apim.moex.com"
    assert "/RFUD/securities/SiU6" in parsed.path
    query = parse_qs(parsed.query)
    assert query["iss.only"] == [core.BLOCKS[kind]]
    assert query[core.BLOCKS[kind] + ".columns"] == [",".join(core.COLUMNS[kind])]
    if kind == "candles":
        assert query["from"] == query["till"] == ["2026-09-08"]
        assert query["interval"] == ["10"] and query["start"] == ["0"]


@pytest.mark.parametrize(
    "start, requested",
    [
        (START + timedelta(minutes=1), REQUESTED),
        (START, START - timedelta(seconds=1)),
        (datetime(2026, 9, 6, 21, tzinfo=UTC), REQUESTED),
        (START.replace(tzinfo=None), REQUESTED),
    ],
)
def test_no_request_window_before_future_boundary(start, requested):
    with pytest.raises(ValueError):
        core.RequestWindow(start, requested)


@pytest.mark.parametrize(
    "kind, asset, secid, cursor",
    [
        ("trades", "SI", "SiU6", 0),
        ("candles", "SI", "BRV6", 0),
        ("candles", "SI", "SiU6/../../other", 0),
        ("candles", "SI", "SiU6", True),
        ("candles", "SI", "SiU6", 145),
        ("orderbook", "SI", "SiU6", 1),
    ],
)
def test_no_route_escape(kind, asset, secid, cursor):
    with pytest.raises(ValueError):
        core.request_url(kind, asset, secid, WINDOW, cursor)


def test_completed_candle_and_actual_receipt():
    result = core.parse_candles(raw("candles", [candle()]), **ARGS)
    assert result[0]["price_status"] == "READY"
    assert result[0]["begin"] == "2026-09-08T07:50:00+00:00"
    assert result[0]["response_completed_at"] == RECEIVED.isoformat()
    assert result[0]["available_at"] is None  # A response is not a committed source version.
    assert result[0]["close"] == 101.0


@pytest.mark.parametrize(
    "change, expected",
    [
        (dict(open=None), "MISSING_OHLC"),
        (dict(low=999.0), "INVALID_OHLC"),
        (dict(open=0.0), "INVALID_OHLC"),
        (dict(begin="2026-09-08 11:00:00", end="2026-09-08 11:03:59"), "INCOMPLETE_INTERVAL"),
    ],
)
def test_candle_masks_not_dropped(change, expected):
    result = core.parse_candles(raw("candles", [candle(**change)]), **ARGS)
    assert len(result) == 1 and result[0]["price_status"] == expected


def test_whole_time_projection_rejected_before_any_numeric_interpretation(monkeypatch):
    calls = []
    monkeypatch.setattr(core, "_number", lambda value, **kwargs: calls.append(value))
    old = candle(begin="2026-09-07 10:50:00", end="2026-09-07 10:59:59")
    with pytest.raises(ValueError, match="pre-F"):
        core.parse_candles(raw("candles", [candle(), old]), **ARGS)
    assert calls == []


@pytest.mark.parametrize(
    "change",
    [
        dict(begin="2026-09-08 10:51:00"),
        dict(end="2026-09-08 11:04:01"),
        dict(begin="2026-09-09 10:50:00"),
        dict(begin="2026-09-08T10:50:00"),
    ],
)
def test_candle_invalid_time(change):
    with pytest.raises(ValueError):
        core.parse_candles(raw("candles", [candle(**change)]), **ARGS)


def test_duplicate_candles_fail():
    with pytest.raises(ValueError, match="unordered"):
        core.parse_candles(raw("candles", [candle(), candle()]), **ARGS)


def test_book_opaque_sequence_never_proves_exchange_date_or_fill():
    result = core.parse_orderbook(
        raw("orderbook", [book(), book(BUYSELL="S", PRICE=101.0)]), **ARGS
    )
    assert result["best_bid"] == 100.0 and result["best_ask"] == 101.0
    assert result["status"] == "OBSERVED_NOT_EXECUTION_ADMITTED"
    assert result["exchange_date_verified"] is result["execution_admitted"] is False
    assert result["rows"][0]["SEQNUM"] == 17  # Not parsed as YYYYMMDDHHMMSS.


@pytest.mark.parametrize(
    "rows, status",
    [
        ([], "EMPTY_BOOK"),
        ([book()], "ONE_SIDED_BOOK"),
        ([book(), book(BUYSELL="S", PRICE=100.0)], "LOCKED_OR_CROSSED_BOOK"),
        ([book(), book(BUYSELL="S", PRICE=None)], "MISSING_BOOK_FIELD"),
        ([book(QUANTITY=0), book(BUYSELL="S", PRICE=101.0)], "NONPOSITIVE_BOOK_LEVEL"),
        ([book(), book(BUYSELL="S", PRICE=101.0, SEQNUM=18)], "MIXED_BOOK_VERSION"),
    ],
)
def test_book_unresolved_is_not_zero_cost(rows, status):
    result = core.parse_orderbook(raw("orderbook", rows), **ARGS)
    assert result["status"] == status and result["execution_admitted"] is False


@pytest.mark.parametrize(
    "change",
    [
        dict(SECID="SiZ6"),
        dict(BOARDID="OTHER"),
        dict(BUYSELL="UNKNOWN"),
        dict(QUANTITY=-1),
        dict(SEQNUM=True),
        dict(UPDATETIME="11:4:00"),
    ],
)
def test_book_invalid_identity_or_values(change):
    with pytest.raises(ValueError):
        core.parse_orderbook(raw("orderbook", [book(**change)]), **ARGS)


def test_book_duplicate_levels_fail():
    with pytest.raises(ValueError, match="duplicate"):
        core.parse_orderbook(raw("orderbook", [book(), book()]), **ARGS)


@pytest.mark.parametrize(
    "change, status",
    [
        ({}, "OBSERVED_NOT_EXECUTION_ADMITTED"),
        (dict(BUYSELLFEE=None), "MISSING_SPEC_FIELD"),
        (dict(BUYSELLFEE=0.0), "OBSERVED_NOT_EXECUTION_ADMITTED"),
        (dict(STEPPRICE=0.0), "NONPOSITIVE_SPEC"),
        (dict(LASTTRADEDATE="2026-09-08"), "EXPIRY_OR_EXPIRED"),
    ],
)
def test_specs_known_zero_fee_distinguished_from_missing(change, status):
    result = core.parse_specs(raw("specs", [specs(**change)]), **ARGS)
    assert result["status"] == status
    assert result["broker_fee_known"] is result["execution_admitted"] is False


@pytest.mark.parametrize(
    "kind, parser",
    [
        ("candles", core.parse_candles),
        ("orderbook", core.parse_orderbook),
        ("specs", core.parse_specs),
    ],
)
def test_unrequested_blocks_and_reversed_clock_rejected(kind, parser):
    with pytest.raises(ValueError, match="unrequested"):
        parser(b'{"marketdata":{"columns":[],"data":[]}}', **ARGS)
    with pytest.raises(ValueError, match="precedes"):
        parser(raw(kind, []), **{**ARGS, "received_at": REQUESTED - timedelta(seconds=1)})


def test_midnight_crossing_is_unresolved():
    with pytest.raises(ValueError, match="midnight"):
        core.parse_candles(
            raw("candles", []), **{**ARGS, "received_at": REQUESTED + timedelta(days=1)}
        )


def test_pagination_requires_empty_terminal_not_short_page_assumption():
    page = core.parse_candles(raw("candles", [candle()]), **ARGS)
    assert core.finish_candle_pages([page, []]) == page
    assert core.finish_candle_pages([[]]) == []
    for pages in ([page], [page, page, []], [[], page, []], [page, [], [], []]):
        with pytest.raises(ValueError):
            core.finish_candle_pages(pages)
