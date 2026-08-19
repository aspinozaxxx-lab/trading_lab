"""Strogii research-ledger variation margin dlya odnoi futures-serii."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Literal

import numpy as np
import pandas as pd

LEDGER_TOLERANCE = 1e-9  # Chislovoi dopusk proverok deneg i risk-limitov.
ALLOWED_SLIPPAGE_TICKS = frozenset({1, 2, 4})  # Fiksirovannye stress-scenarii slip.
MARKET_COLUMNS = frozenset(  # Minimal'naya skhema fakticheskih dnevnyh nablyudenii.
    {
        "session_date",
        "contract_id",
        "open",
        "settle",
        "volume",
        "point_value",
        "tick_size",
        "fee_per_contract",
        "initial_margin",
    }
)
TARGET_COLUMNS = frozenset(  # Minimal'naya skhema causal'nyh target-sobytii.
    {"effective_date", "decision_date", "contract_id", "target_contracts"}
)
ORDER_COLUMNS = (  # Stabil'naya skhema ispolnennyh i otklonennyh nog.
    "session_date",
    "atomic_group",
    "leg",
    "contract_id",
    "quantity_delta",
    "factual_open",
    "execution_price",
    "point_value",
    "tick_size",
    "lagged_volume",
    "participation",
    "gross_notional",
    "commission_cost",
    "slippage_cost",
    "filled",
    "reason",
)
KNOWN_SERIES_PREFIXES = (  # Izvestnye prefiksy SECID dlya single-series zashchity.
    ("SI", "SI"),
    ("RI", "RI"),
    ("BR", "BR"),
    ("MX", "MIX"),
)
KNOWN_ASSET_CODES = {  # Oficial'nyi asset_code -> logical series dlya canonical ID.
    "SI": "SI",
    "RTS": "RI",
    "BR": "BR",
    "MIX": "MIX",
}


@dataclass(frozen=True, slots=True)
class FuturesLedgerConfig:
    """Zadaet kapital, izderzhki i fail-closed limity research-ledger."""

    initial_cash: float = 1_000_000.0
    maximum_gross_notional_multiple: float = 1.0
    initial_margin_buffer_multiplier: float = 2.0
    maximum_participation: float = 0.01
    slippage_ticks: Literal[1, 2, 4] = 1
    fee_multiplier: float = 1.0
    terminal_policy: Literal["carry", "liquidate"] = "carry"

    def __post_init__(self) -> None:
        """Proveryaet tol'ko konservativnye granicy futures-eksperimenta."""
        finite_positive = (
            self.initial_cash,
            self.maximum_gross_notional_multiple,
            self.initial_margin_buffer_multiplier,
            self.maximum_participation,
            self.fee_multiplier,
        )
        if any(not np.isfinite(value) or value <= 0.0 for value in finite_positive):
            raise ValueError("Kapital, limity i mnozhiteli dolzhny byt' polozhitel'nymi")
        if self.maximum_gross_notional_multiple > 1.0:
            raise ValueError("Research-ledger zapreshchaet gross notional vyshe 1x")
        if self.initial_margin_buffer_multiplier < 2.0:
            raise ValueError("Modeled initial-margin buffer dolzhen byt' ne men'she 2x")
        if self.maximum_participation > 0.01:
            raise ValueError("Uchastie v lagged volume ne mozhet prevyshat' 1%")
        if self.slippage_ticks not in ALLOWED_SLIPPAGE_TICKS:
            raise ValueError("slippage_ticks dolzhen byt' odnim iz 1, 2 ili 4")
        if self.fee_multiplier not in {1.0, 2.0}:
            raise ValueError("fee_multiplier podderzhivaet bazu 1x ili stress 2x")
        if self.terminal_policy not in {"carry", "liquidate"}:
            raise ValueError("terminal_policy dolzhen byt' carry ili liquidate")


@dataclass(frozen=True, slots=True)
class FuturesLedgerResult:
    """Hranit daily cash-ledger, order-events, metriki i status ispolneniya."""

    ledger: pd.DataFrame
    orders: pd.DataFrame
    metrics: dict[str, float | int | bool | str]
    execution_complete: bool


@dataclass(slots=True)
class _Position:
    """Hranit odnu fakticheskuyu poziciyu i poslednii izvestnyi settlement."""

    contract_id: str | None = None
    contracts: int = 0
    previous_settle: float | None = None


