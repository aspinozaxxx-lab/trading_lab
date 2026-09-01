"""Sealed V18 Bank of Russia forward-liquidity forecast experiment for SI."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    FuturesPortfolioLedgerResult,
    run_futures_portfolio_ledger,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v18_cbr_liquidity_forecast.yaml"
CONFIG_SHA256: Final[str] = (
    "ee2d7fd77037eccf15237f827ed357e0b8608c96fae1f393e8a3478945b8b10a"
)
CBR_SOURCE_MANIFEST_SHA256: Final[str] = (
    "8f452f2dd963752eab4183e8f80dd2a07398588f9f87124ae913dff6c2a88c9a"
)
OOS_START: Final[pd.Timestamp] = pd.Timestamp("2021-01-01")
OOS_END: Final[pd.Timestamp] = pd.Timestamp("2025-12-31")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
VOLATILITY_LOOKBACK: Final[int] = 60
ANNUALIZATION: Final[int] = 252
VOLATILITY_FLOOR: Final[float] = 0.10
TARGET_VOLATILITY: Final[float] = 0.20
MAXIMUM_ABSOLUTE_WEIGHT: Final[float] = 1.0
INITIAL_CASH: Final[float] = 1_000_000.0
MAXIMUM_PARTICIPATION: Final[float] = 0.01


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    return v12._json_safe(value)


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the byte seal and every V18 economic invariant before outcome access."""
    path = config_path.resolve()
    if path != CONFIG_PATH.resolve() or sha256_file(path) != CONFIG_SHA256:
        raise ValueError("sealed V18 protocol byte drift")
    stated = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V18 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V18 protocol must be a mapping")
    signal = protocol["signal"]
    portfolio = protocol["portfolio"]
    execution = protocol["execution"]
    information = protocol["information_set"]
    if (
        protocol.get("protocol_id") != "futures_v18_cbr_liquidity_forecast_v1"
        or protocol.get("status") != "sealed_before_any_v18_market_outcome_read"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or protocol.get("parent_v12_protocol_sha256") != v12.CONFIG_SHA256
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or signal["value"] != "government_accounts_change_bln_rub_from_that_dated_forecast"
        or int(signal["economic_sign_to_SI"]) != 1
        or signal["direction"] != "sign_of_value_with_exact_zero_flat"
        or signal["normalization"] != "none"
        or signal["trade_threshold"] != "none"
        or signal["expiry_without_successor"]
        != "zero_target_at_end_of_printed_period"
        or information["query_date_is_not_evidence"] is not True
        or information["missing_week_policy"]
        != "flatten_after_prior_printed_forecast_period_end"
        or int(portfolio["SI_daily_volatility_lookback_sessions"])
        != VOLATILITY_LOOKBACK
        or int(portfolio["annualization_sessions"]) != ANNUALIZATION
        or float(portfolio["annualized_volatility_floor"]) != VOLATILITY_FLOOR
        or float(portfolio["annual_target_volatility"]) != TARGET_VOLATILITY
        or float(portfolio["SI_absolute_weight_cap"]) != MAXIMUM_ABSOLUTE_WEIGHT
        or float(portfolio["gross_cap"]) != 1.0
        or float(execution["initial_cash_rub"]) != INITIAL_CASH
        or float(execution["maximum_participation"]) != MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"]) != 1.0
        or float(execution["initial_margin_buffer_multiple"]) != 2.0
    ):
        raise ValueError("sealed V18 protocol invariants were weakened")
    return protocol


@dataclass(frozen=True, slots=True)
class VerifiedInputs:
    paths: dict[str, Path]
    checks: dict[str, bool]
    metadata: dict[str, Any]
    parent_protocol: dict[str, Any]


