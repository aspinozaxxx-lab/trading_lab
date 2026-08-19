"""Construct five-session competing-risk labels from verified contract bars."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from math import isfinite
from typing import Final
from zoneinfo import ZoneInfo

import pandas as pd

from market_lab.futures_v9_corridor.data import ASSETS, CorridorSourceBundle
from market_lab.futures_v9_corridor.labels import (
    PRIMARY_CORRIDOR,
    SAFER_DIAGNOSTIC_CORRIDOR,
    CorridorEvent,
    CorridorOutcome,
    Direction,
    PriceBar,
    evaluate_corridor,
    unresolved_outcome,
)

MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")


def _window_open(day: object) -> datetime:
    return datetime.combine(pd.Timestamp(day).date(), time(19, 20), MOSCOW).astimezone(UTC)


def _price_bar(row: pd.Series) -> PriceBar:
    opened = pd.Timestamp(row["timestamp"]).to_pydatetime()
    return PriceBar(
        opened_at=opened,
        closed_at=opened + timedelta(minutes=10),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
    )


def _outcome_record(
    *,
    decision_at: datetime,
    exit_decision_at: datetime | None,
    asset: str,
    contract_id: str | None,
    corridor_id: str,
    direction: Direction,
    atr: float | None,
    entry_volume: float | None,
    monitor_count: int,
    outcome: CorridorOutcome,
) -> dict[str, object]:
    return {
        "decision_at": pd.Timestamp(decision_at),
        "decision_date": decision_at.astimezone(MOSCOW).date(),
        "exit_decision_at": (
            pd.NaT if exit_decision_at is None else pd.Timestamp(exit_decision_at)
        ),
        "asset": asset,
        "contract_id": contract_id,
        "corridor_id": corridor_id,
        "direction": direction.value,
        "atr_20": atr,
        "entry_volume": entry_volume,
        "monitor_bar_count": monitor_count,
        "event_type": outcome.event.value,
        "event_at": pd.NaT if outcome.event_at is None else pd.Timestamp(outcome.event_at),
        "event_bar_index": outcome.event_bar_index,
        "entry_price": outcome.entry_price,
        "exit_price": outcome.exit_price,
        "take_profit_price": outcome.take_profit_price,
        "stop_loss_price": outcome.stop_loss_price,
        "gross_price_pnl": outcome.gross_price_pnl,
        "same_bar_collision": outcome.same_bar_collision,
        "label_resolved": outcome.event is not CorridorEvent.UNRESOLVED,
        "unresolved_reason": outcome.reason,
    }


def build_competing_risk_labels(bundle: CorridorSourceBundle) -> pd.DataFrame:
    """Build both predeclared corridors without parameter search or future rollover."""
    decisions = bundle.decisions
    decision_index = {item: index for index, item in enumerate(decisions)}
    planned = {
        (pd.Timestamp(row.decision_at).to_pydatetime(), str(row.asset)): str(row.contract_id)
        for row in bundle.planned_contracts.itertuples(index=False)
    }
    features = bundle.features.set_index(["decision_at", "asset"], drop=False)
    rows: list[dict[str, object]] = []
    specs = {
        "primary": PRIMARY_CORRIDOR,
        "safer_diagnostic": SAFER_DIAGNOSTIC_CORRIDOR,
    }
    for decision_at in decisions:
        current_index = decision_index[decision_at]
        exit_decision_at = (
            decisions[current_index + 5] if current_index + 5 < len(decisions) else None
        )
        for asset in ASSETS:
            feature_key = (pd.Timestamp(decision_at), asset)
            feature_row = features.loc[feature_key]
            raw_atr = feature_row["atr_20"]
            atr = (
                float(raw_atr)
                if pd.notna(raw_atr) and isfinite(float(raw_atr)) and float(raw_atr) > 0.0
                else None
            )
            contract_id = planned.get((decision_at, asset))
            base_reason: str | None = None
            if exit_decision_at is None:
                base_reason = "missing_five_session_exit"
            elif contract_id is None:
                base_reason = "missing_planned_contract"
            else:
                horizon = decisions[current_index : current_index + 6]
                if any(planned.get((item, asset)) != contract_id for item in horizon):
                    base_reason = "contract_not_active_for_full_horizon"
            entry_bar: PriceBar | None = None
            exit_bar: PriceBar | None = None
            monitoring: tuple[PriceBar, ...] = ()
            entry_volume: float | None = None
            if base_reason is None and exit_decision_at is not None and contract_id is not None:
                entry_open = _window_open(decision_at.astimezone(MOSCOW).date())
                exit_open = _window_open(exit_decision_at.astimezone(MOSCOW).date())
                raw_entry = bundle.bar_store.exact_bar(contract_id, entry_open)
                raw_exit = bundle.bar_store.exact_bar(contract_id, exit_open)
                if raw_entry is None:
                    base_reason = "missing_exact_entry_bar"
                elif raw_exit is None:
                    base_reason = "missing_exact_time_exit_bar"
                else:
                    entry_bar = _price_bar(raw_entry)
                    exit_bar = _price_bar(raw_exit)
                    entry_volume = float(raw_entry["volume"])
                    raw_monitor = bundle.bar_store.between(
                        contract_id,
                        entry_open + timedelta(minutes=10),
                        exit_open,
                    )
                    monitoring = tuple(
                        _price_bar(row) for _, row in raw_monitor.iterrows()
                    )
            for corridor_id, spec in specs.items():
                for direction in Direction:
                    if base_reason is not None:
                        outcome = unresolved_outcome(direction, base_reason)
                    elif atr is None or entry_bar is None or exit_bar is None:
                        outcome = unresolved_outcome(direction, "invalid_atr_or_bar_evidence")
                    else:
                        outcome = evaluate_corridor(
                            entry_bar=entry_bar,
                            monitoring_bars=monitoring,
                            time_exit_bar=exit_bar,
                            atr=atr,
                            direction=direction,
                            spec=spec,
                        )
                    rows.append(
                        _outcome_record(
                            decision_at=decision_at,
                            exit_decision_at=exit_decision_at,
                            asset=asset,
                            contract_id=contract_id,
                            corridor_id=corridor_id,
                            direction=direction,
                            atr=atr,
                            entry_volume=entry_volume,
                            monitor_count=len(monitoring),
                            outcome=outcome,
                        )
                    )
    frame = pd.DataFrame(rows).sort_values(
        ["corridor_id", "decision_at", "asset", "direction"], kind="stable"
    )
    expected = len(decisions) * len(ASSETS) * len(Direction) * 2
    if len(frame) != expected or frame.duplicated(
        ["decision_at", "asset", "direction", "corridor_id"]
    ).any():
        raise RuntimeError("competing-risk label key coverage drift")
    protected = pd.Timestamp("2026-01-01", tz="UTC")
    if (frame["decision_at"] >= protected).any() or (
        frame["event_at"].dropna() >= protected
    ).any():
        raise RuntimeError("labels touch protected 2026")
    return frame.reset_index(drop=True)


__all__ = ["build_competing_risk_labels"]
