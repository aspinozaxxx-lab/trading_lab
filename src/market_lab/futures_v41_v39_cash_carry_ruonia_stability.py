"""Evaluate sealed V39 plus idle-RUONIA cash-carry stability blend."""

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
    PROJECT_ROOT / "configs/v41_v39_cash_carry_ruonia_stability_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "4541812897ee7356d7e64ba2ccf953e8ef8e1a16bcd4733d13b77f310507ca82"
)
SCENARIOS: Final[dict[str, tuple[str, str]]] = {
    "primary": ("primary", "primary"),
    "doubled": ("doubled", "doubled"),
    "stress": ("stress", "zero_cashflow_stress"),
}


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    v39_root: Path
    cash_root: Path


def _sha(path: Path) -> str:
    return io_utils.sha256_file(path)


def _root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe V41 parent path: {value}")
    if relative.parts[0].lower() != "runs":
        raise ValueError("V41 parent path must start with runs")
    return PROJECT_ROOT / relative


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V41 config must be an object")
    inheritance = payload["inheritance"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id")
        != "futures_v41_v39_cash_carry_ruonia_stability_v1"
        or payload.get("status")
        != "sealed_before_any_v39_cash_ruonia_combined_equity_or_metric"
        or payload.get("live_trading_allowed") is not False
        or float(inheritance["v39_weight"]) != 0.80
        or float(inheritance["cash_carry_weight"]) != 0.20
        or inheritance["rebalance_after_initial_allocation"] != "never"
        or inheritance["weight_search_after_v40r1"] is not False
    ):
        raise ValueError("V41 protocol drifted")
    v39 = payload["parents"]["v39"]
    cash = payload["parents"]["cash_carry_ruonia"]
    v39_root, cash_root = _root(v39["root"]), _root(cash["root"])
    for section, root in ((v39, v39_root), (cash, cash_root)):
        for key, declaration in section.items():
            if key in {"root", "protocol_sha256"}:
                continue
            path = root / declaration["file"]
            if _sha(path) != declaration["sha256"]:
                raise ValueError(f"V41 parent drifted: {root.name}.{key}")
            if (
                "rows" in declaration
                and path.suffix == ".parquet"
                and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
            ):
                raise ValueError(f"V41 parent rows drifted: {root.name}.{key}")
    identity = json.loads(
        (v39_root / v39["identity"]["file"]).read_text(encoding="utf-8-sig")
    )
    manifest = json.loads(
        (cash_root / cash["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    if (
        identity["protocol_sha256"] != v39["protocol_sha256"]
        or manifest["protocol_sha256"] != cash["protocol_sha256"]
    ):
        raise ValueError("V41 parent protocol identity drifted")
    return Protocol(payload, actual, v39_root, cash_root)


def build(protocol: Protocol) -> tuple[pd.DataFrame, dict[str, Any]]:
    cash_ledger = pd.read_parquet(protocol.cash_root / "daily_ledger.parquet")
    cash_ledger["date"] = pd.to_datetime(cash_ledger["date"], errors="raise")
    cash_indexed = cash_ledger.set_index("date")
    v39_metrics = json.loads(
        (protocol.v39_root / "metrics.json").read_text(encoding="utf-8-sig")
    )
    output: pd.DataFrame | None = None
    scenario_metrics: dict[str, Any] = {}
    for name, (v39_scenario, cash_scenario) in SCENARIOS.items():
        parent = pd.read_parquet(
            protocol.v39_root / f"combined_ledger_{v39_scenario}.parquet"
        )
        parent["session_date"] = pd.to_datetime(parent["session_date"], errors="raise")
        parent_nav = parent.set_index("session_date")["combined_ending_equity"].astype(float)
        parent_nav = parent_nav / float(parent_nav.iloc[0])
        cash_nav = cash_indexed[f"overlay_{cash_scenario}_nav"].astype(float)
        cash_nav = cash_nav / float(cash_nav.iloc[0])
        cash_nav = cash_nav.reindex(parent_nav.index).ffill()
        if cash_nav.isna().any():
            raise ValueError("V41 cash-carry NAV missing on V39 calendar")
        combined = 0.80 * parent_nav + 0.20 * cash_nav
        if output is None:
            output = pd.DataFrame({"session_date": parent_nav.index})
        output[f"v39_{name}_nav"] = parent_nav.to_numpy()
        output[f"cash_carry_ruonia_{name}_nav"] = cash_nav.to_numpy()
        output[f"combined_{name}_nav"] = combined.to_numpy()
        output[f"combined_{name}_return"] = combined.pct_change().fillna(0.0).to_numpy()
        reported = v39_metrics["scenarios"][v39_scenario]["combined"]
        parent_metrics = {
            key: reported[key]
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
        combined_metrics = _metrics(combined)
        scenario_metrics[name] = {
            "v39_parent": parent_metrics,
            "combined": combined_metrics,
            "delta": {
                "cagr": combined_metrics["cagr"] - parent_metrics["cagr"],
                "sharpe": combined_metrics["sharpe"] - parent_metrics["sharpe"],
                "maximum_drawdown": combined_metrics["maximum_drawdown"]
                - parent_metrics["maximum_drawdown"],
                "worst_year": combined_metrics["worst_year"] - parent_metrics["worst_year"],
            },
        }
    assert output is not None
    gates = {
        "all_scenario_cagr_gte_20pct": all(
            item["combined"]["cagr"] >= 0.20 for item in scenario_metrics.values()
        ),
        "all_scenario_mdd_strictly_better": all(
            item["combined"]["maximum_drawdown"]
            < item["v39_parent"]["maximum_drawdown"]
            for item in scenario_metrics.values()
        ),
        "all_scenario_sharpe_not_worse": all(
            item["combined"]["sharpe"] >= item["v39_parent"]["sharpe"]
            for item in scenario_metrics.values()
        ),
        "all_scenario_worst_year_not_worse": all(
            item["combined"]["worst_year"] >= item["v39_parent"]["worst_year"]
            for item in scenario_metrics.values()
        ),
        "primary_positive_years_gte_5": scenario_metrics["primary"]["combined"]
        ["positive_years"]
        >= 5,
    }
    metrics = {
        "verdict": "GO_TO_FORWARD_PORTFOLIO_CONFIRMATION" if all(gates.values()) else "NO_GO",
        "allocation": {"v39": 0.80, "cash_carry_ruonia": 0.20, "rebalanced": False},
        "scenarios": scenario_metrics,
        "gates": gates,
        "live_trading_allowed": False,
        "adaptive_same_history": True,
    }
    return output, metrics


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# V41 frozen V39 + cash-carry idle-RUONIA stability blend",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        "Fixed initial weights: 80% V39, 20% cash-carry RUONIA; no rebalancing.",
        "",
        "| Scenario | CAGR | Sharpe | MDD | Worst year | dCAGR | dSharpe | dMDD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in metrics["scenarios"].items():
        combined, delta = item["combined"], item["delta"]
        lines.append(
            f"| {name} | {combined['cagr']:.4%} | {combined['sharpe']:.3f} | "
            f"{combined['maximum_drawdown']:.4%} | {combined['worst_year']:.4%} | "
            f"{delta['cagr']:+.4%} | {delta['sharpe']:+.3f} | "
            f"{delta['maximum_drawdown']:+.4%} |"
        )
    lines.extend(
        [
            "",
            "This is same-history adaptive evidence, not independent confirmation.",
            "The 50% RUONIA realization instrument and cash-carry execution remain unproved.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(protocol: Protocol) -> Path:
    ledger, metrics = build(protocol)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = _root(protocol.payload["outputs"]["root"])
    output = base.parent / f"{base.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"V41 output exists: {output}")
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
            "weights_exact": metrics["allocation"] == {
                "v39": 0.80,
                "cash_carry_ruonia": 0.20,
                "rebalanced": False,
            },
            "all_nav_positive": bool(ledger.filter(regex="_nav$").gt(0.0).all(axis=None)),
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"V41 audit failed: {audit}")
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
