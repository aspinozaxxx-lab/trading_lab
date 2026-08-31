"""Obshchii cash-pool ledger dlya causal'nogo portfelya futures."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Final, Literal

import numpy as np
import pandas as pd

PORTFOLIO_TOLERANCE: Final[float] = 1e-9  # Dopusk denezhnyh i risk-proverok.
PORTFOLIO_ASSETS: Final[tuple[str, ...]] = (  # Fiksirovannyi development-universe.
    "SI",
    "RI",
    "BR",
    "MIX",
)
PORTFOLIO_MARKET_COLUMNS: Final[frozenset[str]] = frozenset(  # Skhema daily market.
    {
        "session_date",
        "asset_code",
        "contract_id",
        "open",
        "high",
        "low",
        "settle",
        "volume",
        "sizing_point_value",
        "accounting_point_value",
        "tick_size",
        "fee_per_contract",
        "initial_margin",
    }
)
PORTFOLIO_TARGET_COLUMNS: Final[frozenset[str]] = frozenset(  # Skhema weight-target.
    {
        "effective_date",
        "decision_date",
        "asset_code",
        "contract_id",
        "target_weight",
    }
)
PORTFOLIO_ORDER_COLUMNS: Final[tuple[str, ...]] = (  # Stabil'naya skhema nog ordera.
    "session_date",
    "atomic_group",
    "asset_code",
    "leg",
    "contract_id",
    "quantity_delta",
    "factual_open",
    "execution_price",
    "point_value",
    "accounting_point_value",
    "tick_size",
    "lagged_volume",
    "participation",
    "gross_notional",
    "commission_cost",
    "slippage_cost",
    "filled",
    "reason",
    "rejection_class",
)
HALT_REASON_TOKENS: Final[frozenset[str]] = frozenset(  # Tol'ko diagnostic halt-prichiny.
    {
        "factual_halt_open",
        "factual_halt_mark",
        "factual_halt_unsized",
        "portfolio_atomic_factual_halt",
    }
)
DIAGNOSTIC_COUNTER_NAMES: Final[frozenset[str]] = frozenset(  # Ne kriticheskie counters.
    {
        "factual_halt_event_count",
        "factual_halt_mark_count",
        "halt_carry_count",
        "halt_order_rejection_count",
        "halt_only_asset_rejection_count",
        "halt_only_portfolio_rejection_count",
        "halt_resolved_count",
        "halt_resolution_event_count",
        "target_cancel_no_open_count",
        "target_cancel_no_liquidity_count",
        "target_cancel_roll_capacity_count",
        "participation_clip_count",
    }
)


@dataclass(frozen=True, slots=True)
class FuturesPortfolioLedgerConfig:
    """Zadaet obshchii kapital i fail-closed limity multi-asset portfelya."""

    initial_cash: float = 1_000_000.0
    expected_assets: tuple[str, ...] = PORTFOLIO_ASSETS
    maximum_gross_notional_multiple: float = 1.0
    initial_margin_buffer_multiplier: float = 2.0
    maximum_participation: float = 0.01
    slippage_ticks: Literal[1, 2, 4] = 1
    fee_multiplier: Literal[1.0, 2.0] = 1.0
    execution_atomicity: Literal["portfolio", "asset"] = "portfolio"
    terminal_policy: Literal["carry"] = "carry"
    unexecutable_target_policy: Literal["retry", "cancel_and_clip"] = "retry"

    def __post_init__(self) -> None:
        """Proveryaet konservativnye granicy do dostupa k market frame."""
        if not np.isfinite(self.initial_cash) or self.initial_cash <= 0.0:
            raise ValueError("initial_cash dolzhen byt' konechnym i polozhitel'nym")
        normalized = tuple(_asset_code(asset) for asset in self.expected_assets)
        if len(normalized) == 0 or len(set(normalized)) != len(normalized):
            raise ValueError("expected_assets dolzhny byt' nepustymi i unikal'nymi")
        if normalized != self.expected_assets:
            raise ValueError("expected_assets dolzhny byt' v canonical upper-case vide")
        if not 0.0 < self.maximum_gross_notional_multiple <= 1.0:
            raise ValueError("maximum_gross_notional_multiple dolzhen byt' v (0, 1]")
        if self.initial_margin_buffer_multiplier < 2.0:
            raise ValueError("initial_margin_buffer_multiplier dolzhen byt' >= 2")
        if not 0.0 < self.maximum_participation <= 0.01:
            raise ValueError("maximum_participation dolzhen byt' v (0, 0.01]")
        if self.slippage_ticks not in {1, 2, 4}:
            raise ValueError("slippage_ticks dolzhen byt' 1, 2 ili 4")
        if self.fee_multiplier not in {1.0, 2.0}:
            raise ValueError("fee_multiplier dolzhen byt' 1.0 ili 2.0")
        if self.execution_atomicity not in {"portfolio", "asset"}:
            raise ValueError("execution_atomicity dolzhen byt' portfolio ili asset")
        if self.terminal_policy != "carry":
            raise ValueError("Multi-asset research-ledger podderzhivaet tol'ko carry")
        if self.unexecutable_target_policy not in {"retry", "cancel_and_clip"}:
            raise ValueError("unexecutable_target_policy dolzhen byt' retry ili cancel_and_clip")
        if (
            self.unexecutable_target_policy == "cancel_and_clip"
            and self.execution_atomicity != "asset"
        ):
            raise ValueError("cancel_and_clip trebuet asset execution_atomicity")


@dataclass(frozen=True, slots=True)
class FuturesPortfolioLedgerResult:
    """Hranit cash-ledger, position snapshots, orders i fail-closed metriki."""

    ledger: pd.DataFrame
    positions: pd.DataFrame
    orders: pd.DataFrame
    metrics: dict[str, float | int | bool | str]
    execution_complete: bool


@dataclass(slots=True)
class _PortfolioPosition:
    """Hranit odnu fakticheskuyu poziciyu asset i poslednii settlement."""

    contract_id: str | None = None
    contracts: int = 0
    previous_settle: float | None = None


@dataclass(slots=True)
class _PortfolioCounters:
    """Nakaplivaet vse prichiny neispolnimosti multi-asset backtesta."""

    missing_contract_row_count: int = 0
    missing_open_count: int = 0
    missing_settle_count: int = 0
    unknown_point_value_count: int = 0
    unknown_tick_size_count: int = 0
    unknown_fee_count: int = 0
    unknown_initial_margin_count: int = 0
    unknown_liquidity_count: int = 0
    participation_rejection_count: int = 0
    gross_limit_rejection_count: int = 0
    initial_margin_rejection_count: int = 0
    atomic_rejection_count: int = 0
    factual_halt_event_count: int = 0
    factual_halt_mark_count: int = 0
    halt_carry_count: int = 0
    halt_order_rejection_count: int = 0
    halt_only_asset_rejection_count: int = 0
    halt_only_portfolio_rejection_count: int = 0
    halt_resolved_count: int = 0
    halt_resolution_event_count: int = 0
    target_cancel_no_open_count: int = 0
    target_cancel_no_liquidity_count: int = 0
    target_cancel_roll_capacity_count: int = 0
    participation_clip_count: int = 0

    def total_failures(self) -> int:
        """Vozvrashchaet tol'ko kriticheskie, a ne diagnostic halt sobytiya."""
        return int(
            sum(
                int(getattr(self, item.name))
                for item in fields(self)
                if item.name not in DIAGNOSTIC_COUNTER_NAMES
            )
        )


