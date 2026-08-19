"""Scenario-isolated state machines for the two stateful futures-v8 candidates.

The module is deliberately economic-output free.  It turns sealed, factual order
evidence into immutable strategy transitions and ledger-ready fill events; cash,
variation margin and performance remain the responsibility of ``eval_run``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import Enum, StrEnum
from hashlib import sha256
from math import isfinite
from typing import Any, Final
from zoneinfo import ZoneInfo

from market_lab.futures_v8.aggressive_strategies import (
    BREAKOUT_PYRAMID_LEVELS,
    BREAKOUT_TRAILING_STOP_ATR,
    CORRIDOR_STOP_LOSS_ATR,
    CORRIDOR_TAKE_PROFIT_ATR,
    V8_ASSET_IDS,
    AggressiveCandidateId,
)
from market_lab.futures_v8.eval_run import V8ScenarioExecutionEvidence, V8ScenarioId
from market_lab.futures_v8.execution import ExecutionStatus, OrderExecution

PROTECTED_HOLDOUT_START: Final[date] = date(2026, 1, 1)
TEN_MINUTES: Final[timedelta] = timedelta(minutes=10)
MOSCOW_TIMEZONE: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
CORRIDOR_STRATEGY_ID: Final[str] = (
    AggressiveCandidateId.VOLATILITY_CORRIDOR_HARVEST.value
)
BREAKOUT_STRATEGY_ID: Final[str] = (
    AggressiveCandidateId.BREAKOUT_PYRAMIDING_TRAILING_STOP.value
)
STATEFUL_STRATEGY_IDS: Final[tuple[str, str]] = (
    CORRIDOR_STRATEGY_ID,
    BREAKOUT_STRATEGY_ID,
)


def _require_identifier(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be str")
    if not value or value.strip() != value or any(character.isspace() for character in value):
        raise ValueError(f"{label} must be a non-empty identifier without whitespace")
    return value


def _require_sha256(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be str")
    normalized = value.lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{label} must be a SHA-256")
    return normalized


def _require_aware(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    normalized = value.astimezone(UTC)
    if normalized.astimezone(MOSCOW_TIMEZONE).date() >= PROTECTED_HOLDOUT_START:
        raise ValueError(f"{label} enters the protected 2026 holdout")
    return normalized


def _require_session_date(value: date, label: str) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise TypeError(f"{label} must be an exact date")
    if value >= PROTECTED_HOLDOUT_START:
        raise ValueError(f"{label} enters the protected 2026 holdout")
    return value


def _require_int(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be int")
    return value


def _require_nonnegative_int(value: int, label: str) -> int:
    normalized = _require_int(value, label)
    if normalized < 0:
        raise ValueError(f"{label} must be nonnegative")
    return normalized


def _require_nonzero_int(value: int, label: str) -> int:
    normalized = _require_int(value, label)
    if normalized == 0:
        raise ValueError(f"{label} must be nonzero")
    return normalized


def _require_positive(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be numeric")
    normalized = float(value)
    if not isfinite(normalized) or normalized <= 0.0:
        raise ValueError(f"{label} must be finite and positive")
    return normalized


def _canonical(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _canonical(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        _canonical(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class StatefulSealSet:
    """Transitive identity required by every stateful order and transition."""

    prediction_sha256: str
    input_bundle_sha256: str
    calendar_sha256: str
    contract_sha256: str
    sleeve_sha256: str

    def __post_init__(self) -> None:
        for name in (
            "prediction_sha256",
            "input_bundle_sha256",
            "calendar_sha256",
            "contract_sha256",
            "sleeve_sha256",
        ):
            object.__setattr__(self, name, _require_sha256(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class ScenarioExecutionWindow:
    """One calendar-sealed, scenario-specific completed 10-minute window."""

    scenario_id: V8ScenarioId
    bar_sequence_id: int
    common_session_sequence_id: int
    opened_at: datetime
    closed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario_id", V8ScenarioId(self.scenario_id))
        object.__setattr__(
            self,
            "bar_sequence_id",
            _require_nonnegative_int(self.bar_sequence_id, "bar_sequence_id"),
        )
        object.__setattr__(
            self,
            "common_session_sequence_id",
            _require_nonnegative_int(
                self.common_session_sequence_id,
                "common_session_sequence_id",
            ),
        )
        opened = _require_aware(self.opened_at, "opened_at")
        closed = _require_aware(self.closed_at, "closed_at")
        if closed - opened != TEN_MINUTES:
            raise ValueError("scenario execution window must be exactly 10 minutes")
        object.__setattr__(self, "opened_at", opened)
        object.__setattr__(self, "closed_at", closed)


@dataclass(frozen=True, slots=True)
class ExactScenarioExecutionWindows:
    """Exact primary/double/delay schedule without a synthetic primary timestamp."""

    windows: tuple[ScenarioExecutionWindow, ...]

    def __post_init__(self) -> None:
        frozen = tuple(self.windows)
        expected = (
            V8ScenarioId.PRIMARY,
            V8ScenarioId.DOUBLE_COST,
            V8ScenarioId.DELAY,
        )
        if tuple(item.scenario_id for item in frozen) != expected:
            raise ValueError("windows must be exact primary, double_cost, delay order")
        primary, doubled, delayed = frozen
        if (
            primary.bar_sequence_id,
            primary.common_session_sequence_id,
            primary.opened_at,
            primary.closed_at,
        ) != (
            doubled.bar_sequence_id,
            doubled.common_session_sequence_id,
            doubled.opened_at,
            doubled.closed_at,
        ):
            raise ValueError("primary and double_cost must use the same factual window")
        if delayed.bar_sequence_id != primary.bar_sequence_id + 1:
            raise ValueError("delay must use the next complete calendar bar")
        if delayed.opened_at < primary.closed_at:
            raise ValueError("delay window cannot overlap the primary window")
        object.__setattr__(self, "windows", frozen)

    def for_scenario(self, scenario_id: V8ScenarioId | str) -> ScenarioExecutionWindow:
        resolved = V8ScenarioId(scenario_id)
        return next(item for item in self.windows if item.scenario_id is resolved)


class StatefulAction(StrEnum):
    """Ledger-facing actions emitted by the isolated state machines."""

    CORRIDOR_ENTRY = "corridor_entry"
    CORRIDOR_EXIT_STOP = "corridor_exit_stop"
    CORRIDOR_EXIT_TAKE_PROFIT = "corridor_exit_take_profit"
    CORRIDOR_EXIT_TIME = "corridor_exit_time"
    BREAKOUT_ENTER = "breakout_enter"
    BREAKOUT_ADD = "breakout_add"
    BREAKOUT_EXIT_TRAIL = "breakout_exit_trail"
    BREAKOUT_EXIT_REVERSAL = "breakout_exit_reversal"


class StatefulResolution(StrEnum):
    """Whether factual evidence is sufficient to advance strategy state."""

    APPLIED = "applied"
    UNRESOLVED = "unresolved"


_CORRIDOR_ACTIONS: Final[frozenset[StatefulAction]] = frozenset(
    {
        StatefulAction.CORRIDOR_ENTRY,
        StatefulAction.CORRIDOR_EXIT_STOP,
        StatefulAction.CORRIDOR_EXIT_TAKE_PROFIT,
        StatefulAction.CORRIDOR_EXIT_TIME,
    }
)
_BREAKOUT_ACTIONS: Final[frozenset[StatefulAction]] = frozenset(
    {
        StatefulAction.BREAKOUT_ENTER,
        StatefulAction.BREAKOUT_ADD,
        StatefulAction.BREAKOUT_EXIT_TRAIL,
        StatefulAction.BREAKOUT_EXIT_REVERSAL,
    }
)


@dataclass(frozen=True, slots=True)
class StatefulOrderIntent:
    """Causal order identity plus an exact scenario execution slot."""

    strategy_id: str
    action: StatefulAction
    scenario_id: V8ScenarioId
    decision_at: datetime
    effective_session_date: date
    asset_id: str
    contract_id: str
    sleeve_id: str
    order_id: str
    requested_contracts: int
    execution_window: ScenarioExecutionWindow
    seals: StatefulSealSet

    def __post_init__(self) -> None:
        strategy = _require_identifier(self.strategy_id, "strategy_id")
        if strategy not in STATEFUL_STRATEGY_IDS:
            raise ValueError("strategy_id is not a stateful futures-v8 candidate")
        action = StatefulAction(self.action)
        allowed = _CORRIDOR_ACTIONS if strategy == CORRIDOR_STRATEGY_ID else _BREAKOUT_ACTIONS
        if action not in allowed:
            raise ValueError("action does not belong to strategy_id")
        scenario = V8ScenarioId(self.scenario_id)
        if self.execution_window.scenario_id is not scenario:
            raise ValueError("intent/window scenario mismatch")
        decision = _require_aware(self.decision_at, "decision_at")
        if self.execution_window.opened_at <= decision:
            raise ValueError("execution window must start after the causal decision")
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("asset_id is outside the sealed universe")
        for name in ("contract_id", "sleeve_id", "order_id"):
            object.__setattr__(self, name, _require_identifier(getattr(self, name), name))
        object.__setattr__(self, "strategy_id", strategy)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "scenario_id", scenario)
        object.__setattr__(self, "decision_at", decision)
        object.__setattr__(
            self,
            "effective_session_date",
            _require_session_date(self.effective_session_date, "effective_session_date"),
        )
        object.__setattr__(
            self,
            "requested_contracts",
            _require_nonzero_int(self.requested_contracts, "requested_contracts"),
        )
        if not isinstance(self.seals, StatefulSealSet):
            raise TypeError("seals must be StatefulSealSet")


@dataclass(frozen=True, slots=True)
class StatefulExecutionEvidence:
    """Factual scenario fill evidence; incomplete rows remain auditable carry."""

    scenario_id: V8ScenarioId
    order_id: str
    decision_at: datetime
    effective_session_date: date
    asset_id: str
    contract_id: str
    sleeve_id: str
    bar_sequence_id: int
    common_session_sequence_id: int
    window_opened_at: datetime
    window_closed_at: datetime
    requested_contracts: int
    executed_contracts: int
    carry_contracts: int
    status: ExecutionStatus
    execution_price: float | None
    factual_open: float | None
    factual_high: float | None
    factual_low: float | None
    factual_close: float | None
    factual_volume: int | None
    capacity_contracts: int | None
    observed_at: datetime
    reason: str
    evidence_sha256: str
    seals: StatefulSealSet

    def __post_init__(self) -> None:
        scenario = V8ScenarioId(self.scenario_id)
        object.__setattr__(self, "scenario_id", scenario)
        for name in ("order_id", "contract_id", "sleeve_id"):
            object.__setattr__(self, name, _require_identifier(getattr(self, name), name))
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("asset_id is outside the sealed universe")
        decision = _require_aware(self.decision_at, "decision_at")
        opened = _require_aware(self.window_opened_at, "window_opened_at")
        closed = _require_aware(self.window_closed_at, "window_closed_at")
        observed = _require_aware(self.observed_at, "observed_at")
        if closed - opened != TEN_MINUTES:
            raise ValueError("execution evidence window must be exactly 10 minutes")
        if opened <= decision or observed < closed:
            raise ValueError("execution evidence violates decision/window chronology")
        object.__setattr__(self, "decision_at", decision)
        object.__setattr__(self, "window_opened_at", opened)
        object.__setattr__(self, "window_closed_at", closed)
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(
            self,
            "effective_session_date",
            _require_session_date(self.effective_session_date, "effective_session_date"),
        )
        object.__setattr__(
            self,
            "bar_sequence_id",
            _require_nonnegative_int(self.bar_sequence_id, "bar_sequence_id"),
        )
        object.__setattr__(
            self,
            "common_session_sequence_id",
            _require_nonnegative_int(
                self.common_session_sequence_id,
                "common_session_sequence_id",
            ),
        )
        requested = _require_nonzero_int(self.requested_contracts, "requested_contracts")
        executed = _require_int(self.executed_contracts, "executed_contracts")
        carry = _require_int(self.carry_contracts, "carry_contracts")
        if executed and (executed > 0) != (requested > 0):
            raise ValueError("executed direction differs from requested direction")
        if abs(executed) > abs(requested) or carry != requested - executed:
            raise ValueError("execution quantity/carry invariant is broken")
        expected_status = (
            ExecutionStatus.FILLED
            if executed == requested and carry == 0
            else ExecutionStatus.CARRIED
            if executed == 0
            else ExecutionStatus.PARTIAL_CARRY
        )
        status = ExecutionStatus(self.status)
        if status is not expected_status:
            raise ValueError("execution status differs from quantity geometry")
        if executed:
            if self.execution_price is None:
                raise ValueError("nonzero execution requires execution_price")
            object.__setattr__(
                self,
                "execution_price",
                _require_positive(self.execution_price, "execution_price"),
            )
        elif self.execution_price is not None:
            raise ValueError("zero execution cannot have execution_price")
        normalized_prices: dict[str, float | None] = {}
        for name in ("factual_open", "factual_high", "factual_low", "factual_close"):
            value = getattr(self, name)
            normalized_prices[name] = None if value is None else _require_positive(value, name)
            object.__setattr__(self, name, normalized_prices[name])
        high = normalized_prices["factual_high"]
        low = normalized_prices["factual_low"]
        if high is not None and low is not None and high < low:
            raise ValueError("factual high/low invariant is broken")
        if all(value is not None for value in normalized_prices.values()) and (
            high < max(normalized_prices["factual_open"], normalized_prices["factual_close"])
            or low > min(normalized_prices["factual_open"], normalized_prices["factual_close"])
        ):
            raise ValueError("factual OHLC invariant is broken")
        if self.factual_volume is not None:
            object.__setattr__(
                self,
                "factual_volume",
                _require_nonnegative_int(self.factual_volume, "factual_volume"),
            )
        if self.capacity_contracts is not None:
            capacity = _require_nonnegative_int(self.capacity_contracts, "capacity_contracts")
            if abs(executed) > capacity:
                raise ValueError("executed contracts exceed factual capacity")
            object.__setattr__(self, "capacity_contracts", capacity)
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be non-empty")
        object.__setattr__(
            self,
            "evidence_sha256",
            _require_sha256(self.evidence_sha256, "evidence_sha256"),
        )
        if not isinstance(self.seals, StatefulSealSet):
            raise TypeError("seals must be StatefulSealSet")
        object.__setattr__(self, "requested_contracts", requested)
        object.__setattr__(self, "executed_contracts", executed)
        object.__setattr__(self, "carry_contracts", carry)
        object.__setattr__(self, "status", status)

    @property
    def factual_window_complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.factual_open,
                self.factual_high,
                self.factual_low,
                self.factual_close,
                self.factual_volume,
                self.capacity_contracts,
            )
        )

    @property
    def fully_resolved(self) -> bool:
        return (
            self.status is ExecutionStatus.FILLED
            and self.executed_contracts == self.requested_contracts
            and self.carry_contracts == 0
            and self.factual_window_complete
        )

    @classmethod
    def from_v8_scenario(
        cls,
        evidence: V8ScenarioExecutionEvidence,
        *,
        asset_id: str,
        sleeve_id: str,
        bar_sequence_id: int,
        common_session_sequence_id: int,
        seals: StatefulSealSet,
        observed_at: datetime | None = None,
    ) -> StatefulExecutionEvidence:
        """Preserve the scenario leg's actual timestamp, including delayed fills."""
        if not isinstance(evidence, V8ScenarioExecutionEvidence):
            raise TypeError("evidence must be V8ScenarioExecutionEvidence")
        if not isinstance(evidence.base_execution, OrderExecution) or len(evidence.legs) != 1:
            raise TypeError("stateful conversion accepts one-contract OrderExecution only")
        leg = evidence.legs[0]
        return cls(
            scenario_id=evidence.scenario_id,
            order_id=evidence.order_id,
            decision_at=evidence.base_execution.decision_at,
            effective_session_date=evidence.effective_session_date,
            asset_id=asset_id,
            contract_id=leg.contract_id,
            sleeve_id=sleeve_id,
            bar_sequence_id=bar_sequence_id,
            common_session_sequence_id=common_session_sequence_id,
            window_opened_at=leg.window_opened_at,
            window_closed_at=leg.window_closed_at,
            requested_contracts=evidence.requested_contracts,
            executed_contracts=evidence.executed_contracts,
            carry_contracts=evidence.carry_contracts,
            status=evidence.status,
            execution_price=leg.execution_price,
            factual_open=leg.factual_open,
            factual_high=leg.factual_high,
            factual_low=leg.factual_low,
            factual_close=leg.factual_close,
            factual_volume=leg.factual_volume,
            capacity_contracts=leg.capacity_contracts,
            observed_at=observed_at or leg.window_closed_at,
            reason=leg.reason,
            evidence_sha256=evidence.evidence_sha256,
            seals=seals,
        )


