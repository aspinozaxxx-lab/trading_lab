"""Real'naya PIT-sborka multi-resolution massiva futures-v7 bez PnL."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from market_lab.futures.cftc_radar import (
    CFTC_CHANNEL_COMPONENTS,
    build_causal_cftc_asset_scores,
    build_causal_cftc_features,
    official_development_release_overrides,
)
from market_lab.futures.info_radar import build_causal_cbr_features
from market_lab.futures.session_timing import legacy_forts_decision_calendar
from market_lab.futures.ten_minute_download import (
    TEN_MINUTE_DEVELOPMENT_END,
    TEN_MINUTE_DEVELOPMENT_START,
    TEN_MINUTE_OUTPUT_COLUMNS,
    TEN_MINUTE_PROTECTED_FROM,
    verify_ten_minute_dataset,
)
from market_lab.futures_v7.config import (
    V7_ASSETS,
    V7_BAR_FEATURES,
    V7_DAILY_FEATURES,
    V7_SSL_HORIZONS,
)
from market_lab.futures_v7.contracts import (
    DecisionTimingBatch,
    next_open_to_next_open_log_return,
)
from market_lab.futures_v7.dataset import (
    MultiResolutionArrays,
    SelfSupervisedTargets,
    build_self_supervised_targets,
)
from market_lab.io_utils import write_json

V7_SEQUENCE_BARS: Final[int] = 512  # Fiksirovannaya dlina causal intraday okna.
V7_ASSEMBLY_SCHEMA_VERSION: Final[int] = 2  # Versiya content-addressed massiva.
V7_EXACT_OPEN_TOLERANCE: Final[float] = 1e-9  # Audit, no ne filtr istorii.
V7_MIN_MAIN_SESSION_BUCKETS: Final[int] = 30  # Porog factual all-asset sessii.
V7_PROTECTED_UTC: Final[pd.Timestamp] = pd.Timestamp(  # Fizicheskii holdout cutoff.
    "2026-01-01T00:00:00Z"
)
V7_INTRADAY_COLUMNS: Final[tuple[str, ...]] = (  # Minimal'naya proverennaya skhema.
    *TEN_MINUTE_OUTPUT_COLUMNS,
)
V7_EXECUTION_OVERLAY_COLUMNS: Final[tuple[str, ...]] = (  # Exact first-open audit.
    "trade_date",
    "decision_date",
    "previous_decision_at",
    "conservative_open_at",
    "event_interval_end_at",
    "asset_code",
    "contract_id",
    "entry_timestamp",
    "open",
    "adjusted_open",
    "daily_open_reference",
    "open_difference",
    "high",
    "low",
    "daily_high_reference",
    "daily_low_reference",
    "interval_10m_high",
    "interval_10m_low",
    "settle",
    "volume",
    "reported_trade_activity",
    "forward_additive_adjustment",
    "is_active_contract",
    "exact_open_available",
    "augmented_boundary_used",
    "high_low_reconstructed",
    "source",
    "provenance",
)


@dataclass(frozen=True, slots=True)
class VerifiedTenMinuteBars:
    """Hranit tol'ko manifest-referenced Parquet i ih proverennyi audit."""

    frame: pd.DataFrame
    source_artifacts: tuple[dict[str, Any], ...]
    verification_totals: dict[str, int]
    dataset_manifest_sha256: str


@dataclass(frozen=True, slots=True)
class V7AssemblyResult:
    """Obedinyaet model arrays, SSL label, exact-open overlay i audit."""

    arrays: MultiResolutionArrays
    log_price: np.ndarray
    asset_entry_open_times: np.ndarray
    asset_exit_open_times: np.ndarray
    ssl_targets: SelfSupervisedTargets
    sample_index: pd.DataFrame
    execution_market_overlay: pd.DataFrame
    audit: dict[str, Any]
    source_artifacts: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class V7AssemblyArtifactPaths:
    """Hranit content-addressed puti atomarnoi real-data sborki."""

    arrays_path: Path
    execution_overlay_path: Path
    manifest_path: Path
    arrays_sha256: str
    execution_overlay_sha256: str


@dataclass(frozen=True, slots=True)
class LoadedV7TrainingArrays:
    """Hranit vosstanovlennye arrays i raw log-price dlya train-only SSL."""

    arrays: MultiResolutionArrays
    log_price: np.ndarray
    asset_entry_open_times: np.ndarray
    asset_exit_open_times: np.ndarray
    sample_trade_dates: np.ndarray


def _sha256_file(path: Path) -> str:
    """Vychislyaet SHA-256 faila potokovo bez skrytoi normalizacii."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    """Chitaet JSON s optional BOM i trebuet object verhnego urovnya."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON ne yavlyaetsya obektom: {path}")
    return payload


def _bounded_path(root: Path, relative: str) -> Path:
    """Razreshaet manifest path tol'ko vnutri ukazannogo data-root."""
    resolved_root = root.resolve()
    target = resolved_root.joinpath(*Path(relative).parts).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"Manifest path vyshel iz data-root: {target}") from error
    return target


def _verified_record(root: Path, record: dict[str, Any]) -> Path:
    """Povtorno proveryaet path, bytes, SHA i vozvrashchaet immutable artifact."""
    path = _bounded_path(root, str(record.get("path", "")))
    if not path.is_file():
        raise FileNotFoundError(path)
    expected_bytes = int(record.get("bytes", -1))
    if expected_bytes >= 0 and path.stat().st_size != expected_bytes:
        raise ValueError(f"Artifact bytes mismatch: {path}")
    expected_sha = str(record.get("sha256", ""))
    if len(expected_sha) != 64 or _sha256_file(path) != expected_sha:
        raise ValueError(f"Artifact SHA-256 mismatch: {path}")
    return path


def load_verified_ten_minute_bars(
    data_root: Path,
    source_data_root: Path | None = None,
    *,
    start_date: date = TEN_MINUTE_DEVELOPMENT_START,
    end_date: date = TEN_MINUTE_DEVELOPMENT_END,
) -> VerifiedTenMinuteBars:
    """Snachala verify-it dataset, zatem chitaet tol'ko referenced Parquet."""
    root = data_root.resolve()
    source_root = (source_data_root or data_root).resolve()
    totals = verify_ten_minute_dataset(root, source_root, start_date, end_date)
    dataset_manifest = root / "processed" / "futures_v7_10m" / (
        f"manifest_{start_date.isoformat()}_{end_date.isoformat()}.json"
    )
    payload = _read_json(dataset_manifest)
    if payload.get("protected_from") != TEN_MINUTE_PROTECTED_FROM.isoformat():
        raise ValueError("10m dataset ne imeet protected 2026 granicy")
    frames: list[pd.DataFrame] = []
    source_records: list[dict[str, Any]] = []
    for asset_record in payload.get("assets", []):
        asset_manifest_path = _verified_record(root, asset_record)
        asset_manifest = _read_json(asset_manifest_path)
        for segment_record in asset_manifest.get("segment_manifests", []):
            segment_manifest_path = _verified_record(root, segment_record)
            segment_manifest = _read_json(segment_manifest_path)
            parquet_record = segment_manifest.get("artifacts", {}).get("parquet")
            if not isinstance(parquet_record, dict):
                raise ValueError("10m segment manifest ne soderzhit Parquet")
            parquet_path = _verified_record(root, parquet_record)
            frame = pd.read_parquet(parquet_path, columns=list(V7_INTRADAY_COLUMNS))
            expected_rows = int(parquet_record.get("rows", -1))
            if len(frame) != expected_rows:
                raise ValueError(f"10m Parquet rows mismatch: {parquet_path}")
            frames.append(frame)
            source_records.append(
                {
                    "kind": "official_moex_10m_parquet",
                    "path": parquet_path.relative_to(root).as_posix(),
                    "rows": len(frame),
                    "bytes": parquet_path.stat().st_size,
                    "sha256": _sha256_file(parquet_path),
                    "segment_manifest_path": segment_manifest_path.relative_to(root).as_posix(),
                    "segment_manifest_sha256": _sha256_file(segment_manifest_path),
                }
            )
    if not frames:
        raise ValueError("Verified 10m manifests ne ssylayutsya ni na odin Parquet")
    combined = pd.concat(frames, ignore_index=True)
    if len(combined) != totals["rows"]:
        raise ValueError("Loaded 10m rows ne sovpali s verify totals")
    return VerifiedTenMinuteBars(
        frame=combined,
        source_artifacts=tuple(source_records),
        verification_totals=totals,
        dataset_manifest_sha256=_sha256_file(dataset_manifest),
    )


def _normalized_utc(values: pd.Series, label: str) -> pd.Series:
    """Privodit timestamp-kolonku k UTC i fail-closed ot NaT/holdout."""
    result = pd.to_datetime(values, errors="raise", utc=True)
    if result.isna().any():
        raise ValueError(f"{label} soderzhit NaT")
    if result.ge(V7_PROTECTED_UTC).any():
        raise ValueError(f"{label} pytayetsya chitat' protected 2026")
    return result


def _normalized_dates(values: pd.Series, label: str) -> pd.Series:
    """Privodit factual trade dates k naive polunochi do 2026."""
    result = pd.to_datetime(values, errors="raise")
    if result.isna().any():
        raise ValueError(f"{label} soderzhit NaT")
    if result.dt.tz is not None:
        result = result.dt.tz_convert("Europe/Moscow").dt.tz_localize(None)
    result = result.dt.normalize()
    if result.ge(pd.Timestamp(TEN_MINUTE_PROTECTED_FROM)).any():
        raise ValueError(f"{label} pytayetsya chitat' protected 2026")
    return result


def _utc_naive_ns(values: pd.Series) -> np.ndarray:
    """Prevrashchaet UTC pandas Series v numpy datetime64[ns] bez sdviga."""
    parsed = pd.to_datetime(values, errors="raise", utc=True)
    return parsed.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")