def _asset_code(value: object) -> str:
    """Privodit logical asset k canonical kodu portfelya."""
    normalized = str(value).strip().upper()
    return "RI" if normalized == "RTS" else normalized


def _normalize_dates(values: pd.Series) -> pd.Series:
    """Privodit session-date k timezone-naive polunochi bez sdviga daty."""
    timestamps = pd.to_datetime(values, errors="raise")
    if timestamps.dt.tz is not None:
        timestamps = timestamps.dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
    return timestamps.dt.normalize()


def _finite_positive(value: object) -> bool:
    """Proveryaet konechnoe strogo polozhitel'noe znachenie."""
    return bool(pd.notna(value) and np.isfinite(float(value)) and float(value) > 0.0)


def _finite_nonnegative(value: object) -> bool:
    """Proveryaet konechnoe neotricatel'noe znachenie, vklyuchaya nol'."""
    return bool(pd.notna(value) and np.isfinite(float(value)) and float(value) >= 0.0)


def _factual_halt(row: pd.Series | None) -> bool:
    """Raspoznaet factual row bez open, no s dostupnym polozhitel'nym settle."""
    return bool(
        row is not None
        and not _finite_positive(row["open"])
        and _finite_positive(row["settle"])
    )


def _reason_tokens(reasons: list[str]) -> set[str]:
    """Razbivaet sostavnye reason stroki v odnoznachnyi nabor tokenov."""
    return {
        token
        for reason in reasons
        for token in str(reason).split(",")
        if token
    }


def _halt_only(reasons: list[str]) -> bool:
    """Proveryaet, chto otkaz vyzvan tol'ko factual halt bez critical primesi."""
    tokens = _reason_tokens(reasons)
    return bool(tokens) and tokens <= HALT_REASON_TOKENS


