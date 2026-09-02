"""Replay V47 with exact integer contracts, capacity and margin admission."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal

import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v15_levered_ruonia_collateral as v15
from market_lab import futures_v26_stlfsi_levered_ruonia_capacity as v26
from market_lab import futures_v27_key_rate_extreme_governor as v27
from market_lab.futures import moex_stock_futures_cash_carry_source as io_utils
from market_lab.futures import portfolio_ledger as ledger_engine
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult
from market_lab.futures_v40_v39_cash_carry_stability import _metrics
from market_lab.io_utils import atomic_write_bytes, write_json

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/v48_v47_exact_integer_execution_v1.yaml"
CONFIG_SHA256: Final[str] = (
    "3b7ae0e4411c2691564491491dc6ef66c623f27cf89c6cd08c33387bd26e5e4b"
)
MODES: Final[tuple[str, ...]] = ("stability", "frontier")
SCENARIOS: Final[tuple[str, ...]] = (
    "primary",
    "doubled",
    "stress",
    "execution_stress",
)
UNIQUE_FUTURES_SCENARIOS: Final[tuple[str, ...]] = ("primary", "doubled", "stress")
_BASE_TARGET_NORMALIZER = ledger_engine._normalize_targets


@dataclass(frozen=True, slots=True)
class Protocol:
    payload: dict[str, Any]
    config_sha256: str
    v39_root: Path
    benchmark_root: Path
    carry_root: Path


@dataclass(frozen=True, slots=True)
class ScaledLedgerConfig:
    initial_cash: float
    expected_assets: tuple[str, ...]
    maximum_gross_notional_multiple: float
    initial_margin_buffer_multiplier: float
    maximum_participation: float
    slippage_ticks: Literal[1, 2, 4]
    fee_multiplier: Literal[1.0, 2.0]
    execution_atomicity: Literal["asset"] = "asset"
    terminal_policy: Literal["carry"] = "carry"
    unexecutable_target_policy: Literal["cancel_and_clip"] = "cancel_and_clip"

    def __post_init__(self) -> None:
        if (
            self.initial_cash != v12.INITIAL_CASH
            or self.expected_assets != v12.ASSETS
            or not 2.0 <= self.maximum_gross_notional_multiple <= 3.0
            or not 2.0 <= self.initial_margin_buffer_multiplier <= 2.5
            or self.maximum_participation != v12.MAXIMUM_PARTICIPATION
            or self.slippage_ticks not in {1, 2, 4}
            or self.fee_multiplier not in {1.0, 2.0}
        ):
            raise ValueError("V48 scaled ledger settings drifted")


def _sha(path: Path) -> str:
    return io_utils.sha256_file(path)


def _root(value: str) -> Path:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"unsafe V48 parent path: {value}")
    if relative.parts[0].lower() != "runs":
        raise ValueError("V48 parent path must start with runs")
    return PROJECT_ROOT / relative


def _verify_artifacts(section: dict[str, Any], root: Path) -> None:
    for key, declaration in section.items():
        if key in {"root", "protocol_sha256"}:
            continue
        path = root / declaration["file"]
        if _sha(path) != declaration["sha256"]:
            raise ValueError(f"V48 parent drifted: {root.name}.{key}")
        if (
            "rows" in declaration
            and path.suffix == ".parquet"
            and pq.ParquetFile(path).metadata.num_rows != int(declaration["rows"])
        ):
            raise ValueError(f"V48 parent rows drifted: {root.name}.{key}")


def load_protocol() -> Protocol:
    actual = _sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V48 config must be an object")
    modes = payload["modes"]
    execution = payload["execution"]
    if (
        actual != CONFIG_SHA256
        or declared != actual
        or payload.get("protocol_id") != "futures_v48_v47_exact_integer_execution_v1"
        or payload.get("status") != "sealed_before_any_scaled_exact_order_position_or_pnl"
        or payload.get("live_trading_allowed") is not False
        or float(modes["stability"]["mapped_target_multiplier"]) != 1.10
        or float(modes["stability"]["maximum_gross_notional_multiple"]) != 2.20
        or float(modes["stability"]["initial_margin_buffer_multiplier"]) != 2.50
        or float(modes["frontier"]["mapped_target_multiplier"]) != 1.50
        or float(modes["frontier"]["maximum_gross_notional_multiple"]) != 3.00
        or float(modes["frontier"]["initial_margin_buffer_multiplier"]) != 2.00
        or modes["select_mode_after_outcome"] is not False
        or float(execution["maximum_lagged_volume_participation"]) != 0.01
        or execution["margin_or_gross_limit_bypass_forbidden"] is not True
    ):
        raise ValueError("V48 protocol drifted")
    parents = payload["parents"]
    sections = (parents["v39"], parents["v47_benchmark"], parents["broad_carry"])
    roots = tuple(_root(section["root"]) for section in sections)
    for section, root in zip(sections, roots, strict=True):
        _verify_artifacts(section, root)
    v39_identity = json.loads(
        (roots[0] / parents["v39"]["identity"]["file"]).read_text(
            encoding="utf-8-sig"
        )
    )
    benchmark_manifest = json.loads(
        (roots[1] / parents["v47_benchmark"]["manifest"]["file"]).read_text(
            encoding="utf-8-sig"
        )
    )
    carry_manifest = json.loads(
        (roots[2] / parents["broad_carry"]["manifest"]["file"]).read_text(
            encoding="utf-8-sig"
        )
    )
    if (
        v39_identity["protocol_sha256"] != parents["v39"]["protocol_sha256"]
        or benchmark_manifest["protocol_sha256"]
        != parents["v47_benchmark"]["protocol_sha256"]
        or carry_manifest["protocol_sha256"]
        != parents["broad_carry"]["protocol_sha256"]
    ):
        raise ValueError("V48 parent protocol identity drifted")
    return Protocol(payload, actual, roots[0], roots[1], roots[2])


def scale_targets(targets: pd.DataFrame, multiplier: float, mode: str) -> pd.DataFrame:
    output = targets.copy()
    output["v39_target_weight"] = pd.to_numeric(
        output["target_weight"], errors="raise"
    ).astype(float)
    output["target_weight"] = output["v39_target_weight"] * multiplier
    output["v48_mode"] = mode
    output["provenance"] = (
        output["provenance"].astype("string")
        + f"|v48_exact_target_multiplier_{multiplier:.2f}"
    )
    if not output.loc[
        output["v39_target_weight"].eq(0.0), "target_weight"
    ].eq(0.0).all():
        raise ValueError("V48 scaling changed a V39 zero target")
    changed_sign = (
        output.loc[output["v39_target_weight"].ne(0.0), "target_weight"]
        * output.loc[output["v39_target_weight"].ne(0.0), "v39_target_weight"]
    ).le(0.0)
    if changed_sign.any():
        raise ValueError("V48 scaling changed target direction")
    return output


def run_scaled_ledger(
    market: pd.DataFrame,
    targets: pd.DataFrame,
    config: ScaledLedgerConfig,
) -> FuturesPortfolioLedgerResult:
    maximum_gross = float(config.maximum_gross_notional_multiple)

    def normalize(
        frame: pd.DataFrame,
        calendar: pd.DatetimeIndex,
        expected_assets: tuple[str, ...],
    ) -> pd.DataFrame:
        scaled = frame.copy()
        scaled["target_weight"] = (
            pd.to_numeric(scaled["target_weight"], errors="raise").astype(float)
            / maximum_gross
        )
        normalized = _BASE_TARGET_NORMALIZER(scaled, calendar, expected_assets)
        normalized["target_weight"] = normalized["target_weight"] * maximum_gross
        return normalized

    original = ledger_engine._normalize_targets
    if original is not _BASE_TARGET_NORMALIZER:
        raise RuntimeError("V48 refuses nested target normalization")
    ledger_engine._normalize_targets = normalize
    try:
        return ledger_engine.run_futures_portfolio_ledger(market, targets, config)
    finally:
        ledger_engine._normalize_targets = original


def combine_with_carry_excess(
    exact_nav: pd.Series,
    carry_nav: pd.Series,
    baseline_nav: pd.Series,
    fraction: float,
) -> pd.Series:
    carry = carry_nav.reindex(exact_nav.index).ffill()
    baseline = baseline_nav.reindex(exact_nav.index).ffill()
    if carry.isna().any() or baseline.isna().any():
        raise ValueError("V48 carry alignment missing")
    carry = carry / float(carry.iloc[0])
    baseline = baseline / float(baseline.iloc[0])
    normalized_exact = exact_nav / float(exact_nav.iloc[0])
    return normalized_exact + fraction * (carry - baseline)


def _prepare_inputs() -> tuple[pd.DataFrame, v15.RuoniaVerification]:
    verified = v27.verify_inputs(v27.load_protocol())
    v26_protocol = v26.load_protocol()
    observations = pd.read_parquet(
        verified.paths["contract_observations"],
        columns=v26_protocol["inputs"]["contract_observations"]["allowed_columns"],
    )
    specs = pd.read_parquet(
        verified.paths["spec_proxy"],
        columns=v26_protocol["inputs"]["spec_proxy"]["allowed_columns"],
    )
    ruonia_frame = pd.read_parquet(
        verified.paths["cbr_panel"],
        columns=v26_protocol["inputs"]["cbr_panel"]["allowed_columns"],
        filters=[("series_id", "==", "ruonia")],
    )
    market = v12.build_execution_market(observations, specs)
    dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"]).drop_duplicates().sort_values()
    )
    predecessor = dates[dates < v12.OOS_START].max()
    market = market.loc[
        pd.to_datetime(market["session_date"]).between(predecessor, v12.OOS_END)
    ].copy()
    return market, v15.verify_ruonia(ruonia_frame)


def _mode_gates(mode: str, scenarios: dict[str, Any], config: dict[str, Any]) -> dict[str, bool]:
    declared = config["gates"][mode]
    shared = config["gates"]["shared"]
    gates = {
        "execution_complete": all(
            item["futures"]["execution_complete"] is True
            for item in scenarios.values()
        ),
        "zero_critical_failures": all(
            int(item["futures"]["critical_failure_count"]) == 0
            for item in scenarios.values()
        ),
        "zero_unresolved_halts": all(
            int(item["futures"]["unresolved_halt_count"]) == 0
            for item in scenarios.values()
        ),
        "maximum_participation": all(
            float(item["futures"]["maximum_participation"])
            <= float(shared["maximum_participation_lte"]) + 1e-12
            for item in scenarios.values()
        ),
        "all_nav_positive": all(
            item["combined"]["minimum_nav"] > 0.0 for item in scenarios.values()
        ),
        "all_scenario_cagr": all(
            item["combined"]["cagr"] >= float(declared["all_scenario_cagr_gte"])
            for item in scenarios.values()
        ),
        "all_scenario_sharpe": all(
            item["combined"]["sharpe"] >= float(declared["all_scenario_sharpe_gte"])
            for item in scenarios.values()
        ),
        "all_scenario_mdd": all(
            item["combined"]["maximum_drawdown"]
            <= float(declared["all_scenario_mdd_lte"])
            for item in scenarios.values()
        ),
        "all_scenario_worst_year": all(
            item["combined"]["worst_year"]
            >= float(declared["all_scenario_worst_year_gte"])
            for item in scenarios.values()
        ),
        "primary_positive_years": scenarios["primary"]["combined"]["positive_years"]
        >= int(declared["primary_positive_years_gte"]),
    }
    if mode == "frontier":
        gates["primary_cagr"] = scenarios["primary"]["combined"]["cagr"] >= float(
            declared["primary_cagr_gte"]
        )
    return gates


def build(
    protocol: Protocol,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
]:
    market, ruonia = _prepare_inputs()
    base_targets = pd.read_parquet(protocol.v39_root / "mapped_targets.parquet")
    carry = pd.read_parquet(protocol.carry_root / "daily_ledger.parquet")
    carry["date"] = pd.to_datetime(carry["date"], errors="raise")
    carry = carry.sort_values("date").set_index("date")
    baseline = (1.0 + carry["half_ruonia_daily_return"].astype(float)).cumprod()
    baseline.iloc[0] = 1.0
    settings = v12._scenario_settings(v27.load_protocol())
    benchmark = json.loads(
        (protocol.benchmark_root / "metrics.json").read_text(encoding="utf-8-sig")
    )
    ledger_output: pd.DataFrame | None = None
    orders: list[pd.DataFrame] = []
    positions: list[pd.DataFrame] = []
    scaled_target_frames: list[pd.DataFrame] = []
    modes: dict[str, Any] = {}
    for mode in MODES:
        mode_config = protocol.payload["modes"][mode]
        targets = scale_targets(
            base_targets,
            float(mode_config["mapped_target_multiplier"]),
            mode,
        )
        gross = targets.groupby("effective_date")["target_weight"].apply(
            lambda values: values.abs().sum()
        )
        if gross.max() > float(mode_config["maximum_gross_notional_multiple"]) + 1e-12:
            raise ValueError(f"V48 {mode} scaled target exceeds sealed gross")
        scaled_target_frames.append(targets)
        futures_results: dict[str, FuturesPortfolioLedgerResult] = {}
        collateral_results: dict[str, v15.CollateralEvaluation] = {}
        for scenario in UNIQUE_FUTURES_SCENARIOS:
            scenario_settings = settings[scenario]
            ledger_config = ScaledLedgerConfig(
                initial_cash=v12.INITIAL_CASH,
                expected_assets=v12.ASSETS,
                maximum_gross_notional_multiple=float(
                    mode_config["maximum_gross_notional_multiple"]
                ),
                initial_margin_buffer_multiplier=float(
                    mode_config["initial_margin_buffer_multiplier"]
                ),
                maximum_participation=v12.MAXIMUM_PARTICIPATION,
                slippage_ticks=int(scenario_settings["slippage_ticks"]),
                fee_multiplier=float(scenario_settings["fee_multiplier"]),
            )
            result = run_scaled_ledger(market, targets, ledger_config)
            futures_results[scenario] = result
            collateral_results[scenario] = v15.evaluate_collateral_income(result, ruonia)
            order_frame = result.orders.copy()
            order_frame.insert(0, "v48_mode", mode)
            order_frame.insert(1, "scenario", scenario)
            orders.append(order_frame)
            position_frame = result.positions.copy()
            position_frame.insert(0, "v48_mode", mode)
            position_frame.insert(1, "scenario", scenario)
            positions.append(position_frame)
        mode_scenarios: dict[str, Any] = {}
        for scenario in SCENARIOS:
            futures_name = "stress" if scenario == "execution_stress" else scenario
            result = futures_results[futures_name]
            collateral = collateral_results[futures_name]
            exact_nav = collateral.combined_ledger.set_index("session_date")[
                "combined_ending_equity"
            ].astype(float)
            fraction = float(mode_config["broad_carry_cash_fraction"])
            carry_name = protocol.payload["scenarios"][scenario]["carry"]
            carry_nav = carry[f"overlay_active_cap_{carry_name}_nav"].astype(float)
            combined_nav = combine_with_carry_excess(
                exact_nav, carry_nav, baseline, fraction
            )
            combined_metrics = _metrics(combined_nav)
            combined_metrics["minimum_nav"] = float(combined_nav.min())
            futures_metrics = v12.scenario_metrics(
                result, market, settings[futures_name]
            )
            benchmark_metrics = benchmark["modes"][mode]["scenarios"][scenario][
                "metrics"
            ]
            mode_scenarios[scenario] = {
                "futures": futures_metrics,
                "combined": combined_metrics,
                "delta_vs_v47_normalized": {
                    key: combined_metrics[key] - benchmark_metrics[key]
                    for key in (
                        "cagr",
                        "sharpe",
                        "maximum_drawdown",
                        "worst_year",
                    )
                },
                "margin_buffer_multiplier": float(
                    mode_config["initial_margin_buffer_multiplier"]
                ),
                "carry_cash_fraction": fraction,
            }
            if ledger_output is None:
                ledger_output = pd.DataFrame(
                    {"session_date": combined_nav.index}
                )
            ledger_output[f"{mode}_{scenario}_exact_futures_nav"] = (
                exact_nav / float(exact_nav.iloc[0])
            ).to_numpy()
            ledger_output[f"{mode}_{scenario}_combined_nav"] = combined_nav.to_numpy()
        gates = _mode_gates(mode, mode_scenarios, protocol.payload)
        modes[mode] = {
            "verdict": "PASS_EXACT_EXECUTION_GATES" if all(gates.values()) else "NO_GO",
            "target_multiplier": float(mode_config["mapped_target_multiplier"]),
            "maximum_scaled_target_gross": float(gross.max()),
            "scenarios": mode_scenarios,
            "gates": gates,
        }
    passing = [name for name, item in modes.items() if item["verdict"].startswith("PASS")]
    metrics = {
        "verdict": "NO_GO" if not passing else "EXACT_EXECUTION_GATES_PASS",
        "passing_modes": passing,
        "modes": modes,
        "mode_selection_after_outcome": False,
        "adaptive_same_history": True,
        "live_trading_allowed": False,
    }
    assert ledger_output is not None
    return (
        ledger_output,
        pd.concat(orders, ignore_index=True),
        pd.concat(positions, ignore_index=True),
        pd.concat(scaled_target_frames, ignore_index=True),
        metrics,
    )


def _report(metrics: dict[str, Any]) -> str:
    lines = [
        "# V48 exact integer execution replay of V47",
        "",
        f"Verdict: **{metrics['verdict']}**",
        "",
        "| Mode | Scenario | CAGR | Sharpe | MDD | Worst year | Clips | "
        "Margin rejects | dCAGR vs V47 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, result in metrics["modes"].items():
        for scenario, item in result["scenarios"].items():
            combined = item["combined"]
            futures = item["futures"]
            delta = item["delta_vs_v47_normalized"]
            lines.append(
                f"| {mode} | {scenario} | {combined['cagr']:.4%} | "
                f"{combined['sharpe']:.3f} | {combined['maximum_drawdown']:.4%} | "
                f"{combined['worst_year']:.4%} | "
                f"{futures['participation_clip_count']} | "
                f"{futures['initial_margin_rejection_count']} | "
                f"{delta['cagr']:+.4%} |"
            )
    lines.extend(
        [
            "",
            "Targets are exact integer replays with factual capacity and margin admission.",
            "This remains same-history research and does not authorize live trading.",
        ]
    )
    return "\n".join(lines) + "\n"


def run(protocol: Protocol) -> Path:
    ledger, orders, positions, targets, metrics = build(protocol)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = _root(protocol.payload["outputs"]["root"])
    output = base.parent / f"{base.name}_{stamp}_{protocol.config_sha256[:8]}"
    if output.exists():
        raise FileExistsError(f"V48 output exists: {output}")
    output.mkdir(parents=True)
    paths = {
        "ledger": output / "combined_ledger.parquet",
        "orders": output / "orders.parquet",
        "positions": output / "positions.parquet",
        "targets": output / "scaled_targets.parquet",
        "metrics": output / "metrics.json",
        "report": output / "report.md",
    }
    io_utils._write_parquet(paths["ledger"], ledger)
    io_utils._write_parquet(paths["orders"], orders)
    io_utils._write_parquet(paths["positions"], positions)
    io_utils._write_parquet(paths["targets"], targets)
    write_json(paths["metrics"], metrics)
    atomic_write_bytes(paths["report"], _report(metrics).encode("utf-8-sig"))
    audit = {
        "checks": {
            "protocol_sha_exact": _sha(CONFIG_PATH) == protocol.config_sha256,
            "dates_before_2026": bool(
                pd.to_datetime(ledger["session_date"]).lt("2026-01-01").all()
            ),
            "both_modes_present": tuple(metrics["modes"]) == MODES,
            "all_scenarios_present": all(
                tuple(item["scenarios"]) == SCENARIOS
                for item in metrics["modes"].values()
            ),
            "no_mode_selection": metrics["mode_selection_after_outcome"] is False,
            "targets_preserve_sign": bool(
                targets.loc[targets["v39_target_weight"].ne(0.0), "target_weight"]
                .mul(
                    targets.loc[
                        targets["v39_target_weight"].ne(0.0), "v39_target_weight"
                    ]
                )
                .gt(0.0)
                .all()
            ),
            "all_nav_positive": bool(
                ledger.filter(regex="_nav$").gt(0.0).all(axis=None)
            ),
            "live_forbidden": metrics["live_trading_allowed"] is False,
        },
        "limitations": protocol.payload["limitations"],
    }
    if not all(audit["checks"].values()):
        raise ValueError(f"V48 audit failed: {audit}")
    audit_path = output / "audit.json"
    write_json(audit_path, audit)
    artifacts = {
        key: io_utils._artifact(path, len(ledger) if key == "ledger" else None)
        for key, path in paths.items()
    }
    artifacts["audit"] = io_utils._artifact(audit_path)
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
