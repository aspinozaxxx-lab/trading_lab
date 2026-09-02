"""Run the sealed V56 outright RVI outlier short corridor candidate."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v52_ofz_carry_roll_down as metrics_engine
from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, atomic_write_text, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v56_rvi_outlier_short_corridor.yaml"
CONFIG_SHA256: Final[str] = "bc1c3f2b9ef21f100d072072650989aa0186b0733f18ff0f7dac68dec94c0b73"
SCENARIOS: Final[tuple[str, ...]] = ("primary", "doubled", "stress")

TRADE_COLUMNS: Final[tuple[str, ...]] = (
    "signal_date",
    "entry_date",
    "trigger_date",
    "exit_date",
    "secid",
    "expiration_date",
    "signal_close",
    "entry_open",
    "trigger_close",
    "exit_open",
    "contracts",
    "point_value_proxy",
    "signal_volume_cap",
    "risk_cap",
    "gross_cap",
    "stop_risk_rub",
    "gross_notional_rub",
    "entry_volume",
    "exit_volume",
    "exit_reason",
    "holding_exchange_sessions",
    "gross_pnl_rub",
)


def _sha(path: Path) -> str:
    return storage.sha256_file(path)


def _root(value: str, expected: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError("unsafe V56 path")
    if relative.parts[0].lower() != expected:
        raise ValueError("V56 path escaped declared root")
    return PROJECT_ROOT / relative


def _read_sealed_config() -> dict[str, Any]:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V56 config must be an object")
    signal = payload["signal"]
    execution = payload["execution"]
    gates = payload["promotion_gates"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "futures_v56_rvi_outlier_short_corridor_v1"
        or payload.get("status")
        != "sealed_after_source_audit_before_any_v56_market_value_signal_trade_or_pnl"
        or payload.get("live_trading_allowed") is not False
        or payload["independence"].get("one_candidate_only") is not True
        or float(signal["entry_close_gte"]) != 30.0
        or float(signal["entry_close_lt"]) != 45.0
        or float(signal["take_profit_close_lte"]) != 24.0
        or float(signal["distant_stop_close_gte"]) != 45.0
        or int(signal["maximum_holding_exchange_sessions"]) != 20
        or int(signal["force_exit_days_to_expiry_lte"]) != 5
        or float(execution["stop_risk_budget_nav"]) != 0.01
        or float(execution["gross_notional_cap_nav"]) != 1.0
        or float(gates["primary_cagr_gte"]) != 0.20
        or gates.get("live_promotion_forbidden") is not True
    ):
        raise ValueError("V56 protocol drifted")
    payload["_config_sha256"] = actual
    return payload


def load_protocol() -> dict[str, Any]:
    payload = _read_sealed_config()
    source = payload["source"]
    root = _root(source["root"], "data")
    for name in ("manifest", "series", "daily", "raw", "audit"):
        item = source[name]
        path = root / item["file"]
        if _sha(path) != item["sha256"]:
            raise ValueError(f"V56 source drifted: {name}")
        if (
            "rows" in item
            and path.suffix == ".parquet"
            and pq.ParquetFile(path).metadata.num_rows != int(item["rows"])
        ):
            raise ValueError(f"V56 source rows drifted: {name}")
    manifest = json.loads((root / source["manifest"]["file"]).read_text(encoding="utf-8-sig"))
    audit = json.loads((root / source["audit"]["file"]).read_text(encoding="utf-8-sig"))
    if (
        manifest.get("protocol_sha256") != source["protocol_sha256"]
        or manifest.get("implementation_sha256") != source["implementation_sha256"]
        or manifest.get("source_only") is not True
        or manifest.get("contains_curve_return_label_signal_trade_or_pnl") is not False
        or audit.get("all_true") is not True
    ):
        raise ValueError("V56 source identity or source-only audit drifted")
    payload["_source_root"] = root
    return payload


def _point_value(frame: pd.DataFrame) -> pd.Series:
    denominator = frame["volume"] * frame["waprice"]
    result = frame["value"] / denominator.where(denominator.gt(0.0))
    return result.where(np.isfinite(result) & result.gt(0.0))


def _prepare_daily(daily: pd.DataFrame) -> pd.DataFrame:
    history = daily.copy()
    history["trade_date"] = pd.to_datetime(history["trade_date"]).dt.normalize()
    history["expiration_date"] = pd.to_datetime(history["expiration_date"]).dt.normalize()
    for column in (
        "open",
        "close",
        "high",
        "low",
        "volume",
        "num_trades",
        "value",
        "waprice",
    ):
        history[column] = pd.to_numeric(history[column], errors="coerce")
    history["point_value"] = _point_value(history)
    return history.sort_values(["trade_date", "secid"], kind="mergesort").reset_index(drop=True)


def build_front_state(
    series: pd.DataFrame, daily: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    contracts = series.copy()
    contracts["start_date"] = pd.to_datetime(contracts["start_date"]).dt.normalize()
    contracts["expiration_date"] = pd.to_datetime(contracts["expiration_date"]).dt.normalize()
    history = _prepare_daily(daily)
    protected = pd.Timestamp(config["dates"]["protected_from"])
    if history["trade_date"].ge(protected).any():
        raise ValueError("V56 protected history leaked")
    if history.duplicated(["trade_date", "secid"]).any():
        raise ValueError("V56 duplicate daily contract rows")
    lookup = history.set_index(["trade_date", "secid"], verify_integrity=True)
    selection = config["contract_selection"]
    minimum_volume = float(config["execution"]["minimum_signal_session_volume"])
    rows: list[dict[str, Any]] = []
    for raw_date in sorted(history["trade_date"].unique()):
        date = pd.Timestamp(raw_date)
        available = contracts.loc[
            contracts["start_date"].le(date) & contracts["expiration_date"].gt(date)
        ].sort_values(["expiration_date", "secid"], kind="mergesort")
        if available.empty:
            continue
        front = available.iloc[0]
        secid = str(front["secid"])
        expiration = pd.Timestamp(front["expiration_date"])
        dte = int((expiration - date).days)
        structural = bool(
            int(selection["front_days_to_expiry_min"])
            <= dte
            <= int(selection["front_days_to_expiry_max"])
        )
        key = (date, secid)
        market = lookup.loc[key] if key in lookup.index else None
        complete = bool(
            structural
            and market is not None
            and pd.notna(market["close"])
            and float(market["close"]) > 0.0
            and pd.notna(market["volume"])
            and float(market["volume"]) >= minimum_volume
            and pd.notna(market["num_trades"])
            and float(market["num_trades"]) > 0.0
            and pd.notna(market["point_value"])
            and float(market["point_value"]) > 0.0
        )
        row: dict[str, Any] = {
            "date": date,
            "front_secid": secid,
            "expiration_date": expiration,
            "front_dte": dte,
            "structural": structural,
            "complete": complete,
        }
        for column in (
            "open",
            "close",
            "high",
            "low",
            "volume",
            "num_trades",
            "point_value",
        ):
            row[column] = (
                float(market[column]) if market is not None and pd.notna(market[column]) else np.nan
            )
        rows.append(row)
    return pd.DataFrame(rows).sort_values("date", ignore_index=True)


def _daily_lookup(history: pd.DataFrame) -> dict[tuple[pd.Timestamp, str], dict[str, Any]]:
    return {
        (pd.Timestamp(row.trade_date), str(row.secid)): row._asdict()
        for row in history.itertuples(index=False)
    }


def _valid_open_activity(row: dict[str, Any] | None) -> bool:
    return bool(
        row is not None
        and pd.notna(row["open"])
        and float(row["open"]) > 0.0
        and pd.notna(row["volume"])
        and float(row["volume"]) > 0.0
        and pd.notna(row["num_trades"])
        and float(row["num_trades"]) > 0.0
    )


def _valid_close(row: dict[str, Any] | None) -> bool:
    return bool(row is not None and pd.notna(row["close"]) and float(row["close"]) > 0.0)


def build_trades(
    config: dict[str, Any], state: pd.DataFrame, daily: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    history = _prepare_daily(daily)
    lookup = _daily_lookup(history)
    dates = pd.DatetimeIndex(sorted(history["trade_date"].unique()))
    date_position = {date: index for index, date in enumerate(dates)}
    signal = config["signal"]
    execution = config["execution"]
    evaluation_start = pd.Timestamp(config["dates"]["evaluation_start"])
    evaluation_end = pd.Timestamp(config["dates"]["evaluation_end"])
    eligible = state.loc[
        state["complete"]
        & state["date"].ge(evaluation_start)
        & state["date"].le(evaluation_end)
        & state["close"].ge(float(signal["entry_close_gte"]))
        & state["close"].lt(float(signal["entry_close_lt"]))
    ].sort_values("date", kind="mergesort")
    counts: dict[str, Any] = {
        "signal_sessions": int(len(eligible)),
        "candidate_signals": 0,
        "overlap_suppressed": 0,
        "entry_rejections": 0,
        "unresolved_entries": 0,
        "unresolved_exits": 0,
        "unresolved_marks": 0,
    }
    rejection_reasons: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    next_free = evaluation_start
    initial_nav = float(execution["initial_nav_rub"])
    stop_level = float(signal["distant_stop_close_gte"])
    for candidate in eligible.itertuples(index=False):
        signal_date = pd.Timestamp(candidate.date)
        if signal_date < next_free:
            counts["overlap_suppressed"] += 1
            continue
        counts["candidate_signals"] += 1
        signal_index = date_position.get(signal_date)
        if signal_index is None or signal_index + 1 >= len(dates):
            counts["unresolved_entries"] += 1
            break
        entry_date = dates[signal_index + 1]
        if entry_date > evaluation_end:
            counts["unresolved_entries"] += 1
            break
        secid = str(candidate.front_secid)
        entry = lookup.get((entry_date, secid))
        if not _valid_open_activity(entry):
            counts["unresolved_entries"] += 1
            rejection_reasons["missing_entry_open_or_activity"] += 1
            continue
        entry_open = float(entry["open"])
        if entry_open >= stop_level:
            counts["entry_rejections"] += 1
            rejection_reasons["entry_open_at_or_beyond_stop"] += 1
            continue
        point_value = float(candidate.point_value)
        entry_point_value = float(entry["point_value"])
        relative_drift = abs(entry_point_value - point_value) / point_value
        if (
            not math.isfinite(entry_point_value)
            or entry_point_value <= 0.0
            or relative_drift > float(execution["maximum_entry_point_value_relative_drift"])
        ):
            counts["entry_rejections"] += 1
            rejection_reasons["point_value_drift"] += 1
            continue
        signal_volume_cap = math.floor(
            float(execution["maximum_contracts_fraction_of_signal_session_volume"])
            * float(candidate.volume)
        )
        gross_cap = math.floor(
            float(execution["gross_notional_cap_nav"]) * initial_nav / (point_value * entry_open)
        )
        stop_per_contract = point_value * (stop_level - entry_open)
        risk_cap = math.floor(
            float(execution["stop_risk_budget_nav"]) * initial_nav / stop_per_contract
        )
        contracts = int(max(0, min(signal_volume_cap, gross_cap, risk_cap)))
        if contracts < 1:
            counts["entry_rejections"] += 1
            rejection_reasons["zero_causal_quantity"] += 1
            continue
        if contracts > (
            float(execution["maximum_contracts_fraction_of_entry_session_volume"])
            * float(entry["volume"])
        ):
            counts["entry_rejections"] += 1
            rejection_reasons["entry_capacity"] += 1
            continue
        entry_index = date_position[entry_date]
        maximum_holding = int(signal["maximum_holding_exchange_sessions"])
        last_trigger_index = min(entry_index + maximum_holding - 1, len(dates) - 1)
        trigger_index: int | None = None
        trigger_reason: str | None = None
        trigger_close = np.nan
        missing_marks = 0
        expiration = pd.Timestamp(candidate.expiration_date)
        for scan_index in range(entry_index, last_trigger_index + 1):
            current_date = dates[scan_index]
            current = lookup.get((current_date, secid))
            if not _valid_close(current):
                missing_marks += 1
                continue
            close = float(current["close"])
            dte = int((expiration - current_date).days)
            if close >= stop_level:
                trigger_index, trigger_reason = scan_index, "distant_stop"
            elif close <= float(signal["take_profit_close_lte"]):
                trigger_index, trigger_reason = scan_index, "take_profit"
            elif dte <= int(signal["force_exit_days_to_expiry_lte"]):
                trigger_index, trigger_reason = scan_index, "expiry_buffer"
            elif scan_index == last_trigger_index:
                trigger_index, trigger_reason = scan_index, "maximum_holding"
            if trigger_index is not None:
                trigger_close = close
                break
        if trigger_index is None or trigger_reason is None:
            counts["unresolved_exits"] += 1
            counts["unresolved_marks"] += missing_marks
            break
        exit_row: dict[str, Any] | None = None
        exit_date: pd.Timestamp | None = None
        retries = int(execution["maximum_exit_retry_sessions"])
        for exit_index in range(
            trigger_index + 1,
            min(trigger_index + retries + 2, len(dates)),
        ):
            possible_date = dates[exit_index]
            if possible_date > evaluation_end:
                break
            possible = lookup.get((possible_date, secid))
            if not _valid_open_activity(possible):
                continue
            capacity = float(execution["maximum_contracts_fraction_of_exit_session_volume"])
            if contracts <= capacity * float(possible["volume"]):
                exit_row, exit_date = possible, possible_date
                break
        if exit_row is None or exit_date is None:
            counts["unresolved_exits"] += 1
            counts["unresolved_marks"] += missing_marks
            break
        exit_index = date_position[exit_date]
        for mark_index in range(entry_index, exit_index):
            mark = lookup.get((dates[mark_index], secid))
            if not _valid_close(mark):
                missing_marks += 1
        if missing_marks > 0:
            counts["unresolved_marks"] += missing_marks
            next_free = exit_date + pd.Timedelta(days=1)
            continue
        exit_open = float(exit_row["open"])
        gross_pnl = (entry_open - exit_open) * point_value * contracts
        rows.append(
            {
                "signal_date": signal_date,
                "entry_date": entry_date,
                "trigger_date": dates[trigger_index],
                "exit_date": exit_date,
                "secid": secid,
                "expiration_date": expiration,
                "signal_close": float(candidate.close),
                "entry_open": entry_open,
                "trigger_close": trigger_close,
                "exit_open": exit_open,
                "contracts": contracts,
                "point_value_proxy": point_value,
                "signal_volume_cap": signal_volume_cap,
                "risk_cap": risk_cap,
                "gross_cap": gross_cap,
                "stop_risk_rub": stop_per_contract * contracts,
                "gross_notional_rub": point_value * entry_open * contracts,
                "entry_volume": float(entry["volume"]),
                "exit_volume": float(exit_row["volume"]),
                "exit_reason": trigger_reason,
                "holding_exchange_sessions": exit_index - entry_index,
                "gross_pnl_rub": gross_pnl,
            }
        )
        next_free = exit_date + pd.Timedelta(days=1)
    counts["rejection_reasons"] = dict(sorted(rejection_reasons.items()))
    return pd.DataFrame(rows, columns=TRADE_COLUMNS), counts


def _scenario_trade_statistics(
    trades: pd.DataFrame, cost_points: float, initial_nav: float
) -> dict[str, Any]:
    net_values: list[float] = []
    gross_values: list[float] = []
    costs: list[float] = []
    for trade in trades.itertuples(index=False):
        gross = float(trade.gross_pnl_rub)
        cost = 2.0 * cost_points * trade.point_value_proxy * trade.contracts
        gross_values.append(gross)
        costs.append(cost)
        net_values.append(gross - cost)
    positive = [value for value in net_values if value > 0.0]
    negative = [value for value in net_values if value < 0.0]
    if negative:
        profit_factor: float | None = float(sum(positive) / abs(sum(negative)))
    elif positive:
        profit_factor = None
    else:
        profit_factor = 0.0
    tail_count = max(1, math.ceil(0.10 * len(net_values))) if net_values else 0
    tail_mean = float(np.mean(sorted(net_values)[:tail_count])) if tail_count else 0.0
    return {
        "completed_trades": len(net_values),
        "winning_trades": len(positive),
        "losing_trades": len(negative),
        "win_rate": len(positive) / len(net_values) if net_values else 0.0,
        "profit_factor": profit_factor,
        "gross_pnl_rub": float(sum(gross_values)),
        "costs_rub": float(sum(costs)),
        "net_pnl_rub": float(sum(net_values)),
        "worst_trade_rub": float(min(net_values)) if net_values else 0.0,
        "worst_trade_nav_fraction": (float(min(net_values) / initial_nav) if net_values else 0.0),
        "bottom_decile_trade_mean_rub": tail_mean,
        "bottom_decile_trade_mean_nav_fraction": tail_mean / initial_nav,
    }


def evaluate(
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    source = config["source"]
    series = pd.read_parquet(config["_source_root"] / source["series"]["file"])
    daily = pd.read_parquet(config["_source_root"] / source["daily"]["file"])
    history = _prepare_daily(daily)
    protected = pd.Timestamp(config["dates"]["protected_from"])
    if history["trade_date"].ge(protected).any():
        raise ValueError("V56 protected rows detected")
    state = build_front_state(series, history, config)
    trades, counts = build_trades(config, state, history)
    lookup = _daily_lookup(history)
    start = pd.Timestamp(config["dates"]["evaluation_start"])
    end = pd.Timestamp(config["dates"]["evaluation_end"])
    dates = pd.DatetimeIndex(
        sorted(history.loc[history["trade_date"].between(start, end), "trade_date"].unique())
    )
    ledger = pd.DataFrame({"date": dates})
    initial_nav = float(config["execution"]["initial_nav_rub"])
    scenario_metrics: dict[str, Any] = {}
    for scenario in SCENARIOS:
        cost_points = float(
            config["cost_scenarios"][scenario]["adverse_rvi_points_per_contract_per_side"]
        )
        daily_pnl = pd.Series(0.0, index=dates)
        for trade in trades.itertuples(index=False):
            entry_date = pd.Timestamp(trade.entry_date)
            exit_date = pd.Timestamp(trade.exit_date)
            position_dates = dates[(dates >= entry_date) & (dates < exit_date)]
            previous_mark = float(trade.entry_open)
            for mark_date in position_dates:
                mark = lookup[(mark_date, str(trade.secid))]
                close = float(mark["close"])
                gross_delta = (previous_mark - close) * trade.point_value_proxy * trade.contracts
                daily_pnl.loc[mark_date] += gross_delta
                previous_mark = close
            side_cost = cost_points * trade.point_value_proxy * trade.contracts
            daily_pnl.loc[entry_date] -= side_cost
            exit_delta = (
                (previous_mark - float(trade.exit_open)) * trade.point_value_proxy * trade.contracts
            )
            daily_pnl.loc[exit_date] += exit_delta - side_cost
        nav = initial_nav + daily_pnl.cumsum()
        ledger[f"{scenario}_pnl"] = daily_pnl.to_numpy()
        ledger[f"{scenario}_nav"] = nav.to_numpy()
        item = metrics_engine.metrics(pd.Series(nav.to_numpy()), pd.Series(dates))
        item.update(_scenario_trade_statistics(trades, cost_points, initial_nav))
        item["minimum_nav_rub"] = float(nav.min())
        returns = nav.pct_change().dropna()
        item["worst_daily_return"] = float(returns.min()) if not returns.empty else 0.0
        scenario_metrics[scenario] = item
    unresolved_total = int(
        counts["unresolved_entries"] + counts["unresolved_exits"] + counts["unresolved_marks"]
    )
    gates = config["promotion_gates"]
    primary = scenario_metrics["primary"]
    primary_profit_factor = primary["profit_factor"]
    checks = {
        "minimum_completed_trades": len(trades) >= int(gates["minimum_completed_trades"]),
        "primary_cagr": primary["cagr"] >= float(gates["primary_cagr_gte"]),
        "doubled_cagr": scenario_metrics["doubled"]["cagr"] >= float(gates["doubled_cagr_gte"]),
        "stress_cagr": scenario_metrics["stress"]["cagr"] >= float(gates["stress_cagr_gte"]),
        "primary_sharpe": primary["sharpe"] >= float(gates["primary_sharpe_gte"]),
        "primary_mdd": primary["maximum_drawdown"] <= float(gates["primary_maximum_drawdown_lte"]),
        "stress_mdd": scenario_metrics["stress"]["maximum_drawdown"]
        <= float(gates["stress_maximum_drawdown_lte"]),
        "primary_worst_year": primary["worst_year"]
        >= float(gates["primary_worst_calendar_year_gte"]),
        "primary_positive_years": primary["positive_years"]
        >= int(gates["primary_positive_calendar_years_gte"]),
        "primary_worst_trade": primary["worst_trade_nav_fraction"]
        >= float(gates["primary_worst_trade_nav_fraction_gte"]),
        "primary_profit_factor": (
            math.inf if primary_profit_factor is None else primary_profit_factor
        )
        >= float(gates["primary_profit_factor_gte"]),
        "zero_unresolved": unresolved_total == int(gates["unresolved_entries_exits_or_marks_eq"]),
        "all_nav_positive": all(
            item["minimum_nav_rub"] > 0.0 for item in scenario_metrics.values()
        ),
    }
    if unresolved_total > 0:
        verdict = "INVALID_UNRESOLVED_EXECUTION_OR_MARKS"
    else:
        verdict = (
            "GO_TO_SEALED_EXACT_COST_CAPACITY_PORTFOLIO_TEST" if all(checks.values()) else "NO_GO"
        )
    counts["completed_trades"] = int(len(trades))
    summary = {
        "protocol_sha256": config["_config_sha256"],
        "counts": counts,
        "unresolved_total": unresolved_total,
        "exit_reasons": (
            trades["exit_reason"].value_counts().sort_index().to_dict() if not trades.empty else {}
        ),
        "scenarios": scenario_metrics,
        "gates": checks,
        "verdict": verdict,
        "adaptive_same_history": True,
        "live_trading_allowed": False,
    }
    return state, trades, ledger, summary


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as stream:
        path = Path(stream.name)
    try:
        frame.to_parquet(path, index=False)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _artifact(path: Path, rows: int | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha(path),
    }
    if rows is not None:
        item["rows"] = rows
    return item


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# V56 outright RVI outlier short corridor",
        "",
        f"Verdict: **{metrics['verdict']}**. Live trading: **false**.",
        "",
        "| Scenario | CAGR | Sharpe | MDD | Worst year | Net PnL | Trades | "
        "Win rate | Profit factor | Worst trade |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in metrics["scenarios"].items():
        profit_factor = "∞" if item["profit_factor"] is None else f"{item['profit_factor']:.3f}"
        lines.append(
            f"| {name} | {item['cagr']:.4%} | {item['sharpe']:.3f} | "
            f"{item['maximum_drawdown']:.4%} | {item['worst_year']:.4%} | "
            f"{item['net_pnl_rub']:.2f} | {item['completed_trades']} | "
            f"{item['win_rate']:.2%} | {profit_factor} | "
            f"{item['worst_trade_nav_fraction']:.4%} |"
        )
    lines.extend(
        [
            "",
            f"Counts: `{json.dumps(metrics['counts'], ensure_ascii=False)}`.",
            "",
            f"Exit reasons: `{json.dumps(metrics['exit_reasons'], ensure_ascii=False)}`.",
            "",
            "This is an adaptive 2021–2025 research proxy using daily OHLC and a "
            "point-value proxy. It does not prove bid/ask fills, exact specifications, "
            "predictable profit or permission for live trading.",
        ]
    )
    return "\n".join(lines) + "\n"


def audit_run(config: dict[str, Any], output: Path, rebuild: bool = True) -> dict[str, Any]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8-sig"))
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    trades = pd.read_parquet(output / "trades.parquet")
    state = pd.read_parquet(output / "front_state.parquet")
    checks = {
        "protocol_exact": manifest["protocol_sha256"] == config["_config_sha256"],
        "implementation_exact": manifest["implementation_sha256"] == _sha(Path(__file__)),
        "manifest_sidecar_exact": (output / "manifest.sha256")
        .read_text(encoding="utf-8-sig")
        .split()[0]
        == _sha(output / "manifest.json"),
        "artifacts_declared": set(manifest["artifacts"])
        == {"front_state", "trades", "daily_ledger", "metrics", "report"},
        "source_dates_before_2026": bool(state["date"].lt("2026-01-01").all()),
        "entry_after_signal": bool(
            trades.empty
            or pd.to_datetime(trades["entry_date"]).gt(pd.to_datetime(trades["signal_date"])).all()
        ),
        "exit_after_trigger": bool(
            trades.empty
            or pd.to_datetime(trades["exit_date"]).gt(pd.to_datetime(trades["trigger_date"])).all()
        ),
        "trades_nonoverlapping": bool(
            trades.empty
            or pd.to_datetime(trades["entry_date"])
            .iloc[1:]
            .reset_index(drop=True)
            .gt(pd.to_datetime(trades["exit_date"]).iloc[:-1].reset_index(drop=True))
            .all()
        ),
        "zero_unresolved_matches_metrics": metrics["gates"]["zero_unresolved"]
        == (metrics["unresolved_total"] == 0),
        "live_false": manifest["live_trading_allowed"] is False
        and metrics["live_trading_allowed"] is False,
    }
    for name, item in manifest["artifacts"].items():
        path = output / item["file"]
        checks[f"{name}_exact"] = path.exists() and _sha(path) == item["sha256"]
    if rebuild:
        rebuilt = evaluate(config)
        for name, expected in zip(
            ("front_state", "trades", "daily_ledger"), rebuilt[:3], strict=True
        ):
            try:
                pd.testing.assert_frame_equal(
                    pd.read_parquet(output / f"{name}.parquet"),
                    expected,
                    check_dtype=False,
                )
                checks[f"{name}_replay_exact"] = True
            except AssertionError:
                checks[f"{name}_replay_exact"] = False
        checks["metrics_replay_exact"] = metrics == rebuilt[3]
    return {
        "checks": checks,
        "all_true": all(checks.values()),
        "limitations": config["limitations"],
    }


def run(config: dict[str, Any]) -> Path:
    state, trades, ledger, metrics = evaluate(config)
    root = _root(config["outputs"]["root"], "runs")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = root.parent / f"{root.name}_{stamp}_{config['_config_sha256'][:8]}"
    output.mkdir(parents=True, exist_ok=False)
    frames = {
        "front_state": state,
        "trades": trades,
        "daily_ledger": ledger,
    }
    for name, frame in frames.items():
        atomic_write_bytes(output / f"{name}.parquet", _parquet_bytes(frame))
    write_json(output / "metrics.json", metrics)
    atomic_write_text(output / "report.md", _report(metrics))
    artifacts = {
        **{
            name: _artifact(output / f"{name}.parquet", len(frame))
            for name, frame in frames.items()
        },
        "metrics": _artifact(output / "metrics.json"),
        "report": _artifact(output / "report.md"),
    }
    manifest = {
        "run_id": output.name,
        "protocol_id": config["protocol_id"],
        "protocol_sha256": config["_config_sha256"],
        "implementation_sha256": _sha(Path(__file__)),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "verdict": metrics["verdict"],
        "adaptive_same_history": True,
        "live_trading_allowed": False,
        "artifacts": artifacts,
    }
    write_json(output / "manifest.json", manifest)
    atomic_write_text(
        output / "manifest.sha256",
        f"{_sha(output / 'manifest.json')}  manifest.json\n",
    )
    write_json(output / "audit.json", audit_run(config, output, True))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    config = load_protocol()
    if args.audit:
        audit = audit_run(config, args.audit, True)
        print(json.dumps(audit, indent=2, sort_keys=True))
        raise SystemExit(0 if audit["all_true"] else 1)
    output = run(config)
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    audit = json.loads((output / "audit.json").read_text(encoding="utf-8-sig"))
    print(f"run={output.name}")
    print(f"verdict={metrics['verdict']}")
    print(f"audit_all_true={audit['all_true']}")


if __name__ == "__main__":
    main()


__all__ = [
    "CONFIG_PATH",
    "CONFIG_SHA256",
    "_point_value",
    "build_front_state",
    "build_trades",
    "evaluate",
    "load_protocol",
]
