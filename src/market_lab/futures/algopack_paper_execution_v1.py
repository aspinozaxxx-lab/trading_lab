"""Pure fixed prospective paper execution; caller owes sealed source and durable ledger."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from market_lab.futures import algopack_paper_journal_v1 as journal
from market_lab.futures.algopack_paper_alignment_v1 import ASSETS, MOSCOW, utc
from market_lab.futures.algopack_paper_inference_v1 import MODEL_SHA, TRAINED_AT, sha

PROTOCOL = "algopack_paper_execution_v1"
INITIAL_CAPITAL_RUB = 1_000_000.0  # Virtual account per arm; not the user's capital.
BROKER_FEE_RUB = 3.0  # Explicit scenario assumption per contract per side, NOT a known tariff.
NOTIONAL_FRACTION = 0.25
MARGIN_FRACTION = 0.10
DEPTH_FRACTION = 0.10
EDGE_COST_MULTIPLE = 2.0
MAX_QUOTE_AGE = timedelta(seconds=5)
MAX_TERMS_AGE = timedelta(seconds=30)
MAX_FILL_DELAY = timedelta(seconds=30)
SLIPPAGE_TICKS = 1


def number(value: float, *, zero: bool = False) -> None:
    if (
        type(value) not in (float, int)
        or not math.isfinite(value)
        or (value < 0 if zero else value <= 0)
    ):
        raise ValueError("invalid finite monetary/price value")


@dataclass(frozen=True)
class Terms:
    asset: str
    secid: str
    minstep: float
    step_rub: float
    margin_rub: float
    exchange_fee_rub: float | None
    expiration_day: date
    observed_at: datetime
    source_sha256: str

    def __post_init__(self):
        if self.asset not in ASSETS or not self.secid or type(self.expiration_day) is not date:
            raise ValueError("invalid contract terms identity")
        for value in (self.minstep, self.step_rub, self.margin_rub):
            number(value)
        if self.exchange_fee_rub is not None:
            number(self.exchange_fee_rub, zero=True)
        utc(self.observed_at)
        sha(self.source_sha256)


@dataclass(frozen=True)
class Quote:
    asset: str
    secid: str
    bid: float
    ask: float
    bid_quantity: int
    ask_quantity: int
    exchange_at: datetime
    request_started_at: datetime
    observed_at: datetime
    source_sha256: str
    exchange_date_verified: bool

    def __post_init__(self):
        if self.asset not in ASSETS or not self.secid:
            raise ValueError("invalid quote identity")
        number(self.bid)
        number(self.ask)
        if self.bid >= self.ask:
            raise ValueError("locked or crossed quote")
        for quantity in (self.bid_quantity, self.ask_quantity):
            if type(quantity) is not int or quantity <= 0:
                raise ValueError("invalid visible capacity")
        for stamp in (self.exchange_at, self.request_started_at, self.observed_at):
            utc(stamp)
        sha(self.source_sha256)
        if type(self.exchange_date_verified) is not bool:
            raise ValueError("date verification must be explicit")


@dataclass(frozen=True)
class Session:
    start: datetime
    end: datetime
    observed_at: datetime
    source_sha256: str

    def __post_init__(self):
        if not utc(self.start) < utc(self.end):
            raise ValueError("invalid uninterrupted session")
        utc(self.observed_at)
        sha(self.source_sha256)


@dataclass(frozen=True)
class Intent:
    arm: str
    asset: str
    secid: str
    side: int
    quantity: int
    created_at: datetime
    entry_at: datetime
    exit_at: datetime
    forecast_sha256: str
    quote_sha256: str
    terms_sha256: str
    session_sha256: str
    notional_budget_rub: float
    margin_budget_rub: float

    def __post_init__(self):
        if (
            self.arm not in MODEL_SHA
            or self.asset not in ASSETS
            or not self.secid
            or type(self.side) is not int
            or self.side not in (-1, 1)
            or type(self.quantity) is not int
            or self.quantity <= 0
            or not utc(self.created_at) < utc(self.entry_at)
            or utc(self.exit_at) - utc(self.entry_at) != timedelta(minutes=60)
        ):
            raise ValueError("invalid fixed paper intent")
        for value in (
            self.forecast_sha256,
            self.quote_sha256,
            self.terms_sha256,
            self.session_sha256,
        ):
            sha(value)
        number(self.notional_budget_rub)
        number(self.margin_budget_rub)


@dataclass(frozen=True)
class Fill:
    intent: Intent
    is_exit: bool
    observed_at: datetime
    reference_mid: float
    price: float
    step_rub: float
    minstep: float
    exchange_fee_rub: float
    quote_sha256: str
    terms_sha256: str

    def __post_init__(self):
        if type(self.is_exit) is not bool:
            raise ValueError("explicit fill direction required")
        due = self.intent.exit_at if self.is_exit else self.intent.entry_at
        if not utc(due) <= utc(self.observed_at) <= utc(due) + MAX_FILL_DELAY:
            raise ValueError("fill outside fixed window")
        for value in (self.reference_mid, self.price, self.step_rub, self.minstep):
            number(value)
        number(self.exchange_fee_rub, zero=True)
        sha(self.quote_sha256)
        sha(self.terms_sha256)


def quote_status(quote: Quote, terms: Terms, at: datetime, future_start: datetime) -> str:
    now, start = utc(at), utc(future_start)
    if start <= TRAINED_AT:
        raise ValueError("future boundary must follow training")
    if (quote.asset, quote.secid) != (terms.asset, terms.secid):
        raise ValueError("quote/terms contract mismatch")
    if not quote.exchange_date_verified:
        return "UNVERIFIED_QUOTE_DATE"
    if not (
        start <= utc(quote.request_started_at) <= utc(quote.observed_at) <= now
        and start <= utc(quote.exchange_at) <= utc(quote.observed_at)
    ):
        return "INVALID_QUOTE_CLOCK"
    if now - utc(quote.exchange_at) > MAX_QUOTE_AGE or now - utc(quote.observed_at) > MAX_QUOTE_AGE:
        return "STALE_QUOTE"
    day = now.astimezone(MOSCOW).date()
    if (
        quote.exchange_at.astimezone(MOSCOW).date() != day
        or terms.observed_at.astimezone(MOSCOW).date() != day
        or terms.expiration_day <= day
        or not start <= utc(terms.observed_at) <= now
    ):
        return "UNRESOLVED_TERMS_DATE"
    if terms.exchange_fee_rub is None:
        return "UNKNOWN_EXCHANGE_FEE"
    if now - utc(terms.observed_at) > MAX_TERMS_AGE:
        return "STALE_CONTRACT_TERMS"
    for price in (quote.bid, quote.ask):
        ticks = price / terms.minstep
        if not math.isclose(ticks, round(ticks), rel_tol=0, abs_tol=1e-6):
            return "OFF_TICK_QUOTE"
    return "READY"


def make_intent(
    *,
    consumed: dict,
    asset: str,
    quote: Quote,
    terms: Terms,
    session: Session,
    arm: str,
    equity_rub: float,
    free_margin_rub: float,
    open_assets: tuple[str, ...],
    unresolved_positions: bool,
    at: datetime,
) -> tuple[str, Intent | None]:
    """One asset position per independent arm; current marked equity is supplied by ledger."""
    candidate = consumed["payload"]
    key = journal.forecast_key(candidate)
    if (
        consumed["state"] != "OBSERVED_NOT_EXECUTION_ADMITTED"
        or consumed["execution_admitted"] is not False
        or asset not in ASSETS
        or arm not in candidate["arms"]
        or consumed["kind"] != "forecast"
        or consumed["key"] != key
    ):
        raise ValueError("invalid consumed forecast")
    now = utc(at)
    observed = utc(datetime.fromisoformat(consumed["observed_at"]))
    entry = utc(datetime.fromisoformat(candidate["planned_entry_at"]))
    exit_at = utc(datetime.fromisoformat(candidate["target_exit_at"]))
    start = utc(datetime.fromisoformat(candidate["future_start"]))
    if not (
        utc(datetime.fromisoformat(candidate["completed_at"]))
        <= utc(datetime.fromisoformat(consumed["durable_payload_at"]))
        <= observed
    ):
        raise ValueError("invalid durable forecast chronology")
    sha(consumed["record_sha256"])
    if (
        type(unresolved_positions) is not bool
        or not isinstance(open_assets, tuple)
        or len(set(open_assets)) != len(open_assets)
        or any(item not in ASSETS for item in open_assets)
    ):
        raise ValueError("invalid portfolio state declaration")
    number(equity_rub)
    number(free_margin_rub, zero=True)
    if not start <= observed <= now < entry:
        return "MISSED_INTENT_DEADLINE", None
    if unresolved_positions:
        return "UNRESOLVED_POSITION_BLOCK", None
    if asset in open_assets:
        return "POSITION_ALREADY_OPEN", None
    if candidate["arms"][arm]["status"] != "READY":
        return "SLEEP_FORECAST", None
    if not (
        start <= utc(session.observed_at) <= now
        and utc(session.start) <= entry
        and exit_at + MAX_FILL_DELAY < utc(session.end)
    ):
        return "NO_UNINTERRUPTED_SESSION", None
    state = quote_status(quote, terms, now, start)
    if state != "READY":
        return state, None
    index = ASSETS.index(asset)
    if quote.asset != asset or candidate["assets"][index]["secid"] != quote.secid:
        raise ValueError("forecast/quote contract mismatch")
    prediction = candidate["arms"][arm]["prediction"][index]
    if abs(prediction) > 0.25:
        return "OUTLIER_FORECAST", None
    side = 1 if prediction > 0 else -1
    mid = (quote.bid + quote.ask) / 2
    conversion = terms.step_rub / terms.minstep
    roundtrip_cost = (
        (quote.ask - quote.bid) * conversion
        + 2 * SLIPPAGE_TICKS * terms.step_rub
        + 2 * (terms.exchange_fee_rub + BROKER_FEE_RUB)
    )
    gross = mid * abs(math.expm1(prediction)) * conversion
    if gross <= EDGE_COST_MULTIPLE * roundtrip_cost:
        return "EDGE_BELOW_COST_BUFFER", None
    budget = min(equity_rub, INITIAL_CAPITAL_RUB)
    notional_budget = budget * NOTIONAL_FRACTION
    margin_budget = min(free_margin_rub, budget * MARGIN_FRACTION)
    worst_price = quote.ask + terms.minstep
    quantity = min(
        math.floor(notional_budget / (worst_price * conversion)),
        math.floor(margin_budget / terms.margin_rub),
        math.floor(DEPTH_FRACTION * (quote.ask_quantity if side == 1 else quote.bid_quantity)),
    )
    if quantity < 1:
        return "INSUFFICIENT_BUDGET_OR_DEPTH", None
    return "PAPER_INTENT_NOT_PERSISTED", Intent(
        arm,
        asset,
        quote.secid,
        side,
        quantity,
        now,
        entry,
        exit_at,
        consumed["record_sha256"],
        quote.source_sha256,
        terms.source_sha256,
        session.source_sha256,
        notional_budget,
        margin_budget,
    )


def simulate_fill(
    intent: Intent,
    *,
    is_exit: bool,
    quote: Quote,
    terms: Terms,
    intent_durable_at: datetime,
    at: datetime,
    future_start: datetime,
) -> tuple[str, Fill | None]:
    """Conditional FOK top-of-book simulation, never an exchange execution claim."""
    now, due, durable = (
        utc(at),
        utc(intent.exit_at if is_exit else intent.entry_at),
        utc(intent_durable_at),
    )
    if not (
        intent.side in (-1, 1)
        and type(intent.quantity) is int
        and intent.quantity > 0
        and utc(intent.created_at) <= durable < utc(intent.entry_at)
    ):
        raise ValueError("invalid or late persisted intent")
    if not due <= now <= due + MAX_FILL_DELAY:
        return "EXIT_UNRESOLVED" if is_exit else "MISSED_ENTRY_WINDOW", None
    if utc(quote.request_started_at) < max(due, durable):
        return "PRE_INTENT_OR_PRE_BOUNDARY_QUOTE", None
    if (intent.asset, intent.secid) != (quote.asset, quote.secid):
        raise ValueError("fill contract differs from intent")
    state = quote_status(quote, terms, now, future_start)
    if state != "READY":
        return state, None
    direction = -intent.side if is_exit else intent.side
    depth = quote.ask_quantity if direction == 1 else quote.bid_quantity
    if intent.quantity > math.floor(depth * DEPTH_FRACTION):
        return "INSUFFICIENT_FOK_DEPTH", None
    price = (
        quote.ask if direction == 1 else quote.bid
    ) + direction * SLIPPAGE_TICKS * terms.minstep
    if price <= 0:
        return "NONPOSITIVE_STRESSED_PRICE", None
    if not is_exit and (
        intent.quantity * max(quote.ask, price) * terms.step_rub / terms.minstep
        > intent.notional_budget_rub
        or intent.quantity * terms.margin_rub > intent.margin_budget_rub
    ):
        return "BUDGET_CHANGED_BEFORE_ENTRY", None
    return "SIMULATED_FILL_NOT_PERSISTED", Fill(
        intent,
        is_exit,
        now,
        (quote.bid + quote.ask) / 2,
        price,
        terms.step_rub,
        terms.minstep,
        terms.exchange_fee_rub,
        quote.source_sha256,
        terms.source_sha256,
    )


def close_trade(entry: Fill, exit_fill: Fill) -> dict:
    if (
        entry.intent != exit_fill.intent
        or entry.is_exit
        or not exit_fill.is_exit
        or utc(entry.observed_at) >= utc(exit_fill.observed_at)
    ):
        raise ValueError("invalid paired fills")
    if (entry.minstep, entry.step_rub) != (exit_fill.minstep, exit_fill.step_rub):
        return dict(status="UNRESOLVED_CONVERSION_CHANGE", net_rub=None, execution_admitted=False)
    intent = entry.intent
    multiplier = intent.quantity * entry.step_rub / entry.minstep
    gross_mid = intent.side * (exit_fill.reference_mid - entry.reference_mid) * multiplier
    gross_fill = intent.side * (exit_fill.price - entry.price) * multiplier
    friction = gross_mid - gross_fill
    fees = intent.quantity * (
        entry.exchange_fee_rub + exit_fill.exchange_fee_rub + 2 * BROKER_FEE_RUB
    )
    if friction < -1e-8:
        raise ValueError("simulated crossing friction cannot be negative")
    return dict(
        status="CONDITIONAL_PAPER_ROUNDTRIP",
        gross_mid_rub=gross_mid,
        crossing_slippage_rub=friction,
        fees_rub=fees,
        net_rub={"1x": gross_mid - friction - fees, "2x": gross_mid - 2 * (friction + fees)},
        quantity=intent.quantity,
        broker_fee_assumption_rub=BROKER_FEE_RUB,
        real_broker_fee_verified=False,
        execution_admitted=False,
    )
