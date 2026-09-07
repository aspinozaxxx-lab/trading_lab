"""Bind supervisor/child completion to actual-time forecast consumption, once per slot."""

from datetime import datetime, timedelta
from pathlib import Path

from market_lab.futures import algopack_paper_preparation_worker_v1 as worker
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW, utc

journal, anchors = worker.journal, worker.runtime.bridge.anchors
PROTOCOL = "algopack_paper_preparation_intake_v1"


def ready(activation):
    worker.ready(activation)
    raw = (activation.project / BUNDLE).read_bytes()
    if journal.sha(raw) != activation.bundle_sha256:
        raise ValueError("intake bundle changed")
    if journal._decode(raw)["files"].get(
        "src/market_lab/futures/" + Path(__file__).name
    ) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("preparation intake absent from activation")


def consume(activation, information_end):
    ready(activation)
    end = utc(information_end)
    if end < activation.future_start or end not in worker.coverage.slots(
        end.astimezone(MOSCOW).date()
    ):
        raise ValueError("invalid intake slot")
    if journal.now() < end + timedelta(minutes=3):
        raise ValueError("intake before preparation window")
    root = worker.runtime.DATA_ROOT / activation.activation_sha256
    market, scheduler = root / "market", root / "scheduler"
    for path in (root, market, scheduler):
        journal._ordinary(path, directory=True)
    stamp = end.strftime("%Y%m%dT%H%M%SZ")
    key, child = "intake_" + stamp, "prepare_" + stamp
    with anchors.transaction(scheduler):
        start_path = scheduler / "source" / (key + "_started")
        if start_path.exists() or start_path.is_symlink():
            return dict(status="EXISTING_INTAKE_ATTEMPT", execution_admitted=False)
        finish_path = scheduler / "source" / (child + "_finished")
        if journal.now() < end + timedelta(minutes=10) and not (
            finish_path.exists() or finish_path.is_symlink()
        ):
            return dict(status="WAITING_PREPARATION", execution_admitted=False)

        def record(suffix, **data):
            return journal.publish(
                scheduler,
                kind="source",
                key=key + suffix,
                future_start=activation.future_start,
                payload=dict(
                    protocol_id=PROTOCOL,
                    activation_sha256=activation.activation_sha256,
                    information_end=end.isoformat(),
                    execution_admitted=False,
                    **data,
                ),
            )

        record("_started", state="STARTED")
        if journal.now() >= end + timedelta(minutes=10):
            ref = record("_finished", state="MISSED_INTAKE_DEADLINE")
            return dict(status="MISSED_INTAKE_DEADLINE", reference=ref, execution_admitted=False)
        try:
            parent_start = anchors.read_event(scheduler, child + "_started", activation)
            parent_finish = anchors.read_event(scheduler, child + "_finished", activation)
            child_start = anchors.read_event(market, child + "_started", activation)
            child_finish = anchors.read_event(market, child + "_finished", activation)
            records = (parent_start, child_start, child_finish, parent_finish)
            clocks = [utc(datetime.fromisoformat(row["durable_payload_at"])) for row in records]
            if clocks != sorted(clocks) or clocks[0] < end + timedelta(minutes=3):
                raise ValueError("preparation completion chronology")
            for row, state in zip(
                records, ("STARTED", "STARTED", "COMPLETE", "WORKER_EXITED"), strict=True
            ):
                payload = row["payload"]
                if (
                    payload["protocol_id"] != worker.PROTOCOL
                    or payload["state"] != state
                    or payload["activation_sha256"] != activation.activation_sha256
                    or payload["execution_admitted"] is not False
                ):
                    raise ValueError("preparation completion identity")
            if (
                parent_start["payload"]["information_end"] != end.isoformat()
                or type(parent_finish["payload"]["exit_code"]) is not int
                or parent_finish["payload"]["exit_code"] != 0
            ):
                raise ValueError("preparation supervisor outcome")
            forecast_ref = child_finish["payload"]["forecast"]
            if forecast_ref["kind"] != "forecast" or forecast_ref["key"] != stamp:
                raise ValueError("preparation forecast belongs to another slot")
            consumed = journal.consume_forecast(market, forecast_ref, activation.future_start)
            if (
                not clocks[1]
                <= utc(datetime.fromisoformat(consumed["durable_payload_at"]))
                <= clocks[2]
            ):
                raise ValueError("forecast publication outside worker lifetime")
            ref = record(
                "_finished",
                state="FORECAST_OBSERVED_NOT_EXECUTION_ADMITTED",
                forecast=forecast_ref,
                observed_at=consumed["observed_at"],
                arm_status={arm: row["status"] for arm, row in consumed["payload"]["arms"].items()},
            )
            return dict(
                status="FORECAST_OBSERVED_NOT_EXECUTION_ADMITTED",
                forecast=forecast_ref,
                consumed=consumed,
                reference=ref,
                execution_admitted=False,
            )
        except Exception:
            record("_failed", state="FAILED")
            raise ValueError("preparation intake failed; attempt retained") from None
