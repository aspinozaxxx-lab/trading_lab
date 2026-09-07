"""Offline dated source/receipt/intent tests; no production activation or market requests."""

import copy
import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from test_algopack_paper_execution_v1 import fixture as execution_fixture
from test_algopack_paper_journal_v1 import END, NOW, START

from market_lab.futures import algopack_paper_execution_source_v1 as core
from market_lab.futures.algopack_paper_activation_v1 import VerifiedActivation

WINDOW = core.market.RequestWindow(START, NOW)


def block(columns, rows):
    return dict(columns=columns, data=[[row[name] for name in columns] for row in rows])


def quote_data():
    row = dict(
        SECID="BRU6",
        BOARDID="RFUD",
        TRADEDATE="2026-09-08",
        SYSTIME="2026-09-08 11:04:01",
        UPDATETIME="11:04:01",
        BID=10000.0,
        OFFER=10001.0,
        BIDDEPTH=1000,
        OFFERDEPTH=1000,
        SEQNUM=123,
    )
    specs = dict(
        SECID="BRU6",
        BOARDID="RFUD",
        ASSETCODE="BR",
        LASTTRADEDATE="2026-09-17",
        LASTDELDATE="2026-09-17",
        LOTVOLUME=1,
        MINSTEP=1.0,
        STEPPRICE=1.0,
        INITIALMARGIN=1000.0,
        BUYSELLFEE=2.0,
    )
    return dict(
        marketdata=block(core.BBO_COLUMNS, [row]),
        securities=block(core.market.SPEC_COLUMNS, [specs]),
    )


def calendar_data(empty=False):
    row = dict(
        tradedate="2026-09-08",
        secid="-",
        boardid="-",
        type="synthetic_main",
        time_from="2026-09-08 10:00:00",
        time_till="2026-09-08 18:45:00",
        updatetime="2026-09-08 06:00:00",
        settlement_session=None,
        clearing_session=None,
    )
    return {
        "session_schedule": block(core.SESSION_COLUMNS, [] if empty else [row]),
        "session_schedule.types": block(
            core.TYPE_COLUMNS, [dict(type="synthetic_main", title="Основная торговая сессия")]
        ),
    }


def encoded(value):
    return json.dumps(value).encode()


def parse_quote(value):
    return core.parse_quote(encoded(value), WINDOW, NOW, "BR", "BRU6")


def calendar_observed(value):
    return dict(
        kind="calendar",
        pages=[core.parse_calendar(encoded(value), WINDOW, NOW)],
        available_at=NOW.isoformat(),
        execution_admitted=False,
        source_observation=dict(record_sha256="a" * 64, observed_at=NOW.isoformat()),
    )


def test_dated_record_and_specs_are_one_response_not_undated_book_upgrade():
    row = parse_quote(quote_data())
    assert row["status"] == "DATED_RECORD_NOT_EXECUTION_ADMITTED"
    assert row["exchange_at"] == NOW.isoformat()
    assert row["available_at"] is None and row["execution_admitted"] is False


@pytest.mark.parametrize(
    "column,value",
    [
        ("TRADEDATE", "2026-09-07"),
        ("TRADEDATE", "2026-09-08 11:04:01"),
        ("SYSTIME", "2026-09-07 11:04:01"),
        ("SYSTIME", "2026-09-08 11:04:02"),
        ("UPDATETIME", "11:04:02"),
    ],
)
def test_entire_time_projection_checked_before_numeric_values(column, value):
    data = quote_data()
    data["marketdata"]["data"][0][core.BBO_COLUMNS.index(column)] = value
    data["marketdata"]["data"][0][core.BBO_COLUMNS.index("BID")] = "NUMERIC_POISON"
    with pytest.raises(ValueError) as error:
        parse_quote(data)
    assert "numeric" not in str(error.value)


@pytest.mark.parametrize(
    "column,value,status",
    [
        ("BID", None, "MISSING_QUOTE_FIELD"),
        ("OFFERDEPTH", 0, "NONPOSITIVE_QUOTE"),
        ("OFFER", 9999.0, "LOCKED_OR_CROSSED_QUOTE"),
    ],
)
def test_bad_quote_is_mask_not_zero_fill(column, value, status):
    data = quote_data()
    data["marketdata"]["data"][0][core.BBO_COLUMNS.index(column)] = value
    assert parse_quote(data)["status"] == status


@pytest.mark.parametrize("case", ["identity", "extra", "fractional_depth", "schema"])
def test_quote_schema_rejected(case):
    data = quote_data()
    if case == "identity":
        data["marketdata"]["data"][0][0] = "BRZ6"
    elif case == "extra":
        data["prices"] = {}
    elif case == "fractional_depth":
        data["marketdata"]["data"][0][7] = 1.5
    else:
        data["marketdata"]["columns"] = list(reversed(core.BBO_COLUMNS))
    with pytest.raises(ValueError):
        parse_quote(data)


@pytest.mark.parametrize(
    "case", ["unknown_title", "clear_between", "clear_before_entry", "overlap", "not_this_contract"]
)
def test_calendar_does_not_invent_tradable_period(case):
    data = calendar_data()
    if case == "unknown_title":
        data["session_schedule.types"]["data"][0][1] = "Неизвестный период"
    elif case.startswith("clear"):
        stamp = "2026-09-08 11:30:00" if case == "clear_between" else "2026-09-08 11:00:00"
        data["session_schedule"]["data"][0][-1] = stamp
    elif case == "overlap":
        data["session_schedule"]["data"].append(copy.deepcopy(data["session_schedule"]["data"][0]))
    else:
        data["session_schedule"]["data"][0][1] = "BRZ6"
    assert (
        core.session_input(
            calendar_observed(data),
            secid="BRU6",
            entry_at=END + timedelta(minutes=10),
            exit_at=END + timedelta(minutes=70),
        )
        is None
    )


