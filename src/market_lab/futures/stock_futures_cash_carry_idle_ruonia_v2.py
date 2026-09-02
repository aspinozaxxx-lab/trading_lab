"""Add sealed causal idle-RUONIA income to frozen stock-futures cash-carry."""

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
import pyarrow.parquet as pq
import yaml

from market_lab.futures import moex_stock_futures_cash_carry_source as io_utils
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/stock_futures_cash_carry_idle_ruonia_v2.yaml"
)
CONFIG_SHA256: Final[str] = (
    "a4c03aaa5b9832fe92b3f5c86db5d41a56acc74253e3f30280bd2a0bb59f0905"
)
ASSETS: Final[tuple[str, ...]] = ("GAZR", "SBRF", "ROSN", "TATN", "NOTK")
SCENARIOS: Final[tuple[str, ...]] = (
    "primary",
    "doubled",
    "zero_cashflow_stress",
    "full_rms_proxy_upper_bound",
)
START: Final[pd.Timestamp] = pd.Timestamp("2020-12-30")
END: Final[pd.Timestamp] = pd.Timestamp("2025-12-30")


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    parent_root: Path
    rates_root: Path


def _sha(path: Path) -> str:
    return io_utils.sha256_file(path)


def _project_root(value: str, required: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe idle RUONIA path: {value}")
    if relative.parts[0].lower() != required:
        raise ValueError(f"idle RUONIA path must start with {required}")
    return PROJECT_ROOT / relative


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("idle RUONIA config must be an object")
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "stock_futures_cash_carry_idle_ruonia_v2"
        or payload.get("status") != "sealed_before_any_idle_interest_nav_or_combined_metric"
        or payload.get("live_trading_allowed") is not False
        or tuple(payload["eligibility"]["assets"]) != ASSETS
        or int(payload["eligibility"]["equal_asset_sleeves"]) != 5
        or float(payload["interest"]["applied_ruonia_fraction"]) != 0.50
        or payload["parent_scenario_mapping"]
        ["parent_decisions_trades_and_costs_unchanged"]
        is not True
    ):
        raise ValueError("idle RUONIA protocol drifted")
    parent = payload["parent"]
    rates = payload["rates"]
    parent_root = _project_root(parent["root"], "runs")
    rates_root = _project_root(rates["root"], "data")
    for section, root, skipped in (
        (parent, parent_root, {"root", "protocol_sha256"}),
        (rates, rates_root, {"root", "series_id"}),
    ):
        for key, declaration in section.items():
            if key in skipped:
                continue
            path = root / declaration["file"]
            if _sha(path) != declaration["sha256"]:
                raise ValueError(f"idle RUONIA input drifted: {key}")
            if (
                "rows" in declaration
                and path.suffix == ".parquet"
                and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
            ):
                raise ValueError(f"idle RUONIA rows drifted: {key}")
    manifest = json.loads(
        (parent_root / parent["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    if manifest["protocol_sha256"] != parent["protocol_sha256"]:
        raise ValueError("idle RUONIA parent protocol drifted")
    return Protocol(payload, actual, parent_root, rates_root)


def _load_rates(protocol: Protocol) -> pd.DataFrame:
    declaration = protocol.payload["rates"]["daily"]
    frame = pd.read_parquet(protocol.rates_root / declaration["file"])
    frame = frame.loc[frame["series_id"].astype(str).eq("ruonia")].copy()
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="raise", utc=True)
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    if frame.empty or (~np.isfinite(frame["value"])).any():
        raise ValueError("idle RUONIA rate source invalid")
    return frame.sort_values("available_at", ignore_index=True)


def _causal_rate(rates: pd.DataFrame, date: pd.Timestamp) -> tuple[float, pd.Timestamp] | None:
    cutoff = (
        pd.Timestamp(date)
        .tz_localize("Europe/Moscow")
        .replace(hour=21, minute=0, second=0)
        .tz_convert("UTC")
    )
    eligible = rates.loc[rates["available_at"].le(cutoff)]
    if eligible.empty:
        return None
    row = eligible.iloc[-1]
    return max(float(row["value"]), 0.0), pd.Timestamp(row["available_at"])


def _load_parent(protocol: Protocol) -> tuple[pd.DataFrame, pd.DataFrame]:
    parent = protocol.payload["parent"]
    ledger = pd.read_parquet(protocol.parent_root / parent["ledger"]["file"])
    trades = pd.read_parquet(protocol.parent_root / parent["trades"]["file"])
    ledger["date"] = pd.to_datetime(ledger["date"], errors="raise").dt.normalize()
    for column in ("entry_date", "exit_date"):
        trades[column] = pd.to_datetime(trades[column], errors="raise").dt.normalize()
    if len(trades) != 15 or trades["trade_id"].duplicated().any():
        raise ValueError("idle RUONIA frozen trades drifted")
    return ledger, trades


def _active_assets(trades: pd.DataFrame, date: pd.Timestamp) -> int:
    active = trades.loc[
        trades["entry_date"].le(date) & trades["exit_date"].ge(date), "logical_asset"
    ]
    count = int(active.nunique())
    if count < 0 or count > len(ASSETS):
        raise ValueError("idle RUONIA active asset count invalid")
    return count


def _metrics(nav: pd.Series) -> dict[str, Any]:
    nav = nav.astype(float)
    returns = nav.pct_change().fillna(0.0)
    total = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    years = max((nav.index[-1] - nav.index[0]).days / 365.25, 1.0 / 365.25)
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / years) - 1.0)
    std = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / std * math.sqrt(365.25)) if std > 0.0 else 0.0
    drawdown = 1.0 - nav / nav.cummax()
    annual: dict[str, float] = {}
    prior = float(nav.iloc[0])
    for year, part in nav.groupby(nav.index.year):
        if year == nav.index[0].year and len(part) <= 2:
            prior = float(part.iloc[-1])
            continue
        ending = float(part.iloc[-1])
        annual[str(year)] = ending / prior - 1.0
        prior = ending
    return {
        "total_return": total,
        "cagr": cagr,
        "sharpe": sharpe,
        "maximum_drawdown": float(drawdown.max()),
        "annual_returns": annual,
        "positive_years": int(sum(value > 0.0 for value in annual.values())),
        "worst_year": float(min(annual.values())) if annual else 0.0,
    }