@dataclass(frozen=True, slots=True)
class StatefulLedgerEvent:
    """Lossless typed fill event for a future bridge into ``V8EventLedgerState``."""

    strategy_id: str
    action: StatefulAction
    scenario_id: V8ScenarioId
    effective_session_date: date
    asset_id: str
    contract_id: str
    sleeve_id: str
    order_id: str
    executed_at: datetime
    window_opened_at: datetime
    bar_sequence_id: int
    common_session_sequence_id: int
    requested_contracts: int
    executed_contracts: int
    carry_contracts: int
    execution_price: float | None
    capacity_contracts: int | None
    factual_window_complete: bool
    resolution: StatefulResolution
    reason: str
    execution_evidence_sha256: str
    seals: StatefulSealSet
    adverse_reference_price: float | None = None

    def __post_init__(self) -> None:
        strategy = _require_identifier(self.strategy_id, "strategy_id")
        if strategy not in STATEFUL_STRATEGY_IDS:
            raise ValueError("ledger event strategy is not stateful")
        action = StatefulAction(self.action)
        allowed = _CORRIDOR_ACTIONS if strategy == CORRIDOR_STRATEGY_ID else _BREAKOUT_ACTIONS
        if action not in allowed:
            raise ValueError("ledger event action/strategy mismatch")
        scenario = V8ScenarioId(self.scenario_id)
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("ledger event asset is outside sealed universe")
        for name in ("contract_id", "sleeve_id", "order_id"):
            object.__setattr__(self, name, _require_identifier(getattr(self, name), name))
        executed_at = _require_aware(self.executed_at, "executed_at")
        opened_at = _require_aware(self.window_opened_at, "window_opened_at")
        if executed_at - opened_at != TEN_MINUTES:
            raise ValueError("ledger event must identify one complete 10-minute window")
        requested = _require_nonzero_int(self.requested_contracts, "requested_contracts")
        executed = _require_int(self.executed_contracts, "executed_contracts")
        carry = _require_int(self.carry_contracts, "carry_contracts")
        if carry != requested - executed or abs(executed) > abs(requested):
            raise ValueError("ledger event quantity/carry invariant is broken")
        if executed:
            if self.execution_price is None:
                raise ValueError("ledger event nonzero fill requires execution_price")
            object.__setattr__(
                self,
                "execution_price",
                _require_positive(self.execution_price, "execution_price"),
            )
        elif self.execution_price is not None:
            raise ValueError("ledger event zero fill cannot have execution_price")
        if self.capacity_contracts is not None:
            capacity = _require_nonnegative_int(self.capacity_contracts, "capacity_contracts")
            if abs(executed) > capacity:
                raise ValueError("ledger event fill exceeds capacity")
            object.__setattr__(self, "capacity_contracts", capacity)
        if not isinstance(self.factual_window_complete, bool):
            raise TypeError("factual_window_complete must be bool")
        resolution = StatefulResolution(self.resolution)
        fully_resolved = (
            executed == requested
            and carry == 0
            and self.factual_window_complete
            and self.capacity_contracts is not None
        )
        if (resolution is StatefulResolution.APPLIED) != fully_resolved:
            raise ValueError("ledger event resolution differs from factual completeness")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("ledger event reason must be non-empty")
        if not isinstance(self.seals, StatefulSealSet):
            raise TypeError("ledger event seals must be StatefulSealSet")
        reference = self.adverse_reference_price
        if reference is not None:
            object.__setattr__(
                self,
                "adverse_reference_price",
                _require_positive(reference, "adverse_reference_price"),
            )
        object.__setattr__(self, "strategy_id", strategy)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "scenario_id", scenario)
        object.__setattr__(
            self,
            "effective_session_date",
            _require_session_date(self.effective_session_date, "effective_session_date"),
        )
        object.__setattr__(self, "executed_at", executed_at)
        object.__setattr__(self, "window_opened_at", opened_at)
        object.__setattr__(
            self,
            "bar_sequence_id",
            _require_nonnegative_int(self.bar_sequence_id, "bar_sequence_id"),
        )
        object.__setattr__(
            self,
            "common_session_sequence_id",
            _require_nonnegative_int(
                self.common_session_sequence_id,
                "common_session_sequence_id",
            ),
        )
        object.__setattr__(self, "requested_contracts", requested)
        object.__setattr__(self, "executed_contracts", executed)
        object.__setattr__(self, "carry_contracts", carry)
        object.__setattr__(self, "resolution", resolution)
        object.__setattr__(
            self,
            "execution_evidence_sha256",
            _require_sha256(
                self.execution_evidence_sha256,
                "execution_evidence_sha256",
            ),
        )

    @property
    def position_key(self) -> tuple[str, str, str, str]:
        return (self.strategy_id, self.sleeve_id, self.asset_id, self.contract_id)


