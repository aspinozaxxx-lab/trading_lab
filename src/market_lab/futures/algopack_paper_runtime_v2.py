"""Integrated asynchronous paper runtime; background IO/model, single ledger owner."""

import argparse
import json
import os
import time
from contextlib import suppress
from datetime import timedelta
from pathlib import Path

from market_lab.futures import algopack_paper_async_due_v1 as due
from market_lab.futures import algopack_paper_async_slot_v1 as slots
from market_lab.futures import algopack_paper_preparation_worker_v1 as preparation
from market_lab.futures import algopack_paper_runtime_v1 as parent
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE, CONFIG, load_activation
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW

PROTOCOL = "algopack_paper_runtime_v2"
journal = parent.journal


def ready(activation):
    for module in (parent, due, slots, preparation):
        module.ready(activation)
    raw = (activation.project / BUNDLE).read_bytes()
    if journal.sha(raw) != activation.bundle_sha256:
        raise ValueError("async runtime bundle changed")
    if journal._decode(raw)["files"].get(
        "src/market_lab/futures/" + Path(__file__).name
    ) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("async runtime absent from activation")
    if (
        journal._decode((activation.project / CONFIG).read_bytes()).get("runtime_protocol")
        != PROTOCOL
    ):
        raise ValueError("activation does not select asynchronous runtime")


class Runtime(parent.Runtime):
    def __init__(self, activation, session, token):
        ready(activation)
        super().__init__(activation, session, token)
        self.due = due.Executor(self.bridge, self.root / "attempts")
        self.preparation = preparation.Supervisor(activation)
        self.slot = None

    def record(self, key, **payload):
        return journal.publish(
            self.root / "scheduler",
            kind="source",
            key=key,
            future_start=self.activation.future_start,
            payload=dict(
                protocol_id=PROTOCOL,
                activation_sha256=self.activation.activation_sha256,
                execution_admitted=False,
                **payload,
            ),
        )

    def dispatch(self, end):
        result = self.preparation.start(end)
        if result["status"] != "WORKER_STARTED":
            return result
        self.slot = slots.Slot(self.bridge, self.root / "attempts", end)
        return dict(status="ASYNC_SLOT_STARTED", execution_admitted=False)

    def maintenance_safe(self):
        return (
            self.slot is None
            and self.preparation.process is None
            and not self.due.pool.active
            and all(
                row["status"] == "UNRESOLVED"
                for row in self.bridge.account.snapshot()["positions"].values()
            )
        )

    def tick(self):
        ready(self.activation)
        if not self.valid:
            raise ValueError("async runtime invalidated; reopen required")
        try:
            # Do not hold scheduler transaction here: intake owns a scheduler transaction.
            # The service lifetime lock is the single runtime/ledger-owner exclusion.
            due_result = self.due.tick()
            preparation_result = self.preparation.poll()
            work = None
            if self.slot is not None:
                slot_result = self.slot.tick()
                work = slot_result["status"]
                if work in ("COMPLETE", "EXPIRED", "SOURCE_FAILED") and not self.slot.pool.active:
                    self.slot = None
            now = journal.now()
            day = now.astimezone(MOSCOW).date()
            if day.weekday() < 5:
                begin, end = parent.calendar.window(day)
                if self.maintenance_safe() and begin <= now < end:
                    work = self.work(parent.calendar.key(day), self.capture_calendar)
                elif self.maintenance_safe() and parent.daily.window(
                    day
                ) <= now <= parent.daily.window(day) + timedelta(seconds=30):
                    work = self.work("daily_" + day.strftime("%Y%m%d"), lambda: self.snapshot(day))
                elif self.slot is None and self.preparation.process is None:
                    for end in parent.slots.coverage.slots(day):
                        if end + timedelta(minutes=3) <= now < end + timedelta(minutes=10):
                            key = "async_dispatch_" + end.strftime("%Y%m%dT%H%M%SZ")
                            work = self.work(key, lambda end=end: self.dispatch(end))
                            break
            return dict(
                status="ASYNC_RUNTIME_TICK",
                due=due_result,
                preparation=preparation_result["status"],
                work=work,
                execution_admitted=False,
            )
        except Exception:
            self.valid = False
            raise RuntimeError("async runtime failed; anchored reopen required") from None

    def stop_children(self):
        """Shutdown only: kill all owned children first, then bounded reap outside trading loop."""
        children = [row["child"] for row in self.due.pool.active.values()]
        if self.preparation.process is not None:
            children.append(self.preparation.process)
        if self.slot is not None:
            children.extend(row["child"] for row in self.slot.pool.active.values())
        for child in children:
            if child.poll() is None:
                with suppress(ProcessLookupError):
                    child.kill()
        for child in children:
            child.wait(timeout=2)


def main():
    parser = argparse.ArgumentParser(
        description="Async prospective paper runtime, no broker orders"
    )
    parser.add_argument("--activation-sha256", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--initialize", action="store_true")
    mode.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    try:
        activation = load_activation(Path(__file__).resolve().parents[3], args.activation_sha256)
        ready(activation)
        if args.check:
            print(json.dumps(dict(status="ASYNC_ACTIVATION_VERIFIED")))
            return 0
        if args.initialize:
            parent.initialize(activation)
            print(json.dumps(dict(status="GENESIS_CREATED")))
            return 0
        token = os.environ.get("MOEX_ALGOPACK_TOKEN", "")
        if not token or "\r" in token or "\n" in token:
            raise ValueError("credential unavailable")
        import requests

        with requests.Session() as session:
            session.trust_env = False
            with parent.bridge.anchors.transaction(parent.DATA_ROOT / activation.activation_sha256):
                runtime = Runtime(activation, session, token)
                try:
                    while True:
                        result = runtime.tick()
                        if result["due"]["outcomes"]:
                            print(json.dumps(result), flush=True)
                        time.sleep(0.1)
                finally:
                    runtime.stop_children()
        return 0
    except Exception:
        print(json.dumps(dict(status="ASYNC_RUNTIME_STOPPED_REQUIRES_REVIEW")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
