"""Apply sealed idle-fund expense and switching stresses to frozen V41."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
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
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/v42r1_v41_idle_fund_cost_stress_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "d21601c20965dfdd063a32943d4f8cb16f4978a3a2e791ef9c236c8dce34fc24"
)
MARKET_SCENARIOS: Final[dict[str, str]] = {
    "primary": "primary",
    "doubled": "doubled",
    "stress": "zero_cashflow_stress",
}
COST_SCENARIOS: Final[tuple[str, ...]] = (
    "lqdt_contractual_max",
    "high_cost_tmon_contractual_max",
    "zero_idle_yield_with_switching",
)
SwitchingCostFunction = Callable[[pd.Series, float], pd.Series]


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    v41_root: Path
    cash_root: Path


def _sha(path: Path) -> str:
    return io_utils.sha256_file(path)


def _root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe V42R1 path: {value}")
    if relative.parts[0].lower() != "runs":
        raise ValueError("V42R1 parent/output path must start with runs")
    return PROJECT_ROOT / relative


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V42R1 config must be an object")
    frozen = payload["frozen_inheritance"]
    correction = payload["correction"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id")
        != "futures_v42r1_v41_idle_fund_cost_stress_v1"
        or payload.get("status")
        != "corrected_only_v41_parent_protocol_sha_before_any_v42_metric"
        or payload.get("live_trading_allowed") is not False
        or correction["only_changed_field"] != "parents.v41.protocol_sha256"
        or correction["metrics_or_combined_nav_computed_before_correction"] is not False
        or float(frozen["v39_weight"]) != 0.80
        or float(frozen["cash_carry_weight"]) != 0.20
        or frozen["rebalance_after_initial_allocation"] != "never"
        or tuple(payload["cost_scenarios"]) != COST_SCENARIOS
    ):
        raise ValueError("V42R1 protocol drifted")
    v41 = payload["parents"]["v41"]
    cash = payload["parents"]["idle_cash"]
    v41_root, cash_root = _root(v41["root"]), _root(cash["root"])
    for section, root in ((v41, v41_root), (cash, cash_root)):
        for key, declaration in section.items():
            if key in {"root", "protocol_sha256"}:
                continue
            path = root / declaration["file"]
            if _sha(path) != declaration["sha256"]:
                raise ValueError(f"V42R1 parent drifted: {root.name}.{key}")
            if (
                "rows" in declaration
                and path.suffix == ".parquet"
                and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
            ):
                raise ValueError(f"V42R1 parent rows drifted: {root.name}.{key}")
    v41_manifest = json.loads(
        (v41_root / v41["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    cash_manifest = json.loads(
        (cash_root / cash["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    if (
        v41_manifest["protocol_sha256"] != v41["protocol_sha256"]
        or cash_manifest["protocol_sha256"] != cash["protocol_sha256"]
    ):
        raise ValueError("V42R1 parent protocol identity drifted")
    return Protocol(payload, actual, v41_root, cash_root)


def _switching_costs(eligible: pd.Series, one_way: float) -> pd.Series:
    if eligible.empty or not eligible.between(0.0, 1.0).all() or one_way < 0.0:
        raise ValueError("V42R1 switching inputs invalid")
    costs = eligible.diff().abs().fillna(0.0) * one_way
    costs.iloc[0] += float(eligible.iloc[0]) * one_way
    costs.iloc[-1] += float(eligible.iloc[-1]) * one_way
    return costs


def _stressed_cash_nav(
    parent_nav: pd.Series,
    gross_idle_return: pd.Series,
    eligible: pd.Series,
    *,
    annual_expense: float,
    income_retention: float,
    one_way: float,
    switching_cost_function: SwitchingCostFunction = _switching_costs,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    if not (
        parent_nav.index.equals(gross_idle_return.index)
        and parent_nav.index.equals(eligible.index)
    ):
        raise ValueError("V42R1 cash inputs not aligned")
    if annual_expense < 0.0 or not 0.0 <= income_retention <= 1.0:
        raise ValueError("V42R1 cost scenario invalid")
    normalized_parent = parent_nav.astype(float) / float(parent_nav.iloc[0])
    parent_return = normalized_parent.pct_change().fillna(0.0)
    net_idle = (
        gross_idle_return.astype(float) * income_retention
        - eligible.astype(float) * annual_expense / 365.0
    )
    switching = switching_cost_function(eligible.astype(float), one_way)
    nav = pd.Series(1.0, index=parent_nav.index, dtype=float)
    for index in range(1, len(nav)):
        following = nav.index[index]
        current = nav.index[index - 1]
        net_return = (
            float(parent_return.loc[following])
            + float(net_idle.loc[current])
            - float(switching.loc[following])
        )
        nav.loc[following] = float(nav.loc[current]) * (1.0 + net_return)
    if not np.isfinite(nav).all() or not nav.gt(0.0).all():
        raise ValueError("V42R1 stressed cash NAV invalid")
    return nav, net_idle, switching


def build(
    protocol: Protocol,
    *,
    switching_cost_function: SwitchingCostFunction = _switching_costs,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    v41 = pd.read_parquet(protocol.v41_root / "combined_ledger.parquet")
    cash = pd.read_parquet(protocol.cash_root / "daily_ledger.parquet")
    v41["session_date"] = pd.to_datetime(v41["session_date"], errors="raise")
    cash["date"] = pd.to_datetime(cash["date"], errors="raise")
    if (
        v41["session_date"].duplicated().any()
        or cash["date"].duplicated().any()
        or not v41["session_date"].is_monotonic_increasing
        or not cash["date"].is_monotonic_increasing
    ):
        raise ValueError("V42R1 parent dates invalid")
    cash_index = cash.set_index("date")
    v41_index = v41.set_index("session_date")
    if not v41_index.index.isin(cash_index.index).all():
        raise ValueError("V42R1 cash calendar does not cover V41")
    eligible = cash_index["eligible_fraction"].astype(float)
    gross_idle = cash_index["idle_interest_return"].astype(float)
    output = pd.DataFrame(
        {
            "date": cash_index.index,
            "active_asset_count": cash_index["active_asset_count"].to_numpy(),
            "eligible_fraction": eligible.to_numpy(),
            "gross_idle_interest_return": gross_idle.to_numpy(),
            "is_v39_session": cash_index.index.isin(v41_index.index),
        }
    ).set_index("date")
    v41_metrics = json.loads(
        (protocol.v41_root / "metrics.json").read_text(encoding="utf-8-sig")
    )
    results: dict[str, Any] = {}
    turnover: dict[str, Any] = {}
    for cost_name, cost in protocol.payload["cost_scenarios"].items():
        switching = switching_cost_function(
            eligible, float(cost["fund_trade_one_way_fraction"])
        )
        turnover[cost_name] = {
            "cash_sleeve_turnover_fraction": float(
                switching.sum() / float(cost["fund_trade_one_way_fraction"])
            ),
            "raw_switching_cost_fraction": float(switching.sum()),
            "expense_ratio": float(cost["annual_fund_expense_ratio"]),
            "income_retention": float(
                cost["gross_idle_income_retention_after_tax_proxy"]
            ),
            "one_way_fraction": float(cost["fund_trade_one_way_fraction"]),
        }
    for market_name, cash_scenario in MARKET_SCENARIOS.items():
        v39_nav = v41_index[f"v39_{market_name}_nav"].astype(float)
        reported_parent = v41_metrics["scenarios"][market_name]["v39_parent"]
        parent_metrics = {
            key: reported_parent[key]
            for key in (
                "total_return",
                "cagr",
                "sharpe",
                "maximum_drawdown",
                "annual_returns",
                "positive_years",
                "worst_year",
            )
        }
        cash_parent = cash_index[f"parent_{cash_scenario}_nav"].astype(float)
        for cost_name, cost in protocol.payload["cost_scenarios"].items():
            cash_nav, net_idle, switching = _stressed_cash_nav(
                cash_parent,
                gross_idle,
                eligible,
                annual_expense=float(cost["annual_fund_expense_ratio"]),
                income_retention=float(
                    cost["gross_idle_income_retention_after_tax_proxy"]
                ),
                one_way=float(cost["fund_trade_one_way_fraction"]),
                switching_cost_function=switching_cost_function,
            )
            cash_sessions = cash_nav.reindex(v39_nav.index)
            combined = 0.80 * v39_nav + 0.20 * cash_sessions
            combined_metrics = _metrics(combined)
            key = f"{market_name}__{cost_name}"
            output[f"{key}__cash_nav"] = cash_nav
            output[f"{key}__net_idle_return"] = net_idle
            output[f"{key}__switching_cost"] = switching
            v39_daily = v39_nav.reindex(output.index).ffill()
            output[f"{key}__v39_nav"] = v39_daily
            output[f"{key}__combined_nav"] = 0.80 * v39_daily + 0.20 * cash_nav
            results[key] = {
                "market_scenario": market_name,
                "cost_scenario": cost_name,
                "v39_parent": parent_metrics,
                "stressed_cash": _metrics(cash_sessions),
                "combined": combined_metrics,
                "delta_vs_v39": {
                    "cagr": combined_metrics["cagr"] - parent_metrics["cagr"],
                    "sharpe": combined_metrics["sharpe"] - parent_metrics["sharpe"],
                    "maximum_drawdown": combined_metrics["maximum_drawdown"]
                    - parent_metrics["maximum_drawdown"],
                    "worst_year": combined_metrics["worst_year"]
                    - parent_metrics["worst_year"],
                },
            }
    gates = {
        "all_nine_cagr_gte_20pct": len(results) == 9
        and all(item["combined"]["cagr"] >= 0.20 for item in results.values()),
        "all_nine_mdd_strictly_better_than_v39": len(results) == 9
        and all(
            item["combined"]["maximum_drawdown"]
            < item["v39_parent"]["maximum_drawdown"]
            for item in results.values()
        ),
        "all_nav_positive": bool(output.filter(regex="__.*nav$").gt(0.0).all(axis=None)),
        "nine_fixed_combinations": len(results) == 9,
    }
    metrics = {
        "verdict": (
            "ROBUST_TO_DECLARED_IDLE_COST_STRESSES"
            if all(gates.values())
            else "COST_STRESS_GATE_FAILED"
        ),
        "allocation": {"v39": 0.80, "cash_carry": 0.20, "rebalanced": False},
        "turnover": turnover,
        "combinations": results,
        "gates": gates,
        "same_history_post_result_diagnostic": True,
        "fund_selection_allowed": False,
        "live_trading_allowed": False,
    }
    return output.reset_index(), metrics


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# V42R1 V41 idle-fund cost stress",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        "Fixed 80/20 V41 allocation; no parent market return or trade was changed.",
        "",
        "| Market | Idle cost | CAGR | Sharpe | MDD | Worst year |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in metrics["combinations"].values():
        combined = item["combined"]
        lines.append(
            f"| {item['market_scenario']} | {item['cost_scenario']} | "
            f"{combined['cagr']:.4%} | {combined['sharpe']:.3f} | "
            f"{combined['maximum_drawdown']:.4%} | "
            f"{combined['worst_year']:.4%} |"
        )
    lines.extend(
        [
            "",
            "This is a post-result same-history robustness diagnostic, not independent evidence.",
            "It cannot select a fund or authorize live trading.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(protocol: Protocol) -> Path:
    ledger, metrics = build(protocol)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = _root(protocol.payload["outputs"]["root"])
    output = base.parent / f"{base.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"V42R1 output exists: {output}")
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
            "dates_before_2026": bool(pd.to_datetime(ledger["date"]).dt.year.le(2025).all()),
            "nine_fixed_combinations": len(metrics["combinations"]) == 9,
            "weights_exact": metrics["allocation"]
            == {"v39": 0.80, "cash_carry": 0.20, "rebalanced": False},
            "all_nav_positive": bool(
                ledger.filter(regex="__.*nav$").gt(0.0).all(axis=None)
            ),
            "selection_forbidden": metrics["fund_selection_allowed"] is False,
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"V42R1 audit failed: {audit}")
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
        "same_history_post_result_diagnostic": True,
        "fund_selection_allowed": False,
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
