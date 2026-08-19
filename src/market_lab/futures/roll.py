"""Causal'nyi planirovshchik rolirovki futures po volume i open interest."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from market_lab.futures.specs import canonical_contract_id

ROLL_REQUIRED_COLUMNS = frozenset(  # Minimal'naya skhema dnevnyh nablyudenii rola.
    {"trade_date", "secid", "expiration_date", "volume", "open_interest"}
)
ROLL_OUTPUT_COLUMNS = (  # Stabil'naya skhema plana ispolneniya na sleduyushchuyu sessiyu.
    "effective_date",
    "decision_date",
    "observed_through",
    "canonical_contract_id",
    "secid",
    "previous_contract_id",
    "requested_contract_id",
    "position_contract_id",
    "action",
    "reason",
    "roll",
    "tradable",
    "expiry_horizon_censored",
    "execution_price",
    "exit_execution_price",
    "entry_execution_price",
    "overlap_old_price",
    "overlap_new_price",
)


@dataclass(frozen=True, slots=True)
class RollPlannerConfig:
    """Zadaet podtverzhdenie dominacii i zhestkii otstup do expiracii."""

    confirmation_days: int = 2
    hard_fallback_sessions: int = 5
    dominance_ratio: float = 1.0
    overlap_price_column: str | None = "settle"
    execution_price_column: str | None = "open"
    hard_fallback_days: int | None = None

    def __post_init__(self) -> None:
        """Proveryaet granicy causal'nyh parametrov rola."""
        if self.confirmation_days < 1:
            raise ValueError("confirmation_days dolzhen byt' >= 1")
        if self.hard_fallback_sessions < 0:
            raise ValueError("hard_fallback_sessions dolzhen byt' >= 0")
        if self.hard_fallback_days is not None:
            if self.hard_fallback_days < 0:
                raise ValueError("hard_fallback_days dolzhen byt' >= 0")
            object.__setattr__(
                self,
                "hard_fallback_sessions",
                self.hard_fallback_days,
            )
        if self.dominance_ratio <= 0.0:
            raise ValueError("dominance_ratio dolzhen byt' > 0")


@dataclass(frozen=True, slots=True)
class _PendingDecision:
    """Hranit prinyatoe na close reshenie do fakticheskoi sleduyushchei sessii."""

    decision_date: pd.Timestamp
    previous_contract_id: str | None
    requested_contract_id: str | None
    action: str
    reason: str
    old_price: float | None = None
    new_price: float | None = None


def _find_column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    """Nahodit pervyi dostupnyi registronezavisimyi alias kolonki."""
    lookup = {str(column).lower(): str(column) for column in frame.columns}
    for name in names:
        if name in lookup:
            return lookup[name]
    return None


def normalize_roll_observations(frame: pd.DataFrame) -> pd.DataFrame:
    """Privodit dnevnoi history ISS ili synthetic panel k skheme planirovshchika."""
    aliases = {
        "trade_date": ("trade_date", "tradedate", "date"),
        "secid": ("secid",),
        "asset_code": ("asset_code", "assetcode"),
        "expiration_date": ("expiration_date", "expiration"),
        "volume": ("volume",),
        "open_interest": ("open_interest", "openposition", "open_position"),
        "settle": ("settle", "settleprice", "close"),
        "open": ("open",),
        "high": ("high",),
        "low": ("low",),
        "close": ("close",),
        "canonical_contract_id": ("canonical_contract_id", "contract_id"),
    }
    normalized = pd.DataFrame(index=frame.index)
    for target, candidates in aliases.items():
        source = _find_column(frame, candidates)
        if source is not None:
            normalized[target] = frame[source].to_numpy()
    if missing := ROLL_REQUIRED_COLUMNS - set(normalized.columns):
        raise ValueError(f"V roll observations net kolonok: {sorted(missing)}")
    normalized["trade_date"] = pd.to_datetime(
        normalized["trade_date"], errors="raise"
    ).dt.normalize()
    normalized["expiration_date"] = pd.to_datetime(
        normalized["expiration_date"], errors="raise"
    ).dt.normalize()
    for column in ("volume", "open_interest"):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        if (normalized[column].dropna() < 0.0).any():
            raise ValueError(f"Otricatel'noe znachenie v {column}")
    for column in ("settle", "open", "high", "low", "close"):
        if column in normalized:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized["secid"] = normalized["secid"].astype("string")
    if "asset_code" not in normalized:
        normalized["asset_code"] = "UNKNOWN"
    normalized["asset_code"] = normalized["asset_code"].astype("string")
    if "canonical_contract_id" not in normalized:
        normalized["canonical_contract_id"] = [
            canonical_contract_id(asset_code, secid, expiration.date())
            for asset_code, secid, expiration in zip(
                normalized["asset_code"],
                normalized["secid"],
                normalized["expiration_date"],
                strict=True,
            )
        ]
    normalized["canonical_contract_id"] = normalized["canonical_contract_id"].astype(
        "string"
    )
    duplicate = normalized.duplicated(["trade_date", "canonical_contract_id"], keep=False)
    if duplicate.any():
        raise ValueError("Povtor nablyudeniya kontrakta v odin den'")
    return normalized.sort_values(
        ["trade_date", "expiration_date", "canonical_contract_id"]
    ).reset_index(drop=True)