def _unresolved_reason(evidence: StatefulExecutionEvidence) -> str:
    if evidence.status is not ExecutionStatus.FILLED:
        return "partial_or_zero_execution_carry"
    if evidence.capacity_contracts is None:
        return "unknown_factual_capacity"
    if not evidence.factual_window_complete:
        return "incomplete_factual_window"
    return "unresolved_execution_evidence"


def reconcile_order_intent(
    intent: StatefulOrderIntent,
    evidence: StatefulExecutionEvidence,
    *,
    adverse_reference_price: float | None = None,
) -> StatefulLedgerEvent:
    """Validate exact identity and expose a ledger event without advancing strategy state."""
    if not isinstance(intent, StatefulOrderIntent):
        raise TypeError("intent must be StatefulOrderIntent")
    if not isinstance(evidence, StatefulExecutionEvidence):
        raise TypeError("evidence must be StatefulExecutionEvidence")
    expected = (
        intent.scenario_id,
        intent.order_id,
        intent.decision_at,
        intent.effective_session_date,
        intent.asset_id,
        intent.contract_id,
        intent.sleeve_id,
        intent.execution_window.bar_sequence_id,
        intent.execution_window.common_session_sequence_id,
        intent.execution_window.opened_at,
        intent.execution_window.closed_at,
        intent.requested_contracts,
        intent.seals,
    )
    actual = (
        evidence.scenario_id,
        evidence.order_id,
        evidence.decision_at,
        evidence.effective_session_date,
        evidence.asset_id,
        evidence.contract_id,
        evidence.sleeve_id,
        evidence.bar_sequence_id,
        evidence.common_session_sequence_id,
        evidence.window_opened_at,
        evidence.window_closed_at,
        evidence.requested_contracts,
        evidence.seals,
    )
    if actual != expected:
        raise ValueError("intent/evidence identity, timestamp, quantity or seal mismatch")
    if (
        intent.action is StatefulAction.CORRIDOR_ENTRY
        or intent.action in _BREAKOUT_ACTIONS
    ) and evidence.executed_contracts:
        if (
            evidence.executed_contracts > 0
            and evidence.factual_high is not None
            and evidence.execution_price < evidence.factual_high
        ):
            raise ValueError("market buy execution is better than factual adverse high")
        if (
            evidence.executed_contracts < 0
            and evidence.factual_low is not None
            and evidence.execution_price > evidence.factual_low
        ):
            raise ValueError("market sell execution is better than factual adverse low")
    reference = (
        None
        if adverse_reference_price is None
        else _require_positive(adverse_reference_price, "adverse_reference_price")
    )
    resolution = (
        StatefulResolution.APPLIED
        if evidence.fully_resolved
        else StatefulResolution.UNRESOLVED
    )
    reason = evidence.reason if evidence.fully_resolved else _unresolved_reason(evidence)
    return StatefulLedgerEvent(
        strategy_id=intent.strategy_id,
        action=intent.action,
        scenario_id=intent.scenario_id,
        effective_session_date=intent.effective_session_date,
        asset_id=intent.asset_id,
        contract_id=intent.contract_id,
        sleeve_id=intent.sleeve_id,
        order_id=intent.order_id,
        executed_at=evidence.window_closed_at,
        window_opened_at=evidence.window_opened_at,
        bar_sequence_id=evidence.bar_sequence_id,
        common_session_sequence_id=evidence.common_session_sequence_id,
        requested_contracts=evidence.requested_contracts,
        executed_contracts=evidence.executed_contracts,
        carry_contracts=evidence.carry_contracts,
        execution_price=evidence.execution_price,
        capacity_contracts=evidence.capacity_contracts,
        factual_window_complete=evidence.factual_window_complete,
        resolution=resolution,
        reason=reason,
        execution_evidence_sha256=evidence.evidence_sha256,
        seals=intent.seals,
        adverse_reference_price=reference,
    )


@dataclass(frozen=True, slots=True)
class StatefulUnresolvedCarry:
    """Terminal state block created by missing, partial or capacity-unknown evidence."""

    strategy_id: str
    scenario_id: V8ScenarioId
    asset_id: str
    contract_id: str
    sleeve_id: str
    reason: str
    requested_contracts: int
    executed_contracts: int
    carry_contracts: int
    observed_at: datetime
    evidence_sha256: str
    seals: StatefulSealSet
    ledger_event: StatefulLedgerEvent | None = None

    def __post_init__(self) -> None:
        if self.strategy_id not in STATEFUL_STRATEGY_IDS:
            raise ValueError("unresolved strategy is not stateful")
        object.__setattr__(self, "scenario_id", V8ScenarioId(self.scenario_id))
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("unresolved asset is outside the sealed universe")
        for name in ("contract_id", "sleeve_id"):
            object.__setattr__(self, name, _require_identifier(getattr(self, name), name))
        if not self.reason:
            raise ValueError("unresolved reason must be non-empty")
        requested = _require_nonzero_int(self.requested_contracts, "requested_contracts")
        executed = _require_int(self.executed_contracts, "executed_contracts")
        carry = _require_int(self.carry_contracts, "carry_contracts")
        if carry != requested - executed:
            raise ValueError("unresolved quantity/carry invariant is broken")
        object.__setattr__(self, "requested_contracts", requested)
        object.__setattr__(self, "executed_contracts", executed)
        object.__setattr__(self, "carry_contracts", carry)
        object.__setattr__(self, "observed_at", _require_aware(self.observed_at, "observed_at"))
        object.__setattr__(
            self,
            "evidence_sha256",
            _require_sha256(self.evidence_sha256, "evidence_sha256"),
        )
        if not isinstance(self.seals, StatefulSealSet):
            raise TypeError("seals must be StatefulSealSet")
        if self.ledger_event is not None:
            event = self.ledger_event
            if event.resolution is not StatefulResolution.UNRESOLVED:
                raise ValueError("unresolved carry cannot contain an applied ledger event")
            if (
                event.strategy_id,
                event.scenario_id,
                event.asset_id,
                event.contract_id,
                event.sleeve_id,
                event.requested_contracts,
                event.executed_contracts,
                event.carry_contracts,
                event.executed_at,
                event.execution_evidence_sha256,
                event.seals,
            ) != (
                self.strategy_id,
                self.scenario_id,
                self.asset_id,
                self.contract_id,
                self.sleeve_id,
                requested,
                executed,
                carry,
                self.observed_at,
                self.evidence_sha256,
                self.seals,
            ):
                raise ValueError("unresolved carry/ledger event mismatch")


