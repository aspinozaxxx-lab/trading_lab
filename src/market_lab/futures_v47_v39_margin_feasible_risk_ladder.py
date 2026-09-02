"""Evaluate the sealed V47 margin-feasible V39 risk ladder."""

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
    PROJECT_ROOT / "configs/v47_v39_margin_feasible_risk_ladder_v1.yaml"
)
CONFIG_SHA256: Final[str] = (
    "0b3524f46220b3c372de702f04f5979f987974674490ac3662e412a5c330212e"
)
MODES: Final[tuple[str, ...]] = ("stability", "frontier")
SCENARIOS: Final[dict[str, tuple[str, str, float]]] = {
    "primary": ("primary", "overlay_active_cap_primary_nav", 1.00),
    "doubled": ("doubled", "overlay_active_cap_doubled_nav", 1.00),
    "stress": (
        "stress",
        "overlay_active_cap_zero_cashflow_stress_nav",
        1.25,
    ),
    "execution_stress": (
        "stress",
        "overlay_active_cap_delayed_fill_stress_nav",
        1.25,
    ),
}


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
        raise ValueError(f"unsafe V47 parent path: {value}")
    if relative.parts[0].lower() != "runs":
        raise ValueError("V47 parent path must start with runs")
    return PROJECT_ROOT / relative


def _verify_artifacts(section: dict[str, Any], root: Path) -> None:
    for key, declaration in section.items():
        if key in {"root", "protocol_sha256"}:
            continue
        path = root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"V47 parent drifted: {root.name}.{key}")
        if (
            "rows" in declaration
            and path.suffix == ".parquet"
            and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
        ):
            raise ValueError(f"V47 parent rows drifted: {root.name}.{key}")


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V47 config must be an object")
    modes = payload["modes"]
    accounting = payload["accounting"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id")
        != "futures_v47_v39_margin_feasible_risk_ladder_v1"
        or payload.get("status")
        != "sealed_after_margin_only_feasibility_before_any_scaled_return_or_metric"
        or payload.get("live_trading_allowed") is not False
        or float(modes["stability"]["v39_market_pnl_scale"]) != 1.10
        or float(modes["stability"]["broad_carry_cash_fraction"]) != 0.20
        or float(modes["frontier"]["v39_market_pnl_scale"]) != 1.50
        or float(modes["frontier"]["broad_carry_cash_fraction"]) != 0.0
        or modes["select_mode_after_outcome"] is not False
        or accounting["borrowing_forbidden"] is not True
        or accounting["original_v39_collateral_interest_not_double_counted"]
        is not True
    ):
        raise ValueError("V47 protocol drifted")
    v39 = payload["parents"]["v39"]
    carry = payload["parents"]["broad_carry"]
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
        or not all(audit["checks"].values())
    ):
        raise ValueError("V47 parent protocol identity drifted")
    return Protocol(payload, actual, v39_root, carry_root)


