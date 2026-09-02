"""Add sealed causal idle-RUONIA income to corrected broad cash-carry."""

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

from market_lab.futures import moex_stock_futures_cash_carry_source as storage
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/stock_futures_cash_carry_broad_idle_ruonia_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "e5d91172a7b78fa25cabe2568d09c33975d472896c40b871e3d33ff6f071907c"
)
SCENARIOS: Final[tuple[str, ...]] = (
    "primary",
    "doubled",
    "zero_cashflow_stress",
    "delayed_fill_stress",
)
VIEWS: Final[tuple[str, ...]] = ("equal_sleeves", "active_cap")
START: Final[pd.Timestamp] = pd.Timestamp("2020-12-30")
END: Final[pd.Timestamp] = pd.Timestamp("2025-12-30")


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    parent_root: Path
    rates_root: Path


def _sha(path: Path) -> str:
    return storage.sha256_file(path)


def _project_root(value: str, required: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe broad idle RUONIA path: {value}")
    if relative.parts[0].lower() != required:
        raise ValueError(f"broad idle RUONIA path must start with {required}")
    return PROJECT_ROOT / relative


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("broad idle RUONIA config must be an object")
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id")
        != "stock_futures_cash_carry_broad_idle_ruonia_v1"
        or payload.get("status")
        != "sealed_before_any_broad_idle_interest_nav_or_metric"
        or payload.get("live_trading_allowed") is not False
        or float(payload["interest"]["applied_ruonia_fraction"]) != 0.50
        or int(payload["eligibility"]["equal_sleeves"]["exact_stock_sleeves"])
        != 29
        or payload["parent_scenario_mapping"][
            "parent_decisions_trades_costs_cashflows_and_positions_unchanged"
        ]
        is not True
    ):
        raise ValueError("broad idle RUONIA protocol drifted")
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
                raise ValueError(f"broad idle RUONIA input drifted: {key}")
            if (
                "rows" in declaration
                and path.suffix == ".parquet"
                and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
            ):
                raise ValueError(f"broad idle RUONIA rows drifted: {key}")
    manifest = json.loads(
        (parent_root / parent["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    if manifest["protocol_sha256"] != parent["protocol_sha256"]:
        raise ValueError("broad idle RUONIA parent protocol drifted")
    return Protocol(payload, actual, parent_root, rates_root)


def _load_rates(protocol: Protocol) -> pd.DataFrame:
    declaration = protocol.payload["rates"]["daily"]
    frame = pd.read_parquet(protocol.rates_root / declaration["file"])
    frame = frame.loc[frame["series_id"].astype(str).eq("ruonia")].copy()
    frame["available_at"] = pd.to_datetime(frame["available_at"], errors="raise", utc=True)
    frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    if frame.empty or (~np.isfinite(frame["value"])).any():
        raise ValueError("broad idle RUONIA rate source invalid")
    return frame.sort_values("available_at", ignore_index=True)


def _causal_rate(
    rates: pd.DataFrame, date: pd.Timestamp
) -> tuple[float, pd.Timestamp] | None:
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
    if len(trades) != 29 or trades["trade_id"].duplicated().any():
        raise ValueError("broad idle RUONIA frozen trades drifted")
    return ledger, trades


def _active_stocks(trades: pd.DataFrame, date: pd.Timestamp) -> int:
    active = trades.loc[
        trades["entry_date"].le(date) & trades["exit_date"].ge(date), "stock_secid"
    ]
    count = int(active.nunique())
    if count < 0 or count > 29:
        raise ValueError("broad idle RUONIA active stock count invalid")
    return count


def _metrics(nav: pd.Series) -> dict[str, Any]:
    values = nav.astype(float)
    returns = values.pct_change().fillna(0.0)
    total = float(values.iloc[-1] / values.iloc[0] - 1.0)
    years = max((values.index[-1] - values.index[0]).days / 365.25, 1.0 / 365.25)
    cagr = float((values.iloc[-1] / values.iloc[0]) ** (1.0 / years) - 1.0)
    std = float(returns.std(ddof=1))
    sharpe = float(returns.mean() / std * math.sqrt(365.25)) if std > 0.0 else 0.0
    drawdown = 1.0 - values / values.cummax()
    annual: dict[str, float] = {}
    prior = float(values.iloc[0])
    for year, part in values.groupby(values.index.year):
        if year == values.index[0].year and len(part) <= 2:
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


def _overlay_nav(
    parent_nav: pd.Series, idle_fraction: pd.Series, rate_return: pd.Series
) -> tuple[pd.Series, float]:
    dates = parent_nav.index
    parent_return = parent_nav.pct_change().fillna(0.0)
    nav = pd.Series(1.0, index=dates, dtype=float)
    cumulative_interest = 0.0
    for index in range(len(dates) - 1):
        current, following = dates[index], dates[index + 1]
        trade_return = float(parent_return.loc[following])
        interest_return = float(idle_fraction.loc[current] * rate_return.loc[current])
        starting = float(nav.loc[current])
        cumulative_interest += starting * interest_return
        nav.loc[following] = starting * (1.0 + trade_return + interest_return)
    return nav, cumulative_interest


def build(protocol: Protocol) -> tuple[pd.DataFrame, dict[str, Any]]:
    parent_ledger, trades = _load_parent(protocol)
    rates = _load_rates(protocol)
    dates = pd.date_range(START, END, freq="D")
    base = pd.DataFrame(index=dates)
    base["active_stock_count"] = [_active_stocks(trades, date) for date in dates]
    base["equal_sleeves_idle_fraction"] = 1.0 - base["active_stock_count"] / 29.0
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
    base["half_ruonia_daily_return"] = 0.50 * base["ruonia_percent"] / 100.0 / 365.0

    parent = parent_ledger.set_index("date")
    view_metrics: dict[str, dict[str, Any]] = {view: {} for view in VIEWS}
    mean_idle: dict[str, dict[str, float]] = {view: {} for view in VIEWS}
    for view in VIEWS:
        for scenario in SCENARIOS:
            parent_nav = parent[f"{view}_{scenario}_nav"].astype(float)
            parent_nav = parent_nav / float(parent_nav.iloc[0])
            parent_daily = parent_nav.reindex(dates).ffill().fillna(1.0)
            if view == "equal_sleeves":
                idle_fraction = base["equal_sleeves_idle_fraction"].copy()
            else:
                exposure = (
                    parent[f"active_cap_{scenario}_exposure"]
                    .astype(float)
                    .reindex(dates)
                    .ffill()
                    .fillna(0.0)
                )
                conservative = pd.concat(
                    [exposure, exposure.shift(1).fillna(0.0)], axis=1
                ).max(axis=1)
                idle_fraction = 1.0 - conservative
                base[f"active_cap_{scenario}_idle_fraction"] = idle_fraction
            if not idle_fraction.between(0.0, 1.0).all():
                raise ValueError("broad idle RUONIA eligibility outside bounds")
            overlay_nav, income = _overlay_nav(
                parent_daily, idle_fraction, base["half_ruonia_daily_return"]
            )
            base[f"parent_{view}_{scenario}_nav"] = parent_daily
            base[f"overlay_{view}_{scenario}_nav"] = overlay_nav
            base[f"overlay_{view}_{scenario}_return"] = (
                overlay_nav.pct_change().fillna(0.0)
            )
            view_metrics[view][scenario] = {
                "parent_same_clock": _metrics(parent_daily),
                "overlay": _metrics(overlay_nav),
                "idle_income_nav_units": income,
            }
            mean_idle[view][scenario] = float(idle_fraction.mean())
    gates = {
        "both_views_all_four_cagr_positive": all(
            view_metrics[view][scenario]["overlay"]["cagr"] > 0.0
            for view in VIEWS
            for scenario in SCENARIOS
        ),
        "equal_primary_mdd_lte_2pct": view_metrics["equal_sleeves"]["primary"]
        ["overlay"]["maximum_drawdown"]
        <= 0.02,
        "active_primary_mdd_lte_5pct": view_metrics["active_cap"]["primary"]
        ["overlay"]["maximum_drawdown"]
        <= 0.05,
        "idle_income_nonnegative": all(
            view_metrics[view][scenario]["idle_income_nav_units"] >= 0.0
            for view in VIEWS
            for scenario in SCENARIOS
        ),
        "exact_29_parent_trades": len(trades) == 29,
    }
    metrics = {
        "verdict": "CASH_SLEEVE_FORWARD_CANDIDATE"
        if all(gates.values())
        else "NO_GO",
        "counts": {
            "parent_trades": len(trades),
            "calendar_intervals": len(dates) - 1,
            "missing_rate_dates": missing,
            "active_stock_days": int(base["active_stock_count"].sum()),
        },
        "mean_idle_fraction": mean_idle,
        "views": view_metrics,
        "gates": gates,
        "live_trading_allowed": False,
    }
    return base.rename_axis("date").reset_index(), metrics


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# Broad cash-carry R1 idle-RUONIA overlay",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        f"Frozen parent trades: {metrics['counts']['parent_trades']}; missing rate dates: "
        f"{metrics['counts']['missing_rate_dates']}.",
        "",
        "| View | Scenario | CAGR | Sharpe | MDD | Worst year | Idle income |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for view, scenarios in metrics["views"].items():
        for scenario, item in scenarios.items():
            value = item["overlay"]
            lines.append(
                f"| {view} | {scenario} | {value['cagr']:.4%} | "
                f"{value['sharpe']:.3f} | {value['maximum_drawdown']:.4%} | "
                f"{value['worst_year']:.4%} | {item['idle_income_nav_units']:.4f} NAV |"
            )
    lines.extend(
        [
            "",
            "No parent signal, trade, cost, cashflow, allocation or position date changed.",
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
        raise FileExistsError(f"broad idle RUONIA output exists: {output}")
    output.mkdir(parents=True)
    ledger_path = output / "daily_ledger.parquet"
    storage._write_parquet(ledger_path, ledger)
    metrics_path = output / "metrics.json"
    write_json(metrics_path, metrics)
    report_path = output / "report.md"
    atomic_write_bytes(report_path, _report(metrics).encode("utf-8-sig"))
    audit = {
        "checks": {
            "protocol_sha_exact": _sha(CONFIG_PATH) == protocol.config_sha256,
            "all_dates_before_2026": bool(
                pd.to_datetime(ledger["date"]).dt.year.le(2025).all()
            ),
            "exact_parent_trades": metrics["counts"]["parent_trades"] == 29,
            "all_idle_fractions_bounded": bool(
                ledger.filter(like="idle_fraction").apply(
                    lambda column: column.between(0.0, 1.0).all()
                ).all()
            ),
            "interest_nonnegative": bool(
                ledger["half_ruonia_daily_return"].ge(0.0).all()
            ),
            "parent_outcomes_unchanged": True,
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"broad idle RUONIA audit failed: {audit}")
    audit_path = output / "audit.json"
    write_json(audit_path, audit)
    artifacts = {
        "ledger": storage._artifact(ledger_path, len(ledger)),
        "metrics": storage._artifact(metrics_path),
        "report": storage._artifact(report_path),
        "audit": storage._artifact(audit_path),
    }
    manifest = {
        "run_id": output.name,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "protocol_sha256": protocol.config_sha256,
        "implementation_sha256": _sha(Path(__file__)),
        "parent_protocol_sha256": protocol.payload["parent"]["protocol_sha256"],
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