class CorridorStatus(StrEnum):
    OPEN = "open"
    EXIT_PENDING = "exit_pending"
    CLOSED = "closed"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class CorridorEntryProtocol:
    """ATR bracket and fifth-session time slot known before entry execution."""

    intent: StatefulOrderIntent
    asset_known_at: datetime
    atr_20: float
    entry_common_session_sequence_id: int
    time_exit_window: ScenarioExecutionWindow

    def __post_init__(self) -> None:
        if self.intent.strategy_id != CORRIDOR_STRATEGY_ID:
            raise ValueError("corridor protocol strategy mismatch")
        if self.intent.action is not StatefulAction.CORRIDOR_ENTRY:
            raise ValueError("corridor protocol requires CORRIDOR_ENTRY")
        known = _require_aware(self.asset_known_at, "asset_known_at")
        if known > self.intent.decision_at:
            raise ValueError("corridor asset input was unknown at decision time")
        if self.time_exit_window.scenario_id is not self.intent.scenario_id:
            raise ValueError("corridor time-exit scenario mismatch")
        entry_session = _require_nonnegative_int(
            self.entry_common_session_sequence_id,
            "entry_common_session_sequence_id",
        )
        if self.time_exit_window.common_session_sequence_id != entry_session + 5:
            raise ValueError("corridor time exit must be the fifth following common session")
        if self.time_exit_window.closed_at <= self.intent.execution_window.closed_at:
            raise ValueError("corridor time exit must follow actual scenario entry window")
        object.__setattr__(self, "asset_known_at", known)
        object.__setattr__(self, "atr_20", _require_positive(self.atr_20, "atr_20"))
        object.__setattr__(self, "entry_common_session_sequence_id", entry_session)


@dataclass(frozen=True, slots=True)
class CorridorScenarioPosition:
    """Scenario-local bracket anchored to the scenario's actual entry fill."""

    position_id: str
    scenario_id: V8ScenarioId
    asset_id: str
    contract_id: str
    sleeve_id: str
    direction: int
    initial_contracts: int
    open_contracts: int
    entry_price: float
    take_profit: float
    stop_loss: float
    opened_at: datetime
    entry_bar_sequence_id: int
    last_bar_sequence_id: int
    last_bar_closed_at: datetime
    entry_common_session_sequence_id: int
    time_exit_window: ScenarioExecutionWindow
    entry_order_id: str
    entry_execution_evidence_sha256: str
    seals: StatefulSealSet
    status: CorridorStatus = CorridorStatus.OPEN
    pending_trigger_id: str | None = None
    pending_source_state_sha256: str | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "position_id",
            _require_identifier(self.position_id, "position_id"),
        )
        object.__setattr__(self, "scenario_id", V8ScenarioId(self.scenario_id))
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("corridor position asset is outside the sealed universe")
        for name in ("contract_id", "sleeve_id", "entry_order_id"):
            object.__setattr__(self, name, _require_identifier(getattr(self, name), name))
        if self.direction not in (-1, 1):
            raise ValueError("corridor direction must be -1 or +1")
        initial = _require_nonnegative_int(self.initial_contracts, "initial_contracts")
        opened = _require_nonnegative_int(self.open_contracts, "open_contracts")
        if initial == 0 or opened > initial:
            raise ValueError("corridor contract quantities are invalid")
        object.__setattr__(self, "initial_contracts", initial)
        object.__setattr__(self, "open_contracts", opened)
        for name in ("entry_price", "take_profit", "stop_loss"):
            object.__setattr__(self, name, _require_positive(getattr(self, name), name))
        if self.direction > 0 and not self.stop_loss < self.entry_price < self.take_profit:
            raise ValueError("long corridor bracket geometry is invalid")
        if self.direction < 0 and not self.take_profit < self.entry_price < self.stop_loss:
            raise ValueError("short corridor bracket geometry is invalid")
        opened_at = _require_aware(self.opened_at, "opened_at")
        last_closed = _require_aware(self.last_bar_closed_at, "last_bar_closed_at")
        if last_closed < opened_at:
            raise ValueError("corridor last bar precedes its entry")
        entry_bar = _require_nonnegative_int(
            self.entry_bar_sequence_id,
            "entry_bar_sequence_id",
        )
        last_bar = _require_nonnegative_int(self.last_bar_sequence_id, "last_bar_sequence_id")
        if last_bar < entry_bar:
            raise ValueError("corridor bar sequence moved backwards")
        if self.time_exit_window.scenario_id is not self.scenario_id:
            raise ValueError("corridor time-exit state scenario mismatch")
        status = CorridorStatus(self.status)
        if status is CorridorStatus.OPEN and any(
            value is not None
            for value in (
                self.pending_trigger_id,
                self.pending_source_state_sha256,
                self.exit_price,
                self.exit_reason,
                self.closed_at,
            )
        ):
            raise ValueError("open corridor state cannot contain exit fields")
        if status is CorridorStatus.EXIT_PENDING and (
            self.pending_trigger_id is None
            or self.pending_source_state_sha256 is None
            or self.exit_reason is None
        ):
            raise ValueError("pending corridor exit requires trigger identity and reason")
        if status is CorridorStatus.CLOSED and (
            opened != 0
            or self.exit_price is None
            or self.exit_reason is None
            or self.closed_at is None
        ):
            raise ValueError("closed corridor state requires factual exit")
        if status is CorridorStatus.UNRESOLVED and self.exit_reason is None:
            raise ValueError("unresolved corridor state requires a reason")
        if self.pending_trigger_id is not None:
            object.__setattr__(
                self,
                "pending_trigger_id",
                _require_identifier(self.pending_trigger_id, "pending_trigger_id"),
            )
        if self.pending_source_state_sha256 is not None:
            object.__setattr__(
                self,
                "pending_source_state_sha256",
                _require_sha256(
                    self.pending_source_state_sha256,
                    "pending_source_state_sha256",
                ),
            )
        if self.exit_price is not None:
            object.__setattr__(self, "exit_price", _require_positive(self.exit_price, "exit_price"))
        if self.closed_at is not None:
            object.__setattr__(self, "closed_at", _require_aware(self.closed_at, "closed_at"))
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "last_bar_closed_at", last_closed)
        object.__setattr__(self, "entry_bar_sequence_id", entry_bar)
        object.__setattr__(self, "last_bar_sequence_id", last_bar)
        object.__setattr__(
            self,
            "entry_common_session_sequence_id",
            _require_nonnegative_int(
                self.entry_common_session_sequence_id,
                "entry_common_session_sequence_id",
            ),
        )
        object.__setattr__(
            self,
            "entry_execution_evidence_sha256",
            _require_sha256(
                self.entry_execution_evidence_sha256,
                "entry_execution_evidence_sha256",
            ),
        )
        if not isinstance(self.seals, StatefulSealSet):
            raise TypeError("corridor position seals must be StatefulSealSet")
        object.__setattr__(self, "status", status)

    @property
    def state_sha256(self) -> str:
        return _canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class CorridorEntryTransition:
    event: StatefulLedgerEvent
    position: CorridorScenarioPosition | None
    unresolved: StatefulUnresolvedCarry | None


def _unresolved_from_event(event: StatefulLedgerEvent) -> StatefulUnresolvedCarry:
    return StatefulUnresolvedCarry(
        strategy_id=event.strategy_id,
        scenario_id=event.scenario_id,
        asset_id=event.asset_id,
        contract_id=event.contract_id,
        sleeve_id=event.sleeve_id,
        reason=event.reason,
        requested_contracts=event.requested_contracts,
        executed_contracts=event.executed_contracts,
        carry_contracts=event.carry_contracts,
        observed_at=event.executed_at,
        evidence_sha256=event.execution_evidence_sha256,
        seals=event.seals,
        ledger_event=event,
    )


def reconcile_corridor_entry(
    protocol: CorridorEntryProtocol,
    evidence: StatefulExecutionEvidence,
) -> CorridorEntryTransition:
    """Open a bracket only after a complete fill in that exact scenario window."""
    event = reconcile_order_intent(protocol.intent, evidence)
    if event.resolution is StatefulResolution.UNRESOLVED:
        return CorridorEntryTransition(event, None, _unresolved_from_event(event))
    if event.execution_price is None:
        raise RuntimeError("resolved corridor entry lost its execution price")
    direction = 1 if event.executed_contracts > 0 else -1
    entry_price = event.execution_price
    take_profit = entry_price + direction * CORRIDOR_TAKE_PROFIT_ATR * protocol.atr_20
    stop_loss = entry_price - direction * CORRIDOR_STOP_LOSS_ATR * protocol.atr_20
    position_payload = (
        f"{event.scenario_id.value}|{event.sleeve_id}|{event.asset_id}|"
        f"{event.contract_id}|{event.order_id}|{event.execution_evidence_sha256}"
    ).encode()
    position = CorridorScenarioPosition(
        position_id=f"corridor-{sha256(position_payload).hexdigest()[:24]}",
        scenario_id=event.scenario_id,
        asset_id=event.asset_id,
        contract_id=event.contract_id,
        sleeve_id=event.sleeve_id,
        direction=direction,
        initial_contracts=abs(event.executed_contracts),
        open_contracts=abs(event.executed_contracts),
        entry_price=entry_price,
        take_profit=take_profit,
        stop_loss=stop_loss,
        opened_at=event.executed_at,
        entry_bar_sequence_id=event.bar_sequence_id,
        last_bar_sequence_id=event.bar_sequence_id,
        last_bar_closed_at=event.executed_at,
        entry_common_session_sequence_id=protocol.entry_common_session_sequence_id,
        time_exit_window=protocol.time_exit_window,
        entry_order_id=event.order_id,
        entry_execution_evidence_sha256=event.execution_evidence_sha256,
        seals=event.seals,
    )
    return CorridorEntryTransition(event, position, None)