def verify_inputs(protocol: dict[str, Any]) -> VerifiedInputs:
    """Verify source-only CBR artifacts and parent market identities before price reads."""
    parent_protocol = v12.load_protocol()
    parent_verified = v12.verify_inputs(parent_protocol)
    checks = {f"parent_{key}": value for key, value in parent_verified.checks.items()}
    parent_names = ("panel", "active_contract_map", "contract_observations", "spec_proxy")
    paths = {name: parent_verified.paths[name] for name in parent_names}
    for name in parent_names:
        declaration = protocol["inputs"][name]
        parent = parent_protocol["inputs"][name]
        checks[f"{name}_matches_parent_hash"] = declaration["sha256"] == parent["sha256"]
        checks[f"{name}_matches_parent_bytes"] = int(declaration["bytes"]) == int(
            parent["bytes"]
        )
        checks[f"{name}_matches_parent_schema"] = tuple(
            declaration["allowed_columns"]
        ) == tuple(parent["allowed_columns"])

    metadata: dict[str, Any] = {"parent_v12": parent_verified.metadata}
    source_names = (
        "cbr_liquidity_forecasts",
        "cbr_liquidity_coverage",
        "cbr_liquidity_manifest",
    )
    for name in source_names:
        declaration = protocol["inputs"][name]
        path = v12._resolved_input(str(declaration["path"]))
        paths[name] = path
        exists = path.is_file()
        checks[f"{name}_exists"] = exists
        checks[f"{name}_bytes"] = exists and path.stat().st_size == int(declaration["bytes"])
        checks[f"{name}_sha256"] = exists and sha256_file(path) == declaration["sha256"]
        metadata[name] = {
            "path": declaration["path"],
            "bytes": path.stat().st_size if exists else None,
            "sha256": sha256_file(path) if exists else None,
        }
        if name != "cbr_liquidity_manifest" and exists:
            parquet = pq.ParquetFile(path)
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
            checks[f"{name}_schema"] = set(declaration["allowed_columns"]) <= set(
                parquet.schema_arrow.names
            )
            metadata[name]["rows"] = parquet.metadata.num_rows
            metadata[name]["columns"] = parquet.schema_arrow.names
    if not all(checks.values()):
        raise ValueError(f"V18 byte/schema preflight failed: {checks}")

    manifest = json.loads(paths["cbr_liquidity_manifest"].read_text(encoding="utf-8-sig"))
    processed = manifest["artifacts"]["processed"]
    manifest_coverage = manifest["artifacts"]["coverage"]
    temporal = manifest["temporal_semantics"]
    checks["cbr_manifest_identity"] = (
        sha256_file(paths["cbr_liquidity_manifest"]) == CBR_SOURCE_MANIFEST_SHA256
    )
    checks["cbr_manifest_processed_identity"] = (
        processed["sha256"] == protocol["inputs"]["cbr_liquidity_forecasts"]["sha256"]
        and int(processed["rows"])
        == int(protocol["inputs"]["cbr_liquidity_forecasts"]["rows"])
    )
    checks["cbr_manifest_coverage_identity"] = (
        manifest_coverage["sha256"]
        == protocol["inputs"]["cbr_liquidity_coverage"]["sha256"]
        and int(manifest_coverage["rows"])
        == int(protocol["inputs"]["cbr_liquidity_coverage"]["rows"])
    )
    checks["cbr_release_counts"] = (
        int(manifest["release_count"]) == 458
        and int(manifest["calendar_week_count"]) == 470
        and int(manifest["missing_calendar_week_count"]) == 12
    )
    checks["cbr_release_keyed_target_free"] = (
        temporal["release_keyed_historical_record"] is True
        and temporal["contains_prices_returns_targets_labels_or_pnl"] is False
    )
    checks["cbr_development_only_semantics"] = (
        temporal["development_backtest_admissible"] is True
        and temporal["independent_confirmation_without_forward_vintage_collection"] is False
        and temporal["original_historical_response_bytes_available"] is False
        and temporal["last_modified_used_for_availability"] is False
    )
    coverage = pd.read_parquet(
        paths["cbr_liquidity_coverage"],
        columns=protocol["inputs"]["cbr_liquidity_coverage"]["allowed_columns"],
    )
    found = coverage["found"].astype(bool)
    checks["cbr_coverage_counts"] = int(found.sum()) == 458 and int((~found).sum()) == 12
    checks["cbr_coverage_identity_complete"] = bool(
        coverage.loc[found, "admitted_raw_sha256"].astype("string").str.fullmatch(
            r"[0-9a-f]{64}"
        ).all()
        and coverage.loc[~found, "admitted_raw_sha256"].isna().all()
    )
    metadata["cbr_manifest_payload"] = manifest
    metadata["cbr_coverage_counts"] = {
        "total": len(coverage),
        "found": int(found.sum()),
        "missing": int((~found).sum()),
    }
    if not all(checks.values()):
        raise ValueError(f"V18 source semantic preflight failed: {checks}")
    return VerifiedInputs(
        paths=paths,
        checks=checks,
        metadata=metadata,
        parent_protocol=parent_protocol,
    )