def test_calendar_terminal_and_dictionary_consistency():
    first = core.parse_calendar(encoded(calendar_data()), WINDOW, NOW)
    empty = core.parse_calendar(encoded(calendar_data(True)), WINDOW, NOW)
    core.validate_pages([first, empty], "calendar")
    for pages in ([first], [first, first, empty], [empty, first, empty]):
        with pytest.raises(ValueError):
            core.validate_pages(pages, "calendar")
    changed = copy.deepcopy(empty)
    changed["types"] = {}
    with pytest.raises(ValueError):
        core.validate_pages([first, changed], "calendar")


class Response:
    def __init__(self, url, raw, status=200):
        self.url, self.raw, self.status_code = url, raw, status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def iter_content(self, _):
        yield self.raw


class Session:
    def __init__(self, override=None, fail_after=None):
        self.calls, self.override, self.fail_after = [], override, fail_after

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        params = parse_qs(urlsplit(url).query)
        data = calendar_data(params["start"] != ["0"]) if "start" in params else quote_data()
        return Response(
            url,
            self.override if self.override is not None else encoded(data),
            403 if self.fail_after is not None and len(self.calls) > self.fail_after else 200,
        )


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(
        VerifiedActivation, "request_ready", lambda _: None
    )  # Explicit synthetic authority only.
    monkeypatch.setattr(core.journal, "now", lambda: NOW)
    monkeypatch.setattr(core.transport, "check_ca", lambda: None)
    monkeypatch.setattr(core.time, "sleep", lambda _: None)
    (tmp_path / "configs").mkdir()
    files = {
        "src/market_lab/futures/" + Path(name).name: hashlib.sha256(
            Path(name).read_bytes()
        ).hexdigest()
        for name in (core.__file__, core.execution.__file__)
    }
    raw = encoded(dict(files=files))
    (tmp_path / core.BUNDLE).write_bytes(raw)
    activation = VerifiedActivation(tmp_path, "a" * 64, START, hashlib.sha256(raw).hexdigest())
    root = tmp_path / "journal"
    root.mkdir(mode=0o700)
    return activation, root


def test_transport_scoped_tls_and_raw_replay(runtime):
    activation, _ = runtime
    session = Session()
    step = core.fetch(
        session, activation=activation, kind="quote", token="SYNTHETIC", asset="BR", secid="BRU6"
    )
    assert core.replay(step, activation) == step["normalized"]
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["verify"] == str(core.transport.CA_PATH)
    assert "SYNTHETIC" not in json.dumps(step)
    step["normalized"]["values"]["BID"] = 1.0
    with pytest.raises(ValueError):
        core.replay(step, activation)


@pytest.mark.parametrize("raw", [b"", b"SYNTHETIC", b"{}"])
def test_transport_bad_body_is_not_returned(runtime, raw):
    activation, _ = runtime
    with pytest.raises(core.transport.CaptureFailure):
        core.fetch(
            Session(raw),
            activation=activation,
            kind="quote",
            token="SYNTHETIC",
            asset="BR",
            secid="BRU6",
        )


def test_missing_closure_or_boundary_prevents_request(runtime, monkeypatch):
    activation, _ = runtime
    session = Session()
    (activation.project / core.BUNDLE).write_bytes(b"{}")
    with pytest.raises(ValueError):
        core.fetch(
            session,
            activation=activation,
            kind="quote",
            token="SYNTHETIC",
            asset="BR",
            secid="BRU6",
        )
    assert session.calls == []


def test_ambient_session_auth_is_rejected_before_request(runtime):
    activation, _ = runtime
    session = Session()
    session.trust_env = True
    with pytest.raises(core.transport.CaptureFailure, match="ambient_session_auth"):
        core.fetch(
            session,
            activation=activation,
            kind="quote",
            token="SYNTHETIC",
            asset="BR",
            secid="BRU6",
        )
    assert session.calls == []


@pytest.mark.skipif(os.name != "posix", reason="Linux durable source journal")
def test_both_sources_replayed_and_accepted_by_intent_core(runtime):
    activation, root = runtime
    quote_ref = core.collect(
        Session(),
        root,
        key="quote_1",
        activation=activation,
        kind="quote",
        token="SYNTHETIC",
        asset="BR",
        secid="BRU6",
    )
    cal_ref = core.collect(
        Session(), root, key="cal_1", activation=activation, kind="calendar", token="SYNTHETIC"
    )
    quote, terms = core.quote_inputs(core.observe(root, quote_ref, activation))
    session = core.session_input(
        core.observe(root, cal_ref, activation),
        secid="BRU6",
        entry_at=END + timedelta(minutes=10),
        exit_at=END + timedelta(minutes=70),
    )
    args = execution_fixture()
    args.update(quote=quote, terms=terms, session=session)
    assert core.execution.make_intent(**args)[0] == "PAPER_INTENT_NOT_PERSISTED"
    assert quote.exchange_date_verified and quote.observed_at == NOW


@pytest.mark.skipif(os.name != "posix", reason="Linux durable source journal")
def test_calendar_failure_preserves_response_without_complete(runtime):
    activation, root = runtime
    with pytest.raises(core.transport.CaptureFailure):
        core.collect(
            Session(fail_after=1),
            root,
            key="cal_failed",
            activation=activation,
            kind="calendar",
            token="SYNTHETIC",
        )
    assert (root / "source/cal_failed_p0/COMMITTED.json").exists()
    assert (root / "source/cal_failed_failed/COMMITTED.json").exists()
    assert not (root / "source/cal_failed").exists()
