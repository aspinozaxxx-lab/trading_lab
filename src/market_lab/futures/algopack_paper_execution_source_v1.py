"""Dated BBO/spec and calendar sources for conditional paper execution, not real fills."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from market_lab.futures import algopack_paper_execution_v1 as execution
from market_lab.futures import algopack_paper_journal_v1 as journal
from market_lab.futures import algopack_paper_market_core_v1 as market
from market_lab.futures import algopack_paper_market_transport_v1 as transport
from market_lab.futures.algopack_fo_witnessed_core_v1 import _block, _date, _decode
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE, VerifiedActivation
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW, utc

PROTOCOL = "algopack_paper_execution_source_v1"
BBO_COLUMNS = [
    "SECID",
    "BOARDID",
    "TRADEDATE",
    "SYSTIME",
    "UPDATETIME",
    "BID",
    "OFFER",
    "BIDDEPTH",
    "OFFERDEPTH",
    "SEQNUM",
]
SESSION_COLUMNS = [
    "tradedate",
    "secid",
    "boardid",
    "type",
    "time_from",
    "time_till",
    "updatetime",
    "settlement_session",
    "clearing_session",
]
TYPE_COLUMNS = ["type", "title"]
# Semantics must be explicit in the official type dictionary, not inferred from a code.
REGULAR_TITLES = {"Основная торговая сессия", "Дневная торговая сессия"}
MAX_PAGES = 3
MAX_ROWS = 1000


def ready(activation: VerifiedActivation) -> None:
    if not isinstance(activation, VerifiedActivation):
        raise ValueError("verified activation required")
    activation.request_ready()
    raw = (activation.project / BUNDLE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != activation.bundle_sha256:
        raise ValueError("activation bundle changed")
    files = _decode(raw)["files"]
    for module in (__file__, execution.__file__):
        path = Path(module)
        name = "src/market_lab/futures/" + path.name
        if files.get(name) != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("execution source/dependency missing from activated closure")


def request_url(
    kind: str,
    window: market.RequestWindow,
    asset: str | None = None,
    secid: str | None = None,
    start: int = 0,
) -> str:
    if type(start) is not int or not 0 <= start <= MAX_ROWS:
        raise ValueError("invalid execution source cursor")
    params = {"iss.meta": "off"}
    if kind == "quote":
        market.identity(asset, secid)
        if start:
            raise ValueError("quote cursor forbidden")
        base = f"https://apim.moex.com/iss/engines/futures/markets/forts/boards/RFUD/securities/{secid}.json"
        params.update(
            {
                "iss.only": "marketdata,securities",
                "marketdata.columns": ",".join(BBO_COLUMNS),
                "securities.columns": ",".join(market.SPEC_COLUMNS),
            }
        )
    elif kind == "calendar" and asset is None and secid is None:
        base = "https://apim.moex.com/iss/calendars/futures/session.json"
        params.update(
            {
                "iss.only": "session_schedule,session_schedule.types",
                "session_schedule.columns": ",".join(SESSION_COLUMNS),
                "session_schedule.types.columns": ",".join(TYPE_COLUMNS),
                "from": window.day,
                "till": window.day,
                "start": start,
            }
        )
    else:
        raise ValueError("invalid execution source route")
    return base + "?" + urlencode(params)


def parse_quote(
    raw: bytes, window: market.RequestWindow, received: datetime, asset: str, secid: str
) -> dict:
    market.identity(asset, secid)
    market.receipt_window(window, received)
    data = _decode(raw)
    if set(data) != {"marketdata", "securities"}:
        raise ValueError("unrequested quote source block")
    rows = _block(data, "marketdata", BBO_COLUMNS)
    if len(rows) != 1 or rows[0]["SECID"] != secid or rows[0]["BOARDID"] != "RFUD":
        raise ValueError("exact dated quote identity required")
    row = rows[0]
    # Validate the complete date/clock projection BEFORE interpreting any market numbers.
    day = _date(row["TRADEDATE"])
    system = market._vendor_stamp(row["SYSTIME"])
    updated = market._vendor_stamp(f"{day} {row['UPDATETIME']}")
    if (
        day != window.day
        or system.astimezone(MOSCOW).date().isoformat() != day
        or not utc(window.future_start) <= updated <= system <= utc(received)
    ):
        raise ValueError("quote date or source clock outside prospective request")
    values = {
        name: market._number(row[name], integer=name in {"BIDDEPTH", "OFFERDEPTH", "SEQNUM"})
        for name in BBO_COLUMNS[5:]
    }
    status = "DATED_RECORD_NOT_EXECUTION_ADMITTED"
    if any(value is None for value in values.values()):
        status = "MISSING_QUOTE_FIELD"
    elif any(values[name] <= 0 for name in ("BID", "OFFER", "BIDDEPTH", "OFFERDEPTH")):
        status = "NONPOSITIVE_QUOTE"
    elif values["BID"] >= values["OFFER"]:
        status = "LOCKED_OR_CROSSED_QUOTE"
    specs = market.parse_specs(
        json.dumps({"securities": data["securities"]}).encode(),
        asset=asset,
        secid=secid,
        window=window,
        received_at=received,
    )
    return dict(
        asset=asset,
        secid=secid,
        day=day,
        exchange_at=updated.isoformat(),
        system_at=system.isoformat(),
        values=values,
        specs=specs,
        status=status,
        date_evidence="SAME_RECORD_TRADEDATE_SYSTIME_UPDATETIME",
        available_at=None,
        execution_admitted=False,
    )


def parse_calendar(raw: bytes, window: market.RequestWindow, received: datetime) -> dict:
    market.receipt_window(window, received)
    data = _decode(raw)
    if set(data) != {"session_schedule", "session_schedule.types"}:
        raise ValueError("unrequested calendar source block")
    rows = _block(data, "session_schedule", SESSION_COLUMNS)
    types = _block(data, "session_schedule.types", TYPE_COLUMNS)
    if len(rows) > MAX_ROWS or len(types) > 200:
        raise ValueError("calendar source limit")
    names = {}
    for row in types:
        if (
            not isinstance(row["type"], str)
            or not row["type"]
            or row["type"] in names
            or not isinstance(row["title"], str)
            or not row["title"]
        ):
            raise ValueError("invalid calendar type dictionary")
        names[row["type"]] = row["title"]
    output = []
    for row in rows:
        if (
            _date(row["tradedate"]) != window.day
            or not isinstance(row["secid"], str)
            or not row["secid"]
            or not isinstance(row["boardid"], str)
            or not row["boardid"]
            or row["type"] not in names
        ):
            raise ValueError("calendar identity or type unresolved")
        begin, end, update = (
            market._vendor_stamp(row[name]) for name in ("time_from", "time_till", "updatetime")
        )
        if begin >= end or update > utc(received):
            raise ValueError("invalid calendar interval or publication clock")
        cuts = []
        for name in ("settlement_session", "clearing_session"):
            if row[name] is not None:
                cuts.append(market._vendor_stamp(row[name]).isoformat())
        output.append(
            dict(
                secid=row["secid"],
                boardid=row["boardid"],
                type=row["type"],
                title=names[row["type"]],
                start=begin.isoformat(),
                end=end.isoformat(),
                update_at=update.isoformat(),
                cuts=cuts,
            )
        )
    return dict(
        day=window.day, rows=output, types=names, available_at=None, execution_admitted=False
    )


def _stamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if (
        result.isoformat() != value
        or utc(result) != result
        or result.utcoffset().total_seconds() != 0
    ):
        raise ValueError("canonical UTC receipt required")
    return result


def replay(step: dict, activation: VerifiedActivation) -> dict:
    receipt = step["receipt"]
    requested, completed, validated = (
        _stamp(receipt[name])
        for name in ("request_started_at", "response_completed_at", "validation_completed_at")
    )
    window = market.RequestWindow(activation.future_start, requested)
    if (
        not requested <= completed <= validated
        or receipt["http_status"] != 200
        or receipt["url"]
        != request_url(step["kind"], window, step["asset"], step["secid"], step["start"])
    ):
        raise ValueError("execution source receipt mismatch")
    raw = base64.b64decode(step["raw_base64"], validate=True)
    elapsed = receipt["request_elapsed_seconds"]
    if (
        type(elapsed) not in (float, int)
        or not math.isfinite(elapsed)
        or elapsed < 0
        or abs((completed - requested).total_seconds() - elapsed) > 2
        or not 0 < len(raw) <= transport.MAX_BYTES
        or len(raw) != receipt["raw_bytes"]
        or hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]
    ):
        raise ValueError("execution source raw/clock mismatch")
    parsed = (
        parse_quote(raw, window, completed, step["asset"], step["secid"])
        if step["kind"] == "quote"
        else parse_calendar(raw, window, completed)
    )
    if journal.encode(parsed) != journal.encode(step["normalized"]):
        raise ValueError("execution source normalization differs from raw")
    return parsed


def fetch(
    session,
    *,
    activation: VerifiedActivation,
    kind: str,
    token: str,
    asset: str | None = None,
    secid: str | None = None,
    start: int = 0,
) -> dict:
    ready(activation)
    window = market.RequestWindow(activation.future_start, journal.now())
    url = request_url(kind, window, asset, secid, start)
    if not isinstance(token, str) or not token or "\n" in token or "\r" in token:
        raise transport.CaptureFailure("credential")
    if getattr(session, "trust_env", False) or getattr(session, "auth", None) is not None:
        raise transport.CaptureFailure("ambient_session_auth")
    transport.check_ca()
    begun = time.monotonic()
    try:
        with session.get(
            url,
            headers={"Accept": "application/json", "Authorization": "Bearer " + token},
            verify=str(transport.CA_PATH),
            timeout=10.0,
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200 or response.url != url:
                raise transport.CaptureFailure("http_status_or_redirect")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > transport.MAX_BYTES or time.monotonic() - begun > 10:
                    raise transport.CaptureFailure("size_or_deadline")
                chunks.append(chunk)
            raw = b"".join(chunks)
        completed = journal.now()
        elapsed = time.monotonic() - begun
        if not raw or token.encode() in raw:
            raise transport.CaptureFailure("empty_or_secret_reflection")
        normalized = (
            parse_quote(raw, window, completed, asset, secid)
            if kind == "quote"
            else parse_calendar(raw, window, completed)
        )
        validated = journal.now()
        step = dict(
            kind=kind,
            asset=asset,
            secid=secid,
            start=start,
            raw_base64=base64.b64encode(raw).decode(),
            normalized=normalized,
            receipt=dict(
                url=url,
                http_status=200,
                request_started_at=window.requested_at.isoformat(),
                response_completed_at=completed.isoformat(),
                validation_completed_at=validated.isoformat(),
                request_elapsed_seconds=elapsed,
                raw_bytes=len(raw),
                raw_sha256=hashlib.sha256(raw).hexdigest(),
            ),
        )
        replay(step, activation)
        if time.monotonic() - begun > 10:
            raise transport.CaptureFailure("size_or_deadline")
        return step
    except transport.CaptureFailure:
        raise
    except Exception:
        raise transport.CaptureFailure("execution_source_transport_or_schema") from None


def validate_pages(pages: list[dict], kind: str) -> None:
    if kind == "quote":
        if len(pages) != 1:
            raise ValueError("one quote response required")
        return
    if kind != "calendar" or not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError("invalid calendar pages")
    if pages[-1]["rows"] or any(not page["rows"] for page in pages[:-1]):
        raise ValueError("incomplete calendar pagination")
    if any(page["day"] != pages[0]["day"] or page["types"] != pages[0]["types"] for page in pages):
        raise ValueError("calendar changed during pagination")
    keys = [journal.encode(row) for page in pages for row in page["rows"]]
    if len(keys) > MAX_ROWS or len(keys) != len(set(keys)):
        raise ValueError("duplicate/excess calendar rows")


def collect(
    session,
    root: Path,
    *,
    key: str,
    activation: VerifiedActivation,
    kind: str,
    token: str,
    asset: str | None = None,
    secid: str | None = None,
) -> dict:
    ready(activation)
    if not key or len(key) > 60:
        raise ValueError("invalid source event key")
    request_url(kind, market.RequestWindow(activation.future_start, journal.now()), asset, secid)
    journal.publish(
        root,
        kind="source",
        key=key + "_started",
        future_start=activation.future_start,
        payload=dict(protocol_id=PROTOCOL, state="STARTED"),
    )
    refs, pages, offset = [], [], 0
    try:
        for index in range(1 if kind == "quote" else MAX_PAGES):
            step = fetch(
                session,
                activation=activation,
                kind=kind,
                token=token,
                asset=asset,
                secid=secid,
                start=offset,
            )
            refs.append(
                journal.publish(
                    root,
                    kind="source",
                    key=f"{key}_p{index}",
                    future_start=activation.future_start,
                    payload=dict(protocol_id=PROTOCOL, state="RESPONSE", step=step),
                )
            )
            pages.append(step["normalized"])
            if kind == "quote" or not step["normalized"]["rows"]:
                break
            offset += len(step["normalized"]["rows"])
            time.sleep(0.5)
        else:
            raise ValueError("calendar terminal page missing")
        validate_pages(pages, kind)
        ready(activation)
        return journal.publish(
            root,
            kind="source",
            key=key,
            future_start=activation.future_start,
            payload=dict(
                protocol_id=PROTOCOL,
                state="COMPLETE",
                kind=kind,
                steps=refs,
                activation_sha256=activation.activation_sha256,
                execution_admitted=False,
            ),
        )
    except Exception:
        journal.publish(
            root,
            kind="source",
            key=key + "_failed",
            future_start=activation.future_start,
            payload=dict(protocol_id=PROTOCOL, state="FAILED", completed_responses=len(refs)),
        )
        raise transport.CaptureFailure("execution_source_capture") from None


def observe(root: Path, reference: dict, activation: VerifiedActivation) -> dict:
    ready(activation)
    if reference["kind"] != "source":
        raise ValueError("source reference required")
    event = journal.observe(
        root,
        kind="source",
        key=reference["key"],
        record_sha256=reference["record_sha256"],
        future_start=activation.future_start,
    )
    payload = event["payload"]
    if (
        payload["protocol_id"] != PROTOCOL
        or payload["state"] != "COMPLETE"
        or payload["activation_sha256"] != activation.activation_sha256
        or payload["execution_admitted"] is not False
    ):
        raise ValueError("invalid execution source publication")
    pages, offset, previous = [], 0, activation.future_start
    if not 1 <= len(payload["steps"]) <= (1 if payload["kind"] == "quote" else MAX_PAGES):
        raise ValueError("invalid execution source page count")
    for index, ref in enumerate(payload["steps"]):
        part = journal.observe(
            root,
            kind="source",
            key=ref["key"],
            record_sha256=ref["record_sha256"],
            future_start=activation.future_start,
        )
        if (
            part["payload"]["protocol_id"] != PROTOCOL
            or part["payload"]["state"] != "RESPONSE"
            or ref["key"] != f"{reference['key']}_p{index}"
        ):
            raise ValueError("invalid execution source response reference")
        step = part["payload"]["step"]
        if (
            step["kind"] != payload["kind"]
            or step["start"] != offset
            or not previous <= _stamp(step["receipt"]["request_started_at"])
            or _stamp(step["receipt"]["validation_completed_at"])
            > _stamp(part["durable_payload_at"])
            or _stamp(part["durable_payload_at"]) > _stamp(event["durable_payload_at"])
        ):
            raise ValueError("execution source chronology/cursor mismatch")
        parsed = replay(step, activation)
        previous = _stamp(part["durable_payload_at"])
        pages.append(parsed)
        if payload["kind"] == "calendar":
            offset += len(parsed["rows"])
    validate_pages(pages, payload["kind"])
    observed = journal.now()
    if observed < _stamp(event["observed_at"]):
        raise ValueError("source observation clock reversed")
    return dict(
        kind=payload["kind"],
        pages=pages,
        available_at=observed.isoformat(),
        execution_admitted=False,
        request_started_at=payload["steps"] and step["receipt"]["request_started_at"],
        source_observation=dict(
            kind="source",
            key=reference["key"],
            record_sha256=reference["record_sha256"],
            observed_at=observed.isoformat(),
        ),
    )


def quote_inputs(observed: dict) -> tuple[execution.Quote, execution.Terms] | None:
    if observed["kind"] != "quote" or len(observed["pages"]) != 1:
        raise ValueError("one observed quote record required")
    row = observed["pages"][0]
    if (
        row["status"] != "DATED_RECORD_NOT_EXECUTION_ADMITTED"
        or row["specs"]["status"] != "OBSERVED_NOT_EXECUTION_ADMITTED"
    ):
        return None
    available = _stamp(observed["available_at"])
    if (
        observed["execution_admitted"] is not False
        or observed["source_observation"]["observed_at"] != available.isoformat()
    ):
        raise ValueError("quote observation declaration mismatch")
    digest = observed["source_observation"]["record_sha256"]
    values, specs = row["values"], row["specs"]["values"]
    quote = execution.Quote(
        row["asset"],
        row["secid"],
        values["BID"],
        values["OFFER"],
        values["BIDDEPTH"],
        values["OFFERDEPTH"],
        _stamp(row["exchange_at"]),
        _stamp(observed["request_started_at"]),
        available,
        digest,
        True,
    )
    terms = execution.Terms(
        row["asset"],
        row["secid"],
        specs["MINSTEP"],
        specs["STEPPRICE"],
        specs["INITIALMARGIN"],
        specs["BUYSELLFEE"],
        date.fromisoformat(specs["LASTTRADEDATE"]),
        available,
        digest,
    )
    return quote, terms


def session_input(
    observed: dict, *, secid: str, entry_at: datetime, exit_at: datetime
) -> execution.Session | None:
    if observed["kind"] != "calendar":
        raise ValueError("calendar source required")
    entry, end = utc(entry_at), utc(exit_at) + execution.MAX_FILL_DELAY
    rows = [
        row
        for page in observed["pages"]
        for row in page["rows"]
        if row["secid"] in ("-", secid) and row["boardid"] in ("-", "RFUD")
    ]
    candidates = [
        row
        for row in rows
        if row["title"] in REGULAR_TITLES
        and _stamp(row["start"]) <= entry
        and end < _stamp(row["end"])
    ]
    if len(candidates) != 1:
        return None
    selected = candidates[0]
    boundary = _stamp(selected["end"])
    for row in rows:
        cuts = [_stamp(cut) for cut in row["cuts"] if _stamp(cut) >= _stamp(selected["start"])]
        if cuts:
            boundary = min(boundary, *cuts)
        if any(
            _stamp(cut) <= end and _stamp(cut) >= _stamp(selected["start"]) for cut in row["cuts"]
        ):
            return None
        if row != selected and _stamp(row["start"]) <= end and _stamp(row["end"]) > entry:
            return None  # Unknown/clearing/overriding interval conflicts: never assume tradable.
    return execution.Session(
        _stamp(selected["start"]),
        boundary,
        _stamp(observed["available_at"]),
        observed["source_observation"]["record_sha256"],
    )
