"""Event-sourced paper portfolio; no source selection, orders, or implicit fill admission."""

from __future__ import annotations

import copy
import math
import os
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path

from market_lab.futures import algopack_paper_execution_source_v1 as source
from market_lab.futures import algopack_paper_execution_v1 as execution
from market_lab.futures import algopack_paper_journal_v1 as journal
from market_lab.futures.algopack_paper_activation_v1 import BUNDLE, VerifiedActivation
from market_lab.futures.algopack_paper_alignment_v1 import utc

PROTOCOL = "algopack_paper_portfolio_v1"
ZERO = "0" * 64


def wire(value):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(item) for item in value]
    return value


def decode(kind, value):
    result = dict(value)
    for key in (
        "created_at",
        "entry_at",
        "exit_at",
        "observed_at",
        "exchange_at",
        "request_started_at",
    ):
        if key in result:
            result[key] = source._stamp(result[key])
    if "expiration_day" in result:
        result["expiration_day"] = date.fromisoformat(result["expiration_day"])
    if kind is execution.Fill:
        result["intent"] = decode(execution.Intent, result["intent"])
    return kind(**result)


def initial(future_start: datetime) -> dict:
    journal._boundary(future_start, future_start)
    return dict(
        sequence=0,
        last_record_sha256=ZERO,
        last_at=utc(future_start).isoformat(),
        future_start=utc(future_start).isoformat(),
        positions={},
        marks={},
        seen=[],
        cash={
            arm: {cost: execution.INITIAL_CAPITAL_RUB for cost in ("1x", "2x")}
            for arm in execution.MODEL_SHA
        },
        closed_trades=0,
    )


def position_key(intent: execution.Intent) -> str:
    return intent.arm + "_" + intent.asset


def intent_key(intent: execution.Intent) -> str:
    return position_key(intent) + "_" + utc(intent.entry_at).strftime("%Y%m%dT%H%M%SZ")


def view(state: dict, arm: str, at: datetime) -> dict:
    """Liquidation-value marks with exit costs; missing prices never become zero return."""
    if arm not in execution.MODEL_SHA or utc(at) < source._stamp(state["last_at"]):
        raise ValueError("invalid portfolio valuation clock/arm")
    equity = dict(state["cash"][arm])
    reserved_notional = reserved_margin = 0.0
    unknown, blocked, assets = [], [], []
    start = source._stamp(state["future_start"])
    for key, position in state["positions"].items():
        intent = decode(execution.Intent, position["intent"])
        if intent.arm != arm:
            continue
        assets.append(intent.asset)
        if position["status"] == "UNRESOLVED":
            blocked.append(key)
        if position["entry"] is None:
            reserved_notional += intent.notional_budget_rub
            reserved_margin += intent.margin_budget_rub
            continue
        entry = decode(execution.Fill, position["entry"])
        mark = state["marks"].get(key)
        if mark is None:
            unknown.append(key)
            continue
        quote, terms = (
            decode(execution.Quote, mark["quote"]),
            decode(execution.Terms, mark["terms"]),
        )
        if (
            (quote.asset, quote.secid) != (intent.asset, intent.secid)
            or execution.quote_status(quote, terms, at, start) != "READY"
            or quote.observed_at < entry.observed_at
            or (terms.minstep, terms.step_rub) != (entry.minstep, entry.step_rub)
            or intent.quantity
            > math.floor(
                execution.DEPTH_FRACTION
                * (quote.bid_quantity if intent.side == 1 else quote.ask_quantity)
            )
        ):
            unknown.append(key)
            continue
        reserved_notional += intent.quantity * quote.ask * terms.step_rub / terms.minstep
        reserved_margin += intent.quantity * terms.margin_rub
        mid = (quote.bid + quote.ask) / 2
        exit_price = (
            (quote.bid - terms.minstep) if intent.side == 1 else (quote.ask + terms.minstep)
        )
        if exit_price <= 0:
            unknown.append(key)
            continue
        multiplier = intent.quantity * terms.step_rub / terms.minstep
        gross = intent.side * (mid - entry.reference_mid) * multiplier
        filled = intent.side * (exit_price - entry.price) * multiplier
        friction = gross - filled
        fees = intent.quantity * (
            entry.exchange_fee_rub + terms.exchange_fee_rub + 2 * execution.BROKER_FEE_RUB
        )
        equity["1x"] += gross - friction - fees
        equity["2x"] += gross - 2 * (friction + fees)
    if unknown:
        return dict(
            status="UNRESOLVED_MARK",
            equity_rub=None,
            free_margin_rub=None,
            free_notional_rub=None,
            open_assets=tuple(assets),
            unresolved=unknown + blocked,
        )
    basis = max(0.0, min(equity["1x"], execution.INITIAL_CAPITAL_RUB))
    return dict(
        status="UNRESOLVED_POSITION" if blocked else "VALUED",
        equity_rub=equity,
        free_margin_rub=max(0.0, basis * 0.4 - reserved_margin),
        free_notional_rub=max(0.0, basis - reserved_notional),
        open_assets=tuple(assets),
        unresolved=blocked,
    )