def _normalize_market(market: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet multi-asset market i causal'no stroit lagged volume."""
    aliases = {
        "trade_date": "session_date",
        "canonical_contract_id": "contract_id",
    }
    frame = market.rename(
        columns={source: target for source, target in aliases.items() if target not in market}
    ).copy()
    if "point_value" in frame:
        if "sizing_point_value" not in frame:
            frame["sizing_point_value"] = frame["point_value"]
        if "accounting_point_value" not in frame:
            frame["accounting_point_value"] = frame["point_value"]
    if missing := PORTFOLIO_MARKET_COLUMNS - set(frame.columns):
        raise ValueError(f"V portfolio market net kolonok: {sorted(missing)}")
    frame = frame.loc[:, sorted(PORTFOLIO_MARKET_COLUMNS)].copy()
    frame["session_date"] = _normalize_dates(frame["session_date"])
    frame["asset_code"] = frame["asset_code"].map(_asset_code)
    frame["contract_id"] = frame["contract_id"].astype("string")
    if frame["asset_code"].eq("").any() or frame["contract_id"].isna().any():
        raise ValueError("asset_code i contract_id ne mogut byt' pustymi")
    numeric = PORTFOLIO_MARKET_COLUMNS - {
        "session_date",
        "asset_code",
        "contract_id",
    }
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in (
        "open",
        "high",
        "low",
        "settle",
        "sizing_point_value",
        "accounting_point_value",
        "tick_size",
    ):
        values = frame[column].dropna()
        if (~np.isfinite(values)).any() or (values <= 0.0).any():
            raise ValueError(f"Dostupnoe pole {column} dolzhno byt' polozhitel'nym")
    for column in ("volume", "fee_per_contract", "initial_margin"):
        values = frame[column].dropna()
        if (~np.isfinite(values)).any() or (values < 0.0).any():
            raise ValueError(f"Dostupnoe pole {column} ne mozhet byt' otricatel'nym")
    complete = frame[["open", "high", "low"]].notna().all(axis=1)
    invalid = complete & (
        (frame["low"] > frame["open"])
        | (frame["high"] < frame["open"])
        | (frame["high"] < frame["low"])
    )
    if invalid.any():
        raise ValueError("Narushen daily high/low/open invariant")
    if frame.duplicated(["session_date", "asset_code", "contract_id"]).any():
        raise ValueError("Povtor session/asset/contract v portfolio market")
    frame = frame.sort_values(
        ["asset_code", "contract_id", "session_date"], kind="mergesort"
    ).reset_index(drop=True)
    frame["lagged_volume"] = frame.groupby(
        ["asset_code", "contract_id"], sort=False
    )["volume"].shift(1)
    return frame.sort_values(
        ["session_date", "asset_code", "contract_id"], kind="mergesort"
    ).reset_index(drop=True)


def _normalize_targets(
    targets: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    expected_assets: tuple[str, ...],
) -> pd.DataFrame:
    """Proveryaet polnye causal'nye weight-snapshot dlya kazhdogo resheniya."""
    aliases = {
        "session_date": "effective_date",
        "canonical_contract_id": "contract_id",
    }
    frame = targets.rename(
        columns={source: target for source, target in aliases.items() if target not in targets}
    ).copy()
    if missing := PORTFOLIO_TARGET_COLUMNS - set(frame.columns):
        raise ValueError(f"V portfolio targets net kolonok: {sorted(missing)}")
    keep = sorted(PORTFOLIO_TARGET_COLUMNS | ({"observed_through"} & set(frame.columns)))
    frame = frame.loc[:, keep].copy()
    frame["effective_date"] = _normalize_dates(frame["effective_date"])
    frame["decision_date"] = _normalize_dates(frame["decision_date"])
    if "observed_through" in frame:
        frame["observed_through"] = _normalize_dates(frame["observed_through"])
    frame["asset_code"] = frame["asset_code"].map(_asset_code)
    frame["contract_id"] = frame["contract_id"].astype("string")
    frame["target_weight"] = pd.to_numeric(frame["target_weight"], errors="raise")
    if (~np.isfinite(frame["target_weight"])).any():
        raise ValueError("target_weight dolzhen byt' konechnym")
    if (frame["target_weight"].abs() > 1.0 + PORTFOLIO_TOLERANCE).any():
        raise ValueError("Otdel'nyi target_weight ne mozhet prevyshat' 1")
    nonzero = frame["target_weight"].abs() > PORTFOLIO_TOLERANCE
    if frame.loc[nonzero, "contract_id"].isna().any() or frame.loc[
        nonzero, "contract_id"
    ].eq("").any():
        raise ValueError("Nenulevoi target_weight trebuet contract_id")
    frame.loc[~nonzero, "contract_id"] = pd.NA
    if (frame["decision_date"] >= frame["effective_date"]).any():
        raise ValueError("decision_date dolzhen byt' ran'she effective open")
    if "observed_through" in frame and (
        frame["observed_through"] > frame["decision_date"]
    ).any():
        raise ValueError("observed_through ne mozhet byt' pozhe decision_date")
    if frame.duplicated(["effective_date", "asset_code"]).any():
        raise ValueError("Povtor asset v odnom portfolio snapshot")
    expected = frozenset(expected_assets)
    for effective_date, snapshot in frame.groupby("effective_date", sort=False):
        if frozenset(snapshot["asset_code"]) != expected:
            raise ValueError(f"Nepolnyi asset snapshot na {effective_date.date()}")
        if snapshot["decision_date"].nunique() != 1:
            raise ValueError("Odin snapshot dolzhen imet' odnu decision_date")
        if snapshot["target_weight"].abs().sum() > 1.0 + PORTFOLIO_TOLERANCE:
            raise ValueError("Gross target weights prevyshayut 1x")
    unknown_dates = set(frame["effective_date"]) - set(calendar)
    if unknown_dates:
        raise ValueError("effective_date dolzhen byt' factual market session")
    return frame.sort_values(["effective_date", "asset_code"]).reset_index(drop=True)


def _market_row(
    indexed: pd.DataFrame,
    session_date: pd.Timestamp,
    asset_code: str,
    contract_id: str | None,
) -> pd.Series | None:
    """Nahodit odnu factual stroku kontrakta v ukazannuyu sessiyu."""
    if contract_id is None:
        return None
    try:
        row = indexed.loc[(session_date, asset_code, contract_id)]
    except KeyError:
        return None
    if isinstance(row, pd.DataFrame):
        raise RuntimeError("Vnutrennii dublikat portfolio market")
    return row


def _desired_legs(
    position: _PortfolioPosition,
    desired_contract: str | None,
    desired_contracts: int,
) -> list[tuple[str, str, int]]:
    """Razlagaet asset-target na rebalance ili dve atomarnye nogi rola."""
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


def _leg(
    session_date: pd.Timestamp,
    atomic_group: str,
    asset_code: str,
    leg_name: str,
    contract_id: str,
    quantity_delta: int,
    row: pd.Series | None,
    config: FuturesPortfolioLedgerConfig,
    counters: _PortfolioCounters,
) -> dict[str, object]:
    """Stroit odnu nogu s factual open, specs i lagged participation."""
    output: dict[str, object] = {
        "session_date": session_date,
        "atomic_group": atomic_group,
        "asset_code": asset_code,
        "leg": leg_name,
        "contract_id": contract_id,
        "quantity_delta": int(quantity_delta),
        "factual_open": np.nan,
        "execution_price": np.nan,
        "point_value": np.nan,
        "accounting_point_value": np.nan,
        "tick_size": np.nan,
        "lagged_volume": np.nan,
        "participation": np.inf,
        "gross_notional": np.nan,
        "commission_cost": np.nan,
        "slippage_cost": np.nan,
        "filled": False,
        "reason": "",
        "rejection_class": "",
    }
    reasons: list[str] = []
    if row is None:
        counters.missing_contract_row_count += 1
        output["reason"] = "missing_contract_row"
        output["rejection_class"] = "critical"
        return output
    output.update(
        {
            "factual_open": row["open"],
            "point_value": row["sizing_point_value"],
            "accounting_point_value": row["accounting_point_value"],
            "tick_size": row["tick_size"],
            "lagged_volume": row["lagged_volume"],
        }
    )
    if not _finite_positive(row["open"]):
        if _factual_halt(row):
            reasons.append("factual_halt_open")
        else:
            counters.missing_open_count += 1
            reasons.append("missing_factual_open")
            if not _finite_positive(row["settle"]):
                counters.missing_settle_count += 1
                reasons.append("missing_factual_settle")
    if not _finite_positive(row["sizing_point_value"]):
        counters.unknown_point_value_count += 1
        reasons.append("unknown_sizing_point_value")
    if not _finite_positive(row["accounting_point_value"]):
        counters.unknown_point_value_count += 1
        reasons.append("unknown_accounting_point_value")
    if not _finite_positive(row["tick_size"]):
        counters.unknown_tick_size_count += 1
        reasons.append("unknown_tick_size")
    if not _finite_nonnegative(row["fee_per_contract"]):
        counters.unknown_fee_count += 1
        reasons.append("unknown_fee")
    lagged_volume = row["lagged_volume"]
    if not _finite_positive(lagged_volume):
        counters.unknown_liquidity_count += 1
        reasons.append("unknown_lagged_volume")
    else:
        participation = abs(quantity_delta) / float(lagged_volume)
        output["participation"] = participation
        if participation > config.maximum_participation + PORTFOLIO_TOLERANCE:
            counters.participation_rejection_count += 1
            reasons.append("participation_limit")
    if reasons:
        output["reason"] = ",".join(reasons)
        output["rejection_class"] = "factual_halt" if _halt_only(reasons) else "critical"
        return output
    factual_open = float(row["open"])
    point_value = float(row["sizing_point_value"])
    tick_size = float(row["tick_size"])
    direction = 1.0 if quantity_delta > 0 else -1.0
    output.update(
        {
            "execution_price": factual_open + direction * config.slippage_ticks * tick_size,
            "gross_notional": abs(quantity_delta) * factual_open * point_value,
            "commission_cost": abs(quantity_delta)
            * float(row["fee_per_contract"])
            * config.fee_multiplier,
            "slippage_cost": abs(quantity_delta)
            * config.slippage_ticks
            * tick_size
            * point_value,
            "reason": "ready",
            "rejection_class": "",
        }
    )
    return output


def _target_quantity(weight: float, equity: float, row: pd.Series | None) -> int | None:
    """Prevrashchaet weight v celye kontrakty prostym conservative truncation."""
    if abs(weight) <= PORTFOLIO_TOLERANCE:
        return 0
    if row is None or not _finite_positive(row["open"]) or not _finite_positive(
        row["sizing_point_value"]
    ):
        return None
    notional = float(row["open"]) * float(row["sizing_point_value"])
    magnitude = int(np.floor(abs(weight) * max(equity, 0.0) / notional))
    return magnitude if weight > 0.0 else -magnitude


def _unsized_target_reasons(
    row: pd.Series | None,
    counters: _PortfolioCounters,
) -> list[str]:
    """Klassificiruet nepoluchennyi target size kak halt ili critical data fault."""
    if row is None:
        counters.missing_contract_row_count += 1
        return ["missing_contract_row"]
    reasons: list[str] = []
    if not _finite_positive(row["open"]):
        if _factual_halt(row):
            reasons.append("factual_halt_unsized")
        else:
            counters.missing_open_count += 1
            reasons.append("missing_factual_open")
            if not _finite_positive(row["settle"]):
                counters.missing_settle_count += 1
                reasons.append("missing_factual_settle")
    for column, reason in (
        ("sizing_point_value", "unknown_sizing_point_value"),
        ("accounting_point_value", "unknown_accounting_point_value"),
    ):
        if not _finite_positive(row[column]):
            counters.unknown_point_value_count += 1
            reasons.append(reason)
    if not _finite_positive(row["tick_size"]):
        counters.unknown_tick_size_count += 1
        reasons.append("unknown_tick_size")
    if not _finite_nonnegative(row["fee_per_contract"]):
        counters.unknown_fee_count += 1
        reasons.append("unknown_fee")
    if not _finite_positive(row["lagged_volume"]):
        counters.unknown_liquidity_count += 1
        reasons.append("unknown_lagged_volume")
    if not _finite_positive(row["initial_margin"]):
        counters.unknown_initial_margin_count += 1
        reasons.append("unknown_initial_margin")
    return reasons


def _estimated_rebalance_cost(
    desired: dict[str, tuple[str | None, int, pd.Series | None]],
    positions: dict[str, _PortfolioPosition],
    indexed: pd.DataFrame,
    session_date: pd.Timestamp,
    config: FuturesPortfolioLedgerConfig,
) -> float:
    """Ocenivaet denezhnye costs vseh nog do okonchatel'nogo integer sizing."""
    total = 0.0
    for asset, (contract, quantity, _) in desired.items():
        for _, leg_contract, delta in _desired_legs(
            positions[asset], contract, quantity
        ):
            row = _market_row(indexed, session_date, asset, leg_contract)
            if row is None:
                continue
            if not all(
                (
                    _finite_positive(row["sizing_point_value"]),
                    _finite_positive(row["tick_size"]),
                    _finite_nonnegative(row["fee_per_contract"]),
                )
            ):
                continue
            total += abs(delta) * (
                float(row["fee_per_contract"]) * config.fee_multiplier
                + config.slippage_ticks
                * float(row["tick_size"])
                * float(row["sizing_point_value"])
            )
    return float(total)


def _fit_integer_risk_budget(
    desired: dict[str, tuple[str | None, int, pd.Series | None]],
    positions: dict[str, _PortfolioPosition],
    indexed: pd.DataFrame,
    session_date: pd.Timestamp,
    equity: float,
    config: FuturesPortfolioLedgerConfig,
) -> dict[str, tuple[str | None, int, pd.Series | None]]:
    """Snizhaet krupneishuyu nogu, poka gross, costs i IM ne pomeshchayutsya."""
    fitted = dict(desired)
    maximum_steps = sum(abs(quantity) for _, quantity, _ in fitted.values()) + 1
    for _ in range(maximum_steps):
        gross = 0.0
        margin = 0.0
        candidates: list[tuple[float, str]] = []
        for asset, (contract, quantity, row) in fitted.items():
            if quantity == 0 or row is None:
                continue
            carried = (
                contract == positions[asset].contract_id
                and quantity == positions[asset].contracts
            )
            risk_price = (
                row["open"]
                if _finite_positive(row["open"])
                else row["settle"] if carried and _finite_positive(row["settle"]) else np.nan
            )
            notional = (
                float(risk_price) * float(row["sizing_point_value"])
                if _finite_positive(risk_price)
                and _finite_positive(row["sizing_point_value"])
                else 0.0
            )
            gross += abs(quantity) * notional
            if _finite_positive(row["initial_margin"]):
                margin += abs(quantity) * float(row["initial_margin"])
            candidates.append((abs(quantity) * notional, asset))
        estimated_cost = _estimated_rebalance_cost(
            fitted,
            positions,
            indexed,
            session_date,
            config,
        )
        available = max(equity - estimated_cost, 0.0)
        gross_ok = (
            gross
            <= available * config.maximum_gross_notional_multiple
            + PORTFOLIO_TOLERANCE
        )
        margin_ok = (
            margin * config.initial_margin_buffer_multiplier
            <= available + PORTFOLIO_TOLERANCE
        )
        if gross_ok and margin_ok:
            return fitted
        if not candidates:
            return fitted
        _, asset = max(candidates)
        contract, quantity, row = fitted[asset]
        fitted[asset] = (
            contract,
            quantity - (1 if quantity > 0 else -1),
            row,
        )
    raise RuntimeError("Integer risk fitting ne soshelsya za konechnoe chislo shagov")


def _fit_capacity_admission(
    desired: dict[str, tuple[str | None, int, pd.Series | None]],
    positions: dict[str, _PortfolioPosition],
    indexed: pd.DataFrame,
    session_date: pd.Timestamp,
    config: FuturesPortfolioLedgerConfig,
    counters: _PortfolioCounters,
) -> tuple[
    dict[str, tuple[str | None, int, pd.Series | None]],
    set[str],
    set[str],
]:
    """Cancel unprovable legs and clip one-contract-series deltas to known capacity."""
    fitted = dict(desired)
    cancelled: set[str] = set()
    clipped: set[str] = set()
    for asset, (desired_contract, desired_quantity, _) in desired.items():
        legs = _desired_legs(positions[asset], desired_contract, desired_quantity)
        if not legs:
            continue
        leg_rows = [
            (
                leg_name,
                leg_contract,
                delta,
                _market_row(indexed, session_date, asset, leg_contract),
            )
            for leg_name, leg_contract, delta in legs
        ]
        if any(row is None for _, _, _, row in leg_rows):
            continue
        halt_rows = [
            row
            for _, _, _, row in leg_rows
            if row is not None and not _finite_positive(row["open"]) and _factual_halt(row)
        ]
        if halt_rows:
            position = positions[asset]
            current_row = _market_row(indexed, session_date, asset, position.contract_id)
            fitted[asset] = (position.contract_id, position.contracts, current_row)
            counters.target_cancel_no_open_count += 1
            cancelled.add(asset)
            continue
        if any(
            row is not None and not _finite_positive(row["lagged_volume"])
            for _, _, _, row in leg_rows
        ):
            position = positions[asset]
            current_row = _market_row(indexed, session_date, asset, position.contract_id)
            fitted[asset] = (position.contract_id, position.contracts, current_row)
            counters.target_cancel_no_liquidity_count += 1
            cancelled.add(asset)
            continue
        capacities = [
            int(np.floor(float(row["lagged_volume"]) * config.maximum_participation))
            for _, _, _, row in leg_rows
            if row is not None
        ]
        if len(legs) > 1:
            if any(
                abs(delta) > capacity
                for (_, _, delta, _), capacity in zip(
                    leg_rows, capacities, strict=True
                )
            ):
                position = positions[asset]
                current_row = _market_row(
                    indexed, session_date, asset, position.contract_id
                )
                fitted[asset] = (position.contract_id, position.contracts, current_row)
                counters.target_cancel_roll_capacity_count += 1
                cancelled.add(asset)
            continue
        _, leg_contract, delta, row = leg_rows[0]
        capacity = capacities[0]
        if abs(delta) <= capacity:
            continue
        admitted_delta = (1 if delta > 0 else -1) * capacity
        admitted_quantity = positions[asset].contracts + admitted_delta
        admitted_contract = leg_contract if admitted_quantity != 0 else None
        fitted[asset] = (admitted_contract, admitted_quantity, row)
        counters.participation_clip_count += 1
        clipped.add(asset)
        if capacity == 0:
            cancelled.add(asset)
    return fitted, cancelled, clipped


def _risk_reasons(
    desired: dict[str, tuple[str | None, int, pd.Series | None]],
    estimated_equity: float,
    config: FuturesPortfolioLedgerConfig,
    counters: _PortfolioCounters,
) -> tuple[list[str], float, float]:
    """Proveryaet aggregate gross i modeled initial margin vsego portfelya."""
    reasons: list[str] = []
    gross = 0.0
    margin = 0.0
    for _, contracts, row in desired.values():
        if contracts == 0:
            continue
        if row is None:
            reasons.append("missing_desired_contract_row")
            continue
        if not _finite_positive(row["sizing_point_value"]):
            counters.unknown_point_value_count += 1
            reasons.append("unknown_sizing_point_value")
        risk_price = row["open"] if _finite_positive(row["open"]) else row["settle"]
        if not _finite_positive(risk_price):
            counters.missing_open_count += 1
            counters.missing_settle_count += 1
            reasons.extend(("missing_factual_open", "missing_factual_settle"))
        if not _finite_positive(row["initial_margin"]):
            counters.unknown_initial_margin_count += 1
            reasons.append("unknown_initial_margin")
        if _finite_positive(row["sizing_point_value"]) and _finite_positive(risk_price):
            gross += (
                abs(contracts)
                * float(risk_price)
                * float(row["sizing_point_value"])
            )
        if _finite_positive(row["initial_margin"]):
            margin += abs(contracts) * float(row["initial_margin"])
    cap = max(estimated_equity, 0.0)
    if gross > cap * config.maximum_gross_notional_multiple + PORTFOLIO_TOLERANCE:
        counters.gross_limit_rejection_count += 1
        reasons.append("aggregate_gross_limit")
    if margin * config.initial_margin_buffer_multiplier > cap + PORTFOLIO_TOLERANCE:
        counters.initial_margin_rejection_count += 1
        reasons.append("aggregate_initial_margin_buffer")
    return list(dict.fromkeys(reasons)), gross, margin


def _performance_metrics(
    equity: pd.Series,
    dates: pd.Series,
    initial_cash: float,
) -> dict[str, float]:
    """Schitaet daily CAGR, Sharpe i drawdown s nachal'noi tochkoi kapitala."""
    values = np.r_[initial_cash, equity.to_numpy(dtype=float)]
    returns = pd.Series(values).pct_change().dropna()
    total_return = float(values[-1] / initial_cash - 1.0)
    elapsed_days = max((pd.Timestamp(dates.iloc[-1]) - pd.Timestamp(dates.iloc[0])).days, 1)
    years = elapsed_days / 365.2425
    cagr = float((values[-1] / initial_cash) ** (1.0 / years) - 1.0) if values[-1] > 0 else -1.0
    deviation = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    sharpe = float(np.sqrt(252.0) * returns.mean() / deviation) if deviation > 0.0 else 0.0
    peaks = np.maximum.accumulate(values)
    maximum_drawdown = float(np.max(1.0 - values / peaks))
    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": maximum_drawdown,
    }


