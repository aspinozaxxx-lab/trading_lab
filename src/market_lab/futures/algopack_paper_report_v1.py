"""Combine source/model/ledger/snapshot checks before descriptive daily evaluation."""

from pathlib import Path

from market_lab.futures import algopack_paper_daily_snapshot_v1 as daily
from market_lab.futures import algopack_paper_evaluation_v1 as evaluation
from market_lab.futures import algopack_paper_execution_audit_v1 as execution_audit
from market_lab.futures import algopack_paper_forecast_audit_v1 as forecast_audit
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW

portfolio, journal, source = execution_audit.portfolio, daily.journal, daily.bridge.source
PROTOCOL = "algopack_paper_report_v1"


def ready(activation):
    execution_audit.ready(activation)
    forecast_audit.ready(activation)
    daily.ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    name = "src/market_lab/futures/algopack_paper_report_v1.py"
    if files.get(name) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("combined report absent from complete activation")


def check_coverage(saved, snapshot, root, activation, checked):
    if (
        saved["protocol_id"] != daily.coverage.PROTOCOL
        or saved["state"] != "COVERAGE_NOT_PERSISTED"
        or saved["expected_slots"] != 42
        or saved["expected_asset_decisions_per_arm"] != 168
        or saved["execution_admitted"] is not False
        or saved["day"] != snapshot["day"]
        or saved["activation_sha256"] != activation.activation_sha256
        or saved["source_root"] != str(root)
        or source._stamp(saved["observed_at"]) > source._stamp(snapshot["observed_at"])
    ):
        raise ValueError("coverage scope/clock mismatch")
    counts = {
        arm: dict.fromkeys(("ready", "sleep", "failed", "missing"), 0) for arm in journal.MODEL_SHA
    }
    from datetime import date, timedelta

    ends = daily.coverage.slots(date.fromisoformat(snapshot["day"]))
    if len(saved["slots"]) != len(ends):
        raise ValueError("coverage slot denominator mismatch")
    for end, row in zip(ends, saved["slots"], strict=True):
        if row["information_end"] != end.isoformat():
            raise ValueError("coverage grid mismatch")
        reference = row["observation"]
        if reference is None:
            category = {
                "MISSING_PUBLICATION": "missing",
                "INVALID_OR_INCOMPLETE_PUBLICATION": "failed",
            }.get(row["reason"])
            if category is None or row["categories"] != dict.fromkeys(journal.MODEL_SHA, category):
                raise ValueError("unsupported missing/failed coverage")
        else:
            record = journal.observe(
                root,
                kind="forecast",
                key=reference["key"],
                record_sha256=reference["record_sha256"],
                future_start=activation.future_start,
            )
            if reference["key"] != end.strftime("%Y%m%dT%H%M%SZ") or not source._stamp(
                record["durable_payload_at"]
            ) <= source._stamp(reference["observed_at"]) <= source._stamp(saved["observed_at"]):
                raise ValueError("coverage publication chronology mismatch")
            if reference["record_sha256"] not in checked:
                forecast_audit.audit(root, reference, activation)
                checked.add(reference["record_sha256"])
            categories = dict.fromkeys(journal.MODEL_SHA, "failed")
            if source._stamp(record["durable_payload_at"]) < end + timedelta(minutes=10):
                categories = {
                    arm: {"READY": "ready", "SLEEP_MISSING_FEATURES": "sleep"}.get(
                        value["status"], "failed"
                    )
                    for arm, value in record["payload"]["arms"].items()
                }
            if row["categories"] != categories:
                raise ValueError("coverage category differs from forecast evidence")
        for arm, category in row["categories"].items():
            counts[arm][category] += 4
    execution_audit.same(saved["arms"], counts)
    for arm in counts:
        execution_audit.same(
            counts[arm], {key: snapshot["arms"][arm]["counts"][key] for key in counts[arm]}
        )


