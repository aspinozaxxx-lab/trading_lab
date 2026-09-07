"""Offline source-bound replay of paper decisions/fills; not independent forecast validation."""

from pathlib import Path

from market_lab.futures import algopack_paper_execution_bridge_v1 as bridge
from market_lab.futures import algopack_paper_mark_refresh_v1 as marks
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE

portfolio, journal, source, execution = (
    bridge.portfolio,
    bridge.journal,
    bridge.source,
    bridge.execution,
)
PROTOCOL = "algopack_paper_execution_audit_v1"


def ready(activation):
    marks.ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    name = "src/market_lab/futures/algopack_paper_execution_audit_v1.py"
    if files.get(name) != journal.sha(Path(__file__).read_bytes()):
        raise ValueError("execution audit absent from complete activation")


def observation(root, ref, activation, at):
    record = journal.observe(
        root,
        kind=ref["kind"],
        key=ref["key"],
        record_sha256=ref["record_sha256"],
        future_start=activation.future_start,
    )
    original = source._stamp(ref["observed_at"])
    if not activation.future_start <= source._stamp(record["durable_payload_at"]) <= original <= at:
        raise ValueError("original source observation is not supported by durable chronology")
    if ref["kind"] == "source":
        replay = source.observe(
            root, ref, activation
        )  # Actual audit clock and complete raw replay.
        # Reconstruct historical inputs from saved evidence, NOT a new backdated observation.
        replay["available_at"] = original.isoformat()
        replay["source_observation"] = dict(ref)
        replay["offline_reconstruction"] = True
        return replay
    if ref["kind"] != "forecast" or journal.forecast_key(record["payload"]) != ref["key"]:
        raise ValueError("invalid forecast observation")
    record["observed_at"] = original.isoformat()
    record["state"] = "OBSERVED_NOT_EXECUTION_ADMITTED"
    return record


def same(actual, expected):
    if journal.encode(portfolio.wire(actual)) != journal.encode(portfolio.wire(expected)):
        raise ValueError("saved economic value differs from source-derived replay")


