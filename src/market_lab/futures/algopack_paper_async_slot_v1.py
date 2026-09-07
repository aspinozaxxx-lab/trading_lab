"""Stepwise paper intent admission using background sources; one authoritative ledger owner."""

import uuid
from contextlib import suppress
from datetime import timedelta
from pathlib import Path

from market_lab.futures import algopack_paper_execution_worker_v1 as worker
from market_lab.futures import algopack_paper_mark_refresh_v1 as marks
from market_lab.futures import algopack_paper_preparation_intake_v1 as intake
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE
from market_lab.futures.algopack_paper_alignment_v1 import ASSETS, MOSCOW, utc

PROTOCOL = "algopack_paper_async_slot_v1"
journal = marks.journal


def ready(activation):
    intake.ready(activation)
    worker.ready(activation)
    marks.ready(activation)
    raw = (activation.project / BUNDLE).read_bytes()
    if journal.sha(raw) != activation.bundle_sha256:
        raise ValueError("async slot bundle changed")
    if journal._decode(raw)["files"].get(
        "src/market_lab/futures/" + Path(__file__).name
    ) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("async slot missing from activation")


class Slot:
    """Caller ticks due execution first; a dedicated pool never uses due-pool capacity."""

    def __init__(self, runtime, attempts: Path, information_end):
        self.activation = runtime.account.activation
        ready(self.activation)
        self.end = utc(information_end)
        if self.end < self.activation.future_start or self.end not in intake.worker.coverage.slots(
            self.end.astimezone(MOSCOW).date()
        ):
            raise ValueError("invalid async slot")
        self.deadline = self.end + timedelta(minutes=10)
        if not self.end + timedelta(minutes=3) <= journal.now() < self.deadline:
            raise ValueError("outside async slot start window")
        journal._ordinary(attempts, directory=True)
        if attempts in (runtime.account.control, runtime.account.ledger, runtime.market_root):
            raise ValueError("async slot attempt root must be separate")
        expected_market = worker.runtime.DATA_ROOT / self.activation.activation_sha256 / "market"
        if runtime.market_root != expected_market:
            raise ValueError("async slot source root differs")
        self.runtime, self.attempts = runtime, attempts
        self.key = "async_slot_" + self.end.strftime("%Y%m%dT%H%M%SZ")
        self.phase, self.valid = "INTAKE", True
        self.pool = worker.Pool(self.activation)
        self.jobs, self.completed, self.references = {}, {}, {}
        self.open_contracts, self.assets, self.index = {}, {}, 0
        self.forecast = self.calendar = None
        self.record(
            "_started", state="STARTED"
        )  # Partial/existing attempt is never resumed blindly.

    def record(self, suffix, **payload):
        return journal.publish(
            self.attempts,
            kind="source",
            key=self.key + suffix,
            future_start=self.activation.future_start,
            payload=dict(
                protocol_id=PROTOCOL,
                activation_sha256=self.activation.activation_sha256,
                information_end=self.end.isoformat(),
                execution_admitted=False,
                **payload,
            ),
        )

    def launch(self, tag, kind, asset=None, secid=None):
        if tag in self.jobs:
            return
        job = worker.Job(
            "async_" + uuid.uuid4().hex, kind, journal.now(), self.deadline, asset, secid
        )
        status = self.pool.start(job)
        if status == "STARTED":
            self.jobs[tag] = job
        elif status != "POOL_FULL":
            raise ValueError("unexpected slot source reservation")

    def take(self, tag):
        if tag in self.references:
            return True, self.references[tag]
        job = self.jobs.get(tag)
        if job is None or job.key not in self.completed:
            return False, None
        terminal, reference = self.completed[job.key], None
        if terminal["state"] == "EXITED":
            with suppress(ValueError, OSError, KeyError, TypeError):
                reference = worker.observe(job, self.activation)["reference"]
        self.record(
            "_source_" + tag,
            state="SOURCE_OBSERVED",
            job_key=job.key,
            worker_state=terminal["state"],
            reference=reference,
        )
        self.references[tag] = reference
        return True, reference

    def finish(self, state):
        self.record("_finished", state=state)
        self.phase = state

    def tick(self):
        ready(self.activation)
        if not self.valid:
            raise ValueError("async slot invalidated; anchored reopen required")
        try:
            self.completed.update({row["key"]: row for row in self.pool.poll()})
            if self.phase in ("COMPLETE", "EXPIRED", "SOURCE_FAILED"):
                return dict(
                    status=self.phase,
                    active_workers=len(self.pool.active),
                    execution_admitted=False,
                )
            if journal.now() >= self.deadline:
                self.finish("EXPIRED")
            elif self.phase == "INTAKE":
                result = intake.consume(self.activation, self.end)
                if result["status"] == "WAITING_PREPARATION":
                    return dict(status="WAITING_PREPARATION", execution_admitted=False)
                if result["status"] != "FORECAST_OBSERVED_NOT_EXECUTION_ADMITTED":
                    self.finish("SOURCE_FAILED")
                else:
                    self.forecast = result["forecast"]
                    self.assets = {
                        row["asset"]: row for row in result["consumed"]["payload"]["assets"]
                    }
                    if set(self.assets) != set(ASSETS):
                        raise ValueError("async slot forecast assets differ")
                    self.record("_intake", state="INTAKE", reference=result["reference"])
                    self.phase = "CALENDAR"
            elif self.phase == "CALENDAR":
                self.launch("calendar", "calendar")
                done, reference = self.take("calendar")
                if done:
                    if reference is None:
                        self.finish("SOURCE_FAILED")
                    else:
                        self.calendar = reference
                        opened = self.runtime.account.snapshot()["positions"]
                        identities = sorted(
                            {
                                (row["intent"]["asset"], row["intent"]["secid"])
                                for row in opened.values()
                                if row["entry"] is not None
                            }
                            | {(asset, self.assets[asset]["secid"]) for asset in ASSETS}
                        )
                        self.open_contracts = {
                            identity: "quote" + str(i) for i, identity in enumerate(identities)
                        }
                        self.phase = "MARKS"
            elif self.phase == "MARKS":
                all_done = True
                for (asset, secid), tag in self.open_contracts.items():
                    self.launch(tag, "quote", asset, secid)
                    done, _ = self.take(tag)
                    all_done &= done
                if all_done:
                    refs = {}
                    for position, row in self.runtime.account.snapshot()["positions"].items():
                        if row["entry"] is not None:
                            tag = self.open_contracts.get(
                                (row["intent"]["asset"], row["intent"]["secid"])
                            )
                            if tag is not None and self.references.get(tag) is not None:
                                refs[position] = self.references[tag]
                    # Newly opened/missing marks remain explicit unknowns, never old carry-forward.
                    marks.refresh(self.runtime, refs)
                    self.record("_marks", state="MARKS_REFRESHED")
                    self.phase = "DECISIONS"
            elif self.phase == "DECISIONS":
                asset = ASSETS[self.index]
                done, reference = self.take(
                    self.open_contracts[(asset, self.assets[asset]["secid"])]
                )
                if done:
                    for arm in journal.MODEL_SHA:
                        if journal.now() >= self.deadline:
                            self.finish("EXPIRED")
                            break
                        suffix = "_decision_" + arm + "_" + asset
                        self.record(suffix + "_started", state="DECISION_STARTED")
                        result = dict(status="MISSING_ASYNC_QUOTE", execution_admitted=False)
                        if reference is not None:
                            result = self.runtime.reserve(
                                asset=asset,
                                arm=arm,
                                forecast_reference=self.forecast,
                                quote_reference=reference,
                                calendar_reference=self.calendar,
                            )
                        self.record(suffix + "_finished", state="DECISION_FINISHED", result=result)
                    if self.phase != "EXPIRED":
                        self.index += 1
                        if self.index == len(ASSETS):
                            self.finish("COMPLETE")
            return dict(
                status=self.phase, active_workers=len(self.pool.active), execution_admitted=False
            )
        except Exception:
            self.valid = False
            self.record("_failed", state="FAILED_REOPEN_REQUIRED", phase=self.phase)
            raise RuntimeError("async slot failed; anchored reopen required") from None
