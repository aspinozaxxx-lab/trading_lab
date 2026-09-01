"""Sealed V24 frozen-V12 trend with a daily Cboe VIX/VIX3M risk governor."""

from __future__ import annotations

import argparse
import base64
import gzip
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
from market_lab.futures import cboe_vix_term_structure_source as vix_source
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    FuturesPortfolioLedgerResult,
    run_futures_portfolio_ledger,
)

PROJECT_ROOT: Final[Path] = v12.PROJECT_ROOT
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v24_cboe_vix_term_structure_governor.yaml"
)
CONFIG_SHA256: Final[str] = (
    "f81b5aaa666346fa049b550e5dfc92c24ecf6ef2790a2cb00fb83235f24c064c"
)
V12_PROTOCOL_SHA256: Final[str] = v12.CONFIG_SHA256
V12_METRICS_SHA256: Final[str] = "c989377f7de65c3ef0a8dd52a1f5fcbf11c6ad8048119ea0a7b4402f47b23288"
V12_PRIMARY_REFERENCE: Final[dict[str, float]] = {
    "total_return": 0.451113922334873,
    "cagr": 0.07731837008966158,
    "sharpe": 0.7624477569712388,
    "maximum_drawdown": 0.14152584161232418,
    "positive_years": 4.0,
    "worst_year": -0.026317846517727284,
    "total_cost_rub": 13387.28160116245,
}
VIX_COLUMNS: Final[tuple[str, ...]] = (
    "observation_date",
    "vix_close",
    "vix3m_close",
    "available_at",
    "complete_pair",
    "vix_vix3m_ratio",
    "term_structure",
    "retrieved_at_utc",
    "source_current_vintage",
)
COVERAGE_COLUMNS: Final[tuple[str, ...]] = (
    "series_id",
    "value_column",
    "url",
    "response_bytes",
    "response_sha256",
    "rows",
    "nonmissing_rows",
    "missing_rows",
    "minimum_observation_date",
    "maximum_observation_date",
)
MAXIMUM_SOURCE_AGE_DAYS: Final[int] = 4
EXPECTED_ALL_STATES: Final[dict[str, int]] = {
    "decision_dates": 2024,
    "pass_contango": 1785,
    "cash_backwardation": 167,
    "cash_flat": 0,
    "cash_missing_or_stale": 72,
}
EXPECTED_OOS_STATES: Final[dict[str, int]] = {
    "decision_dates": 1270,
    "pass_contango": 1170,
    "cash_backwardation": 53,
    "cash_flat": 0,
    "cash_missing_or_stale": 47,
}


@dataclass(frozen=True, slots=True)
class VixVerification:
    """Strictly replayed source bundle and its proof checks."""

    frame: pd.DataFrame
    coverage: pd.DataFrame
    checks: dict[str, bool]
    raw_records: int


