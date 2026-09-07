"""Daily ledger-derived paper snapshot with strict actual-time publication admission."""

from datetime import datetime, time, timedelta
from pathlib import Path

from market_lab.futures import algopack_paper_coverage_v1 as coverage
from market_lab.futures import algopack_paper_mark_refresh_v1 as marks
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW, utc

bridge, journal, portfolio = marks.bridge, marks.journal, marks.portfolio
PROTOCOL = "algopack_paper_daily_snapshot_v1"


def ready(activation):
    coverage.ready(activation)
    marks.ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    name = "src/market_lab/futures/algopack_paper_daily_snapshot_v1.py"
    if files.get(name) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("daily snapshot absent from complete activation")


def window(day):
    return utc(datetime.combine(day, time(18, 20), MOSCOW))


def publish(runtime, reports: Path, day, quote_references: dict):
    activation = runtime.account.activation
    ready(activation)
    scheduled = window(day)
    if not scheduled <= journal.now() <= scheduled + timedelta(seconds=30):
        raise ValueError("outside actual daily snapshot window")
    if reports in (runtime.market_root, runtime.account.ledger, runtime.account.control):
        raise ValueError("dedicated snapshot report root required")
    counts = coverage.build(runtime.market_root, activation, day)
    # Reopen validates control commands, anchors and full ledger before deriving counts.
    checked = bridge.anchors.AnchoredPortfolio(
        runtime.account.control, runtime.account.ledger, activation
    )
    original = checked.snapshot()
    if original != runtime.account.snapshot():
        raise ValueError("stale runtime snapshot")
    arms = {
        arm: dict(
            **counts["arms"][arm],
            entries=0,
            closed=0,
            open_positions=0,
            pending_positions=0,
            unresolved_positions=0,
        )
        for arm in journal.MODEL_SHA
    }
    state = portfolio.initial(activation.future_start)
    for index in range(1, original["sequence"] + 1):
        event = bridge.anchors.read_event(
            runtime.account.ledger, f"portfolio_{index:08d}", activation
        )
        payload = event["payload"]
        prior = state
        state = portfolio.apply(
            state,
            payload,
            durable_at=bridge.source._stamp(event["durable_payload_at"]),
            record_sha256=event["record_sha256"],
        )
        if payload["operation"] in ("ENTRY", "EXIT"):
            row = prior["positions"][payload["data"]["position"]]
            fill_day = (
                bridge.source._stamp(payload["data"]["fill"]["observed_at"])
                .astimezone(MOSCOW)
                .date()
            )
            if fill_day == day:
                arm = arms[row["intent"]["arm"]]
                if payload["operation"] == "ENTRY":
                    arm["entries"] += 1
                arm["closed"] += state["closed_trades"] - prior["closed_trades"]
    if state != original:
        raise ValueError("daily replay differs from anchored state")
    valuation = marks.refresh(runtime, quote_references)
    current = runtime.account.snapshot()
    if current["sequence"] != original["sequence"] + 1:
        raise ValueError("concurrent portfolio mutation during daily snapshot")
    for row in current["positions"].values():
        arm = arms[row["intent"]["arm"]]
        arm["pending_positions" if row["entry"] is None else "open_positions"] += 1
        arm["unresolved_positions"] += int(row["status"] == "UNRESOLVED")
    observed = journal.now()
    if observed > scheduled + timedelta(seconds=30):
        raise ValueError("daily snapshot preparation missed deadline")
    snapshot = dict(
        day=day.isoformat(),
        valuation_at=valuation["observed_at"],
        observed_at=observed.isoformat(),
        ledger_sha256=current["last_record_sha256"],
        arms={
            arm: dict(
                status=valuation["arms"][arm]["status"],
                equity_rub=valuation["arms"][arm]["equity_rub"],
                counts=arms[arm],
            )
            for arm in arms
        },
    )
    ref = journal.publish(
        reports,
        kind="source",
        key="daily_" + day.strftime("%Y%m%d"),
        future_start=activation.future_start,
        payload=dict(
            protocol_id=PROTOCOL,
            activation_sha256=activation.activation_sha256,
            snapshot=snapshot,
            coverage=counts,
            ledger_reference=valuation["ledger_reference"],
            execution_admitted=False,
        ),
    )
    timely = bridge.source._stamp(ref["durable_payload_at"]) <= scheduled + timedelta(seconds=30)
    return dict(
        status="RECORDED" if timely else "RECORDED_LATE_NOT_EVALUABLE",
        reference=ref,
        execution_admitted=False,
    )


def observe(reports: Path, activation, reference: dict) -> dict:
    ready(activation)
    if reference["kind"] != "source":
        raise ValueError("snapshot source reference required")
    record = journal.observe(
        reports,
        kind="source",
        key=reference["key"],
        record_sha256=reference["record_sha256"],
        future_start=activation.future_start,
    )
    payload = record["payload"]
    row = payload["snapshot"]
    valuation, observed = (
        bridge.source._stamp(row[name]) for name in ("valuation_at", "observed_at")
    )
    day = valuation.astimezone(MOSCOW).date()
    if (
        payload["protocol_id"] != PROTOCOL
        or payload["activation_sha256"] != activation.activation_sha256
        or payload["execution_admitted"] is not False
        or row["day"] != day.isoformat()
        or reference["key"] != "daily_" + day.strftime("%Y%m%d")
        or not window(day)
        <= valuation
        <= observed
        <= bridge.source._stamp(record["durable_payload_at"])
        <= window(day) + timedelta(seconds=30)
    ):
        raise ValueError("snapshot identity or original publication window invalid")
    return row  # Original builder observation, never replace it with a later report-read clock.