def build(account, market_root, reports_root, *, expected_days, calendar_sha256):
    activation = account.activation
    ready(activation)
    journal._ordinary(reports_root, directory=True)
    parent = reports_root / "source"
    if parent.exists() or parent.is_symlink():
        journal._ordinary(parent, directory=True)
    # Validate requested period before source/ledger economic reads.
    evaluation.evaluate(
        expected_days=expected_days,
        observations=[],
        future_start=activation.future_start,
        evaluated_at=journal.now(),
        calendar_sha256=calendar_sha256,
    )
    execution_result = execution_audit.audit(account, market_root)
    snapshots, payloads = [], {}
    for day in expected_days:
        key = "daily_" + day.strftime("%Y%m%d")
        path = reports_root / "source" / key
        if not path.exists() and not path.is_symlink():
            continue  # Evaluator retains missing day; never trim expected calendar.
        marker = journal._decode(journal._read(path / "COMMITTED.json"))
        ref = dict(kind="source", key=key, record_sha256=marker["record_sha256"])
        snapshot = daily.observe(reports_root, activation, ref)
        record = journal.observe(
            reports_root,
            kind="source",
            key=key,
            record_sha256=ref["record_sha256"],
            future_start=activation.future_start,
        )
        if snapshot["ledger_sha256"] in payloads:
            raise ValueError("duplicate snapshot ledger reference")
        payloads[snapshot["ledger_sha256"]] = record["payload"]
        snapshots.append(snapshot)
    state = portfolio.initial(activation.future_start)
    totals, found, checked = {}, set(), set()
    expected = account.snapshot()
    for index in range(1, expected["sequence"] + 1):
        record = daily.bridge.anchors.read_event(
            account.ledger, f"portfolio_{index:08d}", activation
        )
        event, before = record["payload"], state
        prior_snapshot = payloads.get(before["last_record_sha256"])
        if prior_snapshot and source._stamp(record["durable_payload_at"]) <= source._stamp(
            prior_snapshot["snapshot"]["valuation_at"]
        ):
            raise ValueError("snapshot omits a ledger event already durable at valuation")
        state = portfolio.apply(
            state,
            event,
            durable_at=source._stamp(record["durable_payload_at"]),
            record_sha256=record["record_sha256"],
        )
        if event["operation"] == "RESERVE":
            ref = event["data"]["execution_evidence"]["observations"][0]
            if ref["record_sha256"] not in checked:
                forecast_audit.audit(market_root, ref, activation)
                checked.add(ref["record_sha256"])
        if event["operation"] in {"ENTRY", "EXIT"}:
            row = before["positions"][event["data"]["position"]]
            day = (
                source._stamp(event["data"]["fill"]["observed_at"])
                .astimezone(MOSCOW)
                .date()
                .isoformat()
            )
            count = totals.setdefault((day, row["intent"]["arm"]), dict(entries=0, closed=0))
            count["entries"] += int(event["operation"] == "ENTRY")
            count["closed"] += state["closed_trades"] - before["closed_trades"]
        digest = record["record_sha256"]
        if digest not in payloads:
            continue
        payload = payloads[digest]
        snapshot = payload["snapshot"]
        if event["operation"] != "MARK" or payload["ledger_reference"]["record_sha256"] != digest:
            raise ValueError("daily snapshot is not bound to its MARK")
        check_coverage(payload["coverage"], snapshot, market_root, activation, checked)
        for arm, saved in snapshot["arms"].items():
            value = portfolio.view(state, arm, source._stamp(snapshot["valuation_at"]))
            execution_audit.same(saved["equity_rub"], value["equity_rub"])
            execution_audit.same(saved["status"], value["status"])
            positions = [row for row in state["positions"].values() if row["intent"]["arm"] == arm]
            derived = dict(
                **totals.get((snapshot["day"], arm), dict(entries=0, closed=0)),
                open_positions=sum(row["entry"] is not None for row in positions),
                pending_positions=sum(row["entry"] is None for row in positions),
                unresolved_positions=sum(row["status"] == "UNRESOLVED" for row in positions),
            )
            execution_audit.same(derived, {key: saved["counts"][key] for key in derived})
        found.add(digest)
    if found != set(payloads):
        raise ValueError("snapshot references absent ledger history")
    execution_audit.same(state, expected)
    execution_audit.same(portfolio.recover(account.ledger, activation), expected)
    result = evaluation.evaluate(
        expected_days=expected_days,
        observations=snapshots,
        future_start=activation.future_start,
        evaluated_at=journal.now(),
        calendar_sha256=calendar_sha256,
    )
    return dict(
        protocol_id=PROTOCOL,
        evaluation=result,
        execution_audit=execution_result,
        recomputed_forecasts=len(checked),
        verified_snapshots=len(found),
        calendar_source_verified=False,
        execution_admitted=False,
        target_income_verified=False,
    )
