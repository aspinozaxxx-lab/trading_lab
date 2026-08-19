"""Pure competing-risk labels for the predeclared five-session corridor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Final

PROTECTED_HOLDOUT_AT: Final[datetime] = datetime(2026, 1, 1, tzinfo=UTC)


class Direction(StrEnum):
    """Position direction."""

    LONG = "long"
    SHORT = "short"


class CorridorEvent(StrEnum):
    """First observed competing event."""

    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TIME_EXIT = "time_exit"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class CorridorSpec:
    """One predeclared ATR corridor."""

    take_profit_atr: float
    stop_loss_atr: float

    def __post_init__(self) -> None:
        if not (
            isfinite(self.take_profit_atr)
            and isfinite(self.stop_loss_atr)
            and self.take_profit_atr > 0.0
            and self.stop_loss_atr > 0.0
        ):
            raise ValueError("corridor multipliers must be finite and positive")

    @property
    def nominal_break_even_win_rate(self) -> float:
        return self.stop_loss_atr / (self.take_profit_atr + self.stop_loss_atr)


@dataclass(frozen=True, slots=True)
class PriceBar:
    """One completed factual ten-minute OHLCV bar."""

    opened_at: datetime
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.opened_at.tzinfo is None or self.closed_at.tzinfo is None:
            raise ValueError("bar timestamps must be timezone-aware")
        opened = self.opened_at.astimezone(UTC)
        closed = self.closed_at.astimezone(UTC)
        if closed - opened != timedelta(minutes=10):
            raise ValueError("bar interval must be exactly ten minutes")
        if opened >= PROTECTED_HOLDOUT_AT or closed > PROTECTED_HOLDOUT_AT:
            raise ValueError("bar touches protected 2026")
        values = (self.open, self.high, self.low, self.close, self.volume)
        if not all(isfinite(value) for value in values):
            raise ValueError("bar contains non-finite OHLCV")
        if min(self.open, self.high, self.low, self.close) <= 0.0 or self.volume < 0.0:
            raise ValueError("bar prices must be positive and volume nonnegative")
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("bar high violates OHLC")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("bar low violates OHLC")
        object.__setattr__(self, "opened_at", opened)
        object.__setattr__(self, "closed_at", closed)


@dataclass(frozen=True, slots=True)
class CorridorOutcome:
    """Label plus exact unit-price economics, before contract multiplier and fees."""

    event: CorridorEvent
    direction: Direction
    entry_price: float | None
    exit_price: float | None
    take_profit_price: float | None
    stop_loss_price: float | None
    event_at: datetime | None
    event_bar_index: int | None
    gross_price_pnl: float | None
    same_bar_collision: bool
    reason: str | None = None


def unresolved_outcome(direction: Direction | str, reason: str) -> CorridorOutcome:
    """Create an explicit no-fill/no-label result."""
    if not reason:
        raise ValueError("unresolved reason cannot be empty")
    return CorridorOutcome(
        event=CorridorEvent.UNRESOLVED,
        direction=Direction(direction),
        entry_price=None,
        exit_price=None,
        take_profit_price=None,
        stop_loss_price=None,
        event_at=None,
        event_bar_index=None,
        gross_price_pnl=None,
        same_bar_collision=False,
        reason=reason,
    )


def evaluate_corridor(
    *,
    entry_bar: PriceBar,
    monitoring_bars: tuple[PriceBar, ...],
    time_exit_bar: PriceBar,
    atr: float,
    direction: Direction | str,
    spec: CorridorSpec,
) -> CorridorOutcome:
    """Resolve TP/SL/time competing risks with conservative same-bar ordering."""
    resolved_direction = Direction(direction)
    if not isfinite(atr) or atr <= 0.0:
        return unresolved_outcome(resolved_direction, "invalid_atr")
    if entry_bar.closed_at > time_exit_bar.opened_at:
        raise ValueError("time exit must follow the entry bar")
    ordered = tuple(monitoring_bars)
    if ordered != tuple(sorted(ordered, key=lambda item: item.opened_at)):
        raise ValueError("monitoring bars must be sorted")
    if len({item.opened_at for item in ordered}) != len(ordered):
        raise ValueError("monitoring bars contain duplicate starts")
    if any(
        item.opened_at < entry_bar.closed_at or item.closed_at > time_exit_bar.opened_at
        for item in ordered
    ):
        raise ValueError("monitoring bars must be strictly between entry and time exit")

    if resolved_direction is Direction.LONG:
        entry = entry_bar.high
        take_profit = entry + spec.take_profit_atr * atr
        stop_loss = entry - spec.stop_loss_atr * atr
    else:
        entry = entry_bar.low
        take_profit = entry - spec.take_profit_atr * atr
        stop_loss = entry + spec.stop_loss_atr * atr
    if min(entry, take_profit, stop_loss) <= 0.0:
        return unresolved_outcome(resolved_direction, "nonpositive_barrier")

    for index, bar in enumerate(ordered):
        if resolved_direction is Direction.LONG:
            stop_hit = bar.low <= stop_loss
            take_hit = bar.high >= take_profit
            if stop_hit:
                exit_price = min(stop_loss, bar.open)
                event = CorridorEvent.STOP_LOSS
            elif take_hit:
                exit_price = take_profit
                event = CorridorEvent.TAKE_PROFIT
            else:
                continue
            price_pnl = exit_price - entry
        else:
            stop_hit = bar.high >= stop_loss
            take_hit = bar.low <= take_profit
            if stop_hit:
                exit_price = max(stop_loss, bar.open)
                event = CorridorEvent.STOP_LOSS
            elif take_hit:
                exit_price = take_profit
                event = CorridorEvent.TAKE_PROFIT
            else:
                continue
            price_pnl = entry - exit_price
        return CorridorOutcome(
            event=event,
            direction=resolved_direction,
            entry_price=entry,
            exit_price=exit_price,
            take_profit_price=take_profit,
            stop_loss_price=stop_loss,
            event_at=bar.closed_at,
            event_bar_index=index,
            gross_price_pnl=price_pnl,
            same_bar_collision=stop_hit and take_hit,
        )

    exit_price = time_exit_bar.low if resolved_direction is Direction.LONG else time_exit_bar.high
    price_pnl = (
        exit_price - entry
        if resolved_direction is Direction.LONG
        else entry - exit_price
    )
    return CorridorOutcome(
        event=CorridorEvent.TIME_EXIT,
        direction=resolved_direction,
        entry_price=entry,
        exit_price=exit_price,
        take_profit_price=take_profit,
        stop_loss_price=stop_loss,
        event_at=time_exit_bar.closed_at,
        event_bar_index=len(ordered),
        gross_price_pnl=price_pnl,
        same_bar_collision=False,
    )


PRIMARY_CORRIDOR: Final[CorridorSpec] = CorridorSpec(0.8, 2.8)
SAFER_DIAGNOSTIC_CORRIDOR: Final[CorridorSpec] = CorridorSpec(1.2, 1.6)

__all__ = [
    "CorridorEvent",
    "CorridorOutcome",
    "CorridorSpec",
    "Direction",
    "PRIMARY_CORRIDOR",
    "PriceBar",
    "SAFER_DIAGNOSTIC_CORRIDOR",
    "evaluate_corridor",
    "unresolved_outcome",
]
