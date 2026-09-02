"""Evaluate sealed V39 plus broad cash-carry idle-RUONIA stability blends."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab.futures import moex_stock_futures_cash_carry_source as io_utils
from market_lab.futures_v40_v39_cash_carry_stability import _metrics
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/v43_v39_broad_carry_ruonia_stability_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "e816f05f94739ae5b1604cb91bfc3066023aea37f6497edd59733ed5f4ab6421"
)
VIEWS: Final[tuple[str, ...]] = ("equal_sleeves", "active_cap")
SCENARIOS: Final[dict[str, tuple[str, str, str]]] = {
    "primary": ("primary", "primary", "primary"),
    "doubled": ("doubled", "doubled", "doubled"),
    "stress": ("stress", "zero_cashflow_stress", "stress"),
    "execution_stress": ("stress", "delayed_fill_stress", "stress"),
}
BENCHMARK_SCENARIOS: Final[tuple[str, ...]] = ("primary", "doubled", "stress")
METRIC_KEYS: Final[tuple[str, ...]] = (
    "total_return",
    "cagr",
    "sharpe",
    "maximum_drawdown",
    "annual_returns",
    "positive_years",
    "worst_year",
)


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    v39_root: Path
    cash_root: Path
    benchmark_root: Path


def _sha(path: Path) -> str:
    return io_utils.sha256_file(path)


def _root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe V43 parent path: {value}")
    if relative.parts[0].lower() != "runs":
        raise ValueError("V43 parent path must start with runs")
    return PROJECT_ROOT / relative


def _verify_artifacts(section: dict[str, Any], root: Path) -> None:
    for key, declaration in section.items():
        if key in {"root", "protocol_sha256"}:
            continue
        path = root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"V43 parent drifted: {root.name}.{key}")
        if (
            "rows" in declaration
            and path.suffix == ".parquet"
            and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
        ):
            raise ValueError(f"V43 parent rows drifted: {root.name}.{key}")


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V43 config must be an object")
    inheritance = payload["inheritance"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id")
        != "futures_v43_v39_broad_carry_ruonia_stability_v1"
        or payload.get("status")
        != "sealed_before_any_v39_broad_carry_combined_equity_or_metric"
        or payload.get("live_trading_allowed") is not False
        or tuple(payload["views"]) != VIEWS
        or float(inheritance["v39_weight"]) != 0.80
        or float(inheritance["broad_cash_carry_weight"]) != 0.20
        or inheritance["rebalance_after_initial_allocation"] != "never"
        or inheritance["weight_search_after_v41"] is not False
        or inheritance["view_selection_after_outcome"] != "forbidden"
    ):
        raise ValueError("V43 protocol drifted")
    parents = payload["parents"]
    v39 = parents["v39"]
    cash = parents["broad_cash_carry_ruonia"]
    benchmark = parents["v41_benchmark"]
    roots = tuple(_root(section["root"]) for section in (v39, cash, benchmark))
    for section, root in zip((v39, cash, benchmark), roots, strict=True):
        _verify_artifacts(section, root)
    v39_identity = json.loads(
        (roots[0] / v39["identity"]["file"]).read_text(encoding="utf-8-sig")
    )
    cash_manifest = json.loads(
        (roots[1] / cash["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    benchmark_manifest = json.loads(
        (roots[2] / benchmark["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    identities = (
        v39_identity["protocol_sha256"] == v39["protocol_sha256"],
        cash_manifest["protocol_sha256"] == cash["protocol_sha256"],
        benchmark_manifest["protocol_sha256"] == benchmark["protocol_sha256"],
    )
    if not all(identities):
        raise ValueError("V43 parent protocol identity drifted")
    return Protocol(payload, actual, roots[0], roots[1], roots[2])


def _reported_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload[key] for key in METRIC_KEYS}


def _not_worse_than_benchmark(item: dict[str, Any]) -> bool:
    combined = item["combined"]
    benchmark = item["v41_benchmark"]
    return bool(
        combined["cagr"] >= benchmark["cagr"]
        and combined["sharpe"] >= benchmark["sharpe"]
        and combined["maximum_drawdown"] <= benchmark["maximum_drawdown"]
        and combined["worst_year"] >= benchmark["worst_year"]
    )


def build(protocol: Protocol) -> tuple[pd.DataFrame, dict[str, Any]]:
    cash_ledger = pd.read_parquet(protocol.cash_root / "daily_ledger.parquet")
    cash_ledger["date"] = pd.to_datetime(cash_ledger["date"], errors="raise")
    cash_indexed = cash_ledger.set_index("date")
    v39_metrics = json.loads(
        (protocol.v39_root / "metrics.json").read_text(encoding="utf-8-sig")
    )
    v41_metrics = json.loads(
        (protocol.benchmark_root / "metrics.json").read_text(encoding="utf-8-sig")
    )
    output: pd.DataFrame | None = None
    views: dict[str, Any] = {}
    for view in VIEWS:
        scenario_metrics: dict[str, Any] = {}
        for name, (v39_scenario, cash_scenario, benchmark_scenario) in SCENARIOS.items():
            parent = pd.read_parquet(
                protocol.v39_root / f"combined_ledger_{v39_scenario}.parquet"
            )
            parent["session_date"] = pd.to_datetime(
                parent["session_date"], errors="raise"
            )
            parent_nav = parent.set_index("session_date")[
                "combined_ending_equity"
            ].astype(float)
            parent_nav = parent_nav / float(parent_nav.iloc[0])
            cash_column = f"overlay_{view}_{cash_scenario}_nav"
            cash_nav = cash_indexed[cash_column].astype(float)
            cash_nav = cash_nav / float(cash_nav.iloc[0])
            cash_nav = cash_nav.reindex(parent_nav.index).ffill()
            if cash_nav.isna().any():
                raise ValueError(f"V43 cash NAV missing: {view}.{name}")
            combined = 0.80 * parent_nav + 0.20 * cash_nav
            if output is None:
                output = pd.DataFrame({"session_date": parent_nav.index})
            output[f"v39_{view}_{name}_nav"] = parent_nav.to_numpy()
            output[f"broad_carry_{view}_{name}_nav"] = cash_nav.to_numpy()
            output[f"combined_{view}_{name}_nav"] = combined.to_numpy()
            output[f"combined_{view}_{name}_return"] = (
                combined.pct_change().fillna(0.0).to_numpy()
            )
            parent_metrics = _reported_metrics(
                v39_metrics["scenarios"][v39_scenario]["combined"]
            )
            benchmark_metrics = _reported_metrics(
                v41_metrics["scenarios"][benchmark_scenario]["combined"]
            )
            combined_metrics = _metrics(combined)
            scenario_metrics[name] = {
                "v39_parent": parent_metrics,
                "v41_benchmark": benchmark_metrics,
                "combined": combined_metrics,
                "delta_vs_v39": {
                    key: combined_metrics[key] - parent_metrics[key]
                    for key in ("cagr", "sharpe", "maximum_drawdown", "worst_year")
                },
                "delta_vs_v41": {
                    key: combined_metrics[key] - benchmark_metrics[key]
                    for key in ("cagr", "sharpe", "maximum_drawdown", "worst_year")
                },
            }
        gates = {
            "all_four_cagr_gte_20pct": all(
                item["combined"]["cagr"] >= 0.20
                for item in scenario_metrics.values()
            ),
            "all_four_mdd_strictly_better_than_v39": all(
                item["combined"]["maximum_drawdown"]
                < item["v39_parent"]["maximum_drawdown"]
                for item in scenario_metrics.values()
            ),
            "all_four_sharpe_not_worse_than_v39": all(
                item["combined"]["sharpe"] >= item["v39_parent"]["sharpe"]
                for item in scenario_metrics.values()
            ),
            "all_four_worst_year_not_worse_than_v39": all(
                item["combined"]["worst_year"] >= item["v39_parent"]["worst_year"]
                for item in scenario_metrics.values()
            ),
            "primary_positive_years_gte_5": scenario_metrics["primary"]["combined"]
            ["positive_years"]
            >= 5,
        }
        improves_v41 = all(
            _not_worse_than_benchmark(scenario_metrics[name])
            for name in BENCHMARK_SCENARIOS
        )
        views[view] = {
            "verdict": (
                "GO_TO_FORWARD_PORTFOLIO_CONFIRMATION"
                if all(gates.values())
                else "NO_GO"
            ),
            "improves_v41_all_four_metrics": improves_v41,
            "scenarios": scenario_metrics,
            "gates": gates,
        }
    any_forward = any(
        item["verdict"] == "GO_TO_FORWARD_PORTFOLIO_CONFIRMATION"
        for item in views.values()
    )
    any_improves = any(item["improves_v41_all_four_metrics"] for item in views.values())
    verdict = "NO_GO"
    if any_forward:
        verdict = "GO_TO_FORWARD_PORTFOLIO_CONFIRMATION"
    if any_forward and any_improves:
        verdict = "IMPROVES_V41_AND_GO_TO_FORWARD_PORTFOLIO_CONFIRMATION"
    metrics = {
        "verdict": verdict,
        "allocation": {"v39": 0.80, "broad_cash_carry_ruonia": 0.20, "rebalanced": False},
        "views": views,
        "view_selection_after_outcome": False,
        "live_trading_allowed": False,
        "adaptive_same_history": True,
    }
    assert output is not None
    return output, metrics


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# V43 frozen V39 + broad cash-carry idle-RUONIA stability blend",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        "Fixed initial weights: 80% V39, 20% broad carry; no rebalancing or view selection.",
        "",
        "| View | Scenario | CAGR | Sharpe | MDD | Worst year | "
        "dCAGR vs V41 | dSharpe vs V41 | dMDD vs V41 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for view, view_result in metrics["views"].items():
        for name, item in view_result["scenarios"].items():
            combined, delta = item["combined"], item["delta_vs_v41"]
            lines.append(
                f"| {view} | {name} | {combined['cagr']:.4%} | "
                f"{combined['sharpe']:.3f} | {combined['maximum_drawdown']:.4%} | "
                f"{combined['worst_year']:.4%} | {delta['cagr']:+.4%} | "
                f"{delta['sharpe']:+.3f} | {delta['maximum_drawdown']:+.4%} |"
            )
    lines.extend(
        [
            "",
            "Both views were predeclared and remain separate; this run does not select one.",
            "This is same-history adaptive evidence, not independent confirmation.",
            "Historical bid/ask execution and the 50% RUONIA instrument remain unproved.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(protocol: Protocol) -> Path:
    ledger, metrics = build(protocol)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = _root(protocol.payload["outputs"]["root"])
    output = base.parent / f"{base.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"V43 output exists: {output}")
    output.mkdir(parents=True)
    ledger_path = output / "combined_ledger.parquet"
    io_utils._write_parquet(ledger_path, ledger)
    metrics_path = output / "metrics.json"
    write_json(metrics_path, metrics)
    report_path = output / "report.md"
    atomic_write_bytes(report_path, _report(metrics).encode("utf-8-sig"))
    audit = {
        "checks": {
            "protocol_sha_exact": _sha(CONFIG_PATH) == protocol.config_sha256,
            "dates_before_2026": bool(
                pd.to_datetime(ledger["session_date"]).dt.year.le(2025).all()
            ),
            "weights_exact": metrics["allocation"]
            == {"v39": 0.80, "broad_cash_carry_ruonia": 0.20, "rebalanced": False},
            "both_views_present": tuple(metrics["views"]) == VIEWS,
            "all_scenarios_present": all(
                tuple(item["scenarios"]) == tuple(SCENARIOS)
                for item in metrics["views"].values()
            ),
            "no_view_selection": metrics["view_selection_after_outcome"] is False,
            "all_nav_positive": bool(ledger.filter(regex="_nav$").gt(0.0).all(axis=None)),
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"V43 audit failed: {audit}")
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