@dataclass(frozen=True, slots=True)
class GovernorBuild:
    """Daily frozen-V12 targets and one-row-per-decision source audit."""

    weights: pd.DataFrame
    governor: pd.DataFrame
    checks: dict[str, bool]


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the V24 byte seal and every fixed economic choice."""
    config_path = config_path.resolve()
    if config_path != CONFIG_PATH.resolve() or v12.sha256_file(config_path) != CONFIG_SHA256:
        raise ValueError("sealed V24 protocol byte drift")
    sidecar = config_path.with_suffix(".sha256")
    stated = sidecar.read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V24 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V24 protocol must be a mapping")
    parent = protocol["parent_v12"]
    signal = protocol["signal"]
    governor = protocol["risk_governor"]
    portfolio = protocol["portfolio"]
    execution = protocol["execution"]
    reference = {str(key): float(value) for key, value in parent["primary_reference"].items()}
    declared_all = {
        str(key): int(value)
        for key, value in governor["sealed_state_counts"]["all_2018_2025"].items()
    }
    declared_oos = {
        str(key): int(value)
        for key, value in governor["sealed_state_counts"]["oos_2021_2025"].items()
    }
    expected_all_without_flat = {
        key: value for key, value in EXPECTED_ALL_STATES.items() if key != "cash_flat"
    }
    expected_oos_without_flat = {
        key: value for key, value in EXPECTED_OOS_STATES.items() if key != "cash_flat"
    }
    if (
        protocol.get("protocol_id") != "futures_v24_cboe_vix_term_structure_governor_v1"
        or protocol.get("status") != "predeclared_before_v24_oos_outcomes"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or tuple(protocol["universe"]["exact_order"]) != v12.ASSETS
        or parent["protocol_sha256"] != V12_PROTOCOL_SHA256
        or parent["metrics_sha256"] != V12_METRICS_SHA256
        or reference != V12_PRIMARY_REFERENCE
        or tuple(protocol["inputs"]["vix_term_structure"]["allowed_columns"]) != VIX_COLUMNS
        or tuple(protocol["inputs"]["vix_coverage"]["allowed_columns"]) != COVERAGE_COLUMNS
        or tuple(int(value) for value in signal["log_momentum_horizons_sessions"])
        != v12.MOMENTUM_HORIZONS
        or int(signal["volatility_lookback_sessions"]) != v12.VOLATILITY_LOOKBACK
        or int(signal["annualization_sessions"]) != v12.ANNUALIZATION
        or float(signal["volatility_floor_annualized"]) != v12.VOLATILITY_FLOOR
        or signal.get("score_implementation") != "imported_frozen_v12"
        or signal.get("hyperparameter_search") is not False
        or float(governor["structural_boundary"]) != 1.0
        or float(governor["admitted_scale"]) != 1.0
        or float(governor["cash_scale"]) != 0.0
        or int(governor["maximum_source_age_calendar_days"]) != MAXIMUM_SOURCE_AGE_DAYS
        or governor["scale_can_increase_v12_risk"] is not False
        or governor["threshold_fit"] != "none"
        or declared_all != expected_all_without_flat
        or declared_oos != expected_oos_without_flat
        or int(protocol["information_set"]["maximum_source_age_calendar_days"])
        != MAXIMUM_SOURCE_AGE_DAYS
        or int(portfolio["ewma_volatility_span_sessions"]) != 20
        or int(portfolio["covariance_lookback_sessions"]) != 60
        or float(portfolio["annual_target_volatility_before_governor"]) != 0.20
        or float(portfolio["gross_cap"]) != 1.0
        or int(portfolio["turnover_sleeves"]) != 5
        or float(execution["maximum_participation"]) != v12.MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"]) != 1.0
        or float(execution["initial_margin_buffer_multiple"]) != 2.0
        or float(execution["initial_cash_rub"]) != v12.INITIAL_CASH
        or execution["execution_atomicity"] != "asset"
    ):
        raise ValueError("sealed V24 protocol invariants were weakened")
    if v12._scenario_settings(protocol) != {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }:
        raise ValueError("sealed V24 cost scenarios drifted")
    return protocol


def verify_inputs(protocol: dict[str, Any]) -> v12.VerifiedInputs:
    """Verify every declared byte before loading any market outcome columns."""
    verified = v12.verify_inputs(protocol)
    checks = dict(verified.checks)
    checks["v12_parent_protocol_seal"] = checks.pop("protocol_seal")
    checks["v24_protocol_seal"] = v12.sha256_file(CONFIG_PATH) == CONFIG_SHA256
    if not all(checks.values()):
        raise ValueError(f"V24 input identity preflight failed: {checks}")
    return v12.VerifiedInputs(
        paths=verified.paths,
        checks=checks,
        metadata=verified.metadata,
    )


def _expected_coverage(
    parsed: dict[str, pd.DataFrame], records: dict[str, dict[str, Any]]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for series_id in vix_source.FRED_SERIES:
        frame = parsed[series_id]
        value_column = vix_source.FRED_SERIES[series_id]
        record = records[series_id]
        rows.append(
            {
                "series_id": series_id,
                "value_column": value_column,
                "url": record["url"],
                "response_bytes": int(record["bytes"]),
                "response_sha256": record["sha256"],
                "rows": len(frame),
                "nonmissing_rows": int(frame[value_column].notna().sum()),
                "missing_rows": int(frame[value_column].isna().sum()),
                "minimum_observation_date": frame["observation_date"].min(),
                "maximum_observation_date": frame["observation_date"].max(),
            }
        )
    return pd.DataFrame(rows, columns=COVERAGE_COLUMNS)


def verify_vix_bundle(protocol: dict[str, Any], verified: v12.VerifiedInputs) -> VixVerification:
    """Replay both raw responses and prove processed values and availability exactly."""
    paths = verified.paths
    manifest = json.loads(paths["vix_manifest"].read_text(encoding="utf-8-sig"))
    sidecar = paths["vix_manifest_sidecar"].read_text(encoding="utf-8-sig").split()[0]
    core = {key: value for key, value in manifest.items() if key != "manifest_payload_sha256"}
    if sidecar != protocol["inputs"]["vix_manifest"]["sha256"]:
        raise ValueError("V24 VIX manifest sidecar drift")
    if manifest.get("manifest_payload_sha256") != vix_source.sha256_bytes(
        vix_source._canonical_json(core)
    ):
        raise ValueError("V24 VIX manifest payload drift")

    raw_records: dict[str, dict[str, Any]] = {}
    parsed: dict[str, pd.DataFrame] = {}
    with gzip.open(paths["vix_raw_responses"], "rt", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            identity = str(record["identity"])
            if identity in raw_records or identity not in vix_source.FRED_SERIES:
                raise ValueError("V24 raw VIX identity is duplicate or unexpected")
            content = base64.b64decode(record["content"], validate=True)
            if (
                record.get("kind") != "fred_csv"
                or record.get("content_encoding") != "base64"
                or record.get("url") != vix_source.series_url(identity)
                or int(record.get("bytes", -1)) != len(content)
                or record.get("sha256") != vix_source.sha256_bytes(content)
                or b"2026-" in content
            ):
                raise ValueError("V24 raw VIX response identity or protected bound drift")
            raw_records[identity] = record
            parsed[identity] = vix_source.parse_fred_csv(content, series_id=identity)
    if set(raw_records) != set(vix_source.FRED_SERIES):
        raise ValueError("V24 did not replay both exact VIX sources")

    rebuilt = vix_source.build_term_structure(
        parsed,
        retrieved_at_utc=str(manifest["fetched_at_utc"]),
        minimum_rows=2087,
        minimum_complete_pairs=2011,
    ).reset_index(drop=True)
    processed = pd.read_parquet(paths["vix_term_structure"], columns=list(VIX_COLUMNS)).reset_index(
        drop=True
    )
    pd.testing.assert_frame_equal(processed, rebuilt, check_exact=True)
    coverage = pd.read_parquet(paths["vix_coverage"], columns=list(COVERAGE_COLUMNS)).reset_index(
        drop=True
    )
    pd.testing.assert_frame_equal(
        coverage,
        _expected_coverage(parsed, raw_records).reset_index(drop=True),
        check_exact=True,
    )

    processed["observation_date"] = pd.to_datetime(
        processed["observation_date"], errors="raise"
    ).dt.normalize()
    processed["available_at"] = pd.to_datetime(processed["available_at"], errors="raise", utc=True)
    expected_available = pd.Series(
        [
            vix_source.conservative_available_at(value.date())
            for value in processed["observation_date"]
        ],
        dtype="datetime64[ns, UTC]",
    )
    if not processed["available_at"].reset_index(drop=True).equals(expected_available):
        raise ValueError("V24 VIX conservative availability drift")
    if (
        len(processed) != 2087
        or processed["observation_date"].min() != pd.Timestamp("2018-01-02")
        or processed["observation_date"].max() != pd.Timestamp("2025-12-31")
        or processed["observation_date"].ge(v12.PROTECTED_FROM).any()
        or int(processed["complete_pair"].sum()) != 2011
        or int((~processed["complete_pair"]).sum()) != 76
        or not processed["source_current_vintage"].eq(True).all()  # noqa: E712
    ):
        raise ValueError("V24 VIX row, date, missingness or vintage identity drift")
    admitted = processed.loc[
        processed["available_at"].lt(pd.Timestamp("2026-01-01T00:00:00Z"))
    ]
    admitted_counts = admitted.loc[admitted["complete_pair"], "term_structure"].value_counts()
    if (
        int(admitted["complete_pair"].sum()) != 2010
        or int(admitted_counts.get("backwardation", 0)) != 174
        or int(admitted_counts.get("contango", 0)) != 1836
        or int(admitted_counts.get("flat", 0)) != 0
    ):
        raise ValueError("V24 admissible VIX term-structure identity drift")

    artifacts = manifest["artifacts"]
    declared = protocol["inputs"]
    manifest_checks = {
        "vix_manifest_source_id_exact": manifest.get("source_id")
        == "fred-cboe-vix-term-structure-current-vintage-2018-2025-v2",
        "vix_manifest_request_count_exact": int(manifest.get("request_count", -1)) == 2,
        "vix_manifest_processed_identity_exact": artifacts["processed"]["sha256"]
        == declared["vix_term_structure"]["sha256"]
        and int(artifacts["processed"]["bytes"]) == int(declared["vix_term_structure"]["bytes"]),
        "vix_manifest_coverage_identity_exact": artifacts["coverage"]["sha256"]
        == declared["vix_coverage"]["sha256"]
        and int(artifacts["coverage"]["bytes"]) == int(declared["vix_coverage"]["bytes"]),
        "vix_manifest_raw_identity_exact": artifacts["raw_responses"]["sha256"]
        == declared["vix_raw_responses"]["sha256"]
        and int(artifacts["raw_responses"]["bytes"]) == int(declared["vix_raw_responses"]["bytes"]),
        "vix_manifest_target_free": manifest["temporal_semantics"][
            "contains_MOEX_prices_returns_targets_labels_or_pnl"
        ]
        is False,
        "vix_manifest_current_vintage_disclosed": manifest["temporal_semantics"][
            "current_vintage_retrieved_now"
        ]
        is True
        and manifest["temporal_semantics"][
            "historical_content_immutability_cryptographically_proved"
        ]
        is False,
    }
    if not all(manifest_checks.values()):
        raise ValueError(f"V24 VIX manifest semantics drifted: {manifest_checks}")
    checks = {
        **manifest_checks,
        "vix_manifest_payload_and_sidecar_exact": True,
        "vix_raw_two_record_hash_replay_exact": True,
        "vix_raw_contains_no_2026_observations": True,
        "vix_processed_exactly_rebuilt_from_raw": True,
        "vix_coverage_exactly_rebuilt_from_raw": True,
        "vix_rows_dates_missingness_and_schema_exact": True,
        "vix_conservative_availability_exact": True,
        "vix_structural_boundary_not_fitted": True,
    }
    return VixVerification(
        frame=processed.sort_values("available_at", kind="mergesort", ignore_index=True),
        coverage=coverage,
        checks=checks,
        raw_records=len(raw_records),
    )


def _state_counts(frame: pd.DataFrame) -> dict[str, int]:
    counts = frame["governor_state"].value_counts()
    return {
        "decision_dates": int(len(frame)),
        "pass_contango": int(counts.get("pass_contango", 0)),
        "cash_backwardation": int(counts.get("cash_backwardation", 0)),
        "cash_flat": int(counts.get("cash_flat", 0)),
        "cash_missing_or_stale": int(counts.get("cash_missing_or_stale", 0)),
    }


def build_daily_governed_weights(
    weekly_weights: pd.DataFrame,
    active_map: pd.DataFrame,
    vix: VixVerification,
) -> GovernorBuild:
    """Carry frozen weekly V12 weights daily and apply the causal binary governor."""
    required = {"decision_date", "asset", "target_weight", "provenance"}
    if missing := required - set(weekly_weights.columns):
        raise ValueError(f"V24 weekly weights lack columns: {sorted(missing)}")
    weekly = weekly_weights.loc[:, sorted(required)].copy()
    weekly["decision_date"] = pd.to_datetime(weekly["decision_date"], errors="raise").dt.normalize()
    weekly["asset"] = weekly["asset"].map(v12._asset_code)
    weekly["target_weight"] = pd.to_numeric(weekly["target_weight"], errors="raise").astype(float)
    if (
        weekly.duplicated(["decision_date", "asset"]).any()
        or weekly.groupby("decision_date")["asset"].nunique().ne(len(v12.ASSETS)).any()
    ):
        raise ValueError("V24 weekly V12 snapshots are duplicate or incomplete")
    weekly_gross = weekly.groupby("decision_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    if weekly_gross.gt(1.0 + 1e-12).any():
        raise ValueError("V24 frozen weekly V12 weights exceed gross one")

    active = v12.normalize_active_map(active_map)
    active_dates = pd.DatetimeIndex(active["decision_date"].drop_duplicates().sort_values())
    weight_matrix = weekly.pivot(
        index="decision_date", columns="asset", values="target_weight"
    ).reindex(columns=v12.ASSETS)
    union = weight_matrix.index.union(active_dates).sort_values()
    carried = weight_matrix.reindex(union).ffill().reindex(active_dates).fillna(0.0)
    weekly_dates = pd.Series(weight_matrix.index, index=weight_matrix.index)
    base_decision_dates = weekly_dates.reindex(union).ffill().reindex(active_dates)
    daily = (
        carried.stack(future_stack=True)
        .rename("v12_target_weight")
        .reset_index()
        .rename(columns={"level_0": "decision_date", "level_1": "asset"})
    )
    daily["v12_source_decision_date"] = daily["decision_date"].map(base_decision_dates)
    base_provenance = weekly.rename(
        columns={
            "decision_date": "v12_source_decision_date",
            "provenance": "v12_provenance",
        }
    ).loc[:, ["v12_source_decision_date", "asset", "v12_provenance"]]
    daily = daily.merge(
        base_provenance,
        on=["v12_source_decision_date", "asset"],
        how="left",
        validate="many_to_one",
    )
    daily["v12_provenance"] = daily["v12_provenance"].fillna("no_frozen_v12_weight_yet")

    decisions = pd.DataFrame({"decision_date": active_dates})
    decisions["decision_at"] = (
        decisions["decision_date"].dt.tz_localize("Europe/Moscow")
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).dt.tz_convert("UTC")
    source = vix.frame.loc[
        :,
        [
            "observation_date",
            "available_at",
            "complete_pair",
            "vix_vix3m_ratio",
            "term_structure",
        ],
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
    fresh_complete = (
        available
        & governor["complete_pair"].fillna(False).astype(bool)
        & governor["source_age_calendar_days"].between(0, MAXIMUM_SOURCE_AGE_DAYS, inclusive="both")
    )
    governor["governor_state"] = "cash_missing_or_stale"
    governor.loc[
        fresh_complete & governor["term_structure"].eq("contango"),
        "governor_state",
    ] = "pass_contango"
    governor.loc[
        fresh_complete & governor["term_structure"].eq("backwardation"),
        "governor_state",
    ] = "cash_backwardation"
    governor.loc[
        fresh_complete & governor["term_structure"].eq("flat"),
        "governor_state",
    ] = "cash_flat"
    governor["risk_scale"] = governor["governor_state"].eq("pass_contango").astype(float)

    governed = daily.merge(
        governor.loc[
            :,
            [
                "decision_date",
                "decision_at",
                "observation_date",
                "available_at",
                "source_age_calendar_days",
                "governor_state",
                "risk_scale",
            ],
        ],
        on="decision_date",
        how="left",
        validate="many_to_one",
    )
    governed["target_weight"] = governed["v12_target_weight"] * governed["risk_scale"]
    governed["provenance"] = governed["v12_provenance"].astype("string") + np.select(
        [
            governed["governor_state"].eq("pass_contango"),
            governed["governor_state"].eq("cash_backwardation"),
            governed["governor_state"].eq("cash_flat"),
        ],
        [
            "|daily_vix_vix3m_contango_pass",
            "|daily_vix_vix3m_backwardation_cash",
            "|daily_vix_vix3m_flat_cash",
        ],
        default="|daily_vix_vix3m_missing_or_stale_cash",
    )
    governed_gross = governed.groupby("decision_date")["target_weight"].apply(
        lambda values: values.abs().sum()
    )
    all_counts = _state_counts(governor)
    oos_counts = _state_counts(
        governor.loc[governor["decision_date"].between(v12.OOS_START, v12.OOS_END)]
    )
    checks = {
        "daily_governor_complete_four_asset_snapshots": governed.groupby("decision_date")["asset"]
        .nunique()
        .eq(len(v12.ASSETS))
        .all(),
        "daily_governor_exact_active_decision_schedule": len(governor) == len(active_dates)
        and governor["decision_date"].equals(pd.Series(active_dates)),
        "daily_governor_available_at_not_after_decision": bool(
            governor.loc[governor["available_at"].notna(), "available_at"]
            .le(governor.loc[governor["available_at"].notna(), "decision_at"])
            .all()
        ),
        "daily_governor_never_increases_v12_risk": bool(
            governed["target_weight"].abs().le(governed["v12_target_weight"].abs() + 1e-12).all()
        ),
        "daily_governor_gross_at_most_one": bool(governed_gross.le(1.0 + 1e-12).all()),
        "daily_governor_all_state_counts_exact": all_counts == EXPECTED_ALL_STATES,
        "daily_governor_oos_state_counts_exact": oos_counts == EXPECTED_OOS_STATES,
    }
    if not all(checks.values()):
        raise ValueError(
            f"V24 daily governor invariant failure: checks={checks}, "
            f"all={all_counts}, oos={oos_counts}"
        )
    return GovernorBuild(
        weights=governed.sort_values(
            ["decision_date", "asset"], kind="mergesort", ignore_index=True
        ),
        governor=governor.sort_values("decision_date", kind="mergesort", ignore_index=True),
        checks=checks,
    )


def _scenario_metrics_with_risk(
    result: FuturesPortfolioLedgerResult,
    market: pd.DataFrame,
    settings: dict[str, float],
) -> dict[str, Any]:
    metrics = v12.scenario_metrics(result, market, settings)
    ledger = result.ledger
    metrics["maximum_post_mark_gross_leverage"] = (
        float(ledger["gross_leverage"].max()) if not ledger.empty else 0.0
    )
    metrics["maximum_2x_margin_to_starting_cash"] = (
        float((2.0 * ledger["modeled_initial_margin"] / ledger["starting_cash"]).max())
        if not ledger.empty
        else 0.0
    )
    return metrics


def _comparison(primary: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference_protocol_sha256": V12_PROTOCOL_SHA256,
        "reference_metrics_sha256": V12_METRICS_SHA256,
        "reference": V12_PRIMARY_REFERENCE,
        "delta": {
            "total_return": float(primary["total_return"]) - V12_PRIMARY_REFERENCE["total_return"],
            "cagr": float(primary["cagr"]) - V12_PRIMARY_REFERENCE["cagr"],
            "sharpe": float(primary["sharpe"]) - V12_PRIMARY_REFERENCE["sharpe"],
            "maximum_drawdown_reduction": V12_PRIMARY_REFERENCE["maximum_drawdown"]
            - float(primary["maximum_drawdown"]),
            "worst_year_improvement": float(primary["worst_year"])
            - V12_PRIMARY_REFERENCE["worst_year"],
            "cost_reduction_rub": V12_PRIMARY_REFERENCE["total_cost_rub"]
            - float(primary["total_cost"]),
        },
    }


def _promotion(results: dict[str, dict[str, Any]], checks: dict[str, bool]) -> dict[str, Any]:
    primary = results["primary"]
    conditions = {
        "every_input_raw_replay_source_and_temporal_check_true": all(checks.values()),
        "exact_sealed_daily_state_counts": checks["daily_governor_all_state_counts_exact"]
        and checks["daily_governor_oos_state_counts_exact"],
        "all_scenarios_execution_complete": all(
            bool(value["execution_complete"]) for value in results.values()
        ),
        "zero_critical_failures_and_unresolved_halts": all(
            int(value["critical_failure_count"]) == 0 and int(value["unresolved_halt_count"]) == 0
            for value in results.values()
        ),
        "primary_cagr_at_least_0_05": float(primary["cagr"]) >= 0.05,
        "primary_sharpe_at_least_frozen_v12": float(primary["sharpe"])
        >= V12_PRIMARY_REFERENCE["sharpe"],
        "primary_maximum_drawdown_at_most_frozen_v12": float(primary["maximum_drawdown"])
        <= V12_PRIMARY_REFERENCE["maximum_drawdown"],
        "primary_positive_years_at_least_4_of_5": int(primary["positive_years"]) >= 4
        and len(primary["annual_returns"]) == 5,
        "doubled_total_return_positive": float(results["doubled"]["total_return"]) > 0.0,
        "stress_total_return_positive": float(results["stress"]["total_return"]) > 0.0,
        "no_order_time_gross_participation_or_margin_breach": all(
            float(value["maximum_participation"]) <= v12.MAXIMUM_PARTICIPATION + 1e-12
            and int(value["gross_limit_rejection_count"]) == 0
            and int(value["initial_margin_rejection_count"]) == 0
            and float(value["ending_cash"]) > 0.0
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
        "# V24 frozen V12 plus daily Cboe VIX/VIX3M risk governor",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        "This is one adaptive 2021-2025 stability hypothesis, not independent confirmation.",
        "",
        "| Scenario | Total return | CAGR | Sharpe | MDD | Positive years | Costs RUB | Complete |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name in ("primary", "doubled", "stress"):
        item = payload["scenarios"][name]
        lines.append(
            f"| {name} | {item['total_return']:.4%} | {item['cagr']:.4%} | "
            f"{item['sharpe']:.3f} | {item['maximum_drawdown']:.4%} | "
            f"{item['positive_years']}/5 | {item['total_cost']:.2f} | "
            f"{item['execution_complete']} |"
        )
    delta = payload["comparison_to_v12"]["delta"]
    lines.extend(
        [
            "",
            "## Delta versus frozen V12 primary",
            "",
            f"- CAGR: {delta['cagr']:+.4%}",
            f"- Sharpe: {delta['sharpe']:+.4f}",
            f"- Drawdown reduction: {delta['maximum_drawdown_reduction']:+.4%}",
            f"- Worst-year improvement: {delta['worst_year_improvement']:+.4%}",
            f"- Cost reduction: {delta['cost_reduction_rub']:+.2f} RUB",
            "",
            "## Primary annual returns",
            "",
        ]
    )
    for year, value in payload["scenarios"]["primary"]["annual_returns"].items():
        lines.append(f"- {year}: {value:.4%}")
    counts = payload["counts"]
    lines.extend(
        [
            "",
            "## Source, governor and execution",
            "",
            f"- Strict raw response replays: {counts['vix_raw_records']}/2",
            f"- Source grid/complete pairs: {counts['vix_source_rows']}/"
            f"{counts['vix_complete_pairs']}",
            f"- OOS daily decisions: {counts['oos_daily_decisions']}",
            f"- OOS contango pass: {counts['oos_pass_contango']}",
            f"- OOS backwardation cash: {counts['oos_cash_backwardation']}",
            f"- OOS missing/stale cash: {counts['oos_cash_missing_or_stale']}",
            f"- Weekly frozen-V12 snapshots: {counts['weekly_v12_decisions']}",
            f"- Mapped daily decisions: {counts['mapped_daily_decisions']}",
            f"- Non-zero targets: {counts['nonzero_targets']}",
            f"- Complete next-open dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "The source is a current-vintage Cboe/FRED snapshot. Same-Moscow-day US "
            "closes are unavailable; missing, stale, flat or backwardated states fail "
            "closed to cash. Terminal positions are carried and broker/order-book "
            "economics remain proxy.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute exactly one immutable V24 adaptive-development run."""
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    vix = verify_vix_bundle(protocol, verified)
    checks = {**verified.checks, **vix.checks}

    panel = pd.read_parquet(
        verified.paths["panel"], columns=protocol["inputs"]["panel"]["allowed_columns"]
    )
    active = pd.read_parquet(
        verified.paths["active_contract_map"],
        columns=protocol["inputs"]["active_contract_map"]["allowed_columns"],
    )
    observations = pd.read_parquet(
        verified.paths["contract_observations"],
        columns=protocol["inputs"]["contract_observations"]["allowed_columns"],
    )
    specs = pd.read_parquet(
        verified.paths["spec_proxy"],
        columns=protocol["inputs"]["spec_proxy"]["allowed_columns"],
    )
    scores = v12.build_trend_scores(panel)
    weekly_weights = v12.build_weekly_weights(panel, scores)
    governed = build_daily_governed_weights(weekly_weights, active, vix)
    checks.update(governed.checks)
    target_build = v12.build_execution_targets(governed.weights, active)
    market = v12.build_execution_market(observations, specs)
    coverage = v12.execution_coverage(market, target_build.targets)
    nonzero_targets = int(target_build.targets["target_weight"].abs().gt(1e-12).sum())
    covered_nonzero_targets = int(coverage["execution_dependencies_complete"].sum())
    checks["all_nonzero_next_open_dependencies_complete"] = (
        covered_nonzero_targets == nonzero_targets
    )

    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < v12.OOS_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(predecessor, v12.OOS_END)
    ].copy()
    scenario_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    scenario_results: dict[str, dict[str, Any]] = {}
    for name, settings in v12._scenario_settings(protocol).items():
        result = run_futures_portfolio_ledger(
            execution_market,
            target_build.targets,
            FuturesPortfolioLedgerConfig(
                initial_cash=v12.INITIAL_CASH,
                expected_assets=v12.ASSETS,
                maximum_gross_notional_multiple=1.0,
                initial_margin_buffer_multiplier=2.0,
                maximum_participation=v12.MAXIMUM_PARTICIPATION,
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
                execution_atomicity="asset",
                terminal_policy="carry",
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name] = _scenario_metrics_with_risk(result, execution_market, settings)

    oos_governor = governed.governor.loc[
        governed.governor["decision_date"].between(v12.OOS_START, v12.OOS_END)
    ]
    oos_counts = _state_counts(oos_governor)
    counts = {
        "source_panel_rows": int(len(panel)),
        "source_active_map_rows": int(len(active)),
        "source_contract_observation_rows": int(len(observations)),
        "source_spec_rows": int(len(specs)),
        "vix_source_rows": int(len(vix.frame)),
        "vix_complete_pairs": int(vix.frame["complete_pair"].sum()),
        "vix_raw_records": vix.raw_records,
        "score_rows": int(len(scores)),
        "finite_score_rows": int(scores["candidate_score"].notna().sum()),
        "weekly_v12_decisions": int(weekly_weights["decision_date"].nunique()),
        "all_daily_decisions": int(len(governed.governor)),
        "oos_daily_decisions": oos_counts["decision_dates"],
        "oos_pass_contango": oos_counts["pass_contango"],
        "oos_cash_backwardation": oos_counts["cash_backwardation"],
        "oos_cash_flat": oos_counts["cash_flat"],
        "oos_cash_missing_or_stale": oos_counts["cash_missing_or_stale"],
        "mapped_daily_decisions": target_build.weekly_decisions,
        "additional_roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": int(len(target_build.targets)),
        "nonzero_targets": nonzero_targets,
        "covered_nonzero_targets": covered_nonzero_targets,
    }
    comparison = _comparison(scenario_results["primary"])
    promotion = _promotion(scenario_results, checks)
    code_paths = {
        "v24_implementation": Path(__file__).resolve(),
        "v12_frozen_parent": Path(v12.__file__).resolve(),
        "vix_source_builder": Path(vix_source.__file__).resolve(),
        "portfolio_construction": PROJECT_ROOT / "src/market_lab/futures/portfolio_construction.py",
        "execution_dataset": PROJECT_ROOT / "src/market_lab/futures/execution_dataset.py",
        "portfolio_ledger": PROJECT_ROOT / "src/market_lab/futures/portfolio_ledger.py",
        "spec_proxy": PROJECT_ROOT / "src/market_lab/futures/spec_proxy.py",
    }
    identity = {
        "protocol_sha256": CONFIG_SHA256,
        "parent_v12_protocol_sha256": V12_PROTOCOL_SHA256,
        "parent_v12_metrics_sha256": V12_METRICS_SHA256,
        "input_sha256": {
            name: declaration["sha256"] for name, declaration in protocol["inputs"].items()
        },
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
        "comparison_to_v12": comparison,
        "promotion": promotion,
        "limitations": protocol["execution"]["limitations"],
    }

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v24_cboe_vix_governor_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V24 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        v12._write_parquet(temporary / "scores.parquet", scores)
        v12._write_parquet(temporary / "weekly_v12_weights.parquet", weekly_weights)
        v12._write_parquet(temporary / "daily_governed_weights.parquet", governed.weights)
        governed.governor.to_csv(temporary / "vix_governor.csv", index=False, encoding="utf-8-sig")
        v12._write_parquet(temporary / "mapped_targets.parquet", target_build.targets)
        decision_audit = target_build.decision_audit.rename(
            columns={"weekly_rebalance": "daily_governor_rebalance"}
        )
        decision_audit.to_csv(temporary / "decision_audit.csv", index=False, encoding="utf-8-sig")
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        for name, result in scenario_outputs.items():
            v12._write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            v12._write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            v12._write_parquet(temporary / f"positions_{name}.parquet", result.positions)
        report_path = temporary / "report.md"
        report_path.write_text(_report_text(payload), encoding="utf-8-sig")
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
        identity_path = temporary / "identity.json"
        identity_path.write_text(
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
        help="External immutable runs root; a unique V24 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