def apply(state: dict, event: dict, *, durable_at: datetime, record_sha256: str) -> dict:
    """Deterministic transition replay. Runtime still must replay each fill's source evidence."""
    execution.sha(record_sha256)
    at = source._stamp(event["at"])
    if (
        set(event)
        != {"protocol_id", "sequence", "previous_record_sha256", "at", "operation", "data"}
        or event["protocol_id"] != PROTOCOL
        or type(event["sequence"]) is not int
        or event["sequence"] != state["sequence"] + 1
        or event["previous_record_sha256"] != state["last_record_sha256"]
        or not source._stamp(state["last_at"]) <= at <= utc(durable_at)
    ):
        raise ValueError("portfolio event chain/clock mismatch")
    result = copy.deepcopy(state)
    operation, data = event["operation"], event["data"]
    if operation == "RESERVE":
        intent = decode(execution.Intent, data["intent"])
        key, unique = position_key(intent), intent_key(intent)
        valuation = view(state, intent.arm, at)
        if (
            key in state["positions"]
            or unique in state["seen"]
            or not source._stamp(state["future_start"]) <= intent.created_at <= at < intent.entry_at
            or valuation["status"] != "VALUED"
            or valuation["equity_rub"]["1x"] <= 0
        ):
            raise ValueError("duplicate, stale or unresolved reservation")
        basis = min(valuation["equity_rub"]["1x"], execution.INITIAL_CAPITAL_RUB)
        if intent.notional_budget_rub > min(
            basis * execution.NOTIONAL_FRACTION, valuation["free_notional_rub"]
        ) or intent.margin_budget_rub > min(
            basis * execution.MARGIN_FRACTION, valuation["free_margin_rub"]
        ):
            raise ValueError("portfolio aggregate budget exceeded")
        result["positions"][key] = dict(
            intent=wire(intent),
            intent_durable_at=utc(durable_at).isoformat(),
            entry=None,
            status="PENDING",
            reason=None,
        )
        result["seen"].append(unique)
    elif operation == "MARK":
        marks = data["marks"]
        if not isinstance(marks, dict) or not set(marks) <= set(state["positions"]):
            raise ValueError("mark for nonexistent portfolio position")
        for mark in marks.values():
            if mark is not None:
                quote, terms = (
                    decode(execution.Quote, mark["quote"]),
                    decode(execution.Terms, mark["terms"]),
                )
                if quote.observed_at > at or terms.observed_at > at:
                    raise ValueError("future portfolio mark")
        result["marks"] = copy.deepcopy(marks)  # No old quote forward fill.
    else:
        key = data["position"]
        if key not in result["positions"]:
            raise ValueError("transition without reserved position")
        position = result["positions"][key]
        intent = decode(execution.Intent, position["intent"])
        if operation in ("ENTRY", "EXIT"):
            fill = decode(execution.Fill, data["fill"])
            if (
                fill.intent != intent
                or fill.observed_at > at
                or source._stamp(position["intent_durable_at"]) >= intent.entry_at
            ):
                raise ValueError("fill identity/intent publication mismatch")
            if operation == "ENTRY":
                if position["entry"] is not None or fill.is_exit:
                    raise ValueError("duplicate or invalid entry")
                if (
                    intent.quantity * fill.price * fill.step_rub / fill.minstep
                    > intent.notional_budget_rub
                ):
                    raise ValueError("entry exceeds reserved notional")
                position.update(entry=wire(fill), status="OPEN")
                result["marks"].pop(key, None)
            else:
                if position["entry"] is None or not fill.is_exit:
                    raise ValueError("exit without entry")
                closed = execution.close_trade(decode(execution.Fill, position["entry"]), fill)
                if closed["net_rub"] is None:
                    position.update(status="UNRESOLVED", reason=closed["status"])
                else:
                    for cost, net in closed["net_rub"].items():
                        result["cash"][intent.arm][cost] += net
                    result["closed_trades"] += 1
                    del result["positions"][key]
                    result["marks"].pop(key, None)
        elif operation == "CANCEL":
            if (
                position["entry"] is not None
                or not isinstance(data["reason"], str)
                or not data["reason"]
            ):
                raise ValueError("cannot cancel an open position")
            del result["positions"][key]
            result["marks"].pop(key, None)
        elif operation == "UNRESOLVED":
            if (
                position["entry"] is None
                or not isinstance(data["reason"], str)
                or not data["reason"]
            ):
                raise ValueError("invalid unresolved position")
            position.update(status="UNRESOLVED", reason=data["reason"])
        else:
            raise ValueError("unknown portfolio operation")
    result.update(
        sequence=event["sequence"],
        last_record_sha256=record_sha256,
        last_at=utc(durable_at).isoformat(),
    )
    journal.encode(result)
    return result


