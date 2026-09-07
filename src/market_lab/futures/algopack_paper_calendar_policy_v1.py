"""Fixed pre-decision calendar version policy; never selects from economic outcomes."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta
from pathlib import Path

from market_lab.futures import algopack_paper_calendar_source_v1 as source
from market_lab.futures import algopack_paper_journal_v1 as journal
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE, VerifiedActivation
from market_lab.futures.algopack_paper_alignment_v1 import MOSCOW, utc

PROTOCOL = "algopack_paper_calendar_policy_v1"


def ready(activation: VerifiedActivation) -> None:
    source.ready(activation)
    raw = (activation.project / BUNDLE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != activation.bundle_sha256:
        raise ValueError("calendar policy bundle changed")
    files = source.source._decode(raw)["files"]
    path = Path(__file__)
    if (
        files.get("src/market_lab/futures/" + path.name)
        != hashlib.sha256(path.read_bytes()).hexdigest()
    ):
        raise ValueError("calendar policy absent from activation")


def key(day: date) -> str:
    if type(day) is not date:
        raise ValueError("calendar date required")
    return "calendar_" + day.strftime("%Y%m%d")


def window(day: date) -> tuple[datetime, datetime]:
    key(day)
    begin = utc(datetime.combine(day, time(9), MOSCOW))
    return begin, begin + timedelta(minutes=5)


def capture(session, root: Path, activation: VerifiedActivation, *, token: str) -> dict:
    ready(activation)
    now = journal.now()
    day = now.astimezone(MOSCOW).date()
    begin, end = window(day)
    if day.weekday() >= 5 or not begin <= now < end:
        raise ValueError("outside fixed calendar attempt window")
    # Canonical STARTED prevents a second attempt/revision, including after failure.
    return source.collect(session, root, key(day), activation, token=token)


def build(root: Path, activation: VerifiedActivation, *, through: date) -> dict:
    """Complete F-to-through calendar decision ledger, not economic report admission."""
    ready(activation)
    now = journal.now()
    source.current_window(activation)  # F/current-clock gate before journal reads.
    first = activation.future_start.astimezone(MOSCOW).date()
    if (
        type(through) is not date
        or through < first
        or utc(datetime.combine(through, time(18, 20, 30), MOSCOW)) > now
    ):
        raise ValueError("calendar report period is not complete after F")
    journal._ordinary(root, directory=True)
    parent = root / "source"
    if parent.exists() or parent.is_symlink():
        journal._ordinary(parent, directory=True)
    days, expected, unresolved = [], [], []
    for offset in range((through - first).days + 1):
        day = first + timedelta(days=offset)
        row = dict(day=day.isoformat(), status="OUT_OF_SCOPE_WEEKEND", source_observation=None)
        if day.weekday() < 5:
            row["status"] = "MISSING_CALENDAR"
            path = parent / key(day)
            if path.exists() or path.is_symlink():
                # Corruption is an error, not a reason to try a later, favorable version.
                marker = journal._decode(journal._read(path / "COMMITTED.json"))
                ref = dict(kind="source", key=key(day), record_sha256=marker["record_sha256"])
                observed = source.observe(root, ref, activation)
                begin, cutoff = window(day)
                if observed["first"] != day.isoformat() or observed["last"] != day.isoformat():
                    raise ValueError("canonical calendar date mismatch")
                timely = (
                    all(
                        begin
                        <= source.source._stamp(page["requested_at"])
                        <= source.source._stamp(page["received_at"])
                        < cutoff
                        for page in observed["pages"]
                    )
                    and source.source._stamp(observed["durable_payload_at"]) < cutoff
                )
                row.update(
                    status=observed["rows"][0]["status"] if timely else "LATE_CALENDAR",
                    source_observation=observed["source_observation"],
                    replay_sha256=observed["replay_sha256"],
                    durable_payload_at=observed["durable_payload_at"],
                )
            if row["status"] == "OPEN":
                expected.append(day.isoformat())
            elif row["status"] != "CLOSED":
                unresolved.append(day.isoformat())
        days.append(row)
    # Observation clocks vary on reread; digest binds canonical source identities and
    # fixed policy decisions, not the auditor's wall clock.
    evidence = [
        {
            **row,
            "source_observation": None
            if row["source_observation"] is None
            else {
                name: row["source_observation"][name] for name in ("kind", "key", "record_sha256")
            },
        }
        for row in days
    ]
    digest = hashlib.sha256(
        journal.encode(
            dict(
                protocol_id=PROTOCOL, activation_sha256=activation.activation_sha256, days=evidence
            )
        )
    ).hexdigest()
    return dict(
        protocol_id=PROTOCOL,
        activation_sha256=activation.activation_sha256,
        first=first.isoformat(),
        through=through.isoformat(),
        days=days,
        expected_days=expected if not unresolved else None,
        unresolved_days=unresolved,
        calendar_sha256=digest,
        observed_at=journal.now().isoformat(),
        status="CALENDAR_POLICY_RESOLVED" if not unresolved else "UNRESOLVED_CALENDAR",
        calendar_source_verified=not unresolved,
        execution_admitted=False,
        report_admitted=False,
    )
