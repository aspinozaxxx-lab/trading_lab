"""Sealed V21 CBR next-year macro-forecast revision experiment."""

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
from market_lab.futures import cbr_macro_survey_source as cbr_source
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    FuturesPortfolioLedgerResult,
    run_futures_portfolio_ledger,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v21_cbr_macro_revision_breadth.yaml"
CONFIG_SHA256: Final[str] = (
    "5d97fd51050f5e23932fbbaf283d823f7322e8f38d158474b86d61f70fc822bc"
)
OOS_START: Final[pd.Timestamp] = pd.Timestamp("2021-01-01")
OOS_END: Final[pd.Timestamp] = pd.Timestamp("2025-12-31")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
EXPIRY_DAYS: Final[int] = 70
VOLATILITY_LOOKBACK: Final[int] = 60
ANNUALIZATION: Final[int] = 252
VOLATILITY_FLOOR: Final[float] = 0.10
TARGET_VOLATILITY: Final[float] = 0.20
RISK_BUDGET: Final[float] = 0.25
INITIAL_CASH: Final[float] = 1_000_000.0
MAXIMUM_PARTICIPATION: Final[float] = 0.01
USD_INDICATOR: Final[str] = "usd_rub_average"
GDP_INDICATOR: Final[str] = "gdp_yoy_pct"
OIL_PRIORITY: Final[tuple[str, ...]] = (
    "oil_tax_price_usd_bbl",
    "brent_price_usd_bbl",
    "urals_price_usd_bbl",
)
SELECTED_INDICATORS: Final[tuple[str, ...]] = (
    USD_INDICATOR,
    GDP_INDICATOR,
    *OIL_PRIORITY,
)


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
    """Verify the byte seal and every V21 economic invariant."""
    path = config_path.resolve()
    if path != CONFIG_PATH.resolve() or sha256_file(path) != CONFIG_SHA256:
        raise ValueError("sealed V21 protocol byte drift")
    stated = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V21 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V21 protocol must be a mapping")
    information = protocol["information_set"]
    signal = protocol["signal"]
    portfolio = protocol["portfolio"]
    execution = protocol["execution"]
    sealed_counts = signal["sealed_source_counts"]
    if (
        protocol.get("protocol_id") != "futures_v21_cbr_macro_revision_breadth_v1"
        or protocol.get("status") != "sealed_before_any_v21_market_outcome_read"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or protocol.get("parent_v12_protocol_sha256") != v12.CONFIG_SHA256
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or information["source_availability"]
        != "23_59_59_Europe_Moscow_on_last_day_of_month_after_survey_month"
        or information["selected_statistic"] != "median_only"
        or information["selected_forecast_horizon"] != "next_calendar_year_only"
        or information["revision_history"]
        != "immediately_previous_survey_for_exact_same_indicator_and_forecast_year"
        or tuple(information["oil_series_priority"]) != OIL_PRIORITY
        or information["oil_cross_series_bridge"] != "forbidden"
        or information["missing_component_target"]
        != "zero_without_risk_reallocation"
        or signal["transform"] != "sign_only_in_negative_zero_positive"
        or signal["magnitude_scaling"] != "none"
        or signal["threshold"] != "none"
        or int(signal["expiry_calendar_days"]) != EXPIRY_DAYS
        or int(sealed_counts["causally_available_releases"]) != 36
        or int(sealed_counts["warmup_releases"]) != 1
        or int(sealed_counts["scored_releases"]) != 35
        or {int(key): int(value) for key, value in sealed_counts["scored_by_survey_year"].items()}
        != {2021: 4, 2022: 8, 2023: 8, 2024: 8, 2025: 7}
        or int(sealed_counts["nonzero_asset_revisions"]) != 102
        or float(portfolio["equal_absolute_risk_budget_each_asset"]) != RISK_BUDGET
        or portfolio["unused_component_budget_reallocated"] is not False
        or int(portfolio["daily_volatility_lookback_sessions"])
        != VOLATILITY_LOOKBACK
        or int(portfolio["annualization_sessions"]) != ANNUALIZATION
        or float(portfolio["annualized_volatility_floor"]) != VOLATILITY_FLOOR
        or float(portfolio["annual_target_volatility_each_asset"])
        != TARGET_VOLATILITY
        or float(portfolio["maximum_absolute_weight_each_asset"]) != RISK_BUDGET
        or float(portfolio["gross_cap"]) != 1.0
        or execution["execution_atomicity"] != "portfolio"
        or float(execution["initial_cash_rub"]) != INITIAL_CASH
        or float(execution["maximum_participation"]) != MAXIMUM_PARTICIPATION
        or float(execution["maximum_gross_notional_multiple"]) != 1.0
        or float(execution["initial_margin_buffer_multiple"]) != 2.0
    ):
        raise ValueError("sealed V21 protocol invariants were weakened")
    return protocol