def verify_event(before, event, root, activation):
    """Check economic inputs before the parent reducer accepts the state transition."""
    at, data, operation = source._stamp(event["at"]), event["data"], event["operation"]
    evidence = data["mark_evidence" if operation == "MARK" else "execution_evidence"]
    checked_at = source._stamp(evidence["checked_at"])
    if (
        evidence["market_root"] != str(root)
        or evidence["execution_admitted"] is not False
        or not activation.future_start <= checked_at <= at
    ):
        raise ValueError("economic evidence scope/clock mismatch")
    at = checked_at
    if operation == "MARK":
        evidence = data["mark_evidence"]
        if evidence["protocol_id"] != marks.PROTOCOL:
            raise ValueError("unknown mark evidence protocol")
        opened = {key for key, row in before["positions"].items() if row["entry"] is not None}
        if set(data["marks"]) != opened or set(evidence["positions"]) != opened:
            raise ValueError("incomplete all-position mark evidence")
        for key, mark in data["marks"].items():
            item = evidence["positions"][key]
            if mark is None:
                if item["status"] not in {
                    "MISSING_REFERENCE",
                    "SOURCE_REPLAY_FAILED",
                    "UNAVAILABLE_QUOTE",
                }:
                    raise ValueError("missing mark without explicit failure mask")
                if item["status"] == "UNAVAILABLE_QUOTE":
                    inputs = source.quote_inputs(
                        observation(root, item["observation"], activation, at)
                    )
                    if inputs is not None:
                        raise ValueError("available quote mislabeled as unavailable")
            else:
                if item["status"] != "OBSERVED_CANDIDATE":
                    raise ValueError("positive mark without observed source")
                inputs = source.quote_inputs(observation(root, item["observation"], activation, at))
                if inputs is None:
                    raise ValueError("saved mark has no usable source")
                same(mark, dict(quote=inputs[0], terms=inputs[1]))
    else:
        evidence = data["execution_evidence"]
        if evidence["protocol_id"] != bridge.PROTOCOL:
            raise ValueError("unknown execution evidence protocol")
        refs = evidence["observations"]
        if operation == "RESERVE":
            intent = portfolio.decode(execution.Intent, data["intent"])
            if intent.created_at > checked_at:
                raise ValueError("intent created after evidence check")
            if len(refs) != 3 or refs[0]["kind"] != "forecast":
                raise ValueError("reservation requires forecast, quote and calendar evidence")
            consumed, quote_record, calendar = [
                observation(root, ref, activation, intent.created_at) for ref in refs
            ]
            inputs = source.quote_inputs(quote_record)
            if inputs is None:
                raise ValueError("reservation without source quote")
            session = source.session_input(
                calendar, secid=intent.secid, entry_at=intent.entry_at, exit_at=intent.exit_at
            )
            value = portfolio.view(before, intent.arm, intent.created_at)
            if session is None or value["status"] != "VALUED" or value["equity_rub"]["1x"] <= 0:
                raise ValueError("reservation violates calendar or portfolio admission")
            _, expected = execution.make_intent(
                consumed=consumed,
                asset=intent.asset,
                arm=intent.arm,
                quote=inputs[0],
                terms=inputs[1],
                session=session,
                equity_rub=value["equity_rub"]["1x"],
                free_margin_rub=value["free_margin_rub"],
                open_assets=tuple(value["open_assets"]),
                unresolved_positions=False,
                at=intent.created_at,
            )
            same(intent, expected)
        elif operation in {"ENTRY", "EXIT"}:
            if len(refs) != 1:
                raise ValueError("fill requires one exact quote source")
            fill = portfolio.decode(execution.Fill, data["fill"])
            if fill.observed_at > checked_at:
                raise ValueError("fill observed after evidence check")
            row = before["positions"][data["position"]]
            intent = portfolio.decode(execution.Intent, row["intent"])
            inputs = source.quote_inputs(observation(root, refs[0], activation, fill.observed_at))
            if inputs is None:
                raise ValueError("fill without source quote")
            _, expected = execution.simulate_fill(
                intent,
                is_exit=operation == "EXIT",
                quote=inputs[0],
                terms=inputs[1],
                intent_durable_at=source._stamp(row["intent_durable_at"]),
                at=fill.observed_at,
                future_start=activation.future_start,
            )
            same(fill, expected)
        elif operation in {"CANCEL", "UNRESOLVED"}:
            row = before["positions"][data["position"]]
            is_exit = operation == "UNRESOLVED"
            due = source._stamp(row["intent"]["exit_at" if is_exit else "entry_at"])
            if (
                refs
                or (row["entry"] is not None) != is_exit
                or at <= due + execution.MAX_FILL_DELAY
                or data["reason"] != ("MISSED_EXIT_WINDOW" if is_exit else "MISSED_ENTRY_WINDOW")
            ):
                raise ValueError("unsupported cancellation/unresolved decision")
        else:
            raise ValueError("unknown economic operation")
    if (
        evidence["market_root"] != str(root)
        or evidence["execution_admitted"] is not False
        or not activation.future_start <= source._stamp(evidence["checked_at"]) <= at
    ):
        raise ValueError("economic evidence scope/clock mismatch")


def audit(account, root: Path):
    if not isinstance(account, bridge.anchors.AnchoredPortfolio):
        raise ValueError("verified anchored account required")
    activation = account.activation
    ready(activation)
    journal._ordinary(root, directory=True)
    expected = account.snapshot()
    state = portfolio.initial(activation.future_start)
    for index in range(1, expected["sequence"] + 1):
        record = bridge.anchors.read_event(account.ledger, f"portfolio_{index:08d}", activation)
        verify_event(state, record["payload"], root, activation)
        state = portfolio.apply(
            state,
            record["payload"],
            durable_at=source._stamp(record["durable_payload_at"]),
            record_sha256=record["record_sha256"],
        )
    same(state, expected)
    same(
        portfolio.recover(account.ledger, activation), expected
    )  # Detect a concurrently advanced tail.
    return dict(
        protocol_id=PROTOCOL,
        status="EXECUTION_BINDINGS_REPLAYED",
        events=state["sequence"],
        ledger_sha256=state["last_record_sha256"],
        audited_at=journal.now().isoformat(),
        forecast_recomputed=False,
        execution_admitted=False,
        target_income_verified=False,
    )
