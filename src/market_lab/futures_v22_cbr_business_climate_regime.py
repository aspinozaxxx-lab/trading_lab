"""Sealed V22 Bank of Russia Business Climate Index regime experiment."""

from __future__ import annotations

import argparse
import base64
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
from market_lab import futures_v21_cbr_macro_revision_breadth as infrastructure
from market_lab.futures import cbr_business_climate_source as cbr_source
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    FuturesPortfolioLedgerResult,
    run_futures_portfolio_ledger,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = (
    PROJECT_ROOT / "configs/futures_v22_cbr_business_climate_regime.yaml"
)
CONFIG_SHA256: Final[str] = (
    "97b2aa74416eae4ebbce28d018a460f98ade4993cfb086487d28515976c18fbe"
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
    ).encode()


def _json_safe(value: Any) -> Any:
    return v12._json_safe(value)


def load_protocol(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Verify the byte seal and every V22 economic invariant."""
    path = config_path.resolve()
    if path != CONFIG_PATH.resolve() or sha256_file(path) != CONFIG_SHA256:
        raise ValueError("sealed V22 protocol byte drift")
    stated = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V22 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V22 protocol must be a mapping")
    information = protocol["information_set"]
    signal = protocol["signal"]
    portfolio = protocol["portfolio"]
    execution = protocol["execution"]
    counts = signal["sealed_source_counts"]
    if (
        protocol.get("protocol_id") != "futures_v22_cbr_business_climate_regime_v1"
        or protocol.get("status") != "sealed_before_any_v22_market_outcome_read"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or protocol.get("source_commit_before_protocol") != "7fee819"
        or protocol.get("parent_v12_protocol_sha256") != v12.CONFIG_SHA256
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or information["source_availability"]
        != "23_59_59_Europe_Moscow_on_max_publication_and_last_update_date"
        or information["selected_value"]
        != "printed_one_decimal_composite_BCI_endpoint_only"
        or information["chart_exact_decimals"] != "audit_only_forbidden_in_signal"
        or information["component_values"] != "archived_but_forbidden_in_v22_signal"
        or information["same_available_at_collision"] != "keep_latest_release_month"
        or signal["transform"] != "sign_only_in_negative_zero_positive"
        or signal["magnitude_scaling"] != "none"
        or signal["threshold"] != "none"
        or int(signal["expiry_calendar_days"]) != EXPIRY_DAYS
        or int(counts["releases"]) != 44
        or int(counts["warmup_releases"]) != 1
        or int(counts["scored_releases"]) != 43
        or {int(key): int(value) for key, value in counts["scored_by_release_year"].items()}
        != {2022: 7, 2023: 12, 2024: 12, 2025: 12}
        or int(counts["positive_BCI_deltas"]) != 21
        or int(counts["negative_BCI_deltas"]) != 18
        or int(counts["zero_BCI_deltas"]) != 4
        or int(counts["nonzero_asset_directions"]) != 117
        or int(counts["source_only_expiry_states"]) != 2
        or int(counts["prior_month_observation_endpoints"]) != 3
        or int(counts["modified_after_publication_pages"]) != 1
        or int(counts["same_available_at_collision_rows"]) != 2
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
        raise ValueError("sealed V22 protocol invariants were weakened")
    return protocol


@dataclass(frozen=True, slots=True)
class VerifiedInputs:
    paths: dict[str, Path]
    checks: dict[str, bool]
    metadata: dict[str, Any]
    parent_protocol: dict[str, Any]


def _decode_raw_archive(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                record = json.loads(line)
                content = base64.b64decode(record["content"], validate=True)
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"invalid CBR raw record at line {line_number}") from error
            if (
                record.get("content_encoding") != "base64"
                or len(content) != int(record["bytes"])
                or _sha256_bytes(content) != record["sha256"]
            ):
                raise ValueError(f"CBR raw record identity drift at line {line_number}")
            records.append({**record, "decoded_content": content})
    return records


def verify_inputs(protocol: dict[str, Any]) -> VerifiedInputs:
    """Verify source bytes, raw reparse, and frozen parent identities before prices."""
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
        "cbr_bci_releases",
        "cbr_bci_manifest",
        "cbr_bci_coverage",
        "cbr_bci_raw_responses",
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
        if name in {"cbr_bci_releases", "cbr_bci_coverage"} and exists:
            parquet = pq.ParquetFile(path)
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
            checks[f"{name}_schema"] = tuple(parquet.schema_arrow.names) == tuple(
                declaration["allowed_columns"]
            )
            metadata[name]["rows"] = parquet.metadata.num_rows
            metadata[name]["columns"] = parquet.schema_arrow.names
    if not all(checks.values()):
        raise ValueError(f"V22 byte/schema preflight failed: {checks}")

    manifest = json.loads(paths["cbr_bci_manifest"].read_text(encoding="utf-8-sig"))
    manifest_payload = dict(manifest)
    stated_payload_hash = manifest_payload.pop("manifest_payload_sha256")
    artifacts = manifest["artifacts"]
    coverage_manifest = manifest["coverage"]
    temporal = manifest["temporal_semantics"]
    values = manifest["value_semantics"]
    quality = manifest["source_quality"]
    checks["cbr_manifest_payload_identity"] = (
        _sha256_bytes(_canonical_json(manifest_payload)) == stated_payload_hash
    )
    checks["cbr_manifest_artifact_identities"] = bool(
        artifacts["processed"]["sha256"]
        == protocol["inputs"]["cbr_bci_releases"]["sha256"]
        and int(artifacts["processed"]["rows"]) == 44
        and artifacts["coverage"]["sha256"]
        == protocol["inputs"]["cbr_bci_coverage"]["sha256"]
        and int(artifacts["coverage"]["rows"]) == 44
        and artifacts["raw_responses"]["sha256"]
        == protocol["inputs"]["cbr_bci_raw_responses"]["sha256"]
        and int(artifacts["raw_responses"]["records"]) == 90
    )
    checks["cbr_manifest_coverage"] = bool(
        manifest["source_id"]
        == "official-cbr-business-climate-release-pages-2022-2025-v1"
        and int(coverage_manifest["release_pages"]) == 44
        and coverage_manifest["release_pages_by_year"]
        == {"2022": 8, "2023": 12, "2024": 12, "2025": 12}
        and coverage_manifest["minimum_release_month"] == "2022-05-01"
        and coverage_manifest["maximum_release_month"] == "2025-12-01"
        and int(coverage_manifest["prior_month_observation_count"]) == 3
        and int(coverage_manifest["modified_after_publication_count"]) == 1
        and int(coverage_manifest["rows_in_availability_collisions"]) == 2
        and coverage_manifest["sequential_bci_delta_counts"]
        == {"positive": 21, "negative": 18, "zero": 4}
    )
    checks["cbr_release_specific_target_free"] = bool(
        temporal["release_specific_pages_retrieved_currently"] is True
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
    checks["cbr_printed_value_semantics"] = bool(
        values["strategy_admissible_value"]
        == "one-decimal label printed on each release-specific chart endpoint"
        and values["chart_exact_value_retained_for_source_audit_only"] is True
        and values["latest_current_vintage_history_not_used"] is True
        and values["components"] == ["bci", "current_assessments", "expectations"]
    )
    checks["cbr_source_quality"] = bool(
        quality["archive_contains_every_expected_month"] is True
        and quality["archive_index_unchanged_during_collection"] is True
        and quality["every_page_has_one_unique_release_pdf"] is True
        and quality["every_release_point_is_labeled"] is True
        and quality["every_chart_has_no_non_null_future_point"] is True
        and int(quality["duplicate_release_months"]) == 0
    )

    raw_records = _decode_raw_archive(paths["cbr_bci_raw_responses"])
    raw_counts = pd.Series([record["kind"] for record in raw_records]).value_counts()
    raw_key = {
        (str(record["kind"]), str(record["identity"])): record
        for record in raw_records
    }
    checks["cbr_raw_record_counts"] = bool(
        len(raw_records) == 90
        and len(raw_key) == 90
        and raw_counts.to_dict() == {"page": 44, "pdf": 44, "archive": 2}
    )
    initial = raw_key[("archive", "initial")]["decoded_content"]
    final = raw_key[("archive", "final")]["decoded_content"]
    initial_releases = cbr_source.discover_release_links(initial)
    final_releases = cbr_source.discover_release_links(final)
    checks["cbr_raw_archive_indexes_match"] = initial_releases == final_releases
    reparsed_rows: list[dict[str, object]] = []
    for release in initial_releases:
        page_record = raw_key[("page", release.release_key)]
        pdf_record = raw_key[("pdf", release.release_key)]
        if not pdf_record["decoded_content"].startswith(b"%PDF-"):
            raise ValueError(f"V22 raw PDF is invalid for {release.release_key}")
        reparsed_rows.append(
            cbr_source.parse_release_page(
                page_record["decoded_content"],
                release=release,
                retrieved_at_utc=manifest["fetched_at_utc"],
            )
        )
    reparsed = pd.DataFrame(reparsed_rows).sort_values("release_month", ignore_index=True)
    stored = pd.read_parquet(
        paths["cbr_bci_releases"],
        columns=protocol["inputs"]["cbr_bci_releases"]["allowed_columns"],
    )
    try:
        pd.testing.assert_frame_equal(reparsed, stored, check_exact=True)
        checks["cbr_raw_pages_reparse_exactly"] = True
    except AssertionError:
        checks["cbr_raw_pages_reparse_exactly"] = False
    coverage = pd.read_parquet(paths["cbr_bci_coverage"])
    checks["cbr_coverage_matches_raw_hashes"] = all(
        raw_key[("page", row.release_key)]["sha256"] == row.page_sha256
        and raw_key[("pdf", row.release_key)]["sha256"] == row.pdf_sha256
        for row in coverage.itertuples(index=False)
    )
    metadata["cbr_manifest_payload"] = manifest
    metadata["cbr_raw_audit"] = {
        "records": len(raw_records),
        "pages": int(raw_counts.get("page", 0)),
        "pdfs": int(raw_counts.get("pdf", 0)),
        "reparsed_rows": len(reparsed),
    }
    if not all(checks.values()):
        raise ValueError(f"V22 source semantic preflight failed: {checks}")
    return VerifiedInputs(paths, checks, metadata, parent_protocol)


def normalize_releases(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the release-specific source without market data."""
    required = {
        "release_month",
        "release_key",
        "publication_date",
        "last_updated_date",
        "availability_date",
        "available_at",
        "observation_month",
        "bci_value",
        "bci_chart_exact",
        "current_assessments_value",
        "current_assessments_chart_exact",
        "expectations_value",
        "expectations_chart_exact",
        "page_url",
        "pdf_url",
        "retrieved_at_utc",
        "release_specific_current_vintage",
        "modified_after_publication",
    }
    if missing := required - set(frame.columns):
        raise ValueError(f"V22 CBR source lacks columns: {sorted(missing)}")
    releases = frame.loc[:, sorted(required)].copy()
    for column in (
        "release_month",
        "publication_date",
        "last_updated_date",
        "availability_date",
        "observation_month",
    ):
        releases[column] = pd.to_datetime(releases[column], errors="raise").dt.normalize()
    releases["available_at"] = pd.to_datetime(
        releases["available_at"], errors="raise", utc=True
    )
    releases["retrieved_at_utc"] = pd.to_datetime(
        releases["retrieved_at_utc"], errors="raise", utc=True
    )
    numeric = (
        "bci_value",
        "bci_chart_exact",
        "current_assessments_value",
        "current_assessments_chart_exact",
        "expectations_value",
        "expectations_chart_exact",
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
    month_lag = (
        (releases["release_month"].dt.year - releases["observation_month"].dt.year) * 12
        + releases["release_month"].dt.month
        - releases["observation_month"].dt.month
    )
    printed_columns = (
        "bci_value",
        "current_assessments_value",
        "expectations_value",
    )
    exact_pairs = (
        ("bci_value", "bci_chart_exact"),
        ("current_assessments_value", "current_assessments_chart_exact"),
        ("expectations_value", "expectations_chart_exact"),
    )
    expected_months = set(cbr_source.EXPECTED_RELEASE_MONTHS)
    if (
        len(releases) != 44
        or releases["release_month"].duplicated().any()
        or set(releases["release_month"].dt.date) != expected_months
        or releases["release_month"].min() != pd.Timestamp("2022-05-01")
        or releases["release_month"].max() != pd.Timestamp("2025-12-01")
        or releases[list(numeric)].isna().any().any()
        or not np.isfinite(releases[list(numeric)].to_numpy(dtype=float)).all()
        or not releases["release_specific_current_vintage"].astype(bool).all()
        or releases["retrieved_at_utc"].nunique() != 1
        or not releases["available_at"].reset_index(drop=True).equals(expected_available)
        or releases["available_at"].ge(PROTECTED_FROM).any()
        or not month_lag.isin([0, 1]).all()
        or int(month_lag.eq(1).sum()) != 3
        or int(releases["modified_after_publication"].astype(bool).sum()) != 1
        or int(releases["available_at"].duplicated(keep=False).sum()) != 2
        or not releases["availability_date"].eq(
            releases[["publication_date", "last_updated_date"]].max(axis=1)
        ).all()
        or not all(
            np.allclose(releases[column] * 10.0, np.round(releases[column] * 10.0))
            for column in printed_columns
        )
        or not all(
            releases[printed].sub(releases[exact]).abs().le(0.051).all()
            for printed, exact in exact_pairs
        )
    ):
        raise ValueError("V22 CBR normalized source identity or semantics drifted")
    return releases


def build_source_signals(releases: pd.DataFrame) -> pd.DataFrame:
    """Build the sealed sign of sequential printed composite BCI changes."""
    signals = normalize_releases(releases).copy()
    signals["previous_release_month"] = signals["release_month"].shift(1)
    signals["previous_bci_value"] = signals["bci_value"].shift(1)
    signals["bci_delta"] = signals["bci_value"] - signals["previous_bci_value"]
    signals["direction"] = np.sign(signals["bci_delta"]).fillna(0.0).astype(float)
    signals["signal_status"] = np.where(
        signals["previous_release_month"].notna(), "scored", "source_warmup"
    )
    scored_mask = signals["signal_status"].eq("scored")
    signals["SI_signal"] = np.where(scored_mask, -signals["direction"], 0.0)
    signals["RI_signal"] = np.where(scored_mask, signals["direction"], 0.0)
    signals["BR_signal"] = 0.0
    signals["MIX_signal"] = np.where(scored_mask, signals["direction"], 0.0)
    scored = signals.loc[scored_mask].copy()
    counts_by_year = scored["release_month"].dt.year.value_counts().sort_index().to_dict()
    nonzero_directions = int(
        scored[[f"{asset}_signal" for asset in v12.ASSETS]].ne(0.0).sum().sum()
    )
    if (
        len(signals) != 44
        or int(signals["signal_status"].eq("source_warmup").sum()) != 1
        or len(scored) != 43
        or counts_by_year != {2022: 7, 2023: 12, 2024: 12, 2025: 12}
        or int(scored["bci_delta"].gt(0.0).sum()) != 21
        or int(scored["bci_delta"].lt(0.0).sum()) != 18
        or int(scored["bci_delta"].eq(0.0).sum()) != 4
        or nonzero_directions != 117
        or not scored["BR_signal"].eq(0.0).all()
        or not scored["RI_signal"].eq(scored["MIX_signal"]).all()
        or not scored["SI_signal"].eq(-scored["RI_signal"]).all()
        or scored["previous_release_month"].ge(scored["release_month"]).any()
        or signals["available_at"].ge(PROTECTED_FROM).any()
        or not signals["available_at"].is_monotonic_increasing
    ):
        raise ValueError("V22 sealed source-signal counts or semantics drifted")
    return signals


@dataclass(frozen=True, slots=True)
class SourceDecisionBuild:
    decisions: pd.DataFrame
    weights: pd.DataFrame
    mapped_state_count: int
    same_session_collisions: int
    expiry_state_count: int


def _decision_at(decision_date: pd.Timestamp) -> pd.Timestamp:
    return (
        decision_date.tz_localize(MOSCOW)
        + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).tz_convert("UTC")


def _available_local_date(available_at: pd.Timestamp) -> pd.Timestamp:
    return available_at.tz_convert(MOSCOW).tz_localize(None).normalize()


def _state_rows(signals: pd.DataFrame) -> list[dict[str, Any]]:
    scored = signals.loc[signals["signal_status"].eq("scored")].sort_values(
        ["available_at", "release_month"], ignore_index=True
    )
    rows: list[dict[str, Any]] = []
    for index, signal in scored.iterrows():
        desired = _available_local_date(pd.Timestamp(signal["available_at"]))
        common = {
            "source_release_month": pd.Timestamp(signal["release_month"]),
            "source_observation_month": pd.Timestamp(signal["observation_month"]),
            "source_available_at": pd.Timestamp(signal["available_at"]),
            "bci_value": float(signal["bci_value"]),
            "previous_bci_value": float(signal["previous_bci_value"]),
            "bci_delta": float(signal["bci_delta"]),
            "direction": float(signal["direction"]),
        }
        rows.append(
            {
                **common,
                "state_kind": "signal",
                "desired_decision_date": desired,
                "state_available_at": pd.Timestamp(signal["available_at"]),
                **{
                    f"signal_{asset}": float(signal[f"{asset}_signal"])
                    for asset in v12.ASSETS
                },
            }
        )
        expiry = desired + pd.Timedelta(days=EXPIRY_DAYS)
        next_desired = (
            _available_local_date(pd.Timestamp(scored.iloc[index + 1]["available_at"]))
            if index + 1 < len(scored)
            else None
        )
        if next_desired is None or next_desired > expiry:
            rows.append(
                {
                    **common,
                    "state_kind": "expiry",
                    "desired_decision_date": expiry,
                    "state_available_at": _decision_at(expiry),
                    **{f"signal_{asset}": 0.0 for asset in v12.ASSETS},
                }
            )
    return rows


def build_source_decisions(
    signals: pd.DataFrame,
    panel: pd.DataFrame,
    active_map: pd.DataFrame,
) -> SourceDecisionBuild:
    """Map release states to next-open targets with three fixed risk budgets."""
    market = v12.normalize_signal_panel(panel)
    volatilities: dict[str, pd.Series] = {}
    for asset in v12.ASSETS:
        closes = market.loc[market["asset"].eq(asset)].set_index("trade_date")["close"]
        volatilities[asset] = (
            np.log(closes)
            .diff()
            .rolling(VOLATILITY_LOOKBACK, min_periods=VOLATILITY_LOOKBACK)
            .std(ddof=1)
            * math.sqrt(float(ANNUALIZATION))
        )
    active = v12.normalize_active_map(active_map)
    active_dates = pd.DatetimeIndex(active["decision_date"].drop_duplicates().sort_values())
    state_rows = _state_rows(signals)
    decisions: list[dict[str, Any]] = []
    for state in state_rows:
        desired = pd.Timestamp(state["desired_decision_date"])
        location = int(active_dates.searchsorted(desired, side="left"))
        if location >= len(active_dates):
            decisions.append(
                {
                    **state,
                    "decision_date": pd.NaT,
                    "decision_at": pd.NaT,
                    **{f"annualized_{asset}_volatility": np.nan for asset in v12.ASSETS},
                    **{f"target_{asset}": np.nan for asset in v12.ASSETS},
                    "decision_status": "no_future_active_decision_session",
                }
            )
            continue
        decision_date = pd.Timestamp(active_dates[location])
        decision_at = _decision_at(decision_date)
        if pd.Timestamp(state["state_available_at"]) > decision_at:
            raise ValueError("V22 source state mapped before it became available")
        volatility_values = {
            asset: volatilities[asset].get(decision_date, np.nan) for asset in v12.ASSETS
        }
        targets: dict[str, float] = {}
        missing_volatility = False
        for asset in v12.ASSETS:
            component_signal = float(state[f"signal_{asset}"])
            if component_signal == 0.0:
                targets[asset] = 0.0
                continue
            volatility = volatility_values[asset]
            if pd.isna(volatility) or not math.isfinite(float(volatility)):
                missing_volatility = True
                targets[asset] = np.nan
                continue
            risk_scale = min(
                1.0,
                TARGET_VOLATILITY / max(float(volatility), VOLATILITY_FLOOR),
            )
            targets[asset] = component_signal * RISK_BUDGET * risk_scale
        decisions.append(
            {
                **state,
                "decision_date": decision_date,
                "decision_at": decision_at,
                **{
                    f"annualized_{asset}_volatility": value
                    for asset, value in volatility_values.items()
                },
                **{f"target_{asset}": value for asset, value in targets.items()},
                "decision_status": (
                    "missing_prior_60_session_volatility" if missing_volatility else "mapped"
                ),
            }
        )
    frame = pd.DataFrame(decisions)
    frame["state_precedence"] = frame["state_kind"].map({"expiry": 0, "signal": 1})
    frame = frame.sort_values(
        [
            "decision_date",
            "desired_decision_date",
            "state_precedence",
            "source_release_month",
        ],
        kind="mergesort",
        na_position="last",
        ignore_index=True,
    )
    mapped = frame.loc[frame["decision_status"].eq("mapped")].copy()
    duplicate = mapped.duplicated("decision_date", keep="last")
    collisions = int(duplicate.sum())
    if collisions:
        frame.loc[mapped.index[duplicate], "decision_status"] = (
            "superseded_same_decision_session"
        )
        mapped = mapped.loc[~duplicate].copy()
    weight_rows: list[dict[str, Any]] = []
    for row in mapped.itertuples(index=False):
        provenance = json.dumps(
            {
                "version": "futures_v22_cbr_business_climate_regime_v1",
                "state_kind": row.state_kind,
                "source_release_month": row.source_release_month.date().isoformat(),
                "source_observation_month": row.source_observation_month.date().isoformat(),
                "source_available_at": row.source_available_at.isoformat(),
                "state_available_at": row.state_available_at.isoformat(),
                "source_value": "printed_one_decimal_composite_BCI_endpoint",
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
                    "target_weight": float(getattr(row, f"target_{asset}")),
                    "provenance": provenance,
                }
            )
    weights = pd.DataFrame(weight_rows)
    if not weights.empty:
        if weights.groupby("decision_date")["asset"].nunique().ne(len(v12.ASSETS)).any():
            raise ValueError("V22 weights are not complete four-asset snapshots")
        if weights.groupby("decision_date")["target_weight"].apply(
            lambda values: float(values.abs().sum())
        ).gt(1.0 + 1e-12).any():
            raise ValueError("V22 source weights breach the sealed gross cap")
        if weights.loc[weights["asset"].isin(ACTIVE_ASSETS), "target_weight"].abs().gt(
            RISK_BUDGET + 1e-12
        ).any():
            raise ValueError("V22 active asset breaches its fixed risk budget")
        if not weights.loc[weights["asset"].eq("BR"), "target_weight"].eq(0.0).all():
            raise ValueError("V22 BR target is not identically zero")
    return SourceDecisionBuild(
        decisions=frame.drop(columns="state_precedence"),
        weights=weights.sort_values(
            ["decision_date", "asset"], kind="mergesort", ignore_index=True
        ),
        mapped_state_count=len(mapped),
        same_session_collisions=collisions,
        expiry_state_count=sum(row["state_kind"] == "expiry" for row in state_rows),
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
        raise ValueError("V22 cost scenarios drifted from the seal")
    return output


def _annual_return(metrics: dict[str, Any], year: int) -> float:
    annual = metrics["annual_returns"]
    value = annual.get(str(year), annual.get(year))
    if value is None:
        return float("nan")
    return float(value)


def _promotion(
    scenario_results: dict[str, dict[str, Any]],
    checks: dict[str, bool],
    scored_releases: int,
    nonzero_asset_directions: int,
) -> dict[str, Any]:
    primary = scenario_results["primary"]
    active_returns = [_annual_return(primary, year) for year in range(2022, 2026)]
    conditions = {
        "every_input_and_temporal_check_true": all(checks.values()),
        "exactly_43_scored_releases_and_117_nonzero_asset_directions": (
            scored_releases == 43 and nonzero_asset_directions == 117
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
    frame.to_parquet(path, index=False, compression="zstd")


def _report_text(payload: dict[str, Any]) -> str:
    lines = [
        "# V22 CBR Business Climate Index regime",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        (
            "The official release-specific pages are a current retrieval development "
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
            f"- BCI delta counts: {counts['bci_delta_counts']}",
            f"- Nonzero asset directions: {counts['nonzero_asset_directions']}",
            f"- Expiry states: {counts['expiry_states']}",
            f"- Same-session state collisions: {counts['same_session_collisions']}",
            f"- Extra roll decisions: {counts['roll_decisions']}",
            f"- Complete dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "Only the printed one-decimal composite BCI endpoint enters the signal. "
            "Execution begins at the next factual active-contract open.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute one immutable V22 run after every identity check passes."""
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    releases_raw = pd.read_parquet(
        verified.paths["cbr_bci_releases"],
        columns=protocol["inputs"]["cbr_bci_releases"]["allowed_columns"],
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
        raise ValueError("V22 produced no mapped source weights")
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
    checks["exactly_44_release_specific_source_rows_before_2026"] = bool(
        len(releases) == 44 and releases["available_at"].lt(PROTECTED_FROM).all()
    )
    checks["printed_BCI_delta_only"] = bool(
        scored["bci_delta"].eq(scored["bci_value"] - scored["previous_bci_value"]).all()
    )
    checks["strictly_prior_release_history"] = bool(
        scored["previous_release_month"].lt(scored["release_month"]).all()
    )
    checks["same_available_at_collision_keeps_latest_release"] = bool(
        source_build.same_session_collisions == 1
        and source_build.decisions.loc[
            source_build.decisions["source_release_month"].eq(pd.Timestamp("2022-10-01")),
            "decision_status",
        ].eq("superseded_same_decision_session").all()
        and source_build.decisions.loc[
            source_build.decisions["source_release_month"].eq(pd.Timestamp("2022-11-01"))
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
    delta_counts = {
        "positive": int(scored["bci_delta"].gt(0.0).sum()),
        "negative": int(scored["bci_delta"].lt(0.0).sum()),
        "zero": int(scored["bci_delta"].eq(0.0).sum()),
    }
    counts = {
        "source_releases": len(releases),
        "source_warmup_releases": int(signals["signal_status"].eq("source_warmup").sum()),
        "scored_source_releases": len(scored),
        "scored_releases_by_year": scored_by_year,
        "bci_delta_counts": delta_counts,
        "nonzero_asset_directions": nonzero_asset_directions,
        "prior_month_observation_endpoints": int(
            releases["observation_month"].lt(releases["release_month"]).sum()
        ),
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
        nonzero_asset_directions,
    )
    code_paths = {
        "v22_implementation": Path(__file__).resolve(),
        "cbr_business_climate_source": Path(cbr_source.__file__).resolve(),
        "v21_shared_infrastructure": Path(infrastructure.__file__).resolve(),
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
    run_name = f"v22_cbr_business_climate_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V22 run already exists: {final}")
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
        help="External immutable runs root; a unique V22 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