def _valid_overlap_price(row: pd.Series | None, column: str | None) -> float | None:
    """Vozvrashchaet konechnuyu polozhitel'nuyu cenu ili None dlya flat/skip."""
    if row is None or column is None or column not in row.index:
        return None
    value = row[column]
    if pd.isna(value) or not np.isfinite(float(value)) or float(value) <= 0.0:
        return None
    return float(value)


def _execution_column(frame: pd.DataFrame, settings: RollPlannerConfig) -> str | None:
    """Vyberaet yavnyi execution stolbec ili dostupnyi causal'nyi settle/open alias."""
    if settings.execution_price_column is not None:
        return settings.execution_price_column
    if settings.overlap_price_column in frame.columns:
        return settings.overlap_price_column
    for column in ("settle", "open", "close"):
        if column in frame.columns:
            return column
    return None


def _normalize_session_calendar(
    frame: pd.DataFrame,
    session_calendar: Iterable[object] | pd.DatetimeIndex | None,
) -> pd.DatetimeIndex:
    """Normalizuet yavnyi kalendar' ili stroit business-day fallback bez cen budushchego."""
    if session_calendar is None:
        start = frame["trade_date"].min()
        finish = max(frame["expiration_date"].max(), frame["trade_date"].max())
        return pd.bdate_range(start=start, end=finish).normalize()
    calendar = pd.DatetimeIndex(pd.to_datetime(list(session_calendar), errors="raise"))
    if calendar.tz is not None:
        calendar = calendar.tz_localize(None)
    calendar = calendar.normalize().drop_duplicates().sort_values()
    if calendar.empty:
        raise ValueError("session_calendar ne mozhet byt' pustym")
    return calendar


def _validate_observed_session_coverage(
    dates: list[pd.Timestamp],
    session_calendar: pd.DatetimeIndex,
) -> None:
    """Zapreshchaet tikhii perenos resheniya cherez propushchennuyu birzhevuyu sessiyu."""
    expected = session_calendar[
        (session_calendar >= dates[0]) & (session_calendar <= dates[-1])
    ]
    observed = pd.DatetimeIndex(dates)
    if not observed.equals(expected):
        raise ValueError("Nablyudeniya ne pokryvayut yavnyi session_calendar bez propuskov")


def _sessions_to_expiry(
    decision_date: pd.Timestamp,
    expiration_date: pd.Timestamp,
    session_calendar: pd.DatetimeIndex,
) -> int | None:
    """Schitaet izvestnye sessii ili vozvrashchaet horizon-censored None."""
    if expiration_date > session_calendar.max():
        return None
    remaining = session_calendar[
        (session_calendar > decision_date) & (session_calendar <= expiration_date)
    ]
    return int(len(remaining))


