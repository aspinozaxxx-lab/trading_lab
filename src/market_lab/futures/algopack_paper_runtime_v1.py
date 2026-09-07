"""Activation-gated unified paper scheduler. No broker API or retrospective execution."""

import argparse
import json
import os
import time
from datetime import timedelta
from pathlib import Path

from market_lab.futures import algopack_paper_daily_snapshot_v1 as daily
from market_lab.futures import algopack_paper_due_pump_v1 as pump
from market_lab.futures import algopack_paper_flow_selection_v1 as flow
from market_lab.futures import algopack_paper_slot_runner_v1 as slots
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE, load_activation
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW

bridge, journal = pump.bridge, pump.journal
PROTOCOL = "algopack_paper_runtime_v1"
DATA_ROOT = Path("/srv/trading_lab_data/data/forward/algopack-paper-v1")
COMPONENTS = ("market", "control", "ledger", "attempts", "scheduler", "reports")


def ready(activation):
    for module in (daily, pump, flow, slots):
        module.ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    name = "src/market_lab/futures/algopack_paper_runtime_v1.py"
    if files.get(name) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("runtime absent from complete activation")
    if os.name != "posix":
        raise ValueError("paper runtime requires Linux")


def initialize(activation):
    """Explicit once-only bootstrap AFTER F. Normal restart never calls this."""
    ready(activation)
    root = DATA_ROOT / activation.activation_sha256
    DATA_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    journal._ordinary(DATA_ROOT, directory=True)
    root.mkdir(mode=0o700)  # Even an incomplete prior initialization is never reset.
    for name in COMPONENTS:
        (root / name).mkdir(mode=0o700)
    bridge.anchors.initialize(root / "control", root / "ledger", activation)


class Runtime:
    def __init__(self, activation, session, token):
        ready(activation)
        self.activation, self.session, self.token = activation, session, token
        self.root = DATA_ROOT / activation.activation_sha256
        for name in COMPONENTS:
            journal._ordinary(self.root / name, directory=True)
        account = bridge.anchors.AnchoredPortfolio(
            self.root / "control", self.root / "ledger", activation
        )
        self.bridge = bridge.ExecutionBridge(account, self.root / "market")
        self.valid = True

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

    def work(self, key, callback):
        parent = self.root / "scheduler/source" / (key + "_started")
        if parent.exists() or parent.is_symlink():
            return "EXISTING_ATTEMPT"
        self.record(key + "_started", state="STARTED")
        try:
            result = callback()
            self.record(key + "_finished", state="FINISHED", result=result)
            return result["status"]
        except Exception:
            self.record(key + "_failed", state="FAILED_REOPEN_REQUIRED")
            self.valid = False
            raise RuntimeError("scheduled work failed; reopen required") from None

    def forecast(self, end, key):
        selection = flow.select_and_import(self.root / "market", self.activation)
        self.record(key + "_selection", state="FLOW_SELECTION", result=selection)
        result = slots.run(
            self.bridge,
            self.session,
            self.root / "attempts",
            information_end=end,
            token=self.token,
            flow_reference=selection["reference"],
        )
        if result["status"] == "FAILED":
            self.valid = False
            raise RuntimeError("slot failure requires anchored reopen")
        return result

    def snapshot(self, day):
        references, shared = {}, {}
        for key, row in sorted(self.bridge.account.snapshot()["positions"].items()):
            if row["entry"] is None:
                continue
            identity = (row["intent"]["asset"], row["intent"]["secid"])
            if identity not in shared:
                shared[identity] = bridge.source.collect(
                    self.session,
                    self.root / "market",
                    key="daily_" + day.strftime("%Y%m%d") + "_q" + str(len(shared)),
                    activation=self.activation,
                    kind="quote",
                    token=self.token,
                    asset=identity[0],
                    secid=identity[1],
                )
            references[key] = shared[identity]
        return daily.publish(self.bridge, self.root / "reports", day, references)

    def tick(self):
        ready(self.activation)
        if not self.valid:
            raise ValueError("runtime invalidated; reconstruct before tick")
        with bridge.anchors.transaction(self.root / "scheduler"):
            result = pump.run(self.bridge, self.session, self.root / "attempts", token=self.token)
            if result["status"] == "FAILED_REOPEN_REQUIRED":
                self.valid = False
                raise RuntimeError("due pump requires anchored reopen")
            now = journal.now()
            day = now.astimezone(MOSCOW).date()
            work = None
            if day.weekday() < 5:
                if daily.window(day) <= now <= daily.window(day) + timedelta(seconds=30):
                    work = self.work("daily_" + day.strftime("%Y%m%d"), lambda: self.snapshot(day))
                else:
                    for end in slots.coverage.slots(day):
                        if end + timedelta(minutes=3) <= now < end + timedelta(minutes=10):
                            key = "slot_" + end.strftime("%Y%m%dT%H%M%SZ")
                            work = self.work(key, lambda end=end, key=key: self.forecast(end, key))
                            break
            return dict(
                status="TICK_COMPLETED", pump=result["status"], work=work, execution_admitted=False
            )


def main():
    parser = argparse.ArgumentParser(description="Prospective paper runtime only")
    parser.add_argument("--activation-sha256", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--initialize", action="store_true")
    mode.add_argument("--serve", action="store_true")
    args = parser.parse_args()
    try:
        activation = load_activation(Path(__file__).resolve().parents[3], args.activation_sha256)
        ready(activation)  # Before secret access, session creation, directories or market IO.
        if args.check:
            print(json.dumps(dict(status="ACTIVATION_VERIFIED", execution_admitted=False)))
            return 0
        if args.initialize:
            initialize(activation)
            print(json.dumps(dict(status="GENESIS_CREATED", execution_admitted=False)))
            return 0
        token = os.environ.get("MOEX_ALGOPACK_TOKEN", "")
        if not token or "\r" in token or "\n" in token:
            raise ValueError("credential unavailable")
        import requests

        with requests.Session() as session:
            session.trust_env = False
            runtime = Runtime(activation, session, token)
            with bridge.anchors.transaction(runtime.root):  # One serving process per activation.
                while True:
                    result = runtime.tick()
                    if (
                        result["work"] not in (None, "EXISTING_ATTEMPT")
                        or result["pump"] != "NOTHING_DUE"
                    ):
                        print(json.dumps(result), flush=True)
                    time.sleep(1)
    except Exception:
        print(json.dumps(dict(status="RUNTIME_STOPPED_REQUIRES_REVIEW", execution_admitted=False)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
