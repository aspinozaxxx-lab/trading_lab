"""Causal reuse v7 inputov i nezavisimo zapechatannye 5-session v8 metki.

Modul namerenno ne importiruet v7 dataset classes. Arhiv v7 soderzhit legacy
supervised metki, a v8 mozhet materializovat' tol'ko causal model-inputy iz
:data:`V8_CAUSAL_V7_KEYS`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from market_lab.futures_v8.config import (
    V8_ASSETS,
    V8_DAILY_FEATURES,
    V8_DAILY_VOLATILITY_FLOOR,
    V8_PURGE_SESSIONS,
    V8_SSL_HORIZONS,
    V8_TARGET_HORIZON_COMMON_SESSIONS,
)
from market_lab.io_utils import write_json

V8_ASSEMBLY_SCHEMA_VERSION: Final[int] = 1
V8_PROTECTED_HOLDOUT_START: Final[date] = date(2026, 1, 1)
V8_DECISION_TIME: Final[str] = "18:50:00"
V8_EXECUTION_WINDOW_OPEN: Final[str] = "19:20:00"
V8_EXECUTION_WINDOW_CLOSE: Final[str] = "19:30:00"
V8_TIMEZONE: Final[str] = "Europe/Moscow"
V8_MIN_MAIN_SESSION_BUCKETS: Final[int] = 30
V8_EXPECTED_ALL_CONTRACT_PARQUET_FILES: Final[int] = 219
V8_CAUSAL_V7_KEYS: Final[tuple[str, ...]] = (
    "intraday",
    "intraday_valid",
    "daily_context",
    "daily_valid",
    "asset_valid",
    "log_price",
    "bar_times",
    "sample_trade_dates",
    "decision_times",
)
V8_LEGACY_SUPERVISED_V7_KEYS: Final[tuple[str, ...]] = (
    "supervised_target",
    "supervised_valid",
)
_DAILY_VOLATILITY_INDEX: Final[int] = V8_DAILY_FEATURES.index("daily_volatility_20")
_NAT_INT64: Final[int] = np.datetime64("NaT", "ns").astype(np.int64)


@dataclass(frozen=True, slots=True)
class V8CausalInputs:
    """Whitelist causal v7 tensorov i immutable provenance vhodnogo arhiva."""

    intraday: np.ndarray
    intraday_valid: np.ndarray
    daily_context: np.ndarray
    daily_valid: np.ndarray
    asset_valid: np.ndarray
    log_price: np.ndarray
    bar_times: np.ndarray
    sample_trade_dates: np.ndarray
    decision_times: np.ndarray
    source_path: Path
    source_sha256: str
    keys_read: tuple[str, ...] = V8_CAUSAL_V7_KEYS

    @property
    def sample_count(self) -> int:
        """Vozvrashchaet chislo sohranennyh calendar samples bez target-filtracii."""
        return int(self.intraday.shape[0])

    @property
    def asset_count(self) -> int:
        """Vozvrashchaet fixed shirinu cross-section."""
        return int(self.intraday.shape[1])


@dataclass(frozen=True, slots=True)
class V8TargetArrays:
    """Nezavisimye raw/scaled metki i factual per-asset window timestamps."""

    raw_target: np.ndarray
    normalized_target: np.ndarray
    valid: np.ndarray
    ex_ante_daily_volatility_20: np.ndarray
    entry_window_open_times: np.ndarray
    entry_window_close_times: np.ndarray
    exit_window_open_times: np.ndarray
    exit_window_close_times: np.ndarray
    availability_times: np.ndarray
    entry_contract_ids: np.ndarray
    exit_contract_ids: np.ndarray
    entry_capacity_open_times: np.ndarray
    exit_capacity_open_times: np.ndarray
    entry_capacity_volumes: np.ndarray
    exit_capacity_volumes: np.ndarray

    @property
    def target(self) -> np.ndarray:
        """Vozvrashchaet normalized supervised target dlya v8 training."""
        return self.normalized_target

    @property
    def target_mask(self) -> np.ndarray:
        """Vozvrashchaet valid target mask bez udaleniya samples."""
        return self.valid


@dataclass(frozen=True, slots=True)
class V8AssemblyResult:
    """Obedinyaet causal v7 inputy i metki iz primary factual candles."""

    inputs: V8CausalInputs
    targets: V8TargetArrays
    audit: dict[str, Any]
    source_artifacts: tuple[dict[str, Any], ...]

    @property
    def inference_asset_valid(self) -> np.ndarray:
        """Vozvrashchaet tol'ko D-dostupnuyu asset mask bez ex-post target rollov."""
        return self.inputs.asset_valid


@dataclass(frozen=True, slots=True)
class V8AssemblyArtifactPaths:
    """Content-addressed puti persisted v8 massiva i manifesta."""

    arrays_path: Path
    manifest_path: Path
    arrays_sha256: str


@dataclass(frozen=True, slots=True)
class V8FoldScope:
    """Purged train-indeksy i exclusive effective cutoff odnogo fold."""

    sample_indices: np.ndarray
    effective_cutoff: np.datetime64
    purge_sessions: int = V8_PURGE_SESSIONS


@dataclass(frozen=True, slots=True)
class V8SourceFileProof:
    """Opisivaet odin byte-exact source file iz sealed v7 manifesta."""

    kind: str
    path: Path
    bytes: int
    sha256: str
    rows: int | None = None


@dataclass(frozen=True, slots=True)
class V8VerifiedSourceProvenance:
    """Peredaet real source chain dlya povtornoi byte-proverki pered assembly."""

    data_root: Path
    top_manifest: V8SourceFileProof
    all_contract_parquets: tuple[V8SourceFileProof, ...]
    active_contract_map: V8SourceFileProof


@dataclass(frozen=True, slots=True)
class _V8CalendarEvidence:
    """Hranit calendar dates i ih proverennyi ili fixture-only istochnik."""

    verified_common_session_dates: object | None
    unmodeled_factual_session_dates: object | None
    source: str
    source_sha256: str | None
    include_derived_boundaries: bool


def _sha256_file(path: Path) -> str:
    """Hashiruet exact bity bez text decode ili newline normalizacii."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _resolved_proof_path(proof: V8SourceFileProof, data_root: Path) -> tuple[Path, str]:
    """Razreshaet proof path strogo vnutri data root i vozvrashchaet relative POSIX."""
    if not isinstance(proof.path, Path):
        raise TypeError("Source proof path dolzhen byt' pathlib.Path")
    root = data_root.resolve()
    candidate = proof.path if proof.path.is_absolute() else root / proof.path
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(f"Source proof path vne data root: {resolved}") from error
    return resolved, relative


def _verify_file_proof(proof: V8SourceFileProof, data_root: Path) -> dict[str, Any]:
    """Povtorno proveriaet size i SHA-256 odnogo source file po ego real baitam."""
    if not proof.kind.strip():
        raise ValueError("Source proof kind ne mozhet byt' pustym")
    if not isinstance(proof.bytes, int) or isinstance(proof.bytes, bool) or proof.bytes < 0:
        raise ValueError("Source proof bytes dolzhen byt' neotricatel'nym int")
    if not re.fullmatch(r"[0-9a-f]{64}", proof.sha256):
        raise ValueError("Source proof sha256 dolzhen byt' lowercase hex64")
    if proof.rows is not None and (
        not isinstance(proof.rows, int) or isinstance(proof.rows, bool) or proof.rows < 0
    ):
        raise ValueError("Source proof rows dolzhen byt' neotricatel'nym int ili None")
    path, relative = _resolved_proof_path(proof, data_root)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != proof.bytes:
        raise ValueError(f"Source proof bytes ne sovpali: {relative}")
    if _sha256_file(path) != proof.sha256:
        raise ValueError(f"Source proof SHA-256 ne sovpal: {relative}")
    record: dict[str, Any] = {
        "id": f"{proof.kind}:{relative}",
        "kind": proof.kind,
        "path": relative,
        "bytes": proof.bytes,
        "sha256": proof.sha256,
    }
    if proof.rows is not None:
        record["rows"] = proof.rows
    return record


def _proof_matches_manifest_record(
    proof_record: dict[str, Any],
    manifest_record: dict[str, Any],
) -> bool:
    """Sravnivaet exact path/bytes/SHA/rows proof s zapis'yu top manifesta."""
    fields = ("kind", "path", "bytes", "sha256", "rows")
    return all(proof_record.get(field) == manifest_record.get(field) for field in fields)