@dataclass(frozen=True, slots=True)
class VerifiedInputs:
    paths: dict[str, Path]
    checks: dict[str, bool]
    metadata: dict[str, Any]
    parent_protocol: dict[str, Any]


def verify_inputs(protocol: dict[str, Any]) -> VerifiedInputs:
    """Verify official source artifacts and frozen parent identities before prices."""
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
        "cbr_macro_forecasts",
        "cbr_macro_manifest",
        "cbr_macro_coverage",
        "cbr_macro_raw_workbook",
        "cbr_macro_raw_page",
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
        if name in {"cbr_macro_forecasts", "cbr_macro_coverage"} and exists:
            parquet = pq.ParquetFile(path)
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
            metadata[name]["rows"] = parquet.metadata.num_rows
            metadata[name]["columns"] = parquet.schema_arrow.names
            if name == "cbr_macro_forecasts":
                checks[f"{name}_schema"] = tuple(parquet.schema_arrow.names) == tuple(
                    declaration["allowed_columns"]
                )
    if not all(checks.values()):
        raise ValueError(f"V21 byte/schema preflight failed: {checks}")

    manifest = json.loads(paths["cbr_macro_manifest"].read_text(encoding="utf-8-sig"))
    manifest_payload = dict(manifest)
    stated_payload_hash = manifest_payload.pop("manifest_payload_sha256")
    artifacts = manifest["artifacts"]
    coverage = manifest["coverage"]
    temporal = manifest["temporal_semantics"]
    quality = manifest["source_quality"]
    checks["cbr_manifest_payload_identity"] = (
        _sha256_bytes(_canonical_json(manifest_payload)) == stated_payload_hash
    )
    checks["cbr_manifest_artifact_identities"] = bool(
        artifacts["processed"]["sha256"]
        == protocol["inputs"]["cbr_macro_forecasts"]["sha256"]
        and int(artifacts["processed"]["rows"]) == 11787
        and artifacts["coverage"]["sha256"]
        == protocol["inputs"]["cbr_macro_coverage"]["sha256"]
        and int(artifacts["coverage"]["rows"]) == 423
        and artifacts["raw_workbook"]["sha256"]
        == protocol["inputs"]["cbr_macro_raw_workbook"]["sha256"]
        and artifacts["raw_page"]["sha256"]
        == protocol["inputs"]["cbr_macro_raw_page"]["sha256"]
    )
    checks["cbr_manifest_coverage"] = bool(
        manifest["source_id"]
        == "official-cbr-macro-survey-current-vintage-2021-2025-v1"
        and int(coverage["records"]) == 11787
        and int(coverage["survey_months"]) == 37
        and coverage["survey_months_by_year"]
        == {"2021": 5, "2022": 8, "2023": 8, "2024": 8, "2025": 8}
        and coverage["minimum_survey_month"] == "2021-05-01"
        and coverage["maximum_survey_month"] == "2025-12-01"
        and int(coverage["survey_months_available_before_protected_boundary"]) == 36
    )
    checks["cbr_current_vintage_target_free"] = bool(
        temporal["current_vintage_historical_record"] is True
        and temporal["contains_prices_returns_targets_labels_or_pnl"] is False
        and temporal["missing_workbook_cells_are_not_zero"] is True
        and temporal["availability_is_deliberately_later_than_typical_publication"] is True
    )
    checks["cbr_development_only_semantics"] = bool(
        temporal["development_backtest_admissible"] is True
        and temporal["independent_confirmation_without_forward_vintage_collection"] is False
        and temporal["original_historical_workbook_vintages_available"] is False
        and temporal["historical_content_immutability_cryptographically_proved"] is False
    )
    checks["cbr_source_quality"] = bool(
        quality["official_page_points_to_expected_workbook"] is True
        and quality["all_17_indicator_sheets_present"] is True
        and quality["survey_columns_strictly_chronological"] is True
        and int(quality["duplicate_economic_keys"]) == 0
        and quality["future_survey_columns_filtered_from_processed_data"] is True
    )
    with gzip.open(paths["cbr_macro_raw_page"], "rb") as stream:
        raw_page = stream.read()
    checks["cbr_raw_page_links_expected_workbook"] = (
        cbr_source.workbook_url_from_page(raw_page) == manifest["workbook_url"]
    )
    raw_workbook = paths["cbr_macro_raw_workbook"].read_bytes()
    reparsed = cbr_source.parse_macro_survey_workbook(
        raw_workbook,
        retrieved_at_utc=manifest["fetched_at_utc"],
    )
    stored = pd.read_parquet(
        paths["cbr_macro_forecasts"],
        columns=protocol["inputs"]["cbr_macro_forecasts"]["allowed_columns"],
    )
    try:
        pd.testing.assert_frame_equal(reparsed, stored, check_exact=True)
        checks["cbr_raw_workbook_reparses_exactly"] = True
    except AssertionError:
        checks["cbr_raw_workbook_reparses_exactly"] = False
    metadata["cbr_manifest_payload"] = manifest
    metadata["cbr_raw_audit"] = {
        "page_uncompressed_bytes": len(raw_page),
        "workbook_bytes": len(raw_workbook),
        "reparsed_rows": len(reparsed),
    }
    if not all(checks.values()):
        raise ValueError(f"V21 source semantic preflight failed: {checks}")
    return VerifiedInputs(
        paths=paths,
        checks=checks,
        metadata=metadata,
        parent_protocol=parent_protocol,
    )