def _plan_row(
    effective_date: pd.Timestamp,
    decision_date: pd.Timestamp | None,
    current: pd.Series | None,
    previous_contract_id: str | None,
    requested: pd.Series | None,
    action: str,
    reason: str,
    tradable: bool,
    execution_price: float | None = None,
    old_price: float | None = None,
    new_price: float | None = None,
    position_contract_id: str | None = None,
    exit_execution_price: float | None = None,
    entry_execution_price: float | None = None,
) -> dict[str, Any]:
    """Sobiraet odnu stroku stabil'noi shemy plana rola."""
    resolved_position_id = position_contract_id
    if resolved_position_id is None and current is not None and tradable:
        resolved_position_id = str(current["canonical_contract_id"])
    show_current = current is not None and (tradable or resolved_position_id is not None)
    return {
        "effective_date": effective_date,
        "decision_date": decision_date,
        "observed_through": decision_date,
        "canonical_contract_id": (
            str(current["canonical_contract_id"]) if show_current else pd.NA
        ),
        "secid": str(current["secid"]) if show_current else pd.NA,
        "previous_contract_id": previous_contract_id if previous_contract_id else pd.NA,
        "requested_contract_id": (
            str(requested["canonical_contract_id"]) if requested is not None else pd.NA
        ),
        "position_contract_id": resolved_position_id or pd.NA,
        "action": action,
        "reason": reason,
        "roll": action == "roll",
        "tradable": tradable,
        "expiry_horizon_censored": reason == "front_retained_horizon_censored",
        "execution_price": execution_price,
        "exit_execution_price": exit_execution_price,
        "entry_execution_price": entry_execution_price,
        "overlap_old_price": old_price,
        "overlap_new_price": new_price,
    }


def _row_for_contract(
    frame: pd.DataFrame,
    trading_date: pd.Timestamp,
    contract_id: str | None,
) -> pd.Series | None:
    """Nahodit edinstvennuyu fakticheskuyu stroku kontrakta v ukazannuyu sessiyu."""
    if contract_id is None:
        return None
    rows = frame.loc[
        (frame["trade_date"] == trading_date)
        & (frame["canonical_contract_id"] == contract_id)
    ]
    return None if rows.empty else rows.iloc[0]