def run_futures_portfolio_ledger(
    market: pd.DataFrame,
    targets: pd.DataFrame,
    config: FuturesPortfolioLedgerConfig | None = None,
) -> FuturesPortfolioLedgerResult:
    """Ispolnyaet polnyi weight-snapshot na next factual open v obshchem cash-pool."""
    settings = config or FuturesPortfolioLedgerConfig()
    normalized_market = _normalize_market(market)
    available_assets = frozenset(normalized_market["asset_code"].unique())
    if not frozenset(settings.expected_assets) <= available_assets:
        raise ValueError("Portfolio market ne soderzhit vse expected_assets")
    calendar = pd.DatetimeIndex(
        normalized_market["session_date"].drop_duplicates().sort_values()
    )
    normalized_targets = _normalize_targets(targets, calendar, settings.expected_assets)
    target_by_date = {
        pd.Timestamp(effective_date): snapshot.copy()
        for effective_date, snapshot in normalized_targets.groupby("effective_date", sort=False)
    }
    indexed = normalized_market.set_index(["session_date", "asset_code", "contract_id"])
    positions = {asset: _PortfolioPosition() for asset in settings.expected_assets}
    counters = _PortfolioCounters()
    cash = float(settings.initial_cash)
    ledger_rows: list[dict[str, object]] = []
    position_rows: list[dict[str, object]] = []
    order_rows: list[dict[str, object]] = []
    total_vm = 0.0
    total_commission = 0.0
    total_slippage = 0.0
    total_order_notional = 0.0
    maximum_participation = 0.0
    minimum_intraday_equity = cash
    running_equity_peak = cash
    maximum_intraday_adverse_drawdown = 0.0
    maximum_gross = 0.0
    maximum_margin = 0.0
    pending_asset_targets: dict[str, dict[str, object]] = {}
    pending_portfolio_targets: dict[str, dict[str, object]] | None = None
    pending_portfolio_halt_assets: set[str] = set()
    target_policy = str(getattr(settings, "unexecutable_target_policy", "retry"))
    if target_policy not in {"retry", "cancel_and_clip"}:
        raise ValueError("unknown unexecutable_target_policy")

    for session_number, session_value in enumerate(calendar):
        session_date = pd.Timestamp(session_value)
        start_cash = cash
        gap_vm = 0.0
        fallback_vm = 0.0
        critical_blocked_assets: set[str] = set()
        halt_mark_assets: set[str] = set()
        session_halt_assets: set[str] = set()
        capacity_cancelled_assets: set[str] = set()
        participation_clipped_assets: set[str] = set()
        for asset, position in positions.items():
            if position.contracts == 0:
                continue
            row = _market_row(indexed, session_date, asset, position.contract_id)
            if row is None:
                counters.missing_contract_row_count += 1
                critical_blocked_assets.add(asset)
                continue
            if not _finite_positive(row["accounting_point_value"]):
                counters.unknown_point_value_count += 1
                critical_blocked_assets.add(asset)
                continue
            if position.previous_settle is None or not _finite_positive(row["settle"]):
                counters.missing_settle_count += 1
                critical_blocked_assets.add(asset)
                continue
            if _finite_positive(row["open"]):
                gap_vm += position.contracts * (
                    float(row["open"]) - position.previous_settle
                ) * float(row["accounting_point_value"])
            else:
                fallback_vm += position.contracts * (
                    float(row["settle"]) - position.previous_settle
                ) * float(row["accounting_point_value"])
                position.previous_settle = float(row["settle"])
                halt_mark_assets.add(asset)
                session_halt_assets.add(asset)
                counters.factual_halt_mark_count += 1
                counters.halt_carry_count += 1
        cash += gap_vm + fallback_vm

        session_commission = 0.0
        session_slippage = 0.0
        status = "factual_halt_carry" if halt_mark_assets else "hold"
        incoming = target_by_date.get(session_date)
        incoming_targets = (
            {
                str(target["asset_code"]): target
                for target in incoming.to_dict("records")
            }
            if incoming is not None
            else {}
        )
        retry_assets: set[str] = set()
        retrying_portfolio = False
        previous_portfolio_halt_assets: set[str] = set()
        if settings.execution_atomicity == "asset":
            if incoming_targets:
                active_targets = incoming_targets
                retry_assets = set(pending_asset_targets) & set(active_targets)
            else:
                active_targets = dict(pending_asset_targets)
                retry_assets = set(active_targets)
        else:
            if incoming_targets:
                active_targets = incoming_targets
                retrying_portfolio = pending_portfolio_targets is not None
            elif pending_portfolio_targets is not None:
                active_targets = dict(pending_portfolio_targets)
                retrying_portfolio = True
            else:
                active_targets = {}
            previous_portfolio_halt_assets = set(pending_portfolio_halt_assets)
        if active_targets:
            desired: dict[str, tuple[str | None, int, pd.Series | None]] = {}
            asset_failures: dict[str, list[str]] = {}
            for asset in settings.expected_assets:
                target = active_targets.get(asset)
                if target is None:
                    position = positions[asset]
                    current_row = _market_row(
                        indexed,
                        session_date,
                        asset,
                        position.contract_id,
                    )
                    desired[asset] = (
                        position.contract_id,
                        position.contracts,
                        current_row,
                    )
                    continue
                contract = None if pd.isna(target["contract_id"]) else str(
                    target["contract_id"]
                )
                row = _market_row(indexed, session_date, asset, contract)
                if (
                    target_policy == "cancel_and_clip"
                    and contract is not None
                    and row is not None
                    and not _finite_positive(row["open"])
                    and _factual_halt(row)
                ):
                    position = positions[asset]
                    current_row = _market_row(
                        indexed,
                        session_date,
                        asset,
                        position.contract_id,
                    )
                    desired[asset] = (
                        position.contract_id,
                        position.contracts,
                        current_row,
                    )
                    counters.target_cancel_no_open_count += 1
                    capacity_cancelled_assets.add(asset)
                    session_halt_assets.add(asset)
                    continue
                quantity = _target_quantity(float(target["target_weight"]), cash, row)
                if quantity is None:
                    reasons = _unsized_target_reasons(row, counters)
                    asset_failures.setdefault(asset, []).extend(reasons)
                    if _halt_only(reasons):
                        session_halt_assets.add(asset)
                    position = positions[asset]
                    contract = position.contract_id
                    quantity = position.contracts
                    row = _market_row(indexed, session_date, asset, contract)
                desired[asset] = (contract, quantity, row)
            desired = _fit_integer_risk_budget(
                desired,
                positions,
                indexed,
                session_date,
                cash,
                settings,
            )
            if target_policy == "cancel_and_clip":
                desired, cancelled, clipped = _fit_capacity_admission(
                    desired,
                    positions,
                    indexed,
                    session_date,
                    settings,
                    counters,
                )
                capacity_cancelled_assets.update(cancelled)
                participation_clipped_assets.update(clipped)
            proposed: list[dict[str, object]] = []
            atomic_group = f"{session_date.date().isoformat()}:{session_number:06d}"
            for asset in settings.expected_assets:
                contract, quantity, _ = desired[asset]
                for leg_name, leg_contract, delta in _desired_legs(
                    positions[asset], contract, quantity
                ):
                    leg = _leg(
                        session_date,
                        atomic_group,
                        asset,
                        leg_name,
                        leg_contract,
                        delta,
                        _market_row(indexed, session_date, asset, leg_contract),
                        settings,
                        counters,
                    )
                    proposed.append(leg)
                    if leg["rejection_class"] == "factual_halt":
                        session_halt_assets.add(asset)
            for leg in proposed:
                asset = str(leg["asset_code"])
                if leg["reason"] != "ready":
                    asset_failures.setdefault(asset, []).append(str(leg["reason"]))
            changing_assets = {str(leg["asset_code"]) for leg in proposed} | set(
                asset_failures
            )
            for asset in changing_assets & critical_blocked_assets:
                asset_failures.setdefault(asset, []).append("critical_mark_block")
            for asset in changing_assets & halt_mark_assets:
                asset_failures.setdefault(asset, []).append("factual_halt_mark")
            if settings.execution_atomicity == "asset":
                effective_desired = dict(desired)
                for asset in asset_failures:
                    position = positions[asset]
                    current_row = _market_row(
                        indexed,
                        session_date,
                        asset,
                        position.contract_id,
                    )
                    effective_desired[asset] = (
                        position.contract_id,
                        position.contracts,
                        current_row,
                    )
                ready_legs = [
                    leg for leg in proposed if str(leg["asset_code"]) not in asset_failures
                ]
                estimated_cost = sum(
                    float(leg["commission_cost"]) + float(leg["slippage_cost"])
                    for leg in ready_legs
                )
                risk_reasons, _, _ = _risk_reasons(
                    effective_desired,
                    cash - estimated_cost,
                    settings,
                    counters,
                )
                if risk_reasons:
                    ready_assets = {str(leg["asset_code"]) for leg in ready_legs}
                    for asset in ready_assets:
                        asset_failures.setdefault(asset, []).extend(risk_reasons)
                halt_failures = {
                    asset for asset, reasons in asset_failures.items() if _halt_only(reasons)
                }
                critical_failures = set(asset_failures) - halt_failures
                filled_assets: set[str] = set()
                for leg in proposed:
                    asset = str(leg["asset_code"])
                    if asset in asset_failures:
                        leg["filled"] = False
                        leg["reason"] = ",".join(dict.fromkeys(asset_failures[asset]))
                        leg["rejection_class"] = (
                            "factual_halt" if asset in halt_failures else "critical"
                        )
                        continue
                    leg["filled"] = True
                    leg["reason"] = (
                        "filled_after_factual_halt"
                        if asset in retry_assets
                        else (
                            "filled_participation_clipped"
                            if asset in participation_clipped_assets
                            else "filled"
                        )
                    )
                    leg["rejection_class"] = (
                        "resolved_halt" if asset in retry_assets else ""
                    )
                    filled_assets.add(asset)
                    session_commission += float(leg["commission_cost"])
                    session_slippage += float(leg["slippage_cost"])
                    total_order_notional += float(leg["gross_notional"])
                    maximum_participation = max(
                        maximum_participation,
                        float(leg["participation"]),
                    )
                for asset, (contract, quantity, _) in desired.items():
                    if asset not in asset_failures:
                        positions[asset].contract_id = contract if quantity != 0 else None
                        positions[asset].contracts = int(quantity)
                for asset in halt_failures:
                    if asset in active_targets:
                        pending_asset_targets[asset] = active_targets[asset]
                for asset in critical_failures:
                    pending_asset_targets.pop(asset, None)
                resolved_assets = retry_assets - set(asset_failures)
                if resolved_assets:
                    counters.halt_resolved_count += len(resolved_assets)
                    counters.halt_resolution_event_count += 1
                    for asset in resolved_assets:
                        pending_asset_targets.pop(asset, None)
                counters.halt_order_rejection_count += len(halt_failures)
                counters.halt_only_asset_rejection_count += len(halt_failures)
                counters.atomic_rejection_count += len(critical_failures)
                if halt_failures and filled_assets:
                    status = "partial_asset_atomic_halt_pending"
                elif halt_failures and not critical_failures:
                    status = "asset_atomic_halt_pending"
                elif asset_failures and filled_assets:
                    status = "partial_asset_atomic_rebalance"
                elif asset_failures:
                    status = "asset_atomic_critical_rejected"
                elif capacity_cancelled_assets and filled_assets:
                    status = "partial_capacity_admission"
                elif capacity_cancelled_assets:
                    status = "target_cancelled_by_capacity_admission"
                else:
                    status = "portfolio_rebalanced" if proposed else "target_unchanged"
            else:
                estimated_cost = sum(
                    float(leg["commission_cost"]) + float(leg["slippage_cost"])
                    for leg in proposed
                    if leg["reason"] == "ready"
                )
                risk_reasons, _, _ = _risk_reasons(
                    desired,
                    cash - estimated_cost,
                    settings,
                    counters,
                )
                halt_failures = {
                    asset for asset, reasons in asset_failures.items() if _halt_only(reasons)
                }
                critical_failures = set(asset_failures) - halt_failures
                portfolio_halt_only = bool(halt_failures) and not critical_failures and not (
                    risk_reasons
                )
                if asset_failures or risk_reasons:
                    if portfolio_halt_only:
                        pending_portfolio_targets = dict(active_targets)
                        pending_portfolio_halt_assets = set(halt_failures)
                        counters.halt_order_rejection_count += len(halt_failures)
                        counters.halt_only_portfolio_rejection_count += 1
                        status = "portfolio_atomic_halt_pending"
                        rejection_class = "factual_halt"
                        reason = "portfolio_atomic_factual_halt"
                    else:
                        pending_portfolio_targets = None
                        pending_portfolio_halt_assets.clear()
                        counters.atomic_rejection_count += 1
                        status = "portfolio_atomic_critical_rejected"
                        rejection_class = "critical"
                        all_reasons = [
                            reason
                            for reasons in asset_failures.values()
                            for reason in reasons
                        ] + risk_reasons
                        reason = ",".join(dict.fromkeys(all_reasons))
                    for leg in proposed:
                        leg["filled"] = False
                        leg["reason"] = reason
                        leg["rejection_class"] = rejection_class
                else:
                    for leg in proposed:
                        leg["filled"] = True
                        leg["reason"] = (
                            "filled_after_factual_halt"
                            if retrying_portfolio
                            else "filled"
                        )
                        leg["rejection_class"] = (
                            "resolved_halt" if retrying_portfolio else ""
                        )
                        session_commission += float(leg["commission_cost"])
                        session_slippage += float(leg["slippage_cost"])
                        total_order_notional += float(leg["gross_notional"])
                        maximum_participation = max(
                            maximum_participation,
                            float(leg["participation"]),
                        )
                    for asset, (contract, quantity, _) in desired.items():
                        positions[asset].contract_id = contract if quantity != 0 else None
                        positions[asset].contracts = int(quantity)
                    if retrying_portfolio:
                        counters.halt_resolved_count += len(
                            previous_portfolio_halt_assets
                        )
                        counters.halt_resolution_event_count += 1
                    pending_portfolio_targets = None
                    pending_portfolio_halt_assets.clear()
                    status = "portfolio_rebalanced" if proposed else "target_unchanged"
            order_rows.extend(proposed)
        counters.factual_halt_event_count += len(session_halt_assets)

        open_cash = cash - session_commission - session_slippage
        intraday_vm = 0.0
        adverse_vm = 0.0
        gross = 0.0
        modeled_margin = 0.0
        for asset, position in positions.items():
            row = _market_row(indexed, session_date, asset, position.contract_id)
            if position.contracts == 0:
                position.previous_settle = None
                position_rows.append(
                    {
                        "session_date": session_date,
                        "asset_code": asset,
                        "contract_id": pd.NA,
                        "contracts": 0,
                        "gross_notional": 0.0,
                        "modeled_initial_margin": 0.0,
                    }
                )
                continue
            if row is None:
                position_rows.append(
                    {
                        "session_date": session_date,
                        "asset_code": asset,
                        "contract_id": position.contract_id,
                        "contracts": position.contracts,
                        "gross_notional": np.nan,
                        "modeled_initial_margin": np.nan,
                    }
                )
                continue
            if not _finite_positive(row["accounting_point_value"]):
                counters.unknown_point_value_count += 1
                critical_blocked_assets.add(asset)
                position_rows.append(
                    {
                        "session_date": session_date,
                        "asset_code": asset,
                        "contract_id": position.contract_id,
                        "contracts": position.contracts,
                        "gross_notional": np.nan,
                        "modeled_initial_margin": np.nan,
                    }
                )
                continue
            point_value = float(row["accounting_point_value"])
            if _finite_positive(row["open"]) and _finite_positive(row["settle"]):
                intraday_vm += position.contracts * (
                    float(row["settle"]) - float(row["open"])
                ) * point_value
                position.previous_settle = float(row["settle"])
                if _finite_positive(row["low"]) and _finite_positive(row["high"]):
                    adverse_price = float(row["low"] if position.contracts > 0 else row["high"])
                    adverse_vm += position.contracts * (
                        adverse_price - float(row["open"])
                    ) * point_value
            elif asset not in critical_blocked_assets and asset not in halt_mark_assets:
                counters.missing_settle_count += 1
                critical_blocked_assets.add(asset)
            mark = row["settle"] if _finite_positive(row["settle"]) else row["open"]
            asset_gross = (
                abs(position.contracts) * float(mark) * point_value
                if _finite_positive(mark)
                else np.nan
            )
            asset_margin = (
                abs(position.contracts) * float(row["initial_margin"])
                if _finite_positive(row["initial_margin"])
                else np.nan
            )
            if np.isfinite(asset_gross):
                gross += float(asset_gross)
            if np.isfinite(asset_margin):
                modeled_margin += float(asset_margin)
            position_rows.append(
                {
                    "session_date": session_date,
                    "asset_code": asset,
                    "contract_id": position.contract_id,
                    "contracts": position.contracts,
                    "gross_notional": asset_gross,
                    "modeled_initial_margin": asset_margin,
                }
            )
        cash = open_cash + intraday_vm
        adverse_equity = open_cash + adverse_vm
        reference_peak = max(running_equity_peak, open_cash)
        if reference_peak > PORTFOLIO_TOLERANCE:
            maximum_intraday_adverse_drawdown = max(
                maximum_intraday_adverse_drawdown,
                1.0 - adverse_equity / reference_peak,
            )
        running_equity_peak = max(running_equity_peak, cash)
        session_vm = gap_vm + fallback_vm + intraday_vm
        total_vm += session_vm
        total_commission += session_commission
        total_slippage += session_slippage
        maximum_gross = max(maximum_gross, gross)
        maximum_margin = max(maximum_margin, modeled_margin)
        minimum_intraday_equity = min(minimum_intraday_equity, adverse_equity)
        ledger_rows.append(
            {
                "session_date": session_date,
                "starting_cash": start_cash,
                "overnight_gap_vm": gap_vm,
                "fallback_settle_vm": fallback_vm,
                "intraday_vm": intraday_vm,
                "variation_margin": session_vm,
                "commission_cost": session_commission,
                "slippage_cost": session_slippage,
                "ending_cash": cash,
                "gross_notional": gross,
                "modeled_initial_margin": modeled_margin,
                "gross_leverage": gross / max(cash, PORTFOLIO_TOLERANCE),
                "intraday_adverse_equity": adverse_equity,
                "status": status,
                "blocked_asset_count": len(
                    critical_blocked_assets | halt_mark_assets
                ),
                "critical_blocked_asset_count": len(critical_blocked_assets),
                "factual_halt_asset_count": len(session_halt_assets),
                "pending_halt_count": (
                    len(pending_asset_targets)
                    if settings.execution_atomicity == "asset"
                    else len(pending_portfolio_halt_assets)
                ),
            }
        )

    ledger = pd.DataFrame(ledger_rows)
    positions_frame = pd.DataFrame(position_rows)
    orders = pd.DataFrame(order_rows, columns=PORTFOLIO_ORDER_COLUMNS)
    performance = _performance_metrics(
        ledger["ending_cash"],
        ledger["session_date"],
        settings.initial_cash,
    )
    critical_failure_count = counters.total_failures()
    unresolved_halt_count = (
        len(pending_asset_targets)
        if settings.execution_atomicity == "asset"
        else len(pending_portfolio_halt_assets)
    )
    execution_complete = (
        critical_failure_count == 0
        and unresolved_halt_count == 0
        and cash > 0.0
    )
    metrics: dict[str, float | int | bool | str] = {
        "starting_cash": settings.initial_cash,
        "ending_cash": float(cash),
        **performance,
        "variation_margin": float(total_vm),
        "commission_cost": float(total_commission),
        "slippage_cost": float(total_slippage),
        "total_cost": float(total_commission + total_slippage),
        "order_notional": float(total_order_notional),
        "maximum_gross_notional": float(maximum_gross),
        "maximum_modeled_initial_margin": float(maximum_margin),
        "maximum_participation": float(maximum_participation),
        "minimum_intraday_adverse_equity": float(minimum_intraday_equity),
        "intraday_adverse_drawdown": float(
            max(0.0, maximum_intraday_adverse_drawdown)
        ),
        "filled_leg_count": int(orders["filled"].sum()) if not orders.empty else 0,
        "critical_failure_count": int(critical_failure_count),
        "unresolved_halt_count": int(unresolved_halt_count),
        "execution_complete": execution_complete,
        "terminal_carried": any(position.contracts != 0 for position in positions.values()),
        "research_only": True,
        "broker_exact": False,
        "accounting_note": "modeled_vm_requires_historical_specs_and_intraday_margin",
    }
    metrics.update(
        {item.name: int(getattr(counters, item.name)) for item in fields(counters)}
    )
    return FuturesPortfolioLedgerResult(
        ledger=ledger,
        positions=positions_frame,
        orders=orders,
        metrics=metrics,
        execution_complete=execution_complete,
    )


__all__ = [
    "FuturesPortfolioLedgerConfig",
    "FuturesPortfolioLedgerResult",
    "run_futures_portfolio_ledger",
]