@dataclass(frozen=True, slots=True)
class ScenarioFactualBar:
    """A complete bar used only after it closed; it never enters the D signal."""

    scenario_id: V8ScenarioId
    asset_id: str
    contract_id: str
    bar_sequence_id: int
    common_session_sequence_id: int
    opened_at: datetime
    closed_at: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    observed_at: datetime
    calendar_sha256: str
    contract_sha256: str
    market_evidence_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario_id", V8ScenarioId(self.scenario_id))
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("bar asset is outside the sealed universe")
        object.__setattr__(
            self,
            "contract_id",
            _require_identifier(self.contract_id, "contract_id"),
        )
        object.__setattr__(
            self,
            "bar_sequence_id",
            _require_nonnegative_int(self.bar_sequence_id, "bar_sequence_id"),
        )
        object.__setattr__(
            self,
            "common_session_sequence_id",
            _require_nonnegative_int(
                self.common_session_sequence_id,
                "common_session_sequence_id",
            ),
        )
        opened = _require_aware(self.opened_at, "opened_at")
        closed = _require_aware(self.closed_at, "closed_at")
        observed = _require_aware(self.observed_at, "observed_at")
        if closed - opened != TEN_MINUTES or observed < closed:
            raise ValueError("bar must be a fully observed 10-minute window")
        prices = {}
        for name in ("open_price", "high_price", "low_price", "close_price"):
            prices[name] = _require_positive(getattr(self, name), name)
            object.__setattr__(self, name, prices[name])
        if prices["high_price"] < max(prices["open_price"], prices["close_price"]):
            raise ValueError("bar high violates OHLC")
        if prices["low_price"] > min(prices["open_price"], prices["close_price"]):
            raise ValueError("bar low violates OHLC")
        object.__setattr__(self, "volume", _require_nonnegative_int(self.volume, "volume"))
        object.__setattr__(self, "opened_at", opened)
        object.__setattr__(self, "closed_at", closed)
        object.__setattr__(self, "observed_at", observed)
        for name in ("calendar_sha256", "contract_sha256", "market_evidence_sha256"):
            object.__setattr__(self, name, _require_sha256(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class CorridorExitTrigger:
    """Predeclared bracket trigger derived from one fully closed factual bar."""

    trigger_id: str
    position_state_sha256: str
    action: StatefulAction
    reason: str
    requested_contracts: int
    adverse_reference_price: float
    trigger_window: ScenarioExecutionWindow
    trigger_volume: int
    factual_open: float
    factual_high: float
    factual_low: float
    factual_close: float
    market_evidence_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "trigger_id", _require_identifier(self.trigger_id, "trigger_id"))
        object.__setattr__(
            self,
            "position_state_sha256",
            _require_sha256(self.position_state_sha256, "position_state_sha256"),
        )
        action = StatefulAction(self.action)
        if action not in _CORRIDOR_ACTIONS - {StatefulAction.CORRIDOR_ENTRY}:
            raise ValueError("corridor trigger has a non-exit action")
        object.__setattr__(self, "action", action)
        if not self.reason:
            raise ValueError("corridor trigger reason must be non-empty")
        object.__setattr__(
            self,
            "requested_contracts",
            _require_nonzero_int(self.requested_contracts, "requested_contracts"),
        )
        object.__setattr__(
            self,
            "adverse_reference_price",
            _require_positive(self.adverse_reference_price, "adverse_reference_price"),
        )
        object.__setattr__(
            self,
            "trigger_volume",
            _require_nonnegative_int(self.trigger_volume, "trigger_volume"),
        )
        for name in ("factual_open", "factual_high", "factual_low", "factual_close"):
            object.__setattr__(self, name, _require_positive(getattr(self, name), name))
        if self.factual_high < max(self.factual_open, self.factual_close):
            raise ValueError("corridor trigger high violates OHLC")
        if self.factual_low > min(self.factual_open, self.factual_close):
            raise ValueError("corridor trigger low violates OHLC")
        object.__setattr__(
            self,
            "market_evidence_sha256",
            _require_sha256(self.market_evidence_sha256, "market_evidence_sha256"),
        )


@dataclass(frozen=True, slots=True)
class CorridorBarTransition:
    position: CorridorScenarioPosition
    trigger: CorridorExitTrigger | None = None
    unresolved: StatefulUnresolvedCarry | None = None


def _missing_corridor_state(
    position: CorridorScenarioPosition,
    *,
    reason: str,
    observed_at: datetime,
    evidence_sha256: str,
) -> CorridorBarTransition:
    unresolved_position = replace(
        position,
        status=CorridorStatus.UNRESOLVED,
        exit_reason=reason,
    )
    unresolved = StatefulUnresolvedCarry(
        strategy_id=CORRIDOR_STRATEGY_ID,
        scenario_id=position.scenario_id,
        asset_id=position.asset_id,
        contract_id=position.contract_id,
        sleeve_id=position.sleeve_id,
        reason=reason,
        requested_contracts=-position.direction * position.open_contracts,
        executed_contracts=0,
        carry_contracts=-position.direction * position.open_contracts,
        observed_at=observed_at,
        evidence_sha256=evidence_sha256,
        seals=position.seals,
    )
    return CorridorBarTransition(unresolved_position, unresolved=unresolved)


def transition_corridor_bar(
    position: CorridorScenarioPosition,
    bar: ScenarioFactualBar,
) -> CorridorBarTransition:
    """Apply stop-first OHLC logic and the exact fifth-session time exit."""
    if position.status is not CorridorStatus.OPEN:
        raise ValueError("only an open corridor position can observe a bar")
    if (
        bar.scenario_id is not position.scenario_id
        or bar.asset_id != position.asset_id
        or bar.contract_id != position.contract_id
        or bar.calendar_sha256 != position.seals.calendar_sha256
        or bar.contract_sha256 != position.seals.contract_sha256
    ):
        raise ValueError("corridor bar identity or seal mismatch")
    if bar.bar_sequence_id != position.last_bar_sequence_id + 1:
        return _missing_corridor_state(
            position,
            reason="missing_expected_factual_bar",
            observed_at=bar.observed_at,
            evidence_sha256=bar.market_evidence_sha256,
        )
    if bar.opened_at < position.last_bar_closed_at or bar.closed_at <= position.last_bar_closed_at:
        raise ValueError("corridor bar chronology is invalid")
    time_slot = position.time_exit_window
    if bar.bar_sequence_id > time_slot.bar_sequence_id or bar.closed_at > time_slot.closed_at:
        return _missing_corridor_state(
            position,
            reason="missing_scheduled_fifth_session_window",
            observed_at=bar.observed_at,
            evidence_sha256=bar.market_evidence_sha256,
        )
    scheduled = bar.bar_sequence_id == time_slot.bar_sequence_id
    if scheduled and (
        bar.common_session_sequence_id != time_slot.common_session_sequence_id
        or bar.opened_at != time_slot.opened_at
        or bar.closed_at != time_slot.closed_at
    ):
        return _missing_corridor_state(
            position,
            reason="scheduled_fifth_session_window_mismatch",
            observed_at=bar.observed_at,
            evidence_sha256=bar.market_evidence_sha256,
        )
    if position.direction > 0:
        stop_touched = bar.low_price <= position.stop_loss
        take_touched = bar.high_price >= position.take_profit
        stop_reference = min(bar.open_price, position.stop_loss)
        time_reference = bar.low_price
    else:
        stop_touched = bar.high_price >= position.stop_loss
        take_touched = bar.low_price <= position.take_profit
        stop_reference = max(bar.open_price, position.stop_loss)
        time_reference = bar.high_price
    if stop_touched:
        action = StatefulAction.CORRIDOR_EXIT_STOP
        reason = "stop_loss_ambiguous_bar_adverse_first" if take_touched else "stop_loss"
        reference = stop_reference
    elif take_touched:
        action = StatefulAction.CORRIDOR_EXIT_TAKE_PROFIT
        reason = "take_profit"
        reference = position.take_profit
    elif scheduled:
        action = StatefulAction.CORRIDOR_EXIT_TIME
        reason = "scheduled_fifth_session_adverse_window_exit"
        reference = time_reference
    else:
        return CorridorBarTransition(
            replace(
                position,
                last_bar_sequence_id=bar.bar_sequence_id,
                last_bar_closed_at=bar.closed_at,
            )
        )
    window = ScenarioExecutionWindow(
        position.scenario_id,
        bar.bar_sequence_id,
        bar.common_session_sequence_id,
        bar.opened_at,
        bar.closed_at,
    )
    source_state_sha256 = position.state_sha256
    trigger_payload = (
        f"{source_state_sha256}|{action.value}|{bar.bar_sequence_id}|"
        f"{bar.market_evidence_sha256}"
    ).encode()
    trigger = CorridorExitTrigger(
        trigger_id=f"corridor-trigger-{sha256(trigger_payload).hexdigest()[:24]}",
        position_state_sha256=source_state_sha256,
        action=action,
        reason=reason,
        requested_contracts=-position.direction * position.open_contracts,
        adverse_reference_price=reference,
        trigger_window=window,
        trigger_volume=bar.volume,
        factual_open=bar.open_price,
        factual_high=bar.high_price,
        factual_low=bar.low_price,
        factual_close=bar.close_price,
        market_evidence_sha256=bar.market_evidence_sha256,
    )
    pending = replace(
        position,
        last_bar_sequence_id=bar.bar_sequence_id,
        last_bar_closed_at=bar.closed_at,
        status=CorridorStatus.EXIT_PENDING,
        pending_trigger_id=trigger.trigger_id,
        pending_source_state_sha256=source_state_sha256,
        exit_reason=reason,
    )
    return CorridorBarTransition(pending, trigger=trigger)


@dataclass(frozen=True, slots=True)
class MissingBarEvidence:
    """Evidence that an exact calendar slot remained absent after its close."""

    scenario_id: V8ScenarioId
    asset_id: str
    contract_id: str
    expected_window: ScenarioExecutionWindow
    observed_through: datetime
    calendar_sha256: str
    contract_sha256: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        scenario = V8ScenarioId(self.scenario_id)
        object.__setattr__(self, "scenario_id", scenario)
        if self.expected_window.scenario_id is not scenario:
            raise ValueError("missing-bar scenario mismatch")
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("missing-bar asset is outside sealed universe")
        object.__setattr__(
            self,
            "contract_id",
            _require_identifier(self.contract_id, "contract_id"),
        )
        observed = _require_aware(self.observed_through, "observed_through")
        if observed <= self.expected_window.closed_at:
            raise ValueError("bar absence is factual only after the expected window")
        object.__setattr__(self, "observed_through", observed)
        for name in ("calendar_sha256", "contract_sha256", "evidence_sha256"):
            object.__setattr__(self, name, _require_sha256(getattr(self, name), name))


def mark_corridor_missing_bar(
    position: CorridorScenarioPosition,
    evidence: MissingBarEvidence,
) -> CorridorBarTransition:
    """Block the position instead of crossing a missing expected 10-minute bar."""
    if position.status is not CorridorStatus.OPEN:
        raise ValueError("only an open corridor position can be marked missing")
    if (
        evidence.scenario_id is not position.scenario_id
        or evidence.asset_id != position.asset_id
        or evidence.contract_id != position.contract_id
        or evidence.calendar_sha256 != position.seals.calendar_sha256
        or evidence.contract_sha256 != position.seals.contract_sha256
        or evidence.expected_window.bar_sequence_id != position.last_bar_sequence_id + 1
        or evidence.expected_window.opened_at < position.last_bar_closed_at
    ):
        raise ValueError("missing-bar evidence does not match next corridor slot")
    reason = (
        "missing_scheduled_fifth_session_window"
        if evidence.expected_window == position.time_exit_window
        else "missing_expected_factual_bar"
    )
    return _missing_corridor_state(
        position,
        reason=reason,
        observed_at=evidence.observed_through,
        evidence_sha256=evidence.evidence_sha256,
    )


@dataclass(frozen=True, slots=True)
class CorridorExitTransition:
    event: StatefulLedgerEvent
    position: CorridorScenarioPosition
    unresolved: StatefulUnresolvedCarry | None


def reconcile_corridor_exit(
    position: CorridorScenarioPosition,
    trigger: CorridorExitTrigger,
    intent: StatefulOrderIntent,
    evidence: StatefulExecutionEvidence,
) -> CorridorExitTransition:
    """Close only on full factual exit; delayed scenarios use their later window."""
    if position.status is not CorridorStatus.EXIT_PENDING:
        raise ValueError("corridor exit requires EXIT_PENDING state")
    if position.pending_trigger_id != trigger.trigger_id:
        raise ValueError("corridor trigger identity mismatch")
    if position.pending_source_state_sha256 != trigger.position_state_sha256:
        raise ValueError("corridor trigger source-state seal mismatch")
    if (
        intent.strategy_id != CORRIDOR_STRATEGY_ID
        or intent.action is not trigger.action
        or intent.scenario_id is not position.scenario_id
        or intent.asset_id != position.asset_id
        or intent.contract_id != position.contract_id
        or intent.sleeve_id != position.sleeve_id
        or intent.requested_contracts != trigger.requested_contracts
        or intent.seals != position.seals
    ):
        raise ValueError("corridor exit intent does not match position/trigger")
    if position.scenario_id in (V8ScenarioId.PRIMARY, V8ScenarioId.DOUBLE_COST):
        if intent.execution_window != trigger.trigger_window:
            raise ValueError("primary/double corridor exit must use its trigger window")
        if (
            evidence.factual_open,
            evidence.factual_high,
            evidence.factual_low,
            evidence.factual_close,
            evidence.factual_volume,
        ) != (
            trigger.factual_open,
            trigger.factual_high,
            trigger.factual_low,
            trigger.factual_close,
            trigger.trigger_volume,
        ):
            raise ValueError("corridor trigger/execution factual bar mismatch")
    elif (
        intent.execution_window.bar_sequence_id != trigger.trigger_window.bar_sequence_id + 1
        or intent.execution_window.opened_at < trigger.trigger_window.closed_at
    ):
        raise ValueError("delay corridor exit must use the next complete factual window")
    event = reconcile_order_intent(
        intent,
        evidence,
        adverse_reference_price=trigger.adverse_reference_price,
    )
    if event.executed_contracts and event.execution_price is not None:
        if (
            event.requested_contracts < 0
            and event.execution_price > trigger.adverse_reference_price
        ):
            raise ValueError("long corridor exit is better than adverse reference")
        if (
            event.requested_contracts > 0
            and event.execution_price < trigger.adverse_reference_price
        ):
            raise ValueError("short corridor exit is better than adverse reference")
    if event.resolution is StatefulResolution.UNRESOLVED:
        unresolved_position = replace(
            position,
            status=CorridorStatus.UNRESOLVED,
            pending_trigger_id=None,
            pending_source_state_sha256=None,
            exit_reason=event.reason,
        )
        return CorridorExitTransition(event, unresolved_position, _unresolved_from_event(event))
    if event.execution_price is None:
        raise RuntimeError("resolved corridor exit lost its execution price")
    closed = replace(
        position,
        open_contracts=0,
        last_bar_sequence_id=event.bar_sequence_id,
        last_bar_closed_at=event.executed_at,
        status=CorridorStatus.CLOSED,
        pending_trigger_id=None,
        pending_source_state_sha256=None,
        exit_price=event.execution_price,
        exit_reason=trigger.reason,
        closed_at=event.executed_at,
    )
    return CorridorExitTransition(event, closed, None)


@dataclass(frozen=True, slots=True)
class BreakoutAssetState:
    """Filled breakout exposure with a monotone trailing extreme."""

    asset_id: str
    contract_id: str
    sleeve_id: str
    direction: int
    pyramid_level: int
    open_contracts: int
    extreme_close: float
    last_order_id: str
    last_execution_at: datetime
    last_execution_evidence_sha256: str
    seals: StatefulSealSet

    def __post_init__(self) -> None:
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("breakout asset is outside sealed universe")
        for name in ("contract_id", "sleeve_id", "last_order_id"):
            object.__setattr__(self, name, _require_identifier(getattr(self, name), name))
        if self.direction not in (-1, 1):
            raise ValueError("breakout direction must be -1 or +1")
        level = _require_nonnegative_int(self.pyramid_level, "pyramid_level")
        if not 1 <= level <= BREAKOUT_PYRAMID_LEVELS:
            raise ValueError("breakout pyramid level is outside fixed range")
        contracts = _require_nonnegative_int(self.open_contracts, "open_contracts")
        if contracts == 0:
            raise ValueError("filled breakout state requires open contracts")
        object.__setattr__(self, "pyramid_level", level)
        object.__setattr__(self, "open_contracts", contracts)
        object.__setattr__(
            self,
            "extreme_close",
            _require_positive(self.extreme_close, "extreme_close"),
        )
        object.__setattr__(
            self,
            "last_execution_at",
            _require_aware(self.last_execution_at, "last_execution_at"),
        )
        object.__setattr__(
            self,
            "last_execution_evidence_sha256",
            _require_sha256(
                self.last_execution_evidence_sha256,
                "last_execution_evidence_sha256",
            ),
        )
        if not isinstance(self.seals, StatefulSealSet):
            raise TypeError("seals must be StatefulSealSet")


@dataclass(frozen=True, slots=True)
class BreakoutLockedPosition:
    """Carry-only audit marker for an invalid input with prior filled exposure."""

    state: BreakoutAssetState
    decision_at: datetime
    reason_codes: tuple[str, ...]
    prediction_sha256: str
    input_bundle_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, BreakoutAssetState):
            raise TypeError("locked state must be BreakoutAssetState")
        decision = _require_aware(self.decision_at, "decision_at")
        if decision <= self.state.last_execution_at:
            raise ValueError("locked decision must follow the factual fill")
        reasons = tuple(sorted(set(self.reason_codes)))
        if not reasons or any(
            not isinstance(reason, str) or not reason or reason.strip() != reason
            for reason in reasons
        ):
            raise ValueError("locked position requires explicit reason codes")
        object.__setattr__(self, "decision_at", decision)
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(
            self,
            "prediction_sha256",
            _require_sha256(self.prediction_sha256, "prediction_sha256"),
        )
        object.__setattr__(
            self,
            "input_bundle_sha256",
            _require_sha256(self.input_bundle_sha256, "input_bundle_sha256"),
        )