def simulate_mode(
    parent: pd.DataFrame,
    carry_nav: pd.Series,
    baseline_nav: pd.Series,
    *,
    market_scale: float,
    carry_fraction: float,
    margin_multiplier: float,
    initial_nav: float,
) -> pd.DataFrame:
    """Rebuild NAV without scaling V39's original collateral interest."""
    frame = parent.copy()
    frame["session_date"] = pd.to_datetime(frame["session_date"], errors="raise")
    frame = frame.sort_values("session_date", ignore_index=True)
    index = pd.DatetimeIndex(frame["session_date"])
    aligned_carry = carry_nav.reindex(index).ffill()
    aligned_baseline = baseline_nav.reindex(index).ffill()
    if aligned_carry.isna().any() or aligned_baseline.isna().any():
        raise ValueError("V47 carry or baseline missing after alignment")
    carry_return = aligned_carry.pct_change().fillna(0.0)
    baseline_return = aligned_baseline.pct_change().fillna(0.0)
    previous_parent_equity = frame["combined_ending_equity"].astype(float).shift(1)
    market_pnl = frame["ending_cash"].astype(float) - frame["starting_cash"].astype(
        float
    )
    market_return = (market_pnl / previous_parent_equity).fillna(0.0)
    prior_margin_fraction = (
        frame["modeled_initial_margin"].astype(float).shift(1)
        / previous_parent_equity
    ).fillna(0.0)
    committed_fraction = (
        market_scale * margin_multiplier * prior_margin_fraction + carry_fraction
    )
    free_cash_fraction = 1.0 - committed_fraction
    if free_cash_fraction.lt(0.0).any():
        raise ValueError("V47 negative free cash would require borrowing")
    scaled_market_return = market_scale * market_return
    collateral_return = free_cash_fraction.to_numpy() * baseline_return.to_numpy()
    allocated_carry_return = carry_fraction * carry_return.to_numpy()
    total_return = (
        scaled_market_return.to_numpy()
        + collateral_return
        + allocated_carry_return
    )
    nav = initial_nav * pd.Series(1.0 + total_return).cumprod()
    return pd.DataFrame(
        {
            "session_date": index,
            "parent_market_return": market_return.to_numpy(),
            "scaled_market_return": scaled_market_return.to_numpy(),
            "prior_margin_fraction": prior_margin_fraction.to_numpy(),
            "committed_fraction": committed_fraction.to_numpy(),
            "free_cash_fraction": free_cash_fraction.to_numpy(),
            "half_ruonia_return": baseline_return.to_numpy(),
            "collateral_return": collateral_return,
            "carry_return": carry_return.to_numpy(),
            "allocated_carry_return": allocated_carry_return,
            "total_return": total_return,
            "nav": nav.to_numpy(),
        }
    )


def _mode_gates(
    mode: str, scenarios: dict[str, Any], minimum_free: float, config: dict[str, Any]
) -> dict[str, bool]:
    declared = config["gates"][mode]
    gates = {
        "all_scenario_cagr": all(
            item["metrics"]["cagr"] >= float(declared["all_scenario_cagr_gte"])
            for item in scenarios.values()
        ),
        "all_scenario_sharpe": all(
            item["metrics"]["sharpe"] >= float(declared["all_scenario_sharpe_gte"])
            for item in scenarios.values()
        ),
        "all_scenario_mdd": all(
            item["metrics"]["maximum_drawdown"]
            <= float(declared["all_scenario_mdd_lte"])
            for item in scenarios.values()
        ),
        "all_scenario_worst_year": all(
            item["metrics"]["worst_year"]
            >= float(declared["all_scenario_worst_year_gte"])
            for item in scenarios.values()
        ),
        "primary_positive_years": scenarios["primary"]["metrics"]["positive_years"]
        >= int(declared["primary_positive_years_gte"]),
        "minimum_stressed_free_cash": minimum_free
        >= float(declared["minimum_stressed_free_cash_fraction_gte"]),
    }
    if mode == "frontier":
        gates["primary_cagr"] = scenarios["primary"]["metrics"]["cagr"] >= float(
            declared["primary_cagr_gte"]
        )
    return gates