def normalize_forecasts(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the observed-only current-vintage corpus without market data."""
    required = {
        "survey_month",
        "survey_label",
        "available_at",
        "indicator",
        "indicator_name",
        "unit",
        "statistic",
        "source_sheet",
        "source_cell",
        "source_url",
        "retrieved_at_utc",
        "current_vintage",
        "forecast_period",
        "forecast_year",
        "value",
    }
    if missing := required - set(frame.columns):
        raise ValueError(f"V21 CBR source lacks columns: {sorted(missing)}")
    forecasts = frame.loc[:, sorted(required)].copy()
    forecasts["survey_month"] = pd.to_datetime(
        forecasts["survey_month"], errors="raise"
    ).dt.normalize()
    forecasts["forecast_period"] = pd.to_datetime(
        forecasts["forecast_period"], errors="coerce"
    ).dt.normalize()
    forecasts["available_at"] = pd.to_datetime(
        forecasts["available_at"], errors="raise", utc=True
    )
    forecasts["retrieved_at_utc"] = pd.to_datetime(
        forecasts["retrieved_at_utc"], errors="raise", utc=True
    )
    forecasts["forecast_year"] = pd.array(forecasts["forecast_year"], dtype="Int64")
    forecasts["value"] = pd.array(
        pd.to_numeric(forecasts["value"], errors="raise"), dtype="Float64"
    )
    key = ["survey_month", "indicator", "statistic", "forecast_period"]
    months = forecasts[["survey_month", "available_at"]].drop_duplicates()
    expected_availability = pd.to_datetime(
        months["survey_month"].dt.date.map(cbr_source.conservative_available_at),
        utc=True,
    )
    indicator_set = {spec.indicator for spec in cbr_source.INDICATOR_SPECS}
    if (
        len(forecasts) != 11787
        or forecasts.duplicated(key).any()
        or forecasts["value"].isna().any()
        or not np.isfinite(forecasts["value"].to_numpy(dtype=float)).all()
        or not forecasts["current_vintage"].astype(bool).all()
        or forecasts["survey_month"].min() != pd.Timestamp("2021-05-01")
        or forecasts["survey_month"].max() != pd.Timestamp("2025-12-01")
        or len(months) != 37
        or int(months["available_at"].lt(PROTECTED_FROM).sum()) != 36
        or not months["available_at"].reset_index(drop=True).equals(
            pd.Series(expected_availability).reset_index(drop=True)
        )
        or set(forecasts["indicator"].astype(str)) != indicator_set
        or not forecasts["source_url"].astype("string").eq(cbr_source.WORKBOOK_URL).all()
        or forecasts["retrieved_at_utc"].nunique() != 1
    ):
        raise ValueError("V21 CBR normalized source identity or semantics drifted")
    return forecasts.sort_values(
        ["survey_month", "indicator", "statistic", "forecast_period"],
        kind="mergesort",
        na_position="last",
        ignore_index=True,
    )


def _next_year_revisions(forecasts: pd.DataFrame) -> pd.DataFrame:
    """Compute revisions only within an exact indicator and target-year history."""
    selected = forecasts.loc[
        forecasts["statistic"].eq("median")
        & forecasts["indicator"].isin(SELECTED_INDICATORS)
        & forecasts["forecast_year"].notna()
    ].copy()
    selected = selected.sort_values(
        ["indicator", "forecast_year", "survey_month"], kind="mergesort"
    )
    groups = selected.groupby(["indicator", "forecast_year"], observed=True, sort=False)
    selected["previous_value"] = groups["value"].shift(1)
    selected["previous_survey_month"] = groups["survey_month"].shift(1)
    selected["revision"] = selected["value"] - selected["previous_value"]
    current_year = selected["survey_month"].dt.year + 1
    output = selected.loc[
        selected["forecast_year"].eq(current_year)
        & selected["available_at"].lt(PROTECTED_FROM)
    ].copy()
    causal = output["previous_survey_month"].notna()
    if output.loc[causal, "previous_survey_month"].ge(
        output.loc[causal, "survey_month"]
    ).any():
        raise ValueError("V21 revision history includes current or future survey")
    return output.sort_values(
        ["survey_month", "indicator"], kind="mergesort", ignore_index=True
    )


def _component(revisions: pd.DataFrame, indicator: str, month: pd.Timestamp) -> pd.Series | None:
    rows = revisions.loc[
        revisions["indicator"].eq(indicator) & revisions["survey_month"].eq(month)
    ]
    if rows.empty:
        return None
    if len(rows) != 1:
        raise ValueError("V21 component has duplicate next-year revision")
    return rows.iloc[0]


def _revision_sign(value: object) -> float:
    if pd.isna(value):
        return 0.0
    return float(np.sign(float(value)))


def _assemble_signal_rows(revisions: pd.DataFrame) -> pd.DataFrame:
    usd = revisions.loc[revisions["indicator"].eq(USD_INDICATOR)]
    gdp = revisions.loc[revisions["indicator"].eq(GDP_INDICATOR)]
    months = sorted(set(usd["survey_month"]) | set(gdp["survey_month"]))
    rows: list[dict[str, Any]] = []
    for month in months:
        usd_row = _component(revisions, USD_INDICATOR, pd.Timestamp(month))
        gdp_row = _component(revisions, GDP_INDICATOR, pd.Timestamp(month))
        if usd_row is None or gdp_row is None:
            raise ValueError("V21 USD/RUB and GDP release calendars diverged")
        if pd.Timestamp(usd_row["available_at"]) != pd.Timestamp(gdp_row["available_at"]):
            raise ValueError("V21 release components have inconsistent availability")
        oil_row: pd.Series | None = None
        for indicator in OIL_PRIORITY:
            candidate = _component(revisions, indicator, pd.Timestamp(month))
            if candidate is not None and pd.notna(candidate["revision"]):
                oil_row = candidate
                break
        usd_revision = usd_row["revision"]
        gdp_revision = gdp_row["revision"]
        scored = pd.notna(usd_revision) and pd.notna(gdp_revision)
        oil_revision = np.nan if oil_row is None else float(oil_row["revision"])
        rows.append(
            {
                "survey_month": pd.Timestamp(month),
                "available_at": pd.Timestamp(usd_row["available_at"]),
                "forecast_year": int(usd_row["forecast_year"]),
                "usd_rub_value": float(usd_row["value"]),
                "usd_rub_previous_value": (
                    np.nan
                    if pd.isna(usd_row["previous_value"])
                    else float(usd_row["previous_value"])
                ),
                "usd_rub_previous_survey_month": usd_row["previous_survey_month"],
                "usd_rub_revision": (
                    np.nan if pd.isna(usd_revision) else float(usd_revision)
                ),
                "gdp_value": float(gdp_row["value"]),
                "gdp_previous_value": (
                    np.nan
                    if pd.isna(gdp_row["previous_value"])
                    else float(gdp_row["previous_value"])
                ),
                "gdp_previous_survey_month": gdp_row["previous_survey_month"],
                "gdp_revision": np.nan if pd.isna(gdp_revision) else float(gdp_revision),
                "oil_indicator": None if oil_row is None else str(oil_row["indicator"]),
                "oil_value": np.nan if oil_row is None else float(oil_row["value"]),
                "oil_previous_value": (
                    np.nan if oil_row is None else float(oil_row["previous_value"])
                ),
                "oil_previous_survey_month": (
                    pd.NaT if oil_row is None else oil_row["previous_survey_month"]
                ),
                "oil_revision": oil_revision,
                "SI_signal": _revision_sign(usd_revision) if scored else 0.0,
                "RI_signal": _revision_sign(gdp_revision) if scored else 0.0,
                "BR_signal": _revision_sign(oil_revision) if scored else 0.0,
                "MIX_signal": _revision_sign(gdp_revision) if scored else 0.0,
                "oil_component_status": (
                    "same_series_revision_available"
                    if oil_row is not None
                    else "component_unavailable_target_zero"
                ),
                "signal_status": "scored" if scored else "source_warmup",
            }
        )
    return pd.DataFrame(rows).sort_values("survey_month", ignore_index=True)


def build_source_signals(forecasts: pd.DataFrame) -> pd.DataFrame:
    """Build the sealed direct component signs using source values only."""
    source = normalize_forecasts(forecasts)
    revisions = _next_year_revisions(source)
    signals = _assemble_signal_rows(revisions)
    scored = signals.loc[signals["signal_status"].eq("scored")].copy()
    counts_by_year = scored["survey_month"].dt.year.value_counts().sort_index().to_dict()
    nonzero_asset_revisions = int(
        scored[[f"{asset}_signal" for asset in v12.ASSETS]].abs().gt(0.0).sum().sum()
    )
    oil_counts = scored["oil_indicator"].value_counts(dropna=False).to_dict()
    if (
        len(signals) != 36
        or int(signals["signal_status"].eq("source_warmup").sum()) != 1
        or len(scored) != 35
        or counts_by_year != {2021: 4, 2022: 8, 2023: 8, 2024: 8, 2025: 7}
        or nonzero_asset_revisions != 102
        or int(scored["usd_rub_revision"].ne(0.0).sum()) != 34
        or int(scored["gdp_revision"].ne(0.0).sum()) != 28
        or int(scored["oil_revision"].fillna(0.0).ne(0.0).sum()) != 12
        or oil_counts
        != {
            None: 16,
            "brent_price_usd_bbl": 9,
            "urals_price_usd_bbl": 5,
            "oil_tax_price_usd_bbl": 5,
        }
        or signals["available_at"].ge(PROTECTED_FROM).any()
    ):
        raise ValueError("V21 sealed source-signal counts or semantics drifted")
    for column in ("usd_rub_previous_survey_month", "gdp_previous_survey_month"):
        if scored[column].ge(scored["survey_month"]).any():
            raise ValueError("V21 revision is not strictly prior-survey causal")
    oil_available = scored["oil_indicator"].notna()
    if scored.loc[oil_available, "oil_previous_survey_month"].ge(
        scored.loc[oil_available, "survey_month"]
    ).any():
        raise ValueError("V21 oil revision is not strictly same-series prior causal")
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
        "available_at", ignore_index=True
    )
    rows: list[dict[str, Any]] = []
    for index, signal in scored.iterrows():
        desired = _available_local_date(pd.Timestamp(signal["available_at"]))
        common = {
            "source_survey_month": pd.Timestamp(signal["survey_month"]),
            "source_available_at": pd.Timestamp(signal["available_at"]),
            "forecast_year": int(signal["forecast_year"]),
            "usd_rub_revision": float(signal["usd_rub_revision"]),
            "gdp_revision": float(signal["gdp_revision"]),
            "oil_indicator": signal["oil_indicator"],
            "oil_revision": (
                np.nan if pd.isna(signal["oil_revision"]) else float(signal["oil_revision"])
            ),
            "oil_component_status": signal["oil_component_status"],
        }
        rows.append(
            {
                **common,
                "state_kind": "signal",
                "desired_decision_date": desired,
                "state_available_at": pd.Timestamp(signal["available_at"]),
                **{f"signal_{asset}": float(signal[f"{asset}_signal"]) for asset in v12.ASSETS},
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
    """Map independent release states to next-open targets with fixed risk budgets."""
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
            raise ValueError("V21 source state mapped before it became available")
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
        ["decision_date", "desired_decision_date", "state_precedence", "source_survey_month"],
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
                "version": "futures_v21_cbr_macro_revision_breadth_v1",
                "state_kind": row.state_kind,
                "source_survey_month": row.source_survey_month.date().isoformat(),
                "source_available_at": row.source_available_at.isoformat(),
                "state_available_at": row.state_available_at.isoformat(),
                "forecast_year": int(row.forecast_year),
                "oil_indicator": row.oil_indicator,
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
            raise ValueError("V21 weights are not complete four-asset snapshots")
        if weights.groupby("decision_date")["target_weight"].apply(
            lambda values: float(values.abs().sum())
        ).gt(1.0 + 1e-12).any():
            raise ValueError("V21 source weights breach the sealed gross cap")
        if weights["target_weight"].abs().gt(RISK_BUDGET + 1e-12).any():
            raise ValueError("V21 component weight breaches its non-reallocated budget")
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
        raise ValueError("V21 cost scenarios drifted from the seal")
    return output


def _promotion(
    scenario_results: dict[str, dict[str, Any]],
    checks: dict[str, bool],
    signal_counts_by_year: dict[str, int],
    nonzero_asset_revisions: int,
) -> dict[str, Any]:
    primary = scenario_results["primary"]
    conditions = {
        "every_input_and_temporal_check_true": all(checks.values()),
        "exactly_35_scored_releases_and_at_least_4_each_survey_year": (
            sum(signal_counts_by_year.values()) == 35
            and all(signal_counts_by_year.get(str(year), 0) >= 4 for year in range(2021, 2026))
        ),
        "at_least_100_nonzero_asset_revisions": nonzero_asset_revisions >= 100,
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
        "# V21 CBR next-year macro revision breadth",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        (
            "The official workbook is a current-vintage development source, not original "
            "historical release vintages or an independent holdout."
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
            f"- Source forecast records: {counts['source_forecasts']}",
            f"- Available/warmup/scored releases: {counts['available_source_releases']}/"
            f"{counts['source_warmup_releases']}/{counts['scored_source_releases']}",
            f"- Scored releases by survey year: {counts['scored_releases_by_survey_year']}",
            f"- Nonzero asset revisions: {counts['nonzero_asset_revisions']}",
            f"- Component counts: {counts['component_counts']}",
            f"- Expiry states: {counts['expiry_states']}",
            f"- Same-session state collisions: {counts['same_session_collisions']}",
            f"- Extra roll decisions: {counts['roll_decisions']}",
            f"- Complete dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "Every survey is admitted only at the conservative month-end timestamp and "
            "can fill only at the next factual active-contract open. Revisions never "
            "cross indicator, target year, or oil-series boundaries.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute one immutable V21 run after every identity check passes."""
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    forecasts_raw = pd.read_parquet(
        verified.paths["cbr_macro_forecasts"],
        columns=protocol["inputs"]["cbr_macro_forecasts"]["allowed_columns"],
    )
    forecasts = normalize_forecasts(forecasts_raw)
    signals = build_source_signals(forecasts)
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
        raise ValueError("V21 produced no mapped source weights")
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
    signal_counts_by_year = {
        str(key): int(value)
        for key, value in scored["survey_month"].dt.year.value_counts().items()
    }
    nonzero_asset_revisions = int(
        scored[[f"{asset}_signal" for asset in v12.ASSETS]].abs().gt(0.0).sum().sum()
    )
    mapped = source_build.decisions.loc[
        source_build.decisions["decision_status"].eq("mapped")
    ].copy()
    checks = dict(verified.checks)
    release_availability = forecasts[["survey_month", "available_at"]].drop_duplicates()
    checks["exactly_36_source_releases_available_before_2026"] = bool(
        release_availability["available_at"].lt(PROTECTED_FROM).sum() == 36
        and release_availability["available_at"].ge(PROTECTED_FROM).sum() == 1
    )
    checks["next_year_only"] = bool(
        signals["forecast_year"].eq(signals["survey_month"].dt.year + 1).all()
    )
    checks["same_target_prior_revisions_only"] = bool(
        scored["usd_rub_previous_survey_month"].lt(scored["survey_month"]).all()
        and scored["gdp_previous_survey_month"].lt(scored["survey_month"]).all()
    )
    checks["mapped_states_after_availability"] = bool(
        pd.to_datetime(mapped["state_available_at"], utc=True)
        .le(pd.to_datetime(mapped["decision_at"], utc=True))
        .all()
    )
    expiry = source_build.decisions.loc[source_build.decisions["state_kind"].eq("expiry")]
    checks["expiry_exactly_70_calendar_days"] = bool(
        (
            pd.to_datetime(expiry["desired_decision_date"])
            - pd.to_datetime(expiry["source_available_at"])
            .dt.tz_convert(MOSCOW)
            .dt.tz_localize(None)
            .dt.normalize()
        ).dt.days.eq(EXPIRY_DAYS).all()
        and all(expiry[f"signal_{asset}"].eq(0.0).all() for asset in v12.ASSETS)
    )
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
    checks["component_budget_not_reallocated"] = bool(
        source_build.weights["target_weight"].abs().le(RISK_BUDGET + 1e-12).all()
    )
    component_counts = {
        "SI_nonzero": int(scored["SI_signal"].ne(0.0).sum()),
        "RI_nonzero": int(scored["RI_signal"].ne(0.0).sum()),
        "BR_nonzero": int(scored["BR_signal"].ne(0.0).sum()),
        "MIX_nonzero": int(scored["MIX_signal"].ne(0.0).sum()),
        "oil_missing": int(scored["oil_indicator"].isna().sum()),
    }
    counts = {
        "source_forecasts": len(forecasts),
        "available_source_releases": len(signals),
        "source_warmup_releases": int(signals["signal_status"].eq("source_warmup").sum()),
        "scored_source_releases": len(scored),
        "scored_releases_by_survey_year": signal_counts_by_year,
        "nonzero_asset_revisions": nonzero_asset_revisions,
        "component_counts": component_counts,
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
        signal_counts_by_year,
        nonzero_asset_revisions,
    )
    code_paths = {
        "v21_implementation": Path(__file__).resolve(),
        "cbr_macro_source": Path(cbr_source.__file__).resolve(),
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
    run_name = f"v21_cbr_macro_revision_breadth_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V21 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        _write_parquet(temporary / "source_forecasts.parquet", forecasts)
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
        help="External immutable runs root; a unique V21 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
