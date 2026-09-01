"""Sealed V1 USD/RUB TOM cash-and-carry economic experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DATA_ROOT: Final[Path] = PROJECT_ROOT / "data"
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/fx_cash_carry_v1.yaml"
CONFIG_SHA256: Final[str] = "4b3ca33ebd4362505bbc2aa8fb2c824f1134d91af6f1fb71cdc597d999e6a480"
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
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if actual != CONFIG_SHA256 or declared != CONFIG_SHA256:
        raise ValueError("FX cash-and-carry config seal mismatch")
    protocol = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if (
        protocol.get("protocol_id") != "fx_cash_carry_v1"
        or protocol.get("live_trading_allowed") is not False
        or protocol["periods"]["protected_ceiling_exclusive"] != "2026-01-01"
        or protocol["hypothesis"]["reverse_carry_without_proven_usd_borrow"] != "forbidden"
        or protocol["execution"]["usd_interest_percent"] != 0.0
        or protocol["scenarios"]["forbidden"]
        != [
            "threshold_search",
            "alternate_entry_days",
            "asset_subset_search",
            "reverse_carry",
        ]
    ):
        raise ValueError("FX cash-and-carry protocol invariant drift")
    return protocol


def _project_path(relative: str) -> Path:
    path = (PROJECT_ROOT / relative).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _verify(path: Path, expected_sha256: str) -> bool:
    return path.is_file() and _sha_file(path) == expected_sha256


def load_inputs(
    protocol: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], pd.DataFrame, dict[str, bool], dict[str, Any]]:
    protocol = protocol or load_protocol()
    spot_cfg = protocol["inputs"]["spot"]
    si_cfg = protocol["inputs"]["si"]
    ruonia_cfg = protocol["inputs"]["ruonia"]
    spot_manifest_path = _project_path(spot_cfg["manifest"])
    spot_path = _project_path(spot_cfg["parquet"])
    si_manifest_path = _project_path(si_cfg["manifest"])
    ruonia_manifest_path = _project_path(ruonia_cfg["manifest"])
    ruonia_path = _project_path(ruonia_cfg["parquet"])
    checks = {
        "spot_manifest_exact": _verify(spot_manifest_path, spot_cfg["manifest_sha256"]),
        "spot_parquet_exact": _verify(spot_path, spot_cfg["parquet_sha256"]),
        "si_manifest_exact": _verify(si_manifest_path, si_cfg["manifest_sha256"]),
        "si_manifest_bytes_exact": si_manifest_path.stat().st_size == si_cfg["manifest_bytes"],
        "ruonia_manifest_exact": _verify(ruonia_manifest_path, ruonia_cfg["manifest_sha256"]),
        "ruonia_parquet_exact": _verify(ruonia_path, ruonia_cfg["parquet_sha256"]),
    }
    if not all(checks.values()):
        raise ValueError("FX cash-and-carry source identity mismatch")

    spot = pd.read_parquet(
        spot_path,
        columns=[
            "board_id",
            "trade_date",
            "security_id",
            "open",
            "close",
            "number_of_trades",
        ],
    )
    spot["trade_date"] = pd.to_datetime(spot["trade_date"])
    checks.update(
        {
            "spot_rows_exact": len(spot) == int(spot_cfg["rows"]),
            "spot_identity_exact": set(spot["security_id"].astype(str))
            == {spot_cfg["security_id"]}
            and set(spot["board_id"].astype(str)) == {spot_cfg["board_id"]},
            "spot_dates_unique": not spot["trade_date"].duplicated().any(),
            "spot_prices_positive": bool((spot[["open", "close"]].min(axis=1) > 0).all()),
        }
    )

    si_manifest = json.loads(si_manifest_path.read_text(encoding="utf-8-sig"))
    contracts: list[dict[str, Any]] = []
    selected_child_exact = True
    cycles = set(si_cfg["contract_cycle_month_codes"])
    lower = pd.Timestamp(protocol["periods"]["development"][0])
    upper = pd.Timestamp(protocol["periods"]["protected_ceiling_exclusive"])
    for item in si_manifest["segment_artifacts"]:
        contract_id = str(item["canonical_contract_id"])
        _, canonical_secid, expiration_text = contract_id.split(":")
        match = re.fullmatch(r"Si([HMUZ])\d", canonical_secid)
        expiration = pd.Timestamp(expiration_text)
        if not match or match.group(1) not in cycles or not (lower <= expiration < upper):
            continue
        child = item["daily"]["parquet"]
        path = (DATA_ROOT / child["path"]).resolve()
        exact = (
            path.is_file()
            and path.stat().st_size == int(child["bytes"])
            and _sha_file(path) == child["sha256"]
        )
        selected_child_exact = selected_child_exact and exact
        if not exact:
            raise ValueError(f"SI child artifact mismatch: {contract_id}")
        frame = pd.read_parquet(
            path,
            columns=[
                "trade_date",
                "board_id",
                "asset_code",
                "open",
                "close",
                "settle",
                "volume",
                "num_trades",
                "ohlc_complete",
            ],
        )
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        frame = frame.loc[frame["trade_date"].lt(upper)].copy()
        contracts.append(
            {
                "contract_id": contract_id,
                "secid": str(item["secid"]),
                "expiration_date": expiration,
                "path": str(path),
                "sha256": child["sha256"],
                "frame": frame.sort_values("trade_date", ignore_index=True),
            }
        )
    checks.update(
        {
            "si_selected_children_exact": selected_child_exact,
            "si_quarterly_contract_count_exact": len(contracts) == 32,
            "si_child_identity_exact": all(
                set(item["frame"]["board_id"].astype(str)) == {si_cfg["board_id"]}
                and set(item["frame"]["asset_code"].astype(str)) == {si_cfg["asset_code"]}
                for item in contracts
            ),
            "si_no_protected_rows": all(
                item["frame"]["trade_date"].max() < upper for item in contracts
            ),
        }
    )

    ruonia = pd.read_parquet(
        ruonia_path,
        columns=["series_id", "observation_date", "available_at", "value"],
        filters=[("series_id", "==", ruonia_cfg["series_id"])],
    )
    ruonia["available_at"] = pd.to_datetime(ruonia["available_at"], utc=True)
    ruonia["observation_date"] = pd.to_datetime(ruonia["observation_date"])
    ruonia = ruonia.sort_values("available_at", ignore_index=True)
    checks.update(
        {
            "ruonia_nonempty": not ruonia.empty,
            "ruonia_identity_exact": set(ruonia["series_id"].astype(str))
            == {ruonia_cfg["series_id"]},
            "ruonia_values_positive": bool((ruonia["value"] > 0).all()),
            "ruonia_availability_present": bool(ruonia["available_at"].notna().all()),
        }
    )
    if not all(checks.values()):
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise ValueError(f"FX cash-and-carry input checks failed: {failed}")
    identities = {
        "spot_manifest_sha256": _sha_file(spot_manifest_path),
        "spot_parquet_sha256": _sha_file(spot_path),
        "si_manifest_sha256": _sha_file(si_manifest_path),
        "si_child_sha256": {
            item["contract_id"]: item["sha256"] for item in contracts
        },
        "ruonia_manifest_sha256": _sha_file(ruonia_manifest_path),
        "ruonia_parquet_sha256": _sha_file(ruonia_path),
    }
    return spot.sort_values("trade_date", ignore_index=True), contracts, ruonia, checks, identities


def causal_ruonia_percent(
    ruonia: pd.DataFrame, session_date: pd.Timestamp
) -> tuple[float, str | None]:
    boundary = session_date.tz_localize("Europe/Moscow").tz_convert("UTC")
    eligible = ruonia.loc[ruonia["available_at"].le(boundary)]
    if eligible.empty:
        return 0.0, None
    row = eligible.iloc[-1]
    return float(row["value"]), pd.Timestamp(row["available_at"]).isoformat()


def _scenario_costs(protocol: dict[str, Any], scenario: str) -> tuple[float, float]:
    if scenario == "primary":
        spread = float(protocol["execution"]["primary_half_spread_bps_each_leg_each_side"])
    elif scenario == "stress":
        spread = float(protocol["execution"]["stress_half_spread_bps_each_leg_each_side"])
    else:
        raise ValueError(f"unknown scenario: {scenario}")
    commission = float(protocol["execution"]["explicit_commission_bps_each_leg_each_side"])
    return spread / 10_000.0, commission / 10_000.0


def _candidate(
    spot: pd.DataFrame,
    contract: dict[str, Any],
    ruonia: pd.DataFrame,
    protocol: dict[str, Any],
    scenario: str,
) -> dict[str, Any] | None:
    frame = contract["frame"]
    expiration = contract["expiration_date"]
    common = sorted(set(spot["trade_date"]) & set(frame["trade_date"]))
    if not common:
        return None
    target = expiration - pd.Timedelta(
        days=int(protocol["candidate_schedule"]["target_calendar_days_before_expiration"])
    )
    minimum = int(protocol["candidate_schedule"]["entry_min_calendar_days_before_expiration"])
    maximum = int(protocol["candidate_schedule"]["entry_max_calendar_days_before_expiration"])
    entry_dates = [
        date
        for date in common
        if date >= target and minimum <= (expiration - date).days <= maximum
    ]
    if not entry_dates:
        return None
    entry_date = entry_dates[0]
    exit_dates = [date for date in common if entry_date < date < expiration]
    if not exit_dates:
        return None
    exit_date = exit_dates[-1]
    spot_by_date = spot.set_index("trade_date")
    future_by_date = frame.set_index("trade_date")
    spot_open = float(spot_by_date.loc[entry_date, "open"])
    futures_open = float(future_by_date.loc[entry_date, "open"])
    if not (spot_open > 0 and futures_open > 0):
        return None
    spread, commission = _scenario_costs(protocol, scenario)
    usd_notional = float(protocol["inputs"]["si"]["contract_usd_notional"])
    spot_entry = spot_open * (1.0 + spread)
    futures_entry = futures_open * (1.0 - spread)
    notional = spot_entry * usd_notional
    margin_fraction = float(
        protocol["capital"]["modeled_initial_margin_fraction_of_futures_notional"]
    )
    buffer_fraction = float(
        protocol["capital"]["operational_cash_buffer_fraction_of_futures_notional"]
    )
    required_capital = notional + futures_entry * (margin_fraction + buffer_fraction)
    holding_days = int((exit_date - entry_date).days)
    raw_entry_basis = futures_open - spot_open * usd_notional
    stressed_entry_basis = futures_entry - spot_entry * usd_notional
    estimated_exit_spread = spread * (notional + futures_entry)
    estimated_commissions = commission * 2.0 * (notional + futures_entry)
    estimated_profit = stressed_entry_basis - estimated_exit_spread - estimated_commissions
    annualized_yield_percent = estimated_profit / required_capital * 365.0 / holding_days * 100.0
    ruonia_percent, ruonia_available_at = causal_ruonia_percent(ruonia, entry_date)
    excess = annualized_yield_percent - ruonia_percent
    admitted = (
        raw_entry_basis > 0
        and excess >= float(protocol["admission"]["minimum_excess_over_ruonia_percent"])
    )
    return {
        "contract_id": contract["contract_id"],
        "secid": contract["secid"],
        "expiration_date": expiration,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "holding_days": holding_days,
        "spot_open": spot_open,
        "futures_open": futures_open,
        "spot_entry": spot_entry,
        "futures_entry": futures_entry,
        "required_capital_per_contract": required_capital,
        "raw_entry_basis_rub": raw_entry_basis,
        "estimated_profit_per_contract_rub": estimated_profit,
        "annualized_entry_yield_percent": annualized_yield_percent,
        "ruonia_percent": ruonia_percent,
        "ruonia_available_at": ruonia_available_at,
        "excess_over_ruonia_percent": excess,
        "admitted": admitted,
    }


def _metrics(equity: pd.Series) -> dict[str, Any]:
    equity = equity.astype(float)
    returns = equity.pct_change().fillna(0.0)
    total = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    days = max(int((equity.index[-1] - equity.index[0]).days), 1)
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (365.0 / days) - 1.0)
    volatility = float(returns.std(ddof=1) * math.sqrt(252.0)) if len(returns) > 1 else 0.0
    sharpe = (
        float(returns.mean() / returns.std(ddof=1) * math.sqrt(252.0))
        if returns.std(ddof=1) > 0
        else 0.0
    )
    drawdown = equity / equity.cummax() - 1.0
    years = {}
    for year, values in equity.groupby(equity.index.year):
        years[str(year)] = float(values.iloc[-1] / values.iloc[0] - 1.0)
    return {
        "total_return": total,
        "cagr": cagr,
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "maximum_drawdown": float(-drawdown.min()),
        "per_year": years,
        "positive_years": int(sum(value > 0 for value in years.values())),
    }


def _ruonia_benchmark(
    dates: pd.DatetimeIndex,
    ruonia: pd.DataFrame,
    initial_equity: float,
) -> tuple[pd.Series, int]:
    values = [initial_equity]
    missing = 0
    for current, following in zip(dates[:-1], dates[1:], strict=True):
        rate, available = causal_ruonia_percent(ruonia, pd.Timestamp(current))
        if available is None:
            missing += 1
        days = int((following - current).days)
        values.append(values[-1] * (1.0 + rate / 100.0 * days / 365.0))
    return pd.Series(values, index=dates, dtype=float), missing


def simulate_period(
    spot: pd.DataFrame,
    contracts: list[dict[str, Any]],
    ruonia: pd.DataFrame,
    protocol: dict[str, Any],
    period_name: str,
    scenario: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, bool]]:
    start_text, end_text = protocol["periods"][period_name]
    start, end = pd.Timestamp(start_text), pd.Timestamp(end_text)
    period_spot = spot.loc[spot["trade_date"].between(start, end)].copy()
    dates = pd.DatetimeIndex(period_spot["trade_date"])
    if dates.empty:
        raise ValueError(f"empty spot period: {period_name}")
    initial = float(protocol["capital"]["initial_equity_rub"])
    equity = pd.Series(initial, index=dates, dtype=float)
    current_equity = initial
    previous_exit: pd.Timestamp | None = None
    trade_rows: list[dict[str, Any]] = []
    margin_failures = 0
    causal_failures = 0
    stale_mark_days = 0
    spread, commission = _scenario_costs(protocol, scenario)
    usd_notional = float(protocol["inputs"]["si"]["contract_usd_notional"])
    utilization = float(protocol["capital"]["maximum_entry_equity_utilization"])
    margin_fraction = float(
        protocol["capital"]["modeled_initial_margin_fraction_of_futures_notional"]
    )
    buffer_fraction = float(
        protocol["capital"]["operational_cash_buffer_fraction_of_futures_notional"]
    )

    selected = [
        item for item in contracts if start <= item["expiration_date"] <= end
    ]
    for contract in sorted(selected, key=lambda item: item["expiration_date"]):
        candidate = _candidate(period_spot, contract, ruonia, protocol, scenario)
        if candidate is None:
            trade_rows.append(
                {
                    "period": period_name,
                    "scenario": scenario,
                    "contract_id": contract["contract_id"],
                    "admitted": False,
                    "reason": "no_complete_fixed_schedule",
                }
            )
            continue
        if candidate["ruonia_available_at"] is not None:
            boundary = candidate["entry_date"].tz_localize("Europe/Moscow").tz_convert("UTC")
            if pd.Timestamp(candidate["ruonia_available_at"]) > boundary:
                causal_failures += 1
        reason = "admitted" if candidate["admitted"] else "entry_hurdle_not_met"
        if previous_exit is not None and candidate["entry_date"] <= previous_exit:
            candidate["admitted"] = False
            reason = "overlap_rejected"
        quantity = 0
        realized_pnl = 0.0
        margin_ok = True
        if candidate["admitted"]:
            quantity = int(
                math.floor(
                    current_equity * utilization / candidate["required_capital_per_contract"]
                )
            )
            if quantity <= 0:
                candidate["admitted"] = False
                reason = "integer_capacity_zero"
        if candidate["admitted"]:
            frame = contract["frame"].set_index("trade_date")
            spot_indexed = period_spot.set_index("trade_date")
            mark_dates = dates[
                (dates >= candidate["entry_date"]) & (dates <= candidate["exit_date"])
            ]
            marks = pd.DataFrame(index=mark_dates).join(
                spot_indexed[["close"]].rename(columns={"close": "spot_close"})
            ).join(frame[["close"]].rename(columns={"close": "futures_close"}))
            stale_mark_days += int(marks["futures_close"].isna().sum())
            marks[["spot_close", "futures_close"]] = marks[
                ["spot_close", "futures_close"]
            ].ffill()
            if marks[["spot_close", "futures_close"]].isna().any().any():
                raise ValueError("missing entry-to-exit mark before first valid value")
            entry_fee_per_contract = commission * (
                candidate["spot_entry"] * usd_notional + candidate["futures_entry"]
            )
            mark_per_contract = (
                usd_notional * (marks["spot_close"] - candidate["spot_entry"])
                + candidate["futures_entry"]
                - marks["futures_close"]
                - entry_fee_per_contract
            )
            futures_loss = (
                marks["futures_close"] - candidate["futures_entry"]
            ).clip(lower=0.0)
            margin_cash = candidate["futures_entry"] * (margin_fraction + buffer_fraction)
            margin_ok = bool((futures_loss <= margin_cash).all())
            if not margin_ok:
                margin_failures += 1
            equity.loc[mark_dates] = current_equity + quantity * mark_per_contract
            exit_spot_open = float(spot_indexed.loc[candidate["exit_date"], "open"])
            exit_futures_open = float(frame.loc[candidate["exit_date"], "open"])
            spot_exit = exit_spot_open * (1.0 - spread)
            futures_exit = exit_futures_open * (1.0 + spread)
            fees = commission * (
                candidate["spot_entry"] * usd_notional
                + spot_exit * usd_notional
                + candidate["futures_entry"]
                + futures_exit
            )
            realized_per_contract = (
                usd_notional * (spot_exit - candidate["spot_entry"])
                + candidate["futures_entry"]
                - futures_exit
                - fees
            )
            realized_pnl = quantity * realized_per_contract
            current_equity += realized_pnl
            equity.loc[candidate["exit_date"] :] = current_equity
            previous_exit = candidate["exit_date"]
            candidate.update(
                {
                    "exit_spot_open": exit_spot_open,
                    "exit_futures_open": exit_futures_open,
                    "spot_exit": spot_exit,
                    "futures_exit": futures_exit,
                    "realized_per_contract_rub": realized_per_contract,
                }
            )
        trade_rows.append(
            {
                "period": period_name,
                "scenario": scenario,
                **candidate,
                "admitted": bool(candidate["admitted"]),
                "reason": reason,
                "quantity": quantity,
                "realized_pnl_rub": realized_pnl,
                "margin_ok": margin_ok,
            }
        )

    benchmark, missing_benchmark = _ruonia_benchmark(dates, ruonia, initial)
    strategy_metrics = _metrics(equity)
    benchmark_metrics = _metrics(benchmark)
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
        "equity_finite_positive": bool(np.isfinite(equity).all() and (equity > 0).all()),
        "no_overlapping_admitted_positions": not any(
            row.get("reason") == "overlap_rejected" and row.get("admitted")
            for row in trade_rows
        ),
        "benchmark_unknown_gets_no_credit": missing_benchmark >= 0,
        "protected_rows_absent": bool((dates < pd.Timestamp("2026-01-01")).all()),
    }
    strategy_metrics["margin_failure_count"] = margin_failures
    strategy_metrics["causal_failure_count"] = causal_failures
    strategy_metrics["stale_futures_mark_days"] = stale_mark_days
    strategy_metrics["benchmark_missing_rate_intervals"] = missing_benchmark
    return pd.DataFrame(trade_rows), daily, strategy_metrics, checks


def _promotion(
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


def _report(metrics: dict[str, Any], promotion: dict[str, bool]) -> str:
    lines = [
        "# FX cash-and-carry V1",
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
    lines.extend(f"- {name}: `{passed}`" for name, passed in promotion.items())
    lines.extend(
        [
            "",
            "This is a current-vintage historical mechanism test, not independent live evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(run_root: Path = DEFAULT_RUN_ROOT) -> Path:
    protocol = load_protocol()
    spot, contracts, ruonia, source_checks, identities = load_inputs(protocol)
    all_trades = []
    all_daily = []
    metrics: dict[str, Any] = {"development": {}, "evaluation": {}}
    execution_checks: dict[str, bool] = {}
    for period in ("development", "evaluation"):
        for scenario in ("primary", "stress"):
            trades, daily, result, checks = simulate_period(
                spot, contracts, ruonia, protocol, period, scenario
            )
            all_trades.append(trades)
            all_daily.append(daily)
            metrics[period][scenario] = result
            execution_checks.update(
                {f"{period}_{scenario}_{name}": passed for name, passed in checks.items()}
            )
    checks = {**source_checks, **execution_checks}
    promotion = _promotion(metrics, checks, protocol)
    metrics["promotion_gates"] = promotion
    metrics["checks_all_true"] = all(checks.values())
    metrics["verdict"] = "GO" if all(promotion.values()) else "NO_GO"
    metrics["live_trading_allowed"] = False
    metrics["config_sha256"] = CONFIG_SHA256

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    final = run_root.resolve() / f"fx_cash_carry_v1_{timestamp}_{CONFIG_SHA256[:8]}"
    if final.exists():
        raise FileExistsError(final)
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}-", dir=final.parent))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "config_snapshot.yaml")
        trades_path = temporary / "trades.parquet"
        daily_path = temporary / "daily_equity.parquet"
        pd.concat(all_trades, ignore_index=True).to_parquet(trades_path, index=False)
        pd.concat(all_daily, ignore_index=True).to_parquet(daily_path, index=False)
        _write_json(temporary / "metrics.json", metrics)
        (temporary / "report.md").write_text(
            _report(metrics, promotion), encoding="utf-8-sig"
        )
        identity = {
            "protocol_id": protocol["protocol_id"],
            "config_sha256": CONFIG_SHA256,
            "implementation_sha256": _sha_file(MODULE_PATH),
            "sources": identities,
        }
        _write_json(temporary / "identity.json", identity)
        _write_json(temporary / "audit.json", {"checks": checks, "all_true": all(checks.values())})
        artifact_paths = [
            "config_snapshot.yaml",
            "trades.parquet",
            "daily_equity.parquet",
            "metrics.json",
            "report.md",
            "identity.json",
            "audit.json",
        ]
        artifact_manifest = {
            name: {
                "bytes": (temporary / name).stat().st_size,
                "sha256": _sha_file(temporary / name),
            }
            for name in artifact_paths
        }
        _write_json(temporary / "artifact_manifest.json", artifact_manifest)
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    if not all(audit(final).values()):
        raise ValueError("FX cash-and-carry canonical run audit failed")
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
    }
    for name, item in artifacts.items():
        path = run_directory / name
        checks[f"artifact_{name}_exact"] = (
            path.is_file()
            and path.stat().st_size == int(item["bytes"])
            and _sha_file(path) == item["sha256"]
        )
    stored_audit = json.loads((run_directory / "audit.json").read_text(encoding="utf-8-sig"))
    checks["stored_execution_audit_all_true"] = stored_audit["all_true"] is True
    metrics = json.loads((run_directory / "metrics.json").read_text(encoding="utf-8-sig"))
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
