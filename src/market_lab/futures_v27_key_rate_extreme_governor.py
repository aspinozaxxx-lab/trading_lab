"""Sealed V27: V26 capital efficiency with an extreme CBR key-rate cash governor."""

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
from market_lab import futures_v25_stlfsi_stress_governor as v25
from market_lab import futures_v26_stlfsi_levered_ruonia_capacity as v26
from market_lab.futures import info_radar
from market_lab.futures.portfolio_ledger import FuturesPortfolioLedgerResult

PROJECT_ROOT: Final[Path] = v12.PROJECT_ROOT
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v27_key_rate_extreme_governor.yaml"
CONFIG_SHA256: Final[str] = "7a9a44cf7b09c7820a514b2706e332744a3b30ced8b7d3d4c8bdf7448a3194fe"
V26_PROTOCOL_SHA256: Final[str] = v26.CONFIG_SHA256
V26_METRICS_SHA256: Final[str] = "b4149969696e23a29a06b58085510d9f8c9f2bbf584ca0d2aaa883801493567d"
V26_PRIMARY_REFERENCE: Final[dict[str, float]] = {
    "total_return": 1.9513836250949326,
    "cagr": 0.2416982598452151,
    "sharpe": 0.9763643289877022,
    "maximum_drawdown": 0.3356613090610189,
    "positive_years": 4.0,
    "worst_year": -0.12268625825407442,
    "total_cost_rub": 55297.66434774309,
    "critical_failure_count": 0.0,
}
KEY_RATE_COLUMNS: Final[tuple[str, ...]] = v15.RUONIA_COLUMNS
KEY_RATE_ROWS: Final[int] = 2015
KEY_RATE_BOUNDARY: Final[float] = 20.0
MAXIMUM_KEY_RATE_AGE_DAYS: Final[int] = 7
EXPECTED_ALL_STATES: Final[dict[str, int]] = {
    "weekly_decisions": 418,
    "pass_both": 309,
    "cash_stlfsi4": 68,
    "cash_key_rate_at_least_20": 40,
    "cash_key_rate_missing_or_stale": 1,
}
EXPECTED_OOS_STATES: Final[dict[str, int]] = {
    "weekly_decisions": 261,
    "pass_both": 197,
    "cash_stlfsi4": 24,
    "cash_key_rate_at_least_20": 40,
    "cash_key_rate_missing_or_stale": 0,
}


@dataclass(frozen=True, slots=True)
class KeyRateVerification:
    """Raw-replayed official key-rate observations with conservative timing."""

    frame: pd.DataFrame
    checks: dict[str, bool]
    raw_bytes: int
    raw_sha256: str


