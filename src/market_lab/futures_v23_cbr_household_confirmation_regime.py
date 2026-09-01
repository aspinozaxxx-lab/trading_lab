"""Sealed V23 CBR household inflation/sentiment confirmation experiment."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from market_lab import futures_v12_core4_correlation_trend as v12
from market_lab import futures_v22_cbr_business_climate_regime as shared_mapper
from market_lab.futures import cbr_inflation_expectations_source as cbr_source
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    FuturesPortfolioLedgerResult,
    run_futures_portfolio_ledger,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v23_cbr_household_confirmation_regime.yaml"
)
CONFIG_SHA256: Final[str] = (
    "2a8a35a898eddae72694bce159282ced6f72230b537613ad224c0d2b6001f2ee"
)
OOS_START: Final[pd.Timestamp] = pd.Timestamp("2021-01-01")
OOS_END: Final[pd.Timestamp] = pd.Timestamp("2025-12-31")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
EXPIRY_DAYS: Final[int] = 45
VOLATILITY_LOOKBACK: Final[int] = 60
ANNUALIZATION: Final[int] = 252
VOLATILITY_FLOOR: Final[float] = 0.10
TARGET_VOLATILITY: Final[float] = 0.20
RISK_BUDGET: Final[float] = 1.0 / 3.0
INITIAL_CASH: Final[float] = 1_000_000.0
MAXIMUM_PARTICIPATION: Final[float] = 0.01
ACTIVE_ASSETS: Final[tuple[str, ...]] = ("SI", "RI", "MIX")


def sha256_file(path: Path) -> str:
    return shared_mapper.sha256_file(path)


def _canonical_json(value: object) -> bytes:
    return shared_mapper._canonical_json(value)


def _json_safe(value: Any) -> Any:
    return v12._json_safe(value)


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the byte seal and every predeclared V23 economic invariant."""
    path = config_path.resolve()
    if path != CONFIG_PATH.resolve() or sha256_file(path) != CONFIG_SHA256:
        raise ValueError("sealed V23 protocol byte drift")
    stated = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V23 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V23 protocol must be a mapping")
    information = protocol["information_set"]
    signal = protocol["signal"]
    portfolio = protocol["portfolio"]
    execution = protocol["execution"]
    counts = signal["sealed_source_counts"]
    expected_values = [
        "exact_release_specific_XLSX_expected_inflation_12m_median",
        "exact_release_specific_XLSX_consumer_sentiment_index",
    ]
    expected_counts = {
        "releases": 48,
        "warmup_releases": 1,
        "scored_releases": 47,
        "expected_inflation_delta_positive": 25,
        "expected_inflation_delta_negative": 22,
        "expected_inflation_delta_zero": 0,
        "consumer_sentiment_delta_positive": 24,
        "consumer_sentiment_delta_negative": 23,
        "consumer_sentiment_delta_zero": 0,
        "risk_on_confirmations": 16,
        "risk_off_confirmations": 17,
        "mixed_or_zero_confirmations": 14,
        "nonzero_asset_directions": 99,
        "source_only_expiry_states": 2,
        "modified_after_publication_pages": 1,
        "same_available_at_collision_rows": 2,
        "page_XLSX_display_matches": 48,
        "page_XLSX_exact_matches": 43,
    }
    if (
        protocol.get("protocol_id")
        != "futures_v23_cbr_household_confirmation_regime_v1"
        or protocol.get("status")
        != "sealed_before_any_v23_market_outcome_read"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or protocol.get("source_commit_before_protocol") != "3d18a03"
        or protocol.get("parent_v12_protocol_sha256") != v12.CONFIG_SHA256
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or information["source_availability"]
        != "23_59_59_Europe_Moscow_on_max_publication_and_last_update_date"
        or list(information["selected_values"]) != expected_values
        or information["html_chart_values"] != "rounded_display_cross_check_only"
        or information["observed_inflation"]
        != "archived_for_audit_forbidden_in_v23_signal"
        or information["same_available_at_collision"] != "keep_latest_release_month"
        or signal["mixed_or_zero_pair"] != "cash"
        or signal["magnitude_scaling"] != "none"
        or signal["threshold"] != "none"
        or signal["fit_or_outcome_training"] != "none"
        or signal["hyperparameter_search"] is not False
        or int(signal["expiry_calendar_days"]) != EXPIRY_DAYS
        or {key: int(counts[key]) for key in expected_counts} != expected_counts
        or {int(key): int(value) for key, value in counts["scored_by_release_year"].items()}
        != {2022: 11, 2023: 12, 2024: 12, 2025: 12}
        or tuple(portfolio["active_signal_assets"]) != ACTIVE_ASSETS
        or float(portfolio["equal_absolute_risk_budget_each_active_asset"])
        != RISK_BUDGET
        or portfolio["BR_target_always_zero"] is not True
        or int(portfolio["daily_volatility_lookback_sessions"])
        != VOLATILITY_LOOKBACK
        or int(portfolio["annualization_sessions"]) != ANNUALIZATION
        or float(portfolio["annualized_volatility_floor"]) != VOLATILITY_FLOOR
        or float(portfolio["annual_target_volatility_each_asset"])
        != TARGET_VOLATILITY
        or float(portfolio["maximum_absolute_weight_each_active_asset"])
        != RISK_BUDGET
        or float(portfolio["gross_cap"]) != 1.0
        or execution["execution_atomicity"] != "portfolio"
        or float(execution["initial_cash_rub"]) != INITIAL_CASH
        or float(execution["maximum_participation"]) != MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"]) != 1.0
        or float(execution["initial_margin_buffer_multiple"]) != 2.0
    ):
        raise ValueError("sealed V23 protocol invariants were weakened")
    return protocol


