"""Run the presealed V52 monthly OFZ carry and roll-down experiment."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures import moex_stock_futures_cash_carry_source as artifact_io
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v52_ofz_carry_roll_down_v1.yaml"
CONFIG_SHA256: Final[str] = "ee995ff40887db0d3a393cedf3b9c6ed365a76fc8089db34f8317837cc1c241b"
SCENARIOS: Final[tuple[str, ...]] = (
    "primary_10bps",
    "doubled_20bps",
    "stress_40bps",
)
COMBINED_SCENARIOS: Final[tuple[str, ...]] = (
    "primary",
    "doubled",
    "stress",
    "execution_stress",
)
HISTORY_COLUMNS: Final[tuple[str, ...]] = (
    "trade_date",
    "security_id",
    "value_rub",
    "open_clean_pct",
    "close_clean_pct",
    "wap_clean_pct",
    "legal_close_clean_pct",
    "accrued_interest_rub",
    "yield_at_wap_pct",
    "maturity_date",
    "face_value",
    "currency_id",
    "face_unit",
    "available_at_utc",
)
SCHEDULE_COLUMNS: Final[tuple[str, ...]] = (
    "event_kind",
    "security_id",
    "event_date",
    "record_date",
    "value_rub",
    "current_vintage",
)


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    ofz_root: Path
    v49_root: Path


@dataclass(frozen=True, slots=True)
class SimulationResult:
    trades: pd.DataFrame
    positions: pd.DataFrame
    ledger: pd.DataFrame
    completed_rebalances: int
    unresolved_rebalances: int
    unresolved_cashflows: int
    mark_sessions: int
    total_sessions: int


def _sha(path: Path) -> str:
    return artifact_io.sha256_file(path)


def _safe_root(value: str, kind: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe V52 {kind} path")
    expected = "data" if kind == "data" else "runs"
    if relative.parts[0].lower() != expected:
        raise ValueError(f"V52 {kind} path escaped {expected}")
    return PROJECT_ROOT / relative


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V52 config must be an object")
    selection = payload["selection"]
    execution = payload["execution"]
    portfolio = payload["portfolio"]
    gates = payload["gates"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "v52_ofz_carry_roll_down_v1"
        or payload.get("status") != "sealed_before_any_ofz_market_value_return_or_pnl"
        or payload.get("independent_return_engine") is not True
        or payload.get("live_trading_allowed") is not False
        or selection["universe_security_id_prefix"] != "SU262"
        or float(selection["minimum_remaining_maturity_years"]) != 2.0
        or float(selection["maximum_remaining_maturity_years"]) != 7.0
        or int(selection["trailing_liquidity_observations"]) != 20
        or float(selection["minimum_trailing_median_value_rub"]) != 10_000_000.0
        or int(selection["selected_security_count"]) != 3
        or execution["fractional_bond_proxy"] is not True
        or execution["historical_lot_size_proven"] is not False
        or tuple(float(item["one_way_bps"]) for item in payload["cost_scenarios"].values())
        != (10.0, 20.0, 40.0)
        or not math.isclose(float(portfolio["v49_weight"]), 0.85)
        or not math.isclose(float(portfolio["ofz_weight"]), 0.15)
        or not math.isclose(
            float(portfolio["v49_weight"]) + float(portfolio["ofz_weight"]), 1.0
        )
        or gates["live_promotion_forbidden"] is not True
    ):
        raise ValueError("V52 protocol drifted")
    ofz = payload["inputs"]["ofz_source"]
    v49 = payload["inputs"]["frozen_v49"]
    ofz_root = _safe_root(ofz["root"], "data")
    v49_root = _safe_root(v49["root"], "run")
    for declaration in (ofz["manifest"], ofz["audit"], ofz["history"], ofz["bondization"]):
        path = ofz_root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"V52 OFZ input drifted: {path.name}")
        if "rows" in declaration and pq.ParquetFile(path).metadata.num_rows != int(
            declaration["rows"]
        ):
            raise ValueError(f"V52 OFZ row count drifted: {path.name}")
    for declaration in (v49["manifest"], v49["ledger"], v49["metrics"]):
        path = v49_root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"V52 V49 input drifted: {path.name}")
    source_manifest = json.loads(
        (ofz_root / ofz["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    source_audit = json.loads(
        (ofz_root / ofz["audit"]["file"]).read_text(encoding="utf-8-sig")
    )
    v49_manifest = json.loads(
        (v49_root / v49["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    if (
        source_manifest.get("config_sha256") != ofz["protocol_sha256"]
        or source_manifest.get("contains_return_label_target_prediction_or_pnl") is not False
        or source_audit.get("all_true") is not True
        or v49_manifest.get("protocol_sha256") != v49["protocol_sha256"]
    ):
        raise ValueError("V52 parent identity or audit drifted")
    return Protocol(payload, actual, ofz_root, v49_root)


def dirty_price(clean_pct: float, face_value: float, accrued_interest: float) -> float:
    values = (clean_pct, face_value, accrued_interest)
    if (
        not all(math.isfinite(float(value)) for value in values)
        or clean_pct <= 0
        or face_value <= 0
    ):
        return float("nan")
    result = clean_pct * face_value / 100.0 + accrued_interest
    return float(result) if result > 0 else float("nan")


def _first_positive(frame: pd.DataFrame, columns: tuple[str, ...]) -> pd.Series:
    output = pd.Series(np.nan, index=frame.index, dtype=float)
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        output = output.where(output.notna(), values.where(values > 0))
    return output


def prepare_history(history: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    missing = set(HISTORY_COLUMNS) - set(history.columns)
    if missing:
        raise ValueError(f"V52 history schema missing: {sorted(missing)}")
    frame = history.loc[:, HISTORY_COLUMNS].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    frame["maturity_date"] = pd.to_datetime(frame["maturity_date"], errors="coerce").dt.normalize()
    frame["available_at_utc"] = pd.to_datetime(frame["available_at_utc"], utc=True, errors="raise")
    protected = pd.Timestamp(config["dates"]["protected_from"])
    start, end = pd.Timestamp(config["dates"]["start"]), pd.Timestamp(config["dates"]["end"])
    if frame["trade_date"].ge(protected).any():
        raise ValueError("V52 history crossed protected period")
    frame = frame.loc[frame["trade_date"].between(start, end, inclusive="both")].copy()
    if frame.duplicated(["trade_date", "security_id"]).any():
        raise ValueError("V52 history identity is not unique")
    numeric = (
        "value_rub",
        "open_clean_pct",
        "close_clean_pct",
        "wap_clean_pct",
        "legal_close_clean_pct",
        "accrued_interest_rub",
        "yield_at_wap_pct",
        "face_value",
    )
    for column in numeric:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.sort_values(["security_id", "trade_date"], kind="mergesort")
    clean_mark = _first_positive(
        frame, tuple(config["execution"]["close_mark_priority"])
    )
    frame["dirty_open"] = (
        frame["open_clean_pct"] * frame["face_value"] / 100.0
        + frame["accrued_interest_rub"]
    ).where(
        frame["open_clean_pct"].gt(0)
        & frame["face_value"].gt(0)
        & frame["accrued_interest_rub"].ge(0)
    )
    frame["dirty_mark"] = (
        clean_mark * frame["face_value"] / 100.0 + frame["accrued_interest_rub"]
    ).where(
        clean_mark.gt(0) & frame["face_value"].gt(0) & frame["accrued_interest_rub"].ge(0)
    )
    window = int(config["selection"]["trailing_liquidity_observations"])
    frame["trailing_median_value_rub"] = frame.groupby("security_id", sort=False)[
        "value_rub"
    ].transform(lambda values: values.rolling(window, min_periods=window).median())
    return frame.sort_values(["trade_date", "security_id"], kind="mergesort").reset_index(
        drop=True
    )


def build_decisions(history: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    selection = config["selection"]
    month_last = history.groupby(history["trade_date"].dt.to_period("M"), sort=True)[
        "trade_date"
    ].max()
    rows: list[dict[str, Any]] = []
    for decision_date in month_last:
        current = history.loc[history["trade_date"].eq(decision_date)].copy()
        remaining = (current["maturity_date"] - decision_date).dt.days / 365.25
        eligible = current.loc[
            current["security_id"].astype(str).str.startswith(
                str(selection["universe_security_id_prefix"])
            )
            & current["currency_id"].astype(str).eq(str(selection["currency_id"]))
            & current["face_unit"].astype(str).eq(str(selection["face_unit"]))
            & remaining.ge(float(selection["minimum_remaining_maturity_years"]))
            & remaining.le(float(selection["maximum_remaining_maturity_years"]))
            & current["trailing_median_value_rub"].ge(
                float(selection["minimum_trailing_median_value_rub"])
            )
            & current["yield_at_wap_pct"].gt(0)
            & current["dirty_open"].notna()
            & current["dirty_mark"].notna()
        ].copy()
        eligible["remaining_maturity_years"] = remaining.loc[eligible.index]
        eligible = eligible.sort_values(
            ["yield_at_wap_pct", "security_id"], ascending=[False, True], kind="mergesort"
        )
        required = int(selection["selected_security_count"])
        selected = eligible.head(required)
        status = "selected" if len(selected) == required else "sleep_insufficient_candidates"
        if selected.empty:
            rows.append(
                {
                    "decision_date": decision_date,
                    "security_id": pd.NA,
                    "rank": pd.NA,
                    "target_weight": 0.0,
                    "status": status,
                    "eligible_count": len(eligible),
                    "yield_at_wap_pct": np.nan,
                    "remaining_maturity_years": np.nan,
                    "trailing_median_value_rub": np.nan,
                    "available_at_utc": pd.NaT,
                }
            )
            continue
        for rank, (_, item) in enumerate(selected.iterrows(), start=1):
            rows.append(
                {
                    "decision_date": decision_date,
                    "security_id": item["security_id"],
                    "rank": rank,
                    "target_weight": 1.0 / required,
                    "status": status,
                    "eligible_count": len(eligible),
                    "yield_at_wap_pct": item["yield_at_wap_pct"],
                    "remaining_maturity_years": item["remaining_maturity_years"],
                    "trailing_median_value_rub": item["trailing_median_value_rub"],
                    "available_at_utc": item["available_at_utc"],
                }
            )
    return pd.DataFrame(rows)


def solve_post_cost_nav(
    pre_nav: float,
    current_values: dict[str, float],
    targets: tuple[str, ...],
    cost_rate: float,
    iterations: int = 100,
    tolerance: float = 1e-8,
) -> tuple[float, dict[str, float], float]:
    if pre_nav <= 0 or not targets or cost_rate < 0:
        raise ValueError("invalid V52 rebalance state")
    post_nav = pre_nav
    desired: dict[str, float] = {}
    for _ in range(iterations):
        desired = {security: post_nav / len(targets) for security in targets}
        universe = set(current_values) | set(desired)
        turnover = sum(
            abs(desired.get(security, 0.0) - current_values.get(security, 0.0))
            for security in universe
        )
        updated = pre_nav - cost_rate * turnover
        if abs(updated - post_nav) <= tolerance:
            post_nav = updated
            break
        post_nav = updated
    else:
        raise ValueError("V52 rebalance cost fixed point did not converge")
    desired = {security: post_nav / len(targets) for security in targets}
    turnover = sum(
        abs(desired.get(security, 0.0) - current_values.get(security, 0.0))
        for security in set(current_values) | set(desired)
    )
    cost = cost_rate * turnover
    if not math.isclose(post_nav, pre_nav - cost, abs_tol=max(tolerance * 10, 1e-6)):
        raise ValueError("V52 rebalance accounting identity failed")
    return post_nav, desired, cost


def _lookup(history: pd.DataFrame) -> dict[tuple[pd.Timestamp, str], dict[str, Any]]:
    return {
        (pd.Timestamp(item.trade_date), str(item.security_id)): item._asdict()
        for item in history.itertuples(index=False)
    }


def _schedule(schedule: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    missing = set(SCHEDULE_COLUMNS) - set(schedule.columns)
    if missing:
        raise ValueError(f"V52 schedule schema missing: {sorted(missing)}")
    output = schedule.loc[:, SCHEDULE_COLUMNS].copy()
    output["event_date"] = pd.to_datetime(output["event_date"], errors="coerce").dt.normalize()
    output["record_date"] = pd.to_datetime(output["record_date"], errors="coerce").dt.normalize()
    output["value_rub"] = pd.to_numeric(output["value_rub"], errors="coerce")
    output = output.loc[
        output["security_id"].astype(str).str.startswith(
            str(config["selection"]["universe_security_id_prefix"])
        )
        & output["event_kind"].isin(["coupon", "amortization"])
    ].copy()
    if not output["current_vintage"].eq(True).all():  # noqa: E712
        raise ValueError("V52 schedule current-vintage identity drifted")
    return output.sort_values(["event_date", "security_id", "event_kind"], kind="mergesort")


def simulate(
    history: pd.DataFrame,
    schedule: pd.DataFrame,
    decisions: pd.DataFrame,
    config: dict[str, Any],
    scenario: str,
) -> SimulationResult:
    if scenario not in SCENARIOS:
        raise ValueError("unknown V52 scenario")
    dates = tuple(pd.Timestamp(value) for value in sorted(history["trade_date"].unique()))
    by_key = _lookup(history)
    decision_groups = {
        pd.Timestamp(date): group.loc[group["status"].eq("selected")].copy()
        for date, group in decisions.groupby("decision_date", sort=True)
    }
    events = _schedule(schedule, config)
    event_dates = pd.Series(dates)
    events["credit_date"] = events["event_date"].map(
        lambda value: (
            event_dates.loc[event_dates.ge(value)].iloc[0]
            if pd.notna(value) and event_dates.ge(value).any()
            else pd.NaT
        )
    )
    cost_rate = float(config["cost_scenarios"][scenario]["one_way_bps"]) / 10_000.0
    max_delay = int(config["execution"]["maximum_execution_delay_calendar_days"])
    cash = float(config["execution"]["initial_cash_rub"])
    quantities: dict[str, float] = {}
    holdings_at_close: dict[pd.Timestamp, dict[str, float]] = {}
    credited_events: set[int] = set()
    pending: tuple[pd.Timestamp, tuple[str, ...]] | None = None
    trades: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    completed = unresolved_rebalances = unresolved_cashflows = mark_sessions = 0

    for date in dates:
        if pending is not None:
            decision_date, targets = pending
            if (date - decision_date).days > max_delay:
                unresolved_rebalances += 1
                pending = None
            elif date > decision_date:
                execution_universe = tuple(sorted(set(quantities) | set(targets)))
                rows = {security: by_key.get((date, security)) for security in execution_universe}
                executable = all(
                    row is not None
                    and math.isfinite(float(row["dirty_open"]))
                    and float(row["dirty_open"]) > 0
                    for row in rows.values()
                )
                selected_rows = decision_groups[decision_date]
                causal = pd.to_datetime(selected_rows["available_at_utc"], utc=True).dt.date.le(
                    date.date()
                ).all()
                if executable and causal:
                    current_values = {
                        security: quantities[security] * float(rows[security]["dirty_open"])
                        for security in quantities
                    }
                    pre_nav = cash + sum(current_values.values())
                    post_nav, desired, total_cost = solve_post_cost_nav(
                        pre_nav,
                        current_values,
                        targets,
                        cost_rate,
                        int(config["execution"]["maximum_fixed_point_iterations"]),
                        float(config["execution"]["fixed_point_tolerance_rub"]),
                    )
                    for security in sorted(set(current_values) | set(desired)):
                        delta = desired.get(security, 0.0) - current_values.get(security, 0.0)
                        if abs(delta) <= 1e-10:
                            continue
                        trades.append(
                            {
                                "scenario": scenario,
                                "decision_date": decision_date,
                                "execution_date": date,
                                "security_id": security,
                                "side": "buy" if delta > 0 else "sell",
                                "dirty_open": float(rows[security]["dirty_open"]),
                                "notional_rub": abs(delta),
                                "cost_rub": abs(delta) * cost_rate,
                            }
                        )
                    quantities = {
                        security: desired[security] / float(rows[security]["dirty_open"])
                        for security in targets
                    }
                    cash = post_nav - sum(desired.values())
                    day_trade_cost = sum(
                        item["cost_rub"]
                        for item in trades
                        if item["execution_date"] == date
                    )
                    if abs(day_trade_cost - total_cost) > 1e-5:
                        raise ValueError("V52 trade cost allocation drifted")
                    completed += 1
                    pending = None

        day_events = events.loc[events["credit_date"].eq(date)]
        cashflow_credit = 0.0
        for index, event in day_events.iterrows():
            if index in credited_events:
                continue
            credited_events.add(index)
            if pd.isna(event["record_date"]) or pd.isna(event["value_rub"]):
                unresolved_cashflows += 1
                continue
            eligible_dates = [item for item in holdings_at_close if item <= event["record_date"]]
            entitlement = (
                holdings_at_close[max(eligible_dates)].get(str(event["security_id"]), 0.0)
                if eligible_dates
                else 0.0
            )
            if entitlement > 0:
                credit = entitlement * float(event["value_rub"])
                if not math.isfinite(credit) or credit < 0:
                    unresolved_cashflows += 1
                    continue
                cash += credit
                cashflow_credit += credit

        marks: dict[str, float] = {}
        missing_mark = False
        for security, quantity in quantities.items():
            row = by_key.get((date, security))
            if row is None or not math.isfinite(float(row["dirty_mark"])):
                missing_mark = True
                break
            marks[security] = float(row["dirty_mark"])
            positions.append(
                {
                    "scenario": scenario,
                    "date": date,
                    "security_id": security,
                    "quantity": quantity,
                    "dirty_mark": marks[security],
                    "market_value_rub": quantity * marks[security],
                }
            )
        holdings_at_close[date] = dict(quantities)
        if not missing_mark:
            nav = cash + sum(quantities[security] * marks[security] for security in quantities)
            if not math.isfinite(nav) or nav <= 0:
                raise ValueError("V52 non-positive NAV")
            mark_sessions += 1
            ledger.append(
                {
                    "date": date,
                    "scenario": scenario,
                    "nav": nav,
                    "cash_rub": cash,
                    "cashflow_credit_rub": cashflow_credit,
                    "held_security_count": len(quantities),
                    "mark_complete": True,
                }
            )

        group = decision_groups.get(date)
        if group is not None and not group.empty:
            targets = tuple(group.sort_values("rank")["security_id"].astype(str))
            if len(targets) == int(config["selection"]["selected_security_count"]):
                pending = (date, targets)

    if pending is not None:
        unresolved_rebalances += 1
    return SimulationResult(
        pd.DataFrame(trades),
        pd.DataFrame(positions),
        pd.DataFrame(ledger),
        completed,
        unresolved_rebalances,
        unresolved_cashflows,
        mark_sessions,
        len(dates),
    )


def metrics(nav: pd.Series, dates: pd.Series) -> dict[str, Any]:
    frame = pd.DataFrame({"date": pd.to_datetime(dates), "nav": pd.to_numeric(nav)}).dropna()
    frame = frame.sort_values("date", kind="mergesort").drop_duplicates("date", keep="last")
    if len(frame) < 2 or (frame["nav"] <= 0).any():
        raise ValueError("V52 metrics require positive time series")
    returns = frame["nav"].pct_change().dropna()
    years = (frame["date"].iloc[-1] - frame["date"].iloc[0]).days / 365.25
    cagr = (frame["nav"].iloc[-1] / frame["nav"].iloc[0]) ** (1.0 / years) - 1.0
    volatility = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / volatility * math.sqrt(252.0)) if volatility > 0 else 0.0
    drawdown = frame["nav"] / frame["nav"].cummax() - 1.0
    annual = (
        pd.DataFrame({"date": frame["date"].iloc[1:], "return": returns.to_numpy()})
        .assign(year=lambda item: item["date"].dt.year)
        .groupby("year")["return"]
        .apply(lambda values: float((1.0 + values).prod() - 1.0))
    )
    return {
        "rows": len(frame),
        "start": str(frame["date"].iloc[0].date()),
        "end": str(frame["date"].iloc[-1].date()),
        "total_return": float(frame["nav"].iloc[-1] / frame["nav"].iloc[0] - 1.0),
        "cagr": float(cagr),
        "sharpe": sharpe,
        "maximum_drawdown": float(-drawdown.min()),
        "worst_year": float(annual.min()),
        "positive_years": int(annual.gt(0).sum()),
        "annual_returns": {str(year): value for year, value in annual.items()},
    }


def combine_with_v49(
    ofz_ledgers: dict[str, pd.DataFrame], v49: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    mapping = config["portfolio"]["scenario_mapping"]
    v49_weight = float(config["portfolio"]["v49_weight"])
    ofz_weight = float(config["portfolio"]["ofz_weight"])
    base = v49.rename(columns={"session_date": "date"}).copy()
    base["date"] = pd.to_datetime(base["date"]).dt.normalize()
    outputs: list[pd.DataFrame] = []
    for scenario in COMBINED_SCENARIOS:
        declared = mapping[scenario]
        ofz = ofz_ledgers[str(declared["ofz"])].loc[:, ["date", "nav"]].copy()
        merged = base.loc[:, ["date", str(declared["v49"])]].merge(
            ofz, on="date", how="inner", validate="one_to_one"
        )
        if merged.empty:
            raise ValueError("V52 combined portfolio has no exact common sessions")
        merged["scenario"] = scenario
        merged["v49_normalized_nav"] = merged[str(declared["v49"])] / merged[
            str(declared["v49"])
        ].iloc[0]
        merged["ofz_normalized_nav"] = merged["nav"] / merged["nav"].iloc[0]
        merged["combined_normalized_nav"] = (
            v49_weight * merged["v49_normalized_nav"]
            + ofz_weight * merged["ofz_normalized_nav"]
        )
        outputs.append(
            merged.loc[
                :,
                [
                    "date",
                    "scenario",
                    "v49_normalized_nav",
                    "ofz_normalized_nav",
                    "combined_normalized_nav",
                ],
            ]
        )
    return pd.concat(outputs, ignore_index=True)


def evaluate_gates(
    results: dict[str, SimulationResult],
    ofz_metrics: dict[str, dict[str, Any]],
    combined_metrics: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, bool]:
    gates = config["gates"]
    return {
        "zero_protected_rows": True,
        "zero_lookahead_decisions": True,
        "zero_unresolved_cashflows": all(
            item.unresolved_cashflows == 0 for item in results.values()
        ),
        "minimum_completed_rebalances": min(item.completed_rebalances for item in results.values())
        >= int(gates["minimum_completed_rebalances"]),
        "maximum_unresolved_rebalances": max(
            item.unresolved_rebalances for item in results.values()
        )
        <= int(gates["maximum_unresolved_rebalances"]),
        "minimum_mark_coverage_fraction": min(
            item.mark_sessions / item.total_sessions for item in results.values()
        )
        >= float(gates["minimum_mark_coverage_fraction"]),
        "all_ofz_nav_positive": all(
            float(item["minimum_nav"]) > 0 for item in ofz_metrics.values()
        ),
        "all_ofz_scenario_cagr": all(
            float(item["cagr"]) >= float(gates["all_ofz_scenario_cagr_gte"])
            for item in ofz_metrics.values()
        ),
        "all_ofz_scenario_sharpe": all(
            float(item["sharpe"]) >= float(gates["all_ofz_scenario_sharpe_gte"])
            for item in ofz_metrics.values()
        ),
        "all_ofz_scenario_mdd": all(
            float(item["maximum_drawdown"]) <= float(gates["all_ofz_scenario_mdd_lte"])
            for item in ofz_metrics.values()
        ),
        "all_ofz_scenario_worst_year": all(
            float(item["worst_year"]) >= float(gates["all_ofz_scenario_worst_year_gte"])
            for item in ofz_metrics.values()
        ),
        "primary_ofz_positive_years": int(ofz_metrics["primary_10bps"]["positive_years"])
        >= int(gates["primary_ofz_positive_years_gte"]),
        "all_combined_scenario_cagr": all(
            float(item["cagr"]) >= float(gates["all_combined_scenario_cagr_gte"])
            for item in combined_metrics.values()
        ),
        "all_combined_scenario_mdd": all(
            float(item["maximum_drawdown"]) <= float(gates["all_combined_scenario_mdd_lte"])
            for item in combined_metrics.values()
        ),
        "primary_combined_cagr": float(combined_metrics["primary"]["cagr"])
        >= float(gates["primary_combined_cagr_gte"]),
        "aspirational_primary_combined_cagr_50": float(combined_metrics["primary"]["cagr"])
        >= float(gates["aspirational_primary_combined_cagr_gte"]),
    }


def build(
    protocol: Protocol,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    inputs = protocol.payload["inputs"]
    history = prepare_history(
        pd.read_parquet(protocol.ofz_root / inputs["ofz_source"]["history"]["file"]),
        protocol.payload,
    )
    schedule = pd.read_parquet(
        protocol.ofz_root / inputs["ofz_source"]["bondization"]["file"]
    )
    decisions = build_decisions(history, protocol.payload)
    results = {
        scenario: simulate(history, schedule, decisions, protocol.payload, scenario)
        for scenario in SCENARIOS
    }
    trades = pd.concat(
        [item.trades for item in results.values() if not item.trades.empty], ignore_index=True
    )
    positions = pd.concat(
        [item.positions for item in results.values() if not item.positions.empty], ignore_index=True
    )
    ledgers = {scenario: item.ledger for scenario, item in results.items()}
    combined = combine_with_v49(
        ledgers,
        pd.read_parquet(protocol.v49_root / inputs["frozen_v49"]["ledger"]["file"]),
        protocol.payload,
    )
    daily = pd.concat(
        [
            pd.concat(
                [
                    item.ledger.assign(ledger_kind="ofz"),
                    pd.DataFrame(),
                ],
                ignore_index=True,
            )
            for item in results.values()
        ],
        ignore_index=True,
    )
    combined_daily = combined.rename(columns={"combined_normalized_nav": "nav"}).assign(
        ledger_kind="combined",
        cash_rub=np.nan,
        cashflow_credit_rub=np.nan,
        held_security_count=np.nan,
        mark_complete=True,
    )
    daily = pd.concat([daily, combined_daily], ignore_index=True, sort=False)
    ofz_metrics: dict[str, dict[str, Any]] = {}
    for scenario, item in results.items():
        value = metrics(item.ledger["nav"], item.ledger["date"])
        value.update(
            {
                "minimum_nav": float(item.ledger["nav"].min()),
                "completed_rebalances": item.completed_rebalances,
                "unresolved_rebalances": item.unresolved_rebalances,
                "unresolved_cashflows": item.unresolved_cashflows,
                "mark_coverage_fraction": item.mark_sessions / item.total_sessions,
                "total_cost_rub": (
                    float(item.trades["cost_rub"].sum()) if not item.trades.empty else 0.0
                ),
            }
        )
        ofz_metrics[scenario] = value
    combined_metrics = {
        scenario: metrics(group["combined_normalized_nav"], group["date"])
        for scenario, group in combined.groupby("scenario", sort=False)
    }
    gates = evaluate_gates(results, ofz_metrics, combined_metrics, protocol.payload)
    required = {key: value for key, value in gates.items() if not key.startswith("aspirational_")}
    summary = {
        "protocol_id": protocol.payload["protocol_id"],
        "protocol_sha256": protocol.config_sha256,
        "ofz": ofz_metrics,
        "combined_85_v49_15_ofz": combined_metrics,
        "counts": {
            "decisions": int(decisions["decision_date"].nunique()),
            "selected_decision_rows": int(decisions["status"].eq("selected").sum()),
            "trades": len(trades),
            "positions": len(positions),
        },
        "gates": gates,
        "verdict": "GO_TO_FORWARD_EXECUTION_VALIDATION" if all(required.values()) else "NO_GO",
        "live_trading_allowed": False,
    }
    return decisions, trades, positions, daily, summary


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as stream:
        path = Path(stream.name)
    try:
        frame.to_parquet(path, index=False)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    output: dict[str, Any] = {"file": path.name, "bytes": path.stat().st_size, "sha256": _sha(path)}
    if rows is not None:
        output["rows"] = rows
    return output


def run(protocol: Protocol) -> Path:
    decisions, trades, positions, daily, summary = build(protocol)
    created = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_base = _safe_root(protocol.payload["outputs"]["root"], "run")
    run_id = f"{output_base.name}_{created}_{protocol.config_sha256[:8]}"
    output = output_base.parent / run_id
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    frames = {
        "decisions": decisions,
        "trades": trades,
        "positions": positions,
        "daily_ledger": daily,
    }
    for name, frame in frames.items():
        atomic_write_bytes(output / f"{name}.parquet", _parquet_bytes(frame))
    write_json(output / "metrics.json", summary)
    report = (
        "# V52 OFZ carry/roll-down\n\n"
        f"Verdict: `{summary['verdict']}`. Live trading: `false`.\n\n"
        "This is a fractional, daily-mark proxy on official current-vintage MOEX data; "
        "it is not broker-executable evidence.\n"
    )
    atomic_write_text(output / "report.md", report)
    manifest = {
        "run_id": run_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": protocol.config_sha256,
        "implementation_sha256": _sha(Path(__file__)),
        "verdict": summary["verdict"],
        "live_trading_allowed": False,
        "artifacts": {
            **{
                name: _artifact(output / f"{name}.parquet", len(frame))
                for name, frame in frames.items()
            },
            "metrics": _artifact(output / "metrics.json"),
            "report": _artifact(output / "report.md"),
        },
    }
    write_json(output / "manifest.json", manifest)
    atomic_write_text(
        output / "manifest.sha256",
        f"{_sha(output / 'manifest.json')}  manifest.json\n",
    )
    audit = audit_run(protocol, output, rebuild=True)
    write_json(output / "audit.json", audit)
    return output


def audit_run(protocol: Protocol, output: Path, *, rebuild: bool = False) -> dict[str, Any]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    checks: dict[str, bool] = {
        "protocol_exact": manifest.get("protocol_sha256") == protocol.config_sha256,
        "implementation_exact": manifest.get("implementation_sha256") == _sha(Path(__file__)),
        "live_false": manifest.get("live_trading_allowed") is False,
        "manifest_sidecar_exact": (output / "manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        == _sha(output / "manifest.json"),
    }
    for name, declaration in manifest.get("artifacts", {}).items():
        path = output / declaration["file"]
        checks[f"{name}_exact"] = path.exists() and _sha(path) == declaration["sha256"]
        if "rows" in declaration and path.exists():
            checks[f"{name}_rows_exact"] = (
                pq.ParquetFile(path).metadata.num_rows == int(declaration["rows"])
            )
    if rebuild:
        rebuilt = build(protocol)
        for name, expected in zip(
            ("decisions", "trades", "positions", "daily_ledger"), rebuilt[:4], strict=True
        ):
            actual = pd.read_parquet(output / f"{name}.parquet")
            try:
                pd.testing.assert_frame_equal(actual, expected, check_dtype=False)
                checks[f"{name}_replay_exact"] = True
            except AssertionError:
                checks[f"{name}_replay_exact"] = False
        stored_metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
        checks["metrics_replay_exact"] = stored_metrics == rebuilt[4]
    return {"checks": checks, "all_true": all(checks.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path)
    arguments = parser.parse_args()
    protocol = load_protocol()
    if arguments.audit is not None:
        audit = audit_run(protocol, arguments.audit, rebuild=True)
        print(json.dumps(audit, indent=2, sort_keys=True))
        if not audit["all_true"]:
            raise SystemExit(1)
        return
    output = run(protocol)
    summary = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    print(f"run={output.name}")
    print(f"verdict={summary['verdict']}")
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8-sig"))
    print(f"audit_all_true={audit['all_true']}")


if __name__ == "__main__":
    main()


__all__ = [
    "CONFIG_PATH",
    "CONFIG_SHA256",
    "Protocol",
    "SimulationResult",
    "build_decisions",
    "dirty_price",
    "load_protocol",
    "metrics",
    "prepare_history",
    "simulate",
    "solve_post_cost_nav",
]