def _normalize_active_map(active_map: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet exact effective asset/contract map i forward adjustment."""
    required = {
        "effective_date",
        "decision_date",
        "asset_code",
        "contract_id",
        "forward_additive_adjustment",
        "chain_id",
        "open",
        "high",
        "low",
        "settle",
        "volume",
        "expiration_date",
    }
    if missing := required - set(active_map.columns):
        raise ValueError(f"Active map ne soderzhit: {sorted(missing)}")
    frame = active_map.copy()
    frame["effective_date"] = _normalized_dates(frame["effective_date"], "active effective")
    frame["decision_date"] = pd.to_datetime(frame["decision_date"], errors="coerce")
    frame["asset_code"] = frame["asset_code"].astype("string").str.upper()
    frame["contract_id"] = frame["contract_id"].astype("string")
    frame["expiration_date"] = pd.to_datetime(frame["expiration_date"], errors="coerce")
    frame["forward_additive_adjustment"] = pd.to_numeric(
        frame["forward_additive_adjustment"], errors="coerce"
    )
    if frame.duplicated(["effective_date", "asset_code"]).any():
        raise ValueError("Active map soderzhit duplicate date/asset")
    if set(frame["asset_code"].dropna()) != set(V7_ASSETS):
        raise ValueError("Active map imeet drugoi v7 universe")
    return frame.sort_values(["effective_date", "asset_code"], ignore_index=True)


def _normalize_panel(panel: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet daily PIT-panel bez iskusstvennogo calendar fill."""
    required = {
        "trade_date",
        "asset_code",
        "active_chain_id",
        "close",
        "open_interest",
        "roll_yield",
        "participant_source_date",
        "participant_lag_sessions",
        "participant_snapshot_complete",
        "physical_long",
        "physical_short",
        "legal_long",
        "legal_short",
    }
    if missing := required - set(panel.columns):
        raise ValueError(f"Daily panel ne soderzhit: {sorted(missing)}")
    frame = panel.copy()
    frame["trade_date"] = _normalized_dates(frame["trade_date"], "panel trade_date")
    frame["asset_code"] = frame["asset_code"].astype("string").str.upper()
    frame["participant_source_date"] = pd.to_datetime(
        frame["participant_source_date"], errors="coerce"
    )
    if frame.duplicated(["trade_date", "asset_code"]).any():
        raise ValueError("Daily panel soderzhit duplicate date/asset")
    if set(frame["asset_code"].dropna()) != set(V7_ASSETS):
        raise ValueError("Daily panel imeet drugoi v7 universe")
    return frame.sort_values(["asset_code", "trade_date"], ignore_index=True)


def _normalize_contract_observations(observations: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet vse daily contract legs dlya exact execution overlay."""
    required = {
        "trade_date",
        "asset_code",
        "canonical_contract_id",
        "open",
        "high",
        "low",
        "settle",
        "volume",
        "reported_trade_activity",
    }
    if missing := required - set(observations.columns):
        raise ValueError(f"Contract observations ne soderzhat: {sorted(missing)}")
    frame = observations.copy()
    frame["trade_date"] = _normalized_dates(frame["trade_date"], "contract trade_date")
    frame["asset_code"] = frame["asset_code"].astype("string").str.upper()
    frame["canonical_contract_id"] = frame["canonical_contract_id"].astype("string")
    if frame.duplicated(["trade_date", "asset_code", "canonical_contract_id"]).any():
        raise ValueError("Contract observations soderzhat duplicate exact leg")
    if set(frame["asset_code"].dropna()) != set(V7_ASSETS):
        raise ValueError("Contract observations imeyut drugoi v7 universe")
    return frame.sort_values(
        ["trade_date", "asset_code", "canonical_contract_id"], ignore_index=True
    )


def _decision_calendar(panel: pd.DataFrame) -> pd.DataFrame:
    """Stroit legacy D18:50 calendar tol'ko iz factual common trade dates."""
    per_asset = panel.groupby("asset_code")["trade_date"].apply(set)
    common = sorted(set.intersection(*per_asset.tolist()))
    timing = legacy_forts_decision_calendar(common)
    if timing["decision_at"].ge(V7_PROTECTED_UTC).any():
        raise ValueError("Decision calendar vyshel v protected 2026")
    return timing


def _decision_at(trade_date: pd.Timestamp) -> pd.Timestamp:
    """Vozvrashchaet factual legacy decision D 18:50 MSK v UTC."""
    normalized = pd.Timestamp(trade_date).normalize()
    return (
        normalized.tz_localize("Europe/Moscow")
        + pd.Timedelta(hours=18, minutes=50)
    ).tz_convert("UTC")


def _main_session_candidates(
    bars: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    minimum_buckets: int = V7_MIN_MAIN_SESSION_BUCKETS,
) -> tuple[pd.DatetimeIndex, dict[str, Any]]:
    """Nahodit propushchennye panel'em all-4 factual main-session dates."""
    if minimum_buckets <= 0:
        raise ValueError("minimum_buckets dolzhen byt' > 0")
    local_start = bars["timestamp"].dt.tz_convert("Europe/Moscow")
    local_end = bars["end_timestamp"].dt.tz_convert("Europe/Moscow")
    session_date = local_start.dt.tz_localize(None).dt.normalize()
    end_date = local_end.dt.tz_localize(None).dt.normalize()
    start_second = (
        local_start.dt.hour * 3600
        + local_start.dt.minute * 60
        + local_start.dt.second
    )
    end_second = (
        local_end.dt.hour * 3600
        + local_end.dt.minute * 60
        + local_end.dt.second
    )
    main = (
        session_date.eq(end_date)
        & session_date.dt.dayofweek.lt(5)
        & start_second.ge(10 * 3600)
        & end_second.le(18 * 3600 + 50 * 60)
        & bars["asset_code"].isin(V7_ASSETS)
    )
    counted = (
        pd.DataFrame(
            {
                "session_date": session_date.loc[main],
                "asset_code": bars.loc[main, "asset_code"].to_numpy(),
                "timestamp": bars.loc[main, "timestamp"].to_numpy(),
            }
        )
        .groupby(["session_date", "asset_code"], observed=True)["timestamp"]
        .nunique()
        .unstack(fill_value=0)
        .reindex(columns=list(V7_ASSETS), fill_value=0)
    )
    strong = counted.index[counted.ge(minimum_buckets).all(axis=1)]
    per_asset = panel.groupby("asset_code")["trade_date"].apply(set)
    model_dates = pd.DatetimeIndex(sorted(set.intersection(*per_asset.tolist())))
    in_model_span = strong[(strong >= model_dates.min()) & (strong <= model_dates.max())]
    unmodeled = pd.DatetimeIndex(in_model_span.difference(model_dates)).sort_values()
    audit = {
        "minimum_distinct_main_session_buckets_per_asset": minimum_buckets,
        "strong_all_asset_main_session_count": len(in_model_span),
        "unmodeled_all_asset_main_session_count": len(unmodeled),
        "unmodeled_all_asset_main_session_dates": [
            timestamp.date().isoformat() for timestamp in unmodeled
        ],
        "weekend_sessions_are_excluded": True,
        "source": "verified_10m_distinct_scheduled_buckets_10:00_to_18:50_msk",
    }
    return unmodeled, audit


def _overlay_calendar(
    panel: pd.DataFrame,
    bars: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DatetimeIndex, dict[str, Any]]:
    """Dopolnyaet tol'ko execution boundaries sil'nymi factual 10m sessiyami."""
    unmodeled, audit = _main_session_candidates(bars, panel)
    per_asset = panel.groupby("asset_code")["trade_date"].apply(set)
    model_dates = pd.DatetimeIndex(sorted(set.intersection(*per_asset.tolist())))
    augmented_dates = model_dates.union(unmodeled).sort_values()
    timing = legacy_forts_decision_calendar(augmented_dates)
    if timing["decision_at"].ge(V7_PROTECTED_UTC).any():
        raise ValueError("Augmented execution calendar vyshel v protected 2026")
    audit = {
        **audit,
        "model_session_count": len(model_dates),
        "augmented_boundary_session_count": len(augmented_dates),
        "daily_panel_rows_are_not_fabricated": True,
        "augmentation_scope": "exact_execution_boundaries_only",
    }
    return timing, unmodeled, audit


def _annotate_irregular_model_intervals(
    timing: pd.DataFrame,
    unmodeled_dates: pd.DatetimeIndex,
    active: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Maskiruet ambiguous labels i dokazyvaet active-chain continuity gapov."""
    annotated = timing.copy()
    gap_dates: list[str] = []
    irregular: list[bool] = []
    continuity_cells = 0
    lookup = active.set_index(["effective_date", "asset_code"])
    for row in annotated.itertuples(index=False):
        inside = unmodeled_dates[
            (unmodeled_dates > pd.Timestamp(row.trade_date))
            & (unmodeled_dates < pd.Timestamp(row.effective_date))
        ]
        is_irregular = bool(len(inside))
        irregular.append(is_irregular)
        gap_dates.append("|".join(timestamp.date().isoformat() for timestamp in inside))
        if not is_irregular:
            continue
        for asset in V7_ASSETS:
            start_key = (pd.Timestamp(row.trade_date), asset)
            end_key = (pd.Timestamp(row.effective_date), asset)
            if start_key not in lookup.index or end_key not in lookup.index:
                raise ValueError("Irregular gap ne imeet active-map continuity endpoints")
            start = lookup.loc[start_key]
            end = lookup.loc[end_key]
            same_contract = str(start["contract_id"]) == str(end["contract_id"])
            same_chain = str(start["chain_id"]) == str(end["chain_id"])
            start_adjustment = float(start["forward_additive_adjustment"])
            end_adjustment = float(end["forward_additive_adjustment"])
            same_adjustment = np.isclose(
                start_adjustment,
                end_adjustment,
                rtol=0.0,
                atol=V7_EXACT_OPEN_TOLERANCE,
            )
            if not (same_contract and same_chain and same_adjustment):
                raise ValueError(
                    "Active contract/chain/adjustment izmenilsya v unmodeled session gap: "
                    f"{row.trade_date.date()}->{row.effective_date.date()} {asset}"
                )
            continuity_cells += 1
    annotated["irregular_unmodeled_session_gap"] = irregular
    annotated["unmodeled_session_dates"] = gap_dates
    audit = {
        "irregular_model_interval_count": int(sum(irregular)),
        "irregular_model_decision_dates": [
            pd.Timestamp(value).date().isoformat()
            for value in annotated.loc[
                annotated["irregular_unmodeled_session_gap"], "trade_date"
            ]
        ],
        "active_contract_chain_adjustment_continuity_cells_checked": continuity_cells,
        "active_continuity_required_for_collapsed_intraday_assignment": True,
        "irregular_supervised_labels_are_masked": True,
    }
    return annotated, audit


def _normalize_intraday(bars: pd.DataFrame) -> pd.DataFrame:
    """Proveryaet raw official 10m OHLCV bez zapolneniya propuskov."""
    if missing := set(V7_INTRADAY_COLUMNS) - set(bars.columns):
        raise ValueError(f"10m bars ne soderzhat: {sorted(missing)}")
    frame = bars.loc[:, list(V7_INTRADAY_COLUMNS)].copy()
    frame["timestamp"] = _normalized_utc(frame["timestamp"], "10m timestamp")
    frame["end_timestamp"] = _normalized_utc(frame["end_timestamp"], "10m end_timestamp")
    if frame["end_timestamp"].lt(frame["timestamp"]).any():
        raise ValueError("10m end_timestamp ran'she open timestamp")
    frame["asset_code"] = frame["logical_symbol"].astype("string").str.upper()
    frame["canonical_contract_id"] = frame["canonical_contract_id"].astype("string")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    finite_price = np.isfinite(frame[["open", "high", "low", "close"]]).all(axis=1)
    positive_price = frame[["open", "high", "low", "close"]].gt(0.0).all(axis=1)
    invariant = (
        frame["high"].ge(frame[["open", "close", "low"]].max(axis=1))
        & frame["low"].le(frame[["open", "close", "high"]].min(axis=1))
    )
    if not (finite_price & positive_price & invariant).all():
        raise ValueError("10m OHLC narushaet positive/invariant contract")
    if (~np.isfinite(frame["volume"])).any() or frame["volume"].lt(0.0).any():
        raise ValueError("10m volume dolzhen byt' finite i nonnegative")
    if frame.duplicated(
        ["timestamp", "end_timestamp", "asset_code", "canonical_contract_id"]
    ).any():
        raise ValueError("10m bars soderzhat duplicate factual candle")
    return frame.sort_values(["end_timestamp", "asset_code"], ignore_index=True)


def _assign_trade_dates(
    bars: pd.DataFrame,
    timing: pd.DataFrame,
) -> pd.DataFrame:
    """Naznachaet kazhdoi sveche (previous decision, D decision] factual interval."""
    terminal = _decision_at(pd.Timestamp(timing["effective_date"].iloc[-1]))
    decisions = pd.concat(
        [timing["decision_at"], pd.Series([terminal])], ignore_index=True
    )
    decisions_ns = decisions.astype("int64").to_numpy()
    if (np.diff(decisions_ns) <= 0).any():
        raise ValueError("Execution boundaries dolzhny strogo vozrastat'")
    end_ns = bars["end_timestamp"].astype("int64").to_numpy()
    interval_index = np.searchsorted(decisions_ns, end_ns, side="left") - 1
    eligible = (interval_index >= 0) & (interval_index < len(timing))
    assigned = bars.loc[eligible].copy()
    assigned["trade_date"] = timing["effective_date"].to_numpy()[interval_index[eligible]]
    assigned["interval_previous_decision_at"] = timing["decision_at"].to_numpy()[
        interval_index[eligible]
    ]
    assigned["interval_conservative_open_at"] = timing[
        "conservative_open_at"
    ].to_numpy()[interval_index[eligible]]
    assigned["interval_end_at"] = decisions.to_numpy()[interval_index[eligible] + 1]
    return assigned


def _join_active_contracts(
    assigned: pd.DataFrame,
    active: pd.DataFrame,
) -> pd.DataFrame:
    """Ostavlyaet exact canonical contract iz causal active map bez bar fill."""
    active_keys = active.loc[
        active["contract_id"].notna(),
        [
            "effective_date",
            "asset_code",
            "contract_id",
            "forward_additive_adjustment",
            "chain_id",
        ],
    ].rename(
        columns={
            "effective_date": "trade_date",
            "contract_id": "canonical_contract_id",
        }
    )
    joined = assigned.merge(
        active_keys,
        on=["trade_date", "asset_code", "canonical_contract_id"],
        how="inner",
        validate="many_to_one",
    )
    if joined.duplicated(["timestamp", "asset_code"]).any():
        raise ValueError("Active 10m grid imeet dva bara asset na odin scheduled bucket")
    return joined.sort_values(["asset_code", "end_timestamp"], ignore_index=True)


def _first_exact_open_overlay(
    assigned_bars: pd.DataFrame,
    contract_observations: pd.DataFrame,
    active: pd.DataFrame,
    timing: pd.DataFrame,
    *,
    unmodeled_session_dates: pd.DatetimeIndex | None = None,
    tolerance: float = V7_EXACT_OPEN_TOLERANCE,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Stroit first factual >=19:00 open i ledger-compatible interval H/L."""
    unmodeled = pd.DatetimeIndex([]) if unmodeled_session_dates is None else (
        unmodeled_session_dates
    )
    decision_by_effective = timing.set_index("effective_date")
    grouped = {
        key: group.sort_values("timestamp", kind="mergesort")
        for key, group in assigned_bars.groupby(
            ["trade_date", "asset_code", "canonical_contract_id"], sort=False
        )
    }
    active_lookup = active.loc[active["contract_id"].notna()].set_index(
        ["effective_date", "asset_code", "contract_id"]
    )
    rows: list[dict[str, Any]] = []
    for item in contract_observations.to_dict("records"):
        trade_date = pd.Timestamp(item["trade_date"])
        contract = str(item["canonical_contract_id"])
        asset = str(item["asset_code"])
        timing_row = (
            decision_by_effective.loc[trade_date]
            if trade_date in decision_by_effective.index
            else None
        )
        previous_decision = (
            pd.NaT if timing_row is None else pd.Timestamp(timing_row["decision_at"])
        )
        conservative_open = (
            pd.NaT
            if timing_row is None
            else pd.Timestamp(timing_row["conservative_open_at"])
        )
        event_end = pd.NaT if timing_row is None else _decision_at(trade_date)
        exact_row: pd.Series | None = None
        event_rows: pd.DataFrame | None = None
        if timing_row is not None:
            candidate = grouped.get((trade_date, asset, contract))
            if candidate is not None:
                candidate = candidate.loc[
                    candidate["timestamp"].ge(conservative_open)
                    & candidate["end_timestamp"].le(event_end)
                ]
                if not candidate.empty:
                    event_rows = candidate
                    exact_row = candidate.iloc[0]
        raw_open = float("nan") if exact_row is None else float(exact_row["open"])
        active_key = (trade_date, asset, contract)
        is_active = active_key in active_lookup.index
        adjustment = (
            float(active_lookup.loc[active_key, "forward_additive_adjustment"])
            if is_active
            else 0.0
        )
        daily_open = float(item["open"]) if pd.notna(item["open"]) else float("nan")
        difference = raw_open - daily_open if np.isfinite(raw_open + daily_open) else np.nan
        daily_high = float(item["high"]) if pd.notna(item["high"]) else np.nan
        daily_low = float(item["low"]) if pd.notna(item["low"]) else np.nan
        event_high = (
            float(pd.to_numeric(event_rows["high"], errors="coerce").max())
            if event_rows is not None
            else np.nan
        )
        event_low = (
            float(pd.to_numeric(event_rows["low"], errors="coerce").min())
            if event_rows is not None
            else np.nan
        )
        settle = float(item["settle"]) if pd.notna(item["settle"]) else np.nan
        finite_highs = [
            value
            for value in (daily_high, event_high, raw_open, settle)
            if np.isfinite(value)
        ]
        finite_lows = [
            value
            for value in (daily_low, event_low, raw_open, settle)
            if np.isfinite(value)
        ]
        interval_high = max(finite_highs) if finite_highs else np.nan
        interval_low = min(finite_lows) if finite_lows else np.nan
        augmented_boundary = bool(
            timing_row is not None
            and pd.Timestamp(timing_row["trade_date"]) in unmodeled
        )
        provenance = {
            "source": "official_moex_iss_10m_manifest_referenced",
            "selection": "first_factual_candle_timestamp_gte_19:00_previous_decision_date",
            "signal_cutoff": "end_timestamp_lte_decision_at",
            "high_low": "valuation_envelope_not_claimed_traded_extrema",
            "synthetic_bar_or_fill": False,
            "daily_open_is_audit_reference_only": True,
            "augmented_boundary_used": augmented_boundary,
        }
        rows.append(
            {
                "trade_date": trade_date,
                "decision_date": (
                    pd.NaT if timing_row is None else pd.Timestamp(timing_row["trade_date"])
                ),
                "previous_decision_at": previous_decision,
                "conservative_open_at": conservative_open,
                "event_interval_end_at": event_end,
                "asset_code": asset,
                "contract_id": contract,
                "entry_timestamp": pd.NaT if exact_row is None else exact_row["timestamp"],
                "open": raw_open,
                "adjusted_open": raw_open + adjustment if np.isfinite(raw_open) else np.nan,
                "daily_open_reference": daily_open,
                "open_difference": difference,
                "high": interval_high,
                "low": interval_low,
                "daily_high_reference": daily_high,
                "daily_low_reference": daily_low,
                "interval_10m_high": event_high,
                "interval_10m_low": event_low,
                "settle": settle,
                "volume": item["volume"],
                "reported_trade_activity": item["reported_trade_activity"],
                "forward_additive_adjustment": adjustment,
                "is_active_contract": is_active,
                "exact_open_available": exact_row is not None,
                "augmented_boundary_used": augmented_boundary,
                "high_low_reconstructed": event_rows is not None,
                "source": "official_moex_iss_10m",
                "provenance": json.dumps(
                    provenance,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )
    overlay = pd.DataFrame(rows, columns=V7_EXECUTION_OVERLAY_COLUMNS)
    expected_exact = (
        overlay["reported_trade_activity"].fillna(False).astype(bool)
        & np.isfinite(overlay["daily_open_reference"])
    )
    comparable = overlay.loc[expected_exact & overlay["exact_open_available"]].copy()
    absolute = comparable["open_difference"].abs()
    mismatch = absolute.gt(tolerance)
    finite_open = overlay["exact_open_available"] & np.isfinite(overlay["open"])
    outside_interval = finite_open & (
        overlay["open"].gt(overlay["high"] + tolerance)
        | overlay["open"].lt(overlay["low"] - tolerance)
    )
    before_conservative = finite_open & overlay["entry_timestamp"].lt(
        overlay["conservative_open_at"]
    )
    expanded_high = (
        np.isfinite(overlay["daily_high_reference"])
        & np.isfinite(overlay["high"])
        & overlay["high"].gt(overlay["daily_high_reference"] + tolerance)
    )
    expanded_low = (
        np.isfinite(overlay["daily_low_reference"])
        & np.isfinite(overlay["low"])
        & overlay["low"].lt(overlay["daily_low_reference"] - tolerance)
    )
    if outside_interval.any():
        raise ValueError("Exact execution open vyshel za reconstructed interval H/L")
    if before_conservative.any():
        raise ValueError("Exact execution open okazalsya ran'she 19:00 boundary")
    quantiles = {
        f"q{int(level * 100):02d}": float(absolute.quantile(level)) if len(absolute) else 0.0
        for level in (0.50, 0.90, 0.95, 0.99)
    }
    active_mask = overlay["is_active_contract"].fillna(False).astype(bool)
    active_exact = active_mask & overlay["exact_open_available"]
    audit = {
        "rows": len(overlay),
        "daily_contract_leg_rows": len(overlay),
        "reported_activity_with_daily_open_rows": int(expected_exact.sum()),
        "exact_open_available_rows": int(overlay["exact_open_available"].sum()),
        "missing_exact_open_rows": int((expected_exact & ~overlay["exact_open_available"]).sum()),
        "active_contract_rows": int(active_mask.sum()),
        "active_exact_open_available_rows": int(active_exact.sum()),
        "active_missing_exact_open_rows": int(
            (active_mask & ~overlay["exact_open_available"]).sum()
        ),
        "active_missing_exact_open_is_unavailable_not_filled": True,
        "daily_open_comparison_rows": len(comparable),
        "daily_open_mismatch_count": int(mismatch.sum()),
        "daily_open_mismatch_tolerance": tolerance,
        "daily_open_absolute_difference_max": (
            float(absolute.max()) if len(absolute) else 0.0
        ),
        "daily_open_absolute_difference_quantiles": quantiles,
        "mismatch_is_audited_not_filtered": True,
        "exact_open_outside_reconstructed_high_low_rows": int(outside_interval.sum()),
        "entry_before_conservative_19_00_rows": int(before_conservative.sum()),
        "high_low_semantics": (
            "valuation_envelope_of_daily_high_low_interval_10m_exact_open_and_settle;"
            "settle_is_not_claimed_as_traded_extremum"
        ),
        "valuation_envelope_high_expansion_rows": int(expanded_high.sum()),
        "valuation_envelope_low_expansion_rows": int(expanded_low.sum()),
        "active_valuation_envelope_high_expansion_rows": int(
            (expanded_high & overlay["is_active_contract"]).sum()
        ),
        "active_valuation_envelope_low_expansion_rows": int(
            (expanded_low & overlay["is_active_contract"]).sum()
        ),
        "augmented_boundary_row_count": int(overlay["augmented_boundary_used"].sum()),
        "augmented_boundary_trade_dates": sorted(
            {
                pd.Timestamp(value).date().isoformat()
                for value in overlay.loc[
                    overlay["augmented_boundary_used"], "trade_date"
                ]
            }
        ),
        "by_asset": {
            asset: {
                "reported_activity_with_daily_open_rows": int(expected_exact[mask].sum()),
                "missing_exact_open_rows": int(
                    (expected_exact[mask] & ~overlay.loc[mask, "exact_open_available"]).sum()
                ),
                "daily_open_mismatch_count": int(
                    comparable.loc[comparable["asset_code"].eq(asset), "open_difference"]
                    .abs()
                    .gt(tolerance)
                    .sum()
                ),
                "active_contract_rows": int((mask & active_mask).sum()),
                "active_exact_open_available_rows": int(
                    (mask & active_exact).sum()
                ),
                "active_missing_exact_open_rows": int(
                    (mask & active_mask & ~overlay["exact_open_available"]).sum()
                ),
            }
            for asset in V7_ASSETS
            for mask in [overlay["asset_code"].eq(asset)]
        },
    }
    return overlay, audit


def _intraday_features(active_bars: pd.DataFrame) -> pd.DataFrame:
    """Stroit 12 fixed causal features tol'ko na factual active candles."""
    frame = active_bars.sort_values(
        ["asset_code", "chain_id", "timestamp"], kind="mergesort"
    ).copy()
    adjustment = pd.to_numeric(frame["forward_additive_adjustment"], errors="coerce")
    for column in ("open", "high", "low", "close"):
        frame[f"adjusted_{column}"] = pd.to_numeric(frame[column], errors="coerce") + adjustment
    group_keys = [frame["asset_code"], frame["chain_id"]]
    adjusted_close = frame["adjusted_close"]
    log_close = np.log(adjusted_close.where(adjusted_close.gt(0.0)))
    grouped_log = log_close.groupby(group_keys, sort=False)
    frame["log_return_1"] = grouped_log.diff(1)
    frame["log_return_3"] = grouped_log.diff(3)
    frame["log_return_6"] = grouped_log.diff(6)
    frame["range_log"] = np.log(frame["adjusted_high"] / frame["adjusted_low"])
    frame["body_log"] = np.log(frame["adjusted_close"] / frame["adjusted_open"])
    price_range = frame["adjusted_high"] - frame["adjusted_low"]
    frame["close_location"] = (
        (frame["adjusted_close"] - frame["adjusted_low"]) / price_range
    ).where(price_range.gt(0.0))
    frame["log1p_volume"] = np.log1p(frame["volume"])
    volume_mean = frame["volume"].groupby(group_keys, sort=False).transform(
        lambda values: values.rolling(36, min_periods=36).mean()
    )
    frame["relative_volume_36"] = (frame["volume"] / volume_mean - 1.0).where(
        volume_mean.gt(0.0)
    )
    square_return = frame["log_return_1"].pow(2)
    for horizon in (6, 36):
        mean_square = square_return.groupby(group_keys, sort=False).transform(
            lambda values, window=horizon: values.rolling(
                window, min_periods=window
            ).mean()
        )
        frame[f"realized_volatility_{horizon}"] = np.sqrt(mean_square)
    local_end = frame["end_timestamp"].dt.tz_convert("Europe/Moscow")
    phase = (
        local_end.dt.hour * 60.0
        + local_end.dt.minute
        + local_end.dt.second / 60.0
    ) / (24.0 * 60.0)
    frame["session_phase_sin"] = np.sin(2.0 * np.pi * phase)
    frame["session_phase_cos"] = np.cos(2.0 * np.pi * phase)
    frame["log_adjusted_close"] = log_close
    return frame


def _daily_price_features(panel: pd.DataFrame, active: pd.DataFrame) -> pd.DataFrame:
    """Stroit price<=D, roll/OI D-1 i participant prelag-1 features."""
    active_extra = active[
        ["effective_date", "asset_code", "expiration_date"]
    ].rename(columns={"effective_date": "trade_date"})
    frame = panel.merge(
        active_extra,
        on=["trade_date", "asset_code"],
        how="left",
        validate="one_to_one",
    ).sort_values(["asset_code", "trade_date"], ignore_index=True)
    close = pd.to_numeric(frame["close"], errors="coerce")
    valid_close = close.where(close.gt(0.0))
    keys = [frame["asset_code"], frame["active_chain_id"]]
    log_close = np.log(valid_close)
    grouped_log = log_close.groupby(keys, sort=False)
    frame["daily_return_1"] = grouped_log.diff(1)
    frame["daily_return_5"] = grouped_log.diff(5)
    frame["daily_return_20"] = grouped_log.diff(20)
    frame["daily_volatility_20"] = frame["daily_return_1"].groupby(
        keys, sort=False
    ).transform(lambda values: values.rolling(20, min_periods=20).std(ddof=0))
    asset_group = frame.groupby("asset_code", sort=False)
    frame["roll_yield"] = asset_group["roll_yield"].shift(1)
    dte = (frame["expiration_date"] - frame["trade_date"]).dt.days.astype(float) / 365.0
    frame["days_to_expiry_scaled"] = dte.groupby(frame["asset_code"], sort=False).shift(1)
    open_interest = pd.to_numeric(frame["open_interest"], errors="coerce")
    for horizon in (1, 5):
        previous = open_interest.groupby(frame["asset_code"], sort=False).shift(horizon)
        change = (open_interest / previous - 1.0).where(
            open_interest.gt(0.0) & previous.gt(0.0)
        )
        frame[f"open_interest_change_{horizon}"] = change.groupby(
            frame["asset_code"], sort=False
        ).shift(1)
    participant_valid = (
        frame["participant_snapshot_complete"].fillna(False).astype(bool)
        & pd.to_numeric(frame["participant_lag_sessions"], errors="coerce").eq(1)
        & frame["participant_source_date"].lt(frame["trade_date"])
    )
    for prefix in ("physical", "legal"):
        long_value = pd.to_numeric(frame[f"{prefix}_long"], errors="coerce")
        short_value = pd.to_numeric(frame[f"{prefix}_short"], errors="coerce")
        denominator = long_value + short_value
        frame[f"{prefix}_net_share_lag_1"] = (
            (long_value - short_value) / denominator
        ).where(participant_valid & denominator.gt(0.0))
    return frame


def _cbr_context(cbr: pd.DataFrame, decisions: pd.Series) -> pd.DataFrame:
    """Stroit four CBR channels i dokazyvaet available_at<=decision."""
    features = build_causal_cbr_features(cbr, decisions)
    for prefix in ("key_rate", "ruonia", "usd_rub_official"):
        available = pd.to_datetime(
            features[f"cbr_{prefix}_available_at"], errors="coerce", utc=True
        )
        invalid = available.notna() & available.gt(features["decision_at"])
        if invalid.any():
            raise ValueError(f"CBR {prefix} proshel as-of posle decision")
    previous_fx = (
        features["cbr_usd_rub_official_value"]
        - features["cbr_usd_rub_official_change"]
    )
    features["cbr_usdrub_return_1"] = np.log(
        features["cbr_usd_rub_official_value"] / previous_fx
    ).where(
        features["cbr_usd_rub_official_value"].gt(0.0) & previous_fx.gt(0.0)
    )
    features["cbr_ruonia_spread"] = (
        features["cbr_ruonia_value"] - features["cbr_key_rate_value"]
    )
    return features


def _cftc_scores(
    cftc: pd.DataFrame,
    decisions: pd.Series,
    precomputed: pd.DataFrame | None,
) -> pd.DataFrame:
    """Stroit ili validiruet asset CFTC score s yavnoi as-of dostupnost'yu."""
    if precomputed is None:
        features = build_causal_cftc_features(
            cftc,
            decisions,
            release_overrides=official_development_release_overrides(),
        )
        scores = build_causal_cftc_asset_scores(features)
        available_columns = [
            f"{channel}_available_at" for channel in CFTC_CHANNEL_COMPONENTS
        ]
        scores["available_at"] = scores[available_columns].max(axis=1)
    else:
        scores = precomputed.copy()
    aliases = {"asset_symbol": "asset_code"}
    scores = scores.rename(
        columns={source: target for source, target in aliases.items() if target not in scores}
    )
    required = {"decision_at", "asset_code", "score", "available_at"}
    if missing := required - set(scores.columns):
        raise ValueError(f"CFTC scores ne soderzhat: {sorted(missing)}")
    scores["decision_at"] = pd.to_datetime(scores["decision_at"], errors="raise", utc=True)
    scores["available_at"] = pd.to_datetime(scores["available_at"], errors="coerce", utc=True)
    scores["asset_code"] = scores["asset_code"].astype("string").str.upper()
    future = scores["available_at"].notna() & scores["available_at"].gt(
        scores["decision_at"]
    )
    if future.any():
        raise ValueError("CFTC score available_at pozhe decision")
    if scores.duplicated(["decision_at", "asset_code"]).any():
        raise ValueError("CFTC scores soderzhat duplicate decision/asset")
    return scores


def _daily_context_arrays(
    panel: pd.DataFrame,
    active: pd.DataFrame,
    samples: pd.DataFrame,
    cbr: pd.DataFrame,
    cftc: pd.DataFrame,
    precomputed_cftc_scores: pd.DataFrame | None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Sobiraet 16 fixed daily PIT features v poryadke config."""
    daily = _daily_price_features(panel, active).set_index(["trade_date", "asset_code"])
    cbr_features = _cbr_context(cbr, samples["decision_at"]).set_index("decision_at")
    scores = _cftc_scores(cftc, samples["decision_at"], precomputed_cftc_scores)
    score_lookup = scores.set_index(["decision_at", "asset_code"])
    score_matrix = scores.pivot(index="decision_at", columns="asset_code", values="score")
    values = np.full(
        (len(samples), len(V7_ASSETS), len(V7_DAILY_FEATURES)),
        np.nan,
        dtype=np.float32,
    )
    for sample_index, sample in enumerate(samples.itertuples(index=False)):
        decision_at = pd.Timestamp(sample.decision_at)
        cbr_row = cbr_features.loc[decision_at]
        for asset_index, asset in enumerate(V7_ASSETS):
            key = (pd.Timestamp(sample.trade_date), asset)
            row = daily.loc[key]
            primary = (
                float(score_lookup.loc[(decision_at, asset), "score"])
                if (decision_at, asset) in score_lookup.index
                else np.nan
            )
            cross_values = score_matrix.loc[decision_at].drop(labels=[asset]).to_numpy(dtype=float)
            finite_cross = cross_values[np.isfinite(cross_values)]
            cross = float(finite_cross.mean()) if len(finite_cross) else np.nan
            payload = {
                "daily_return_1": row["daily_return_1"],
                "daily_return_5": row["daily_return_5"],
                "daily_return_20": row["daily_return_20"],
                "daily_volatility_20": row["daily_volatility_20"],
                "roll_yield": row["roll_yield"],
                "days_to_expiry_scaled": row["days_to_expiry_scaled"],
                "open_interest_change_1": row["open_interest_change_1"],
                "open_interest_change_5": row["open_interest_change_5"],
                "physical_net_share_lag_1": row["physical_net_share_lag_1"],
                "legal_net_share_lag_1": row["legal_net_share_lag_1"],
                "cbr_key_rate_level": cbr_row["cbr_key_rate_value"],
                "cbr_key_rate_change": cbr_row["cbr_key_rate_change"],
                "cbr_ruonia_spread": cbr_row["cbr_ruonia_spread"],
                "cbr_usdrub_return_1": cbr_row["cbr_usdrub_return_1"],
                "cftc_primary_score": primary,
                "cftc_cross_asset_score": cross,
            }
            values[sample_index, asset_index] = np.asarray(
                [payload[name] for name in V7_DAILY_FEATURES], dtype=np.float32
            )
    valid = np.isfinite(values)
    audit = {
        "daily_cells": int(values.size),
        "daily_valid_cells": int(valid.sum()),
        "daily_valid_fraction": float(valid.mean()),
        "cbr_asof_checked": True,
        "cftc_asof_checked": True,
        "participant_pre_lag_sessions": 1,
        "roll_and_open_interest_lag_sessions": 1,
    }
    return values, valid, audit


def _sample_rows(
    timing: pd.DataFrame,
    scheduled_completion_times: np.ndarray,
    overlay: pd.DataFrame,
    sequence_bars: int,
) -> pd.DataFrame:
    """Vybirayet decisions tol'ko po calendar/grid, nikogda po target availability."""
    if sequence_bars <= 0:
        raise ValueError("sequence_bars dolzhen byt' > 0")
    active_lookup = overlay.loc[overlay["is_active_contract"]].set_index(
        ["trade_date", "asset_code"]
    )
    if active_lookup.index.duplicated().any():
        raise ValueError("Exact-open overlay imeet dva active contract na date/asset")
    leg_lookup = overlay.set_index(["trade_date", "asset_code", "contract_id"])
    rows: list[dict[str, Any]] = []
    completion_ns = scheduled_completion_times.astype("datetime64[ns]").astype(np.int64)
    for index in range(len(timing) - 1):
        current = timing.iloc[index]
        following = timing.iloc[index + 1]
        decision = pd.Timestamp(current["decision_at"])
        window_end = int(np.searchsorted(completion_ns, decision.value, side="right"))
        if window_end < sequence_bars:
            continue
        entry_times: list[pd.Timestamp] = []
        exit_times: list[pd.Timestamp] = []
        for asset in V7_ASSETS:
            entry_key = (pd.Timestamp(current["effective_date"]), asset)
            if entry_key not in active_lookup.index:
                continue
            entry_row = active_lookup.loc[entry_key]
            entry_time = entry_row["entry_timestamp"]
            if pd.notna(entry_time):
                entry_times.append(pd.Timestamp(entry_time))
            entry_contract = str(entry_row["contract_id"])
            exit_key = (
                pd.Timestamp(following["effective_date"]),
                asset,
                entry_contract,
            )
            if exit_key in leg_lookup.index:
                exit_time = leg_lookup.loc[exit_key, "entry_timestamp"]
                if pd.notna(exit_time):
                    exit_times.append(pd.Timestamp(exit_time))
        entry_placeholder = not entry_times
        exit_placeholder = not exit_times
        entry_at = (
            pd.Timestamp(current["conservative_open_at"])
            if entry_placeholder
            else max(entry_times)
        )
        exit_at = (
            pd.Timestamp(following["conservative_open_at"])
            if exit_placeholder
            else max(exit_times)
        )
        if not decision < entry_at < exit_at:
            raise ValueError("Factual execution timing narushaet decision<entry<exit")
        rows.append(
            {
                "trade_date": pd.Timestamp(current["trade_date"]),
                "decision_at": decision,
                "entry_trade_date": pd.Timestamp(current["effective_date"]),
                "exit_trade_date": pd.Timestamp(following["effective_date"]),
                "entry_open_at": entry_at,
                "exit_open_at": exit_at,
                "entry_time_placeholder": entry_placeholder,
                "exit_time_placeholder": exit_placeholder,
                "irregular_unmodeled_session_gap": bool(
                    current["irregular_unmodeled_session_gap"]
                ),
                "following_irregular_unmodeled_session_gap": bool(
                    following["irregular_unmodeled_session_gap"]
                ),
                "unmodeled_session_dates": str(current["unmodeled_session_dates"]),
                "union_window_end": window_end,
            }
        )
    if not rows:
        raise ValueError("Net ni odnogo target-independent sample s polnym bar window")
    return pd.DataFrame(rows)


def _grid_arrays(
    features: pd.DataFrame,
    samples: pd.DataFrame,
    sequence_bars: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Raskladyvaet scheduled-begin union s raw-end causal mask bez fill."""
    union = np.sort(np.unique(_utc_naive_ns(features["timestamp"])))
    scheduled_completion = union + np.timedelta64(10, "m")
    asset_to_index = {asset: index for index, asset in enumerate(V7_ASSETS)}
    feature_grid = np.full(
        (len(union), len(V7_ASSETS), len(V7_BAR_FEATURES)), np.nan, dtype=np.float32
    )
    log_price_grid = np.full((len(union), len(V7_ASSETS)), np.nan, dtype=np.float64)
    raw_end_grid = np.full(
        (len(union), len(V7_ASSETS)), np.datetime64("NaT"), dtype="datetime64[ns]"
    )
    union_ns = union.astype(np.int64)
    row_positions = np.searchsorted(
        union_ns,
        features["timestamp"].astype("int64").to_numpy(),
    )
    asset_positions = features["asset_code"].map(asset_to_index).to_numpy(dtype=int)
    feature_values = features.loc[:, list(V7_BAR_FEATURES)].to_numpy(dtype=np.float32)
    finite_rows = np.isfinite(feature_values).all(axis=1)
    feature_grid[row_positions[finite_rows], asset_positions[finite_rows]] = feature_values[
        finite_rows
    ]
    log_prices = features["log_adjusted_close"].to_numpy(dtype=float)
    finite_log = np.isfinite(log_prices)
    log_price_grid[row_positions[finite_log], asset_positions[finite_log]] = log_prices[finite_log]
    raw_end_grid[row_positions, asset_positions] = _utc_naive_ns(features["end_timestamp"])
    intraday = np.full(
        (
            len(samples),
            len(V7_ASSETS),
            sequence_bars,
            len(V7_BAR_FEATURES),
        ),
        np.nan,
        dtype=np.float32,
    )
    log_price = np.full(
        (len(samples), len(V7_ASSETS), sequence_bars), np.nan, dtype=np.float64
    )
    bar_times = np.empty((len(samples), sequence_bars), dtype="datetime64[ns]")
    masked_unfinished_cells = 0
    for sample_number, sample in enumerate(samples.itertuples(index=False)):
        window_end = int(sample.union_window_end)
        selected = slice(window_end - sequence_bars, window_end)
        feature_window = np.moveaxis(feature_grid[selected], 0, 1)
        log_window = np.moveaxis(log_price_grid[selected], 0, 1)
        raw_end_window = np.moveaxis(raw_end_grid[selected], 0, 1)
        decision_naive = np.datetime64(
            pd.Timestamp(sample.decision_at).tz_convert("UTC").tz_localize(None), "ns"
        )
        completed = ~np.isnat(raw_end_window) & (raw_end_window <= decision_naive)
        masked_unfinished_cells += int((~completed & ~np.isnat(raw_end_window)).sum())
        feature_window[~completed] = np.nan
        log_window[~completed] = np.nan
        intraday[sample_number] = feature_window
        log_price[sample_number] = log_window
        bar_times[sample_number] = scheduled_completion[selected]
    intraday_valid = np.isfinite(intraday).all(axis=-1)
    if np.isnat(bar_times).any() or (np.diff(bar_times, axis=1) <= np.timedelta64(0, "ns")).any():
        raise ValueError("Exact union bar grid ne yavlyaetsya strogo rastushchim")
    scheduled_occupancy = features.groupby("timestamp")["asset_code"].nunique()
    raw_end_occupancy = features.groupby("end_timestamp")["asset_code"].nunique()
    audit = {
        "grid_key": "scheduled_timestamp",
        "bar_availability_time": "scheduled_timestamp_plus_10_minutes",
        "raw_end_must_also_be_lte_decision": True,
        "scheduled_union_timestamp_count": len(union),
        "raw_end_union_timestamp_count": int(features["end_timestamp"].nunique()),
        "scheduled_mean_assets_per_key": float(scheduled_occupancy.mean()),
        "raw_end_mean_assets_per_key": float(raw_end_occupancy.mean()),
        "scheduled_one_asset_key_count": int(scheduled_occupancy.eq(1).sum()),
        "raw_end_one_asset_key_count": int(raw_end_occupancy.eq(1).sum()),
        "unfinished_asset_cells_masked": masked_unfinished_cells,
    }
    return intraday, intraday_valid, log_price, bar_times, audit


def _supervised_targets(
    samples: pd.DataFrame,
    overlay: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Stroit raw same-entry-leg target i maskiruet irregular session gap."""
    active_lookup = overlay.loc[overlay["is_active_contract"]].set_index(
        ["trade_date", "asset_code"]
    )
    leg_lookup = overlay.set_index(["trade_date", "asset_code", "contract_id"])
    entry = np.full((len(samples), len(V7_ASSETS)), np.nan, dtype=float)
    exit_ = np.full_like(entry, np.nan)
    asset_entry_times = np.full(entry.shape, np.datetime64("NaT"), dtype="datetime64[ns]")
    asset_exit_times = np.full(exit_.shape, np.datetime64("NaT"), dtype="datetime64[ns]")
    roll_boundary = np.zeros(entry.shape, dtype=bool)
    irregular_cells = np.zeros(entry.shape, dtype=bool)
    for sample_index, sample in enumerate(samples.itertuples(index=False)):
        if bool(sample.irregular_unmodeled_session_gap) or bool(
            sample.following_irregular_unmodeled_session_gap
        ):
            irregular_cells[sample_index, :] = True
            continue
        for asset_index, asset in enumerate(V7_ASSETS):
            entry_key = (pd.Timestamp(sample.entry_trade_date), asset)
            if entry_key not in active_lookup.index:
                continue
            entry_row = active_lookup.loc[entry_key]
            entry_contract = str(entry_row["contract_id"])
            entry[sample_index, asset_index] = entry_row["open"]
            if pd.notna(entry_row["entry_timestamp"]):
                asset_entry_times[sample_index, asset_index] = np.datetime64(
                    pd.Timestamp(entry_row["entry_timestamp"]).tz_convert("UTC").tz_localize(None),
                    "ns",
                )
            active_exit_key = (pd.Timestamp(sample.exit_trade_date), asset)
            if active_exit_key in active_lookup.index:
                roll_boundary[sample_index, asset_index] = (
                    str(active_lookup.loc[active_exit_key, "contract_id"]) != entry_contract
                )
            exit_key = (pd.Timestamp(sample.exit_trade_date), asset, entry_contract)
            if exit_key not in leg_lookup.index:
                continue
            exit_row = leg_lookup.loc[exit_key]
            exit_[sample_index, asset_index] = exit_row["open"]
            if pd.notna(exit_row["entry_timestamp"]):
                asset_exit_times[sample_index, asset_index] = np.datetime64(
                    pd.Timestamp(exit_row["entry_timestamp"]).tz_convert("UTC").tz_localize(None),
                    "ns",
                )
    target, valid = next_open_to_next_open_log_return(entry, exit_)
    timing_valid = (
        ~np.isnat(asset_entry_times)
        & ~np.isnat(asset_exit_times)
        & (asset_entry_times < asset_exit_times)
    )
    valid &= timing_valid
    valid &= ~irregular_cells
    target[~valid] = 0.0
    audit = {
        "target_cells": int(target.size),
        "target_valid_cells": int(valid.sum()),
        "target_missing_cells": int((~valid).sum()),
        "target_valid_fraction": float(valid.mean()),
        "roll_boundary_target_cells": int(roll_boundary.sum()),
        "roll_boundary_valid_target_cells": int((roll_boundary & valid).sum()),
        "roll_boundary_missing_old_leg_exit_cells": int((roll_boundary & ~valid).sum()),
        "irregular_unmodeled_session_gap_cells": int(irregular_cells.sum()),
        "irregular_unmodeled_session_gap_valid_cells": int(
            (irregular_cells & valid).sum()
        ),
        "irregular_mask_rule": "current_or_following_model_timing_row_is_irregular",
        "missing_target_is_masked_not_sample_dropped": True,
        "target_formula": "log(raw_exact_same_entry_contract_exit_open/raw_exact_entry_open)",
    }
    return target, valid, asset_entry_times, asset_exit_times, audit


def assemble_v7_arrays(
    bars: pd.DataFrame,
    active_map: pd.DataFrame,
    panel: pd.DataFrame,
    cbr: pd.DataFrame,
    cftc: pd.DataFrame,
    *,
    contract_observations: pd.DataFrame | None = None,
    sequence_bars: int = V7_SEQUENCE_BARS,
    ssl_horizons: tuple[int, ...] = V7_SSL_HORIZONS,
    precomputed_cftc_scores: pd.DataFrame | None = None,
    source_artifacts: tuple[dict[str, Any], ...] = (),
) -> V7AssemblyResult:
    """Sobiraet real causal arrays i exact-open overlay bez PnL ili train."""
    normalized_active = _normalize_active_map(active_map)
    normalized_panel = _normalize_panel(panel)
    normalized_bars = _normalize_intraday(bars)
    timing = _decision_calendar(normalized_panel)
    overlay_timing, unmodeled_dates, session_audit = _overlay_calendar(
        normalized_panel, normalized_bars
    )
    timing, irregular_audit = _annotate_irregular_model_intervals(
        timing, unmodeled_dates, normalized_active
    )
    assigned_bars = _assign_trade_dates(normalized_bars, timing)
    overlay_assigned_bars = _assign_trade_dates(normalized_bars, overlay_timing)
    active_bars = _join_active_contracts(assigned_bars, normalized_active)
    if active_bars.empty:
        raise ValueError("Posle exact active-contract join ne ostalos' 10m bars")
    observations = (
        _normalize_contract_observations(contract_observations)
        if contract_observations is not None
        else _normalize_contract_observations(
            normalized_active.loc[normalized_active["contract_id"].notna()].rename(
                columns={
                    "effective_date": "trade_date",
                    "contract_id": "canonical_contract_id",
                }
            ).assign(reported_trade_activity=True)
        )
    )
    overlay, overlay_audit = _first_exact_open_overlay(
        overlay_assigned_bars,
        observations,
        normalized_active,
        overlay_timing,
        unmodeled_session_dates=unmodeled_dates,
    )
    features = _intraday_features(active_bars)
    scheduled_times = np.sort(np.unique(_utc_naive_ns(features["timestamp"])))
    scheduled_completion_times = scheduled_times + np.timedelta64(10, "m")
    samples = _sample_rows(
        timing, scheduled_completion_times, overlay, sequence_bars
    )
    intraday, intraday_valid, log_price, bar_times, grid_audit = _grid_arrays(
        features, samples, sequence_bars
    )
    daily_context, daily_valid, daily_audit = _daily_context_arrays(
        normalized_panel,
        normalized_active,
        samples,
        cbr,
        cftc,
        precomputed_cftc_scores,
    )
    (
        supervised_target,
        supervised_valid,
        asset_entry_times,
        asset_exit_times,
        target_audit,
    ) = _supervised_targets(samples, overlay)
    decision_times = samples["decision_at"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(
        dtype="datetime64[ns]"
    )
    entry_times = samples["entry_open_at"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(
        dtype="datetime64[ns]"
    )
    exit_times = samples["exit_open_at"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(
        dtype="datetime64[ns]"
    )
    timing_batch = DecisionTimingBatch(
        bar_times=bar_times,
        decision_times=decision_times,
        entry_open_times=entry_times,
        exit_open_times=exit_times,
    )
    timing_batch.validate()
    asset_valid = intraday_valid.any(axis=2)
    if not asset_valid.any(axis=1).all():
        raise ValueError("Hotya by odin sample ne imeet valid intraday asset")
    arrays = MultiResolutionArrays(
        intraday=intraday,
        intraday_valid=intraday_valid,
        daily_context=daily_context,
        daily_valid=daily_valid,
        asset_valid=asset_valid,
        supervised_target=supervised_target,
        supervised_valid=supervised_valid,
        timing=timing_batch,
    )
    ssl = build_self_supervised_targets(
        log_price,
        np.isfinite(log_price),
        ssl_horizons,
    )
    audit = {
        "schema_version": V7_ASSEMBLY_SCHEMA_VERSION,
        "research_status": "development_only_no_pnl_no_training",
        "protected_from": TEN_MINUTE_PROTECTED_FROM.isoformat(),
        "assets": list(V7_ASSETS),
        "bar_feature_names": list(V7_BAR_FEATURES),
        "daily_feature_names": list(V7_DAILY_FEATURES),
        "sequence_bars": sequence_bars,
        "ssl_horizons": list(ssl_horizons),
        "raw_10m_rows": len(normalized_bars),
        "active_10m_rows": len(active_bars),
        "exact_union_timestamp_count": len(scheduled_times),
        "sample_count": len(samples),
        "sample_first_decision": samples["decision_at"].iloc[0].isoformat(),
        "sample_last_decision": samples["decision_at"].iloc[-1].isoformat(),
        "intraday_valid_fraction": float(intraday_valid.mean()),
        "synthetic_bars_or_forward_fills": 0,
        "bar_cutoff_rule": "factual_end_timestamp_lte_decision_at",
        "scheduled_bucket_cutoff_rule": "timestamp_plus_10_minutes_lte_decision_at",
        "trade_date_assignment": (
            "previous_decision_exclusive_current_decision_inclusive_with_terminal_censor"
        ),
        "sampling_uses_target_availability": False,
        "scalar_execution_time_semantics": (
            "max_observed_asset_time_or_scheduled_placeholder_for_timing_cutoff_only"
        ),
        "entry_time_placeholder_sample_count": int(
            samples["entry_time_placeholder"].sum()
        ),
        "exit_time_placeholder_sample_count": int(
            samples["exit_time_placeholder"].sum()
        ),
        "terminal_post_decision_10m_rows_censored": int(
            normalized_bars["end_timestamp"].gt(
                _decision_at(pd.Timestamp(timing["effective_date"].iloc[-1]))
            ).sum()
        ),
        "forward_additive_adjustment_applied": True,
        "scheduled_grid": grid_audit,
        "factual_session_calendar": session_audit,
        "irregular_intervals": irregular_audit,
        "exact_open_overlay": overlay_audit,
        "daily_context": daily_audit,
        "supervised_target": target_audit,
    }
    return V7AssemblyResult(
        arrays=arrays,
        log_price=log_price,
        asset_entry_open_times=asset_entry_times,
        asset_exit_open_times=asset_exit_times,
        ssl_targets=ssl,
        sample_index=samples.drop(columns="union_window_end").reset_index(drop=True),
        execution_market_overlay=overlay,
        audit=audit,
        source_artifacts=source_artifacts,
    )


def _atomic_write_npz(path: Path, result: V7AssemblyResult) -> None:
    """Atomarno pishet vse arrays odnim compressed NPZ bez pickle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("wb") as stream:
            np.savez_compressed(
                stream,
                intraday=result.arrays.intraday,
                intraday_valid=result.arrays.intraday_valid,
                daily_context=result.arrays.daily_context,
                daily_valid=result.arrays.daily_valid,
                asset_valid=result.arrays.asset_valid,
                supervised_target=result.arrays.supervised_target,
                supervised_valid=result.arrays.supervised_valid,
                log_price=result.log_price,
                asset_entry_open_times=result.asset_entry_open_times.astype(
                    "datetime64[ns]"
                ).astype(np.int64),
                asset_exit_open_times=result.asset_exit_open_times.astype(
                    "datetime64[ns]"
                ).astype(np.int64),
                bar_times=result.arrays.timing.bar_times.astype("datetime64[ns]").astype(np.int64),
                decision_times=result.arrays.timing.decision_times.astype("datetime64[ns]").astype(
                    np.int64
                ),
                entry_open_times=result.arrays.timing.entry_open_times.astype(
                    "datetime64[ns]"
                ).astype(np.int64),
                exit_open_times=result.arrays.timing.exit_open_times.astype(
                    "datetime64[ns]"
                ).astype(np.int64),
                ssl_values=result.ssl_targets.values,
                ssl_valid=result.ssl_targets.valid,
                sample_trade_dates=result.sample_index["trade_date"].to_numpy(
                    dtype="datetime64[ns]"
                ).astype(np.int64),
            )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_parquet(path: Path, frame: pd.DataFrame) -> None:
    """Atomarno pishet exact execution overlay v Zstandard Parquet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def persist_v7_assembly(
    result: V7AssemblyResult,
    data_root: Path,
) -> V7AssemblyArtifactPaths:
    """Pishet content-addressed NPZ, exact-open Parquet i manifest atomarno."""
    output = data_root.resolve() / "processed" / "futures_v7"
    output.mkdir(parents=True, exist_ok=True)
    temporary_arrays = output / ".assembly.pending.npz"
    _atomic_write_npz(temporary_arrays, result)
    arrays_sha = _sha256_file(temporary_arrays)
    arrays_path = output / f"assembly_{arrays_sha[:16]}.npz"
    if arrays_path.exists():
        if _sha256_file(arrays_path) != arrays_sha:
            raise FileExistsError(f"Content-address collision: {arrays_path}")
        temporary_arrays.unlink()
    else:
        temporary_arrays.replace(arrays_path)
    temporary_overlay = output / ".execution_open.pending.parquet"
    _atomic_write_parquet(temporary_overlay, result.execution_market_overlay)
    overlay_sha = _sha256_file(temporary_overlay)
    overlay_path = output / f"execution_open_{overlay_sha[:16]}.parquet"
    if overlay_path.exists():
        if _sha256_file(overlay_path) != overlay_sha:
            raise FileExistsError(f"Content-address collision: {overlay_path}")
        temporary_overlay.unlink()
    else:
        temporary_overlay.replace(overlay_path)
    bundle_sha = hashlib.sha256(
        f"{arrays_sha}:{overlay_sha}".encode("ascii")
    ).hexdigest()
    manifest = {
        "schema_version": V7_ASSEMBLY_SCHEMA_VERSION,
        "research_status": "development_only_no_pnl_no_training",
        "protected_from": TEN_MINUTE_PROTECTED_FROM.isoformat(),
        "arrays": {
            "path": arrays_path.relative_to(data_root.resolve()).as_posix(),
            "bytes": arrays_path.stat().st_size,
            "sha256": arrays_sha,
            "sample_count": len(result.sample_index),
            "intraday_shape": list(result.arrays.intraday.shape),
            "daily_context_shape": list(result.arrays.daily_context.shape),
            "log_price_shape": list(result.log_price.shape),
            "asset_execution_time_shape": list(result.asset_entry_open_times.shape),
            "ssl_shape": list(result.ssl_targets.values.shape),
        },
        "execution_market_overlay": {
            "path": overlay_path.relative_to(data_root.resolve()).as_posix(),
            "rows": len(result.execution_market_overlay),
            "bytes": overlay_path.stat().st_size,
            "sha256": overlay_sha,
            "open_semantics": (
                "first_factual_10m_open_gte_19:00_on_previous_decision_date_"
                "using_augmented_all_asset_main_session_boundaries"
            ),
        },
        "bundle_sha256": bundle_sha,
        "audit": result.audit,
        "source_artifacts": list(result.source_artifacts),
    }
    manifest_payload_sha = hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    manifest["manifest_payload_sha256"] = manifest_payload_sha
    manifest_path = output / f"manifest_{manifest_payload_sha[:16]}.json"
    write_json(manifest_path, manifest)
    return V7AssemblyArtifactPaths(
        arrays_path=arrays_path,
        execution_overlay_path=overlay_path,
        manifest_path=manifest_path,
        arrays_sha256=arrays_sha,
        execution_overlay_sha256=overlay_sha,
    )


def load_v7_training_arrays(
    path: Path,
    *,
    validate_supervised_timing: bool = True,
) -> LoadedV7TrainingArrays:
    """Chitaet NPZ; optional global target-timing check ostavlen dlya staryh callers."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    with np.load(resolved, allow_pickle=False) as payload:
        required = {
            "intraday",
            "intraday_valid",
            "daily_context",
            "daily_valid",
            "asset_valid",
            "supervised_target",
            "supervised_valid",
            "log_price",
            "bar_times",
            "decision_times",
            "entry_open_times",
            "exit_open_times",
            "sample_trade_dates",
            "asset_entry_open_times",
            "asset_exit_open_times",
        }
        if missing := required - set(payload.files):
            raise ValueError(f"V7 NPZ ne soderzhit: {sorted(missing)}")
        timing = DecisionTimingBatch(
            bar_times=payload["bar_times"].astype("datetime64[ns]"),
            decision_times=payload["decision_times"].astype("datetime64[ns]"),
            entry_open_times=payload["entry_open_times"].astype("datetime64[ns]"),
            exit_open_times=payload["exit_open_times"].astype("datetime64[ns]"),
        )
        arrays = MultiResolutionArrays(
            intraday=payload["intraday"],
            intraday_valid=payload["intraday_valid"].astype(bool),
            daily_context=payload["daily_context"],
            daily_valid=payload["daily_valid"].astype(bool),
            asset_valid=payload["asset_valid"].astype(bool),
            supervised_target=payload["supervised_target"],
            supervised_valid=payload["supervised_valid"].astype(bool),
            timing=timing,
        )
        log_price = payload["log_price"].astype(np.float64)
        asset_entry_times = payload["asset_entry_open_times"].astype("datetime64[ns]")
        asset_exit_times = payload["asset_exit_open_times"].astype("datetime64[ns]")
        sample_dates = payload["sample_trade_dates"].astype("datetime64[ns]")
    timing.validate()
    if log_price.shape != arrays.intraday.shape[:3]:
        raise ValueError("V7 NPZ log_price shape ne sovpadaet s intraday")
    if sample_dates.shape != (arrays.intraday.shape[0],):
        raise ValueError("V7 NPZ sample_trade_dates shape ne sovpadaet s samples")
    if asset_entry_times.shape != arrays.supervised_target.shape:
        raise ValueError("V7 NPZ asset entry time shape ne sovpadaet s targets")
    if asset_exit_times.shape != arrays.supervised_target.shape:
        raise ValueError("V7 NPZ asset exit time shape ne sovpadaet s targets")
    if validate_supervised_timing:
        valid_timing = arrays.supervised_valid
        if (
            np.isnat(asset_entry_times[valid_timing]).any()
            or np.isnat(asset_exit_times[valid_timing]).any()
            or (asset_entry_times[valid_timing] >= asset_exit_times[valid_timing]).any()
        ):
            raise ValueError("V7 NPZ valid target imeet nekorrektnye asset execution times")
    return LoadedV7TrainingArrays(
        arrays=arrays,
        log_price=log_price,
        asset_entry_open_times=asset_entry_times,
        asset_exit_open_times=asset_exit_times,
        sample_trade_dates=sample_dates,
    )


def _verified_v5_inputs(
    data_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    """Chitaet panel/map tol'ko iz ih zapechatannogo output audit."""
    audit_path = data_root / "processed" / "futures_v5" / "development_panel_2018_2025_audit.json"
    audit = _read_json(audit_path)
    if audit.get("protected_from") != TEN_MINUTE_PROTECTED_FROM.isoformat():
        raise ValueError("V5 audit ne imeet protected 2026 granicy")
    loaded: dict[str, pd.DataFrame] = {}
    sources: list[dict[str, Any]] = []
    for name in ("panel", "active_contract_map", "contract_observations"):
        record = audit.get("output_artifacts", {}).get(name)
        if not isinstance(record, dict):
            raise ValueError(f"V5 audit ne soderzhit {name}")
        path = Path(str(record["path"])).resolve()
        try:
            path.relative_to(data_root.resolve())
        except ValueError as error:
            raise ValueError(f"V5 artifact vyshel iz data-root: {path}") from error
        if _sha256_file(path) != str(record["sha256"]):
            raise ValueError(f"V5 artifact SHA mismatch: {path}")
        frame = pd.read_parquet(path)
        if len(frame) != int(record["rows"]):
            raise ValueError(f"V5 artifact rows mismatch: {path}")
        loaded[name] = frame
        sources.append(
            {
                "kind": f"futures_v5_{name}",
                "path": path.relative_to(data_root.resolve()).as_posix(),
                "rows": len(frame),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return (
        loaded["panel"],
        loaded["active_contract_map"],
        loaded["contract_observations"],
        sources,
    )


def _verified_information_inputs(
    data_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    """Proveryaet lokal'nye CBR/CFTC development snapshots i ih row counts."""
    cbr_manifest_path = (
        data_root / "processed" / "info_radar" / "cbr-dev-2018-2025-v1" / "manifest.json"
    )
    cbr_manifest = _read_json(cbr_manifest_path)
    cbr_record = cbr_manifest.get("artifacts", {}).get("cbr")
    if not isinstance(cbr_record, dict):
        raise ValueError("CBR manifest ne soderzhit cbr artifact")
    cbr_path = _bounded_path(data_root, str(cbr_record["path"]))
    if _sha256_file(cbr_path) != str(cbr_record["sha256"]):
        raise ValueError("CBR parquet SHA mismatch")
    cbr = pd.read_parquet(cbr_path)
    if len(cbr) != int(cbr_record["rows"]):
        raise ValueError("CBR parquet rows mismatch")
    cftc_root = data_root / "processed" / "info_radar" / "cftc-dev-2018-2025-v1"
    cftc_manifest_path = cftc_root / "manifest.json"
    cftc_manifest = _read_json(cftc_manifest_path)
    if cftc_manifest.get("protected_from") != TEN_MINUTE_PROTECTED_FROM.isoformat():
        raise ValueError("CFTC manifest ne imeet protected 2026 granicy")
    cftc_path = (cftc_root / str(cftc_manifest["processed_path"])).resolve()
    try:
        cftc_path.relative_to(cftc_root.resolve())
    except ValueError as error:
        raise ValueError("CFTC processed path vyshel iz snapshot") from error
    cftc = pd.read_parquet(cftc_path)
    if len(cftc) != int(cftc_manifest["rows"]):
        raise ValueError("CFTC parquet rows mismatch")
    sources = [
        {
            "kind": "cbr_pit_context",
            "path": cbr_path.relative_to(data_root.resolve()).as_posix(),
            "rows": len(cbr),
            "bytes": cbr_path.stat().st_size,
            "sha256": _sha256_file(cbr_path),
            "manifest_sha256": _sha256_file(cbr_manifest_path),
        },
        {
            "kind": "cftc_pit_context",
            "path": cftc_path.relative_to(data_root.resolve()).as_posix(),
            "rows": len(cftc),
            "bytes": cftc_path.stat().st_size,
            "sha256": _sha256_file(cftc_path),
            "manifest_sha256": _sha256_file(cftc_manifest_path),
        },
    ]
    return cbr, cftc, sources


def build_and_persist_real_v7_assembly(project_root: Path) -> V7AssemblyArtifactPaths:
    """Verificiruet vse real sources, sobiraet i pishet dataset bez PnL/train."""
    root = project_root.resolve()
    data_root = root / "data"
    verified_bars = load_verified_ten_minute_bars(data_root, data_root)
    panel, active_map, contract_observations, v5_sources = _verified_v5_inputs(data_root)
    cbr, cftc, information_sources = _verified_information_inputs(data_root)
    dataset_source = {
        "kind": "official_moex_10m_dataset_manifest",
        "path": (
            "processed/futures_v7_10m/"
            "manifest_2018-01-01_2025-12-31.json"
        ),
        "rows": verified_bars.verification_totals["rows"],
        "sha256": verified_bars.dataset_manifest_sha256,
    }
    result = assemble_v7_arrays(
        verified_bars.frame,
        active_map,
        panel,
        cbr,
        cftc,
        contract_observations=contract_observations,
        source_artifacts=(
            dataset_source,
            *verified_bars.source_artifacts,
            *v5_sources,
            *information_sources,
        ),
    )
    return persist_v7_assembly(result, data_root)


__all__ = [
    "LoadedV7TrainingArrays",
    "V7AssemblyArtifactPaths",
    "V7AssemblyResult",
    "V7_EXECUTION_OVERLAY_COLUMNS",
    "VerifiedTenMinuteBars",
    "assemble_v7_arrays",
    "build_and_persist_real_v7_assembly",
    "load_verified_ten_minute_bars",
    "load_v7_training_arrays",
    "persist_v7_assembly",
]