def build(protocol: Protocol) -> tuple[pd.DataFrame, dict[str, Any]]:
    parent, trades = _load_parent(protocol)
    rates = _load_rates(protocol)
    dates = pd.date_range(START, END, freq="D")
    base = pd.DataFrame(index=dates)
    base["active_asset_count"] = [_active_assets(trades, date) for date in dates]
    base["eligible_fraction"] = 1.0 - base["active_asset_count"] / float(len(ASSETS))
    rate_values: list[float] = []
    rate_available: list[pd.Timestamp | pd.NaT] = []
    missing = 0
    for date in dates:
        value = _causal_rate(rates, date)
        if value is None:
            missing += 1
            rate_values.append(0.0)
            rate_available.append(pd.NaT)
        else:
            rate_values.append(value[0])
            rate_available.append(value[1])
    base["ruonia_percent"] = rate_values
    base["ruonia_available_at"] = rate_available
    base["idle_interest_return"] = (
        base["eligible_fraction"] * 0.50 * base["ruonia_percent"] / 100.0 / 365.0
    )
    scenario_metrics: dict[str, Any] = {}
    for scenario in SCENARIOS:
        parent_nav = parent.set_index("date")[f"{scenario}_nav"].astype(float)
        parent_nav = parent_nav / float(parent_nav.iloc[0])
        parent_daily = parent_nav.reindex(dates).ffill().fillna(1.0)
        parent_return = parent_daily.pct_change().fillna(0.0)
        nav = pd.Series(1.0, index=dates, dtype=float)
        interest_contribution = pd.Series(0.0, index=dates, dtype=float)
        cumulative_interest = 0.0
        for index in range(len(dates) - 1):
            current, following = dates[index], dates[index + 1]
            trade_return = float(parent_return.loc[following])
            interest_return = float(base.loc[current, "idle_interest_return"])
            starting = float(nav.loc[current])
            interest_value = starting * interest_return
            nav.loc[following] = starting * (1.0 + trade_return + interest_return)
            cumulative_interest += interest_value
            interest_contribution.loc[following] = cumulative_interest
        base[f"parent_{scenario}_nav"] = parent_daily
        base[f"overlay_{scenario}_nav"] = nav
        base[f"overlay_{scenario}_return"] = nav.pct_change().fillna(0.0)
        base[f"{scenario}_cumulative_interest"] = interest_contribution
        scenario_metrics[scenario] = {
            "parent_same_clock": _metrics(parent_daily),
            "overlay": _metrics(nav),
            "collateral_income_nav_units": cumulative_interest,
        }
    gates = {
        "primary_doubled_zero_cagr_positive": all(
            scenario_metrics[name]["overlay"]["cagr"] > 0.0
            for name in ("primary", "doubled", "zero_cashflow_stress")
        ),
        "primary_mdd_lte_2pct": scenario_metrics["primary"]["overlay"]
        ["maximum_drawdown"]
        <= 0.02,
        "collateral_income_nonnegative": all(
            scenario_metrics[name]["collateral_income_nav_units"] >= 0.0
            for name in SCENARIOS
        ),
        "exact_15_parent_trades": len(trades) == 15,
    }
    metrics = {
        "verdict": "CASH_SLEEVE_FORWARD_CANDIDATE" if all(gates.values()) else "NO_GO",
        "counts": {
            "parent_trades": len(trades),
            "calendar_intervals": len(dates) - 1,
            "missing_rate_dates": missing,
            "active_asset_days": int(base["active_asset_count"].sum()),
            "mean_eligible_fraction": float(base["eligible_fraction"].mean()),
        },
        "scenarios": scenario_metrics,
        "gates": gates,
        "live_trading_allowed": False,
    }
    return base.rename_axis("date").reset_index(), metrics


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# Covered stock-futures cash-carry V2 idle-RUONIA overlay",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        f"Frozen trades: {metrics['counts']['parent_trades']}; mean eligible fraction: "
        f"{metrics['counts']['mean_eligible_fraction']:.2%}; missing rate dates: "
        f"{metrics['counts']['missing_rate_dates']}.",
        "",
        "| Scenario | CAGR | Sharpe | MDD | Worst year | Collateral income |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, item in metrics["scenarios"].items():
        value = item["overlay"]
        lines.append(
            f"| {name} | {value['cagr']:.4%} | {value['sharpe']:.3f} | "
            f"{value['maximum_drawdown']:.4%} | {value['worst_year']:.4%} | "
            f"{item['collateral_income_nav_units']:.4f} NAV |"
        )
    lines.extend(
        [
            "",
            "No parent signal, trade, cost, cashflow or position date was changed.",
            "A broker instrument actually paying 50% RUONIA with required liquidity is not proved.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(protocol: Protocol) -> Path:
    ledger, metrics = build(protocol)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = _project_root(protocol.payload["outputs"]["root"], "runs")
    output = base.parent / f"{base.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"idle RUONIA output exists: {output}")
    output.mkdir(parents=True)
    ledger_path = output / "daily_ledger.parquet"
    io_utils._write_parquet(ledger_path, ledger)
    metrics_path = output / "metrics.json"
    write_json(metrics_path, metrics)
    report_path = output / "report.md"
    atomic_write_bytes(report_path, _report(metrics).encode("utf-8-sig"))
    audit = {
        "checks": {
            "protocol_sha_exact": _sha(CONFIG_PATH) == protocol.config_sha256,
            "all_dates_before_2026": bool(pd.to_datetime(ledger["date"]).dt.year.le(2025).all()),
            "exact_parent_trades": metrics["counts"]["parent_trades"] == 15,
            "eligible_fraction_bounded": bool(
                ledger["eligible_fraction"].between(0.0, 1.0).all()
            ),
            "interest_nonnegative": bool(ledger["idle_interest_return"].ge(0.0).all()),
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"idle RUONIA audit failed: {audit}")
    audit_path = output / "audit.json"
    write_json(audit_path, audit)
    artifacts = {
        "ledger": io_utils._artifact(ledger_path, len(ledger)),
        "metrics": io_utils._artifact(metrics_path),
        "report": io_utils._artifact(report_path),
        "audit": io_utils._artifact(audit_path),
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
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    output = run(load_protocol())
    print(output)
    print((output / "report.md").read_text(encoding="utf-8-sig"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