def _execute_pending(
    frame: pd.DataFrame,
    effective_date: pd.Timestamp,
    pending: _PendingDecision,
    execution_column: str | None,
) -> tuple[dict[str, Any], str | None]:
    """Fiksiruet fakticheskoe sostoyanie pozicii tol'ko posle validnoi ceny sessii."""
    requested = _row_for_contract(
        frame,
        pending.decision_date,
        pending.requested_contract_id,
    )
    previous = _row_for_contract(
        frame,
        pending.decision_date,
        pending.previous_contract_id,
    )
    previous_effective = _row_for_contract(
        frame,
        effective_date,
        pending.previous_contract_id,
    )
    requested_effective = _row_for_contract(
        frame,
        effective_date,
        pending.requested_contract_id,
    )
    exit_price = _valid_overlap_price(previous_effective, execution_column)
    entry_price = _valid_overlap_price(requested_effective, execution_column)
    if pending.action == "flat" and pending.previous_contract_id is None:
        return (
            _plan_row(
                effective_date,
                pending.decision_date,
                None,
                pending.previous_contract_id,
                requested,
                pending.action,
                pending.reason,
                False,
                old_price=pending.old_price,
                new_price=pending.new_price,
            ),
            None,
        )
    if pending.action == "flat_skip":
        if pending.previous_contract_id is None:
            return (
                _plan_row(
                    effective_date,
                    pending.decision_date,
                    None,
                    None,
                    requested,
                    pending.action,
                    pending.reason,
                    False,
                    old_price=pending.old_price,
                    new_price=pending.new_price,
                ),
                None,
            )
        if exit_price is not None:
            return (
                _plan_row(
                    effective_date,
                    pending.decision_date,
                    None,
                    pending.previous_contract_id,
                    requested,
                    pending.action,
                    pending.reason,
                    False,
                    exit_price,
                    pending.old_price,
                    pending.new_price,
                    exit_execution_price=exit_price,
                ),
                None,
            )
        current = previous_effective if previous_effective is not None else previous
        return (
            _plan_row(
                effective_date,
                pending.decision_date,
                current,
                pending.previous_contract_id,
                requested,
                "carry_unfilled_exit",
                "missing_exit_execution_price",
                False,
                old_price=pending.old_price,
                new_price=pending.new_price,
                position_contract_id=pending.previous_contract_id,
            ),
            pending.previous_contract_id,
        )
    if pending.action == "hold":
        if entry_price is None:
            current = requested_effective if requested_effective is not None else requested
            return (
                _plan_row(
                    effective_date,
                    pending.decision_date,
                    current,
                    pending.previous_contract_id,
                    requested,
                    "carry_missing_mark",
                    "missing_hold_mark",
                    False,
                    old_price=pending.old_price,
                    new_price=pending.new_price,
                    position_contract_id=pending.previous_contract_id,
                ),
                pending.previous_contract_id,
            )
        return (
            _plan_row(
                effective_date,
                pending.decision_date,
                requested_effective,
                pending.previous_contract_id,
                requested,
                pending.action,
                pending.reason,
                True,
                entry_price,
                pending.old_price,
                pending.new_price,
            ),
            pending.previous_contract_id,
        )
    if pending.action == "roll":
        if exit_price is None or entry_price is None:
            current = previous_effective if previous_effective is not None else previous
            return (
                _plan_row(
                    effective_date,
                    pending.decision_date,
                    current,
                    pending.previous_contract_id,
                    requested,
                    "carry_unfilled_roll",
                    "missing_roll_execution_leg",
                    False,
                    old_price=pending.old_price,
                    new_price=pending.new_price,
                    position_contract_id=pending.previous_contract_id,
                    exit_execution_price=exit_price,
                    entry_execution_price=entry_price,
                ),
                pending.previous_contract_id,
            )
        return (
            _plan_row(
                effective_date,
                pending.decision_date,
                requested_effective,
                pending.previous_contract_id,
                requested,
                pending.action,
                pending.reason,
                True,
                entry_price,
                pending.old_price,
                pending.new_price,
                exit_execution_price=exit_price,
                entry_execution_price=entry_price,
            ),
            pending.requested_contract_id,
        )
    if requested_effective is None or entry_price is None:
        return (
            _plan_row(
                effective_date,
                pending.decision_date,
                None,
                pending.previous_contract_id,
                requested,
                "flat_skip",
                "missing_effective_price",
                False,
                old_price=pending.old_price,
                new_price=pending.new_price,
            ),
            None,
        )
    return (
        _plan_row(
            effective_date,
            pending.decision_date,
            requested_effective,
            pending.previous_contract_id,
            requested,
            pending.action,
            pending.reason,
            True,
            entry_price,
            pending.old_price,
            pending.new_price,
            entry_execution_price=entry_price,
        ),
        str(requested_effective["canonical_contract_id"]),
    )


