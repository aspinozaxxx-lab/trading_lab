"""Sealed V39: frozen V27 plus a lagged option-OI tail-shock veto."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v15_levered_ruonia_collateral as v15
from market_lab import futures_v26_stlfsi_levered_ruonia_capacity as v26
from market_lab import futures_v27_key_rate_extreme_governor as v27
from market_lab.futures import moex_options_weekly_state_source_v3 as option_source
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult

PROJECT_ROOT: Final[Path] = v12.PROJECT_ROOT
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v39_option_oi_tail_governor.yaml"
CONFIG_SHA256: Final[str] = "3b5d3074f8ec93ffb3aa7170c332f19af7dcd55900a5f7902bc636dd595032a6"
SOURCE_ROOT: Final[Path] = (
    PROJECT_ROOT / "data/processed/options/moex-core4-options-weekly-2021-2025-v3"
)
SOURCE_MANIFEST_SHA256: Final[str] = (
    "0453f05c2b89f9c1df169f4b89356ec4093bc56f46a56edc99dd89b46a2e6e66"
)
SOURCE_AUDIT_SHA256: Final[str] = "e09534fff372a3a72fb82cc543be4d62b8463e78052002daf01d983b16244aec"
SOURCE_PARQUET_SHA256: Final[str] = (
    "fdd67cd9a4080371aee1b5a3546abb24912a2ef5e40052b9f33c153535db262d"
)
PARENT_WEIGHTS_SHA256: Final[str] = (
    "576b2b9d951c6f80895d609aff5e5dbf327472290a946078ee0afdc353110df8"
)
SOURCE_ROWS: Final[int] = 1_327_744
WINDOW: Final[int] = 52
LOWER_Q: Final[float] = 0.10
UPPER_Q: Final[float] = 0.90
MAXIMUM_AGE_DAYS: Final[int] = 10


@dataclass(frozen=True, slots=True)
class OptionStateVerification:
    states: pd.DataFrame
    checks: dict[str, bool]
    manifest_sha256: str
    audit_sha256: str


@dataclass(frozen=True, slots=True)
class GovernorBuild:
    weights: pd.DataFrame
    governor: pd.DataFrame
    checks: dict[str, bool]


def load_protocol() -> dict[str, Any]:
    if v12.sha256_file(CONFIG_PATH) != CONFIG_SHA256:
        raise ValueError("sealed V39 protocol byte drift")
    if (
        CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
        != CONFIG_SHA256
    ):
        raise ValueError("V39 sidecar mismatch")
    protocol = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    source = protocol["source"]
    info = protocol["information_set"]
    rule = protocol["option_oi_governor"]
    capital = protocol["capital_execution_and_costs"]
    if (
        protocol["protocol_id"] != "futures_v39_option_oi_tail_governor_v1"
        or protocol["sealed_before_outcomes"] is not True
        or protocol["live_trading_allowed"] is not False
        or protocol["parent_v27"]["protocol_sha256"] != v27.CONFIG_SHA256
        or source["archive_protocol_sha256"] != option_source.CONFIG_SHA256
        or source["archive_implementation_sha256"] != v12.sha256_file(Path(option_source.__file__))
        or source["manifest_sha256"] != SOURCE_MANIFEST_SHA256
        or source["audit_sha256"] != SOURCE_AUDIT_SHA256
        or source["processed"]["sha256"] != SOURCE_PARQUET_SHA256
        or int(source["processed"]["rows"]) != SOURCE_ROWS
        or int(info["baseline_observations"]) != WINDOW
        or float(info["lower_quantile"]) != LOWER_Q
        or float(info["upper_quantile"]) != UPPER_Q
        or int(info["maximum_selected_state_age_calendar_days"]) != MAXIMUM_AGE_DAYS
        or float(rule["admitted_scale"]) != 1.0
        or float(rule["cash_scale"]) != 0.0
        or rule["scale_can_increase_parent_risk"] is not False
        or rule["option_trade_created"] is not False
        or capital["inherited_byte_identical_from_V27"] is not True
    ):
        raise ValueError("sealed V39 invariants weakened")
    declared = {
        name: {
            "slippage_ticks": int(values["slippage_ticks_per_leg"]),
            "fee_multiplier": float(values["conservative_fee_multiplier"]),
        }
        for name, values in capital["scenarios"].items()
    }
    if declared != v12._scenario_settings(v27.load_protocol()):
        raise ValueError("V39 scenarios drifted from V27")
    return protocol


def verify_option_source(protocol: dict[str, Any]) -> OptionStateVerification:
    root = SOURCE_ROOT.resolve()
    manifest_path = root / "manifest.json"
    audit_path = root / "audit.json"
    parquet_path = root / protocol["source"]["processed"]["path"]
    replay = option_source.audit(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    stored_audit = json.loads(audit_path.read_text(encoding="utf-8-sig"))
    raw = pd.read_parquet(parquet_path, columns=protocol["source"]["processed"]["allowed_columns"])
    raw["tradedate"] = pd.to_datetime(raw["tradedate"], errors="raise").dt.normalize()
    raw["openposition"] = pd.to_numeric(raw["openposition"], errors="coerce")
    finite = raw["openposition"].dropna()
    grouped = (
        raw.groupby(["tradedate", "logical_asset", "option_type"], observed=True)["openposition"]
        .sum(min_count=1)
        .unstack("option_type")
        .reset_index()
        .rename(columns={"call": "call_oi", "put": "put_oi"})
    )
    grouped["put_share"] = grouped["put_oi"] / (grouped["call_oi"] + grouped["put_oi"])
    checks = {
        "source_config_exact": manifest["config_sha256"] == option_source.CONFIG_SHA256,
        "source_implementation_exact": manifest["implementation_sha256"]
        == v12.sha256_file(Path(option_source.__file__)),
        "source_manifest_exact": v12.sha256_file(manifest_path) == SOURCE_MANIFEST_SHA256,
        "source_audit_exact": v12.sha256_file(audit_path) == SOURCE_AUDIT_SHA256,
        "source_parquet_exact": len(raw) == SOURCE_ROWS
        and v12.sha256_file(parquet_path) == SOURCE_PARQUET_SHA256,
        "source_replay_all_true": all(replay.values()) and stored_audit["all_true"] is True,
        "source_target_free": manifest["contains_returns_targets_predictions_or_pnl"] is False,
        "source_open_interest_nonnegative_finite": bool(
            len(finite) and np.isfinite(finite).all() and finite.ge(0).all()
        ),
        "source_grid_complete": len(grouped) == 1_044 and grouped["tradedate"].nunique() == 261,
        "source_assets_exact": set(grouped["logical_asset"]) == set(v12.ASSETS),
        "source_both_sides_positive": bool(
            grouped["call_oi"].gt(0).all() and grouped["put_oi"].gt(0).all()
        ),
        "source_put_share_bounded": bool(grouped["put_share"].between(0.0, 1.0).all()),
        "source_pre2026_only": bool(grouped["tradedate"].lt(v12.PROTECTED_FROM).all()),
    }
    if not all(checks.values()):
        raise ValueError(f"V39 option source failure: {checks}")
    return OptionStateVerification(
        states=grouped.sort_values(["logical_asset", "tradedate"], ignore_index=True),
        checks=checks,
        manifest_sha256=v12.sha256_file(manifest_path),
        audit_sha256=v12.sha256_file(audit_path),
    )


def apply_option_governor(
    parent_weights: pd.DataFrame, source: OptionStateVerification
) -> GovernorBuild:
    weights = parent_weights.copy()
    weights["decision_date"] = pd.to_datetime(
        weights["decision_date"], errors="raise"
    ).dt.normalize()
    if weights.duplicated(["decision_date", "asset"]).any():
        raise ValueError("V39 duplicate parent weights")
    rows: list[pd.DataFrame] = []
    for asset in v12.ASSETS:
        decisions = weights.loc[weights["asset"].eq(asset), ["decision_date", "asset"]].sort_values(
            "decision_date"
        )
        states = source.states.loc[source.states["logical_asset"].eq(asset)].rename(
            columns={"tradedate": "source_date"}
        )
        merged = pd.merge_asof(
            decisions,
            states.sort_values("source_date"),
            left_on="decision_date",
            right_on="source_date",
            direction="backward",
            allow_exact_matches=False,
        )
        merged["source_age_days"] = (merged["decision_date"] - merged["source_date"]).dt.days
        merged["fresh"] = merged["source_age_days"].between(1, MAXIMUM_AGE_DAYS, inclusive="both")
        merged["put_share_change"] = merged["put_share"].diff()
        prior = merged["put_share_change"].shift(1)
        merged["q10"] = prior.rolling(WINDOW, min_periods=WINDOW).quantile(
            LOWER_Q, interpolation="linear"
        )
        merged["q90"] = prior.rolling(WINDOW, min_periods=WINDOW).quantile(
            UPPER_Q, interpolation="linear"
        )
        merged["baseline_ready"] = merged[["q10", "q90"]].notna().all(axis=1)
        rows.append(merged)
    governor = pd.concat(rows, ignore_index=True).sort_values(
        ["decision_date", "asset"], ignore_index=True
    )
    governed = weights.merge(
        governor, on=["decision_date", "asset"], how="left", validate="one_to_one"
    )
    governed["pre_option_oi_target_weight"] = pd.to_numeric(
        governed["target_weight"], errors="raise"
    )
    ready = governed["baseline_ready"]
    complete = governed["fresh"] & governed["put_share_change"].notna()
    put_shock = ready & complete & governed["put_share_change"].gt(governed["q90"])
    call_shock = ready & complete & governed["put_share_change"].lt(governed["q10"])
    governed["option_oi_state"] = "pass_warmup"
    governed.loc[ready & complete, "option_oi_state"] = "pass_nonextreme"
    governed.loc[put_shock, "option_oi_state"] = "put_tail_shock"
    governed.loc[call_shock, "option_oi_state"] = "call_tail_shock"
    governed.loc[ready & ~complete, "option_oi_state"] = "cash_missing_or_stale"
    cash = (
        (put_shock & governed["pre_option_oi_target_weight"].gt(0.0))
        | (call_shock & governed["pre_option_oi_target_weight"].lt(0.0))
        | governed["option_oi_state"].eq("cash_missing_or_stale")
    )
    governed["option_oi_scale"] = (~cash).astype(float)
    governed["target_weight"] = (
        governed["pre_option_oi_target_weight"] * governed["option_oi_scale"]
    )
    governed["provenance"] = (
        governed["provenance"].astype("string") + "|option_oi_" + governed["option_oi_state"]
    )
    oos = governed["decision_date"].between(v12.OOS_START, v12.OOS_END)
    checks = {
        "governor_complete": len(governed) == len(weights)
        and governed.groupby("decision_date")["asset"].nunique().eq(4).all(),
        "source_strictly_before_decision": bool(
            governed.loc[governed["source_date"].notna(), "source_date"]
            .lt(governed.loc[governed["source_date"].notna(), "decision_date"])
            .all()
        ),
        "quantile_order_valid": bool(
            governed.loc[ready, "q10"].le(governed.loc[ready, "q90"]).all()
        ),
        "scale_exact": set(governed["option_oi_scale"].unique()) <= {0.0, 1.0},
        "never_increases_parent_risk": bool(
            governed["target_weight"]
            .abs()
            .le(governed["pre_option_oi_target_weight"].abs() + 1e-12)
            .all()
        ),
        "oos_has_tail_state": bool((oos & (put_shock | call_shock)).any()),
        "oos_reduces_nonzero_target": bool(
            (oos & cash & governed["pre_option_oi_target_weight"].abs().gt(1e-12)).any()
        ),
    }
    if not all(checks.values()):
        raise ValueError(f"V39 governor invariant failure: {checks}")
    return GovernorBuild(
        governed.sort_values(["decision_date", "asset"], ignore_index=True), governor, checks
    )


def _parent_metrics(protocol: dict[str, Any]) -> dict[str, Any]:
    root = PROJECT_ROOT / protocol["parent_v27"]["canonical_run"]
    if v12.sha256_file(root / "metrics.json") != protocol["parent_v27"]["metrics_sha256"]:
        raise ValueError("V39 parent metrics drift")
    if v12.sha256_file(root / "identity.json") != protocol["parent_v27"]["identity_sha256"]:
        raise ValueError("V39 parent identity drift")
    return json.loads((root / "metrics.json").read_text(encoding="utf-8-sig"))


def _promotion(
    results: dict[str, dict[str, Any]], checks: dict[str, bool], parent: dict[str, Any]
) -> dict[str, Any]:
    reference = parent["scenarios"]
    primary = results["primary"]["combined"]
    conditions = {
        "all_checks_true": all(checks.values()),
        "zero_critical_and_unresolved": all(
            int(x["futures_only"]["critical_failure_count"]) == 0
            and int(x["futures_only"]["unresolved_halt_count"]) == 0
            for x in results.values()
        ),
        "all_cagr_at_least_20pct": all(
            float(x["combined"]["cagr"]) >= 0.20 for x in results.values()
        ),
        "all_mdd_not_worse_than_v27": all(
            float(results[n]["combined"]["maximum_drawdown"])
            <= float(reference[n]["combined"]["maximum_drawdown"]) + 1e-12
            for n in results
        ),
        "primary_sharpe_at_least_v27": float(primary["sharpe"])
        >= float(reference["primary"]["combined"]["sharpe"]),
        "primary_worst_year_not_worse": float(primary["worst_year"])
        >= float(reference["primary"]["combined"]["worst_year"]),
        "primary_positive_years_at_least_4": int(primary["positive_years"]) >= 4
        and len(primary["annual_returns"]) == 5,
        "execution_limits_clean": all(
            float(x["futures_only"]["maximum_participation"]) <= v12.MAXIMUM_PARTICIPATION + 1e-12
            and int(x["futures_only"]["gross_limit_rejection_count"]) == 0
            and int(x["futures_only"]["initial_margin_rejection_count"]) == 0
            for x in results.values()
        ),
    }
    passed = all(conditions.values())
    return {
        "conditions": conditions,
        "passed": passed,
        "verdict": "GO_TO_NEW_FORWARD_CONFIRMATION" if passed else "NO_GO",
        "live_trading_allowed": False,
    }


def run_experiment(output_root: Path) -> Path:
    protocol = load_protocol()
    parent = _parent_metrics(protocol)
    verified = v27.verify_inputs(v27.load_protocol())
    v26_protocol = v26.load_protocol()
    source = verify_option_source(protocol)
    parent_root = PROJECT_ROOT / protocol["parent_v27"]["canonical_run"]
    parent_path = parent_root / "weekly_v27_monetary_governed_weights.parquet"
    if v12.sha256_file(parent_path) != PARENT_WEIGHTS_SHA256:
        raise ValueError("V39 parent weekly weights drift")
    parent_weights = pd.read_parquet(parent_path)
    governed = apply_option_governor(parent_weights, source)
    active = pd.read_parquet(
        verified.paths["active_contract_map"],
        columns=v26_protocol["inputs"]["active_contract_map"]["allowed_columns"],
    )
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
    ruonia = v15.verify_ruonia(ruonia_frame)
    target_build = v26.build_execution_targets(governed.weights, active)
    market = v12.build_execution_market(observations, specs)
    coverage = v12.execution_coverage(market, target_build.targets)
    nonzero = int(target_build.targets["target_weight"].abs().gt(1e-12).sum())
    checks = {
        **verified.checks,
        **source.checks,
        **governed.checks,
        **ruonia.checks,
        "protocol_seal": v12.sha256_file(CONFIG_PATH) == CONFIG_SHA256,
        "parent_weights_exact": True,
        "execution_complete": int(coverage["execution_dependencies_complete"].sum()) == nonzero,
    }
    if not all(checks.values()):
        raise ValueError(f"V39 pre-execution failure: {checks}")
    dates = pd.DatetimeIndex(pd.to_datetime(market["session_date"]).drop_duplicates().sort_values())
    predecessor = dates[dates < v12.OOS_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"]).between(predecessor, v12.OOS_END)
    ].copy()
    outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    collaterals: dict[str, v15.CollateralEvaluation] = {}
    results: dict[str, dict[str, Any]] = {}
    for name, settings in v12._scenario_settings(v27.load_protocol()).items():
        result = v15.run_levered_portfolio_ledger(
            execution_market,
            target_build.targets,
            v26.CapacityAwareLeveredLedgerConfig(
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
            ),
        )
        outputs[name] = result
        results[name], collaterals[name] = v15._scenario_payload(
            result, execution_market, settings, ruonia
        )
    oos = governed.weights["decision_date"].between(v12.OOS_START, v12.OOS_END)
    state_counts = governed.weights.loc[oos, "option_oi_state"].value_counts()
    counts = {
        "source_rows": SOURCE_ROWS,
        "source_dates": 261,
        "asset_week_groups": 1044,
        "all_parent_states": len(governed.weights),
        "oos_states": int(oos.sum()),
        "tail_put_states": int(state_counts.get("put_tail_shock", 0)),
        "tail_call_states": int(state_counts.get("call_tail_shock", 0)),
        "targets_reduced": int(
            (
                oos
                & governed.weights["option_oi_scale"].eq(0.0)
                & governed.weights["pre_option_oi_target_weight"].abs().gt(1e-12)
            ).sum()
        ),
        "mapped_targets": len(target_build.targets),
        "nonzero_targets": nonzero,
    }
    comparison = {
        name: {
            metric: float(results[name]["combined"][metric])
            - float(parent["scenarios"][name]["combined"][metric])
            for metric in ("total_return", "cagr", "sharpe", "maximum_drawdown", "worst_year")
        }
        for name in results
    }
    promotion = _promotion(results, checks, parent)
    identity = {
        "protocol_sha256": CONFIG_SHA256,
        "parent_v27_metrics_sha256": protocol["parent_v27"]["metrics_sha256"],
        "parent_weights_sha256": PARENT_WEIGHTS_SHA256,
        "source_manifest_sha256": source.manifest_sha256,
        "source_audit_sha256": source.audit_sha256,
        "source_parquet_sha256": SOURCE_PARQUET_SHA256,
        "code_sha256": v12.sha256_file(Path(__file__)),
        "contains_2026_prices_returns_targets_or_pnl": False,
    }
    payload = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "research_only": True,
        "adaptive_same_period": True,
        "live_trading_allowed": False,
        "checks": checks,
        "identity": identity,
        "counts": counts,
        "scenarios": results,
        "comparison_to_v27": comparison,
        "promotion": promotion,
    }
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    final = output_root.resolve() / f"v39_option_oi_tail_governor_{timestamp}_{CONFIG_SHA256[:8]}"
    final.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{final.name}.", dir=final.parent))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        v12._write_parquet(temporary / "weekly_v39_governed_weights.parquet", governed.weights)
        v12._write_parquet(temporary / "option_oi_governor.parquet", governed.governor)
        v12._write_parquet(temporary / "mapped_targets.parquet", target_build.targets)
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        for name, result in outputs.items():
            v12._write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            v12._write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            v12._write_parquet(temporary / f"positions_{name}.parquet", result.positions)
            v12._write_parquet(
                temporary / f"combined_ledger_{name}.parquet", collaterals[name].combined_ledger
            )
        artifacts = {}
        for path in sorted(temporary.iterdir()):
            item = {"bytes": path.stat().st_size, "sha256": v12.sha256_file(path)}
            if path.suffix == ".parquet":
                item["rows"] = pq.ParquetFile(path).metadata.num_rows
            artifacts[path.name] = item
        payload["artifacts"] = artifacts
        metrics = temporary / "metrics.json"
        metrics.write_text(
            json.dumps(v12._json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8-sig",
        )
        (temporary / "identity.json").write_text(
            json.dumps({**identity, "metrics_sha256": v12.sha256_file(metrics)}, indent=2) + "\n",
            encoding="utf-8-sig",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    args = parser.parse_args()
    print(run_experiment(args.output_root))


if __name__ == "__main__":
    main()
