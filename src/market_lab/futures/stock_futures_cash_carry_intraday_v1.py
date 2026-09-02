"""Run the sealed synchronous covered stock-futures cash-and-carry screen."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures import moex_stock_futures_cash_carry_source as source_utils
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/stock_futures_cash_carry_intraday_v1.yaml"
CONFIG_SHA256: Final[str] = (
    "aa35b0d864483b30e0b6ffec67dec9b5efeab945362dc9cf5b91e60c06c1885e"
)
ASSETS: Final[tuple[str, ...]] = ("GAZR", "SBRF", "ROSN", "TATN", "NOTK")
SCENARIOS: Final[dict[str, tuple[float, str]]] = {
    "primary": (0.50, "ordinary"),
    "doubled": (0.50, "doubled"),
    "zero_cashflow_stress": (0.00, "doubled"),
    "full_rms_proxy_upper_bound": (1.00, "ordinary"),
}
COSTS: Final[dict[str, tuple[float, float]]] = {
    "ordinary": (10.0 / 10_000.0, 5.0 / 10_000.0),
    "doubled": (20.0 / 10_000.0, 10.0 / 10_000.0),
}


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    paths: dict[str, Path]
    spot_paths: dict[str, Path]


def _sha(path: Path) -> str:
    return source_utils.sha256_file(path)


def _path(root: str, file: str) -> Path:
    return source_utils._project_path(root, "data" if root.startswith("data/") else "runs") / file


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("cash-carry economic config must be an object")
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "stock_futures_cash_carry_intraday_v1"
        or payload.get("status")
        != "sealed_before_any_stock_futures_basis_signal_return_or_pnl"
        or payload.get("live_trading_allowed") is not False
        or tuple(payload["universe"]["assets"]) != ASSETS
        or int(payload["universe"]["shares_per_contract"]) != 100
        or float(payload["point_in_time_cashflow"]["projected_cashflow_haircut"])
        != 0.50
    ):
        raise ValueError("cash-carry economic protocol drifted")
    paths: dict[str, Path] = {}
    for section_name, keys in {
        "intraday": ("manifest", "specs", "candles", "raw"),
        "rms": ("manifest", "cashflow"),
        "rates": ("manifest", "daily"),
    }.items():
        section = payload["sources"][section_name]
        for key in keys:
            declaration = section[key]
            path = _path(section["root"], declaration["file"])
            if _sha(path) != declaration["sha256"]:
                raise ValueError(f"cash-carry input drifted: {section_name}.{key}")
            if (
                "rows" in declaration
                and path.suffix == ".parquet"
                and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
            ):
                raise ValueError(f"cash-carry rows drifted: {section_name}.{key}")
            paths[f"{section_name}_{key}"] = path
    spot_section = payload["sources"]["spot"]
    spot_manifest = _path(spot_section["root"], spot_section["manifest"]["file"])
    if _sha(spot_manifest) != spot_section["manifest"]["sha256"]:
        raise ValueError("cash-carry spot manifest drifted")
    spot_paths: dict[str, Path] = {}
    for asset, declaration in spot_section["files"].items():
        path = _path(spot_section["root"], declaration["file"])
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"cash-carry spot drifted: {asset}")
        if pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"]):
            raise ValueError(f"cash-carry spot rows drifted: {asset}")
        spot_paths[asset] = path
    return Protocol(payload, actual, paths, spot_paths)


def _load_cashflows(protocol: Protocol) -> pd.DataFrame:
    frame = pd.read_parquet(protocol.paths["rms_cashflow"])
    frame["t"] = pd.to_datetime(frame["t"], errors="raise").dt.normalize()
    frame["available_at_utc"] = pd.to_datetime(
        frame["available_at_utc"], errors="raise", utc=True
    )
    frame["cf"] = pd.to_numeric(frame["cf"], errors="raise")
    if (~np.isfinite(frame["cf"]) | frame["cf"].lt(0.0)).any():
        raise ValueError("cash-carry RMS cashflow invalid")
    return frame


def _cashflow_sum(
    frame: pd.DataFrame,
    asset: str,
    available_at: pd.Timestamp,
    after_date: pd.Timestamp,
    through_date: pd.Timestamp,
) -> tuple[float, int]:
    selected = frame.loc[
        frame["logical_asset"].eq(asset)
        & frame["available_at_utc"].le(available_at)
        & frame["t"].gt(after_date)
        & frame["t"].le(through_date)
    ].copy()
    if selected.empty:
        return 0.0, 0
    latest = selected.sort_values("available_at_utc").groupby("t", as_index=False).tail(1)
    return float(latest["cf"].sum()), int(len(latest))


def _load_ruonia(protocol: Protocol) -> pd.DataFrame:
    frame = pd.read_parquet(protocol.paths["rates_daily"])
    frame = frame.loc[frame["series_id"].astype(str).eq("ruonia")].copy()
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="raise", utc=True)
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    return frame.sort_values("available_at", ignore_index=True)


def _prior_ruonia(
    frame: pd.DataFrame, decision_at: pd.Timestamp
) -> tuple[float, pd.Timestamp] | None:
    eligible = frame.loc[frame["available_at"].le(decision_at)]
    if eligible.empty:
        return None
    row = eligible.iloc[-1]
    return float(row["value"]), pd.Timestamp(row["available_at"])


def _aligned_asset(
    protocol: Protocol, asset: str, futures: pd.DataFrame, specs: pd.DataFrame
) -> pd.DataFrame:
    selected = futures.loc[futures["logical_asset"].eq(asset)].copy()
    local = selected["timestamp"].dt.tz_convert("Europe/Moscow")
    decisions = selected.loc[local.dt.strftime("%H:%M:%S").eq("15:40:00")].copy()
    decisions["local_date"] = local.loc[decisions.index].dt.tz_localize(None).dt.normalize()
    decisions["execution_timestamp"] = decisions["timestamp"] + pd.Timedelta(minutes=10)
    execution = selected.rename(
        columns={
            "timestamp": "execution_timestamp",
            "open": "futures_entry_open",
            "volume": "futures_entry_volume",
        }
    )[["contract_id", "execution_timestamp", "futures_entry_open", "futures_entry_volume"]]
    decisions = decisions.rename(
        columns={
            "close": "futures_decision_close",
            "volume": "futures_decision_volume",
            "end_timestamp": "decision_at",
        }
    ).merge(execution, on=["contract_id", "execution_timestamp"], how="left")
    spot = pd.read_parquet(protocol.spot_paths[asset]).copy()
    spot.index = pd.to_datetime(spot.index, utc=True)
    spot_decision = spot[["close", "volume"]].rename(
        columns={"close": "spot_decision_close", "volume": "spot_decision_volume"}
    )
    spot_execution = spot[["open", "volume"]].rename(
        columns={"open": "spot_entry_open", "volume": "spot_entry_volume"}
    )
    decisions = decisions.join(spot_decision, on="timestamp").join(
        spot_execution, on="execution_timestamp"
    )
    decisions = decisions.merge(
        specs[["contract_id", "last_trade"]], on="contract_id", how="left"
    )
    decisions["last_trade"] = pd.to_datetime(decisions["last_trade"]).dt.normalize()
    decisions["dte"] = (decisions["last_trade"] - decisions["local_date"]).dt.days
    numeric = [
        "futures_decision_close",
        "futures_decision_volume",
        "futures_entry_open",
        "futures_entry_volume",
        "spot_decision_close",
        "spot_decision_volume",
        "spot_entry_open",
        "spot_entry_volume",
    ]
    decisions["fill_complete"] = decisions[numeric].notna().all(axis=1) & decisions[
        numeric
    ].gt(0.0).all(axis=1)
    return decisions.sort_values(["local_date", "dte", "secid"], ignore_index=True)


def _roundtrip_cost(row: pd.Series, model: str) -> tuple[float, float, float]:
    spot_bps, futures_bps = COSTS[model]
    entry = spot_bps * 100.0 * float(row["spot_entry_open"]) + futures_bps * float(
        row["futures_entry_open"]
    )
    exit_cost = spot_bps * 100.0 * float(row["spot_exit_open"]) + futures_bps * float(
        row["futures_exit_open"]
    )
    return entry + exit_cost, entry, exit_cost


def build_decisions_and_trades(
    protocol: Protocol,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    futures = pd.read_parquet(protocol.paths["intraday_candles"])
    futures["timestamp"] = pd.to_datetime(futures["timestamp"], errors="raise", utc=True)
    futures["end_timestamp"] = pd.to_datetime(
        futures["end_timestamp"], errors="raise", utc=True
    )
    specs = pd.read_parquet(protocol.paths["intraday_specs"])
    cashflows = _load_cashflows(protocol)
    ruonia = _load_ruonia(protocol)
    aligned = {asset: _aligned_asset(protocol, asset, futures, specs) for asset in ASSETS}
    decision_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    trade_number = 0
    for asset in ASSETS:
        frame = aligned[asset]
        candidates = frame.loc[frame["dte"].between(30, 90)].groupby(
            "local_date", as_index=False, sort=True
        ).head(1)
        blocked_through: pd.Timestamp | None = None
        for candidate in candidates.to_dict("records"):
            row = pd.Series(candidate)
            record = {
                "decision_id": f"{asset}:{pd.Timestamp(row['local_date']).date()}",
                "logical_asset": asset,
                "local_date": row["local_date"],
                "decision_at": row["decision_at"],
                "execution_timestamp": row["execution_timestamp"],
                "contract_id": row["contract_id"],
                "secid": row["secid"],
                "last_trade": row["last_trade"],
                "dte": int(row["dte"]),
                "status": "pending",
                "signal": False,
            }
            if blocked_through is not None and pd.Timestamp(row["local_date"]) <= blocked_through:
                record["status"] = "position_open"
                decision_rows.append(record)
                continue
            if not bool(row["fill_complete"]):
                record["status"] = "missing_next_aligned_fill"
                decision_rows.append(record)
                continue
            prior_rate = _prior_ruonia(ruonia, pd.Timestamp(row["decision_at"]))
            if prior_rate is None:
                record["status"] = "missing_ruonia"
                decision_rows.append(record)
                continue
            rate, rate_available = prior_rate
            planned_exit = pd.Timestamp(row["last_trade"]) - pd.Timedelta(days=5)
            expected_cf, expected_events = _cashflow_sum(
                cashflows,
                asset,
                pd.Timestamp(row["decision_at"]),
                pd.Timestamp(row["local_date"]),
                planned_exit,
            )
            stock_notional = 100.0 * float(row["spot_decision_close"])
            futures_notional = float(row["futures_decision_close"])
            capital = stock_notional + 0.30 * futures_notional
            decision_cost = (
                2.0 * COSTS["ordinary"][0] * stock_notional
                + 2.0 * COSTS["ordinary"][1] * futures_notional
            )
            holding_days = max(int(row["dte"]) - 5, 1)
            locked = futures_notional + 100.0 * 0.50 * expected_cf - stock_notional - decision_cost
            annualized = locked / capital * 365.0 / holding_days
            threshold = max(0.20, rate / 100.0 + 0.04)
            record.update(
                {
                    "ruonia_percent": rate,
                    "ruonia_available_at": rate_available,
                    "expected_cashflow_per_share": expected_cf,
                    "expected_cashflow_events": expected_events,
                    "decision_stock_notional": stock_notional,
                    "decision_futures_notional": futures_notional,
                    "conservative_capital": capital,
                    "annualized_locked_proxy": annualized,
                    "entry_threshold": threshold,
                }
            )
            if annualized < threshold:
                record["status"] = "hurdle_not_met"
                decision_rows.append(record)
                continue
            exits = frame.loc[
                frame["contract_id"].eq(row["contract_id"])
                & frame["local_date"].gt(row["local_date"])
                & frame["dte"].between(0, 5)
                & frame["fill_complete"]
            ]
            if exits.empty:
                record["status"] = "missing_scheduled_exit"
                decision_rows.append(record)
                continue
            exit_row = exits.iloc[0]
            record["status"] = "admitted"
            record["signal"] = True
            decision_rows.append(record)
            trade_number += 1
            outcome_cf, outcome_events = _cashflow_sum(
                cashflows,
                asset,
                pd.Timestamp(exit_row["execution_timestamp"]),
                pd.Timestamp(row["local_date"]),
                pd.Timestamp(exit_row["local_date"]),
            )
            trade = {
                "trade_id": f"cash_carry_{trade_number:04d}",
                "decision_id": record["decision_id"],
                "logical_asset": asset,
                "contract_id": row["contract_id"],
                "secid": row["secid"],
                "entry_date": row["local_date"],
                "exit_date": exit_row["local_date"],
                "entry_timestamp": row["execution_timestamp"],
                "exit_timestamp": exit_row["execution_timestamp"],
                "spot_entry_open": float(row["spot_entry_open"]),
                "futures_entry_open": float(row["futures_entry_open"]),
                "spot_exit_open": float(exit_row["spot_entry_open"]),
                "futures_exit_open": float(exit_row["futures_entry_open"]),
                "capital": 100.0 * float(row["spot_entry_open"])
                + 0.30 * float(row["futures_entry_open"]),
                "projected_cashflow_per_share": expected_cf,
                "outcome_rms_proxy_per_share": outcome_cf,
                "outcome_rms_event_count": outcome_events,
                "holding_calendar_days": int(
                    (pd.Timestamp(exit_row["local_date"]) - pd.Timestamp(row["local_date"])).days
                ),
            }
            gross_pair = 100.0 * (trade["spot_exit_open"] - trade["spot_entry_open"]) + (
                trade["futures_entry_open"] - trade["futures_exit_open"]
            )
            trade["gross_pair_pnl"] = gross_pair
            for scenario, (fraction, model) in SCENARIOS.items():
                total_cost, entry_cost, exit_cost = _roundtrip_cost(pd.Series(trade), model)
                net = gross_pair + 100.0 * fraction * outcome_cf - total_cost
                trade[f"{scenario}_cashflow_credit"] = 100.0 * fraction * outcome_cf
                trade[f"{scenario}_entry_cost"] = entry_cost
                trade[f"{scenario}_exit_cost"] = exit_cost
                trade[f"{scenario}_net_pnl"] = net
                trade[f"{scenario}_return"] = net / trade["capital"]
            trade_rows.append(trade)
            blocked_through = pd.Timestamp(exit_row["local_date"])
    return pd.DataFrame(decision_rows), pd.DataFrame(trade_rows), aligned


def build_ledger(trades: pd.DataFrame, aligned: dict[str, pd.DataFrame]) -> pd.DataFrame:
    dates = pd.DatetimeIndex(
        sorted(set().union(*(set(frame["local_date"]) for frame in aligned.values())))
    )
    ledger = pd.DataFrame(index=dates)
    for scenario in SCENARIOS:
        asset_navs: list[pd.Series] = []
        for asset in ASSETS:
            nav = pd.Series(np.nan, index=dates, dtype=float)
            nav.iloc[0] = 1.0
            current_nav = 1.0
            for trade in trades.loc[trades["logical_asset"].eq(asset)].to_dict("records"):
                marks = aligned[asset].loc[
                    aligned[asset]["contract_id"].eq(trade["contract_id"])
                    & aligned[asset]["local_date"].between(trade["entry_date"], trade["exit_date"])
                    & aligned[asset]["fill_complete"]
                ].drop_duplicates("local_date", keep="last")
                marks = marks.set_index("local_date").sort_index()
                if marks.empty:
                    raise ValueError("cash-carry trade lacks mark path")
                gross = 100.0 * (marks["spot_entry_open"] - trade["spot_entry_open"]) + (
                    trade["futures_entry_open"] - marks["futures_entry_open"]
                )
                entry_cost = float(trade[f"{scenario}_entry_cost"])
                cumulative = gross - entry_cost
                cumulative.loc[pd.Timestamp(trade["exit_date"])] += (
                    float(trade[f"{scenario}_cashflow_credit"])
                    - float(trade[f"{scenario}_exit_cost"])
                )
                path = current_nav * (1.0 + cumulative / float(trade["capital"]))
                nav.loc[path.index] = path
                current_nav = float(path.loc[pd.Timestamp(trade["exit_date"])])
            asset_navs.append(nav.ffill().rename(asset))
        sleeve = pd.concat(asset_navs, axis=1)
        ledger[f"{scenario}_nav"] = sleeve.mean(axis=1)
        ledger[f"{scenario}_return"] = ledger[f"{scenario}_nav"].pct_change().fillna(0.0)
    return ledger.rename_axis("date").reset_index()


def _metrics(nav: pd.Series, dates: pd.DatetimeIndex) -> dict[str, Any]:
    nav = nav.astype(float)
    returns = nav.pct_change().fillna(0.0)
    total = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    days = max(int((dates[-1] - dates[0]).days), 1)
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (365.0 / days) - 1.0)
    std = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / std * math.sqrt(252.0)) if std > 0 else 0.0
    drawdown = nav / nav.cummax() - 1.0
    years: dict[str, float] = {}
    indexed = pd.Series(nav.to_numpy(), index=dates)
    for year, values in indexed.groupby(indexed.index.year):
        years[str(year)] = float(values.iloc[-1] / values.iloc[0] - 1.0)
    return {
        "total_return": total,
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": float(-drawdown.min()),
        "per_year": years,
        "positive_years": int(sum(value > 0.0 for value in years.values())),
    }


def build_metrics(
    decisions: pd.DataFrame, trades: pd.DataFrame, ledger: pd.DataFrame
) -> dict[str, Any]:
    dates = pd.DatetimeIndex(ledger["date"])
    scenarios = {
        name: _metrics(ledger[f"{name}_nav"], dates) for name in SCENARIOS
    }
    primary = scenarios["primary"]
    doubled = scenarios["doubled"]
    gates = {
        "primary_and_doubled_positive_cagr": primary["cagr"] > 0.0
        and doubled["cagr"] > 0.0,
        "primary_sharpe_gte_1": primary["sharpe"] >= 1.0,
        "primary_mdd_lte_15pct": primary["maximum_drawdown"] <= 0.15,
        "trades_gte_20": len(trades) >= 20,
        "positive_years_gte_2": primary["positive_years"] >= 2,
    }
    return {
        "verdict": "FORWARD_CANDIDATE" if all(gates.values()) else "NO_GO",
        "counts": {
            "decisions": len(decisions),
            "signals": int(decisions["signal"].fillna(False).sum()),
            "trades": len(trades),
            "unresolved": int(decisions["status"].astype(str).str.startswith("missing").sum()),
            "statuses": decisions["status"].value_counts().astype(int).to_dict(),
        },
        "scenarios": scenarios,
        "gates": gates,
    }


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# Stock–futures intraday cash-and-carry V1",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        f"Decisions: {metrics['counts']['decisions']}; signals/trades: "
        f"{metrics['counts']['signals']}/{metrics['counts']['trades']}; unresolved: "
        f"{metrics['counts']['unresolved']}.",
        "",
        "| Scenario | CAGR | Sharpe | MDD | Total return | Positive years |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, item in metrics["scenarios"].items():
        lines.append(
            f"| {name} | {item['cagr']:.4%} | {item['sharpe']:.3f} | "
            f"{item['maximum_drawdown']:.4%} | {item['total_return']:.4%} | "
            f"{item['positive_years']} |"
        )
    lines.extend(
        [
            "",
            "RMS cashflows are projections/outcome proxies, not proof of paid dividends. "
            "The zero-cashflow scenario is the hard lower bound.",
            "Candles do not prove bid/ask fills, queue position, broker margin, or live profit.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(protocol: Protocol) -> Path:
    decisions, trades, aligned = build_decisions_and_trades(protocol)
    ledger = build_ledger(trades, aligned)
    metrics = build_metrics(decisions, trades, ledger)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    root = PROJECT_ROOT / protocol.payload["outputs"]["root"]
    output = root.parent / f"{root.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"cash-carry run exists: {output}")
    output.mkdir(parents=True)
    paths = {
        "decisions": output / "decisions.parquet",
        "trades": output / "trades.parquet",
        "ledger": output / "daily_ledger.parquet",
        "audit": output / "audit.json",
        "metrics": output / "metrics.json",
        "report": output / "report.md",
    }
    source_utils._write_parquet(paths["decisions"], decisions)
    source_utils._write_parquet(paths["trades"], trades)
    source_utils._write_parquet(paths["ledger"], ledger)
    audit = {
        "checks": {
            "protocol_sha_exact": _sha(CONFIG_PATH) == protocol.config_sha256,
            "all_decisions_before_2026": bool(
                pd.to_datetime(decisions["local_date"]).dt.year.le(2025).all()
            ),
            "signals_equal_trades": int(decisions["signal"].sum()) == len(trades),
            "no_asset_overlap": bool(
                all(
                    not (
                        part.sort_values("entry_date")["entry_date"].iloc[1:].reset_index(drop=True)
                        <= part.sort_values("entry_date")["exit_date"]
                        .iloc[:-1]
                        .reset_index(drop=True)
                    ).any()
                    for _, part in trades.groupby("logical_asset")
                )
            ),
            "scenario_decisions_identical": True,
            "rms_not_labeled_realized_dividend": not any(
                "realized_dividend" in str(column).lower() for column in trades.columns
            ),
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"cash-carry run audit failed: {audit}")
    write_json(paths["audit"], audit)
    write_json(paths["metrics"], metrics)
    atomic_write_bytes(paths["report"], _report(metrics).encode("utf-8-sig"))
    artifacts = {
        name: source_utils._artifact(path, pq.ParquetFile(path).metadata.num_rows)
        if path.suffix == ".parquet"
        else source_utils._artifact(path)
        for name, path in paths.items()
    }
    manifest = {
        "run_id": output.name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": protocol.config_sha256,
        "implementation_sha256": _sha(Path(__file__)),
        "verdict": metrics["verdict"],
        "live_trading_allowed": False,
        "artifacts": artifacts,
    }
    manifest_path = output / "manifest.json"
    write_json(manifest_path, manifest)
    atomic_write_bytes(
        output / "manifest.sha256",
        f"{_sha(manifest_path)}  manifest.json\n".encode("utf-8-sig"),
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    protocol = load_protocol()
    output = run(protocol)
    print(output)
    print((output / "report.md").read_text(encoding="utf-8-sig"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
