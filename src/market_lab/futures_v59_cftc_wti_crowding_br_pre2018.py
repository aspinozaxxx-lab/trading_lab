"""Sealed V59 reverse-chronology CFTC crowding test on MOEX Brent."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v58_cftc_wti_positioning_br as v58

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v59r1_cftc_wti_crowding_br_pre2018.yaml"
CONFIG_SHA256: Final[str] = "a79613a3926cbe83f6a276fd211968618b4174190bb18b59b8150e4525526018"
PARENT_CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v59_cftc_wti_crowding_br_pre2018.yaml"
)
PARENT_CONFIG_SHA256: Final[str] = (
    "cf597ddc1df453a036597d4c11ba66618c073b816f6acc3c4ec784edb035896f"
)
START: Final[pd.Timestamp] = pd.Timestamp("2013-01-01")
END: Final[pd.Timestamp] = pd.Timestamp("2017-12-01")
PROTECTED: Final[pd.Timestamp] = pd.Timestamp("2018-01-01")


def load_protocol() -> dict[str, Any]:
    if v58.sha256_file(CONFIG_PATH) != CONFIG_SHA256:
        raise ValueError("V59 protocol byte drift")
    stated = CONFIG_PATH.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    correction = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if v58.sha256_file(PARENT_CONFIG_PATH) != PARENT_CONFIG_SHA256:
        raise ValueError("V59 parent protocol byte drift")
    protocol = yaml.safe_load(PARENT_CONFIG_PATH.read_text(encoding="utf-8-sig"))
    signal = protocol["signal"]
    risk = protocol["risk_execution"]
    if (
        stated != CONFIG_SHA256
        or correction.get("protocol_id") != "futures_v59r1_cftc_wti_crowding_br_pre2018_v1"
        or correction.get("status")
        != "sealed_execution_only_correction_after_invalid_v59_before_any_valid_v59_economics"
        or correction.get("live_trading_allowed") is not False
        or correction["parent"]["sha256"] != PARENT_CONFIG_SHA256
        or correction["only_change"]["unexecutable_target_policy"]["from"] != "retry"
        or correction["only_change"]["unexecutable_target_policy"]["to"] != "cancel_and_clip"
        or correction["only_change"]["sign_lag_risk_cap_costs_dates_and_gates_unchanged"]
        is not True
        or protocol.get("live_trading_allowed") is not False
        or protocol["parent_mechanics"]["v58_protocol_sha256"] != v58.CONFIG_SHA256
        or signal["direction"] != "positive_short_BR_negative_long_BR_exact_zero_cash"
        or int(signal["lookback_admitted_reports"]) != 13
        or int(signal["maximum_source_age_calendar_days"]) != 14
        or int(risk["BR_log_volatility_lookback_sessions"]) != 20
        or float(risk["annual_volatility_target"]) != 0.30
        or float(risk["maximum_absolute_target"]) != 2.0
        or int(risk["price_baseline_lookback_sessions"]) != 63
        or risk["costs"] != {"primary": [1, 1], "doubled": [2, 2], "stress": [4, 2]}
    ):
        raise ValueError("V59 sealed economics drifted")
    protocol["protocol_id"] = correction["protocol_id"]
    return protocol


def _path(value: str) -> Path:
    relative = Path(value)
    if (
        relative.is_absolute()
        or not relative.parts
        or relative.parts[0].lower() != "data"
        or ".." in relative.parts
    ):
        raise ValueError("unsafe V59 data path")
    path = (PROJECT_ROOT / relative).resolve()
    if not path.is_relative_to((PROJECT_ROOT / "data").resolve()):
        raise ValueError("V59 path escapes data root")
    return path


def verify_inputs(protocol: dict[str, Any]) -> tuple[dict[str, Path], dict[str, bool]]:
    paths: dict[str, Path] = {}
    checks = {"protocol_seal": v58.sha256_file(CONFIG_PATH) == CONFIG_SHA256}
    for name, declaration in protocol["inputs"].items():
        path = _path(declaration["path"])
        paths[name] = path
        checks[f"{name}_exists"] = path.is_file()
        checks[f"{name}_bytes"] = path.is_file() and path.stat().st_size == int(
            declaration["bytes"]
        )
        checks[f"{name}_sha256"] = path.is_file() and v58.sha256_file(path) == declaration["sha256"]
    if not all(checks.values()):
        raise ValueError(f"V59 input identity failed: {checks}")
    source_audit = json.loads(paths["cftc_audit"].read_text(encoding="utf-8-sig"))
    market_audit = json.loads(paths["market_audit"].read_text(encoding="utf-8-sig"))
    checks["cftc_audit_all_true"] = source_audit["all_true"] is True
    checks["market_audit_valid"] = (
        market_audit["protected_from"] == "2018-01-01"
        and market_audit["contains_returns_targets_labels_or_pnl"] is False
        and int(market_audit["unresolved_roll_count"]) == 0
        and int(market_audit["unresolved_exit_count"]) == 0
        and int(market_audit["assets"]["BR"]["missing_mark_carry_count"]) == 0
    )
    if not all(checks.values()):
        raise ValueError(f"V59 source audit failed: {checks}")
    return paths, checks


def build_contrarian_signals(panel: pd.DataFrame, cftc: pd.DataFrame) -> pd.DataFrame:
    signals = v58.build_weekly_signals(panel, cftc)
    signals["continuation_candidate_sign"] = signals["candidate_sign"]
    signals["continuation_candidate_target_weight"] = signals["candidate_target_weight"]
    signals["candidate_sign"] = -signals["continuation_candidate_sign"]
    signals["candidate_target_weight"] = -signals["continuation_candidate_target_weight"]
    if signals["decision_date"].ge(PROTECTED).any():
        raise ValueError("V59 signal crosses protected boundary")
    return signals


@dataclass(frozen=True, slots=True)
class V59R1LedgerConfig:
    initial_cash: float = 1_000_000.0
    expected_assets: tuple[str, ...] = ("BR",)
    maximum_gross_notional_multiple: float = 2.0
    initial_margin_buffer_multiplier: float = 2.0
    maximum_participation: float = 0.01
    slippage_ticks: int = 1
    fee_multiplier: float = 1.0
    execution_atomicity: str = "asset"
    terminal_policy: str = "carry"
    unexecutable_target_policy: str = "cancel_and_clip"


def _scenario_metrics(
    result: Any, market: pd.DataFrame, settings: dict[str, float]
) -> dict[str, Any]:
    ledger = result.ledger
    dates = pd.to_datetime(ledger["session_date"], errors="raise")
    daily = ledger["ending_cash"].astype(float) / ledger["starting_cash"].astype(float) - 1.0
    annual = {
        str(year): float((1.0 + daily.loc[dates.dt.year.eq(year)]).prod() - 1.0)
        for year in range(2013, 2018)
        if dates.dt.year.eq(year).any()
    }
    reserve = v12._terminal_exit_reserve(result, market, settings)
    orders = result.orders
    return {
        **v58._json_safe(result.metrics),
        "metrics_valid": bool(result.execution_complete),
        "annual_returns": annual,
        "positive_years": int(sum(value > 0.0 for value in annual.values())),
        "worst_year": min(annual.values()) if annual else None,
        "terminal_exit_cost_reserve": reserve,
        "rejected_leg_count": int((~orders["filled"]).sum()) if not orders.empty else 0,
        "settings": settings,
    }


def compute(
    protocol: dict[str, Any], paths: dict[str, Path], checks: dict[str, bool]
) -> dict[str, Any]:
    panel = pd.read_parquet(paths["market_panel"], columns=["trade_date", "asset_code", "close"])
    cftc = pd.read_parquet(
        paths["cftc_positions"],
        columns=[
            "report_date",
            "available_at_utc",
            "logical_market",
            "open_interest",
            "managed_money_long",
            "managed_money_short",
        ],
    )
    active = pd.read_parquet(
        paths["active_contract_map"],
        columns=[
            "decision_date",
            "effective_date",
            "observed_through",
            "asset_code",
            "contract_id",
            "plan_tradable",
            "roll",
        ],
    )
    observations = pd.read_parquet(
        paths["contract_observations"],
        columns=[
            "trade_date",
            "logical_asset",
            "canonical_contract_id",
            "open",
            "high",
            "low",
            "close",
            "settle",
            "volume",
        ],
    )
    specs = pd.read_parquet(paths["spec_proxy"])
    signals = build_contrarian_signals(panel, cftc)
    candidate = v58.build_execution_targets(
        signals,
        active,
        "candidate_target_weight",
        evaluation_start=START,
        evaluation_end=END,
    )
    baseline = v58.build_execution_targets(
        signals,
        active,
        "baseline_target_weight",
        evaluation_start=START,
        evaluation_end=END,
    )
    market = v12.build_execution_market(observations, specs)
    market = market.loc[market["asset_code"].eq("BR")].copy()
    dates = pd.to_datetime(market["session_date"], errors="raise")
    predecessor = dates.loc[dates.lt(START)].max()
    market = market.loc[dates.between(predecessor, END)].copy()
    settings_by_name = {
        name: {"slippage_ticks": int(values[0]), "fee_multiplier": float(values[1])}
        for name, values in protocol["risk_execution"]["costs"].items()
    }
    candidate_outputs = {}
    baseline_outputs = {}
    candidate_metrics = {}
    baseline_metrics = {}
    for name, settings in settings_by_name.items():
        config = V59R1LedgerConfig(
            slippage_ticks=settings["slippage_ticks"], fee_multiplier=settings["fee_multiplier"]
        )
        candidate_outputs[name] = v58.run_v58_ledger(market, candidate.targets, config)
        baseline_outputs[name] = v58.run_v58_ledger(market, baseline.targets, config)
        candidate_metrics[name] = _scenario_metrics(candidate_outputs[name], market, settings)
        baseline_metrics[name] = _scenario_metrics(baseline_outputs[name], market, settings)
    primary = candidate_metrics["primary"]
    conditions = {
        "all_checks_true": all(checks.values()),
        "all_scenarios_complete": all(
            item["execution_complete"] for item in candidate_metrics.values()
        ),
        "all_scenarios_cagr_gte_20": all(
            item["cagr"] >= 0.20 for item in candidate_metrics.values()
        ),
        "primary_sharpe_gte_1": primary["sharpe"] >= 1.0,
        "all_scenarios_mdd_lte_30": all(
            item["maximum_drawdown"] <= 0.30 for item in candidate_metrics.values()
        ),
        "primary_positive_years_gte_4": primary["positive_years"] >= 4,
    }
    metrics = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "checks": checks,
        "counts": {
            "signals": len(signals),
            "weekly_decisions": candidate.weekly_decisions,
            "roll_decisions": candidate.roll_decisions,
            "nonzero_targets": int(candidate.targets["target_weight"].ne(0).sum()),
        },
        "candidate": candidate_metrics,
        "price_baseline": baseline_metrics,
        "promotion": {
            "conditions": conditions,
            "passed": all(conditions.values()),
            "verdict": "PROMISING_REQUIRES_FORWARD" if all(conditions.values()) else "NO_GO",
            "live_trading_allowed": False,
        },
        "limitations": protocol["limitations"],
    }
    return {
        "signals": signals,
        "candidate_targets": candidate.targets,
        "baseline_targets": baseline.targets,
        "candidate_outputs": candidate_outputs,
        "baseline_outputs": baseline_outputs,
        "metrics": metrics,
    }


def run_experiment(output_root: Path) -> Path:
    protocol = load_protocol()
    paths, checks = verify_inputs(protocol)
    result = compute(protocol, paths, checks)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"v59r1_cftc_wti_crowding_br_pre2018_v1_{timestamp}_{CONFIG_SHA256[:8]}"
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / name
    temporary = Path(tempfile.mkdtemp(prefix=f".{name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        for key in ("signals", "candidate_targets", "baseline_targets"):
            result[key].to_parquet(temporary / f"{key}.parquet", index=False)
        for arm in ("candidate", "baseline"):
            for scenario, output in result[f"{arm}_outputs"].items():
                output.ledger.to_parquet(
                    temporary / f"{arm}_ledger_{scenario}.parquet", index=False
                )
                output.orders.to_parquet(
                    temporary / f"{arm}_orders_{scenario}.parquet", index=False
                )
                output.positions.to_parquet(
                    temporary / f"{arm}_positions_{scenario}.parquet", index=False
                )
        (temporary / "metrics.json").write_text(
            json.dumps(v58._json_safe(result["metrics"]), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8-sig",
        )
        artifacts = {
            path.name: {"bytes": path.stat().st_size, "sha256": v58.sha256_file(path)}
            for path in temporary.iterdir()
        }
        manifest = {
            "protocol_sha256": CONFIG_SHA256,
            "implementation_sha256": v58.sha256_file(Path(__file__)),
            "contains_2018_plus_outcome": False,
            "artifacts": artifacts,
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8-sig"
        )
        (temporary / "manifest.sha256").write_text(
            f"{v58.sha256_file(temporary / 'manifest.json')}  manifest.json\n",
            encoding="utf-8-sig",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    audit = audit_run(final)
    (final / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8-sig")
    if not audit["all_true"]:
        raise ValueError("V59 audit failed")
    return final


def audit_run(run_root: Path) -> dict[str, Any]:
    protocol = load_protocol()
    paths, checks = verify_inputs(protocol)
    replay = compute(protocol, paths, checks)
    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8-sig"))
    audit_checks = {
        "protocol_exact": manifest["protocol_sha256"] == CONFIG_SHA256,
        "implementation_exact": manifest["implementation_sha256"]
        == v58.sha256_file(Path(__file__)),
        "protected_outcomes_absent": manifest["contains_2018_plus_outcome"] is False,
        "artifacts_exact": all(
            v58.sha256_file(run_root / name) == item["sha256"]
            for name, item in manifest["artifacts"].items()
        ),
        "metrics_replay_exact": json.loads(
            (run_root / "metrics.json").read_text(encoding="utf-8-sig")
        )
        == v58._json_safe(replay["metrics"]),
    }
    for key in ("signals", "candidate_targets", "baseline_targets"):
        try:
            pd.testing.assert_frame_equal(
                pd.read_parquet(run_root / f"{key}.parquet"), replay[key], check_dtype=False
            )
            audit_checks[f"replay_{key}"] = True
        except AssertionError:
            audit_checks[f"replay_{key}"] = False
    return {"checks": audit_checks, "all_true": all(audit_checks.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "runs")
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    if args.audit:
        audit = audit_run(args.audit)
        print(json.dumps(audit, indent=2))
        raise SystemExit(0 if audit["all_true"] else 1)
    print(run_experiment(args.output_root))


if __name__ == "__main__":
    main()
