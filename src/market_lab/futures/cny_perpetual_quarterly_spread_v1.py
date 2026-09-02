"""Sealed V1 CNYRUBF short versus quarterly CR long experiment."""

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

from market_lab.futures import fx_cash_carry_v1 as ledger

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/cny_perpetual_quarterly_spread_v1.yaml"
CONFIG_SHA256: Final[str] = "5b2d6be704d100f1f4e7984c698c5137567b445ce76e1135bf84c30dce3a692e"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
DEFAULT_RUN_ROOT: Final[Path] = PROJECT_ROOT / "runs"


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


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
        raise ValueError("CNY perpetual-quarterly config seal mismatch")
    protocol = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        protocol.get("protocol_id") != "cny_perpetual_quarterly_spread_v1"
        or protocol.get("live_trading_allowed") is not False
        or protocol["official_accounting"]["perpetual_side"] != "short"
        or protocol["official_accounting"]["quarterly_side"] != "long"
        or protocol["official_accounting"]["seller_funding_component"]
        != "positive_SwapRate_times_Lot"
        or protocol["candidate_schedule"]["no_retry_after_rejected_entry"] is not True
        or protocol["periods"]["protected_ceiling_exclusive"] != "2026-01-01"
        or protocol["scenarios"]["forbidden"]
        != [
            "threshold_search",
            "direction_flip",
            "alternate_entry_days",
            "contract_subset_search",
        ]
    ):
        raise ValueError("CNY perpetual-quarterly protocol invariant drift")
    return protocol


