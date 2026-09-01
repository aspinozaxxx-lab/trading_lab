"""Sealed V19 CBR-reported Ministry of Finance FX-flow experiment for SI."""

from __future__ import annotations

import argparse
import gzip
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
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v19_cbr_minfin_fx_persistence.yaml"
CONFIG_SHA256: Final[str] = (
    "1340ffacae93b514fe4605262d8946a6a87cbc4619c1748b48ac45b9a9b19946"
)
CBR_SOURCE_MANIFEST_SHA256: Final[str] = (
    "f1701ec330fce9813d75bd711de235744dd8a9daf5f192325efe64f16e98e61a"
)
CBR_RAW_HTML_SHA256: Final[str] = (
    "5e9ec55d25f39291c5992225c103f6fe038e2e8513ed54f95cfdbcecccdd9977"
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


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _json_safe(value: Any) -> Any:
    return v12._json_safe(value)


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the byte seal and every V19 economic invariant before outcome access."""
    path = config_path.resolve()
    if path != CONFIG_PATH.resolve() or sha256_file(path) != CONFIG_SHA256:
        raise ValueError("sealed V19 protocol byte drift")
    stated = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V19 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V19 protocol must be a mapping")
    signal = protocol["signal"]
    portfolio = protocol["portfolio"]
    execution = protocol["execution"]
    information = protocol["information_set"]
    if (
        protocol.get("protocol_id") != "futures_v19_cbr_minfin_fx_persistence_v1"
        or protocol.get("status") != "sealed_before_any_v19_market_outcome_read"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or protocol.get("parent_v12_protocol_sha256") != v12.CONFIG_SHA256
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or signal["value"]
        != "minfin_fx_operations_bln_rub_from_previous_observation_day"
        or int(signal["economic_sign_to_SI"]) != 1
        or signal["direction"] != "sign_of_value_with_exact_zero_flat"
        or signal["normalization"] != "none"
        or signal["amount_scaling"] != "none"
        or signal["trade_threshold"] != "none"
        or signal["smoothing"] != "none"
        or information["source_availability"]
        != "10_31_Europe_Moscow_on_next_dated_CBR_working_day"
        or information["same_decision_session_collision"]
        != "keep_latest_observation_available_by_that_session_close"
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
        raise ValueError("sealed V19 protocol invariants were weakened")
    return protocol


@dataclass(frozen=True, slots=True)
class VerifiedInputs:
    paths: dict[str, Path]
    checks: dict[str, bool]
    metadata: dict[str, Any]
    parent_protocol: dict[str, Any]


def verify_inputs(protocol: dict[str, Any]) -> VerifiedInputs:
    """Verify source-only CBR artifacts and parent identities before price reads."""
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
        "cbr_liquidity_factors",
        "cbr_liquidity_factors_manifest",
        "cbr_liquidity_factors_raw",
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
        if name == "cbr_liquidity_factors" and exists:
            parquet = pq.ParquetFile(path)
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
            checks[f"{name}_schema"] = set(declaration["allowed_columns"]) <= set(
                parquet.schema_arrow.names
            )
            metadata[name]["rows"] = parquet.metadata.num_rows
            metadata[name]["columns"] = parquet.schema_arrow.names
    if not all(checks.values()):
        raise ValueError(f"V19 byte/schema preflight failed: {checks}")

    manifest = json.loads(
        paths["cbr_liquidity_factors_manifest"].read_text(encoding="utf-8-sig")
    )
    processed = manifest["artifacts"]["processed"]
    raw = manifest["artifacts"]["raw_current_vintage"]
    temporal = manifest["temporal_semantics"]
    manifest_payload = dict(manifest)
    stated_payload_hash = manifest_payload.pop("manifest_payload_sha256")
    raw_html = gzip.decompress(paths["cbr_liquidity_factors_raw"].read_bytes())
    checks["cbr_manifest_identity"] = (
        sha256_file(paths["cbr_liquidity_factors_manifest"])
        == CBR_SOURCE_MANIFEST_SHA256
    )
    checks["cbr_manifest_payload_identity"] = (
        _sha256_bytes(_canonical_json(manifest_payload)) == stated_payload_hash
    )
    checks["cbr_manifest_processed_identity"] = (
        processed["sha256"] == protocol["inputs"]["cbr_liquidity_factors"]["sha256"]
        and int(processed["rows"])
        == int(protocol["inputs"]["cbr_liquidity_factors"]["rows"])
    )
    checks["cbr_manifest_raw_identity"] = (
        raw["sha256"] == protocol["inputs"]["cbr_liquidity_factors_raw"]["sha256"]
        and int(raw["bytes"])
        == int(protocol["inputs"]["cbr_liquidity_factors_raw"]["bytes"])
        and int(raw["uncompressed_bytes"]) == len(raw_html)
        and raw["uncompressed_sha256"] == _sha256_bytes(raw_html) == CBR_RAW_HTML_SHA256
    )
    coverage = manifest["coverage"]
    checks["cbr_coverage_counts"] = (
        int(coverage["raw_dated_rows"]) == 1239
        and int(coverage["admitted_rows"]) == 1238
        and int(coverage["excluded_without_pre_boundary_publication"]) == 1
        and coverage["minimum_observation_date"] == "2021-01-11"
        and coverage["maximum_observation_date"] == "2025-12-30"
        and coverage["maximum_publication_date"] == "2025-12-31"
        and coverage["maximum_available_at"] == "2025-12-31T07:31:00+00:00"
    )
    checks["cbr_current_vintage_target_free"] = (
        temporal["current_vintage_historical_record"] is True
        and temporal["contains_prices_returns_targets_labels_or_pnl"] is False
    )
    checks["cbr_development_only_semantics"] = (
        temporal["development_backtest_admissible"] is True
        and temporal["independent_confirmation_without_forward_vintage_collection"] is False
        and temporal["original_historical_response_bytes_available"] is False
        and temporal["historical_values_may_be_revised"] is True
        and temporal["last_modified_used_for_availability"] is False
    )
    checks["cbr_sign_semantics"] = manifest["sign_semantics"] == {
        "minfin_fx_positive": "purchase of foreign currency on the domestic FX market",
        "minfin_fx_negative": "sale of foreign currency on the domestic FX market",
    }
    metadata["cbr_manifest_payload"] = manifest
    if not all(checks.values()):
        raise ValueError(f"V19 source semantic preflight failed: {checks}")
    return VerifiedInputs(
        paths=paths,
        checks=checks,
        metadata=metadata,
        parent_protocol=parent_protocol,
    )


def normalize_factors(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate current-vintage records and derive only the sealed Minfin-FX sign."""
    required = {
        "observation_date",
        "publication_date",
        "available_at",
        "minfin_fx_operations_bln_rub",
        "source_url",
        "raw_sha256",
        "current_vintage_historical_record",
        "original_publication_bytes_available",
        "historical_values_may_be_revised",
    }
    if missing := required - set(frame.columns):
        raise ValueError(f"V19 CBR source lacks columns: {sorted(missing)}")
    source = frame.loc[:, sorted(required)].copy()
    for column in ("observation_date", "publication_date"):
        source[column] = pd.to_datetime(source[column], errors="raise").dt.normalize()
    source["available_at"] = pd.to_datetime(source["available_at"], errors="raise", utc=True)
    source["minfin_fx_operations_bln_rub"] = pd.to_numeric(
        source["minfin_fx_operations_bln_rub"], errors="coerce"
    )
    if len(source) != 1238 or source["observation_date"].duplicated().any():
        raise ValueError("V19 CBR source row identity or observation uniqueness drifted")
    if (
        source["observation_date"].min() != pd.Timestamp("2021-01-11")
        or source["observation_date"].max() != pd.Timestamp("2025-12-30")
        or source["publication_date"].max() != pd.Timestamp("2025-12-31")
    ):
        raise ValueError("V19 CBR source date boundaries drifted")
    if source["available_at"].ge(PROTECTED_FROM).any():
        raise ValueError("V19 CBR source touches protected 2026+")
    expected_available = (
        source["publication_date"].dt.tz_localize(MOSCOW)
        + pd.Timedelta(hours=10, minutes=31)
    ).dt.tz_convert("UTC")
    if not source["available_at"].equals(expected_available):
        raise ValueError("V19 CBR conservative publication availability drifted")
    if source["publication_date"].le(source["observation_date"]).any():
        raise ValueError("V19 source publication must follow the observation day")
    values = source["minfin_fx_operations_bln_rub"].to_numpy(dtype=float)
    if source["minfin_fx_operations_bln_rub"].isna().any() or not np.isfinite(values).all():
        raise ValueError("V19 required Minfin FX values must be finite")
    if (
        not source["current_vintage_historical_record"].astype(bool).all()
        or source["original_publication_bytes_available"].astype(bool).any()
        or not source["historical_values_may_be_revised"].astype(bool).all()
    ):
        raise ValueError("V19 current-vintage/revision semantics drifted")
    if not source["raw_sha256"].astype("string").eq(CBR_RAW_HTML_SHA256).all():
        raise ValueError("V19 raw source identity drifted")
    if not source["source_url"].astype("string").str.startswith(
        "https://www.cbr.ru/statistics/flikvid/"
    ).all():
        raise ValueError("V19 source URL escaped the official endpoint")
    signs = {
        "positive": int((values > 0.0).sum()),
        "negative": int((values < 0.0).sum()),
        "zero": int((values == 0.0).sum()),
    }
    if signs != {"positive": 249, "negative": 690, "zero": 299}:
        raise ValueError("V19 source sign counts drifted")
    source["direction"] = np.sign(values)
    return source.sort_values("observation_date", kind="mergesort", ignore_index=True)


@dataclass(frozen=True, slots=True)
class SourceDecisionBuild:
    decisions: pd.DataFrame
    weights: pd.DataFrame
    mapped_source_count: int
    same_session_collisions: int


def _decision_at(decision_date: pd.Timestamp) -> pd.Timestamp:
    return (
        decision_date.tz_localize(MOSCOW)
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).tz_convert("UTC")


def build_source_decisions(
    factors: pd.DataFrame,
    panel: pd.DataFrame,
    active_map: pd.DataFrame,
) -> SourceDecisionBuild:
    """Map published factors to completed sessions and keep the latest causal collision."""
    source = normalize_factors(factors)
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
    decisions: list[dict[str, Any]] = []
    for row in source.itertuples(index=False):
        desired = pd.Timestamp(row.publication_date)
        location = int(active_dates.searchsorted(desired, side="left"))
        common = {
            "source_observation_date": row.observation_date,
            "source_publication_date": row.publication_date,
            "source_available_at": row.available_at,
            "minfin_fx_operations_bln_rub": float(row.minfin_fx_operations_bln_rub),
            "direction": float(row.direction),
            "raw_sha256": row.raw_sha256,
        }
        if location >= len(active_dates):
            decisions.append(
                {
                    **common,
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
        if pd.Timestamp(row.available_at) > decision_at:
            raise ValueError("V19 factor mapped before its source was available")
        volatility = si_volatility.get(decision_date, np.nan)
        if float(row.direction) == 0.0:
            status = "mapped"
            target = 0.0
        elif pd.isna(volatility) or not math.isfinite(float(volatility)):
            status = "missing_prior_60_session_SI_volatility"
            target = np.nan
        else:
            risk_scale = min(
                MAXIMUM_ABSOLUTE_WEIGHT,
                TARGET_VOLATILITY / max(float(volatility), VOLATILITY_FLOOR),
            )
            status = "mapped"
            target = float(row.direction) * risk_scale
        decisions.append(
            {
                **common,
                "decision_date": decision_date,
                "decision_at": decision_at,
                "annualized_si_volatility": volatility,
                "target_weight": target,
                "decision_status": status,
            }
        )
    decision_frame = pd.DataFrame(decisions).sort_values(
        ["decision_date", "source_publication_date", "source_observation_date"],
        kind="mergesort",
        na_position="last",
        ignore_index=True,
    )
    mapped = decision_frame.loc[decision_frame["decision_status"].eq("mapped")].copy()
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
                "version": "v19_cbr_minfin_fx_persistence_v1",
                "source_observation_date": row.source_observation_date.date().isoformat(),
                "source_publication_date": row.source_publication_date.date().isoformat(),
                "source_available_at": row.source_available_at.isoformat(),
                "minfin_fx_operations_bln_rub": float(row.minfin_fx_operations_bln_rub),
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
        raise ValueError("V19 source weights are not complete four-asset snapshots")
    return SourceDecisionBuild(
        decisions=decision_frame,
        weights=weights.sort_values(
            ["decision_date", "asset"], kind="mergesort", ignore_index=True
        ),
        mapped_source_count=len(mapped),
        same_session_collisions=collisions,
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
        raise ValueError("V19 cost scenarios drifted from the seal")
    return output


def _promotion(
    scenario_results: dict[str, dict[str, Any]],
    checks: dict[str, bool],
    decision_counts_by_year: dict[str, int],
    nonzero_mapped_decisions: int,
) -> dict[str, Any]:
    primary = scenario_results["primary"]
    source_count = sum(decision_counts_by_year.values())
    conditions = {
        "every_input_and_temporal_check_true": all(checks.values()),
        "at_least_1000_mapped_source_decisions_and_180_each_oos_year": (
            source_count >= 1000
            and all(decision_counts_by_year.get(str(year), 0) >= 180 for year in range(2021, 2026))
        ),
        "at_least_800_nonzero_mapped_source_decisions": nonzero_mapped_decisions >= 800,
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
        "# V19 CBR-reported Minfin FX-flow persistence for SI",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        (
            "This uses a revisable current-vintage historical table and the same seen "
            "2021-2025 SI period, not original publication vintages or an independent holdout."
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
            f"- Source rows: {counts['source_rows']}",
            f"- Source sign counts: {counts['source_sign_counts']}",
            f"- OOS mapped decisions by year: {counts['source_decisions_by_year']}",
            f"- Non-zero mapped source decisions: {counts['nonzero_source_decisions']}",
            f"- Same-session source collisions resolved latest-first: "
            f"{counts['same_session_collisions']}",
            f"- Extra roll decisions: {counts['roll_decisions']}",
            f"- Non-zero target dependencies: {counts['nonzero_targets']}",
            f"- Complete dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "Each previous-working-day factor is admitted only from 10:31 Moscow on its "
            "inferred publication day. The position can change at that session close and "
            "is filled only at the following factual active-contract open.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute one immutable V19 run after all source and protocol identities pass."""
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    source = pd.read_parquet(
        verified.paths["cbr_liquidity_factors"],
        columns=protocol["inputs"]["cbr_liquidity_factors"]["allowed_columns"],
    )
    source_factors = normalize_factors(source)
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
    source_build = build_source_decisions(source_factors, panel, active)
    if source_build.weights.empty:
        raise ValueError("V19 produced no mapped source weights")
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
    decision_counts_by_year = {
        str(key): int(value)
        for key, value in pd.to_datetime(mapped_decisions["decision_date"])
        .dt.year.value_counts()
        .items()
    }
    nonzero_mapped = int(mapped_decisions["direction"].ne(0.0).sum())
    checks = dict(verified.checks)
    checks["source_available_before_2026"] = bool(
        source_factors["available_at"].lt(PROTECTED_FROM).all()
    )
    checks["source_observation_precedes_publication"] = bool(
        source_factors["observation_date"].lt(source_factors["publication_date"]).all()
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
    checks["mapped_weight_sessions_unique"] = not source_build.weights.duplicated(
        ["decision_date", "asset"]
    ).any()
    collision_candidates = source_build.decisions.loc[
        source_build.decisions["decision_status"].isin(
            {"mapped", "superseded_same_decision_session"}
        )
    ]
    latest_observations = collision_candidates.groupby("decision_date")[
        "source_observation_date"
    ].max()
    selected_observations = mapped_all.set_index("decision_date")["source_observation_date"]
    checks["same_session_collisions_keep_latest_known_observation"] = bool(
        selected_observations.sort_index().equals(latest_observations.sort_index())
    )
    checks["all_required_Minfin_FX_values_finite"] = bool(
        np.isfinite(source_factors["minfin_fx_operations_bln_rub"].to_numpy()).all()
    )
    checks["every_source_row_classified"] = len(source_build.decisions) == len(source_factors)
    source_values = source_factors["minfin_fx_operations_bln_rub"]
    source_sign_counts = {
        "positive": int(source_values.gt(0.0).sum()),
        "negative": int(source_values.lt(0.0).sum()),
        "zero": int(source_values.eq(0.0).sum()),
    }
    mapped_directions = mapped_decisions.sort_values("decision_date")["direction"]
    counts = {
        "source_rows": len(source_factors),
        "source_sign_counts": source_sign_counts,
        "mapped_source_decisions_all_dates": source_build.mapped_source_count,
        "same_session_collisions": source_build.same_session_collisions,
        "decision_status_counts": {
            str(key): int(value)
            for key, value in source_build.decisions["decision_status"].value_counts().items()
        },
        "source_decisions_by_year": decision_counts_by_year,
        "nonzero_source_decisions": nonzero_mapped,
        "mapped_direction_changes": int(mapped_directions.ne(mapped_directions.shift()).sum()),
        "source_event_decisions": target_build.weekly_decisions,
        "roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": len(target_build.targets),
        "nonzero_targets": int(target_build.targets["target_weight"].abs().gt(1e-12).sum()),
        "covered_nonzero_targets": int(coverage["execution_dependencies_complete"].sum()),
    }
    promotion = _promotion(
        scenario_results,
        checks,
        decision_counts_by_year,
        nonzero_mapped,
    )
    code_paths = {
        "v19_implementation": Path(__file__).resolve(),
        "cbr_source": PROJECT_ROOT / "src/market_lab/futures/cbr_liquidity_factors_source.py",
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
        "new_current_vintage_information_family": True,
        "original_publication_vintages": False,
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
    run_name = f"v19_cbr_minfin_fx_persistence_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V19 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        _write_parquet(temporary / "source_factors.parquet", source_factors)
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
        help="External immutable runs root; a unique V19 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
