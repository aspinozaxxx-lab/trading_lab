"""Evaluate the sealed V46 self-financing margin-headroom carry overlay."""

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
    PROJECT_ROOT / "configs/v46_v39_margin_headroom_carry_overlay_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "b18ed5bc101772bad3fd2d61d3839213b38f0844fea1378af7848f3bcc461d4b"
)
SCENARIOS: Final[dict[str, tuple[str, str]]] = {
    "primary": ("primary", "overlay_active_cap_primary_nav"),
    "doubled": ("doubled", "overlay_active_cap_doubled_nav"),
    "stress": ("stress", "overlay_active_cap_zero_cashflow_stress_nav"),
    "execution_stress": (
        "stress",
        "overlay_active_cap_delayed_fill_stress_nav",
    ),
}
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
    carry_root: Path


def _sha(path: Path) -> str:
    return io_utils.sha256_file(path)


def _root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe V46 parent path: {value}")
    if relative.parts[0].lower() != "runs":
        raise ValueError("V46 parent path must start with runs")
    return PROJECT_ROOT / relative


def _verify_artifacts(section: dict[str, Any], root: Path) -> None:
    for key, declaration in section.items():
        if key in {"root", "protocol_sha256"}:
            continue
        path = root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"V46 parent drifted: {root.name}.{key}")
        if (
            "rows" in declaration
            and path.suffix == ".parquet"
            and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
        ):
            raise ValueError(f"V46 parent rows drifted: {root.name}.{key}")


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V46 config must be an object")
    overlay = payload["overlay"]
    headroom = payload["headroom"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id")
        != "futures_v46_v39_margin_headroom_carry_overlay_v1"
        or payload.get("status")
        != "sealed_before_any_additive_overlay_equity_or_metric"
        or payload.get("live_trading_allowed") is not False
        or float(overlay["v39_directional_nav_weight"]) != 1.0
        or float(overlay["fixed_initial_carry_cash_fraction"]) != 0.20
        or overlay["rebalance_overlay_after_initial_allocation"] != "never"
        or overlay["no_directional_leverage_added"] is not True
        or overlay["no_weight_search"] is not True
        or float(headroom["minimum_uncommitted_nav_reserve"]) != 0.10
        or float(headroom["full_overlay_requires_prior_margin_fraction_lte"])
        != 0.70
        or headroom["no_partial_scaling"] is not True
    ):
        raise ValueError("V46 protocol drifted")
    parents = payload["parents"]
    v39, carry = parents["v39"], parents["broad_carry"]
    v39_root, carry_root = _root(v39["root"]), _root(carry["root"])
    _verify_artifacts(v39, v39_root)
    _verify_artifacts(carry, carry_root)
    identity = json.loads(
        (v39_root / v39["identity"]["file"]).read_text(encoding="utf-8-sig")
    )
    manifest = json.loads(
        (carry_root / carry["manifest"]["file"]).read_text(encoding="utf-8-sig")
    )
    audit = json.loads(
        (carry_root / carry["audit"]["file"]).read_text(encoding="utf-8-sig")
    )
    if (
        identity["protocol_sha256"] != v39["protocol_sha256"]
        or manifest["protocol_sha256"] != carry["protocol_sha256"]
        or manifest["live_trading_allowed"] is not False
        or not all(audit["checks"].values())
    ):
        raise ValueError("V46 parent protocol identity drifted")
    return Protocol(payload, actual, v39_root, carry_root)


def _reported_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload[key] for key in METRIC_KEYS}


