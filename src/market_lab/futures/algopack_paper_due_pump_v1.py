"""Prioritized due-position pass with durable outcomes and no live orders."""

import uuid
from pathlib import Path

from market_lab.futures import algopack_paper_execution_bridge_v1 as bridge
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE

journal = bridge.journal
PROTOCOL = "algopack_paper_due_pump_v1"


def ready(activation):
    bridge.ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    name = "src/market_lab/futures/algopack_paper_due_pump_v1.py"
    if files.get(name) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("due pump absent from complete activation")


def due_positions(state, at):
    result = []
    for key, row in state["positions"].items():
        if row["status"] == "UNRESOLVED":
            continue
        is_exit = row["entry"] is not None
        due = bridge.source._stamp(row["intent"]["exit_at" if is_exit else "entry_at"])
        if due <= at:
            result.append((not is_exit, due, key))
    return sorted(result)  # Exits first, then earliest due, then stable position key.


def run(runtime, session, attempts: Path, *, token):
    activation = runtime.account.activation
    ready(activation)
    if attempts in (runtime.market_root, runtime.account.control, runtime.account.ledger):
        raise ValueError("dedicated attempt journal required")
    with bridge.anchors.transaction(attempts):
        positions = due_positions(runtime.account.snapshot(), journal.now())
        if not positions:
            return dict(status="NOTHING_DUE", outcomes=[], execution_admitted=False)
        key = "pump_" + uuid.uuid4().hex

        def record(suffix, **payload):
            return journal.publish(
                attempts,
                kind="source",
                key=key + suffix,
                future_start=activation.future_start,
                payload=dict(
                    protocol_id=PROTOCOL,
                    activation_sha256=activation.activation_sha256,
                    execution_admitted=False,
                    **payload,
                ),
            )

        record("_started", state="STARTED", positions=[item[2] for item in positions])
        outcomes, quotes = [], {}
        for index, (is_entry, due, position) in enumerate(positions):
            # Authoritative account state is rechecked per operation; never restore a saved Fill.
            row = runtime.account.snapshot()["positions"][position]
            record(f"_{index}_started", state="POSITION_STARTED", position=position)
            reference, source_failed = None, False
            if journal.now() <= due + bridge.execution.MAX_FILL_DELAY:
                group = (row["intent"]["asset"], row["intent"]["secid"], due, is_entry)
                if group not in quotes:
                    try:
                        quotes[group] = bridge.source.collect(
                            session,
                            runtime.market_root,
                            key=key + f"_q{index}",
                            activation=activation,
                            kind="quote",
                            token=token,
                            asset=group[0],
                            secid=group[1],
                        )
                    except Exception:
                        quotes[group] = (
                            None  # This pass records failure; next pass gets a new source.
                        )
                reference = quotes[group]
                source_failed = reference is None
            try:
                # Collection past deadline means CANCEL/UNRESOLVED, never a late fill.
                result = runtime.fill_due(position=position, quote_reference=reference)
            except Exception:
                record(
                    f"_{index}_failed", state="POSITION_FAILED_REOPEN_REQUIRED", position=position
                )
                record("_failed", state="FAILED_REOPEN_REQUIRED")
                return dict(
                    status="FAILED_REOPEN_REQUIRED", outcomes=outcomes, execution_admitted=False
                )
            record(
                f"_{index}_finished",
                state="POSITION_FINISHED",
                position=position,
                source_failed=source_failed,
                result=result,
            )
            outcomes.append(dict(position=position, source_failed=source_failed, result=result))
        record("_finished", state="COMPLETE", outcomes=outcomes)
        return dict(status="COMPLETE", outcomes=outcomes, execution_admitted=False)