def _ready(activation: VerifiedActivation):
    source.ready(activation)
    files = journal._decode((activation.project / BUNDLE).read_bytes())["files"]
    if files.get("src/market_lab/futures/algopack_paper_portfolio_v1.py") != journal.sha(
        Path(__file__).read_bytes()
    ):
        raise ValueError("portfolio absent from complete activation")


def recover(
    root: Path, activation: VerifiedActivation, *, expected_tail: dict | None = None
) -> dict:
    """Dedicated root; incomplete events fail closed, external tail can detect truncation."""
    _ready(activation)
    journal._ordinary(root, directory=True)
    state = initial(activation.future_start)
    parent = root / "source"
    if parent.exists():
        journal._ordinary(parent, directory=True)
        names = sorted(item.name for item in parent.iterdir())
        for index, name in enumerate(names, 1):
            if name != f"portfolio_{index:08d}":
                raise ValueError("portfolio sequence gap or foreign event")
            marker = journal._decode(journal._read(parent / name / "COMMITTED.json"))
            record = journal.observe(
                root,
                kind="source",
                key=name,
                record_sha256=marker["record_sha256"],
                future_start=activation.future_start,
            )
            state = apply(
                state,
                record["payload"],
                durable_at=source._stamp(record["durable_payload_at"]),
                record_sha256=record["record_sha256"],
            )
            if (
                expected_tail
                and index == expected_tail["sequence"]
                and state["last_record_sha256"] != expected_tail["record_sha256"]
            ):
                raise ValueError("portfolio external tail mismatch")
    if expected_tail and state["sequence"] < expected_tail["sequence"]:
        raise ValueError("portfolio truncated before external tail")
    return state


def append(
    root: Path,
    activation: VerifiedActivation,
    *,
    operation: str,
    data: dict,
    expected_tail: dict | None = None,
) -> tuple[dict, dict]:
    """Serialize competing portfolio writers; journal itself uses its independent inner lock."""
    _ready(activation)
    if os.name != "posix":
        raise ValueError("portfolio persistence requires Linux")
    import fcntl

    journal._ordinary(root, directory=True)
    lock = root / ".portfolio.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        journal._ordinary(lock)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = recover(root, activation, expected_tail=expected_tail)
        at = journal.now()
        event = dict(
            protocol_id=PROTOCOL,
            sequence=state["sequence"] + 1,
            previous_record_sha256=state["last_record_sha256"],
            at=at.isoformat(),
            operation=operation,
            data=wire(data),
        )
        apply(state, event, durable_at=at, record_sha256=ZERO)  # Validate before reservation.
        reference = journal.publish(
            root,
            kind="source",
            key=f"portfolio_{event['sequence']:08d}",
            future_start=activation.future_start,
            payload=event,
        )
        state = apply(
            state,
            event,
            durable_at=source._stamp(reference["durable_payload_at"]),
            record_sha256=reference["record_sha256"],
        )
        return state, reference
    finally:
        os.close(fd)
