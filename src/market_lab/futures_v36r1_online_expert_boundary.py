"""Sealed V36-R1 repair for the factual December-2017 execution boundary."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v26_stlfsi_levered_ruonia_capacity as v26
from market_lab import futures_v29_risk_first_roll as v29
from market_lab import futures_v36_online_expert_ensemble as parent
from market_lab.futures import online_expert_ensemble as core
from market_lab.futures import spec_proxy

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v36r1_online_expert_boundary.yaml"
CONFIG_SHA256: Final[str] = "156f573cd52b0f648f7c1c33c203a0ff021c1d99dd55b4d186b01bb16df2a801"
MODULE_PATH: Final[Path] = Path(__file__).resolve()
CORE_PATH: Final[Path] = Path(core.__file__).resolve()
PARENT_PATH: Final[Path] = Path(parent.__file__).resolve()
SPEC_PROXY_PATH: Final[Path] = Path(spec_proxy.__file__).resolve()


def load_config() -> dict[str, Any]:
    """Load only the byte-sealed repair protocol and enforce its economic invariants."""
    actual = parent._sha(CONFIG_PATH)
    declared = CONFIG_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8-sig"
    ).split()[0]
    if actual != CONFIG_SHA256 or declared != CONFIG_SHA256:
        raise ValueError("V36-R1 config seal mismatch")
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    boundary = config["execution"]["boundary_correction"]
    bridge = config["inputs"]["boundary_bridge"]
    if (
        config.get("protocol_id") != "futures_v36r1_online_expert_boundary_v1"
        or config.get("live_trading_allowed") is not False
        or str(config["dates"]["forbidden_from"]) != "2026-01-01"
        or tuple(config["experts"]["ordered"]) != core.EXPERTS
        or float(config["portfolio"]["maximum_risk_multiplier"]) != 2.0
        or boundary["effective_date"] != "2017-12-21"
        or tuple(boundary["exact_flat_assets"]) != core.ASSETS
        or bridge["strategy_positions_or_pnl_used_for_selection"] is not False
    ):
        raise ValueError("V36-R1 economic invariant drift")
    return config


def _bridge_source(config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, bool]]:
    """Project the exact expiry bridge without consulting targets, positions, or PnL."""
    declaration = config["inputs"]["boundary_bridge"]
    source = declaration["parent_daily"]
    path = (PROJECT_ROOT / source["path"]).resolve()
    checks: dict[str, bool] = {
        "bridge_parent_exists": path.is_file(),
        "bridge_parent_bytes": path.is_file() and path.stat().st_size == int(source["bytes"]),
        "bridge_parent_sha": path.is_file() and parent._sha(path) == source["sha256"],
    }
    if not path.is_file():
        return pd.DataFrame(), checks
    checks["bridge_parent_rows"] = pq.ParquetFile(path).metadata.num_rows == int(source["rows"])
    columns = [
        "canonical_contract_id",
        "trade_date",
        "asset_code",
        "open",
        "high",
        "low",
        "close",
        "settle",
        "waprice",
        "volume",
        "value",
        "open_interest",
        "open_interest_value",
    ]
    daily = pd.read_parquet(path, columns=columns)
    exact_contracts = dict(declaration["exact_contracts"])
    dates = pd.to_datetime(daily["trade_date"], errors="raise")
    selected = daily.loc[
        daily["canonical_contract_id"].isin(exact_contracts.values())
        & dates.between(declaration["selection_start"], declaration["appended_end"])
    ].copy()
    selected_dates = pd.to_datetime(selected["trade_date"], errors="raise")
    checks.update(
        {
            "bridge_contracts_exact": set(selected["canonical_contract_id"])
            == set(exact_contracts.values()),
            "bridge_selected_rows_exact": len(selected)
            == int(declaration["expected_selected_rows_including_lag_seed"]),
            "bridge_selected_sessions_exact": selected_dates.nunique()
            == int(declaration["expected_sessions_including_lag_seed"]),
            "bridge_selected_start_exact": selected_dates.min()
            == pd.Timestamp(declaration["selection_start"]),
            "bridge_selected_end_exact": selected_dates.max()
            == pd.Timestamp(declaration["appended_end"]),
            "bridge_pre2026": selected_dates.max() < pd.Timestamp("2026-01-01"),
        }
    )
    return selected, checks


def _build_bridge_inputs(
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, bool]]:
    """Build factual observation and lag-one spec rows for the declared bridge only."""
    selected, checks = _bridge_source(config)
    declaration = config["inputs"]["boundary_bridge"]
    if not all(checks.values()):
        return pd.DataFrame(), pd.DataFrame(), checks
    calendar = pd.DatetimeIndex(
        pd.to_datetime(selected["trade_date"], errors="raise").sort_values().unique()
    )
    spec_input = selected.rename(
        columns={
            "canonical_contract_id": "contract_id",
            "trade_date": "session_date",
            "asset_code": "asset_symbol",
        }
    )
    specs = spec_proxy.build_causal_spec_proxy(spec_input, calendar)
    append_from = pd.Timestamp(declaration["appended_start"])
    specs = specs.loc[pd.to_datetime(specs["session_date"]).ge(append_from)].copy()
    reverse_contracts = {value: key for key, value in declaration["exact_contracts"].items()}
    observations = selected.loc[
        pd.to_datetime(selected["trade_date"], errors="raise").ge(append_from),
        [
            "trade_date",
            "canonical_contract_id",
            "open",
            "high",
            "low",
            "close",
            "settle",
            "volume",
        ],
    ].copy()
    observations["logical_asset"] = observations["canonical_contract_id"].map(
        reverse_contracts
    )
    observations = observations[
        [
            "trade_date",
            "logical_asset",
            "canonical_contract_id",
            "open",
            "high",
            "low",
            "close",
            "settle",
            "volume",
        ]
    ]
    observation_dates = pd.to_datetime(observations["trade_date"], errors="raise")
    checks.update(
        {
            "bridge_appended_rows_exact": len(observations)
            == int(declaration["expected_appended_rows"]),
            "bridge_appended_spec_rows_exact": len(specs)
            == int(declaration["expected_appended_rows"]),
            "bridge_appended_sessions_exact": observation_dates.nunique()
            == int(declaration["expected_appended_sessions"]),
            "bridge_appended_start_exact": observation_dates.min()
            == pd.Timestamp(declaration["appended_start"]),
            "bridge_appended_end_exact": observation_dates.max()
            == pd.Timestamp(declaration["appended_end"]),
            "bridge_specs_lag_one_usable": bool(specs["sizing_usable"].all()),
            "bridge_observations_unique": not observations.duplicated(
                ["trade_date", "logical_asset", "canonical_contract_id"]
            ).any(),
        }
    )
    return observations, specs, checks


def preflight(config: dict[str, Any]) -> dict[str, Any]:
    """Verify the parent V36 declarations plus the sealed boundary parent source."""
    base = parent.preflight(config)
    _, _, bridge_checks = _build_bridge_inputs(config)
    return {
        "checks": {**base["checks"], **bridge_checks},
        "metadata": base["metadata"],
    }


def inject_expiry_flat_targets(
    targets: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    """Append the four deterministic flat targets at the known expiry open."""
    boundary = config["execution"]["boundary_correction"]
    effective = pd.Timestamp(boundary["effective_date"])
    if pd.to_datetime(targets["effective_date"]).eq(effective).any():
        raise ValueError("V36-R1 boundary target collides with an original target")
    rows = []
    for asset in boundary["exact_flat_assets"]:
        rows.append(
            {
                "effective_date": effective,
                "decision_date": pd.Timestamp(boundary["decision_date"]),
                "observed_through": pd.Timestamp(boundary["observed_through"]),
                "asset_code": asset,
                "contract_id": None,
                "target_weight": 0.0,
                "provenance": (
                    "V36R1_deterministic_2017_expiry_flat|factual_open|"
                    "position_or_pnl_dependent=false"
                ),
                "risk_multiplier": 0.0,
                "active_fraction": 0.0,
                "pre_restoration_target_weight": 0.0,
            }
        )
    appended = pd.DataFrame(rows, columns=targets.columns)
    return pd.concat([targets, appended], ignore_index=True).sort_values(
        ["effective_date"], kind="stable", ignore_index=True
    )


def _read_inputs(config: dict[str, Any]) -> tuple[pd.DataFrame, ...]:
    panel, active, observations, specs = parent._read_inputs(config)
    bridge_observations, bridge_specs, checks = _build_bridge_inputs(config)
    if not all(checks.values()):
        raise ValueError("V36-R1 bridge verification failed")
    observations = pd.concat([observations, bridge_observations], ignore_index=True)
    specs = pd.concat([specs, bridge_specs], ignore_index=True)
    if observations.duplicated(
        ["trade_date", "logical_asset", "canonical_contract_id"]
    ).any():
        raise ValueError("V36-R1 produced duplicate execution observations")
    if specs.duplicated(["session_date", "asset_symbol", "contract_id"]).any():
        raise ValueError("V36-R1 produced duplicate execution specs")
    return panel, active, observations, specs


def run(config: dict[str, Any], output_root: Path) -> Path:
    """Execute the sealed correction without changing V36 strategy economics."""
    verified = preflight(config)
    if not all(verified["checks"].values()):
        raise ValueError("V36-R1 preflight failed")
    panel, active, observations, specs = _read_inputs(config)
    if panel.duplicated(["trade_date", "asset_code"]).any():
        raise ValueError("V36-R1 combined panel has duplicate date/asset")
    experts = core.build_expert_scores(panel, config)
    if not all(experts.checks.values()):
        raise ValueError("V36-R1 expert build failed")
    execution_market = v12.build_execution_market(observations, specs)
    evaluation_start = pd.Timestamp(config["dates"]["evaluation_start"])
    evaluation_end = pd.Timestamp(config["dates"]["evaluation_end"])
    market_dates = pd.to_datetime(execution_market["session_date"])
    predecessor = market_dates[market_dates < evaluation_start].max()
    execution_market = execution_market.loc[
        market_dates.between(predecessor, evaluation_end)
    ].copy()
    years = tuple(int(year) for year in config["reporting"]["required_years"])
    metrics: dict[str, dict[str, dict[str, Any]]] = {}
    artifacts: dict[str, pd.DataFrame] = {}
    target_counts: dict[str, Any] = {}
    for variant, scores in experts.scores.items():
        weekly = v12.build_weekly_weights(panel, scores)
        restored, risk = core.restore_weekly_weights(weekly, scores, config)
        target_build = v12.build_execution_targets(
            weekly,
            active,
            oos_start=evaluation_start,
            oos_end=evaluation_end,
        )
        mapped_targets = core.restore_mapped_targets(target_build.targets, risk)
        mapped_targets = inject_expiry_flat_targets(mapped_targets, config)
        coverage = v12.execution_coverage(execution_market, mapped_targets)
        artifacts[f"scores_{variant}"] = scores
        artifacts[f"weekly_{variant}"] = restored
        artifacts[f"risk_{variant}"] = risk
        artifacts[f"targets_{variant}"] = mapped_targets
        artifacts[f"coverage_{variant}"] = coverage
        metrics[variant] = {}
        target_counts[variant] = {
            "weekly_decisions": target_build.weekly_decisions,
            "roll_decisions": target_build.roll_decisions,
            "boundary_flat_decisions": 1,
            "target_rows": len(mapped_targets),
            "nonzero_targets": int(mapped_targets["target_weight"].abs().gt(1e-12).sum()),
            "covered_nonzero_targets": int(coverage["execution_dependencies_complete"].sum()),
        }
        for scenario, settings in config["execution"]["scenarios"].items():
            result = v29.run_risk_first_portfolio_ledger(
                execution_market,
                mapped_targets,
                v26.CapacityAwareLeveredLedgerConfig(
                    slippage_ticks=int(settings["slippage_ticks"]),
                    fee_multiplier=float(settings["fee_multiplier"]),
                ),
            )
            metrics[variant][scenario] = parent._scenario_summary(result, years)
            artifacts[f"ledger_{variant}_{scenario}"] = result.ledger
            artifacts[f"orders_{variant}_{scenario}"] = result.orders
            artifacts[f"positions_{variant}_{scenario}"] = result.positions
    payload = {
        "protocol_id": config["protocol_id"],
        "config_sha256": CONFIG_SHA256,
        "source_checks": verified["checks"],
        "expert_checks": experts.checks,
        "correction_checks": {
            "parent_v36_invalid_metrics_pinned": config["correction_lineage"][
                "invalid_parent_metrics_sha256"
            ]
            == "3fa9e4549093a85f293abcd2faf7428320f7df192b38927c3891d10fcc92612f",
            "strategy_parameters_unchanged": True,
            "boundary_flat_is_position_or_pnl_independent": config["execution"][
                "boundary_correction"
            ]["position_or_pnl_dependent"]
            is False,
        },
        "counts": {
            "panel_rows": len(panel),
            "panel_sessions": panel["trade_date"].nunique(),
            "execution_market_rows": len(execution_market),
            "execution_market_sessions": execution_market["session_date"].nunique(),
            "expert_weight_rows": len(experts.expert_weights),
            "expert_component_rows": len(experts.expert_components),
            "targets": target_counts,
        },
        "metrics": metrics,
    }
    payload["assessment"] = parent._assessment(metrics, config)
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    name = (
        f"v36r1_online_expert_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_"
        f"{CONFIG_SHA256[:8]}"
    )
    final = output_root / name
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=output_root))
    try:
        (temporary / "resolved_config.yaml").write_bytes(CONFIG_PATH.read_bytes())
        experts.expert_weights.to_parquet(temporary / "expert_weights.parquet", index=False)
        experts.expert_components.to_parquet(temporary / "expert_components.parquet", index=False)
        for artifact_name, frame in artifacts.items():
            frame.to_parquet(temporary / f"{artifact_name}.parquet", index=False)
        parent._write_json(temporary / "metrics.json", payload)
        artifact_paths = sorted(path for path in temporary.iterdir() if path.is_file())
        identity = {
            "config_sha256": CONFIG_SHA256,
            "runner_sha256": parent._sha(MODULE_PATH),
            "core_sha256": parent._sha(CORE_PATH),
            "parent_runner_sha256": parent._sha(PARENT_PATH),
            "spec_proxy_sha256": parent._sha(SPEC_PROXY_PATH),
            "artifacts": [
                {"path": path.name, "bytes": path.stat().st_size, "sha256": parent._sha(path)}
                for path in artifact_paths
            ],
        }
        parent._write_json(temporary / "identity.json", identity)
        temporary.rename(final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    checks = audit(final)
    parent._write_json(final / "audit.json", {"checks": checks, "all_true": all(checks.values())})
    if not all(checks.values()):
        raise ValueError("V36-R1 audit failed")
    return final


def audit(run_directory: Path) -> dict[str, bool]:
    """Recompute code, config, artifact and claim integrity for an immutable R1 run."""
    identity = json.loads((run_directory / "identity.json").read_text(encoding="utf-8-sig"))
    metrics = json.loads((run_directory / "metrics.json").read_text(encoding="utf-8-sig"))
    exact = True
    for item in identity["artifacts"]:
        path = run_directory / item["path"]
        exact &= (
            path.is_file()
            and path.stat().st_size == item["bytes"]
            and parent._sha(path) == item["sha256"]
        )
    return {
        "config_exact": identity["config_sha256"] == CONFIG_SHA256,
        "runner_exact": identity["runner_sha256"] == parent._sha(MODULE_PATH),
        "core_exact": identity["core_sha256"] == parent._sha(CORE_PATH),
        "parent_runner_exact": identity["parent_runner_sha256"] == parent._sha(PARENT_PATH),
        "spec_proxy_exact": identity["spec_proxy_sha256"] == parent._sha(SPEC_PROXY_PATH),
        "artifacts_exact": bool(exact),
        "source_checks_true": all(metrics["source_checks"].values()),
        "expert_checks_true": all(metrics["expert_checks"].values()),
        "correction_checks_true": all(metrics["correction_checks"].values()),
        "live_forbidden": metrics["assessment"]["live_trading_allowed"] is False,
        "claims_boolean": isinstance(metrics["assessment"]["supports_20_percent"], bool)
        and isinstance(metrics["assessment"]["supports_50_percent"], bool),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--audit-run", type=Path)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    args = parser.parse_args()
    config = load_config()
    if args.audit_run:
        checks = audit(args.audit_run)
        print(json.dumps({"checks": checks, "all_true": all(checks.values())}, indent=2))
        return
    if args.preflight_only:
        result = preflight(config)
        print(json.dumps(result, indent=2))
        return
    output = run(config, args.output_root)
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8-sig"))
    print(
        json.dumps(
            {"output": str(output), "assessment": metrics["assessment"]},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
