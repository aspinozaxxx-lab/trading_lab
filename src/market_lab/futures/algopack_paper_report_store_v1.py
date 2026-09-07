"""Immutable economic report publication and offline server CLI; no HTTP or token access."""

import argparse
import json
from datetime import date
from pathlib import Path

from market_lab.futures import algopack_paper_calendar_report_v1 as report
from market_lab.futures import algopack_paper_runtime_v1 as runtime
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE, load_activation

PROTOCOL = "algopack_paper_report_store_v1"
journal, anchors = report.journal, runtime.bridge.anchors


def ready(activation):
    report.ready(activation)
    runtime.ready(activation)
    raw = (activation.project / BUNDLE).read_bytes()
    if journal.sha(raw) != activation.bundle_sha256:
        raise ValueError("report publication bundle changed")
    files = journal._decode(raw)["files"]
    if files.get("src/market_lab/futures/" + Path(__file__).name) != journal.sha(
        Path(__file__).read_bytes()
    ):
        raise ValueError("report publication absent from activation")


def publish(account, market_root, snapshots_root, calendar_root, output_root, *, through: date):
    activation = account.activation
    ready(activation)
    if type(through) is not date:
        raise ValueError("exact report date required")
    inputs = (account.ledger, account.control, market_root, snapshots_root, calendar_root)
    for root in (*inputs, output_root):
        journal._ordinary(root, directory=True)
    if any(
        output_root == root or output_root in root.parents or root in output_root.parents
        for root in inputs
    ):
        raise ValueError("report output must be separate from inputs")
    key = "evaluation_" + through.strftime("%Y%m%d")
    with anchors.transaction(output_root):
        before = account.snapshot()
        scope = dict(
            protocol_id=PROTOCOL,
            activation_sha256=activation.activation_sha256,
            bundle_sha256=activation.bundle_sha256,
            through=through.isoformat(),
            roots=dict(
                ledger=str(account.ledger),
                control=str(account.control),
                market=str(market_root),
                snapshots=str(snapshots_root),
                calendar=str(calendar_root),
            ),
            ledger_sequence=before["sequence"],
            ledger_sha256=before["last_record_sha256"],
            execution_admitted=False,
            target_income_verified=False,
        )
        started = journal.now().isoformat()
        journal.publish(
            output_root,
            kind="source",
            key=key + "_started",
            future_start=activation.future_start,
            payload=dict(**scope, state="STARTED", started_at=started),
        )
        try:
            result = report.build(
                account, market_root, snapshots_root, calendar_root, through=through
            )
            after = account.snapshot()
            report.report.execution_audit.same(before, after)
            completed = journal.now().isoformat()
            return journal.publish(
                output_root,
                kind="source",
                key=key,
                future_start=activation.future_start,
                payload=dict(
                    **scope,
                    state="COMPLETE",
                    started_at=started,
                    completed_at=completed,
                    result=result,
                ),
            )
        except Exception:
            journal.publish(
                output_root,
                kind="source",
                key=key + "_failed",
                future_start=activation.future_start,
                payload=dict(**scope, state="FAILED", completed_at=journal.now().isoformat()),
            )
            raise ValueError("report publication failed; retained for review") from None


def observe(output_root, reference, activation):
    """Read the original immutable report; does not pretend to rerun its economic audit."""
    ready(activation)
    if reference["kind"] != "source":
        raise ValueError("report source reference required")
    event = journal.observe(
        output_root,
        kind="source",
        key=reference["key"],
        record_sha256=reference["record_sha256"],
        future_start=activation.future_start,
    )
    payload = event["payload"]
    through = date.fromisoformat(payload["through"])
    if (
        payload["protocol_id"] != PROTOCOL
        or payload["state"] != "COMPLETE"
        or payload["activation_sha256"] != activation.activation_sha256
        or payload["bundle_sha256"] != activation.bundle_sha256
        or payload["through"] != through.isoformat()
        or reference["key"] != "evaluation_" + through.strftime("%Y%m%d")
        or payload["execution_admitted"] is not False
        or payload["target_income_verified"] is not False
        or not activation.future_start
        <= report.source._stamp(payload["started_at"])
        <= report.source._stamp(payload["completed_at"])
        <= report.source._stamp(event["durable_payload_at"])
    ):
        raise ValueError("saved report scope or chronology")
    return dict(
        payload=payload,
        observed_at=journal.now().isoformat(),
        durable_payload_at=event["durable_payload_at"],
        economic_recomputed=False,
        execution_admitted=False,
        target_income_verified=False,
    )


def main():
    parser = argparse.ArgumentParser(description="Offline prospective paper report; no broker/HTTP")
    parser.add_argument("--activation-sha256", required=True)
    parser.add_argument("--through", required=True)
    args = parser.parse_args()
    try:
        through = date.fromisoformat(args.through)
        if through.isoformat() != args.through:
            raise ValueError("canonical date required")
        activation = load_activation(Path(__file__).resolve().parents[3], args.activation_sha256)
        ready(activation)
        root = runtime.DATA_ROOT / activation.activation_sha256
        # Nonblocking lifetime lock before account construction/recovery. Does not stop
        # or compete with --serve; operator runs this only while runtime is stopped.
        with anchors.transaction(root):
            for name in runtime.COMPONENTS:
                journal._ordinary(root / name, directory=True)
            account = anchors.AnchoredPortfolio(root / "control", root / "ledger", activation)
            output = root / "economic_reports"
            output.mkdir(mode=0o700, exist_ok=True)
            journal._ordinary(output, directory=True)
            ref = publish(
                account,
                root / "market",
                root / "reports",
                root / "calendar",
                output,
                through=through,
            )
            print(
                json.dumps(
                    dict(
                        status="REPORT_RECORDED",
                        reference=ref,
                        execution_admitted=False,
                        target_income_verified=False,
                    )
                )
            )
        return 0
    except Exception:
        print(json.dumps(dict(status="REPORT_STOPPED_REQUIRES_REVIEW")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
