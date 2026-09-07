"""Isolated source/model preparation and non-waiting child supervision; no portfolio writes."""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from market_lab.futures import algopack_paper_capture_v1 as capture
from market_lab.futures import algopack_paper_coverage_v1 as coverage
from market_lab.futures import algopack_paper_flow_selection_v1 as flow
from market_lab.futures import algopack_paper_predictor_v1 as predictor
from market_lab.futures import algopack_paper_runtime_v1 as runtime
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE, load_activation
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW, utc

PROTOCOL = "algopack_paper_preparation_worker_v1"
journal = runtime.journal


def ready(activation):
    runtime.ready(activation)
    predictor._ready(activation)
    raw = (activation.project / BUNDLE).read_bytes()
    if journal.sha(raw) != activation.bundle_sha256:
        raise ValueError("preparation bundle changed")
    if journal._decode(raw)["files"].get(
        "src/market_lab/futures/" + Path(__file__).name
    ) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("preparation worker absent from activation")


def scope(activation, information_end):
    ready(activation)
    end = utc(information_end)
    if end < activation.future_start or end not in coverage.slots(end.astimezone(MOSCOW).date()):
        raise ValueError("invalid preparation slot")
    if not end + timedelta(minutes=3) <= journal.now() < end + timedelta(minutes=10):
        raise ValueError("outside preparation window")
    root = runtime.DATA_ROOT / activation.activation_sha256
    journal._ordinary(root, directory=True)
    journal._ordinary(root / "market", directory=True)
    journal._ordinary(root / "scheduler", directory=True)
    return root, "prepare_" + end.strftime("%Y%m%dT%H%M%SZ")


def prepare(session, activation, *, information_end, token):
    root, key = scope(activation, information_end)
    market = root / "market"

    def record(suffix, **data):
        return journal.publish(
            market,
            kind="source",
            key=key + suffix,
            future_start=activation.future_start,
            payload=dict(
                protocol_id=PROTOCOL,
                activation_sha256=activation.activation_sha256,
                execution_admitted=False,
                **data,
            ),
        )

    record("_started", state="STARTED")
    try:
        selection = flow.select_and_import(market, activation)
        record("_selection", state="FLOW_SELECTION", result=selection)
        scope(activation, information_end)
        packet = capture.capture_packet(
            session, activation=activation, root=market, key=key + "_market", token=token
        )
        scope(activation, information_end)
        forecast = predictor.predict_slot(
            market,
            activation=activation,
            information_end=information_end,
            market_reference=packet,
            flow_reference=selection["reference"],
        )
        # Predictor owns actual completion/deadline masking. Supervisor expiry is not
        # a substitute for original durable-source and actual-time consumer checks.
        return record("_finished", state="COMPLETE", forecast=forecast)
    except Exception:
        record("_failed", state="FAILED")
        raise ValueError("preparation failed; source attempt retained") from None


class Supervisor:
    """One owned child, no wait/communicate/join; caller must poll every execution tick."""

    def __init__(self, activation):
        ready(activation)
        self.activation = activation
        self.process = None
        self.end = self.key = self.root = None
        self.terminated_at = None

    def start(self, information_end):
        if self.process is not None:
            return dict(status="WORKER_BUSY", execution_admitted=False)
        root, key = scope(self.activation, information_end)
        parent = root / "scheduler" / "source" / (key + "_started")
        if parent.exists() or parent.is_symlink():
            return dict(status="EXISTING_PREPARATION_ATTEMPT", execution_admitted=False)
        self.root, self.key, self.end = root, key, utc(information_end)
        self.record("_started", state="STARTED", information_end=self.end.isoformat())
        try:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "market_lab.futures.algopack_paper_preparation_worker_v1",
                    "--activation-sha256",
                    self.activation.activation_sha256,
                    "--information-end",
                    self.end.isoformat(),
                ],
                cwd=str(self.activation.project),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except Exception:
            self.record("_failed", state="SPAWN_FAILED")
            raise ValueError("preparation spawn failed") from None
        return dict(status="WORKER_STARTED", execution_admitted=False)

    def record(self, suffix, **data):
        return journal.publish(
            self.root / "scheduler",
            kind="source",
            key=self.key + suffix,
            future_start=self.activation.future_start,
            payload=dict(
                protocol_id=PROTOCOL,
                activation_sha256=self.activation.activation_sha256,
                execution_admitted=False,
                **data,
            ),
        )

    def poll(self):
        if self.process is None:
            return dict(status="NO_WORKER", execution_admitted=False)
        code = self.process.poll()
        if code is not None:
            expired = self.terminated_at is not None or journal.now() >= self.end + timedelta(
                minutes=10
            )
            status = (
                "WORKER_EXPIRED" if expired else "WORKER_EXITED" if code == 0 else "WORKER_FAILED"
            )
            self.record("_finished", state=status, exit_code=code)
            self.process = None
            self.terminated_at = None
            return dict(status=status, execution_admitted=False, forecast_admitted=False)
        if journal.now() >= self.end + timedelta(minutes=10):
            if self.terminated_at is None:
                self.terminated_at = time.monotonic()
                self.process.terminate()
            elif time.monotonic() - self.terminated_at >= 5:
                self.process.kill()
            return dict(status="WORKER_STOP_REQUESTED", execution_admitted=False)
        return dict(status="WORKER_RUNNING", execution_admitted=False)


def main():
    parser = argparse.ArgumentParser(description="Isolated prospective source/model worker")
    parser.add_argument("--activation-sha256", required=True)
    parser.add_argument("--information-end", required=True)
    args = parser.parse_args()
    try:
        activation = load_activation(Path(__file__).resolve().parents[3], args.activation_sha256)
        end = datetime.fromisoformat(args.information_end)
        if utc(end).isoformat() != args.information_end:
            raise ValueError("canonical UTC worker slot required")
        scope(activation, end)  # Before secret/session access.
        token = os.environ.get("MOEX_ALGOPACK_TOKEN", "")
        if not token or "\r" in token or "\n" in token:
            raise ValueError("credential unavailable")
        import requests

        with requests.Session() as session:
            session.trust_env = False
            prepare(session, activation, information_end=end, token=token)
        return 0
    except Exception:
        return 1  # Detailed raw/exception output must not escape a worker.


if __name__ == "__main__":
    raise SystemExit(main())
