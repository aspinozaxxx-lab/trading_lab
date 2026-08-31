"""Adaptive V11 execution sensitivity for the sealed triangular signal."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from market_lab.futures_v10_triangular_relative_value.core import (
    PRIMARY_STRATEGY,
    PROTECTED_FROM,
    SignalSettings,
    build_signal_frame,
    calculate_metrics,
    settings_from_protocol,
)
from market_lab.futures_v10_triangular_relative_value.data import (
    PROJECT_ROOT,
    load_verified_panel,
    sha256_file,
)
from market_lab.futures_v10_triangular_relative_value.data import (
    load_protocol as load_v10_protocol,
)

CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v11_liquidity_buffered_open.yaml"
CONFIG_SHA256: Final[str] = (
    "584bf28977238681bfd90a39fa886eb0d1e1691a4799e041c4321d5bb02f400c"
)
SIGNAL_PARTICIPATION: Final[float] = 0.0025
REALIZED_PARTICIPATION_CAP: Final[float] = 0.01
MAXIMUM_PENDING_EXIT_BARS: Final[int] = 6


def load_protocol() -> dict[str, Any]:
    if sha256_file(CONFIG_PATH) != CONFIG_SHA256:
        raise ValueError("sealed V11 protocol byte drift")
    protocol = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("V11 protocol must be a mapping")
    if (
        protocol.get("protocol_id") != "futures_v11_liquidity_buffered_open_v1"
        or protocol.get("status") != "sealed_before_any_v11_outcome_calculation"
        or protocol["adaptive_research_notice"]["confirmatory_claim_from_2021_2025_forbidden"]
        is not True
        or float(protocol["execution"]["signal_bar_sizing_participation"])
        != SIGNAL_PARTICIPATION
        or float(protocol["execution"]["factual_entry_and_exit_participation_cap"])
        != REALIZED_PARTICIPATION_CAP
        or int(protocol["execution"]["maximum_pending_exit_bars"])
        != MAXIMUM_PENDING_EXIT_BARS
    ):
        raise ValueError("sealed V11 protocol invariants were weakened")
    return protocol


@dataclass(slots=True)
class _Position:
    entry_decision_index: int
    entry_fill_index: int
    entry_residual_side: int
    entry_zscore: float
    contracts: dict[str, str]
    leg_sides: dict[str, int]
    quantities: dict[str, int]
    entry_prices: dict[str, float]
    point_values: dict[str, float]
    notionals: dict[str, float]
    entry_cost_per_side: dict[str, float]
    entry_participation: dict[str, float]
    exit_reason: str = ""
    exit_trigger_index: int = -1
    pending_exit_bars: int = 0


@dataclass(frozen=True, slots=True)
class V11SimulationResult:
    trades: pd.DataFrame
    legs: pd.DataFrame
    unresolved_events: pd.DataFrame
    counts: dict[str, Any]
    halted: bool


def _usable_specs(row: pd.Series) -> bool:
    for asset in PRIMARY_STRATEGY.assets:
        if not bool(row[f"{asset}_sizing_usable"]):
            return False
        for field in (
            "sizing_point_value",
            "sizing_notional",
            "sizing_tick_cash_value",
        ):
            value = float(row[f"{asset}_{field}"])
            if not math.isfinite(value) or value <= 0.0:
                return False
        fee = float(row[f"{asset}_conservative_fee_per_side"])
        if not math.isfinite(fee) or fee < 0.0:
            return False
    return True


def _exact_successor(previous: pd.Series, current: pd.Series) -> bool:
    return pd.Timestamp(current["timestamp"]) == pd.Timestamp(previous["end_timestamp"])


def _contracts_match(row: pd.Series, position: _Position) -> bool:
    return all(
        str(row[f"{asset}_contract_id"]) == contract
        for asset, contract in position.contracts.items()
    )


def simulate_buffered_open(
    signals: pd.DataFrame,
    settings: SignalSettings,
) -> V11SimulationResult:
    """Use next-window opens, buffered causal size, and bounded exit retries."""

    frame = signals.reset_index(drop=True)
    if len(frame) and pd.Timestamp(frame["end_timestamp"].max()) > PROTECTED_FROM:
        raise ValueError("V11 simulation touches protected 2026 data")
    oos = frame["oos"].astype(bool)
    counts: dict[str, Any] = {
        "common_bars": int(oos.sum()),
        "eligible_signal_bars": int(frame["eligible_signal_bar"].sum()),
        "raw_entries": int(frame["raw_entry_signal"].sum()),
        "orders_submitted": 0,
        "entry_orders_unfilled_nonexact": 0,
        "entry_orders_unfilled_capacity": 0,
        "skipped_zero_quantity": 0,
        "skipped_missing_spec": 0,
        "exit_capacity_retries": 0,
        "unresolved": 0,
        "completed_trades": 0,
        "exits_by_reason": {"distant_stop": 0, "take_profit": 0, "time_exit": 0},
    }
    trade_rows: list[dict[str, Any]] = []
    leg_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    position: _Position | None = None
    equity = settings.initial_capital_rub
    halted = False

    def fail(index: int, reason: str) -> None:
        nonlocal halted
        counts["unresolved"] += 1
        unresolved_rows.append(
            {
                "strategy": "v11_triangular_buffered_open",
                "index": index,
                "decision_at": frame.iloc[index]["end_timestamp"],
                "reason": reason,
            }
        )
        halted = True

    for index in range(len(frame)):
        row = frame.iloc[index]
        if not bool(row["oos"]):
            continue
        exit_requested = False
        if position is not None:
            if index > position.entry_fill_index and not _exact_successor(
                frame.iloc[index - 1], row
            ):
                fail(index, "clock_gap_while_open")
                break
            if not _contracts_match(row, position):
                fail(index, "contract_changed_while_open")
                break
            holding_bars = index - position.entry_fill_index + 1
            zscore = float(row["zscore"])
            if not position.exit_reason:
                adverse = (
                    math.isfinite(zscore)
                    and position.entry_residual_side * zscore
                    <= -settings.distant_stop_absolute_z
                )
                if adverse:
                    position.exit_reason = "distant_stop"
                elif math.isfinite(zscore) and abs(zscore) <= settings.take_profit_absolute_z:
                    position.exit_reason = "take_profit"
                elif holding_bars >= settings.maximum_holding_completed_bars:
                    position.exit_reason = "time_exit"
                if position.exit_reason:
                    position.exit_trigger_index = index

            if position.exit_reason:
                exit_requested = True
                candidate_index = index + 1
                if candidate_index >= len(frame):
                    fail(index, "missing_exit_candidate")
                    break
                candidate = frame.iloc[candidate_index]
                if not _exact_successor(row, candidate):
                    fail(index, "non_exact_exit_candidate")
                    break
                if not _contracts_match(candidate, position):
                    fail(index, "contract_changed_before_exit")
                    break
                if not _usable_specs(row):
                    fail(index, "missing_exit_spec")
                    break
                capacity_ok = all(
                    position.quantities[asset]
                    <= math.floor(
                        REALIZED_PARTICIPATION_CAP * float(candidate[f"{asset}_volume"])
                    )
                    for asset in PRIMARY_STRATEGY.assets
                )
                if not capacity_ok:
                    position.pending_exit_bars += 1
                    counts["exit_capacity_retries"] += 1
                    if position.pending_exit_bars >= MAXIMUM_PENDING_EXIT_BARS:
                        fail(index, "exit_capacity_retry_limit")
                        break
                    continue

                current_legs: list[dict[str, Any]] = []
                for asset in PRIMARY_STRATEGY.assets:
                    side = position.leg_sides[asset]
                    quantity = position.quantities[asset]
                    exit_price = float(candidate[f"{asset}_open"])
                    gross_pnl = (
                        quantity
                        * position.point_values[asset]
                        * side
                        * (exit_price - position.entry_prices[asset])
                    )
                    exit_cost = float(
                        row[f"{asset}_conservative_fee_per_side"]
                        + row[f"{asset}_sizing_tick_cash_value"]
                    )
                    costs_1x = quantity * (
                        position.entry_cost_per_side[asset] + exit_cost
                    )
                    leg = {
                        "strategy": "v11_triangular_buffered_open",
                        "trade_id": len(trade_rows),
                        "asset": asset,
                        "contract_id": position.contracts[asset],
                        "side": "long" if side == 1 else "short",
                        "quantity": quantity,
                        "entry_price": position.entry_prices[asset],
                        "exit_price": exit_price,
                        "point_value": position.point_values[asset],
                        "entry_notional": quantity * position.notionals[asset],
                        "gross_pnl": gross_pnl,
                        "costs_1x": costs_1x,
                        "pnl_1x": gross_pnl - costs_1x,
                        "pnl_2x": gross_pnl - 2.0 * costs_1x,
                        "entry_participation": position.entry_participation[asset],
                        "exit_participation": quantity
                        / max(float(candidate[f"{asset}_volume"]), 1.0),
                    }
                    current_legs.append(leg)
                    leg_rows.append(leg)
                gross_pnl = float(sum(leg["gross_pnl"] for leg in current_legs))
                costs_1x = float(sum(leg["costs_1x"] for leg in current_legs))
                pnl_1x = gross_pnl - costs_1x
                pnl_2x = gross_pnl - 2.0 * costs_1x
                entry_decision = frame.iloc[position.entry_decision_index]
                trigger = frame.iloc[position.exit_trigger_index]
                trade_rows.append(
                    {
                        "strategy": "v11_triangular_buffered_open",
                        "trade_id": len(trade_rows),
                        "entry_decision_at": entry_decision["end_timestamp"],
                        "entry_fill_at": frame.iloc[position.entry_fill_index]["timestamp"],
                        "exit_decision_at": trigger["end_timestamp"],
                        "exit_fill_at": candidate["timestamp"],
                        "entry_side": (
                            "long_residual"
                            if position.entry_residual_side == 1
                            else "short_residual"
                        ),
                        "entry_zscore": position.entry_zscore,
                        "exit_zscore": float(trigger["zscore"]),
                        "holding_completed_bars": (
                            position.exit_trigger_index - position.entry_fill_index + 1
                        ),
                        "pending_exit_bars": position.pending_exit_bars,
                        "exit_reason": position.exit_reason,
                        "gross_entry_notional": float(
                            sum(
                                position.quantities[asset] * position.notionals[asset]
                                for asset in PRIMARY_STRATEGY.assets
                            )
                        ),
                        "gross_pnl": gross_pnl,
                        "costs_1x": costs_1x,
                        "pnl_1x": pnl_1x,
                        "pnl_2x": pnl_2x,
                        "maximum_entry_participation": max(
                            position.entry_participation.values()
                        ),
                        "maximum_exit_participation": max(
                            float(leg["exit_participation"]) for leg in current_legs
                        ),
                    }
                )
                equity += pnl_1x
                counts["completed_trades"] += 1
                counts["exits_by_reason"][position.exit_reason] += 1
                position = None

        if halted or position is not None or exit_requested:
            continue
        if not bool(row["raw_entry_signal"]):
            continue
        counts["orders_submitted"] += 1
        if not bool(row["exact_next"]):
            counts["entry_orders_unfilled_nonexact"] += 1
            continue
        if not _usable_specs(row):
            counts["skipped_missing_spec"] += 1
            continue
        entry_index = index + 1
        entry = frame.iloc[entry_index]
        residual_side = int(row["residual_position_side"])
        quantities: dict[str, int] = {}
        notionals: dict[str, float] = {}
        for asset in PRIMARY_STRATEGY.assets:
            notional = float(row[f"{asset}_sizing_notional"])
            capital_quantity = math.floor(
                PRIMARY_STRATEGY.gross_fraction_per_leg * max(equity, 0.0) / notional
            )
            buffered_capacity = math.floor(
                SIGNAL_PARTICIPATION * float(row[f"{asset}_volume"])
            )
            quantities[asset] = min(capital_quantity, buffered_capacity)
            notionals[asset] = notional
        if any(quantity < 1 for quantity in quantities.values()):
            counts["skipped_zero_quantity"] += 1
            continue
        gross = sum(quantities[asset] * notionals[asset] for asset in PRIMARY_STRATEGY.assets)
        if gross > settings.maximum_gross_fraction * max(equity, 0.0) + 1e-9:
            raise AssertionError("V11 gross cap exceeded")
        capacity_ok = all(
            quantities[asset]
            <= math.floor(REALIZED_PARTICIPATION_CAP * float(entry[f"{asset}_volume"]))
            for asset in PRIMARY_STRATEGY.assets
        )
        if not capacity_ok:
            counts["entry_orders_unfilled_capacity"] += 1
            continue
        contracts: dict[str, str] = {}
        leg_sides: dict[str, int] = {}
        entry_prices: dict[str, float] = {}
        point_values: dict[str, float] = {}
        entry_costs: dict[str, float] = {}
        entry_participation: dict[str, float] = {}
        for asset, coefficient in zip(
            PRIMARY_STRATEGY.assets, PRIMARY_STRATEGY.coefficients, strict=True
        ):
            contracts[asset] = str(row[f"{asset}_contract_id"])
            leg_sides[asset] = residual_side * coefficient
            entry_prices[asset] = float(entry[f"{asset}_open"])
            point_values[asset] = float(row[f"{asset}_sizing_point_value"])
            entry_costs[asset] = float(
                row[f"{asset}_conservative_fee_per_side"]
                + row[f"{asset}_sizing_tick_cash_value"]
            )
            entry_participation[asset] = quantities[asset] / max(
                float(entry[f"{asset}_volume"]), 1.0
            )
        position = _Position(
            entry_decision_index=index,
            entry_fill_index=entry_index,
            entry_residual_side=residual_side,
            entry_zscore=float(row["zscore"]),
            contracts=contracts,
            leg_sides=leg_sides,
            quantities=quantities,
            entry_prices=entry_prices,
            point_values=point_values,
            notionals=notionals,
            entry_cost_per_side=entry_costs,
            entry_participation=entry_participation,
        )

    if position is not None and not halted:
        fail(len(frame) - 1, "open_position_at_data_end")
    return V11SimulationResult(
        trades=pd.DataFrame(trade_rows),
        legs=pd.DataFrame(leg_rows),
        unresolved_events=pd.DataFrame(unresolved_rows),
        counts=counts,
        halted=halted,
    )


def _screen(
    ordinary: dict[str, Any],
    doubled: dict[str, Any],
    counts: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    checks = {
        "metrics_valid": bool(ordinary["valid"] and doubled["valid"]),
        "completed_trades": int(ordinary["trades"]) >= int(rules["completed_trades_minimum"]),
        "minimum_trades_each_year": all(
            int(values["trades"]) >= int(rules["minimum_trades_each_year"])
            for values in ordinary["per_year"].values()
        ),
        "positive_years": int(ordinary["positive_years"])
        >= int(rules["positive_years_minimum"]),
        "ordinary_cagr": float(ordinary["cagr"]) >= float(rules["ordinary_cagr_minimum"]),
        "ordinary_sharpe": float(ordinary["annualized_sharpe"])
        >= float(rules["ordinary_annualized_sharpe_minimum"]),
        "maximum_drawdown": float(ordinary["maximum_drawdown"])
        >= float(rules["maximum_drawdown_floor"]),
        "doubled_cost_cagr": float(doubled["cagr"]) > 0.0,
        "unresolved_zero": int(counts["unresolved"]) == 0,
        "participation_cap": float(ordinary["maximum_realized_participation"])
        <= REALIZED_PARTICIPATION_CAP + 1e-12,
    }
    return {"passed": all(checks.values()), "checks": checks}


def _json_default(value: object) -> object:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_report(path: Path, result: dict[str, Any]) -> None:
    ordinary = result["ordinary_cost"]
    doubled = result["doubled_cost"]
    counts = result["counts"]
    lines = [
        "# V11 liquidity-buffered open execution result",
        "",
        f"- Verdict: **{result['verdict']}**",
        f"- Protocol SHA-256: `{result['protocol_sha256']}`",
        f"- Completed trades: {counts['completed_trades']}",
        f"- Unresolved events: {counts['unresolved']}",
        f"- Ordinary CAGR (partial if invalid): {ordinary['cagr']:.6%}",
        f"- Ordinary Sharpe (partial if invalid): {ordinary['annualized_sharpe']:.6f}",
        f"- Ordinary maximum drawdown: {ordinary['maximum_drawdown']:.6%}",
        f"- Doubled-cost CAGR (partial if invalid): {doubled['cagr']:.6%}",
        "",
        "This adaptive same-period experiment is exploratory only. It cannot support a",
        "confirmatory or live-trading claim without genuinely unseen history.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_experiment(output_dir: Path) -> dict[str, Any]:
    protocol = load_protocol()
    v10_protocol = load_v10_protocol()
    settings = settings_from_protocol(v10_protocol)
    loaded = load_verified_panel()
    output_dir.mkdir(parents=True, exist_ok=False)
    signals = build_signal_frame(loaded.panel, PRIMARY_STRATEGY, settings)
    simulation = simulate_buffered_open(signals, settings)
    valid = not simulation.halted and int(simulation.counts["unresolved"]) == 0
    ordinary = calculate_metrics(
        signals,
        simulation.trades,
        settings,
        cost_column="pnl_1x",
        valid=valid,
    )
    doubled = calculate_metrics(
        signals,
        simulation.trades,
        settings,
        cost_column="pnl_2x",
        valid=valid,
    )
    screen = _screen(
        ordinary,
        doubled,
        simulation.counts,
        protocol["exploratory_screen_only"],
    )
    if simulation.halted:
        verdict = "NO_GO_UNRESOLVED_EXECUTION"
    elif screen["passed"]:
        verdict = "CANDIDATE_FOR_NEW_UNSEEN_HISTORY"
    else:
        verdict = "NO_GO_EXPLORATORY_SCREEN_NOT_MET"

    signal_columns = [
        "timestamp",
        "end_timestamp",
        "local_date",
        "residual",
        "baseline_mean",
        "baseline_std",
        "zscore",
        "contract_run_id",
        "exact_next",
        "oos",
        "entry_window",
        "signal_ready",
        "eligible_signal_bar",
        "raw_entry_signal",
        "residual_position_side",
    ]
    signals[signal_columns].to_parquet(output_dir / "signal_audit.parquet", index=False)
    simulation.trades.to_parquet(output_dir / "trades.parquet", index=False)
    simulation.legs.to_parquet(output_dir / "legs.parquet", index=False)
    simulation.unresolved_events.to_parquet(output_dir / "unresolved.parquet", index=False)
    result: dict[str, Any] = {
        "schema_version": 1,
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "parent_signal_protocol_sha256": v10_protocol["parents"]["alpha_protocol"]["sha256"]
        if "parents" in v10_protocol
        else "4ff5c4cb84e5ecd608d69f5673a0e8af6e4f8103cea8f9cb348530e525e6103c",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "research_only": True,
        "adaptive_same_period": True,
        "confirmatory_claim_allowed": False,
        "live_trading_allowed": False,
        "protected_holdout_touches": 0,
        "verdict": verdict,
        "exploratory_screen": screen,
        "counts": simulation.counts,
        "ordinary_cost": ordinary,
        "doubled_cost": doubled,
        "data_counts": loaded.counts,
        "source_hashes": loaded.source_hashes,
        "code_hashes": {
            "v10_core.py": sha256_file(
                PROJECT_ROOT
                / "src/market_lab/futures_v10_triangular_relative_value/core.py"
            ),
            "v10_data.py": sha256_file(
                PROJECT_ROOT
                / "src/market_lab/futures_v10_triangular_relative_value/data.py"
            ),
            "v11.py": sha256_file(Path(__file__)),
        },
        "artifacts": {},
    }
    _write_report(output_dir / "report.md", result)
    for name in (
        "signal_audit.parquet",
        "trades.parquet",
        "legs.parquet",
        "unresolved.parquet",
        "report.md",
    ):
        path = output_dir / name
        result["artifacts"][name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    _write_json(output_dir / "metrics.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_experiment(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
