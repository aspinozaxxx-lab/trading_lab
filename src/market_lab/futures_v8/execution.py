"""Causal'noe completed-window POV ispolnenie futures-v8 bez PnL."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from math import isfinite
from typing import Protocol
from zoneinfo import ZoneInfo

BAR_INTERVAL = timedelta(minutes=10)
DECISION_TIME = time(18, 50)
FIRST_CANDLE_TIME = time(19, 0)
CAPACITY_BPS = 100
BASIS_POINTS = 10_000
MINIMUM_ORDER_LATENCY = BAR_INTERVAL
DEFAULT_ORDER_LATENCY = BAR_INTERVAL
MOSCOW_TIMEZONE = ZoneInfo("Europe/Moscow")
RESEARCH_ONLY_NOT_QUEUE_EXACT = "research_only_not_queue_exact"
FUTURES_V8_EXECUTION_VERSION = "futures-v8-completed-window-pov-v2"
PRIMARY_ORDER_PRICE_POLICY = (
    "market_order_research_fill_at_adverse_high_or_low_of_19_20_19_30_window"
)
PAIRED_ROLL_POLICY = "paired_research_fill_broker_atomicity_not_proven"
DIAGNOSTIC_LIMIT_ORDER_ONLY = "diagnostic_limit_order_not_primary_protocol"


class ExecutionStatus(StrEnum):
    """Yavnye final'nye sostoyaniya bez predpolagaemogo venue fill."""

    FILLED = "filled"
    PARTIAL_CARRY = "partial_carry"
    CARRIED = "carried"
    SKIPPED_LIMIT = "skipped_limit"


@dataclass(frozen=True, slots=True)
class CausalPovExecutionPolicy:
    """Fiksiruet explicit latency i 1-percent completed-window POV limit."""

    order_latency: timedelta = DEFAULT_ORDER_LATENCY
    participation_bps: int = CAPACITY_BPS

    def __post_init__(self) -> None:
        """Zapreshchaet drift ot sealed 10m latency i 1-percent policy."""
        if not isinstance(self.order_latency, timedelta):
            raise TypeError("order_latency dolzhen byt' timedelta")
        if self.order_latency != DEFAULT_ORDER_LATENCY:
            raise ValueError("primary v8 order_latency dolzhen byt' rovno odin polnyi 10m bar")
        if isinstance(self.participation_bps, bool) or not isinstance(self.participation_bps, int):
            raise TypeError("participation_bps dolzhen byt' int")
        if self.participation_bps != CAPACITY_BPS:
            raise ValueError("v8 policy fiksiruet participation rovno v 1 percent")


class SealedExecutionProtocol(Protocol):
    """Minimal'nyi typed view sealed execution sekcii config v8."""

    execution_version: str
    decision_timezone: str
    decision_local_time: str
    capacity_observation_window_open_time: str
    capacity_observation_window_close_time: str
    mandatory_order_latency_minutes: int
    order_live_local_time: str
    execution_window_open_time: str
    execution_window_close_time: str
    max_observed_bar_participation_bps: int
    max_realized_execution_window_participation_bps: int
    primary_order_price_policy: str
    adverse_hl_ledger: str
    provenance: str
    paired_roll_policy: str


