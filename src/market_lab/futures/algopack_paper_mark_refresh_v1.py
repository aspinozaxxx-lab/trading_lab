"""Refresh every open position from replayed sources; never retain a missing old mark."""

from pathlib import Path

from market_lab.futures import algopack_paper_execution_bridge_v1 as bridge
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE

portfolio, journal, source = bridge.portfolio, bridge.journal, bridge.source
PROTOCOL = "algopack_paper_mark_refresh_v1"


def ready(activation):
    bridge.ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    name = "src/market_lab/futures/algopack_paper_mark_refresh_v1.py"
    if files.get(name) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("mark refresh absent from complete activation")


def refresh(runtime: bridge.ExecutionBridge, references: dict) -> dict:
    """One all-open-position MARK event followed by actual post-commit valuation.

    References are position-key -> quote source reference. Missing/unreadable sources
    produce explicit masks; this function never fetches, retries or invents a price.
    Values are not daily evaluation snapshots and must not be annualized directly.
    """
    if not isinstance(runtime, bridge.ExecutionBridge):
        raise ValueError("execution bridge required")
    activation = runtime.account.activation
    ready(activation)
    state = runtime.account.snapshot()
    opened = {key: row for key, row in state["positions"].items() if row["entry"] is not None}
    if not isinstance(references, dict) or not set(references) <= set(opened):
        raise ValueError("mark references must name current open positions only")
    marks, evidence = {}, {}
    for key in sorted(opened):
        marks[key] = None
        reference = references.get(key)
        if reference is None:
            evidence[key] = dict(status="MISSING_REFERENCE", observation=None)
            continue
        try:
            observed = source.observe(runtime.market_root, reference, activation)
            inputs = source.quote_inputs(observed)
        except (OSError, ValueError, KeyError, TypeError):
            # Do not leak payloads, paths, tokens or exception text into portfolio logs.
            evidence[key] = dict(status="SOURCE_REPLAY_FAILED", observation=None)
            continue
        evidence[key] = dict(
            status="UNAVAILABLE_QUOTE" if inputs is None else "OBSERVED_CANDIDATE",
            observation=observed["source_observation"],
        )
        if inputs is not None:
            marks[key] = dict(quote=inputs[0], terms=inputs[1])
    # Missing sources deliberately replace every prior mark, not just successful keys.
    updated, reference = runtime.account.append(
        operation="MARK",
        data=dict(
            marks=marks,
            mark_evidence=dict(
                protocol_id=PROTOCOL,
                market_root=str(runtime.market_root),
                checked_at=journal.now().isoformat(),
                positions=evidence,
                execution_admitted=False,
            ),
        ),
    )
    at = journal.now()  # Includes observation + durable publication delay, never backdated.
    views = {arm: portfolio.view(updated, arm, at) for arm in portfolio.execution.MODEL_SHA}
    return dict(
        protocol_id=PROTOCOL,
        state="OBSERVED_PORTFOLIO_NOT_DAILY_SNAPSHOT",
        sequence=updated["sequence"],
        ledger_reference=reference,
        observed_at=at.isoformat(),
        arms=views,
        source_status=evidence,
        execution_admitted=False,
    )