def plan_causal_rolls(
    observations: pd.DataFrame,
    config: RollPlannerConfig | None = None,
    session_calendar: Iterable[object] | pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Stroit next-session plan s fakticheskim position state i causal'nym fallback."""
    settings = config or RollPlannerConfig()
    frame = normalize_roll_observations(observations)
    assets = frame["asset_code"].dropna().astype(str).unique()
    if len(assets) > 1:
        raise ValueError("plan_causal_rolls prinimaet tol'ko odin asset_code")
    dates = frame["trade_date"].drop_duplicates().sort_values().tolist()
    if not dates:
        return pd.DataFrame(columns=ROLL_OUTPUT_COLUMNS)
    calendar = _normalize_session_calendar(frame, session_calendar)
    if session_calendar is not None:
        _validate_observed_session_coverage(dates, calendar)
    execution_column = _execution_column(frame, settings)
    plan: list[dict[str, Any]] = [
        _plan_row(
            dates[0],
            None,
            None,
            None,
            None,
            "flat",
            "initial_warmup",
            False,
        )
    ]
    position_id: str | None = None
    retired_ids: set[str] = set()
    dominance_candidate: str | None = None
    dominance_streak = 0
    pending: _PendingDecision | None = None
    for position, decision_date in enumerate(dates):
        if position > 0:
            if pending is None:
                raise RuntimeError("Net pending resheniya dlya sleduyushchei sessii")
            executed, position_id = _execute_pending(
                frame,
                decision_date,
                pending,
                execution_column,
            )
            plan.append(executed)
        if position == len(dates) - 1:
            break
        today = frame.loc[frame["trade_date"] == decision_date].copy()
        active = today.loc[today["expiration_date"] >= decision_date].sort_values(
            ["expiration_date", "canonical_contract_id"]
        )
        active = active.loc[~active["canonical_contract_id"].isin(retired_ids)]
        if position_id is None:
            dominance_candidate = None
            dominance_streak = 0
            if active.empty:
                pending = _PendingDecision(
                    decision_date,
                    None,
                    None,
                    "flat",
                    "no_active_contract",
                )
                continue
            target = active.iloc[0]
            pending = _PendingDecision(
                decision_date,
                None,
                str(target["canonical_contract_id"]),
                "enter",
                "first_observed_front",
            )
            continue
        current_rows = today.loc[today["canonical_contract_id"] == position_id]
        if current_rows.empty:
            replacement = active.iloc[0] if not active.empty else None
            retired_ids.add(position_id)
            pending = _PendingDecision(
                decision_date,
                position_id,
                (
                    str(replacement["canonical_contract_id"])
                    if replacement is not None
                    else None
                ),
                "flat_skip",
                "missing_current_observation",
            )
            dominance_candidate = None
            dominance_streak = 0
            continue
        current = current_rows.iloc[0]
        later = active.loc[active["expiration_date"] > current["expiration_date"]]
        challenger = later.iloc[0] if not later.empty else None
        sessions_to_expiry = _sessions_to_expiry(
            decision_date,
            current["expiration_date"],
            calendar,
        )
        expiry_horizon_censored = sessions_to_expiry is None
        hard_fallback = bool(
            sessions_to_expiry is not None
            and sessions_to_expiry <= settings.hard_fallback_sessions
        )
        dominates = False
        if challenger is not None:
            metrics = (
                current["volume"],
                current["open_interest"],
                challenger["volume"],
                challenger["open_interest"],
            )
            if all(pd.notna(value) for value in metrics):
                dominates = bool(
                    challenger["volume"] > current["volume"] * settings.dominance_ratio
                    and challenger["open_interest"]
                    > current["open_interest"] * settings.dominance_ratio
                )
        challenger_id = (
            str(challenger["canonical_contract_id"]) if challenger is not None else None
        )
        if dominates and challenger_id == dominance_candidate:
            dominance_streak += 1
        elif dominates:
            dominance_candidate = challenger_id
            dominance_streak = 1
        else:
            dominance_candidate = None
            dominance_streak = 0
        confirmed = challenger is not None and dominance_streak >= settings.confirmation_days
        if not hard_fallback and not confirmed:
            pending = _PendingDecision(
                decision_date,
                position_id,
                position_id,
                "hold",
                (
                    "front_retained_horizon_censored"
                    if expiry_horizon_censored
                    else "front_retained"
                ),
            )
            continue
        if challenger is None:
            retired_ids.add(position_id)
            pending = _PendingDecision(
                decision_date,
                position_id,
                None,
                "flat_skip",
                "hard_fallback_without_next_contract",
            )
            dominance_candidate = None
            dominance_streak = 0
            continue
        price_column = settings.overlap_price_column
        old_price = _valid_overlap_price(current, price_column)
        new_price = _valid_overlap_price(challenger, price_column)
        overlap_required = price_column is not None
        previous_id = position_id
        retired_ids.add(previous_id)
        if overlap_required and (old_price is None or new_price is None):
            pending = _PendingDecision(
                decision_date,
                previous_id,
                challenger_id,
                "flat_skip",
                "missing_roll_overlap",
                old_price,
                new_price,
            )
        else:
            pending = _PendingDecision(
                decision_date,
                previous_id,
                challenger_id,
                "roll",
                (
                    "two_day_volume_oi_dominance"
                    if confirmed
                    else "hard_fallback"
                ),
                old_price,
                new_price,
            )
        dominance_candidate = None
        dominance_streak = 0
    return pd.DataFrame(plan, columns=ROLL_OUTPUT_COLUMNS).sort_values(
        "effective_date", ignore_index=True
    )