def verify_v8_source_provenance(
    provenance: V8VerifiedSourceProvenance,
    *,
    v7_npz_path: Path,
) -> tuple[tuple[dict[str, Any], ...], _V8CalendarEvidence]:
    """Proveriaet top manifest, 219 parquet, active map i izvlekaet calendar proof."""
    data_root = provenance.data_root.resolve()
    if provenance.top_manifest.kind != "futures_v7_top_manifest":
        raise ValueError("Top manifest proof imeet nevernyi kind")
    top_record = _verify_file_proof(provenance.top_manifest, data_root)
    top_path, _ = _resolved_proof_path(provenance.top_manifest, data_root)
    payload = json.loads(top_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("V7 top manifest dolzhen byt' JSON object")
    claimed_payload_sha = payload.get("manifest_payload_sha256")
    if not isinstance(claimed_payload_sha, str):
        raise ValueError("V7 top manifest ne soderzhit manifest_payload_sha256")
    payload_without_hash = dict(payload)
    payload_without_hash.pop("manifest_payload_sha256", None)
    calculated_payload_sha = hashlib.sha256(
        json.dumps(
            payload_without_hash,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    if calculated_payload_sha != claimed_payload_sha:
        raise ValueError("V7 top manifest payload SHA-256 ne sovpal")
    if payload.get("protected_from") != V8_PROTECTED_HOLDOUT_START.isoformat():
        raise ValueError("V7 top manifest ne dokazyvaet protected 2026 boundary")
    artifacts = payload.get("source_artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("V7 top manifest ne soderzhit source_artifacts list")
    parquet_manifest_records = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("kind") == "official_moex_10m_parquet"
    ]
    if len(parquet_manifest_records) != V8_EXPECTED_ALL_CONTRACT_PARQUET_FILES:
        raise ValueError("V7 top manifest dolzhen soderzhat' rovno 219 all-contract parquet")
    if len(provenance.all_contract_parquets) != V8_EXPECTED_ALL_CONTRACT_PARQUET_FILES:
        raise ValueError("V8 provenance dolzhen peredat' rovno 219 all-contract parquet proof")
    parquet_proofs = tuple(
        _verify_file_proof(proof, data_root) for proof in provenance.all_contract_parquets
    )
    if any(record["kind"] != "official_moex_10m_parquet" for record in parquet_proofs):
        raise ValueError("All-contract proof imeet nevernyi kind")
    proof_by_path = {record["path"]: record for record in parquet_proofs}
    if len(proof_by_path) != len(parquet_proofs):
        raise ValueError("All-contract provenance soderzhit duplicate path")
    manifest_by_path = {str(record.get("path")): record for record in parquet_manifest_records}
    if len(manifest_by_path) != len(parquet_manifest_records):
        raise ValueError("V7 top manifest soderzhit duplicate parquet path")
    if set(proof_by_path) != set(manifest_by_path):
        raise ValueError("All-contract proof paths ne sovpali s V7 top manifest")
    for path, proof_record in proof_by_path.items():
        if not _proof_matches_manifest_record(proof_record, manifest_by_path[path]):
            raise ValueError(f"All-contract proof ne sovpal s manifest record: {path}")
    active_record = _verify_file_proof(provenance.active_contract_map, data_root)
    if active_record["kind"] != "futures_v5_active_contract_map":
        raise ValueError("Active-map proof imeet nevernyi kind")
    active_manifest_records = [
        artifact
        for artifact in artifacts
        if isinstance(artifact, dict) and artifact.get("kind") == "futures_v5_active_contract_map"
    ]
    if len(active_manifest_records) != 1 or not _proof_matches_manifest_record(
        active_record, active_manifest_records[0]
    ):
        raise ValueError("Active-map byte proof ne sovpal s V7 top manifest")
    arrays = payload.get("arrays")
    if not isinstance(arrays, dict):
        raise ValueError("V7 top manifest ne soderzhit arrays proof")
    resolved_npz = v7_npz_path.resolve()
    expected_npz = (data_root / str(arrays.get("path", ""))).resolve()
    if resolved_npz != expected_npz:
        raise ValueError("V7 NPZ path ne sovpal s top manifest")
    if resolved_npz.stat().st_size != int(arrays.get("bytes", -1)):
        raise ValueError("V7 NPZ bytes ne sovpali s top manifest")
    if _sha256_file(resolved_npz) != arrays.get("sha256"):
        raise ValueError("V7 NPZ SHA-256 ne sovpal s top manifest")
    calendar = payload.get("audit", {}).get("factual_session_calendar", {})
    unmodeled = calendar.get("unmodeled_all_asset_main_session_dates")
    if (
        not isinstance(unmodeled, list)
        or calendar.get("source")
        != "verified_10m_distinct_scheduled_buckets_10:00_to_18:50_msk"
        or calendar.get("unmodeled_all_asset_main_session_count") != len(unmodeled)
    ):
        raise ValueError("V7 top manifest ne soderzhit cryptographically bound calendar proof")
    evidence = _V8CalendarEvidence(
        verified_common_session_dates=None,
        unmodeled_factual_session_dates=tuple(unmodeled),
        source="cryptographically_verified_v7_top_manifest_calendar",
        source_sha256=provenance.top_manifest.sha256,
        include_derived_boundaries=True,
    )
    records = (top_record, *parquet_proofs, active_record)
    return records, evidence


def assert_v8_pre_io_date_range(start: date, end: date) -> None:
    """Otkazyvaet protected 2026 daty prezhde chem modul otkroet input artifact."""
    if not isinstance(start, date) or not isinstance(end, date):
        raise TypeError("V8 pre-I/O dates dolzhny byt' datetime.date")
    if start > end:
        raise ValueError("V8 pre-I/O range imeet start posle end")
    if end >= V8_PROTECTED_HOLDOUT_START:
        raise ValueError("V8 pre-I/O guard zapreshchaet 2026 holdout")


def _to_datetime64_ns(
    values: np.ndarray,
    label: str,
    *,
    allow_nat: bool = False,
    allow_protected: bool = False,
) -> np.ndarray:
    """Normalizuet timestamps; explicit override nuzhen dlia pre-slice target timing."""
    converted = np.asarray(values).astype("datetime64[ns]")
    if not allow_nat and np.isnat(converted).any():
        raise ValueError(f"{label} soderzhit NaT")
    protected = np.datetime64(V8_PROTECTED_HOLDOUT_START, "ns")
    if not allow_protected and converted[~np.isnat(converted)].size and (
        converted[~np.isnat(converted)] >= protected
    ).any():
        raise ValueError(f"{label} pytayetsya prochitat' protected 2026")
    return converted


def _validate_v8_causal_inputs(inputs: V8CausalInputs) -> None:
    """Proveryaet v7 tensor forms i timing bez chteniya legacy target members."""
    intraday = np.asarray(inputs.intraday)
    bar_valid = np.asarray(inputs.intraday_valid, dtype=bool)
    daily = np.asarray(inputs.daily_context)
    daily_valid = np.asarray(inputs.daily_valid, dtype=bool)
    assets = np.asarray(inputs.asset_valid, dtype=bool)
    prices = np.asarray(inputs.log_price)
    bars = _to_datetime64_ns(inputs.bar_times, "v7 bar_times")
    dates = _to_datetime64_ns(inputs.sample_trade_dates, "v7 sample_trade_dates")
    decisions = _to_datetime64_ns(inputs.decision_times, "v7 decision_times")
    if intraday.ndim != 4:
        raise ValueError("V7 causal intraday dolzhen byt' [samples, assets, bars, features]")
    samples, assets_count, bars_count, _ = intraday.shape
    if assets_count != len(V8_ASSETS):
        raise ValueError("V7 causal asset width ne sootvetstvuet v8 universe")
    if bar_valid.shape != intraday.shape[:3] or prices.shape != intraday.shape[:3]:
        raise ValueError("V7 intraday mask ili log_price imeet nevernuyu formu")
    if daily.shape[:2] != intraday.shape[:2] or daily_valid.shape != daily.shape:
        raise ValueError("V7 daily context ili mask imeet nevernuyu formu")
    if daily.shape[2] <= _DAILY_VOLATILITY_INDEX:
        raise ValueError("V7 daily context ne soderzhit daily_volatility_20")
    if assets.shape != intraday.shape[:2]:
        raise ValueError("V7 asset_valid imeet nevernuyu formu")
    if bars.shape != (samples, bars_count):
        raise ValueError("V7 bar_times ne sovpadaet s intraday")
    if dates.shape != (samples,) or decisions.shape != (samples,):
        raise ValueError("V7 sample dates ili decision times ne sovpadayut s samples")
    if (np.diff(bars, axis=1) <= np.timedelta64(0, "ns")).any():
        raise ValueError("V7 bar_times dolzhny strogo vozrastat'")
    if (bars > decisions[:, None]).any():
        raise ValueError("V7 intraday bar posle svoego D18:50 decision")
    if (np.diff(dates) <= np.timedelta64(0, "ns")).any():
        raise ValueError("V7 sample trade dates dolzhny byt' strogo vozrastayushchimi")
    if (np.diff(decisions) <= np.timedelta64(0, "ns")).any():
        raise ValueError("V7 decision times dolzhny byt' strogo vozrastayushchimi")
    local_decisions = pd.DatetimeIndex(decisions).tz_localize("UTC").tz_convert(V8_TIMEZONE)
    if not np.all(local_decisions.strftime("%H:%M:%S") == V8_DECISION_TIME):
        raise ValueError("V8 trebuet D18:50 Moscow decision times")
    local_dates = local_decisions.tz_localize(None).normalize().to_numpy("datetime64[ns]")
    if not np.array_equal(local_dates, dates):
        raise ValueError("V7 sample trade_date ne sovpadaet s local decision D")


def _daily_row_complete_at_decision(inputs: V8CausalInputs) -> np.ndarray:
    """Dokazyvaet per-asset factual D18:50 bar dlya D-known daily context."""
    bars = _to_datetime64_ns(inputs.bar_times, "v7 bar_times")
    decisions = _to_datetime64_ns(inputs.decision_times, "v7 decision_times")
    exact_decision_bar = bars == decisions[:, None]
    intraday_valid = np.asarray(inputs.intraday_valid, dtype=bool)
    return (intraday_valid & exact_decision_bar[:, None, :]).any(axis=2)


def load_v7_causal_inputs(
    path: Path,
    *,
    source_start: date = date(2018, 1, 1),
    source_end: date = date(2025, 12, 31),
) -> V8CausalInputs:
    """Chitaet tol'ko sealed causal v7 keys i nikogda ne materializuet starye metki."""
    assert_v8_pre_io_date_range(source_start, source_end)
    resolved = path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    source_sha256 = _sha256_file(resolved)
    # Vyzov v7 loader zdes' nel'zya: on obyazatel'no materializuet legacy metki.
    with np.load(resolved, allow_pickle=False) as payload:
        missing = set(V8_CAUSAL_V7_KEYS) - set(payload.files)
        if missing:
            raise ValueError(f"V7 NPZ ne soderzhit causal keys: {sorted(missing)}")
        materialized = {key: payload[key] for key in V8_CAUSAL_V7_KEYS}
    inputs = V8CausalInputs(
        intraday=np.asarray(materialized["intraday"], dtype=np.float32),
        intraday_valid=np.asarray(materialized["intraday_valid"], dtype=bool),
        daily_context=np.asarray(materialized["daily_context"], dtype=np.float32),
        daily_valid=np.asarray(materialized["daily_valid"], dtype=bool),
        asset_valid=np.asarray(materialized["asset_valid"], dtype=bool),
        log_price=np.asarray(materialized["log_price"], dtype=np.float64),
        bar_times=np.asarray(materialized["bar_times"]).astype("datetime64[ns]"),
        sample_trade_dates=np.asarray(materialized["sample_trade_dates"]).astype(
            "datetime64[ns]"
        ),
        decision_times=np.asarray(materialized["decision_times"]).astype("datetime64[ns]"),
        source_path=resolved,
        source_sha256=source_sha256,
    )
    _validate_v8_causal_inputs(inputs)
    return inputs


def _frame_sha256(frame: pd.DataFrame) -> str:
    """Hashiruet normalized in-memory source stroki dlya manifest provenance."""
    ordered = frame.sort_index(axis=1).sort_values(list(frame.columns), kind="stable").reset_index(
        drop=True
    )
    digest = hashlib.sha256()
    digest.update("|".join(ordered.columns).encode("utf-8"))
    digest.update("|".join(str(dtype) for dtype in ordered.dtypes).encode("ascii"))
    digest.update(pd.util.hash_pandas_object(ordered, index=False).to_numpy().tobytes())
    return digest.hexdigest()


def _utc_series(frame: pd.DataFrame, column: str, label: str) -> pd.Series:
    """Privodit raw candle timestamp field k UTC i zapreshchaet 2026."""
    parsed = pd.to_datetime(frame[column], errors="raise", utc=True)
    if parsed.isna().any():
        raise ValueError(f"{label} soderzhit NaT")
    if parsed.ge(pd.Timestamp("2026-01-01T00:00:00Z")).any():
        raise ValueError(f"{label} pytayetsya prochitat' protected 2026")
    return parsed


def _asset_source_column(frame: pd.DataFrame) -> str:
    """Predpochitaet logical symbols, potomu chto raw RI mozhet imet' RTS code."""
    if "logical_symbol" in frame.columns:
        return "logical_symbol"
    if "asset_code" in frame.columns:
        return "asset_code"
    raise ValueError("All-contract 10m ne soderzhit logical_symbol ili asset_code")


def _contract_source_column(frame: pd.DataFrame) -> str:
    """Vozvrashchaet exact contract identifier iz all-contract candles."""
    if "canonical_contract_id" in frame.columns:
        return "canonical_contract_id"
    if "contract_id" in frame.columns:
        return "contract_id"
    raise ValueError("All-contract 10m ne soderzhit canonical_contract_id")


def _normalize_all_contract_candles(candles: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet factual all-contract 10m stroki bez fill propushchennyh candles."""
    required = {"timestamp", "end_timestamp", "open", "high", "low", "close", "volume"}
    if missing := required - set(candles.columns):
        raise ValueError(f"All-contract 10m ne soderzhit: {sorted(missing)}")
    asset_column = _asset_source_column(candles)
    contract_column = _contract_source_column(candles)
    frame = candles.copy()
    frame["timestamp"] = _utc_series(frame, "timestamp", "all-contract timestamp")
    frame["end_timestamp"] = _utc_series(frame, "end_timestamp", "all-contract end_timestamp")
    if frame["end_timestamp"].lt(frame["timestamp"]).any():
        raise ValueError("All-contract 10m end_timestamp ran'she timestamp")
    frame["asset_code"] = frame[asset_column].astype("string").str.upper()
    frame["contract_id"] = frame[contract_column].astype("string")
    if frame["asset_code"].isna().any() or frame["contract_id"].isna().any():
        raise ValueError("All-contract 10m imeet pustoi asset ili contract")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "is_active_contract" in frame.columns:
        active = frame["is_active_contract"].fillna(False).astype(bool)
        frame = frame.loc[active].copy()
    if frame.duplicated(["timestamp", "asset_code", "contract_id"]).any():
        raise ValueError("All-contract 10m imeet duplicate exact candle")
    return frame.sort_values(["timestamp", "asset_code", "contract_id"], ignore_index=True)


def _normalize_active_map(active_map: pd.DataFrame) -> pd.DataFrame:
    """Normalizuet active contract map dlya kazhdoi effective common session."""
    required = {"effective_date", "asset_code"}
    if missing := required - set(active_map.columns):
        raise ValueError(f"Active map ne soderzhit: {sorted(missing)}")
    contract_column = (
        "contract_id" if "contract_id" in active_map.columns else "canonical_contract_id"
    )
    if contract_column not in active_map.columns:
        raise ValueError("Active map ne soderzhit contract_id")
    frame = active_map.copy()
    raw_dates = pd.to_datetime(frame["effective_date"], errors="raise")
    if getattr(raw_dates.dt, "tz", None) is not None:
        raw_dates = raw_dates.dt.tz_convert(V8_TIMEZONE).dt.tz_localize(None)
    frame["effective_date"] = raw_dates.dt.normalize()
    if frame["effective_date"].ge(pd.Timestamp(V8_PROTECTED_HOLDOUT_START)).any():
        raise ValueError("Active map pytayetsya prochitat' protected 2026")
    frame["asset_code"] = frame["asset_code"].astype("string").str.upper()
    raw_contract = frame[contract_column].astype("string")
    null_contract = raw_contract.isna() | raw_contract.str.strip().eq("").fillna(True)
    if null_contract.any():
        required_warmup = {
            "action",
            "reason",
            "roll",
            "plan_tradable",
            "expiry_horizon_censored",
            "carry_unfilled",
            "execution_open_available",
            "feature_input_valid",
            "chain_id",
            "forward_additive_adjustment",
        }
        if missing_warmup := required_warmup - set(frame.columns):
            raise ValueError(
                "Null contract bez polnoi initial_warmup shemy: "
                f"{sorted(missing_warmup)}"
            )
        warmup = frame.loc[null_contract]
        boolean_false = (
            ~warmup[
                [
                    "roll",
                    "plan_tradable",
                    "expiry_horizon_censored",
                    "carry_unfilled",
                    "execution_open_available",
                    "feature_input_valid",
                ]
            ]
            .fillna(True)
            .astype(bool)
        ).all(axis=None)
        exact_initial_warmup = (
            len(warmup) == len(V8_ASSETS)
            and set(warmup["asset_code"].dropna().astype(str)) == set(V8_ASSETS)
            and warmup["effective_date"].nunique() == 1
            and warmup["effective_date"].iloc[0] == frame["effective_date"].min()
            and warmup["action"].astype("string").eq("flat").all()
            and warmup["reason"].astype("string").eq("initial_warmup").all()
            and bool(boolean_false)
            and pd.to_numeric(warmup["chain_id"], errors="coerce").eq(0).all()
            and pd.to_numeric(
                warmup["forward_additive_adjustment"], errors="coerce"
            ).eq(0.0).all()
        )
        if not exact_initial_warmup:
            raise ValueError("Null contract razreshen tol'ko dlya exact initial_warmup rows")
        frame = frame.loc[~null_contract].copy()
        raw_contract = frame[contract_column].astype("string")
    frame["contract_id"] = raw_contract
    if "is_active_contract" in frame.columns:
        frame = frame.loc[frame["is_active_contract"].fillna(False).astype(bool)].copy()
    if frame.duplicated(["effective_date", "asset_code"]).any():
        raise ValueError("Active map imeet duplicate effective_date/asset")
    source_carry_priced = (
        frame["carry_priced"].copy() if "carry_priced" in frame.columns else None
    )
    frame["carry_priced"] = True
    if source_carry_priced is not None:
        frame["carry_priced"] &= source_carry_priced.fillna(False).astype(bool)
    if "unpriced_carry" in frame.columns:
        frame["carry_priced"] &= ~frame["unpriced_carry"].fillna(True).astype(bool)
    if "is_unpriced_carry" in frame.columns:
        frame["carry_priced"] &= ~frame["is_unpriced_carry"].fillna(True).astype(bool)
    for column in ("is_carry_priced", "carry_available"):
        if column in active_map.columns:
            frame["carry_priced"] &= frame[column].fillna(False).astype(bool)
    if "carry_unfilled" in active_map.columns:
        frame["carry_priced"] &= ~frame["carry_unfilled"].fillna(True).astype(bool)
    for column in (
        "plan_tradable",
        "execution_open_available",
        "feature_input_valid",
        "ohlc_complete",
    ):
        if column in active_map.columns:
            frame["carry_priced"] &= frame[column].fillna(False).astype(bool)
    if "forward_additive_adjustment" in frame.columns:
        adjustment = pd.to_numeric(frame["forward_additive_adjustment"], errors="coerce")
        frame["carry_priced"] &= np.isfinite(adjustment)
    if frame["asset_code"].isna().any() or frame["contract_id"].isna().any():
        raise ValueError("Active map imeet pustoi asset ili contract")
    return frame.sort_values(["effective_date", "asset_code"], ignore_index=True)


def _normalize_session_dates(
    values: object,
    label: str,
) -> pd.DatetimeIndex:
    """Normalizuet explicit factual common-session daty bez 2026 ili povtorov."""
    parsed = pd.DatetimeIndex(pd.to_datetime(values, errors="raise"))
    if parsed.tz is not None:
        parsed = parsed.tz_convert(V8_TIMEZONE).tz_localize(None)
    normalized = parsed.normalize()
    if normalized.has_duplicates or not normalized.is_monotonic_increasing:
        raise ValueError(f"{label} dolzhen byt' unikal'nym i strogo vozrastayushchim")
    if (normalized >= pd.Timestamp(V8_PROTECTED_HOLDOUT_START)).any():
        raise ValueError(f"{label} pytayetsya prochitat' protected 2026")
    return normalized


def _derive_strong_common_session_dates(candles: pd.DataFrame) -> pd.DatetimeIndex:
    """Ishchet tol'ko dokazannye all-asset main sessions v polnom 10m istochnike."""
    local = candles["timestamp"].dt.tz_convert(V8_TIMEZONE)
    local_dates = local.dt.tz_localize(None).dt.normalize()
    seconds = local.dt.hour * 3600 + local.dt.minute * 60 + local.dt.second
    main = (
        local_dates.dt.dayofweek.lt(5)
        & seconds.ge(10 * 3600)
        & seconds.le(18 * 3600 + 40 * 60)
    )
    if not main.any():
        return pd.DatetimeIndex([], dtype="datetime64[ns]")
    counts = (
        pd.DataFrame(
            {
                "session_date": local_dates.loc[main].to_numpy(),
                "asset_code": candles.loc[main, "asset_code"].to_numpy(),
                "timestamp": candles.loc[main, "timestamp"].to_numpy(),
            }
        )
        .groupby(["session_date", "asset_code"], observed=True)["timestamp"]
        .nunique()
        .unstack(fill_value=0)
        .reindex(columns=list(V8_ASSETS), fill_value=0)
    )
    return pd.DatetimeIndex(counts.index[counts.ge(V8_MIN_MAIN_SESSION_BUCKETS).all(axis=1)])


def _session_calendar_proof(
    inputs: V8CausalInputs,
    candles: pd.DataFrame,
    evidence: _V8CalendarEvidence | None,
) -> tuple[pd.DatetimeIndex, bool, dict[str, Any], dict[str, Any]]:
    """Stroit proverennyi common-session kalendar ili fail-closed mask osnovu."""
    sample_dates = pd.DatetimeIndex(
        _to_datetime64_ns(inputs.sample_trade_dates, "v7 sample_trade_dates")
    )
    derived = _derive_strong_common_session_dates(candles)
    verified_common_session_dates = (
        None if evidence is None else evidence.verified_common_session_dates
    )
    unmodeled_factual_session_dates = (
        None if evidence is None else evidence.unmodeled_factual_session_dates
    )
    explicit_unmodeled = (
        None
        if unmodeled_factual_session_dates is None
        else _normalize_session_dates(
            unmodeled_factual_session_dates,
            "unmodeled_factual_session_dates",
        )
    )
    if verified_common_session_dates is not None:
        factual = _normalize_session_dates(
            verified_common_session_dates,
            "verified_common_session_dates",
        )
        source = (
            "fixture_explicit_common_session_dates" if evidence is None else evidence.source
        )
        proven = True
    elif explicit_unmodeled is not None:
        factual = pd.DatetimeIndex(sample_dates.union(explicit_unmodeled)).sort_values()
        source = (
            "fixture_sample_calendar_plus_unmodeled_dates"
            if evidence is None
            else evidence.source
        )
        proven = True
    elif len(derived) and sample_dates.isin(derived).all():
        factual = derived
        source = "derived_strong_all_asset_main_session_evidence"
        proven = True
    else:
        factual = pd.DatetimeIndex([], dtype="datetime64[ns]")
        source = "unproven_no_verified_or_complete_main_session_evidence"
        proven = False
    if explicit_unmodeled is not None and proven:
        factual = pd.DatetimeIndex(factual.union(explicit_unmodeled)).sort_values()
    if evidence is not None and evidence.include_derived_boundaries and proven:
        factual = pd.DatetimeIndex(factual.union(derived)).sort_values()
    factual_hash = hashlib.sha256(
        factual.to_numpy(dtype="datetime64[ns]").astype(np.int64).tobytes()
    ).hexdigest()
    audit = {
        "proven": proven,
        "source": source,
        "factual_common_session_count": len(factual),
        "derived_strong_main_session_count": len(derived),
        "explicit_unmodeled_factual_session_count": (
            None if explicit_unmodeled is None else len(explicit_unmodeled)
        ),
        "explicit_unmodeled_factual_session_dates": (
            None
            if explicit_unmodeled is None
            else [timestamp.date().isoformat() for timestamp in explicit_unmodeled]
        ),
        "minimum_distinct_main_session_buckets_per_asset": V8_MIN_MAIN_SESSION_BUCKETS,
        "factual_common_session_sha256": factual_hash,
        "calendar_source_sha256": None if evidence is None else evidence.source_sha256,
    }
    artifact = {
        "id": f"factual_common_session_calendar:{factual_hash}",
        "kind": "factual_common_session_calendar",
        "rows": len(factual),
        "sha256": factual_hash,
        "provenance": source,
        "source_sha256": None if evidence is None else evidence.source_sha256,
    }
    return factual, proven, audit, artifact


def _expected_window_open(decision_time: np.datetime64) -> np.datetime64:
    """Mapit exact D18:50 v sealed 19:20 execution-window opening timestamp."""
    local = pd.Timestamp(decision_time).tz_localize("UTC").tz_convert(V8_TIMEZONE)
    if local.strftime("%H:%M:%S") != V8_DECISION_TIME:
        raise ValueError("V8 execution window trebuet D18:50 decision")
    expected = local + pd.Timedelta(minutes=30)
    return np.datetime64(expected.tz_convert("UTC").tz_localize(None), "ns")


def _candle_is_completed_ohlcv(candle: pd.Series, expected_open: np.datetime64) -> bool:
    """Proveryaet, chto exact 19:20 candle factual zakonchila polnoe 10m window."""
    values = candle[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or values[4] <= 0.0 or (values[:4] <= 0.0).any():
        return False
    if values[2] > min(values[0], values[3]) or values[1] < max(values[0], values[3]):
        return False
    open_timestamp = pd.Timestamp(candle["timestamp"]).tz_convert("UTC").tz_localize(None)
    open_at = np.datetime64(open_timestamp, "ns")
    close_at = np.datetime64(
        pd.Timestamp(candle["end_timestamp"]).tz_convert("UTC").tz_localize(None), "ns"
    )
    expected_close = expected_open + np.timedelta64(10, "m")
    return (
        open_at == expected_open
        and close_at > open_at
        and close_at <= expected_close
    )


def _date_key(value: np.datetime64) -> pd.Timestamp:
    """Stroit normalized local-naive map key iz v7 sample trade date."""
    return pd.Timestamp(value).normalize()


def _empty_time_matrix(samples: int, assets: int) -> np.ndarray:
    """Sozdaet explicit NaT timing output bez object dtype."""
    return np.full((samples, assets), np.datetime64("NaT"), dtype="datetime64[ns]")


def build_v8_targets(
    inputs: V8CausalInputs,
    all_contract_candles: pd.DataFrame,
    active_map: pd.DataFrame,
    *,
    calendar_evidence: _V8CalendarEvidence | None = None,
) -> tuple[V8TargetArrays, dict[str, Any], tuple[dict[str, Any], ...]]:
    """Stroit no-roll five-common-session metki iz factual 19:20--19:30 bars.

    Target-calendar ispol'zuet sohranennuyu v7 factual common-session
    posledovatel'nost'. Dlya decision ``i`` entry prinadlezhit effective session
    ``i + 1``, a exit -- effective session ``i + 6``. Poetomu factual execution
    candles nahodyatsya na decision dates sootvetstvenno ``i`` i ``i + 5``.
    """
    _validate_v8_causal_inputs(inputs)
    candles = _normalize_all_contract_candles(all_contract_candles)
    active = _normalize_active_map(active_map)
    factual_calendar, calendar_proven, calendar_audit, calendar_artifact = _session_calendar_proof(
        inputs,
        candles,
        calendar_evidence,
    )
    samples = inputs.sample_count
    assets_count = inputs.asset_count
    raw = np.zeros((samples, assets_count), dtype=np.float32)
    normalized = np.zeros_like(raw)
    valid = np.zeros((samples, assets_count), dtype=bool)
    volatility = np.zeros_like(raw)
    entry_open = _empty_time_matrix(samples, assets_count)
    entry_close = _empty_time_matrix(samples, assets_count)
    exit_open = _empty_time_matrix(samples, assets_count)
    exit_close = _empty_time_matrix(samples, assets_count)
    availability = _empty_time_matrix(samples, assets_count)
    entry_contract_ids = np.full((samples, assets_count), "", dtype="U128")
    exit_contract_ids = np.full((samples, assets_count), "", dtype="U128")
    entry_capacity_open = _empty_time_matrix(samples, assets_count)
    exit_capacity_open = _empty_time_matrix(samples, assets_count)
    entry_capacity_volume = np.zeros((samples, assets_count), dtype=np.float32)
    exit_capacity_volume = np.zeros((samples, assets_count), dtype=np.float32)
    active_lookup = active.set_index(["effective_date", "asset_code"])
    candle_lookup = candles.set_index(
        ["timestamp", "asset_code", "contract_id"],
        drop=False,
    )
    daily_vol = np.asarray(inputs.daily_context, dtype=np.float64)[..., _DAILY_VOLATILITY_INDEX]
    daily_vol_valid = np.asarray(inputs.daily_valid, dtype=bool)[..., _DAILY_VOLATILITY_INDEX]
    daily_row_complete = _daily_row_complete_at_decision(inputs)
    reasons = {
        "insufficient_tail": 0,
        "missing_active_map": 0,
        "unpriced_carry": 0,
        "contract_change_or_roll": 0,
        "missing_or_incomplete_window": 0,
        "unknown_d_daily_volatility_20": 0,
        "daily_row_not_proven_complete_at_d18_50": 0,
        "irregular_or_unproven_common_session_horizon": 0,
        "missing_or_nonpositive_capacity_volume_19_00": 0,
    }
    dates = _to_datetime64_ns(inputs.sample_trade_dates, "v7 sample_trade_dates")
    decisions = _to_datetime64_ns(inputs.decision_times, "v7 decision_times")
    for sample_index in range(samples):
        if sample_index + V8_TARGET_HORIZON_COMMON_SESSIONS >= samples:
            reasons["insufficient_tail"] += assets_count
            continue
        entry_expected_open = _expected_window_open(decisions[sample_index])
        exit_decision_index = sample_index + V8_TARGET_HORIZON_COMMON_SESSIONS
        exit_expected_open = _expected_window_open(decisions[exit_decision_index])
        expected_availability = exit_expected_open + np.timedelta64(10, "m")
        availability[sample_index, :] = expected_availability
        if not calendar_proven:
            reasons["irregular_or_unproven_common_session_horizon"] += assets_count
            continue
        entry_decision_date = _date_key(dates[sample_index])
        exit_decision_date = _date_key(dates[exit_decision_index])
        if (
            entry_decision_date not in factual_calendar
            or exit_decision_date not in factual_calendar
        ):
            reasons["irregular_or_unproven_common_session_horizon"] += assets_count
            continue
        entry_position = factual_calendar.get_loc(entry_decision_date)
        exit_position = factual_calendar.get_loc(exit_decision_date)
        if exit_position - entry_position != V8_TARGET_HORIZON_COMMON_SESSIONS:
            reasons["irregular_or_unproven_common_session_horizon"] += assets_count
            continue
        effective_end_position = exit_position + 1
        if effective_end_position >= len(factual_calendar):
            reasons["insufficient_tail"] += assets_count
            continue
        effective_dates = list(
            factual_calendar[entry_position + 1 : effective_end_position + 1]
        )
        if len(effective_dates) != V8_TARGET_HORIZON_COMMON_SESSIONS + 1:
            raise RuntimeError("V8 effective calendar slice ne raven shesti session dates")
        for asset_index, asset in enumerate(V8_ASSETS):
            active_rows: list[pd.Series] = []
            for effective_date in effective_dates:
                key = (effective_date, asset)
                if key not in active_lookup.index:
                    active_rows = []
                    reasons["missing_active_map"] += 1
                    break
                active_rows.append(active_lookup.loc[key])
            if not active_rows:
                continue
            contracts = [str(row["contract_id"]) for row in active_rows]
            chain_column = (
                "chain_id"
                if "chain_id" in active.columns
                else "active_chain_id" if "active_chain_id" in active.columns else None
            )
            economic_contracts = [
                (contract, "" if chain_column is None else str(row[chain_column]))
                for contract, row in zip(contracts, active_rows, strict=True)
            ]
            if not all(bool(row["carry_priced"]) for row in active_rows):
                reasons["unpriced_carry"] += 1
                continue
            if len(set(economic_contracts)) != 1:
                reasons["contract_change_or_roll"] += 1
                continue
            contract = contracts[0]
            entry_key = (pd.Timestamp(entry_expected_open).tz_localize("UTC"), asset, contract)
            exit_key = (pd.Timestamp(exit_expected_open).tz_localize("UTC"), asset, contract)
            entry_capacity_expected_open = entry_expected_open - np.timedelta64(20, "m")
            exit_capacity_expected_open = exit_expected_open - np.timedelta64(20, "m")
            entry_capacity_key = (
                pd.Timestamp(entry_capacity_expected_open).tz_localize("UTC"),
                asset,
                contract,
            )
            exit_capacity_key = (
                pd.Timestamp(exit_capacity_expected_open).tz_localize("UTC"),
                asset,
                contract,
            )
            if entry_key not in candle_lookup.index or exit_key not in candle_lookup.index:
                reasons["missing_or_incomplete_window"] += 1
                continue
            entry_row = candle_lookup.loc[entry_key]
            exit_row = candle_lookup.loc[exit_key]
            # Duplicate otsecheny pri normalizacii, poetomu lookup vsegda Series.
            entry_open[sample_index, asset_index] = entry_expected_open
            entry_close[sample_index, asset_index] = np.datetime64(
                pd.Timestamp(entry_row["end_timestamp"]).tz_convert("UTC").tz_localize(None),
                "ns",
            )
            exit_open[sample_index, asset_index] = exit_expected_open
            exit_close[sample_index, asset_index] = np.datetime64(
                pd.Timestamp(exit_row["end_timestamp"]).tz_convert("UTC").tz_localize(None),
                "ns",
            )
            entry_contract_ids[sample_index, asset_index] = contract
            exit_contract_ids[sample_index, asset_index] = contract
            if not (
                _candle_is_completed_ohlcv(entry_row, entry_expected_open)
                and _candle_is_completed_ohlcv(exit_row, exit_expected_open)
            ):
                reasons["missing_or_incomplete_window"] += 1
                continue
            if entry_capacity_key in candle_lookup.index:
                entry_capacity_row = candle_lookup.loc[entry_capacity_key]
                entry_capacity_open[sample_index, asset_index] = entry_capacity_expected_open
                entry_capacity_volume[sample_index, asset_index] = np.float32(
                    entry_capacity_row["volume"]
                )
            else:
                entry_capacity_row = None
            if exit_capacity_key in candle_lookup.index:
                exit_capacity_row = candle_lookup.loc[exit_capacity_key]
                exit_capacity_open[sample_index, asset_index] = exit_capacity_expected_open
                exit_capacity_volume[sample_index, asset_index] = np.float32(
                    exit_capacity_row["volume"]
                )
            else:
                exit_capacity_row = None
            capacity_rows = (entry_capacity_row, exit_capacity_row)
            if any(
                row is None
                or not _candle_is_completed_ohlcv(row, expected_open)
                for row, expected_open in zip(
                    capacity_rows,
                    (entry_capacity_expected_open, exit_capacity_expected_open),
                    strict=True,
                )
            ):
                reasons["missing_or_nonpositive_capacity_volume_19_00"] += 1
                continue
            known_volatility = daily_vol[sample_index, asset_index]
            if not daily_row_complete[sample_index, asset_index]:
                reasons["daily_row_not_proven_complete_at_d18_50"] += 1
                continue
            if (
                not daily_vol_valid[sample_index, asset_index]
                or not np.isfinite(known_volatility)
                or known_volatility < 0.0
            ):
                reasons["unknown_d_daily_volatility_20"] += 1
                continue
            volatility[sample_index, asset_index] = np.float32(known_volatility)
            raw_value = float(np.log(float(exit_row["close"]) / float(entry_row["close"])))
            denominator = max(float(known_volatility), V8_DAILY_VOLATILITY_FLOOR) * np.sqrt(
                V8_TARGET_HORIZON_COMMON_SESSIONS
            )
            raw[sample_index, asset_index] = np.float32(raw_value)
            normalized[sample_index, asset_index] = np.float32(raw_value / denominator)
            valid[sample_index, asset_index] = True
    raw[~valid] = 0.0
    normalized[~valid] = 0.0
    targets = V8TargetArrays(
        raw_target=raw,
        normalized_target=normalized,
        valid=valid,
        ex_ante_daily_volatility_20=volatility,
        entry_window_open_times=entry_open,
        entry_window_close_times=entry_close,
        exit_window_open_times=exit_open,
        exit_window_close_times=exit_close,
        availability_times=availability,
        entry_contract_ids=entry_contract_ids,
        exit_contract_ids=exit_contract_ids,
        entry_capacity_open_times=entry_capacity_open,
        exit_capacity_open_times=exit_capacity_open,
        entry_capacity_volumes=entry_capacity_volume,
        exit_capacity_volumes=exit_capacity_volume,
    )
    audit = {
        "target_formula": (
            "log(exit_factual_19_20_19_30_close/entry_factual_19_20_19_30_close)"
            "/(max(D_known_daily_volatility_20,0.01)*sqrt(5))"
        ),
        "horizon_common_sessions": V8_TARGET_HORIZON_COMMON_SESSIONS,
        "decision_time": f"D{V8_DECISION_TIME} {V8_TIMEZONE}",
        "entry_window": "D19:20-19:30 Moscow; next effective common session",
        "exit_window": "D19:20-19:30 Moscow; fifth common session after entry",
        "availability_rule": "scheduled_exit_window_close_19:30_Moscow",
        "capacity_rule": "same_contract_factual_19_00_volume_finite_and_positive_at_entry_and_exit",
        "daily_volatility_20_asof_rule": (
            "same_sample_D_daily_context_only_when_scheduled_D18:50_completion_exists"
        ),
        "same_contract_required_throughout_effective_sessions": True,
        "same_economic_chain_required_throughout_effective_sessions": True,
        "target_cells": int(valid.size),
        "target_valid_cells": int(valid.sum()),
        "target_invalid_cells": int((~valid).sum()),
        "invalid_reason_cells": reasons,
        "no_target_sample_drop": True,
        "factual_common_session_calendar": calendar_audit,
    }
    candle_frame_sha256 = _frame_sha256(candles)
    active_frame_sha256 = _frame_sha256(active)
    artifacts = (
        {
            "id": f"sealed_all_contract_10m_in_memory:{candle_frame_sha256}",
            "kind": "sealed_all_contract_10m_in_memory",
            "rows": len(candles),
            "sha256": candle_frame_sha256,
        },
        {
            "id": f"active_contract_map_in_memory:{active_frame_sha256}",
            "kind": "active_contract_map_in_memory",
            "rows": len(active),
            "sha256": active_frame_sha256,
        },
        calendar_artifact,
    )
    return targets, audit, artifacts


def assemble_v8_from_v7_npz(
    v7_npz_path: Path,
    all_contract_candles: pd.DataFrame,
    active_map: pd.DataFrame,
    *,
    source_start: date = date(2018, 1, 1),
    source_end: date = date(2025, 12, 31),
    source_provenance: V8VerifiedSourceProvenance | None = None,
    allow_unverified_fixture: bool = False,
    fixture_common_session_dates: object | None = None,
    fixture_unmodeled_factual_session_dates: object | None = None,
) -> V8AssemblyResult:
    """Stroit tol'ko in-memory v8 foundation bez train, PnL ili OOS raboty."""
    # Eto dolzhno predshestvovat' i otkrytiyu arhiva, i lyubomu artifact hash.
    assert_v8_pre_io_date_range(source_start, source_end)
    provenance_records: tuple[dict[str, Any], ...] = ()
    if source_provenance is None:
        if not allow_unverified_fixture:
            raise ValueError(
                "Real V8 assembly trebuet cryptographically verified source provenance"
            )
        calendar_evidence = (
            None
            if fixture_common_session_dates is None
            and fixture_unmodeled_factual_session_dates is None
            else _V8CalendarEvidence(
                verified_common_session_dates=fixture_common_session_dates,
                unmodeled_factual_session_dates=fixture_unmodeled_factual_session_dates,
                source="unverified_fixture_calendar_only",
                source_sha256=None,
                include_derived_boundaries=False,
            )
        )
        provenance_status = "unverified_fixture_explicitly_allowed"
    else:
        if allow_unverified_fixture or fixture_common_session_dates is not None or (
            fixture_unmodeled_factual_session_dates is not None
        ):
            raise ValueError("Verified real provenance nel'zya smeshivat' s fixture calendar")
        provenance_records, calendar_evidence = verify_v8_source_provenance(
            source_provenance,
            v7_npz_path=v7_npz_path,
        )
        expected_candle_rows = sum(
            int(proof.rows) for proof in source_provenance.all_contract_parquets
        )
        if len(all_contract_candles) != expected_candle_rows:
            raise ValueError("In-memory all-contract rows ne sovpali s verified source proofs")
        if source_provenance.active_contract_map.rows is None or len(active_map) != int(
            source_provenance.active_contract_map.rows
        ):
            raise ValueError("In-memory active-map rows ne sovpali s verified source proof")
        provenance_status = "cryptographically_verified_real_sources"
    inputs = load_v7_causal_inputs(
        v7_npz_path,
        source_start=source_start,
        source_end=source_end,
    )
    targets, target_audit, input_artifacts = build_v8_targets(
        inputs,
        all_contract_candles,
        active_map,
        calendar_evidence=calendar_evidence,
    )
    if source_provenance is None:
        v7_source_path = str(inputs.source_path)
    else:
        v7_source_path = inputs.source_path.relative_to(
            source_provenance.data_root.resolve()
        ).as_posix()
    v7_source_artifact = {
        "id": f"v7_causal_npz:{v7_source_path}",
        "kind": "v7_causal_npz",
        "path": v7_source_path,
        "bytes": inputs.source_path.stat().st_size,
        "sha256": inputs.source_sha256,
        "keys_read": list(inputs.keys_read),
        "legacy_supervised_keys_read": [],
        "cryptographically_verified": source_provenance is not None,
    }
    source_artifacts = (
        v7_source_artifact,
        *input_artifacts,
        *provenance_records,
    )
    audit = {
        "schema_version": V8_ASSEMBLY_SCHEMA_VERSION,
        "research_status": "assembly_only_no_train_no_pnl_no_holdout_access",
        "protected_holdout_start": V8_PROTECTED_HOLDOUT_START.isoformat(),
        "v7_causal_keys_read": list(inputs.keys_read),
        "legacy_v7_supervised_keys_read": [],
        "target_valid_is_ex_post_label_only_not_inference_eligibility": True,
        "source_provenance_status": provenance_status,
        "target": target_audit,
    }
    return V8AssemblyResult(
        inputs=inputs,
        targets=targets,
        audit=audit,
        source_artifacts=source_artifacts,
    )


def _local_midnight_utc(value: date) -> np.datetime64:
    """Vozvrashchaet Moscow local-date granicu kak UTC-naive numpy timestamp."""
    timestamp = pd.Timestamp(value).tz_localize(V8_TIMEZONE).tz_convert("UTC").tz_localize(None)
    return np.datetime64(timestamp, "ns")


def _scope_indices(indices: np.ndarray, sample_count: int) -> np.ndarray:
    """Proveryaet nepustoi strogo vozrastayushchii sample-index selection."""
    normalized = np.asarray(indices, dtype=np.int64)
    if normalized.ndim != 1 or not len(normalized):
        raise ValueError("V8 fold scope trebuet nepustye odnomernye sample indices")
    if (normalized < 0).any() or (normalized >= sample_count).any():
        raise ValueError("V8 fold scope imeet index vne samples")
    if len(np.unique(normalized)) != len(normalized) or (np.diff(normalized) <= 0).any():
        raise ValueError("V8 fold scope indices dolzhny byt' strogo vozrastayushchimi")
    return normalized


def build_v8_fold_scope(
    inputs: V8CausalInputs,
    targets: V8TargetArrays,
    *,
    train_start: date,
    train_end: date,
    purge_sessions: int = V8_PURGE_SESSIONS,
) -> V8FoldScope:
    """Stroit sealed purge10 common-session fold scope bez target leakage."""
    _validate_v8_causal_inputs(inputs)
    if purge_sessions != V8_PURGE_SESSIONS:
        raise ValueError("V8 fold scope trebuet sealed purge10")
    if train_start > train_end:
        raise ValueError("V8 fold train_start posle train_end")
    if train_end >= V8_PROTECTED_HOLDOUT_START:
        raise ValueError("V8 fold ne mozhet vkluchat' 2026")
    dates = _to_datetime64_ns(inputs.sample_trade_dates, "v7 sample_trade_dates")
    decisions = _to_datetime64_ns(inputs.decision_times, "v7 decision_times")
    availability = _to_datetime64_ns(
        targets.availability_times,
        "target availability",
        allow_nat=True,
        allow_protected=True,
    )
    if availability.shape != (inputs.sample_count, inputs.asset_count):
        raise ValueError("V8 target availability imeet nevernuyu formu")
    calendar_start = _local_midnight_utc(train_start)
    calendar_end = _local_midnight_utc(train_end + pd.Timedelta(days=1))
    candidates = np.flatnonzero((decisions >= calendar_start) & (decisions < calendar_end))
    if len(candidates) <= purge_sessions:
        raise ValueError("V8 fold ne imeet dostatochno factual sessions dlya purge10")
    # sample_trade_dates uzhe yavlyayutsya all-asset factual common-session calendar.
    first_purged_date = _date_key(dates[candidates[-purge_sessions]])
    cutoff = _local_midnight_utc(first_purged_date.date())
    if np.asarray(targets.valid, dtype=bool).shape != availability.shape:
        raise ValueError("V8 target valid ili availability imeet nevernuyu formu")
    train_candidates = np.flatnonzero(
        (decisions >= calendar_start) & (decisions < cutoff)
    )
    candidate_availability = availability[train_candidates]
    target_before_cutoff = ~np.isnat(candidate_availability) & (
        candidate_availability < cutoff
    )
    selected = train_candidates[target_before_cutoff.all(axis=1)]
    if not len(selected):
        raise ValueError("V8 fold pust posle purge10")
    scope = V8FoldScope(
        sample_indices=selected.astype(np.int64, copy=False),
        effective_cutoff=cutoff,
        purge_sessions=purge_sessions,
    )
    validate_v8_fold_scope(inputs, targets, scope)
    return scope


def build_v8_ssl_valid_mask(
    inputs: V8CausalInputs,
    scope: V8FoldScope,
    *,
    horizons: tuple[int, ...] = V8_SSL_HORIZONS,
) -> np.ndarray:
    """Stroit fold-local SSL valid s origin i horizon end strogo do cutoff."""
    _validate_v8_causal_inputs(inputs)
    indices = _scope_indices(scope.sample_indices, inputs.sample_count)
    if scope.purge_sessions != V8_PURGE_SESSIONS:
        raise ValueError("V8 SSL scope trebuet sealed purge10")
    cutoff = _to_datetime64_ns(np.asarray([scope.effective_cutoff]), "fold cutoff")[0]
    if not horizons or any(horizon < 1 for horizon in horizons):
        raise ValueError("V8 SSL horizons dolzhny byt' polozhitelnymi")
    samples = inputs.sample_count
    assets = inputs.asset_count
    bars_count = inputs.intraday.shape[2]
    mask = np.zeros((samples, assets, bars_count, len(horizons)), dtype=bool)
    bar_times = _to_datetime64_ns(inputs.bar_times, "v7 bar_times")
    finite = (
        np.isfinite(np.asarray(inputs.log_price, dtype=np.float64))
        & np.asarray(inputs.intraday_valid, dtype=bool)
        & np.asarray(inputs.asset_valid, dtype=bool)[..., None]
    )
    for horizon_index, horizon in enumerate(horizons):
        if horizon >= bars_count:
            continue
        usable = bars_count - horizon
        invalid_prefix = np.concatenate(
            (
                np.zeros((samples, assets, 1), dtype=np.int32),
                np.cumsum(~finite, axis=2, dtype=np.int32),
            ),
            axis=2,
        )
        complete = invalid_prefix[:, :, horizon + 1 :] - invalid_prefix[:, :, :usable] == 0
        time_valid = (bar_times[:, :usable] < cutoff) & (bar_times[:, horizon:] < cutoff)
        selected_mask = np.zeros(samples, dtype=bool)
        selected_mask[indices] = True
        mask[:, :, :usable, horizon_index] = (
            complete & time_valid[:, None, :] & selected_mask[:, None, None]
        )
    return mask


def validate_v8_fold_scope(
    inputs: V8CausalInputs,
    targets: V8TargetArrays,
    scope: V8FoldScope,
) -> None:
    """Padaet zakryto, esli supervised exit ili SSL interval dostigaet cutoff."""
    _validate_v8_causal_inputs(inputs)
    indices = _scope_indices(scope.sample_indices, inputs.sample_count)
    if scope.purge_sessions != V8_PURGE_SESSIONS:
        raise ValueError("V8 fold scope trebuet sealed purge10")
    cutoff = _to_datetime64_ns(np.asarray([scope.effective_cutoff]), "fold cutoff")[0]
    if targets.valid.shape != (inputs.sample_count, inputs.asset_count):
        raise ValueError("V8 target valid imeet nevernuyu formu")
    availability = _to_datetime64_ns(
        targets.availability_times,
        "target availability",
        allow_nat=True,
        allow_protected=True,
    )
    selected_availability = availability[indices]
    if np.isnat(selected_availability).any():
        raise ValueError("V8 fold scope prochit target bez exit availability")
    if (selected_availability >= cutoff).any():
        raise ValueError("V8 fold scope prochit exit na ili posle effective cutoff")
    decisions = _to_datetime64_ns(inputs.decision_times, "v7 decision_times")[indices]
    if (decisions >= cutoff).any():
        raise ValueError("V8 fold scope prochit decision iz purge/OOS")
    input_bars = _to_datetime64_ns(inputs.bar_times, "v7 bar_times")[indices]
    if (input_bars >= cutoff).any():
        raise ValueError("V8 fold scope prochit SSL input bar na ili posle cutoff")
    ssl_mask = build_v8_ssl_valid_mask(inputs, scope)
    if ssl_mask.any():
        bars = _to_datetime64_ns(inputs.bar_times, "v7 bar_times")
        for horizon_index, horizon in enumerate(V8_SSL_HORIZONS):
            if horizon >= bars.shape[1]:
                continue
            origins = bars[:, : bars.shape[1] - horizon]
            ends = bars[:, horizon:]
            valid_ssl = ssl_mask[:, :, : bars.shape[1] - horizon, horizon_index]
            origin_values = np.broadcast_to(origins[:, None, :], valid_ssl.shape)
            end_values = np.broadcast_to(ends[:, None, :], valid_ssl.shape)
            origin_leaks = (origin_values[valid_ssl] >= cutoff).any()
            end_leaks = (end_values[valid_ssl] >= cutoff).any()
            if origin_leaks or end_leaks:
                raise ValueError("V8 SSL origin ili end peresekaet effective cutoff")


def _atomic_write_npz(path: Path, result: V8AssemblyResult) -> None:
    """Atomarno pishet v8 inputy i nezavisimye metki bez pickle payloadov."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("wb") as stream:
            np.savez_compressed(
                stream,
                intraday=result.inputs.intraday,
                intraday_valid=result.inputs.intraday_valid,
                daily_context=result.inputs.daily_context,
                daily_valid=result.inputs.daily_valid,
                asset_valid=result.inputs.asset_valid,
                log_price=result.inputs.log_price,
                bar_times=result.inputs.bar_times.astype("datetime64[ns]").astype(np.int64),
                sample_trade_dates=result.inputs.sample_trade_dates.astype("datetime64[ns]").astype(
                    np.int64
                ),
                decision_times=result.inputs.decision_times.astype("datetime64[ns]").astype(
                    np.int64
                ),
                target_raw=result.targets.raw_target,
                target_normalized=result.targets.normalized_target,
                target_valid=result.targets.valid,
                target_ex_ante_daily_volatility_20=result.targets.ex_ante_daily_volatility_20,
                target_entry_window_open_times=result.targets.entry_window_open_times.astype(
                    "datetime64[ns]"
                ).astype(np.int64),
                target_entry_window_close_times=result.targets.entry_window_close_times.astype(
                    "datetime64[ns]"
                ).astype(np.int64),
                target_exit_window_open_times=result.targets.exit_window_open_times.astype(
                    "datetime64[ns]"
                ).astype(np.int64),
                target_exit_window_close_times=result.targets.exit_window_close_times.astype(
                    "datetime64[ns]"
                ).astype(np.int64),
                target_availability_times=result.targets.availability_times.astype("datetime64[ns]").astype(
                    np.int64
                ),
                target_entry_contract_ids=result.targets.entry_contract_ids,
                target_exit_contract_ids=result.targets.exit_contract_ids,
                target_entry_capacity_open_times=result.targets.entry_capacity_open_times.astype(
                    "datetime64[ns]"
                ).astype(np.int64),
                target_exit_capacity_open_times=result.targets.exit_capacity_open_times.astype(
                    "datetime64[ns]"
                ).astype(np.int64),
                target_entry_capacity_volumes=result.targets.entry_capacity_volumes,
                target_exit_capacity_volumes=result.targets.exit_capacity_volumes,
            )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def persist_v8_assembly(result: V8AssemblyResult, data_root: Path) -> V8AssemblyArtifactPaths:
    """Persistit content-addressed v8 assembly i BOM-safe provenance manifest."""
    _validate_v8_causal_inputs(result.inputs)
    output = data_root.resolve() / "processed" / "futures_v8"
    output.mkdir(parents=True, exist_ok=True)
    pending_descriptor, pending_name = tempfile.mkstemp(
        prefix=".assembly.pending.", suffix=".npz", dir=output
    )
    os.close(pending_descriptor)
    temporary_arrays = Path(pending_name)
    temporary_arrays.unlink()
    _atomic_write_npz(temporary_arrays, result)
    arrays_sha256 = _sha256_file(temporary_arrays)
    arrays_path = output / f"assembly_{arrays_sha256[:16]}.npz"
    if arrays_path.exists():
        if _sha256_file(arrays_path) != arrays_sha256:
            raise FileExistsError(f"Content-address collision: {arrays_path}")
        temporary_arrays.unlink()
    else:
        temporary_arrays.replace(arrays_path)
    source_hashes: dict[str, str] = {}
    for artifact in result.source_artifacts:
        if "sha256" not in artifact:
            continue
        artifact_id = artifact.get("id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError("Kazhdii source artifact dolzhen imet' stable unique id")
        if artifact_id in source_hashes:
            raise ValueError(f"Duplicate source artifact id: {artifact_id}")
        source_hashes[artifact_id] = str(artifact["sha256"])
    verified_files = [
        artifact
        for artifact in result.source_artifacts
        if (
            artifact.get("kind")
            in {
                "futures_v7_top_manifest",
                "official_moex_10m_parquet",
                "futures_v5_active_contract_map",
            }
            or (
                artifact.get("kind") == "v7_causal_npz"
                and artifact.get("cryptographically_verified") is True
            )
        )
    ]
    expected_verified_files = V8_EXPECTED_ALL_CONTRACT_PARQUET_FILES + 3
    if (
        result.audit.get("source_provenance_status")
        == "cryptographically_verified_real_sources"
        and len(verified_files) != expected_verified_files
    ):
        raise ValueError(
            "Verified real source proof count dolzhen byt' "
            f"{expected_verified_files}, polucheno {len(verified_files)}"
        )
    manifest: dict[str, Any] = {
        "schema_version": V8_ASSEMBLY_SCHEMA_VERSION,
        "research_status": "assembly_only_no_train_no_pnl_no_holdout_access",
        "protected_holdout_start": V8_PROTECTED_HOLDOUT_START.isoformat(),
        "arrays": {
            "path": arrays_path.relative_to(data_root.resolve()).as_posix(),
            "bytes": arrays_path.stat().st_size,
            "sha256": arrays_sha256,
            "sample_count": result.inputs.sample_count,
            "intraday_shape": list(result.inputs.intraday.shape),
            "target_shape": list(result.targets.target.shape),
        },
        "v7_source": {
            "path": str(result.inputs.source_path),
            "sha256": result.inputs.source_sha256,
            "keys_read": list(result.inputs.keys_read),
            "legacy_supervised_keys_read": [],
        },
        "source_hashes": source_hashes,
        "source_artifacts": list(result.source_artifacts),
        "source_provenance": {
            "status": result.audit.get("source_provenance_status"),
            "verified_file_count": len(verified_files),
            "verified_file_ids": [artifact["id"] for artifact in verified_files],
            "verified_all_contract_parquet_count": sum(
                artifact.get("kind") == "official_moex_10m_parquet"
                for artifact in verified_files
            ),
            "top_manifest_sha256": next(
                (
                    artifact.get("sha256")
                    for artifact in verified_files
                    if artifact.get("kind") == "futures_v7_top_manifest"
                ),
                None,
            ),
        },
        "audit": result.audit,
    }
    manifest_payload_sha256 = hashlib.sha256(
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    manifest["manifest_payload_sha256"] = manifest_payload_sha256
    manifest_path = output / f"manifest_{manifest_payload_sha256[:16]}.json"
    if manifest_path.exists():
        existing_bytes = manifest_path.read_bytes()
        if not existing_bytes.startswith(b"\xef\xbb\xbf"):
            raise FileExistsError(f"Immutable manifest ne imeet UTF-8 BOM: {manifest_path}")
        try:
            existing_manifest = json.loads(existing_bytes.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FileExistsError(f"Immutable manifest ne chitaetsya: {manifest_path}") from error
        if existing_manifest != manifest:
            raise FileExistsError(f"Content-address manifest collision: {manifest_path}")
    else:
        write_json(manifest_path, manifest)
    return V8AssemblyArtifactPaths(
        arrays_path=arrays_path,
        manifest_path=manifest_path,
        arrays_sha256=arrays_sha256,
    )


__all__ = [
    "V8_ASSEMBLY_SCHEMA_VERSION",
    "V8_CAUSAL_V7_KEYS",
    "V8_DECISION_TIME",
    "V8_EXECUTION_WINDOW_CLOSE",
    "V8_EXECUTION_WINDOW_OPEN",
    "V8_EXPECTED_ALL_CONTRACT_PARQUET_FILES",
    "V8_LEGACY_SUPERVISED_V7_KEYS",
    "V8_MIN_MAIN_SESSION_BUCKETS",
    "V8_PROTECTED_HOLDOUT_START",
    "V8_TIMEZONE",
    "V8AssemblyArtifactPaths",
    "V8AssemblyResult",
    "V8CausalInputs",
    "V8FoldScope",
    "V8SourceFileProof",
    "V8TargetArrays",
    "V8VerifiedSourceProvenance",
    "assert_v8_pre_io_date_range",
    "assemble_v8_from_v7_npz",
    "build_v8_fold_scope",
    "build_v8_ssl_valid_mask",
    "build_v8_targets",
    "load_v7_causal_inputs",
    "persist_v8_assembly",
    "verify_v8_source_provenance",
    "validate_v8_fold_scope",
]
