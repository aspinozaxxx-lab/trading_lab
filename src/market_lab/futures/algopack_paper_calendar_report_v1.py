"""Bind calendar evidence and excluded-day risk checks to the full economic report."""

from datetime import date, datetime, time, timedelta
from pathlib import Path

from market_lab.futures import algopack_paper_calendar_policy_v1 as calendar
from market_lab.futures import algopack_paper_report_v1 as report
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW, utc

PROTOCOL = "algopack_paper_calendar_report_v1"
journal, portfolio, source = report.journal, report.portfolio, report.source


def ready(activation):
    calendar.ready(activation)
    report.ready(activation)
    raw = (activation.project / calendar.BUNDLE).read_bytes()
    if journal.sha(raw) != activation.bundle_sha256:
        raise ValueError("calendar report bundle changed")
    files = journal._decode(raw)["files"]
    if files.get("src/market_lab/futures/" + Path(__file__).name) != journal.sha(
        Path(__file__).read_bytes()
    ):
        raise ValueError("calendar report absent from activation")


def excluded_days(account, decisions):
    """Replay full anchored prefix; excluded dates must have no risk or economic event."""
    activation = account.activation
    expected = account.snapshot()
    state = portfolio.initial(activation.future_start)
    records = [
        report.daily.bridge.anchors.read_event(account.ledger, f"portfolio_{index:08d}", activation)
        for index in range(1, expected["sequence"] + 1)
    ]
    exclusions = {row["day"] for row in decisions if row["status"] != "OPEN"}
    cursor = 0
    for row in decisions:
        day = date.fromisoformat(row["day"])
        boundary = utc(datetime.combine(day + timedelta(days=1), time(), MOSCOW))
        excluded = row["day"] in exclusions
        if excluded and state["positions"]:
            raise ValueError("excluded calendar day carries risk or reserved capital")
        while cursor < len(records):
            record = records[cursor]
            event = record["payload"]
            at = source._stamp(event["at"])
            if at >= boundary:
                break
            durable = source._stamp(record["durable_payload_at"])
            if excluded and (event["operation"] != "MARK" or state["positions"]):
                raise ValueError("economic activity on excluded calendar day")
            if at.astimezone(MOSCOW).date() != durable.astimezone(MOSCOW).date():
                first, last = at.astimezone(MOSCOW).date(), durable.astimezone(MOSCOW).date()
                crosses = any(first <= date.fromisoformat(value) <= last for value in exclusions)
                if crosses and (event["operation"] != "MARK" or state["positions"]):
                    raise ValueError("economic event durability crosses excluded day")
            state = portfolio.apply(
                state, event, durable_at=durable, record_sha256=record["record_sha256"]
            )
            cursor += 1
        if excluded and state["positions"]:
            raise ValueError("excluded calendar day ends with risk")
    # Validate the remaining suffix too, without evaluating it as part of this period.
    for record in records[cursor:]:
        state = portfolio.apply(
            state,
            record["payload"],
            durable_at=source._stamp(record["durable_payload_at"]),
            record_sha256=record["record_sha256"],
        )
    report.execution_audit.same(state, expected)
    report.execution_audit.same(portfolio.recover(account.ledger, activation), expected)
    return dict(
        excluded_days=sorted(exclusions),
        ledger_sequence=expected["sequence"],
        ledger_sha256=expected["last_record_sha256"],
    )


def build(account, market_root, snapshots_root, calendar_root, *, through: date):
    activation = account.activation
    ready(activation)
    selection = calendar.build(calendar_root, activation, through=through)
    if selection["expected_days"] is None:
        return dict(
            protocol_id=PROTOCOL,
            status="UNRESOLVED_CALENDAR",
            calendar=selection,
            evaluation=None,
            calendar_source_verified=False,
            execution_admitted=False,
            target_income_verified=False,
        )
    exclusions = excluded_days(account, selection["days"])
    result = report.build(
        account,
        market_root,
        snapshots_root,
        expected_days=tuple(date.fromisoformat(day) for day in selection["expected_days"]),
        calendar_sha256=selection["calendar_sha256"],
    )
    tail = account.snapshot()
    if (
        tail["sequence"] != exclusions["ledger_sequence"]
        or tail["last_record_sha256"] != exclusions["ledger_sha256"]
    ):
        raise ValueError("ledger changed during calendar/report binding")
    # Keep child report's original false flag: it does not itself verify a calendar.
    return dict(
        protocol_id=PROTOCOL,
        status="CALENDAR_BOUND_DESCRIPTIVE_PAPER_REPORT",
        calendar=selection,
        excluded_day_audit=exclusions,
        report=result,
        evaluation=result["evaluation"],
        calendar_source_verified=True,
        execution_admitted=False,
        target_income_verified=False,
    )
