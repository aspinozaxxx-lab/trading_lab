"""Separate immutable command/anchor journal; crash recovery never re-executes commands."""

from __future__ import annotations

import os
import re
import uuid
from contextlib import contextmanager
from pathlib import Path

from market_lab.futures import algopack_paper_portfolio_session_v1 as cached
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE, VerifiedActivation

portfolio, journal = cached.portfolio, cached.journal
PROTOCOL = "algopack_paper_portfolio_anchor_v1"
COMMAND_FIELD = "transaction_command"


def ready(activation):
    cached.ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    if files.get("src/market_lab/futures/algopack_paper_portfolio_anchor_v1.py") != journal.sha(
        Path(__file__).read_bytes()
    ):
        raise ValueError("anchor module absent from complete activation")


@contextmanager
def transaction(root):
    if os.name != "posix":
        raise ValueError("anchor transactions require Linux")
    import fcntl

    journal._ordinary(root, directory=True)
    fd = os.open(root / ".anchor_transaction.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        journal._ordinary(root / ".anchor_transaction.lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def read_event(root, key, activation):
    journal._key("source", key)
    marker = journal._decode(journal._read(root / "source" / key / "COMMITTED.json"))
    return journal.observe(
        root,
        kind="source",
        key=key,
        record_sha256=marker["record_sha256"],
        future_start=activation.future_start,
    )


def _header(activation, ledger):
    return dict(
        protocol_id=PROTOCOL,
        activation_sha256=activation.activation_sha256,
        portfolio_root=str(ledger),
        execution_admitted=False,
    )


def _validate_header(payload, activation, ledger):
    if any(payload.get(key) != value for key, value in _header(activation, ledger).items()):
        raise ValueError("anchor/command scope mismatch")


def initialize(control: Path, ledger: Path, activation: VerifiedActivation):
    """Explicit one-time initialization only; a normal restart never calls this function."""
    ready(activation)
    if control == ledger:
        raise ValueError("control and portfolio journals must be distinct")
    journal._ordinary(ledger, directory=True)
    with transaction(control):
        for root in (control, ledger):
            for item in root.iterdir():
                if item.name not in {
                    ".anchor_transaction.lock",
                    ".portfolio.lock",
                    ".journal.lock",
                }:
                    raise ValueError("initialization requires unused dedicated roots")
        journal.publish(
            control,
            kind="source",
            key="anchor_00000000",
            future_start=activation.future_start,
            payload=dict(
                **_header(activation, ledger),
                state="ANCHOR",
                sequence=0,
                portfolio_record_sha256=portfolio.ZERO,
                previous_anchor_record_sha256=portfolio.ZERO,
                command=None,
            ),
        )


class AnchoredPortfolio:
    def __init__(self, control: Path, ledger: Path, activation: VerifiedActivation):
        ready(activation)
        if control == ledger:
            raise ValueError("distinct journal roots required")
        self.control, self.ledger, self.activation = control, ledger, activation
        self._valid = False
        with transaction(control):
            parent = control / "source"
            journal._ordinary(parent, directory=True)  # Missing genesis is NOT a fresh account.
            names = sorted(item.name for item in parent.iterdir())
            if any(
                re.fullmatch(r"anchor_[0-9]{8}|command_[0-9a-f]{32}", name) is None
                for name in names
            ):
                raise ValueError("foreign control event")
            anchors = [name for name in names if name.startswith("anchor_")]
            if not anchors:
                raise ValueError("missing portfolio genesis anchor")
            previous = portfolio.ZERO
            for index, name in enumerate(anchors):
                if name != f"anchor_{index:08d}":
                    raise ValueError("anchor sequence gap")
                event = read_event(control, name, activation)
                data = event["payload"]
                _validate_header(data, activation, ledger)
                if (
                    data["state"] != "ANCHOR"
                    or type(data["sequence"]) is not int
                    or data["sequence"] != index
                    or data["previous_anchor_record_sha256"] != previous
                ):
                    raise ValueError("anchor chain mismatch")
                portfolio.execution.sha(data["portfolio_record_sha256"])
                if index == 0 and (
                    data["portfolio_record_sha256"] != portfolio.ZERO or data["command"] is not None
                ):
                    raise ValueError("invalid genesis")
                if index:
                    record = read_event(ledger, f"portfolio_{index:08d}", activation)
                    if record["record_sha256"] != data["portfolio_record_sha256"]:
                        raise ValueError("anchored portfolio record differs")
                    command = self._command(record)
                    if command != data["command"] or portfolio.source._stamp(
                        record["durable_payload_at"]
                    ) > portfolio.source._stamp(event["durable_payload_at"]):
                        raise ValueError("anchor publication chronology mismatch")
                previous = event["record_sha256"]
            self._last_anchor = event
            tail = dict(sequence=data["sequence"], record_sha256=data["portfolio_record_sha256"])
            self._session = cached.PortfolioSession(ledger, activation, expected_tail=tail)
            state = self._session.snapshot()
            if state["sequence"] > tail["sequence"] + 1:
                raise ValueError("multiple unexplained unanchored portfolio events")
            if state["sequence"] == tail["sequence"] + 1:
                record = read_event(ledger, f"portfolio_{state['sequence']:08d}", activation)
                command = self._command(record)
                if record["payload"]["previous_record_sha256"] != tail["record_sha256"]:
                    raise ValueError("unanchored event does not extend verified tail")
                self._publish_anchor(state, command)
            self._valid = True

    def _command(self, record):
        data = dict(record["payload"]["data"])
        ref = data.pop(COMMAND_FIELD)
        if ref["kind"] != "source" or re.fullmatch(r"command_[0-9a-f]{32}", ref["key"]) is None:
            raise ValueError("invalid portfolio command reference")
        command = journal.observe(
            self.control,
            kind="source",
            key=ref["key"],
            record_sha256=ref["record_sha256"],
            future_start=self.activation.future_start,
        )
        body = command["payload"]
        _validate_header(body, self.activation, self.ledger)
        if (
            body["state"] != "COMMAND"
            or type(body["sequence"]) is not int
            or body["sequence"] != record["payload"]["sequence"]
            or body["previous_portfolio_record_sha256"]
            != record["payload"]["previous_record_sha256"]
            or body["operation"] != record["payload"]["operation"]
            or journal.encode(body["data"]) != journal.encode(data)
            or portfolio.source._stamp(command["durable_payload_at"])
            > portfolio.source._stamp(record["payload"]["at"])
        ):
            raise ValueError("portfolio event differs from its prior durable command")
        return ref

    def _publish_anchor(self, state, command):
        ref = journal.publish(
            self.control,
            kind="source",
            key=f"anchor_{state['sequence']:08d}",
            future_start=self.activation.future_start,
            payload=dict(
                **_header(self.activation, self.ledger),
                state="ANCHOR",
                sequence=state["sequence"],
                portfolio_record_sha256=state["last_record_sha256"],
                previous_anchor_record_sha256=self._last_anchor["record_sha256"],
                command=command,
            ),
        )
        self._last_anchor = dict(
            payload=dict(sequence=state["sequence"]), record_sha256=ref["record_sha256"]
        )

    def snapshot(self):
        if not self._valid:
            raise ValueError("anchored portfolio invalidated; reopen required")
        return self._session.snapshot()

    def append(self, *, operation: str, data: dict):
        ready(self.activation)
        self.snapshot()
        if COMMAND_FIELD in data:
            raise ValueError("command reference is runtime-owned")
        with transaction(self.control):
            sequence = self._session.snapshot()["sequence"]
            if (self.control / "source" / f"anchor_{sequence + 1:08d}").exists():
                self._valid = False
                raise ValueError("another anchored writer advanced the journal")
            try:
                journal.observe(
                    self.control,
                    kind="source",
                    key=f"anchor_{sequence:08d}",
                    record_sha256=self._last_anchor["record_sha256"],
                    future_start=self.activation.future_start,
                )
                command = journal.publish(
                    self.control,
                    kind="source",
                    key="command_" + uuid.uuid4().hex,
                    future_start=self.activation.future_start,
                    payload=dict(
                        **_header(self.activation, self.ledger),
                        state="COMMAND",
                        sequence=sequence + 1,
                        previous_portfolio_record_sha256=self._session.anchor()["record_sha256"],
                        operation=operation,
                        data=portfolio.wire(data),
                    ),
                )
                ref = dict(
                    kind="source", key=command["key"], record_sha256=command["record_sha256"]
                )
                state, record = self._session.append(
                    operation=operation, data={**data, COMMAND_FIELD: ref}
                )
                self._publish_anchor(state, ref)
                return state, record
            except Exception:
                self._valid = False
                raise