@dataclass(frozen=True, slots=True)
class BreakoutScenarioState:
    """Independent filled state for exactly one execution stress scenario."""

    scenario_id: V8ScenarioId
    calendar_sha256: str
    assets: tuple[BreakoutAssetState, ...] = ()
    unresolved: tuple[StatefulUnresolvedCarry, ...] = ()
    last_decision_at: datetime | None = None
    locked_positions: tuple[BreakoutLockedPosition, ...] = ()

    def __post_init__(self) -> None:
        scenario = V8ScenarioId(self.scenario_id)
        calendar = _require_sha256(self.calendar_sha256, "calendar_sha256")
        assets = tuple(sorted(self.assets, key=lambda item: item.asset_id))
        unresolved = tuple(sorted(self.unresolved, key=lambda item: item.asset_id))
        if len({item.asset_id for item in assets}) != len(assets):
            raise ValueError("breakout state contains duplicate asset")
        if len({item.asset_id for item in unresolved}) != len(unresolved):
            raise ValueError("breakout state contains duplicate unresolved asset")
        locked = tuple(sorted(self.locked_positions, key=lambda item: item.state.asset_id))
        if len({item.state.asset_id for item in locked}) != len(locked):
            raise ValueError("breakout state contains duplicate locked asset")
        if {item.state.asset_id for item in locked} - {item.asset_id for item in assets}:
            raise ValueError("locked breakout marker must preserve a filled asset")
        if {item.asset_id for item in unresolved} & {item.state.asset_id for item in locked}:
            raise ValueError("breakout asset cannot be unresolved and locked")
        if any(item.scenario_id is not scenario for item in unresolved):
            raise ValueError("breakout unresolved scenario mismatch")
        if any(item.seals.calendar_sha256 != calendar for item in assets):
            raise ValueError("breakout asset calendar seal mismatch")
        if self.last_decision_at is not None:
            object.__setattr__(
                self,
                "last_decision_at",
                _require_aware(self.last_decision_at, "last_decision_at"),
            )
        object.__setattr__(self, "scenario_id", scenario)
        object.__setattr__(self, "calendar_sha256", calendar)
        object.__setattr__(self, "assets", assets)
        object.__setattr__(self, "unresolved", unresolved)
        object.__setattr__(self, "locked_positions", locked)

    @classmethod
    def create(
        cls,
        scenario_id: V8ScenarioId | str,
        calendar_sha256: str,
    ) -> BreakoutScenarioState:
        return cls(V8ScenarioId(scenario_id), calendar_sha256)

    @property
    def state_sha256(self) -> str:
        return _canonical_sha256(self)