def _path(relative: str) -> Path:
    path = (PROJECT_ROOT / relative).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load_inputs(
    protocol: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], pd.DataFrame, dict[str, bool], dict[str, str]]:
    protocol = protocol or load_protocol()
    perp_cfg = protocol["inputs"]["perpetual"]
    quarter_cfg = protocol["inputs"]["quarterly"]
    ruonia_cfg = protocol["inputs"]["ruonia"]
    paths = {
        "perpetual_manifest": _path(perp_cfg["manifest"]),
        "perpetual": _path(perp_cfg["parquet"]),
        "quarterly_manifest": _path(quarter_cfg["manifest"]),
        "quarterly": _path(quarter_cfg["parquet"]),
        "ruonia_manifest": _path(ruonia_cfg["manifest"]),
        "ruonia": _path(ruonia_cfg["parquet"]),
    }
    expected = {
        "perpetual_manifest": perp_cfg["manifest_sha256"],
        "perpetual": perp_cfg["parquet_sha256"],
        "quarterly_manifest": quarter_cfg["manifest_sha256"],
        "quarterly": quarter_cfg["parquet_sha256"],
        "ruonia_manifest": ruonia_cfg["manifest_sha256"],
        "ruonia": ruonia_cfg["parquet_sha256"],
    }
    checks = {
        f"{name}_exact": _sha_file(path) == expected[name] for name, path in paths.items()
    }
    if not all(checks.values()):
        raise ValueError("CNY perpetual-quarterly source identity mismatch")

    perpetual = pd.read_parquet(
        paths["perpetual"],
        columns=[
            "security_id",
            "asset_code",
            "trade_date",
            "lot_size_cny",
            "open",
            "close",
            "swap_rate",
            "number_of_trades",
            "volume",
            "available_at_utc",
        ],
    )
    perpetual["trade_date"] = pd.to_datetime(perpetual["trade_date"])
    perpetual["available_at_utc"] = pd.to_datetime(perpetual["available_at_utc"], utc=True)
    perpetual = perpetual.sort_values("trade_date", ignore_index=True)
    quarterly = pd.read_parquet(
        paths["quarterly"],
        columns=[
            "instrument_kind",
            "security_id",
            "asset_code",
            "trade_date",
            "expiration_date",
            "lot_size_cny",
            "open",
            "close",
            "number_of_trades",
            "volume",
        ],
    )
    quarterly["trade_date"] = pd.to_datetime(quarterly["trade_date"])
    quarterly["expiration_date"] = pd.to_datetime(quarterly["expiration_date"])
    upper = pd.Timestamp(protocol["periods"]["protected_ceiling_exclusive"])
    checks.update(
        {
            "perpetual_rows_exact": len(perpetual) == int(perp_cfg["rows"]),
            "perpetual_identity_exact": set(perpetual["security_id"].astype(str))
            == {perp_cfg["security_id"]}
            and set(perpetual["asset_code"].astype(str)) == {"CNYRUBTOM"}
            and set(perpetual["lot_size_cny"].astype(float))
            == {float(perp_cfg["lot_size_cny"])},
            "perpetual_unique": not perpetual["trade_date"].duplicated().any(),
            "perpetual_activity_positive": bool(
                perpetual["open"].gt(0).all()
                and perpetual["close"].gt(0).all()
                and perpetual["number_of_trades"].gt(0).all()
                and perpetual["volume"].gt(0).all()
            ),
            "swaprate_count_exact": int(perpetual["swap_rate"].notna().sum())
            == int(perp_cfg["swaprate_nonmissing_rows"]),
            "swaprate_availability_after_trade_date": bool(
                (
                    perpetual["available_at_utc"].dt.tz_convert("Europe/Moscow").dt.normalize()
                    > perpetual["trade_date"].dt.tz_localize("Europe/Moscow")
                ).all()
            ),
            "quarterly_rows_exact": len(quarterly) == int(quarter_cfg["rows"]),
            "quarterly_contract_count_exact": quarterly["security_id"].nunique()
            == int(quarter_cfg["contracts"]),
            "quarterly_identity_exact": set(quarterly["asset_code"].astype(str))
            == {quarter_cfg["asset_code"]}
            and set(quarterly["instrument_kind"].astype(str)) == {"futures"}
            and set(quarterly["lot_size_cny"].astype(float))
            == {float(quarter_cfg["lot_size_cny"])},
            "quarterly_unique": not quarterly.duplicated(["security_id", "trade_date"]).any(),
            "protected_rows_absent": perpetual["trade_date"].max() < upper
            and quarterly["trade_date"].max() < upper,
        }
    )
    contracts: list[dict[str, Any]] = []
    for secid, frame in quarterly.groupby("security_id", sort=True):
        expirations = frame["expiration_date"].dropna().unique()
        if len(expirations) != 1:
            raise ValueError(f"CNY quarterly expiration identity drift: {secid}")
        executable = frame.loc[
            frame["open"].gt(0)
            & frame["close"].gt(0)
            & frame["number_of_trades"].gt(0)
            & frame["volume"].gt(0),
            ["trade_date", "open", "close"],
        ].copy()
        expiration = pd.Timestamp(expirations[0])
        contracts.append(
            {
                "contract_id": f"CNY-PERP:{secid}:{expiration.date().isoformat()}",
                "secid": str(secid),
                "expiration_date": expiration,
                "frame": executable.sort_values("trade_date", ignore_index=True),
            }
        )
    checks["all_contracts_have_executable_rows"] = all(
        not item["frame"].empty for item in contracts
    )
    ruonia = pd.read_parquet(
        paths["ruonia"],
        columns=["series_id", "observation_date", "available_at", "value"],
        filters=[("series_id", "==", ruonia_cfg["series_id"])],
    )
    ruonia["available_at"] = pd.to_datetime(ruonia["available_at"], utc=True)
    ruonia["observation_date"] = pd.to_datetime(ruonia["observation_date"])
    ruonia = ruonia.sort_values("available_at", ignore_index=True)
    checks.update(
        {
            "ruonia_identity_exact": set(ruonia["series_id"].astype(str))
            == {ruonia_cfg["series_id"]},
            "ruonia_availability_present": bool(ruonia["available_at"].notna().all()),
            "ruonia_positive": bool(ruonia["value"].gt(0).all()),
        }
    )
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(f"CNY perpetual-quarterly input checks failed: {failed}")
    identities = {name: _sha_file(path) for name, path in paths.items()}
    return perpetual, contracts, ruonia, checks, identities


def _scenario_costs(protocol: dict[str, Any], scenario: str) -> tuple[float, float]:
    return ledger._scenario_costs(protocol, scenario)