@dataclass(frozen=True, slots=True)
class MonetaryGovernorBuild:
    """V25 weights after the binary official key-rate cash state."""

    weights: pd.DataFrame
    governor: pd.DataFrame
    checks: dict[str, bool]


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the V27 byte seal and the one fixed monetary regime."""
    config_path = config_path.resolve()
    if config_path != CONFIG_PATH.resolve() or v12.sha256_file(config_path) != CONFIG_SHA256:
        raise ValueError("sealed V27 protocol byte drift")
    sidecar = config_path.with_suffix(".sha256")
    if sidecar.read_text(encoding="utf-8-sig").split()[0] != CONFIG_SHA256:
        raise ValueError("V27 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V27 protocol must be a mapping")

    parent = protocol["parent_v26"]
    inherited = protocol["input_inheritance"]
    governor = protocol["monetary_governor"]
    capital = protocol["capital_efficiency"]
    collateral = protocol["collateral_income"]
    execution = protocol["execution"]
    reference = {
        str(key): float(value) for key, value in parent["primary_combined_reference"].items()
    }
    declared_all = {
        str(key): int(value)
        for key, value in governor["sealed_state_counts"]["all_2018_2025"].items()
    }
    declared_oos = {
        str(key): int(value)
        for key, value in governor["sealed_state_counts"]["oos_2021_2025"].items()
    }
    raw = inherited["cbr_key_rate_transitive_raw"]
    if (
        protocol.get("protocol_id") != "futures_v27_key_rate_extreme_governor_v1"
        or protocol.get("status") != "predeclared_before_v27_oos_outcomes"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or parent["protocol_sha256"] != V26_PROTOCOL_SHA256
        or parent["metrics_sha256"] != V26_METRICS_SHA256
        or reference != V26_PRIMARY_REFERENCE
        or inherited["protocol_sha256"] != V26_PROTOCOL_SHA256
        or tuple(inherited["exact_input_names"]) != tuple(v26.load_protocol()["inputs"].keys())
        or inherited["new_market_outcome_input"] != "none"
        or raw["path"]
        != "raw/info_radar/cbr-dev-2018-2025-v1/0001_cbr_key_rate_soap_key_rate_xml.xml"
        or int(raw["bytes"]) != 121958
        or raw["sha256"] != "06da1497c27f985151bbb4455cc7f6109660edf190a8fbf5280c0d04016d4639"
        or raw["request_body_sha256"]
        != "04c6f1fc8ba0217fe150392a05dbb57e7070cc9f6e662e873dddda81cf819856"
        or float(governor["boundary_percent_per_annum"]) != KEY_RATE_BOUNDARY
        or governor["comparison"] != "greater_than_or_equal"
        or float(governor["admitted_scale_before_2x"]) != 1.0
        or float(governor["cash_scale_before_2x"]) != 0.0
        or int(governor["maximum_age_calendar_days"]) != MAXIMUM_KEY_RATE_AGE_DAYS
        or governor["threshold_fit"] != "none_round_economic_boundary"
        or governor["scale_can_increase_v26_risk"] is not False
        or int(governor["sealed_source_rows"]) != KEY_RATE_ROWS
        or declared_all != EXPECTED_ALL_STATES
        or declared_oos != EXPECTED_OOS_STATES
        or float(capital["target_weight_multiplier_after_governors"]) != v15.LEVERAGE_MULTIPLIER
        or float(capital["maximum_gross_notional_multiple"]) != v15.MAXIMUM_GROSS
        or float(capital["initial_margin_buffer_multiple"]) != v15.MARGIN_BUFFER_MULTIPLIER
        or collateral["inherited_byte_identical_from_V26"] is not True
        or float(collateral["applied_rate_fraction"]) != v15.RUONIA_APPLIED_FRACTION
        or float(collateral["operational_buffer_fraction_of_conservative_equity"])
        != v15.OPERATIONAL_BUFFER_FRACTION
        or collateral["reinvested_into_contract_sizing"] is not False
        or collateral["compounded_into_future_eligible_balance"] is not False
        or execution["inherited_byte_identical_from_V26"] is not True
        or execution["unexecutable_target_policy"] != "cancel_and_clip"
        or float(execution["maximum_participation"]) != v12.MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"]) != v15.MAXIMUM_GROSS
        or float(execution["initial_margin_buffer_multiple"]) != v15.MARGIN_BUFFER_MULTIPLIER
    ):
        raise ValueError("sealed V27 protocol invariants were weakened")
    if v12._scenario_settings(protocol) != {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }:
        raise ValueError("sealed V27 cost scenarios drifted")
    return protocol


def verify_inputs(protocol: dict[str, Any]) -> v12.VerifiedInputs:
    """Verify the inherited V26 inputs and make the V27 seal explicit."""
    if protocol["input_inheritance"]["protocol_sha256"] != V26_PROTOCOL_SHA256:
        raise ValueError("V27 input inheritance drift")
    parent_protocol = v26.load_protocol()
    verified = v26.verify_inputs(parent_protocol)
    checks = dict(verified.checks)
    checks["parent_v26_protocol_seal"] = checks.pop("v26_protocol_seal")
    checks["v27_protocol_seal"] = v12.sha256_file(CONFIG_PATH) == CONFIG_SHA256
    if not all(checks.values()):
        raise ValueError(f"V27 inherited input identity preflight failed: {checks}")
    return v12.VerifiedInputs(paths=verified.paths, checks=checks, metadata=verified.metadata)


def verify_key_rate_bundle(
    protocol: dict[str, Any], verified: v12.VerifiedInputs
) -> KeyRateVerification:
    """Replay the exact CBR SOAP response and prove processed values and timing."""
    manifest = json.loads(verified.paths["cbr_manifest"].read_text(encoding="utf-8-sig"))
    requests = [item for item in manifest["requests"] if item["series_id"] == "key_rate"]
    if len(requests) != 1:
        raise ValueError("V27 CBR manifest must have exactly one key-rate request")
    request = requests[0]
    declared = protocol["input_inheritance"]["cbr_key_rate_transitive_raw"]
    data_root = (PROJECT_ROOT / "data").resolve()
    raw_path = (data_root / str(request["raw_path"])).resolve()
    if (
        not raw_path.is_relative_to(data_root)
        or raw_path != (data_root / str(declared["path"])).resolve()
    ):
        raise ValueError("V27 key-rate raw path escapes or drifts")
    if not raw_path.is_file():
        raise FileNotFoundError("V27 key-rate raw response is missing")
    content = raw_path.read_bytes()
    content_sha = v12.sha256_file(raw_path)
    if (
        request["source"] != "cbr"
        or request["mode"] != "soap_key_rate_xml"
        or request["method"] != "POST"
        or request["request_body_sha256"] != declared["request_body_sha256"]
        or request["raw_path"] != declared["path"]
        or int(request["raw_bytes"]) != int(declared["bytes"])
        or request["raw_sha256"] != declared["sha256"]
        or len(content) != int(declared["bytes"])
        or content_sha != declared["sha256"]
        or b"2026-" in content
    ):
        raise ValueError("V27 key-rate raw request identity or protected boundary drift")

    rebuilt = (
        info_radar.parse_cbr_key_rate_xml(content)
        .drop(columns="effective_date")
        .reset_index(drop=True)
    )
    processed = pd.read_parquet(
        verified.paths["cbr_panel"],
        columns=list(KEY_RATE_COLUMNS),
        filters=[("series_id", "==", "key_rate")],
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(processed, rebuilt, check_exact=True)
    for column in ("observation_date", "publication_date"):
        processed[column] = pd.to_datetime(processed[column], errors="coerce").dt.normalize()
    processed["available_at"] = pd.to_datetime(processed["available_at"], errors="raise", utc=True)
    expected_available = (
        (processed["observation_date"] + pd.Timedelta(days=1))
        .dt.tz_localize(v15.MOSCOW_TIMEZONE)
        .dt.tz_convert("UTC")
    )
    rate = pd.to_numeric(processed["value"], errors="coerce").astype(float)
    if (
        len(processed) != KEY_RATE_ROWS
        or not processed["source"].astype("string").eq("cbr").all()
        or not processed["series_id"].astype("string").eq("key_rate").all()
        or processed["publication_date"].notna().any()
        or not processed["available_at"].equals(expected_available)
        or not processed["availability_rule"]
        .astype("string")
        .eq("effective_date_plus_one_calendar_day")
        .all()
        or processed["observation_date"].min() != pd.Timestamp("2018-01-09")
        or processed["observation_date"].max() != pd.Timestamp("2025-12-30")
        or processed["observation_date"].ge(v12.PROTECTED_FROM).any()
        or processed["available_at"].ge(pd.Timestamp("2026-01-01T00:00:00Z")).any()
        or rate.isna().any()
        or not np.isfinite(rate).all()
        or rate.le(0.0).any()
        or float(rate.min()) != 4.25
        or float(rate.max()) != 21.0
    ):
        raise ValueError("V27 key-rate processed identity, timing or values drifted")
    processed["key_rate_percent"] = rate
    checks = {
        "key_rate_manifest_one_exact_request": True,
        "key_rate_raw_path_hash_bytes_and_request_body_exact": True,
        "key_rate_raw_contains_no_2026_observation": True,
        "key_rate_processed_exactly_rebuilt_from_raw": True,
        "key_rate_filtered_series_only": True,
        "key_rate_rows_dates_range_and_schema_exact": True,
        "key_rate_conservative_availability_exact": True,
        "key_rate_values_finite_positive_and_range_exact": True,
        "key_rate_round_20_percent_boundary_not_fitted": True,
    }
    return KeyRateVerification(
        frame=processed.sort_values("available_at", kind="mergesort", ignore_index=True),
        checks=checks,
        raw_bytes=len(content),
        raw_sha256=content_sha,
    )


def _state_counts(frame: pd.DataFrame) -> dict[str, int]:
    counts = frame["combined_state"].value_counts()
    return {
        "weekly_decisions": int(len(frame)),
        "pass_both": int(counts.get("pass_both", 0)),
        "cash_stlfsi4": int(counts.get("cash_stlfsi4", 0)),
        "cash_key_rate_at_least_20": int(counts.get("cash_key_rate_at_least_20", 0)),
        "cash_key_rate_missing_or_stale": int(counts.get("cash_key_rate_missing_or_stale", 0)),
    }


def apply_monetary_governor(
    v25_weights: pd.DataFrame, key_rate: KeyRateVerification
) -> MonetaryGovernorBuild:
    """Move the whole V25 snapshot to cash only in the predeclared monetary state."""
    required = {
        "decision_date",
        "asset",
        "target_weight",
        "provenance",
        "governor_state",
        "risk_scale",
    }
    if missing := required - set(v25_weights.columns):
        raise ValueError(f"V27 V25 weights lack columns: {sorted(missing)}")
    weights = v25_weights.copy()
    weights["decision_date"] = pd.to_datetime(
        weights["decision_date"], errors="raise"
    ).dt.normalize()
    if (
        weights.duplicated(["decision_date", "asset"]).any()
        or weights.groupby("decision_date")["asset"].nunique().ne(len(v12.ASSETS)).any()
        or weights.groupby("decision_date")["governor_state"].nunique().ne(1).any()
        or weights.groupby("decision_date")["risk_scale"].nunique().ne(1).any()
    ):
        raise ValueError("V27 V25 weekly snapshots or states are incomplete")
    decisions = weights.loc[:, ["decision_date", "governor_state", "risk_scale"]].drop_duplicates(
        "decision_date"
    )
    decisions = decisions.sort_values("decision_date", kind="mergesort", ignore_index=True)
    decisions["decision_at"] = (
        decisions["decision_date"].dt.tz_localize(v15.MOSCOW_TIMEZONE)
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).dt.tz_convert("UTC")
    source = key_rate.frame.loc[
        :, ["observation_date", "available_at", "key_rate_percent"]
    ].sort_values("available_at", kind="mergesort")
    governor = pd.merge_asof(
        decisions.sort_values("decision_at", kind="mergesort"),
        source,
        left_on="decision_at",
        right_on="available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    governor["source_age_calendar_days"] = (
        governor["decision_date"] - governor["observation_date"]
    ).dt.days
    available = (
        governor["available_at"].notna()
        & governor["available_at"].le(governor["decision_at"])
        & governor["observation_date"].lt(v12.PROTECTED_FROM)
    )
    fresh = available & governor["source_age_calendar_days"].between(
        0, MAXIMUM_KEY_RATE_AGE_DAYS, inclusive="both"
    )
    stlfsi_pass = governor["governor_state"].eq("pass_normal_or_below") & governor["risk_scale"].eq(
        1.0
    )
    governor["combined_state"] = "cash_key_rate_missing_or_stale"
    governor.loc[fresh & ~stlfsi_pass, "combined_state"] = "cash_stlfsi4"
    governor.loc[
        fresh & stlfsi_pass & governor["key_rate_percent"].ge(KEY_RATE_BOUNDARY),
        "combined_state",
    ] = "cash_key_rate_at_least_20"
    governor.loc[
        fresh & stlfsi_pass & governor["key_rate_percent"].lt(KEY_RATE_BOUNDARY),
        "combined_state",
    ] = "pass_both"
    governor["monetary_scale"] = governor["combined_state"].eq("pass_both").astype(float)

    governed = weights.merge(
        governor.loc[
            :,
            [
                "decision_date",
                "key_rate_percent",
                "observation_date",
                "available_at",
                "source_age_calendar_days",
                "combined_state",
                "monetary_scale",
            ],
        ],
        on="decision_date",
        how="left",
        validate="many_to_one",
    )
    governed["pre_key_rate_target_weight"] = pd.to_numeric(
        governed["target_weight"], errors="raise"
    ).astype(float)
    governed["target_weight"] = governed["pre_key_rate_target_weight"] * governed["monetary_scale"]
    governed["provenance"] = governed["provenance"].astype("string") + np.select(
        [
            governed["combined_state"].eq("pass_both"),
            governed["combined_state"].eq("cash_stlfsi4"),
            governed["combined_state"].eq("cash_key_rate_at_least_20"),
        ],
        [
            "|key_rate_below_20_pass",
            "|stlfsi4_cash_retained",
            "|key_rate_at_least_20_cash",
        ],
        default="|key_rate_missing_or_stale_cash",
    )
    all_counts = _state_counts(governor)
    oos_counts = _state_counts(
        governor.loc[governor["decision_date"].between(v12.OOS_START, v12.OOS_END)]
    )
    checks = {
        "monetary_governor_complete_four_asset_snapshots": governed.groupby("decision_date")[
            "asset"
        ]
        .nunique()
        .eq(len(v12.ASSETS))
        .all(),
        "monetary_governor_available_at_not_after_decision": bool(
            governor.loc[governor["available_at"].notna(), "available_at"]
            .le(governor.loc[governor["available_at"].notna(), "decision_at"])
            .all()
        ),
        "monetary_governor_never_increases_v25_risk": bool(
            governed["target_weight"]
            .abs()
            .le(governed["pre_key_rate_target_weight"].abs() + 1e-12)
            .all()
        ),
        "monetary_governor_key_rate_boundary_exact": bool(
            governor.loc[
                governor["combined_state"].eq("cash_key_rate_at_least_20"),
                "key_rate_percent",
            ]
            .ge(KEY_RATE_BOUNDARY)
            .all()
        ),
        "monetary_governor_all_state_counts_exact": all_counts == EXPECTED_ALL_STATES,
        "monetary_governor_oos_state_counts_exact": oos_counts == EXPECTED_OOS_STATES,
    }
    if not all(checks.values()):
        raise ValueError(
            f"V27 monetary governor invariant failure: {checks}, {all_counts}, {oos_counts}"
        )
    return MonetaryGovernorBuild(
        weights=governed.sort_values(
            ["decision_date", "asset"], kind="mergesort", ignore_index=True
        ),
        governor=governor.sort_values("decision_date", kind="mergesort", ignore_index=True),
        checks=checks,
    )


def _comparison(primary: dict[str, Any]) -> dict[str, Any]:
    combined = primary["combined"]
    futures = primary["futures_only"]
    return {
        "protocol_sha256": V26_PROTOCOL_SHA256,
        "metrics_sha256": V26_METRICS_SHA256,
        "reference": V26_PRIMARY_REFERENCE,
        "delta": {
            "total_return": float(combined["total_return"]) - V26_PRIMARY_REFERENCE["total_return"],
            "cagr": float(combined["cagr"]) - V26_PRIMARY_REFERENCE["cagr"],
            "sharpe": float(combined["sharpe"]) - V26_PRIMARY_REFERENCE["sharpe"],
            "maximum_drawdown_reduction": V26_PRIMARY_REFERENCE["maximum_drawdown"]
            - float(combined["maximum_drawdown"]),
            "worst_year_improvement": float(combined["worst_year"])
            - V26_PRIMARY_REFERENCE["worst_year"],
            "cost_reduction_rub": V26_PRIMARY_REFERENCE["total_cost_rub"]
            - float(futures["total_cost"]),
        },
    }


def _promotion(results: dict[str, dict[str, Any]], checks: dict[str, bool]) -> dict[str, Any]:
    primary = results["primary"]["combined"]
    conditions = {
        "every_parent_input_key_rate_raw_replay_source_temporal_and_accrual_check_true": all(
            checks.values()
        ),
        "exact_predeclared_weekly_combined_state_counts": checks[
            "monetary_governor_all_state_counts_exact"
        ]
        and checks["monetary_governor_oos_state_counts_exact"],
        "all_scenarios_execution_and_combined_metrics_complete": all(
            bool(value["futures_only"]["execution_complete"])
            and bool(value["combined"]["metrics_valid"])
            for value in results.values()
        ),
        "zero_critical_failures_and_zero_unresolved_halts": all(
            int(value["futures_only"]["critical_failure_count"]) == 0
            and int(value["futures_only"]["unresolved_halt_count"]) == 0
            for value in results.values()
        ),
        "all_scenarios_combined_cagr_at_least_0_20": all(
            float(value["combined"]["cagr"]) >= 0.20 for value in results.values()
        ),
        "all_scenarios_combined_maximum_drawdown_at_most_0_30": all(
            float(value["combined"]["maximum_drawdown"]) <= 0.30 for value in results.values()
        ),
        "primary_combined_sharpe_at_least_sealed_v26": float(primary["sharpe"])
        >= V26_PRIMARY_REFERENCE["sharpe"],
        "primary_combined_worst_year_at_least_sealed_v26": float(primary["worst_year"])
        >= V26_PRIMARY_REFERENCE["worst_year"],
        "primary_combined_positive_years_at_least_4_of_5": int(primary["positive_years"]) >= 4
        and len(primary["annual_returns"]) == 5,
        "no_order_time_gross_participation_or_margin_breach": all(
            float(value["futures_only"]["maximum_participation"])
            <= v12.MAXIMUM_PARTICIPATION + 1e-12
            and int(value["futures_only"]["gross_limit_rejection_count"]) == 0
            and int(value["futures_only"]["initial_margin_rejection_count"]) == 0
            and float(value["futures_only"]["ending_cash"]) > 0.0
            for value in results.values()
        ),
    }
    passed = all(conditions.values())
    return {
        "conditions": conditions,
        "passed": passed,
        "verdict": "GO_TO_NEW_UNSEEN_VALIDATION" if passed else "NO_GO",
        "live_trading_allowed": False,
        "independent_confirmation_required": True,
    }


def _report_text(payload: dict[str, Any]) -> str:
    lines = [
        "# V27 official CBR extreme key-rate cash governor",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        "This is one adaptive 2021-2025 stability test, not independent confirmation.",
        "",
        "| Scenario | Combined return | CAGR | Sharpe | MDD | Worst year | Costs RUB |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("primary", "doubled", "stress"):
        item = payload["scenarios"][name]
        combined = item["combined"]
        futures = item["futures_only"]
        lines.append(
            f"| {name} | {combined['total_return']:.4%} | {combined['cagr']:.4%} | "
            f"{combined['sharpe']:.3f} | {combined['maximum_drawdown']:.4%} | "
            f"{combined['worst_year']:.4%} | {futures['total_cost']:.2f} |"
        )
    delta = payload["comparison_to_v26"]["delta"]
    counts = payload["counts"]
    lines.extend(
        [
            "",
            "## Delta versus sealed V26 primary",
            "",
            f"- CAGR: {delta['cagr']:+.4%}",
            f"- Sharpe: {delta['sharpe']:+.4f}",
            f"- Drawdown reduction: {delta['maximum_drawdown_reduction']:+.4%}",
            f"- Worst-year improvement: {delta['worst_year_improvement']:+.4%}",
            f"- Cost reduction: {delta['cost_reduction_rub']:+.2f} RUB",
            "",
            "## Primary combined annual returns",
            "",
        ]
    )
    for year, value in payload["scenarios"]["primary"]["combined"]["annual_returns"].items():
        lines.append(f"- {year}: {value:.4%}")
    lines.extend(
        [
            "",
            "## Source and states",
            "",
            f"- Raw CBR key-rate replay bytes: {counts['key_rate_raw_bytes']}",
            f"- Key-rate processed rows: {counts['key_rate_source_rows']}",
            f"- OOS both-governors pass weeks: {counts['oos_pass_both']}",
            f"- OOS STLFSI4 cash weeks: {counts['oos_cash_stlfsi4']}",
            f"- OOS key-rate >=20% cash weeks: {counts['oos_cash_key_rate_at_least_20']}",
            f"- OOS missing/stale key-rate cash weeks: "
            f"{counts['oos_cash_key_rate_missing_or_stale']}",
            "",
            "The exact 20% boundary and seven-day age cap were sealed before this run. "
            "Key-rate availability is conservatively delayed to the next calendar day.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute exactly one immutable V27 adaptive-development run."""
    protocol = load_protocol()
    parent_protocol = v26.load_protocol()
    verified = verify_inputs(protocol)
    stlfsi = v25.verify_stlfsi_bundle(parent_protocol, verified)
    key_rate = verify_key_rate_bundle(protocol, verified)

    panel = pd.read_parquet(
        verified.paths["panel"],
        columns=parent_protocol["inputs"]["panel"]["allowed_columns"],
    )
    active = pd.read_parquet(
        verified.paths["active_contract_map"],
        columns=parent_protocol["inputs"]["active_contract_map"]["allowed_columns"],
    )
    observations = pd.read_parquet(
        verified.paths["contract_observations"],
        columns=parent_protocol["inputs"]["contract_observations"]["allowed_columns"],
    )
    specs = pd.read_parquet(
        verified.paths["spec_proxy"],
        columns=parent_protocol["inputs"]["spec_proxy"]["allowed_columns"],
    )
    ruonia_frame = pd.read_parquet(
        verified.paths["cbr_panel"],
        columns=parent_protocol["inputs"]["cbr_panel"]["allowed_columns"],
        filters=[("series_id", "==", "ruonia")],
    )
    ruonia = v15.verify_ruonia(ruonia_frame)
    checks = {
        **verified.checks,
        **stlfsi.checks,
        **key_rate.checks,
        **ruonia.checks,
    }
    scores = v12.build_trend_scores(panel)
    weekly_v12 = v12.build_weekly_weights(panel, scores)
    governed_v25 = v25.apply_weekly_governor(weekly_v12, stlfsi)
    checks.update(governed_v25.checks)
    monetary = apply_monetary_governor(governed_v25.weights, key_rate)
    checks.update(monetary.checks)
    levered = v26.build_levered_governed_weights(monetary.weights)
    target_build = v26.build_execution_targets(monetary.weights, active)
    mapped_gross = target_build.targets.groupby("effective_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    checks["mapped_target_gross_at_most_two"] = bool(
        mapped_gross.le(v15.MAXIMUM_GROSS + 1e-12).all()
    )
    market = v12.build_execution_market(observations, specs)
    coverage = v12.execution_coverage(market, target_build.targets)
    nonzero_targets = int(target_build.targets["target_weight"].abs().gt(1e-12).sum())
    covered_nonzero_targets = int(coverage["execution_dependencies_complete"].sum())
    checks["all_nonzero_next_open_dependencies_complete"] = (
        covered_nonzero_targets == nonzero_targets
    )
    if not all(checks.values()):
        raise ValueError(f"V27 pre-execution invariant failure: {checks}")

    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < v12.OOS_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(predecessor, v12.OOS_END)
    ].copy()
    scenario_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    collateral_outputs: dict[str, v15.CollateralEvaluation] = {}
    scenario_results: dict[str, dict[str, Any]] = {}
    for name, settings in v12._scenario_settings(protocol).items():
        result = v15.run_levered_portfolio_ledger(
            execution_market,
            target_build.targets,
            v26.CapacityAwareLeveredLedgerConfig(
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name], collateral_outputs[name] = v15._scenario_payload(
            result, execution_market, settings, ruonia
        )

    oos_governor = monetary.governor.loc[
        monetary.governor["decision_date"].between(v12.OOS_START, v12.OOS_END)
    ]
    oos_counts = _state_counts(oos_governor)
    counts = {
        "source_panel_rows": int(len(panel)),
        "source_ruonia_rows": int(len(ruonia.frame)),
        "stlfsi_source_rows": int(len(stlfsi.frame)),
        "key_rate_source_rows": int(len(key_rate.frame)),
        "key_rate_raw_bytes": key_rate.raw_bytes,
        "key_rate_raw_sha256": key_rate.raw_sha256,
        "all_weekly_decisions": int(len(monetary.governor)),
        "oos_weekly_decisions": oos_counts["weekly_decisions"],
        "oos_pass_both": oos_counts["pass_both"],
        "oos_cash_stlfsi4": oos_counts["cash_stlfsi4"],
        "oos_cash_key_rate_at_least_20": oos_counts["cash_key_rate_at_least_20"],
        "oos_cash_key_rate_missing_or_stale": oos_counts["cash_key_rate_missing_or_stale"],
        "mapped_weekly_decisions": target_build.weekly_decisions,
        "roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": int(len(target_build.targets)),
        "nonzero_targets": nonzero_targets,
        "covered_nonzero_targets": covered_nonzero_targets,
    }
    comparison = _comparison(scenario_results["primary"])
    promotion = _promotion(scenario_results, checks)
    code_paths = {
        "v27_implementation": Path(__file__).resolve(),
        "v26_parent": Path(v26.__file__).resolve(),
        "v25_governor_parent": Path(v25.__file__).resolve(),
        "v15_collateral_parent": Path(v15.__file__).resolve(),
        "v12_frozen_parent": Path(v12.__file__).resolve(),
        "info_radar": Path(info_radar.__file__).resolve(),
        "portfolio_ledger": PROJECT_ROOT / "src/market_lab/futures/portfolio_ledger.py",
    }
    identity = {
        "protocol_sha256": CONFIG_SHA256,
        "parent_v26_protocol_sha256": V26_PROTOCOL_SHA256,
        "parent_v26_metrics_sha256": V26_METRICS_SHA256,
        "inherited_input_sha256": {
            name: declaration["sha256"] for name, declaration in parent_protocol["inputs"].items()
        },
        "key_rate_transitive_raw_sha256": key_rate.raw_sha256,
        "code_sha256": {name: v12.sha256_file(path) for name, path in code_paths.items()},
        "protected_from": v12.PROTECTED_FROM.date().isoformat(),
        "contains_2026_prices_returns_targets_or_pnl": False,
    }
    payload: dict[str, Any] = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "research_only": True,
        "adaptive_same_period": True,
        "independent_holdout_confirmation": False,
        "live_trading_allowed": False,
        "checks": checks,
        "input_metadata": verified.metadata,
        "identity": identity,
        "counts": counts,
        "scenarios": scenario_results,
        "comparison_to_v26": comparison,
        "promotion": promotion,
        "limitations": protocol["execution"]["limitations"],
    }

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v27_key_rate_governor_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V27 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        shutil.copyfile(v26.CONFIG_PATH, temporary / "parent_v26_protocol.yaml")
        v12._write_parquet(temporary / "scores.parquet", scores)
        v12._write_parquet(temporary / "weekly_v12_weights.parquet", weekly_v12)
        v12._write_parquet(temporary / "weekly_v25_governed_weights.parquet", governed_v25.weights)
        v12._write_parquet(
            temporary / "weekly_v27_monetary_governed_weights.parquet", monetary.weights
        )
        v12._write_parquet(temporary / "weekly_v27_levered_weights.parquet", levered)
        monetary.governor.to_csv(
            temporary / "combined_governor.csv", index=False, encoding="utf-8-sig"
        )
        v12._write_parquet(temporary / "mapped_targets.parquet", target_build.targets)
        target_build.decision_audit.to_csv(
            temporary / "decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        for name, result in scenario_outputs.items():
            v12._write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            v12._write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            v12._write_parquet(temporary / f"positions_{name}.parquet", result.positions)
            v12._write_parquet(
                temporary / f"collateral_{name}.parquet", collateral_outputs[name].audit
            )
            v12._write_parquet(
                temporary / f"combined_ledger_{name}.parquet",
                collateral_outputs[name].combined_ledger,
            )
        (temporary / "report.md").write_text(_report_text(payload), encoding="utf-8-sig")
        artifacts: dict[str, Any] = {}
        for path in sorted(temporary.iterdir()):
            if path.name in {"metrics.json", "identity.json"}:
                continue
            entry: dict[str, Any] = {
                "bytes": path.stat().st_size,
                "sha256": v12.sha256_file(path),
            }
            if path.suffix == ".parquet":
                entry["rows"] = pq.ParquetFile(path).metadata.num_rows
            artifacts[path.name] = entry
        payload["artifacts"] = artifacts
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(v12._json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8-sig",
        )
        (temporary / "identity.json").write_text(
            json.dumps(
                v12._json_safe({**identity, "metrics_sha256": v12.sha256_file(metrics_path)}),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8-sig",
        )
        temporary.replace(final)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "runs",
        help="External immutable runs root; a unique V27 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