def assert_exact_scenario_partition(states: Sequence[BreakoutScenarioState]) -> None:
    """Require three distinct state objects in fixed primary/double/delay order."""
    frozen = tuple(states)
    if tuple(item.scenario_id for item in frozen) != (
        V8ScenarioId.PRIMARY,
        V8ScenarioId.DOUBLE_COST,
        V8ScenarioId.DELAY,
    ):
        raise ValueError("state partition must be exact primary, double_cost, delay order")
    if len({id(item) for item in frozen}) != 3:
        raise ValueError("scenario state objects must not be shared")
    if len({item.calendar_sha256 for item in frozen}) != 1:
        raise ValueError("scenario states must share one calendar seal")


@dataclass(frozen=True, slots=True)
class BreakoutDecisionObservation:
    """Causal per-asset close and direction available at one decision timestamp."""

    decision_at: datetime
    known_at: datetime
    asset_id: str
    contract_id: str
    sleeve_id: str
    close_price: float | None
    atr_20: float | None
    breakout_direction: int
    input_valid: bool
    seals: StatefulSealSet
    invalid_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        decision = _require_aware(self.decision_at, "decision_at")
        known = _require_aware(self.known_at, "known_at")
        if known > decision:
            raise ValueError("breakout observation was unknown at decision time")
        if self.asset_id not in V8_ASSET_IDS:
            raise ValueError("breakout observation asset is outside sealed universe")
        for name in ("contract_id", "sleeve_id"):
            object.__setattr__(self, name, _require_identifier(getattr(self, name), name))
        if not isinstance(self.input_valid, bool):
            raise TypeError("input_valid must be bool")
        if self.breakout_direction not in (-1, 0, 1):
            raise ValueError("breakout_direction must be -1, 0 or +1")
        if self.input_valid:
            if self.close_price is None or self.atr_20 is None:
                raise ValueError("valid breakout observation requires close and ATR")
            object.__setattr__(
                self,
                "close_price",
                _require_positive(self.close_price, "close_price"),
            )
            object.__setattr__(self, "atr_20", _require_positive(self.atr_20, "atr_20"))
            if self.invalid_reason_codes:
                raise ValueError("valid breakout observation cannot have invalid reasons")
        elif any(value is not None for value in (self.close_price, self.atr_20)):
            raise ValueError("invalid breakout observation must not smuggle market values")
        reasons = tuple(sorted(set(self.invalid_reason_codes)))
        if not self.input_valid and (
            not reasons
            or any(
                not isinstance(reason, str) or not reason or reason.strip() != reason
                for reason in reasons
            )
        ):
            raise ValueError("invalid breakout observation requires explicit reason codes")
        if not isinstance(self.seals, StatefulSealSet):
            raise TypeError("seals must be StatefulSealSet")
        object.__setattr__(self, "decision_at", decision)
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "invalid_reason_codes", reasons)


@dataclass(frozen=True, slots=True)
class BreakoutProposal:
    """Pure decision-time proposal; it contains no later execution outcome."""

    prior_state_sha256: str
    observation: BreakoutDecisionObservation
    action: StatefulAction | None
    prior_direction: int
    prior_level: int
    prior_open_contracts: int
    desired_direction: int
    desired_level: int
    next_extreme_close: float | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prior_state_sha256",
            _require_sha256(self.prior_state_sha256, "prior_state_sha256"),
        )
        if self.action is not None:
            action = StatefulAction(self.action)
            if action not in _BREAKOUT_ACTIONS:
                raise ValueError("breakout proposal contains a non-breakout action")
            object.__setattr__(self, "action", action)
        if self.prior_direction not in (-1, 0, 1) or self.desired_direction not in (-1, 0, 1):
            raise ValueError("breakout proposal direction is invalid")
        if not 0 <= self.prior_level <= BREAKOUT_PYRAMID_LEVELS:
            raise ValueError("breakout prior level is invalid")
        prior_contracts = _require_nonnegative_int(
            self.prior_open_contracts,
            "prior_open_contracts",
        )
        if (self.prior_level == 0) != (prior_contracts == 0):
            raise ValueError("breakout prior level/contracts geometry is invalid")
        object.__setattr__(self, "prior_open_contracts", prior_contracts)
        if not 0 <= self.desired_level <= BREAKOUT_PYRAMID_LEVELS:
            raise ValueError("breakout desired level is invalid")
        if self.next_extreme_close is not None:
            object.__setattr__(
                self,
                "next_extreme_close",
                _require_positive(self.next_extreme_close, "next_extreme_close"),
            )


def propose_breakout_transition(
    state: BreakoutScenarioState,
    observation: BreakoutDecisionObservation,
) -> BreakoutProposal:
    """Compute enter/add/exit intent while preserving filled state until evidence."""
    if observation.seals.calendar_sha256 != state.calendar_sha256:
        raise ValueError("breakout observation calendar seal mismatch")
    if state.last_decision_at is not None and observation.decision_at <= state.last_decision_at:
        raise ValueError("breakout decisions must be strictly chronological")
    if any(item.asset_id == observation.asset_id for item in state.unresolved):
        previous = next(
            (item for item in state.assets if item.asset_id == observation.asset_id),
            None,
        )
        return BreakoutProposal(
            state.state_sha256,
            observation,
            None,
            previous.direction if previous else 0,
            previous.pyramid_level if previous else 0,
            previous.open_contracts if previous else 0,
            previous.direction if previous else 0,
            previous.pyramid_level if previous else 0,
            previous.extreme_close if previous else None,
        )
    previous = next((item for item in state.assets if item.asset_id == observation.asset_id), None)
    if previous is not None and (
        previous.contract_id != observation.contract_id
        or previous.sleeve_id != observation.sleeve_id
        or previous.seals.contract_sha256 != observation.seals.contract_sha256
        or previous.seals.sleeve_sha256 != observation.seals.sleeve_sha256
    ):
        raise ValueError("breakout persistent contract/sleeve identity drift")
    if not observation.input_valid:
        return BreakoutProposal(
            state.state_sha256,
            observation,
            None,
            previous.direction if previous else 0,
            previous.pyramid_level if previous else 0,
            previous.open_contracts if previous else 0,
            previous.direction if previous else 0,
            previous.pyramid_level if previous else 0,
            previous.extreme_close if previous else None,
        )
    if observation.close_price is None or observation.atr_20 is None:
        raise RuntimeError("valid observation lost close/ATR")
    if previous is None:
        action = (
            StatefulAction.BREAKOUT_ENTER if observation.breakout_direction else None
        )
        return BreakoutProposal(
            state.state_sha256,
            observation,
            action,
            0,
            0,
            0,
            observation.breakout_direction if action else 0,
            1 if action else 0,
            observation.close_price if action else None,
        )
    next_extreme = (
        max(previous.extreme_close, observation.close_price)
        if previous.direction > 0
        else min(previous.extreme_close, observation.close_price)
    )
    stopped = (
        previous.direction > 0
        and observation.close_price
        <= next_extreme - BREAKOUT_TRAILING_STOP_ATR * observation.atr_20
    ) or (
        previous.direction < 0
        and observation.close_price
        >= next_extreme + BREAKOUT_TRAILING_STOP_ATR * observation.atr_20
    )
    if stopped:
        action = StatefulAction.BREAKOUT_EXIT_TRAIL
        desired_direction = 0
        desired_level = 0
    elif observation.breakout_direction and observation.breakout_direction != previous.direction:
        action = StatefulAction.BREAKOUT_EXIT_REVERSAL
        desired_direction = 0
        desired_level = 0
    elif (
        observation.breakout_direction == previous.direction
        and previous.pyramid_level < BREAKOUT_PYRAMID_LEVELS
    ):
        action = StatefulAction.BREAKOUT_ADD
        desired_direction = previous.direction
        desired_level = previous.pyramid_level + 1
    else:
        action = None
        desired_direction = previous.direction
        desired_level = previous.pyramid_level
    return BreakoutProposal(
        state.state_sha256,
        observation,
        action,
        previous.direction,
        previous.pyramid_level,
        previous.open_contracts,
        desired_direction,
        desired_level,
        next_extreme,
    )


