"""Synthetic calendar metadata only; no network, prices, model or actual calendar."""

import copy
import json
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from market_lab.futures import algopack_paper_calendar_core_v1 as core

NOW = datetime(2026, 9, 8, 6, tzinfo=UTC)
WINDOW = core.CalendarWindow(date(2026, 9, 8), date(2026, 9, 9))
ROWS = [
    ["2026-09-08", 1, None, "N", "2026-09-08 08:00:00"],
    ["2026-09-09", 0, None, "H", "2026-09-08 08:00:00"],
]


def page(rows, start=0, clock=NOW):
    raw = json.dumps({"off_days": {"columns": core.COLUMNS, "data": rows}}).encode()
    return core.Page(start, clock, clock + timedelta(seconds=1), raw)


def replay(rows=None):
    rows = copy.deepcopy(ROWS) if rows is None else rows
    return core.replay(
        (page(rows), page([], len(rows), NOW + timedelta(seconds=2))),
        WINDOW,
        observed_at=NOW + timedelta(seconds=4),
    )


def test_closed_request_and_full_replay_not_admission():
    url = urlsplit(core.request_url(WINDOW))
    assert url.netloc == "apim.moex.com" and url.path == "/iss/calendars/futures.json"
    params = parse_qs(url.query)
    assert params["show_all_days"] == ["1"] and params["iss.only"] == ["off_days"]
    result = replay()
    assert [row["status"] for row in result["rows"]] == ["OPEN", "CLOSED"]
    assert result["calendar_source_verified"] is result["execution_admitted"] is False
    assert result["replay_sha256"] == replay()["replay_sha256"]


@pytest.mark.parametrize("flag,reason", [(None, None), (None, "N"), (0, "N"), (1, "H")])
def test_unknown_or_contradictory_is_not_closed(flag, reason):
    rows = copy.deepcopy(ROWS)
    rows[0][1], rows[0][3] = flag, reason
    result = replay(rows)
    assert result["rows"][0]["status"] == "UNRESOLVED"
    assert result["unresolved_days"] == ["2026-09-08"]


@pytest.mark.parametrize("flag", [True, False, 1.0, "1", 2])
def test_strict_flag(flag):
    rows = copy.deepcopy(ROWS)
    rows[0][1] = flag
    with pytest.raises(ValueError, match="trading flag"):
        replay(rows)


def test_weekend_session_keeps_calendar_date_and_scope():
    window = core.CalendarWindow(date(2026, 9, 12), date(2026, 9, 12))
    rows = [["2026-09-12", 1, "2026-09-14", "W", "2026-09-08 08:00:00"]]
    result = core.parse_page(page(rows), window)[0]
    assert result["day"] == "2026-09-12" and result["trade_session_date"] == "2026-09-14"
    assert result["status"] == "OPEN" and result["strategy_scope"] == "OUT_OF_SCOPE_WEEKEND"


def test_weekday_additional_session_and_invalid_session_label():
    rows = copy.deepcopy(ROWS)
    rows[0][2:4] = ["2026-09-09", "W"]
    assert replay(rows)["rows"][0]["status"] == "OPEN"
    rows[0][2] = None
    assert replay(rows)["rows"][0]["status"] == "UNRESOLVED"


@pytest.mark.parametrize("case", ["missing", "duplicate", "reverse", "outside", "future_update"])
def test_bad_coverage_or_timestamp(case):
    rows = copy.deepcopy(ROWS)
    if case == "missing":
        rows.pop()
    elif case == "duplicate":
        rows[1] = rows[0]
    elif case == "reverse":
        rows.reverse()
    elif case == "outside":
        rows[0][0] = "2026-09-07"
    else:
        rows[0][4] = "2026-09-08 10:00:00"
    with pytest.raises(ValueError):
        replay(rows)


def test_single_row_pages_and_terminal_required():
    pages = (
        page(ROWS[:1]),
        page(ROWS[1:], 1, NOW + timedelta(seconds=2)),
        page([], 2, NOW + timedelta(seconds=4)),
    )
    assert len(core.replay(pages, WINDOW, observed_at=NOW + timedelta(seconds=6))["rows"]) == 2
    with pytest.raises(ValueError, match="terminal"):
        core.replay(pages[:2], WINDOW, observed_at=NOW + timedelta(seconds=6))


def test_page_chronology_and_cursor():
    for terminal in (page([], 1), page([], 2)):
        with pytest.raises(ValueError):
            core.replay((page(ROWS), terminal), WINDOW, observed_at=NOW + timedelta(seconds=4))


def test_revision_has_distinct_digest_without_changing_previous_result():
    original = replay()
    rows = copy.deepcopy(ROWS)
    rows[1][1:4] = [1, None, "N"]
    revised = replay(rows)
    assert original["replay_sha256"] != revised["replay_sha256"]
    assert original["rows"][1]["status"] == "CLOSED"


def test_scope_limits_and_extra_blocks():
    with pytest.raises(ValueError):
        core.CalendarWindow(date(2026, 12, 31), date(2027, 1, 1))
    with pytest.raises(ValueError):
        core.request_url(WINDOW, True)
    bad = core.Page(0, NOW, NOW, b'{"off_days":{},"marketdata":{}}')
    with pytest.raises(ValueError, match="unrequested"):
        core.parse_page(bad, WINDOW)