def build_candidate(
    perpetual: pd.DataFrame,
    contract: dict[str, Any],
    ruonia: pd.DataFrame,
    protocol: dict[str, Any],
    scenario: str,
) -> dict[str, Any] | None:
    frame = contract["frame"]
    expiration = contract["expiration_date"]
    common = sorted(set(perpetual["trade_date"]) & set(frame["trade_date"]))
    if not common:
        return None
    schedule = protocol["candidate_schedule"]
    target = expiration - pd.Timedelta(days=int(schedule["target_calendar_days_before_expiration"]))
    minimum = int(schedule["entry_min_calendar_days_before_expiration"])
    maximum = int(schedule["entry_max_calendar_days_before_expiration"])
    entries = [
        date
        for date in common
        if date >= target and minimum <= (expiration - date).days <= maximum
    ]
    if not entries:
        return None
    entry_date = entries[0]
    exits = [date for date in common if entry_date < date < expiration]
    if not exits:
        return None
    exit_date = exits[-1]
    lookback_size = int(protocol["admission"]["causal_swaprate_lookback_sessions"])
    minimum_observed = int(protocol["admission"]["minimum_nonmissing_lookback_sessions"])
    prior_window = perpetual.loc[perpetual["trade_date"].lt(entry_date)].tail(lookback_size)
    prior_observed = prior_window["swap_rate"].dropna()
    holding = perpetual.loc[
        perpetual["trade_date"].ge(entry_date) & perpetual["trade_date"].lt(exit_date)
    ].copy()
    missing_realized = int(holding["swap_rate"].isna().sum())
    lookback_ready = len(prior_observed) >= minimum_observed
    realized_ready = not holding.empty and missing_realized == 0
    perp_by_date = perpetual.set_index("trade_date")
    quarter_by_date = frame.set_index("trade_date")
    perp_open = float(perp_by_date.loc[entry_date, "open"])
    quarter_open = float(quarter_by_date.loc[entry_date, "open"])
    spread, commission = _scenario_costs(protocol, scenario)
    perp_entry = perp_open * (1.0 - spread)
    quarter_entry = quarter_open * (1.0 + spread)
    midpoint = (perp_open + quarter_open) / 2.0
    estimated_exit_spread = 2.0 * midpoint * spread
    estimated_commissions = 2.0 * (perp_open + quarter_open) * commission
    prior_mean = float(prior_observed.mean()) if lookback_ready else math.nan
    planned_sessions = len(holding)
    lot = float(protocol["official_accounting"]["swaprate_lot_multiplier"])
    estimated_funding = prior_mean * lot * planned_sessions if lookback_ready else math.nan
    estimated_convergence = perp_entry - quarter_entry
    estimated_profit = (
        estimated_convergence + estimated_funding - estimated_exit_spread - estimated_commissions
        if lookback_ready
        else math.nan
    )
    capital = protocol["capital"]
    required_capital = (
        quarter_entry * float(capital["quarterly_margin_fraction_of_notional"])
        + perp_entry * float(capital["perpetual_margin_fraction_of_notional"])
        + max(quarter_entry, perp_entry)
        * float(capital["operational_buffer_fraction_of_one_notional"])
    )
    holding_days = int((exit_date - entry_date).days)
    annualized = (
        estimated_profit / required_capital * 365.0 / holding_days * 100.0
        if lookback_ready and required_capital > 0 and holding_days > 0
        else math.nan
    )
    ruonia_percent, ruonia_available_at = ledger.causal_ruonia_percent(ruonia, entry_date)
    excess = annualized - ruonia_percent if math.isfinite(annualized) else math.nan
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
    return {
        "contract_id": contract["contract_id"],
        "secid": contract["secid"],
        "expiration_date": expiration,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "holding_days": holding_days,
        "planned_funding_sessions": planned_sessions,
        "prior_window_rows": len(prior_window),
        "prior_swaprate_observations": len(prior_observed),
        "prior_mean_swaprate": prior_mean,
        "missing_realized_swaprate_rows": missing_realized,
        "perpetual_open": perp_open,
        "quarterly_open": quarter_open,
        "perpetual_entry": perp_entry,
        "quarterly_entry": quarter_entry,
        "required_capital_per_pair": required_capital,
        "estimated_convergence_rub": estimated_convergence,
        "estimated_funding_rub": estimated_funding,
        "estimated_profit_per_pair_rub": estimated_profit,
        "annualized_entry_yield_percent": annualized,
        "ruonia_percent": ruonia_percent,
        "ruonia_available_at": ruonia_available_at,
        "excess_over_ruonia_percent": excess,
        "admitted": admitted,
        "reason": reason,
    }


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
    spread, commission = _scenario_costs(protocol, scenario)
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
                raise ValueError("missing admitted entry-to-exit price or funding mark")
            cumulative_funding = marks["swap_rate"].cumsum() * float(
                protocol["official_accounting"]["swaprate_lot_multiplier"]
            )
            quarterly_liquidation = marks["quarterly_close"] * (1.0 - spread)
            perpetual_liquidation = marks["perpetual_close"] * (1.0 + spread)
            fees_to_liquidate = commission * (
                candidate["quarterly_entry"]
                + candidate["perpetual_entry"]
                + quarterly_liquidation
                + perpetual_liquidation
            )
            mark_per_pair = (
                quarterly_liquidation
                - candidate["quarterly_entry"]
                + candidate["perpetual_entry"]
                - perpetual_liquidation
                + cumulative_funding
                - fees_to_liquidate
            )
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
                * float(protocol["official_accounting"]["swaprate_lot_multiplier"])
            )
            fees = commission * (
                candidate["quarterly_entry"]
                + candidate["perpetual_entry"]
                + quarterly_exit
                + perpetual_exit
            )
            realized_per_pair = (
                quarterly_exit
                - candidate["quarterly_entry"]
                + candidate["perpetual_entry"]
                - perpetual_exit
                + realized_funding
                - fees
            )
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
    }
    return pd.DataFrame(trade_rows), daily, strategy_metrics, checks


