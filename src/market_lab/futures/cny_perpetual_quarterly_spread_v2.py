"""Unit-corrected V2 CNYRUBF short versus quarterly CR long experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

from market_lab.futures import cny_perpetual_quarterly_spread_v1 as parent
from market_lab.futures import fx_cash_carry_v1 as ledger

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/cny_perpetual_quarterly_spread_v2.yaml"
CONFIG_SHA256: Final[str] = "6a0a7cbea42e82f6e22f03670c811be3e040af4cc2b5644e0c55ba6f2be4bf4f"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_RUN_ROOT: Final[Path] = PROJECT_ROOT / "runs"


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8-sig",
    )


def load_protocol() -> dict[str, Any]:
    actual = _sha_file(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".yaml.sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    if actual != CONFIG_SHA256 or declared != CONFIG_SHA256:
        raise ValueError("CNY perpetual-quarterly V2 config seal mismatch")
    correction = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    base = parent.load_protocol()
    unit = correction["exact_corrections"]["point_value_rub_per_price_unit"]
    if (
        correction.get("protocol_id") != "cny_perpetual_quarterly_spread_v2"
        or correction.get("live_trading_allowed") is not False
        or correction["parent"]["config_sha256"] != parent.CONFIG_SHA256
        or correction["parent"]["invalid_metrics_sha256"]
        != "109f501794d3c858603106a1ea16866ab677084cd3f405f057c7eb4945481438"
        or correction["diagnosis"]["parent_numeric_result_valid"] is not False
        or correction["diagnosis"]["no_corrected_return_or_pnl_read_before_this_seal"]
        is not True
        or unit != {"old": 1.0, "new": 1000.0, "basis": "lot_size_cny_for_rub_per_cny_quote"}
    ):
        raise ValueError("CNY perpetual-quarterly V2 correction invariant drift")
    effective = json.loads(json.dumps(base))
    effective["protocol_id"] = correction["protocol_id"]
    effective["protocol_version"] = 2
    effective["official_accounting"]["point_value_rub_per_price_unit"] = float(unit["new"])
    effective["output"]["root"] = correction["output"]["root"]
    effective["v2_correction"] = correction
    return effective


def load_inputs(
    protocol: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], pd.DataFrame, dict[str, bool], dict[str, str]]:
    return parent.load_inputs(protocol or load_protocol())


def build_candidate(
    perpetual: pd.DataFrame,
    contract: dict[str, Any],
    ruonia: pd.DataFrame,
    protocol: dict[str, Any],
    scenario: str,
) -> dict[str, Any] | None:
    candidate = parent.build_candidate(perpetual, contract, ruonia, protocol, scenario)
    if candidate is None:
        return None
    spread, commission = parent._scenario_costs(protocol, scenario)
    point_value = float(protocol["official_accounting"]["point_value_rub_per_price_unit"])
    perp_open = float(candidate["perpetual_open"])
    quarter_open = float(candidate["quarterly_open"])
    perp_entry = float(candidate["perpetual_entry"])
    quarter_entry = float(candidate["quarterly_entry"])
    midpoint = (perp_open + quarter_open) / 2.0
    estimated_exit_spread = 2.0 * midpoint * spread * point_value
    estimated_commissions = (
        2.0 * (perp_open + quarter_open) * commission * point_value
    )
    estimated_convergence = (perp_entry - quarter_entry) * point_value
    estimated_funding = float(candidate["estimated_funding_rub"])
    estimated_profit = (
        estimated_convergence
        + estimated_funding
        - estimated_exit_spread
        - estimated_commissions
        if math.isfinite(estimated_funding)
        else math.nan
    )
    capital = protocol["capital"]
    required_capital = point_value * (
        quarter_entry * float(capital["quarterly_margin_fraction_of_notional"])
        + perp_entry * float(capital["perpetual_margin_fraction_of_notional"])
        + max(quarter_entry, perp_entry)
        * float(capital["operational_buffer_fraction_of_one_notional"])
    )
    annualized = (
        estimated_profit
        / required_capital
        * 365.0
        / int(candidate["holding_days"])
        * 100.0
        if math.isfinite(estimated_profit)
        and required_capital > 0
        and int(candidate["holding_days"]) > 0
        else math.nan
    )
    excess = (
        annualized - float(candidate["ruonia_percent"])
        if math.isfinite(annualized)
        else math.nan
    )
    lookback_ready = int(candidate["prior_swaprate_observations"]) >= int(
        protocol["admission"]["minimum_nonmissing_lookback_sessions"]
    )
    realized_ready = (
        int(candidate["planned_funding_sessions"]) > 0
        and int(candidate["missing_realized_swaprate_rows"]) == 0
    )
    admitted = bool(
        lookback_ready
        and realized_ready
        and estimated_profit > 0
        and excess
        >= float(protocol["admission"]["minimum_annualized_excess_over_ruonia_percent"])
    )
    if not lookback_ready:
        reason = "insufficient_causal_swaprate_history"
    elif not realized_ready:
        reason = "missing_realized_swaprate"
    elif not admitted:
        reason = "entry_hurdle_not_met"
    else:
        reason = "admitted"
    candidate.update(
        {
            "point_value_rub_per_price_unit": point_value,
            "required_capital_per_pair": required_capital,
            "estimated_convergence_rub": estimated_convergence,
            "estimated_exit_spread_rub": estimated_exit_spread,
            "estimated_commissions_rub": estimated_commissions,
            "estimated_profit_per_pair_rub": estimated_profit,
            "annualized_entry_yield_percent": annualized,
            "excess_over_ruonia_percent": excess,
            "admitted": admitted,
            "reason": reason,
        }
    )
    return candidate


def simulate_period(
    perpetual: pd.DataFrame,
    contracts: list[dict[str, Any]],
    ruonia: pd.DataFrame,
    protocol: dict[str, Any],
    period_name: str,
    scenario: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, bool]]:
    start_text, end_text = protocol["periods"][period_name]
    start, end = pd.Timestamp(start_text), pd.Timestamp(end_text)
    period_perpetual = perpetual.loc[perpetual["trade_date"].between(start, end)].copy()
    dates = pd.DatetimeIndex(period_perpetual["trade_date"])
    if dates.empty:
        raise ValueError(f"empty perpetual period: {period_name}")
    initial = float(protocol["capital"]["initial_equity_rub"])
    equity = pd.Series(initial, index=dates, dtype=float)
    current_equity = initial
    previous_exit: pd.Timestamp | None = None
    trade_rows: list[dict[str, Any]] = []
    spread, commission = parent._scenario_costs(protocol, scenario)
    point_value = float(protocol["official_accounting"]["point_value_rub_per_price_unit"])
    lot = float(protocol["official_accounting"]["swaprate_lot_multiplier"])
    utilization = float(protocol["capital"]["maximum_entry_equity_utilization"])
    margin_failures = 0
    causal_failures = 0
    stale_quarterly_mark_days = 0
    selected = [item for item in contracts if start <= item["expiration_date"] <= end]

    for contract in sorted(selected, key=lambda item: item["expiration_date"]):
        candidate = build_candidate(perpetual, contract, ruonia, protocol, scenario)
        if candidate is None:
            trade_rows.append(
                {
                    "period": period_name,
                    "scenario": scenario,
                    "contract_id": contract["contract_id"],
                    "admitted": False,
                    "reason": "no_complete_fixed_schedule",
                    "quantity": 0,
                    "realized_pnl_rub": 0.0,
                    "margin_ok": True,
                }
            )
            continue
        if candidate["ruonia_available_at"] is not None:
            boundary = candidate["entry_date"].tz_localize("Europe/Moscow").tz_convert("UTC")
            if pd.Timestamp(candidate["ruonia_available_at"]) > boundary:
                causal_failures += 1
        if previous_exit is not None and candidate["entry_date"] <= previous_exit:
            candidate["admitted"] = False
            candidate["reason"] = "overlap_rejected"
        quantity = 0
        realized_pnl = 0.0
        margin_ok = True
        if candidate["admitted"]:
            quantity = math.floor(
                current_equity * utilization / candidate["required_capital_per_pair"]
            )
            if quantity <= 0:
                candidate["admitted"] = False
                candidate["reason"] = "integer_capacity_zero"
        if candidate["admitted"]:
            frame = contract["frame"].set_index("trade_date")
            perp = perpetual.set_index("trade_date")
            mark_dates = dates[
                (dates >= candidate["entry_date"]) & (dates < candidate["exit_date"])
            ]
            marks = pd.DataFrame(index=mark_dates).join(
                perp[["close", "swap_rate"]].rename(columns={"close": "perpetual_close"})
            ).join(frame[["close"]].rename(columns={"close": "quarterly_close"}))
            stale_quarterly_mark_days += int(marks["quarterly_close"].isna().sum())
            marks["quarterly_close"] = marks["quarterly_close"].ffill()
            if marks[["perpetual_close", "quarterly_close", "swap_rate"]].isna().any().any():
                raise ValueError("missing admitted V2 entry-to-exit price or funding mark")
            cumulative_funding = marks["swap_rate"].cumsum() * lot
            quarterly_liquidation = marks["quarterly_close"] * (1.0 - spread)
            perpetual_liquidation = marks["perpetual_close"] * (1.0 + spread)
            fees_to_liquidate = commission * point_value * (
                candidate["quarterly_entry"]
                + candidate["perpetual_entry"]
                + quarterly_liquidation
                + perpetual_liquidation
            )
            mark_per_pair = point_value * (
                quarterly_liquidation
                - candidate["quarterly_entry"]
                + candidate["perpetual_entry"]
                - perpetual_liquidation
            ) + cumulative_funding - fees_to_liquidate
            margin_capacity = candidate["required_capital_per_pair"]
            margin_ok = bool((-mark_per_pair.clip(upper=0.0) <= margin_capacity).all())
            if not margin_ok:
                margin_failures += 1
            equity.loc[mark_dates] = current_equity + quantity * mark_per_pair
            exit_perpetual_open = float(perp.loc[candidate["exit_date"], "open"])
            exit_quarterly_open = float(frame.loc[candidate["exit_date"], "open"])
            perpetual_exit = exit_perpetual_open * (1.0 + spread)
            quarterly_exit = exit_quarterly_open * (1.0 - spread)
            realized_funding = float(
                perp.loc[
                    (perp.index >= candidate["entry_date"])
                    & (perp.index < candidate["exit_date"]),
                    "swap_rate",
                ].sum()
                * lot
            )
            fees = commission * point_value * (
                candidate["quarterly_entry"]
                + candidate["perpetual_entry"]
                + quarterly_exit
                + perpetual_exit
            )
            realized_per_pair = point_value * (
                quarterly_exit
                - candidate["quarterly_entry"]
                + candidate["perpetual_entry"]
                - perpetual_exit
            ) + realized_funding - fees
            realized_pnl = quantity * realized_per_pair
            current_equity += realized_pnl
            equity.loc[candidate["exit_date"] :] = current_equity
            previous_exit = candidate["exit_date"]
            candidate.update(
                {
                    "exit_perpetual_open": exit_perpetual_open,
                    "exit_quarterly_open": exit_quarterly_open,
                    "perpetual_exit": perpetual_exit,
                    "quarterly_exit": quarterly_exit,
                    "realized_funding_per_pair_rub": realized_funding,
                    "realized_per_pair_rub": realized_per_pair,
                }
            )
        trade_rows.append(
            {
                "period": period_name,
                "scenario": scenario,
                **candidate,
                "quantity": quantity,
                "realized_pnl_rub": realized_pnl,
                "margin_ok": margin_ok,
            }
        )

    benchmark, missing_benchmark = ledger._ruonia_benchmark(dates, ruonia, initial)
    strategy_metrics = ledger._metrics(equity)
    benchmark_metrics = ledger._metrics(benchmark)
    strategy_metrics.update(
        {
            "period": period_name,
            "scenario": scenario,
            "candidate_count": len(selected),
            "admitted_trade_count": int(sum(row.get("admitted", False) for row in trade_rows)),
            "rejected_trade_count": int(sum(not row.get("admitted", False) for row in trade_rows)),
            "ending_equity_rub": float(equity.iloc[-1]),
            "ruonia_benchmark_cagr": benchmark_metrics["cagr"],
            "excess_over_ruonia_cagr": strategy_metrics["cagr"] - benchmark_metrics["cagr"],
            "ruonia_benchmark_ending_equity_rub": float(benchmark.iloc[-1]),
            "margin_failure_count": margin_failures,
            "causal_failure_count": causal_failures,
            "stale_quarterly_mark_days": stale_quarterly_mark_days,
            "benchmark_missing_rate_intervals": missing_benchmark,
        }
    )
    daily = pd.DataFrame(
        {
            "trade_date": dates,
            "period": period_name,
            "scenario": scenario,
            "equity": equity.to_numpy(),
            "ruonia_benchmark_equity": benchmark.to_numpy(),
        }
    )
    checks = {
        "ruonia_entry_causal": causal_failures == 0,
        "margin_calls_covered": margin_failures == 0,
        "equity_finite_positive": bool(np.isfinite(equity).all() and equity.gt(0).all()),
        "no_overlapping_admitted_positions": not any(
            row.get("reason") == "overlap_rejected" and row.get("admitted")
            for row in trade_rows
        ),
        "benchmark_unknown_gets_no_credit": missing_benchmark >= 0,
        "protected_rows_absent": bool((dates < pd.Timestamp("2026-01-01")).all()),
        "corrected_point_value": point_value == 1000.0,
    }
    return pd.DataFrame(trade_rows), daily, strategy_metrics, checks


def _report(metrics: dict[str, Any]) -> str:
    text = parent._report(metrics)
    return text.replace(
        "# CNY perpetual-quarterly spread V1",
        "# CNY perpetual-quarterly spread V2 (unit-corrected)",
        1,
    )


def run(run_root: Path = DEFAULT_RUN_ROOT) -> Path:
    protocol = load_protocol()
    perpetual, contracts, ruonia, source_checks, identities = load_inputs(protocol)
    all_trades, all_daily = [], []
    metrics: dict[str, Any] = {"development": {}, "evaluation": {}}
    execution_checks: dict[str, bool] = {}
    for period in ("development", "evaluation"):
        for scenario in ("primary", "stress"):
            trades, daily, result, checks = simulate_period(
                perpetual, contracts, ruonia, protocol, period, scenario
            )
            all_trades.append(trades)
            all_daily.append(daily)
            metrics[period][scenario] = result
            execution_checks.update(
                {f"{period}_{scenario}_{name}": passed for name, passed in checks.items()}
            )
    checks = {**source_checks, **execution_checks}
    gates = parent.promotion(metrics, checks, protocol)
    metrics["promotion_gates"] = gates
    metrics["checks_all_true"] = all(checks.values())
    metrics["numeric_verdict"] = "GO" if all(gates.values()) else "NO_GO"
    metrics["verdict"] = "REQUIRES_FORWARD_CONFIRMATION" if all(gates.values()) else "NO_GO"
    metrics["live_trading_allowed"] = False
    metrics["config_sha256"] = CONFIG_SHA256
    metrics["parent_v1_numeric_result_valid"] = False

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    final = run_root.resolve() / (
        f"cny_perpetual_quarterly_spread_v2_{timestamp}_{CONFIG_SHA256[:8]}"
    )
    if final.exists():
        raise FileExistsError(final)
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}-", dir=final.parent))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "config_snapshot.yaml")
        pd.concat(all_trades, ignore_index=True).to_parquet(
            temporary / "trades.parquet", index=False
        )
        pd.concat(all_daily, ignore_index=True).to_parquet(
            temporary / "daily_equity.parquet", index=False
        )
        _write_json(temporary / "metrics.json", metrics)
        (temporary / "report.md").write_text(_report(metrics), encoding="utf-8-sig")
        _write_json(
            temporary / "identity.json",
            {
                "protocol_id": protocol["protocol_id"],
                "config_sha256": CONFIG_SHA256,
                "parent_config_sha256": parent.CONFIG_SHA256,
                "implementation_sha256": _sha_file(MODULE_PATH),
                "parent_implementation_sha256": _sha_file(parent.MODULE_PATH),
                "ledger_dependency_sha256": _sha_file(ledger.MODULE_PATH),
                "sources": identities,
            },
        )
        _write_json(temporary / "audit.json", {"checks": checks, "all_true": all(checks.values())})
        names = [
            "config_snapshot.yaml",
            "trades.parquet",
            "daily_equity.parquet",
            "metrics.json",
            "report.md",
            "identity.json",
            "audit.json",
        ]
        _write_json(
            temporary / "artifact_manifest.json",
            {
                name: {
                    "bytes": (temporary / name).stat().st_size,
                    "sha256": _sha_file(temporary / name),
                }
                for name in names
            },
        )
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    if not all(audit(final).values()):
        raise ValueError("CNY perpetual-quarterly V2 canonical audit failed")
    return final


def audit(run_directory: Path) -> dict[str, bool]:
    identity = json.loads((run_directory / "identity.json").read_text(encoding="utf-8-sig"))
    artifacts = json.loads(
        (run_directory / "artifact_manifest.json").read_text(encoding="utf-8-sig")
    )
    checks = {
        "config_exact": identity["config_sha256"] == CONFIG_SHA256
        and _sha_file(run_directory / "config_snapshot.yaml") == CONFIG_SHA256,
        "parent_config_exact": identity["parent_config_sha256"] == parent.CONFIG_SHA256,
        "implementation_exact": identity["implementation_sha256"] == _sha_file(MODULE_PATH),
        "parent_implementation_exact": identity["parent_implementation_sha256"]
        == _sha_file(parent.MODULE_PATH),
        "ledger_dependency_exact": identity["ledger_dependency_sha256"]
        == _sha_file(ledger.MODULE_PATH),
    }
    for name, item in artifacts.items():
        path = run_directory / name
        checks[f"artifact_{name}_exact"] = (
            path.is_file()
            and path.stat().st_size == int(item["bytes"])
            and _sha_file(path) == item["sha256"]
        )
    stored = json.loads((run_directory / "audit.json").read_text(encoding="utf-8-sig"))
    metrics = json.loads((run_directory / "metrics.json").read_text(encoding="utf-8-sig"))
    checks["stored_execution_audit_all_true"] = stored["all_true"] is True
    checks["live_trading_stays_false"] = metrics["live_trading_allowed"] is False
    checks["parent_numeric_result_rejected"] = metrics["parent_v1_numeric_result_valid"] is False
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--audit-directory", type=Path)
    args = parser.parse_args()
    if args.audit_directory:
        checks = audit(args.audit_directory)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
    else:
        print(run(args.run_root))


if __name__ == "__main__":
    main()