def normalize_forecasts(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate dated forward records and derive the single sealed SI direction."""
    required = {
        "publication_date",
        "available_at",
        "forecast_period_start",
        "forecast_period_end",
        "government_accounts_change_bln_rub",
        "source_schema",
        "raw_sha256",
        "release_keyed_historical_record",
    }
    if missing := required - set(frame.columns):
        raise ValueError(f"V18 CBR source lacks columns: {sorted(missing)}")
    source = frame.loc[:, sorted(required)].copy()
    for column in ("publication_date", "forecast_period_start", "forecast_period_end"):
        source[column] = pd.to_datetime(source[column], errors="raise").dt.normalize()
    source["available_at"] = pd.to_datetime(source["available_at"], errors="raise", utc=True)
    source["government_accounts_change_bln_rub"] = pd.to_numeric(
        source["government_accounts_change_bln_rub"], errors="coerce"
    )
    if len(source) != 458 or source["publication_date"].duplicated().any():
        raise ValueError("V18 CBR source row identity or publication uniqueness drifted")
    if (
        source["publication_date"].min() != pd.Timestamp("2017-01-10")
        or source["publication_date"].max() != pd.Timestamp("2025-12-30")
    ):
        raise ValueError("V18 CBR source date boundaries drifted")
    if source["available_at"].ge(PROTECTED_FROM).any():
        raise ValueError("V18 CBR source touches protected 2026+")
    publication_local = source["publication_date"].dt.tz_localize(MOSCOW)
    expected_available = (
        publication_local
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).dt.tz_convert("UTC")
    if not source["available_at"].equals(expected_available):
        raise ValueError("V18 CBR conservative publication availability drifted")
    if (
        source["forecast_period_start"].lt(source["publication_date"]).any()
        or source["forecast_period_end"].lt(source["forecast_period_start"]).any()
    ):
        raise ValueError("V18 CBR forecast periods are not forward ordered")
    if source["government_accounts_change_bln_rub"].isna().any() or not np.isfinite(
        source["government_accounts_change_bln_rub"].to_numpy(dtype=float)
    ).all():
        raise ValueError("V18 required government forecast values must be finite")
    if not source["release_keyed_historical_record"].astype(bool).all():
        raise ValueError("V18 source contains a non-release-keyed record")
    if not source["source_schema"].astype("string").isin(
        {"archive_2012_2020", "current_2021_plus"}
    ).all():
        raise ValueError("V18 source schema drifted")
    if not source["raw_sha256"].astype("string").str.fullmatch(r"[0-9a-f]{64}").all():
        raise ValueError("V18 raw source identity is malformed")
    source["direction"] = np.sign(source["government_accounts_change_bln_rub"].astype(float))
    return source.sort_values("publication_date", kind="mergesort", ignore_index=True)


@dataclass(frozen=True, slots=True)
class SourceDecisionBuild:
    decisions: pd.DataFrame
    weights: pd.DataFrame
    mapped_release_count: int
    mapped_expiry_count: int
    same_session_collisions: int
    required_expiry_count: int


def _decision_at(decision_date: pd.Timestamp) -> pd.Timestamp:
    return (
        decision_date.tz_localize(MOSCOW)
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).tz_convert("UTC")


def build_source_decisions(
    forecasts: pd.DataFrame,
    panel: pd.DataFrame,
    active_map: pd.DataFrame,
) -> SourceDecisionBuild:
    """Map releases and explicit forecast expiries to completed MOEX sessions."""
    source = normalize_forecasts(forecasts)
    market = v12.normalize_signal_panel(panel)
    si = market.loc[market["asset"].eq("SI")].set_index("trade_date")["close"]
    si_volatility = (
        np.log(si)
        .diff()
        .rolling(VOLATILITY_LOOKBACK, min_periods=VOLATILITY_LOOKBACK)
        .std(ddof=1)
        * math.sqrt(float(ANNUALIZATION))
    )
    active = v12.normalize_active_map(active_map)
    active_dates = pd.DatetimeIndex(active["decision_date"].drop_duplicates().sort_values())
    next_publication = source["publication_date"].shift(-1)
    expiry_required = next_publication.isna() | next_publication.gt(source["forecast_period_end"])
    event_rows: list[dict[str, Any]] = []
    for index, row in source.iterrows():
        event_rows.append(
            {
                "event_type": "release",
                "desired_decision_date": row["publication_date"],
                "source_publication_date": row["publication_date"],
                "source_available_at": row["available_at"],
                "forecast_period_start": row["forecast_period_start"],
                "forecast_period_end": row["forecast_period_end"],
                "government_accounts_change_bln_rub": float(
                    row["government_accounts_change_bln_rub"]
                ),
                "direction": float(row["direction"]),
                "raw_sha256": row["raw_sha256"],
            }
        )
        if bool(expiry_required.iat[index]):
            event_rows.append(
                {
                    "event_type": "expiry",
                    "desired_decision_date": row["forecast_period_end"],
                    "source_publication_date": row["publication_date"],
                    "source_available_at": row["available_at"],
                    "forecast_period_start": row["forecast_period_start"],
                    "forecast_period_end": row["forecast_period_end"],
                    "government_accounts_change_bln_rub": float(
                        row["government_accounts_change_bln_rub"]
                    ),
                    "direction": 0.0,
                    "raw_sha256": row["raw_sha256"],
                }
            )
    events = pd.DataFrame(event_rows)
    decisions: list[dict[str, Any]] = []
    for event in events.itertuples(index=False):
        desired = pd.Timestamp(event.desired_decision_date)
        location = int(active_dates.searchsorted(desired, side="left"))
        if location >= len(active_dates):
            decisions.append(
                {
                    **event._asdict(),
                    "decision_date": pd.NaT,
                    "decision_at": pd.NaT,
                    "annualized_si_volatility": np.nan,
                    "target_weight": np.nan,
                    "decision_status": "no_future_active_decision_session",
                }
            )
            continue
        decision_date = pd.Timestamp(active_dates[location])
        decision_at = _decision_at(decision_date)
        if pd.Timestamp(event.source_available_at) > decision_at:
            raise ValueError("V18 event mapped before its source was available")
        if event.event_type == "release" and decision_date > pd.Timestamp(
            event.forecast_period_end
        ):
            status = "forecast_expired_before_factual_decision_session"
            volatility = np.nan
            target = np.nan
        elif event.event_type == "expiry" or float(event.direction) == 0.0:
            status = "mapped"
            volatility = si_volatility.get(decision_date, np.nan)
            target = 0.0
        else:
            volatility = si_volatility.get(decision_date, np.nan)
            if pd.isna(volatility) or not math.isfinite(float(volatility)):
                status = "missing_prior_60_session_SI_volatility"
                target = np.nan
            else:
                risk_scale = min(
                    MAXIMUM_ABSOLUTE_WEIGHT,
                    TARGET_VOLATILITY / max(float(volatility), VOLATILITY_FLOOR),
                )
                status = "mapped"
                target = float(event.direction) * risk_scale
        decisions.append(
            {
                **event._asdict(),
                "decision_date": decision_date,
                "decision_at": decision_at,
                "annualized_si_volatility": volatility,
                "target_weight": target,
                "decision_status": status,
            }
        )
    decision_frame = pd.DataFrame(decisions).sort_values(
        ["decision_date", "source_publication_date", "event_type"],
        kind="mergesort",
        na_position="last",
        ignore_index=True,
    )
    mapped_mask = decision_frame["decision_status"].eq("mapped")
    mapped = decision_frame.loc[mapped_mask].copy()
    duplicate_mask = mapped.duplicated("decision_date", keep="last")
    collisions = int(duplicate_mask.sum())
    if collisions:
        dropped_indices = mapped.index[duplicate_mask]
        decision_frame.loc[dropped_indices, "decision_status"] = (
            "superseded_same_decision_session"
        )
        mapped = mapped.loc[~duplicate_mask].copy()

    weight_rows: list[dict[str, Any]] = []
    for row in mapped.itertuples(index=False):
        provenance = json.dumps(
            {
                "version": "v18_cbr_liquidity_forecast_v1",
                "event_type": row.event_type,
                "source_publication_date": row.source_publication_date.date().isoformat(),
                "source_available_at": row.source_available_at.isoformat(),
                "forecast_period_start": row.forecast_period_start.date().isoformat(),
                "forecast_period_end": row.forecast_period_end.date().isoformat(),
                "government_accounts_change_bln_rub": float(
                    row.government_accounts_change_bln_rub
                ),
                "annualized_si_volatility": (
                    None
                    if pd.isna(row.annualized_si_volatility)
                    else float(row.annualized_si_volatility)
                ),
                "contains_prices_returns_targets_or_pnl_from_2026": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        for asset in v12.ASSETS:
            weight_rows.append(
                {
                    "decision_date": row.decision_date,
                    "asset": asset,
                    "target_weight": float(row.target_weight) if asset == "SI" else 0.0,
                    "provenance": provenance,
                }
            )
    weights = pd.DataFrame(weight_rows)
    if not weights.empty and weights.groupby("decision_date")["asset"].nunique().ne(
        len(v12.ASSETS)
    ).any():
        raise ValueError("V18 source weights are not complete four-asset snapshots")
    return SourceDecisionBuild(
        decisions=decision_frame,
        weights=weights.sort_values(
            ["decision_date", "asset"], kind="mergesort", ignore_index=True
        ),
        mapped_release_count=int(mapped["event_type"].eq("release").sum()),
        mapped_expiry_count=int(mapped["event_type"].eq("expiry").sum()),
        same_session_collisions=collisions,
        required_expiry_count=int(expiry_required.sum()),
    )


def _scenario_settings(protocol: dict[str, Any]) -> dict[str, dict[str, float]]:
    output = {
        str(name): {
            "slippage_ticks": int(values["slippage_ticks_per_leg"]),
            "fee_multiplier": float(values["conservative_fee_multiplier"]),
        }
        for name, values in protocol["execution"]["scenarios"].items()
    }
    expected = {
        "primary": {"slippage_ticks": 1, "fee_multiplier": 1.0},
        "doubled": {"slippage_ticks": 2, "fee_multiplier": 2.0},
        "stress": {"slippage_ticks": 4, "fee_multiplier": 2.0},
    }
    if output != expected:
        raise ValueError("V18 cost scenarios drifted from the seal")
    return output


def _promotion(
    scenario_results: dict[str, dict[str, Any]],
    checks: dict[str, bool],
    decision_counts_by_year: dict[str, int],
) -> dict[str, Any]:
    primary = scenario_results["primary"]
    release_count = sum(decision_counts_by_year.values())
    conditions = {
        "every_input_and_temporal_check_true": all(checks.values()),
        "at_least_245_release_decisions_and_45_each_oos_year": release_count >= 245
        and all(decision_counts_by_year.get(str(year), 0) >= 45 for year in range(2021, 2026)),
        "all_three_scenarios_execution_complete": all(
            bool(value["execution_complete"]) for value in scenario_results.values()
        ),
        "zero_critical_failures_and_zero_unresolved_halts": all(
            int(value["critical_failure_count"]) == 0
            and int(value["unresolved_halt_count"]) == 0
            for value in scenario_results.values()
        ),
        "primary_cagr_at_least_0_05": float(primary["cagr"]) >= 0.05,
        "primary_sharpe_at_least_0_75": float(primary["sharpe"]) >= 0.75,
        "primary_maximum_drawdown_at_most_0_20": float(primary["maximum_drawdown"]) <= 0.20,
        "primary_positive_years_at_least_4_of_5": int(primary["positive_years"]) >= 4
        and len(primary["annual_returns"]) == 5,
        "doubled_total_return_positive": float(scenario_results["doubled"]["total_return"])
        > 0.0,
        "stress_total_return_positive": float(scenario_results["stress"]["total_return"])
        > 0.0,
        "no_gross_participation_or_margin_breach": all(
            float(value["maximum_participation"]) <= MAXIMUM_PARTICIPATION + 1e-12
            and float(value["ending_cash"]) > 0.0
            for value in scenario_results.values()
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


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    frame.to_parquet(path, index=False, compression="zstd")


def _report_text(payload: dict[str, Any]) -> str:
    lines = [
        "# V18 CBR forward-liquidity direction for SI",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        (
            "This is a new release-keyed information family but the same previously seen "
            "2021-2025 market period, not an independent holdout."
        ),
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
    lines.extend(["", "## Primary annual returns", ""])
    for year, value in payload["scenarios"]["primary"]["annual_returns"].items():
        lines.append(f"- {year}: {value:.4%}")
    counts = payload["counts"]
    lines.extend(
        [
            "",
            "## Signal and execution",
            "",
            f"- Source releases: {counts['source_releases']}",
            f"- OOS release decisions by year: {counts['release_decisions_by_year']}",
            f"- Explicit forecast-expiry decisions: {counts['expiry_decisions_oos']}",
            f"- Extra roll decisions: {counts['roll_decisions']}",
            f"- Non-zero target dependencies: {counts['nonzero_targets']}",
            f"- Complete dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "The dated CBR record is delayed to end-of-publication-day Moscow. The signal "
            "then enters only at the following factual open and is flattened when its "
            "printed forecast period expires without a successor release.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute one immutable V18 run after all source and protocol identities pass."""
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    source = pd.read_parquet(
        verified.paths["cbr_liquidity_forecasts"],
        columns=protocol["inputs"]["cbr_liquidity_forecasts"]["allowed_columns"],
    )
    source_forecasts = normalize_forecasts(source)
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
    source_build = build_source_decisions(source_forecasts, panel, active)
    if source_build.weights.empty:
        raise ValueError("V18 produced no mapped source weights")
    target_build = v12.build_execution_targets(source_build.weights, active)
    market = v12.build_execution_market(observations, specs)
    coverage = v12.execution_coverage(market, target_build.targets)

    market_dates = pd.DatetimeIndex(
        pd.to_datetime(market["session_date"], errors="raise").drop_duplicates().sort_values()
    )
    predecessor = market_dates[market_dates < OOS_START].max()
    execution_market = market.loc[
        pd.to_datetime(market["session_date"], errors="raise").between(predecessor, OOS_END)
    ].copy()
    scenario_outputs: dict[str, FuturesPortfolioLedgerResult] = {}
    scenario_results: dict[str, dict[str, Any]] = {}
    for name, settings in _scenario_settings(protocol).items():
        result = run_futures_portfolio_ledger(
            execution_market,
            target_build.targets,
            FuturesPortfolioLedgerConfig(
                initial_cash=INITIAL_CASH,
                expected_assets=v12.ASSETS,
                maximum_gross_notional_multiple=1.0,
                initial_margin_buffer_multiplier=2.0,
                maximum_participation=MAXIMUM_PARTICIPATION,
                slippage_ticks=int(settings["slippage_ticks"]),
                fee_multiplier=float(settings["fee_multiplier"]),
                execution_atomicity="asset",
                terminal_policy="carry",
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name] = v12.scenario_metrics(result, execution_market, settings)

    mapped_decisions = source_build.decisions.loc[
        source_build.decisions["decision_status"].eq("mapped")
        & pd.to_datetime(source_build.decisions["decision_date"]).between(OOS_START, OOS_END)
    ].copy()
    release_decisions = mapped_decisions.loc[mapped_decisions["event_type"].eq("release")]
    decision_counts_by_year = {
        str(key): int(value)
        for key, value in pd.to_datetime(release_decisions["decision_date"])
        .dt.year.value_counts()
        .items()
    }
    checks = dict(verified.checks)
    checks["source_available_before_2026"] = bool(
        source_forecasts["available_at"].lt(PROTECTED_FROM).all()
    )
    mapped_all = source_build.decisions.loc[
        source_build.decisions["decision_status"].eq("mapped")
    ]
    checks["mapped_decisions_after_source_availability"] = bool(
        (
            pd.to_datetime(mapped_all["source_available_at"], utc=True)
            <= pd.to_datetime(mapped_all["decision_at"], utc=True)
        ).all()
    )
    checks["release_decisions_not_after_forecast_expiry"] = bool(
        (
            pd.to_datetime(
                mapped_all.loc[mapped_all["event_type"].eq("release"), "decision_date"]
            )
            <= pd.to_datetime(
                mapped_all.loc[mapped_all["event_type"].eq("release"), "forecast_period_end"]
            )
        ).all()
    )
    checks["every_required_expiry_was_constructed"] = (
        int(source_build.decisions["event_type"].eq("expiry").sum())
        == source_build.required_expiry_count
    )
    checks["no_same_session_collisions"] = source_build.same_session_collisions == 0
    checks["all_required_government_values_finite"] = bool(
        np.isfinite(source_forecasts["government_accounts_change_bln_rub"].to_numpy()).all()
    )
    counts = {
        "source_rows": len(source),
        "source_releases": int(source_forecasts["publication_date"].nunique()),
        "mapped_release_decisions_all_dates": source_build.mapped_release_count,
        "mapped_expiry_decisions_all_dates": source_build.mapped_expiry_count,
        "required_expiry_decisions_all_dates": source_build.required_expiry_count,
        "same_session_collisions": source_build.same_session_collisions,
        "release_decisions_by_year": decision_counts_by_year,
        "expiry_decisions_oos": int(mapped_decisions["event_type"].eq("expiry").sum()),
        "source_event_decisions": target_build.weekly_decisions,
        "roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": len(target_build.targets),
        "nonzero_targets": int(target_build.targets["target_weight"].abs().gt(1e-12).sum()),
        "covered_nonzero_targets": int(coverage["execution_dependencies_complete"].sum()),
    }
    promotion = _promotion(scenario_results, checks, decision_counts_by_year)
    code_paths = {
        "v18_implementation": Path(__file__).resolve(),
        "cbr_source": PROJECT_ROOT / "src/market_lab/futures/cbr_liquidity_forecast_source.py",
        "v12_parent": Path(v12.__file__).resolve(),
        "execution_dataset": PROJECT_ROOT / "src/market_lab/futures/execution_dataset.py",
        "portfolio_ledger": PROJECT_ROOT / "src/market_lab/futures/portfolio_ledger.py",
    }
    identity = {
        "protocol_sha256": CONFIG_SHA256,
        "parent_v12_protocol_sha256": v12.CONFIG_SHA256,
        "input_sha256": {
            name: declaration["sha256"] for name, declaration in protocol["inputs"].items()
        },
        "code_sha256": {name: sha256_file(path) for name, path in code_paths.items()},
        "protected_from": PROTECTED_FROM.isoformat(),
        "contains_2026_prices_returns_targets_or_pnl": False,
    }
    payload: dict[str, Any] = {
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": CONFIG_SHA256,
        "research_only": True,
        "adaptive_same_market_period": True,
        "new_release_keyed_information_family": True,
        "independent_holdout_confirmation": False,
        "live_trading_allowed": False,
        "checks": checks,
        "input_metadata": verified.metadata,
        "identity": identity,
        "counts": counts,
        "scenarios": scenario_results,
        "promotion": promotion,
        "limitations": protocol["execution"]["limitations"],
    }

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"v18_cbr_liquidity_forecast_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V18 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        _write_parquet(temporary / "source_forecasts.parquet", source_forecasts)
        _write_parquet(temporary / "source_decisions.parquet", source_build.decisions)
        _write_parquet(temporary / "mapped_targets.parquet", target_build.targets)
        target_build.decision_audit.to_csv(
            temporary / "decision_audit.csv", index=False, encoding="utf-8-sig"
        )
        coverage.to_csv(temporary / "coverage.csv", index=False, encoding="utf-8-sig")
        for name, result in scenario_outputs.items():
            _write_parquet(temporary / f"ledger_{name}.parquet", result.ledger)
            _write_parquet(temporary / f"orders_{name}.parquet", result.orders)
            _write_parquet(temporary / f"positions_{name}.parquet", result.positions)
        (temporary / "report.md").write_text(_report_text(payload), encoding="utf-8-sig")
        artifacts: dict[str, Any] = {}
        for path in sorted(temporary.iterdir()):
            if path.name in {"metrics.json", "identity.json"}:
                continue
            entry: dict[str, Any] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            if path.suffix == ".parquet":
                entry["rows"] = pq.ParquetFile(path).metadata.num_rows
            artifacts[path.name] = entry
        payload["artifacts"] = artifacts
        metrics_path = temporary / "metrics.json"
        metrics_path.write_text(
            json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8-sig",
        )
        (temporary / "identity.json").write_text(
            json.dumps(
                _json_safe({**identity, "metrics_sha256": sha256_file(metrics_path)}),
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
        help="External immutable runs root; a unique V18 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