def build(protocol: Protocol) -> tuple[pd.DataFrame, dict[str, Any]]:
    carry = pd.read_parquet(protocol.carry_root / "daily_ledger.parquet")
    carry["date"] = pd.to_datetime(carry["date"], errors="raise")
    carry = carry.sort_values("date").set_index("date")
    baseline = (1.0 + carry["half_ruonia_daily_return"].astype(float)).cumprod()
    baseline.iloc[0] = 1.0
    initial_nav = float(protocol.payload["accounting"]["initial_nav_rub"])
    output: pd.DataFrame | None = None
    modes: dict[str, Any] = {}
    for mode in MODES:
        mode_config = protocol.payload["modes"][mode]
        scale = float(mode_config["v39_market_pnl_scale"])
        carry_fraction = float(mode_config["broad_carry_cash_fraction"])
        mode_scenarios: dict[str, Any] = {}
        mode_min_free = 1.0
        for scenario, (v39_name, carry_column, margin_multiplier) in SCENARIOS.items():
            parent = pd.read_parquet(
                protocol.v39_root / f"combined_ledger_{v39_name}.parquet"
            )
            carry_nav = carry[carry_column].astype(float)
            carry_nav = carry_nav / float(carry_nav.iloc[0])
            simulation = simulate_mode(
                parent,
                carry_nav,
                baseline,
                market_scale=scale,
                carry_fraction=carry_fraction,
                margin_multiplier=margin_multiplier,
                initial_nav=initial_nav,
            )
            nav = pd.Series(
                simulation["nav"].to_numpy(),
                index=pd.to_datetime(simulation["session_date"]),
            )
            metrics = _metrics(nav)
            minimum_free = float(simulation["free_cash_fraction"].min())
            mode_min_free = min(mode_min_free, minimum_free)
            mode_scenarios[scenario] = {
                "metrics": metrics,
                "minimum_free_cash_fraction": minimum_free,
                "maximum_committed_fraction": float(
                    simulation["committed_fraction"].max()
                ),
                "margin_multiplier": margin_multiplier,
            }
            if output is None:
                output = pd.DataFrame({"session_date": simulation["session_date"]})
            for column in simulation.columns:
                if column == "session_date":
                    continue
                output[f"{mode}_{scenario}_{column}"] = simulation[column].to_numpy()
        gates = _mode_gates(
            mode, mode_scenarios, mode_min_free, protocol.payload
        )
        modes[mode] = {
            "verdict": "PASS_SAME_HISTORY_RISK_GATE" if all(gates.values()) else "NO_GO",
            "market_scale": scale,
            "carry_cash_fraction": carry_fraction,
            "minimum_free_cash_fraction": mode_min_free,
            "primary_cagr_gte_aspirational_45pct": mode_scenarios["primary"]
            ["metrics"]["cagr"]
            >= float(protocol.payload["gates"]["aspirational_primary_cagr_report_level"]),
            "scenarios": mode_scenarios,
            "gates": gates,
        }
    passes = [name for name, item in modes.items() if item["verdict"].startswith("PASS")]
    metrics = {
        "verdict": "NO_GO" if not passes else "RISK_LADDER_PASSES_SAME_HISTORY_GATES",
        "passing_modes": passes,
        "modes": modes,
        "mode_selection_after_outcome": False,
        "adaptive_same_history": True,
        "live_trading_allowed": False,
    }
    assert output is not None
    return output, metrics


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# V47 margin-feasible V39 risk ladder",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        "| Mode | Scenario | CAGR | Sharpe | MDD | Worst year | Positive years | Min free cash |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, result in metrics["modes"].items():
        for scenario, item in result["scenarios"].items():
            values = item["metrics"]
            lines.append(
                f"| {mode} | {scenario} | {values['cagr']:.4%} | "
                f"{values['sharpe']:.3f} | {values['maximum_drawdown']:.4%} | "
                f"{values['worst_year']:.4%} | {values['positive_years']} | "
                f"{item['minimum_free_cash_fraction']:.2%} |"
            )
    lines.extend(
        [
            "",
            "Both modes were predeclared and remain reported; no winner is selected.",
            "This is same-history normalized risk engineering, not live evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(protocol: Protocol) -> Path:
    ledger, metrics = build(protocol)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = _root(protocol.payload["outputs"]["root"])
    output = base.parent / f"{base.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"V47 output exists: {output}")
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
            "both_modes_present": tuple(metrics["modes"]) == MODES,
            "all_scenarios_present": all(
                tuple(item["scenarios"]) == tuple(SCENARIOS)
                for item in metrics["modes"].values()
            ),
            "no_mode_selection": metrics["mode_selection_after_outcome"] is False,
            "no_negative_free_cash": bool(
                ledger.filter(regex="_free_cash_fraction$").ge(0.0).all(axis=None)
            ),
            "all_nav_positive": bool(
                ledger.filter(regex="_nav$").gt(0.0).all(axis=None)
            ),
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"V47 audit failed: {audit}")
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