def simulate_overlay(
    parent: pd.DataFrame,
    carry_nav: pd.Series,
    baseline_nav: pd.Series,
    *,
    fraction: float,
    headroom_threshold: float,
) -> pd.DataFrame:
    """Add only frozen carry excess over displaced cash on causally free headroom."""
    parent = parent.copy()
    parent["session_date"] = pd.to_datetime(parent["session_date"], errors="raise")
    parent = parent.sort_values("session_date", ignore_index=True)
    index = pd.DatetimeIndex(parent["session_date"])
    v39_nav = parent.set_index("session_date")["combined_ending_equity"].astype(float)
    v39_nav = v39_nav / float(v39_nav.iloc[0])
    aligned_carry = carry_nav.reindex(index).ffill()
    aligned_baseline = baseline_nav.reindex(index).ffill()
    if aligned_carry.isna().any() or aligned_baseline.isna().any():
        raise ValueError("V46 carry or baseline NAV missing after alignment")
    carry_returns = aligned_carry.pct_change().fillna(0.0)
    baseline_returns = aligned_baseline.pct_change().fillna(0.0)
    margin_fraction = (
        parent["modeled_initial_margin"].astype(float)
        / parent["combined_ending_equity"].astype(float)
    )
    prior_margin_fraction = margin_fraction.shift(1)
    eligible = prior_margin_fraction.le(headroom_threshold)
    eligible.iloc[0] = False
    carry_value = fraction
    displaced_value = fraction
    carry_values: list[float] = []
    displaced_values: list[float] = []
    combined_values: list[float] = []
    for offset, date in enumerate(index):
        if bool(eligible.iloc[offset]):
            carry_value *= 1.0 + float(carry_returns.loc[date])
        else:
            carry_value *= 1.0 + float(baseline_returns.loc[date])
        displaced_value *= 1.0 + float(baseline_returns.loc[date])
        combined = float(v39_nav.loc[date]) + carry_value - displaced_value
        carry_values.append(carry_value)
        displaced_values.append(displaced_value)
        combined_values.append(combined)
    return pd.DataFrame(
        {
            "session_date": index,
            "v39_nav": v39_nav.to_numpy(),
            "prior_margin_fraction": prior_margin_fraction.to_numpy(),
            "headroom_eligible": eligible.to_numpy(dtype=bool),
            "carry_overlay_value": carry_values,
            "displaced_cash_value": displaced_values,
            "carry_excess_value": (
                pd.Series(carry_values) - pd.Series(displaced_values)
            ).to_numpy(),
            "combined_nav": combined_values,
        }
    )