def assert_causal_v8_policy_matches_protocol(
    protocol: SealedExecutionProtocol,
    policy: CausalPovExecutionPolicy | None = None,
) -> None:
    """Fail-closed svyazyvaet runtime executor s sealed YAML execution v2."""
    resolved = policy or CausalPovExecutionPolicy()
    expected: dict[str, object] = {
        "execution_version": FUTURES_V8_EXECUTION_VERSION,
        "decision_timezone": "Europe/Moscow",
        "decision_local_time": "18:50:00",
        "capacity_observation_window_open_time": "19:00:00",
        "capacity_observation_window_close_time": "19:10:00",
        "mandatory_order_latency_minutes": int(resolved.order_latency.total_seconds() // 60),
        "order_live_local_time": "19:20:00",
        "execution_window_open_time": "19:20:00",
        "execution_window_close_time": "19:30:00",
        "max_observed_bar_participation_bps": resolved.participation_bps,
        "max_realized_execution_window_participation_bps": resolved.participation_bps,
        "primary_order_price_policy": PRIMARY_ORDER_PRICE_POLICY,
        "adverse_hl_ledger": "buy_high_sell_low_of_factual_execution_window",
        "provenance": RESEARCH_ONLY_NOT_QUEUE_EXACT,
        "paired_roll_policy": PAIRED_ROLL_POLICY,
    }
    for field_name, expected_value in expected.items():
        actual_value = getattr(protocol, field_name, None)
        if actual_value != expected_value:
            raise ValueError(
                f"Execution protocol drift: {field_name}={actual_value!r}, "
                f"expected {expected_value!r}"
            )


def _require_contract_id(value: str, label: str) -> str:
    """Proveryaet kanonicheskii ne-pustoi contract identifier."""
    if not isinstance(value, str):
        raise TypeError(f"{label} dolzhen byt' strokoj")
    normalized = value.strip()
    if not normalized or any(character.isspace() for character in normalized):
        raise ValueError(f"{label} dolzhen byt' nepustym contract_id bez probelov")
    return normalized


def _require_aware_timestamp(value: datetime, label: str) -> datetime:
    """Privodit timestamp k UTC i zapreshchaet naivnoe vremya."""
    if not isinstance(value, datetime):
        raise TypeError(f"{label} dolzhen byt' datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} dolzhen imet' timezone")
    return value.astimezone(UTC)


def _require_finite_positive(value: float, label: str) -> float:
    """Proveryaet yavnyi finite price dlya limit ili factual OHLC."""
    if isinstance(value, bool):
        raise TypeError(f"{label} ne mozhet byt' bool")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{label} dolzhen byt' chislom") from exc
    if not isfinite(numeric) or numeric <= 0.0:
        raise ValueError(f"{label} dolzhen byt' finite i > 0")
    return numeric


def _require_nonzero_integer(value: int, label: str) -> int:
    """Trebuet celyi nenulevoi razmer ordera v kontraktah."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} dolzhen byt' int")
    if value == 0:
        raise ValueError(f"{label} ne mozhet byt' ravnym nulyu")
    return value


def _require_positive_integer(value: int, label: str) -> int:
    """Trebuet celyi polozhitel'nyi razmer paired rolla."""
    checked = _require_nonzero_integer(value, label)
    if checked < 0:
        raise ValueError(f"{label} dolzhen byt' > 0")
    return checked


def _require_nonnegative_integer(value: int, label: str) -> int:
    """Trebuet stable nonnegative prioritet allocation."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} dolzhen byt' int")
    if value < 0:
        raise ValueError(f"{label} ne mozhet byt' otricatel'nym")
    return value


def _require_decision_time(value: datetime) -> datetime:
    """Fiksiruet signal D18:50 Moscow do perevoda momenta v UTC."""
    if not isinstance(value, datetime):
        raise TypeError("decision_at dolzhen byt' datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decision_at dolzhen imet' timezone")
    local = value.astimezone(MOSCOW_TIMEZONE)
    if local.time().replace(tzinfo=None) != DECISION_TIME:
        raise ValueError("Causal v8 policy prinimaet signal tol'ko v 18:50 Moscow")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class TenMinuteCandle:
    """Factual 10m OHLCV candle odnogo kontrakta bez zapolneniya propuskov."""

    contract_id: str
    opened_at: datetime
    closed_at: datetime
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    volume: int | None

    def __post_init__(self) -> None:
        """Proveryaet exact 10m granicy i dostupnye raw OHLCV polya."""
        contract_id = _require_contract_id(self.contract_id, "contract_id")
        opened_at = _require_aware_timestamp(self.opened_at, "opened_at")
        closed_at = _require_aware_timestamp(self.closed_at, "closed_at")
        if closed_at - opened_at != BAR_INTERVAL:
            raise ValueError("Candle dolzhen imet' rovno 10 minut")
        prices: dict[str, float | None] = {}
        for label, value in (
            ("open_price", self.open_price),
            ("high_price", self.high_price),
            ("low_price", self.low_price),
            ("close_price", self.close_price),
        ):
            prices[label] = _require_finite_positive(value, label) if value is not None else None
        high = prices["high_price"]
        low = prices["low_price"]
        if high is not None and low is not None and high < low:
            raise ValueError("high_price ne mozhet byt' men'she low_price")
        if all(value is not None for value in prices.values()):
            open_price = prices["open_price"]
            close_price = prices["close_price"]
            if high is None or low is None or open_price is None or close_price is None:
                raise RuntimeError("Polnyi OHLC neozhidanno nedostupen")
            if high < max(open_price, close_price) or low > min(open_price, close_price):
                raise ValueError("Factual OHLC narushaet high/low invariant")
        if self.volume is not None:
            if isinstance(self.volume, bool) or not isinstance(self.volume, int):
                raise TypeError("volume dolzhen byt' int ili None")
            if self.volume < 0:
                raise ValueError("volume ne mozhet byt' otricatel'nym")
        object.__setattr__(self, "contract_id", contract_id)
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "closed_at", closed_at)
        for label, value in prices.items():
            object.__setattr__(self, label, value)

    @property
    def has_factual_ohlc(self) -> bool:
        """Vozvrashchaet True tol'ko dlya polnogo factual OHLC."""
        return all(
            value is not None
            for value in (self.open_price, self.high_price, self.low_price, self.close_price)
        )


@dataclass(frozen=True, slots=True)
class PredeclaredMarketOrder:
    """Primary market order, polnost'yu zadannyi signalom D18:50."""

    order_id: str
    contract_id: str
    decision_at: datetime
    signed_contracts: int
    allocation_priority: int = 0

    def __post_init__(self) -> None:
        """Fiksiruet direction, integer size i deterministic prioritet."""
        object.__setattr__(self, "order_id", _require_contract_id(self.order_id, "order_id"))
        object.__setattr__(
            self, "contract_id", _require_contract_id(self.contract_id, "contract_id")
        )
        object.__setattr__(self, "decision_at", _require_decision_time(self.decision_at))
        object.__setattr__(
            self,
            "signed_contracts",
            _require_nonzero_integer(self.signed_contracts, "signed_contracts"),
        )
        object.__setattr__(
            self,
            "allocation_priority",
            _require_nonnegative_integer(self.allocation_priority, "allocation_priority"),
        )


@dataclass(frozen=True, slots=True)
class PredeclaredPairedMarketRollOrder:
    """Primary paired market roll signed exposure bez broker atomicity claim.

    ``contracts`` -- eto signed exposure ``q`` starogo kontrakta: dlya long
    ``q > 0``, dlya short ``q < 0``. Atomarnye research-legi vsegda ravny
    ``old=-q`` i ``new=+q``.
    """

    order_id: str
    old_contract_id: str
    new_contract_id: str
    decision_at: datetime
    contracts: int
    allocation_priority: int = 0

    def __post_init__(self) -> None:
        """Fiksiruet dve market-legi i odin obshchii signal D18:50."""
        order_id = _require_contract_id(self.order_id, "order_id")
        old_contract_id = _require_contract_id(self.old_contract_id, "old_contract_id")
        new_contract_id = _require_contract_id(self.new_contract_id, "new_contract_id")
        if old_contract_id == new_contract_id:
            raise ValueError("Paired roll trebuet dva raznyh contract_id")
        object.__setattr__(self, "order_id", order_id)
        object.__setattr__(self, "old_contract_id", old_contract_id)
        object.__setattr__(self, "new_contract_id", new_contract_id)
        object.__setattr__(self, "decision_at", _require_decision_time(self.decision_at))
        object.__setattr__(
            self,
            "contracts",
            _require_nonzero_integer(self.contracts, "contracts"),
        )
        object.__setattr__(
            self,
            "allocation_priority",
            _require_nonnegative_integer(self.allocation_priority, "allocation_priority"),
        )

    @property
    def signed_contracts(self) -> int:
        """Vozvrashchaet canonical signed exposure ``q`` dlya rolla."""
        return self.contracts


@dataclass(frozen=True, slots=True)
class PredeclaredLimitOrder:
    """Diagnostic limit-or-skip order, ne yavlyayushchiisya primary v8 policy."""

    order_id: str
    contract_id: str
    decision_at: datetime
    signed_contracts: int
    limit_price: float
    allocation_priority: int = 0

    def __post_init__(self) -> None:
        """Fiksiruet direction, integer size, limit i deterministic prioritet."""
        object.__setattr__(self, "order_id", _require_contract_id(self.order_id, "order_id"))
        object.__setattr__(
            self, "contract_id", _require_contract_id(self.contract_id, "contract_id")
        )
        object.__setattr__(self, "decision_at", _require_decision_time(self.decision_at))
        object.__setattr__(
            self,
            "signed_contracts",
            _require_nonzero_integer(self.signed_contracts, "signed_contracts"),
        )
        object.__setattr__(
            self,
            "limit_price",
            _require_finite_positive(self.limit_price, "limit_price"),
        )
        object.__setattr__(
            self,
            "allocation_priority",
            _require_nonnegative_integer(self.allocation_priority, "allocation_priority"),
        )


@dataclass(frozen=True, slots=True)
class PredeclaredRollOrder:
    """Diagnostic paired limit roll, ne yavlyayushchiisya primary v8 policy."""

    order_id: str
    old_contract_id: str
    new_contract_id: str
    decision_at: datetime
    contracts: int
    exit_limit_price: float
    entry_limit_price: float
    allocation_priority: int = 0

    def __post_init__(self) -> None:
        """Fiksiruet obe legi, oba limit'a i prioritet v odin signal."""
        order_id = _require_contract_id(self.order_id, "order_id")
        old_contract_id = _require_contract_id(self.old_contract_id, "old_contract_id")
        new_contract_id = _require_contract_id(self.new_contract_id, "new_contract_id")
        if old_contract_id == new_contract_id:
            raise ValueError("Paired roll trebuet dva raznyh contract_id")
        object.__setattr__(self, "order_id", order_id)
        object.__setattr__(self, "old_contract_id", old_contract_id)
        object.__setattr__(self, "new_contract_id", new_contract_id)
        object.__setattr__(self, "decision_at", _require_decision_time(self.decision_at))
        object.__setattr__(
            self,
            "contracts",
            _require_positive_integer(self.contracts, "contracts"),
        )
        object.__setattr__(
            self,
            "exit_limit_price",
            _require_finite_positive(self.exit_limit_price, "exit_limit_price"),
        )
        object.__setattr__(
            self,
            "entry_limit_price",
            _require_finite_positive(self.entry_limit_price, "entry_limit_price"),
        )
        object.__setattr__(
            self,
            "allocation_priority",
            _require_nonnegative_integer(self.allocation_priority, "allocation_priority"),
        )


@dataclass(frozen=True, slots=True)
class ExecutionLeg:
    """Audit odnogo contract leg s completed-window factual POV outcome."""

    contract_id: str
    requested_contracts: int
    capacity_candle_open_at: datetime
    capacity_candle_close_at: datetime
    observed_capacity_volume: int | None
    observed_capacity_contracts: int | None
    order_live_at: datetime
    execution_window_open_at: datetime
    execution_window_close_at: datetime
    factual_execution_open: float | None
    factual_execution_high: float | None
    factual_execution_low: float | None
    factual_execution_close: float | None
    realized_execution_volume: int | None
    realized_execution_capacity_contracts: int | None
    execution_volume_is_post_window_outcome: bool
    aggregate_available_before: int | None
    executed_contracts: int
    execution_price: float | None
    reason: str
    provenance: str


@dataclass(frozen=True, slots=True)
class OrderExecution:
    """Rezultat odnogo non-roll limit ordera s deterministic gross allocation."""

    order_id: str
    decision_at: datetime
    requested_contracts: int
    executed_contracts: int
    carry_contracts: int
    allocation_priority: int
    status: ExecutionStatus
    reason: str
    provenance: str
    leg: ExecutionLeg


@dataclass(frozen=True, slots=True)
class RollExecution:
    """Rezultat signed paired research rolla bez venue atomicity claim."""

    order_id: str
    decision_at: datetime
    requested_contracts: int
    executed_contracts: int
    carry_contracts: int
    allocation_priority: int
    status: ExecutionStatus
    reason: str
    paired_research_fill: bool
    old_exposure_carried: bool
    broker_atomicity_not_proven: bool
    provenance: str
    old_leg: ExecutionLeg
    new_leg: ExecutionLeg

    def __post_init__(self) -> None:
        """Fail-closed fiksiruet signed equal-and-opposite roll geometry."""
        requested = _require_nonzero_integer(self.requested_contracts, "requested_contracts")
        if isinstance(self.executed_contracts, bool) or not isinstance(
            self.executed_contracts, int
        ):
            raise TypeError("executed_contracts dolzhen byt' int")
        if isinstance(self.carry_contracts, bool) or not isinstance(self.carry_contracts, int):
            raise TypeError("carry_contracts dolzhen byt' int")
        executed = self.executed_contracts
        carry = self.carry_contracts
        if executed and (executed > 0) != (requested > 0):
            raise ValueError("paired executed direction dolzhen sovpadat' s requested exposure")
        if abs(executed) > abs(requested) or carry != requested - executed:
            raise ValueError("paired signed quantity/carry invariant narushen")
        if self.old_leg.requested_contracts != -requested:
            raise ValueError("paired old requested leg dolzhen byt' -q")
        if self.new_leg.requested_contracts != requested:
            raise ValueError("paired new requested leg dolzhen byt' +q")
        if self.old_leg.executed_contracts != -executed:
            raise ValueError("paired old executed leg dolzhen byt' -executed q")
        if self.new_leg.executed_contracts != executed:
            raise ValueError("paired new executed leg dolzhen byt' +executed q")
        absolute_request = abs(requested)
        absolute_execution = abs(executed)
        expected_status = (
            ExecutionStatus.FILLED
            if absolute_execution == absolute_request
            else ExecutionStatus.CARRIED
            if absolute_execution == 0
            else ExecutionStatus.PARTIAL_CARRY
        )
        if self.status is not expected_status:
            raise ValueError("paired status ne sootvetstvuet signed quantity geometry")
        if self.paired_research_fill is not bool(executed):
            raise ValueError("paired_research_fill ne sootvetstvuet factual fill")
        if self.old_exposure_carried is not (absolute_execution < absolute_request):
            raise ValueError("old_exposure_carried ne sootvetstvuet residual exposure")
        if not self.broker_atomicity_not_proven:
            raise ValueError("paired research roll ne mozhet zayavlyat' broker atomicity")


ExecutionRequest = PredeclaredMarketOrder | PredeclaredPairedMarketRollOrder
DiagnosticExecutionRequest = PredeclaredLimitOrder | PredeclaredRollOrder
ExecutionResult = OrderExecution | RollExecution


@dataclass(frozen=True, slots=True)
class _LegProbe:
    """Vnutrennii factual snapshot do gross-cap allocation i final'nogo audit."""

    contract_id: str
    requested_contracts: int
    capacity_candle_open_at: datetime
    capacity_candle_close_at: datetime
    observed_capacity_volume: int | None
    observed_capacity_contracts: int | None
    order_live_at: datetime
    execution_window_open_at: datetime
    execution_window_close_at: datetime
    factual_execution_open: float | None
    factual_execution_high: float | None
    factual_execution_low: float | None
    factual_execution_close: float | None
    realized_execution_volume: int | None
    realized_execution_capacity_contracts: int | None
    reason: str

    @property
    def ready(self) -> bool:
        """Pokazyvaet, chto oba bar'a i worst-price limit dopuskayut fill."""
        return self.reason == "ready"

    @property
    def aggregate_budget(self) -> int:
        """Vozvrashchaet observed i realized 1-percent gross budget leg'a."""
        if not self.ready:
            raise RuntimeError("Nedostupnyi leg ne imeet allocation budget")
        if (
            self.observed_capacity_contracts is None
            or self.realized_execution_capacity_contracts is None
        ):
            raise RuntimeError("Ready leg dolzhen imet' oba capacity limit'a")
        return min(self.observed_capacity_contracts, self.realized_execution_capacity_contracts)

    def execution_leg(
        self,
        executed_contracts: int,
        aggregate_available_before: int | None,
        reason: str | None = None,
    ) -> ExecutionLeg:
        """Materializuet audit-leg; cena ne poyavlyaetsya bez factual fill."""
        if executed_contracts and not self.ready:
            raise RuntimeError("Nedostupnyi leg ne mozhet poluchit' fill")
        if executed_contracts > 0:
            execution_price = self.factual_execution_high
        elif executed_contracts < 0:
            execution_price = self.factual_execution_low
        else:
            execution_price = None
        return ExecutionLeg(
            contract_id=self.contract_id,
            requested_contracts=self.requested_contracts,
            capacity_candle_open_at=self.capacity_candle_open_at,
            capacity_candle_close_at=self.capacity_candle_close_at,
            observed_capacity_volume=self.observed_capacity_volume,
            observed_capacity_contracts=self.observed_capacity_contracts,
            order_live_at=self.order_live_at,
            execution_window_open_at=self.execution_window_open_at,
            execution_window_close_at=self.execution_window_close_at,
            factual_execution_open=self.factual_execution_open,
            factual_execution_high=self.factual_execution_high,
            factual_execution_low=self.factual_execution_low,
            factual_execution_close=self.factual_execution_close,
            realized_execution_volume=self.realized_execution_volume,
            realized_execution_capacity_contracts=self.realized_execution_capacity_contracts,
            execution_volume_is_post_window_outcome=True,
            aggregate_available_before=aggregate_available_before,
            executed_contracts=executed_contracts,
            execution_price=execution_price,
            reason=reason or self.reason,
            provenance=RESEARCH_ONLY_NOT_QUEUE_EXACT,
        )


@dataclass(frozen=True, slots=True)
class _PreparedSingle:
    """Svyazyvaet odin signal s ego factual completed-window probe."""

    order: PredeclaredMarketOrder | PredeclaredLimitOrder
    probe: _LegProbe


@dataclass(frozen=True, slots=True)
class _PreparedRoll:
    """Svyazyvaet paired roll s dvumya factual completed-window probe."""

    order: PredeclaredPairedMarketRollOrder | PredeclaredRollOrder
    old_probe: _LegProbe
    new_probe: _LegProbe


_PreparedRequest = _PreparedSingle | _PreparedRoll


def _planned_times(
    decision_at: datetime,
    policy: CausalPovExecutionPolicy,
) -> tuple[datetime, datetime, datetime, datetime]:
    """Stroit 19:00 capacity i bolee pozdnee polnoe execution window."""
    capacity_open_at = decision_at + BAR_INTERVAL
    capacity_close_at = capacity_open_at + BAR_INTERVAL
    execution_window_open_at = capacity_close_at + policy.order_latency
    execution_window_close_at = execution_window_open_at + BAR_INTERVAL
    local_capacity = capacity_open_at.astimezone(MOSCOW_TIMEZONE)
    if local_capacity.time().replace(tzinfo=None) != FIRST_CANDLE_TIME:
        raise RuntimeError("D18:50 schedule dolzhen nachinat' capacity candle v 19:00")
    return (
        capacity_open_at,
        capacity_close_at,
        execution_window_open_at,
        execution_window_close_at,
    )


def _index_candles(
    candles: Sequence[TenMinuteCandle],
) -> dict[tuple[str, datetime], TenMinuteCandle]:
    """Indeksiruet raw candles i fail-closed ot duplicate contract/timestamp."""
    index: dict[tuple[str, datetime], TenMinuteCandle] = {}
    for candle in candles:
        if not isinstance(candle, TenMinuteCandle):
            raise TypeError("candles dolzhny soderzhat' TenMinuteCandle")
        key = (candle.contract_id, candle.opened_at)
        if key in index:
            raise ValueError("Candle panel soderzhit duplicate contract_id/opened_at")
        index[key] = candle
    return index


def _assert_unique_order_ids(
    orders: Sequence[object],
    allowed_types: tuple[type[object], ...],
    surface_name: str,
) -> None:
    """Proveryaet request surface i unikal'nye ID do allocation."""
    seen: set[str] = set()
    for order in orders:
        if not isinstance(order, allowed_types):
            raise TypeError(f"orders dolzhny soderzhat' tol'ko {surface_name} ordery")
        if order.order_id in seen:
            raise ValueError("order_id dolzhen byt' unikal'nym")
        seen.add(order.order_id)


def _limit_allows(signed_contracts: int, limit_price: float, probe: _LegProbe) -> bool:
    """Proveryaet limit po adverse high dlya buy i low dlya sell."""
    if signed_contracts > 0:
        return (
            probe.factual_execution_high is not None
            and probe.factual_execution_high <= limit_price
        )
    return (
        probe.factual_execution_low is not None
        and probe.factual_execution_low >= limit_price
    )


def _probe_leg(
    *,
    contract_id: str,
    decision_at: datetime,
    signed_contracts: int,
    diagnostic_limit_price: float | None,
    policy: CausalPovExecutionPolicy,
    candles: dict[tuple[str, datetime], TenMinuteCandle],
) -> _LegProbe:
    """Chitaet capacity bar i tol'ko bolee pozdnii completed execution bar."""
    (
        capacity_open_at,
        capacity_close_at,
        execution_window_open_at,
        execution_window_close_at,
    ) = _planned_times(decision_at, policy)
    capacity = candles.get((contract_id, capacity_open_at))
    execution = candles.get((contract_id, execution_window_open_at))
    observed_volume = capacity.volume if capacity is not None else None
    observed_capacity = (
        observed_volume * policy.participation_bps // BASIS_POINTS
        if observed_volume is not None
        else None
    )
    factual_open = execution.open_price if execution is not None else None
    factual_high = execution.high_price if execution is not None else None
    factual_low = execution.low_price if execution is not None else None
    factual_close = execution.close_price if execution is not None else None
    realized_volume = execution.volume if execution is not None else None
    realized_capacity = (
        realized_volume * policy.participation_bps // BASIS_POINTS
        if realized_volume is not None
        else None
    )
    base = {
        "contract_id": contract_id,
        "requested_contracts": signed_contracts,
        "capacity_candle_open_at": capacity_open_at,
        "capacity_candle_close_at": capacity_close_at,
        "observed_capacity_volume": observed_volume,
        "observed_capacity_contracts": observed_capacity,
        "order_live_at": execution_window_open_at,
        "execution_window_open_at": execution_window_open_at,
        "execution_window_close_at": execution_window_close_at,
        "factual_execution_open": factual_open,
        "factual_execution_high": factual_high,
        "factual_execution_low": factual_low,
        "factual_execution_close": factual_close,
        "realized_execution_volume": realized_volume,
        "realized_execution_capacity_contracts": realized_capacity,
    }
    if capacity is None:
        return _LegProbe(**base, reason="missing_capacity_candle")
    if capacity.closed_at != capacity_close_at:
        raise RuntimeError("Capacity candle ne pokryvaet polnoe 19:00--19:10 window")
    if observed_volume is None:
        return _LegProbe(**base, reason="unavailable_capacity_volume")
    if execution is None:
        return _LegProbe(**base, reason="missing_execution_candle")
    if execution.closed_at != execution_window_close_at:
        raise RuntimeError("Execution candle ne pokryvaet polnoe planned window")
    if not execution.has_factual_ohlc:
        return _LegProbe(**base, reason="unavailable_execution_ohlc")
    if realized_volume is None:
        return _LegProbe(**base, reason="unavailable_execution_volume")
    if observed_capacity == 0:
        return _LegProbe(**base, reason="zero_observed_capacity")
    if realized_capacity == 0:
        return _LegProbe(**base, reason="zero_realized_execution_capacity")
    candidate = _LegProbe(**base, reason="ready")
    if diagnostic_limit_price is not None and not _limit_allows(
        signed_contracts, diagnostic_limit_price, candidate
    ):
        return _LegProbe(**base, reason="limit_not_reached_skip")
    return candidate


def _capacity_key(probe: _LegProbe) -> tuple[str, datetime]:
    """Delaet odin aggregate gross budget na contract i execution window."""
    return probe.contract_id, probe.execution_window_open_at


def _build_remaining_capacity(
    prepared: Sequence[_PreparedRequest],
) -> dict[tuple[str, datetime], int]:
    """Stroit obshchii cap do allocation, bez netting protivopolozhnyh orderov."""
    remaining: dict[tuple[str, datetime], int] = {}
    probes: list[_LegProbe] = []
    for item in prepared:
        if isinstance(item, _PreparedSingle):
            probes.append(item.probe)
        else:
            probes.extend((item.old_probe, item.new_probe))
    for probe in probes:
        if not probe.ready:
            continue
        key = _capacity_key(probe)
        budget = probe.aggregate_budget
        previous = remaining.setdefault(key, budget)
        if previous != budget:
            raise RuntimeError("Odna factual execution candle imeet nesovmestimye cap")
    return remaining


def _single_execution(
    item: _PreparedSingle,
    remaining: dict[tuple[str, datetime], int],
) -> OrderExecution:
    """Vydelyaet gross per-contract POV cap v deterministic order."""
    order = item.order
    probe = item.probe
    if not probe.ready:
        skipped = probe.reason == "limit_not_reached_skip"
        status = ExecutionStatus.SKIPPED_LIMIT if skipped else ExecutionStatus.CARRIED
        carry = 0 if skipped else order.signed_contracts
        return OrderExecution(
            order_id=order.order_id,
            decision_at=order.decision_at,
            requested_contracts=order.signed_contracts,
            executed_contracts=0,
            carry_contracts=carry,
            allocation_priority=order.allocation_priority,
            status=status,
            reason=probe.reason,
            provenance=RESEARCH_ONLY_NOT_QUEUE_EXACT,
            leg=probe.execution_leg(0, None),
        )
    key = _capacity_key(probe)
    available = remaining[key]
    quantity = min(abs(order.signed_contracts), available)
    remaining[key] -= quantity
    executed = quantity if order.signed_contracts > 0 else -quantity
    if quantity == 0:
        status = ExecutionStatus.CARRIED
        reason = "aggregate_capacity_exhausted"
    elif quantity < abs(order.signed_contracts):
        status = ExecutionStatus.PARTIAL_CARRY
        reason = "aggregate_capacity_limited"
    else:
        status = ExecutionStatus.FILLED
        reason = "filled"
    return OrderExecution(
        order_id=order.order_id,
        decision_at=order.decision_at,
        requested_contracts=order.signed_contracts,
        executed_contracts=executed,
        carry_contracts=order.signed_contracts - executed,
        allocation_priority=order.allocation_priority,
        status=status,
        reason=reason,
        provenance=RESEARCH_ONLY_NOT_QUEUE_EXACT,
        leg=probe.execution_leg(executed, available, reason),
    )


def _roll_execution(
    item: _PreparedRoll,
    remaining: dict[tuple[str, datetime], int],
) -> RollExecution:
    """Modeliruet paired research fill, no ne utverzhdaet venue atomicity."""
    order = item.order
    old_probe = item.old_probe
    new_probe = item.new_probe
    signed_request = order.contracts
    absolute_request = abs(signed_request)
    failed = next((probe for probe in (old_probe, new_probe) if not probe.ready), None)
    if failed is not None:
        reason = f"paired_research_fill_{failed.contract_id}_{failed.reason}"
        return RollExecution(
            order_id=order.order_id,
            decision_at=order.decision_at,
            requested_contracts=signed_request,
            executed_contracts=0,
            carry_contracts=signed_request,
            allocation_priority=order.allocation_priority,
            status=ExecutionStatus.CARRIED,
            reason=reason,
            paired_research_fill=False,
            old_exposure_carried=True,
            broker_atomicity_not_proven=True,
            provenance=RESEARCH_ONLY_NOT_QUEUE_EXACT,
            old_leg=old_probe.execution_leg(0, None, reason),
            new_leg=new_probe.execution_leg(0, None, reason),
        )
    old_available = remaining[_capacity_key(old_probe)]
    new_available = remaining[_capacity_key(new_probe)]
    quantity = min(absolute_request, old_available, new_available)
    remaining[_capacity_key(old_probe)] -= quantity
    remaining[_capacity_key(new_probe)] -= quantity
    executed = quantity if signed_request > 0 else -quantity
    if quantity == 0:
        status = ExecutionStatus.CARRIED
        reason = "paired_aggregate_capacity_exhausted"
    elif quantity < absolute_request:
        status = ExecutionStatus.PARTIAL_CARRY
        reason = "paired_aggregate_capacity_limited"
    else:
        status = ExecutionStatus.FILLED
        reason = "paired_research_fill"
    return RollExecution(
        order_id=order.order_id,
        decision_at=order.decision_at,
        requested_contracts=signed_request,
        executed_contracts=executed,
        carry_contracts=signed_request - executed,
        allocation_priority=order.allocation_priority,
        status=status,
        reason=reason,
        paired_research_fill=quantity > 0,
        old_exposure_carried=quantity < absolute_request,
        broker_atomicity_not_proven=True,
        provenance=RESEARCH_ONLY_NOT_QUEUE_EXACT,
        old_leg=old_probe.execution_leg(-executed, old_available, reason),
        new_leg=new_probe.execution_leg(executed, new_available, reason),
    )


def _prepare_requests(
    orders: Sequence[ExecutionRequest | DiagnosticExecutionRequest],
    policy: CausalPovExecutionPolicy,
    candles: dict[tuple[str, datetime], TenMinuteCandle],
) -> list[_PreparedRequest]:
    """Sobiraet vse factual probe do allocation, chtoby ne chitat' future fallback."""
    prepared: list[_PreparedRequest] = []
    for order in orders:
        if isinstance(order, (PredeclaredMarketOrder, PredeclaredLimitOrder)):
            diagnostic_limit_price = (
                order.limit_price if isinstance(order, PredeclaredLimitOrder) else None
            )
            prepared.append(
                _PreparedSingle(
                    order=order,
                    probe=_probe_leg(
                        contract_id=order.contract_id,
                        decision_at=order.decision_at,
                        signed_contracts=order.signed_contracts,
                        diagnostic_limit_price=diagnostic_limit_price,
                        policy=policy,
                        candles=candles,
                    ),
                )
            )
        else:
            diagnostic_exit_limit = (
                order.exit_limit_price if isinstance(order, PredeclaredRollOrder) else None
            )
            diagnostic_entry_limit = (
                order.entry_limit_price if isinstance(order, PredeclaredRollOrder) else None
            )
            prepared.append(
                _PreparedRoll(
                    order=order,
                    old_probe=_probe_leg(
                        contract_id=order.old_contract_id,
                        decision_at=order.decision_at,
                        signed_contracts=-order.contracts,
                        diagnostic_limit_price=diagnostic_exit_limit,
                        policy=policy,
                        candles=candles,
                    ),
                    new_probe=_probe_leg(
                        contract_id=order.new_contract_id,
                        decision_at=order.decision_at,
                        signed_contracts=order.contracts,
                        diagnostic_limit_price=diagnostic_entry_limit,
                        policy=policy,
                        candles=candles,
                    ),
                )
            )
    return prepared


def _allocation_key(item: _PreparedRequest) -> tuple[int, str]:
    """Fiksiruet stable prioritet: men'shee chislo, zatem lexical order_id."""
    return item.order.allocation_priority, item.order.order_id


def plan_causal_v8_execution(
    orders: Sequence[ExecutionRequest],
    candles: Sequence[TenMinuteCandle],
    policy: CausalPovExecutionPolicy | None = None,
) -> tuple[ExecutionResult, ...]:
    """Stroit primary market-order POV fill/carry bez PnL i synthetic cen.

    Signal v D18:50 nablyudaet tol'ko capacity candle 19:00--19:10. Posle
    explicit minimum-odnobar latency order zhivet v bolee pozdnem polnom 10m
    window (po default 19:20--19:30). Ego volume stanovitsya izvestnym tol'ko
    po zakrytii window i sluzhit outcome-modeli POV, a ne inputom v moment live.
    Odnovremennye ordery odnogo kontrakta allocation'atsya po gross cap
    deterministicheski: allocation_priority, zatem order_id; netting ne zayavlen.
    """
    frozen_orders = tuple(orders)
    _assert_unique_order_ids(
        frozen_orders,
        (PredeclaredMarketOrder, PredeclaredPairedMarketRollOrder),
        "primary market",
    )
    return _plan_prevalidated_execution(frozen_orders, candles, policy)


def plan_diagnostic_limit_v8_execution(
    orders: Sequence[DiagnosticExecutionRequest],
    candles: Sequence[TenMinuteCandle],
    policy: CausalPovExecutionPolicy | None = None,
) -> tuple[ExecutionResult, ...]:
    """Zapuskaet izolirovannyi non-primary limit diagnostic na tom zhe POV yadre."""
    frozen_orders = tuple(orders)
    _assert_unique_order_ids(
        frozen_orders,
        (PredeclaredLimitOrder, PredeclaredRollOrder),
        "diagnostic limit",
    )
    return _plan_prevalidated_execution(frozen_orders, candles, policy)


def _plan_prevalidated_execution(
    orders: Sequence[ExecutionRequest | DiagnosticExecutionRequest],
    candles: Sequence[TenMinuteCandle],
    policy: CausalPovExecutionPolicy | None,
) -> tuple[ExecutionResult, ...]:
    """Vypolnyaet obshchee yadro posle fail-closed proverki API surface."""
    resolved_policy = policy or CausalPovExecutionPolicy()
    index = _index_candles(candles)
    prepared = _prepare_requests(orders, resolved_policy, index)
    remaining = _build_remaining_capacity(prepared)
    results_by_id: dict[str, ExecutionResult] = {}
    for item in sorted(prepared, key=_allocation_key):
        if isinstance(item, _PreparedSingle):
            result: ExecutionResult = _single_execution(item, remaining)
        else:
            result = _roll_execution(item, remaining)
        results_by_id[result.order_id] = result
    return tuple(results_by_id[order.order_id] for order in orders)


__all__ = [
    "BAR_INTERVAL",
    "BASIS_POINTS",
    "CAPACITY_BPS",
    "DECISION_TIME",
    "DIAGNOSTIC_LIMIT_ORDER_ONLY",
    "DEFAULT_ORDER_LATENCY",
    "FIRST_CANDLE_TIME",
    "FUTURES_V8_EXECUTION_VERSION",
    "MINIMUM_ORDER_LATENCY",
    "PAIRED_ROLL_POLICY",
    "PRIMARY_ORDER_PRICE_POLICY",
    "RESEARCH_ONLY_NOT_QUEUE_EXACT",
    "CausalPovExecutionPolicy",
    "DiagnosticExecutionRequest",
    "ExecutionLeg",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "OrderExecution",
    "PredeclaredLimitOrder",
    "PredeclaredMarketOrder",
    "PredeclaredPairedMarketRollOrder",
    "PredeclaredRollOrder",
    "RollExecution",
    "SealedExecutionProtocol",
    "TenMinuteCandle",
    "assert_causal_v8_policy_matches_protocol",
    "plan_causal_v8_execution",
    "plan_diagnostic_limit_v8_execution",
]
