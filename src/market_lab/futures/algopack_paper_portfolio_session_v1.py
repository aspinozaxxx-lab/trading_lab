"""Verified process-local state with bounded journal-read append, not a disk checkpoint."""

from __future__ import annotations

import copy
import os
from pathlib import Path

from market_lab.futures import algopack_paper_portfolio_v1 as portfolio
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE, VerifiedActivation

journal = portfolio.journal


def ready(activation: VerifiedActivation) -> None:
    portfolio._ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    name = "src/market_lab/futures/algopack_paper_portfolio_session_v1.py"
    if files.get(name) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("portfolio session missing from complete activation")


class PortfolioSession:
    """One process-local cache. Never deserialize arbitrary cached equity as trusted state.

    Every construction fully replays the immutable journal. A competing writer or any
    uncertain publication invalidates this instance; reopen/replay before another decision.
    Full history byte auditing remains a startup/offline operation, not each hot append.
    """

    def __init__(self, root: Path, activation: VerifiedActivation, *, expected_tail: dict):
        ready(activation)
        if (
            set(expected_tail) != {"sequence", "record_sha256"}
            or type(expected_tail["sequence"]) is not int
            or expected_tail["sequence"] < 0
        ):
            raise ValueError("explicit external tail required")
        portfolio.execution.sha(expected_tail["record_sha256"])
        if expected_tail["sequence"] == 0 and expected_tail["record_sha256"] != portfolio.ZERO:
            raise ValueError("invalid initial external tail")
        self._root, self._activation = root, activation
        self._state = portfolio.recover(root, activation, expected_tail=expected_tail)

    def snapshot(self) -> dict:
        if self._state is None:
            raise ValueError("portfolio session invalidated; full replay required")
        return copy.deepcopy(self._state)

    def anchor(self) -> dict:
        state = self.snapshot()
        return dict(sequence=state["sequence"], record_sha256=state["last_record_sha256"])

    def _tail(self) -> None:
        state = self.snapshot()
        parent = self._root / "source"
        if state["sequence"]:
            key = f"portfolio_{state['sequence']:08d}"
            journal.observe(
                self._root,
                kind="source",
                key=key,
                record_sha256=state["last_record_sha256"],
                future_start=self._activation.future_start,
            )
        elif parent.exists():
            journal._ordinary(parent, directory=True)
            if any(parent.iterdir()):
                raise ValueError("cached portfolio is stale")
        # Ordinary writers can only append this next reserved slot, under the same lock.
        next_path = parent / f"portfolio_{state['sequence'] + 1:08d}"
        if next_path.exists() or next_path.is_symlink():
            raise ValueError("cached portfolio is stale or next event is incomplete")

    def append(self, *, operation: str, data: dict) -> tuple[dict, dict]:
        ready(self._activation)
        self.snapshot()  # Reject an invalidated instance before any lock or publication.
        if os.name != "posix":
            raise ValueError("portfolio session requires Linux")
        import fcntl

        journal._ordinary(self._root, directory=True)
        lock = self._root / ".portfolio.lock"
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        publishing = False
        try:
            journal._ordinary(lock)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                self._tail()
            except Exception:
                self._state = None
                raise
            at = journal.now()
            event = dict(
                protocol_id=portfolio.PROTOCOL,
                sequence=self._state["sequence"] + 1,
                previous_record_sha256=self._state["last_record_sha256"],
                at=at.isoformat(),
                operation=operation,
                data=portfolio.wire(data),
            )
            portfolio.apply(self._state, event, durable_at=at, record_sha256=portfolio.ZERO)
            publishing = True
            reference = journal.publish(
                self._root,
                kind="source",
                key=f"portfolio_{event['sequence']:08d}",
                future_start=self._activation.future_start,
                payload=event,
            )
            self._state = portfolio.apply(
                self._state,
                event,
                durable_at=portfolio.source._stamp(reference["durable_payload_at"]),
                record_sha256=reference["record_sha256"],
            )
            return self.snapshot(), reference
        except Exception:
            if publishing:
                self._state = None  # Even a lost acknowledgment must not retry from stale state.
            raise
        finally:
            os.close(fd)
