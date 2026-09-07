"""Single ledger owner consuming a dedicated parallel quote pool for due positions."""

import uuid
from contextlib import suppress
from pathlib import Path

from market_lab.futures import algopack_paper_execution_bridge_v1 as bridge
from market_lab.futures import algopack_paper_execution_worker_v1 as worker
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE

PROTOCOL = "algopack_paper_async_due_v1"
journal = bridge.journal


def ready(activation):
    bridge.ready(activation)
    worker.ready(activation)
    raw = (activation.project / BUNDLE).read_bytes()
    if journal.sha(raw) != activation.bundle_sha256:
        raise ValueError("async due bundle changed")
    if journal._decode(raw)["files"].get(
        "src/market_lab/futures/" + Path(__file__).name
    ) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("async due absent from activation")


def market_root(activation):
    return worker.runtime.DATA_ROOT / activation.activation_sha256 / "market"


def groups(state, now):
    result = {}
    for position, row in state["positions"].items():
        if row["status"] == "UNRESOLVED":
            continue
        entry = row["entry"] is None
        intent = row["intent"]
        due = bridge.source._stamp(intent["entry_at" if entry else "exit_at"])
        if due <= now:
            result.setdefault((entry, due, intent["asset"], intent["secid"]), []).append(position)
    return {group: sorted(result[group]) for group in sorted(result)}


class Executor:
    """Owner must hold runtime lifetime lock; pool is exclusively for due jobs, not preparation."""

    def __init__(self, runtime, attempts: Path):
        ready(runtime.account.activation)
        if runtime.market_root != market_root(runtime.account.activation):
            raise ValueError("async due worker market root differs from execution root")
        journal._ordinary(attempts, directory=True)
        if attempts in (runtime.market_root, runtime.account.control, runtime.account.ledger):
            raise ValueError("async due attempt root must be separate")
        self.runtime, self.attempts = runtime, attempts
        self.activation = runtime.account.activation
        self.pool = worker.Pool(self.activation)
        self.jobs = {}
        self.valid = True

    def tick(self):
        ready(self.activation)
        if not self.valid:
            raise ValueError("async execution invalidated; anchored reopen required")
        with bridge.anchors.transaction(self.attempts):
            try:
                completed = {row["key"]: row for row in self.pool.poll()}
                due_groups = groups(self.runtime.account.snapshot(), journal.now())
                outcomes = []
                for group, positions in due_groups.items():
                    _, due, asset, secid = group
                    deadline = due + bridge.execution.MAX_FILL_DELAY
                    pending = self.jobs.get(group)
                    if journal.now() > deadline:
                        for position in positions:
                            outcomes.append(self.fill(position, None))
                        # Still-running child remains owned until reaped; no new job for
                        # this expired group. Next poll removes its completed mapping.
                        continue
                    if pending is not None:
                        terminal = completed.get(pending.key)
                        if terminal is None:
                            continue
                        del self.jobs[group]
                        reference = None
                        if terminal["state"] == "EXITED":
                            with suppress(ValueError, OSError, KeyError, TypeError):
                                reference = worker.observe(pending, self.activation)["reference"]
                        self.record(
                            state="SOURCE_COMPLETED",
                            job_key=pending.key,
                            source_state=terminal["state"],
                            source_observed=reference is not None,
                        )
                        if reference is not None:
                            for position in positions:
                                current = self.runtime.account.snapshot()["positions"].get(position)
                                if current is not None and position in groups(
                                    dict(positions={position: current}), journal.now()
                                ).get(group, []):
                                    outcomes.append(self.fill(position, reference))
                        # Retry on a later tick only, with a fresh UUID/current receipt.
                        continue
                    if journal.now() >= deadline:
                        continue
                    job = worker.Job(
                        "async_" + uuid.uuid4().hex, "quote", due, deadline, asset, secid
                    )
                    status = self.pool.start(job)
                    if status == "STARTED":
                        self.jobs[group] = job
                    elif status != "POOL_FULL":
                        raise ValueError("unexpected async source job reservation")
                for group, job in list(self.jobs.items()):
                    if job.key not in self.pool.active and (
                        group not in due_groups
                        or journal.now() > group[1] + bridge.execution.MAX_FILL_DELAY
                    ):
                        del self.jobs[group]
                return dict(
                    status="ASYNC_DUE_TICK",
                    outcomes=outcomes,
                    active_workers=len(self.pool.active),
                    execution_admitted=False,
                )
            except Exception:
                self.valid = False
                self.record(state="FAILED_REOPEN_REQUIRED")
                raise RuntimeError("async execution failed; anchored reopen required") from None

    def record(self, **payload):
        return journal.publish(
            self.attempts,
            kind="source",
            key="async_due_" + uuid.uuid4().hex,
            future_start=self.activation.future_start,
            payload=dict(
                protocol_id=PROTOCOL,
                activation_sha256=self.activation.activation_sha256,
                execution_admitted=False,
                **payload,
            ),
        )

    def fill(self, position, reference):
        self.record(state="FILL_STARTED", position=position, reference=reference)
        result = self.runtime.fill_due(position=position, quote_reference=reference)
        self.record(state="FILL_FINISHED", position=position, result=result)
        return dict(position=position, result=result)