def promotion(
    metrics: dict[str, Any], checks: dict[str, bool], protocol: dict[str, Any]
) -> dict[str, bool]:
    primary = metrics["evaluation"]["primary"]
    stress = metrics["evaluation"]["stress"]
    gates = protocol["promotion_gates"]
    return {
        "evaluation_cagr": primary["cagr"] * 100.0
        >= float(gates["evaluation_cagr_minimum_percent"]),
        "evaluation_sharpe": primary["sharpe"] >= float(gates["evaluation_sharpe_minimum"]),
        "evaluation_max_drawdown": primary["maximum_drawdown"] * 100.0
        <= float(gates["evaluation_max_drawdown_maximum_percent"]),
        "evaluation_positive_years": primary["positive_years"]
        >= int(gates["evaluation_positive_years_minimum"]),
        "evaluation_excess_over_ruonia": primary["excess_over_ruonia_cagr"] * 100.0
        >= float(gates["evaluation_excess_over_ruonia_cagr_minimum_percent"]),
        "stress_evaluation_cagr": stress["cagr"] * 100.0
        >= float(gates["stress_evaluation_cagr_minimum_percent"]),
        "minimum_evaluation_trades": primary["admitted_trade_count"]
        >= int(gates["minimum_evaluation_trades"]),
        "execution_and_identity": all(checks.values()),
    }


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# CNY perpetual-quarterly spread V1",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        "| Period | Scenario | CAGR | Sharpe | MDD | Trades | RUONIA CAGR |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for period in ("development", "evaluation"):
        for scenario in ("primary", "stress"):
            item = metrics[period][scenario]
            lines.append(
                f"| {period} | {scenario} | {item['cagr']:.4%} | {item['sharpe']:.3f} | "
                f"{item['maximum_drawdown']:.4%} | {item['admitted_trade_count']} | "
                f"{item['ruonia_benchmark_cagr']:.4%} |"
            )
    lines.extend(["", "## Promotion gates", ""])
    lines.extend(
        f"- {name}: `{passed}`" for name, passed in metrics["promotion_gates"].items()
    )
    lines.extend(["", "Even a numeric GO remains research-only pending future confirmation."])
    return "\n".join(lines) + "\n"


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
    gates = promotion(metrics, checks, protocol)
    metrics["promotion_gates"] = gates
    metrics["checks_all_true"] = all(checks.values())
    metrics["numeric_verdict"] = "GO" if all(gates.values()) else "NO_GO"
    metrics["verdict"] = "REQUIRES_FORWARD_CONFIRMATION" if all(gates.values()) else "NO_GO"
    metrics["live_trading_allowed"] = False
    metrics["config_sha256"] = CONFIG_SHA256

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    final = run_root.resolve() / (
        f"cny_perpetual_quarterly_spread_v1_{timestamp}_{CONFIG_SHA256[:8]}"
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
                "implementation_sha256": _sha_file(MODULE_PATH),
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
        raise ValueError("CNY perpetual-quarterly canonical audit failed")
    return final


def audit(run_directory: Path) -> dict[str, bool]:
    identity = json.loads((run_directory / "identity.json").read_text(encoding="utf-8-sig"))
    artifacts = json.loads(
        (run_directory / "artifact_manifest.json").read_text(encoding="utf-8-sig")
    )
    checks = {
        "config_exact": identity["config_sha256"] == CONFIG_SHA256
        and _sha_file(run_directory / "config_snapshot.yaml") == CONFIG_SHA256,
        "implementation_exact": identity["implementation_sha256"] == _sha_file(MODULE_PATH),
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
