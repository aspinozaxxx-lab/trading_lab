"""Bounded isolated execution-source jobs; no ledger/fill operations or implicit admission."""

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from market_lab.futures import algopack_paper_execution_source_v1 as source
from market_lab.futures import algopack_paper_runtime_v1 as runtime
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE, load_activation
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW, utc

PROTOCOL = "algopack_paper_execution_worker_v1"
CAPACITY = 4
journal = runtime.journal


@dataclass(frozen=True)
class Job:
    key: str
    kind: str
    not_before: datetime
    deadline: datetime
    asset: str | None = None
    secid: str | None = None


def ready(activation):
    runtime.ready(activation)
    raw = (activation.project / BUNDLE).read_bytes()
    if journal.sha(raw) != activation.bundle_sha256:
        raise ValueError("execution worker bundle changed")
    if journal._decode(raw)["files"].get(
        "src/market_lab/futures/" + Path(__file__).name
    ) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("execution worker absent from activation")


def validate(job, activation):
    ready(activation)
    now = journal.now()
    if not isinstance(job, Job) or re.fullmatch(r"async_[0-9a-f]{32}", job.key) is None:
        raise ValueError("canonical execution job required")
    begin, end = utc(job.not_before), utc(job.deadline)
    if not activation.future_start <= begin <= now < end or end - begin > timedelta(minutes=10):
        raise ValueError("execution job outside bounded window")
    if begin.astimezone(MOSCOW).date() != end.astimezone(MOSCOW).date():
        raise ValueError("execution job crosses calendar date")
    source.request_url(
        job.kind, source.market.RequestWindow(activation.future_start, now), job.asset, job.secid
    )
    root = runtime.DATA_ROOT / activation.activation_sha256
    for path in (root, root / "market", root / "scheduler"):
        journal._ordinary(path, directory=True)
    return root


def collect(session, job, activation, *, token):
    root = validate(job, activation)
    # Existing collector owns TLS, raw receipts, source validation and durable publication.
    return source.collect(
        session,
        root / "market",
        key=job.key,
        activation=activation,
        kind=job.kind,
        token=token,
        asset=job.asset,
        secid=job.secid,
    )


class Pool:
    """At most four owned children. Caller prioritizes exits; no hidden waiting queue."""

    def __init__(self, activation):
        ready(activation)
        self.activation, self.active = activation, {}

    def record(self, root, job, suffix, **payload):
        return journal.publish(
            root / "scheduler",
            kind="source",
            key=job.key + suffix,
            future_start=self.activation.future_start,
            payload=dict(
                protocol_id=PROTOCOL,
                activation_sha256=self.activation.activation_sha256,
                kind=job.kind,
                asset=job.asset,
                secid=job.secid,
                not_before=utc(job.not_before).isoformat(),
                deadline=utc(job.deadline).isoformat(),
                execution_admitted=False,
                **payload,
            ),
        )

    def start(self, job):
        if len(self.active) >= CAPACITY:
            return "POOL_FULL"
        root = validate(job, self.activation)
        marker = root / "scheduler" / "source" / (job.key + "_started")
        if marker.exists() or marker.is_symlink():
            return "EXISTING_ATTEMPT"
        self.record(root, job, "_started", state="STARTED")
        argv = [
            sys.executable,
            "-m",
            "market_lab.futures.algopack_paper_execution_worker_v1",
            "--activation-sha256",
            self.activation.activation_sha256,
            "--key",
            job.key,
            "--kind",
            job.kind,
            "--not-before",
            utc(job.not_before).isoformat(),
            "--deadline",
            utc(job.deadline).isoformat(),
        ]
        if job.asset is not None:
            argv.extend(["--asset", job.asset, "--secid", job.secid])
        try:
            child = subprocess.Popen(
                argv,
                cwd=str(self.activation.project),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except Exception:
            self.record(root, job, "_failed", state="SPAWN_FAILED")
            raise ValueError("execution source spawn failed") from None
        self.active[job.key] = dict(job=job, root=root, child=child, terminated=None)
        return "STARTED"

    def poll(self):
        outcomes = []
        for key, item in list(self.active.items()):
            job, child = item["job"], item["child"]
            code = child.poll()
            expired = journal.now() >= utc(job.deadline) or item["terminated"] is not None
            if code is not None:
                state = "EXPIRED" if expired else "EXITED" if code == 0 else "FAILED"
                self.record(item["root"], job, "_finished", state=state, exit_code=code)
                outcomes.append(dict(key=key, state=state, source_admitted=False))
                del self.active[key]
            elif expired:
                try:
                    if item["terminated"] is None:
                        item["terminated"] = time.monotonic()
                        child.terminate()
                    elif time.monotonic() - item["terminated"] >= 5:
                        child.kill()
                except ProcessLookupError:
                    pass  # A concurrent exit is reaped on the next non-waiting poll.
        return outcomes


def observe(job, activation):
    root = validate(job, activation)  # Actual consumption must still be before deadline.
    path = root / "market" / "source" / job.key
    marker = journal._decode(journal._read(path / "COMMITTED.json"))
    ref = dict(kind="source", key=job.key, record_sha256=marker["record_sha256"])
    observed = source.observe(root / "market", ref, activation)
    completed = journal.observe(
        root / "market",
        kind="source",
        key=job.key,
        record_sha256=ref["record_sha256"],
        future_start=activation.future_start,
    )
    first_ref = completed["payload"]["steps"][0]
    first = journal.observe(
        root / "market",
        kind="source",
        key=first_ref["key"],
        record_sha256=first_ref["record_sha256"],
        future_start=activation.future_start,
    )
    if (
        observed["kind"] != job.kind
        or source._stamp(first["payload"]["step"]["receipt"]["request_started_at"])
        < utc(job.not_before)
        or source._stamp(observed["request_started_at"]) < utc(job.not_before)
        or journal.now() >= utc(job.deadline)
    ):
        raise ValueError("execution source job observation scope/deadline")
    if job.kind == "quote" and any(
        page["asset"] != job.asset or page["secid"] != job.secid for page in observed["pages"]
    ):
        raise ValueError("execution job quote identity mismatch")
    # Five-second freshness remains the execution bridge's
    # responsibility. A source receipt is never itself an accepted fill.
    return dict(reference=ref, observation=observed, execution_admitted=False)


def main():
    parser = argparse.ArgumentParser(description="Isolated paper execution-source worker")
    for name in ("activation-sha256", "key", "kind", "not-before", "deadline"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--asset")
    parser.add_argument("--secid")
    args = parser.parse_args()
    try:
        activation = load_activation(Path(__file__).resolve().parents[3], args.activation_sha256)
        begin, end = datetime.fromisoformat(args.not_before), datetime.fromisoformat(args.deadline)
        if utc(begin).isoformat() != args.not_before or utc(end).isoformat() != args.deadline:
            raise ValueError("canonical UTC job clocks required")
        job = Job(args.key, args.kind, begin, end, args.asset, args.secid)
        validate(job, activation)
        token = os.environ.get("MOEX_ALGOPACK_TOKEN", "")
        if not token or "\r" in token or "\n" in token:
            raise ValueError("credential unavailable")
        import requests

        with requests.Session() as session:
            session.trust_env = False
            collect(session, job, activation, token=token)
        return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
