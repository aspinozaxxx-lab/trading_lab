"""Sealed V20 Minfin OFZ-PD prior-rank demand-strength experiment."""

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
from market_lab.futures.portfolio_ledger import (
    FuturesPortfolioLedgerConfig,
    FuturesPortfolioLedgerResult,
    run_futures_portfolio_ledger,
)

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
CONFIG_PATH: Final[Path] = PROJECT_ROOT / "configs/futures_v20_minfin_ofz_demand_strength.yaml"
CONFIG_SHA256: Final[str] = (
    "788fadbd9c499483c560488a5a3d9d2e95f7e95496e5736ed4465eca889341ed"
)
MINFIN_MANIFEST_SHA256: Final[str] = (
    "c6fcf390b728ebfd55c32b3a20880908bd4eb5ebfcff18bcaf150f568b607d52"
)
MINFIN_RAW_SHA256: Final[str] = (
    "f56af34a15a284e74f8364daf3abd6ae7d2978a01b22443e33ced079d72133c7"
)
OOS_START: Final[pd.Timestamp] = pd.Timestamp("2021-01-01")
OOS_END: Final[pd.Timestamp] = pd.Timestamp("2025-12-31")
PROTECTED_FROM: Final[pd.Timestamp] = pd.Timestamp("2026-01-01T00:00:00Z")
MOSCOW: Final[ZoneInfo] = ZoneInfo("Europe/Moscow")
FIXED_COUPON: Final[str] = "ПД"
RANK_WINDOW: Final[int] = 26
MINIMUM_HISTORY: Final[int] = 13
EXPIRY_DAYS: Final[int] = 7
VOLATILITY_LOOKBACK: Final[int] = 60
ANNUALIZATION: Final[int] = 252
VOLATILITY_FLOOR: Final[float] = 0.10
TARGET_VOLATILITY: Final[float] = 0.20
RISK_BUDGET: Final[float] = 1.0 / 3.0
INITIAL_CASH: Final[float] = 1_000_000.0
MAXIMUM_PARTICIPATION: Final[float] = 0.01
ECONOMIC_SIGNS: Final[dict[str, float]] = {
    "SI": -1.0,
    "RI": 1.0,
    "BR": 0.0,
    "MIX": 1.0,
}


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
    """Verify the byte seal and every V20 economic invariant before outcomes."""
    path = config_path.resolve()
    if path != CONFIG_PATH.resolve() or sha256_file(path) != CONFIG_SHA256:
        raise ValueError("sealed V20 protocol byte drift")
    stated = path.with_suffix(".sha256").read_text(encoding="utf-8-sig").split()[0]
    if stated != CONFIG_SHA256:
        raise ValueError("V20 sidecar does not match the code-pinned protocol seal")
    protocol = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(protocol, dict):
        raise TypeError("sealed V20 protocol must be a mapping")
    signal = protocol["signal"]
    portfolio = protocol["portfolio"]
    execution = protocol["execution"]
    information = protocol["information_set"]
    if (
        protocol.get("protocol_id") != "futures_v20_minfin_ofz_demand_strength_v1"
        or protocol.get("status") != "sealed_before_any_v20_market_outcome_read"
        or protocol.get("sealed_before_outcomes") is not True
        or protocol.get("live_trading_allowed") is not False
        or protocol.get("parent_v12_protocol_sha256") != v12.CONFIG_SHA256
        or str(protocol["dates"]["forbidden_from"]) != "2026-01-01"
        or information["source_availability"]
        != "23_59_59_Europe_Moscow_on_printed_publication_day"
        or information["event_filter"] != "successful_primary_OFZ_PD_only"
        or information["causal_rank_history"]
        != "previous_26_successful_OFZ_PD_auction_days_only"
        or int(information["causal_rank_minimum_history"]) != MINIMUM_HISTORY
        or information["same_decision_session_collision"]
        != "keep_latest_causally_available_signal_or_expiry"
        or int(signal["rank_window_prior_auction_days"]) != RANK_WINDOW
        or int(signal["minimum_prior_auction_days"]) != MINIMUM_HISTORY
        or signal["score_formula"]
        != "bid_to_cover_percentile_plus_placed_volume_percentile_minus_one"
        or signal["score_threshold"] != "none"
        or signal["failed_auction_imputation"] != "none_excluded"
        or int(signal["expiry_calendar_days"]) != EXPIRY_DAYS
        or {str(key): int(value) for key, value in signal["economic_signs"].items()}
        != {"RI": 1, "MIX": 1, "SI": -1, "BR": 0}
        or float(portfolio["equal_absolute_risk_budget_each_active_asset"])
        != RISK_BUDGET
        or int(portfolio["daily_volatility_lookback_sessions"]) != VOLATILITY_LOOKBACK
        or int(portfolio["annualization_sessions"]) != ANNUALIZATION
        or float(portfolio["annualized_volatility_floor"]) != VOLATILITY_FLOOR
        or float(portfolio["annual_target_volatility_each_active_asset"])
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
        raise ValueError("sealed V20 protocol invariants were weakened")
    return protocol


@dataclass(frozen=True, slots=True)
class VerifiedInputs:
    paths: dict[str, Path]
    checks: dict[str, bool]
    metadata: dict[str, Any]
    parent_protocol: dict[str, Any]


def _verify_raw_archive(path: Path, expected_records: int) -> dict[str, int]:
    records = 0
    content_bytes = 0
    with gzip.open(path, "rb") as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            content = base64.b64decode(record["content"], validate=True)
            if len(content) != int(record["bytes"]):
                raise ValueError("V20 Minfin raw record byte count drifted")
            if _sha256_bytes(content) != record["sha256"]:
                raise ValueError("V20 Minfin raw record content hash drifted")
            if not str(record["url"]).startswith("https://minfin.gov.ru/"):
                raise ValueError("V20 Minfin raw record escaped official host")
            records += 1
            content_bytes += len(content)
    if records != expected_records:
        raise ValueError("V20 Minfin raw record count drifted")
    return {"records": records, "uncompressed_content_bytes": content_bytes}


def verify_inputs(protocol: dict[str, Any]) -> VerifiedInputs:
    """Verify source-only Minfin artifacts and frozen parent identities before prices."""
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
        "minfin_ofz_auction_events",
        "minfin_ofz_manifest",
        "minfin_ofz_coverage",
        "minfin_ofz_raw",
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
        if name in {"minfin_ofz_auction_events", "minfin_ofz_coverage"} and exists:
            parquet = pq.ParquetFile(path)
            checks[f"{name}_rows"] = parquet.metadata.num_rows == int(declaration["rows"])
            metadata[name]["rows"] = parquet.metadata.num_rows
            metadata[name]["columns"] = parquet.schema_arrow.names
            if name == "minfin_ofz_auction_events":
                checks[f"{name}_schema"] = set(declaration["allowed_columns"]) <= set(
                    parquet.schema_arrow.names
                )
    if not all(checks.values()):
        raise ValueError(f"V20 byte/schema preflight failed: {checks}")

    manifest = json.loads(paths["minfin_ofz_manifest"].read_text(encoding="utf-8-sig"))
    manifest_payload = dict(manifest)
    stated_payload_hash = manifest_payload.pop("manifest_payload_sha256")
    artifacts = manifest["artifacts"]
    coverage = manifest["coverage"]
    temporal = manifest["temporal_semantics"]
    quality = manifest["source_quality"]
    checks["minfin_manifest_identity"] = (
        sha256_file(paths["minfin_ofz_manifest"]) == MINFIN_MANIFEST_SHA256
    )
    checks["minfin_manifest_payload_identity"] = (
        _sha256_bytes(_canonical_json(manifest_payload)) == stated_payload_hash
    )
    checks["minfin_manifest_processed_identity"] = (
        artifacts["processed"]["sha256"]
        == protocol["inputs"]["minfin_ofz_auction_events"]["sha256"]
        and int(artifacts["processed"]["rows"]) == 410
    )
    checks["minfin_manifest_coverage_identity"] = (
        artifacts["coverage"]["sha256"]
        == protocol["inputs"]["minfin_ofz_coverage"]["sha256"]
        and int(artifacts["coverage"]["rows"]) == 410
    )
    checks["minfin_manifest_raw_identity"] = (
        artifacts["raw_pages"]["sha256"]
        == protocol["inputs"]["minfin_ofz_raw"]["sha256"]
        == MINFIN_RAW_SHA256
        and int(artifacts["raw_pages"]["records"]) == 490
    )
    checks["minfin_coverage_identity"] = (
        manifest["source_id"]
        == "official-minfin-ofz-auction-results-current-vintage-2021-2025-v2"
        and int(coverage["source_interval_cards"]) == 410
        and int(coverage["primary_result_rows"]) == 364
        and coverage["primary_result_rows_by_auction_year"]
        == {"2021": 80, "2022": 34, "2023": 88, "2024": 69, "2025": 93}
        and coverage["event_kind_counts"]
        == {
            "auction_announcement": 1,
            "correction": 7,
            "failed_or_cancelled": 30,
            "primary_result": 364,
            "supplemental_result": 8,
        }
        and coverage["minimum_publication_date"] == "2021-01-13"
        and coverage["maximum_publication_date"] == "2025-12-24"
        and int(coverage["maximum_publication_lag_days"]) == 0
    )
    checks["minfin_current_vintage_target_free"] = (
        temporal["current_vintage_historical_record"] is True
        and temporal["contains_prices_returns_targets_labels_or_pnl"] is False
        and temporal["date_only_source_uses_conservative_day_end"] is True
    )
    checks["minfin_development_only_semantics"] = (
        temporal["development_backtest_admissible"] is True
        and temporal["independent_confirmation_without_forward_vintage_collection"] is False
        and temporal["original_historical_response_bytes_available"] is False
        and temporal["historical_content_immutability_cryptographically_proved"] is False
        and temporal["last_modified_used_for_availability"] is False
    )
    checks["minfin_source_quality"] = (
        quality["archive_reverse_chronology_verified"] is True
        and quality["first_page_result_index_unchanged_during_discovery"] is True
        and quality["every_interval_card_classified"] is True
        and quality["every_primary_result_required_field_complete"] is True
        and quality["bid_to_cover_is_demand_divided_by_placed_volume"] is True
    )
    raw_audit = _verify_raw_archive(paths["minfin_ofz_raw"], 490)
    checks["minfin_raw_transitive_records"] = raw_audit["records"] == 490
    metadata["minfin_manifest_payload"] = manifest
    metadata["minfin_raw_audit"] = raw_audit
    if not all(checks.values()):
        raise ValueError(f"V20 source semantic preflight failed: {checks}")
    return VerifiedInputs(
        paths=paths,
        checks=checks,
        metadata=metadata,
        parent_protocol=parent_protocol,
    )


def _end_of_moscow_day(values: pd.Series) -> pd.Series:
    return (
        values.dt.tz_localize(MOSCOW) + pd.Timedelta(hours=23, minutes=59, seconds=59)
    ).dt.tz_convert("UTC")


def normalize_events(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the sealed current-vintage event corpus without reading market data."""
    required = {
        "document_id",
        "event_kind",
        "publication_date",
        "modified_date",
        "available_at",
        "auction_date",
        "issue_code",
        "ofz_type",
        "demand_volume_bln_rub",
        "placed_volume_bln_rub",
        "bid_to_cover",
        "source_url",
        "raw_sha256",
        "current_vintage_historical_record",
        "original_publication_bytes_available",
        "historical_content_immutability_cryptographically_proved",
    }
    if missing := required - set(frame.columns):
        raise ValueError(f"V20 Minfin source lacks columns: {sorted(missing)}")
    events = frame.loc[:, sorted(required)].copy()
    for column in ("publication_date", "modified_date", "auction_date"):
        events[column] = pd.to_datetime(events[column], errors="coerce").dt.normalize()
    events["available_at"] = pd.to_datetime(events["available_at"], errors="raise", utc=True)
    numeric = ("demand_volume_bln_rub", "placed_volume_bln_rub", "bid_to_cover")
    for column in numeric:
        events[column] = pd.to_numeric(events[column], errors="coerce")
    if len(events) != 410 or events["document_id"].duplicated().any():
        raise ValueError("V20 Minfin row identity or document uniqueness drifted")
    if (
        events["publication_date"].min() != pd.Timestamp("2021-01-13")
        or events["publication_date"].max() != pd.Timestamp("2025-12-24")
    ):
        raise ValueError("V20 Minfin publication boundaries drifted")
    if not events["available_at"].equals(_end_of_moscow_day(events["publication_date"])):
        raise ValueError("V20 Minfin conservative availability drifted")
    if events["available_at"].ge(PROTECTED_FROM).any():
        raise ValueError("V20 Minfin source touches protected 2026+")
    if (
        not events["current_vintage_historical_record"].astype(bool).all()
        or events["original_publication_bytes_available"].astype(bool).any()
        or events["historical_content_immutability_cryptographically_proved"]
        .astype(bool)
        .any()
    ):
        raise ValueError("V20 Minfin current-vintage semantics drifted")
    if not events["source_url"].astype("string").str.startswith(
        "https://minfin.gov.ru/"
    ).all():
        raise ValueError("V20 Minfin source URL escaped official host")
    if not events["raw_sha256"].astype("string").str.fullmatch(r"[0-9a-f]{64}").all():
        raise ValueError("V20 Minfin detail hash is malformed")
    expected_counts = {
        "primary_result": 364,
        "failed_or_cancelled": 30,
        "supplemental_result": 8,
        "correction": 7,
        "auction_announcement": 1,
    }
    if events["event_kind"].value_counts().to_dict() != expected_counts:
        raise ValueError("V20 Minfin event-kind counts drifted")
    primary = events["event_kind"].eq("primary_result")
    if not events.loc[primary, "auction_date"].equals(
        events.loc[primary, "publication_date"]
    ):
        raise ValueError("V20 primary auction/publication dates drifted")
    selected = primary & events["ofz_type"].eq(FIXED_COUPON)
    if int(selected.sum()) != 283:
        raise ValueError("V20 successful OFZ-PD row count drifted")
    values = events.loc[selected, [*numeric]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0.0).any():
        raise ValueError("V20 successful OFZ-PD demand fields must be positive and finite")
    recomputed = (
        events.loc[selected, "demand_volume_bln_rub"]
        / events.loc[selected, "placed_volume_bln_rub"]
    )
    if not np.allclose(
        recomputed.to_numpy(),
        events.loc[selected, "bid_to_cover"].to_numpy(),
        rtol=1e-12,
        atol=1e-12,
    ):
        raise ValueError("V20 source bid-to-cover identity drifted")
    return events.sort_values(
        ["publication_date", "document_id"], kind="mergesort", ignore_index=True
    )


def _empirical_percentile(history: np.ndarray, value: float) -> float:
    if history.ndim != 1 or len(history) < 1 or not np.isfinite(history).all():
        raise ValueError("V20 empirical percentile requires finite prior history")
    return float(np.mean(history < value) + 0.5 * np.mean(history == value))


def build_source_signals(events: pd.DataFrame) -> pd.DataFrame:
    """Aggregate OFZ-PD auction days and score them against prior source values only."""
    source = normalize_events(events)
    selected = source.loc[
        source["event_kind"].eq("primary_result") & source["ofz_type"].eq(FIXED_COUPON)
    ].copy()
    rows: list[dict[str, Any]] = []
    for (publication, available), group in selected.groupby(
        ["publication_date", "available_at"], sort=True
    ):
        demand = float(group["demand_volume_bln_rub"].sum())
        placed = float(group["placed_volume_bln_rub"].sum())
        rows.append(
            {
                "publication_date": pd.Timestamp(publication),
                "available_at": pd.Timestamp(available),
                "result_count": len(group),
                "document_ids": json.dumps(
                    sorted(int(value) for value in group["document_id"]),
                    separators=(",", ":"),
                ),
                "total_demand_bln_rub": demand,
                "total_placed_bln_rub": placed,
                "same_day_bid_to_cover": demand / placed,
            }
        )
    signals = pd.DataFrame(rows).sort_values("publication_date", ignore_index=True)
    if len(signals) != 179 or signals["publication_date"].duplicated().any():
        raise ValueError("V20 aggregated OFZ-PD auction-day identity drifted")
    bid_history: list[float] = []
    placed_history: list[float] = []
    scored: list[dict[str, Any]] = []
    for row in signals.itertuples(index=False):
        prior_bid = np.asarray(bid_history[-RANK_WINDOW:], dtype=float)
        prior_placed = np.asarray(placed_history[-RANK_WINDOW:], dtype=float)
        common = row._asdict()
        common["history_count"] = len(prior_bid)
        common["history_min_publication_date"] = (
            signals.iloc[max(0, len(bid_history) - RANK_WINDOW)]["publication_date"]
            if bid_history
            else pd.NaT
        )
        common["history_max_publication_date"] = (
            signals.iloc[len(bid_history) - 1]["publication_date"]
            if bid_history
            else pd.NaT
        )
        if len(prior_bid) < MINIMUM_HISTORY:
            common.update(
                {
                    "bid_to_cover_percentile": np.nan,
                    "placed_volume_percentile": np.nan,
                    "score": np.nan,
                    "signal_status": "source_warmup",
                }
            )
        else:
            bid_percentile = _empirical_percentile(
                prior_bid, float(row.same_day_bid_to_cover)
            )
            placed_percentile = _empirical_percentile(
                prior_placed, float(row.total_placed_bln_rub)
            )
            common.update(
                {
                    "bid_to_cover_percentile": bid_percentile,
                    "placed_volume_percentile": placed_percentile,
                    "score": bid_percentile + placed_percentile - 1.0,
                    "signal_status": "scored",
                }
            )
        scored.append(common)
        bid_history.append(float(row.same_day_bid_to_cover))
        placed_history.append(float(row.total_placed_bln_rub))
    output = pd.DataFrame(scored)
    scored_mask = output["signal_status"].eq("scored")
    values = output.loc[scored_mask, "score"]
    counts = {
        "positive": int(values.gt(0.0).sum()),
        "negative": int(values.lt(0.0).sum()),
        "zero": int(values.eq(0.0).sum()),
    }
    year_counts = (
        output.loc[scored_mask, "publication_date"].dt.year.value_counts().sort_index().to_dict()
    )
    if (
        int(scored_mask.sum()) != 166
        or counts != {"positive": 82, "negative": 76, "zero": 8}
        or year_counts != {2021: 28, 2022: 13, 2023: 40, 2024: 37, 2025: 48}
        or values.abs().gt(1.0 + 1e-12).any()
    ):
        raise ValueError("V20 sealed source-signal counts or bounds drifted")
    causal = output.loc[scored_mask]
    if causal["history_max_publication_date"].ge(causal["publication_date"]).any():
        raise ValueError("V20 rank history includes current or future auction day")
    return output


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


def _state_rows(signals: pd.DataFrame) -> list[dict[str, Any]]:
    scored = signals.loc[signals["signal_status"].eq("scored")].reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for index, row in scored.iterrows():
        source_date = pd.Timestamp(row["publication_date"])
        signal_common = {
            "source_publication_date": source_date,
            "source_available_at": pd.Timestamp(row["available_at"]),
            "total_demand_bln_rub": float(row["total_demand_bln_rub"]),
            "total_placed_bln_rub": float(row["total_placed_bln_rub"]),
            "same_day_bid_to_cover": float(row["same_day_bid_to_cover"]),
            "bid_to_cover_percentile": float(row["bid_to_cover_percentile"]),
            "placed_volume_percentile": float(row["placed_volume_percentile"]),
            "history_count": int(row["history_count"]),
            "document_ids": row["document_ids"],
        }
        rows.append(
            {
                **signal_common,
                "state_kind": "signal",
                "desired_decision_date": source_date,
                "state_available_at": pd.Timestamp(row["available_at"]),
                "score": float(row["score"]),
            }
        )
        expiry = source_date + pd.Timedelta(days=EXPIRY_DAYS)
        next_source = (
            pd.Timestamp(scored.iloc[index + 1]["publication_date"])
            if index + 1 < len(scored)
            else None
        )
        if next_source is None or next_source > expiry:
            rows.append(
                {
                    **signal_common,
                    "state_kind": "expiry",
                    "desired_decision_date": expiry,
                    "state_available_at": _decision_at(expiry),
                    "score": 0.0,
                }
            )
    return rows


def build_source_decisions(
    signals: pd.DataFrame,
    panel: pd.DataFrame,
    active_map: pd.DataFrame,
) -> SourceDecisionBuild:
    """Map source signal/expiry states to decisions and risk-size the fixed basket."""
    source_signals = signals.copy()
    market = v12.normalize_signal_panel(panel)
    volatilities: dict[str, pd.Series] = {}
    for asset in ECONOMIC_SIGNS:
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
    decisions: list[dict[str, Any]] = []
    state_rows = _state_rows(source_signals)
    for state in state_rows:
        desired = pd.Timestamp(state["desired_decision_date"])
        location = int(active_dates.searchsorted(desired, side="left"))
        common = dict(state)
        if location >= len(active_dates):
            decisions.append(
                {
                    **common,
                    "decision_date": pd.NaT,
                    "decision_at": pd.NaT,
                    **{f"annualized_{asset}_volatility": np.nan for asset in ECONOMIC_SIGNS},
                    **{f"target_{asset}": np.nan for asset in ECONOMIC_SIGNS},
                    "decision_status": "no_future_active_decision_session",
                }
            )
            continue
        decision_date = pd.Timestamp(active_dates[location])
        decision_at = _decision_at(decision_date)
        if pd.Timestamp(state["state_available_at"]) > decision_at:
            raise ValueError("V20 source state mapped before it became available")
        score = float(state["score"])
        volatility_values = {
            asset: volatilities[asset].get(decision_date, np.nan) for asset in ECONOMIC_SIGNS
        }
        target_values: dict[str, float] = {}
        missing_volatility = False
        for asset, sign in ECONOMIC_SIGNS.items():
            if score == 0.0 or sign == 0.0:
                target_values[asset] = 0.0
                continue
            volatility = volatility_values[asset]
            if pd.isna(volatility) or not math.isfinite(float(volatility)):
                missing_volatility = True
                target_values[asset] = np.nan
                continue
            risk_scale = min(
                1.0,
                TARGET_VOLATILITY / max(float(volatility), VOLATILITY_FLOOR),
            )
            target_values[asset] = score * sign * RISK_BUDGET * risk_scale
        decisions.append(
            {
                **common,
                "decision_date": decision_date,
                "decision_at": decision_at,
                **{
                    f"annualized_{asset}_volatility": volatility
                    for asset, volatility in volatility_values.items()
                },
                **{f"target_{asset}": target for asset, target in target_values.items()},
                "decision_status": (
                    "missing_prior_60_session_volatility" if missing_volatility else "mapped"
                ),
            }
        )
    frame = pd.DataFrame(decisions)
    frame["state_precedence"] = frame["state_kind"].map({"expiry": 0, "signal": 1})
    frame = frame.sort_values(
        ["decision_date", "desired_decision_date", "state_precedence", "source_publication_date"],
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
                "version": "futures_v20_minfin_ofz_demand_strength_v1",
                "state_kind": row.state_kind,
                "source_publication_date": row.source_publication_date.date().isoformat(),
                "source_available_at": row.source_available_at.isoformat(),
                "state_available_at": row.state_available_at.isoformat(),
                "score": float(row.score),
                "history_count": int(row.history_count),
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
            raise ValueError("V20 weights are not complete four-asset snapshots")
        if weights.groupby("decision_date")["target_weight"].apply(
            lambda values: float(values.abs().sum())
        ).gt(1.0 + 1e-12).any():
            raise ValueError("V20 source weights breach the sealed gross cap")
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
        raise ValueError("V20 cost scenarios drifted from the seal")
    return output


def _promotion(
    scenario_results: dict[str, dict[str, Any]],
    checks: dict[str, bool],
    signal_counts_by_year: dict[str, int],
    nonzero_signals: int,
) -> dict[str, Any]:
    primary = scenario_results["primary"]
    source_count = sum(signal_counts_by_year.values())
    conditions = {
        "every_input_and_temporal_check_true": all(checks.values()),
        "at_least_150_scored_source_days_and_10_each_oos_year": (
            source_count >= 150
            and all(signal_counts_by_year.get(str(year), 0) >= 10 for year in range(2021, 2026))
        ),
        "at_least_140_nonzero_scored_source_days": nonzero_signals >= 140,
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
        "# V20 Minfin OFZ-PD prior-rank demand strength",
        "",
        f"Verdict: **{payload['promotion']['verdict']}** (research-only; live forbidden).",
        "",
        (
            "Current-vintage date-only Minfin pages are development evidence, not original "
            "publication vintages or an independent holdout."
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
            f"- Source events: {counts['source_events']}",
            f"- Successful OFZ-PD results/days: {counts['selected_results']}/"
            f"{counts['aggregated_source_days']}",
            f"- Scored source days by year: {counts['scored_source_days_by_year']}",
            f"- Score signs: {counts['score_sign_counts']}",
            f"- Expiry states: {counts['expiry_states']}",
            f"- Same-session state collisions: {counts['same_session_collisions']}",
            f"- Extra roll decisions: {counts['roll_decisions']}",
            f"- Complete dependencies: {counts['covered_nonzero_targets']}/"
            f"{counts['nonzero_targets']}",
            "",
            "Each date-only result is admitted only at 23:59:59 Moscow and can fill only "
            "at the following factual active-contract open. Rankings use prior auction "
            "days only; no market outcome trains the score.",
        ]
    )
    return "\n".join(lines) + "\n"


def run_experiment(output_root: Path) -> Path:
    """Execute one immutable V20 run after all source/protocol identities pass."""
    protocol = load_protocol()
    verified = verify_inputs(protocol)
    events_raw = pd.read_parquet(
        verified.paths["minfin_ofz_auction_events"],
        columns=protocol["inputs"]["minfin_ofz_auction_events"]["allowed_columns"],
    )
    events = normalize_events(events_raw)
    signals = build_source_signals(events)
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
        raise ValueError("V20 produced no mapped source weights")
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
        for key, value in scored["publication_date"].dt.year.value_counts().items()
    }
    nonzero_signals = int(scored["score"].ne(0.0).sum())
    mapped = source_build.decisions.loc[
        source_build.decisions["decision_status"].eq("mapped")
    ].copy()
    checks = dict(verified.checks)
    checks["source_available_before_2026"] = bool(events["available_at"].lt(PROTECTED_FROM).all())
    checks["successful_OFZ_PD_only_in_signal"] = bool(
        len(
            events.loc[
                events["event_kind"].eq("primary_result")
                & events["ofz_type"].eq(FIXED_COUPON)
            ]
        )
        == 283
    )
    checks["rank_history_strictly_prior"] = bool(
        scored["history_max_publication_date"].lt(scored["publication_date"]).all()
        and scored["history_count"].between(MINIMUM_HISTORY, RANK_WINDOW).all()
    )
    checks["score_is_bounded_and_finite"] = bool(
        np.isfinite(scored["score"].to_numpy(dtype=float)).all()
        and scored["score"].abs().le(1.0 + 1e-12).all()
    )
    checks["mapped_states_after_availability"] = bool(
        (
            pd.to_datetime(mapped["state_available_at"], utc=True)
            <= pd.to_datetime(mapped["decision_at"], utc=True)
        ).all()
    )
    expiry = source_build.decisions.loc[source_build.decisions["state_kind"].eq("expiry")]
    checks["expiry_exactly_seven_calendar_days"] = bool(
        (
            pd.to_datetime(expiry["desired_decision_date"])
            - pd.to_datetime(expiry["source_publication_date"])
        ).dt.days.eq(EXPIRY_DAYS).all()
        and expiry["score"].eq(0.0).all()
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
    score_values = scored["score"]
    score_sign_counts = {
        "positive": int(score_values.gt(0.0).sum()),
        "negative": int(score_values.lt(0.0).sum()),
        "zero": int(score_values.eq(0.0).sum()),
    }
    counts = {
        "source_events": len(events),
        "selected_results": 283,
        "aggregated_source_days": len(signals),
        "source_warmup_days": int(signals["signal_status"].eq("source_warmup").sum()),
        "scored_source_days": len(scored),
        "scored_source_days_by_year": signal_counts_by_year,
        "score_sign_counts": score_sign_counts,
        "score_direction_changes": int(
            np.sign(score_values).ne(np.sign(score_values).shift()).sum()
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
        signal_counts_by_year,
        nonzero_signals,
    )
    code_paths = {
        "v20_implementation": Path(__file__).resolve(),
        "minfin_source": PROJECT_ROOT / "src/market_lab/futures/minfin_ofz_auction_source.py",
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
    run_name = f"v20_minfin_ofz_demand_strength_{timestamp}_{CONFIG_SHA256[:8]}"
    final = output_root / run_name
    if final.exists():
        raise FileExistsError(f"V20 run already exists: {final}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{run_name}.", dir=output_root))
    try:
        shutil.copyfile(CONFIG_PATH, temporary / "resolved_protocol.yaml")
        _write_parquet(temporary / "source_events.parquet", events)
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
        help="External immutable runs root; a unique V20 child directory is created.",
    )
    arguments = parser.parse_args()
    print(run_experiment(arguments.output_root))


if __name__ == "__main__":
    main()