@dataclass(slots=True)
class _Counters:
    """Nakaplivaet vse prichiny nepolnogo ili otklonennogo ispolneniya."""

    missing_open_count: int = 0
    missing_settle_count: int = 0
    unknown_point_value_count: int = 0
    unknown_fee_count: int = 0
    unknown_initial_margin_count: int = 0
    unknown_tick_size_count: int = 0
    unknown_liquidity_count: int = 0
    participation_rejection_count: int = 0
    gross_limit_rejection_count: int = 0
    initial_margin_rejection_count: int = 0
    gross_limit_breach_count: int = 0
    initial_margin_buffer_breach_count: int = 0
    missing_contract_row_count: int = 0

    def total_failures(self) -> int:
        """Vozvrashchaet chislo fail-closed sobytii bez skrytoi kompensacii."""
        return int(sum(getattr(self, item.name) for item in fields(self)))


def _normalize_dates(values: pd.Series) -> pd.Series:
    """Privodit session-date k timezone-naive polunochi bez sdviga dnya."""
    timestamps = pd.to_datetime(values, errors="raise")
    if timestamps.dt.tz is not None:
        timestamps = timestamps.dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
    return timestamps.dt.normalize()


def _normalize_market(market: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet factual open/settle i sam stroit causal lagged volume."""
    aliases = {
        "trade_date": "session_date",
        "canonical_contract_id": "contract_id",
    }
    result = market.rename(
        columns={source: target for source, target in aliases.items() if target not in market}
    ).copy()
    if missing := MARKET_COLUMNS - set(result.columns):
        raise ValueError(f"V futures market net kolonok: {sorted(missing)}")
    result = result.loc[:, sorted(MARKET_COLUMNS)].copy()
    result["session_date"] = _normalize_dates(result["session_date"])
    result["contract_id"] = result["contract_id"].astype("string")
    if result["contract_id"].isna().any() or result["contract_id"].eq("").any():
        raise ValueError("contract_id ne mozhet byt' pustym")
    numeric = MARKET_COLUMNS - {"session_date", "contract_id"}
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    positive = ("open", "settle", "point_value", "tick_size", "initial_margin")
    for column in positive:
        values = result[column].dropna()
        if (~np.isfinite(values)).any() or (values <= 0.0).any():
            raise ValueError(f"Dostupnoe znachenie {column} dolzhno byt' polozhitel'nym")
    nonnegative = ("volume", "fee_per_contract")
    for column in nonnegative:
        values = result[column].dropna()
        if (~np.isfinite(values)).any() or (values < 0.0).any():
            raise ValueError(f"Dostupnoe znachenie {column} ne mozhet byt' otricatelnym")
    if result.duplicated(["session_date", "contract_id"]).any():
        raise ValueError("Futures market soderzhit dublikat session/contract")
    result = result.sort_values(
        ["contract_id", "session_date"], kind="mergesort"
    ).reset_index(drop=True)
    result["lagged_volume"] = result.groupby("contract_id", sort=False)["volume"].shift(1)
    return result.sort_values(
        ["session_date", "contract_id"], kind="mergesort"
    ).reset_index(drop=True)


def _infer_series_id(contract_id: object) -> str | None:
    """Izvlekaet izvestnuyu seriyu iz canonical ID ili standartnogo SECID."""
    if pd.isna(contract_id):
        return None
    normalized = str(contract_id).upper()
    canonical_asset = normalized.split(":", maxsplit=1)[0]
    if canonical_asset in KNOWN_ASSET_CODES:
        return KNOWN_ASSET_CODES[canonical_asset]
    for prefix, series_id in KNOWN_SERIES_PREFIXES:
        if normalized.startswith(prefix):
            return series_id
    return None


def _validate_single_series(market: pd.DataFrame, targets: pd.DataFrame) -> None:
    """Zapreshchaet tikhii cross-asset roll vmesto portfel'nogo cash-pool."""
    identifiers = pd.concat(
        [market["contract_id"], targets["contract_id"]], ignore_index=True
    )
    series_ids = {series_id for value in identifiers if (series_id := _infer_series_id(value))}
    if len(series_ids) > 1:
        raise ValueError(
            "run_futures_ledger podderzhivaet odnu seriyu; "
            "multi-asset trebuet otdel'nyi portfolio cash-pool"
        )


def _normalize_targets(targets: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Proveryaet celye kontrakty i zapreshchaet signal iz tekushchego open."""
    aliases = {"session_date": "effective_date", "canonical_contract_id": "contract_id"}
    result = targets.rename(
        columns={source: target for source, target in aliases.items() if target not in targets}
    ).copy()
    if missing := TARGET_COLUMNS - set(result.columns):
        raise ValueError(f"V futures targets net kolonok: {sorted(missing)}")
    keep = sorted(TARGET_COLUMNS | ({"observed_through"} & set(result.columns)))
    result = result.loc[:, keep].copy()
    result["effective_date"] = _normalize_dates(result["effective_date"])
    result["decision_date"] = _normalize_dates(result["decision_date"])
    if "observed_through" in result:
        result["observed_through"] = _normalize_dates(result["observed_through"])
    result["target_contracts"] = pd.to_numeric(
        result["target_contracts"], errors="raise"
    )
    rounded = result["target_contracts"].round()
    if (~np.isfinite(result["target_contracts"])).any() or not np.allclose(
        result["target_contracts"], rounded
    ):
        raise ValueError("Futures target dolzhen byt' celym chislom kontraktov")
    result["target_contracts"] = rounded.astype(int)
    result["contract_id"] = result["contract_id"].astype("string")
    nonzero = result["target_contracts"].ne(0)
    if result.loc[nonzero, "contract_id"].isna().any() or result.loc[
        nonzero, "contract_id"
    ].eq("").any():
        raise ValueError("Nenulevoi target trebuet contract_id")
    result.loc[~nonzero, "contract_id"] = pd.NA
    if (result["decision_date"] >= result["effective_date"]).any():
        raise ValueError("decision_date dolzhen byt' strogo ran'she effective open")
    if "observed_through" in result and (
        result["observed_through"] > result["decision_date"]
    ).any():
        raise ValueError("observed_through ne mozhet byt' pozhe decision_date")
    if result.duplicated("effective_date").any():
        raise ValueError("Na odin effective_date dopuskaetsya tol'ko odin target")
    unknown_dates = set(result["effective_date"]) - set(calendar)
    if unknown_dates:
        raise ValueError("Kazhdii effective_date dolzhen byt' fakticheskoi sessiei")
    return result.sort_values("effective_date", kind="mergesort").reset_index(drop=True)


def _valid_positive(value: object) -> bool:
    """Proveryaet konechnoe strogo polozhitel'noe chislo bez podstanovki."""
    return bool(pd.notna(value) and np.isfinite(float(value)) and float(value) > 0.0)


def _valid_nonnegative(value: object) -> bool:
    """Proveryaet konechnoe neotricatel'noe chislo, vklyuchaya nulevoi fee."""
    return bool(pd.notna(value) and np.isfinite(float(value)) and float(value) >= 0.0)


def _market_row(
    indexed_market: pd.DataFrame,
    session_date: pd.Timestamp,
    contract_id: str | None,
) -> pd.Series | None:
    """Nahodit odnu fakticheskuyu stroku kontrakta na tekushchei sessii."""
    if contract_id is None:
        return None
    try:
        row = indexed_market.loc[(session_date, contract_id)]
    except KeyError:
        return None
    if isinstance(row, pd.DataFrame):
        raise RuntimeError("Vnutrennii dublikat futures market")
    return row


def _increment_unknown_specs(row: pd.Series, counters: _Counters) -> list[str]:
    """Fiksiruet vse neizvestnye contract-specs nogi i vozvrashchaet prichiny."""
    reasons: list[str] = []
    if not _valid_positive(row["point_value"]):
        counters.unknown_point_value_count += 1
        reasons.append("unknown_point_value")
    if not _valid_positive(row["tick_size"]):
        counters.unknown_tick_size_count += 1
        reasons.append("unknown_tick_size")
    if not _valid_nonnegative(row["fee_per_contract"]):
        counters.unknown_fee_count += 1
        reasons.append("unknown_fee")
    return reasons


def _build_leg(
    session_date: pd.Timestamp,
    atomic_group: str,
    leg: str,
    contract_id: str,
    quantity_delta: int,
    row: pd.Series | None,
    config: FuturesLedgerConfig,
    counters: _Counters,
) -> dict[str, object]:
    """Sobiraet odnu nogu i fail-closed proverki ceny, specs i likvidnosti."""
    result: dict[str, object] = {
        "session_date": session_date,
        "atomic_group": atomic_group,
        "leg": leg,
        "contract_id": contract_id,
        "quantity_delta": int(quantity_delta),
        "factual_open": np.nan,
        "execution_price": np.nan,
        "point_value": np.nan,
        "tick_size": np.nan,
        "lagged_volume": np.nan,
        "participation": np.inf,
        "gross_notional": np.nan,
        "commission_cost": np.nan,
        "slippage_cost": np.nan,
        "filled": False,
        "reason": "",
    }
    reasons: list[str] = []
    if row is None:
        counters.missing_contract_row_count += 1
        reasons.append("missing_contract_row")
        result["reason"] = ",".join(reasons)
        return result
    result.update(
        {
            "factual_open": row["open"],
            "point_value": row["point_value"],
            "tick_size": row["tick_size"],
            "lagged_volume": row["lagged_volume"],
        }
    )
    if not _valid_positive(row["open"]):
        counters.missing_open_count += 1
        reasons.append("missing_factual_open")
    reasons.extend(_increment_unknown_specs(row, counters))
    if leg in {"entry", "rebalance", "roll_entry"} and not _valid_positive(
        row["settle"]
    ):
        counters.missing_settle_count += 1
        reasons.append("missing_factual_settle")
    lagged_volume = row["lagged_volume"]
    if pd.isna(lagged_volume) or not np.isfinite(float(lagged_volume)):
        counters.unknown_liquidity_count += 1
        reasons.append("unknown_lagged_volume")
    elif float(lagged_volume) <= 0.0:
        counters.participation_rejection_count += 1
        reasons.append("zero_lagged_volume")
    else:
        participation = abs(quantity_delta) / float(lagged_volume)
        result["participation"] = participation
        if participation > config.maximum_participation + LEDGER_TOLERANCE:
            counters.participation_rejection_count += 1
            reasons.append("participation_limit")
    if reasons:
        result["reason"] = ",".join(reasons)
        return result
    factual_open = float(row["open"])
    point_value = float(row["point_value"])
    tick_size = float(row["tick_size"])
    direction = 1.0 if quantity_delta > 0 else -1.0
    execution_price = factual_open + direction * config.slippage_ticks * tick_size
    result.update(
        {
            "execution_price": execution_price,
            "gross_notional": abs(quantity_delta) * factual_open * point_value,
            "commission_cost": (
                abs(quantity_delta)
                * float(row["fee_per_contract"])
                * config.fee_multiplier
            ),
            "slippage_cost": (
                abs(quantity_delta)
                * config.slippage_ticks
                * tick_size
                * point_value
            ),
            "reason": "ready",
        }
    )
    return result


def _desired_legs(
    position: _Position,
    desired_contract: str | None,
    desired_contracts: int,
) -> list[tuple[str, str, int]]:
    """Razlagaet target na odnu nogu ili atomarnyi exit/entry roll."""
    if position.contracts == 0:
        return (
            []
            if desired_contracts == 0
            else [("entry", str(desired_contract), desired_contracts)]
        )
    if desired_contracts == 0:
        return [("exit", str(position.contract_id), -position.contracts)]
    if position.contract_id == desired_contract:
        delta = desired_contracts - position.contracts
        return [] if delta == 0 else [("rebalance", str(desired_contract), delta)]
    return [
        ("roll_exit", str(position.contract_id), -position.contracts),
        ("roll_entry", str(desired_contract), desired_contracts),
    ]


def _risk_reasons(
    desired_row: pd.Series | None,
    desired_contracts: int,
    estimated_equity: float,
    config: FuturesLedgerConfig,
    counters: _Counters,
) -> list[str]:
    """Proveryaet gross 1x i dvoinoi modeled-IM buffer posle izderzhek."""
    if desired_contracts == 0:
        return []
    if desired_row is None:
        return ["missing_target_contract_row"]
    reasons: list[str] = []
    if not _valid_positive(desired_row["initial_margin"]):
        counters.unknown_initial_margin_count += 1
        reasons.append("unknown_initial_margin")
    if not _valid_positive(desired_row["point_value"]) or not _valid_positive(
        desired_row["open"]
    ):
        return reasons
    gross = (
        abs(desired_contracts)
        * float(desired_row["open"])
        * float(desired_row["point_value"])
    )
    gross_cap = max(estimated_equity, 0.0) * config.maximum_gross_notional_multiple
    if gross > gross_cap + LEDGER_TOLERANCE:
        counters.gross_limit_rejection_count += 1
        reasons.append("gross_notional_limit")
    if _valid_positive(desired_row["initial_margin"]):
        margin = abs(desired_contracts) * float(desired_row["initial_margin"])
        required = margin * config.initial_margin_buffer_multiplier
        if required > max(estimated_equity, 0.0) + LEDGER_TOLERANCE:
            counters.initial_margin_rejection_count += 1
            reasons.append("initial_margin_buffer")
    return reasons


def _daily_exposure(
    row: pd.Series | None,
    contracts: int,
    cash: float,
    config: FuturesLedgerConfig,
) -> tuple[float, float, float, bool, bool]:
    """Schitaet gross i modeled IM bez vosstanovleniya neizvestnyh specs."""
    if contracts == 0:
        return 0.0, 0.0, 0.0, True, True
    point_known = row is not None and _valid_positive(row["point_value"])
    margin_known = row is not None and _valid_positive(row["initial_margin"])
    open_known = row is not None and _valid_positive(row["open"])
    gross = (
        abs(contracts) * float(row["open"]) * float(row["point_value"])
        if point_known and open_known
        else np.nan
    )
    margin = (
        abs(contracts) * float(row["initial_margin"]) if margin_known else np.nan
    )
    leverage = gross / max(cash, LEDGER_TOLERANCE) if np.isfinite(gross) else np.nan
    gross_ok = bool(
        np.isfinite(gross)
        and gross <= max(cash, 0.0) * config.maximum_gross_notional_multiple + LEDGER_TOLERANCE
    )
    margin_ok = bool(
        np.isfinite(margin)
        and margin * config.initial_margin_buffer_multiplier
        <= max(cash, 0.0) + LEDGER_TOLERANCE
    )
    return float(gross), float(margin), float(leverage), gross_ok, margin_ok


def run_futures_ledger(
    market: pd.DataFrame,
    targets: pd.DataFrame,
    config: FuturesLedgerConfig | None = None,
) -> FuturesLedgerResult:
    """Ispolnyaet causal targets na factual open i nachislyaet daily variation margin."""
    settings = config or FuturesLedgerConfig()
    normalized_market = _normalize_market(market)
    calendar = pd.DatetimeIndex(
        normalized_market["session_date"].drop_duplicates().sort_values()
    )
    if calendar.empty:
        raise ValueError("Futures ledger trebuet hotya by odnu sessiyu")
    normalized_targets = _normalize_targets(targets, calendar)
    _validate_single_series(normalized_market, normalized_targets)
    target_by_date = {
        pd.Timestamp(row["effective_date"]): row
        for row in normalized_targets.to_dict("records")
    }
    indexed_market = normalized_market.set_index(["session_date", "contract_id"])
    position = _Position()
    counters = _Counters()
    cash = float(settings.initial_cash)
    previous_cash = cash
    pending_contract: str | None = None
    pending_contracts = 0
    has_pending = False
    ledger_rows: list[dict[str, object]] = []
    order_rows: list[dict[str, object]] = []
    total_commission = 0.0
    total_slippage = 0.0
    total_variation_margin = 0.0
    maximum_participation = 0.0
    roll_count = 0
    filled_leg_count = 0
    rejected_event_count = 0

    for session_index, session_value in enumerate(calendar):
        session_date = pd.Timestamp(session_value)
        session_start_cash = cash
        session_complete = True
        status = "hold"
        current_row = _market_row(indexed_market, session_date, position.contract_id)
        gap_pnl = 0.0
        intraday_pnl = 0.0
        fallback_settle_pnl = 0.0
        session_commission = 0.0
        session_slippage = 0.0
        session_max_participation = 0.0
        can_split_mark = position.contracts == 0
        fallback_marked = False

        if position.contracts != 0:
            if current_row is None:
                counters.missing_contract_row_count += 1
                session_complete = False
            elif not _valid_positive(current_row["point_value"]):
                counters.unknown_point_value_count += 1
                session_complete = False
            elif position.previous_settle is None:
                counters.missing_settle_count += 1
                session_complete = False
            elif _valid_positive(current_row["open"]):
                gap_pnl = (
                    position.contracts
                    * (float(current_row["open"]) - position.previous_settle)
                    * float(current_row["point_value"])
                )
                can_split_mark = True
            elif _valid_positive(current_row["settle"]):
                counters.missing_open_count += 1
                fallback_settle_pnl = (
                    position.contracts
                    * (float(current_row["settle"]) - position.previous_settle)
                    * float(current_row["point_value"])
                )
                fallback_marked = True
                session_complete = False
            else:
                counters.missing_open_count += 1
                counters.missing_settle_count += 1
                session_complete = False
        cash += gap_pnl

        target = target_by_date.get(session_date)
        if target is not None:
            pending_contracts = int(target["target_contracts"])
            value = target["contract_id"]
            pending_contract = None if pd.isna(value) else str(value)
            has_pending = True
        is_terminal = session_index == len(calendar) - 1
        if is_terminal and settings.terminal_policy == "liquidate":
            pending_contract = None
            pending_contracts = 0
            has_pending = True
            status = "terminal_liquidation_requested"

        desired_contract = pending_contract if has_pending else position.contract_id
        desired_contracts = pending_contracts if has_pending else position.contracts
        legs = _desired_legs(position, desired_contract, desired_contracts)
        executed = False
        if legs:
            atomic_group = f"{session_date.date().isoformat()}:{len(order_rows):06d}"
            proposed: list[dict[str, object]] = []
            for leg_name, contract_id, quantity_delta in legs:
                proposed.append(
                    _build_leg(
                        session_date,
                        atomic_group,
                        leg_name,
                        contract_id,
                        quantity_delta,
                        _market_row(indexed_market, session_date, contract_id),
                        settings,
                        counters,
                    )
                )
            for leg in proposed:
                session_max_participation = max(
                    session_max_participation,
                    float(leg["participation"]),
                )
            leg_reasons = [str(leg["reason"]) for leg in proposed if leg["reason"] != "ready"]
            estimated_cost = sum(
                float(leg["commission_cost"]) + float(leg["slippage_cost"])
                for leg in proposed
                if leg["reason"] == "ready"
            )
            desired_row = _market_row(indexed_market, session_date, desired_contract)
            risk_reasons = _risk_reasons(
                desired_row,
                desired_contracts,
                cash - estimated_cost,
                settings,
                counters,
            )
            reasons = leg_reasons + risk_reasons
            if not can_split_mark and position.contracts != 0:
                reasons.append("missing_old_factual_open")
            if reasons:
                rejection = ",".join(dict.fromkeys(reasons))
                for leg in proposed:
                    leg["filled"] = False
                    leg["reason"] = rejection
                rejected_event_count += 1
                session_complete = False
                status = "carry_rejected"
            else:
                for leg in proposed:
                    leg["filled"] = True
                    leg["reason"] = "filled"
                    session_commission += float(leg["commission_cost"])
                    session_slippage += float(leg["slippage_cost"])
                position.contract_id = desired_contract
                position.contracts = int(desired_contracts)
                position.previous_settle = None
                has_pending = False
                executed = True
                filled_leg_count += len(proposed)
                if len(proposed) == 2:
                    roll_count += 1
                    status = "roll_filled"
                else:
                    status = str(proposed[0]["leg"]) + "_filled"
                if position.contracts == 0:
                    position.contract_id = None
            order_rows.extend(proposed)

        active_row = _market_row(indexed_market, session_date, position.contract_id)
        if position.contracts != 0:
            if executed:
                if active_row is None or not _valid_positive(active_row["settle"]):
                    raise RuntimeError("Ispolnenie bez proverennogo factual settle nedopustimo")
                if not _valid_positive(active_row["open"]) or not _valid_positive(
                    active_row["point_value"]
                ):
                    raise RuntimeError("Ispolnenie bez proverennyh open/point value nedopustimo")
                intraday_pnl = (
                    position.contracts
                    * (float(active_row["settle"]) - float(active_row["open"]))
                    * float(active_row["point_value"])
                )
                position.previous_settle = float(active_row["settle"])
            elif can_split_mark and active_row is not None and _valid_positive(
                active_row["settle"]
            ) and _valid_positive(active_row["open"]) and _valid_positive(
                active_row["point_value"]
            ):
                intraday_pnl = (
                    position.contracts
                    * (float(active_row["settle"]) - float(active_row["open"]))
                    * float(active_row["point_value"])
                )
                position.previous_settle = float(active_row["settle"])
            elif fallback_marked and current_row is not None:
                position.previous_settle = float(current_row["settle"])
            elif active_row is not None and not _valid_positive(active_row["settle"]):
                counters.missing_settle_count += 1
                cash -= gap_pnl
                gap_pnl = 0.0
                session_complete = False
        if position.contracts == 0:
            position.previous_settle = None

        variation_margin = gap_pnl + intraday_pnl + fallback_settle_pnl
        cash += intraday_pnl + fallback_settle_pnl - session_commission - session_slippage
        total_variation_margin += variation_margin
        total_commission += session_commission
        total_slippage += session_slippage
        maximum_participation = max(maximum_participation, session_max_participation)
        exposure_row = _market_row(indexed_market, session_date, position.contract_id)
        gross, modeled_margin, gross_leverage, gross_ok, margin_ok = _daily_exposure(
            exposure_row,
            position.contracts,
            cash,
            settings,
        )
        if position.contracts != 0 and not gross_ok:
            exposure_known = (
                exposure_row is not None
                and _valid_positive(exposure_row["open"])
                and _valid_positive(exposure_row["point_value"])
            )
            if exposure_known:
                counters.gross_limit_breach_count += 1
            session_complete = False
        if position.contracts != 0 and not margin_ok:
            if exposure_row is None or not _valid_positive(exposure_row["initial_margin"]):
                counters.unknown_initial_margin_count += 1
            else:
                counters.initial_margin_buffer_breach_count += 1
            session_complete = False
        if cash <= 0.0:
            session_complete = False
        ledger_rows.append(
            {
                "session_date": session_date,
                "starting_cash": session_start_cash,
                "overnight_gap_vm": gap_pnl,
                "intraday_vm": intraday_pnl,
                "fallback_settle_vm": fallback_settle_pnl,
                "variation_margin": variation_margin,
                "commission_cost": session_commission,
                "slippage_cost": session_slippage,
                "collateral_yield": 0.0,
                "ending_cash": cash,
                "equity": cash,
                "net_return": cash / previous_cash - 1.0,
                "contract_id": position.contract_id or pd.NA,
                "contracts": position.contracts,
                "gross_notional": gross,
                "gross_notional_multiple": gross_leverage,
                "modeled_initial_margin": modeled_margin,
                "required_margin_buffer": (
                    modeled_margin * settings.initial_margin_buffer_multiplier
                    if np.isfinite(modeled_margin)
                    else np.nan
                ),
                "maximum_participation": session_max_participation,
                "execution_status": status,
                "session_execution_complete": session_complete,
            }
        )
        previous_cash = cash

    ledger = pd.DataFrame(ledger_rows)
    orders = pd.DataFrame(order_rows, columns=ORDER_COLUMNS)
    pending_unfilled = bool(
        has_pending
        and (
            pending_contract != position.contract_id
            or pending_contracts != position.contracts
        )
    )
    terminal_carried = position.contracts != 0
    execution_complete = bool(
        counters.total_failures() == 0
        and rejected_event_count == 0
        and not pending_unfilled
        and ledger["session_execution_complete"].all()
    )
    metrics: dict[str, float | int | bool | str] = {
        "initial_cash": float(settings.initial_cash),
        "ending_cash": float(cash),
        "total_return": float(cash / settings.initial_cash - 1.0),
        "variation_margin": float(total_variation_margin),
        "commission_cost": float(total_commission),
        "slippage_cost": float(total_slippage),
        "total_cost": float(total_commission + total_slippage),
        "collateral_yield": 0.0,
        "filled_leg_count": filled_leg_count,
        "roll_count": roll_count,
        "rejected_event_count": rejected_event_count,
        "maximum_participation": float(maximum_participation),
        "terminal_contracts": int(position.contracts),
        "terminal_carried": terminal_carried,
        "pending_unfilled_target": pending_unfilled,
        "execution_complete": execution_complete,
        "research_only": True,
        "broker_exact": False,
        "accounting_note": "modeled_vm_requires_historical_point_value_fee_and_im",
    }
    metrics.update(
        {item.name: int(getattr(counters, item.name)) for item in fields(counters)}
    )
    return FuturesLedgerResult(
        ledger=ledger,
        orders=orders,
        metrics=metrics,
        execution_complete=execution_complete,
    )