def verify_inputs(protocol: dict[str, Any]) -> shared_mapper.VerifiedInputs:
    """Verify raw official responses and frozen parent identities before prices."""
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

    source_names = (
        "cbr_household_releases",
        "cbr_household_manifest",
        "cbr_household_coverage",
        "cbr_household_raw_responses",
    )
    metadata: dict[str, Any] = {"parent_v12": parent_verified.metadata}
    for name in source_names:
        declaration = protocol["inputs"][name]
        path = v12._resolved_input(str(declaration["path"]))
        paths[name] = path
        exists = path.is_file()
        actual_bytes = path.stat().st_size if exists else None
        actual_sha = sha256_file(path) if exists else None
        checks[f"{name}_exists"] = exists
        checks[f"{name}_bytes"] = exists and actual_bytes == int(declaration["bytes"])
        checks[f"{name}_sha256"] = exists and actual_sha == declaration["sha256"]
        metadata[name] = {
            "path": declaration["path"],
            "bytes": actual_bytes,
            "sha256": actual_sha,
        }
        if name in {"cbr_household_releases", "cbr_household_coverage"} and exists:
            parquet = pq.ParquetFile(path)
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
            checks[f"{name}_schema"] = tuple(parquet.schema_arrow.names) == tuple(
                declaration["allowed_columns"]
            )
            metadata[name]["rows"] = parquet.metadata.num_rows
            metadata[name]["columns"] = parquet.schema_arrow.names
    if not all(checks.values()):
        raise ValueError(f"V23 byte/schema preflight failed: {checks}")

    manifest = json.loads(paths["cbr_household_manifest"].read_text(encoding="utf-8-sig"))
    manifest_payload = dict(manifest)
    stated_payload_hash = manifest_payload.pop("manifest_payload_sha256")
    artifacts = manifest["artifacts"]
    coverage_manifest = manifest["coverage"]
    temporal = manifest["temporal_semantics"]
    values = manifest["value_semantics"]
    quality = manifest["source_quality"]
    checks["cbr_manifest_payload_identity"] = (
        shared_mapper._sha256_bytes(_canonical_json(manifest_payload))
        == stated_payload_hash
    )
    checks["cbr_manifest_artifact_identities"] = bool(
        artifacts["processed"]["sha256"]
        == protocol["inputs"]["cbr_household_releases"]["sha256"]
        and int(artifacts["processed"]["rows"]) == 48
        and artifacts["coverage"]["sha256"]
        == protocol["inputs"]["cbr_household_coverage"]["sha256"]
        and int(artifacts["coverage"]["rows"]) == 48
        and artifacts["raw_responses"]["sha256"]
        == protocol["inputs"]["cbr_household_raw_responses"]["sha256"]
        and int(artifacts["raw_responses"]["records"]) == 146
    )
    checks["cbr_manifest_coverage"] = bool(
        manifest["source_id"]
        == "official-cbr-inflation-expectations-releases-2022-2025-v1"
        and int(coverage_manifest["release_pages"]) == 48
        and coverage_manifest["release_pages_by_year"]
        == {"2022": 12, "2023": 12, "2024": 12, "2025": 12}
        and coverage_manifest["minimum_release_month"] == "2022-01-01"
        and coverage_manifest["maximum_release_month"] == "2025-12-01"
        and int(coverage_manifest["modified_after_publication_count"]) == 1
        and int(coverage_manifest["rows_in_availability_collisions"]) == 2
        and coverage_manifest["sequential_expected_inflation_delta_counts"]
        == {"positive": 25, "negative": 22, "zero": 0}
        and coverage_manifest["sequential_consumer_sentiment_delta_counts"]
        == {"positive": 24, "negative": 23, "zero": 0}
        and coverage_manifest["aligned_confirmation_counts"]
        == {"risk_on": 16, "risk_off": 17, "mixed_or_zero": 14}
    )
    checks["cbr_release_specific_target_free"] = bool(
        temporal["release_specific_files_retrieved_currently"] is True
        and temporal["contains_prices_returns_targets_labels_or_pnl"] is False
        and temporal["missing_values_are_not_zero"] is True
        and temporal["date_only_source_uses_conservative_day_end"] is True
    )
    checks["cbr_development_only_semantics"] = bool(
        temporal["development_backtest_admissible"] is True
        and temporal["independent_confirmation_without_forward_vintage_collection"]
        is False
        and temporal["original_historical_response_bytes_available"] is False
        and temporal["historical_content_immutability_cryptographically_proved"] is False
    )
    checks["cbr_exact_xlsx_value_semantics"] = bool(
        values["strategy_admissible_values"]
        == [
            "exact XLSX median expected inflation over the next 12 months",
            "exact XLSX consumer sentiment index",
        ]
        and values["observed_inflation_exact_retained_for_source_audit"] is True
        and values["page_chart_endpoints_cross_checked_against_xlsx"] is True
        and values["one_decimal_page_chart_display_retained"] is True
        and values["latest_current_vintage_history_not_used"] is True
    )
    checks["cbr_source_quality"] = bool(
        quality["archive_contains_every_expected_month"] is True
        and quality["archive_index_unchanged_during_collection"] is True
        and quality["every_release_has_page_pdf_and_xlsx"] is True
        and quality["every_xlsx_series_ends_on_release_month"] is True
        and quality["every_page_and_xlsx_inflation_display_endpoint_matches"] is True
        and int(quality["page_xlsx_exact_match_count"]) == 43
        and int(quality["duplicate_release_months"]) == 0
    )

    raw_records = shared_mapper._decode_raw_archive(paths["cbr_household_raw_responses"])
    raw_counts = pd.Series([record["kind"] for record in raw_records]).value_counts()
    raw_key = {
        (str(record["kind"]), str(record["identity"])): record
        for record in raw_records
    }
    checks["cbr_raw_record_counts"] = bool(
        len(raw_records) == 146
        and len(raw_key) == 146
        and raw_counts.to_dict()
        == {"page": 48, "xlsx": 48, "pdf": 48, "archive": 2}
    )
    initial = raw_key[("archive", "initial")]["decoded_content"]
    final = raw_key[("archive", "final")]["decoded_content"]
    initial_releases = cbr_source.discover_release_links(initial)
    final_releases = cbr_source.discover_release_links(final)
    checks["cbr_raw_archive_indexes_match"] = initial_releases == final_releases
    reparsed_rows: list[dict[str, object]] = []
    for release in initial_releases:
        page_record = raw_key[("page", release.release_key)]
        xlsx_record = raw_key[("xlsx", release.release_key)]
        pdf_record = raw_key[("pdf", release.release_key)]
        if not pdf_record["decoded_content"].startswith(b"%PDF-"):
            raise ValueError(f"V23 raw PDF is invalid for {release.release_key}")
        row = cbr_source.parse_release_page(
            page_record["decoded_content"],
            release=release,
            retrieved_at_utc=manifest["fetched_at_utc"],
        )
        workbook = cbr_source.parse_statistics_workbook(
            xlsx_record["decoded_content"], release_month=release.release_month
        )
        exact_matches: list[bool] = []
        for component in ("expected_inflation", "observed_inflation"):
            page_exact = float(row[f"{component}_chart_exact"])
            workbook_exact = float(workbook[f"{component}_exact"])
            if (
                abs(page_exact - workbook_exact) > 0.051
                or not math.isclose(
                    float(row[f"{component}_value"]),
                    cbr_source._one_decimal(workbook_exact),
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError(f"V23 page/XLSX mismatch for {release.release_key}")
            exact_matches.append(
                math.isclose(page_exact, workbook_exact, rel_tol=0.0, abs_tol=1e-9)
            )
        reparsed_rows.append(
            {
                **row,
                **workbook,
                "page_xlsx_display_match": True,
                "page_xlsx_exact_match": all(exact_matches),
            }
        )
    reparsed = pd.DataFrame(reparsed_rows).sort_values("release_month", ignore_index=True)
    stored = pd.read_parquet(
        paths["cbr_household_releases"],
        columns=protocol["inputs"]["cbr_household_releases"]["allowed_columns"],
    )
    try:
        pd.testing.assert_frame_equal(reparsed, stored, check_exact=True)
        checks["cbr_raw_pages_and_xlsx_reparse_exactly"] = True
    except AssertionError:
        checks["cbr_raw_pages_and_xlsx_reparse_exactly"] = False
    coverage = pd.read_parquet(paths["cbr_household_coverage"])
    checks["cbr_coverage_matches_raw_hashes"] = all(
        raw_key[("page", row.release_key)]["sha256"] == row.page_sha256
        and raw_key[("pdf", row.release_key)]["sha256"] == row.pdf_sha256
        and raw_key[("xlsx", row.release_key)]["sha256"] == row.xlsx_sha256
        for row in coverage.itertuples(index=False)
    )
    metadata["cbr_manifest_payload"] = manifest
    metadata["cbr_raw_audit"] = {
        "records": len(raw_records),
        "pages": int(raw_counts.get("page", 0)),
        "pdfs": int(raw_counts.get("pdf", 0)),
        "workbooks": int(raw_counts.get("xlsx", 0)),
        "reparsed_rows": len(reparsed),
    }
    if not all(checks.values()):
        raise ValueError(f"V23 source semantic preflight failed: {checks}")
    return shared_mapper.VerifiedInputs(paths, checks, metadata, parent_protocol)


def normalize_releases(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the target-free release-specific source without market data."""
    required = {
        "release_month",
        "release_key",
        "publication_date",
        "last_updated_date",
        "availability_date",
        "available_at",
        "expected_inflation_chart_exact",
        "expected_inflation_value",
        "observed_inflation_chart_exact",
        "observed_inflation_value",
        "page_url",
        "pdf_url",
        "xlsx_url",
        "retrieved_at_utc",
        "release_specific_current_vintage",
        "modified_after_publication",
        "expected_inflation_exact",
        "observed_inflation_exact",
        "consumer_sentiment_index_exact",
        "page_xlsx_display_match",
        "page_xlsx_exact_match",
    }
    if missing := required - set(frame.columns):
        raise ValueError(f"V23 CBR source lacks columns: {sorted(missing)}")
    releases = frame.loc[:, sorted(required)].copy()
    for column in (
        "release_month",
        "publication_date",
        "last_updated_date",
        "availability_date",
    ):
        releases[column] = pd.to_datetime(releases[column], errors="raise").dt.normalize()
    releases["available_at"] = pd.to_datetime(
        releases["available_at"], errors="raise", utc=True
    )
    releases["retrieved_at_utc"] = pd.to_datetime(
        releases["retrieved_at_utc"], errors="raise", utc=True
    )
    numeric = (
        "expected_inflation_chart_exact",
        "expected_inflation_value",
        "observed_inflation_chart_exact",
        "observed_inflation_value",
        "expected_inflation_exact",
        "observed_inflation_exact",
        "consumer_sentiment_index_exact",
    )
    for column in numeric:
        releases[column] = pd.to_numeric(releases[column], errors="raise").astype(float)
    releases = releases.sort_values("release_month", ignore_index=True)
    expected_available = pd.Series(
        [
            cbr_source.conservative_available_at(
                row.publication_date.date(), row.last_updated_date.date()
            )
            for row in releases.itertuples(index=False)
        ],
        dtype="datetime64[ns, UTC]",
    )
    expected_months = set(cbr_source.EXPECTED_RELEASE_MONTHS)
    display_matches = all(
        releases[f"{component}_value"].eq(
            releases[f"{component}_exact"].map(cbr_source._one_decimal)
        ).all()
        for component in ("expected_inflation", "observed_inflation")
    )
    within_display_precision = all(
        releases[f"{component}_chart_exact"]
        .sub(releases[f"{component}_exact"])
        .abs()
        .le(0.051)
        .all()
        for component in ("expected_inflation", "observed_inflation")
    )
    if (
        len(releases) != 48
        or releases["release_month"].duplicated().any()
        or set(releases["release_month"].dt.date) != expected_months
        or releases["release_month"].min() != pd.Timestamp("2022-01-01")
        or releases["release_month"].max() != pd.Timestamp("2025-12-01")
        or releases[list(numeric)].isna().any().any()
        or not np.isfinite(releases[list(numeric)].to_numpy(dtype=float)).all()
        or not releases["release_specific_current_vintage"].astype(bool).all()
        or releases["retrieved_at_utc"].nunique() != 1
        or not releases["available_at"].reset_index(drop=True).equals(expected_available)
        or releases["available_at"].ge(PROTECTED_FROM).any()
        or not releases["availability_date"].eq(
            releases[["publication_date", "last_updated_date"]].max(axis=1)
        ).all()
        or int(releases["modified_after_publication"].astype(bool).sum()) != 1
        or int(releases["available_at"].duplicated(keep=False).sum()) != 2
        or not releases["page_xlsx_display_match"].astype(bool).all()
        or int(releases["page_xlsx_exact_match"].astype(bool).sum()) != 43
        or not display_matches
        or not within_display_precision
    ):
        raise ValueError("V23 CBR normalized source identity or semantics drifted")
    return releases


def build_source_signals(releases: pd.DataFrame) -> pd.DataFrame:
    """Build the sealed two-series confirmation regime without market data."""
    signals = normalize_releases(releases).copy()
    signals["previous_release_month"] = signals["release_month"].shift(1)
    signals["previous_expected_inflation_exact"] = signals[
        "expected_inflation_exact"
    ].shift(1)
    signals["previous_consumer_sentiment_index_exact"] = signals[
        "consumer_sentiment_index_exact"
    ].shift(1)
    signals["expected_inflation_delta"] = (
        signals["expected_inflation_exact"]
        - signals["previous_expected_inflation_exact"]
    )
    signals["consumer_sentiment_delta"] = (
        signals["consumer_sentiment_index_exact"]
        - signals["previous_consumer_sentiment_index_exact"]
    )
    signals["signal_status"] = np.where(
        signals["previous_release_month"].notna(), "scored", "source_warmup"
    )
    scored_mask = signals["signal_status"].eq("scored")
    risk_on = (
        scored_mask
        & signals["expected_inflation_delta"].lt(0.0)
        & signals["consumer_sentiment_delta"].gt(0.0)
    )
    risk_off = (
        scored_mask
        & signals["expected_inflation_delta"].gt(0.0)
        & signals["consumer_sentiment_delta"].lt(0.0)
    )
    signals["regime"] = np.select(
        [risk_on, risk_off, scored_mask],
        ["risk_on", "risk_off", "mixed_or_zero"],
        default="source_warmup",
    )
    signals["regime_direction"] = np.select(
        [risk_on, risk_off], [1.0, -1.0], default=0.0
    )
    signals["SI_signal"] = -signals["regime_direction"]
    signals["RI_signal"] = signals["regime_direction"]
    signals["BR_signal"] = 0.0
    signals["MIX_signal"] = signals["regime_direction"]
    scored = signals.loc[scored_mask].copy()
    counts_by_year = scored["release_month"].dt.year.value_counts().sort_index().to_dict()
    regime_counts = scored["regime"].value_counts().to_dict()
    nonzero_directions = int(
        scored[[f"{asset}_signal" for asset in v12.ASSETS]].ne(0.0).sum().sum()
    )
    if (
        len(signals) != 48
        or int(signals["signal_status"].eq("source_warmup").sum()) != 1
        or len(scored) != 47
        or counts_by_year != {2022: 11, 2023: 12, 2024: 12, 2025: 12}
        or int(scored["expected_inflation_delta"].gt(0.0).sum()) != 25
        or int(scored["expected_inflation_delta"].lt(0.0).sum()) != 22
        or int(scored["expected_inflation_delta"].eq(0.0).sum()) != 0
        or int(scored["consumer_sentiment_delta"].gt(0.0).sum()) != 24
        or int(scored["consumer_sentiment_delta"].lt(0.0).sum()) != 23
        or int(scored["consumer_sentiment_delta"].eq(0.0).sum()) != 0
        or regime_counts != {"risk_off": 17, "risk_on": 16, "mixed_or_zero": 14}
        or nonzero_directions != 99
        or not scored.loc[scored["regime"].eq("mixed_or_zero"), [
            f"{asset}_signal" for asset in v12.ASSETS
        ]].eq(0.0).all().all()
        or not scored["BR_signal"].eq(0.0).all()
        or not scored["RI_signal"].eq(scored["MIX_signal"]).all()
        or not scored["SI_signal"].eq(-scored["RI_signal"]).all()
        or scored["previous_release_month"].ge(scored["release_month"]).any()
        or signals["available_at"].ge(PROTECTED_FROM).any()
        or not signals["available_at"].is_monotonic_increasing
    ):
        raise ValueError("V23 sealed source-signal counts or semantics drifted")
    return signals


def build_source_decisions(
    signals: pd.DataFrame,
    panel: pd.DataFrame,
    active_map: pd.DataFrame,
) -> shared_mapper.SourceDecisionBuild:
    """Map confirmed household states with the frozen causal V22 state engine."""
    proxy = signals.copy()
    proxy["observation_month"] = proxy["release_month"]
    proxy["bci_value"] = proxy["expected_inflation_exact"]
    proxy["previous_bci_value"] = proxy["previous_expected_inflation_exact"]
    proxy["bci_delta"] = proxy["expected_inflation_delta"]
    proxy["direction"] = proxy["regime_direction"]
    base = shared_mapper.build_source_decisions(proxy, panel, active_map)
    decisions = base.decisions.rename(
        columns={
            "source_observation_month": "source_survey_month",
            "bci_value": "expected_inflation_exact",
            "previous_bci_value": "previous_expected_inflation_exact",
            "bci_delta": "expected_inflation_delta",
            "direction": "regime_direction",
        }
    )
    signal_details = signals.loc[
        signals["signal_status"].eq("scored"),
        [
            "release_month",
            "consumer_sentiment_index_exact",
            "previous_consumer_sentiment_index_exact",
            "consumer_sentiment_delta",
            "regime",
        ],
    ].rename(columns={"release_month": "source_release_month"})
    decisions = decisions.merge(
        signal_details,
        on="source_release_month",
        how="left",
        validate="many_to_one",
    )
    mapped = decisions.loc[decisions["decision_status"].eq("mapped")].copy()
    if mapped["decision_date"].duplicated().any():
        raise ValueError("V23 mapped state decisions are not unique")
    mapped_by_date = mapped.set_index("decision_date")
    weights = base.weights.copy()
    provenance: list[str] = []
    for row in weights.itertuples(index=False):
        state = mapped_by_date.loc[pd.Timestamp(row.decision_date)]
        provenance.append(
            json.dumps(
                {
                    "version": "futures_v23_cbr_household_confirmation_regime_v1",
                    "state_kind": str(state["state_kind"]),
                    "source_release_month": pd.Timestamp(
                        state["source_release_month"]
                    ).date().isoformat(),
                    "source_available_at": pd.Timestamp(
                        state["source_available_at"]
                    ).isoformat(),
                    "source_values": [
                        "exact_release_specific_XLSX_expected_inflation_12m_median",
                        "exact_release_specific_XLSX_consumer_sentiment_index",
                    ],
                    "regime": str(state["regime"]),
                    "contains_prices_returns_targets_or_pnl_from_2026": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    if len(provenance) != len(weights):
        raise ValueError("V23 provenance cardinality drifted")
    weights["provenance"] = provenance
    return shared_mapper.SourceDecisionBuild(
        decisions=decisions,
        weights=weights,
        mapped_state_count=base.mapped_state_count,
        same_session_collisions=base.same_session_collisions,
        expiry_state_count=base.expiry_state_count,
    )


def _scenario_settings(protocol: dict[str, Any]) -> dict[str, dict[str, float]]:
    return shared_mapper._scenario_settings(protocol)


def _annual_return(metrics: dict[str, Any], year: int) -> float:
    return shared_mapper._annual_return(metrics, year)


def _promotion(
    scenario_results: dict[str, dict[str, Any]],
    checks: dict[str, bool],
    scored_releases: int,
    confirmed_releases: int,
    nonzero_asset_directions: int,
) -> dict[str, Any]:
    primary = scenario_results["primary"]
    active_returns = [_annual_return(primary, year) for year in range(2022, 2026)]
    conditions = {
        "every_input_and_temporal_check_true": all(checks.values()),
        "exactly_47_scored_releases_33_confirmations_and_99_nonzero_asset_directions": (
            scored_releases == 47
            and confirmed_releases == 33
            and nonzero_asset_directions == 99
        ),
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
        "primary_maximum_drawdown_at_most_0_20": (
            float(primary["maximum_drawdown"]) <= 0.20
        ),
        "primary_positive_active_years_at_least_3_of_4": (
            all(math.isfinite(value) for value in active_returns)
            and sum(value > 0.0 for value in active_returns) >= 3
        ),
        "doubled_total_return_positive": (
            float(scenario_results["doubled"]["total_return"]) > 0.0
        ),
        "stress_total_return_positive": (
            float(scenario_results["stress"]["total_return"]) > 0.0
        ),
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
    shared_mapper._write_parquet(path, frame)


def _report_text(payload: dict[str, Any]) -> str:
    lines = [
        "# V23 CBR household confirmation regime",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        (
            "Release-specific pages and XLSX files are a current-retrieval development "
            "source, not original publication-time bytes or an independent holdout."
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
            f"- Source/warmup/scored releases: {counts['source_releases']}/"
            f"{counts['source_warmup_releases']}/{counts['scored_source_releases']}",
            f"- Scored releases by year: {counts['scored_releases_by_year']}",
            f"- Expected-inflation delta counts: {counts['expected_inflation_delta_counts']}",
            f"- Consumer-sentiment delta counts: {counts['consumer_sentiment_delta_counts']}",
            f"- Confirmation counts: {counts['regime_counts']}",
            f"- Nonzero asset directions: {counts['nonzero_asset_directions']}",
            f"- Expiry states: {counts['expiry_states']}",
            f"- Same-session state collisions: {counts['same_session_collisions']}",
            f"- Extra roll decisions: {counts['roll_decisions']}",
            f"- Complete dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "Only aligned exact XLSX changes enter the signal; mixed releases go to cash. "
            "Execution begins at the next factual active-contract open.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute one immutable V23 run after every pre-outcome identity check passes."""
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    releases_raw = pd.read_parquet(
        verified.paths["cbr_household_releases"],
        columns=protocol["inputs"]["cbr_household_releases"]["allowed_columns"],
    )
    releases = normalize_releases(releases_raw)
    signals = build_source_signals(releases)

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
    source_build = build_source_decisions(signals, panel, active)
    if source_build.weights.empty:
        raise ValueError("V23 produced no mapped source weights")
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
                execution_atomicity="portfolio",
                terminal_policy="carry",
            ),
        )
        scenario_outputs[name] = result
        scenario_results[name] = v12.scenario_metrics(result, execution_market, settings)

    scored = signals.loc[signals["signal_status"].eq("scored")].copy()
    confirmed = scored.loc[scored["regime"].isin(["risk_on", "risk_off"])].copy()
    scored_by_year = {
        str(key): int(value)
        for key, value in scored["release_month"].dt.year.value_counts().items()
    }
    nonzero_asset_directions = int(
        scored[[f"{asset}_signal" for asset in v12.ASSETS]].ne(0.0).sum().sum()
    )
    mapped = source_build.decisions.loc[
        source_build.decisions["decision_status"].eq("mapped")
    ].copy()
    checks = dict(verified.checks)
    checks["exactly_48_release_specific_source_rows_before_2026"] = bool(
        len(releases) == 48 and releases["available_at"].lt(PROTECTED_FROM).all()
    )
    checks["exact_two_series_sequential_deltas_only"] = bool(
        scored["expected_inflation_delta"].eq(
            scored["expected_inflation_exact"]
            - scored["previous_expected_inflation_exact"]
        ).all()
        and scored["consumer_sentiment_delta"].eq(
            scored["consumer_sentiment_index_exact"]
            - scored["previous_consumer_sentiment_index_exact"]
        ).all()
    )
    checks["strictly_prior_release_history"] = bool(
        scored["previous_release_month"].lt(scored["release_month"]).all()
    )
    checks["mixed_or_zero_releases_are_cash"] = bool(
        scored.loc[
            scored["regime"].eq("mixed_or_zero"),
            [f"{asset}_signal" for asset in v12.ASSETS],
        ].eq(0.0).all().all()
    )
    checks["same_available_at_collision_keeps_latest_release"] = bool(
        source_build.same_session_collisions == 1
        and source_build.decisions.loc[
            source_build.decisions["source_release_month"].eq(pd.Timestamp("2022-09-01"))
            & source_build.decisions["state_kind"].eq("signal"),
            "decision_status",
        ].eq("superseded_same_decision_session").all()
        and source_build.decisions.loc[
            source_build.decisions["source_release_month"].eq(pd.Timestamp("2022-10-01"))
            & source_build.decisions["state_kind"].eq("signal"),
            "decision_status",
        ].eq("mapped").all()
    )
    checks["mapped_states_after_availability"] = bool(
        pd.to_datetime(mapped["state_available_at"], utc=True)
        .le(pd.to_datetime(mapped["decision_at"], utc=True))
        .all()
    )
    expiry = source_build.decisions.loc[source_build.decisions["state_kind"].eq("expiry")]
    checks["expiry_exactly_45_calendar_days"] = bool(
        (
            pd.to_datetime(expiry["desired_decision_date"])
            - pd.to_datetime(expiry["source_available_at"])
            .dt.tz_convert(MOSCOW)
            .dt.tz_localize(None)
            .dt.normalize()
        ).dt.days.eq(EXPIRY_DAYS).all()
        and all(expiry[f"signal_{asset}"].eq(0.0).all() for asset in v12.ASSETS)
    )
    checks["exactly_2_source_only_expiry_states"] = source_build.expiry_state_count == 2
    checks["mapped_weight_sessions_unique"] = not source_build.weights.duplicated(
        ["decision_date", "asset"]
    ).any()
    checks["complete_four_asset_weights"] = bool(
        source_build.weights.groupby("decision_date")["asset"].nunique().eq(4).all()
    )
    checks["source_weight_gross_cap"] = bool(
        source_build.weights.groupby("decision_date")["target_weight"]
        .apply(lambda values: float(values.abs().sum()))
        .le(1.0 + 1e-12)
        .all()
    )
    checks["active_asset_budget_fixed"] = bool(
        source_build.weights.loc[
            source_build.weights["asset"].isin(ACTIVE_ASSETS), "target_weight"
        ].abs().le(RISK_BUDGET + 1e-12).all()
    )
    checks["BR_target_always_zero"] = bool(
        source_build.weights.loc[
            source_build.weights["asset"].eq("BR"), "target_weight"
        ].eq(0.0).all()
    )
    expected_delta_counts = {
        "positive": int(scored["expected_inflation_delta"].gt(0.0).sum()),
        "negative": int(scored["expected_inflation_delta"].lt(0.0).sum()),
        "zero": int(scored["expected_inflation_delta"].eq(0.0).sum()),
    }
    sentiment_delta_counts = {
        "positive": int(scored["consumer_sentiment_delta"].gt(0.0).sum()),
        "negative": int(scored["consumer_sentiment_delta"].lt(0.0).sum()),
        "zero": int(scored["consumer_sentiment_delta"].eq(0.0).sum()),
    }
    regime_counts = {
        str(key): int(value) for key, value in scored["regime"].value_counts().items()
    }
    counts = {
        "source_releases": len(releases),
        "source_warmup_releases": int(signals["signal_status"].eq("source_warmup").sum()),
        "scored_source_releases": len(scored),
        "scored_releases_by_year": scored_by_year,
        "expected_inflation_delta_counts": expected_delta_counts,
        "consumer_sentiment_delta_counts": sentiment_delta_counts,
        "regime_counts": regime_counts,
        "confirmed_releases": len(confirmed),
        "nonzero_asset_directions": nonzero_asset_directions,
        "page_xlsx_display_matches": int(releases["page_xlsx_display_match"].sum()),
        "page_xlsx_exact_matches": int(releases["page_xlsx_exact_match"].sum()),
        "expiry_states": source_build.expiry_state_count,
        "mapped_state_decisions": source_build.mapped_state_count,
        "same_session_collisions": source_build.same_session_collisions,
        "decision_status_counts": {
            str(key): int(value)
            for key, value in source_build.decisions["decision_status"].value_counts().items()
        },
        "source_event_decisions": target_build.weekly_decisions,
        "roll_decisions": target_build.roll_decisions,
        "mapped_target_rows": len(target_build.targets),
        "nonzero_targets": int(target_build.targets["target_weight"].abs().gt(1e-12).sum()),
        "covered_nonzero_targets": int(coverage["execution_dependencies_complete"].sum()),
    }
    promotion = _promotion(
        scenario_results,
        checks,
        len(scored),
        len(confirmed),
        nonzero_asset_directions,
    )
    code_paths = {
        "v23_implementation": Path(__file__).resolve(),
        "cbr_inflation_expectations_source": Path(cbr_source.__file__).resolve(),
        "v22_shared_state_mapper": Path(shared_mapper.__file__).resolve(),
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
        "new_release_specific_information_family": True,
        "original_publication_response_bytes": False,
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
    run_name = f"v23_cbr_household_confirmation_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V23 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        _write_parquet(temporary / "source_releases.parquet", releases)
        _write_parquet(temporary / "source_signals.parquet", signals)
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
            json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
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
        help="External immutable runs root; a unique V23 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