def build(protocol: Protocol) -> tuple[pd.DataFrame, dict[str, Any]]:
    carry = pd.read_parquet(protocol.carry_root / "daily_ledger.parquet")
    carry["date"] = pd.to_datetime(carry["date"], errors="raise")
    carry = carry.sort_values("date").set_index("date")
    baseline = (1.0 + carry["half_ruonia_daily_return"].astype(float)).cumprod()
    baseline.iloc[0] = 1.0
    carry_metrics = json.loads(
        (protocol.carry_root / "metrics.json").read_text(encoding="utf-8-sig")
    )
    v39_metrics = json.loads(
        (protocol.v39_root / "metrics.json").read_text(encoding="utf-8-sig")
    )
    fraction = float(protocol.payload["overlay"]["fixed_initial_carry_cash_fraction"])
    threshold = float(
        protocol.payload["headroom"][
            "full_overlay_requires_prior_margin_fraction_lte"
        ]
    )
    output: pd.DataFrame | None = None
    scenarios: dict[str, Any] = {}
    for name, (v39_scenario, carry_column) in SCENARIOS.items():
        parent = pd.read_parquet(
            protocol.v39_root / f"combined_ledger_{v39_scenario}.parquet"
        )
        carry_nav = carry[carry_column].astype(float)
        carry_nav = carry_nav / float(carry_nav.iloc[0])
        simulation = simulate_overlay(
            parent,
            carry_nav,
            baseline,
            fraction=fraction,
            headroom_threshold=threshold,
        )
        combined = pd.Series(
            simulation["combined_nav"].to_numpy(),
            index=pd.to_datetime(simulation["session_date"]),
        )
        combined_metrics = _metrics(combined)
        parent_metrics = _reported_metrics(
            v39_metrics["scenarios"][v39_scenario]["combined"]
        )
        scenarios[name] = {
            "v39_parent": parent_metrics,
            "combined": combined_metrics,
            "carry_parent_view": _reported_metrics(
                carry_metrics["views"]["active_cap"][
                    SCENARIOS[name][1]
                    .removeprefix("overlay_active_cap_")
                    .removesuffix("_nav")
                ]["overlay"]
            ),
            "headroom": {
                "eligible_sessions": int(simulation["headroom_eligible"].sum()),
                "sleep_sessions": int((~simulation["headroom_eligible"]).sum()),
                "maximum_prior_margin_fraction": float(
                    simulation["prior_margin_fraction"].max()
                ),
            },
            "delta_vs_v39": {
                key: combined_metrics[key] - parent_metrics[key]
                for key in ("cagr", "sharpe", "maximum_drawdown", "worst_year")
            },
        }
        if output is None:
            output = pd.DataFrame({"session_date": simulation["session_date"]})
        for column in simulation.columns:
            if column == "session_date":
                continue
            output[f"{name}_{column}"] = simulation[column].to_numpy()
    gates = {
        "all_scenario_cagr_gte_v39": all(
            item["combined"]["cagr"] >= item["v39_parent"]["cagr"]
            for item in scenarios.values()
        ),
        "all_scenario_sharpe_gte_v39": all(
            item["combined"]["sharpe"] >= item["v39_parent"]["sharpe"]
            for item in scenarios.values()
        ),
        "all_scenario_mdd_lte_v39": all(
            item["combined"]["maximum_drawdown"]
            <= item["v39_parent"]["maximum_drawdown"]
            for item in scenarios.values()
        ),
        "all_scenario_worst_year_gte_v39": all(
            item["combined"]["worst_year"] >= item["v39_parent"]["worst_year"]
            for item in scenarios.values()
        ),
        "primary_positive_years_gte_5": scenarios["primary"]["combined"]
        ["positive_years"]
        >= 5,
        "all_headroom_checks_true": all(
            item["headroom"]["maximum_prior_margin_fraction"] <= threshold
            for item in scenarios.values()
        ),
    }
    metrics = {
        "verdict": (
            "IMPROVES_V39_GO_TO_FORWARD_PORTFOLIO_CONFIRMATION"
            if all(gates.values())
            else "NO_GO"
        ),
        "allocation": {
            "v39_directional_weight": 1.0,
            "carry_cash_fraction": fraction,
            "rebalanced": False,
            "cash_baseline_displaced": "half_ruonia",
        },
        "scenarios": scenarios,
        "gates": gates,
        "adaptive_same_history": True,
        "live_trading_allowed": False,
    }
    assert output is not None
    return output, metrics


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# V46 V39 self-financing margin-headroom carry overlay",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        "100% V39 plus fixed 20% free-cash carry; only excess over displaced half-RUONIA is added.",
        "",
        "| Scenario | CAGR | Sharpe | MDD | Worst year | dCAGR | dSharpe | dMDD | Headroom max |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in metrics["scenarios"].items():
        combined, delta = item["combined"], item["delta_vs_v39"]
        lines.append(
            f"| {name} | {combined['cagr']:.4%} | {combined['sharpe']:.3f} | "
            f"{combined['maximum_drawdown']:.4%} | {combined['worst_year']:.4%} | "
            f"{delta['cagr']:+.4%} | {delta['sharpe']:+.3f} | "
            f"{delta['maximum_drawdown']:+.4%} | "
            f"{item['headroom']['maximum_prior_margin_fraction']:.2%} |"
        )
    lines.extend(
        [
            "",
            "The accounting is self-financing but still uses historical proxy margin "
            "and carry execution.",
            "This is same-history portfolio engineering; live trading remains forbidden.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(protocol: Protocol) -> Path:
    ledger, metrics = build(protocol)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = _root(protocol.payload["outputs"]["root"])
    output = base.parent / f"{base.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"V46 output exists: {output}")
    output.mkdir(parents=True)
    ledger_path = output / "combined_ledger.parquet"
    metrics_path = output / "metrics.json"
    report_path = output / "report.md"
    io_utils._write_parquet(ledger_path, ledger)
    write_json(metrics_path, metrics)
    atomic_write_bytes(report_path, _report(metrics).encode("utf-8-sig"))
    audit = {
        "checks": {
            "protocol_sha_exact": _sha(CONFIG_PATH) == protocol.config_sha256,
            "dates_before_2026": bool(
                pd.to_datetime(ledger["session_date"]).lt("2026-01-01").all()
            ),
            "allocation_exact": metrics["allocation"]
            == {
                "v39_directional_weight": 1.0,
                "carry_cash_fraction": 0.20,
                "rebalanced": False,
                "cash_baseline_displaced": "half_ruonia",
            },
            "all_scenarios_present": tuple(metrics["scenarios"])
            == tuple(SCENARIOS),
            "headroom_strictly_prior": all(
                pd.isna(ledger[f"{name}_prior_margin_fraction"].iloc[0])
                for name in SCENARIOS
            ),
            "all_nav_positive": bool(
                ledger.filter(regex="_combined_nav$").gt(0.0).all(axis=None)
            ),
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"V46 audit failed: {audit}")
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