def advance_breakout_observation(
    state: BreakoutScenarioState,
    proposal: BreakoutProposal,
) -> BreakoutScenarioState:
    """Commit only a no-order causal observation, such as HOLD or invalid input."""
    if proposal.prior_state_sha256 != state.state_sha256:
        raise ValueError("breakout proposal was built from another state")
    if proposal.action is not None:
        raise ValueError("execution action cannot advance without factual evidence")
    observation = proposal.observation
    assets = {item.asset_id: item for item in state.assets}
    previous = assets.get(observation.asset_id)
    locked = {item.state.asset_id: item for item in state.locked_positions}
    if not observation.input_valid and previous is not None:
        locked[observation.asset_id] = BreakoutLockedPosition(
            state=previous,
            decision_at=observation.decision_at,
            reason_codes=observation.invalid_reason_codes,
            prediction_sha256=observation.seals.prediction_sha256,
            input_bundle_sha256=observation.seals.input_bundle_sha256,
        )
    elif observation.input_valid:
        locked.pop(observation.asset_id, None)
    if previous is not None and observation.input_valid:
        if proposal.next_extreme_close is None:
            raise RuntimeError("valid breakout HOLD lost its trailing extreme")
        assets[observation.asset_id] = replace(
            previous,
            extreme_close=proposal.next_extreme_close,
        )
    return BreakoutScenarioState(
        state.scenario_id,
        state.calendar_sha256,
        tuple(assets.values()),
        state.unresolved,
        observation.decision_at,
        tuple(locked.values()),
    )


@dataclass(frozen=True, slots=True)
class PendingBreakoutTransition:
    proposal: BreakoutProposal
    intent: StatefulOrderIntent


def bind_breakout_order(
    proposal: BreakoutProposal,
    intent: StatefulOrderIntent,
) -> PendingBreakoutTransition:
    """Bind a pure proposal to its independently sealed scenario order schedule."""
    if proposal.action is None:
        raise ValueError("breakout HOLD/invalid proposal has no order")
    observation = proposal.observation
    if (
        intent.strategy_id != BREAKOUT_STRATEGY_ID
        or intent.action is not proposal.action
        or intent.decision_at != observation.decision_at
        or intent.asset_id != observation.asset_id
        or intent.contract_id != observation.contract_id
        or intent.sleeve_id != observation.sleeve_id
        or intent.seals != observation.seals
    ):
        raise ValueError("breakout order does not match the causal proposal")
    expected_sign = (
        proposal.desired_direction
        if proposal.action in (StatefulAction.BREAKOUT_ENTER, StatefulAction.BREAKOUT_ADD)
        else -proposal.prior_direction
    )
    if (1 if intent.requested_contracts > 0 else -1) != expected_sign:
        raise ValueError("breakout requested direction does not match proposal")
    if proposal.action in (
        StatefulAction.BREAKOUT_EXIT_TRAIL,
        StatefulAction.BREAKOUT_EXIT_REVERSAL,
    ) and abs(intent.requested_contracts) != proposal.prior_open_contracts:
        raise ValueError("breakout exit request must flatten all factual contracts")
    return PendingBreakoutTransition(proposal, intent)


@dataclass(frozen=True, slots=True)
class BreakoutExecutionTransition:
    state: BreakoutScenarioState
    event: StatefulLedgerEvent
    unresolved: StatefulUnresolvedCarry | None


def reconcile_breakout_execution(
    state: BreakoutScenarioState,
    pending: PendingBreakoutTransition,
    evidence: StatefulExecutionEvidence,
) -> BreakoutExecutionTransition:
    """Advance direction/level only after a full, capacity-proven factual fill."""
    proposal = pending.proposal
    if proposal.prior_state_sha256 != state.state_sha256:
        raise ValueError("breakout pending transition was built from another state")
    if pending.intent.scenario_id is not state.scenario_id:
        raise ValueError("breakout intent/state scenario mismatch")
    event = reconcile_order_intent(pending.intent, evidence)
    observation = proposal.observation
    assets = {item.asset_id: item for item in state.assets}
    previous = assets.get(observation.asset_id)
    if event.resolution is StatefulResolution.UNRESOLVED:
        unresolved = _unresolved_from_event(event)
        unresolved_by_asset = {item.asset_id: item for item in state.unresolved}
        unresolved_by_asset[unresolved.asset_id] = unresolved
        return BreakoutExecutionTransition(
            BreakoutScenarioState(
                state.scenario_id,
                state.calendar_sha256,
                state.assets,
                tuple(unresolved_by_asset.values()),
                observation.decision_at,
                tuple(
                    item
                    for item in state.locked_positions
                    if item.state.asset_id != observation.asset_id
                ),
            ),
            event,
            unresolved,
        )
    if proposal.next_extreme_close is None or event.execution_price is None:
        raise RuntimeError("resolved breakout transition lost required factual values")
    if proposal.action is StatefulAction.BREAKOUT_ENTER:
        if previous is not None:
            raise ValueError("breakout ENTER found an existing filled state")
        assets[observation.asset_id] = BreakoutAssetState(
            asset_id=observation.asset_id,
            contract_id=observation.contract_id,
            sleeve_id=observation.sleeve_id,
            direction=proposal.desired_direction,
            pyramid_level=proposal.desired_level,
            open_contracts=abs(event.executed_contracts),
            extreme_close=proposal.next_extreme_close,
            last_order_id=event.order_id,
            last_execution_at=event.executed_at,
            last_execution_evidence_sha256=event.execution_evidence_sha256,
            seals=event.seals,
        )
    elif proposal.action is StatefulAction.BREAKOUT_ADD:
        if previous is None:
            raise ValueError("breakout ADD has no prior filled state")
        assets[observation.asset_id] = replace(
            previous,
            pyramid_level=proposal.desired_level,
            open_contracts=previous.open_contracts + abs(event.executed_contracts),
            extreme_close=proposal.next_extreme_close,
            last_order_id=event.order_id,
            last_execution_at=event.executed_at,
            last_execution_evidence_sha256=event.execution_evidence_sha256,
            seals=event.seals,
        )
    else:
        if previous is None:
            raise ValueError("breakout exit has no prior filled state")
        if abs(event.executed_contracts) != previous.open_contracts:
            raise ValueError("full breakout exit must flatten all factual contracts")
        assets.pop(observation.asset_id)
    unresolved_by_asset = {item.asset_id: item for item in state.unresolved}
    unresolved_by_asset.pop(observation.asset_id, None)
    return BreakoutExecutionTransition(
        BreakoutScenarioState(
            state.scenario_id,
            state.calendar_sha256,
            tuple(assets.values()),
            tuple(unresolved_by_asset.values()),
            observation.decision_at,
            tuple(
                item
                for item in state.locked_positions
                if item.state.asset_id != observation.asset_id
            ),
        ),
        event,
        None,
    )


__all__ = [
    "BREAKOUT_STRATEGY_ID",
    "CORRIDOR_STRATEGY_ID",
    "STATEFUL_STRATEGY_IDS",
    "BreakoutAssetState",
    "BreakoutDecisionObservation",
    "BreakoutExecutionTransition",
    "BreakoutLockedPosition",
    "BreakoutProposal",
    "BreakoutScenarioState",
    "CorridorBarTransition",
    "CorridorEntryProtocol",
    "CorridorEntryTransition",
    "CorridorExitTransition",
    "CorridorExitTrigger",
    "CorridorScenarioPosition",
    "CorridorStatus",
    "ExactScenarioExecutionWindows",
    "MissingBarEvidence",
    "PendingBreakoutTransition",
    "ScenarioExecutionWindow",
    "ScenarioFactualBar",
    "StatefulAction",
    "StatefulExecutionEvidence",
    "StatefulLedgerEvent",
    "StatefulOrderIntent",
    "StatefulResolution",
    "StatefulSealSet",
    "StatefulUnresolvedCarry",
    "advance_breakout_observation",
    "assert_exact_scenario_partition",
    "bind_breakout_order",
    "mark_corridor_missing_bar",
    "propose_breakout_transition",
    "reconcile_breakout_execution",
    "reconcile_corridor_entry",
    "reconcile_corridor_exit",
    "reconcile_order_intent",
    "transition_corridor_bar",
]
