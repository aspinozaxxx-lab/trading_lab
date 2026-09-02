"""Evaluate the sealed V45 adjacent-month RVI calendar corridor."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures import moex_stock_futures_cash_carry_source as io_utils
from market_lab.futures_v40_v39_cash_carry_stability import _metrics
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v45_rvi_calendar_corridor.yaml"
CONFIG_SHA256: Final[str] = (
    "2207f5491c4cdc186d7fe25aec78bb354d2c53494964bbba677b26ef99b2e71e"
)
SCENARIOS: Final[tuple[str, ...]] = ("primary", "doubled", "stress")


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    source_root: Path


def _sha(path: Path) -> str:
    return io_utils.sha256_file(path)


def _relative_root(value: str, prefix: tuple[str, ...]) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe V45 path: {value}")
    if tuple(part.lower() for part in relative.parts[: len(prefix)]) != tuple(prefix):
        raise ValueError(f"V45 path must start with {'/'.join(prefix)}")
    return PROJECT_ROOT / relative


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V45 config must be an object")
    signal = payload["signal"]
    execution = payload["execution"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "futures_v45_rvi_calendar_corridor_v1"
        or payload.get("live_trading_allowed") is not False
        or int(signal["rolling_complete_pair_observations"]) != 63
        or int(signal["minimum_prior_observations"]) != 42
        or float(signal["entry_absolute_z_gte"]) != 1.5
        or float(signal["take_profit_absolute_z_lte"]) != 0.5
        or float(signal["adverse_stop_absolute_z_gte"]) != 4.0
        or float(execution["initial_nav_rub"]) != 1_000_000.0
    ):
        raise ValueError("V45 protocol drifted")
    source = payload["source"]
    root = _relative_root(source["root"], ("data", "processed"))
    for key in ("manifest", "series", "daily", "raw", "audit"):
        declaration = source[key]
        path = root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"V45 source artifact drifted: {key}")
        if key in {"series", "daily"} and pq.ParquetFile(path).metadata.num_rows != int(
            declaration["rows"]
        ):
            raise ValueError(f"V45 source rows drifted: {key}")
    manifest = json.loads((root / source["manifest"]["file"]).read_text("utf-8-sig"))
    audit = json.loads((root / source["audit"]["file"]).read_text("utf-8-sig"))
    if (
        manifest["protocol_sha256"] != source["protocol_sha256"]
        or manifest["implementation_sha256"] != source["implementation_sha256"]
        or manifest["source_only"] is not True
        or manifest["contains_curve_return_label_signal_trade_or_pnl"] is not False
        or audit["all_true"] is not True
    ):
        raise ValueError("V45 source identity or source-only audit drifted")
    return Protocol(payload, actual, root)


def _point_value(frame: pd.DataFrame) -> pd.Series:
    denominator = frame["volume"] * frame["waprice"]
    result = frame["value"] / denominator.where(denominator.gt(0.0))
    return result.where(np.isfinite(result) & result.gt(0.0))


def build_curve_state(protocol: Protocol) -> pd.DataFrame:
    series = pd.read_parquet(protocol.source_root / "series.parquet")
    daily = pd.read_parquet(protocol.source_root / "daily_history.parquet")
    series["start_date"] = pd.to_datetime(series["start_date"], errors="raise")
    series["expiration_date"] = pd.to_datetime(
        series["expiration_date"], errors="raise"
    )
    daily["trade_date"] = pd.to_datetime(daily["trade_date"], errors="raise")
    daily["expiration_date"] = pd.to_datetime(
        daily["expiration_date"], errors="raise"
    )
    if daily["trade_date"].ge(protocol.payload["dates"]["protected_from"]).any():
        raise ValueError("V45 protected history leaked")
    daily["point_value"] = _point_value(daily)
    lookup = daily.set_index(["trade_date", "secid"], verify_integrity=True)
    dates = pd.DatetimeIndex(sorted(daily["trade_date"].unique()))
    pair = protocol.payload["pair_selection"]
    rows: list[dict[str, Any]] = []
    for date in dates:
        available = series.loc[
            series["start_date"].le(date) & series["expiration_date"].gt(date)
        ].sort_values("expiration_date")
        if len(available) < 2:
            continue
        front, nxt = available.iloc[0], available.iloc[1]
        front_dte = int((front["expiration_date"] - date).days)
        next_dte = int((nxt["expiration_date"] - date).days)
        gap = next_dte - front_dte
        structural = (
            int(pair["front_days_to_expiry_min"])
            <= front_dte
            <= int(pair["front_days_to_expiry_max"])
            and int(pair["expiration_gap_days_min"])
            <= gap
            <= int(pair["expiration_gap_days_max"])
        )
        front_key, next_key = (date, str(front["secid"])), (date, str(nxt["secid"]))
        front_row = lookup.loc[front_key] if front_key in lookup.index else None
        next_row = lookup.loc[next_key] if next_key in lookup.index else None
        complete = bool(
            structural
            and front_row is not None
            and next_row is not None
            and pd.notna(front_row["close"])
            and pd.notna(next_row["close"])
            and float(front_row["close"]) > 0.0
            and float(next_row["close"]) > 0.0
            and float(front_row["volume"]) > 0.0
            and float(next_row["volume"]) > 0.0
            and float(front_row["num_trades"]) > 0.0
            and float(next_row["num_trades"]) > 0.0
        )
        row: dict[str, Any] = {
            "date": date,
            "front_secid": str(front["secid"]),
            "next_secid": str(nxt["secid"]),
            "front_dte": front_dte,
            "next_dte": next_dte,
            "structural": structural,
            "complete": complete,
        }
        for label, value in (("front", front_row), ("next", next_row)):
            for column in (
                "open",
                "close",
                "high",
                "low",
                "volume",
                "num_trades",
                "point_value",
            ):
                row[f"{label}_{column}"] = (
                    float(value[column])
                    if value is not None and pd.notna(value[column])
                    else np.nan
                )
        rows.append(row)
    state = pd.DataFrame(rows).sort_values("date", ignore_index=True)
    valid = state.loc[state["complete"]].copy()
    valid["curve"] = 365.0 * np.log(valid["next_close"] / valid["front_close"]) / (
        valid["next_dte"] - valid["front_dte"]
    )
    valid["raw_spread"] = valid["next_close"] - valid["front_close"]
    window = int(protocol.payload["signal"]["rolling_complete_pair_observations"])
    minimum = int(protocol.payload["signal"]["minimum_prior_observations"])
    prior = valid["curve"].shift(1)
    rolling = prior.rolling(window, min_periods=minimum)
    valid["center"] = rolling.median()
    valid["scale"] = (
        1.4826
        * rolling.apply(
            lambda values: float(
                np.median(np.abs(values - np.median(values)))
            ),
            raw=True,
        )
    ).clip(lower=float(protocol.payload["signal"]["scale_floor"]))
    raw_prior = valid["raw_spread"].shift(1)
    valid["raw_spread_mad"] = (
        1.4826
        * raw_prior.rolling(window, min_periods=minimum).apply(
            lambda values: float(
                np.median(np.abs(values - np.median(values)))
            ),
            raw=True,
        )
    )
    valid["z"] = (valid["curve"] - valid["center"]) / valid["scale"]
    derived = valid.set_index("date")[
        ["curve", "raw_spread", "center", "scale", "raw_spread_mad", "z"]
    ]
    return state.join(derived, on="date")


def _execution_row(
    state: pd.DataFrame, date: pd.Timestamp, front: str, nxt: str
) -> pd.Series | None:
    match = state.loc[
        state["date"].eq(date)
        & state["front_secid"].eq(front)
        & state["next_secid"].eq(nxt)
    ]
    return None if match.empty else match.iloc[0]


def build_trades(protocol: Protocol, state: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    config = protocol.payload
    signal = config["signal"]
    execution = config["execution"]
    dates = pd.DatetimeIndex(sorted(state["date"].unique()))
    position = {date: index for index, date in enumerate(dates)}
    eligible = state.loc[
        state["complete"]
        & state["date"].ge(config["dates"]["evaluation_start"])
        & state["date"].le(config["dates"]["evaluation_end"])
        & state["z"].abs().ge(float(signal["entry_absolute_z_gte"]))
    ]
    rows: list[dict[str, Any]] = []
    next_free = pd.Timestamp(config["dates"]["evaluation_start"])
    counts = {"signals": len(eligible), "entry_rejections": 0, "unresolved_exits": 0}
    initial_nav = float(execution["initial_nav_rub"])
    for candidate in eligible.itertuples(index=False):
        if candidate.date < next_free:
            continue
        decision_index = position[pd.Timestamp(candidate.date)]
        if decision_index + 1 >= len(dates):
            continue
        entry_date = dates[decision_index + 1]
        entry = _execution_row(
            state, entry_date, candidate.front_secid, candidate.next_secid
        )
        if entry is None:
            counts["entry_rejections"] += 1
            continue
        minimum_volume = float(execution["minimum_entry_volume_each_leg"])
        entry_valid = bool(
            pd.notna(entry["front_open"])
            and pd.notna(entry["next_open"])
            and entry["front_volume"] >= minimum_volume
            and entry["next_volume"] >= minimum_volume
            and entry["front_num_trades"] > 0
            and entry["next_num_trades"] > 0
            and pd.notna(candidate.front_point_value)
            and pd.notna(candidate.next_point_value)
            and pd.notna(candidate.raw_spread_mad)
            and candidate.raw_spread_mad > 0
        )
        if not entry_valid:
            counts["entry_rejections"] += 1
            continue
        point_value = (candidate.front_point_value + candidate.next_point_value) / 2.0
        relative_difference = abs(
            candidate.front_point_value - candidate.next_point_value
        ) / point_value
        if relative_difference > float(
            execution["maximum_point_value_relative_leg_difference"]
        ):
            counts["entry_rejections"] += 1
            continue
        volume_cap = np.floor(
            float(execution["maximum_entry_fraction_of_each_leg_daily_volume"])
            * min(entry["front_volume"], entry["next_volume"])
        )
        gross_per_pair = point_value * (entry["front_open"] + entry["next_open"])
        gross_cap = np.floor(
            float(execution["gross_notional_cap_nav"]) * initial_nav / gross_per_pair
        )
        stop_per_pair = 2.5 * candidate.raw_spread_mad * point_value
        risk_cap = np.floor(
            float(execution["stop_risk_budget_nav"]) * initial_nav / stop_per_pair
        )
        contracts = int(max(0.0, min(volume_cap, gross_cap, risk_cap)))
        if contracts < 1:
            counts["entry_rejections"] += 1
            continue
        direction = -1 if candidate.z < 0 else 1
        trigger_reason = "maximum_holding"
        trigger_index = min(
            position[entry_date] + int(signal["maximum_holding_sessions"]),
            len(dates) - 2,
        )
        for scan_index in range(position[entry_date], trigger_index + 1):
            current = _execution_row(
                state, dates[scan_index], candidate.front_secid, candidate.next_secid
            )
            if current is None:
                continue
            current_z = current["z"]
            if current["front_dte"] <= int(signal["force_exit_front_dte_lte"]):
                trigger_index, trigger_reason = scan_index, "expiry_buffer"
                break
            if pd.notna(current_z) and abs(current_z) <= float(
                signal["take_profit_absolute_z_lte"]
            ):
                trigger_index, trigger_reason = scan_index, "take_profit"
                break
            adverse = bool(
                pd.notna(current_z)
                and np.sign(current_z) == np.sign(candidate.z)
                and abs(current_z) >= float(signal["adverse_stop_absolute_z_gte"])
            )
            if adverse:
                trigger_index, trigger_reason = scan_index, "distant_stop"
                break
        exit_row = None
        exit_date = None
        retries = int(execution["maximum_exit_retry_sessions"])
        for exit_index in range(trigger_index + 1, min(trigger_index + 2 + retries, len(dates))):
            possible = _execution_row(
                state, dates[exit_index], candidate.front_secid, candidate.next_secid
            )
            if possible is None:
                continue
            capacity = float(execution["maximum_exit_fraction_of_each_leg_daily_volume"])
            if bool(
                pd.notna(possible["front_open"])
                and pd.notna(possible["next_open"])
                and possible["front_num_trades"] > 0
                and possible["next_num_trades"] > 0
                and contracts <= capacity * possible["front_volume"]
                and contracts <= capacity * possible["next_volume"]
            ):
                exit_row, exit_date = possible, dates[exit_index]
                break
        if exit_row is None or exit_date is None:
            counts["unresolved_exits"] += 1
            continue
        rows.append(
            {
                "signal_date": candidate.date,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "front_secid": candidate.front_secid,
                "next_secid": candidate.next_secid,
                "signal_z": candidate.z,
                "direction_long_front": direction,
                "contracts_each_leg": contracts,
                "point_value_proxy": point_value,
                "front_entry": entry["front_open"],
                "next_entry": entry["next_open"],
                "front_exit": exit_row["front_open"],
                "next_exit": exit_row["next_open"],
                "exit_reason": trigger_reason,
                "holding_exchange_sessions": position[exit_date] - position[entry_date],
            }
        )
        next_free = pd.Timestamp(exit_date) + pd.Timedelta(days=1)
    return pd.DataFrame(rows), counts


def evaluate(
    protocol: Protocol, trades: pd.DataFrame, counts: dict[str, int], state: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dates = pd.DatetimeIndex(
        sorted(
            state.loc[
                state["date"].ge(protocol.payload["dates"]["evaluation_start"])
                & state["date"].le(protocol.payload["dates"]["evaluation_end"]),
                "date",
            ].unique()
        )
    )
    ledger = pd.DataFrame({"date": dates})
    scenario_metrics: dict[str, Any] = {}
    initial = float(protocol.payload["execution"]["initial_nav_rub"])
    for scenario in SCENARIOS:
        cost_points = float(
            protocol.payload["cost_scenarios"][scenario][
                "adverse_rvi_points_per_leg_per_side"
            ]
        )
        pnl = pd.Series(0.0, index=dates)
        scenario_pnl = []
        for trade in trades.itertuples(index=False):
            gross = (
                trade.direction_long_front
                * (
                    (trade.front_exit - trade.front_entry)
                    - (trade.next_exit - trade.next_entry)
                )
                * trade.point_value_proxy
                * trade.contracts_each_leg
            )
            cost = (
                4.0
                * cost_points
                * trade.point_value_proxy
                * trade.contracts_each_leg
            )
            net = gross - cost
            pnl.loc[pd.Timestamp(trade.exit_date)] += net
            scenario_pnl.append(net)
        ledger[f"{scenario}_pnl"] = pnl.to_numpy()
        ledger[f"{scenario}_nav"] = initial + pnl.cumsum().to_numpy()
        metrics = _metrics(pd.Series(ledger[f"{scenario}_nav"].to_numpy(), index=dates))
        positives = [value for value in scenario_pnl if value > 0.0]
        negatives = [value for value in scenario_pnl if value < 0.0]
        metrics.update(
            {
                "completed_trades": len(scenario_pnl),
                "win_rate": len(positives) / len(scenario_pnl) if scenario_pnl else 0.0,
                "profit_factor": (
                    sum(positives) / abs(sum(negatives))
                    if negatives
                    else (float("inf") if positives else 0.0)
                ),
                "net_pnl_rub": float(sum(scenario_pnl)),
            }
        )
        scenario_metrics[scenario] = metrics
    gates_cfg = protocol.payload["promotion_gates"]
    primary = scenario_metrics["primary"]
    gates = {
        "minimum_completed_trades": len(trades)
        >= int(gates_cfg["minimum_completed_trades"]),
        "primary_cagr": primary["cagr"] >= float(gates_cfg["primary_cagr_gte"]),
        "doubled_cagr": scenario_metrics["doubled"]["cagr"]
        >= float(gates_cfg["doubled_cagr_gte"]),
        "stress_total_positive": scenario_metrics["stress"]["total_return"]
        > float(gates_cfg["stress_total_return_gt"]),
        "primary_sharpe": primary["sharpe"]
        >= float(gates_cfg["primary_sharpe_gte"]),
        "primary_mdd": primary["maximum_drawdown"]
        <= float(gates_cfg["primary_maximum_drawdown_lte"]),
        "positive_years": primary["positive_years"]
        >= int(gates_cfg["primary_positive_calendar_years_gte"]),
        "execution_complete": counts["unresolved_exits"] == 0,
    }
    verdict = (
        "INVALID_UNRESOLVED_EXECUTION"
        if counts["unresolved_exits"] > 0
        else ("GO_TO_SEALED_V41_PORTFOLIO_TEST" if all(gates.values()) else "NO_GO")
    )
    metrics = {
        "verdict": verdict,
        "counts": {**counts, "completed_trades": len(trades)},
        "exit_reasons": (
            trades["exit_reason"].value_counts().sort_index().to_dict()
            if not trades.empty
            else {}
        ),
        "scenarios": scenario_metrics,
        "gates": gates,
        "adaptive_same_history": True,
        "live_trading_allowed": False,
    }
    return ledger, metrics


def build(protocol: Protocol) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    state = build_curve_state(protocol)
    trades, counts = build_trades(protocol, state)
    ledger, metrics = evaluate(protocol, trades, counts, state)
    return state, trades, ledger, metrics


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# V45 RVI adjacent-month calendar corridor",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        "| Scenario | CAGR | Sharpe | MDD | Worst year | Trades | Win rate | Profit factor |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in metrics["scenarios"].items():
        lines.append(
            f"| {name} | {item['cagr']:.4%} | {item['sharpe']:.3f} | "
            f"{item['maximum_drawdown']:.4%} | {item['worst_year']:.4%} | "
            f"{item['completed_trades']} | {item['win_rate']:.2%} | "
            f"{item['profit_factor']:.3f} |"
        )
    lines.extend(
        [
            "",
            f"Counts: `{json.dumps(metrics['counts'], ensure_ascii=False)}`.",
            "",
            "Daily OHLC does not prove atomic bid/ask fills. This is same-history "
            "research; live trading is forbidden.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(protocol: Protocol) -> Path:
    state, trades, ledger, metrics = build(protocol)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = _relative_root(protocol.payload["outputs"]["root"], ("runs",))
    output = base.parent / f"{base.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"V45 output exists: {output}")
    output.mkdir(parents=True)
    paths = {
        "curve": output / "curve_state.parquet",
        "trades": output / "trades.parquet",
        "ledger": output / "daily_ledger.parquet",
        "metrics": output / "metrics.json",
        "report": output / "report.md",
    }
    io_utils._write_parquet(paths["curve"], state)
    io_utils._write_parquet(paths["trades"], trades)
    io_utils._write_parquet(paths["ledger"], ledger)
    write_json(paths["metrics"], metrics)
    atomic_write_bytes(paths["report"], _report(metrics).encode("utf-8-sig"))
    audit = {
        "checks": {
            "protocol_sha_exact": _sha(CONFIG_PATH) == protocol.config_sha256,
            "source_dates_before_2026": bool(state["date"].lt("2026-01-01").all()),
            "signals_causal": bool(
                state.loc[state["z"].notna(), ["center", "scale"]].notna().all(axis=None)
            ),
            "trades_nonoverlapping": bool(
                trades.empty
                or pd.to_datetime(trades["entry_date"])
                .iloc[1:]
                .reset_index(drop=True)
                .gt(pd.to_datetime(trades["exit_date"]).iloc[:-1].reset_index(drop=True))
                .all()
            ),
            "all_nav_positive": bool(ledger.filter(regex="_nav$").gt(0.0).all(axis=None)),
            "execution_complete": metrics["counts"]["unresolved_exits"] == 0,
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    audit["all_true"] = all(audit["checks"].values())
    write_json(output / "audit.json", audit)
    artifacts = {
        key: {"file": path.name, "sha256": _sha(path), "bytes": path.stat().st_size}
        for key, path in paths.items()
    }
    artifacts["audit"] = {
        "file": "audit.json",
        "sha256": _sha(output / "audit.json"),
        "bytes": (output / "audit.json").stat().st_size,
    }
    manifest = {
        "protocol_id": protocol.payload["protocol_id"],
        "protocol_sha256": protocol.config_sha256,
        "implementation_sha256": _sha(Path(__file__)),
        "created_at_utc": datetime.now(UTC).isoformat(),
        "artifacts": artifacts,
        "verdict": metrics["verdict"],
        "adaptive_same_history": True,
        "live_trading_allowed": False,
    }
    write_json(output / "manifest.json", manifest)
    atomic_write_bytes(
        output / "manifest.sha256",
        f"{_sha(output / 'manifest.json')}  manifest.json\n".encode("utf-8-sig"),
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    protocol = load_protocol()
    if args.build_only:
        _, _, _, metrics = build(protocol)
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print(run(protocol))


if __name__ == "__main__":
    main()
